#!/usr/bin/env python3
"""Respeak clips where the reader says German J as if it were English.

    ~/asr.sh Tools/fix_initial_j.py --bad jfix2.jsonl --report jfix2_report.jsonl

WHAT IS WRONG

German J is /j/ -- the sound English spells with a Y. The reader sometimes gives
it the English affricate instead, reading "Jade" as an English speaker would, and
"Jadewald" comes back as "Tschadewald". The owner heard it on that word; the
recogniser's own transcripts had it on fifty-nine, clustered on the Pandaria
jade names and on troll names beginning Jin-.

WHY respeak_bad.py IS THE WRONG TOOL FOR IT

It accepts a take at similarity >= 0.8 against the word. That is the right rule
for what it was built for -- a hallucinated sentence scores far below it -- and
exactly the wrong rule here, because this defect changes one phoneme. Measured on
the first pass: "Jadetempel" came back as "Schade-Tempel" and scored 0.818, so
the tool accepted the defect and wrote it down as fixed. Seven of its thirty-four
"fixes" were the same mispronunciation in a fresh take.

So this reuses all of that machinery -- the batch request, the recogniser, the
encoder, the report -- and replaces the one rule. Everything about how a clip is
written stays identical, which matters more than it sounds: the encoder is where
a resample to 192 kHz once slipped in unnoticed.

THE RULE

The transcript has to begin with a letter the recogniser uses for /j/: J, Y or I.
Nothing else is looked at for the initial. Similarity is kept as a floor rather
than a target, because half these words are invented names -- "Jin'Zil", "Jaloots"
-- which no recogniser spells the same way twice, and demanding 0.8 on those
would reject correct takes forever.
"""

import argparse
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import respeak_bad as rb

# How the recogniser writes a /j/ at the start of a German word. "I" is here
# because it writes "Jinyu" as "Inju" often enough to matter, and an initial I
# before a vowel is the same sound.
SOUNDS_LIKE_J = re.compile(r"^[jyi]", re.I)

# Low, and deliberately so: this rule is about the first sound, and the words
# that carry the defect are mostly invented names the recogniser respells freely.
# Its job is only to catch a take that is not the word at all.
FLOOR = 0.45


def initial(heard):
    """The first letter that carries a sound, past any quoting the ASR added."""
    text = unicodedata.normalize("NFC", str(heard or ""))
    return text.strip(" „“”\"'«».,!?-…")


def acceptable(want, heard, rescue=False):
    text = initial(heard)
    if not text:
        return False
    if not SOUNDS_LIKE_J.match(text):
        return False
    # The ramble check is still worth having: a take can begin with a correct J
    # and then carry on into a sentence nobody asked for.
    if rb.rambles(want, text):
        return False
    return rb.similarity(want, text) >= FLOOR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", default="jfix2.jsonl")
    ap.add_argument("--report", default="jfix2_report.jsonl")
    ap.add_argument("--takes", type=int, default=6,
                    help="more than respeak_bad's default: the defect is a die "
                         "roll and some words take several throws to come up J")
    ap.add_argument("--dry-run", action="store_true")
    known, rest = ap.parse_known_args()

    # The one rule, replaced. Everything downstream -- batching, listening,
    # encoding, the report -- is respeak_bad's own and is not touched.
    rb.acceptable = acceptable

    sys.argv = [sys.argv[0], "--bad", known.bad, "--report", known.report,
                "--takes", str(known.takes)] + rest
    if known.dry_run:
        sys.argv.append("--dry-run")
    return rb.main()


if __name__ == "__main__":
    sys.exit(main())
