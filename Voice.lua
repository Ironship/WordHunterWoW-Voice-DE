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

-- Which data addon holds a given shard. Built once, from what the parts
-- declared, so a lookup never walks the list.
local ownerOf
local function owners()
  if ownerOf then return ownerOf end
  ownerOf = {}
  for folder, shards in pairs(WordHunterWoW_Voice_Parts) do
    for kind, list in pairs(shards) do
      for _, shard in ipairs(list) do
        ownerOf[kind .. shard] = folder
      end
    end
  end
  return ownerOf
end

-- Rebuilt when a part loads after the engine, which is the normal order: the
-- data addons declare themselves and then this map is stale until cleared.
function Addon.ForgetParts() ownerOf = nil end

local function fullPath(relative, kind)
  local shard = relative:match("^sounds\\" .. kind .. "\\([^\\]+)\\")
  if not shard then return nil end
  local folder = owners()[kind .. shard]
  if not folder then return nil end
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

function Addon.PlayQuest(questId, field, sentence)
  if not Addon.GetEnabled() then return false end
  local relative = Addon.QuestPath(questId, field, sentence or 1)
  if not relative then return false end
  return play(fullPath(relative, "q"))
end

function Addon.PlayWord(word)
  if not Addon.GetEnabled() or not Addon.GetWordsEnabled() then return false end
  local key = Addon.WordKey(word)
  if key == "" then return false end
  return play(fullPath(Addon.WordPath(key), "w"))
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
