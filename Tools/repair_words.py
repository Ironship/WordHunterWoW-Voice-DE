#!/usr/bin/env python3
"""Respeak word clips the reader rambled through, and keep the shortest take.

    python Tools/repair_words.py --dry-run
    python Tools/repair_words.py

WHAT IS WRONG

A word clip is one word and nothing else. "die" is three characters, and that is
the entire prompt the reader gets. Its own alignment analyser has almost nothing
to work on at that length -- Tools/speech.py keeps a thirty-character minimum
for quest clips because the same reader raises IndexError on input this short --
and rather than fail, it invents. What comes back is the word buried in several
seconds of confident German that is in no dictionary and was never asked for.

Measured over all 104,274 word clips, against the median duration of words the
same length:

    2 characters    52 of    208 ran past three times the median
    3 characters   141 of    771
    4 characters   266 of  2,431
    10 characters   55 of 10,446

1,652 in total, 1.6% -- concentrated exactly where it hurts, because the short
words are the articles and prepositions a learner clicks most. der, die, dem,
ein, er, in, zu, 'ne and ham were all among them.

WHY RESPEAKING WORKS

The reader samples. One word asked for five times came back at 0.88, 0.72, 4.56,
0.40 and 0.48 seconds -- four clean takes and one invention, from one prompt. So
this is not a property of the word; it is a die roll, and it can be rolled again.

Shortest wins, rather than "the first take under some threshold". A hallucination
adds material and never removes it, so the shortest take is the clean one by
construction -- which means nothing here has to decide how long "zu" ought to be.
A threshold would have to: generous enough not to reject a genuinely long word,
tight enough to catch a short one that rambled, and those two bounds cross
somewhere in the middle of the dictionary.

The floor is the exception to that. A take under a quarter of a second is not a
short word said briskly, it is a word cut off, and "shortest wins" would prefer
exactly that. Takes below the floor are dropped before the shortest is chosen,
and a word with nothing above the floor keeps the clip it already had.
"""
import argparse
import base64
import collections
import concurrent.futures
import io
import json
import pathlib
import statistics
import struct
import subprocess
import sys
import tempfile
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN = ROOT / "Data" / "lines.jsonl"
MODEL = "mistralai/Voxtral-4B-TTS-2603"
LOUDNESS = "loudnorm=I=-18:TP=-2"

# How many times a bad clip is asked for again. Five, because the sampling that
# causes this is also what cures it: a word failing one roll in five is clean
# after five rolls with probability 0.9997, and one failing four rolls in five --
# which is what the two-character words do -- still comes out at 0.999.
TAKES = 5

# A take shorter than this is a word cut off rather than a word said quickly.
# The shortest clean take measured anywhere in the corpus was 0.40s.
FLOOR = 0.25

# A clip longer than this many times the median for words of its length is taken
# to be the reader inventing. Three is deliberately loose: this is a detector,
# not a verdict, and everything it selects is then measured against its own fresh
# takes, which is where the decision actually gets made.
SUSPECT = 3.0


def ogg_seconds(path):
    """Length off the last Ogg page's granule position.

    Divided by the pack's own 24 kHz rather than by whatever the file says,
    because that is the rate every clip is supposed to carry -- so a file at
    some other rate comes out wrong here on purpose, loudly, instead of being
    silently accepted at a rate nothing else in the pack uses.
    """
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read()
    except OSError:
        return None
    at = tail.rfind(b"OggS")
    if at < 0:
        return None
    granule = struct.unpack("<q", tail[at + 6:at + 14])[0]
    return granule / 24000.0 if granule > 0 else None


def wav_seconds(raw):
    """Length of a RIFF/WAVE held in memory, without decoding it."""
    with wave.open(io.BytesIO(raw)) as handle:
        return handle.getnframes() / float(handle.getframerate())


