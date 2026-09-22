#!/usr/bin/env python3
"""Re-encode the quest audio small enough for CurseForge, into a tree of its own.

    python Tools/transcode_packs.py --dry-run
    python Tools/transcode_packs.py                 # all eleven expansions
    python Tools/transcode_packs.py --only Cataclysm --workers 6

WHY

Three approved CurseForge projects hold about 3,500 MB between them at the
largest file the site is proven to serve; the quest audio is 5,246 MB.
Measured on 250 real clips: zipping harder saves 2%, a solid archive would
save 13% and is not an installable format, and no Vorbis setting saves enough
-- 16 kHz Vorbis is still 4,024 MB. MP3 at 24 kbps is 3,091 MB, three files of
about 1,030 MB, and it is the first setting that fits. At 16 kHz the encoder
only accepts 8, 16, 24 and 32 kbps, so 20, 12 and 10 round down; 24 kbps keeps
24 kHz sampling and costs nothing for it, because bitrate decides the size.

MANY CLIPS PER FFMPEG, NOT ONE

One process per clip ran at 16 clips a second and would have taken six hours:
these files are five kilobytes and starting the process costs more than
encoding them. ffmpeg takes many inputs and many outputs in one call, and that
same work runs at 147 a second -- nine times faster, with output identical to
the byte. Batches of sixty, several at once.

A batch that fails is retried one clip at a time, so a single bad file names
itself instead of taking sixty good ones down with it.

WHAT IT DOES NOT TOUCH

The pack repositories. This reads them and writes somewhere else entirely, so
the masters -- the full-quality Vorbis the GitHub downloads ship and every
repair pass writes to -- cannot be damaged by a bad run. Re-running is safe: a
clip already transcoded and newer than its source is skipped, so an
interrupted run continues rather than starting over.

TRANSCODING IS LOSSY ON TOP OF LOSSY

These sources are already Vorbis. 24 kbps MP3 made from them is worse than 24
kbps encoded from the original speech, and regenerating 237,000 clips from the
reader is hundreds of GPU hours. The full-quality packs stay; this is the copy
that fits.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPOS = ROOT.parent
# One tree per setting, so a second run at another bitrate neither overwrites
# the first nor is skipped as "already done" -- the resume check compares
# timestamps, which cannot tell 24 kbps from 16.
def out_dir(kbps):
    return REPOS.parent / ("voice-mp3-%dk" % kbps)
ENGINE = "WordHunterWoW-Voice-DE"
BATCH = 60

EXPANSIONS = ["Classic", "BurningCrusade", "Wrath", "Cataclysm", "Pandaria", "Draenor",
              "Legion", "Azeroth", "Shadowlands", "Dragonflight", "WarWithin"]

# Below normal, so a run in the background does not make the machine unpleasant
# to use. The owner stops jobs that do.
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0


def opts(kbps, rate):
    return ["-c:a", "libmp3lame", "-b:a", "%dk" % kbps, "-ar", str(rate), "-ac", "1",
            "-map_metadata", "-1"]


def spawn(pairs, kbps, rate):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for src, _dst in pairs:
        cmd += ["-i", str(src)]
    for i, (_src, dst) in enumerate(pairs):
        cmd += ["-map", "%d:a" % i] + opts(kbps, rate) + [str(dst)]
    kw = {"creationflags": BELOW_NORMAL} if os.name == "nt" else {}
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)


def one_at_a_time(pairs, kbps, rate):
    """A batch that failed, retried singly, so the bad clip names itself."""
    bad = []
    for src, dst in pairs:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
                           + opts(kbps, rate) + [str(dst)], capture_output=True, text=True)
        if r.returncode:
            bad.append((src, r.stderr.strip()[:120]))
    return bad


def work(name, kbps, rate, workers, dry, out):
    src_root = REPOS / ("%s-%s" % (ENGINE, name)) / "sounds"
    if not src_root.is_dir():
        sys.exit("%s: no sounds/ -- is the audio checked out?" % name)
    dst_root = out(name)
    every = sorted(src_root.rglob("*.ogg"))
    todo = []
    for src in every:
        dst = dst_root / src.relative_to(src_root).with_suffix(".mp3")
        if dst.is_file() and dst.stat().st_size > 0 and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        todo.append((src, dst))
    if dry:
        print("%-16s %6d clips, %6d to do" % (name, len(every), len(todo)))
        return 0, 0

    for _src, dst in todo:
        dst.parent.mkdir(parents=True, exist_ok=True)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    running, done, started, failures = [], 0, time.time(), []
    while batches or running:
        while batches and len(running) < workers:
            pairs = batches.pop(0)
            running.append((spawn(pairs, kbps, rate), pairs))
        for entry in running[:]:
            proc, pairs = entry
            if proc.poll() is None:
                continue
            running.remove(entry)
            if proc.returncode:
                failures.extend(one_at_a_time(pairs, kbps, rate))
            done += len(pairs)
            if done % 6000 < BATCH:
                per_s = done / max(1e-6, time.time() - started)
                print("   %-14s %6d/%d  %4.0f clips/s  %4.1f min left" % (
                    name, done, len(todo), per_s,
                    (len(todo) - done) / max(per_s, 1e-6) / 60), flush=True)
        if running:
            time.sleep(0.02)

    made = sum(1 for _ in dst_root.rglob("*.mp3"))
    size = sum(f.stat().st_size for f in dst_root.rglob("*.mp3"))
    for src, err in failures:
        print("   FAILED %s: %s" % (src.name, err))
    if made != len(every):
        sys.exit("%s: %d clips in, %d out -- refusing to call that done" % (name, len(every), made))
    print("%-16s %6d clips  %7.0f MB  %4.1f min" % (
        name, made, size / 1e6, (time.time() - started) / 60), flush=True)
    return made, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one expansion, or a comma-separated list")
    ap.add_argument("--kbps", type=int, default=24)
    ap.add_argument("--rate", type=int, default=24000)
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel ffmpeg calls, each doing %d clips" % BATCH)
    ap.add_argument("--out", help="where to write; the default is one tree per bitrate")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    names = EXPANSIONS if not args.only else [n.strip() for n in args.only.split(",")]
    unknown = [n for n in names if n not in EXPANSIONS]
    if unknown:
        sys.exit("not an expansion: %s" % ", ".join(unknown))
    root = pathlib.Path(args.out) if args.out else out_dir(args.kbps)
    root.mkdir(parents=True, exist_ok=True)
    print("mp3 %d kbps at %d Hz, %d x %d clips per call, into %s\n"
          % (args.kbps, args.rate, args.workers, BATCH, root))
    clips = size = 0
    t0 = time.time()
    for name in names:
        c, s = work(name, args.kbps, args.rate, args.workers, args.dry_run,
                    lambda n: root / n / "sounds")
        clips += c
        size += s
    if not args.dry_run:
        print("\n%d clips, %.0f MB total, %.1f min" % (clips, size / 1e6, (time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
