#!/usr/bin/env python3
"""Does a built pack put its clips where the addon looks for them?

    python tests/packlayout.test.py

This exists because they did not, in every pack, from the first one built. The
addon asks the client for

    Interface\\AddOns\\<pack>\\sounds\\q\\69\\24469_o1.ogg

and Tools/build_pack.py wrote

    Interface\\AddOns\\<pack>\\q\\69\\24469_o1.ogg

one directory out. No pack ever played a sound. It took a long time to find,
because every check of "is the clip there" was written from the same wrong rule
as the builder -- so the two agreed with each other, and neither was ever
compared against Naming.lua, which is the only thing whose opinion counts.

So this test does not ask the builder where it put a clip. It builds a pack from
a fixture, computes the path the way the addon computes it, and looks there.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Tools"))
import naming


def fail(why):
    print("  FAIL: %s" % why)
    sys.exit(1)


def addon_path(pack, relative):
    """The path the addon asks the client for, built the addon's way.

    Naming.lua returns "sounds\\q\\52\\25152_o1.ogg" and Voice.lua prefixes
    "Interface\\AddOns\\<pack>\\". Everything after the pack folder is what has
    to exist on disk.
    """
    return relative.replace("\\", "/")


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="packlayout-"))
    try:
        sounds = work / "sounds"
        # One clip in a Cataclysm-range quest, named the way the generator names
        # them, holding a byte so the builder has something to copy.
        quest, field, sentence = 24469, "description", 1
        relative = naming.quest_path(quest, field, sentence)
        clip = sounds / relative.replace("sounds/", "", 1)
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"OggS\0\2" + b"\0" * 64)

        out = work / "build"
        result = subprocess.run(
            [sys.executable, str(ROOT / "Tools/build_pack.py"),
             "--sounds", str(sounds), "--out", str(out), "--only", "Cataclysm"],
            capture_output=True, text=True)
        if result.returncode != 0:
            fail("build_pack.py failed:\n%s" % (result.stderr or result.stdout))

        pack = out / "WordHunterWoW-Voice-DE-Cataclysm"
        if not pack.is_dir():
            fail("no pack was built at %s" % pack)

        wanted = pack / addon_path(pack.name, relative)
        if not wanted.exists():
            found = [str(p.relative_to(pack)) for p in pack.rglob("*.ogg")]
            fail("the addon would ask for %s\n        the builder wrote %s"
                 % (relative, found or "nothing"))
        print("  a built pack holds its clips where Naming.lua says they are")

        part = pack / "Part.lua"
        if not part.exists():
            fail("the pack does not declare itself")
        text = part.read_text(encoding="utf-8")
        if "quests = { 14621, 29377 }" not in text:
            fail("the pack declares the wrong quest range")
        if "24469 o " not in text:
            fail("the pack ships no duration for the clip it holds")
        print("  and declares the range and the duration for it")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("packlayout: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
