#!/usr/bin/env python3
"""Respeak the clips the recogniser found wanting, and check each take by ear.

    ~/asr/bin/python Tools/respeak_bad.py --dry-run
    ~/asr/bin/python Tools/respeak_bad.py

Needs the reader up:

    VLLM_USE_FLASHINFER_SAMPLER=0 vllm serve mistralai/Voxtral-4B-TTS-2603 \
        --omni --port 8000 --kv-cache-memory 4294967296

WHY NOT Tools/repair_words.py AGAIN

That one chooses between takes by length, because when it was written length was
the only evidence there was: a hallucination adds material and never removes it,
so the shortest take is the clean one. It worked -- 1,649 clips, and the owner
confirmed the words he had complained about now sound right.

But it can only repair what it can detect, and it detects by duration against the
median for words of that length. That catches the articles, where an invented
sentence is many times the length of "der". It does not catch a six-character
word that rambles for twice its median and stays under the three-times bar. The
listening pass found where those went: of 1,059 certain defects, 210 are five
characters long and 206 are six, against 60 of two characters. The duration
detector was looking at the tail of the distribution the hallucinations mostly
are not in.

WHAT THIS DOES INSTEAD

Asks for takes and listens to them. A take is accepted when the recogniser hears
the word and not much else -- the same test that found the defect in the first
place, now pointed at the cure. Length is kept only as a floor, because a take of
a tenth of a second transcribes as nothing and would otherwise look like silence
rather than like a clip cut off.

THE CLIP IS ONLY EVER REPLACED BY A TAKE THAT PASSED

If none of the takes pass, the original stays and the clip is written to the
report as unsettled. That is what makes it safe to feed this a work list with
false positives in it: a name the recogniser cannot spell will fail every take,
including the fresh ones, and the answer to that is to leave the clip alone
rather than to overwrite good audio with equally unverifiable audio. The cost of
a false positive here is GPU time, never a worse pack.

WHAT IS LEFT OUT OF THE WORK LIST

Rows where the transcript is nothing but digits. "drei" comes back as "3.",
"dreihundert" as "300", "achtzehnte" as "18." -- the reader said the number and
the recogniser wrote it in figures, which scores zero similarity against the
spelled-out word and lands in the work list looking like a total mismatch. Those
clips are correct, and respeaking cannot help them anyway: a new take says the
same number and transcribes the same way, so every take would fail and the
original would be kept regardless. Dropping them up front saves the hour rather
than spending it to arrive at "no change" 600 times.

A transcript of digits *and* words is not affected by this -- that is a number
the reader rambled through, and it stays in the list.
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


def spoken_case(word):
    """A word the corpus shouts, handed to the reader as a word.

    Quest text writes a shout in capitals -- KRABUMMS, ABENTEUERSUCHER,
    RIESENFLOEZ -- and the reader takes capitals for an initialism and spells
    them: on 2026-09-19 "ABENTEUERSUCHER" came back as "A, B, N, T, T, U, R,
    Suc", and passed, because a string of letters is not a ramble and is not
    clipped. Nothing else in the corpus is written that way. Only the prompt is
    changed, as with the apostrophe above; the clip keeps the name of the word
    as the dictionary spells it.

    Left alone: three letters or fewer (SI, KI and their kind are initialisms
    that are meant to be spelled), a word with no vowel to say (BFFI), and a
    spelling written out with hyphens (A-K-I-D-A, C-O-O), which the quest
    itself is spelling.
    """
    if len(word) < 4 or not word.isupper():
        return word
    if not any(c in "AEIOUÄÖÜY" for c in word):
        return word
    if re.match(r"^(\w-)+\w$", word):
        return word
    return word[:1] + word[1:].lower()

# How many times a bad clip is asked for again. The takes are listened to in
# order and the first one that passes wins, so this is a ceiling on the work
# rather than the work itself -- a word that is clean on its first roll costs one
# transcription, not five.
TAKES = 5

# Under this a take is a word cut off rather than a word said briskly. The
# shortest clean take measured anywhere in the corpus was 0.40s.
FLOOR = 0.25

KEEP = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text):
    return KEEP.sub("", unicodedata.normalize("NFC", str(text or ""))).casefold()


def similarity(want, heard):
    return difflib.SequenceMatcher(None, normalise(want), normalise(heard)).ratio()


def rambles(want, heard):
    """Is this transcript several words where one was asked for?

    The same length test Tools/heard_report.py uses to find the defect, so that
    "did the repair remove the rambling" is asked in exactly the terms the
    rambling was found in.
    """
    a, b = normalise(want), normalise(heard)
    return bool(a) and len(b) > max(len(a) * 3, len(a) + 12)


def acceptable(want, heard, rescue=False):
    """Does this take say the word, and not a great deal more?

    Deliberately looser than Tools/listen_words.py's "ok". That one is sorting
    104,274 clips into piles and can afford to be strict, because a clip it calls
    wrong is only ever looked at again. This is deciding whether to keep audio,
    and the alternative to keeping it is leaving a clip that is known to be bad.
    A take that contains the word with a little around it is better than what it
    would replace.

    THE RESCUE BAR, AND WHY IT IS LOWER

    Under --rescue the last clause drops from 0.8 to 0.5 and gains a condition:
    the take must not itself ramble. That is not a softer standard applied to the
    same question, it is a different question. The full bar asks "is this the
    word", which is the right question when the clip being replaced might be
    perfectly good. Rescue only ever runs on clips whose original was measured as
    rambling, so the clip being replaced is known bad, and the question becomes
    "does this stop the rambling" -- which the length test answers directly.

    It is worth being concrete about what this lets through. Coups was recorded
    as "Kups Nei, so nah der Fussel entleischt" and the best fresh take came back
    as "Kups." -- a correct German reading of a French word, scoring 0.67 because
    the recogniser spelled what it heard. The full bar rejects that and keeps the
    rambling. Holding a defect in place because the cure cannot be spelled is the
    wrong trade, and 0.5 is still far enough from zero to refuse a take that has
    nothing to do with the word: de heard as "hat viele" scores 0.20 and stays
    rejected, so its original is kept and reported unsettled, as it should be.
    """
    a, b = normalise(want), normalise(heard)
    if not b:
        return False
    if a == b:
        return True
    if a in b:
        # The word plus a trailing fragment. Twice the length is the line: past
        # that the reader has started a sentence.
        return len(b) <= len(a) * 2
    if rescue:
        return not rambles(want, heard) and similarity(want, heard) >= 0.5
    # Spelling, not substance: the recogniser writes the umlaut its own way.
    return similarity(want, heard) >= 0.8


def wav_seconds(raw):
    with wave.open(io.BytesIO(raw)) as handle:
        return handle.getnframes() / float(handle.getframerate())


def work_list(path, keep_numerals):
    """The rows to repair, with the numeral readings dropped unless asked for."""
    rows, numerals = [], 0
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if not keep_numerals and normalise(row.get("heard")).isdigit():
            numerals += 1
            continue
        rows.append(row)
    return rows, numerals


def rescue_list(bad_path, report_path):
    """Clips the first pass could not settle, whose original was rambling.

    Only those. A clip that went unsettled because the recogniser could not
    spell a name is left alone, because nothing is known to be wrong with it --
    the listening pass called it a candidate, not a defect, and replacing it on
    a 0.5 match would be trading audio nobody has faulted for audio nobody can
    verify. A clip whose original was measured as rambling is a different case:
    that one is known bad, and the only question is whether the fresh take is
    better.
    """
    if not pathlib.Path(report_path).exists():
        sys.exit("no first pass to rescue from at %s" % report_path)
    originals = {}
    for line in io.open(bad_path, encoding="utf-8"):
        line = line.strip()
        if line:
            row = json.loads(line)
            originals[row["path"]] = row
    rows = []
    for line in io.open(report_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("outcome") != "unsettled":
            continue
        was = originals.get(row["path"])
        if was and (was.get("verdict") == "rambled"
                    or rambles(was.get("word"), was.get("heard"))):
            rows.append({"word": row["word"], "path": row["path"],
                         "heard": was.get("heard", "")})
    return rows


def stamps(plan):
    """path -> (voice, stamp), from the generator's own casting.

    Imported rather than written down here for the same reason
    Tools/repair_words.py imports it: the voice is half of a clip's stamp, so a
    second opinion on who reads this pack would let a repaired clip claim to be
    current while carrying a different reader.
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
    return {row["path"]: row for row in cast(rows)}


