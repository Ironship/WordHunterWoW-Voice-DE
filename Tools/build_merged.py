#!/usr/bin/env python3
"""Assemble the sound packs that ship -- audio, a copy of the engine, a manifest,
a README -- and prove each archive opens.

    python Tools/build_merged.py --dry-run                # sizes only, nothing written
    python Tools/build_merged.py                          # every pack of the default layout
    python Tools/build_merged.py --only Words
    python Tools/build_merged.py --layout five --dry-run  # the other grouping
    python Tools/build_merged.py --readme Classic         # the README an archive would carry
    python Tools/build_merged.py --descriptions           # the CurseForge page for each pack

WHY SEVERAL PACKS AND NOT ONE

Thirteen CurseForge projects for one voiceover is what the platform objected
to. One file is impossible: the audio is 5.96 GB against a 2 GB limit per
upload, and re-encoding was measured (Tools/size_probe.py) and declined -- Vorbis
at 24 kHz mono is already near its floor, and the one lever that buys anything,
16 kHz, costs quality the owner heard and refused. So the packs are regrouped
at the quality they have, into as few archives as fit under the limit.

Measured from the source files on 2026-09-19 (MB; an archive adds ~0.7%):

    Classic 648   BurningCrusade 346   Wrath 470   Cataclysm 790   Pandaria 409
    Draenor 326   Legion 447   Azeroth 434   Shadowlands 433   Dragonflight 301
    WarWithin 642   Words 800

Two layouts are kept, and --layout picks one:

    four   Classic     Classic + TBC + Wrath             1464 MB   73%
           Cataclysm   Cata + MoP + WoD + Legion         1972 MB   99%
           Modern      BfA + SL + DF + TWW               1810 MB   91%
           Words       the dictionary                     800 MB   40%

    five   Classic     Classic + TBC + Wrath             1464 MB   73%
           Cataclysm   Cata + MoP + WoD                  1525 MB   76%
           Legion      Legion + BfA + SL                 1314 MB   66%
           WarWithin   DF + TWW                           943 MB   47%
           Words       the dictionary                     800 MB   40%

"four" is the owner's grouping and the fewest projects possible, decided on
2026-09-19 with the numbers in view. 5.2 GB of quest audio into three files
is 1.75 GB each on average, and no split of eleven expansions into three
keeps every file under the 80% target. The one pack that can afford to sit at
the limit is the one that will not grow -- Cataclysm through Legion are read
in full and finished -- so that is the one that does, at 99%: the archive
comes to about 1,990 MB against the 2,000 MB this tool refuses above, and the
owner accepted that margin. What must not sit at the limit is the Classic
pack, which is what the Forever client installs, and Forever adds quests of
its own -- a thousand already, at Classic's 0.154 MB per quest about 150 MB
-- so Classic + TBC + Wrath stays at 73% with room for them. Modern at 91% is
the compromise: the WarWithin member is "74001 and up", so a patch's new
quests land there; the day it no longer fits, Dragonflight moves out. "five"
is the layout every archive fits under 80%, built on 2026-09-18, and stays as
the fallback.

THE ENGINE RIDES IN EVERY PACK

There is no separate engine project any more. Every archive carries the five
Lua files the engine's own manifest loads, and the two stand-in clips, ahead
of its Part.lua; the client runs the first copy it loads and the others stand
down at their first line -- Naming.lua in the engine says how, and
tests/engine-copies.test.lua proves it. So any one pack is a whole install,
and a player never has to find a second download to make the first one speak.
The files come from this repository's working copy, read off the manifest
rather than listed here, so a file added to the engine arrives in every pack
without this tool being edited. The version the engine writes into Naming.lua
must match the manifest's, or nothing is built.

A pack whose expansions are not neighbours cannot declare one quest id range
-- Classic + TBC + Wrath + Draenor, say, would span 1 to 39,694 with Cataclysm
and Pandaria in the gap. Such a pack's Part.lua keeps the span as `quests`,
for an engine older than this, and adds `ranges`, the exact runs, which the
engine reads first -- so a Cataclysm quest is Cataclysm's even though the
other span holds it. Neither layout above needs it today; the engine and the
test keep it so that the next regrouping can. Clip paths are sharded by quest
id (sounds/q/<id % 100>/...), and quest ids are unique across the whole game,
so four expansions in one sounds/ tree cannot collide. The lengths and starts
tables are one line per passage, so concatenating the members' tables is a
correct table.

WHAT THIS DOES NOT TOUCH

The twelve pack repositories. They stay the source of truth, one expansion
each, and this reads from them. Audio is streamed from them straight into the
archive rather than staged, so nothing is copied that does not have to be. If
the grouping is ever changed again, nothing needs recovering.

Every archive is written to a .partial name, reopened, compared entry by entry
against what went in -- including that every file its manifest loads is there
-- and only then moved into place: the same discipline Tools/pack_release.py
keeps, for the same reason. A listing cannot tell a truncated archive from a
good one, and one of these shipped that way once.
"""

import argparse
import html
import os
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPOS = ROOT.parent
ENGINE = "WordHunterWoW-Voice-DE"
OUTDIR = REPOS.parent / "curseforge-packages"

# Set by --audio/--ext. None means the clips come from each member repository's
# own sounds/, which is where the masters live and what every build did before
# the transcoded trees existed.
AUDIO_DIR = None
AUDIO_EXT = "ogg"


