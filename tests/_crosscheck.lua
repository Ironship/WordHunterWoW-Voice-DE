-- Does the addon split a passage into the same sentences the generator did?
--
-- One clip per sentence means the addon has to agree with Tools/speech.py about
-- where the sentences are. If it does not, the highlight lands on the wrong
-- line and there is nothing to notice it: no error, just a mismatch nobody sees
-- until they are watching the text while it is read.
--
-- Fed by Tools that write the passages and the counts Python arrived at.

strlower = string.lower
strtrim = function(s) return (tostring(s or ""):gsub("^%s+", ""):gsub("%s+$", "")) end
time = os.time
GetLocale = function() return "deDE" end
CreateFrame = function()
  return setmetatable({}, { __index = function() return function() end end })
end

dofile("../WordHunterWoW/Core.lua")
local Addon = WordHunterWoW_Addon

local blob = io.open("tests/_texts.txt", "rb"):read("a")
local counts = {}
for line in io.open("tests/_counts.txt"):lines() do counts[#counts + 1] = tonumber(line) end

local index, disagreed, total = 0, 0, 0
-- Record separator, chosen because no quest text contains it.
for passage in (blob .. "\30"):gmatch("(.-)\30") do
  index = index + 1
  local want = counts[index]
  if want then
    local got = #Addon.SplitSentences(passage)
    total = total + 1
    if got ~= want then
      disagreed = disagreed + 1
      if disagreed <= 5 then
        print(string.format("  lua=%d python=%d | %s", got, want, passage:sub(1, 90)))
      end
    end
  end
end

print(string.format("compared %d passages; %d disagreed", total, disagreed))
if disagreed > 0 then os.exit(1) end
print("sentence splitting: the addon and the generator agree")
