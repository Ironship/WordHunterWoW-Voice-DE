-- Run from the voice root: lua5.1 tests/talker-reading-dim.test.lua [base root]
local baseRoot = arg[1] or "../WordHunterWoW"
dofile(baseRoot .. "/tests/wowstub.lua")
dofile(baseRoot .. "/Core.lua")
WordHunterWoWDB = { settings = { readingMode = true, frames = {} }, words = {} }
local base = WordHunterWoW_Addon
local panelShown = true
base.panel = { IsShown = function() return panelShown end }

-- Dispatch the client's OnShow transition; the shared stub only stores hooks.
local create = CreateFrame
CreateFrame = function(kind, name, parent, template)
  local f = create(kind, name, parent, template)
  if name == "WordHunterWoWVoiceTalker" then
    local show = f.Show
    function f:Show()
      local wasShown = self:IsShown()
      show(self)
      local onShow = self:GetScript("OnShow")
      if not wasShown and onShow then onShow(self) end
    end
  end
  return f
end

base.ApplyReadingDim()
assert(base.readingDim:IsShown(), "the dim must already be up")
assert(WordHunterWoWVoiceTalker == nil, "the talker must not yet exist")
dofile("Naming.lua")
dofile("Talker.lua")
local voice = WordHunterWoW_Voice
voice.ShowTalker("Werkzeuge", nil, "Satz 1 von 3")
local talker = voice.talkerFrame
assert(talker:GetFrameStrata() == "FULLSCREEN_DIALOG",
  "lazy talker must be above the already visible FULLSCREEN dim")
assert(talker:GetFrameLevel() == 10, "talker uses the base dim lift level")
voice.RestTalker()
assert(talker:GetFrameStrata() == "FULLSCREEN_DIALOG", "finished talker stays bright")
voice.HideTalker()
voice.ShowTalker("Werkzeuge", nil, "Satz 2 von 3")
assert(talker:GetFrameStrata() == "FULLSCREEN_DIALOG", "reopen stays bright")

panelShown = false
base.ApplyReadingDim()
assert(not base.readingDim:IsShown(), "closing the reader removes the dim")
assert(talker:GetFrameStrata() == "HIGH" and talker:GetFrameLevel() == 0,
  "repeated OnShow must preserve the original talker strata and level")
voice.HideTalker()
voice.ShowTalker("Werkzeuge", nil, "")
assert(talker:GetFrameStrata() == "HIGH", "closed reader must not lift audio")
panelShown = true
base.ApplyReadingDim()
assert(talker:GetFrameStrata() == "FULLSCREEN_DIALOG", "existing talker is also lifted")
WordHunterWoWDB.settings.readingMode = false
base.ApplyReadingDim()
assert(talker:GetFrameStrata() == "HIGH", "reading mode off restores audio")
print("talker-reading-dim: lazy show, reopen, finished state and restore OK")
