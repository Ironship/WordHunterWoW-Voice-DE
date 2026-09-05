# Voices

One JSON file per voice. The reader clones from a reference recording, so a
voice is a few seconds of German speech plus the settings it is read with.

```json
{
  "name": "narrator",
  "reference": "narrator.wav",
  "exaggeration": 0.5,
  "cfg_weight": 0.5,
  "note": "who this is and where the recording came from"
}
```

`reference` is a path inside this folder. Five to ten seconds is enough, and
more is not better: a long reference with varied delivery gives a less stable
voice than a short, even one. It must be **German**. The model carries the
accent of its reference across languages, so an English recording produces
German spoken by an English speaker.

The `.wav` files are not in git — they are recordings, not source — and
`.gitignore` keeps them out. Keep them somewhere you will still have them: a
voice cannot be reproduced from the clips it generated.

## Where a reference may come from

This pack is given away, so the reference has to be one that may be. Three
sources qualify:

- a recording you made yourself
- a speaker who has released their voice permissively — Thorsten-Voice is a
  German corpus in the public domain (CC0), which is the cleanest option
- a synthetic voice from a model whose licence allows redistribution

**Not** the game's own voice acting. Cloning Blizzard's actors and handing the
result out is a copyright problem no licence on the model can fix, and it is the
one way this project could get taken down.

## Races

The intent is a voice per race — dwarves, humans, elves, orcs — rather than one
narrator for everything.

The model side of that is easy: a race is another JSON file with another
reference, and a quest is still spoken once, in one voice, so more voices do not
mean more generation. `race` and `sex` on a voice file say who it is for.

What is missing is the other half: **which race gives which quest**. Blizzard's
Game Data API does not publish it. The quest endpoint returns a title, a
description, an area and rewards, and no quest giver; the creature endpoint
answers 404 for the quest-giver ids that were tried. Other voiceover packs solve
this from a third-party content dump, which this project deliberately does not
use and will not start using.

The client knows, though, at the moment the quest window opens: the NPC being
spoken to is `UnitGUID("npc")`, which carries the creature id, along with
`UnitSex` and `UnitCreatureType`. That is the same gap the dictionary already
fills by collecting from the client rather than from the API, and the same
answer applies — see `../WordHunterWoW/Harvest.lua`.

So the order is: a narrator voice for everything first, because it needs nothing
that does not exist yet; the quest-to-NPC map collected while people play; and
race voices generated for the quests the map covers, growing as it does.
