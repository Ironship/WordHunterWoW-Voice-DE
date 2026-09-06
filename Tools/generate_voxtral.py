#!/usr/bin/env python3
"""Speak the planned lines with Voxtral, which runs as a server.

Start the reader first (inside WSL -- vllm has no Windows build):

    VLLM_USE_FLASHINFER_SAMPLER=0 \\
      ~/voxtral/.venv/bin/vllm serve mistralai/Voxtral-4B-TTS-2603 --omni --port 8000

then, from the same place:

    ~/voxtral/.venv/bin/python Tools/generate_voxtral.py --limit 64   # a pilot
    ~/voxtral/.venv/bin/python Tools/generate_voxtral.py              # the rest

Resumable by design. It is days of work and it will be interrupted: a reboot, a
power cut, someone wanting the card back. Nothing that matters is held in
memory, every clip is encoded and stamped before the run moves on, and a second
run picks up exactly where the first stopped.

Two things differ from the Chatterbox generator this replaces.

The reader is spoken to over HTTP, and it takes a whole batch in one request
with a voice named per item -- so a batch need not be all one speaker. Measured
on the model this replaced, batching was worth seven times the throughput and
stopped paying above sixteen: past that every clip in a batch waits for the
longest one in it, and the card runs out of memory.

And the voices are the model's own. Voxtral's open weights have the audio
encoder removed, so it cannot clone: the thirty-four references built from the
contributors' recordings are unusable here, and what is left is twenty-one
voices Mistral trained. Two of them are native German.
"""
import argparse
import base64
import concurrent.futures
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINES = ROOT / "Data/lines.jsonl"
QUEST_VOICE = ROOT / "Data/quest_voice.json"

MODEL = "mistralai/Voxtral-4B-TTS-2603"
# Who reads what. Voxtral has no gnome and no orc; it has a German man and a
# German woman, and the man chosen here is neutral_male rather than de_male
# because that is the one that was listened to and preferred.
BY_SEX = {"male": "neutral_male", "female": "de_female"}
# Every dictionary word, and every quest given by a book or a notice board.
DEFAULT_VOICE = "de_female"

# neutral_male came out at -37.5 LUFS and de_male at -24.3: thirteen decibels
# apart, which is the difference between a quest giver you can hear over the
# game and one you cannot. Every clip is brought to the same level, so the pack
# is uniform whoever is speaking.
LOUDNESS = "loudnorm=I=-18:TP=-2"

# How long to keep waiting for a reader that has stopped answering before
# writing the batch off. Long enough to cover a restart of the server and the
# minute it takes to load the weights; short enough that a reader which is never
# coming back does not hold the run open until morning.
RETRY_MINUTES = 20

# When to stop believing a reader that is still answering.
#
# The reader has a second way of failing, and it is the quiet one. It keeps
# answering /health, keeps accepting batches, keeps returning audio -- and takes
# thirty seconds over what took four. Measured during one occurrence: 236 clips
# a minute fell to 32 and stayed there, and nothing in this log said so, because
# every batch succeeded. The cause is below the reader and invisible to it; see
# Tools/voxtral_watchdog.sh, which is what acts on this.
#
# A batch of sixteen takes about four seconds on a healthy card, steady across
# three hours. Sixty is fifteen times that, further than any run of long quest
# text can explain, and well under the ten-minute ceiling on the request itself.
#
# Deliberately a fixed number rather than a multiple of the recent average. The
# fault arrives as a decay over about three minutes, and an average recomputed
# as it happens simply follows the damage down and falls silent exactly when it
# is wanted.
SLOW_BATCH_SECONDS = 60


def load_plan(only=None):
    if not LINES.exists():
        sys.exit("no plan at %s -- run Tools/plan_lines.py --write first" % LINES)
    rows = []
    for raw in LINES.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            row = json.loads(raw)
            if only is None or row["kind"] == only:
                rows.append(row)
    return rows


def cast(rows):
    """Name the voice for each line, and stamp it alongside the text hash.

    The stamp is what makes a clip current: change the German, or change who
    says it, and the clip is spoken again. Nothing else counts.
    """
    speakers = {}
    if QUEST_VOICE.exists():
        speakers = json.loads(QUEST_VOICE.read_text(encoding="utf-8"))
    for row in rows:
        voice = DEFAULT_VOICE
        if row.get("kind") == "quest":
            who = speakers.get(str(row.get("id")))
            if who:
                voice = BY_SEX.get(who.get("sex"), DEFAULT_VOICE)
        row["voice"] = voice
        row["stamp"] = "%s %s" % (row["hash"], voice)
    return rows


