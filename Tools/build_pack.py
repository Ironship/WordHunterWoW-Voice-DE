#!/usr/bin/env python3
"""Stage complete per-expansion quest sources from approved generated OGG clips.

    python Tools/build_pack.py --dry-run
    python Tools/build_pack.py --only Classic

This is a metadata/staging step, not the two-pack release command. The default
input is <delivery>/work/audio/sounds/q/. Part.lua and audio are written together under
<delivery>/work/voice-packs/<Expansion>/. Original audio/quests sources and
archived Git repositories are not modified. Files use local hardlinks where
possible and atomic replacement, so replacing a staged clip does not rewrite
its shared original. Never modify staged audio in place.
Single-word audio belongs solely to Dictionary-DE and is not copied by this tool.

--sources selects original expansion assets; --out selects complete staging; --repos remains a legacy
alias with the same <Expansion> layout. --quests and --forever-quests override
the German corpora used to recover sentence groupings. Existing manifests are
kept. Pass the same staged --sources tree to Tools/transcode_packs.py and
Tools/build_merged.py to create releases. Generate/review first; this stages
only local files and does not publish them.
"""
import argparse
import json
import os
import pathlib
import shutil
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import naming
import speech

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT.parent
DELIVERY = SUITE.parent
SOURCE_DIR = DELIVERY / "audio" / "quests"
GENERATED_SOUNDS = DELIVERY / "work" / "audio" / "sounds"
ENGINE = "WordHunterWoW-Voice-DE"

# The word pack needs the base addon as well, and the others do not.
#
# A quest pack is played when a quest window opens, which the engine hooks on
# its own. A word is played when somebody clicks one, and clicking a word is
# something only QuestWordHunter's panel offers -- Voice.lua's PlayWord has
# exactly one caller, the wrapper HookBaseAddon puts around that panel's editor,
# and HookBaseAddon returns at once when the base addon is not there. So without
# it the word pack is 104,274 clips that nothing can reach.
#
# The engine keeps OptionalDeps on the base addon, which is right for the engine:
# quest passages are read without it. That optionality does not carry down to
# this pack, and nothing said so until now.
BASE_ADDON = "WordHunterWoW"
WORD_PACK_DEPENDENCIES = "%s, %s" % (ENGINE, BASE_ADDON)
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

# Which packs may claim Classic Era, and why the rest may not.
#
# Every pack used to ship a Vanilla manifest, so a Classic Era player could
# install the Cataclysm pack and have the client load it. It would then never
# play one clip, and an addon that loads and can never do anything is the same
# fault as a button that plays nothing: it turns "this content is not in your
# game" into "this addon is broken".
#
# The reason is the harvest, not the game, and the first version of this comment
# had it wrong. It said Classic Era is vanilla and its quests stop where the
# Classic pack's range does. They do not: that client's own saved variables on
# this machine record quest 77667, eight times above the boundary and absent
# from the 49,041-record Retail harvest entirely. Season of Discovery and the
# anniversary realms run on the Era client and bring ids of their own.
#
# What is true is that every clip in every pack was spoken from a Retail record,
# because plan_lines.py takes the Retail half of the corpus and skips the
# Classic-keyed rows. So a quest that exists only on Era has no audio in any
# pack -- 77667 is not in WarWithin either, whose range would otherwise own it.
# Shipping a Vanilla manifest cannot fix that; only harvesting from a Classic
# client can.
#
# Words is the exception among the non-quest packs. A German word is the same
# word in either game, and the panel that plays it is there in both.
VANILLA_PACKS = {"Classic", "Words"}

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

