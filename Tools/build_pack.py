#!/usr/bin/env python3
"""Assemble the generated audio into installable sound packs, one per expansion.

    python Tools/build_pack.py

The whole pack does not fit in one addon. The German VoiceOver for Classic is
split into four parts and that is Classic alone; this covers Retail, which is
more than twenty times the quests, plus a clip for every word in the dictionary.

Split by expansion rather than by arbitrary slices. A player levelling through
Classic downloads Classic and nothing else, and knows what they are getting; a
player who never goes to Draenor never carries Draenor. Eleven quest packs of
440 MB to 1.2 GB, and one for the dictionary words.

The boundary is a quest id range, because quest ids were handed out roughly in
the order the content was written. Approximate at the edges -- a few quests
added to an old zone years later keep a new id -- and harmlessly so: a clip in
the neighbouring pack still plays for anyone holding that pack, and anyone who
does not gets silence, which is what already happens for a clip nobody has
generated yet.

Two destinations, and they are not the same thing
-------------------------------------------------

Each pack is a git repository of its own, beside the engine's: --repos says
where those live. A pack repository holds everything the addon is made of
except the audio -- both manifests, the licence, the notice, the readme -- and
Part.lua, which is generated here because it is derived from the clips -- and,
for the sentence grouping, from the quest text they were made from -- and
nothing else can write it. The audio is gitignored while it is undecided how
seven gigabytes should ship, so a repository alone is not playable.

--out says where a playable pack is assembled: the repository's files copied
in, plus the clips. That is the copy the client loads, and it is what a release
would be if the audio were attached to one.

The alternative was to make the repository itself the assembled pack and have
the client copy be a mirror of it. That doubles seven gigabytes on a disk a
generation run is already writing to, and buys nothing: the only file that has
to be regenerated is Part.lua, and it is 200 KB.

Nothing here writes a manifest a repository already has. The version line in a
.toc is what a tag publishes, it is bumped by hand for a release, and a builder
that rewrote it every run would quietly put 0.1.0 back over it. A manifest is
written only where none exists, to bootstrap a pack that has no repository yet.
"""
import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import naming
import speech

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT.parent
ENGINE = "WordHunterWoW-Voice-DE"
# The text the clips were made from. Read here so that a pack can say which
# sentences each of its clips covers; the audio alone cannot answer that, since
# a clip's file name carries its number and not its contents.
DEFAULT_QUESTS = SUITE / "WordHunterWoW-Dictionary-DE/Data/cache/quests_deDE.jsonl"
# What the reader produces, and so what a granule position counts in.
SAMPLE_RATE = 24000
# Classic Era, which does not move with Retail and so is not a switch. Taken
# from the engine's own Vanilla manifest; there is no second place to look it up
# and no version of this that may be guessed.
VANILLA_INTERFACE = "11509"

EXPANSIONS = [
    ("Classic", 1, 9665),
    ("BurningCrusade", 9666, 11579),
    ("Wrath", 11580, 14620),
    ("Cataclysm", 14621, 29377),
    ("Pandaria", 29378, 34575),
    ("Draenor", 34576, 39694),
    ("Legion", 39695, 48158),
    ("Azeroth", 48159, 56054),
    ("Shadowlands", 56055, 64000),
    ("Dragonflight", 64001, 74000),
    ("WarWithin", 74001, 10 ** 9),
]

# The icon is the engine's, carried by every pack so that a dozen entries in the
# addon list read as one thing. A pack built without a repository has no icon
# file to point at; the client shows its default and loads the addon anyway,
# which is why this line is unconditional.
TOC = """## Interface: {interface}
## Title: QuestWordHunter - German Voiceover: {label}
## Notes: {notes}
## IconTexture: Interface\\AddOns\\{folder}\\icon
## Author: Ironship
## Version: {version}
## Dependencies: {engine}

Part.lua
"""


def quest_id(path):
    """The quest a clip belongs to, read from its own file name."""
    try:
        return int(path.stem.split("_")[0])
    except ValueError:
        return None


def gather(sounds):
    """Every clip, filed under the pack that will carry it."""
    packs = {}
    quests = sounds / "q"
    if quests.is_dir():
        for clip in quests.rglob("*.ogg"):
            qid = quest_id(clip)
            if qid is None:
                continue
            for name, low, high in EXPANSIONS:
                if low <= qid <= high:
                    packs.setdefault(name, []).append(clip)
                    break
    words = sounds / "w"
    if words.is_dir():
        found = list(words.rglob("*.ogg"))
        if found:
            packs["Words"] = found
    return packs


