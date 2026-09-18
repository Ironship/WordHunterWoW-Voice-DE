#!/usr/bin/env python3
"""Fold the eleven expansion packs into four, and prove each archive opens.

    python Tools/build_merged.py --dry-run          # sizes only, nothing written
    python Tools/build_merged.py                    # the three merged packs
    python Tools/build_merged.py --all              # plus WarWithin and Words, unchanged
    python Tools/build_merged.py --only Classic

WHY FOUR AND NOT ONE

Thirteen CurseForge projects for one voiceover is what the platform objected
to. One file is impossible: the audio is 5.96 GB against a 2 GB limit per
upload, and re-encoding was measured (Tools/size_probe.py) and declined -- Vorbis
at 24 kHz mono is already near its floor, and the one lever that buys anything,
16 kHz, costs quality the owner heard and refused. So the packs are regrouped
at the quality they have, into as few archives as fit under 80% of the limit:

    Classic     Classic + TBC + Wrath        1464 MB   73%
    Cataclysm   Cata + MoP + WoD             1525 MB   76%
    Legion      Legion + BfA + SL            1315 MB   66%
    WarWithin   DF + TWW                      944 MB   47%
    Words       the dictionary                804 MB   40%   (unchanged)

Sizes are measured from the source files, not estimated from the old archives:
the first cut had Dragonflight with Legion and came to 1616 MB, sixteen over
the target, so DF rides with the current expansion instead. That also pairs
the two newest eras, which is where the next one lands anyway.

THE NAMES ARE THE OLD ONES ON PURPOSE

Each merged pack keeps the folder name and CurseForge project of its first
member. Five existing projects grow; seven -- TBC, Wrath, MoP, WoD, BfA, SL, DF
-- become obsolete and nothing new is created, which is the rule this project
has kept since the platform first pushed back.

WHY THE ENGINE NEEDS NO CHANGE

A pack declares the range of quest ids it covers and the engine finds a quest's
pack by that range alone -- Voice.lua's questOwner walks the parts and returns
the first whose range holds the id. A merged pack declares the union of its
members' ranges. Clip paths are sharded by quest id (sounds/q/<id % 100>/...),
and quest ids are unique across the whole game, so three expansions in one
sounds/ tree cannot collide. The lengths and starts tables are one line per
passage, so concatenating three packs' tables is a correct table.

WHAT THIS DOES NOT TOUCH

The twelve pack repositories. They stay the source of truth, one expansion
each, and this reads from them. Audio is streamed from them straight into the
archive rather than staged, so nothing is copied that does not have to be. If
the merge is ever undone, nothing needs recovering.

Every archive is written to a .partial name, reopened, compared entry by entry
against what went in, and only then moved into place -- the same discipline
Tools/pack_release.py keeps, for the same reason: a listing cannot tell a
truncated archive from a good one, and one of these shipped that way once.
"""

import argparse
import os
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPOS = ROOT.parent
ENGINE = "WordHunterWoW-Voice-DE"
OUTDIR = REPOS.parent / "curseforge-packages"

# 80% of CurseForge's 2 GB per-file limit. Not the limit itself: an archive that
# lands at 1.99 GB has no room for the next expansion's clips, and the point of
# regrouping is to stop doing this.
TARGET = int(2000 * 1e6 * 0.80)
HARD_LIMIT = 2000 * 1e6

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from build_pack import EXPANSIONS, VANILLA_PACKS
except Exception:  # noqa: BLE001 -- the table is small enough to carry
    EXPANSIONS = [
        ("Classic", 1, 9665), ("BurningCrusade", 9666, 11579), ("Wrath", 11580, 14620),
        ("Cataclysm", 14621, 29377), ("Pandaria", 29378, 34575), ("Draenor", 34576, 39694),
        ("Legion", 39695, 48158), ("Azeroth", 48159, 56054), ("Shadowlands", 56055, 64000),
        ("Dragonflight", 64001, 74000), ("WarWithin", 74001, 10 ** 9),
    ]
    VANILLA_PACKS = {"Classic", "Words"}

RANGE = {name: (lo, hi) for name, lo, hi in EXPANSIONS}

