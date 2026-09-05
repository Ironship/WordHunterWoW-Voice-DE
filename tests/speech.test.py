#!/usr/bin/env python3
"""Run from the repo root:  python tests/speech.test.py

Every case here is a token that really occurs in the German quest corpus. A
reader that says markup out loud is the single most noticeable way this pack can
be wrong, and it is not something the game will report.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "Tools"))
from speech import clean, chunks, MAX_CHARS


def check(got, want, why):
    if got != want:
        raise AssertionError("%s\n  got:  %r\n  want: %r" % (why, got, want))


# The player's name is vocative in almost every case, and it takes its comma.
check(clean("Lasst sie nicht warten, <name>."), "Lasst sie nicht warten.",
      "a trailing vocative should leave a clean sentence")
check(clean("Ihr habt Euch bewiesen, <name>. Nehmt dies."),
      "Ihr habt Euch bewiesen. Nehmt dies.", "mid-passage vocative")
check(clean("Nun, <name>, mir kann es egal sein."), "Nun, mir kann es egal sein.",
      "a name between commas leaves one comma, not two")
check(clean("<name> hat es geschafft."), "hat es geschafft.",
      "a leading name is dropped without eating the sentence")
check(clean("Willkommen, <class>!"), "Willkommen!", "class token behaves like name")

# Markup the client resolves at display time.
check(clean("|cFF0000FFBlau|r und rot."), "Blau und rot.", "colour codes are not spoken")
check(clean("in |4Minute:Minuten;"), "in Minuten", "plural picker takes the plural")
check(clean("$GHerr:Frau; Vogel"), "Herr Vogel", "gender picker takes the masculine")
check(clean("Ein |3-6(Anhänger) der Klinge."), "Ein Anhänger der Klinge.",
      "declension markup keeps the word")
check(clean("Erste Zeile$BZweite Zeile"), "Erste Zeile\nZweite Zeile",
      "$B is a line break")

# Passages that are not text at all.
check(clean("[PH] placeholder"), "", "Blizzard's own placeholder is not read")
check(clean("   "), "", "blank is blank")
check(clean(None), "", "None is blank")

# Whitespace the substitutions leave behind.
check(clean("Zwei  Leerzeichen ."), "Zwei Leerzeichen.", "space before punctuation")
check(clean("Drei\n\n\n\nAbsätze"), "Drei\n\nAbsätze", "runs of blank lines collapse")
check(clean("Zeile \r\n Zwei"), "Zeile\nZwei", "carriage returns and edge spaces")

# Real text must survive untouched. The rules exist to remove markup, and a rule
# that also eats prose is worse than no rule.
intact = ("Als erstes müssen wir Euch ein wenig Selbstvertrauen lehren. "
          "Ich könnte Euch ins Brachland auf die Kodojagd schicken.")
check(clean(intact), intact, "ordinary German prose is left alone")
check(clean("Er kostet 5 Gold, 3 Silber."), "Er kostet 5 Gold, 3 Silber.",
      "numbers and commas are prose")

# Chunking: the reader drifts past roughly forty seconds, so nothing may exceed
# the limit by much, and nothing may be split mid-sentence while a sentence end
# was available.
long_text = " ".join("Dies ist ein Satz Nummer %d und er ist lang genug." % i
                     for i in range(1, 40))
pieces = chunks(long_text)
assert len(pieces) > 1, "a long passage was not split"
for piece in pieces:
    assert len(piece) <= MAX_CHARS * 1.5, "chunk too long: %d" % len(piece)
    assert piece.strip() == piece, "chunk has loose whitespace"
assert " ".join(pieces) == long_text, "chunking lost or duplicated text"

# A paragraph break is always a split; the listener expects the pause.
two = chunks("Erster Absatz.\n\nZweiter Absatz.")
check(two, ["Erster Absatz.", "Zweiter Absatz."], "paragraphs are separate clips")

# One sentence longer than the limit cannot split on sentence ends. It must
# still come apart, and never in the middle of a word.
runon = "Ich sage Euch, " + ", ".join(["dieser Teil ist ziemlich lang"] * 30) + "."
pieces = chunks(runon)
assert len(pieces) > 1, "an over-long single sentence was not split"
for piece in pieces:
    assert not piece.startswith(" ") and "  " not in piece, "split left ragged text"

check(chunks(""), [], "nothing to say means no clips")

print("speech: ok (%d cases)" % 24)
