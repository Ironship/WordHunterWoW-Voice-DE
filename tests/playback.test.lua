-- Run from the addon root:  lua tests/playback.test.lua
--
-- The engine holds no list of what exists. It works out a clip's name, works out
-- which sound pack owns it, and asks the client. Every step of that is silent
-- when it goes wrong -- a wrong path is not an error, it is a quest that says
-- nothing -- so each step is checked here.

local asked, stopped, handle = {}, {}, 0
PlaySoundFile = function(path, channel)
  asked[#asked + 1] = { path = path, channel = channel }
  -- The client answers false for a file that is not there. Only the paths this
  -- test says exist are allowed to play.
  if not _G.EXISTS[path] then return false end
  handle = handle + 1
  return true, handle
end
StopSound = function(h) stopped[#stopped + 1] = h end
GetQuestID = function() return _G.QUEST_ID or 0 end
events = {}
CreateFrame = function()
  local f = {}
  function f:RegisterEvent(name) events[name] = true end
  function f:SetScript(_, fn) _G.ON_EVENT = fn end
  return f
end

dofile("Naming.lua")
dofile("Voice.lua")
local Addon = WordHunterWoW_Voice

-- Two packs installed out of the twelve.
-- Quest 25152 falls in the Cataclysm range and that pack is installed; quest
-- 8325 is Classic and that pack is not.
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"] = { quests = { 14621, 29377 } }
WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Words"] = { words = true }
Addon.ForgetParts()

local questClip =
  "Interface\\AddOns\\WordHunterWoW-Voice-DE-Cataclysm\\sounds\\q\\52\\25152_o1.ogg"
local wordClip =
  "Interface\\AddOns\\WordHunterWoW-Voice-DE-Words\\" .. Addon.WordPath("zuflucht")
_G.EXISTS = { [questClip] = true, [wordClip] = true }

assert(Addon.PlayQuest(25152, "description", 1), "a quest in an installed pack did not play")
assert(asked[#asked].path == questClip, "wrong path: " .. asked[#asked].path)
assert(asked[#asked].channel == "Dialog", "quest audio should use the Dialog channel")
print("  a quest passage resolves to the pack that holds it")

-- The shard the clip names and the folder it is looked for in must agree. This
-- is the join that a change to either half would break.
assert(questClip:find("\\q\\52\\", 1, true), "the path lost its shard")

local before = #asked
assert(not Addon.PlayQuest(8325, "completion", 1),
  "a quest in a pack nobody installed must not claim to play")
assert(#asked == before, "the client was asked for a clip from a missing pack")
print("  a missing sound pack is silence, not a wrong file and not an error")

-- Objectives and titles have no clip at all; asking must not reach the client.
before = #asked
assert(not Addon.PlayQuest(25152, "objectives", 1), "objectives are not spoken")
assert(#asked == before, "the client was asked for a passage nobody says")

-- Starting a new clip stops the one running. Two quest givers talking over each
-- other is the worst thing this addon could do.
local playedHandle = handle
Addon.PlayQuest(25152, "description", 1)
assert(stopped[#stopped] == playedHandle, "the previous clip was not stopped")
print("  a new passage stops the one already playing")

-- A passage is several sentences, and the client never says when one has
-- finished, so the pack ships how long each runs and the engine books the next
-- on a timer. This is the whole reason a quest is read through rather than cut
-- off after its first line, so it is checked step by step.
local booked = {}
C_Timer = { After = function(delay, action) booked[#booked + 1] = { delay = delay, action = action } end }
local function fire()
  local due = table.remove(booked, 1)
  if due then due.action() end
  return due
end

local pack = WordHunterWoW_Voice_Parts["WordHunterWoW-Voice-DE-Cataclysm"]
-- Quest 25152: a description of three sentences, 1.2s, 2.5s and 0.8s.
pack.lengths = "25152 o 120,250,80\n25152 c 90\n"
local two = "Interface\\AddOns\\WordHunterWoW-Voice-DE-Cataclysm\\sounds\\q\\52\\25152_o2.ogg"
local three = "Interface\\AddOns\\WordHunterWoW-Voice-DE-Cataclysm\\sounds\\q\\52\\25152_o3.ogg"
_G.EXISTS[two] = true
_G.EXISTS[three] = true

assert(Addon.LengthsFor("WordHunterWoW-Voice-DE-Cataclysm", 25152, "description")[2] == 250,
  "the durations were not parsed out of the pack")
assert(Addon.LengthsFor("WordHunterWoW-Voice-DE-Cataclysm", 25152, "objectives") == nil,
  "a field nobody speaks must have no durations")

booked = {}
assert(Addon.PlayQuest(25152, "description"), "the passage did not start")
assert(asked[#asked].path == questClip, "the passage did not start at sentence one")
assert(#booked == 1, "sentence two was not booked")
assert(math.abs(booked[1].delay - (1.2 + 0.25)) < 0.001,
  "sentence two is due at the wrong time: " .. booked[1].delay)
fire()
assert(asked[#asked].path == two, "sentence two did not play: " .. asked[#asked].path)
assert(#booked == 1, "sentence three was not booked")
fire()
assert(asked[#asked].path == three, "sentence three did not play")
-- One thing is still booked after the last sentence: hiding the frame that says
-- who is talking, once the talking stops. Nothing further is played.
assert(#booked == 1, "the frame was not booked to disappear")
local before = #asked
fire()
assert(#asked == before, "something was played after the last sentence")
assert(#booked == 0, "still booked after the frame was hidden")
print("  a passage plays through, one sentence booking the next")

-- A timer that fires after the player has closed the window must do nothing.
-- Getting this wrong means a quest giver talking over an empty screen.
booked = {}
Addon.PlayQuest(25152, "description")
local heard = #asked
Addon.Stop()
fire()
assert(#asked == heard, "a cancelled reading carried on after it was stopped")
print("  stopping a passage cancels the sentences still to come")

-- A pack with no durations is the state every pack was in before this existed,
-- and it must still say its first sentence rather than nothing.
pack.lengths = nil
booked = {}
assert(Addon.PlayQuest(25152, "description"), "a pack without durations went silent")
assert(asked[#asked].path == questClip, "wrong clip without durations")
assert(#booked == 0, "booked a sentence with no duration to book it from")
pack.lengths = "25152 o 120,250,80\n"
print("  a pack that ships no durations still reads its first sentence")

-- Pause and play.
--
-- The client will not say how far into a clip it has got, and a stopped clip
-- can only be started again from its beginning, so the sentence is the finest
-- honest unit. What must not happen is play quietly restarting the passage:
-- that is a replay button wearing a play icon, and on a five-sentence quest the
-- difference is a minute of somebody's evening.
booked = {}
assert(Addon.PlayQuest(25152, "description"), "the passage did not start")
fire()
assert(asked[#asked].path == two, "the passage did not reach its second sentence")
assert(not Addon.IsPaused(), "nothing has been paused yet")

assert(Addon.Pause(), "pausing a running passage did nothing")
assert(Addon.IsPaused(), "paused, but not saying so")
before = #asked
fire()
assert(#asked == before, "a paused passage carried on to the sentence it had booked")

assert(Addon.Resume(), "play did nothing on a paused passage")
assert(asked[#asked].path == two,
  "play restarted the passage instead of carrying on: " .. asked[#asked].path)
assert(not Addon.IsPaused(), "still paused after playing")
print("  pause remembers the sentence, and play carries on from it")

-- A passage that has run to its end has nothing to carry on from, so play reads
-- it again from the top. Resuming its closing line would be the literal reading
-- of "remember where you were" and is not what a play button means.
booked = {}
assert(Addon.PlayQuest(25152, "description"), "the passage did not start")
fire(); fire(); fire()
assert(not Addon.IsPaused(), "a finished passage is not a paused one")
assert(Addon.Resume(), "play did nothing on a finished passage")
assert(asked[#asked].path == questClip, "a finished passage did not start again from the top")
print("  a passage that ran to its end starts again rather than resuming")

-- Stop is the other one: the quest window has closed, so there is nothing left
-- to resume or repeat. Without that distinction the play button would offer to
-- read a quest that is no longer on screen.
Addon.Stop()
assert(not Addon.IsPaused(), "stop left the passage paused")
assert(not Addon.CanReplay(), "stop remembered a passage it was told to forget")
before = #asked
assert(not Addon.Resume(), "there was nothing to resume, but something played")
assert(not Addon.Pause(), "paused a passage that was never playing")
assert(#asked == before, "the client was asked for a clip after everything was stopped")
print("  stop forgets the passage; pause is the one that remembers")

-- Closing the window stops it too.
_G.ON_EVENT(nil, "QUEST_FINISHED")
local quiet = #stopped
_G.ON_EVENT(nil, "QUEST_FINISHED")
assert(#stopped == quiet, "stopping twice stopped a handle that was already gone")
print("  closing the quest window stops the voice, once")

-- The event path, not just the functions under it.
--
-- Nothing is spoken the instant the window opens: the client is still making
-- its own noise and the player is still reading the title. The wait is booked
-- like everything else, so the test fires it rather than sleeping.
_G.QUEST_ID = 25152
booked = {}
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
assert(#asked == before, "the quest was read before the delay had passed")
assert(#booked == 1, "the delayed start was not booked")
assert(math.abs(booked[1].delay - 1.5) < 0.001,
  "the delay is " .. booked[1].delay .. ", not the default 1.5")
fire()
assert(#asked > before and asked[#asked].path == questClip, "QUEST_DETAIL did not read the quest")
print("  a quest is read a beat after the window opens, not the instant it does")

-- Opening a second window while the first is still counting down must cancel
-- the first, or two quests speak over each other.
booked = {}
_G.ON_EVENT(nil, "QUEST_DETAIL")
_G.ON_EVENT(nil, "QUEST_DETAIL")
before = #asked
fire()
assert(#asked == before, "the first window still spoke after a second one opened")
fire()
assert(#asked > before, "the second window never spoke either")
print("  a second quest window cancels the first one's pending start")

-- Taking a quest from a gossip window fires QUEST_DETAIL and then
-- GOSSIP_CLOSED. If the second cancels the first, the delayed start never
-- happens and nothing is ever read for any quest taken from a gossip menu --
-- which is nearly all of them. This is the regression that made the whole addon
-- look dead in game.
assert(not events["GOSSIP_CLOSED"],
  "GOSSIP_CLOSED is subscribed again; it cancels the quest it just opened")
booked = {}
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
-- Whatever else the client sends between the two, the pending start survives.
-- Only QUEST_FINISHED may cancel it.
_G.ON_EVENT(nil, "GOSSIP_CLOSED")
_G.ON_EVENT(nil, "SOME_UNRELATED_EVENT")
assert(#booked == 1, "an unrelated event threw away the pending start")
fire()
assert(#asked > before and asked[#asked].path == questClip,
  "a quest taken from a gossip window was never read")
print("  only QUEST_FINISHED cancels a reading, not any event that turns up")

_G.QUEST_ID = 0
booked = {}
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
assert(#booked == 0 and #asked == before,
  "a quest window with no quest id still booked or asked for a clip")
print("  a missing quest id is ignored")

-- Off means off, including the wait.
Addon.SetDelay(0)
assert(Addon.GetDelay() == 0, "the delay would not go to zero")
_G.QUEST_ID = 25152
booked = {}
before = #asked
_G.ON_EVENT(nil, "QUEST_DETAIL")
assert(#asked > before, "with no delay the quest should be read at once")
Addon.SetDelay(1.5)
-- Out of range on either side is clamped rather than obeyed: a negative delay
-- and a delay of an hour are both ways of breaking it by accident.
Addon.SetDelay(-5); assert(Addon.GetDelay() == 0, "a negative delay was accepted")
Addon.SetDelay(9999); assert(Addon.GetDelay() == 10, "an absurd delay was accepted")
Addon.SetDelay(1.5)
print("  the delay can be turned off, and cannot be set to nonsense")

-- Words. The key is casefolded and the eszett becomes ss, exactly as the
-- dictionary files them, or a word goes looking in the wrong place.
assert(Addon.PlayWord("Zuflucht"), "a word in an installed pack did not play")
assert(asked[#asked].path == wordClip, "wrong word path: " .. asked[#asked].path)
assert(Addon.WordKey("STRAßE") == "strasse", "the eszett rule is not applied: "
  .. Addon.WordKey("STRAßE"))
assert(not Addon.PlayWord(""), "an empty word must not be looked up")
print("  a word resolves through the same key the dictionary files it under")

-- Switched off means silent, both settings independently.
Addon.SetEnabled(false)
before = #asked
assert(not Addon.PlayQuest(25152, "description", 1), "switched off but still playing")
assert(#asked == before, "switched off but still asking the client")
Addon.SetEnabled(true)
Addon.SetWordsEnabled(false)
assert(not Addon.PlayWord("Zuflucht"), "words switched off but still playing")
assert(Addon.PlayQuest(25152, "description", 1), "switching words off silenced the quests too")
Addon.SetWordsEnabled(true)
print("  quest reading and word reading switch off separately")

-- Stand-in clips: off by default, and never in place of a clip that exists.
UnitSex = function() return 2 end
-- demo/, not sounds/: .pkgmeta keeps sounds/ out of the built addon, so a
-- stand-in kept there would never reach a player.
local demoDir = "Interface\\AddOns\\WordHunterWoW-Voice-DE\\demo\\"
local male = demoDir .. "male.ogg"
local female = demoDir .. "female.ogg"
_G.EXISTS[male] = true
_G.EXISTS[female] = true
assert(not Addon.GetDemo(), "stand-ins must be off unless asked for")
before = #asked
assert(not Addon.PlayQuest(8325, "completion", 1), "played a stand-in without being asked")
assert(#asked == before, "asked the client for a stand-in while switched off")
Addon.SetDemo(true)
assert(Addon.PlayQuest(8325, "completion", 1), "the stand-in did not play")
assert(asked[#asked].path == male, "wrong stand-in: " .. asked[#asked].path)
-- A real clip always wins; the stand-in is only for what does not exist yet.
Addon.PlayQuest(25152, "description", 1)
assert(asked[#asked].path == questClip, "a stand-in replaced a clip that exists")
UnitSex = function() return 3 end
Addon.PlayQuest(8325, "completion", 1)
assert(asked[#asked].path == female, "the stand-in ignored the speaker's sex")
UnitSex = function() return nil end
Addon.PlayQuest(8325, "completion", 1)
assert(asked[#asked].path == male, "an unknown sex should fall back to the male stand-in")
Addon.SetDemo(false)
print("  stand-ins fill in only what is missing, and follow the speaker's sex")

-- The word hook wraps the base addon rather than requiring it to offer a hook,
-- and must pass the call through untouched.
local opened = {}
WordHunterWoW_Addon = { openEditor = function(...) opened[#opened + 1] = { ... } end }
Addon.HookBaseAddon()
Addon.HookBaseAddon()
WordHunterWoW_Addon.openEditor("Zuflucht", "context", 1, "title")
assert(#opened == 1 and opened[1][1] == "Zuflucht" and opened[1][3] == 1,
  "the editor call was not passed through intact")
assert(asked[#asked].path == wordClip, "clicking a word did not say it")
print("  clicking a word says it, and the editor still opens")

-- The slash command is the only way into any of this in the game, so it is
-- checked like anything else the player touches.
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
assert(SlashCmdList and SlashCmdList["WHWVOICE"], "no slash command registered")
assert(SLASH_WHWVOICE1 == "/whwvoice" and SLASH_WHWVOICE2 == "/whwv", "wrong slash names")
local run = SlashCmdList["WHWVOICE"]
run("off"); assert(not Addon.GetEnabled(), "/whwv off did not switch it off")
run("on");  assert(Addon.GetEnabled(), "/whwv on did not switch it on")
run("words"); assert(not Addon.GetWordsEnabled(), "/whwv words did not toggle")
run("words"); assert(Addon.GetWordsEnabled(), "/whwv words did not toggle back")
run("demo"); assert(Addon.GetDemo(), "/whwv demo did not turn stand-ins on")
run("demo"); assert(not Addon.GetDemo(), "/whwv demo did not turn them off")
run(""); run("nonsense")   -- must not raise
run("  ON  "); assert(Addon.GetEnabled(), "the command should ignore case and spaces")
print("  the slash command reaches every switch")

print("playback: ok")
