#!/usr/bin/env python3
"""How fast does this card actually read, and does half precision help?

    .venv/Scripts/python.exe -u Tools/bench.py

Three hundred and fifty-seven hours of speech is worth twenty minutes of
measurement first. The demo ran at 0.73x realtime, which is nearly three weeks
of generation; anything that moves that number is worth knowing before the run
rather than after it.

Uses real sentences from the plan, not invented ones, because the length
distribution is what decides the answer: a model with a fixed cost per call is
slower per second of audio on short clips than on long ones, and this pack is
now one clip per sentence.
"""
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sample_sentences(n=12):
    rows = []
    with (ROOT / "Data/lines.jsonl").open(encoding="utf-8") as fh:
        for raw in fh:
            row = json.loads(raw)
            if row["kind"] == "quest":
                rows.append(row["text"])
            if len(rows) >= 4000:
                break
    rows.sort(key=len)
    # Spread across the range rather than taking the first n, which would all be
    # two-word sentences and flatter the result.
    step = max(1, len(rows) // n)
    return rows[::step][:n]


def run(model, torch, texts, reference, label):
    audio = elapsed = 0.0
    for text in texts:
        began = time.time()
        wav = model.generate(text, language_id="de", audio_prompt_path=reference,
                             exaggeration=0.5, cfg_weight=0.5)
        elapsed += time.time() - began
        audio += wav.shape[1] / model.sr
    rate = audio / elapsed
    print("%-22s %6.1fs audio in %6.1fs  = %.2fx realtime  -> %.0f h for the pack (%.1f days)"
          % (label, audio, elapsed, rate, 357 / rate, 357 / rate / 24), flush=True)
    return rate


def main():
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    texts = sample_sentences()
    print("sample: %d sentences, %d-%d chars, median %d"
          % (len(texts), len(texts[0]), len(texts[-1]),
             statistics.median(len(t) for t in texts)), flush=True)
    reference = str((ROOT / "voices/narrator.wav").resolve())

    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    print("warming up...", flush=True)
    model.generate(texts[0], language_id="de", audio_prompt_path=reference)

    base = run(model, torch, texts, reference, "as installed")

    # Half precision. The weights are float32 by default; speech models usually
    # take fp16 without an audible difference, and it halves the memory traffic
    # that a 4090 spends most of its time on.
    try:
        for module in ("t3", "s3gen", "ve"):
            part = getattr(model, module, None)
            if part is not None and hasattr(part, "half"):
                part.half()
        half = run(model, torch, texts, reference, "half precision")
        print("\nhalf precision is %.2fx the speed" % (half / base), flush=True)
    except Exception as exc:
        print("half precision failed: %s: %s" % (type(exc).__name__, exc), flush=True)
        print("(not a problem -- it just means the run uses the default)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