# Target name -> members, in expansion order. The target is the repository and
# CurseForge project that keeps its name and grows; it need not come first.
GROUPS = {
    "Classic":   ["Classic", "BurningCrusade", "Wrath"],
    "Cataclysm": ["Cataclysm", "Pandaria", "Draenor"],
    "Legion":    ["Legion", "Azeroth", "Shadowlands"],
    # Dragonflight rides with the current expansion, not with Legion's pack.
    # Measured from the source files rather than from the old archives, Legion
    # plus all three of BfA, SL and DF came to 1616 MB -- 81%, sixteen
    # megabytes over the target the owner set. Moving DF here puts Legion at
    # 66% and this pack at 47%, both with room, and pairs the two newest
    # expansions, which is where the next one lands anyway.
    "WarWithin": ["Dragonflight", "WarWithin"],
    "Words":     ["Words"],
}
MERGED = [g for g, members in GROUPS.items() if len(members) > 1]

# What the eras are called on the addon page. Not the repository names, which a
# player never sees.
SHOWN = {
    "Classic": "Classic", "BurningCrusade": "Burning Crusade", "Wrath": "Wrath",
    "Cataclysm": "Cataclysm", "Pandaria": "Pandaria", "Draenor": "Draenor",
    "Legion": "Legion", "Azeroth": "Battle for Azeroth", "Shadowlands": "Shadowlands",
    "Dragonflight": "Dragonflight", "WarWithin": "The War Within", "Words": "Words",
}

SMALL_FILES = ("LICENSE", "NOTICE", "README.md", "icon.tga")


def folder_of(name):
    return "%s-%s" % (ENGINE, name)


def repo_of(name):
    return REPOS / folder_of(name)


def blob(part_text, folder, which):
    """One of the two tables out of a pack's Part.lua, or "" if it has none."""
    pattern = re.compile(
        r'WordHunterWoW_Voice_Parts\["' + re.escape(folder) + r'"\]\.' + which
        + r' = \[\[\n(.*?)\n\]\]', re.S)
    found = pattern.search(part_text)
    return found.group(1) if found else ""


def merged_part(target, members):
    """Part.lua for the merged pack: the union range and the joined tables."""
    folder = folder_of(target)
    lines = ["-- Generated by Tools/build_merged.py. Do not edit by hand.",
             "WordHunterWoW_Voice_Parts = WordHunterWoW_Voice_Parts or {}"]
    if target == "Words":
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { words = true }' % folder)
        return "\n".join(lines) + "\n"
    low = min(RANGE[m][0] for m in members)
    high = max(RANGE[m][1] for m in members)
    lines.append('WordHunterWoW_Voice_Parts["%s"] = { quests = { %d, %d } }' % (folder, low, high))
    lengths, starts = [], []
    for m in members:
        text = (repo_of(m) / "Part.lua").read_text(encoding="utf-8")
        l = blob(text, folder_of(m), "lengths")
        s = blob(text, folder_of(m), "starts")
        if l:
            lengths.append(l)
        if s:
            starts.append(s)
    lines.append('WordHunterWoW_Voice_Parts["%s"].lengths = [[' % folder)
    lines.append("\n".join(lengths))
    lines.append("]]")
    lines.append('WordHunterWoW_Voice_Parts["%s"].starts = [[' % folder)
    lines.append("\n".join(starts))
    lines.append("]]")
    return "\n".join(lines) + "\n"


# A backslash, kept out of string literals so that no tool between here and the
# shell can eat it. The clip path in the README is the one place it is needed.
BS = chr(92)


def counts(name):
    """Clips and seconds a member pack can be asked for, from its own table."""
    text = (repo_of(name) / "Part.lua").read_text(encoding="utf-8")
    clips, hundredths = 0, 0
    for line in blob(text, folder_of(name), "lengths").splitlines():
        cells = line.split()
        if len(cells) < 3:
            continue
        values = [int(v) for v in cells[2].split(",")]
        clips += len(values)
        hundredths += sum(values)
    return clips, hundredths / 100.0


def spoken(members):
    eras = [SHOWN[m] for m in members]
    return eras[0] if len(eras) == 1 else ", ".join(eras[:-1]) + " and " + eras[-1]


def ids(lo, hi):
    return "{:,} and up".format(lo) if hi >= 10 ** 9 else "{:,}–{:,}".format(lo, hi)


