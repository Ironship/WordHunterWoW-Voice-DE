-- Run from the addon root:  lua tests/spans.test.lua
--
-- Quest 8473, "Eine traurige Aufgabe", which is the passage this whole
-- mechanism exists for. It is here on its own, with its text and its pack
-- written out, because tests/grouping.test.lua needs a corpus and a Python run
-- before it says anything, and the one case somebody photographed should fail
-- loudly on a bare checkout.
--
-- The passage begins "Das sind schwierige Zeiten, {name}." The generator speaks
-- it without the vocative -- 27 characters, under the thirty-character minimum
-- -- so it reads sentences one and two as a single clip and the passage is four
-- clips. The client draws it with a player's name in it, 36 characters, and the
-- addon working the grouping out for itself found five. Button one was right,
-- every button after it was one sentence early, and the last paragraph had no
-- button at all, because PlayButtons stops where the shipped durations stop.

strlower = string.lower
strtrim = function(s) return (tostring(s or ""):gsub("^%s+", ""):gsub("%s+$", "")) end
time = os.time
GetLocale = function() return "deDE" end
CreateFrame = function()
  return setmetatable({}, { __index = function() return function() end end })
end
PlaySoundFile = function() return false end
StopSound = function() end

dofile("../WordHunterWoW/Core.lua")
dofile("Naming.lua")
dofile("Voice.lua")
local Base = WordHunterWoW_Addon
local Addon = WordHunterWoW_Voice

-- What the client puts on screen: the raw text with the tokens filled in, which
-- is what GetQuestText hands the base addon. A name of ordinary length -- the
-- point is not this name, it is that there is one.
local TEXT = table.concat({
  "Das sind schwierige Zeiten, Kwandar. Es war eine schwere Entscheidung, die "
    .. "Wälder am Rande der Geisterlande niederzubrennen, um die weitere "
    .. "Expansion der Geißel zu stoppen.",
  "Die Treants, seit Jahrzehnten unsere Verbündeten, versuchen den "
    .. "niedergebrannten Wald am Versengten Hain wieder aufzuforsten.",
  "Es tut mir in der Seele weh, Euch um diesen Gefallen zu bitten, Krieger, "
    .. "doch wir konnten unsere Verbündeten nicht davon abhalten, den Wald zu "
    .. "erneuern. Ihr müsst sie und ihr Vorhaben mit dem einzig noch "
    .. "verbleibenden Mittel beenden: Gewalt.",
}, "\n\n")

-- The pack, exactly as Tools/build_pack.py writes it: four durations, and the
-- sentence each of the four clips starts at.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Classic"] = {
  quests = { 1, 9665 },
  lengths = "8473 o 480,390,510,300",
  starts = "8473 o 1,3,4,5",
}
Addon.ForgetParts()

local sentences = {}
for _, paragraph in ipairs(Base.SplitParagraphs(TEXT)) do
  for _, sentence in ipairs(Base.SplitSentences(paragraph)) do
    sentences[#sentences + 1] = sentence
  end
end
assert(#sentences == 5, "klient widzi " .. #sentences .. " zdan, nie 5")

local folder = Addon.QuestOwner(8473)
assert(folder, "zaden pakiet nie obejmuje questa 8473")
local lengths = Addon.LengthsFor(folder, 8473, "description")
assert(#lengths == 4, "pakiet ma " .. #lengths .. " klipow, nie 4")

local spans = Addon.ClipSpans(TEXT, 8473, "description")
assert(#spans == 4, "podzial na " .. #spans .. " klipow, a pakiet ma 4")
for index, first in ipairs({ 1, 3, 4, 5 }) do
  assert(spans[index].first == first,
    string.format("klip %d zaczyna sie na zdaniu %d, nie %d",
      index, spans[index].first, first))
end
-- The first clip covers two sentences, which is the join the whole passage
-- turns on; nothing else does.
assert(spans[1].last == 2, "pierwszy klip konczy sie na zdaniu " .. spans[1].last)
print("  cztery przyciski, na zdaniach 1, 3, 4 i 5")

-- Every button plays its own clip, in order, and the fourth is the last one the
-- pack holds -- which is the loop PlayButtons runs.
local drawn = 0
for index, span in ipairs(spans) do
  if not lengths[index] then break end
  drawn = drawn + 1
  assert(Addon.QuestPath(8473, "description", index)
    == string.format("sounds\\q\\73\\8473_o%d.ogg", index),
    "klip " .. index .. " ma zla sciezke")
  assert(sentences[span.first], "zdanie " .. span.first .. " nie istnieje")
end
assert(drawn == 4, "narysowano " .. drawn .. " przyciskow, nie 4")
print("  kazdy odtwarza swoj wlasny klip")

-- The old packs. Six of them are published without the grouping, and they must
-- keep working rather than stop: the derived answer is what the engine always
-- gave, and for this passage it is the wrong one -- five clips against the four
-- the pack holds. Asserted rather than tolerated in silence, because the day
-- somebody deletes the fallback this says what is lost.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Classic"].starts = nil
Addon.ForgetParts()
local old = Addon.ClipSpans(TEXT, 8473, "description")
assert(old and #old == 5,
  "stary pakiet powinien wyliczyc 5 klipow, wyliczyl " .. tostring(old and #old))
print("  pakiet bez podzialu nadal dziala, tyle ze zle -- 5 klipow zamiast 4")

print("spans: ok")
