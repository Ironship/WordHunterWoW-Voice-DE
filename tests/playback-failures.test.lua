-- lua5.1 tests/playback-failures.test.lua [engine-root] [host-mode] [ctimer|fallback] [word|next|all]
-- Defaults run the local engine. Optional host modes use real carrier copies.
local root,mode,timer,which=arg[1] or '.',arg[2] or 'local',arg[3] or 'ctimer',arg[4] or 'all'
local dictionary,classic='WordHunterWoW-Dictionary-DE','WordHunterWoW-Voice-DE-Classic'
local hosts={localhost={'WordHunterWoW-Voice-DE'},['dictionary-first']={dictionary,classic},
  ['classic-first']={classic,dictionary},['dictionary-only']={dictionary},['classic-only']={classic}}
local order=assert(hosts[mode=='local' and 'localhost' or mode],'unknown host mode')
local frames,asked,stops,pending,active,nextHandle={},{},{},{},{},0
local function frame(kind,parent)
  local f={kind=kind,parent=parent,shown=true,points={}}
  frames[#frames+1]=f
  function f:SetSize(w,h) self.w,self.h=w,h end
  function f:SetScale(s) self.scale=s end
  function f:SetPoint(...) self.points[#self.points+1]={...} end
  function f:ClearAllPoints() self.points={} end
  function f:SetAllPoints() end
  function f:SetScript(event,fn) self[event]=fn end
  function f:Show() self.shown=true end
  function f:Hide() self.shown=false end
  function f:IsShown() return self.shown end
  function f:IsVisible() return self.shown and (not self.parent or self.parent:IsVisible()) end
  function f:SetText(text) self.text=text end
  function f:SetTexture(path) self.texture=path end
  function f:CreateTexture() return frame('Texture',self) end
  function f:CreateFontString() return frame('FontString',self) end
  for _,name in ipairs({'SetFrameStrata','SetClampedToScreen','SetMovable','EnableMouse','RegisterForDrag',
    'StartMoving','StopMovingOrSizing','RegisterEvent','SetBackdrop','SetHighlightTexture','SetTextColor',
    'SetJustifyH','SetWordWrap','SetTexCoord','SetVertexColor'}) do f[name]=function() end end
  return f
end
UIParent=frame('Frame')
CreateFrame=function(kind,_,parent) return frame(kind,parent) end
GameTooltip={SetOwner=function() end,SetText=function(self,text) self.text=text end,
  Show=function() end,Hide=function() end}
UnitExists=function() return false end
WordHunterWoWVoiceDB={enabled=true,words=true,talker=true,sentenceGap=0.25}
local exists={}
PlaySoundFile=function(path)
  asked[#asked+1]=path
  if not exists[path] then return false end
  nextHandle=nextHandle+1;active[nextHandle]=path
  return true,nextHandle
end
StopSound=function(handle) stops[#stops+1]=handle;active[handle]=nil end
C_Timer=timer=='ctimer' and {After=function(_,action) pending[#pending+1]=action end} or nil
for _,host in ipairs(order) do
  for _,name in ipairs({'Naming.lua','Talker.lua','Voice.lua','PlayButtons.lua','Settings.lua'}) do
    assert(loadfile(root..'/'..(mode=='local' and '' or host..'/')..name))(host)
  end
end
local V=assert(WordHunterWoW_Voice)
assert(V.host==order[1],'wrong active host')
local questPack,wordPack='QuestPack','WordPack'
WordHunterWoW_Voice_Parts={
  [questPack]={quests={1,1000},lengths='40 o 100,100,100\n'},[wordPack]={words=true},
}
V.ForgetParts()
local clips={}
for i=1,3 do clips[i]='Interface\\AddOns\\'..questPack..'\\'..V.QuestPath(40,'description',i);exists[clips[i]]=true end
local wordPath='Interface\\AddOns\\'..wordPack..'\\'..V.WordPath('zuflucht')
exists[wordPath]=true
local function fire()
  if #pending>0 then table.remove(pending,1)();return true end
  for _,f in ipairs(frames) do if f.OnUpdate then f.OnUpdate(f,60);return true end end
  return false
end
local function drain()
  local n=0
  while fire() do n=n+1;assert(n<100,'timer loop') end
end
local buttons={}
V.BuildTalker()
for _,f in ipairs(frames) do
  if f.kind=='Button' and f.OnEnter then f.OnEnter(f);buttons[GameTooltip.text]=f end
end
local close=assert(buttons['Vorlesen stoppen und schließen'])
local play=assert(buttons['Vorlesen fortsetzen'])
local pause=assert(buttons['Vorlesen pausieren'])
if which=='word' or which=='all' then
  assert(V.PlayQuest(40,'description'))
  local handle,beforeStops=nextHandle,#stops
  assert(not V.PlayWord('unrecordedword'))
  assert(#stops==beforeStops and active[handle]==clips[1],
    'MISSING WORD CUTS QUEST: failed word lookup must leave the active quest handle alone')
  assert(V.CanReplay() and not V.IsPaused() and pause:IsVisible(),'missing word changed quest transport state')
  assert(fire() and asked[#asked]==clips[2],'missing word changed the scheduled quest continuation')
  local questHandle=nextHandle
  assert(V.PlayWord('Zuflucht'),'existing word should still play')
  assert(stops[#stops]==questHandle and active[nextHandle]==wordPath,'existing word no longer interrupts the old clip')
  V.Stop();drain()
  assert(V.PlayWord('Zuflucht'))
  handle,beforeStops=nextHandle,#stops
  assert(not V.PlayWord('unrecordedword'))
  assert(#stops==beforeStops and active[handle]==wordPath,'missing word cut unrelated active word audio')
  WordHunterWoW_Voice_Parts[wordPack]=nil;V.ForgetParts()
  local beforeAsk=#asked
  assert(not V.PlayWord('Zuflucht') and #asked==beforeAsk and active[handle]==wordPath,
    'absent word owner should not ask for or stop any audio')
  V.Stop()
  WordHunterWoW_Voice_Parts[wordPack]={words=true};V.ForgetParts()
  print('missing word: quest and unrelated audio survive; existing word still interrupts; absent owner is silent')
end
if which=='next' or which=='all' then
  exists[clips[2]]=nil
  assert(V.PlayQuest(40,'description'))
  local handle=nextHandle
  assert(fire(),'missing next clip was not attempted')
  assert(V.IsPaused() and V.CanReplay() and play:IsVisible() and not pause:IsVisible(),
    'FAILED NEXT CLIP STUCK READING: a failed continuation must pause with retry and close available')
  assert(not active[handle] and close:IsVisible(),'failure left current handle playing or hid close')
  local beforeAsk=#asked
  drain()
  assert(#asked==beforeAsk,'a failed continuation resurrected another clip')
  exists[clips[2]]=true
  assert(V.Resume() and asked[#asked]==clips[1],'retry should repeat the last successfully read sentence')
  drain()
  assert(V.CanReplay() and not V.IsPaused() and play:IsVisible(),'recovered passage did not finish normally')
  assert(V.Replay() and asked[#asked]==clips[1],'replay became unreachable after recovery')
  close.OnClick(close);beforeAsk=#asked;drain()
  assert(#asked==beforeAsk and not V.CanReplay() and not V.talkerFrame:IsVisible(),'X failed after recovered replay')
  print('failed next: coherent pause, no timers/sound resurrection, retry/replay and X remain usable')
end
print('playback-failures: '..V.host..' '..mode..' '..timer..' '..which..': ok')
