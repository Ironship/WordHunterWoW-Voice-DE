#!/usr/bin/env python3
"""Respeak clips that lose a sound off the front, or start before the word.

    ~/asr.sh Tools/fix_word_edges.py --build      # write the work list
    ~/asr.sh Tools/fix_word_edges.py              # repair it

TWO FAMILIES, ONE SHAPE

Both are damage at the edge of the clip rather than inside it, and both were
found by the listening pass and then left alone.

*Clipped* -- the recogniser heard part of the word and nothing else, so the
transcript is a substring of it. "Drachenschuppe" came back as "Rachenschuppe":
the D is simply not in the audio. 1,519 clips carry this verdict and not one of
them was ever repaired. Most are mild, 658 missing about a single sound, but 37
are down to under half the word -- "Wirbel" as "W.", "Bill" as "b".

*False start* -- the reader says something before the word and then says the
word, so the transcript ends with the word and is longer than it. "Nehmt" came
back as "Mitnehmt", which the owner heard as "Nehm Nehmt"; others are plainer,
"Abgebaut" as "Man. Abgebaut." 368 of these sit in the ok-ish bucket, which is
the bucket nothing ever looks at again.

WHY respeak_bad.py CANNOT BE POINTED AT THEM AS IT IS

Its rule is similarity >= 0.8 against the word. "Rachenschuppe" against
"Drachenschuppe" scores 0.963 -- one letter short of fourteen -- so it would
accept a fresh take with the same missing D and record it as repaired. That is
not a hypothetical: on the J-mispronunciation pass the same rule accepted seven
defects out of thirty-four, and they had to be found afterwards by re-judging
the report.

So the rule here keeps respeak_bad's own bar and adds the two conditions that
say the defect is still present. Everything else -- the batched request, the
recogniser, the report, the encoder -- is respeak_bad's and is untouched.
"""

import argparse
import json
import pathlib
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import respeak_bad as rb
from settle_words import has_filler

ROOT = pathlib.Path(__file__).resolve().parent.parent


def fold(text):
    """Compared without case, punctuation or spacing.

    Spaces go because German runs compounds together and the recogniser pulls
    them apart again: "Jade Wald" and "Jadewald" are the same audio, and a
    substring test that kept the space would call the first one clipped.

    Punctuation goes from inside as well as from the ends, and that is not
    tidiness. TRAILING_MIN counts characters, so a comma the recogniser wrote
    counted as material the reader had spoken: "beginnt, ähm," came out four
    characters longer than "beginnt" and was filed as a spurious word, while the
    same take without the comma would have been three and filed as harmless. The
    defect there is the hesitation, which has its own rule below; the comma was
    deciding which rule saw it.
    """
    text = unicodedata.normalize("NFC", str(text or ""))
    return "".join(c for c in text.lower()
                   if not unicodedata.category(c).startswith(("P", "Z", "C")))


def still_clipped(want, heard):
    w, h = fold(want), fold(heard)
    return bool(h) and h != w and h in w


def still_false_start(want, heard):
    w, h = fold(want), fold(heard)
    return bool(w) and h != w and h.endswith(w) and len(h) > len(w)


# How much has to follow the word before it counts as material nobody asked for.
#
# Four characters, and the number is the whole difficulty of this third family.
# The reader says the word and carries on -- "öffnet" came back as "Öffnet
# Anni." -- but the same shape, word plus a little more, is also what a plain
# inflection looks like: "ablehn" read as "ablehnen", "aben" as "Abend",
# "Abbau" as "Abbaue". Those are the reader saying the ordinary form of a
# clipped headword, and respeaking them would chase a difference of one letter
# forever.
#
# Measured over the 1,537 clips with anything at all after the word: 757 add one
# to three characters and 454 of those add exactly one. Everything at four or
# more is a word, not an ending. Counted in characters rather than in spaces,
# because the recogniser writes a hallucination without them often enough --
# "Ting" as "Ting-Darm-Tortes-Tennis", "Astrid" as "Astrid.DianneDuschlatz" --
# that a token count sorted those into the harmless pile.
TRAILING_MIN = 4


def still_trailing(want, heard):
    w, h = fold(want), fold(heard)
    return bool(w) and h.startswith(w) and len(h) - len(w) >= TRAILING_MIN


def acceptable(want, heard, rescue=False):
    if (still_clipped(want, heard) or still_false_start(want, heard)
            or still_trailing(want, heard)):
        return False
    # A hesitation the word does not itself contain. Its own rule rather than a
    # length one, because "ähm" is three characters and would sit under
    # TRAILING_MIN forever -- which is how "beginnt, ähm," only reached a repair
    # list at all: the comma made it four. settle_words.has_filler already knows
    # the difference between a hesitation in the take and a word that is one,
    # and the dictionary does hold ääh and Hmmmm.
    if has_filler(want, heard):
        return False
    return rb.acceptable_original(want, heard, rescue)


def build(out):
    """The work list, from the listening pass and what has been settled since."""
    def rows(name):
        path = ROOT / name
        if not path.exists():
            return []
        found = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    found.append(json.loads(line))
                except ValueError:
                    pass
        return found

    done = set()
    for name in ("settled.jsonl", "jfix_report.jsonl", "jfix2_report.jsonl"):
        done |= {r["path"] for r in rows(name) if r.get("path")}

    work = []
    for r in rows("heard.jsonl"):
        if r.get("path") in done:
            continue
        want, was = r.get("word"), r.get("heard")
        if r.get("verdict") == "clipped" and still_clipped(want, was):
            work.append(r)
        elif still_false_start(want, was):
            work.append(r)
        elif has_filler(want, was):
            work.append(r)
        elif still_trailing(want, was):
            # Not filtered by verdict, unlike the two above. This family is
            # split across ok-ish and rambled by a length bar -- twice the word
            # or not -- and that bar has nothing to do with whether a spurious
            # word is there. "Öffnet Anni." fell one character short of it.
            work.append(r)

    # Worst first, so an interrupted run has spent its time where it counted.
    # The measure is how much of the word survived: "Wirbel" heard as "W." is a
    # different kind of broken from a missing D, and the reader is more likely
    # to need several throws for it.
    work.sort(key=lambda r: len(fold(r.get("heard"))) / max(1, len(fold(r.get("word")))))
    with open(out, "w", encoding="utf-8") as f:
        for r in work:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("work list: %d clips -> %s" % (len(work), out))
    return len(work)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", default=str(ROOT / "edgefix.jsonl"))
    ap.add_argument("--report", default=str(ROOT / "edgefix_report.jsonl"))
    ap.add_argument("--takes", type=int, default=5)
    ap.add_argument("--build", action="store_true",
                    help="write the work list and stop")
    ap.add_argument("--dry-run", action="store_true")
    known, rest = ap.parse_known_args()

    if known.build:
        return 0 if build(known.bad) else 1

    # Kept so the added conditions narrow the existing bar rather than replace
    # it: a take still has to be the word and still has to not ramble.
    rb.acceptable_original = rb.acceptable
    rb.acceptable = acceptable

    sys.argv = [sys.argv[0], "--bad", known.bad, "--report", known.report,
                "--takes", str(known.takes)] + rest
    if known.dry_run:
        sys.argv.append("--dry-run")
    return rb.main()


if __name__ == "__main__":
    sys.exit(main())