def audio_base(name):
    """The folder holding one member's clips, whichever tree is in use."""
    if AUDIO_DIR is not None:
        return AUDIO_DIR / name / "sounds"
    return repo_of(name) / "sounds"

# 80% of CurseForge's 2 GB per-file limit. Not the limit itself: an archive that
# lands at 1.99 GB has no room for the next expansion's clips, and the point of
# regrouping is to stop doing this. The four-project layout cannot meet it and
# says so in its report; the number stays as the mark to measure against.
TARGET = int(2000 * 1e6 * 0.80)
HARD_LIMIT = 2000 * 1e6

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from build_pack import EXPANSIONS, VANILLA_PACKS, FOREVER_PACK, FOREVER_RUNS
except Exception:  # noqa: BLE001 -- the table is small enough to carry
    EXPANSIONS = [
        ("Classic", 1, 9665), ("BurningCrusade", 9666, 11579), ("Wrath", 11580, 14620),
        ("Cataclysm", 14621, 29377), ("Pandaria", 29378, 34575), ("Draenor", 34576, 39694),
        ("Legion", 39695, 48158), ("Azeroth", 48159, 56054), ("Shadowlands", 56055, 64000),
        ("Dragonflight", 64001, 74000), ("WarWithin", 74001, 10 ** 9),
    ]
    VANILLA_PACKS = {"Classic", "Words"}
    FOREVER_PACK, FOREVER_RUNS = "Classic", [(97277, 97277)]

RANGE = {name: (lo, hi) for name, lo, hi in EXPANSIONS}

# Layout name -> target -> members, in expansion order. A target is the folder
# the pack installs as and the CurseForge project it is uploaded to; where a
# target has a repository of its own, the licence, notice and icon come from
# there, and NAMED says where they come from otherwise.
LAYOUTS = {
    "four": {
        "Classic":   ["Classic", "BurningCrusade", "Wrath"],
        "Cataclysm": ["Cataclysm", "Pandaria", "Draenor", "Legion"],
        "Modern":    ["Azeroth", "Shadowlands", "Dragonflight", "WarWithin"],
        "Words":     ["Words"],
    },
    # The mp3 layout. At 16 kbps the whole voiceover is 2.01 GiB, which is two
    # archives rather than four, and the split falls after Pandaria. Names
    # rather than --cap defaults, because the folder name is written into the
    # path of every clip: renaming the pack afterwards means rebuilding it.
    "two": {
        "Classic":   ["Classic", "BurningCrusade", "Wrath", "Cataclysm", "Pandaria"],
        "Modern":    ["Draenor", "Legion", "Azeroth", "Shadowlands", "Dragonflight", "WarWithin"],
    },
    "five": {
        "Classic":   ["Classic", "BurningCrusade", "Wrath"],
        "Cataclysm": ["Cataclysm", "Pandaria", "Draenor"],
        "Legion":    ["Legion", "Azeroth", "Shadowlands"],
        "WarWithin": ["Dragonflight", "WarWithin"],
        "Words":     ["Words"],
    },
}
DEFAULT_LAYOUT = "four"
NAMED = {"Modern": "WarWithin"}

# What an archive costs over the audio it holds: the zip's own headers, one per
# file, plus the engine and the tables. Measured across the four archives built
# on 2026-09-19 -- 1475/1464, 1989/1972, 1826/1810, 821/815 -- and rounded up.
OVERHEAD = 1.009


def measured_sizes(names=None):
    """Bytes of ogg per expansion, from the repositories. Slow the first time."""
    out = {}
    every = [n for n, _lo, _hi in EXPANSIONS]
    # The dictionary is only a pack of its own in the ogg tree; its audio ships
    # inside the dictionary addon now, so a transcoded tree does not carry it.
    if AUDIO_DIR is None:
        every = every + ["Words"]
    for name in names or every:
        base = audio_base(name)
        if not base.is_dir():
            sys.exit("%s: no %s -- is the audio there?" % (name, base))
        out[name] = sum(f.stat().st_size for f in base.rglob("*." + AUDIO_EXT))
    return out


def layout_for_cap(cap_bytes, sizes=None):
    """The fewest packs whose archives all fit under cap_bytes, keeping the
    expansions in order.

    In order, because a pack a player can describe -- "Classic through Wrath"
    -- is a pack they can choose, and because a group that skips an expansion
    has to declare its runs and explain the hole. Among the groupings with the
    fewest packs, the one whose largest pack is smallest is taken, so the
    headroom is spread rather than left on one pack. The dictionary is a pack
    of its own always: it holds no quests and cannot share a range with any.

    Returns the same shape as LAYOUTS[...]: target -> members, target being the
    first expansion of the group, which is the project that keeps its name."""
    sizes = sizes or measured_sizes()
    names = [n for n, _lo, _hi in EXPANSIONS]
    room = cap_bytes / OVERHEAD
    n = len(names)
    too_big = [m for m in names if sizes[m] > room]
    if too_big:
        sys.exit("%s alone is over the cap -- no grouping can help; the audio "
                 "itself would have to be split or re-encoded" % ", ".join(too_big))
    # best[i] = (packs, largest, cuts) for names[i:], packs minimal then largest minimal
    best = [None] * (n + 1)
    best[n] = (0, 0, [])
    for i in range(n - 1, -1, -1):
        total, chosen = 0, None
        for j in range(i, n):
            total += sizes[names[j]]
            if total > room:
                break
            packs, largest, cuts = best[j + 1]
            here = (packs + 1, max(largest, total), [j + 1] + cuts)
            if chosen is None or here[:2] < chosen[:2]:
                chosen = here
        best[i] = chosen
    layout, start = {}, 0
    for cut in best[0][2]:
        members = names[start:cut]
        layout[members[0]] = members
        start = cut
    # The dictionary is a pack of its own only in the ogg tree. Its audio ships
    # inside WordHunterWoW-Dictionary-DE now, and a transcoded tree does not
    # carry it, so there is nothing to group.
    if AUDIO_DIR is None:
        layout["Words"] = ["Words"]
    return layout