def encode(raw, clip, quality):
    """WAV bytes to the ogg the pack ships, at the rate every other clip is.

    -ac and -ar are not decoration: loudnorm resamples to 192 kHz and stays there
    unless the output rate is named. Leaving them out is what put 1,649 clips in
    this pack at eight times everything around them.
    """
    clip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(raw)
        source = handle.name
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "2", "-i", source,
             "-af", LOUDNESS, "-ac", "1", "-ar", "24000",
             "-c:a", "libvorbis", "-qscale:a", str(quality),
             "-y", str(clip)],
            check=True)
    finally:
        pathlib.Path(source).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", default=str(ROOT / "bad.jsonl"))
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--plan", default=str(ROOT / "Data" / "lines.jsonl"))
    ap.add_argument("--report", default=str(ROOT / "respoken.jsonl"))
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--takes", type=int, default=TAKES)
    ap.add_argument("--quality", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-numerals", action="store_true",
                    help="do not drop rows whose transcript is only digits")
    ap.add_argument("--rescue", action="store_true",
                    help="second pass over the first pass's unsettled ramblers, "
                         "at the lower bar described on acceptable()")
    ap.add_argument("--rescued", default=str(ROOT / "rescued.jsonl"),
                    help="where --rescue writes, kept apart from the first "
                         "pass's report so neither overwrites the other")
    ap.add_argument("--max-factor", type=float, default=0.0,
                    help="reject a take longer than this many times the median "
                         "clip length for a word of its length (Data/word_seconds.json); "
                         "0 means no ceiling. verify_repairs.py faults at 3.0, so a "
                         "repair that has to survive it should not accept above that")
    ap.add_argument("--only", metavar="FILE",
                    help="a file of clip paths, one per line: repair these and nothing else")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.rescue:
        rows, numerals = rescue_list(args.bad, args.report), 0
        args.report = args.rescued
        print("rescue pass over %s" % args.rescued)
        print("  unsettled clips whose original rambled: %d" % len(rows), flush=True)
    else:
        rows, numerals = work_list(args.bad, args.keep_numerals)
        print("work list: %d clips" % (len(rows) + numerals))
        if numerals:
            print("  dropped as numeral readings: %d" % numerals)
        print("  to repair: %d" % len(rows), flush=True)

    # Resumed rather than restarted, like the listening pass: whatever has
    # already been decided stays decided.
    done = set()
    report_path = pathlib.Path(args.report)
    if report_path.exists():
        for line in io.open(report_path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["path"])
                except Exception:
                    pass
        if done:
            print("  already settled: %d" % len(done), flush=True)
    rows = [row for row in rows if row["path"] not in done]
    if args.only:
        wanted = {line.strip() for line in io.open(args.only, encoding="utf-8") if line.strip()}
        rows = [row for row in rows if row["path"] in wanted]
        print("  named in %s: %d" % (args.only, len(rows)), flush=True)
    if args.limit:
        rows = rows[:args.limit]
    print("  left to do: %d" % len(rows), flush=True)
    if not rows:
        print("nothing to respeak")
        return 0

    if args.dry_run:
        for row in rows[:15]:
            print("  %-18s heard %r" % (repr(row["word"]), row.get("heard", "")[:50]))
        print("dry run, nothing written")
        return 0

    plan = stamps(pathlib.Path(args.plan))
    missing = [row for row in rows if row["path"] not in plan]
    if missing:
        sys.exit("%d clips are not in the plan, first is %s"
                 % (len(missing), missing[0]["path"]))

    import httpx
    client = httpx.Client()
    try:
        client.get(args.server + "/health", timeout=10).raise_for_status()
    except Exception as exc:
        sys.exit("no reader at %s (%s)" % (args.server, type(exc).__name__))

    from faster_whisper import WhisperModel
    # cpu_threads capped. CTranslate2 defaults to every thread on the machine
    # for its CPU-side work -- feature extraction, decoding -- and on a sixteen-
    # thread desktop that is sixteen threads pegged for a moment on every take,
    # which is what the owner saw as a CPU stuck at 100% during a run that never
    # used to load it. The old generation did no recognising at all. Four is
    # plenty for a clip of a second; the GPU is where the model lives.
    ears = WhisperModel(args.model, device=args.device, compute_type=args.compute,
                        cpu_threads=4)
    print("reader up, ears up: %s" % args.model, flush=True)

    def hear(raw):
        segments, _ = ears.transcribe(io.BytesIO(raw), language="de", beam_size=1,
                                      condition_on_previous_text=False)
        return " ".join(segment.text for segment in segments).strip()

    # The ceiling, when asked for: the measured median length for a word of
    # this many letters, times the factor. A take over it is the reader
    # inventing, whatever the transcript says -- verify_repairs.py would fault
    # it afterwards, so it is not a repair.
    medians = {}
    if args.max_factor > 0:
        with io.open(ROOT / "Data" / "word_seconds.json", encoding="utf-8") as handle:
            medians = json.load(handle)

    def ceiling(word):
        median = medians.get(str(len(word)))
        return median * args.max_factor if median and args.max_factor > 0 else None

    sounds = pathlib.Path(args.sounds)
    out = io.open(args.report, "a", encoding="utf-8", newline="\n")
    counts = collections.Counter()
    listens = 0
    for index, row in enumerate(rows, 1):
        word = row["word"]
        entry = plan[row["path"]]
        # The apostrophe goes out of the prompt and stays in the file name.
        #
        # It is not a sound. The reader says "Zul'Nazman" the same with or
        # without it, and Warcraft's invented names are full of them -- but the
        # generator does not treat it as nothing: on 2026-09-18 a run wedged on
        # that exact word for eight minutes, the card at 100% and 87 W, which is
        # the model generating without end rather than computing. A punctuation
        # mark in the middle of a word is not something the corpus it was
        # trained on has much of.
        #
        # Only the prompt is changed. The clip is named by a hash of the real
        # word, so the file it lands in is the same file either way, and the
        # dictionary entry keeps its apostrophe.
        spoken = word.replace("'", "").replace("’", "")
        spoken = spoken_case(spoken)
        payload = {
            "model": MODEL,
            "response_format": "wav",
            "items": [{"input": spoken, "voice": entry["voice"]}] * args.takes,
        }
        try:
            # Ten minutes was the timeout when a batch took four seconds. A
            # wedged generation then holds the whole run for ten of them, and
            # 3,647 clips cannot afford one. Abandoned after ninety seconds,
            # which is twenty times the measured batch and still generous.
            answer = client.post(args.server + "/v1/audio/speech/batch",
                                 json=payload, timeout=180)
            answer.raise_for_status()
            results = answer.json().get("results", [])
        except Exception as exc:
            counts["failed"] += 1
            print("  ! %s: %s" % (repr(word), type(exc).__name__), flush=True)
            continue

        chosen = None
        best = None
        tried = []
        for result in results:
            if result.get("status") != "success":
                continue
            raw = base64.b64decode(result["audio_data"])
            seconds = wav_seconds(raw)
            if seconds < FLOOR:
                continue
            heard = hear(raw)
            listens += 1
            score = similarity(word, heard)
            tried.append({"heard": heard, "seconds": round(seconds, 2),
                          "similarity": round(score, 3)})
            if best is None or score > best[0]:
                best = (score, raw, heard, seconds)
            limit = ceiling(word)
            if limit and seconds > limit:
                tried[-1]["long"] = round(limit, 2)
                continue
            if acceptable(word, heard, args.rescue):
                chosen = (raw, heard, seconds, score)
                break

        record = {"word": word, "path": row["path"], "was": row.get("heard", ""),
                  "takes": tried}
        if chosen:
            raw, heard, seconds, score = chosen
            clip = sounds / row["path"].replace("sounds/", "", 1)
            encode(raw, clip, args.quality)
            clip.with_suffix(".hash").write_text(entry["stamp"], encoding="utf-8")
            counts["fixed"] += 1
            record.update(outcome="fixed", heard=heard,
                          seconds=round(seconds, 2), similarity=round(score, 3))
        else:
            # Nothing came back that the recogniser could hear as the word. The
            # clip that is there may be fine and unspellable, or bad and
            # unfixable; either way a take that failed the same test is not an
            # improvement on it.
            counts["unsettled"] += 1
            record.update(outcome="unsettled",
                          best=round(best[0], 3) if best else None,
                          heard=best[2] if best else "")
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        out.flush()
        if index % 25 == 0 or index == len(rows):
            print("  %d/%d  fixed %d, unsettled %d, failed %d  (%.1f takes heard each)"
                  % (index, len(rows), counts["fixed"], counts["unsettled"],
                     counts["failed"], listens / max(1, index)), flush=True)
    out.close()

    print()
    print("fixed      %d" % counts["fixed"])
    print("unsettled  %d  (original kept)" % counts["unsettled"])
    if counts["failed"]:
        print("failed     %d  (reader would not answer)" % counts["failed"])
    print("report written to %s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