# Quests that exist only on World of Warcraft: Forever, and the pack they go in.
#
# Forever installs the Classic pack and no other: only Classic and the
# dictionary list its interface number. Its own quests are numbered among
# Retail's -- 97277 sits inside The War Within's run -- so filed by number their
# clips would land in a pack Forever never loads, and the quest would be silent
# there with nothing to say why.
#
# Named one by one rather than as a run, because a run wide enough to hold them
# would also claim the Retail quests numbered around them. The Classic pack
# keeps its own span as `quests` and lists these beside it in `ranges`: an
# engine that reads `ranges` finds them, and one older than the field sees the
# span it always saw. None of these ids is in the Retail quest corpus (checked
# for 97277 on 2026-09-25), so on Retail no quest is sent here by mistake.
#
# Their German text is not in the Retail corpus either. The sentence grouping
# for them comes from the Forever harvest the dictionary keeps beside it.
FOREVER_PACK = "Classic"
FOREVER_QUESTS = (97277,)
FOREVER_CORPUS = SUITE / "WordHunterWoW-Dictionary-DE/Data/cache/forever/quests_deDE.jsonl"
# The harvest's own names for the three passages: it records the hand-in text as
# "reward" (Tools/harvest_delta.py, VOICED), and the clips call it completion.
FOREVER_FIELDS = {"description": "o", "progress": "p", "reward": "c"}


def runs(ids):
    """Quest ids joined where they touch, as (low, high) pairs in order."""
    out = []
    for qid in sorted(set(ids)):
        if out and qid == out[-1][1] + 1:
            out[-1] = (out[-1][0], qid)
        else:
            out.append((qid, qid))
    return out


FOREVER_RUNS = runs(FOREVER_QUESTS)


def pack_of(qid):
    """The pack a quest's clips go in: Forever's own first, then by number."""
    if qid in FOREVER_QUESTS:
        return FOREVER_PACK
    for name, low, high in EXPANSIONS:
        if low <= qid <= high:
            return name
    return None


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
            name = pack_of(qid)
            if name:
                packs.setdefault(name, []).append(clip)
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


