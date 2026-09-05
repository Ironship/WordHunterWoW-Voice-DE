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
PLAYER_TOKEN = re.compile(r"\s*,?\s*<[A-Za-z][A-Za-z ]*>\s*")

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
NOT_REAL = re.compile(r"^\s*(\[PH\]|\[DNT\]|PH\b|TEST\b)", re.IGNORECASE)

SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
REPEATED_PUNCT = re.compile(r"([,;:])\s*([,.;:!?])")
MANY_SPACES = re.compile(r"[ \t]+")
MANY_BREAKS = re.compile(r"\n{3,}")


def clean(text):
    """The passage as it should be read, or "" if it should not be read at all."""
    text = unicodedata.normalize("NFC", str(text or ""))
    if not text.strip() or NOT_REAL.match(text):
        return ""
    text = COLOUR_OPEN.sub("", text)
    text = COLOUR_CLOSE.sub("", text)
    text = DECLINE_TOKEN.sub(r"\1", text)
    text = PLURAL_TOKEN.sub(r"\2", text)
    text = GENDER_TOKEN.sub(r"\1", text)
    text = BREAK_TOKEN.sub("\n", text)
    text = PLAYER_TOKEN.sub(" ", text)
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


# Chatterbox is reliable up to roughly forty seconds of speech and starts to
# drift beyond it. German runs about fifteen characters a second, and the
# longest passage in the corpus is 1054 characters -- seventy seconds -- so
# long passages have to be read in pieces and joined.
MAX_CHARS = 420
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def chunks(text, limit=MAX_CHARS):
    """Split for the reader, on sentence ends, never mid-sentence if avoidable.

    A paragraph break is always a split: it is a pause the listener expects, and
    joining across one makes the reader run two thoughts together.
    """
    out = []
    for paragraph in [p for p in text.split("\n\n") if p.strip()]:
        current = ""
        for sentence in SENTENCE_END.split(paragraph.replace("\n", " ")):
            sentence = sentence.strip()
            if not sentence:
                continue
            if not current:
                current = sentence
            elif len(current) + 1 + len(sentence) <= limit:
                current += " " + sentence
            else:
                out.append(current)
                current = sentence
        if current:
            out.append(current)
    # A single sentence longer than the limit is rare and cannot be split on
    # sentence ends. Fall back to commas, then to nothing: better a long clip
    # than a clip cut in the middle of a word.
    final = []
    for piece in out:
        if len(piece) <= limit * 1.5:
            final.append(piece)
            continue
        part = ""
        for bit in piece.split(", "):
            if part and len(part) + 2 + len(bit) > limit:
                final.append(part)
                part = bit
            else:
                part = bit if not part else part + ", " + bit
        if part:
            final.append(part)
    return final
