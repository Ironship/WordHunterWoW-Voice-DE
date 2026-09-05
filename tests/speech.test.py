#!/usr/bin/env python3
"""Run from the repo root:  python tests/speech.test.py

Every case here is a token that really occurs in the German quest corpus. A
reader that says markup out loud is the single most noticeable way this pack can
be wrong, and it is not something the game will report.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "Tools"))
from speech import clean, sentences, MAX_CHARS


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
# The same placeholders are written in braces elsewhere in the corpus -- {name}
# 4,917 times, {class} 1,052, {race} 482 -- and only the angled form was handled
# at first, so six and a half thousand passages had the reader say "name".
check(clean("Lasst sie nicht warten, {name}."), "Lasst sie nicht warten.",
      "a braced vocative is a vocative too")
check(clean("eine Aufgabe, die zu einem wie Euch passt, {class}."),
      "eine Aufgabe, die zu einem wie Euch passt.", "braced class token")
check(clean("Ihr seid ein {race} von Rang."), "Ihr seid ein von Rang.", "braced race token")
check(clean("<Kaltunk lacht.>"), "<Kaltunk lacht.>", "a stage direction is kept, it is prose")
check(clean("Nun <hust> weiter."), "Nun weiter.", "a cough is not pronounced")
check(clean("[DEPRECATED] alter Text"), "", "a retired quest is not voiced")

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

# One clip per sentence. The split is a port of the addon's own SplitSentences,
# and tests/_crosscheck.lua holds the two to the same answers across four
# thousand real passages. These are the shapes that broke it while porting.
check(sentences("Eins. Zwei! Drei?\nVier."), ["Eins.", "Zwei!", "Drei?", "Vier."],
      "sentences split on . ! ? and on line breaks")
check(sentences("Dr. Jones hat 3.5 Gold. Los!"), ["Dr. Jones hat 3.5 Gold.", "Los!"],
      "an abbreviation and a decimal are not sentence ends")
check(sentences('Wartet... "Ja!" Zur Zuflucht.'), ["Wartet...", '"Ja!"', "Zur Zuflucht."],
      "a closing quote does not hide the sentence end before it")
check(sentences("Erster Absatz.\n\nZweiter Absatz."), ["Erster Absatz.", "Zweiter Absatz."],
      "a paragraph break separates sentences")
check(sentences("Ohne Punkt am Ende"), ["Ohne Punkt am Ende"],
      "a passage with no final stop is still one sentence")
check(sentences(""), [], "nothing to say means no clips")
check(sentences("   "), [], "whitespace is not a sentence")

# Nothing may be lost or invented: a clip is played while its sentence is lit, so
# a sentence that is not in the passage would light nothing.
passage = "Erste. Zweite! Dritte?\n\nVierte."
for piece in sentences(passage):
    assert piece in passage, "a sentence was invented: %r" % piece
assert len("".join(sentences(passage)).replace(" ", "")) == \
    len(passage.replace(" ", "").replace("\n", "")), "sentence splitting lost text"

# A single sentence can still be longer than the reader handles in one go.
assert MAX_CHARS > 0, "the reader needs a length it will not exceed"

print("speech: ok (%d cases)" % 31)
