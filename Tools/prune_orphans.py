#!/usr/bin/env python3
"""Find clips on disk that the plan no longer asks for, and optionally remove them.

    python Tools/prune_orphans.py            # report
    python Tools/prune_orphans.py --write    # remove

The generator only ever adds. When a passage gets shorter -- a cleaning rule
changes, Blizzard rewrites a quest, a stage direction stops being spoken -- the
clip for the sentence that no longer exists stays where it was.

That is not harmless. Tools/build_pack.py reads the durations out of whatever
clips it finds, so an orphaned sentence six is shipped with a duration, and the
engine chains to it after sentence five and plays text nobody wrote any more.
The listener hears a sentence from a previous version of the quest.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINES = ROOT / "Data/lines.jsonl"


def wanted():
    if not LINES.exists():
        sys.exit("no plan at %s -- run Tools/plan_lines.py --write first" % LINES)
    paths = set()
    with open(LINES, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                paths.add(json.loads(line)["path"].replace("sounds/", "", 1))
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    if not sounds.is_dir():
        sys.exit("no audio at %s" % sounds)
    keep = wanted()

    orphans = []
    for clip in sounds.rglob("*.ogg"):
        if clip.relative_to(sounds).as_posix() not in keep:
            orphans.append(clip)

    print("%d clips on disk, %d planned, %d orphaned"
          % (sum(1 for _ in sounds.rglob("*.ogg")), len(keep), len(orphans)))
    for clip in orphans[:10]:
        print("  %s" % clip.relative_to(sounds).as_posix())
    if len(orphans) > 10:
        print("  ... and %d more" % (len(orphans) - 10))
    if not orphans:
        return 0
    if not args.write:
        print("(report only -- pass --write to remove)")
        return 0
    for clip in orphans:
        clip.unlink()
        # The stamp beside it describes a clip that is gone.
        stamp = clip.with_suffix(".hash")
        if stamp.exists():
            stamp.unlink()
    print("removed %d orphaned clips" % len(orphans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
