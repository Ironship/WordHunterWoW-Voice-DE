#!/usr/bin/env python3
"""Turn a quest passage into the words a narrator should actually say.

Blizzard's quest text is not prose. It carries markup the client resolves at
display time, and a reader who has never seen it says it out loud: "Lasst sie
nicht warten, kleiner als name grösser." Measured on the German corpus, 13.6% of
spoken passages carry at least one of these, almost all of them <name>.

The rules here are deliberately few. Every one of them exists because the token
appears in the corpus; nothing is handled speculatively.
"""
import re
import unicodedata

# The player's own name, class or race, substituted by the client. Pre-rendered
# audio is shared by everyone, so there is no name to say. Dropping the token
# and the comma that introduced it turns "Lasst sie nicht warten, <name>." into
# a sentence that is still a sentence -- which reads better than any stand-in,
# because German quest text uses these vocatively.
#
# Two shapes, both of them real. The German corpus holds <Name> 8,544 times,
# <Klasse> 1,832 and <Volk> 760, and separately {name} 4,917 times, {class}
# 1,052 and {race} 482. Only the angled form was handled at first, which left
# six and a half thousand passages in which the reader says the word "name" out
# loud. Also catches the stage directions written the same way, <hust>, which a
# narrator should not pronounce either.
PLAYER_TOKEN = re.compile(r"\s*,?\s*(?:<[A-Za-z][A-Za-z ]*>|\{[A-Za-z][A-Za-z ]*\})\s*")

# $G male:female;  and its lowercase form. The narrator cannot know, and the
# masculine is what the German client shows a reader who has not chosen.
GENDER_TOKEN = re.compile(r"\$[Gg]\s*([^:;]*):([^;]*);")
# $B and $b are line breaks; $N is the player's name again; $C class, $R race.
BREAK_TOKEN = re.compile(r"\$[Bb]")
BARE_TOKEN = re.compile(r"\$[A-Za-z]")

# |cFFRRGGBB ... |r wraps coloured text. The colour is not spoken; the text is.
COLOUR_OPEN = re.compile(r"\|c[0-9A-Fa-f]{8}")
COLOUR_CLOSE = re.compile(r"\|r")
# |4singular:plural; picks by a number the narrator does not have. Plural reads
# as the general case in the one place this appears ("|4Minute:Minuten;").
PLURAL_TOKEN = re.compile(r"\|4([^:;]*):([^;]*);")
# |3-6(Ausdruck) asks the client to decline a word. The word itself is what the
# reader wants; the case marker is a grammar instruction, not speech.
DECLINE_TOKEN = re.compile(r"\|3-\d+\(([^)]*)\)")
# Blizzard's own placeholder and test markers. A passage that is one of these is
# not real text and should not be given a voice at all.
NOT_REAL = re.compile(r"^\s*(\[PH\]|\[DNT\]|\[DEPRECATED\]|PH\b|TEST\b)", re.IGNORECASE)

# Angled spans that PLAYER_TOKEN does not reach, because it allows only letters
# and spaces between the brackets. Three kinds occur, and they want three
# different answers -- 8,778 clips carry one, which is 2.6% of the pack.
#
# <Abenteurer/Abenteurerin> is one word in two genders, 260 of them. The
# masculine is what the German client shows a reader who has not chosen, which
# is the same rule GENDER_TOKEN already follows for the $G form.
ANGLE_GENDER = re.compile(r"<([^<>/]*)/([^<>]*)>")
# <A'dal grüßt Euch.> is a stage direction, and it is prose: the player reads it
# in the quest window, and this addon exists so that what the player reads is
# also what they hear. So the words stay -- but the brackets go, because a
# reader given them says "kleiner als" out loud.
#
# The one-word forms are not reached here: PLAYER_TOKEN has already taken
# <Name>, <Klasse> and the coughs and grunts written the same way, none of which
# is prose and none of which should be pronounced.
#
# The span runs to 800 characters because these are not all short: the longest
# run to several sentences across a paragraph break, and a limit of 200 left
# 1,131 clips with a bracket hanging off one end and its partner in the next
# clip. Bounded rather than open-ended so that a single unpaired "<" somewhere
# in the corpus cannot swallow the rest of a passage.
ANGLE_PROSE = re.compile(r"<([^<>]{1,800})>", re.DOTALL)

# |A:atlas-name:0:1.00|a inlines an icon. Eleven passages carry a run of them,
# and spoken aloud it is a stream of file names.
TEXTURE_TOKEN = re.compile(r"\|[AaTt]:?[^|]*\|[aAtT]?")
# $2063w is a quantity the client fills in from the quest's own state. There is
# no state here and no number to say, so the token goes. Distinct from
# BARE_TOKEN, which only reaches $ followed by a letter.
NUMBER_TOKEN = re.compile(r"\$\d+[A-Za-z]?")

# The reward header, glued straight onto the end of the prose with no space:
# "...wieder ins Leben rufen.Ihr bekommt:". Interface furniture that the harvest
# swept up with the text, in 2,495 clips. Everything from it to the end goes.
REWARD_TAIL = re.compile(r"(?:Ihr\s+(?:bekommt|erhaltet)|Zur\s+Auswahl\s+stehen)\s*:?\s*.*$",
                         re.DOTALL)

SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
REPEATED_PUNCT = re.compile(r"([,;:])\s*([,.;:!?])")
MANY_SPACES = re.compile(r"[ \t]+")
MANY_BREAKS = re.compile(r"\n{3,}")


def clean(text):
    """The passage as it should be read, or "" if it should not be read at all."""
    text = unicodedata.normalize("NFC", str(text or ""))
    if not text.strip() or NOT_REAL.match(text):
        return ""
    text = REWARD_TAIL.sub("", text)
    text = COLOUR_OPEN.sub("", text)
    text = COLOUR_CLOSE.sub("", text)
    text = TEXTURE_TOKEN.sub(" ", text)
    text = DECLINE_TOKEN.sub(r"\1", text)
    text = PLURAL_TOKEN.sub(r"\2", text)
    text = GENDER_TOKEN.sub(r"\1", text)
    text = BREAK_TOKEN.sub("\n", text)
    # Order matters among the angled spans. The gendered form picks one of two
    # words, so it goes first; the one-word tokens are dropped next; whatever is
    # still in brackets after that is prose.
    text = ANGLE_GENDER.sub(r"\1", text)
    text = PLAYER_TOKEN.sub(" ", text)
    # Last of the angled rules: whatever survived the ones above is prose, and
    # keeps its words while losing its brackets.
    text = ANGLE_PROSE.sub(r"\1", text)
    text = NUMBER_TOKEN.sub("", text)
    text = BARE_TOKEN.sub("", text)
    # The substitutions leave gaps: a dropped vocative takes its comma with it,
    # but a dropped mid-sentence token leaves the space it sat in.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = MANY_SPACES.sub(" ", text)
    text = REPEATED_PUNCT.sub(r"\2", text)
    text = SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = MANY_BREAKS.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


# One clip per sentence, because the addon highlights the sentence it is reading
# and cannot highlight half of one. The split has to match the addon's exactly:
# Addon.SplitSentences in the base addon decides which sentence a highlight
# lands on, and if the two disagree the wrong line lights up. This is a port of
# that function, not a second opinion about German punctuation, and
# tests/sentences.test.py holds it to vectors taken from real quest text.
ABBREVIATIONS = {"dr.", "mr.", "mrs.", "ms.", "z.b.", "d.h.", "bzw.", "e.g.", "i.e."}
TRAILING = "\"'>)]“”’»"
TOKEN = re.compile(r"\S+")


def sentences(text):
    """The passage split the way the addon splits it, in order."""
    text = str(text or "")
    out = []
    first = last = None
    for match in TOKEN.finditer(text):
        start, token, after = match.start(), match.group(), match.end()
        # A line break between two tokens ends the sentence even without a full
        # stop: quest text uses them as one.
        if last is not None and re.search(r"[\r\n]", text[last:start]):
            out.append(text[first:last]); first = last = None
        if first is None:
            first = start
        last = after
        ending = token.rstrip(TRAILING)
        if (ending.endswith((".", "!", "?", "…"))
                and ending.lower() not in ABBREVIATIONS):
            out.append(text[first:last]); first = last = None
    if first is not None:
        out.append(text[first:last])
    return [s.strip() for s in out if s.strip()]


# A sentence longer than this is read in pieces and joined. Chatterbox drifts
# past roughly forty seconds; German runs about fifteen characters a second, and
# the longest single sentence in the corpus is 556 characters.
MAX_CHARS = 420

# And a clip shorter than this is joined to the one after it. Two reasons, and
# the first is not a preference: the reader raises IndexError inside its own
# alignment analyser on very short input, so "Ja..." on its own is not a clip
# that can be made at all. The second is that it should not be one anyway --
# a two-character line is not worth a highlight of its own, and a passage read
# as a string of one-word clips sounds like a list rather than speech.
MIN_CHARS = 30

# Any letter, including the accented ones German needs.
HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def clips(text):
    """The passage as clips: sentences, with the short ones joined to a neighbour.

    A clip may therefore cover more than one sentence, and the addon highlights
    the whole group. That is the trade: perfect per-sentence highlighting would
    mean clips the reader cannot produce.

    Groups never cross a paragraph break, because the pause there is one the
    listener expects to hear.
    """
    out = []
    for paragraph in [p for p in str(text or "").split("\n\n") if p.strip()]:
        group = []
        for sentence in sentences(paragraph):
            candidate = " ".join(group + [sentence])
            if group and len(candidate) > MAX_CHARS:
                out.append(" ".join(group))
                group = [sentence]
            else:
                group.append(sentence)
            if len(" ".join(group)) >= MIN_CHARS:
                out.append(" ".join(group))
                group = []
        if group:
            # Whatever is left is below the minimum. Rather than emit a clip the
            # reader would choke on, give it to the one before it.
            tail = " ".join(group)
            if out and len(out[-1]) + 1 + len(tail) <= MAX_CHARS:
                out[-1] = out[-1] + " " + tail
            else:
                out.append(tail)
    # A clip with no letter in it is not speech. The splitter leaves a bare "!"
    # or "," behind where quest text has stray punctuation, and there is nothing
    # to read aloud in one -- the reader raises on it rather than saying
    # nothing, which is how these were found.
    return [clip for clip in out if HAS_LETTER.search(clip)]
