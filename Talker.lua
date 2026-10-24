local ADDON_NAME = ... or "WordHunterWoW-Voice-DE"
local Addon = WordHunterWoW_Voice or {}
WordHunterWoW_Voice = Addon
if Addon.host == nil and Addon.ForgetParts == nil then Addon.host = ADDON_NAME end
if Addon.host ~= ADDON_NAME then return end
local unpack = unpack or table.unpack

BINDING_HEADER_WORDHUNTERVOICE = "QuestWordHunter Voice"
BINDING_NAME_WORDHUNTERVOICE_PAUSE = "Pause / resume voice"
BINDING_NAME_WORDHUNTERVOICE_REPLAY = "Replay passage"
BINDING_NAME_WORDHUNTERVOICE_STOP = "Stop voice"

local WIDTH, HEIGHT, PORTRAIT, BUTTON = 300, 96, 40, 26
-- The progress bar and the room it needs between the portrait and the buttons.
local BAR, BAR_ROOM = 8, 16
local WHITE = "Interface\\Buttons\\WHITE8X8"
local frame, portrait, title, subtitle, play, pause, restart, closeButton
local track, bar, remaining
local speaking, themeHooked = false, false

local function db()
  if type(WordHunterWoWVoiceDB) ~= "table" then WordHunterWoWVoiceDB = {} end
  return WordHunterWoWVoiceDB
end

local function textScale()
  local base = WordHunterWoW_Addon
  local value = base and base.GetTextScale and base.GetTextScale()
  return type(value) == "number" and value > 0 and value or 1
end

function Addon.GetTalkerEnabled()
  return db().talker ~= false
end

function Addon.SetTalkerEnabled(value)
  db().talker = value and true or false
  if not db().talker then Addon.HideTalker() end
end

function WordHunterWoW_VoiceTogglePause()
  if speaking then
    if Addon.Pause then Addon.Pause() end
  elseif Addon.Resume then Addon.Resume() end
end

local function padding()
  local base = WordHunterWoW_Addon
  local style = base and base.BACKGROUNDS and base.GetBackgroundStyle
    and base.BACKGROUNDS[base.GetBackgroundStyle()]
  local insets = style and style.insets
  if not insets then return 12 end
  return math.max(12, (insets.left or 0) + 4, (insets.right or 0) + 4)
end

local function layout()
  if not frame then return end
  local native = rawget(frame, "whwNativeStyle")
  local pad, top = padding(), native and 36 or 12
  local right = native and pad or pad + 24
  portrait:ClearAllPoints()
  portrait:SetPoint("TOPLEFT", frame, "TOPLEFT", pad, -top)
  title:ClearAllPoints()
  title:SetPoint("TOPLEFT", portrait, "TOPRIGHT", 10, -2)
  title:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -right, -top - 2)
  subtitle:ClearAllPoints()
  subtitle:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -4)
  subtitle:SetPoint("TOPRIGHT", title, "BOTTOMRIGHT", 0, -4)
  for _, button in ipairs({ play, pause }) do
    button:ClearAllPoints()
    button:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -pad, pad)
  end
  restart:ClearAllPoints()
  restart:SetPoint("RIGHT", play, "LEFT", -8, 0)
  -- Just above the buttons, across the window; the time left sits beside them.
  track:ClearAllPoints()
  track:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", pad, pad + BUTTON + 8)
  track:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -pad, pad + BUTTON + 8)
  remaining:ClearAllPoints()
  remaining:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", pad, pad + (BUTTON - 10) / 2)
  closeButton:ClearAllPoints()
  closeButton:SetPoint("TOPRIGHT", frame, "TOPRIGHT", native and -2 or -4, native and -2 or -4)
end

local function applyTheme()
  if not frame then return end
  local base = WordHunterWoW_Addon
  if base and base.ApplyBackground then base.ApplyBackground(frame) end
  local colors = base and base.COLORS
  if colors and colors.text then title:SetTextColor(unpack(colors.text)) end
  if colors and colors.muted then
    subtitle:SetTextColor(unpack(colors.muted))
    remaining:SetTextColor(unpack(colors.muted))
  end
  layout()