def ogg_seconds(path):
    """How long an Ogg Vorbis clip runs, read from its own last page.

    The client will not say when a clip has finished, so the engine can only
    chain one sentence to the next by knowing how long the first one takes. That
    means shipping a duration for every clip.

    Ogg carries it already: the final page's granule position is the sample
    count of the whole stream. Reading the tail of the file costs microseconds,
    where asking ffprobe would be a process per clip and a quarter of an hour
    across the pack.
    """
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        # The last page is within the final few kilobytes unless the file is
        # damaged; 64 KB is generous for clips this short.
        window = min(size, 65536)
        handle.seek(size - window)
        tail = handle.read(window)
    at = tail.rfind(b"OggS")
    if at < 0 or at + 14 > len(tail):
        return 0.0
    granule = int.from_bytes(tail[at + 6:at + 14], "little", signed=False)
    return granule / float(SAMPLE_RATE)


def durations(clips):
    """One line per passage: the quest, the field, and its sentences in order.

    Written as a single Lua string rather than a table literal. A table of
    thirty thousand entries is thirty thousand constants in the compiled chunk,
    and Lua allows a chunk 262,143 of them -- a limit this pack would reach.
    One string is one constant, whatever it holds, and the engine parses it the
    first time a quest asks.

    Centiseconds, because a hundredth of a second is finer than any gap a
    listener notices between two sentences, and it keeps the numbers short.
    """
    by_passage = {}
    for clip in clips:
        name = clip.stem                       # e.g. 25152_o1
        if "_" not in name:
            continue
        quest, tail = name.rsplit("_", 1)
        field, _, index = tail[:1], None, tail[1:]
        if not quest.isdigit() or not index.isdigit():
            continue
        by_passage.setdefault((int(quest), field), {})[int(index)] = \
            int(round(ogg_seconds(clip) * 100))
    lines = []
    for (quest, field), sentences in sorted(by_passage.items()):
        ordered = [str(sentences[i]) for i in sorted(sentences)]
        lines.append("%d %s %s" % (quest, field, ",".join(ordered)))
    return "\n".join(lines)


def groupings(quests, wanted):
    """Which sentence each clip of a passage begins at, one line per passage.

    The engine used to work this out for itself from the text the client draws.
    It cannot. Tools/speech.py joins a sentence shorter than thirty characters
    to its neighbour, and it measures the sentence it is going to speak -- with
    the vocative struck out, because there is no player name to record. The
    client draws the same sentence with a name in it. "Das sind schwierige
    Zeiten, {name}." is 27 characters to the generator and 36 to the client, so
    one side joined it and the other did not, and every play button after it in
    the passage sat one paragraph too high.

    Sentence numbers are what survives that. Filling a token in changes how long
    a sentence is, never how many come before it, so a boundary written as a
    sentence number means the same thing on both sides even though the strings
    differ.

    Same shape as the duration table above, and for the same reason: one Lua
    string rather than a table literal, because a chunk may hold 262,143
    constants and this pack would reach that.

    A passage whose clips are simply its sentences, one for one, is left out.
    That is 58% of the German corpus, it is the answer the engine assumes when
    it finds no line, and writing it down would have added a hundred kilobytes
    saying nothing.
    """
    if not quests.exists():
        return "", 0, 0
    lines, written, missing = [], 0, 0
    with open(quests, encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            record = json.loads(raw)
            quest_id = record.get("id")
            if not isinstance(quest_id, int) or quest_id < 0:
                continue
            for field, letter in naming.SPOKEN_FIELDS.items():
                if (quest_id, letter) not in wanted:
                    continue
                said = speech.clean(record.get(field))
                if not said.strip():
                    continue
                firsts = [first for first, _ in speech.spans(said)]
                # The pack plays clips off the disk and this table is derived
                # from the text; if the corpus has moved on since the audio was
                # made, the two disagree about how many clips there are and the
                # numbers here would point into the wrong passage. Saying
                # nothing leaves the engine to derive the grouping, which is
                # what it did before this table existed -- worse, and not wrong
                # in a new way.
                if len(firsts) != wanted[(quest_id, letter)]:
                    missing += 1
                    continue
                written += 1
                if speech.is_plain(said, firsts):
                    continue
                lines.append("%d %s %s" % (quest_id, letter,
                                           ",".join(str(n) for n in firsts)))
    return "\n".join(lines), written, missing


def spoken(lengths):
    """How many clips a pack accounts for, and how many hours they run.

    Read back out of the duration table rather than counted off the disk, and
    deliberately: the table is the only thing the engine plays from, so a clip
    the table does not name is one nothing will ever ask for. A count of files
    would be the larger number and the wrong one -- it would promise audio the
    addon cannot reach, which is the exact shape of the fault this project has
    already been bitten by once.
    """
    count = seconds = 0
    for line in lengths.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        for value in parts[2].split(","):
            count += 1
            seconds += int(value) / 100.0
    return count, seconds / 3600.0


def declaration(folder, name, lengths=None, starts=None):
    """What the pack tells the engine about itself.

    A quest pack names the range it covers, so the engine finds the owner of a
    clip by comparing one number. The word pack says only that it holds words:
    a word's clip is named by a hash and there is no range to compare.

    A quest pack also carries how long each sentence runs, which is what lets
    the engine play a passage through instead of stopping after the first
    sentence, and which sentences each clip covers, which is what lets it point
    at the right one. The second is written even when it is empty -- an empty
    string is still a declaration that this pack knows the format, and the
    engine reads a pack with no `starts` at all as an old one and falls back to
    guessing. A pack every one of whose passages happens to be one clip per
    sentence would otherwise be treated as old.
    """
    lines = ["-- Generated by Tools/build_pack.py. Do not edit by hand.",
             "WordHunterWoW_Voice_Parts = WordHunterWoW_Voice_Parts or {}"]
    if name == "Words":
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { words = true }' % folder)
    else:
        low, high = next((lo, hi) for n, lo, hi in EXPANSIONS if n == name)
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { quests = { %d, %d } }'
                     % (folder, low, high))
        if lengths:
            lines.append('WordHunterWoW_Voice_Parts["%s"].lengths = [[' % folder)
            lines.append(lengths)
            lines.append("]]")
            lines.append('WordHunterWoW_Voice_Parts["%s"].starts = [[' % folder)
            lines.append(starts or "")
            lines.append("]]")
    return "\n".join(lines) + "\n"


