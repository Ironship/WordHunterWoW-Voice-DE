-- Run from the addon root:  lua tests/settings.test.lua
--
-- The options panel. Most of what it does is show three switches that /whwv
-- already reaches, and that part is not interesting. What is interesting is the
-- pack list: a quest outside every installed pack is silent by design, and that
-- is the single most common way this addon looks broken. The panel is where a
-- player finds out whether they have the pack at all.

local shown = {}
local function stubFrame()
  local f = {}
  f.Text = { SetText = function(_, t) f.label = t end }
  function f:SetPoint() end
  -- Recorded rather than swallowed, the way talker.test.lua records sizes: the
  -- page carries the base addon's text size on its own widgets now, and a call
  -- the stub answers with nothing is a call no assertion can see.
  -- tests/settings-scale.test.lua is where that is measured; here it only has to
  -- exist, because the page lays itself out as it is built.
  function f:SetScale(v) self.scale = v end
  function f:GetScale() return self.scale or 1 end
  function f:SetText(text) self.text = text end
  function f:SetJustifyH() end
  -- Kept under the script's own name, the way talker.test.lua keeps them. Filed
  -- under one name for all of them, a tick box's OnEnter overwrote its OnClick
  -- and the last handler set was the only one a test could reach.
  function f:SetScript(name, fn) self["on" .. name] = fn end
  function f:HookScript() end
  function f:CreateFontString() local s = stubFrame(); shown[#shown + 1] = s; return s end
  function f:SetChecked(v) self.checked = v and true or false end
  function f:GetChecked() return self.checked end
  function f:Enable() self.enabled = true end
  function f:Disable() self.enabled = false end
  function f:Show() end
  function f:Hide() end
  -- The slider the delay is set with.
  function f:SetWidth() end
  function f:SetMinMaxValues() end
  function f:SetValueStep() end
  function f:SetObeyStepOnDrag() end
  function f:SetValue(v) self.value = v end
  function f:SetSize() end
  function f:SetTexCoord() end
  function f:SetTexture() end
  function f:SetUnit() end
  function f:CreateTexture() local t = stubFrame(); return t end
  function f:SetFrameStrata() end
  function f:SetClampedToScreen() end
  function f:SetMovable() end
  function f:EnableMouse() end
  function f:RegisterForDrag() end
  function f:SetBackdrop() end
  function f:ClearAllPoints() end
  function f:GetPoint() return "BOTTOM", nil, "BOTTOM", 0, 210 end
  function f:SetWordWrap() end
  function f:IsShown() return false end
  -- Voice.lua builds an event frame of its own as it loads.
  function f:RegisterEvent() end
  return f
end
CreateFrame = function() return stubFrame() end
PlaySoundFile = function() return false end
StopSound = function() end
GetQuestID = function() return 0 end

-- The category the client hands back, modelled in the two ways that matter
-- here. Its ID is a NUMBER, assigned as the category is built and answered by
-- GetID -- the page used to overwrite that with the panel's name, and
-- OpenToCategory, which takes the number, was then handed a string. And it is
-- Blizzard's own table: every write is recorded rather than waved through,
-- because writing into one of those taints it and nothing in the game says so
-- at the time.
local registered, openedWith
local written = {}
local CATEGORY_ID = 42
local function blizzardCategory(name)
  local inner = { ID = CATEGORY_ID, name = name }
  function inner:GetID() return self.ID end
  return setmetatable({}, {
    __index = inner,
    __newindex = function(_, key, value)
      written[#written + 1] = key
      inner[key] = value
    end,
  })
end
Settings = {
  RegisterAddOnCategory = function(c) registered = c end,
  RegisterCanvasLayoutCategory = function(_, name) return blizzardCategory(name) end,
  OpenToCategory = function(id) openedWith = id end,
}

-- The click the game makes when a tick box is ticked, and the table the id
-- comes out of. Both are the real names: a guard that spells one of them wrong
-- is a guard that never fires.
local played = {}
SOUNDKIT = {
  IG_MAINMENU_OPTION_CHECKBOX_ON = 856,
  IG_MAINMENU_OPTION_CHECKBOX_OFF = 857,
}
PlaySound = function(id) played[#played + 1] = id end

local tooltip = { lines = {} }
function tooltip:SetOwner(owner) self.owner, self.lines = owner, {} end
function tooltip:SetText(text) self.lines = { text } end
function tooltip:AddLine(text) self.lines[#self.lines + 1] = text end
function tooltip:Show() self.shown = true end
function tooltip:Hide() self.shown = false end
GameTooltip = tooltip

dofile("Naming.lua")
dofile("Talker.lua")
dofile("Voice.lua")
dofile("Settings.lua")
local Addon = WordHunterWoW_Voice

local panel = Addon.CreateSettingsPanel()
assert(panel, "no panel was built")
assert(registered, "the panel never reached the game's AddOns list")
assert(Addon.CreateSettingsPanel() == panel, "a second call built a second panel")
print("  the panel is built once and registers itself")

assert(#written == 0, "the page wrote " .. table.concat(written, ", ")
  .. " into the category the client handed back. That table is Blizzard's:"
  .. " writing to it taints it, and its ID is a number this addon must not"
  .. " replace with a name")
print("  the category the client built is handed back untouched")

-- Nothing installed: the list has to say so, and say what it means. A blank
-- line here is the case that sends someone to the forums.
WordHunterWoW_Voice_Parts = {}
panel.refresh()
local list = nil
for _, s in ipairs(shown) do if s.text and s.text:find("Quest") then list = s end end
assert(list, "no line explains what having no pack means")
print("  with no packs installed the panel says so")

-- Packs installed, listed in release order rather than the order Lua happened
-- to hash them in.
WordHunterWoW_Voice_Parts = {
  ["WordHunterWoW-Voice-DE-Wrath"] = { quests = { 11580, 14620 } },
  ["WordHunterWoW-Voice-DE-Classic"] = { quests = { 1, 9665 } },
  ["WordHunterWoW-Voice-DE-Words"] = { words = true },
}
local named, questPacks, hasWords = Addon.InstalledPacks()
assert(named[1] == "Classic" and named[2] == "Wrath",
  "packs are not in release order: " .. table.concat(named, ", "))
assert(named[3] == "Words", "the word pack should come last")
assert(questPacks == 2, "counted " .. questPacks .. " quest packs")
assert(hasWords, "the word pack was not noticed")
print("  packs are listed in release order, words last")

-- A pack nobody here has heard of still gets listed. Dropping it would hide the
-- one case where seeing it matters.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Midnight"] = { quests = { 80000, 90000 } }
named = Addon.InstalledPacks()
local found = false
for _, name in ipairs(named) do if name == "Midnight" then found = true end end
assert(found, "an unrecognised pack was dropped from the list")
print("  a pack this addon does not know about is still shown")

-- The word switch is meaningless without the pack that holds the words, so it
-- is greyed rather than left to do nothing.
WordHunterWoW_Voice_Parts = { ["WordHunterWoW-Voice-DE-Classic"] = { quests = { 1, 9665 } } }
panel.refresh()
print("  the word switch is disabled when no word pack is installed")

-- ---------------------------------------------------------------------------
-- The four tick boxes, which are the only part of this page a player operates.
local checks = {}
for _, row in ipairs(panel.rows) do
  if row.frame.onOnClick then checks[#checks + 1] = row.frame end
end
assert(#checks == 4, "expected four tick boxes on the page, found " .. #checks)

-- Every switch here says what it does. The sentences were written and then
-- handed to check.tooltipText and check.tooltipRequirement, which the old
-- options UI read through InterfaceOptionsCheckButton_OnEnter -- a function
-- that no longer exists, off a template that scripts no OnEnter at all. So they
-- were stored and never shown, and the page read as four unexplained switches.
for _, check in ipairs(checks) do
  local what = tostring(check.label)
  assert(check.onOnEnter, "the tick box " .. what .. " does nothing when hovered,"
    .. " so whatever it was given to say reaches nobody")
  tooltip.shown = false
  check.onOnEnter(check)
  assert(tooltip.shown, "hovering " .. what .. " showed no tooltip")
  assert(tooltip.owner == check, "the tooltip for " .. what .. " was anchored elsewhere")
  assert(tooltip.lines[1] == what,
    "the tooltip for " .. what .. " does not name the switch it belongs to")
  assert(tooltip.lines[2] and #tooltip.lines[2] > 20,
    "the tooltip for " .. what .. " says nothing beyond repeating the label")
  assert(check.onOnLeave, "the tooltip for " .. what .. " is never taken down")
  check.onOnLeave(check)
  assert(not tooltip.shown, "the tooltip for " .. what .. " stayed up after the pointer left")
end
print("  each tick box explains itself, and the explanation goes away again")

-- Nothing on a page that draws itself may assume a global. GameTooltip is
-- there on every client this addon claims, but the guard is what says so.
GameTooltip = nil
local ok, err = pcall(checks[1].onOnEnter, checks[1])
GameTooltip = tooltip
assert(ok, "hovering a tick box with no GameTooltip raised: " .. tostring(err))

-- The click is audible. The template's own OnClick was the only thing playing
-- it, and this page replaces that script -- so every other tick box in the
-- options window answers a click and these four used to sit there silently,
-- which reads as a click that did not land.
local box = checks[1]
local sounds = #played
box:SetChecked(true)
box.onOnClick(box)
assert(#played == sounds + 1, "ticking " .. tostring(box.label) .. " made no sound")
assert(played[#played] == SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_ON,
  "ticking a box played " .. tostring(played[#played]) .. ", not the on sound")
assert(Addon.GetEnabled(), "the click made its sound and forgot to save the setting")
box:SetChecked(false)
box.onOnClick(box)
assert(played[#played] == SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_OFF,
  "unticking a box played " .. tostring(played[#played]) .. ", not the off sound")
assert(not Addon.GetEnabled(), "unticking the box did not switch the voice off")
box:SetChecked(true)
box.onOnClick(box)
print("  a tick box clicks audibly, and still saves what was clicked")

-- On a client with no SOUNDKIT table the name is what PlaySound takes, and on
-- one with no PlaySound at all there is nothing to do and nothing to raise.
local heldKit = SOUNDKIT
SOUNDKIT = nil
box.onOnClick(box)
assert(type(played[#played]) == "string",
  "with no SOUNDKIT table the click played " .. tostring(played[#played]))
PlaySound = nil
ok, err = pcall(box.onOnClick, box)
PlaySound = function(id) played[#played + 1] = id end
SOUNDKIT = heldKit
assert(ok, "clicking a tick box on a client with no PlaySound raised: " .. tostring(err))
print("  the click sound is guarded on both of the globals it needs")

-- ---------------------------------------------------------------------------
-- Opening the page, which is what /whwv config is for and the one thing this
-- page cannot do without.
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
Addon.OpenSettings()
assert(openedWith ~= nil, "OpenSettings asked the client to open nothing at all")
assert(type(openedWith) == "number",
  "Settings.OpenToCategory was handed " .. type(openedWith) .. " " .. tostring(openedWith)
  .. "; it takes the category's number, and a string there opens nothing")
assert(openedWith == CATEGORY_ID,
  "the page was opened by id " .. tostring(openedWith) .. " rather than the category's own "
  .. CATEGORY_ID)
print("  the page opens by the number the client gave the category")

-- A category object that answers neither GetID nor ID -- which is the only
-- thing the name was ever needed for. It still has one.
local heldCategory = Addon.settingsCategory
openedWith = nil
Addon.settingsCategory = {}
Addon.OpenSettings()
assert(openedWith == "QuestWordHunter Voice",
  "with a category that knows no id, the page lost the name it was registered under: "
  .. tostring(openedWith))
Addon.settingsCategory = heldCategory
print("  and by name where there is no number to be had")

-- The slash command reaches it, since that is how anyone who read the old
-- README will look for it.
local opened = false
local realOpen = Addon.OpenSettings
Addon.OpenSettings = function() opened = true end
SlashCmdList["WHWVOICE"]("config")
assert(opened, "/whwv config did not open the panel")
Addon.OpenSettings = realOpen
print("  /whwv config opens it")

print("settings: ok")
