-- lua5.1 tests/talker-button-geometry.test.lua [classic]
-- Measure rendered alpha footprints, not just the already-equal hitboxes.
-- Bounds are from the client's native 32px PNGs (Gethe/wow-ui-textures).
local classic = arg[1] == 'classic'
local buttons = {}
local alpha = {
  ['Interface\\Buttons\\UI-SpellbookIcon-NextPage-Up'] = { 2, 3, 29, 29 },
  ['Interface\\Buttons\\UI-RotationLeft-Button-Up'] = { 3, 3, 29, 28 },
  ['Interface\\Buttons\\UI-Panel-MinimizeButton-Up'] = { 6, 7, 25, 25 },
  ['Interface\\Buttons\\UI-Panel-MinimizeButton-Down'] = { 6, 7, 25, 25 },
  ['Interface\\Buttons\\UI-Panel-MinimizeButton-Disabled'] = { 6, 7, 25, 25 },
}
local function region(kind, parent)
  local r = { kind = kind, parent = parent, points = {}, textures = {}, scripts = {},
    w = 0, h = 0, scale = 1, uv = { 0, 1, 0, 1 } }
  function r:SetSize(w, h) self.w, self.h = w, h end
  function r:GetSize() if self.all then return self.all:GetSize() end return self.w, self.h end
  function r:GetWidth() local w = self:GetSize() return w end
  function r:GetHeight() local _, h = self:GetSize() return h end
  function r:SetScale(value) self.scale = value end
  function r:GetEffectiveScale() return self.scale * (self.parent and self.parent:GetEffectiveScale() or 1) end
  function r:SetPoint(...) self.points[#self.points + 1] = { ... } end
  function r:ClearAllPoints() self.points, self.all = {}, nil end
  function r:SetAllPoints(target) self.all = target or self.parent end
  function r:SetScript(name, fn) self.scripts[name] = fn end
  function r:SetTexture(file) self.file = file end
  function r:GetAtlas() return self.atlas end
  function r:SetTexCoord(...) self.uv = { ... } end
  function r:CreateTexture()
    local t = region('Texture', self)
    self.textures[#self.textures + 1] = t
    return t
  end
  function r:CreateFontString() return region('FontString', self) end
  function r:GetNormalTexture() return self.normal end
  function r:GetPushedTexture() return self.pushed end
  function r:GetDisabledTexture() return self.disabled end
  function r:GetHighlightTexture() return self.highlight end
  function r:Show() self.shown = true end
  function r:Hide() self.shown = false end
  function r:IsShown() return self.shown end
  for _, method in ipairs({ 'SetFrameStrata', 'SetClampedToScreen', 'SetMovable', 'EnableMouse',
    'RegisterForDrag', 'StartMoving', 'StopMovingOrSizing', 'SetHighlightTexture',
    'SetText', 'SetTextColor', 'SetJustifyH', 'SetWordWrap', 'SetVertexColor' }) do r[method] = function() end end
  return r
end
UIParent = region('Frame')
CreateFrame = function(kind, name, parent, template)
  local r = region(kind, parent)
  r.template = template
  if kind == 'Button' then buttons[#buttons + 1] = r end
  if template == 'UIPanelCloseButton' then
    -- The client template really differs: Mainline24px atlas vs Classic32px
    -- bitmap. Template texture state is preserved while fitting our24px slot.
    r:SetSize(classic and 32 or 24, classic and 32 or 24)
    for key, suffix in pairs({ normal = 'Up', pushed = 'Down', disabled = 'Disabled', highlight = 'Highlight' }) do
      local t = r:CreateTexture()
      t:SetAllPoints()
      if classic then t.file = 'Interface\\Buttons\\UI-Panel-MinimizeButton-' .. suffix
      else t.atlas, t.uv = 'RedButton-' .. key, { 0.1, 0.4, 0.2, 0.5 } end
      r[key] = t
    end
  end
  return r
end
BackdropTemplateMixin = nil
GameTooltip = { SetOwner = function() end, SetText = function(self, tip) self.tip = tip end,
  Show = function() end, Hide = function() end }
WordHunterWoW_Addon = { GetTextScale = function() return 1.5 end }
dofile('Talker.lua')
local A = WordHunterWoW_Voice
local frame = A.BuildTalker()
local byTip = {}
for _, button in ipairs(buttons) do
  button.scripts.OnEnter(button)
  byTip[GameTooltip.tip] = button
  local w, h = button:GetSize()
  assert(w == 24 and h == 24, 'every action keeps the same24px hitbox')
end
local play, replay, pause, close = byTip['Vorlesen fortsetzen'], byTip['Von vorne vorlesen'],
  byTip['Vorlesen pausieren'], byTip['Vorlesen stoppen und schließen']
local function footprint(t)
  local w, h = t:GetSize()
  if t.atlas then return w, h end
  local b, uv = assert(alpha[t.file], 'unknown client alpha bounds'), t.uv
  assert(uv[1] * 32 == b[1] and uv[2] * 32 == b[3]
    and uv[3] * 32 == b[2] and uv[4] * 32 == b[4], 'crop must retain the entire native visible artwork')
  return w * (b[3] - b[1]) / (32 * (uv[2] - uv[1])),
    h * (b[4] - b[2]) / (32 * (uv[4] - uv[3]))
end
for _, texture in ipairs({ play.textures[1], replay.textures[1], close.normal, close.pushed, close.disabled }) do
  local w, h = footprint(texture)
  assert(math.abs(w - 24) < 0.001 and math.abs(h - 24) < 0.001,
    'visible button body must fill24px, got ' .. w .. 'x' .. h)
  assert(math.abs(texture:GetEffectiveScale() - 1.5) < 0.001, 'texture and hitbox must share the talker scale')
end
assert(close.template == 'UIPanelCloseButton', 'the native close style remains intact')
if not classic then
  assert(close.normal.atlas == 'RedButton-normal' and close.normal.uv[1] == 0.1,
    'Mainline atlas UVs must not be overwritten with Classic bitmap cropping')
end
assert(close.highlight:GetWidth() == 24 and close.highlight:GetHeight() == 24, 'hover fits the same slot')
-- Pause has the same 24px framed slot as Play, with a smaller glyph inside.
assert(#pause.textures == 7, 'pause needs a surface, four native border slices and two bars')
for i = 2, 5 do
  local edge = pause.textures[i]
  assert(edge.file == play.textures[1].file, 'pause border must use the same native artwork as Play')
  local p = edge.points[1]
  local x, y = p[4], -p[5]
  assert(x >= 0 and y >= 0 and x + edge:GetWidth() <= 24.001 and y + edge:GetHeight() <= 24.001,
    'border slices must stay inside the same hitbox')
end
for i = 6, 7 do
  local bar = pause.textures[i]
  assert(bar:GetWidth() == 4 and bar:GetHeight() == 14, 'pause glyph must fit inside its border')
  assert(bar.points[1][1] == 'CENTER' and math.abs(bar.points[1][4]) == 3)
end
local function x(button) local p = button.points[1] return p[#p - 1] end
assert(x(close) - x(play) == 26 and x(play) - x(replay) == 26, 'the three slots keep their spacing')
assert(x(play) == x(pause), 'play and pause remain in the same slot')
A.SetTalkerSpeaking(true)
assert(pause:IsShown() and not play:IsShown())
A.SetTalkerSpeaking(false)
assert(play:IsShown() and not pause:IsShown())
local stopped = false
A.Stop = function() stopped = true end
close.scripts.OnClick(close)
assert(stopped, 'close still stops the audio')
assert(WordHunterWoWVoiceDB.talker == nil and WordHunterWoWVoiceDB.talkerPoint == nil,
  'visual normalization cannot change stored settings/position')
print('talker-button-geometry: ' .. (classic and 'Classic bitmap' or 'Mainline atlas')
  .. ',24px bodies/hitboxes,14px pause glyph,36px at1.5scale: ok')
