#!/usr/bin/env python3
"""Rebuild plans must use external quest sources and disjoint Forever ranges."""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tools"))
import build_merged
import build_pack


def main():
    assert build_merged.DEFAULT_LAYOUT == "two"
    modern = build_merged.runs_of(build_merged.LAYOUTS["two"]["Modern"])
    assert modern == [(34576, 97276), (97278, 10 ** 9)], modern
    declared = build_pack.declaration("WordHunterWoW-Voice-DE-WarWithin", "WarWithin")
    assert "ranges = { { 74001, 97276 }, { 97278, 1000000000 } }" in declared

    with tempfile.TemporaryDirectory(prefix="voice-external-") as tmp:
        work = pathlib.Path(tmp)
        sources, mp3, output = work / "quests", work / "mp3", work / "out"
        for name, lo, _hi in build_pack.EXPANSIONS:
            home = sources / name
            home.mkdir(parents=True)
            (home / "Part.lua").write_text(build_pack.declaration(
                build_merged.folder_of(name), name, "%d o 100" % lo,
                "%d o 1" % lo), encoding="utf-8")
            master = home / "sounds" / "q" / ("%02d" % (lo % 100)) / ("%d_o1.ogg" % lo)
            master.parent.mkdir(parents=True)
            master.write_bytes(b"OggS fixture")
            clip = mp3 / name / "sounds" / "q" / ("%02d" % (lo % 100)) / ("%d_o1.mp3" % lo)
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"fixture")
        args = [sys.executable, str(ROOT / "Tools/build_merged.py"),
                "--sources", str(sources), "--audio", str(mp3),
                "--out", str(output), "--dry-run"]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "layout two" in result.stdout and "2 pack(s)" in result.stdout, result.stdout
        assert "Classic" in result.stdout and "Modern" in result.stdout
        assert not output.exists(), "dry-run created output"
        assert not (sources / "Words").exists()
        print(result.stdout.strip())
        result = subprocess.run([sys.executable, str(ROOT / "Tools/transcode_packs.py"),
                                 "--sources", str(sources), "--out", str(output),
                                 "--dry-run"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "mp3 16 kbps at 24000 Hz" in result.stdout, result.stdout
        assert result.stdout.count("1 clips,      1 to do") == 11, result.stdout
        assert not output.exists(), "transcode dry-run created output"
        wrong = mp3 / "Draenor" / "sounds" / "q" / "76" / "34576_o1.mp3"
        wrong.rename(wrong.with_name("34576_o2.mp3"))
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode != 0 and "audio does not match Part.lua" in result.stderr, result.stderr
        assert not output.exists(), "failed dry-run created output"
    print("external-sources: ok")


if __name__ == "__main__":
    main()
