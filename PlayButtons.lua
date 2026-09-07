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
local BUTTON_SIZE = 16
-- The panel keeps this much clear at the left of every line, and the button
-- sits in it. It used to be squeezed into whatever margin the window happened
-- to leave outside the scroll frame -- 18px with the English column off, and
-- with it on, eight pixels shared with the divider, so the icon was drawn on
-- the line between the two columns. That is the picture this replaces.
local TEXT_GAP = 4

local pool = {}

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
      Addon.PlayQuest(self.questId, self.field, self.clip, true)
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

  -- The pack's own grouping, not one derived from the text on screen. Deriving
  -- it measured the client's rendering of a sentence against thresholds the
  -- generator applied to its own, and a passage carrying a player's name came
  -- out one clip longer -- which put every button after the first on the wrong
  -- paragraph and left the last one with none.
  local spans = Addon.ClipSpans(quest.text, quest.id, field)
  if not spans then return 0 end

  -- A window that is not on screen yet cannot say where its text begins, and a
  -- button placed against a column with no position lands somewhere arbitrary.
  -- The panel refreshes as it opens, so nothing is lost by waiting for it.
  local contentTop = panel.content:GetTop()
  if not contentTop then return 0 end

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
        button = makeButton(panel.content)
        pool[drawn] = button
      end
      button:SetParent(panel.content)
      -- A step above the words, which are its siblings now. They no longer
      -- share any ground -- the strip is kept clear of them -- so this decides
      -- nothing today. It is here because the day they do touch again, the
      -- failure is a button showing through a word as a smudge, which reads as
      -- a rendering fault rather than as a layout one and is hunted for in the
      -- wrong place. Level and not strata: a strata above the panel's would put
      -- these over every window opened on top of it, the word editor included.
      button:SetFrameLevel(panel.content:GetFrameLevel() + 2)
      button:ClearAllPoints()
      local top = token:GetTop()
      local row = top
      if free and row > free + 0.5 then row = free end
      -- The panel steps one token height per line -- it scales the row height
      -- and the row step from the same number -- so a token's own height is the
      -- distance down to the line below it.
      free = row - (token:GetHeight() or 0)
      -- Inside the text frame, at the left edge of the strip the panel keeps
      -- clear. A child of the content rides the text for free: the content is
      -- what slides when the pane is scrolled, and the scroll frame clips it,
      -- so nothing here has to follow a wheel or hide a button that has left
      -- the view. Vertically off the line the clip starts on, horizontally off
      -- the frame -- never off the word, which starts wherever its sentence
      -- happened to begin.
      button:SetPoint("TOPLEFT", panel.content, "TOPLEFT", 0, row - contentTop)
      button.questId, button.field, button.clip = quest.id, field, index
      button:Show()
    end
  end
  return drawn
end

-- Installed on the base addon rather than asked for by it, so QuestWordHunter
-- needs no knowledge of this addon and works unchanged without it.
function Addon.HookQuestPanel()
  local base = WordHunterWoW_Addon
  if not base or Addon.panelHooked then return end
  Addon.panelHooked = true
  -- How much of each line the panel keeps clear for these buttons. Answered
  -- with zero while the voiceover is switched off, so a player who turns it off
  -- gets their full column width back on the next quest rather than a blank
  -- strip where the buttons used to be.
  local previousGutter = base.TextGutter
  base.TextGutter = function()
    if not Addon.GetEnabled() then
      return previousGutter and previousGutter() or 0
    end
    return math.max(BUTTON_SIZE + TEXT_GAP, previousGutter and previousGutter() or 0)
  end
  local previous = base.OnQuestPanelRendered
  base.OnQuestPanelRendered = function(quest, panel)
    -- Anything already listening keeps its turn.
    if previous then previous(quest, panel) end
    Addon.PlacePlayButtons(quest, panel)
  end
end
