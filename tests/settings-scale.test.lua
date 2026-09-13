-- Run from the addon root:  lua tests/settings-scale.test.lua
--
-- This addon's options page followed no size setting at all. The talker window
-- has borrowed the base addon's quest panel text size since it was built -- it
-- is captioning the words that setting governs -- but the page that switches
-- the talker on came up at whatever Blizzard's options canvas happened to be,
-- so the two were never the same size on screen.
--
-- It cannot be answered by scaling the page. The frame is parented into that
-- canvas, so it already carries the canvas's effective scale and SetScale would
-- multiply with it rather than replace it. So the page sizes its contents: font
-- roles for this file's own strings, and a scale on each of Blizzard's
-- composites one at a time -- which is safe exactly where scaling the page is
-- not, because their parent is this panel and this panel is never scaled.
--
-- Run against the base addon's own stub rather than a hand-rolled one, the way
-- playbuttons.test.lua runs its join half: the sizes come out of the base
-- addon's real Core.lua, so this file cannot agree with a role table that only
-- exists in the test.

local BASE = "../WordHunterWoW"
local probe = io.open(BASE .. "/Core.lua", "rb")
assert(probe, "no QuestWordHunter checkout at " .. BASE
  .. " -- this page borrows that addon's text size, so its absence is a failure, not a skip")
probe:close()

dofile(BASE .. "/tests/wowstub.lua")

-- That stub invents a frame for any global whose name extends a named frame's,
-- because the client makes one for every template child and the panel code looks
-- them up again by name. This addon's globals begin with the same letters, and a
-- frame answers every field with another frame -- so a nil check on one of them
-- would come back true and the page would build against furniture that is not
-- there. Same guard playbuttons.test.lua puts up, for the same reason.
local invented = getmetatable(_G).__index
setmetatable(_G, {
  __index = function(globals, key)
    if type(key) == "string" and key:find("^WordHunterWoW_?Voice") then return nil end
    return invented(globals, key)
  end,
})

PlaySoundFile = function() return false end
StopSound = function() end
UIParent = CreateFrame("Frame")

dofile(BASE .. "/Core.lua")
-- Set before the addon that reads them loads, not after: a frame standing in for
-- the saved variables would have made every option quietly true.
WordHunterWoWDB = { settings = { targetLocale = "deDE", frames = {} }, words = {}, wordsByLocale = {} }
WordHunterWoWVoiceDB = { enabled = true }
WordHunterWoW_Voice_Parts = {}

dofile("Naming.lua")
dofile("Talker.lua")
dofile("Voice.lua")
dofile("Settings.lua")
local Base = WordHunterWoW_Addon
local Addon = WordHunterWoW_Voice
Base.initializeDatabase()

local function eq(what, got, want)
  assert(got == want, ("%s: expected %s, got %s"):format(what, tostring(want), tostring(got)))
end

-- Every message is built before its assertion is judged, so a %d holding a
-- fraction raises in Lua 5.4 whatever the page did. Rounded for the reading.
local function at(y) return string.format("%.0f", tonumber(y) or 0) end
local function pct(scale) return string.format("%.0f%%", (tonumber(scale) or 0) * 100) end

