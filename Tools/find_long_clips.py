#!/usr/bin/env python3
"""Find word clips that transcribe correctly and still run too long.

    python Tools/find_long_clips.py --ratio 1.8 --out breathfix.jsonl

THE DEFECT NO TRANSCRIPT SHOWS

The owner reported "mir" as sounding like the reader was out of breath. Its
settle record has sixteen takes -- "Mia", "E-mail-Bond, wo ich das nicht
zusammen habe", "Ich wünsche halt jeden Plech" -- and the pass kept the one the
recogniser wrote down as exactly "mir". That take is 1.12 s against a 0.56 s
median for three-letter words. The transcript is perfect and the audio has a
hesitation in it, because the recogniser drops hesitations rather than spelling
them.

So a clip can pass every check this project has and still be wrong: the settling
pass judged text, the filler rule reads text, and the similarity bar reads text.
Duration is the one signal that does not.

WHY 3x MISSED IT

Tools/repair_words.py already screens on duration, at three times the median.
That threshold was chosen for hallucinations, which run many times long -- a
two-second invention where a word takes half a second. A hesitation adds one
breath. "mir" is 2.0x and every clip like it sat under the bar.

WHAT IT CANNOT TELL APART

Length in characters is a poor predictor for anything that is not a word.
Murloc noises (Mlrgrlgr, mglrmlr), abbreviations (XXI, Ksk) and invented names
(Izk'tilak) are legitimately slow for their spelling, and at 1.8x they are most
of what comes back. They are filtered out here rather than left for a human to
wade through, and the dictionary is what does it: a word with an entry is a
word whatever its case, and none of those have one. Asking for lowercase
instead -- the first attempt -- threw away every German noun, "Euer" among
them.
"""

import argparse
import json
import pathlib
import re
import struct
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Which words count as words, answered by the dictionary rather than by their
# shape.
#
# The first version of this asked for lowercase letters only, on the reasoning
# that proper names start upper. German capitalises every noun, so that threw
# away most of the language: "Euer" -- the owner reported it, 2.4x the median
# and plainly wrong -- was filed as a name and never measured, and so were the
# 73,651 other clips this skipped.
#
# The dictionary knows. A word with an entry is a word whatever its case, and a
# murloc line, an abbreviation or an invented name has no entry, which is the
# same test the addon itself applies when it decides whether a word is worth
# offering to a learner.
def load_dictionary(path):
    known = set()
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for field in ("word", "key"):
            value = row.get(field)
            if isinstance(value, str) and value:
                known.add(unicodedata.normalize("NFC", value).lower())
    return known


# Still excluded whatever the dictionary says: anything with a digit or an
# apostrophe in it, which is an id or an invented name. The floor is three
# characters and not four, because "mir" is three and is the clip that started
# this -- at 1.12 s against a 0.56 s median it is as wrong as anything longer,
# and the dictionary is what keeps XXI and Ksk out, not the length.
SHAPE = re.compile(r"^[^\W\d_]{3,}$", re.U)

# A shout, a laugh or a murloc line: the same letter three times over. The
# dictionary holds these -- it was built from this corpus, so every noise the
# quests contain has an entry -- and they are legitimately slow.
# "AAAARRRRRGGGHHHHH" takes 7.4 s because it is seventeen characters of
# screaming, not because the reader hesitated.
# Built with chr(92) rather than written out. The backreference here has been
# eaten twice by the shells this file is edited through -- once leaving a
# literal backslash-1, once vanishing entirely and leaving "(.)", which
# matches every word and would have skipped the whole corpus in silence.
STRETCHED = re.compile("(.)" + chr(92) + "1" + chr(92) + "1", re.U)


def clip_seconds(path):
    """Length from the Ogg granule position: the last page, bytes 6-14, LE.

    Read from the tail rather than by decoding, because this runs over a hundred
    thousand files and decoding each one would take hours instead of minutes.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read()
    except OSError:
        return None
    at = tail.rfind(b"OggS")
    if at < 0 or at + 14 > len(tail):
        return None
    try:
        granule = struct.unpack("<q", tail[at + 6:at + 14])[0]
    except struct.error:
        return None
    return granule / 24000.0 if granule > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heard", default=str(ROOT / "heard.jsonl"))
    ap.add_argument("--medians", default=str(ROOT / "Data" / "word_seconds.json"))
    ap.add_argument("--ratio", type=float, default=1.8,
                    help="how many times the median for that word length counts as long")
    ap.add_argument("--out", default=str(ROOT / "breathfix.jsonl"))
    ap.add_argument("--wordlist", default=str(
        ROOT.parent / "WordHunterWoW-Dictionary-DE" / "Data" / "cache" / "wordlist_deDE.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    medians = json.loads(pathlib.Path(args.medians).read_text(encoding="utf-8"))

    # The table stops at fifteen characters, and German does not. Capping there
    # compared every compound against a fifteen-letter median, so
    # "Baumschrittaussenpostens" at twenty-three looked three times too slow
    # when it was merely long. Past the end the median is extrapolated at the
    # rate the table itself runs at -- 10 to 15 characters costs 0.24 s, so
    # 0.048 s a character -- which is a straight line through the data rather
    # than a number invented here.
    longest = max(int(k) for k in medians)
    slope = (medians[str(longest)] - medians["10"]) / (longest - 10)

    def expected(word):
        n = len(word)
        if not n:
            return None
        if n <= longest:
            return medians.get(str(n))
        return medians[str(longest)] + (n - longest) * slope

    known = load_dictionary(args.wordlist)
    print("dictionary: %d known words" % len(known))

    rows = []
    for line in pathlib.Path(args.heard).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if args.limit:
        rows = rows[:args.limit]
    print("clips to measure: %d" % len(rows))

    hits, measured, skipped = [], 0, 0
    for index, row in enumerate(rows, 1):
        word = unicodedata.normalize("NFC", str(row.get("word") or ""))
        if STRETCHED.search(word) or not SHAPE.match(word) or word.lower() not in known:
            skipped += 1
            continue
        due = expected(word)
        if not due:
            continue
        seconds = clip_seconds(ROOT / row["path"])
        if seconds is None:
            continue
        measured += 1
        if seconds >= due * args.ratio:
            hits.append({"word": word, "heard": row.get("heard", ""),
                         "verdict": "long", "path": row["path"],
                         "seconds": round(seconds, 2), "median": due,
                         "ratio": round(seconds / due, 2), "similarity": 0.0})
        if index % 20000 == 0:
            print("  %d/%d  measured %d, long %d" % (index, len(rows), measured, len(hits)),
                  flush=True)

    hits.sort(key=lambda h: -h["ratio"])
    with open(args.out, "w", encoding="utf-8") as fh:
        for hit in hits:
            fh.write(json.dumps(hit, ensure_ascii=False) + "\n")
    print("\nmeasured %d real words (%d skipped as names or noise)" % (measured, skipped))
    print("longer than %.1fx the median: %d -> %s" % (args.ratio, len(hits), args.out))
    for hit in hits[:15]:
        print("   %-20s %.2f s  (median %.2f, %.1fx)"
              % (hit["word"], hit["seconds"], hit["median"], hit["ratio"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
