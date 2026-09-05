local Addon = WordHunterWoW_Voice or {}
WordHunterWoW_Voice = Addon

-- The engine. It holds no audio: the clips live in the data addons, which are
-- separate downloads because the whole pack does not fit in one.
--
-- Nothing here builds an index of what exists. A clip is found by computing its
-- name (Naming.lua) and asking the client to play it; a clip that has not been
-- generated yet simply does not play. That is what lets the pack ship
-- incomplete and grow, instead of having to be finished before it is useful.

local ENGINE = "WordHunterWoW-Voice-DE"

-- Filled in by each data addon as it loads. A player who installed parts 1 and
-- 3 gets the quests those parts cover and silence for the rest, rather than an
-- error or a refusal to load.
WordHunterWoW_Voice_Parts = WordHunterWoW_Voice_Parts or {}

local playing

local function settings()
  WordHunterWoWVoiceDB = WordHunterWoWVoiceDB or {}
  local db = WordHunterWoWVoiceDB
  if db.enabled == nil then db.enabled = true end
  if db.words == nil then db.words = true end
  if db.channel == nil then db.channel = "Dialog" end
  return db
end

function Addon.GetEnabled() return settings().enabled and true or false end
function Addon.SetEnabled(value)
  settings().enabled = value and true or false
  if not settings().enabled then Addon.Stop() end
end

function Addon.GetWordsEnabled() return settings().words and true or false end
function Addon.SetWordsEnabled(value) settings().words = value and true or false end

-- Which sound pack holds a given clip.
--
-- One pack per expansion, because that is a unit a player recognises: someone
-- levelling through Classic installs Classic and carries nothing else, and
-- everything outside it is silent rather than broken. A quest pack declares the
-- range of quest ids it covers, so finding the owner is a comparison against at
-- most a dozen packs. The word pack declares only that it holds words -- a
-- word's clip is named by a hash and has no range to compare.
--
-- Nothing is cached, so a pack that loads after the engine is seen the moment
-- it declares itself; the list is short enough that caching would buy nothing.
function Addon.ForgetParts() end

local function questOwner(questId)
  questId = tonumber(questId)
  if not questId then return nil end
  for folder, part in pairs(WordHunterWoW_Voice_Parts) do
    local range = part.quests
    if range and questId >= range[1] and questId <= range[2] then
      return folder
    end
  end
end

local function wordOwner()
  for folder, part in pairs(WordHunterWoW_Voice_Parts) do
    if part.words then return folder end
  end
end

local function fullPath(relative, folder)
  if not folder or not relative then return nil end
  return "Interface\\AddOns\\" .. folder .. "\\" .. relative
end

function Addon.Stop()
  if playing then
    StopSound(playing)
    playing = nil
  end
end

local function play(path)
  if not path then return false end
  Addon.Stop()
  -- PlaySoundFile answers false when the file is not there, which is the normal
  -- case for a clip nobody has generated yet. Not an error, and not worth a
  -- message: the player asked for a voice, not for a report on coverage.
  local willPlay, handle = PlaySoundFile(path, settings().channel)
  if willPlay then playing = handle end
  return willPlay and true or false
end

-- The three passages an NPC says out loud, and the event that shows each.
local PASSAGE_EVENT = {
  QUEST_DETAIL = "description",
  QUEST_PROGRESS = "progress",
  QUEST_COMPLETE = "completion",
}

-- Stand-in clips, played when the real one has not been generated yet. The pack
-- takes weeks to speak in full, and waiting for it to answer the only questions
-- that matter -- does a voice reading over a quest window help or annoy, is it
-- too loud, does it stop when it should -- would be weeks wasted.
--
-- Off unless asked for. A player wants the quest they opened, not a sample of
-- somebody else's; this is for judging the behaviour before the content exists.
function Addon.GetDemo() return settings().demo and true or false end
function Addon.SetDemo(value)
  settings().demo = value and true or false
  if not settings().demo then Addon.Stop() end
end

-- Which stand-in to use. UnitSex answers 2 for male and 3 for female, and it
-- answers for NPCs, which is the one piece of the casting the client knows by
-- itself -- so the stand-in is at least the right sex even though the words are
-- somebody else's.
local function placeholder()
  local sex = UnitSex and UnitSex("npc")
  local name = sex == 3 and "female" or "male"
  return "Interface\\AddOns\\" .. ENGINE .. "\\sounds\\demo\\" .. name .. ".ogg"
