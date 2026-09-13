#!/usr/bin/env python3
"""Settle the clips neither repair pass could decide, by asking the reader twice.

    ~/asr.sh Tools/settle_words.py --dry-run
    ~/asr.sh Tools/settle_words.py

Needs the reader up, same as Tools/respeak_bad.py.

THE PROBLEM THIS EXISTS FOR

After Tools/respeak_bad.py and its rescue pass there is a residue of clips that
no take could be accepted for. Cozzle comes back as "KOSLA", Cyrce as "Zürze",
Coups as "Kups" -- every time, from every take. The natural reading is that these
clips are broken and the repair failed on them.

That reading is wrong, and the shape of the evidence says so. A hallucinating
reader is not consistent: that is the whole basis of Tools/repair_words.py, which
fixes clips precisely because asking again gives a different answer. One word
asked for five times came back at 0.88, 0.72, 4.56, 0.40 and 0.48 seconds. So a
word that gives the *same* answer eight times running is not hallucinating. It is
saying a thing, reliably, and the recogniser is writing that thing down in a
spelling that does not match a name invented for a fantasy game.

WHAT IS ACTUALLY BEING MEASURED

Not "is this the right word" -- nothing available here can answer that for
Cozzle, and a recogniser asked to spell it will guess differently every time it
is asked. What can be answered is "is the reader stable on this word", and that
is the question that separates the two failures that matter:

    stable    the same rendering every time. Whatever the recogniser calls it,
              the reader is not inventing, and the clip on disk is as good as
              this word gets. If the clip already matches what the takes agree
              on, it is confirmed where it stands and not rewritten.

    unstable  a different answer every time, or takes that ramble. This is the
              reader guessing, and the clip cannot be trusted.

A clip that comes out stable is verified, not excused. A clip that comes out
unstable is reported as such, by name, with what was heard each time -- because
at that point the honest answer is that a human has to listen to it, and a list
of forty words is a thing a human can actually listen to.

WHY THE ORIGINAL IS USUALLY KEPT RATHER THAN REPLACED

When the fresh takes agree with each other *and* with what the clip on disk
already transcribes as, the clip on disk is one more sample from the same stable
distribution. Replacing it would spend a write to arrive at the same audio, and
churn 1,100 files in a pack that is committed to git for no gain. It is confirmed
instead: the recording is what this reader reliably says for this word.
"""
import argparse
import base64
import collections
import difflib
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unicodedata
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = "mistralai/Voxtral-4B-TTS-2603"
LOUDNESS = "loudnorm=I=-18:TP=-2"

# More takes than a repair pass uses. A repair stops at the first take it can
# accept, so five is a ceiling it rarely reaches; this one has to characterise a
# distribution rather than draw from it, and every take is paid for.
TAKES = 8

# Mean similarity between takes, above which the reader is called stable. Drawn
# from what the two repair passes already showed: takes of a word the reader is
# sure of differ only in the recogniser's punctuation and casing, which
# normalisation removes, so they score near 1.0 against each other. Takes of a
# word it is inventing for are different sentences and score near 0.
AGREE = 0.6

# How close the agreed rendering has to be to what the clip on disk already
# says, for the clip to be confirmed where it stands rather than replaced.
CONFIRM = 0.7

FLOOR = 0.25

# A take longer than this many times the median for words of its length is the
# reader inventing, whatever the recogniser made of it. Data/word_seconds.json
# holds those medians, measured over all 104,274 word clips.
#
# This is not belt and braces on the transcript test -- it catches a fault the
# transcript test cannot see at all. The word "de" was given a ten-second take
# of "die die die die die"; the recogniser wrote down "die", which scores 0.80
# against "de" and cleared the acceptance bar exactly. Ten seconds of repetition
# was written into the pack as a repair, and every text-based check agreed it
# was one.
SUSPECT = 3.0
KEEP = re.compile(r"[^\w]+", re.UNICODE)


