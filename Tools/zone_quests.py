#!/usr/bin/env python3
"""Which quests belong to a zone, so a zone can be generated before the rest.

    python Tools/zone_quests.py --grail "<AddOns>/Grail" --zone 48 --name lochmodan --write

A pack is an expansion, but a player is in a zone, and on a live realm those are
not the same thing at all: Blizzard rewrote the old world in Cataclysm and its
quests took new ids, so Loch Modan is 42% Classic, 37% Cataclysm and 14% Wrath.
Generating pack by pack means a player standing in one zone hears fewer than
half the quests they open until several packs are finished.

So the order is settled by zone instead, and this works out which quests those
are: Grail records the NPC who gives each quest, and where that NPC stands.

    G[24469]='FA L1 A:37081 T:37081 e0'
    G[37081]={'FA 427:67.14,41.30 27:36.87,70.05>427'}

The numbers before each colon are map ids. A quest belongs to a zone when the
NPC handing it out stands there.

Nothing from Grail is redistributed. This reads it at build time and writes out
a list of quest ids -- which are Blizzard's numbers, not Grail's work -- purely
to decide what order to speak things in.
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# G[24469]='FA L1 A:37081 T:37081 e0'
QUEST_ROW = re.compile(r"^G\[(\d+)\]\s*=\s*'([^']*)'", re.MULTILINE)
# A:37081 names the giver, T:37081 the one who takes it back. Both count.
#
# The giver alone found only three quarters of a known zone list: a breadcrumb
# handed out in Ironforge that sends you to Loch Modan is given somewhere else
# and finished here, and a player standing in the zone meets it either way.
GIVER = re.compile(r"\b[AT]:([\d,]+)")
# G[37081]={'FA 427:67.14,41.30 27:36.87,70.05>427'}
NPC_ROW = re.compile(r"^G\[(\d+)\]\s*=\s*\{'([^']*)'", re.MULTILINE)
# 427:67.14,41.30 -- a map id and where on it
PLACE = re.compile(r"(\d+):\d+\.?\d*,\d+\.?\d*")


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def npc_places(folder):
    """Every NPC, and the maps it stands on."""
    places = {}
    for path in sorted((folder / "NPCs").glob("*.lua")):
        for npc, body in NPC_ROW.findall(read(path)):
            maps = {int(m) for m in PLACE.findall(body)}
            if maps:
                places.setdefault(int(npc), set()).update(maps)
    return places


def quest_givers(folder):
    """Every quest, and the NPCs that hand it out."""
    givers = {}
    for path in sorted((folder / "Quests").glob("*.lua")):
        for quest, body in QUEST_ROW.findall(read(path)):
            found = set()
            for run in GIVER.findall(body):
                for npc in run.split(","):
                    if npc.isdigit():
                        found.add(int(npc))
            if found:
                givers.setdefault(int(quest), set()).update(found)
    return givers


def quests_on(zone, givers, places):
    found = set()
    for quest, npcs in givers.items():
        for npc in npcs:
            if zone in places.get(npc, ()):
                found.add(quest)
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grail", required=True, help="the Grail addon folder")
    ap.add_argument("--zone", type=int, action="append", required=True,
                    help="a map id; repeat for several")
    ap.add_argument("--name", help="write Data/<name>.json")
    ap.add_argument("--against", help="a Data/*.json to check the answer against")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    folder = pathlib.Path(args.grail)
    if not (folder / "Quests").is_dir():
        sys.exit("no Grail quest data at %s" % folder)

    places = npc_places(folder)
    givers = quest_givers(folder)
    print("Grail: %d quests with a named giver, %d NPCs with a place"
          % (len(givers), len(places)))

    found = set()
    for zone in args.zone:
        here = quests_on(zone, givers, places)
        print("  map %-6d %5d quests" % (zone, len(here)))
        found |= here

    # Only quests this project has German text for are worth ordering.
    planned = set()
    lines = ROOT / "Data/lines.jsonl"
    if lines.exists():
        with open(lines, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if row.get("kind") == "quest" and row.get("id"):
                        planned.add(int(row["id"]))
        spoken = found & planned
        print("%d quests in the zone, %d of them with German text to speak"
              % (len(found), len(spoken)))
        found = spoken

    if args.against:
        known = set(json.loads(pathlib.Path(args.against).read_text(encoding="utf-8")))
        known &= planned or known
        hit = len(known & found)
        print("against %s: %d of %d known quests found (%.0f%%), %d extra"
              % (args.against, hit, len(known),
                 100 * hit / max(1, len(known)), len(found - known)))

    if args.name and args.write:
        target = ROOT / "Data" / (args.name + ".json")
        target.write_text(json.dumps(sorted(found)), encoding="utf-8")
        print("wrote %d quest ids to %s" % (len(found), target))
    elif args.name:
        print("(pass --write to save)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
