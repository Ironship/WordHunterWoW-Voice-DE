#!/usr/bin/env python3
"""Turn a play session on WoW Forever into work the pipeline can pick up.

    python Tools/harvest_delta.py                     # report only
    python Tools/harvest_delta.py --write             # also write the delta
    python Tools/harvest_delta.py --client "<path to SavedVariables>"

WHY THIS EXISTS

Forever has quests that are in no dictionary and on no recording. Their German
text is not in any file here -- Data/lines.jsonl holds exactly the 35,334
quests that already have clips and not one more -- and the client will not let
an addon dump its quest table. The only way to get that text is to walk up to
the quest giver with the harvest switched on, which writes it into
WordHunterWoWCorpus.

This reads that corpus and answers the two questions worth asking:

  * which quests are new, and how many clips would they need;
  * which words in them the dictionary does not cover yet.

With --write it also emits Data/lines-new.jsonl in exactly the shape
Data/lines.jsonl uses, so the generator can be pointed straight at it. Clip
paths and hashes come from Tools/naming.py, the same code the addon's
Naming.lua mirrors, so a clip lands where the engine will look for it.

HOW TO COLLECT

    /whw harvest on     then play, then    /whw harvest export

The switch is off by default and what it records is kept until it is exported
or cleared.
"""
import argparse
import json
import pathlib
import re
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REPOS = ROOT.parent
sys.path.insert(0, str(HERE))

import naming   # noqa: E402  -- the paths the engine looks for
import speech   # noqa: E402  -- the same cleaning and clip grouping
from plan_lines import text_hash  # noqa: E402  -- the manifest's own hash

DEFAULT_CLIENT = pathlib.Path(
    r"C:\Program Files (x86)\World of Warcraft\_classic_beta_"
    r"\WTF\Account\400243779#1\SavedVariables\WordHunterWoW.lua")

# What the harvest calls a passage against what a clip is filed under. Titles
# and objectives are collected for the dictionary but have never been voiced,
# so they are counted and not written. naming.SPOKEN_FIELDS is the authority on
# which three are ever voiced, and this refuses to run if that list moves.
VOICED = {"description": "description", "progress": "progress", "reward": "completion"}
assert set(VOICED.values()) == set(naming.SPOKEN_FIELDS), \
    "naming.SPOKEN_FIELDS has changed; this mapping has to change with it"
UNVOICED = ("title", "objectives")

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def corpus_entries(text):
    """Every {kind, id, text, flavor} the corpus holds, in file order.

    The saved-variables format is regular enough to read with a pattern: each
    entry is a brace block of quoted keys. Written as one pass over the blocks
    rather than a Lua parser, because the shape is fixed by Harvest.lua and a
    parser would be more to get wrong than the thing it replaces.
    """
    block = re.compile(r"\{([^{}]*)\}", re.S)
    field = re.compile(r'\["(\w+)"\]\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(-?\d+))')
    out = []
    for m in block.finditer(text):
        row = {}
        for f in field.finditer(m.group(1)):
            key, string, number = f.group(1), f.group(2), f.group(3)
            row[key] = string if string is not None else int(number)
        if "kind" in row and "text" in row and "id" in row:
            row["text"] = (row["text"].replace('\\"', '"')
                           .replace("\\n", "\n").replace("\\\\", "\\"))
            out.append(row)
    return out


def dictionary_words():
    """Every headword the German dictionary covers, folded for comparison."""
    words = set()
    path = REPOS / "WordHunterWoW-Dictionary-DE" / "Data" / "CuratedDE.jsonl"
    if not path.exists():
        return words
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for key in ("word", "headword", "key", "lemma"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    words.add(fold(value))
                    break
    return words


def fold(word):
    return unicodedata.normalize("NFC", word).lower()


def voiced_quests():
    """Quest ids that already have clips, straight out of the manifest."""
    ids = set()
    path = ROOT / "Data" / "lines.jsonl"
    if not path.exists():
        return ids
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") == "quest" and isinstance(row.get("id"), int):
                ids.add(row["id"])
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=str(DEFAULT_CLIENT),
                    help="the SavedVariables file the harvest wrote")
    ap.add_argument("--write", action="store_true",
                    help="write Data/lines-new.jsonl for the generator")
    ap.add_argument("--out", default=str(ROOT / "Data" / "lines-new.jsonl"))
    args = ap.parse_args()

    client = pathlib.Path(args.client)
    if not client.exists():
        sys.exit("no such file: %s" % client)
    text = read(client)
    if re.search(r"^WordHunterWoWCorpus\s*=\s*nil", text, re.M):
        sys.exit("WordHunterWoWCorpus is nil -- the harvest has never been on.\n"
                 "In game: /whw harvest on, play, then /whw harvest export.")

    start = text.find("WordHunterWoWCorpus = {")
    if start < 0:
        sys.exit("this file holds no corpus")
    entries = corpus_entries(text[start:])
    if not entries:
        sys.exit("the corpus is there but empty")

    already = voiced_quests()
    covered = dictionary_words()

    quests, unvoiced_passages, words_seen = {}, 0, {}
    for row in entries:
        kind, qid, passage = row["kind"], row["id"], row["text"]
        for w in WORD.findall(passage):
            if len(w) > 1:
                words_seen.setdefault(fold(w), w)
        if kind in UNVOICED:
            unvoiced_passages += 1
            continue
        field = VOICED.get(kind)
        if not field or not qid:
            continue
        quests.setdefault(qid, {})[field] = passage

    fresh = {q: f for q, f in quests.items() if q not in already}
    new_words = sorted(w for k, w in words_seen.items() if k not in covered)

    rows = []
    for qid in sorted(fresh):
        for field, passage in sorted(fresh[qid].items()):
            # Exactly what Tools/plan_lines.py does, by calling the same code.
            # Not sentences(): clips() joins a sentence too short to stand on
            # its own to its neighbour, so splitting any other way would number
            # the clips differently from every clip already recorded.
            said = speech.clean(passage)
            if not said:
                continue
            for index, sentence in enumerate(speech.clips(said), start=1):
                rows.append({
                    "kind": "quest", "id": qid, "field": field, "sentence": index,
                    "path": naming.quest_path(qid, field, index),
                    "text": sentence,
                    "hash": text_hash(sentence),
                })

    print("corpus:            %d passages" % len(entries))
    print("  quests in it:    %d" % len(quests))
    print("  already voiced:  %d" % (len(quests) - len(fresh)))
    print("  new:             %d" % len(fresh))
    print("  titles/objectives collected but never voiced: %d" % unvoiced_passages)
    print()
    print("clips the new quests would need: %d" % len(rows))
    print("words in the corpus:             %d distinct" % len(words_seen))
    print("  not covered by the dictionary: %d" % len(new_words))
    if new_words:
        print("  first few: %s" % ", ".join(new_words[:15]))
    print()
    if fresh:
        print("the new quests: %s" % ", ".join(str(q) for q in sorted(fresh)))

    if args.write and rows:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print()
        print("wrote %s (%d lines)" % (out, len(rows)))
    elif args.write:
        print()
        print("nothing new to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
