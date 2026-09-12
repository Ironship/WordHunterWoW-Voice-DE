#!/usr/bin/env python3
"""Find clips encoded at anything but the pack's own rate, and put them right.

    python Tools/fix_rate.py --dry-run
    python Tools/fix_rate.py

Every clip in every pack is mono at 24 kHz. That is what Tools/generate_voxtral.py
writes, with "-ac 1 -ar 24000" spelled out in its ffmpeg call, and it is what the
addon's duration tables are counted in.

Tools/repair_words.py was written without those two flags, and ffmpeg's loudnorm
filter resamples to 192 kHz and stays there unless the output rate is named. So
1,649 repaired word clips came out at eight times the data rate of everything
around them. They sound right -- the client reads the rate from the header --
but they are eight times the size, and any tool that counts an Ogg granule
against the pack's 24 kHz reads them as eight times as long as they are. That is
exactly what happened: a repair that had worked was measured afterwards with the
pack's constant and read as a repair that had changed nothing.

Re-encoding rather than respeaking. The audio in these files is the good take
that the repair already found and there is no reason to roll the dice for it
again; a downsample to 24 kHz costs one more vorbis generation on speech that is
already encoded for 24 kHz playback, and keeps the clip that was chosen.
"""
import argparse
import concurrent.futures
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RATE = "24000"
LOUDNESS_FREE = ["-c:a", "libvorbis"]


def sample_rate(path):
    """The rate ffprobe reports, or None if it cannot be read."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    value = out.stdout.strip()
    return value if value else None


def reencode(path, quality):
    """Down to 24 kHz mono in place, through a temporary file beside it.

    Written beside rather than to a system temp and moved, so the replacement is
    a rename within one directory -- which cannot half-succeed and leave a clip
    that is neither the old one nor the new one.
    """
    staging = path.with_suffix(".resample.ogg")
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-ac", "1", "-ar", RATE, "-c:a", "libvorbis",
             "-qscale:a", str(quality), "-y", str(staging)],
            check=True)
        staging.replace(path)
        return True
    except Exception:
        staging.unlink(missing_ok=True)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--quality", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    clips = sorted(sounds.rglob("*.ogg"))
    print("clips on disk: %d" % len(clips), flush=True)

    wrong = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for clip, rate in zip(clips, pool.map(sample_rate, clips, chunksize=64)):
            if rate is not None and rate != RATE:
                wrong.append((clip, rate))

    print("not at %s Hz: %d" % (RATE, len(wrong)))
    if not wrong:
        print("nothing to fix")
        return 0
    rates = {}
    for _, rate in wrong:
        rates[rate] = rates.get(rate, 0) + 1
    for rate, count in sorted(rates.items()):
        print("  %s Hz: %d" % (rate, count))
    if args.dry_run:
        for clip, rate in wrong[:8]:
            print("  %s at %s Hz" % (clip, rate))
        print("dry run, nothing written")
        return 0

    done = failed = 0
    for index, (clip, _rate) in enumerate(wrong, 1):
        if reencode(clip, args.quality):
            done += 1
        else:
            failed += 1
            print("  ! %s" % clip, flush=True)
        if index % 200 == 0 or index == len(wrong):
            print("  %d/%d  fixed %d, failed %d" % (index, len(wrong), done, failed), flush=True)

    print("re-encoded %d clips, %d failed" % (done, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
