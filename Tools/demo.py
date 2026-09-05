#!/usr/bin/env python3
"""Speak the demo plan in the chosen voices, one clip per sentence.

    .venv/Scripts/python.exe -u Tools/demo.py

Not part of the pipeline. This exists so a voice can be judged on real quest
text before hours of it are generated, which is the only way to find out whether
a reader that sounds right reading fairy tales also sounds right giving orders
in Orgrimmar.
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "demo"
DESKTOP = pathlib.Path.home() / "Desktop" / "Glosy-WordHunter"


def main():
    plan = json.loads((ROOT / "Data/demo.json").read_text(encoding="utf-8"))
    voices = {}
    for name in {row["voice"] for row in plan}:
        voices[name] = json.loads((ROOT / "voices" / (name + ".json")).read_text(encoding="utf-8"))

    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    print("loading the reader (first run downloads the weights)...", flush=True)
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    print("loaded, sample rate", model.sr, flush=True)

    OUT.mkdir(exist_ok=True)
    started = time.time()
    # Per quest, so the sentences can be heard as one passage as well as singly.
    joined = {}
    for n, row in enumerate(plan, 1):
        voice = voices[row["voice"]]
        reference = str((ROOT / "voices" / voice["reference"]).resolve())
        began = time.time()
        wav = model.generate(row["text"], language_id="de", audio_prompt_path=reference,
                             exaggeration=voice.get("exaggeration", 0.5),
                             cfg_weight=voice.get("cfg_weight", 0.5))
        seconds = wav.shape[1] / model.sr
        clip = OUT / ("q%d_%02d_%s.wav" % (row["qid"], row["i"], row["voice"]))
        torchaudio.save(str(clip), wav, model.sr)
        joined.setdefault((row["qid"], row["voice"]), []).append(wav)
        print("  %2d/%d  %-28s %5.1fs audio in %4.1fs  (%.1fx realtime)"
              % (n, len(plan), clip.name, seconds, time.time() - began,
                 seconds / max(0.01, time.time() - began)), flush=True)

    for (qid, voice), waves in joined.items():
        gap = torch.zeros(1, int(model.sr * 0.45))
        full = torch.cat([w for pair in ((x, gap) for x in waves) for w in pair][:-1], dim=1)
        whole = OUT / ("quest%d_%s_caly.wav" % (qid, voice))
        torchaudio.save(str(whole), full, model.sr)
        print("  whole passage: %s  %.1fs" % (whole.name, full.shape[1] / model.sr), flush=True)

    DESKTOP.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.wav"):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(f),
                        "-ar", "44100", str(DESKTOP / ("demo_" + f.name))], check=False)
    print("done in %.1f minutes -> %s" % ((time.time() - started) / 60, DESKTOP), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