# What the eras are called on the addon page. Not the repository names, which a
# player never sees.
SHOWN = {
    "Classic": "Classic", "BurningCrusade": "Burning Crusade", "Wrath": "Wrath",
    "Cataclysm": "Cataclysm", "Pandaria": "Pandaria", "Draenor": "Draenor",
    "Legion": "Legion", "Azeroth": "Battle for Azeroth", "Shadowlands": "Shadowlands",
    "Dragonflight": "Dragonflight", "WarWithin": "The War Within", "Words": "Words",
    "Modern": "Modern",
}

# How a pack is named where a player meets it. The CurseForge project title is
# this with "QuestWordHunter — German " in front; the edit form allows 128
# characters, so the full word fits and no abbreviation is needed.
def pack_label(target):
    return "Voiceover: %s" % SHOWN[target]


def pack_title(target):
    return "QuestWordHunter — German Voiceover: %s" % SHOWN[target]


def holders(layout):
    """Which pack speaks each expansion, and the order to list them in."""
    return {m: target for target, members in layout.items() for m in members}


SMALL_FILES = ("LICENSE", "NOTICE", "README.md", "icon.tga")

# Retail, and World of Warcraft: Forever, which loads the Mainline manifest and
# looks for its own number in the list. Only the packs that also ship a Classic
# Era manifest list it: Forever's content is Classic's.
RETAIL_INTERFACE = "120100, 120105"
FOREVER_INTERFACE = "16001"
ERA_INTERFACE = "11509"


def folder_of(name):
    return "%s-%s" % (ENGINE, name)


def repo_of(name):
    return REPOS / folder_of(name)


def named_repo(target):
    """The repository a target's licence, notice and icon come from."""
    return repo_of(NAMED.get(target, target))


# --- the engine's files ------------------------------------------------------

def engine_loads():
    """The files the engine's manifest loads, in its order. Read, not listed."""
    toc = (ROOT / ("%s_Mainline.toc" % ENGINE)).read_text(encoding="utf-8-sig")
    loads = [line.strip() for line in toc.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not loads:
        sys.exit("the engine's manifest loads nothing -- is this the engine repository?")
    return loads


def engine_version():
    """The version Naming.lua writes into every copy, held to the manifest's."""
    literal = re.search(r'^local ENGINE_VERSION = "([^"]+)"',
                        (ROOT / "Naming.lua").read_text(encoding="utf-8"), re.M)
    toc = (ROOT / ("%s_Mainline.toc" % ENGINE)).read_text(encoding="utf-8-sig")
    declared = re.search(r"^## Version:\s*(.+)$", toc, re.M)
    if not literal or not declared:
        sys.exit("cannot read the engine's version from Naming.lua and the manifest")
    if literal.group(1) != declared.group(1).strip():
        sys.exit("Naming.lua says the engine is %s, the manifest says %s -- settle that first"
                 % (literal.group(1), declared.group(1).strip()))
    return literal.group(1)


def engine_files():
    """(archive-relative path, source path) for everything a pack carries of the engine."""
    for rel in engine_loads():
        src = ROOT / rel
        if not src.is_file():
            sys.exit("the engine's manifest loads %s, which is not here" % rel)
        yield rel, src
    # The stand-in clips Voice.lua builds a path to at runtime, under the folder
    # it is running from -- which is the pack's, so every pack carries them.
    demo = sorted((ROOT / "demo").glob("*.ogg"))
    if not demo:
        sys.exit("no stand-in clips in demo/")
    for src in demo:
        yield "demo/%s" % src.name, src


# --- Part.lua ----------------------------------------------------------------

def blob(part_text, folder, which):
    """One of the two tables out of a pack's Part.lua, or "" if it has none."""
    pattern = re.compile(
        r'WordHunterWoW_Voice_Parts\["' + re.escape(folder) + r'"\]\.' + which
        + r' = \[\[\n(.*?)\n\]\]', re.S)
    found = pattern.search(part_text)
    return found.group(1) if found else ""


def runs_of(members, forever=True):
    """The members' quest id ranges joined where they touch: the exact runs.

    With the pack Forever installs among the members, Forever's own quests are
    runs of it too (FOREVER_QUESTS in build_pack.py says why). forever=False
    leaves them out, which is the span an engine without `ranges` is given."""
    pairs = [RANGE[m] for m in members]
    if forever and FOREVER_PACK in members:
        pairs += list(FOREVER_RUNS)
    runs = []
    for lo, hi in sorted(pairs):
        if runs and lo == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], hi)
        else:
            runs.append((lo, hi))
    return runs


