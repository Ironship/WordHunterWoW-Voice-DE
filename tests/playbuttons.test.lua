-- Run from the addon root:  lua tests/playbuttons.test.lua
--
-- A play button beside every paragraph the pack can read aloud.
--
-- The interesting cases are the ones where nothing should appear. A button that
-- plays nothing turns "this quest has no audio yet" -- which is true, and will
-- stay true for most of the game for a while -- into "this addon is broken". So
-- most of what is checked here is restraint.
--
-- The second half checks the join to QuestWordHunter, and it is here because
-- everything in the first half passed while not one button was ever drawn in
-- the game. This side was right in every particular; the callback it hangs off
-- was never called, and nothing on this side could have told the difference. A
-- check of one end of a join says nothing about the join.
--
-- That half runs in a second copy of this file, started as a child process. The
-- two halves need incompatible worlds -- one where a frame is a hand-written
-- stub whose every answer is known, one where a frame answers to anything so
-- that the real panel code will run at all -- and in a shared Lua state the
-- second half is handed buttons the first half pooled, which is how a check
-- comes to pass for a reason nobody intended. A second process is cheap; that
-- is not.

local mode = ...

-- A passage of four sentences. The first two are short enough to be joined into
-- one clip, so clip two does not start at sentence two -- which is exactly the
-- case a naive "one button per sentence" would get wrong. Where it does start is
-- asked of the grouping rather than written down: the two halves split the text
-- with different splitters, the hand-written one here and the addon's own in the
-- child, and each has to agree with itself rather than with this comment.
local TEXT = "Kurz eins. Kurz zwei. "
  .. "Dies ist ein deutlich laengerer Satz, der fuer sich allein steht und nicht angehaengt wird. "
  .. "Und noch ein ebenso langer Satz, damit auch dieser ein eigener Klang wird."

local QUEST_ID = 25152
local PACK = {
  ["WordHunterWoW-Voice-DE-Cataclysm"] = { quests = { 14621, 29377 }, lengths = "25152 o 210,340,190\n" },
}

