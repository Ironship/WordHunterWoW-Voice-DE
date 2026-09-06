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
"""
import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = "WordHunterWoW-Voice-DE"
# What the reader produces, and so what a granule position counts in.
SAMPLE_RATE = 24000

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

TOC = """## Interface: {interface}
## Title: QuestWordHunter - German Voiceover: {label}
## Notes: {notes}
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


def durations(clips, sounds):
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


def declaration(folder, name, clips=None, sounds=None):
    """What the pack tells the engine about itself.

    A quest pack names the range it covers, so the engine finds the owner of a
    clip by comparing one number. The word pack says only that it holds words:
    a word's clip is named by a hash and there is no range to compare.

    A quest pack also carries how long each sentence runs, which is what lets
    the engine play a passage through instead of stopping after the first
    sentence.
    """
    lines = ["-- Generated by Tools/build_pack.py. Do not edit by hand.",
             "WordHunterWoW_Voice_Parts = WordHunterWoW_Voice_Parts or {}"]
    if name == "Words":
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { words = true }' % folder)
    else:
        low, high = next((lo, hi) for n, lo, hi in EXPANSIONS if n == name)
        lines.append('WordHunterWoW_Voice_Parts["%s"] = { quests = { %d, %d } }'
                     % (folder, low, high))
        if clips:
            lines.append('WordHunterWoW_Voice_Parts["%s"].lengths = [[' % folder)
            lines.append(durations(clips, sounds))
            lines.append("]]")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sounds", default=str(ROOT / "sounds"))
    ap.add_argument("--out", default=str(ROOT / "build"))
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--interface", default="120100")
    ap.add_argument("--only", help="build one pack by name, e.g. Classic")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sounds = pathlib.Path(args.sounds)
    if not sounds.is_dir():
        sys.exit("no audio at %s -- run Tools/generate.py first" % sounds)
    packs = gather(sounds)
    if not packs:
        sys.exit("no clips found under %s" % sounds)

    order = [n for n, _, _ in EXPANSIONS if n in packs] + (["Words"] if "Words" in packs else [])
    total = sum(sum(c.stat().st_size for c in packs[n]) for n in order)
    print("%d clips, %.1f GB, %d packs" % (sum(len(packs[n]) for n in order),
                                           total / 1024 ** 3, len(order)))

    out = pathlib.Path(args.out)
    built = 0
    for name in order:
        if args.only and name != args.only:
            continue
        clips = packs[name]
        folder = "%s-%s" % (ENGINE, name)
        held = sum(c.stat().st_size for c in clips)
        print("  %-42s %6.0f MB  %6d clips" % (folder, held / 1024 ** 2, len(clips)))
        if args.dry_run:
            continue
        target = out / folder
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
        (target / "Part.lua").write_text(
            declaration(folder, name, clips, sounds), encoding="utf-8")
        notes = ("German quest audio for %s. Needs %s." % (name, ENGINE)
                 if name != "Words" else
                 "German audio for single dictionary words. Needs %s." % ENGINE)
        for suffix, interface in (("Mainline", args.interface), ("Vanilla", "11509")):
            (target / ("%s_%s.toc" % (folder, suffix))).write_text(
                TOC.format(interface=interface, label=name, notes=notes,
                           version=args.version, engine=ENGINE), encoding="utf-8")
        built += 1

    if args.dry_run:
        print("dry run, nothing written")
    else:
        print("wrote %d packs to %s" % (built, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
