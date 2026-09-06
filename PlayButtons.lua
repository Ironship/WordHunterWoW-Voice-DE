local Addon = WordHunterWoW_Voice or {}
WordHunterWoW_Voice = Addon

-- A play button beside every paragraph the pack has a recording for, so a
-- passage can be heard again without reopening the quest.
--
-- Drawn into QuestWordHunter's own panel, from here rather than from there.
-- That is what makes it optional in the way it has to be: a player without the
-- voice packs has this addon absent entirely, and the panel they see is the
-- panel they have always seen. Nothing in QuestWordHunter knows what a button
-- is for; it only offers a callback once its text is laid out.
--
-- A button appears only where a clip actually exists. One that plays nothing is
-- worse than none at all -- it turns "this quest has no audio yet", which is
-- true and common, into "this addon is broken".

-- What QuestWordHunter calls the passage on screen, against what the clips are
-- filed under. "gossip" has no entry: gossip text is not a quest and has no
-- recording.
local PASSAGE_FIELD = {
  offer = "description",
  progress = "progress",
  reward = "completion",
}

-- Where a button goes, and why it is no longer beside the word its clip starts
-- at.
--
-- It used to be exactly there: anchored to the left of the first word of the
-- clip's first sentence. But a clip starts where its sentence starts, and a
-- sentence starts mid-line about a third of the time -- 65% of the clips in
-- tests/_grouping_texts.txt begin a line, and the rest do not. Every one of the
-- rest had its button drawn on top of the word in front of it: "erbost[]Meine".
--
-- The trailing space at the ragged end of a line looks like the answer and is
-- not. The panel wraps a line when the next word would cross the content's
-- width, so what a line leaves behind is narrower than the word that would not
-- fit: at the panel's own default size, two clips in five start on a line with
-- under 18px to spare, and one in ten has no line anywhere in the clip with that
-- much. A place to stand that exists for nine clips in ten is not a place to
-- stand.
--
-- Nor is there a gutter to be had inside the text. QuestPanel's wordButtons loop
-- lays its tokens from x = 0 and wraps them at the full width of panel.content,
-- and that content fills the scroll frame it sits in: 8px short of it with the
-- English column on, 2px wider than it without. Every pixel of the column can
-- hold a word, so room inside it can only be made by the panel, and reflowing
-- the panel's own text is not this addon's to do.
--
-- What is left is the margin the panel already leaves outside that scroll frame,
-- between the text and its own edge. One button to a line, on the line its clip
-- starts.
local BUTTON_SIZE = 14
-- 14 rather than 16, because the narrower of the two layouts decides it: with
-- the English column switched off the panel leaves 18px between the window's
-- edge and the first word, and 16 plus the gap fills that exactly, which pushes
-- the icon under the window's border art. With the column on, the same margin is
-- the channel between the two panes and the button sits across the divider line.
local TEXT_GAP = 2

local pool = {}
-- The buttons the last placement drew. The pool outlives a passage and keeps
-- buttons for clips that are no longer on screen; these are the ones the panel
-- is showing, and so the only ones a scroll has anything to say about.
local placed = {}
local strip
local watchedScroll

-- A button whose line has been scrolled out of the pane has to leave with it.
-- The words manage that by themselves -- the scroll frame clips them to its own
-- rectangle -- but these are drawn outside that frame, so nothing clips them and
-- nothing moves them. Clipping the gutter settles what is drawn; this settles
-- what can be clicked, which is not something to take clipping's word for.
local function keepWithinPane(scroll)
  local paneTop, paneBottom = scroll:GetTop(), scroll:GetBottom()
  if not paneTop or not paneBottom then return end
  for _, button in ipairs(placed) do
    local top, bottom = button:GetTop(), button:GetBottom()
    if top and bottom and (bottom > paneTop or top < paneBottom) then
      button:Hide()
    else
      button:Show()
    end
  end
end

-- The gutter: a strip of the panel beside the text, and the parent every button
-- hangs from.
--
-- Anchored to the scroll frame and not to the content, because the content is
-- the part that slides when the pane is scrolled, and a gutter that slid with it
-- would carry its buttons off the top of the window.
--
-- Its level is raised above the content's. A token is a frame of the panel's
-- own, one step deeper in its tree and so one level higher than anything hung
-- off the panel itself: a button left at the level it inherits is drawn *behind*
-- the words, which is what made one read as a smudge on a word rather than as a
-- button. The level and not the strata -- a strata above the panel's would put
-- these over every window that opens on top of it, the word editor included.
local function gutter(panel)
  if not strip then strip = CreateFrame("Frame", nil, panel) end
  strip:SetParent(panel)
  strip:ClearAllPoints()
  strip:SetPoint("TOPRIGHT", panel.scroll, "TOPLEFT", -TEXT_GAP, 0)
  strip:SetPoint("BOTTOMRIGHT", panel.scroll, "BOTTOMLEFT", -TEXT_GAP, 0)
  strip:SetWidth(BUTTON_SIZE)
  -- Asked for rather than assumed: there is no SetClipsChildren on the oldest
  -- clients this addon claims to support, the same ones that have no C_Timer.
  -- What it costs there is a button on a half-scrolled line drawn whole instead
  -- of cut off at the edge of the pane. A button whose line has gone altogether
  -- is hidden by the hook below, and that is the half worth having.
  if strip.SetClipsChildren then strip:SetClipsChildren(true) end
  strip:SetFrameLevel(panel.content:GetFrameLevel() + 5)
  strip:Show()
  -- The panel calls back when it lays its text out, and a scroll is not that.
  if watchedScroll ~= panel.scroll then
    watchedScroll = panel.scroll
    panel.scroll:HookScript("OnVerticalScroll", keepWithinPane)
  end
  return strip
