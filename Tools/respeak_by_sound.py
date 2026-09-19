#!/usr/bin/env python3
"""Respeak the clips the edge repair could not settle, judged by sound.

    ~/asr.sh Tools/respeak_by_sound.py --only unsettled_paths.txt
    ~/asr.sh Tools/respeak_by_sound.py --only unsettled_paths.txt --takes 8 --max-factor 2.5

WHAT WAS LEFT, AND WHY

Tools/fix_word_edges.py re-read 3,647 clips and settled 2,940 of them. The 707
it could not settle are, almost to a clip, names: Sahakk heard as "Sahak",
Uzjax as "Uziaks", VEIL as "W-I-I-L", Vrykuldame as "Wirkull Dame". Six takes
each, and not one accepted -- not because the reader failed, but because the
bar it had to clear was spelled. The recogniser is handed a sound that has no
spelling and invents one, and a fresh invention cannot score 0.8 against the
dictionary's. Tools/phonetic.py was written for exactly this on the stability
pass, and it puts every one of those pairs at 1.0 by sound.

WHAT THIS CHANGES, AND WHAT IT KEEPS

Only the bar at the end. The take still has to pass fix_word_edges.py's own
rules -- not clipped, no false start, nothing trailing, no hesitation -- and
those are spelled comparisons that still work on a name: a transcript that is
a substring of the word is still a clipped take whatever the word is. It still
has to not ramble. And it has to sit under the length ceiling respeak_bad.py
now carries (--max-factor), because a take the recogniser hears as the word
can still be the reader inventing around it; the 34 clips verify_repairs.py
held back on 2026-09-18 were exactly that.

So the only new leniency is: a take that sounds like the word is the word,
even when the recogniser spells it differently. That is the rule a listener
applies, and it is the rule the earlier pass was missing.

Murloc speech -- Mrlgmrlgmrl and its kin -- goes through the same gate. The
recogniser spells those as letters ("R.M.G.R.M.L.G."), and the phonetic code of
a string of consonants is the string of consonants, so a take that has the
right consonants in the right order passes; one that rambles, or runs past the
ceiling, does not.

Reads what respeak_bad.py reads, writes what it writes, resumes the way it
resumes. Everything except the judgement is respeak_bad's.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import respeak_bad as rb
import fix_word_edges as edges
from phonetic import phonetic_similarity
from settle_words import has_filler

ROOT = pathlib.Path(__file__).resolve().parent.parent

# How alike the Koelner codes of the word and the transcript must be. Below the
# 1.0 the stability pass measured on genuine name pairs, above the 0.75 that
# "Nehmt" heard as "Mitnehmt" scores -- a false start the edge rules catch on
# their own, but the margin says the bar is not what is catching it.
SOUND_BAR = 0.85


def by_sound(want, heard, rescue=False):
    """respeak_bad's original bar, with the spelling test given a second chance."""
    if rb.rambles(want, heard):
        return False
    if rb.similarity(want, heard) >= 0.8:
        return True
    return phonetic_similarity(want, heard) >= SOUND_BAR


def acceptable(want, heard, rescue=False):
    """fix_word_edges' rules, with one of them read by sound as well.

    The clipped rule says: a transcript that is a substring of the word is a
    take that lost part of it. On a name the recogniser also simplifies, that
    fires on nothing -- "Sahakk" heard as "Sahak" is the doubled letter gone
    from the spelling, not a sound gone from the audio. So a substring only
    counts as clipped here when the sounds differ too: "Rachenschuppe" is
    still a clipped "Drachenschuppe", because the D is a sound.
    """
    if edges.still_clipped(want, heard) and phonetic_similarity(want, heard) < 1.0:
        return False
    if edges.still_false_start(want, heard) or edges.still_trailing(want, heard):
        return False
    if has_filler(want, heard):
        return False
    return by_sound(want, heard, rescue)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", default=str(ROOT / "worklist.jsonl"))
    ap.add_argument("--report", default=str(ROOT / "sound_report.jsonl"))
    ap.add_argument("--takes", type=int, default=6)
    ap.add_argument("--max-factor", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true")
    known, rest = ap.parse_known_args()

    # The edge rules first, then this file's bar where the spelled one stood.
    rb.acceptable_original = by_sound
    rb.acceptable = acceptable

    sys.argv = [sys.argv[0], "--bad", known.bad, "--report", known.report,
                "--takes", str(known.takes), "--max-factor", str(known.max_factor)] + rest
    if known.dry_run:
        sys.argv.append("--dry-run")
    return rb.main()


if __name__ == "__main__":
    sys.exit(main())