def groupings(quests, wanted, fields=None):
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
            for field, letter in (fields or naming.SPOKEN_FIELDS).items():
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
        declared = [(low, high)]
        for qid in FOREVER_QUESTS:
            remaining = []
            for lo, hi in declared:
                if not lo <= qid <= hi:
                    remaining.append((lo, hi))
                else:
                    if lo < qid:
                        remaining.append((lo, qid - 1))
                    if qid < hi:
                        remaining.append((qid + 1, hi))
            declared = remaining
        if name == FOREVER_PACK:
            declared += FOREVER_RUNS
        if len(declared) > 1:
            lines.append("-- Explicit runs keep Forever's own ids exclusively in Classic.")
            lines.append('WordHunterWoW_Voice_Parts["%s"].ranges = { %s }' % (
                folder, ", ".join("{ %d, %d }" % run for run in declared)))
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
            partial = landing.with_name("." + landing.name + "." + uuid.uuid4().hex + ".partial")
            shutil.copy2(path, partial)
            os.replace(partial, landing)
            moved += 1
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(GENERATED_SOUNDS))
    ap.add_argument("--out", default=str(DELIVERY / "work" / "voice-packs"),
                    help="where a playable pack is assembled, audio included")
    ap.add_argument("--sources", "--repos", dest="sources", default=str(SOURCE_DIR),
                    help="external quest sources, one <Expansion> folder each; --repos is a legacy alias")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--interface", default="120100, 120105")
    ap.add_argument("--only", help="build one pack by name, e.g. Classic")
    ap.add_argument("--quests", default=str(DEFAULT_QUESTS),
                    help="the quest text the clips were made from, which is "
                         "where the sentence grouping comes from")
    ap.add_argument("--forever-quests", default=str(FOREVER_CORPUS),
                    help="Forever corpus used for its own quest grouping")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    if not sounds.is_dir():
        sys.exit("no audio at %s -- run Tools/generate.py first" % sounds)
    packs = gather(sounds)
    # Single-word clips are maintained and released only by Dictionary-DE.
    packs.pop("Words", None)
    if not packs:
        sys.exit("no clips found under %s" % sounds)

    out = pathlib.Path(args.out)
    sources = pathlib.Path(args.sources)
    if out.resolve().is_relative_to(sources.resolve()) or out.resolve().is_relative_to(sounds.resolve()):
        ap.error("--out must be separate from original sources and generated sounds")

    # Also retain metadata for existing external expansion folders.
    known = [n for n, _, _ in EXPANSIONS]
    order = [n for n in known
             if n in packs or (sources / n).is_dir()]

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
        lengths = durations(clips)
        counted, hours = spoken(lengths)
        # How many clips each passage has, read back out of the duration table
        # rather than counted off the disk a second time. The grouping is
        # written only where the two agree about that count.
        held_counts = {}
        for line in lengths.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                held_counts[(int(parts[0]), parts[1])] = len(parts[2].split(","))
        # Forever's quests are grouped from Forever's harvest and everything
        # else from the Retail corpus, each from its own text and never both.
        forever = {key: n for key, n in held_counts.items() if key[0] in FOREVER_QUESTS}
        retail = {key: n for key, n in held_counts.items() if key not in forever}
        starts, grouped, stale = groupings(pathlib.Path(args.quests), retail)
        if forever:
            more, also_grouped, also_stale = groupings(pathlib.Path(args.forever_quests), forever, FOREVER_FIELDS)
            starts = "\n".join(part for part in (starts, more) if part)
            grouped, stale = grouped + also_grouped, stale + also_stale
        print("  %-42s %6.0f MB  %6d clips  %6.1f h" %
              (folder, held / 1024 ** 2, len(clips), hours))
        if stale:
            print("    UWAGA: %d fragmentow ma inna liczbe zdan niz klipow -- "
                  "podzial nie zapisany" % stale)
        # The two counts answer different questions and are printed together
        # only when they disagree, which they should not: a clip on disk whose
        # name no passage claims is one the engine can never ask for.
        if counted != len(clips):
            print("    UWAGA: %d klipow na dysku, %d w tabeli dlugosci"
                  % (len(clips), counted))
        if args.dry_run:
            continue

        # Complete staging source: metadata and audio must describe one tree.
        # Original external sources and archived hardlinks are not modified.
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        original = sources / name
        if original.is_dir():
            mirror(original, target)
        home = target
        home.mkdir(parents=True, exist_ok=True)
        part = home / "Part.lua"
        partial = part.with_name("." + part.name + "." + uuid.uuid4().hex + ".partial")
        partial.write_text(
            declaration(folder, name, lengths, starts), encoding="utf-8")
        os.replace(partial, part)
        notes = "German quest audio for %s. Needs %s." % (name, ENGINE)
        flavours = [("Mainline", args.interface)]
        if name in VANILLA_PACKS:
            flavours.append(("Vanilla", VANILLA_INTERFACE))
        for suffix, interface in flavours:
            manifest = home / ("%s_%s.toc" % (folder, suffix))
            if manifest.exists():
                continue
            manifest.write_text(
                TOC.format(interface=interface, label=name, notes=notes,
                           version=args.version, folder=folder,
                           engine=ENGINE),
                encoding="utf-8")

        if not clips:
            # Nothing to play. The repository is brought up to date so it can be
            # tagged; no folder is made in the client, because an addon holding
            # no audio is a line in the addon list that does nothing, and the
            # engine already treats a pack that is not installed as silence.
            print("    bez klipow -- tylko metadane")
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
            partial = landing.with_name("." + landing.name + "." + uuid.uuid4().hex + ".partial")
            try:
                os.link(clip, partial)
            except OSError:
                shutil.copy2(clip, partial)
            os.replace(partial, landing)
            copied += 1
        if skipped:
            print("    %d nowych, %d juz na miejscu" % (copied, skipped))
        built += 1

    if args.dry_run:
        print("dry run, nothing written")
    else:
        print("wrote %d packs to %s" % (built, out))
        print("complete staged sources in %s; original sources unchanged" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