def merged_part(target, members):
    """Part.lua for the pack: the span, the exact runs if there is more than
    one, and the joined tables."""
    folder = folder_of(target)
    lines = ["-- Generated by Tools/build_merged.py. Do not edit by hand.",
             "WordHunterWoW_Voice_Parts = WordHunterWoW_Voice_Parts or {}"]
    if target == "Words":
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { words = true }' % folder)
        return "\n".join(lines) + "\n"
    runs = runs_of(members)
    # The span is the expansions' alone. Forever's quests lie far outside it,
    # and a span stretched to reach them would hand an engine that reads only
    # the pair every Retail quest in between.
    span = runs_of(members, forever=False)
    low, high = span[0][0], span[-1][1]
    lines.append('WordHunterWoW_Voice_Parts["%s"] = { quests = { %d, %d } }' % (folder, low, high))
    if len(runs) > 1:
        lines.append("-- The pair above is the span of this pack's expansions, for an engine that")
        lines.append("-- knows only the pair, and these are the runs the engine reads. Quests between")
        lines.append("-- the runs belong to another pack.")
        if runs != span:
            lines.append("-- The runs past the span are World of Warcraft: Forever's own quests,")
            lines.append("-- which are numbered among Retail's.")
        lines.append('WordHunterWoW_Voice_Parts["%s"].ranges = { %s }' % (
            folder, ", ".join("{ %d, %d }" % run for run in runs)))
    lengths, starts = [], []
    for m in members:
        text = (repo_of(m) / "Part.lua").read_text(encoding="utf-8")
        l = blob(text, folder_of(m), "lengths")
        s = blob(text, folder_of(m), "starts")
        if l:
            lengths.append(l)
        if s:
            starts.append(s)
    if AUDIO_EXT != "ogg":
        # Naming.lua maps anything that is not "mp3" to "ogg", so a pack of mp3
        # that stays quiet about it sends the engine looking for files that are
        # not in the archive.
        lines.append('WordHunterWoW_Voice_Parts["%s"].ext = "%s"' % (folder, AUDIO_EXT))
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


def words_counts():
    """The Words pack has no duration table; its own README carries the figures."""
    text = (repo_of("Words") / "README.md").read_text(encoding="utf-8")
    found = re.search(r"\*\*([\d,]+) clips, ([\d.]+) hours\.\*\*", text)
    if not found:
        sys.exit("the Words README no longer states its clips and hours where this reads them")
    return int(found.group(1).replace(",", "")), float(found.group(2)) * 3600


def spoken(members):
    eras = [SHOWN[m] for m in members]
    return eras[0] if len(eras) == 1 else ", ".join(eras[:-1]) + " and " + eras[-1]


def ids(lo, hi):
    return "{:,} and up".format(lo) if hi >= 10 ** 9 else "{:,}–{:,}".format(lo, hi)


def ids_of_runs(runs):
    return " and ".join(ids(lo, hi) for lo, hi in runs)


def still_reading(name):
    """Whether the member's own README says its expansion is still being read."""
    path = repo_of(name) / "README.md"
    return path.exists() and "still being read" in path.read_text(encoding="utf-8")


def number(n):
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
            8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}.get(n, str(n))


def games(target):
    if target in VANILLA_PACKS:
        return ("Retail 12.1 (interfaces 120100 and 120105) and World of Warcraft: Forever (16001) share a "
                "manifest; Classic Era (11509) has its own.")
    return "Retail 12.1 (interfaces 120100 and 120105)."


# --- the README ----------------------------------------------------------------
#
# The paragraphs every pack README shares, word for word. Only what is specific
# to one pack is rebuilt.

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

PARA_ENGINE = """## The reader is inside

The five Lua files are the engine that plays the clips — the same engine in
every pack, and one runs however many packs are installed: the first the client
loads takes the job, and the copies in the other packs stand down at their first
line. Nothing else needs installing.
[QuestWordHunter](https://github.com/Ironship/WordHunterWoW) is optional, and
adds a play button beside each paragraph when it is there. If the separate
engine addon from before, `WordHunterWoW-Voice-DE`, is still in
`Interface/AddOns`, remove it: it would run in place of these and is behind them.

The options page — Options, AddOns, QuestWordHunter Voice, or `/whwv config` —
lists the packs installed and says which pack's copy of the engine is running.
After updating one pack of several, the newest engine can be on disk and not
running; the page names the pack to update when that happens."""

PARA_WHERE = """## Where a clip lives

`%s` — `o` is the offer, `p`
the progress line, `c` the hand-in, and sentences are numbered from one. The
engine computes that name and asks the client for it, so there is no index that
can fall out of step with the files. The two-digit folder is there only so that
nothing has to open a directory of tens of thousands of clips.""" % (
    "sounds" + BS + "q" + BS + "<id mod 100>" + BS + "<id>_<o|p|c><sentence>.ogg")

PARA_LICENCE = """GPL v3, see `LICENSE` — the engine's licence, and the code in this pack is the
engine. The audio carries CC BY-NC 4.0, which `NOTICE` sets out: this is given
away and may not be sold."""

# What the Words repository's README says about the engine, replaced in the
# archive's copy. Anchored to the letter, so that a change to the README is
# noticed here rather than shipped around.
WORDS_OLD_ENGINE = """## It does nothing on its own, and it needs two addons rather than one

Everything that decides when to play a clip is in the engine addon,
[QuestWordHunter — German Voiceover](https://github.com/Ironship/WordHunterWoW-Voice-DE).

It also needs [QuestWordHunter](https://github.com/Ironship/WordHunterWoW)
itself, which the quest packs do not. A quest pack plays when a quest window
opens, and the engine watches for that on its own. A word plays when somebody
clicks one, and clicking a word is something only QuestWordHunter's panel
offers — so without it these clips are 104,274 files nothing can reach.

Both are hard dependencies: without either, the client will not load this pack
at all."""

