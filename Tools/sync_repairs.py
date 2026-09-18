#!/usr/bin/env python3
"""Carry repaired word clips from the engine's corpus into the Words pack repo.

    python Tools/sync_repairs.py --dry-run
    python Tools/sync_repairs.py
    python Tools/sync_repairs.py --report worklist_report.jsonl --report jfix_report.jsonl
    python Tools/sync_repairs.py --version 1.0.7

WHY A TOOL, AND WHY ONLY "fixed"

The repair tools (fix_word_edges.py, fix_initial_j.py, respeak_bad.py) write
into the engine's sounds/, which is the master corpus and ships nowhere. The
pack that players install is a separate repository with its own copy of every
clip, and until now the repaired ones were carried across by hand -- forty-one
files for 1.0.6, out of a hundred thousand that look exactly alike. A hand copy
of 2,650 is where one goes missing and nobody notices, because a clip that did
not arrive still plays: the old recording, with the defect the repair removed.

So the list comes from the repair's own report, and only rows it marked
"fixed". An "unsettled" row is a clip every take failed on; the tool left the
file as it was, and this leaves the pack's copy as it was. Checked rather than
trusted: --dry-run also reports any unsettled clip whose engine copy differs
from the pack's, which would mean a repair tool wrote a take it did not pass.

EVERY COPY IS READ BACK

The file written to the pack is reopened and compared byte for byte with the
source before it counts. A copy that fails that comparison is reported and the
run exits non-zero -- the same rule pack_release.py keeps for archives, for the
same reason: a listing cannot tell a good copy from a truncated one, and the
question that matters is what is on disk at the end.

Nothing here touches git. The pack repository shows the copies as modified
files, and the commit is a decision made by the owner, not by a tool.
"""

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK = ROOT.parent / "WordHunterWoW-Voice-DE-Words"
CLIP = re.compile(r"^sounds/w/[0-9a-f]{2}/[0-9a-f]{16}\.ogg$")


def rows_of(report):
    with open(report, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def outcomes(reports):
    """Path -> outcome, the last word a report had on each clip."""
    last = {}
    for report in reports:
        for row in rows_of(report):
            path = row.get("path")
            if path:
                last[path] = row.get("outcome")
    return last


def same_bytes(a, b):
    return a.read_bytes() == b.read_bytes()


def copy_verified(src, dst):
    """Write dst from src through a temp name, then read it back. True if it matches."""
    data = src.read_bytes()
    if not data.startswith(b"OggS"):
        return False, "source is not an Ogg file"
    partial = dst.with_name(dst.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, dst)
    if dst.read_bytes() != data:
        return False, "read back differs from the source"
    return True, ""


def set_version(version):
    """The version line in both of the pack's manifests. Refuses a no-op."""
    tocs = sorted(PACK.glob("WordHunterWoW-Voice-DE-Words_*.toc"))
    if not tocs:
        sys.exit("no manifests found under %s" % PACK)
    for toc in tocs:
        text = toc.read_text(encoding="utf-8-sig")
        found = re.search(r"^## Version:\s*(.+)$", text, re.M)
        if not found:
            sys.exit("%s has no Version line" % toc.name)
        if found.group(1).strip() == version:
            sys.exit("%s already says %s" % (toc.name, version))
        toc.write_text(text[:found.start(1)] + version + text[found.end(1):], encoding="utf-8")
        print("  %s: %s -> %s" % (toc.name, found.group(1).strip(), version))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="append", default=[],
                    help="a repair report (repeatable); default worklist_report.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="count and check, write nothing")
    ap.add_argument("--version", help="also set this version in both of the pack's manifests")
    ap.add_argument("--exclude", metavar="FILE",
                    help="paths to hold back, one per line -- clips a later check "
                         "(Tools/verify_repairs.py) faulted although the repair passed them")
    args = ap.parse_args()
    held = set()
    if args.exclude:
        with open(args.exclude, encoding="utf-8") as handle:
            held = {line.strip() for line in handle if line.strip()}
    reports = [ROOT / r for r in (args.report or ["worklist_report.jsonl"])]
    for report in reports:
        if not report.exists():
            sys.exit("no such report: %s" % report)
    if not PACK.is_dir():
        sys.exit("the Words pack is not checked out beside the engine: %s" % PACK)

    last = outcomes(reports)
    fixed = sorted(p for p, o in last.items() if o == "fixed")
    unsettled = sorted(p for p, o in last.items() if o == "unsettled")
    print("reports: %s" % ", ".join(r.name for r in reports))
    print("clips: %d fixed, %d unsettled, %d other" % (
        len(fixed), len(unsettled), len(last) - len(fixed) - len(unsettled)))

    # The invariant the repair tools promise: a clip they did not fix, they did
    # not touch. Reported, not repaired -- a difference here is a tool bug.
    touched = [p for p in unsettled if (PACK / p).exists() and not same_bytes(ROOT / p, PACK / p)]
    if touched:
        print("WARNING: %d unsettled clip(s) differ between engine and pack, e.g. %s" % (len(touched), touched[0]))

    to_copy, already, absent, odd = [], 0, [], []
    kept_back = [p for p in fixed if p in held]
    if kept_back:
        print("held back on request: %d" % len(kept_back))
    for path in fixed:
        if path in held:
            continue
        if not CLIP.match(path):
            odd.append(path)
            continue
        src, dst = ROOT / path, PACK / path
        if not src.exists():
            odd.append(path)
        elif not dst.exists():
            absent.append(path)
        elif same_bytes(src, dst):
            already += 1
        else:
            to_copy.append(path)
    print("of the fixed: %d to copy, %d already in the pack, %d not in the pack, %d odd" % (
        len(to_copy), already, len(absent), len(odd)))
    for path in absent[:5]:
        print("  not in the pack: %s" % path)
    for path in odd[:5]:
        print("  odd: %s" % path)

    if args.dry_run:
        print("dry run: nothing written")
        return 1 if odd else 0

    failed = []
    for index, path in enumerate(to_copy, 1):
        ok, why = copy_verified(ROOT / path, PACK / path)
        if not ok:
            failed.append((path, why))
        if index % 500 == 0:
            print("  %d/%d" % (index, len(to_copy)), flush=True)
    print("copied and read back: %d; failed: %d" % (len(to_copy) - len(failed), len(failed)))
    for path, why in failed[:10]:
        print("  FAILED %s: %s" % (path, why))
    if args.version and not failed:
        set_version(args.version)
    return 1 if (failed or odd) else 0


if __name__ == "__main__":
    sys.exit(main())