end

function Addon.PlayQuest(questId, field, sentence)
  if not Addon.GetEnabled() then return false end
  local relative = Addon.QuestPath(questId, field, sentence or 1)
  if not relative then return false end
  if play(fullPath(relative, questOwner(tonumber(questId)))) then return true end
  if Addon.GetDemo() then return play(placeholder()) end
  return false
end

function Addon.PlayWord(word)
  if not Addon.GetEnabled() or not Addon.GetWordsEnabled() then return false end
  local key = Addon.WordKey(word)
  if key == "" then return false end
  return play(fullPath(Addon.WordPath(key), wordOwner()))
end

-- The key a clip was filed under. The dictionary casefolds and turns the eszett
-- into ss; the generator hashed that same key, so the same rule has to run here
-- or every word with an eszett in it goes looking in the wrong place.
function Addon.WordKey(word)
  word = tostring(word or "")
  local base = WordHunterWoW_Addon
  if base and base.wordKey then return base.wordKey(word) end
  -- Standing alone, without the base addon: good enough for ASCII, and the
  -- words that need more than this are exactly the ones the base addon is
  -- installed to look up anyway.
  return (word:gsub("ẞ", "ss"):gsub("ß", "ss"):lower())
end

local frame = CreateFrame("Frame")
for event in pairs(PASSAGE_EVENT) do frame:RegisterEvent(event) end
frame:RegisterEvent("QUEST_FINISHED")
frame:RegisterEvent("GOSSIP_CLOSED")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    -- A data addon may load after this one. Its declaration is only visible
    -- once it has, so the map is dropped and rebuilt on the next lookup.
    Addon.ForgetParts()
    if arg1 == ENGINE then Addon.HookBaseAddon() end
    return
  end
  local field = PASSAGE_EVENT[event]
  if field then
    local questId = GetQuestID and GetQuestID() or 0
    -- Sentence one; the rest follow it once the durations are shipped.
    if questId and questId > 0 then Addon.PlayQuest(questId, field, 1) end
  else
    -- Closing the window stops the voice. Reading on while the frame is gone is
    -- the single most irritating thing a pack like this can do.
    Addon.Stop()
  end
end)

-- There is no settings panel yet, and there does not need to be one before the
-- pack has anything to say. A slash command is enough to answer the questions
-- this build exists to answer.
local function say(text)
  if DEFAULT_CHAT_FRAME then
    DEFAULT_CHAT_FRAME:AddMessage("|cff59aefaQuestWordHunter Voice:|r " .. text)
  end
end

local function status()
  return string.format("quests %s, words %s, stand-ins %s",
    Addon.GetEnabled() and "on" or "off",
    Addon.GetWordsEnabled() and "on" or "off",
    Addon.GetDemo() and "on" or "off")
end

SLASH_WHWVOICE1 = "/whwvoice"
SLASH_WHWVOICE2 = "/whwv"
SlashCmdList = SlashCmdList or {}
SlashCmdList["WHWVOICE"] = function(input)
  local command = (input or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
  if command == "on" or command == "off" then
    Addon.SetEnabled(command == "on")
  elseif command == "words" then
    Addon.SetWordsEnabled(not Addon.GetWordsEnabled())
  elseif command == "demo" then
    Addon.SetDemo(not Addon.GetDemo())
    if Addon.GetDemo() then
      say("stand-ins on: every quest will say something, but only the ones "
        .. "already generated say their own words.")
    end
  elseif command == "stop" then
    Addon.Stop()
  else
    say(status())
    say("/whwv on | off | words | demo | stop")
    return
  end
  say(status())
end

-- Clicking a word in QuestWordHunter should say it. Done by wrapping the base
-- addon's own editor rather than asking it for a hook, so this addon can be
-- installed beside any version of it without the two having to agree on
-- anything.
function Addon.HookBaseAddon()
  local base = WordHunterWoW_Addon
  if not base or not base.openEditor or Addon.hooked then return end
  Addon.hooked = true
  local openEditor = base.openEditor
  base.openEditor = function(word, ...)
    Addon.PlayWord(word)
    return openEditor(word, ...)
  end
end