WORDS_NEW_ENGINE = """## The reader is inside, and it needs QuestWordHunter

The five Lua files are the engine that plays the clips — the same engine in
every pack, and one runs however many packs are installed: the first the client
loads takes the job, and the copies in the other packs stand down at their first
line. If the separate engine addon from before, `WordHunterWoW-Voice-DE`, is
still in `Interface/AddOns`, remove it: it would run in place of these and is
behind them.

This pack also needs [QuestWordHunter](https://github.com/Ironship/WordHunterWoW)
itself, which the quest packs do not. A quest pack plays when a quest window
opens, and the engine watches for that on its own. A word plays when somebody
clicks one, and clicking a word is something only QuestWordHunter's panel
offers — so without it these clips are 104,274 files nothing can reach. It is
a hard dependency: without it the client will not load this pack at all.

Its natural companion is the
[German dictionary](https://github.com/Ironship/WordHunterWoW-Dictionary-DE),
which gives a clicked word its meaning while this pack gives it a voice. They
are separate downloads because one is 3 MB of text and the other is 821 MB of
audio, and nobody who only wants the meanings should have to take the audio."""

WORDS_OLD_GAMES = "Retail 12.1 (interfaces 120100 and 120105) and Classic Era (11509) — one manifest each."


def coverage(target, layout):
    """Every expansion of the game, and which pack speaks it.

    The one table a player has to read. A pack holding three expansions of
    eleven looks, from its own page, like the whole thing -- and a quest with
    no recording is silent rather than broken, so nothing on screen says that
    the audio is in another download. This says it."""
    quest_packs = [t for t in layout if t != "Words"]
    held = holders(layout)
    rows = []
    for m, _lo, _hi in EXPANSIONS:
        owner = held.get(m)
        clips, seconds = counts(m)
        where = "**THIS PACK**" if owner == target else pack_label(owner) if owner else "not recorded"
        rows.append("| %s | %s | %s | %.1f | %s |" % (
            SHOWN[m], ids(*RANGE[m]), "{:,}".format(clips), seconds / 3600, where))
    clips, seconds = words_counts()
    rows.append("| *Single words you click* | — | %s | %.1f | %s |" % (
        "{:,}".format(clips), seconds / 3600,
        "**THIS PACK**" if target == "Words" else pack_label("Words")))
    out = []
    if target == "Words":
        out.append("## What this pack does, and what it does not")
        out.append("")
        out.append("It speaks **single words**, one at a time, when you click one. It speaks")
        out.append("**no quest text at all** — not for any expansion. Quest narration is in the")
        out.append("%s other packs, and this one is used together with them, not instead." % number(len(quest_packs)))
    else:
        out.append("## What this pack covers: %s of the %s expansions" % (
            number(len(layout[target])), number(len(EXPANSIONS))))
        out.append("")
        out.append("Read the last column. Where it does not say **THIS PACK**, those quests are")
        out.append("**silent** unless you also install the pack it names. Nothing breaks and no")
        out.append("error appears — there is simply no recording, which looks exactly like an")
        out.append("addon that is not working. This table is the whole of the difference.")
    out.append("")
    out.append("| Expansion of the game | Quest ids | Clips | Hours | Spoken by |")
    out.append("| --- | --- | ---: | ---: | --- |")
    out.extend(rows)
    out.append("")
    out.append("### The %s packs, and what each one speaks" % number(len(layout)))
    out.append("")
    for other in layout:
        what = ("every word in the German dictionary, spoken when you click one — needs QuestWordHunter"
                if other == "Words" else spoken(layout[other]))
        mark = "  ← **you are here**" if other == target else ""
        out.append("- **%s** — %s%s" % (pack_title(other), what, mark))
    out.append("")
    out.append("Install as many as you play; they do not overlap, and no clip is in two of")
    out.append("them. Each carries the same reader, and one reader runs however many packs")
    out.append("are installed.")
    return out


def readme(target, members, layout):
    """README.md for an archive.

    The repositories keep their own READMEs, one expansion each, and this does
    not touch them. An archive holding several expansions needs one that says
    so, with the clip count and the hours counted from the joined table -- the
    same way each repository counts its own -- rather than copied from the
    first member and left describing a third of the contents. The Words archive
    takes its repository's README with the paragraph about the engine replaced
    and the coverage table put in."""
    if target == "Words":
        text = (repo_of("Words") / "README.md").read_text(encoding="utf-8")
        cover = "\n".join(coverage(target, layout)) + "\n\n"
        for old, new in ((WORDS_OLD_ENGINE, cover + WORDS_NEW_ENGINE),
                         (WORDS_OLD_GAMES, games("Words"))):
            if text.count(old) != 1:
                sys.exit("the Words README no longer holds the passage this replaces:\n%s" % old[:80])
            text = text.replace(old, new, 1)
        return text
    per = [(m,) + counts(m) for m in members]
    clips = sum(c for _, c, _ in per)
    seconds = sum(s for _, _, s in per)
    # The expansions' ids. Forever's handful are not a range a reader can use.
    runs = runs_of(members, forever=False)
    reading = [m for m in members if still_reading(m)]
    out = []
    out.append("# %s" % pack_title(target))
    out.append("")
    out.append("The German a quest giver says out loud, and **only for %s**:" % spoken(members))
    out.append("quest ids **%s**. The other expansions are in the other packs — the table" % ids_of_runs(runs))
    out.append("below says which.")
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
    out.extend(coverage(target, layout))
    out.append("")
    out.append("CurseForge allows 2 GB per file and all of the audio is three times that, so")
    out.append("it cannot be one download. If a separate pack for one of these expansions is")
    out.append("still installed from before the grouping, remove it: two packs claiming the")
    out.append("same quest is not defined, and the old one is behind.")
    if len(runs) > 1:
        out.append("")
        out.append("The expansions here are not neighbours — the quest ids %s" % ids(runs[0][1] + 1, runs[1][0] - 1))
        out.append("belong to another pack — so `Part.lua` declares the exact runs beside the span,")
        out.append("and the engine reads the runs.")
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
    out.append(games(target))
    out.append(PARA_LICENCE)
    return "\n".join(out) + "\n"