def limits():
    """Median seconds per word length, or an empty table if it is not there."""
    path = ROOT / "Data" / "word_seconds.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def too_long(table, word, seconds):
    median = table.get(str(len(word)))
    return bool(median) and seconds > median * SUSPECT


def normalise(text):
    return KEEP.sub("", unicodedata.normalize("NFC", str(text or ""))).casefold()


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def rambles(want, heard):
    a, b = normalise(want), normalise(heard)
    return bool(a) and len(b) > max(len(a) * 3, len(a) + 12)


def acceptable(want, heard):
    """The full bar, as Tools/respeak_bad.py draws it."""
    a, b = normalise(want), normalise(heard)
    if not b:
        return False
    if a == b:
        return True
    if a in b:
        return len(b) <= len(a) * 2
    return similarity(want, heard) >= 0.8


def agreement(transcripts):
    """Mean similarity of every take to every other, and the take nearest all.

    The medoid rather than the first or the shortest: with the takes agreeing,
    the one closest to the rest is the one least likely to carry whatever
    oddity a single pass through the recogniser introduced.
    """
    if len(transcripts) < 2:
        return 0.0, 0
    best_index, best_mean, total, pairs = 0, -1.0, 0.0, 0
    for i, one in enumerate(transcripts):
        mean = 0.0
        for j, other in enumerate(transcripts):
            if i == j:
                continue
            score = similarity(one, other)
            mean += score
            if j > i:
                total += score
                pairs += 1
        mean /= len(transcripts) - 1
        if mean > best_mean:
            best_mean, best_index = mean, i
    return (total / pairs if pairs else 0.0), best_index


def wav_seconds(raw):
    with wave.open(io.BytesIO(raw)) as handle:
        return handle.getnframes() / float(handle.getframerate())


def encode(raw, clip, quality):
    clip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(raw)
        source = handle.name
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", source,
             "-af", LOUDNESS, "-ac", "1", "-ar", "24000",
             "-c:a", "libvorbis", "-qscale:a", str(quality),
             "-y", str(clip)],
            check=True)
    finally:
        pathlib.Path(source).unlink(missing_ok=True)


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


def outstanding(bad, first, rescue):
    """Clips still unsettled once both repair passes have had their turn."""
    originals = {row["path"]: row for row in read_jsonl(bad)}
    settled = set()
    unsettled = {}
    for row in read_jsonl(first) + read_jsonl(rescue):
        if row.get("outcome") == "fixed":
            settled.add(row["path"])
            unsettled.pop(row["path"], None)
        elif row["path"] not in settled:
            unsettled[row["path"]] = row
    rows = []
    for path, row in unsettled.items():
        was = originals.get(path, {})
        rows.append({"word": row["word"], "path": path,
                     "was": was.get("heard", ""),
                     "verdict": was.get("verdict", "")})
    rows.sort(key=lambda r: r["word"])
    return rows