# Which packs to finish first, and why this is not simply release order.
#
# A zone is not a pack. Blizzard rewrote the old world in Cataclysm and its
# quests took new ids, so Loch Modan on a live realm is 42% Classic, 37%
# Cataclysm and 14% Wrath -- and a player levelling there with only the Classic
# pack hears fewer than half the quests they open. Which is how this was found:
# the first quest in the zone was 24469, a Cataclysm id in a Classic zone.
#
# Classic, Cataclysm and Wrath together cover 93% of that zone, so they go
# first. After them the order is the one the expansions were released in.
PRIORITY = ("Classic", "Cataclysm", "Wrath")


def in_release_order(rows):
    """The packs that cover the levelling world first, the dictionary last.

    The pack ships one addon per expansion, so the order clips are spoken in
    decides which addon can be released first. Left in plan order, Classic would
    only be complete once most of the corpus was, and there would be nothing to
    give anyone for a day and a half.

    The dictionary's hundred and four thousand words go last. They are a whole
    addon of their own and nothing in the quest packs waits on them.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from build_pack import EXPANSIONS

    order = {}
    for name in PRIORITY:
        order[name] = len(order)
    for name, _, _ in EXPANSIONS:
        if name not in order:
            order[name] = len(order)

    def rank(row):
        if row.get("kind") != "quest":
            return (len(order) + 1, 0, row.get("path", ""))
        qid = row.get("id") or 0
        for name, low, high in EXPANSIONS:
            if low <= qid <= high:
                return (order[name], qid, row.get("path", ""))
        # A quest with an id nobody's range claims, negative ids among them:
        # after the named expansions but before the dictionary.
        return (len(order), qid, row.get("path", ""))

    return sorted(rows, key=rank)


def outstanding(rows, sounds, force=False):
    """Clips that are missing, or whose text or speaker has changed since.

    The stamp lives beside its clip rather than in one index: an index is a
    single point of loss, and a run that dies partway would leave it describing
    a state that is no longer true.

    One walk of the tree, not two questions per planned clip. The generator runs
    under WSL against a folder on the Windows disk, and every individual stat
    crosses that boundary: asking about 333,045 clips twice over took so long
    that the first launch sat there with the card idle and had to be killed. A
    single walk costs one traversal, and only the clips that actually exist are
    then read for their stamp -- which at the start of a run is almost none.
    """
    if force:
        return list(rows)
    have = set()
    stamps = {}
    if sounds.exists():
        for path in sounds.rglob("*.ogg"):
            have.add(path.relative_to(sounds).as_posix())
        marks = list(sounds.rglob("*.hash"))

        def read(path):
            try:
                return (path.relative_to(sounds).with_suffix(".ogg").as_posix(),
                        path.read_text(encoding="utf-8").strip())
            except OSError:
                return None

        # Read in parallel. These are tiny files and the cost is not the reading
        # but the round trip: the generator runs under WSL against a folder on
        # the Windows disk, and each open crosses that boundary. Serially, 86,000
        # of them took eight minutes before a run could start -- and that number
        # grows with every clip spoken, so by the end of the pack it would be
        # half an hour every time the run was resumed.
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            for found in pool.map(read, marks):
                if found:
                    stamps[found[0]] = found[1]
    todo = []
    for row in rows:
        key = row["path"].replace("sounds/", "", 1)
        if key not in have or stamps.get(key) != row["stamp"]:
            todo.append(row)
    return todo


def encode(wav_bytes, clip, quality):
    """Level the loudness and write Ogg Vorbis, in one pass, without a temp file.

    Ogg because the WoW client plays it. Mono at quality 1 because the pack is
    the largest thing in the suite and, measured on real clips, quality 3 cost
    twelve and a half gigabytes across the pack where 1 costs eight, for speech
    at 24 kHz where no listener can tell them apart.
    """
    clip.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "wav", "-i", "pipe:0",
         "-af", LOUDNESS, "-ac", "1", "-ar", "24000",
         "-c:a", "libvorbis", "-qscale:a", str(quality), str(clip)],
        input=wav_bytes, check=True, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)


def speak(client, base, rows, timeout):
    """One request, one batch, a voice per item. Returns wav bytes per row."""
    payload = {
        "model": MODEL,
        "response_format": "wav",
        "items": [{"input": row["text"], "voice": row["voice"]} for row in rows],
    }
    answer = client.post(base + "/v1/audio/speech/batch", json=payload, timeout=timeout)
    answer.raise_for_status()
    body = answer.json()
    made = [None] * len(rows)
    for result in body.get("results", []):
        index = result.get("index", 0)
        if result.get("status") == "success" and 0 <= index < len(rows):
            made[index] = base64.b64decode(result["audio_data"])
    return made


def heartbeat(path, spoken, batch_seconds, done=False):
    """Write down how much has been spoken and when, for a supervisor to read.

    Counting the Ogg files is the honest measure of progress and it is the one
    used by hand, but it walks a tree that ends at a third of a million files
    across the Windows boundary. That is twenty seconds a look by the end of the
    pack, paid every time anything wants to know whether the run is alive, and
    it hammers the very crossing the run is already waiting on. The run knows
    the number without asking the disk, so it writes it down instead: one small
    file per batch, fifteen a minute.

    Written whole and moved into place, because a supervisor that read this file
    midway through a rewrite would see a torn line, conclude the run had died,
    and restart a reader that was working perfectly.

    The done flag is what tells a supervisor the difference between a run that
    finished and a run that was killed. Without it the two look identical from
    outside -- a process that is gone and a count that stopped moving -- and a
    supervisor would spend the night restarting a reader to speak nothing.
    """
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "spoken": spoken,
                                   "batch_seconds": round(batch_seconds, 2),
                                   "done": done}),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        # Bookkeeping never stops the speaking. A supervisor that loses sight of
        # the run says so loudly by itself; a run that died writing a status file
        # would be the more expensive of the two failures by far.
        print("  ! heartbeat: %s" % str(exc)[:120], flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--progress", default=str(ROOT / "voxtral.progress"),
                    help="where to record clips spoken, for a supervisor to read")
    ap.add_argument("--only", choices=("quest", "word"))
    ap.add_argument("--limit", type=int, default=0, help="stop after this many clips")
    # Sixteen: measured as the point where batching stops paying. Past it the
    # short clips in a batch sit waiting for the long one.
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--quality", type=int, default=1, help="vorbis qscale, 0-10")
    ap.add_argument("--first", help="a JSON list of quest ids to speak before the rest")
    ap.add_argument("--order", choices=("release", "plan"), default="release",
                    help="release: Classic first, then each expansion, dictionary last")
    ap.add_argument("--force", action="store_true", help="respeak clips already present")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    progress = pathlib.Path(args.progress)
    rows = cast(load_plan(args.only))
    if args.order == "release":
        rows = in_release_order(rows)
    todo = outstanding(rows, sounds, args.force)
    if args.first:
        # A week is a long time to wait to hear one zone. Named quests go to the
        # front; everything else keeps the order it had, so this changes when a
        # clip is spoken and never whether it is.
        #
        # In the order they are named, not merely ahead of the rest. The list is
        # one zone after another, and a player asking for Loch Modan first wants
        # Loch Modan finished first -- not its quests interleaved with two other
        # zones' by quest id.
        named = json.loads(pathlib.Path(args.first).read_text(encoding="utf-8"))
        rank = {}
        for position, quest in enumerate(named):
            rank.setdefault(int(quest), position)
        head = [r for r in todo if r.get("id") in rank]
        head.sort(key=lambda r: (rank[r["id"]], r.get("path", "")))
        todo = head + [r for r in todo if r.get("id") not in rank]
        print("first in the queue: %d clips from %d named quests" % (len(head), len(rank)))
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print("nothing to speak: every planned clip is present and current")
        heartbeat(progress, 0, 0.0, done=True)
        return 0

    counts = {}
    for row in todo:
        counts[row["voice"]] = counts.get(row["voice"], 0) + 1
    chars = sum(len(r["text"]) for r in todo)
    print("to speak: %d clips, %.1f hours of audio at an unhurried pace"
          % (len(todo), chars / 15 / 3600))
    print("cast: %s" % ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    if args.order == "release":
        # What is left in each pack, in the order they will be finished. The
        # first line is the one that matters: it says when there is something to
        # release.
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from build_pack import EXPANSIONS
        ranges = {name: (low, high) for name, low, high in EXPANSIONS}
        listed = list(PRIORITY) + [n for n, _, _ in EXPANSIONS if n not in PRIORITY]
        per, running = [], 0
        for name in listed:
            low, high = ranges[name]
            n = sum(1 for r in todo
                    if r.get("kind") == "quest" and low <= (r.get("id") or 0) <= high)
            if n:
                running += n
                per.append((name, n, running))
        words = sum(1 for r in todo if r.get("kind") != "quest")
        if words:
            running += words
            per.append(("Words", words, running))
        print("packs left, in the order they finish:")
        for name, n, cumulative in per:
            print("  %-16s %7d clips   done after %7d" % (name, n, cumulative))
    if args.dry_run:
        for row in todo[:5]:
            print("  %-46s %-14s %s" % (row["path"], row["voice"], row["text"][:40]))
        print("dry run, nothing written")
        return 0

    import httpx
    client = httpx.Client()
    try:
        client.get(args.server + "/health", timeout=10).raise_for_status()
    except Exception as exc:
        sys.exit("no reader at %s (%s)\nStart it with:  vllm serve %s --omni"
                 % (args.server, type(exc).__name__, MODEL))

    started, spoken, failed, stopped = time.time(), 0, 0, False
    # Encoding runs alongside the next batch: ffmpeg is cheap but there are
    # three hundred thousand of them, and the card should never wait for a disk.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = []
        for start in range(0, len(todo), args.batch):
            chunk = todo[start:start + args.batch]
            # A generous ceiling: a batch of sixteen ordinary clips takes well
            # under a minute, and one that takes ten is one worth abandoning.
            # Wait for the reader rather than racing past it. Without this a
            # reader that stops for a minute -- a restart, a driver reset -- is
            # answered by the queue being marked failed at several thousand
            # clips a minute, and a night's run ends with nothing generated and
            # no sign of why.
            made, waited, took = None, 0, 0.0
            while made is None:
                began = time.time()
                try:
                    made = speak(client, args.server, chunk, timeout=600.0)
                    # Only the call that worked. Timing from the top of the loop
                    # would fold the backoff into the figure and report a reader
                    # that was down for ten minutes as a slow one, which is a
                    # different fault wanting a different answer.
                    took = time.time() - began
                except KeyboardInterrupt:
                    print("\nstopped after %d clips -- run again to continue" % spoken)
                    stopped = True
                    break
                except Exception as exc:
                    if waited >= RETRY_MINUTES * 60:
                        failed += len(chunk)
                        print("  ! giving up on batch at %d after %d min: %s %s"
                              % (start, RETRY_MINUTES, type(exc).__name__, str(exc)[:140]),
                              flush=True)
                        break
                    pause = min(60, 5 * (2 ** min(waited // 30, 4)))
                    print("  ... reader unavailable (%s), waiting %ds"
                          % (type(exc).__name__, pause), flush=True)
                    time.sleep(pause)
                    waited += pause
            # Ctrl-C leaves the retry loop; only this leaves the run. Without
            # it the break above fell through to "no batch, take the next one"
            # and the interrupt skipped a single batch of sixteen -- so stopping
            # a run of a quarter of a million clips meant one Ctrl-C per batch.
            # Falling out here rather than exiting: the drain below still waits
            # for the encodes already in flight and stamps them, so the clips
            # this batch paid for are on disk and the resume skips them.
            if stopped:
                break
            if made is None:
                continue
            if took > SLOW_BATCH_SECONDS:
                print("  ! slow batch at %d: %.0fs for %d clips, against about "
                      "4s healthy. The reader is answering and not working."
                      % (start, took, len(chunk)), flush=True)

            for row, wav in zip(chunk, made):
                if wav is None:
                    failed += 1
                    print("  ! no audio: %s" % row["path"])
                    continue
                clip = sounds / row["path"].replace("sounds/", "", 1)
                pending.append((pool.submit(encode, wav, clip, args.quality), row, clip))

            # Retire finished encodes and stamp them. The stamp is written only
            # once the clip is on disk, so an interrupted run never leaves a clip
            # claiming to be current when it is not.
            still = []
            for future, row, clip in pending:
                if not future.done():
                    still.append((future, row, clip))
                    continue
                try:
                    future.result()
                    clip.with_suffix(".hash").write_text(row["stamp"], encoding="utf-8")
                    spoken += 1
                except Exception as exc:
                    failed += 1
                    print("  ! encode %s: %s" % (row["path"], str(exc)[:160]))
            pending = still
            heartbeat(progress, spoken, took)

            done = start + len(chunk)
            if done % (args.batch * 20) < args.batch:
                rate = spoken / (time.time() - started) if spoken else 0
                left = (len(todo) - done) / rate / 3600 if rate else 0
                print("  %d/%d clips, %.1f/min, about %.1f hours left"
                      % (done, len(todo), rate * 60, left), flush=True)

        for future, row, clip in pending:
            try:
                future.result()
                clip.with_suffix(".hash").write_text(row["stamp"], encoding="utf-8")
                spoken += 1
            except Exception as exc:
                failed += 1
                print("  ! encode %s: %s" % (row["path"], str(exc)[:160]))

    minutes = (time.time() - started) / 60
    print("spoke %d clips, %d failed, in %.1f minutes (%.1f/min)"
          % (spoken, failed, minutes, spoken / minutes if minutes else 0))
    # Not done if someone stopped it. A supervisor told the work had finished
    # would go quiet for the night with a quarter of the pack unspoken.
    heartbeat(progress, spoken, 0.0, done=not stopped)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
