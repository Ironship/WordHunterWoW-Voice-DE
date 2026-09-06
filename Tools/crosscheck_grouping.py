#!/usr/bin/env python3
"""Write down how this side groups sentences into clips, for Lua to be held to.

    python Tools/crosscheck_grouping.py --count 4000
    lua tests/grouping.test.lua

The addon works out for itself which sentences each clip covers, rather than the
pack shipping that mapping: the text and the sentence splitter are already on
both sides, so deriving it costs nothing where shipping it would add a field to
every passage in every pack.

That only holds while the two agree. If Lua groups differently from
Tools/speech.py, the English panel highlights the wrong line while the German is
read -- and nothing raises, because both answers are well-formed. So the Python
writes its answer here and the Lua test is measured against it.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT.parent
QUESTS = SUITE / "WordHunterWoW-Dictionary-DE/Data/cache/quests_deDE.jsonl"
TESTS = ROOT / "tests"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import speech

# Record separators, chosen because no quest text contains them.
PASSAGE_END = "\x1e"
CLIP_END = "\x1f"

FIELDS = ("description", "progress", "completion")


def passages(limit):
    """Real passages, spread across the file rather than taken from the front."""
    if not QUESTS.exists():
        sys.exit("no quest text at %s" % QUESTS)
    rows = []
    with open(QUESTS, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            for field in FIELDS:
                said = speech.clean(record.get(field))
                if said.strip():
                    rows.append(said)
    step = max(1, len(rows) // limit)
    return rows[::step][:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=4000)
    args = ap.parse_args()

    chosen = passages(args.count)
    TESTS.mkdir(exist_ok=True)
    (TESTS / "_grouping_texts.txt").write_text(
        PASSAGE_END.join(chosen), encoding="utf-8")
    (TESTS / "_grouping_clips.txt").write_text(
        PASSAGE_END.join(CLIP_END.join(speech.clips(p)) for p in chosen),
        encoding="utf-8")
    total = sum(len(speech.clips(p)) for p in chosen)
    print("wrote %d passages, %d clips, to tests/_grouping_*.txt"
          % (len(chosen), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
