-- lua5.1 tests/catalog-missing-word.test.lua [base-root] [engine-root] [host-mode]
-- A real reader token/editor hook must not interrupt a quest for missing audio.
local baseRoot,engineRoot,mode=arg[1] or '../WordHunterWoW',arg[2] or '.',arg[3] or 'local'
dofile(baseRoot..'/tests/wowstub.lua')
local create=CreateFrame
CreateFrame=function(kind,name,parent,template)
  local f=create(kind,name,parent,template)
  local children={}
  f._testChildren=children
  if parent and rawget(parent,'_testChildren') then table.insert(parent._testChildren,f) end
  function f:GetChildren() return unpack(children) end
  function f:GetTop()
    local points=rawget(self,'_points') or {}
    local p=points.TOPLEFT or points.TOPRIGHT or points.TOP
    return (parent and parent.GetTop and parent:GetTop() or 1000)+(p and p.y or 0)
  end
  function f:GetLeft()
    local points=rawget(self,'_points') or {}
    local p=points.TOPLEFT or points.BOTTOMLEFT or points.LEFT
    return (parent and parent.GetLeft and parent:GetLeft() or 0)+(p and p.x or 0)
  end
  return f
end
GetBuildInfo=function() return '1.60.1','','',16001 end
for _,name in ipairs({'Core.lua','Compat.lua','UICommon.lua','Recall.lua','QuestPanel.lua',
  'WordList.lua','Editor.lua','QuestBrowser.lua','QuestReader.lua'}) do dofile(baseRoot..'/'..name) end
local B=WordHunterWoW_Addon
WordHunterWoWDB={settings={targetLocale='deDE',frames={},integratedLayout=false},wordsByLocale={}}
B.initializeDatabase()
WordHunterWoW_QuestDataByFlavor={forever={deDE={[40]={title='Testauftrag',description='Unrecordedword wartet.'}}}}
C_QuestLog,GetQuestLogQuestText=nil,nil
SelectQuestLogEntry=function() error('catalog must not change selected live quest') end
WordHunterWoWVoiceDB={enabled=true,words=true}
local dictionary,classic='WordHunterWoW-Dictionary-DE','WordHunterWoW-Voice-DE-Classic'
local orders={['local']={'WordHunterWoW-Voice-DE'},['dictionary-first']={dictionary,classic},
  ['classic-first']={classic,dictionary},['dictionary-only']={dictionary},['classic-only']={classic}}
for _,host in ipairs(assert(orders[mode])) do
  for _,name in ipairs({'Naming.lua','Talker.lua','Voice.lua','PlayButtons.lua','Settings.lua'}) do
    assert(loadfile(engineRoot..'/'..(mode=='local' and '' or host..'/')..name))(host)
  end
end
local V=WordHunterWoW_Voice
WordHunterWoW_Voice_Parts={AudioTest={quests={1,100},words=true,lengths='40 o 100,100\n'}}
V.ForgetParts()
local sounds,stops,pending,active={}, {}, {}, nil
C_Timer={After=function(_,fn) pending[#pending+1]=fn end}
PlaySoundFile=function(path)
  if path:find('\\w\\',1,true) then return false end
  sounds[#sounds+1]=path;active=#sounds
  return true,active
end
StopSound=function(handle) stops[#stops+1]=handle;if active==handle then active=nil end end
B.createPanel();B.createEditor();V.HookBaseAddon();V.HookQuestPanel()
assert(B.OpenCatalogQuest(40,'deDE') and V.PlayQuest(40,'description'))
local handle,beforeStops=active,#stops
local token
for _,button in ipairs(B.panel.wordButtons) do if button:IsShown() and button.word=='Unrecordedword' then token=button end end
assert(token,'real reader token absent')
token:GetScript('OnClick')(token,'LeftButton')
assert(B.editor:IsShown() and B.selected.locale=='deDE','actual editor path not reached')
assert(#stops==beforeStops and active==handle,
  'MISSING WORD EDITOR CUTS QUEST: reader token must open the editor without silencing the quest')
assert(V.CanReplay() and not V.IsPaused(),'missing word editor click changed quest transport state')
table.remove(pending,1)()
assert(sounds[#sounds]:find('40_o2',1,true),'missing word editor click changed the next quest clip')
V.Stop()
print('catalog-missing-word: '..V.host..' '..mode..', real token/editor hook preserves active quest and continuation: ok')
