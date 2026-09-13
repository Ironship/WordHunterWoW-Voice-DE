#!/usr/bin/env python3
"""Re-judge the clips called unstable, by sound instead of by spelling.

    python Tools/rescore_settled.py            # report only
    python Tools/rescore_settled.py --write    # promote what qualifies

WHY THIS COSTS NOTHING TO RUN

Tools/settle_words.py records every transcript it heard, all eight or twenty-four
of them, next to the clip they came from. So the expensive half of the work --
speaking the word again and listening to each take -- is already done and on
disk. Only the judgement was wrong, and a judgement can be made again for free.

WHAT WAS WRONG WITH IT

It compared the takes letter by letter. For a word out of a German dictionary
that is fine, because the recogniser spells those the one way they are spelled.
For a name invented for a fantasy game there is no one way, and the recogniser
picks a different plausible spelling every time it is asked. Aithlyn came back as
Aislinn, Eislin, Etlin and Eithnen -- one sound, four spellings, a mean letter
similarity of 0.61, and a verdict of "the reader is unstable on this word" that
the evidence flatly contradicts.

Kölner Phonetik is the standard answer to exactly this in German, and it is
decisive here: Aislinn and Eislin both code to 0856. Identical. See
Tools/phonetic.py.

WHAT PROMOTION MEANS, AND WHAT IT DOES NOT

A promoted clip is marked confirmed, and confirmed writes nothing. The clip on
disk is left exactly as it is. The promotion is a statement about what is known
about it -- that the reader says the same thing every time, and that the clip on
disk is one of those same things -- not a change to it.

So a clip is only promoted when both hold:

    the takes agree with each other, phonetically, at or above the bar, and
    the clip already on disk agrees with them too.

The second condition is what keeps this honest. Takes that agree among
themselves while disagreeing with the clip would mean the clip is the odd one
out, and that is a reason to replace it, not to confirm it -- which needs audio
this tool does not have. Those stay unstable and are reported separately, so the
count of what still needs the reader is never quietly absorbed into the count of
what is fine.
"""
import argparse
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from phonetic import agreement, phonetic_similarity

# The bar for phonetic agreement. Not the same number as the letter bar and not
# a loosening of it: nine codes instead of twenty-six letters lifts every score,
# the floor included. 0.70 was chosen by matching recall -- it keeps the same
# 76.6% of known-stable clips that letters at 0.60 kept -- so nothing that
# passes today can start failing, and the cost is paid in a higher rate of
# accidental agreement between unrelated words, 1.85% against 0.53%.
AGREE = 0.70

# How close the clip on disk has to sound to what the takes agree on.
CONFIRM = 0.70


def read_jsonl(path):
    rows = []
    p = pathlib.Path(path)
    if not p.exists():
        return rows
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "settled.jsonl"))
    ap.add_argument("--agree", type=float, default=AGREE)
    ap.add_argument("--confirm", type=float, default=CONFIRM)
    ap.add_argument("--write", action="store_true",
                    help="write the promotions back into the report")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    rows = read_jsonl(args.report)
    if not rows:
        sys.exit("nothing in %s" % args.report)
    unstable = [row for row in rows if row.get("outcome") == "unstable"]
    print("report rows: %d, of them unstable: %d" % (len(rows), len(unstable)))
    if not unstable:
        return 0

    promoted, disagrees, still = [], [], []
    for row in unstable:
        heard = [text for text in row.get("heard", []) if text]
        if len(heard) < 2:
            still.append((row, 0.0))
            continue
        score, which = agreement(heard)
        if score < args.agree:
            still.append((row, score))
            continue
        consensus = heard[which]
        on_disk = phonetic_similarity(consensus, row.get("was", ""))
        if on_disk >= args.confirm:
            promoted.append((row, score, consensus, on_disk))
        else:
            disagrees.append((row, score, consensus, on_disk))

    print()
    print("stable by sound, and the clip on disk matches:   %d" % len(promoted))
    print("stable by sound, but the clip on disk does not:  %d" % len(disagrees))
    print("not stable even by sound:                        %d" % len(still))

    if args.show and promoted:
        print()
        print("promoted, with what the recogniser made of the same sound:")
        for row, score, consensus, _ in promoted[:args.show]:
            spellings = sorted(set(text for text in row["heard"] if text))[:4]
            print("   %-16s agreement %.2f  %s"
                  % (repr(row["word"]), score,
                     " / ".join(repr(s)[:18] for s in spellings)))
    if args.show and disagrees:
        print()
        print("stable but the clip on disk is the odd one out -- these need the reader:")
        for row, score, consensus, on_disk in disagrees[:args.show]:
            print("   %-16s takes agree %.2f on %-20r but disk says %r"
                  % (repr(row["word"]), score, consensus[:18],
                     (row.get("was") or "")[:24]))

    if not args.write:
        print()
        print("report only, nothing written -- pass --write to promote")
        return 0

    lift = {id(row): (score, consensus) for row, score, consensus, _ in promoted}
    out = []
    for row in rows:
        if id(row) in lift:
            score, consensus = lift[id(row)]
            row = dict(row, outcome="confirmed", agreement=round(score, 3),
                       kept=consensus, confirmed_by="phonetic")
        out.append(row)
    with io.open(args.report, "w", encoding="utf-8", newline="\n") as handle:
        for row in out:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print()
    print("promoted %d clips to confirmed in %s (no audio touched)"
          % (len(promoted), args.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
