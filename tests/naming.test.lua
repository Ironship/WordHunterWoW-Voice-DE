-- Run from the addon root:  lua tests/naming.test.lua
--
-- The addon finds a clip by computing its name, and the generator writes the
-- clip under the name it computes. Nothing checks at runtime that the two
-- agree: a mismatch is not an error, it is silence on every word in the pack.
-- So they are checked here, against vectors Tools/naming.py froze.

dofile("Naming.lua")
local Addon = WordHunterWoW_Voice

local vectors = dofile("tests/naming.vectors.lua")
assert(#vectors > 0, "no vectors to check against")
for _, case in ipairs(vectors) do
  local got = Addon.WordHash(case.key)
  assert(got == case.hash, string.format(
    "hash drifted for %q: python says %s, lua says %s", case.key, case.hash, got))
end
print(string.format("  %d word hashes match Tools/naming.py", #vectors))

-- Sixteen hex digits, always. A short one would mean the format string was
-- handed something that is not a whole number, which is how a 32-bit multiply
-- done with unsafe arithmetic first shows itself.
for _, case in ipairs(vectors) do
  local hash = Addon.WordHash(case.key)
  assert(#hash == 16, "hash is not 16 hex digits: " .. hash)
  assert(hash:match("^%x+$"), "hash is not hexadecimal: " .. hash)
end
print("  every hash is sixteen hex digits")

-- Different words must not share a clip. Cheap to assert, and it is the whole
-- reason the hash is 64 bits rather than 32.
local seen = {}
for _, case in ipairs(vectors) do
  local hash = Addon.WordHash(case.key)
  assert(not seen[hash], "two keys share a clip: " .. tostring(seen[hash]) .. " and " .. case.key)
  seen[hash] = case.key
end
print("  no two keys share a clip")

assert(Addon.WordPath("Zuflucht"):find("^sounds\\w\\"), "word path lost its prefix")
assert(Addon.WordPath("Zuflucht"):sub(-4) == ".ogg", "word path lost its extension")
-- The shard is the first two digits of the hash, so a clip is always found in
-- the folder its own name points at.
local hash = Addon.WordHash("Zuflucht")
assert(Addon.WordPath("Zuflucht") == "sounds\\w\\" .. hash:sub(1, 2) .. "\\" .. hash .. ".ogg",
  "word path and hash disagree")

assert(Addon.QuestPath(25152, "description") == "sounds\\q\\52\\25152_o.ogg",
  "quest path changed: " .. tostring(Addon.QuestPath(25152, "description")))
assert(Addon.QuestPath(8325, "completion") == "sounds\\q\\25\\8325_c.ogg",
  "quest path changed: " .. tostring(Addon.QuestPath(8325, "completion")))
assert(Addon.QuestPath(7, "progress") == "sounds\\q\\07\\7_p.ogg", "shard is not padded")
-- Objectives and the title have no clip. Asking for one must give nothing back
-- rather than a path that will never resolve.
assert(Addon.QuestPath(25152, "objectives") == nil, "objectives are not spoken")
assert(Addon.QuestPath(25152, "title") == nil, "the title is not spoken")
assert(Addon.QuestPath(nil, "description") == nil, "a missing quest id must not make a path")
print("  quest paths are sharded, padded, and only for spoken passages")

print("naming: ok")
