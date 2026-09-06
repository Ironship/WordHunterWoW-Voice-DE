-- Run from the addon root:  lua tests/highlight.test.lua
--
-- While a passage is read aloud the English side is supposed to light the
-- sentence being spoken. The base addon offers two names for that and they are
-- not interchangeable: HighlightEnglishForWord paints its own English column
-- and then tells whoever else is listening, while OnHighlightEnglishForWord is
-- that telling. Calling the second reached the separate English window and left
-- the column inside the quest panel dark -- and that column is the arrangement
-- the addon ships with, so for most players nothing lit up at all.
--
-- Nothing about the wrong call looks wrong: both names exist, both are
-- functions, both take a sentence number, and neither returns anything to
-- check. So which one is called is measured here.

strlower = string.lower
strtrim = function(s) return (tostring(s or ""):gsub("^%s+", ""):gsub("%s+$", "")) end
time = os.time
GetLocale = function() return "deDE" end
CreateFrame = function()
  return setmetatable({}, { __index = function() return function() end end })
end
PlaySoundFile = function() return true, 1 end
StopSound = function() end

-- Assigned before either file is loaded, so nothing can be answered by a
-- namespace that was invented on the way past.
WordHunterWoW_Addon = {}
WordHunterWoW_Voice = {}
WordHunterWoW_Voice_Parts = {}

-- The real sentence splitter, because which sentence a clip starts at is what
-- is being handed over.
dofile("../WordHunterWoW/Core.lua")
dofile("Naming.lua")
dofile("Voice.lua")
local Base = WordHunterWoW_Addon
local Addon = WordHunterWoW_Voice

local painted, told = {}, {}

-- Stands in for the base addon's own pair, keeping the one part of their
-- relationship this depends on: painting the column ends by telling everyone
-- else, exactly once.
Base.HighlightEnglishForWord = function(word, sentenceIndex, occurrence, sentenceOnly)
  painted[#painted + 1] = { word = word, sentence = sentenceIndex, occurrence = occurrence, only = sentenceOnly }
  if Base.OnHighlightEnglishForWord then
    Base.OnHighlightEnglishForWord(word, Base.lastQuest, sentenceIndex, occurrence, sentenceOnly)
  end
end
Base.OnHighlightEnglishForWord = function(word, quest, sentenceIndex)
  told[#told + 1] = { word = word, quest = quest, sentence = sentenceIndex }
end

-- Three paragraphs of one sentence each, every one long enough to be spoken as
-- a clip of its own. Below thirty characters the generator joins a sentence to
-- its neighbour, and then a clip number is no longer a sentence number.
local german = "Der erste Satz steht hier ganz allein."
  .. "\n\nDer zweite Satz steht dort drüben."
  .. "\n\nDer dritte Satz ist schon vergangen."
Base.lastQuest = { id = 42, text = german, passage = "offer" }

WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Classic"] = { quests = { 1, 100 } }
Addon.ForgetParts()

local spans = Addon.ClipSpans(german)
assert(#spans == 3 and spans[2].first == 2,
  "these three sentences did not become three clips, so this would be measuring the grouping instead")

assert(Addon.PlayQuest(42, "description", 2), "the clip refused to play, so nothing was handed over")
assert(#painted == 1,
  "the voiceover did not ask the base addon to paint its English column: it called the painting function "
    .. #painted .. " times")
local call = painted[1]
assert(call.sentence == 2, "the wrong sentence was handed over: " .. tostring(call.sentence))
assert(call.word == nil, "nobody clicked a word, so none may be sent")
assert(call.only == true, "without sentenceOnly the panel tries to pick a word out of the sentence")
assert(#told == 1,
  "the separate English window heard about the sentence " .. #told .. " times, and it must be exactly one")
assert(told[1].quest == Base.lastQuest, "the notification carried the wrong quest")
print("  reading a sentence aloud paints the base addon's column and tells the window once")

-- Clip three, to show the number is carried through rather than being the
-- first sentence every time.
painted, told = {}, {}
assert(Addon.PlayQuest(42, "description", 3), "the third clip refused to play")
assert(#painted == 1 and painted[1].sentence == 3,
  "the third clip handed over sentence " .. tostring(painted[1] and painted[1].sentence))

-- A clip number the passage does not have must hand over nothing at all rather
-- than a sentence picked at random.
painted, told = {}, {}
Addon.PlayQuest(42, "description", 9)
assert(#painted == 0 and #told == 0,
  "a clip beyond the end of the passage still lit something: sentence " .. tostring(painted[1] and painted[1].sentence))

-- The base addon is optional, and the voiceover has to be silent about the
-- English rather than break when it is not there.
painted, told = {}, {}
WordHunterWoW_Addon = nil
assert(Addon.PlayQuest(42, "description", 1), "the clip must still play with no base addon installed")
assert(#painted == 0 and #told == 0, "something was handed to a base addon that is not installed")
WordHunterWoW_Addon = Base

-- An older base addon that has the notification but not the painting function
-- does not exist -- both names arrived in the same release -- but a missing one
-- must be a quiet no-op either way, never an error mid-sentence.
painted, told = {}, {}
Base.HighlightEnglishForWord = nil
assert(Addon.PlayQuest(42, "description", 1), "the clip must still play against a base addon without the function")
assert(#told == 0, "the voiceover fell back to the notification, which leaves the quest panel's own column dark")

print("highlight: all assertions passed")
