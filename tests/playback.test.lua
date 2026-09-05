-- Run from the addon root:  lua tests/playback.test.lua
--
-- The engine holds no list of what exists. It works out a clip's name, works out
-- which sound pack owns it, and asks the client. Every step of that is silent
-- when it goes wrong -- a wrong path is not an error, it is a quest that says
-- nothing -- so each step is checked here.

local asked, stopped, handle = {}, {}, 0
PlaySoundFile = function(path, channel)
  asked[#asked + 1] = { path = path, channel = channel }
  -- The client answers false for a file that is not there. Only the paths this
  -- test says exist are allowed to play.
  if not _G.EXISTS[path] then return false end
  handle = handle + 1
  return true, handle
end
StopSound = function(h) stopped[#stopped + 1] = h end
GetQuestID = function() return _G.QUEST_ID or 0 end
local events = {}
CreateFrame = function()
  local f = {}
  function f:RegisterEvent(name) events[name] = true end
  function f:SetScript(_, fn) _G.ON_EVENT = fn end
  return f
end

dofile("Naming.lua")
dofile("Voice.lua")
local Addon = WordHunterWoW_Voice

-- Two packs, each owning some shards. Quest 25152 is in shard 52, which pack one
-- holds; quest 8325 is in shard 25, which nobody installed.
-- The word shard is derived, not written down: it is the first two digits of
-- the key's own hash, and a hand-typed one would be testing the test.
local wordShard = Addon.WordHash("zuflucht"):sub(1, 2)
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Data01"] = { q = { "52" } }
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Data02"] = { w = { wordShard } }
Addon.ForgetParts()

local questClip =
  "Interface\\AddOns\\WordHunterWoW-Voice-DE-Data01\\sounds\\q\\52\\25152_o.ogg"
local wordClip =
  "Interface\\AddOns\\WordHunterWoW-Voice-DE-Data02\\" .. Addon.WordPath("zuflucht")
_G.EXISTS = { [questClip] = true, [wordClip] = true }

assert(Addon.PlayQuest(25152, "description"), "a quest in an installed pack did not play")
assert(asked[#asked].path == questClip, "wrong path: " .. asked[#asked].path)
assert(asked[#asked].channel == "Dialog", "quest audio should use the Dialog channel")
print("  a quest passage resolves to the pack that holds it")

-- The shard the clip names and the folder it is looked for in must agree. This
-- is the join that a change to either half would break.
assert(questClip:find("\\q\\52\\", 1, true), "the path lost its shard")

local before = #asked
assert(not Addon.PlayQuest(8325, "completion"),
  "a quest in a pack nobody installed must not claim to play")
assert(#asked == before, "the client was asked for a clip from a missing pack")
print("  a missing sound pack is silence, not a wrong file and not an error")

-- Objectives and titles have no clip at all; asking must not reach the client.
before = #asked
assert(not Addon.PlayQuest(25152, "objectives"), "objectives are not spoken")
assert(#asked == before, "the client was asked for a passage nobody says")

-- Starting a new clip stops the one running. Two quest givers talking over each
-- other is the worst thing this addon could do.
local playedHandle = handle
Addon.PlayQuest(25152, "description")
assert(stopped[#stopped] == playedHandle, "the previous clip was not stopped")
print("  a new passage stops the one already playing")

-- Closing the window stops it too.
_G.ON_EVENT(nil, "QUEST_FINISHED")
local quiet = #stopped
_G.ON_EVENT(nil, "QUEST_FINISHED")
assert(#stopped == quiet, "stopping twice stopped a handle that was already gone")
print("  closing the quest window stops the voice, once")

-- The event path, not just the functions under it.
_G.QUEST_ID = 25152
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
assert(#asked > before and asked[#asked].path == questClip, "QUEST_DETAIL did not read the quest")
_G.QUEST_ID = 0
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
assert(#asked == before, "a quest window with no quest id still asked for a clip")
print("  the quest events are wired, and a missing quest id is ignored")

-- Words. The key is casefolded and the eszett becomes ss, exactly as the
-- dictionary files them, or a word goes looking in the wrong place.
assert(Addon.PlayWord("Zuflucht"), "a word in an installed pack did not play")
assert(asked[#asked].path == wordClip, "wrong word path: " .. asked[#asked].path)
assert(Addon.WordKey("STRAßE") == "strasse", "the eszett rule is not applied: "
  .. Addon.WordKey("STRAßE"))
assert(not Addon.PlayWord(""), "an empty word must not be looked up")
print("  a word resolves through the same key the dictionary files it under")

-- Switched off means silent, both settings independently.
Addon.SetEnabled(false)
before = #asked
assert(not Addon.PlayQuest(25152, "description"), "switched off but still playing")
assert(#asked == before, "switched off but still asking the client")
Addon.SetEnabled(true)
Addon.SetWordsEnabled(false)
assert(not Addon.PlayWord("Zuflucht"), "words switched off but still playing")
assert(Addon.PlayQuest(25152, "description"), "switching words off silenced the quests too")
Addon.SetWordsEnabled(true)
print("  quest reading and word reading switch off separately")

-- The word hook wraps the base addon rather than requiring it to offer a hook,
-- and must pass the call through untouched.
local opened = {}
WordHunterWoW_Addon = { openEditor = function(...) opened[#opened + 1] = { ... } end }
Addon.HookBaseAddon()
Addon.HookBaseAddon()
WordHunterWoW_Addon.openEditor("Zuflucht", "context", 1, "title")
assert(#opened == 1 and opened[1][1] == "Zuflucht" and opened[1][3] == 1,
  "the editor call was not passed through intact")
assert(asked[#asked].path == wordClip, "clicking a word did not say it")
print("  clicking a word says it, and the editor still opens")

print("playback: ok")