def still_reading(name):
    """Whether the member's own README says its expansion is still being read."""
    path = repo_of(name) / "README.md"
    return path.exists() and "still being read" in path.read_text(encoding="utf-8")


# The paragraphs every pack README shares, word for word. A merged archive
# gets them back unchanged; only what is specific to one expansion is rebuilt.
PARA_ONE_CLIP = """One clip per sentence, across the three passages an NPC speaks: the offer, the
progress line and the hand-in. Quest titles and objectives are not here. Nobody
says them out loud; they are read off the screen."""

PARA_BOUNDARY = """The boundary is a quest id range because ids were handed out roughly in the
order the content was written. It is approximate at the edges — a quest added to
an old zone years later keeps a new id — and harmlessly so: a quest outside the
range is silent for anyone who holds only this pack, which is what already
happens for a clip nobody has generated yet."""

PARA_CLASSIC_ERA = """## On Classic Era the words can differ

The clips were read from Retail quest text. On Classic Era the same quest id
does not always mean the same words: roughly one in five shared ids has a
different German title (`Garrick Padfoot` vs `Garrick Schleichfuß`,
`Blackrock` vs `Schwarzfelsklan`), and some ids are entirely different quests
on the two games. Offer, progress and hand-in lines come from the same source,
so where the text diverged you will hear the Retail telling. This note stands
until the clips are re-read from Classic text."""

PARA_ENGINE = """## It does nothing on its own

Everything that decides when to play a clip is in the engine addon,
[QuestWordHunter — German Voiceover](https://github.com/Ironship/WordHunterWoW-Voice-DE).
It is a hard dependency: without it the client will not load this pack at all."""

PARA_WHERE = """## Where a clip lives

`%s` — `o` is the offer, `p`
the progress line, `c` the hand-in, and sentences are numbered from one. The
engine computes that name and asks the client for it, so there is no index that
can fall out of step with the files. The two-digit folder is there only so that
nothing has to open a directory of tens of thousands of clips.""" % (
    "sounds" + BS + "q" + BS + "<id mod 100>" + BS + "<id>_<o|p|c><sentence>.ogg")

PARA_LICENCE = """GPL v3, see `LICENSE`. The audio carries CC BY-NC 4.0, which `NOTICE` sets out:
this is given away and may not be sold."""


def readme(target, members):
    """README.md for a merged archive.

    The repositories keep their own READMEs, one expansion each, and this does
    not touch them. An archive holding three expansions needs one that says so,
    with the clip count and the hours counted from the joined table -- the same
    way each repository counts its own -- rather than copied from the first
    member and left describing a third of the contents."""
    per = [(m,) + counts(m) for m in members]
    clips = sum(c for _, c, _ in per)
    seconds = sum(s for _, _, s in per)
    low = min(RANGE[m][0] for m in members)
    high = max(RANGE[m][1] for m in members)
    absorbed = [m for m in members if m != target]
    reading = [m for m in members if still_reading(m)]
    words = {2: "Two", 3: "Three", 4: "Four"}
    out = []
    out.append("# QuestWordHunter — German Voiceover: %s" % SHOWN[target])
    out.append("")
    out.append("The German a quest giver says out loud, for %s:" % spoken(members))
    out.append("quest ids **%s**." % ids(low, high))
    out.append("")
    out.append("**{:,} clips, {:.1f} hours.** Both are counted from this pack's own duration".format(
        clips, seconds / 3600))
    out.append("table in `Part.lua` — the table the engine plays from — so they are what the")
    out.append("pack can actually be asked for, not what happens to sit on disk.")
    if reading:
        out.append("")
        out.append("%s %s **still being read**, so the numbers are a snapshot taken" % (
            spoken(reading), "is" if len(reading) == 1 else "are"))
        out.append("when this archive was built and will grow.")
    out.append("")
    out.append(PARA_ONE_CLIP)
    out.append("")
    out.append("## %s expansions in one pack" % words.get(len(members), len(members)))
    out.append("")
    out.append("| Expansion | Quest ids | Clips | Hours |")
    out.append("| --- | --- | ---: | ---: |")
    for m, c, s in per:
        out.append("| %s | %s | %s | %.1f |" % (SHOWN[m], ids(*RANGE[m]), "{:,}".format(c), s / 3600))
    out.append("")
    out.append("This one upload replaces the separate %s pack%s, which %s not" % (
        spoken(absorbed), "" if len(absorbed) == 1 else "s", "is" if len(absorbed) == 1 else "are"))
    out.append("updated any more. CurseForge allows 2 GB per file and one file for all of")
    out.append("the audio would be three times that, so the expansions are grouped into four")
    out.append("uploads rather than eleven. If an older separate pack is still installed,")
    out.append("remove it: the engine finds a quest's pack by its id range, which one of two")
    out.append("packs claiming the same range answers is not defined, and the old one may be")
    out.append("behind.")
    out.append("")
    out.append(PARA_BOUNDARY)
    if target in VANILLA_PACKS:
        out.append("")
        out.append(PARA_CLASSIC_ERA)
    out.append("")
    out.append(PARA_ENGINE)
    out.append("")
    out.append(PARA_WHERE)
    out.append("")
    if target in VANILLA_PACKS:
        out.append("Retail 12.1 (interface 120100) and Classic Era (11509) — one manifest each.")
    else:
        out.append("Retail 12.1 (interface 120100).")
    out.append(PARA_LICENCE)
    return "\n".join(out) + "\n"