end

local function makeButton(parent)
  local button = CreateFrame("Button", nil, parent)
  button:SetSize(BUTTON_SIZE, BUTTON_SIZE)
  button:SetNormalTexture("Interface\\TimeManager\\ResetButton")
  if button.GetNormalTexture and button:GetNormalTexture() then
    button:GetNormalTexture():SetTexCoord(0, 1, 0, 1)
  end
  button:SetHighlightTexture("Interface\\Buttons\\UI-Common-MouseHilight")
  button:SetScript("OnEnter", function(self)
    if not GameTooltip then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Diesen Absatz vorlesen")
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", function()
    if GameTooltip then GameTooltip:Hide() end
  end)
  button:SetScript("OnClick", function(self)
    if self.questId and self.field and self.clip then
      Addon.PlayQuest(self.questId, self.field, self.clip)
    end
  end)
  return button
end

-- The token the clip starts on, chosen by where it ended up on screen rather
-- than by counting: the panel lays tokens out itself and only it knows where a
-- line wrapped.
local function firstTokenOfSentence(content, sentence)
  local best
  for _, child in ipairs({ content:GetChildren() }) do
    if child.sentenceIndex == sentence and child:IsShown() and child.GetTop then
      local top, left = child:GetTop(), child:GetLeft()
      if top and left then
        if not best then
          best = child
        else
          local bestTop, bestLeft = best:GetTop(), best:GetLeft()
          -- Higher wins; on the same line, further left wins.
          if top > bestTop + 0.5 or (math.abs(top - bestTop) <= 0.5 and left < bestLeft) then
            best = child
          end
        end
      end
    end
  end
  return best
end

function Addon.HidePlayButtons()
  for _, button in ipairs(pool) do button:Hide() end
  -- Forgotten as well as hidden. What a scroll may show again is what the panel
  -- has just drawn, and a button for a passage that is no longer on screen is
  -- not that.
  for index = #placed, 1, -1 do placed[index] = nil end
end

-- Called by QuestWordHunter once its text is laid out.
function Addon.PlacePlayButtons(quest, panel)
  Addon.HidePlayButtons()
  -- The scroll frame as well as the content: the gutter is measured off the pane
  -- the text is clipped to, and a panel that cannot say where that is gets no
  -- buttons rather than buttons in the wrong place.
  if not Addon.GetEnabled() or not quest or not panel or not panel.content or not panel.scroll then
    return 0
  end
  local field = PASSAGE_FIELD[quest.passage or "offer"]
  if not field then return 0 end

  local folder = Addon.QuestOwner and Addon.QuestOwner(quest.id)
  local lengths = folder and Addon.LengthsFor(folder, quest.id, field)
  -- No pack, or no recording for this passage: draw nothing at all.
  if not lengths then return 0 end

  local spans = Addon.ClipSpans(quest.text)
  if not spans then return 0 end

  -- A window that is not on screen yet cannot say where its margin is, and a
  -- button placed against a column with no position lands somewhere arbitrary.
  -- The panel refreshes as it opens, so nothing is lost by waiting for it.
  local column = gutter(panel):GetRight()
  if not column then return 0 end

  local drawn = 0
  -- The top of the highest line the gutter has not used yet. Two clips can start
  -- on the same line -- one clip in twenty at the panel's default width, one in
  -- four once it has been dragged wide -- and in a single-file gutter the second
  -- button would be drawn on top of the first, which is this same bug wearing
  -- different clothes. It takes the next free line down instead, which across
  -- tests/_grouping_texts.txt is still a line of that clip's own words.
  local free
  for index, span in ipairs(spans) do
    -- Only as far as the recordings go. A quest may have been rewritten longer
    -- since the pack was built, and the paragraphs past the end have no clip.
    if not lengths[index] then break end
    local token = firstTokenOfSentence(panel.content, span.first)
    if token then
      drawn = drawn + 1
      local button = pool[drawn]
      if not button then
        button = makeButton(strip)
        pool[drawn] = button
      end
      button:SetParent(strip)
      button:ClearAllPoints()
      local top = token:GetTop()
      local row = top
      if free and row > free + 0.5 then row = free end
      -- The panel steps one token height per line -- it scales the row height
      -- and the row step from the same number -- so a token's own height is the
      -- distance down to the line below it.
      free = row - (token:GetHeight() or 0)
      -- Hung off the word rather than dropped into the gutter, so the button
      -- rides the text: the panel lays out on a refresh, a scroll is not one,
      -- and a button anchored to the window would part company with its line at
      -- the first turn of the wheel. Only the offsets say where the column is.
      button:SetPoint("RIGHT", token, "LEFT", column - token:GetLeft(), row - top)
      button.questId, button.field, button.clip = quest.id, field, index
      button:Show()
      placed[drawn] = button
    end
  end
  keepWithinPane(panel.scroll)
  return drawn
end

-- Installed on the base addon rather than asked for by it, so QuestWordHunter
-- needs no knowledge of this addon and works unchanged without it.
function Addon.HookQuestPanel()
  local base = WordHunterWoW_Addon
  if not base or Addon.panelHooked then return end
  Addon.panelHooked = true
  local previous = base.OnQuestPanelRendered
  base.OnQuestPanelRendered = function(quest, panel)
    -- Anything already listening keeps its turn.
    if previous then previous(quest, panel) end
    Addon.PlacePlayButtons(quest, panel)
  end
end
