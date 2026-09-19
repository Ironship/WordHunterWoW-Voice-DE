#!/usr/bin/env python3
"""Write the work list for Tools/respeak_by_sound.py.

    python Tools/sound_list.py                 # -> sound_list.jsonl
    python Tools/sound_list.py --out other.jsonl

WHAT GOES ON IT

Three families, one list, because the pass that handles them is one pass:

  unsettled   every clip the edge repair (worklist_report.jsonl) and the
              length-ceiling pass over the held-back 34 (held_report.jsonl)
              gave up on -- names the recogniser spells its own way, which is
              what the sound-judged pass exists for
  shouted     every word the corpus writes in capitals that respeak_bad.py's
              spoken_case() would now hand to the reader as a word: 104 of the
              155 were heard as strings of letters on the listening pass, and
              every pass since has judged letter strings as neither clipped nor
              rambling. They are re-read whatever their last outcome was.

A clip already settled by sound (sound_report.jsonl) is left off, so the list
is what is still to do, and the pass resumes rather than repeats.

Rows carry what respeak_bad.py's work list needs -- word, path, and the
transcript the listening pass heard, when it heard one.
"""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from respeak_bad import spoken_case


def rows_of(path):
    if not path.exists():
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def last_outcomes(path):
    out = {}
    for row in rows_of(path):
        if row.get("path"):
            out[row["path"]] = row.get("outcome")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "sound_list.jsonl"))
    args = ap.parse_args()

    words = {}
    for row in rows_of(ROOT / "Data" / "lines.jsonl"):
        if row.get("kind") == "word":
            words[row["path"]] = row["text"]
    heard = {row["path"]: row.get("heard", "") for row in rows_of(ROOT / "heard.jsonl") if row.get("path")}

    wanted = {}
    for name in ("worklist_report.jsonl", "held_report.jsonl"):
        for path, outcome in last_outcomes(ROOT / name).items():
            if outcome == "unsettled":
                wanted[path] = "unsettled"
    shouted = 0
    for path, word in words.items():
        if spoken_case(word) != word:
            wanted[path] = "shouted"
            shouted += 1
    # The clips verify_repairs.py held back as too long (held_back.txt), whether
    # or not the ceiling pass reached them before it was stopped: a sound-judged
    # take under the ceiling is what they are waiting for.
    held = ROOT / "held_back.txt"
    if held.exists():
        for line in held.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and line not in wanted:
                wanted[line] = "held"
    done = last_outcomes(ROOT / "sound_report.jsonl")
    left = {p: why for p, why in wanted.items() if p not in done}

    with open(args.out, "w", encoding="utf-8", newline="\n") as out:
        for path in sorted(left):
            if path not in words:
                continue
            out.write(json.dumps({"word": words[path], "path": path,
                                  "heard": heard.get(path, ""), "why": left[path]},
                                 ensure_ascii=False) + "\n")
    counts = {}
    for why in left.values():
        counts[why] = counts.get(why, 0) + 1
    print("sound list: %d clips -> %s  (%s; %d already settled by sound, %d shouted words in the corpus)"
          % (len(left), args.out, ", ".join("%s %d" % kv for kv in sorted(counts.items())), len(done), shouted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