def manifest(target, members, interface, version):
    folder = folder_of(target)
    if target == "Words":
        notes = "German audio for single dictionary words. Needs %s." % ENGINE
        deps = "%s, WordHunterWoW" % ENGINE
    else:
        notes = "German quest audio for %s. Needs %s." % (spoken(members), ENGINE)
        deps = ENGINE
    return (
        "## Interface: %s\n"
        "## Title: QuestWordHunter - German Voiceover: %s\n"
        "## Notes: %s\n"
        "## IconTexture: Interface\\AddOns\\%s\\icon\n"
        "## Author: Ironship\n"
        "## Version: %s\n"
        "## Dependencies: %s\n"
        "\n"
        "Part.lua\n" % (interface, SHOWN[target], notes, folder, version, deps))


def audio_of(name):
    """Every clip a member pack ships, as (archive-relative path, source path)."""
    base = repo_of(name) / "sounds"
    if not base.is_dir():
        sys.exit("%s: no sounds/ -- is the audio checked out?" % folder_of(name))
    for src in sorted(base.rglob("*.ogg")):
        yield "sounds/%s" % src.relative_to(base).as_posix(), src


def current_version(name):
    """The version an unchanged pack already carries, so it is not renumbered."""
    toc = repo_of(name) / ("%s_Mainline.toc" % folder_of(name))
    found = re.search(r"^## Version:\s*(.+)$", toc.read_text(encoding="utf-8-sig"), re.M)
    return found.group(1).strip() if found else None


def plan(target, members, version):
    """Everything that goes into the archive, small files first."""
    folder = folder_of(target)
    # The licence, the Questie notice, the README and the icon come from the
    # repository whose name the pack keeps -- not from members[0], which for
    # the WarWithin pack is Dragonflight. Same thing for the other groups.
    named = repo_of(target)
    entries = []   # (arcname, bytes-or-path)
    for small in SMALL_FILES:
        if small == "README.md" and len(members) > 1:
            entries.append(("%s/README.md" % folder, readme(target, members).encode("utf-8")))
            continue
        src = named / small
        if src.exists():
            entries.append(("%s/%s" % (folder, small), src))
    entries.append(("%s/Part.lua" % folder, merged_part(target, members).encode("utf-8")))
    entries.append(("%s/%s_Mainline.toc" % (folder, folder),
                    manifest(target, members, "120100", version).encode("utf-8")))
    if target in VANILLA_PACKS:
        entries.append(("%s/%s_Vanilla.toc" % (folder, folder),
                        manifest(target, members, "11509", version).encode("utf-8")))
    for m in members:
        for rel, src in audio_of(m):
            entries.append(("%s/%s" % (folder, rel), src))
    return entries


def size_of(entries):
    total = 0
    for _, payload in entries:
        total += len(payload) if isinstance(payload, bytes) else payload.stat().st_size
    return total