# --- the CurseForge page -------------------------------------------------------

def h(text):
    return html.escape(text, quote=False)


def coverage_html(target, layout):
    """The same table as the README's, for the project page."""
    held = holders(layout)
    out = []
    if target == "Words":
        out.append("<h3>What this pack does, and what it does not</h3>")
        out.append("<p>It speaks <strong>single words</strong>, one at a time, when you click one. It "
                   "speaks <strong>no quest text at all</strong> — not for any expansion. Quest "
                   "narration is in the other packs, and this one is used together with them.</p>")
    else:
        out.append("<h3>What this pack covers: %s of the %s expansions</h3>" % (
            number(len(layout[target])), number(len(EXPANSIONS))))
        out.append("<p>Read the last column. Where it does not say <strong>THIS PACK</strong>, those "
                   "quests are <strong>silent</strong> unless you also install the pack it names. "
                   "Nothing breaks and no error appears — there is simply no recording, which looks "
                   "exactly like an addon that is not working.</p>")
    out.append("<table><thead><tr><th>Expansion of the game</th><th>Quest ids</th><th>Clips</th>"
               "<th>Hours</th><th>Spoken by</th></tr></thead><tbody>")
    for m, _lo, _hi in EXPANSIONS:
        owner = held.get(m)
        clips, seconds = counts(m)
        where = ("<strong>THIS PACK</strong>" if owner == target
                 else h(pack_label(owner)) if owner else "not recorded")
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%.1f</td><td>%s</td></tr>" % (
            h(SHOWN[m]), h(ids(*RANGE[m])), "{:,}".format(clips), seconds / 3600, where))
    clips, seconds = words_counts()
    out.append("<tr><td><em>Single words you click</em></td><td>—</td><td>%s</td><td>%.1f</td>"
               "<td>%s</td></tr>" % ("{:,}".format(clips), seconds / 3600,
                                     "<strong>THIS PACK</strong>" if target == "Words"
                                     else h(pack_label("Words"))))
    out.append("</tbody></table>")
    out.append("<h3>The %s packs, and what each one speaks</h3>" % number(len(layout)))
    out.append("<ul>")
    for other in layout:
        what = ("every word in the German dictionary, spoken when you click one — needs QuestWordHunter"
                if other == "Words" else h(spoken(layout[other])))
        mark = " — <strong>this page</strong>" if other == target else ""
        out.append("<li><strong>%s</strong> — %s%s</li>" % (h(pack_title(other)), what, mark))
    out.append("</ul>")
    out.append("<p>Install as many as you play; they do not overlap, and no clip is in two of them. "
               "Each carries the same reader, and one reader runs however many packs are installed. "
               "CurseForge allows 2 GB per file and all of the audio is three times that, which is "
               "why it cannot be one download.</p>")
    return out


