-- lua5.1 tests/catalog-language-audio.test.lua [base-directory] [before-voice-directory|-] [word|panel|-] [host1,host2]
-- Real reader/editor clicks exercise the optional companion's installed hooks.
local BASE, before, only = arg[1] or '../whwow', arg[2], arg[3]
if before == '-' then before = nil end
dofile(BASE .. '/tests/wowstub.lua')
local create, frames = CreateFrame, {}
CreateFrame = function(kind, name, parent, template)
  local f = create(kind, name, parent, template)
  local show, hide = f.Show, f.Hide
  function f:HookScript(event, hook)
    local previous = self:GetScript(event)
    self:SetScript(event, function(self, ...)
      if previous then previous(self, ...) end
      hook(self, ...)
    end)
  end
  function f:Show()
    local was = self:IsShown()
    show(self)
    local script = self:GetScript('OnShow')
    if not was and script then script(self) end
  end
  function f:Hide()
    local was = self:IsShown()
    hide(self)
    local script = self:GetScript('OnHide')
    if was and script then script(self) end
  end
  frames[#frames + 1] = f
  local children = {}
  function f:GetChildren() return unpack(children) end
  function f:GetTop()
    local p = rawget(self, '_points') or {}
    local anchor = p.TOPLEFT or p.TOPRIGHT or p.TOP
    return (parent and parent.GetTop and parent:GetTop() or 1000) + (anchor and anchor.y or 0)
  end
  function f:GetLeft()
    local p = rawget(self, '_points') or {}
    local anchor = p.TOPLEFT or p.BOTTOMLEFT or p.LEFT
    return (parent and parent.GetLeft and parent:GetLeft() or 0) + (anchor and anchor.x or 0)
  end
  function f:GetVerticalScroll() return 0 end
  f._testChildren = children
  if parent and rawget(parent, '_testChildren') then table.insert(parent._testChildren, f) end
  return f
end
-- Timers keep a played German clip active until the English render stops it.
local due = {}
C_Timer.After = function(_, callback) due[#due + 1] = callback end
local sounds, stops, handle = {}, {}, 0
PlaySoundFile = function(path, channel)
  handle = handle + 1
  sounds[#sounds + 1] = { path = path, channel = channel, handle = handle }
  return true, handle
end
StopSound = function(h) stops[#stops + 1] = h end
GetBuildInfo = function() return '1.60.1', '', '', 16001 end
for _, file in ipairs({ 'Core.lua', 'Compat.lua', 'UICommon.lua', 'Recall.lua', 'QuestPanel.lua',
  'WordList.lua', 'Editor.lua', 'QuestBrowser.lua', 'QuestReader.lua' }) do dofile(BASE .. '/' .. file) end
local B = WordHunterWoW_Addon
WordHunterWoWDB = { settings = { targetLocale = 'deDE', frames = {}, integratedLayout = true }, wordsByLocale = {} }
B.initializeDatabase()
assert(B.Compat.GameFlavor() == 'forever')
WordHunterWoW_QuestDataByFlavor = { forever = { sourceFlavor = 'classic',
  deDE = { [783] = { title = 'Die Bedrohung von innen', description = 'Der Wolf wartet.', objectives = 'Findet den Wolf.' } },
  enUS = {
    [783] = { title = 'A Threat Within', description = 'The wolf waits.', objectives = 'Find the wolf.' },
    [777] = { title = 'English reference', description = 'Fallbackword waits.' },
  },
} }
WordHunterWoW_QuestEN = { [783] = { title = 'Retail replacement', description = 'Deathwing.' } }
C_QuestLog, GetQuestLogQuestText = nil, nil
SelectQuestLogEntry = function() error('catalog voice test must not change game quest selection') end
WordHunterWoWVoiceDB = { enabled = true, words = true }
WordHunterWoW_Voice_Parts = { ['WordHunterWoW-Voice-DE-Classic'] = {
  quests = { 1, 10000 }, words = true, lengths = '783 o 120\n',
} }
local hosts = arg[4] or 'WordHunterWoW-Voice-DE'
for folder in hosts:gmatch('[^,]+') do
  for _, file in ipairs({ 'Naming.lua', 'Talker.lua', 'Voice.lua', 'PlayButtons.lua' }) do
    local old = before and ((file == 'Voice.lua' and only ~= 'panel') or (file == 'PlayButtons.lua' and only ~= 'word'))
    assert(loadfile(old and before .. '/' .. file or file))(folder)
  end
end
local V = WordHunterWoW_Voice
assert(V.host == hosts:match('^[^,]+'), 'the first loaded carrier must remain the only active engine')
V.ForgetParts()
local voiceEvent
for _, f in ipairs(frames) do
  if f:GetScript('OnEvent') then voiceEvent = f:GetScript('OnEvent') end
end
assert(voiceEvent, 'voice engine event handler must exist')

B.createPanel()
B.createEditor()
V.HookBaseAddon()
V.HookQuestPanel()
local function click(frame)
  assert(frame and type(frame:GetScript('OnClick')) == 'function', 'expected actual click handler')
  frame:GetScript('OnClick')(frame, 'LeftButton')
end
local function word(text)
  for _, b in ipairs(B.panel.wordButtons) do if b:IsShown() and b.word == text then return b end end
  error('reader did not draw word: ' .. text)
end
local function voiceButtons()
  local out = {}
  for _, f in ipairs(frames) do if rawget(f, 'clip') and f:IsShown() then out[#out + 1] = f end end
  return out
end
assert(B.OpenCatalogQuest(783))
assert(B.lastQuest.wordLocale == 'deDE' and not B.lastQuest.voiceUnavailable)
assert(B.TextGutter() > 0 and #voiceButtons() > 0, 'German catalog must keep actual audio gutter and paragraph buttons')
click(word('Wolf'))
assert(#sounds == 1 and sounds[1].path:find('\\w\\', 1, true), 'actual German editor click must still play its word recording')
assert(B.selected.locale == 'deDE' and B.editor:IsShown())
click(voiceButtons()[1])
local active = sounds[#sounds].handle
assert(V.CanReplay() and sounds[#sounds].path:find('783_o1', 1, true), 'German paragraph click must start the actual quest recording')

B.SetTargetLocale('enUS')
assert(B.lastQuest.wordLocale == 'enUS' and B.lastQuest.voiceUnavailable and not B.lastQuest.readOnly)
assert(stops[#stops] == active and not V.CanReplay(), 'English render must stop the active German quest rather than leave unrelated speech running')
assert(B.TextGutter() == 0 and #voiceButtons() == 0, 'English render must reclaim the gutter and hide pooled German paragraph buttons')
local played = #sounds
click(word('wolf'))
assert(B.selected.locale == 'enUS' and B.editor:IsShown(), 'explicit English must still open its real vocabulary editor')
assert(#sounds == played, 'English editor options must suppress German word audio')
assert(B.GetTargetLocale() == 'enUS', 'the Reader must follow the learning language from Settings')

-- Explicit options keep their source language even while the catalog is German.
B.SetTargetLocale('deDE')
played = #sounds
B.openEditor('wolf', 'Explicit English context.', 783, 'A Threat Within', { locale = 'enUS', origin = 'panel' })
assert(B.selected.locale == 'enUS' and #sounds == played, 'source locale must beat the global German target in the voice wrapper')
-- Calls from older German base addons had no options; preserve that path.
B.openEditor('Wolf', 'Legacy German context.', 783, 'Die Bedrohung von innen')
assert(#sounds == played + 1 and B.selected.locale == 'deDE', 'legacy default German calls must keep their audio')
V.PlayQuest(783, 'description', 1, true)
active = sounds[#sounds].handle
assert(B.OpenCatalogQuest(777))
assert(B.lastQuest.readOnly and B.lastQuest.voiceUnavailable and stops[#stops] == active and not V.CanReplay())
assert(B.TextGutter() == 0 and #voiceButtons() == 0)
played = #sounds
click(word('Fallbackword'))
assert(not B.editor:IsShown() and #sounds == played, 'implicit English fallback must stay silent and read-only')
assert(B.GetTargetLocale() == 'deDE' and WordHunterWoWDB.settings.targetLocale == 'deDE')
-- An older base namespace had neither locale options nor GetTargetLocale.
local delegated
WordHunterWoW_Addon = { openEditor = function(...) delegated = { ... } return 'legacy editor result' end }
V.hooked = nil
V.HookBaseAddon()
played = #sounds
assert(WordHunterWoW_Addon.openEditor('Wolf', 'Older base.', 783, 'Old title') == 'legacy editor result')
assert(#sounds == played + 1 and delegated[1] == 'Wolf' and delegated[2] == 'Older base.',
  'older bases without any locale API must retain German audio and editor arguments/results')
print('catalog-language-audio: ' .. V.host .. ', actual DE word/paragraph audio, EN source guard, stop-on-English render, zero gutter/buttons, legacy default and silent fallback: ok')

WordHunterWoW_Addon = B
B.SetQuestVoiceAutoPlay(false)
B.panel:Hide()
played = #sounds
assert(B.OpenCatalogQuest(783))
assert(#sounds == played and V.CanReplay() and V.talkerFrame:IsShown(), 'opening Reader must prepare a silent talker')
B.refreshPanel()
assert(#sounds == played, 'redrawing the same Reader must not start its voice')
V.Resume()
assert(#sounds > played and sounds[#sounds].path:find('783_o1', 1, true), 'manual Play must read the prepared Reader quest')
B.panel:Hide()
assert(not V.CanReplay() and not V.talkerFrame:IsShown(), 'closing Reader must stop and dismiss its talker')
B.SetQuestVoiceAutoPlay(true)
due = {}
played = #sounds
assert(B.OpenCatalogQuest(783))
assert(#sounds == played and #due == 1, 'autoplay must wait for the configured delay')
table.remove(due, 1)()
assert(#sounds > played, 'explicit autoplay must start the Reader quest')
B.panel:Hide()
B.SetQuestVoiceAutoPlay(false)
played = #sounds
assert(B.OpenCatalogQuest(783))
assert(#sounds == played and V.talkerFrame:IsShown(), 'switching back to manual must retain the silent transport')
print('catalog-language-audio: real Reader manual transport, redraw, close and autoplay toggle: ok')

-- Real NPC event must not summon the narrator while Reader is closed.
B.panel:Hide()
B.SetNpcReaderAutoOpen(false)
B.SetQuestVoiceAutoPlay(true) -- Even this opt-in does not imply opening Reader.
GetQuestID = function() return 783 end
GetQuestText = function() return 'Der Wolf wartet.' end
GetObjectiveText = function() return 'Findet den Wolf.' end
QuestFrame:Show(); B.lastPassage = 'offer'
due = {}; played = #sounds
voiceEvent(nil, 'QUEST_DETAIL')
B.readCurrentQuest()
assert(not B.panel:IsShown() and not V.talkerFrame:IsShown() and #sounds == played and #due == 0,
  'NPC event must leave Reader and narrator closed without booking speech')
B.SetQuestVoiceAutoPlay(false)
B.readCurrentQuest(nil, true)
assert(B.panel:IsShown() and V.talkerFrame:IsShown() and V.CanReplay() and #sounds == played)
voiceEvent(nil, 'QUEST_DETAIL')
assert(V.CanReplay() and #due == 0, 'native event must not reset manually prepared playback')
V.Resume(); assert(#sounds > played, 'manual NPC Reader Play must still speak')
B.panel:Hide(); assert(not V.talkerFrame:IsShown() and not V.CanReplay())
B.SetNpcReaderAutoOpen(true); B.SetQuestVoiceAutoPlay(true)
due = {}; played = #sounds
voiceEvent(nil, 'QUEST_DETAIL'); B.readCurrentQuest()
assert(B.panel:IsShown() and V.talkerFrame:IsShown() and #due == 1,
  'NPC auto-open plus autoplay must schedule exactly one start through Reader render')
voiceEvent(nil, 'QUEST_DETAIL'); assert(#due == 1)
table.remove(due, 1)(); assert(#sounds > played)
B.panel:Hide()
print('npc Reader voice: hidden reader stays silent; manual ready/play; opt-in auto-open and single autoplay: ok')