local page = Addon.CreateSettingsPanel()
assert(page.rows and #page.rows > 0, "the page kept no record of what it draws")

-- A control with neither a role nor a scale of its own is a control no size
-- setting reaches, which is this bug in one line.
local strings, composites = 0, 0
for _, row in ipairs(page.rows) do
  assert(row.role or row.own,
    "a control on the page has neither a font role nor a scale, so no setting reaches it")
  if row.role then strings = strings + 1 else composites = composites + 1 end
end
assert(strings >= 4 and composites >= 5,
  ("only %d strings and %d widgets are answered"):format(strings, composites))

local function readPage()
  local seen = {}
  for index, row in ipairs(page.rows) do
    local _, y = row.frame:GetAnchor("TOPLEFT")
    local r, g, b = row.frame:GetTextColor()
    seen[index] = {
      y = y,
      scale = row.frame:GetScale(),
      width = rawget(row.frame, "w"),
      size = row.frame.GetFontSize and row.frame:GetFontSize() or nil,
      color = { r, g, b },
    }
  end
  return seen
end

Base.SetTextScale(1.0)
page.refresh()
local base = readPage()
for index, row in ipairs(page.rows) do
  assert(type(base[index].y) == "number", "a control on the page was never anchored")
  if row.role then
    assert(type(base[index].size) == "number",
      ("the %s string at %s has no size of its own"):format(row.role, at(base[index].y)))
    eq(("the %s string at %s starts at its role"):format(row.role, at(base[index].y)),
      base[index].size, Base.RoleSize(row.role))
  end
end

-- ---------------------------------------------------------------------------
-- Over the whole range the base addon's slider can be put to, not one
-- convenient multiple.
for _, scale in ipairs({ 0.8, 1.5, 2.0 }) do
  Base.SetTextScale(scale)
  -- Through refresh, which is what Blizzard's own route into this page calls:
  -- the size lives in the other addon and changes with this page shut.
  page.refresh()
  local now = readPage()

  for index, row in ipairs(page.rows) do
    local was, is = base[index], now[index]
    if row.role then
      -- Both ways round: against the base addon's role, so the two addons draw
      -- one set of sizes, and against its own size at 100%, so a role that had
      -- quietly stopped taking the multiplier cannot agree with itself.
      eq(("the %s string at %s follows the role at %s"):format(row.role, at(was.y), pct(scale)),
        is.size, Base.RoleSize(row.role, scale))
      eq(("the %s string at %s grew by the setting"):format(row.role, at(was.y)),
        is.size, was.size * scale)
      -- The trap all of this size work has hit before: a Blizzard font object
      -- carries a colour as well as a size, so a size fixed by swapping objects
      -- recolours the page with every size assertion still green.
      assert(is.color[1] == was.color[1] and is.color[2] == was.color[2]
        and is.color[3] == was.color[3],
        ("the %s string at %s changed colour when it was re-sized"):format(row.role, at(was.y)))
    else
      eq(("the widget at %s carries the setting"):format(at(was.y)), is.scale, scale)
    end
    -- One form for both, because on screen there is only one answer: a gap
    -- given to a scaled frame is read in that frame's units and multiplied by
    -- it, and a gap given to an unscaled string has to be multiplied here. Get
    -- that backwards and the page is right at 100% and pulled apart everywhere
    -- else, which is exactly the kind of fault a 100%-only test cannot see.
    eq(("the gap above the control at %s"):format(at(was.y)),
      is.y * is.scale, was.y * scale)
  end

  -- The slider keeps the width it had: the canvas cannot widen, so the page
  -- grows downwards only. It is the one widget here with a width of its own.
  local slider = _G.WordHunterWoWVoiceDelaySlider
  eq(("the delay slider's width on screen at %s"):format(pct(scale)),
    slider:GetWidth() * slider:GetScale(), 220)

  eq("the page is never SetScale'd", page:GetScale(), 1)
end

-- ---------------------------------------------------------------------------
-- And with the base addon absent, which is the ordinary case: it is an
-- OptionalDep and most players of the voice pack will not have it. There is
-- then nothing to ask, so the page stays at the size it was drawn and nothing
-- raises -- the same shape the theming here already takes.
Base.SetTextScale(2.0)
page.refresh()
local held = WordHunterWoW_Addon
WordHunterWoW_Addon = nil
local ok, err = pcall(page.refresh)
WordHunterWoW_Addon = held
assert(ok, "the page raised with the base addon absent: " .. tostring(err))
for index, row in ipairs(page.rows) do
  if row.own then
    eq(("the widget at %s with no base addon"):format(at(base[index].y)),
      row.frame:GetScale(), 1)
  end
end

print(string.format("settings-scale: %d strings by role, %d widgets by scale, over 0.8-2.0, "
  .. "and 1 with no base addon", strings, composites))
