-- Run from the addon root:
--   lua Tools/check_install.lua "<path to Interface/AddOns>" [Data/zone_x.json ...]
--
-- Does the installation actually work? Asked the only way that answers it: by
-- loading the addon's own code, registering the packs the game would register,
-- and looking on disk for the file the addon would ask the client for.
--
-- Every earlier check of this built the path from the same rule as the pack
-- builder, so the two agreed with each other while both were wrong, and every
-- report said the clips were in place while nothing could play. Nothing here
-- knows how a pack is laid out; it only knows what Naming.lua returns.

local ADDONS = ...
if not ADDONS then
  print("podaj sciezke do Interface/AddOns")
  os.exit(1)
end
-- arg[1] the AddOns folder, arg[2] a file listing the pack folders one per
-- line, then the zone lists. The pack names come from a file rather than being
-- discovered here: this runs under Windows Lua, where io.popen starts cmd and
-- an "ls" quietly returns nothing.
local zones = {}
for i = 3, #arg do zones[#zones + 1] = arg[i] end

-- Enough of the client for the addon to load and be asked questions.
PlaySoundFile = function() return false end
StopSound = function() end
GetQuestID = function() return 0 end
CreateFrame = function()
  return setmetatable({}, { __index = function() return function() end end })
end

dofile("Naming.lua")
dofile("Voice.lua")
local Addon = WordHunterWoW_Voice

-- Register every pack the way the game would: by running its Part.lua.
--
-- The names come from the caller. An earlier version listed the folders itself
-- with io.popen("ls ..."), which on Windows runs cmd and quietly found nothing
-- -- so the check registered no packs, tested no clips, and reported success.
-- A check that passes because it checked nothing is worse than no check, which
-- is why the count is now a hard failure.
local packs = 0
local names = {}
do
  local file = arg[2] and io.open(arg[2], "rb")
  if file then
    for line in file:read("a"):gmatch("[^\r\n]+") do names[#names + 1] = line end
    file:close()
  end
end
for _, name in ipairs(names) do
  local part = ADDONS .. "/" .. name .. "/Part.lua"
  local exists = io.open(part, "rb")
  if exists then
    exists:close()
    dofile(part)
    packs = packs + 1
  else
    print("  paczka bez Part.lua: " .. name)
  end
end
print(string.format("zarejestrowanych paczek: %d", packs))
if packs == 0 then
  print("check_install: NIC NIE SPRAWDZONO -- zadna paczka sie nie zarejestrowala")
  os.exit(1)
end

-- The addon builds "Interface\AddOns\<folder>\<relative>". On disk that is the
-- AddOns folder, the pack folder, and the relative path with the slashes the
-- filesystem uses.
local function onDisk(path)
  local rest = path:match("^Interface\\AddOns\\(.+)$")
  if not rest then return nil end
  return ADDONS .. "/" .. rest:gsub("\\", "/")
end

-- Ask the addon for a path, exactly as PlayQuest does, without playing it.
local function pathFor(questId, field, sentence)
  local relative = Addon.QuestPath(questId, field, sentence)
  if not relative then return nil end
  for folder, part in pairs(WordHunterWoW_Voice_Parts) do
    local range = part.quests
    if range and questId >= range[1] and questId <= range[2] then
      return "Interface\\AddOns\\" .. folder .. "\\" .. relative, folder
    end
  end
  return nil
end

local FIELD = { o = "description", p = "progress", c = "completion" }

local function check(name, quests)
  local want, found, noPack, missing = 0, 0, 0, {}
  for _, quest in ipairs(quests) do
    -- Every passage the pack says it has a duration for is one the addon will
    -- try to play, so that is the list to check.
    local owner
    for folder, part in pairs(WordHunterWoW_Voice_Parts) do
      local range = part.quests
      if range and quest >= range[1] and quest <= range[2] then owner = folder end
    end
    if not owner then
      noPack = noPack + 1
    else
      for letter, field in pairs(FIELD) do
        local lengths = Addon.LengthsFor(owner, quest, field)
        if lengths then
          for index = 1, #lengths do
            want = want + 1
            local asked = pathFor(quest, field, index)
            local file = asked and onDisk(asked)
            local ok = file and io.open(file, "rb")
            if ok then
              ok:close()
              found = found + 1
            elseif #missing < 3 then
              missing[#missing + 1] = asked or "(brak sciezki)"
            end
          end
        end
      end
    end
  end
  print(string.format("  %-16s %5d/%5d klipow znalezionych%s", name, found, want,
    noPack > 0 and ("   bez paczki: " .. noPack .. " questow") or ""))
  for _, m in ipairs(missing) do print("      brak: " .. m) end
  return want - found, want
end

local function readIds(path)
  local file = io.open(path, "rb")
  if not file then return nil end
  local text = file:read("a")
  file:close()
  local ids = {}
  for n in text:gmatch("%d+") do ids[#ids + 1] = tonumber(n) end
  return ids
end

local bad, checked = 0, 0
for _, path in ipairs(zones) do
  local ids = readIds(path)
  if ids then
    local short, seen = check(path:match("([^/\\]+)%.json$"), ids)
    bad = bad + short
    checked = checked + seen
  else
    print("  nie ma pliku: " .. path)
  end
end

-- Nothing checked is not a pass either: a zone list that matched no quest with
-- a duration would otherwise sail through with 0/0.
if checked == 0 then
  print("check_install: NIC NIE SPRAWDZONO -- zadna strefa nie miala klipow do sprawdzenia")
  os.exit(1)
elseif bad == 0 then
  print(string.format("check_install: ok -- %d klipow, kazdy tam gdzie addon o niego poprosi",
    checked))
else
  print("check_install: BRAKUJE " .. bad .. " z " .. checked .. " klipow")
  os.exit(1)
end
