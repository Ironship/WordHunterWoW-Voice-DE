#!/usr/bin/env python3
"""Put the pack's copy back into the engine for clips that will not ship.

    python Tools/restore_from_pack.py --paths held_sound.txt --paths held_back.txt --dry-run
    python Tools/restore_from_pack.py --paths held_sound.txt --paths held_back.txt

WHY THE ENGINE HAS TO BE PUT BACK

A repair pass writes its chosen take into the engine's sounds/ the moment it
accepts it; the pack gets that take only when Tools/sync_repairs.py carries it
across. A take accepted by the pass and then refused afterwards -- by
verify_repairs.py as too long, or by the stricter sieve over the sound-judged
pass -- is left standing in the engine while the pack keeps the old clip. Left
like that, the master corpus and the shipped pack disagree about a clip nobody
decided to ship, and the next tool to read the engine takes the refused take
for the truth. So the pack's copy is the one that stands, and it is copied
back.

Only clips whose engine and pack copies differ are touched, and every copy is
read back before it counts, as in sync_repairs.py.
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK = ROOT.parent / "WordHunterWoW-Voice-DE-Words"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", action="append", required=True, metavar="FILE",
                    help="clip paths to put back, one per line (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    wanted = set()
    for name in args.paths:
        with open(ROOT / name, encoding="utf-8") as handle:
            wanted |= {line.strip() for line in handle if line.strip()}
    same, absent, differ = 0, [], []
    for path in sorted(wanted):
        engine, pack = ROOT / path, PACK / path
        if not pack.exists():
            absent.append(path)
        elif engine.exists() and engine.read_bytes() == pack.read_bytes():
            same += 1
        else:
            differ.append(path)
    print("named: %d  already the pack's: %d  to put back: %d  not in the pack: %d"
          % (len(wanted), same, len(differ), len(absent)))
    if args.dry_run:
        for path in differ[:8]:
            print("  would restore %s" % path)
        return 0
    failed = 0
    for path in differ:
        data = (PACK / path).read_bytes()
        target = ROOT / path
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(data)
        partial.replace(target)
        if target.read_bytes() != data:
            failed += 1
            print("  FAILED %s" % path)
    print("put back: %d, failed: %d" % (len(differ) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
