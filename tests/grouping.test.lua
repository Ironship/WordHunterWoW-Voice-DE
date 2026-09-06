-- Run from the addon root:  lua tests/grouping.test.lua
--
-- Does the addon group sentences into clips the same way the generator did?
--
-- The pack ships one clip per group, not one per sentence: sentences under
-- thirty characters are joined to a neighbour, because the reader stumbles on a
-- two-word clip. The addon works the grouping out for itself so the pack does
-- not have to carry it -- which is only safe while both sides agree.
--
-- A disagreement is silent. Both sides produce a well-formed answer, nothing
-- raises, and the only symptom is the English panel lighting the wrong line
-- while the German is read aloud. So it is measured here, against what
-- Tools/crosscheck_grouping.py wrote down.

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

local texts, clips = slurp("tests/_grouping_texts.txt"), slurp("tests/_grouping_clips.txt")

local function split(blob, sep)
  local out = {}
  for piece in (blob .. sep):gmatch("(.-)" .. sep) do out[#out + 1] = piece end
  return out
end

local passages = split(texts, "\30")
local expected = split(clips, "\30")
assert(#passages == #expected,
  string.format("%d fragmentow ale %d zestawow klipow", #passages, #expected))

-- Rebuild each clip's text from the sentence numbers the addon says it covers.
-- Comparing the text rather than the count is the strict form: two groupings can
-- agree on how many clips there are and still draw the boundaries elsewhere.
--
-- Compared with the edges trimmed. What the addon uses is the sentence numbers,
-- and the text here is only a way of proving those numbers point at the same
-- words; the Lua splitter leaves a leading space on a sentence where the Python
-- strips it, which changes no boundary and highlights nothing differently.
local function trim(text)
  local previous
  repeat
    previous = text
    text = text:gsub("^%s+", ""):gsub("%s+$", "")
    text = text:gsub("^\194\160", ""):gsub("\194\160$", "")
  until text == previous
  return text
end

local function rebuild(passage, span)
  local sentences = {}
  for _, paragraph in ipairs(Base.SplitParagraphs(passage)) do
    for _, sentence in ipairs(Base.SplitSentences(paragraph)) do
      sentences[#sentences + 1] = sentence
    end
  end
  local parts = {}
  for i = span.first, span.last do parts[#parts + 1] = sentences[i] end
  return table.concat(parts, " ")
end

local checked, wrong, countWrong = 0, 0, 0
for index, passage in ipairs(passages) do
  local want = split(expected[index], "\31")
  if expected[index] == "" then want = {} end
  local spans = Addon.ClipSpans(passage)
  assert(spans, "ClipSpans nie dziala bez bazowego addona")
  if #spans ~= #want then
    countWrong = countWrong + 1
    if countWrong <= 3 then
      print(string.format("  liczba klipow lua=%d python=%d | %s",
        #spans, #want, passage:sub(1, 80)))
    end
  else
    for i, span in ipairs(spans) do
      checked = checked + 1
      local got = trim(rebuild(passage, span))
      if got ~= trim(want[i] or "") then
        wrong = wrong + 1
        if wrong <= 3 then
          print(string.format("  klip %d rozny:\n    lua   : %s\n    python: %s",
            i, got:sub(1, 90), (want[i] or ""):sub(1, 90)))
        end
      end
    end
  end
end

print(string.format("  %d fragmentow, %d klipow porownanych", #passages, checked))
assert(countWrong == 0, countWrong .. " fragmentow podzielono na inna liczbe klipow")
assert(wrong == 0, wrong .. " klipow ma inne granice niz w generatorze")
print("grouping: ok")
