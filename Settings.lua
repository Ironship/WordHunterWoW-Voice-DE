local Addon = WordHunterWoW_Voice or {}
WordHunterWoW_Voice = Addon

-- The options panel, in the game's own AddOns list.
--
-- Everything here is already reachable through /whwv, and the slash command
-- stays. But a player who installs a voice pack and hears nothing looks in
-- Options first, and finding nothing there reads as "it does not work" rather
-- than "it is switched off" -- so the panel exists mostly to be found.
--
-- It also answers the question the slash command cannot: which packs are
-- actually installed. That is the single most common way this addon appears
-- broken, because a quest outside every installed pack is silent by design and
-- looks exactly like a fault.

local PANEL_NAME = "QuestWordHunter Voice"

local function makeCheck(parent, label, tooltip, get, set)
  local check = CreateFrame("CheckButton", nil, parent, "InterfaceOptionsCheckButtonTemplate")
  check.Text:SetText(label)
  check.tooltipText = label
  check.tooltipRequirement = tooltip
  check:SetScript("OnClick", function(self)
    set(self:GetChecked() and true or false)
  end)
  check.refresh = function() check:SetChecked(get()) end
  return check
end

-- What the player has installed, in the order the packs were released, so the
-- list reads the way the download page does.
local ORDER = {
  "Classic", "BurningCrusade", "Wrath", "Cataclysm", "Pandaria", "Draenor",
  "Legion", "Azeroth", "Shadowlands", "Dragonflight", "WarWithin", "Words",
}

