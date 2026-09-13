#!/usr/bin/env python3
"""Read every repaired clip back off the disk and prove the repair is really there.

    ~/asr.sh Tools/verify_repairs.py

WHY THIS IS A SEPARATE STEP AND NOT A FLAG ON THE REPAIR TOOLS

Because the repair tools verify the take, and the take is not the file.

Tools/repair_words.py chose good audio for 1,649 clips and every one of them
landed on disk at 192 kHz, because its ffmpeg call was missing "-ar 24000" and
loudnorm resamples on its way through. The audio inside was the audio that had
been chosen. Everything the tool checked, it checked before the encode. Nothing
looked afterwards, so nothing noticed, and the pack shipped clips at eight times
the data rate of everything around them -- which then read as eight times too
long to any tool counting granule positions against the pack's own rate. The
conclusion drawn from that measurement was that the repair had done nothing.

So this asks the only question that matters at the end, of the only artefact that
matters: what does the file on disk say, and is it encoded the way the pack says
every clip is encoded. Both together, because they fail independently -- the
192 kHz clips said the right word.

WHAT COUNTS AS A PASS

    rate        mono, 24000 Hz. Not "close to": the addon's duration tables are
                counted in it.
    no ramble   the transcript is not several words where one was asked for.
                This is the fault that was reported and the fault being fixed,
                so it is the fault that has to be gone.

Saying the right word is deliberately not a pass condition here. The repair
tools already decided that, with more evidence than one transcription -- and for
a name like Cozzle no recogniser can settle it at all. Asking it again here would
only re-open a question that was answered better upstream.
"""
import argparse
import collections
import io
import json
import pathlib
import re
import struct
import subprocess
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
RATE = "24000"
KEEP = re.compile(r"[^\w]+", re.UNICODE)

# Data/word_seconds.json holds the median clip length for each word length,
# measured over all 104,274 word clips. A clip longer than this many times the
# median for its own length is the reader having invented something, whatever
# the transcript says.
SUSPECT = 3.0

# Words longer than the table goes. Nothing to compare against, so nothing is
# claimed about them.
def ceiling(table, word):
    median = table.get(str(len(word)))
    return median * SUSPECT if median else None


def normalise(text):
    return KEEP.sub("", unicodedata.normalize("NFC", str(text or ""))).casefold()


def rambles(want, heard):
    a, b = normalise(want), normalise(heard)
    return bool(a) and len(b) > max(len(a) * 3, len(a) + 12)


