-- Run from the addon root:  lua tests/engine-copies.test.lua
--
-- Every sound pack carries a copy of the engine, and the client loads them all.
-- One must run. This loads the five files the way the client does -- with the
-- folder name as the chunk's argument -- once as one pack and again as another,
-- and checks that the second copy did nothing at all; that a stand-alone engine
-- from before the packs carried one is left to run alone; that every copy's
-- version is on record either way and a newer one is named; that of several
-- saved copies of the settings the newest is the one kept; and that a pack
-- whose expansions are not neighbours is found by its exact runs, not its span.
--
-- Twelve deliberate mutations of the engine each fail this file; the script that
-- applies them is kept beside the session notes, not here, because a test that
-- edits the code it tests is the kind of test that passes by accident.

local FILES = { "Naming.lua", "Talker.lua", "Voice.lua", "PlayButtons.lua", "Settings.lua" }

local frames, handlers, asked = 0, {}, {}

-- A client with nothing in it. Reset before every scenario, so that one
-- scenario's engine cannot stand in for another's.
local function client()
  frames, handlers, asked = 0, {}, {}
  CreateFrame = function()
    frames = frames + 1
    local f = {}
    function f:RegisterEvent() end
    function f:SetScript(_, fn) handlers[#handlers + 1] = fn end
    return f
  end
  PlaySoundFile = function(path)
    asked[#asked + 1] = path
    return true, #asked
  end
  StopSound = function() end
  GetQuestID = function() return 0 end
  WordHunterWoW_Voice = nil
  WordHunterWoW_Voice_Parts = nil
  WordHunterWoWVoiceDB = nil
  SlashCmdList = nil
  time = nil
end

local function loadAs(folder)
  for _, name in ipairs(FILES) do
    local chunk = assert(loadfile(name))
    chunk(folder)
  end
end

local function keys(t)
  local out = {}
  for k in pairs(t) do out[#out + 1] = tostring(k) end
  table.sort(out)
  return table.concat(out, " ")
end

local CATA, CLASSIC, WORDS = "WordHunterWoW-Voice-DE-Cataclysm", "WordHunterWoW-Voice-DE-Classic",
  "WordHunterWoW-Voice-DE-Words"

-- 1. Two packs. The first copy runs; the second stands down in every file.
client()
loadAs(CATA)
local Addon = WordHunterWoW_Voice
assert(Addon.host == CATA, "the first copy loaded names itself the host")
assert(type(Addon.GetEnabled) == "function" and type(Addon.CreateSettingsPanel) == "function"
  and type(Addon.WordHash) == "function", "and runs, all five files of it")
assert(frames == 1, "the engine builds one frame as it loads, got " .. frames)
local before, same = keys(Addon), {}
for k, v in pairs(Addon) do same[k] = v end
-- Hostile from here on: anything a second copy did would show.
CreateFrame = function() error("a second copy of the engine built a frame") end
loadAs(CLASSIC)
assert(WordHunterWoW_Voice == Addon, "the table is shared")
assert(Addon.host == CATA, "the second copy leaves the host alone")
assert(keys(Addon) == before, "the second copy defined nothing new:\n  " .. keys(Addon))
for k, v in pairs(same) do
  -- Identity, not names: a file that ran again would define the same names
  -- over with new closures, and a list of keys cannot see that.
  assert(Addon[k] == v, "the second copy redefined " .. k)
end
assert(Addon.copies[CLASSIC] ~= nil, "but it filed its version before standing down")
assert(Addon.copies[CATA] == Addon.EngineVersion(), "the version the host filed is the one running")
assert(#Addon.NewerCopies() == 0, "the same version everywhere is nothing to report")

-- A pack carrying a newer engine than the one running is named, and version
-- parts compare as numbers: 2.10 is newer than 2.9, 1.9.9 is not newer than 2.
Addon.copies[WORDS] = "2.10.0"
Addon.copies["WordHunterWoW-Voice-DE-Old"] = "1.9.9"
local running = Addon.EngineVersion()
Addon.copies[CATA] = "2.9.0"
local newer = Addon.NewerCopies()
assert(#newer == 1 and newer[1].folder == WORDS and newer[1].version == "2.10.0",
  "the one pack carrying a newer copy is named, and 2.10 is newer than 2.9")
Addon.copies[CATA] = running

-- 2. A stand-alone engine from before the packs carried one is already running.
client()
WordHunterWoW_Voice = { ForgetParts = function() end }
loadAs(CLASSIC)
assert(WordHunterWoW_Voice.host == nil, "an engine already running is not displaced")
assert(WordHunterWoW_Voice.GetEnabled == nil and WordHunterWoW_Voice.WordHash == nil,
  "and no second one ran")
assert(WordHunterWoW_Voice.copies[CLASSIC], "the pack's copy is still on record")
assert(frames == 0, "nothing was built")

-- 3. The version written into Naming.lua is the version the manifest declares.
local toc = assert(io.open("WordHunterWoW-Voice-DE_Mainline.toc")):read("*a")
local declared = toc:match("## Version:%s*([^\r\n]+)")
client()
loadAs("WordHunterWoW-Voice-DE")
assert(WordHunterWoW_Voice.EngineVersion() == declared, string.format(
  "Naming.lua says %s, the manifest says %s", tostring(WordHunterWoW_Voice.EngineVersion()), declared))

-- 4. Several packs each load a copy of the saved settings; the newest is kept.
client()
loadAs(CATA)
Addon = WordHunterWoW_Voice
local onEvent = handlers[1]
assert(type(onEvent) == "function", "the engine's frame has an OnEvent")
WordHunterWoWVoiceDB = { saved = 100, delay = 3 }
onEvent(nil, "ADDON_LOADED", "SomethingElse")
WordHunterWoWVoiceDB = { saved = 90, delay = 1 }          -- an older copy, arriving later
onEvent(nil, "ADDON_LOADED", CLASSIC)
assert(WordHunterWoWVoiceDB.delay == 3, "an older copy does not win by arriving last")
WordHunterWoWVoiceDB = { saved = 120, delay = 5 }         -- a newer one
onEvent(nil, "ADDON_LOADED", WORDS)
assert(WordHunterWoWVoiceDB.delay == 5, "a newer copy does")
WordHunterWoWVoiceDB = { delay = 7 }                      -- from before the stamp existed
onEvent(nil, "ADDON_LOADED", "AnotherThing")
assert(WordHunterWoWVoiceDB.delay == 5, "a copy with no stamp counts as the oldest")
assert(Addon.GetDelay() == 5, "and the engine reads the kept copy, not one it captured")
WordHunterWoWVoiceDB = true                               -- a file holding something that is not a table
onEvent(nil, "ADDON_LOADED", "YetAnother")
assert(type(WordHunterWoWVoiceDB) == "table" and WordHunterWoWVoiceDB.delay == 5,
  "a copy that is not a table is not a copy")
WordHunterWoWVoiceDB = "broken"
assert(Addon.GetDelay() ~= nil and type(WordHunterWoWVoiceDB) == "table",
  "and reading the settings replaces a value that is not a table rather than indexing it")
time = function() return 999 end
onEvent(nil, "PLAYER_LOGOUT")
assert(WordHunterWoWVoiceDB.saved == 999, "logout stamps the table every pack's file is written from")

-- 5. A pack whose expansions are not neighbours declares its exact runs beside
-- the span they lie in. Another pack's range sits inside that span, and the
-- quest goes to the pack whose run holds it.
client()
loadAs(CATA)
Addon = WordHunterWoW_Voice
Addon.ShowTalker = nil   -- the window that shows who speaks wants a real frame; not under test here
WordHunterWoW_Voice_Parts[CLASSIC] = { quests = { 1, 39694 }, ranges = { { 1, 14620 }, { 34576, 39694 } } }
WordHunterWoW_Voice_Parts[CATA] = { quests = { 14621, 34575 } }
Addon.ForgetParts()
local function packOf(questId)
  asked = {}
  Addon.PlayQuest(questId, "description")
  local path = asked[1]
  assert(path, "quest " .. questId .. " asked the client for nothing")
  return path:match("^Interface\\AddOns\\([^\\]+)\\")
end
assert(packOf(100) == CLASSIC, "a Classic quest is in the first run")
assert(packOf(20000) == CATA, "a Cataclysm quest is inside Classic's span, and goes to Cataclysm")
assert(packOf(35000) == CLASSIC, "a Draenor quest is in Classic's second run")
asked = {}
Addon.PlayQuest(50000, "description")
assert(#asked == 0, "a quest in no pack asks for nothing")
-- With nothing else installed, the gap between Classic's runs is still a gap:
-- the span is for engines that do not know the runs, not for this one.
WordHunterWoW_Voice_Parts[CATA] = nil
Addon.ForgetParts()
asked = {}
Addon.PlayQuest(20000, "description")
assert(#asked == 0, "a quest between the runs is not claimed by the span")
-- A pack that names only its runs is a quest pack all the same.
WordHunterWoW_Voice_Parts[CLASSIC] = { ranges = { { 1, 14620 } } }
Addon.ForgetParts()
assert(packOf(100) == CLASSIC, "runs alone are enough to own a quest")

print("engine-copies: ok")
