-- Run from the addon root:  lua tests/talker.test.lua
--
-- The frame that shows who is talking. Sound with nothing on screen is
-- confusing: a voice starts and there is no way to tell which quest it belongs
-- to, whether it is this addon at all, or how to stop it.
--
-- What is worth testing here is not the artwork. It is that the frame appears
-- only while something is being read, that it disappears when the reading does,
-- that the line counting sentences never claims "Satz 4 von 3", that exactly one
-- transport button is ever on screen, and that the frame wears QuestWordHunter's
-- skin when that addon is there and does not fall over when it is not.

local frames = {}
local function stub(kind)
  local f = { kind = kind, shown = false, points = {}, scale = 1, w = 0, h = 0 }
  -- Sizes and scales are recorded rather than swallowed. They used to be
  -- dropped on the floor, which meant an assertion about either of them would
  -- have passed without checking anything -- the failure this suite is most
  -- prone to.
  function f:SetSize(w, h) self.w, self.h = w, h end
  function f:GetSize() return self.w, self.h end
  function f:GetWidth() return self.w end
  function f:GetHeight() return self.h end
  function f:SetScale(v) self.scale = v end
  function f:GetScale() return self.scale end
  function f:SetPoint(...) self.points[#self.points + 1] = { ... } end
  function f:SetAllPoints() end
  function f:ClearAllPoints() self.points = {} end
  function f:GetPoint() return "BOTTOM", nil, "BOTTOM", 0, 210 end
  function f:SetFrameStrata() end
  function f:SetClampedToScreen() end
  function f:SetMovable() end
  function f:EnableMouse() end
  function f:RegisterForDrag() end
  function f:SetScript(name, fn) self["on" .. name] = fn end
  function f:SetBackdrop(backdrop) self.backdrop = backdrop end
  function f:SetHighlightTexture() end
  function f:SetText(text) self.text = text end
  function f:SetTextColor(...) self.color = { ... } end
  function f:SetJustifyH() end
  function f:SetWordWrap() end
  function f:SetTexCoord() end
  function f:SetTexture(path) self.texture = path end
  function f:SetVertexColor(...) self.color = { ... } end
  function f:SetUnit(unit) self.unit = unit end
  function f:Show() self.shown = true end
  function f:Hide() self.shown = false end
  function f:IsShown() return self.shown end
  function f:CreateFontString() local s = stub("fontstring"); frames[#frames + 1] = s; return s end
  function f:CreateTexture() local t = stub("texture"); frames[#frames + 1] = t; return t end
  function f:StartMoving() end
  function f:StopMovingOrSizing() end
  function f:RegisterEvent() end
  frames[#frames + 1] = f
  return f
end
CreateFrame = function(kind) return stub(kind) end
UIParent = stub("frame")

-- Real playback, so the buttons can be pressed rather than merely counted. The
-- client answers false for a clip that is not there, and only the paths named
-- below exist.
local asked, handle = {}, 0
_G.EXISTS = {}
PlaySoundFile = function(path)
  asked[#asked + 1] = path
  if not _G.EXISTS[path] then return false end
  handle = handle + 1
  return true, handle
end
StopSound = function() end
UnitExists = function(unit) return _G.NPC_THERE and unit == "npc" end
SetPortraitTexture = function(texture, unit) texture.portraitOf = unit end

-- A passage is read on timers. They are booked and fired here rather than
-- waited for.
local booked = {}
C_Timer = { After = function(delay, action) booked[#booked + 1] = { delay = delay, action = action } end }
local function fire()
  local due = table.remove(booked, 1)
  if due then due.action() end
  return due
end

-- The tooltip is how a button says what it is, so it is also how this test
-- tells the two apart. Going by creation order or by position would pass a
-- layout that had put the wrong words on the wrong icon, which is exactly the
-- mistake worth catching on a frame with no labels on it.
GameTooltip = {
  SetOwner = function() end,
  SetText = function(self, text) self.text = text end,
  Show = function() end,
  Hide = function() end,
}

dofile("Naming.lua")
dofile("Talker.lua")
dofile("Voice.lua")
local Addon = WordHunterWoW_Voice

local function transportButtons()
  local found = {}
  for _, f in ipairs(frames) do
    if f.kind == "Button" and f.onOnEnter then
      GameTooltip.text = nil
      f.onOnEnter(f)
      if GameTooltip.text then found[GameTooltip.text] = f end
    end
  end
  return found
end

-- The sentence counter. A passage of one clip says nothing -- "Satz 1 von 1" is
-- noise -- and an index past the end is clamped rather than printed.
assert(Addon.TalkerLine(1, 1) == "", "a single-sentence passage should say nothing")
assert(Addon.TalkerLine(1, nil) == "", "an unknown total should say nothing")
assert(Addon.TalkerLine(2, 4) == "Satz 2 von 4", "got: " .. Addon.TalkerLine(2, 4))
assert(Addon.TalkerLine(9, 3) == "Satz 3 von 3", "an index past the end was not clamped")
print("  the sentence counter never claims more than there are")

-- Shown with a name, hidden on demand.
local talker = Addon.BuildTalker()
assert(not talker:IsShown(), "the frame should start hidden")
Addon.ShowTalker("Die Stellung halten", "npc", "Satz 1 von 3")
assert(talker:IsShown(), "the frame did not appear while reading")
Addon.HideTalker()
assert(not talker:IsShown(), "the frame did not go away")
print("  it appears while reading and goes when told")

-- Stopping the voice takes the frame with it. This is what closing the quest
-- window does, so the two must not come apart.
Addon.ShowTalker("Die Stellung halten", "npc", "")
Addon.Stop()
assert(not talker:IsShown(), "stopping the voice left the frame on screen")
print("  stopping the voice hides it")

-- Switched off, it stays away however often it is asked for.
Addon.SetTalkerEnabled(false)
Addon.ShowTalker("Die Stellung halten", "npc", "")
assert(not talker:IsShown(), "switched off but still shown")
Addon.SetTalkerEnabled(true)
Addon.ShowTalker("Die Stellung halten", "npc", "")
assert(talker:IsShown(), "switched back on but not shown")
print("  it can be switched off")

-- A quest giver who is no longer there. A passage starts after a delay and can
-- outlive the unit, so this has to fall back rather than show nothing.
_G.NPC_THERE = false
Addon.ShowTalker("Ein Buch", "npc", "")
assert(talker:IsShown(), "no unit meant no frame at all")
print("  a quest with nobody to portray still shows the frame")

-- Without QuestWordHunter installed the frame wears its own backdrop and
-- nothing above this line has raised an error. This addon lists that one as an
-- optional dependency, so a player with the voice packs and nothing else is the
-- ordinary case, not an edge one.
assert(WordHunterWoW_Addon == nil, "the base addon must not be needed to get this far")
assert(talker.backdrop and talker.backdrop.bgFile == "Interface\\DialogFrame\\UI-DialogBox-Background-Dark",
  "the standalone frame lost its own backdrop")
print("  it stands up on its own, with its own backdrop")

-- The two transport buttons, found by the German words they show rather than by
-- where they sit. A frame that reads a passage aloud and offers no way to stop
-- it or hear it again is the complaint this frame exists to answer.
local buttons = transportButtons()
local playButton = buttons["Vorlesen fortsetzen"]
local pauseButton = buttons["Vorlesen pausieren"]
assert(playButton, "no button offers to resume the reading")
assert(pauseButton, "no button offers to pause the reading")
print("  it carries a play button and a pause button, both named in German")

-- One at a time, the way a media player does it: the icon on screen is the
-- thing a click will do. Both showing at once is the bug this guards.
local function onlyOne(which, why)
  local wanted = which == "play" and playButton or pauseButton
  local other = which == "play" and pauseButton or playButton
  assert(wanted:IsShown(), why .. ": the " .. which .. " button was not shown")
  assert(not other:IsShown(), why .. ": both buttons were on screen at once")
end

Addon.ShowTalker("Die Stellung halten", "npc", "Satz 1 von 3")
onlyOne("pause", "while a passage is being read")
Addon.RestTalker()
onlyOne("play", "once the passage has finished")
print("  exactly one of the two is on screen, never both")

-- Pressing them does the thing. Wired through the engine rather than checked
-- for a closure: a button holding the wrong function is invisible until it is
-- pressed in game.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"] = {
  quests = { 14621, 29377 },
  lengths = "25152 o 120,250,80\n",
}
Addon.ForgetParts()
local clip = {}
for i = 1, 3 do
  clip[i] = "Interface\\AddOns\\WordHunterWoW-Voice-DE-Cataclysm\\"
    .. Addon.QuestPath(25152, "description", i)
  _G.EXISTS[clip[i]] = true
end

booked = {}
assert(Addon.PlayQuest(25152, "description"), "the passage did not start")
fire()
assert(asked[#asked] == clip[2], "the passage did not reach its second sentence")
onlyOne("pause", "part-way through a passage")

pauseButton.onOnClick(pauseButton)
assert(talker:IsShown(), "pausing hid the frame, and the play button with it")
onlyOne("play", "while paused")

local heard = #asked
playButton.onOnClick(playButton)
assert(#asked > heard, "the play button played nothing")
assert(asked[#asked] == clip[2],
  "the play button restarted the passage instead of carrying on: " .. tostring(asked[#asked]))
onlyOne("pause", "once the reading has resumed")
print("  pausing keeps the frame, and play carries on from where it stopped")

-- After the last sentence the frame stays, saying it has finished. Hiding it
-- then would put the play button out of reach at the one moment it is wanted.
Addon.ShowTalker("Die Stellung halten", "npc", "Satz 5 von 5")
Addon.RestTalker()
assert(talker:IsShown(), "the frame vanished when the passage ended")
print("  it stays up when the passage ends, so it can be played again")

-- Where it sits is remembered, so a player who moves it does not have to again.
WordHunterWoWVoiceDB.talkerPoint = nil
talker.onOnDragStop(talker)
assert(WordHunterWoWVoiceDB.talkerPoint, "the position was not remembered")
assert(WordHunterWoWVoiceDB.talkerPoint[1] == "BOTTOM",
  "remembered the wrong anchor: " .. tostring(WordHunterWoWVoiceDB.talkerPoint[1]))
print("  moving it is remembered")

-- A base addon that is there but older than the theming: every lookup is
-- guarded, so this must be a quiet no-op rather than an error in somebody's
-- chat frame.
WordHunterWoW_Addon = {}
Addon.ShowTalker("Die Stellung halten", "npc", "Satz 1 von 3")
assert(talker:IsShown(), "an older base addon stopped the frame appearing")
print("  a base addon without the theming is ignored, not fatal")

-- The skin. The frame is painted by the base addon's own helper rather than by
-- a palette copied over here, which is the only way it can still match after
-- the base addon gains a fifth skin.
local painted = {}
WordHunterWoW_Addon = {
  chosen = "tooltip",
  COLORS = { text = { 0.93, 0.94, 0.96 }, muted = { 0.76, 0.80, 0.86 } },
  BACKGROUNDS = {
    tooltip = { insets = { left = 3, right = 3, top = 3, bottom = 3 } },
    -- The parchment one, whose border art reaches far enough in to matter.
    dialog = { insets = { left = 11, right = 12, top = 12, bottom = 11 } },
  },
}
function WordHunterWoW_Addon.GetBackgroundStyle() return WordHunterWoW_Addon.chosen end
function WordHunterWoW_Addon.ApplyBackground(f) painted[#painted + 1] = f end
function WordHunterWoW_Addon.RefreshAllBackdrops() end

Addon.ShowTalker("Die Stellung halten", "npc", "Satz 1 von 3")
assert(painted[#painted] == talker, "the frame was not painted by the base addon's helper")
local titleText
for _, f in ipairs(frames) do
  if f.text == "Die Stellung halten" then titleText = f end
end
assert(titleText and titleText.color and math.abs(titleText.color[1] - 0.93) < 0.001,
  "the title kept the game's gold instead of the base addon's text colour")
print("  it is painted by the base addon's own helper, palette and all")

-- Changing the skin repaints it at once. The base addon fans that out to a list
-- of its own windows with no slot for this one, so the fan-out is wrapped; if
-- that wrapping breaks, the frame only catches up at the next quest.
local before = #painted
WordHunterWoW_Addon.RefreshAllBackdrops()
assert(#painted > before, "changing the skin did not reach the voice frame")

-- And the contents move in with the border art. Eight pixels is right against
-- the thin skins and sits half on the parchment one's border.
local function corner(button)
  local last = button.points[#button.points]
  return last and last[1] == "TOPRIGHT" and last[2] or nil
end
assert(corner(playButton) == -6,
  "the button sits at " .. tostring(corner(playButton)) .. " on the tooltip skin, not -6")
WordHunterWoW_Addon.chosen = "dialog"
WordHunterWoW_Addon.RefreshAllBackdrops()
assert(corner(playButton) == -14,
  "the parchment skin did not push the button clear of its border: " .. tostring(corner(playButton)))
print("  the contents move in as far as the chosen skin's border reaches")

-- ---------------------------------------------------------------------------
-- What size this window is, which until now was one answer: 300x96 for ever.
--
-- It is a scale and not a font size on purpose. Both strings here are pinned in
-- a fixed 300px frame with word wrap off, and the quest name has 194px to fit
-- in -- less than a real German quest name needs at 12pt already. Growing the
-- letters inside the same box truncates more of the name, not less. SetScale
-- takes the box with it.
--
-- No new setting: the voice side stores no size of its own, so it borrows the
-- base addon's quest-panel text size -- the setting for the words this window
-- is captioning.
local talkerFrame
for _, f in ipairs(frames) do
  if f.kind == "Frame" and f.w == 300 and f.h == 96 then talkerFrame = f end
end
assert(talkerFrame, "the talker frame should have been built at 300x96")

-- The base addon here has a theme but no size getter, and a client without
-- QuestWordHunter at all has neither. Both must leave this window alone.
Addon.ShowTalker("Die Stellung halten", nil, nil)
assert(talkerFrame:GetScale() == 1,
  "with no size to ask the base addon for, the talker must stay at 1, got "
  .. tostring(talkerFrame:GetScale()))

WordHunterWoW_Addon.GetTextScale = function() return 1.5 end
Addon.ShowTalker("Die Stellung halten", nil, nil)
assert(talkerFrame:GetScale() == 1.5,
  "the talker should follow the quest panel's text size, got "
  .. tostring(talkerFrame:GetScale()))

-- A nonsense value from a future base addon is not a size to wear.
WordHunterWoW_Addon.GetTextScale = function() return 0 end
Addon.ShowTalker("Die Stellung halten", nil, nil)
assert(talkerFrame:GetScale() == 1,
  "a size of zero should fall back to 1, got " .. tostring(talkerFrame:GetScale()))
WordHunterWoW_Addon.GetTextScale = nil
-- The size is asked for when the window is drawn, not when the slider moves,
-- and that gap is asserted rather than assumed harmless: a player who drags
-- the quest text while the talker is on screen sees it catch up at the start
-- of the next passage. That is the whole cost of not having the companion
-- reach into the base addon to be told, and this is where it is written down.
WordHunterWoW_Addon.GetTextScale = function() return 1.5 end
Addon.ShowTalker("Die Stellung halten", nil, nil)
WordHunterWoW_Addon.GetTextScale = function() return 2.0 end
assert(talkerFrame:GetScale() == 1.5,
  "the talker is not expected to re-scale while it is up: " .. tostring(talkerFrame:GetScale()))
Addon.ShowTalker("Die Stellung halten", nil, nil)
assert(talkerFrame:GetScale() == 2.0,
  "but the next passage must take the new size, got " .. tostring(talkerFrame:GetScale()))
WordHunterWoW_Addon.GetTextScale = nil
print("  a size changed while it is up is taken at the next passage")

print("  it follows the base addon's quest panel size, and nothing when there is none")

print("talker: ok")
