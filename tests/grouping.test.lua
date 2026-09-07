-- Run from the addon root:  lua tests/grouping.test.lua
--
-- Does the addon land on the sentences the generator actually recorded?
--
-- The pack ships one clip per group, not one per sentence: sentences under
-- thirty characters are joined to a neighbour, because the reader stumbles on a
-- two-word clip. The addon used to work that grouping out for itself, and could
-- not: the generator groups the text it speaks, where "Das sind schwierige
-- Zeiten, {name}." has lost its vocative and is 27 characters, and the addon
-- groups the text the client draws, where the same sentence carries a player's
-- name and is 36. So the pack ships the grouping and the addon reads it.
--
-- Which is what is measured here. The passages below are the client's text,
-- with the tokens filled in; the grouping is fed in as a pack declaration, in
-- the format build_pack.py writes; the answer is the generator's own.
--
-- A disagreement is silent. Both sides produce a well-formed answer, nothing
-- raises, and the only symptom is the English panel lighting the wrong line
-- while the German is read aloud -- and a play button missing from the last
-- paragraph, which is how this was finally noticed.

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

local function slurp(path)
  local handle = io.open(path, "rb")
  if not handle then
    print("brak " .. path .. " -- uruchom najpierw Tools/crosscheck_grouping.py")
    os.exit(1)
  end
  local text = handle:read("a")
  handle:close()
  return text
end

local texts = slurp("tests/_grouping_texts.txt")
local wanted = slurp("tests/_grouping_spans.txt")
local starts = slurp("tests/_grouping_starts.txt")
local fieldBlob = slurp("tests/_grouping_fields.txt")
local lengths = slurp("tests/_grouping_lengths.txt")

local function split(blob, sep)
  local out = {}
  for piece in (blob .. sep):gmatch("(.-)" .. sep) do out[#out + 1] = piece end
  return out
end

local passages = split(texts, "\30")
local expected = split(wanted, "\30")
local fields = split(fieldBlob, "\30")
assert(#passages == #fields, "brakuje pol dla fragmentow")
assert(#passages == #expected,
  string.format("%d fragmentow ale %d zestawow granic", #passages, #expected))

-- A pack holding nothing but the grouping. The checker filed each passage under
-- its own position in the sample, so passage n is quest n, and every one of them
-- carries the field it really came from, so a row looked up under the wrong
-- letter shows up as a failure rather than as a table quietly not read.
WordHunterWoW_Voice_Parts["Test"] =
  { quests = { 1, #passages }, lengths = lengths, starts = starts }
Addon.ForgetParts()

local function numbers(list)
  local out = {}
  for value in list:gmatch("(%d+)") do out[#out + 1] = tonumber(value) end
  return out
end

-- The sentences of the passage, so a disagreement can be printed as words
-- rather than as two lists of numbers nobody can read.
local function sentencesOf(passage)
  local out = {}
  for _, paragraph in ipairs(Base.SplitParagraphs(passage)) do
    for _, sentence in ipairs(Base.SplitSentences(paragraph)) do
      out[#out + 1] = sentence
    end
  end
  return out
end

local checked, wrong, countWrong = 0, 0, 0
for index, passage in ipairs(passages) do
  local want = numbers(expected[index])
  local spans = Addon.ClipSpans(passage, index, fields[index])
  assert(spans, "ClipSpans nie dziala bez bazowego addona")
  if #spans ~= #want then
    countWrong = countWrong + 1
    if countWrong <= 3 then
      print(string.format("  liczba klipow lua=%d generator=%d | %s",
        #spans, #want, passage:sub(1, 80)))
    end
  else
    local sentences = sentencesOf(passage)
    for i, span in ipairs(spans) do
      checked = checked + 1
      if span.first ~= want[i] then
        wrong = wrong + 1
        if wrong <= 3 then
          print(string.format("  klip %d zaczyna sie na zdaniu %d, nie %d:\n    lua      : %s\n    generator: %s",
            i, span.first, want[i],
            (sentences[span.first] or ""):sub(1, 70),
            (sentences[want[i]] or ""):sub(1, 70)))
        end
      end
    end
  end
end

print(string.format("  %d fragmentow, %d klipow porownanych", #passages, checked))
assert(countWrong == 0, countWrong .. " fragmentow podzielono na inna liczbe klipow")
assert(wrong == 0, wrong .. " klipow zaczyna sie na innym zdaniu niz w generatorze")

-- The fallback, which is what the six pack repositories already committed in the
-- old format get. It cannot be held to the answer above -- deriving the grouping
-- from the client's text is the bug, and the reason the grouping is shipped at
-- all -- so what is checked is that it still answers, and still answers what it
-- always did on the generator's own text. A pack without the grouping degrades;
-- it does not break.
local without = 0
for index, passage in ipairs(passages) do
  local spans = Addon.ClipSpans(passage)
  assert(spans and #spans > 0, "brak zapasowego podzialu dla fragmentu " .. index)
  local shipped = Addon.ClipSpans(passage, index, fields[index])
  if #spans ~= #shipped then without = without + 1 end
end
print(string.format("  zapasowy podzial: %d z %d fragmentow rozni sie od pakietu",
  without, #passages))

print("grouping: ok")
