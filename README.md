# QuestWordHunter — German Voiceover

Quest text you can read is already here. This is the part you can listen to: the
German a quest giver hands you, spoken, and any single word out loud when you
click it.

**Status: foundations.** The pipeline runs end to end and is measured against
the real corpus. No audio has been generated yet.

## Why it has to be pre-generated

The WoW client cannot synthesise speech. There is no API for it and no way to
reach one from an addon. Everything the pack says has to be generated in
advance, encoded as Ogg Vorbis, and shipped as files the client plays with
`PlaySoundFile`.

That decides the shape of the project. It is not an addon with a tool beside it;
it is a generation pipeline whose output happens to be an addon.

## How big it is

Measured, not estimated, against the German corpus in
`WordHunterWoW-Dictionary-DE`:

| | clips | audio |
|---|---:|---:|
| quest passages — offer, progress, hand-in | 71,791 | ~346 h |
| dictionary words | 104,274 | ~17 h |
| **total** | **176,065** | **~363 h** |

Objectives and quest titles are not in it. Nobody says them out loud — they are
read off the screen.

At the pace an RTX 4090 runs the reader, that is days of generation, not weeks,
and it only has to happen once. Afterwards each run does the new quests and
whatever text Blizzard rewrote.

## Choosing the reader

The constraint is not quality and it is not speed. It is the **licence on the
model weights**, because the audio is given away with the addon and a model that
forbids that forbids the whole project. Code licence and weights licence are
routinely different, and the weights are the ones that matter.

| model | German | weights licence | usable here |
|---|---|---|---|
| **Chatterbox Multilingual** (Resemble AI) | yes, 23 languages | **MIT** | **yes** |
| XTTS-v2 (Coqui) | yes | CPML, non-commercial | no — and Coqui is gone, so there is nobody to license it from |
| F5-TTS, official weights | limited | CC-BY-NC-4.0 | no — trained on Emilia |
| Fish Speech 1.5 | yes | CC-BY-NC-SA-4.0 | no |
| Fish Audio S2 | yes | Fish Audio Research License | no |
| Piper | yes, good German voices | MIT | yes, but no voice cloning |

Chatterbox is the answer: MIT on the code *and* the weights, German among its
languages, zero-shot cloning from a few seconds of reference audio, and it fits
a 4090 several times over. It is free and runs locally — Resemble AI sells a
hosted service, which is a different thing from the model.

Piper is the fallback if cloning turns out not to be worth the trouble. It has
no cloning, so every voice would have to be one somebody already trained, but it
is small, fast and unambiguously free.

## The pipeline

```
Tools/plan_lines.py    what still has to be spoken, and what has to be spoken again
Tools/generate.py      speak it, resumably
Tools/build_pack.py    assemble the clips into installable sound packs
```

Nothing in it is a one-shot. `plan_lines.py` compares the corpus against what is
on disk and reports three numbers — generated, missing, stale — where *stale*
means the German text changed under a clip that already exists. `generate.py`
does exactly that list. Run both again after a patch and only the difference is
spoken.

```bash
python Tools/plan_lines.py --write
python Tools/generate.py --voice narrator --limit 200     # listen to a pilot first
python Tools/generate.py --voice narrator                 # then the rest
python Tools/build_pack.py --size 400
```

`ffmpeg` must be on PATH. `pip install -r Tools/requirements.txt` for the rest.

## How a clip is found

The addon does not ship an index. It computes the name of the clip it wants and
asks for it; if that file has not been generated, nothing plays and nothing
breaks.

- a quest passage is `sounds/q/<id mod 100>/<id>_<o|p|c>.ogg`
- a word is `sounds/w/<first two hex digits>/<64-bit FNV-1a of the key>.ogg`,
  because German keys carry umlauts and the eszett and a WoW client does not
  reliably find a file whose path has those in it

The hash is computed in `Tools/naming.py` and in `Naming.lua`, and the two
implementations are held to the same frozen vectors by `tests/naming.test.lua`.
A drift between them would not be an error — it would be silence on every word
in the pack, which is why it is a test.

Across all 104,274 words in the shipped dictionary, no two share a clip.

## Packaging

One engine addon, several sound packs. The German VoiceOver for Classic is split
into four parts and that covers Classic alone; this covers Retail.

Each pack holds whole shards and declares which ones, so the engine knows where
to look without a manifest of 176,065 filenames. Install some of the parts and
you get what those parts cover — the rest is silent rather than broken.

## Races

The intent is a voice per race rather than one narrator. More voices cost
nothing to generate: a quest is spoken once, in one voice.

What is missing is which race gives which quest. Blizzard's API does not publish
it — the quest endpoint has no quest giver, and the creature endpoint answers
404 for the ids tried. Other packs take it from a third-party content dump; this
project does not use one and will not start.

The client knows at the moment the window opens, and this project already fills
exactly that kind of gap by collecting from the client. See `voices/README.md`.

So: a narrator first, because it needs nothing that does not exist; the map
collected while people play; race voices for what the map covers, growing with
it.

## Layout

```
Naming.lua        where a clip lives — the addon's half
Voice.lua         playback, quest hooks, the word hook
Tools/naming.py   where a clip lives — the generator's half
Tools/speech.py   quest markup out, speakable German in
Tools/plan_lines.py, generate.py, build_pack.py
voices/           one JSON per voice; the recordings are not in git
tests/            run `lua tests/naming.test.lua` and `python tests/speech.test.py`
```

Requires [QuestWordHunter](https://github.com/Ironship/WordHunterWoW) for the
word click; the quest reading works without it.

Retail 12.1 and Classic Era. GPL v3 — see `LICENSE`.