def durations(root):
    """The measured median length per word length, or an empty table."""
    path = root / "Data" / "word_seconds.json"
    if not path.exists():
        print("no %s -- lengths will not be checked" % path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ogg_seconds(path):
    """Length off the last Ogg page's granule position, at the pack's rate.

    Safe to divide by the pack's 24 kHz here because the rate is checked first
    and a clip at any other rate never reaches this.
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


def rewritten(root):
    """Every clip any pass claims to have written, by path, with its word.

    Taken from the reports rather than from file timestamps. A timestamp says
    something was written; the reports say what was meant to be written, which is
    the claim being tested. A clip a report claims and the disk does not have is
    a failure this should catch, and a timestamp scan never could.
    """
    out = {}
    for name in ("respoken.jsonl", "rescued.jsonl", "settled.jsonl"):
        for row in read_jsonl(root / name):
            if row.get("outcome") in ("fixed", "replaced", "forced"):
                out[row["path"]] = row["word"]
    return out


def rate_of(path):
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None, None
    parts = done.stdout.strip().split(",")
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--out", default=str(ROOT / "verified.jsonl"))
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--paths",
                    help="a file of clip paths to check instead of the ones the "
                         "repair passes claim to have written -- for asking "
                         "whether clips nobody repaired carry a fault anyway")
    ap.add_argument("--rate-only", action="store_true",
                    help="check the encoding and skip the listening")
    args = ap.parse_args()

    table = durations(ROOT)
    if args.paths:
        # Every clip in the plan, so a path can be checked whether or not any
        # pass ever wrote it. The question here is not "did the repair land"
        # but "is there a fault", which is worth asking of clips no repair
        # claimed: they were left alone on the strength of an argument, and an
        # argument is not a measurement.
        words = {}
        for line in io.open(ROOT / "Data" / "lines.jsonl", encoding="utf-8"):
            if '"word"' not in line:
                continue
            row = json.loads(line)
            if row.get("kind") == "word":
                words[row["path"]] = row["text"]
        wanted = [line.strip() for line in io.open(args.paths, encoding="utf-8")
                  if line.strip()]
        claims = {path: words[path] for path in wanted if path in words}
        print("named clips to check: %d" % len(claims), flush=True)
    else:
        claims = rewritten(ROOT)
        print("clips the repair passes claim to have written: %d" % len(claims), flush=True)

    sounds = pathlib.Path(args.sounds)
    rows = sorted(claims.items())
    if args.limit:
        rows = rows[:args.limit]

    done = {row["path"] for row in read_jsonl(args.out)}
    if done:
        print("  already verified: %d" % len(done), flush=True)
        rows = [pair for pair in rows if pair[0] not in done]
    print("  to verify: %d" % len(rows), flush=True)
    if not rows:
        print("nothing to verify")
        return 0

    ears = None
    if not args.rate_only:
        from faster_whisper import WhisperModel
        ears = WhisperModel(args.model, device=args.device, compute_type=args.compute)
        print("ears up: %s" % args.model, flush=True)

    out = io.open(args.out, "a", encoding="utf-8", newline="\n")
    counts = collections.Counter()
    faults = []
    for index, (path, word) in enumerate(rows, 1):
        clip = sounds / path.replace("sounds/", "", 1)
        if not clip.exists():
            counts["missing"] += 1
            faults.append((word, path, "the file is not there"))
            continue
        rate, channels = rate_of(clip)
        record = {"word": word, "path": path, "rate": rate, "channels": channels}
        if rate != RATE or channels != "1":
            counts["wrong rate"] += 1
            faults.append((word, path, "%s Hz, %s channel(s)" % (rate, channels)))
            record["fault"] = "encoding"
        else:
            # Length before transcript, because the transcript cannot see this
            # fault. A ten-second clip of "die die die die" transcribes as
            # "die", scores 0.8 against the word "de", and passes every test
            # that only reads text -- which is exactly how it got written.
            seconds = ogg_seconds(clip)
            record["seconds"] = round(seconds, 2) if seconds else None
            limit = ceiling(table, word)
            if seconds and limit and seconds > limit:
                counts["too long"] += 1
                faults.append((word, path, "%.2fs against a ceiling of %.2fs"
                               % (seconds, limit)))
                record["fault"] = "too long"
            elif ears is not None:
                segments, _ = ears.transcribe(str(clip), language="de", beam_size=1,
                                              condition_on_previous_text=False)
                heard = " ".join(segment.text for segment in segments).strip()
                record["heard"] = heard
                if rambles(word, heard):
                    counts["rambles"] += 1
                    faults.append((word, path, "still rambling: %r" % heard[:48]))
                    record["fault"] = "rambles"
                else:
                    counts["ok"] += 1
            else:
                counts["ok"] += 1
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if index % 250 == 0 or index == len(rows):
            print("  %d/%d  ok %d, wrong rate %d, too long %d, rambling %d, missing %d"
                  % (index, len(rows), counts["ok"], counts["wrong rate"],
                     counts["too long"], counts["rambles"], counts["missing"]),
                  flush=True)
    out.close()

    print()
    print("clips checked:  %d" % sum(counts.values()))
    print("  sound and at %s Hz: %d" % (RATE, counts["ok"]))
    print("  wrong encoding:     %d" % counts["wrong rate"])
    print("  too long:           %d" % counts["too long"])
    print("  still rambling:     %d" % counts["rambles"])
    print("  missing from disk:  %d" % counts["missing"])
    if faults:
        print()
        print("faults, by name:")
        for word, path, why in faults[:40]:
            print("   %-18s %-34s %s" % (repr(word), path, why))
        if len(faults) > 40:
            print("   ... and %d more, all in %s" % (len(faults) - 40, args.out))
    print()
    print("written to %s" % args.out)
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
