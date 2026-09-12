#!/usr/bin/env python3
"""Turn what the recogniser heard into a list of clips worth respeaking.

    python Tools/heard_report.py
    python Tools/heard_report.py --bad bad.jsonl     # write the work list out

Tools/listen_words.py writes one line per clip: the word asked for, the words
heard, a verdict and a similarity between the two. This reads that and decides
which of them are actually defects.

WHY A SECOND STEP RATHER THAN A VERDICT IN THE FIRST

Because the first pass cannot know where the line goes, and neither could I
before seeing the numbers. A recogniser handed one German word with no sentence
around it is at its worst, and this pack is full of proper nouns from a fantasy
game. Measured on a calibration sample of 300 clips: 88 came back as "not the
word I asked for", and of those 57 differed only in spelling -- Altumus heard as
Althumus, arathischen as Aratischen, Bom-ben-los as BUMBENLOS, vierundzwanzig
written out as 24. Every one of those clips is fine.

So the line is drawn here, on the whole distribution, rather than guessed at in
the middle of a seven-hour run that would have to start again to move it.

WHAT COUNTS AS A DEFECT

    rambled     the word is in the transcript with much more around it. This is
                the failure the owner reported and the only one that is certain:
                the reader given three characters invents several seconds of
                confident German. No threshold judgement needed -- the word is
                there and so is the invention.

    silent      nothing was heard at all.

    far         heard something else, and not something else that sounds like it.
                Below the similarity floor. These are candidates rather than
                defects: some will be the recogniser losing a fight with a name
                no human would spell either.

Everything else -- a near-miss on spelling, a dropped final consonant, a name
transcribed phonetically -- is left alone. Those are the recogniser's limits
showing, not the pack's.
"""
import argparse
import collections
import io
import json
import pathlib
import re
import sys
import unicodedata

# Shared with Tools/listen_words.py: only letters compare, because the
# recogniser punctuates and capitalises to its own taste.
KEEP = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text):
    return KEEP.sub("", unicodedata.normalize("NFC", str(text or ""))).casefold()

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Below this, the transcript is not a spelling variant of the word -- it is a
# different word. Drawn from the calibration sample: at 0.8 and above the
# mismatches were spelling alone, between 0.5 and 0.8 they were arguable, and
# below 0.5 they were either genuinely wrong or a name the recogniser had no
# chance with. 0.5 keeps the list short enough to listen through.
FAR = 0.5


def load(path):
    rows = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heard", default=str(ROOT / "heard.jsonl"))
    ap.add_argument("--far", type=float, default=FAR)
    ap.add_argument("--bad", help="write the clips worth respeaking here")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    rows = load(args.heard)
    if not rows:
        sys.exit("nothing heard yet at %s" % args.heard)
    print("clips heard: %d" % len(rows))

    verdicts = collections.Counter(row.get("verdict", "?") for row in rows)
    for verdict, count in verdicts.most_common():
        print("  %-10s %6d  (%4.1f%%)" % (verdict, count, 100.0 * count / len(rows)))

    # Rambling is judged here rather than trusted from the verdict, because the
    # verdict calls it rambling only when the word itself survives in the
    # transcript with more around it. When the reader wanders far enough that the
    # recogniser never catches the word at all -- Abels coming back as "Aber das
    # Toetselnusswoertsen" -- that lands in "different" instead, which is where
    # the certain defects go to hide among the spelling noise. Length settles it:
    # a transcript several times the length of a single word is several words,
    # and the pack only ever asked for one.
    def rambling(row):
        if row.get("verdict") == "rambled":
            return True
        word, heard = normalise(row.get("word")), normalise(row.get("heard"))
        return bool(word) and len(heard) > max(len(word) * 3, len(word) + 12)

    certain = [r for r in rows if r.get("verdict") == "silent" or rambling(r)]
    seen = {id(r) for r in certain}
    far = [r for r in rows
           if id(r) not in seen and r.get("verdict") == "different"
           and float(r.get("similarity", 1)) < args.far]
    bad = certain + far

    print()
    print("defects, certain:      %5d  (rambled or silent)" % len(certain))
    print("candidates, far off:   %5d  (heard something else, similarity below %.2f)"
          % (len(far), args.far))
    print("worth respeaking:      %5d  (%.2f%% of the pack)"
          % (len(bad), 100.0 * len(bad) / len(rows)))

    if args.show:
        print()
        print("a look at the certain ones:")
        for row in certain[:args.show]:
            print("   %-20s heard %r" % (repr(row["word"]), row.get("heard", "")))
        if far:
            print()
            print("a look at the candidates:")
            for row in sorted(far, key=lambda r: float(r.get("similarity", 1)))[:args.show]:
                print("   %-20s heard %-24r similarity %.2f"
                      % (repr(row["word"]), row.get("heard", ""),
                         float(row.get("similarity", 0))))

    # How much of this the duration detector would have found on its own, which
    # is the question worth answering before trusting either of them again.
    by_length = collections.Counter(len(r["word"]) for r in certain)
    if by_length:
        print()
        print("certain defects by word length:")
        for size in sorted(by_length)[:10]:
            print("  %2d characters: %4d" % (size, by_length[size]))

    if args.bad:
        with io.open(args.bad, "w", encoding="utf-8", newline="\n") as out:
            for row in bad:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        print()
        print("work list written to %s (%d clips)" % (args.bad, len(bad)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
