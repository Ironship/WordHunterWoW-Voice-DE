-- Run from the addon root:  lua tests/sentence-gap.test.lua
--
-- The pause between two sentences of a passage, which is now the player's to
-- set.
--
-- It was asked for as a reading speed and it is not one. PlaySoundFile takes a
-- path and a channel and hands back a handle: no rate, no pitch, no seek. The
-- client cannot make the reader talk slower, and this is the only pacing the
-- addon actually controls -- so what a longer gap buys is time to finish
-- reading the line, not a slower voice.
--
-- Checked where it is spent rather than where it is stored: the getter can
-- return three and the passage still run at a quarter second if readFrom keeps
-- comparing against the local it used to. Every assertion below is made once in
-- a state where it should hold and once in a state where it should not.

local asked, handle = {}, 0
PlaySoundFile = function(path)
  asked[#asked + 1] = { path = path }
  if not _G.EXISTS[path] then return false end
  handle = handle + 1
  return true, handle
end
StopSound = function() end
GetQuestID = function() return 0 end
CreateFrame = function()
  local f = {}
  function f:RegisterEvent() end
  function f:SetScript() end
  return f
end

local booked = {}
C_Timer = { After = function(delay, action)
  booked[#booked + 1] = { delay = delay, action = action }
end }

dofile("Naming.lua")
dofile("Voice.lua")
local Addon = WordHunterWoW_Voice

WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"] = { quests = { 14621, 29377 } }
Addon.ForgetParts()
local pack = WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"]
-- Three sentences: 1.2s, 2.5s, 0.8s.
pack.lengths = "25152 o 120,250,80\n"

local base = "Interface\\AddOns\\WordHunterWoW-Voice-DE-Cataclysm\\sounds\\q\\52\\25152_o"
_G.EXISTS = { [base .. "1.ogg"] = true, [base .. "2.ogg"] = true, [base .. "3.ogg"] = true }

-- What the engine books for the second sentence, which is the first sentence's
-- length plus whatever the gap is.
local function bookedGap()
  booked = {}
  assert(Addon.PlayQuest(25152, "description"), "the passage did not start")
  assert(#booked == 1, "sentence two was not booked")
  return booked[1].delay - 1.2
end

-- --- the default is where it was -------------------------------------------
assert(Addon.GetSentenceGap() == 0.25, "the default gap moved")
assert(math.abs(bookedGap() - 0.25) < 0.001,
  "the default is not what gets spent: " .. bookedGap())

-- --- and the setting is what gets spent -------------------------------------
Addon.SetSentenceGap(2)
assert(Addon.GetSentenceGap() == 2, "the setter did not take")
assert(math.abs(bookedGap() - 2) < 0.001,
  "sentence two is still due at the old gap: " .. bookedGap())

Addon.SetSentenceGap(0)
assert(math.abs(bookedGap() - 0) < 0.001,
  "no gap at all has to mean no gap: " .. bookedGap())

-- --- what a hand-edited saved variable can put there ------------------------
-- WordHunterWoWVoiceDB is a file the player can open, and the value is added to
-- a time, so a string reaching C_Timer.After is an error inside a timer nobody
-- is watching.
WordHunterWoWVoiceDB.sentenceGap = "zwei"
assert(Addon.GetSentenceGap() == 0.25, "nonsense has to fall back to the default")
WordHunterWoWVoiceDB.sentenceGap = -5
assert(Addon.GetSentenceGap() == Addon.SENTENCE_GAP_MIN, "below the floor clamps up")
WordHunterWoWVoiceDB.sentenceGap = 999
assert(Addon.GetSentenceGap() == Addon.SENTENCE_GAP_MAX, "above the ceiling clamps down")
assert(math.abs(bookedGap() - Addon.SENTENCE_GAP_MAX) < 0.001,
  "the clamped value is not what gets spent either")

-- The setter clamps on the way in too, so the file never holds a value the
-- getter has to repair on every read.
Addon.SetSentenceGap(999)
assert(WordHunterWoWVoiceDB.sentenceGap == Addon.SENTENCE_GAP_MAX,
  "the setter stored a value outside its own range")
Addon.SetSentenceGap(0.25)

-- --- the last sentence books no gap -----------------------------------------
-- Only the frame coming down is booked after the last one, and it waits the
-- clip's own length. A gap added there would leave the talker claiming to be
-- reading for three seconds after it had stopped.
Addon.SetSentenceGap(3)
booked = {}
Addon.PlayQuest(25152, "description", 3)
assert(#booked == 1, "the last sentence booked " .. #booked .. " timers")
assert(math.abs(booked[1].delay - 0.8) < 0.001,
  "the gap was added after the last sentence: " .. booked[1].delay)
Addon.SetSentenceGap(0.25)

print("sentence-gap: ok")
