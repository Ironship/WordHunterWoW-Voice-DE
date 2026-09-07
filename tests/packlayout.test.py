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

        # And the four clips of quest 8473, which is the passage the shipped
        # sentence grouping exists for. Its first sentence loses a vocative and
        # falls under the minimum, so the generator reads sentences one and two
        # as a single clip -- and the addon, given the client's text with a name
        # in it, counted five clips where the pack holds four, which put every
        # play button after the first on the wrong paragraph. A Classic quest,
        # so this is a second pack and not a second clip in the first one.
        for index in range(1, 5):
            spoken = sounds / naming.quest_path(
                8473, "description", index).replace("sounds/", "", 1)
            spoken.parent.mkdir(parents=True, exist_ok=True)
            spoken.write_bytes(b"OggS\0\2" + b"\0" * 64)

        out = work / "build"
        result = subprocess.run(
            [sys.executable, str(ROOT / "Tools/build_pack.py"),
             "--sounds", str(sounds), "--out", str(out),
             # Into the fixture, never at the default. The default is the
             # folder beside this repository, which is where the twelve pack
             # repositories actually live -- so a test run left a Part.lua
             # generated from two fixture clips sitting in a checkout somebody
             # would later tag and publish.
             "--repos", str(work / "repos")],
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

        if ".starts = [[" not in text:
            fail("the pack ships no sentence grouping, so the addon is left to "
                 "guess one from the text the client draws")

        classic = out / "WordHunterWoW-Voice-DE-Classic" / "Part.lua"
        if not classic.exists():
            fail("no Classic pack was built for quest 8473")
        told = classic.read_text(encoding="utf-8")
        rows = [line for line in told.splitlines() if line.startswith("8473 o")]
        if "8473 o 0,0,0,0" not in told:
            fail("quest 8473 should hold four clips; found %s" % rows)
        if "8473 o 1,3,4,5" not in told:
            fail("quest 8473 should be grouped 1,3,4,5 -- its opening sentence "
                 "loses a vocative, falls under the thirty-character minimum "
                 "and is read together with the next; found %s" % rows)
        print("  and which sentences each of its clips covers")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("packlayout: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