def description(target, members, layout):
    """The project description for CurseForge, as HTML for its source editor,
    in the shape the base addon's page already has."""
    out = []
    base = ('<a href="https://www.curseforge.com/wow/addons/questwordhunter" target="_blank" '
            'rel="nofollow">QuestWordHunter</a>')
    if target == "Words":
        clips, seconds = words_counts()
        out.append("<p>Every word in the German dictionary, spoken. Click a word in a quest and hear "
                   "it — for people learning German by playing World of Warcraft in German.</p>")
        out.append("<p><strong>{:,} clips, {:.1f} hours.</strong> One for every entry in the German "
                   "dictionary; each has been checked against its word by a speech recogniser and "
                   "re-read where it did not match.</p>".format(clips, seconds / 3600))
        out.append("<h3>Needs QuestWordHunter</h3>")
        out.append("<p>%s is required, and this pack is mainly for it: a word is spoken when you "
                   "click it, and clicking a word is what its quest panel offers. Without that addon "
                   "these clips are files nothing can reach. The reader itself is inside this pack, "
                   "so nothing else is needed — if you still have the separate <em>German "
                   "Voiceover</em> engine addon from before, remove it.</p>" % base)
        out.append('<p>Its natural companion is the <a href="https://www.curseforge.com/wow/addons/'
                   'questwordhunter-german-dictionary" target="_blank" rel="nofollow">German '
                   "Dictionary</a>, which gives a clicked word its meaning while this pack gives it "
                   "a voice. They are separate downloads on purpose: the dictionary is 3 MB of text, "
                   "this is 821 MB of audio, and nobody who only wants the meanings should have to "
                   "take the recordings.</p>")
    else:
        per = [(m,) + counts(m) for m in members]
        clips = sum(c for _, c, _ in per)
        seconds = sum(s for _, _, s in per)
        out.append("<p>The German a quest giver says, spoken aloud as the quest window opens — and "
                   "<strong>only for %s</strong>. For people learning German by playing World of "
                   "Warcraft in German.</p>" % h(spoken(members)))
        out.append("<p><strong>{:,} clips, {:.1f} hours</strong> — one clip per sentence across the "
                   "offer, the progress line and the hand-in, quest ids {}. Other expansions need "
                   "their own pack; the table below says which.</p>".format(
                       clips, seconds / 3600, h(ids_of_runs(runs_of(members, forever=False)))))
        out.append("<h3>Nothing else to install</h3>")
        out.append("<p>The reader is inside this pack. Install it, open a quest, and it reads. If you "
                   "still have the separate <em>German Voiceover</em> engine addon from before, "
                   "remove it.</p>")
        out.append("<h3>With QuestWordHunter</h3>")
        out.append("<p>%s is optional. With it, every paragraph gets a play button, the sentence being "
                   "read lights up as it is spoken, and a clicked word is said out loud — that last one "
                   "needs the Words pack.</p>" % base)
    out.extend(coverage_html(target, layout))
    out.append("<h3>Settings</h3>")
    out.append("<p><code>/whwv</code>, or Options → AddOns → QuestWordHunter Voice: quests on or off, "
               "single words, the window that shows who is speaking, a delay before the reading "
               "starts, the pause between sentences. The page lists the packs you have installed and "
               "says which pack's copy of the reader is running.</p>")
    out.append("<h3>How it was made</h3>")
    era = (" The clips are read from Retail's German: on Classic Era roughly one quest in five is "
           "worded differently on screen, and you will hear the Retail telling."
           if target in VANILLA_PACKS and target != "Words" else "")
    out.append("<p>Read from Blizzard's German quest text by a neural text-to-speech model, one clip "
               "per sentence, and checked with a speech recogniser.%s</p>" % era)
    where = ("Retail 12.1, Classic Era and World of Warcraft: Forever." if target in VANILLA_PACKS
             else "Retail 12.1.")
    out.append('<p>%s Source and issues: <a href="https://github.com/Ironship/%s" target="_blank" '
               'rel="nofollow">github.com/Ironship/%s</a>. Code under GPL v3, audio under CC BY-NC 4.0 '
               "— given away, not for sale.</p>" % (where, ENGINE, ENGINE))
    return "\n".join(out) + "\n"


# --- the manifest ----------------------------------------------------------------

def manifest(target, members, interface, version, loads):
    folder = folder_of(target)
    if target == "Words":
        notes = "German audio for single dictionary words, with the reader built in. Needs QuestWordHunter."
        deps = "## Dependencies: WordHunterWoW\n"
    else:
        notes = ("German quest audio for %s, with the reader built in. Any pack works on its own."
                 % spoken(members))
        deps = "## OptionalDeps: WordHunterWoW\n"
    return (
        "## Interface: %s\n"
        "## Title: QuestWordHunter - German Voiceover: %s\n"
        "## Notes: %s\n"
        "## IconTexture: Interface\\AddOns\\%s\\icon\n"
        "## Author: Ironship\n"
        "## Version: %s\n"
        "## SavedVariables: WordHunterWoWVoiceDB\n"
        "%s"
        "\n"
        "%s\n" % (interface, SHOWN[target], notes, folder, version, deps, "\n".join(loads)))


def audio_of(name):
    """Every clip a member pack ships, as (archive-relative path, source path)."""
    base = audio_base(name)
    if not base.is_dir():
        sys.exit("%s: no %s -- is the audio there?" % (name, base))
    for src in sorted(base.rglob("*." + AUDIO_EXT)):
        yield "sounds/%s" % src.relative_to(base).as_posix(), src


def plan(target, members, version, layout):
    """Everything that goes into the archive, small files first."""
    folder = folder_of(target)
    named = named_repo(target)
    entries = []   # (arcname, bytes-or-path)
    for small in SMALL_FILES:
        if small == "README.md":
            entries.append(("%s/README.md" % folder, readme(target, members, layout).encode("utf-8")))
            continue
        src = named / small
        if src.exists():
            entries.append(("%s/%s" % (folder, small), src))
    loads = []
    for rel, src in engine_files():
        entries.append(("%s/%s" % (folder, rel), src))
        if rel.endswith(".lua"):
            loads.append(rel)
    loads.append("Part.lua")
    entries.append(("%s/Part.lua" % folder, merged_part(target, members).encode("utf-8")))
    retail = RETAIL_INTERFACE + (", " + FOREVER_INTERFACE if target in VANILLA_PACKS else "")
    entries.append(("%s/%s_Mainline.toc" % (folder, folder),
                    manifest(target, members, retail, version, loads).encode("utf-8")))
    if target in VANILLA_PACKS:
        entries.append(("%s/%s_Vanilla.toc" % (folder, folder),
                        manifest(target, members, ERA_INTERFACE, version, loads).encode("utf-8")))
    for m in members:
        for rel, src in audio_of(m):
            entries.append(("%s/%s" % (folder, rel), src))
    return entries


def size_of(entries):
    total = 0
    for _, payload in entries:
        total += len(payload) if isinstance(payload, bytes) else payload.stat().st_size
    return total