def word_rows(plan):
    """The word half of the plan, with the voice and stamp the generator gives.

    Cast by importing the generator's own function rather than by writing
    de_female down here. The voice is half of a clip's stamp -- the other half
    is the text hash -- so a second answer to "who says this" would let a
    repaired clip claim to be current while carrying a different reader, and the
    next run would neither notice nor fix it.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from generate_voxtral import cast
    rows = []
    for line in io.open(plan, encoding="utf-8"):
        if '"word"' not in line:
            continue
        row = json.loads(line)
        if row.get("kind") == "word":
            rows.append(row)
    return cast(rows)


def suspects(rows, sounds):
    """The clips that ran long for the length of their word, with the median."""
    def measure(row):
        clip = sounds / row["path"].replace("sounds/", "", 1)
        return row, ogg_seconds(clip)

    lengths = collections.defaultdict(list)
    measured = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        for row, seconds in pool.map(measure, rows, chunksize=200):
            if seconds is not None:
                measured.append((row, seconds))
                lengths[len(row["text"])].append(seconds)

    medians = {}
    for size, values in lengths.items():
        if len(values) >= 20:
            medians[size] = statistics.median(values)

    out = []
    for row, seconds in measured:
        median = medians.get(len(row["text"]))
        if median and median > 0 and seconds > median * SUSPECT:
            out.append((row, seconds, median))
    out.sort(key=lambda item: len(item[0]["text"]))
    return out


def encode(raw, clip, quality):
    """WAV bytes to the ogg the pack ships, at the level every other clip is."""
    clip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(raw)
        source = handle.name
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", source,
             # -ac and -ar are not optional decoration. loudnorm resamples to
             # 192 kHz and leaves it there unless the output rate is named, so
             # without these the repaired clip is eight times the data rate of
             # every other clip in the pack -- and a granule position read
             # against the pack's 24 kHz then reports it as eight times as long,
             # which is how a repair that had worked read as a repair that had
             # done nothing. Copied from the generator's own encode, which has
             # always had them.
             "-af", LOUDNESS, "-ac", "1", "-ar", "24000",
             "-c:a", "libvorbis", "-qscale:a", str(quality),
             "-y", str(clip)],
            check=True)
    finally:
        pathlib.Path(source).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--takes", type=int, default=TAKES)
    ap.add_argument("--quality", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    rows = word_rows(PLAN)
    print("word clips in the plan: %d" % len(rows))
    bad = suspects(rows, sounds)
    print("ran long for their length: %d (%.1f%%)"
          % (len(bad), 100.0 * len(bad) / max(1, len(rows))))
    by_size = collections.Counter(len(row["text"]) for row, _, _ in bad)
    for size in sorted(by_size)[:8]:
        print("  %2d characters: %4d" % (size, by_size[size]))
    if args.limit:
        bad = bad[:args.limit]
    if args.dry_run:
        for row, seconds, median in bad[:15]:
            print("  %-16s %5.2fs against a median of %.2fs"
                  % (repr(row["text"]), seconds, median))
        print("dry run, nothing written")
        return 0
    if not bad:
        print("nothing to repair")
        return 0

    import httpx
    client = httpx.Client()
    try:
        client.get(args.server + "/health", timeout=10).raise_for_status()
    except Exception as exc:
        sys.exit("no reader at %s (%s)" % (args.server, type(exc).__name__))

    fixed = kept = failed = 0
    for index, (row, was, _median) in enumerate(bad, 1):
        payload = {
            "model": MODEL,
            "response_format": "wav",
            "items": [{"input": row["text"], "voice": row["voice"]}] * args.takes,
        }
        try:
            answer = client.post(args.server + "/v1/audio/speech/batch",
                                 json=payload, timeout=600)
            answer.raise_for_status()
            results = answer.json().get("results", [])
        except Exception as exc:
            failed += 1
            print("  ! %s: %s" % (repr(row["text"]), type(exc).__name__), flush=True)
            continue

        takes = []
        for result in results:
            if result.get("status") != "success":
                continue
            raw = base64.b64decode(result["audio_data"])
            seconds = wav_seconds(raw)
            if seconds >= FLOOR:
                takes.append((seconds, raw))
        if not takes:
            kept += 1
            continue
        takes.sort(key=lambda pair: pair[0])
        best, raw = takes[0]
        if best >= was:
            # Nothing shorter came back. Keeping what is there is the honest
            # answer: replacing a long clip with an equally long one spends a
            # write and changes nothing a listener would hear.
            kept += 1
            continue
        clip = sounds / row["path"].replace("sounds/", "", 1)
        encode(raw, clip, args.quality)
        clip.with_suffix(".hash").write_text(row["stamp"], encoding="utf-8")
        fixed += 1
        if index % 50 == 0 or index == len(bad):
            print("  %d/%d  fixed %d, kept %d, failed %d"
                  % (index, len(bad), fixed, kept, failed), flush=True)

    print("repaired %d clips, kept %d as they were, %d failed" % (fixed, kept, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
