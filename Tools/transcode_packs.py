#!/usr/bin/env python3
"""Make resumable MP3 copies of external quest OGG masters, outside Git.

    python Tools/transcode_packs.py --dry-run
    python Tools/transcode_packs.py
    python Tools/transcode_packs.py --only Classic --workers 4

Reads <delivery>/audio/quests/<Expansion>/sounds/q/ and writes
<delivery>/work/audio/mp3-16k/<Expansion>/sounds/q/. --sources and --out
relocate those trees. Masters are never modified. The default release setting
is 16 kbps, 24 kHz, mono; other bitrates use separate output trees. Re-running
skips a nonempty output newer than its source. Word clips stay in Dictionary-DE.
Transcoding is lossy and needs ffmpeg. Audio generation and ASR are separate
steps. A failed batch is retried per clip, and missing outputs fail the run.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPOS = ROOT.parent
DELIVERY = REPOS.parent
SOURCES = DELIVERY / "audio" / "quests"
# One tree per setting, so a second run at another bitrate neither overwrites
# the first nor is skipped as "already done" -- the resume check compares
# timestamps, which cannot tell 24 kbps from 16.
def out_dir(kbps):
    return DELIVERY / "work" / "audio" / ("mp3-%dk" % kbps)
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
    src_root = SOURCES / name / "sounds"
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
    global SOURCES
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one expansion, or a comma-separated list")
    ap.add_argument("--kbps", type=int, default=16)
    ap.add_argument("--rate", type=int, default=24000)
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel ffmpeg calls, each doing %d clips" % BATCH)
    ap.add_argument("--out", help="where to write; the default is one tree per bitrate")
    ap.add_argument("--sources", default=str(SOURCES),
                    help="external masters: <Expansion>/sounds/q/...; never modified")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    SOURCES = pathlib.Path(args.sources).resolve()
    if args.workers < 1 or args.kbps < 1 or args.rate < 1:
        ap.error("workers, kbps and rate must be positive")

    names = EXPANSIONS if not args.only else [n.strip() for n in args.only.split(",")]
    unknown = [n for n in names if n not in EXPANSIONS]
    if unknown:
        sys.exit("not an expansion: %s" % ", ".join(unknown))
    root = pathlib.Path(args.out) if args.out else out_dir(args.kbps)
    if not args.dry_run:
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