def mirror(home, target):
    """The pack repository copied into the assembled pack, minus the audio.

    Copied wholesale rather than from a list of file names. A list here would be
    a second answer to the question "what is this addon made of", and the first
    answer -- the repository -- is the one that gets edited; the two drift, and
    a file the .toc named but the client did not hold is a fault this project
    has already paid for once. Tools/install_dev.sh reads the .toc for the same
    reason.

    Dot-entries are left behind because .git, .gitignore and .pkgmeta say how
    the addon is built rather than being part of it. sounds/ is left behind
    because it is filled from the generated audio below; if the audio is ever
    committed, this must not be the thing that copies it, or the incremental
    copy underneath stops being what decides.
    """
    # Nothing to mirror when the repository is the pack. That is what --out and
    # --repos pointing at the same place means, and it is the arrangement once
    # the audio is committed: the checkout is the installable addon and there is
    # no second copy to keep in step. Without this every file would be copied
    # onto itself, which shutil refuses outright.
    if home.resolve() == target.resolve():
        return 0
    moved = 0
    for top in sorted(home.iterdir()):
        if top.name.startswith(".") or top.name == "sounds":
            continue
        files = [top] if top.is_file() else sorted(
            path for path in top.rglob("*") if path.is_file())
        for path in files:
            landing = target / path.relative_to(home)
            landing.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, landing)
            moved += 1
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--out", default=str(ROOT / "build"),
                    help="where a playable pack is assembled, audio included")
    ap.add_argument("--repos", default=str(ROOT.parent),
                    help="where the pack repositories live, one folder each")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--interface", default="120100")
    ap.add_argument("--only", help="build one pack by name, e.g. Classic")
    ap.add_argument("--quests", default=str(DEFAULT_QUESTS),
                    help="the quest text the clips were made from, which is "
                         "where the sentence grouping comes from")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    if not sounds.is_dir():
        sys.exit("no audio at %s -- run Tools/generate.py first" % sounds)
    packs = gather(sounds)
    if not packs:
        sys.exit("no clips found under %s" % sounds)

    out = pathlib.Path(args.out)
    repos = pathlib.Path(args.repos)

    # A pack is in the run if it has clips, or if it has a repository -- the
    # second so that a pack nobody has spoken a word of yet still gets a
    # Part.lua written and can be tagged. Words is that pack today: the
    # dictionary is generated last, and until it is, the repository would
    # otherwise hold a .toc naming a file that does not exist, which is the one
    # way to stop the client loading an addon at all.
    known = [n for n, _, _ in EXPANSIONS] + ["Words"]
    order = [n for n in known
             if n in packs or (repos / ("%s-%s" % (ENGINE, n))).is_dir()]

    # Sized once and remembered. Every stat here is a round trip to a disk a
    # generation run is writing to, and asking twice for the same answer -- once
    # for the total, once per pack -- doubled that for nothing.
    sizes = {n: sum(c.stat().st_size for c in packs[n]) for n in packs}
    print("%d clips, %.1f GB, %d packs" % (sum(len(packs[n]) for n in packs),
                                           sum(sizes.values()) / 1024 ** 3,
                                           len(order)))

    built = 0
    for name in order:
        if args.only and name != args.only:
            continue
        clips = packs.get(name, [])
        folder = "%s-%s" % (ENGINE, name)
        held = sizes.get(name, 0)
        lengths = "" if name == "Words" else durations(clips)
        counted, hours = spoken(lengths)
        # How many clips each passage has, read back out of the duration table
        # rather than counted off the disk a second time. The grouping is
        # written only where the two agree about that count.
        held_counts = {}
        for line in lengths.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                held_counts[(int(parts[0]), parts[1])] = len(parts[2].split(","))
        starts, grouped, stale = ("", 0, 0) if name == "Words" else             groupings(pathlib.Path(args.quests), held_counts)
        print("  %-42s %6.0f MB  %6d clips  %6.1f h" %
              (folder, held / 1024 ** 2, len(clips), hours))
        if stale:
            print("    UWAGA: %d fragmentow ma inna liczbe zdan niz klipow -- "
                  "podzial nie zapisany" % stale)
        # The two counts answer different questions and are printed together
        # only when they disagree, which they should not: a clip on disk whose
        # name no passage claims is one the engine can never ask for.
        if name != "Words" and counted != len(clips):
            print("    UWAGA: %d klipow na dysku, %d w tabeli dlugosci"
                  % (len(clips), counted))
        if args.dry_run:
            continue

        target = out / folder
        # Where the pack's own files live. The repository when there is one,
        # because that is what a release is cut from; otherwise the assembled
        # pack itself, which is what this tool did before the packs had
        # repositories, so a fresh checkout of the engine alone still builds
        # something playable.
        home = repos / folder
        if not home.is_dir():
            home = target
        home.mkdir(parents=True, exist_ok=True)
        (home / "Part.lua").write_text(
            declaration(folder, name, lengths, starts), encoding="utf-8")
        notes = ("German quest audio for %s. Needs %s." % (name, ENGINE)
                 if name != "Words" else
                 "German audio for single dictionary words. Needs %s." % ENGINE)
        for suffix, interface in (("Mainline", args.interface),
                                  ("Vanilla", VANILLA_INTERFACE)):
            manifest = home / ("%s_%s.toc" % (folder, suffix))
            if manifest.exists():
                continue
            manifest.write_text(
                TOC.format(interface=interface, label=name, notes=notes,
                           version=args.version, engine=ENGINE, folder=folder),
                encoding="utf-8")

        if not clips:
            # Nothing to play. The repository is brought up to date so it can be
            # tagged; no folder is made in the client, because an addon holding
            # no audio is a line in the addon list that does nothing, and the
            # engine already treats a pack that is not installed as silence.
            print("    bez klipow -- tylko repozytorium")
            built += 1
            continue

        copied = skipped = 0
        for clip in clips:
            # The on-disk shard is kept in the path. Nothing reads it -- the pack
            # is found by the quest id -- but a folder of forty thousand files is
            # one nobody can open.
            # Under sounds/, because that is where the engine looks:
            # Naming.lua builds "sounds\q\52\25152_o1.ogg" and the addon
            # prefixes the pack folder. Dropping the prefix here put every
            # clip one directory above the only place anything asked for it,
            # so no pack ever played a sound -- and every check of "is the
            # file there" agreed it was, because it was asking the wrong
            # question with the same wrong rule.
            destination = target / "sounds" / clip.relative_to(sounds).parent
            landing = destination / clip.name
            # Only what is new or changed. Rebuilding a pack in place used to
            # copy every clip again -- twenty-six thousand files across the WSL
            # boundary to add a few hundred, ten minutes during which nothing
            # else on that disk could make progress. Size and time are enough to
            # tell a clip apart from itself: they are written once and never
            # edited.
            try:
                there = landing.stat()
                here = clip.stat()
                if there.st_size == here.st_size and there.st_mtime >= here.st_mtime:
                    skipped += 1
                    continue
            except OSError:
                pass
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(clip, landing)
            copied += 1
        if skipped:
            print("    %d nowych, %d juz na miejscu" % (copied, skipped))
        if home != target:
            print("    %d plikow z repozytorium" % mirror(home, target))
        built += 1

    if args.dry_run:
        print("dry run, nothing written")
    else:
        print("wrote %d packs to %s" % (built, out))
        print("manifests and Part.lua in %s" % repos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