def loads_of(entries, folder):
    """Every file the archive's manifests load, so the archive can be checked
    for them: a manifest naming a file the folder lacks stops the client
    loading the addon at all, and a listing would not show it."""
    wanted = set()
    for arcname, payload in entries:
        if arcname.endswith(".toc") and isinstance(payload, bytes):
            for line in payload.decode("utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    wanted.add("%s/%s" % (folder, line.strip()))
    return wanted


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
                        compress_type=zipfile.ZIP_STORED
                        if arcname.endswith((".ogg", ".mp3")) else method)
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
    unloadable = loads_of(entries, folder) - set(written)
    if unloadable:
        problems.append("the manifest loads %d file(s) the archive lacks, e.g. %s"
                        % (len(unloadable), sorted(unloadable)[0]))
    tops = {n.split("/", 1)[0] for n in written}
    if tops != {folder}:
        problems.append("top-level folders %s, expected only %s" % (sorted(tops), folder))
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
    ap.add_argument("--layout", default=DEFAULT_LAYOUT, choices=sorted(LAYOUTS),
                    help="which named grouping (default %s); --cap overrides it" % DEFAULT_LAYOUT)
    ap.add_argument("--cap", type=float, metavar="MB",
                    help="the biggest file the site will take; the grouping is then computed "
                         "as the fewest packs that fit under it, not read from the table")
    ap.add_argument("--only", help="one target of the layout")
    ap.add_argument("--version", default="2.0.0", help="version stamped on every pack built")
    ap.add_argument("--out", default=str(OUTDIR))
    ap.add_argument("--audio", metavar="DIR",
                    help="build from a transcoded tree of <Expansion>/sounds/... instead of "
                         "the ogg in each member repository")
    ap.add_argument("--ext", default="ogg", choices=("ogg", "mp3"),
                    help="the clip format in that tree; mp3 is declared in Part.lua (default ogg)")
    ap.add_argument("--store", action="store_true", help="store everything, deflate nothing")
    ap.add_argument("--dry-run", action="store_true", help="sizes from the sources; write nothing")
    ap.add_argument("--readme", metavar="TARGET", help="print the README an archive would carry")
    ap.add_argument("--descriptions", nargs="?", const=str(ROOT / "curseforge"), metavar="DIR",
                    help="write the CurseForge page of every pack as HTML (default: curseforge/)")
    args = ap.parse_args()

    global AUDIO_DIR, AUDIO_EXT
    AUDIO_EXT = args.ext
    if args.audio:
        AUDIO_DIR = pathlib.Path(args.audio).resolve()
        if not AUDIO_DIR.is_dir():
            sys.exit("no such audio tree: %s" % AUDIO_DIR)
    elif args.ext != "ogg":
        sys.exit("--ext %s needs --audio: the repositories hold ogg" % args.ext)

    if args.cap:
        sizes = measured_sizes()
        layout = layout_for_cap(args.cap * 1e6, sizes)
        print("cap %.0f MB -> %d packs: %s" % (
            args.cap, len(layout), "  ".join(
                "%s(%s)=%.0fMB" % (t, len(m), OVERHEAD * sum(sizes[x] for x in m) / 1e6)
                for t, m in layout.items())))
    else:
        layout = LAYOUTS[args.layout]
    version = engine_version()  # refuses when Naming.lua and the manifest disagree

    if args.readme:
        if args.readme not in layout:
            sys.exit("no such target in layout %s: %s (one of %s)" % (
                args.layout, args.readme, ", ".join(layout)))
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(readme(args.readme, layout[args.readme], layout))
        return 0

    if args.descriptions:
        outdir = pathlib.Path(args.descriptions)
        outdir.mkdir(parents=True, exist_ok=True)
        for target, members in layout.items():
            path = outdir / ("DESCRIPTION-%s.html" % target)
            path.write_text(description(target, members, layout), encoding="utf-8")
            print("wrote %s" % path)
        return 0

    if args.only:
        if args.only not in layout:
            sys.exit("no such target in layout %s: %s (one of %s)" % (
                args.layout, args.only, ", ".join(layout)))
        targets = [args.only]
    else:
        targets = list(layout)

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    grand, failures = 0, []
    print("layout %s, engine %s, packs stamped %s" % (
        "cap %.0f MB" % args.cap if args.cap else args.layout, version, args.version))
    print("%-12s %-40s %9s %6s  %s" % ("pack", "members", "size", "of 2GB", "status"))
    for target in targets:
        members = layout[target]
        entries = plan(target, members, args.version, layout)
        size = size_of(entries)
        grand += size
        over = "OVER 80%" if size > TARGET else ""
        if args.dry_run:
            print("%-12s %-40s %6.0f MB %5.0f%%  %s" % (
                target, "+".join(members), size / 1e6, 100 * size / HARD_LIMIT,
                over or "would build v%s, %d files" % (args.version, len(entries))))
            continue
        archive, actual, problems = write_archive(target, entries, args.version, outdir, args.store)
        if problems:
            failures.append(target)
            print("%-12s %-40s %6.0f MB %5.0f%%  FAILED" % (
                target, "+".join(members), actual / 1e6, 100 * actual / HARD_LIMIT))
            for p in problems:
                print("      %s" % p)
        else:
            print("%-12s %-40s %6.0f MB %5.0f%%  ok  %s%s" % (
                target, "+".join(members), actual / 1e6, 100 * actual / HARD_LIMIT,
                archive.name, "  " + over if over else ""))
    print("\n%d pack(s), %.2f GB total" % (len(targets), grand / 1e9))
    if failures:
        print("%d FAILED -- nothing moved into place for those" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