if mode == "join" then
  local BASE = "../WordHunterWoW"
  local probe = io.open(BASE .. "/QuestPanel.lua", "rb")
  assert(probe, "no QuestWordHunter checkout at " .. BASE
    .. " -- the join is what this half exists to check, so its absence is a failure, not a skip")
  probe:close()

  -- The base addon's own stub, so the real panel code runs against exactly what
  -- its own tests run against. Frames there answer to anything and invent a
  -- child frame for any field asked of them, which is what lets the whole
  -- layout run outside the client at all.
  dofile(BASE .. "/tests/wowstub.lua")
  PlaySoundFile = function() return false end
  StopSound = function() end

  -- That stub invents a frame for any global whose name begins WordHunterWoW,
  -- because the client makes one for every named frame and every template child
  -- and the panel code looks them up again by name. This addon's globals begin
  -- with the same letters, and a frame answers every field with another frame:
  -- WordHunterWoW_Voice.panelHooked came back a frame, HookQuestPanel read it
  -- as "already done" and installed nothing, in a process where it had never
  -- run once. So this addon's own names stay plain, and anything it needs is
  -- written out below.
  local invented = getmetatable(_G).__index
  setmetatable(_G, {
    __index = function(globals, key)
      if type(key) == "string" and key:find("^WordHunterWoW_?Voice") then return nil end
      return invented(globals, key)
    end,
  })

  -- What the play buttons need that a frame answering to anything cannot
  -- supply: which children a frame has, where each one sits, how big it is,
  -- which level it draws at, what a scroll frame does to its child, and what a
  -- hook does to a script. All of it is taken from what the panel actually does
  -- -- the parent it hands a frame at creation, the points it anchors it with --
  -- rather than being posted in, so a panel that laid its tokens out differently
  -- would be seen doing it.
  --
  -- Positions are resolved rather than recorded. The panel anchors a token to
  -- its content, the content to the scroll frame and the scroll frame to the
  -- window, so asking whether a button covers a word means walking that chain
  -- the way the client does. This file used to keep a made-up screen position
  -- per frame instead -- "200 plus whatever x was" -- which is enough to sort
  -- tokens into lines and useless for comparing two frames anchored to different
  -- things. That is how a button drawn across a word passed every check here.
  local plainFrame = CreateFrame
  local unpack = unpack or table.unpack
  local everyFrame = {}

  -- Where a named point sits in a frame's own rectangle, 0..1. Anything not
  -- listed -- CENTER, and the middle of an edge -- is halfway.
  local ACROSS = { LEFT = 0, RIGHT = 1, TOPLEFT = 0, TOPRIGHT = 1, BOTTOMLEFT = 0, BOTTOMRIGHT = 1 }
  local UP = { BOTTOM = 0, TOP = 1, BOTTOMLEFT = 0, BOTTOMRIGHT = 0, TOPLEFT = 1, TOPRIGHT = 1 }

  local rect
  local function anchorOf(frame, point)
    local r = rect(frame)
    return r.left + (r.right - r.left) * (ACROSS[point] or 0.5),
      r.bottom + (r.top - r.bottom) * (UP[point] or 0.5)
  end

  -- A frame's rectangle in screen coordinates, which run up from the bottom.
  -- Each point pins one edge across and one edge up; two opposite points give a
  -- size, one point plus a size gives the rest, and a frame anchored to nothing
  -- sits in the bottom-left corner -- which is where the screen itself is.
  function rect(frame)
    local left, right, top, bottom, middleX, middleY
    for _, point in ipairs(rawget(frame, "anchors") or {}) do
      local relative = point.relativeTo or rawget(frame, "parent")
      local x, y = 0, 0
      if relative then x, y = anchorOf(relative, point.relativePoint) end
      x, y = x + point.x, y + point.y
      local across, up = ACROSS[point.point], UP[point.point]
      if across == 0 then left = x elseif across == 1 then right = x else middleX = x end
      if up == 0 then bottom = y elseif up == 1 then top = y else middleY = y end
    end
    local width = (left and right) and (right - left) or frame:GetWidth()
    local height = (top and bottom) and (top - bottom) or frame:GetHeight()
    left = left or (right and right - width) or (middleX and middleX - width / 2) or 0
    bottom = bottom or (top and top - height) or (middleY and middleY - height / 2) or 0
    return { left = left, bottom = bottom, right = left + width, top = bottom + height }
  end

  CreateFrame = function(kind, name, parent, template)
    local f = plainFrame(kind, name, parent, template)
    rawset(f, "kids", {})
    rawset(f, "anchors", {})
    rawset(f, "parent", parent)
    function f:GetChildren() return unpack(self.kids) end
    function f:GetParent() return rawget(self, "parent") end
    -- SetPoint leaves out the relative frame, the relative point, both, or
    -- neither. The panel uses every one of those shapes.
    function f:SetPoint(point, a, b, c, d)
      local relativeTo, relativePoint, x, y
      if type(b) == "string" then
        relativeTo, relativePoint, x, y = a, b, c, d
      elseif type(a) == "number" or a == nil then
        x, y = a, b
      else
        relativeTo, x, y = a, b, c
      end
      rawset(self, "anchoredTo", relativeTo)
      local anchors = rawget(self, "anchors")
      anchors[#anchors + 1] = {
        point = point,
        relativeTo = relativeTo,
        relativePoint = relativePoint or point,
        x = x or 0,
        y = y or 0,
      }
    end
    function f:ClearAllPoints() rawset(self, "anchors", {}) end
    function f:GetLeft() return rect(self).left end
    function f:GetRight() return rect(self).right end
    function f:GetTop() return rect(self).top end
    function f:GetBottom() return rect(self).bottom end
    -- A scroll frame holds its child at its own top-left, and scrolling moves
    -- the child rather than the frame. That is the whole of what a play button
    -- has to keep up with, and the only reason it is modelled here.
    function f:SetScrollChild(child)
      rawset(self, "scrollChild", child)
      self:SetVerticalScroll(self:GetVerticalScroll())
    end
    function f:GetVerticalScroll() return rawget(self, "vscroll") or 0 end
    function f:SetVerticalScroll(value)
      value = value or 0
      rawset(self, "vscroll", value)
      local child = rawget(self, "scrollChild")
      if child then
        child:ClearAllPoints()
        child:SetPoint("TOPLEFT", self, "TOPLEFT", 0, value)
      end
      local handler = self:GetScript("OnVerticalScroll")
      if handler then handler(self, value) end
    end
    -- A frame draws one level above its parent unless it says otherwise, and
    -- inherits its strata. Between them they decide whether a button is drawn
    -- over a word or under it.
    function f:SetFrameLevel(value) rawset(self, "level", value) end
    function f:GetFrameLevel()
      local own = rawget(self, "level")
      if own then return own end
      local up = rawget(self, "parent")
      return up and (up:GetFrameLevel() + 1) or 0
    end
    function f:SetFrameStrata(value) rawset(self, "strata", value) end
    function f:GetFrameStrata()
      local own = rawget(self, "strata")
      if own then return own end
      local up = rawget(self, "parent")
      return up and up:GetFrameStrata() or "MEDIUM"
    end
    function f:SetClipsChildren(value) rawset(self, "clipsChildren", value and true or false) end
    -- A hook runs after whatever was there and leaves it in place. The shared
    -- stub replaces instead, which would let a hook that quietly took the scroll
    -- frame's own handler away look like a hook that behaved.
    function f:HookScript(script, fn)
      local previous = self.scripts[script]
      self.scripts[script] = previous and function(...) previous(...) return fn(...) end or fn
    end
    if parent and rawget(parent, "kids") then
      local kids = parent.kids
      kids[#kids + 1] = f
    end
    everyFrame[#everyFrame + 1] = f
    return f
  end

  -- Every window in the client is anchored to this one in the end, so the chain
  -- a rectangle is resolved along has to finish somewhere real.
  UIParent = CreateFrame("Frame")
  UIParent:SetSize(1024, 768)

  dofile(BASE .. "/Core.lua")
  dofile(BASE .. "/Compat.lua")
  dofile(BASE .. "/UICommon.lua")
  dofile(BASE .. "/QuestPanel.lua")

  -- Set before the addon that reads them loads, not after: a frame standing in
  -- for the settings would have made every option quietly true.
  WordHunterWoWDB = { settings = { targetLocale = "deDE", frames = {} }, words = {}, wordsByLocale = {} }
  WordHunterWoWVoiceDB = { enabled = true }
  WordHunterWoW_Voice_Parts = PACK

  dofile("Naming.lua")
  dofile("Talker.lua")
  dofile("Voice.lua")
  dofile("PlayButtons.lua")
  local Base = WordHunterWoW_Addon
  local Addon = WordHunterWoW_Voice
  Addon.ForgetParts()

  Base.initializeDatabase()
  Base.createPanel()
  QuestFrame:Show()
  GetQuestID = function() return QUEST_ID end
  GetTitleText = function() return "Ein Test" end
  GetQuestText = function() return TEXT end
  GetObjectiveText = function() return "" end
  GetProgressText = function() return "" end
  GetRewardText = function() return "" end

  -- Somebody already listening when this addon arrives. Nothing else ships a
  -- listener today, but the callback is one field on a shared table: an addon
  -- that claims it without looking takes it off whoever had it, and the addon
  -- that loses it never finds out.
  local order = {}
  Base.OnQuestPanelRendered = function() order[#order + 1] = "the listener already there" end
  local before = Base.OnQuestPanelRendered

  Addon.HookQuestPanel()
  assert(Base.OnQuestPanelRendered ~= before,
    "HookQuestPanel left the callback exactly as it found it -- nothing was installed")
  -- ADDON_LOADED fires once per addon and every one of them reaches the handler
  -- that calls this, so hooking twice is the normal case, not a corner.
  Addon.HookQuestPanel()

  local drawn
  local handed
  local placeForReal = Addon.PlacePlayButtons
  Addon.PlacePlayButtons = function(quest, panel)
    order[#order + 1] = "the play buttons"
    handed = { quest = quest, panel = panel }
    drawn = placeForReal(quest, panel)
    return drawn
  end

  Base.readCurrentQuest()

  assert(#order > 0, "a full refresh of QuestWordHunter's panel called nothing back."
    .. " Look for the OnQuestPanelRendered call at the end of refreshPanel in "
    .. BASE .. "/QuestPanel.lua -- and for whether the copy in the client is the same file")
  assert(order[1] == "the listener already there",
    "the listener that was there first did not run, or did not run first")
  assert(order[2] == "the play buttons" and #order == 2,
    "expected the earlier listener and then the play buttons, got " .. #order .. " calls")

  assert(handed.quest == Base.lastQuest, "the callback was handed a quest that is not the one drawn")
  assert(handed.panel == Base.panel, "the callback was handed something other than the panel")
  assert(handed.panel.content, "the panel handed over has no content frame to draw into")
  assert(handed.quest.passage == "offer" and handed.quest.text == TEXT,
    "the panel drew something other than the fixture, so the pack lengths do not describe it: "
    .. tostring(handed.quest.passage))

  -- And the buttons themselves, off the panel's own tokens rather than off
  -- tokens made here for the purpose.
  local spans = Addon.ClipSpans(Base.lastQuest.text)
  assert(spans and #spans >= 2, "the passage did not group into at least two clips")
  assert(drawn and drawn >= 2,
    "the refresh reached this addon but drew " .. tostring(drawn) .. " buttons, not the clips it has")

  local byClip = {}
  for _, f in ipairs(everyFrame) do
    local clip = rawget(f, "clip")
    if clip then byClip[clip] = f end
  end
  assert(byClip[1] and byClip[2], "the buttons drawn did not record which clip they play")
  local anchor = rawget(byClip[2], "anchoredTo")
  assert(anchor, "clip two's button was not hung off any token")
  assert(rawget(anchor, "sentenceIndex") == spans[2].first,
    "clip two's button landed on sentence " .. tostring(rawget(anchor, "sentenceIndex"))
    .. " but its clip starts at " .. spans[2].first
    .. " -- the two sides are numbering sentences differently")
  print("  the panel's own refresh reaches the buttons, and they land on its own tokens")

  -- And now where they landed, measured against the panel's own words.
  --
  -- This is the half the shipped bug walked straight through. Every check above
  -- passed while each button was drawn across the word in front of the one it
  -- plays from, because nothing here had ever asked where a button was, only
  -- what it was hung off.
  local function buttonsOnScreen()
    local found = {}
    for _, f in ipairs(everyFrame) do
      local clip = rawget(f, "clip")
      if clip and f:IsShown() then found[clip] = f end
    end
    return found
  end

  -- Both columns. The gutter runs down the side of the German text, and in the
  -- two-column layout what is on the other side of it is the English pane.
  --
  -- Every shown child, not the ones carrying a sentence number: a token the
  -- panel could not place in a sentence is still a word on the screen, and a
  -- filter that let those through would be a hole in the shape of the tokens
  -- least likely to have been thought about. The buttons hang off the gutter
  -- rather than off the content, so nothing of ours is in here.
  local function wordsOnScreen()
    local found = {}
    local function collect(holder)
      for _, token in ipairs({ holder:GetChildren() }) do
        if token:IsShown() then found[#found + 1] = token end
      end
    end
    collect(Base.panel.content)
    if Base.panel.enScroll:IsShown() then collect(Base.panel.enContent) end
    return found
  end

  local function overlaps(one, other)
    return one:GetLeft() < other:GetRight() - 0.01 and other:GetLeft() < one:GetRight() - 0.01
      and one:GetBottom() < other:GetTop() - 0.01 and other:GetBottom() < one:GetTop() - 0.01
  end

  local function checkPlacement(layout)
    local panel, content, scroll = Base.panel, Base.panel.content, Base.panel.scroll
    local buttons, words = buttonsOnScreen(), wordsOnScreen()
    assert(buttons[1] and buttons[2], layout .. ": no buttons on screen to check")
    assert(#words > 8, layout .. ": the panel laid out " .. #words
      .. " words, which is too few for a collision to be possible either way")
    for clip, button in pairs(buttons) do
      local which = layout .. ": clip " .. clip .. "'s button"
      for _, word in ipairs(words) do
        assert(not overlaps(button, word), which .. " is drawn over the word \""
          .. tostring(word.text and word.text:GetText()) .. "\"")
      end
      -- Nor over each other. The gutter is one button wide, so two clips that
      -- start on the same line are the same collision in a different place.
      for other, another in pairs(buttons) do
        assert(other == clip or not overlaps(button, another),
          which .. " is drawn over clip " .. other .. "'s")
      end
      -- Clear of the column, and not merely of the words this fixture happens to
      -- put there: the next quest wraps its lines somewhere else entirely.
      assert(button:GetRight() <= content:GetLeft() + 0.01, which .. " reaches into the text column")
      assert(button:GetLeft() >= panel:GetLeft() - 0.01, which .. " hangs off the edge of the window")
      -- In front of the words rather than behind them. Drawn behind, the button
      -- showed through the letters as a smudge on the word.
      assert(button:GetFrameStrata() == words[1]:GetFrameStrata(),
        which .. " is in a different strata from the text, so its level decides nothing")
      assert(button:GetFrameLevel() > words[1]:GetFrameLevel(),
        which .. " draws at level " .. button:GetFrameLevel()
        .. ", under the text at " .. words[1]:GetFrameLevel())
      -- On the line its clip starts, or a whole number of lines below it when
      -- another clip started on the same one and took the slot.
      local token = rawget(button, "anchoredTo")
      local step = token:GetHeight()
      local lines = ((token:GetTop() - step / 2) - (button:GetTop() + button:GetBottom()) / 2) / step
      assert(lines > -0.01 and math.abs(lines - math.floor(lines + 0.5)) < 0.01,
        which .. " sits " .. string.format("%.2f", lines)
        .. " lines from the line its clip starts on")
    end

    local strip = buttons[1]:GetParent()
    assert(rawget(strip, "clipsChildren"), layout .. ": the gutter does not clip what it holds")
    assert(strip:GetTop() <= scroll:GetTop() + 0.01 and strip:GetBottom() >= scroll:GetBottom() - 0.01,
      layout .. ": the gutter stands taller than the pane it runs beside")

    -- Scrolling takes the words with it, and the buttons hang off the words.
    -- Nothing calls this addon back on a scroll, so where a button goes when its
    -- line leaves the pane is worth asking rather than assuming: drawn outside
    -- the scroll frame, it is not clipped away with the text.
    local first = buttons[1]
    scroll:SetVerticalScroll(scroll:GetTop() - scroll:GetBottom() + 40)
    assert(not first:IsShown(),
      layout .. ": a button stayed on screen after its line was scrolled out of the pane")
    scroll:SetVerticalScroll(0)
    assert(first:IsShown(), layout .. ": the button did not come back when its line did")
  end

  checkPlacement("two columns")
  print("  no button is drawn over a word, and they draw in front of the text")

  -- Once is not a join. The panel refreshes on every saved word and every
  -- resize, and a callback installed over the top of another one is exactly the
  -- kind of thing that works the first time.
  order, drawn = {}, nil
  Base.refreshPanel()
  assert(#order == 2 and order[1] == "the listener already there" and order[2] == "the play buttons",
    "a later refresh reached " .. #order .. " listeners rather than both")
  assert(drawn and drawn >= 2, "a later refresh drew " .. tostring(drawn) .. " buttons")
  print("  a later refresh reaches both listeners again")

  -- And the same again with the English column switched off, which is the layout
  -- that leaves the least room beside the text: 18px between the window's edge
  -- and the first word, and no channel between two panes to borrow from.
  drawn = nil
  Base.SetIntegratedLayout(false)
  assert(drawn and drawn >= 2,
    "switching to one column drew " .. tostring(drawn) .. " buttons")
  checkPlacement("one column")
  print("  and the same with the English column switched off")

  -- A passage whose second clip starts on the line the first one is still on.
  -- It happens to one clip in twenty at the panel's own width and one in four
  -- when it is dragged wide, and a gutter one button across has room for only
  -- one of them. Which line each clip starts on is asked of the panel rather
  -- than counted here: the sentence is short enough to reach the thirty
  -- characters that close a clip without filling a line, and the panel is what
  -- decides where that leaves the sentence after it.
  drawn = nil
  GetQuestText = function()
    return "Ausgezeichnete Handwerkskunst hierzulande. "
      .. "Wir brauchen dringend mehr Verstaerkung an der Grenze im Norden."
  end
  Base.readCurrentQuest()
  local crowded = Addon.ClipSpans(Base.lastQuest.text)
  assert(crowded and #crowded == 2, "the crowded fixture did not group into two clips")
  -- Shown ones only. The panel pools its tokens, so the frames past the end of a
  -- shorter passage keep the sentence numbers they were given for a longer one.
  local firstLine = {}
  for _, token in ipairs({ Base.panel.content:GetChildren() }) do
    local sentence = token:IsShown() and rawget(token, "sentenceIndex")
    for i, span in ipairs(crowded) do
      if sentence == span.first and not firstLine[i] then firstLine[i] = token:GetTop() end
    end
  end
  assert(firstLine[1] and firstLine[1] == firstLine[2],
    "the crowded fixture no longer starts two clips on one line, so it checks nothing"
    .. " -- the panel wrapped it at " .. tostring(firstLine[1]) .. " and " .. tostring(firstLine[2]))
  assert(drawn == 2, "the crowded fixture drew " .. tostring(drawn) .. " buttons")
  checkPlacement("two clips on one line")
  local crowdedButtons = buttonsOnScreen()
  assert(crowdedButtons[1]:GetTop() > crowdedButtons[2]:GetTop() + 0.01,
    "both buttons stayed on the same line, so one is sitting on the other")
  print("  two clips starting on one line get a line each")

  print("playbuttons join: ok")
  os.exit(0)
end

local made = {}
local function stub(kind)
  -- Where a frame is defaults to zero rather than to nothing. The placement
  -- measures its gutter off the window and declines to draw against a frame that
  -- cannot say where it is, so a nil here would turn every count below into a
  -- zero for a reason that has nothing to do with what is being checked. Which
  -- numbers they are does not matter: this half is about which clips get a
  -- button at all, and the join half is where a position is compared with the
  -- real panel's own.
  local f = { kind = kind, shown = false, children = {}, points = {}, left = 0, right = 0 }
  function f:SetSize() end
  function f:SetWidth() end
  function f:SetPoint(...) self.points = { ... } end
  function f:ClearAllPoints() self.points = {} end
  function f:SetParent(p) self.parent = p end
  function f:GetParent() return self.parent end
  function f:SetNormalTexture() end
  function f:GetNormalTexture() return nil end
  function f:SetHighlightTexture() end
  function f:SetScript(name, fn) self["on" .. name] = fn end
  function f:HookScript(name, fn) self["on" .. name] = fn end
  function f:Show() self.shown = true end
  function f:Hide() self.shown = false end
  function f:IsShown() return self.shown end
  -- Lua 5.4 moved unpack into table; the game runs 5.1, where it is global.
  local unpack = unpack or table.unpack
  function f:GetChildren() return unpack(self.children) end
  function f:GetTop() return self.top end
  function f:GetLeft() return self.left end
  function f:GetRight() return self.right end
  function f:GetBottom() return self.bottom end
  function f:GetHeight() return self.height end
  -- The gutter draws above the text and clips what it holds; both are checked
  -- against the real panel in the join half, and here they only have to answer.
  function f:SetFrameLevel() end
  function f:GetFrameLevel() return 0 end
  function f:SetClipsChildren() end
  function f:RegisterEvent() end
  function f:CreateFontString() return stub("fontstring") end
  function f:CreateTexture() return stub("texture") end
  function f:SetText() end
  function f:SetJustifyH() end
  function f:SetWordWrap() end
  function f:SetTexCoord() end
  -- Playing a clip also raises the frame that shows who is talking.
  function f:SetFrameStrata() end
  function f:SetClampedToScreen() end
  function f:SetMovable() end
  function f:EnableMouse() end
  function f:RegisterForDrag() end
  function f:SetBackdrop() end
  function f:SetTexture() end
  -- Clicking a button plays a clip, which raises the talker, which builds its
  -- artwork. None of that is measured here -- tests/talker.test.lua owns it --
  -- but it all has to run, so the decoration it applies has to answer.
  function f:SetAllPoints() end
  function f:SetVertexColor() end
  function f:SetTextColor() end
  function f:SetUnit() end
  function f:GetPoint() return "BOTTOM", nil, "BOTTOM", 0, 210 end
  made[#made + 1] = f
  return f
end
CreateFrame = function(kind, _, parent)
  local f = stub(kind)
  if parent and parent.children then parent.children[#parent.children + 1] = f end
  return f
end

local played = {}
PlaySoundFile = function(path) played[#played + 1] = path; return true, #played end
StopSound = function() end
UIParent = stub("frame")

-- Enough of the base addon for the grouping to work: it needs the sentence and
-- paragraph splitters and nothing else.
WordHunterWoW_Addon = {
  SplitParagraphs = function(text)
    local out = {}
    for piece in (tostring(text) .. "\n\n"):gmatch("(.-)\n\n") do
      if piece:match("%S") then out[#out + 1] = piece end
    end
    return out
  end,
  SplitSentences = function(text)
    local out = {}
    for piece in tostring(text):gmatch("[^.!?]+[.!?]?") do
      if piece:match("%S") then out[#out + 1] = (piece:gsub("^%s+", "")) end
    end
    return out
  end,
}

dofile("Naming.lua")
dofile("Talker.lua")
dofile("Voice.lua")
dofile("PlayButtons.lua")
local Addon = WordHunterWoW_Voice

local panel = stub("frame")
panel.content = stub("frame")
-- The pane the content is clipped to. The buttons go beside it rather than in
-- it, so the placement asks the panel for it and draws nothing without it.
panel.scroll = stub("frame")
-- One token frame per sentence, laid out top to bottom, each one line high.
for i = 1, 4 do
  local token = stub("button")
  token.sentenceIndex = i
  token.top = 100 - i * 10
  token.height = 10
  token.left = 20
  token.shown = true
  panel.content.children[#panel.content.children + 1] = token
end

local quest = { id = QUEST_ID, title = "Test", text = TEXT, passage = "offer" }

-- No pack installed. Nothing may appear.
WordHunterWoW_Voice_Parts = {}
assert(Addon.PlacePlayButtons(quest, panel) == 0, "buttons appeared with no pack installed")
print("  no pack means no buttons")

-- A pack that covers the quest but has no recording of this passage.
WordHunterWoW_Voice_Parts = {
  ["WordHunterWoW-Voice-DE-Cataclysm"] = { quests = { 14621, 29377 } },
}
assert(Addon.PlacePlayButtons(quest, panel) == 0, "buttons appeared with no recording")
print("  a pack without this quest's audio means no buttons")

-- Now with durations for two clips.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"].lengths =
  "25152 o 210,340,190\n"
local spans = Addon.ClipSpans(TEXT)
assert(spans and #spans >= 2, "the passage did not group into at least two clips")
local drawn = Addon.PlacePlayButtons(quest, panel)
assert(drawn >= 2, "expected a button per clip, got " .. drawn)
print("  one button per clip once the pack has the audio")

-- The second button must sit on the sentence its clip starts at, not on
-- sentence two. This is the whole reason the grouping is worked out.
local buttons = {}
for _, f in ipairs(made) do
  if f.kind == "Button" and f.clip then buttons[f.clip] = f end
end
assert(buttons[1] and buttons[2], "the buttons did not record which clip they play")
local anchoredTo = buttons[2].points and buttons[2].points[2]
assert(anchoredTo and anchoredTo.sentenceIndex == spans[2].first,
  "clip two was anchored to sentence " .. tostring(anchoredTo and anchoredTo.sentenceIndex)
  .. " but starts at " .. spans[2].first)
print("  a button sits on the sentence its clip starts at, not the next one along")

-- Clicking plays that clip and no other.
played = {}
buttons[2].onOnClick(buttons[2])
assert(#played == 1, "clicking played " .. #played .. " clips")
assert(played[1]:find("25152_o2%.ogg"), "clicking played the wrong clip: " .. played[1])
print("  clicking a button plays its own paragraph")

-- Gossip is not a quest and has no recording.
local gossip = { id = 0, title = "", text = TEXT, passage = "gossip" }
assert(Addon.PlacePlayButtons(gossip, panel) == 0, "buttons appeared on gossip text")
print("  gossip text gets no buttons")

-- Switched off means gone, not merely silent.
Addon.SetEnabled(false)
assert(Addon.PlacePlayButtons(quest, panel) == 0, "buttons stayed after being switched off")
Addon.SetEnabled(true)
print("  switching the addon off takes the buttons with it")

-- A quest rewritten longer than the pack knows: buttons stop where the
-- recordings do rather than offering ones that play nothing.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"].lengths = "25152 o 210\n"
-- The durations are parsed once and kept. ForgetParts throws that parse away,
-- and it runs for real every time an addon loads -- which is how a pack that
-- arrives after the engine is ever noticed at all.
Addon.ForgetParts()
drawn = Addon.PlacePlayButtons(quest, panel)
assert(drawn == 1, "expected one button for one recording, got " .. drawn)
print("  buttons stop where the recordings stop")

-- And now the other end of the join, which needs a world this one cannot hold.
local interpreter = arg and arg[-1] or "lua"
local script = arg and arg[0] or "tests/playbuttons.test.lua"
local command = '"' .. interpreter .. '" "' .. script .. '" join'
-- cmd.exe strips the outer pair of quotes from a command that opens with one,
-- which leaves a quoted interpreter and a quoted script sharing a pair between
-- them and neither of them quoted. The spare pair is what it eats.
if package.config:sub(1, 1) == "\\" then command = '"' .. command .. '"' end
local ok = os.execute(command)
assert(ok == true or ok == 0, "the join to QuestWordHunter failed -- see above")

print("playbuttons: ok")
