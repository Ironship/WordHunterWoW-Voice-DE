#!/usr/bin/env python3
"""Work out the race and sex of every quest giver, and pick a voice for it.

    python Tools/npc_voice.py --world <TDB world sql> --db2 <extracted DBFilesClient> --write

Three sources, none of which knows the answer on its own:

    AllTheThings   quest -> NPC          Tools/quest_givers.py, MIT
    TrinityCore    NPC -> display        the world database, GPL-2.0
    the WoW client display -> race, sex  CreatureDisplayInfoExtra, Tools/db2.py

Blizzard publishes none of it. The Game Data API has no quest giver on a quest
and answers 404 for creature ids. The client does hold race and sex, but only
against a display, and it does not hold the display of an ordinary NPC -- the
server sends that when you meet one, so Creature.db2 covers six per cent of
quest givers. TrinityCore's world database is the piece that bridges them,
because an emulator has to know what to spawn.

All three are read at build time only. What ships in the addon is the voice a
line was spoken in, which is this project's own work.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import db2

ROOT = pathlib.Path(__file__).resolve().parents[1]
GIVERS = ROOT / "Data/quest_givers.json"
OUT = ROOT / "Data/quest_voice.json"

# The client's own race ids. Only the ones a quest giver is plausibly built from
# are named; the rest keep their number and fall back to the default voice.
RACES = {
    1: "human", 2: "orc", 3: "dwarf", 4: "nightelf", 5: "undead", 6: "tauren",
    7: "gnome", 8: "troll", 9: "goblin", 10: "bloodelf", 11: "draenei",
    22: "worgen", 24: "pandaren", 25: "pandaren", 26: "pandaren",
    27: "nightborne", 28: "highmountain", 29: "voidelf", 30: "lightforged",
    31: "zandalari", 32: "kultiran", 34: "darkirondwarf", 35: "vulpera",
    36: "magharorc", 37: "mechagnome",
}
SEX = {0: "male", 1: "female"}

# INSERT INTO `creature_template_model` VALUES (CreatureID, Idx, DisplayID, ...)
# Read as text rather than loaded into a database: six hundred megabytes of SQL
# to answer one question about two columns.
MODEL_ROW = re.compile(r"\((\d+),\s*(\d+),\s*(\d+),")


def creature_models(sql_path):
    """CreatureID -> DisplayID, taking the first model listed for each."""
    models = {}
    wanted = "INSERT INTO `creature_template_model`"
    with open(sql_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith(wanted):
                continue
            for creature, index, display in MODEL_ROW.findall(line):
                creature, display = int(creature), int(display)
                # Several models mean a randomised appearance. The first is as
                # good a choice as any and is stable between runs.
                if display and creature not in models:
                    models[creature] = display
    return models


def display_race_sex(db2_dir):
    """DisplayID -> (race, sex), through the two client tables."""
    extra = {}
    for row_id, values in db2.read(str(pathlib.Path(db2_dir) / "CreatureDisplayInfoExtra.db2")).rows():
        # Columns identified by their own distributions: one holds the 55 race
        # ids, one holds exactly two values. Tools/db2.py records how.
        extra[row_id] = (values[1], values[2])
    out = {}
    for row_id, values in db2.read(str(pathlib.Path(db2_dir) / "CreatureDisplayInfo.db2")).rows():
        found = extra.get(values[7])
        if found:
            out[row_id] = found
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True, help="TrinityCore world database .sql")
    ap.add_argument("--db2", required=True, help="directory of extracted DBFilesClient tables")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if not GIVERS.exists():
        sys.exit("run Tools/quest_givers.py --write first")
    givers = json.loads(GIVERS.read_text(encoding="utf-8"))
    npcs = {npc for ids in givers.values() for npc in ids}
    print("quest givers named by AllTheThings: %d NPCs across %d quests"
          % (len(npcs), len(givers)))

    models = creature_models(args.world)
    print("creature models in the world database:  %d" % len(models))
    print("  of our quest givers:                  %d (%.0f%%)"
          % (len(npcs & set(models)), 100 * len(npcs & set(models)) / max(1, len(npcs))))

    lookup = display_race_sex(args.db2)
    print("displays with a race and sex:           %d" % len(lookup))

    voices, missing = {}, 0
    tally = collections.Counter()
    for quest, ids in givers.items():
        found = None
        for npc in ids:
            display = models.get(npc)
            if display and display in lookup:
                race, sex = lookup[display]
                found = {"npc": npc, "race": RACES.get(race, str(race)),
                         "sex": SEX.get(sex, "male")}
                break
        if found:
            voices[quest] = found
            tally[(found["race"], found["sex"])] += 1
        else:
            missing += 1

    print("\nquests with a race and sex:             %d (%.0f%%)"
          % (len(voices), 100 * len(voices) / max(1, len(givers))))
    print("quests still without:                   %d" % missing)
    print("\nmost common speakers:")
    for (race, sex), count in tally.most_common(12):
        print("   %-16s %-7s %6d" % (race, sex, count))
    print("\nby sex: %s" % dict(collections.Counter(v["sex"] for v in voices.values())))

    if args.write:
        OUT.write_text(json.dumps(voices, ensure_ascii=False), encoding="utf-8")
        print("\nwrote %s" % OUT)
    else:
        print("\n(report only -- pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
