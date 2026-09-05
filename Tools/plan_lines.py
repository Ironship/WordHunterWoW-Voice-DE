#!/usr/bin/env python3
"""Work out what still has to be spoken, and what has to be spoken again.

    python Tools/plan_lines.py                 # report only
    python Tools/plan_lines.py --write         # write Data/lines.jsonl

This is the whole update story. Blizzard adds quests and rewrites old ones, and
the dictionary grows every time somebody plays with collection on. Run this
again and it lists exactly what is missing or out of date; generate.py then does
only that. Nothing is regenerated because a patch happened -- only because the
words changed.

A line carries a hash of the text it was made from. That is what tells a
rewritten quest apart from an unchanged one: the path is the same, so a
comparison of file names would see nothing.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import naming
import speech

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT.parent
DEFAULT_QUESTS = SUITE / "WordHunterWoW-Dictionary-DE/Data/cache/quests_deDE.jsonl"
DEFAULT_WORDS = SUITE / "WordHunterWoW-Dictionary-DE/Data/DictionaryDE.lua"
LINES = ROOT / "Data/lines.jsonl"

# The generated dictionary, one entry per line, always this shape. Parsed rather
# than re-derived from the sources so the pack voices exactly what ships.
ENTRY = re.compile(r'^WordHunterWoW_Dictionary_DE\["((?:[^"\\]|\\.)*)"\] = \{ word = "((?:[^"\\]|\\.)*)"')


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def quest_lines(path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        quest_id = record.get("id")
        # Gossip sits under negative ids and gets its own numbering; Classic
        # records are keyed "classic-2". Neither is a Retail quest id the client
        # can ask for, so neither can be looked up at runtime. Skipping them
        # here is what keeps the pack honest about what it can play.
        if not isinstance(quest_id, int) or quest_id < 0:
            continue
        for field in naming.SPOKEN_FIELDS:
            said = speech.clean(record.get(field))
            if not said:
                continue
            # One clip per sentence, numbered in reading order -- except that
            # sentences too short to stand alone are joined to a neighbour, so a
            # clip can cover two or three of them and the addon highlights the
            # group. A one-character sentence is not merely a poor clip: it
            # raises inside the reader's own alignment analyser, which is how
            # this was found.
            for index, sentence in enumerate(speech.clips(said), start=1):
                yield {
                    "kind": "quest",
                    "id": quest_id,
                    "field": field,
                    "sentence": index,
                    "path": naming.quest_path(quest_id, field, index),
                    "text": sentence,
                    "hash": text_hash(sentence),
                }


def word_lines(path):
    seen = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = ENTRY.match(raw)
        if not match:
            continue
        # The builder escapes only backslash, quote and the line breaks, and no
        # key in the pack contains any of them -- keys are words. So the capture
        # is the key, verbatim.
        key, word = match.group(1), match.group(2)
        if key in seen:
            continue
        seen.add(key)
        # The word is spoken as it is written, not as the key spells it: the key
        # is casefolded and turns the eszett into ss, which is a lookup device,
        # not German.
        said = speech.clean(word) or word
        yield {
            "kind": "word",
            "key": key,
            "path": naming.word_path(key),
            "text": said,
            "hash": text_hash(said),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quests", default=str(DEFAULT_QUESTS))
    ap.add_argument("--words", default=str(DEFAULT_WORDS))
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--only", choices=("quest", "word"), help="plan one kind only")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    lines = []
    if args.only != "word":
        quests = pathlib.Path(args.quests)
        if not quests.exists():
            sys.exit("no quest corpus at %s -- build it in the dictionary repo first" % quests)
        lines += list(quest_lines(quests))
    if args.only != "quest":
        words = pathlib.Path(args.words)
        if not words.exists():
            sys.exit("no dictionary at %s" % words)
        lines += list(word_lines(words))

    # What a previous plan recorded, so a rewritten quest can be told from one
    # that was simply never generated.
    known = {}
    if LINES.exists():
        for raw in LINES.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                row = json.loads(raw)
                known[row["path"]] = row["hash"]

    sounds = pathlib.Path(args.sounds)
    missing, stale, done = [], [], 0
    for row in lines:
        clip = sounds / row["path"].replace("sounds/", "", 1)
        if not clip.exists():
            missing.append(row)
        elif known.get(row["path"]) != row["hash"]:
            stale.append(row)
        else:
            done += 1

    chars = sum(len(r["text"]) for r in lines)
    todo = sum(len(r["text"]) for r in missing + stale)
    print("planned   %7d clips  (%d quest passages, %d words)"
          % (len(lines), sum(1 for r in lines if r["kind"] == "quest"),
             sum(1 for r in lines if r["kind"] == "word")))
    print("generated %7d" % done)
    print("missing   %7d" % len(missing))
    print("stale     %7d  (the German text changed under an existing clip)" % len(stale))
    # Fifteen characters a second is German read at an unhurried pace, which is
    # what this pack is for.
    print("to speak  %7.1f hours of audio, of %.1f in the whole pack"
          % (todo / 15 / 3600, chars / 15 / 3600))

    if args.write:
        LINES.parent.mkdir(parents=True, exist_ok=True)
        with LINES.open("w", encoding="utf-8") as fh:
            for row in lines:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("wrote %s" % LINES)
    else:
        print("(report only -- pass --write to record the plan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
