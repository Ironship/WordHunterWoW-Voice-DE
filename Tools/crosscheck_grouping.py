#!/usr/bin/env python3
"""Write down which sentences each clip covers, for Lua to be held to.

    python Tools/crosscheck_grouping.py --count 4000
    lua tests/grouping.test.lua

The pack ships the grouping -- the first sentence of every clip -- and the addon
reads it rather than working it out again. What has to be checked is therefore
not "do the two sides group alike" but "does the addon land on the sentences the
generator recorded, given the text the client will hand it".

That distinction is the whole point of this file, and getting it wrong is what
hid a bug for as long as it hid. The first version of this checker ran
speech.clean() over the text and wrote *that* out for both sides to work from.
clean() is the transformation under suspicion: it strips "{name}" and the comma
that introduced it, so "Das sind schwierige Zeiten, {name}." reaches the reader
as a 27-character sentence and is joined to the next, while the client renders
it 36 characters long and the addon left it standing alone. By feeding both
sides text that had already been through clean(), the checker compared the two
implementations on input no client ever renders, agreed with itself across
13,177 clips, and reported nothing.

So the text written here has the player tokens filled in -- speech.render(),
which puts a name where clean() takes one away. Everything else is still
cleaned, and that is a deliberate limit rather than an oversight: the corpus
carries markup the live client never sends (the harvested "Ihr bekommt:" reward
header above all), and feeding that through would measure a second, unrelated
divergence and drown this one. What is measured here is exactly the class this
file was blind to.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT.parent
QUESTS = SUITE / "WordHunterWoW-Dictionary-DE/Data/cache/quests_deDE.jsonl"
TESTS = ROOT / "tests"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import naming
import speech

# Record separators, chosen because no quest text contains them.
PASSAGE_END = "\x1e"
FIELD_END = "\x1f"

FIELDS = ("description", "progress", "completion")


def passages(limit):
    """Real passages, spread across the file rather than taken from the front.

    Each one is kept twice over: what the narrator was given, and what the
    client will put on screen. They differ only by the player tokens, which is
    the difference this checker exists to measure.
    """
    if not QUESTS.exists():
        sys.exit("no quest text at %s" % QUESTS)
    rows = []
    with open(QUESTS, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            for field in FIELDS:
                raw = record.get(field)
                said = speech.clean(raw)
                # A passage the generator made no clip of -- every group in it
                # was punctuation and nothing else -- has no grouping to check
                # and no audio to point at, so it is not sampled.
                if said.strip() and speech.spans(said):
                    rows.append((field, said, speech.clean(speech.render(raw))))
    step = max(1, len(rows) // limit)
    return rows[::step][:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=4000)
    args = ap.parse_args()

    chosen = passages(args.count)
    TESTS.mkdir(exist_ok=True)

    # The quest id a passage is filed under here is its position in this list,
    # not its real id. The test needs a pack to read the grouping out of, and a
    # pack is keyed by quest and field; inventing the key locally means the
    # checker does not have to keep a second copy of which quests were sampled.
    texts, wanted, fields, lines, held = [], [], [], [], []
    for index, (field, said, shown) in enumerate(chosen, start=1):
        firsts = [first for first, _ in speech.spans(said)]
        texts.append(shown)
        wanted.append(",".join(str(n) for n in firsts))
        # The field travels with the passage. A row is filed under a letter --
        # "o", "p", "c" -- and looking one up under the wrong letter finds
        # nothing, which is a way for this test to pass by reading none of the
        # table it is meant to be reading. So the test asks for the field the
        # passage actually came from.
        fields.append(field)
        # A duration per clip, as a real pack ships. The engine reads the clip
        # count off this row for a passage the grouping table leaves out, so a
        # test pack without it would be testing a pack that cannot exist.
        held.append("%d %s %s" % (index, naming.SPOKEN_FIELDS[field],
                                  ",".join("100" for _ in firsts)))
        # Written by the same rule build_pack.py writes a real pack with, so
        # that what the test parses is the shipped format and not a rehearsal
        # of it: a passage read one clip per sentence is left out of the table
        # there and left out of it here.
        if not speech.is_plain(said, firsts):
            lines.append("%d %s %s" % (index, naming.SPOKEN_FIELDS[field],
                                       ",".join(str(n) for n in firsts)))

    (TESTS / "_grouping_texts.txt").write_text(
        PASSAGE_END.join(texts), encoding="utf-8")
    (TESTS / "_grouping_spans.txt").write_text(
        PASSAGE_END.join(wanted), encoding="utf-8")
    (TESTS / "_grouping_lengths.txt").write_text(
        "\n".join(held), encoding="utf-8")
    (TESTS / "_grouping_fields.txt").write_text(
        PASSAGE_END.join(fields), encoding="utf-8")
    (TESTS / "_grouping_starts.txt").write_text(
        "\n".join(lines), encoding="utf-8")

    total = sum(len(w.split(",")) for w in wanted)
    print("wrote %d passages, %d clips, %d of them not one-per-sentence"
          % (len(chosen), total, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
