#!/usr/bin/env python3
"""Measure what re-encoding and edge-trimming would actually save, on a sample.

    python Tools/size_probe.py --sample 200

Answers "can the packs be made smaller" with numbers from these clips rather
than from a codec's brochure. Two levers are tried:

  quality  -- Vorbis at lower -q settings. The clips ship at about 30 kbps
              mono, which is already near the codec's floor for speech, so the
              gain from going lower is expected to be modest and the cost
              audible. Measured rather than assumed.
  trim     -- silence at the head and tail of each clip, which the reader
              leaves and the pack carries 341,538 times over. Measured with
              ffmpeg's silencedetect at -40 dB.

Nothing here writes into sounds/. Every re-encode goes to a temp folder and is
deleted; the only output is the numbers.
"""

import argparse
import json
import pathlib
import random
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def silence_edges(path):
    """Seconds of silence at the head and tail, by silencedetect."""
    out = run("ffmpeg", "-hide_banner", "-i", str(path),
              "-af", "silencedetect=noise=-40dB:d=0.05", "-f", "null", "-").stderr
    dur = run("ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(path)).stdout.strip()
    try:
        total = float(dur)
    except ValueError:
        return None, None, None
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    head = 0.0
    if starts and starts[0] <= 0.01 and ends:
        head = ends[0]
    tail = 0.0
    if starts and (not ends or len(ends) < len(starts)):
        tail = total - starts[-1]
    return total, head, tail


def encoded_size(src, quality, tmp):
    dst = tmp / ("q%s_%s" % (quality, src.name))
    r = run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-c:a", "libvorbis", "-q:a", str(quality), "-ar", "24000", "-ac", "1", str(dst))
    if r.returncode != 0 or not dst.exists():
        return None
    size = dst.stat().st_size
    dst.unlink()
    return size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--qualities", default="0,-1,-2")
    args = ap.parse_args()

    clips = sorted((ROOT / "sounds").rglob("*.ogg"))
    if not clips:
        sys.exit("no clips under sounds/")
    random.seed(args.seed)
    sample = random.sample(clips, min(args.sample, len(clips)))
    qualities = [float(q) for q in args.qualities.split(",")]
    print("clips in corpus: %d   sampled: %d" % (len(clips), len(sample)))

    original = sum(c.stat().st_size for c in sample)
    by_quality = {q: 0 for q in qualities}
    failed = 0
    total_dur = head_sil = tail_sil = 0.0
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for i, clip in enumerate(sample, 1):
            for q in qualities:
                s = encoded_size(clip, q, tmp)
                if s is None:
                    failed += 1
                else:
                    by_quality[q] += s
            dur, head, tail = silence_edges(clip)
            if dur is not None:
                total_dur += dur
                head_sil += head
                tail_sil += tail
            if i % 50 == 0:
                print("  %d/%d" % (i, len(sample)), flush=True)

    print()
    print("original (~q2, ~30 kbps):  %8.1f KB  100%%" % (original / 1024))
    for q in qualities:
        s = by_quality[q]
        print("re-encoded at -q %-4s       %8.1f KB  %5.1f%%" % (q, s / 1024, 100.0 * s / original))
    print()
    print("silence at edges: head %.1f s + tail %.1f s of %.1f s total = %.1f%% of every clip"
          % (head_sil, tail_sil, total_dur, 100.0 * (head_sil + tail_sil) / max(total_dur, 0.001)))
    if failed:
        print("(%d re-encodes failed)" % failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