end

local function followTheme()
  local base = WordHunterWoW_Addon
  if themeHooked or not base or not base.RefreshAllBackdrops then return end
  themeHooked = true
  local previous = base.RefreshAllBackdrops
  base.RefreshAllBackdrops = function(...)
    previous(...)
    applyTheme()
  end
  applyTheme()
end

local function bindingText(action)
  local base = WordHunterWoW_Addon
  local usingPad = base and base.GamePadHintsEnabled and base.GamePadHintsEnabled()
  if usingPad == nil then
    usingPad = C_GamePad and C_GamePad.IsEnabled and C_GamePad.IsEnabled()
      or GetCVarBool and GetCVarBool("GamePadEnable") or false
  end
  local labels = {}
  for _, key in ipairs(GetBindingKey and { GetBindingKey(action) } or {}) do
    local pad = key:find("PAD", 1, true) and not key:find("NUMPAD", 1, true) or false
    if (pad and true or false) == (usingPad and true or false) then
      labels[#labels + 1] = base and base.InputKeyText and base.InputKeyText(key)
        or GetBindingText and GetBindingText(key, 1) or key
    end
  end
  return table.concat(labels, " / ")
end

local function tooltip(button, label, action)
  local hook = type(button.HookScript) == "function" and button.HookScript or button.SetScript
  hook(button, "OnEnter", function(self)
    if not GameTooltip then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(label)
    local keys = bindingText(action)
    if GameTooltip.AddLine then
      GameTooltip:AddLine(keys ~= "" and keys or "Assign in Key Bindings > AddOns > QuestWordHunter Voice", .8, .75, .64, true)
    end
    GameTooltip:Show()
  end)
  hook(button, "OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
end

local function build()
  if frame then return frame end
  local base = WordHunterWoW_Addon
  if base and base.CreateNativeWindow then
    frame = base.CreateNativeWindow("WordHunterWoWVoiceTalker", "library", "Quest audio")
  else
    frame = CreateFrame("Frame", "WordHunterWoWVoiceTalker", UIParent,
      BackdropTemplateMixin and "BackdropTemplate" or nil)
    if frame.SetBackdrop then
      frame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background-Dark",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32,
        edgeSize = 16, insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    end
  end
  frame:SetSize(WIDTH, HEIGHT + BAR_ROOM + (rawget(frame, "whwNativeStyle") and 32 or 0))
  frame:SetScale(textScale())
  frame:SetFrameStrata("FULLSCREEN_DIALOG")
  if frame.SetFrameLevel then frame:SetFrameLevel(35) end
  frame:SetClampedToScreen(true)
  frame:SetMovable(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", frame.StartMoving)
  frame:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    local point, _, relative, x, y = self:GetPoint()
    db().talkerPoint = { point, relative, x, y }
  end)
  local held = db().talkerPoint
  if type(held) == "table" and type(held[1]) == "string" and type(held[2]) == "string"
      and type(held[3]) == "number" and type(held[4]) == "number" then
    frame:SetPoint(held[1], UIParent, held[2], held[3], held[4])
  else
    frame:SetPoint("BOTTOM", UIParent, "BOTTOM", 0, 210)
  end

  -- A still portrait has no model animation to render while audio is idle.
  portrait = frame:CreateTexture(nil, "ARTWORK")
  portrait:SetSize(PORTRAIT, PORTRAIT)
  portrait:SetTexCoord(.08, .92, .08, .92)
  title = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  subtitle = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  for _, text in ipairs({ title, subtitle }) do
    text:SetJustifyH("LEFT")
    text:SetWordWrap(false)
    if text.SetMaxLines then text:SetMaxLines(1) end
  end
  if base and base.ApplyFontRole then
    base.ApplyFontRole(title, "body")
    base.ApplyFontRole(subtitle, "label")
  end

  -- How far through the passage the voice is. A dark track with a one-pixel
  -- edge holds the bar so the edge stays visible under the fill.
  track = CreateFrame("Frame", nil, frame, BackdropTemplateMixin and "BackdropTemplate" or nil)
  track:SetHeight(BAR)
  if track.SetBackdrop then
    track:SetBackdrop({ bgFile = WHITE, edgeFile = WHITE, edgeSize = 1 })
    track:SetBackdropColor(.03, .04, .06, 1)
    track:SetBackdropBorderColor(.35, .37, .42, 1)
  end
  bar = CreateFrame("StatusBar", nil, track)
  bar:SetPoint("TOPLEFT", track, "TOPLEFT", 1, -1)
  bar:SetPoint("BOTTOMRIGHT", track, "BOTTOMRIGHT", -1, 1)
  bar:SetStatusBarTexture(WHITE)
  bar:SetMinMaxValues(0, 1)
  bar:SetValue(0)
  remaining = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  remaining:SetJustifyH("LEFT")
  if base and base.ApplyFontRole then base.ApplyFontRole(remaining, "label") end

  local function transport(label, action, binding, tip)
    local button = base and base.createActionButton and base.createActionButton(frame, label)
      or CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    button:SetText(label)
    button:SetSize(80, BUTTON)
    button:SetScript("OnClick", action)
    tooltip(button, tip, binding)
    return button
  end
  restart = transport("Replay", function() if Addon.Replay then Addon.Replay() end end, "WORDHUNTERVOICE_REPLAY", "Von vorne vorlesen")
  play = transport("Play", function() if Addon.Resume then Addon.Resume() end end, "WORDHUNTERVOICE_PAUSE", "Vorlesen fortsetzen")
  pause = transport("Pause", function() if Addon.Pause then Addon.Pause() end end, "WORDHUNTERVOICE_PAUSE", "Vorlesen pausieren")
  closeButton = rawget(frame, "CloseButton") or CreateFrame("Button", nil, frame, "UIPanelCloseButton")
  closeButton:SetSize(24, 24)
  if not rawget(frame, "CloseButton") then
    -- Older clients pad the close bitmap; keep its visible cross inside the hitbox.
    for _, getter in ipairs({ "GetNormalTexture", "GetPushedTexture", "GetDisabledTexture", "GetHighlightTexture" }) do
      local texture = closeButton[getter] and closeButton[getter](closeButton)
      if texture then
        texture:ClearAllPoints()
        texture:SetAllPoints(closeButton)
        if getter ~= "GetHighlightTexture" and (not texture.GetAtlas or not texture:GetAtlas()) then
          texture:SetTexCoord(6 / 32, 25 / 32, 7 / 32, 25 / 32)
        end
      end
    end
  end
  closeButton:SetScript("OnClick", function() if Addon.Stop then Addon.Stop() end end)
  tooltip(closeButton, "Vorlesen stoppen und schließen", "WORDHUNTERVOICE_STOP")

  local registered
  local function refreshControls()
    if not registered and not (InCombatLockdown and InCombatLockdown())
        and ConsolePort and type(ConsolePort.AddInterfaceCursorFrame) == "function" then
      registered = ConsolePort:AddInterfaceCursorFrame(frame)
    end
  end
  frame:SetScript("OnShow", function()
    local current = WordHunterWoW_Addon
    if current and current.ApplyReadingDim then current.ApplyReadingDim() end
    refreshControls()
  end)
  local controls = CreateFrame("Frame", nil, frame)
  for _, event in ipairs({ "ADDON_LOADED", "PLAYER_REGEN_ENABLED" }) do
    pcall(controls.RegisterEvent, controls, event)
  end
  controls:SetScript("OnEvent", refreshControls)
  applyTheme()
  Addon.SetTalkerSpeaking(speaking)
  frame:Hide()
  Addon.talkerFrame = frame
  return frame
end
Addon.BuildTalker = build

-- Where the voice is in the passage, in seconds from its start.
--
-- The client cannot say how far into a clip it has got, so this is a model: the
-- engine says where the sentence now playing begins and how long the whole
-- passage runs, and the bar moves at the pace of the clock from there. Each new
-- sentence puts it back on the engine's own figure, so a timer that fires a
-- frame late cannot add up to a drift.
local progress = { total = nil, base = 0, started = nil }
local ticker

local function clock(seconds)
  seconds = math.max(0, math.ceil(seconds - 1e-6))
  return string.format("-%d:%02d", math.floor(seconds / 60), seconds % 60)
end

local function paintProgress()
  if not bar then return end
  local total = progress.total
  if not total or total <= 0 then
    bar:SetMinMaxValues(0, 1)
    bar:SetValue(0)
    remaining:SetText("")
    return
  end
  local position = progress.base
  if progress.started then position = progress.base + (GetTime() - progress.started) end
  position = math.max(0, math.min(total, position))
  bar:SetMinMaxValues(0, total)
  bar:SetValue(position)
  -- Gold while it speaks, dimmed while it waits, so a paused bar does not look
  -- like a frozen one.
  if progress.started then bar:SetStatusBarColor(.95, .78, .18) else bar:SetStatusBarColor(.55, .47, .15) end
  remaining:SetText(position >= total and "" or clock(total - position))
end

-- The updates run only while the voice is speaking: an idle talker has nothing
-- to count, and a frame that ticks forever for a window nobody is looking at is
-- exactly the idle cost this addon was trimmed of.
local function tick(running)
  if running then
    ticker = ticker or CreateFrame("Frame")
    local since = 0
    ticker:SetScript("OnUpdate", function(_, elapsed)
      since = since + elapsed
      if since >= 0.1 then since = 0; paintProgress() end
    end)
  elseif ticker then
    ticker:SetScript("OnUpdate", nil)
  end
end

-- `start` is the second of the passage at which the sentence now playing begins,
-- `total` how long the whole passage runs; with no `total` there is nothing to
-- show (a pack without durations) and the bar stays empty.
function Addon.SetTalkerProgress(start, total, running)
  progress.total = tonumber(total)
  progress.base = tonumber(start) or 0
  progress.started = (progress.total and running) and GetTime() or nil
  paintProgress()
  tick(progress.started ~= nil)
end

function Addon.SetTalkerSpeaking(value)
  speaking = value and true or false
  if not speaking then
    -- Paused: the reading will start this sentence again, so the bar waits at
    -- its beginning rather than where the clock had got to.
    progress.started = nil
    paintProgress()
    tick(false)
  end
  if not play or not pause then return end
  if speaking then pause:Show(); play:Hide() else play:Show(); pause:Hide() end
end

function Addon.ShowTalker(name, speaker, line)
  if not Addon.GetTalkerEnabled() then return end
  build()
  followTheme()
  Addon.SetTalkerSpeaking(true)
  -- A new line is a new passage as far as the bar goes; the engine says how far
  -- in it is right after.
  progress.total, progress.base, progress.started = nil, 0, nil
  paintProgress()
  tick(false)
  title:SetText(name or "")
  subtitle:SetText(line or "")
  if speaker and UnitExists and UnitExists(speaker) and SetPortraitTexture then
    SetPortraitTexture(portrait, speaker)
  else
    portrait:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
  end
  portrait:Show()
  frame:SetScale(textScale())
  frame:Show()
end

function Addon.HideTalker()
  if frame then frame:Hide() end
  tick(false)
end

function Addon.RestTalker()
  if not frame or not frame:IsShown() then return end
  Addon.SetTalkerSpeaking(false)
  if progress.total then progress.base = progress.total end
  paintProgress()
  if subtitle then subtitle:SetText("fertig vorgelesen") end
end

function Addon.TalkerLine(index, total)
  index, total = tonumber(index) or 1, tonumber(total)
  if not total or total <= 1 then return "" end
  if index > total then index = total end
  return string.format("Satz %d von %d", index, total)
end
