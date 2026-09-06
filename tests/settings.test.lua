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
  function f:SetText(text) self.text = text end
  function f:SetJustifyH() end
  function f:SetScript(_, fn) self.onShow = fn end
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

local registered
Settings = {
  RegisterAddOnCategory = function(c) registered = c end,
  RegisterCanvasLayoutCategory = function(_, name) return { name = name } end,
  OpenToCategory = function() end,
}

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

-- The slash command reaches it, since that is how anyone who read the old
-- README will look for it.
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
local opened = false
local realOpen = Addon.OpenSettings
Addon.OpenSettings = function() opened = true end
SlashCmdList["WHWVOICE"]("config")
assert(opened, "/whwv config did not open the panel")
Addon.OpenSettings = realOpen
print("  /whwv config opens it")

print("settings: ok")