def write_archive(target, entries, version, outdir, store):
    folder = folder_of(target)
    archive = outdir / ("%s-%s.zip" % (folder, version))
    partial = archive.with_suffix(".zip.partial")
    if partial.exists():
        partial.unlink()
    expected = {}
    method = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(partial, "w", method, allowZip64=True) as z:
        for arcname, payload in entries:
            if isinstance(payload, bytes):
                z.writestr(arcname, payload)
                expected[arcname] = len(payload)
            else:
                # Ogg is already compressed; deflating it buys ~3% and costs
                # minutes over 1.5 GB. Stored, unless asked otherwise.
                z.write(payload, arcname,
                        compress_type=zipfile.ZIP_STORED if arcname.endswith(".ogg") else method)
                expected[arcname] = payload.stat().st_size
    with zipfile.ZipFile(partial) as z:
        written = {i.filename: i.file_size for i in z.infolist()}
    problems = []
    missing = set(expected) - set(written)
    extra = set(written) - set(expected)
    if missing:
        problems.append("%d file(s) missing, e.g. %s" % (len(missing), sorted(missing)[0]))
    if extra:
        problems.append("%d unexpected file(s)" % len(extra))
    short = [n for n, s in written.items() if n in expected and s != expected[n]]
    if short:
        problems.append("%d file(s) stored at the wrong size" % len(short))
    size = partial.stat().st_size
    if size > HARD_LIMIT:
        problems.append("%.2f GB is over CurseForge's 2 GB limit" % (size / 1e9))
    if problems:
        return None, size, problems
    if archive.exists():
        archive.unlink()
    os.replace(partial, archive)
    return archive, size, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one target: Classic, Cataclysm, Legion, WarWithin, Words")
    ap.add_argument("--all", action="store_true",
                    help="also rebuild WarWithin and Words, which do not change shape")
    ap.add_argument("--version", default="2.0.0",
                    help="version stamped on the merged packs (unchanged packs keep theirs)")
    ap.add_argument("--out", default=str(OUTDIR))
    ap.add_argument("--store", action="store_true", help="store everything, deflate nothing")
    ap.add_argument("--dry-run", action="store_true", help="sizes from the sources; write nothing")
    ap.add_argument("--readme", metavar="TARGET", help="print the README a merged archive would carry")
    args = ap.parse_args()

    if args.readme:
        if args.readme not in GROUPS:
            sys.exit("no such target: %s (one of %s)" % (args.readme, ", ".join(GROUPS)))
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(readme(args.readme, GROUPS[args.readme]))
        return 0

    if args.only:
        targets = [args.only]
        if args.only not in GROUPS:
            sys.exit("no such target: %s (one of %s)" % (args.only, ", ".join(GROUPS)))
    elif args.all:
        targets = list(GROUPS)
    else:
        targets = MERGED

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    grand, failures = 0, []
    print("%-12s %-34s %9s %6s  %s" % ("pack", "members", "size", "of 2GB", "status"))
    for target in targets:
        members = GROUPS[target]
        version = args.version if target in MERGED else (current_version(target) or args.version)
        entries = plan(target, members, version)
        size = size_of(entries)
        grand += size
        over = "OVER TARGET" if size > TARGET else ""
        if args.dry_run:
            print("%-12s %-34s %6.0f MB %5.0f%%  %s" % (
                target, "+".join(members), size / 1e6, 100 * size / HARD_LIMIT,
                over or "would build v%s, %d files" % (version, len(entries))))
            continue
        archive, actual, problems = write_archive(target, entries, version, outdir, args.store)
        if problems:
            failures.append(target)
            print("%-12s %-34s %6.0f MB %5.0f%%  FAILED" % (
                target, "+".join(members), actual / 1e6, 100 * actual / HARD_LIMIT))
            for p in problems:
                print("      %s" % p)
        else:
            print("%-12s %-34s %6.0f MB %5.0f%%  ok  %s%s" % (
                target, "+".join(members), actual / 1e6, 100 * actual / HARD_LIMIT,
                archive.name, "  " + over if over else ""))
    print("\n%d pack(s), %.2f GB total" % (len(targets), grand / 1e9))
    if failures:
        print("%d FAILED -- nothing moved into place for those" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