def stamps(plan):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from generate_voxtral import cast
    rows = []
    for line in io.open(plan, encoding="utf-8"):
        if '"word"' not in line:
            continue
        row = json.loads(line)
        if row.get("kind") == "word":
            rows.append(row)
    return {row["path"]: row for row in cast(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", default=str(ROOT / "bad.jsonl"))
    ap.add_argument("--first", default=str(ROOT / "respoken.jsonl"))
    ap.add_argument("--rescue", default=str(ROOT / "rescued.jsonl"))
    ap.add_argument("--report", default=str(ROOT / "settled.jsonl"))
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--plan", default=str(ROOT / "Data" / "lines.jsonl"))
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--takes", type=int, default=TAKES)
    ap.add_argument("--agree", type=float, default=AGREE)
    ap.add_argument("--quality", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--paths",
                    help="a file of clip paths, one per line, to work on "
                         "regardless of what any report already says about "
                         "them -- for clips a later check found fault with")
    ap.add_argument("--rambling-only", action="store_true",
                    help="only clips that are rambling on disk -- the reported "
                         "fault, and the short half of the work")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.paths:
        wanted = [line.strip() for line in io.open(args.paths, encoding="utf-8")
                  if line.strip()]
        originals = {row["path"]: row for row in read_jsonl(args.bad)}
        plan_words = stamps(pathlib.Path(args.plan))
        rows = [{"word": plan_words[path]["text"], "path": path,
                 "was": originals.get(path, {}).get("heard", ""),
                 "verdict": ""}
                for path in wanted if path in plan_words]
        print("named clips to work on: %d" % len(rows), flush=True)
    else:
        rows = outstanding(args.bad, args.first, args.rescue)
        print("still unsettled after both repair passes: %d" % len(rows), flush=True)
    if args.rambling_only:
        # Worth doing first and on its own. The reported fault is a clip that
        # rambles, and only a small minority of what reaches this tool does:
        # 39 of 1,128 when the split was measured. Running those first means the
        # defects are gone in minutes rather than being met in alphabetical
        # order somewhere inside a run of several hours.
        rows = [row for row in rows if rambles(row["word"], row["was"])]
        print("  of those, rambling on disk: %d" % len(rows), flush=True)

    done = set() if args.paths else {row["path"] for row in read_jsonl(args.report)}
    if done:
        print("  already settled here: %d" % len(done), flush=True)
    rows = [row for row in rows if row["path"] not in done]
    if args.limit:
        rows = rows[:args.limit]
    print("  left to do: %d" % len(rows), flush=True)
    if not rows:
        print("nothing left to settle")
        return 0

    if args.dry_run:
        for row in rows[:15]:
            print("  %-16s on disk says %r" % (repr(row["word"]), row["was"][:46]))
        print("dry run, nothing written")
        return 0

    plan = stamps(pathlib.Path(args.plan))
    table = limits()
    if not table:
        print("  no Data/word_seconds.json -- take lengths will not be checked",
              flush=True)

    import httpx
    client = httpx.Client()
    try:
        client.get(args.server + "/health", timeout=10).raise_for_status()
    except Exception as exc:
        sys.exit("no reader at %s (%s)" % (args.server, type(exc).__name__))

    from faster_whisper import WhisperModel
    ears = WhisperModel(args.model, device=args.device, compute_type=args.compute)
    print("reader up, ears up: %s" % args.model, flush=True)

    def hear(raw):
        segments, _ = ears.transcribe(io.BytesIO(raw), language="de", beam_size=1,
                                      condition_on_previous_text=False)
        return " ".join(segment.text for segment in segments).strip()

    sounds = pathlib.Path(args.sounds)
    out = io.open(args.report, "a", encoding="utf-8", newline="\n")
    counts = collections.Counter()
    for index, row in enumerate(rows, 1):
        word = row["word"]
        entry = plan.get(row["path"])
        if entry is None:
            counts["absent"] += 1
            continue
        payload = {
            "model": MODEL,
            "response_format": "wav",
            "items": [{"input": word, "voice": entry["voice"]}] * args.takes,
        }
        try:
            answer = client.post(args.server + "/v1/audio/speech/batch",
                                 json=payload, timeout=900)
            answer.raise_for_status()
            results = answer.json().get("results", [])
        except Exception as exc:
            counts["failed"] += 1
            print("  ! %s: %s" % (repr(word), type(exc).__name__), flush=True)
            continue

        takes = []
        passing = None
        for result in results:
            if result.get("status") != "success":
                continue
            raw = base64.b64decode(result["audio_data"])
            seconds = wav_seconds(raw)
            if seconds < FLOOR:
                continue
            heard = hear(raw)
            takes.append({"heard": heard, "seconds": round(seconds, 2), "raw": raw})
            if too_long(table, word, seconds):
                # Long enough to be an invention. Kept in the take list, because
                # it is evidence about how stable the reader is, but never
                # eligible to be written.
                continue
            if passing is None or seconds < passing["seconds"]:
                if acceptable(word, heard):
                    passing = takes[-1]

        record = {"word": word, "path": row["path"], "was": row["was"],
                  "heard": [take["heard"] for take in takes]}
        clip = sounds / row["path"].replace("sounds/", "", 1)

        if passing is not None:
            # A take cleared the full bar after all. More rolls of the same die.
            encode(passing["raw"], clip, args.quality)
            clip.with_suffix(".hash").write_text(entry["stamp"], encoding="utf-8")
            counts["fixed"] += 1
            record.update(outcome="fixed", kept=passing["heard"],
                          seconds=passing["seconds"])
        else:
            steady = [take for take in takes
                      if not rambles(word, take["heard"])
                      and not too_long(table, word, take["seconds"])
                      and normalise(take["heard"])]
            score, which = agreement([take["heard"] for take in steady])
            if len(steady) >= 3 and score >= args.agree:
                consensus = steady[which]
                if similarity(consensus["heard"], row["was"]) >= CONFIRM:
                    # The clip on disk already says what the reader reliably
                    # says. Nothing to write.
                    counts["confirmed"] += 1
                    record.update(outcome="confirmed", agreement=round(score, 3),
                                  kept=consensus["heard"])
                else:
                    encode(consensus["raw"], clip, args.quality)
                    clip.with_suffix(".hash").write_text(entry["stamp"], encoding="utf-8")
                    counts["replaced"] += 1
                    record.update(outcome="replaced", agreement=round(score, 3),
                                  kept=consensus["heard"])
            elif steady and rambles(word, row["was"]):
                # Unstable, and the clip on disk is rambling. Those two facts
                # together are the only case where a take has to be written
                # without anything having verified it.
                #
                # The reported fault -- the one the owner heard and complained
                # about -- is a word clip that runs on into invented German. It
                # is not "the recogniser spells this name differently each
                # time", which is what unstable mostly means: of the first 137
                # clips that landed here, 132 were short on disk and only 5 were
                # rambling. So unstable is not a defect class, and the 132 are
                # left exactly where they are.
                #
                # The 5 are. Leaving a known ramble in place because the cure
                # could not be verified would be preferring an unverified defect
                # to an unverified repair, and between those two the repair is
                # the better bet: the shortest take that does not itself ramble
                # is, at worst, the same uncertainty in less time, and at best
                # the fault is gone. Shortest for the reason
                # Tools/repair_words.py gives -- invention adds material and
                # never removes it.
                best = min(steady, key=lambda take: take["seconds"])
                encode(best["raw"], clip, args.quality)
                clip.with_suffix(".hash").write_text(entry["stamp"], encoding="utf-8")
                counts["forced"] += 1
                record.update(outcome="forced", agreement=round(score, 3),
                              kept=best["heard"], seconds=best["seconds"])
            else:
                counts["unstable"] += 1
                record.update(outcome="unstable", agreement=round(score, 3),
                              steady=len(steady))
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        out.flush()
        if index % 25 == 0 or index == len(rows):
            print("  %d/%d  fixed %d, confirmed %d, replaced %d, forced %d, unstable %d"
                  % (index, len(rows), counts["fixed"], counts["confirmed"],
                     counts["replaced"], counts["forced"], counts["unstable"]), flush=True)
    out.close()

    print()
    print("fixed      %d  (a take cleared the full bar)" % counts["fixed"])
    print("confirmed  %d  (reader stable, clip on disk already says it)" % counts["confirmed"])
    print("replaced   %d  (reader stable, clip on disk did not match)" % counts["replaced"])
    print("forced     %d  (was rambling on disk, shortest steady take written)"
          % counts["forced"])
    print("unstable   %d  (reader varies, but the clip on disk does not ramble)"
          % counts["unstable"])
    if counts["failed"]:
        print("failed     %d" % counts["failed"])
    print("report written to %s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
