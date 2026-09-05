#!/usr/bin/env python3
"""Speak the lines Tools/plan_lines.py planned.

    python Tools/plan_lines.py --write
    python Tools/generate.py --voice narrator --limit 200      # a pilot
    python Tools/generate.py --voice narrator                  # the rest

Resumable by design. It is hours of work on one card and it will be interrupted:
closing the window, a driver update, a power cut. Nothing is held in memory that
matters, every clip is written and encoded before the next is started, and a
second run picks up exactly where the first stopped -- a clip already on disk
whose text has not changed is not spoken again.

The model is Chatterbox Multilingual (Resemble AI, MIT). MIT is why: the weights
and the code are both permissive, so the audio can be given away with the addon.
Most of the alternatives cannot be. See README.md for what was rejected.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import speech

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINES = ROOT / "Data/lines.jsonl"
VOICES = ROOT / "voices"

# A pause between the pieces of a long passage, so two sentences read separately
# do not arrive as one breathless run. Shorter between sentences than the pause
# a paragraph break earns in the reading itself.
JOIN_SILENCE = 0.25


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


def outstanding(rows, sounds, force=False):
    """Clips that are missing, or whose German text has changed since.

    The hash lives beside the clip rather than in one index file: an index is a
    single point of loss, and a run that dies partway would leave it describing
    a state that is no longer true.
    """
    todo = []
    for row in rows:
        clip = sounds / row["path"].replace("sounds/", "", 1)
        stamp = clip.with_suffix(".hash")
        if force or not clip.exists():
            todo.append(row)
        elif not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != row["hash"]:
            todo.append(row)
    return todo


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if not found:
        sys.exit("ffmpeg is not on PATH. It encodes the Ogg Vorbis the game plays.")
    return found


def encode(ffmpeg, wav_path, ogg_path, quality):
    """Wav to Ogg Vorbis, mono, at the quality the pack ships.

    Ogg because the WoW client plays it and it is a quarter the size of wav at a
    quality no listener will fault for speech. Mono because the pack is already
    the largest thing in the suite and nothing here is stereo.
    """
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
         "-ac", "1", "-c:a", "libvorbis", "-qscale:a", str(quality), str(ogg_path)],
        check=True)


class Reader:
    """Chatterbox, loaded once and asked for one passage at a time."""

    def __init__(self, voice, device):
        try:
            import torch                                   # noqa: F401
            import torchaudio                              # noqa: F401
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as exc:
            sys.exit("%s\nInstall the reader first:  pip install -r Tools/requirements.txt" % exc)
        self.torch = __import__("torch")
        self.torchaudio = __import__("torchaudio")
        # from_pretrained takes the device and nothing else in 0.1.7. The model
        # card documents a t3_model argument that the released package does
        # not have, and passing it raises.
        self.model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self.reference = voice.get("reference")
        if self.reference and not pathlib.Path(self.reference).exists():
            sys.exit("voice reference not found: %s" % self.reference)
        self.exaggeration = voice.get("exaggeration", 0.5)
        # The model card warns that a reference recorded in another language
        # carries its accent across. The references here are German, so this
        # stays at the ordinary setting rather than the 0 that suppresses it.
        self.cfg_weight = voice.get("cfg_weight", 0.5)

    @property
    def sample_rate(self):
        return self.model.sr

    def say(self, text):
        return self.model.generate(
            text,
            language_id="de",
            audio_prompt_path=self.reference,
            exaggeration=self.exaggeration,
            cfg_weight=self.cfg_weight,
        )

    def passage(self, text):
        """One clip is one sentence, so this is one call.

        A sentence longer than the reader handles in a single pass is read in
        pieces and joined; the corpus has a few, the longest 556 characters.
        """
        text = text.strip()
        if not text:
            return None
        if len(text) <= speech.MAX_CHARS:
            return self.say(text)
        pieces, current = [], ""
        for bit in text.split(", "):
            if current and len(current) + 2 + len(bit) > speech.MAX_CHARS:
                pieces.append(current)
                current = bit
            else:
                current = bit if not current else current + ", " + bit
        if current:
            pieces.append(current)
        waves = []
        for index, piece in enumerate(pieces):
            if index:
                waves.append(self.torch.zeros(1, int(self.sample_rate * JOIN_SILENCE)))
            waves.append(self.say(piece))
        return self.torch.cat(waves, dim=1)


def load_voice(name):
    path = VOICES / (name + ".json")
    if not path.exists():
        sys.exit("no voice called %r in %s" % (name, VOICES))
    voice = json.loads(path.read_text(encoding="utf-8"))
    if voice.get("reference"):
        voice["reference"] = str((VOICES / voice["reference"]).resolve())
    return voice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="narrator")
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--only", choices=("quest", "word"))
    ap.add_argument("--limit", type=int, default=0, help="stop after this many clips")
    ap.add_argument("--device", default="cuda")
    # qscale 1 rather than 3. Measured on real clips, 3 costs 12.6 GB across the
    # pack and 1 costs 8.0 GB, for speech in mono at 24 kHz where the
    # difference is not audible -- and the pack ships as one addon per few
    # hundred megabytes, so four gigabytes is a dozen fewer downloads.
    ap.add_argument("--quality", type=int, default=1, help="vorbis qscale, 0-10")
    ap.add_argument("--force", action="store_true", help="respeak clips that are already fine")
    ap.add_argument("--dry-run", action="store_true",
                    help="do everything except load the model and speak")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    rows = load_plan(args.only)
    todo = outstanding(rows, sounds, args.force)
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print("nothing to speak: every planned clip is present and current")
        return 0

    chars = sum(len(r["text"]) for r in todo)
    print("to speak: %d clips, %.1f hours of audio at an unhurried pace"
          % (len(todo), chars / 15 / 3600))
    if args.dry_run:
        for row in todo[:5]:
            print("  %s  %d chars" % (row["path"], len(row["text"])))
        print("dry run, nothing written")
        return 0

    ffmpeg = find_ffmpeg()
    reader = Reader(load_voice(args.voice), args.device)
    scratch = ROOT / ".scratch"
    scratch.mkdir(exist_ok=True)
    started, spoken, failed = time.time(), 0, 0
    for row in todo:
        clip = sounds / row["path"].replace("sounds/", "", 1)
        try:
            wave = reader.passage(row["text"])
            if wave is None:
                continue
            wav_path = scratch / "current.wav"
            reader.torchaudio.save(str(wav_path), wave, reader.sample_rate)
            encode(ffmpeg, wav_path, clip, args.quality)
            # The stamp is written only once the clip is on disk, so an
            # interrupted run never leaves a clip that claims to be current.
            clip.with_suffix(".hash").write_text(row["hash"], encoding="utf-8")
            spoken += 1
        except KeyboardInterrupt:
            print("\nstopped after %d clips -- run again to continue" % spoken)
            return 0
        except Exception as exc:
            failed += 1
            print("  ! %s: %s" % (row["path"], exc))
        if spoken and spoken % 50 == 0:
            rate = spoken / (time.time() - started)
            left = (len(todo) - spoken) / rate / 3600 if rate else 0
            print("  %d/%d clips, %.1f/min, about %.1f hours left"
                  % (spoken, len(todo), rate * 60, left))
    print("spoke %d clips, %d failed, in %.1f minutes"
          % (spoken, failed, (time.time() - started) / 60))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