function Addon.InstalledPacks()
  local held, quests, words = {}, 0, false
  for folder, part in pairs(WordHunterWoW_Voice_Parts or {}) do
    local name = folder:match("^WordHunterWoW%-Voice%-DE%-(.+)$") or folder
    held[name] = true
    if part.words then words = true else quests = quests + 1 end
  end
  local named = {}
  for _, name in ipairs(ORDER) do
    if held[name] then
      named[#named + 1] = name
      held[name] = nil
    end
  end
  -- Anything with a name this addon does not know about still gets listed;
  -- silently dropping it would hide exactly the case worth seeing.
  for name in pairs(held) do named[#named + 1] = name end
  return named, quests, words
end

function Addon.CreateSettingsPanel()
  if Addon.settingsPanel then return Addon.settingsPanel end
  local panel = CreateFrame("Frame")
  panel.name = PANEL_NAME

  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText(PANEL_NAME)

  local blurb = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  blurb:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  blurb:SetPoint("RIGHT", panel, "RIGHT", -16, 0)
  blurb:SetJustifyH("LEFT")
  blurb:SetText("Liest deutschen Questtext vor. Die Audiodateien liegen in "
    .. "separaten Paketen; ein Quest ohne Aufnahme bleibt still.")

  local quests = makeCheck(panel, "Questtext vorlesen",
    "Liest Beschreibung, Zwischenstand und Abgabe, Satz für Satz.",
    Addon.GetEnabled, Addon.SetEnabled)
  quests:SetPoint("TOPLEFT", blurb, "BOTTOMLEFT", 0, -16)

  local words = makeCheck(panel, "Einzelne Wörter vorlesen",
    "Spricht ein Wort aus, wenn es angeklickt wird. Braucht das Wörterpaket.",
    Addon.GetWordsEnabled, Addon.SetWordsEnabled)
  words:SetPoint("TOPLEFT", quests, "BOTTOMLEFT", 0, -8)

  local talker = makeCheck(panel, "Sprecherfenster anzeigen",
    "Zeigt während des Vorlesens, zu welchem Quest die Stimme gehört, "
    .. "mit einer Schaltfläche zum Abbrechen. Verschiebbar.",
    Addon.GetTalkerEnabled, Addon.SetTalkerEnabled)
  talker:SetPoint("TOPLEFT", words, "BOTTOMLEFT", 0, -8)

  local demo = makeCheck(panel, "Platzhalter abspielen",
    "Spielt einen Hinweis ab, wenn für den Quest noch keine Aufnahme existiert. "
    .. "Zum Prüfen, ob überhaupt Ton ankommt.",
    Addon.GetDemo, Addon.SetDemo)
  demo:SetPoint("TOPLEFT", talker, "BOTTOMLEFT", 0, -8)

  -- How long the voice waits before starting. A slider rather than a switch
  -- because the right value depends on how fast the player reads, and the
  -- default is a compromise nobody asked for.
  local delay = CreateFrame("Slider", "WordHunterWoWVoiceDelaySlider", panel,
    "OptionsSliderTemplate")
  delay:SetPoint("TOPLEFT", demo, "BOTTOMLEFT", 6, -32)
  delay:SetWidth(220)
  delay:SetMinMaxValues(0, 5)
  delay:SetValueStep(0.25)
  if delay.SetObeyStepOnDrag then delay:SetObeyStepOnDrag(true) end
  if delay.Low then delay.Low:SetText("sofort") end
  if delay.High then delay.High:SetText("5 s") end
  delay:SetScript("OnValueChanged", function(self, value)
    value = math.floor(value * 4 + 0.5) / 4
    Addon.SetDelay(value)
    if self.Text then
      self.Text:SetText(value == 0 and "Verzögerung: sofort"
        or string.format("Verzögerung: %.2f s", value))
    end
  end)
  delay.refresh = function()
    delay:SetValue(Addon.GetDelay())
    if delay.Text then
      local value = Addon.GetDelay()
      delay.Text:SetText(value == 0 and "Verzögerung: sofort"
        or string.format("Verzögerung: %.2f s", value))
    end
  end

  local installed = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  installed:SetPoint("TOPLEFT", delay, "BOTTOMLEFT", -6, -28)
  installed:SetText("Installierte Pakete")

  local list = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  list:SetPoint("TOPLEFT", installed, "BOTTOMLEFT", 0, -6)
  list:SetPoint("RIGHT", panel, "RIGHT", -16, 0)
  list:SetJustifyH("LEFT")

  panel.refresh = function()
    quests.refresh()
    words.refresh()
    talker.refresh()
    demo.refresh()
    delay.refresh()
    local named, questPacks, hasWords = Addon.InstalledPacks()
    if #named == 0 then
      list:SetText("|cffff8080Keine|r. Ohne ein Paket bleibt jeder Quest still.")
    else
      local tail = hasWords and "" or "  |cffc0c0c0(kein Wörterpaket)|r"
      list:SetText(table.concat(named, ", ") .. tail)
    end
    -- Words cannot be spoken without the pack that holds them, and a switch
    -- that does nothing is worse than one that says why.
    if hasWords then words:Enable() else words:Disable() end
    if questPacks == 0 then quests:Disable() else quests:Enable() end
  end

  panel:SetScript("OnShow", function(self) self.refresh() end)

  if Settings and Settings.RegisterAddOnCategory then
    if Settings.RegisterCanvasLayoutCategory then
      local category = Settings.RegisterCanvasLayoutCategory(panel, panel.name)
      category.ID = panel.name
      Settings.RegisterAddOnCategory(category)
      Addon.settingsCategory = category
    else
      local category = Settings.RegisterVerticalLayoutCategory(panel.name)
      Settings.RegisterAddOnCategory(category)
      Addon.settingsCategory = category
    end
  elseif InterfaceOptions_AddCategory then
    InterfaceOptions_AddCategory(panel)
  end

  Addon.settingsPanel = panel
  return panel
end

function Addon.OpenSettings()
  local panel = Addon.CreateSettingsPanel()
  if panel.refresh then panel.refresh() end
  if Settings and Settings.OpenToCategory and Addon.settingsCategory then
    local id = Addon.settingsCategory.GetID and Addon.settingsCategory:GetID()
      or Addon.settingsCategory.ID
    if id then Settings.OpenToCategory(id) end
  elseif InterfaceOptionsFrame_OpenToCategory then
    -- Called twice on the old client: the first call only opens the frame.
    InterfaceOptionsFrame_OpenToCategory(panel)
    InterfaceOptionsFrame_OpenToCategory(panel)
  end
end
