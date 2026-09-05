#!/usr/bin/env python3
"""Which NPC gives which quest, read from AllTheThings.

    python Tools/quest_givers.py --att "<AddOns>/AllTheThings" --write

Blizzard's Game Data API does not publish this. The quest endpoint returns a
title, a description, an area and rewards, and no quest giver; the creature
endpoint answers 404 for every quest-giver id tried against it. So it is read
from AllTheThings, which is MIT licensed and already installed.

Only the mapping is taken, and only at build time. Nothing from AllTheThings
reaches the addon: what ships is a voice assignment derived from it, which is
this project's own work. The attribution is in NOTICE.
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "Data/quest_givers.json"

# q(12345,{...qgs={678}...}) -- the quest id opens the record and the quest
# givers sit somewhere inside it. Read as two passes rather than one pattern:
# the records nest, so a single regex spanning from q( to qgs= would happily
# cross from one quest into the next.
QUEST = re.compile(r"\bq\((\d+),")
GIVERS = re.compile(r"\bqgs=\{([\d,]+)\}")


def parse(text):
    """Every quest id in the file, with the givers named inside its record."""
    found = {}
    starts = [(m.start(), int(m.group(1))) for m in QUEST.finditer(text)]
    for index, (start, quest_id) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        givers = GIVERS.search(text, start, end)
        if not givers:
            continue
        ids = [int(n) for n in givers.group(1).split(",") if n]
        if ids:
            found.setdefault(quest_id, [])
            for npc in ids:
                if npc not in found[quest_id]:
                    found[quest_id].append(npc)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--att", required=True, help="the AllTheThings addon folder")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    db = pathlib.Path(args.att) / "db"
    if not db.is_dir():
        sys.exit("no db directory under %s" % args.att)

    givers = {}
    files = sorted(db.rglob("*.lua"))
    for path in files:
        try:
            found = parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            print("  ! %s: %s" % (path.name, exc))
            continue
        for quest_id, ids in found.items():
            givers.setdefault(quest_id, [])
            for npc in ids:
                if npc not in givers[quest_id]:
                    givers[quest_id].append(npc)

    single = sum(1 for v in givers.values() if len(v) == 1)
    print("read %d files" % len(files))
    print("quests with a named giver: %d" % len(givers))
    print("  exactly one giver:       %d" % single)
    print("  more than one:           %d" % (len(givers) - single))

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({str(k): v for k, v in sorted(givers.items())},
                                  ensure_ascii=False), encoding="utf-8")
        print("wrote %s" % OUT)
    else:
        print("(report only -- pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
