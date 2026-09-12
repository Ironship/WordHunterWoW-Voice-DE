#!/usr/bin/env python3
"""Listen to every word clip and say which ones do not contain their word.

    ~/asr/bin/python Tools/listen_words.py --limit 300      # a sample, to calibrate
    ~/asr/bin/python Tools/listen_words.py                  # all of them

WHY THIS EXISTS

Tools/repair_words.py finds bad clips by how long they run: a word of three
characters that takes four seconds is the reader inventing. That works, and it
agreed with the owner's ear on both sides of the line -- it flagged der, die,
von, ham and in, and left dass, Macht and dort alone, which he confirmed sound
fine. But it is a measurement of the shadow rather than of the thing. It cannot
see a clip that says the wrong word in the right amount of time, and it cannot
see one that was cut off, because it only looks for clips that are too long.

This asks a speech recogniser what each clip actually says, and compares that to
the word that was asked for. One measurement, all three faults: a clip that
rambles transcribes as far more than the word, a clip that says something else
transcribes as something else, and a clip that was cut off transcribes as a
fragment or as nothing.

WHAT A MISMATCH MEANS, AND WHAT IT DOES NOT

A recogniser given one German word with no sentence around it is working at its
worst: there is no context to disambiguate, and German has many near-homophones.
So a mismatch is evidence, not a verdict. The output separates them by shape,
because the shapes mean different things:

    heard nothing            the clip is silent or unintelligible
    heard much more          the reader rambled -- the strong signal
    heard something else     wrong word, or the recogniser mishearing
    heard a fragment         the clip was cut off

The first two are reliable. The third is the one to treat with suspicion, and it
is reported separately for that reason rather than folded into a single count.
"""
import argparse
import collections
import difflib
import io
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN = ROOT / "Data" / "lines.jsonl"

# Only letters matter for the comparison. The recogniser punctuates what it
# hears -- "Die." for die -- and casing is its own guess, not the clip's.
KEEP = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text):
    """Down to comparable letters, keeping the umlauts German needs."""
    text = unicodedata.normalize("NFC", str(text or ""))
    return KEEP.sub("", text).casefold()


def word_rows(plan):
    rows = []
    for line in io.open(plan, encoding="utf-8"):
        if '"word"' not in line:
            continue
        row = json.loads(line)
        if row.get("kind") == "word":
            rows.append(row)
    return rows


def similarity(want, heard):
    """How close the transcript is to the word, 0 to 1.

    The recogniser is given one German word with no sentence around it -- the
    hardest thing you can ask of it -- and this pack is full of proper nouns from
    a fantasy game. It hears them correctly and spells them its own way: Altumus
    as Althumus, arathischen as Aratischen, Bom-ben-los as BUMBENLOS,
    vierundzwanzig as 24. Letter-for-letter comparison calls every one of those a
    fault; in a sample of 300 that was 88 mismatches of which 57 were spelling
    alone. So the distance is measured instead, and carried into the output, so
    the line between a mishearing and a defect can be drawn on evidence rather
    than guessed at here.
    """
    return difflib.SequenceMatcher(None, normalise(want), normalise(heard)).ratio()


def classify(want, heard):
    """What shape of disagreement this is, if any."""
    a, b = normalise(want), normalise(heard)
    if not b:
        return "silent"
    if a == b:
        return "ok"
    # The word is in there with more around it: the reader carried on talking.
    if a and a in b:
        return "rambled" if len(b) > len(a) * 2 else "ok-ish"
    # Part of the word and nothing else: the clip stops early.
    if b and b in a:
        return "clipped"
    return "different"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "heard.jsonl"),
                    help="one line per clip: the word, what was heard, the verdict")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    sounds = pathlib.Path(args.sounds)
    rows = word_rows(PLAN)
    if args.limit:
        # Spread across the file rather than taken from the front, so the sample
        # is not all one letter of the alphabet.
        step = max(1, len(rows) // args.limit)
        rows = rows[::step][:args.limit]
    print("clips to listen to: %d" % len(rows), flush=True)
    # Resumed rather than restarted. Listening to the whole pack is seven hours,
    # and this machine went to sleep in the middle of a nine-hour generation run
    # once already -- a job that must begin again from nothing after that is a job
    # that never finishes. Every clip already in the output is skipped and new
    # ones are appended, so an interrupted run picks up where it stopped.
    done = set()
    heard_path = pathlib.Path(args.out)
    if heard_path.exists():
        for line in io.open(heard_path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["path"])
                except Exception:
                    pass
        if done:
            print("already heard: %d" % len(done), flush=True)
    rows = [row for row in rows if row["path"] not in done]
    print("left to hear: %d" % len(rows), flush=True)
    if not rows:
        print("nothing left to hear")
        return 0

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute)
    print("model up: %s on %s" % (args.model, args.device), flush=True)

    counts = collections.Counter()
    out = io.open(args.out, "a", encoding="utf-8", newline="\n")
    for index, row in enumerate(rows, 1):
        clip = sounds / row["path"].replace("sounds/", "", 1)
        if not clip.exists():
            counts["missing"] += 1
            continue
        try:
            # German is fixed rather than detected: every clip in this pack is
            # German, and detection on a single word is a coin toss that
            # sometimes lands on Dutch.
            segments, _ = model.transcribe(str(clip), language="de", beam_size=1,
                                           condition_on_previous_text=False)
            heard = " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            counts["failed"] += 1
            print("  ! %s: %s" % (row["text"], type(exc).__name__), flush=True)
            continue
        verdict = classify(row["text"], heard)
        counts[verdict] += 1
        out.write(json.dumps({"word": row["text"], "heard": heard,
                              "verdict": verdict, "path": row["path"],
                              "similarity": round(similarity(row["text"], heard), 3)},
                             ensure_ascii=False) + "\n")
        if index % 500 == 0:
            done = sum(counts.values())
            bad = counts["rambled"] + counts["different"] + counts["silent"] + counts["clipped"]
            print("  %d/%d  suspect %d (%.1f%%)" % (index, len(rows), bad,
                                                    100.0 * bad / max(1, done)), flush=True)
    out.close()

    total = sum(counts.values())
    print()
    print("heard %d clips" % total)
    for verdict in ("ok", "ok-ish", "rambled", "different", "clipped", "silent", "failed", "missing"):
        if counts[verdict]:
            print("  %-10s %6d  (%4.1f%%)" % (verdict, counts[verdict],
                                              100.0 * counts[verdict] / max(1, total)))
    print()
    print("written to %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
