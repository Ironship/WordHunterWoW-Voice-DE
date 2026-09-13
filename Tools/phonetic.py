#!/usr/bin/env python3
"""Compare transcripts by the sound they spell, not by the letters they use.

    python3 Tools/phonetic.py        # runs the self-test below

WHAT THE LETTER COMPARISON GETS WRONG

Tools/settle_words.py decides whether the reader is stable on a word by asking
for eight takes and measuring how much the transcripts agree. On German words
that works: the recogniser spells "Krieger" the same way every time, and the
takes differ only in punctuation, which normalise() removes.

On the invented names it does not work, and the reason is not the reader. The
recogniser is being handed a sound that has no spelling, so it invents one, and
it invents a different one each time. Aithlyn came back across eight takes as

    Aislinn   Aislinn?   Eithnen   Eislin   Etlin

which is one sound written five ways. On letters, through settle_words.py's own
normalise(), they score 0.608 mean pairwise similarity: eight thousandths above
the 0.6 bar that separates a stable reader from one needing a human ear. That is
not a verdict, it is a coin landing on its edge, and the individual pairs are
worse -- Aislinn against Eithnen scores 0.429. The reader was never unstable. It
said the same thing eight times and the recogniser could not agree with itself
about how to spell it.

WHAT THIS MEASURES INSTEAD

Koelner Phonetik: the standard German phonetic code (Postel 1969). It maps every
letter to one of nine digits chosen so that letters which sound alike in German
share a digit -- F/V/W all become 3, S/Z and soft C all become 8, vowels all
become 0 and then drop out. "Aislinn", "Aislinn?" and "Eislin" all reduce to
0856, so they compare as identical rather than as 0.77 similar.

It is the right tool for this specific job because it was built for German, not
adapted to it: Soundex would keep the vowels that the recogniser is guessing at,
and would not know that "sch" is one sound or that initial C is read as Z.

THE BAR HAS TO MOVE WITH THE METRIC -- THIS IS THE IMPORTANT PART

Collapsing the alphabet onto nine digits raises every score, not just the scores
that deserve to rise. Measured over 19,937 pairs of transcripts drawn from
*different* words in settled.jsonl -- pairs that by construction should not
agree -- the letter score clears 0.6 on 0.53% of them and the phonetic score on
5.70%. So settle_words.py's AGREE=0.6 cannot be carried over unchanged; it would
multiply false agreement tenfold. AGREE_PHONETIC below is where this metric is
no stricter than the one it would replace, and the price of that is written out
beside it, because there is a price.

This is a trade and not a free win. Read the table by AGREE_PHONETIC before
using this in a decision that costs something.

That is also why phonetic_similarity is not a drop-in replacement for
similarity() anywhere a threshold is already tuned. It answers a narrower
question -- "are these two transcripts the same sound" -- and it is only sound
when the two things compared are takes of one clip, as agreement() uses it.
Asked whether two *different* words are the same it will sometimes say yes:
Esslo codes to 085 and Aislinn to 0856, which scores 0.86 on a pair that shares
nothing but a leading vowel. Short codes are the weak spot -- four digits means
one digit is worth a quarter of the score -- and short codes are exactly what
one-word clips produce.

WHAT IT CANNOT SEE

Digits. "dreihundert" transcribed as "300" has no codeable letters at all and
codes to the empty string, exactly as Tools/respeak_bad.py describes. Those rows
are dropped from the work list upstream and never reach this.

Vowels, which is the whole trick and also the whole cost. Every vowel codes 0
and every 0 but a leading one is dropped, so this cannot tell Aislinn from
Eislin -- which is the point -- and equally cannot tell Meier from Mayr, or Moor
from Meer, which sometimes is not.
"""
import difflib
import re
import sys
import unicodedata

# The nine Koelner codes are assigned by these context sets. They are sets and
# not substring tests on purpose: `"" in "CSZ"` is True in Python, so writing the
# lookahead as a substring test silently codes every word-final T and D as 8
# instead of 2 and turns Mueller-Luedenscheidt into 657526828. Membership in a
# frozenset is False for the empty edge marker, which is the behaviour wanted.
VOWELS = frozenset("AEIJOUY")
BEFORE_C_INITIAL = frozenset("AHKLOQRUX")   # C at the start reads hard before these
BEFORE_C_INNER = frozenset("AHKOQUX")       # C inside the word reads hard before these
AFTER_C_SOFT = frozenset("SZ")              # ...unless it follows one of these ("sch")
BEFORE_DT_SOFT = frozenset("CSZ")           # D/T ahead of these are said as ts
AFTER_X_HARD = frozenset("CKQ")             # X here is only the s half of ks

# The only German letter Python does not already fold for us, and the reason
# this table is one entry rather than the twenty it looks like it should be.
#
# str.upper() expands lowercase eszett to SS on its own -- "ß".upper() == "SS" --
# and every umlaut and accent decomposes under NFD into a base letter plus a
# combining mark, which prepare() drops. So an A-umlaut arrives at A with no
# table at all, and an entry for it here would be dead code that reads as
# load-bearing. Capital eszett is the exception: U+1E9E survives both
# upper() and NFD unchanged, so without this line "STRAẞE" would lose the letter
# entirely to the A-Z filter and code as 827 instead of 8278.
FOLD = {"ẞ": "SS"}

NOT_LETTERS = re.compile(r"[^A-Z]")

# The threshold that means for this metric what AGREE=0.6 means for the letter
# metric in Tools/settle_words.py. Not guessed, and not matched on one side of
# the error only -- matching just the false-agreement rate gives 0.85, which
# also throws away two thirds of the clips the pipeline currently accepts.
#
# Measured on a 306-row snapshot of settled.jsonl. "Keeps" is the share of the
# 107 clips already judged stable and written back (confirmed or replaced) that
# still clear the bar; "fooled" is the share of 19,937 pairs of transcripts of
# *different* words that clear it, where agreement is by construction wrong.
#
#     bar               keeps   fooled
#     letters   0.60    76.6%    0.53%     <- what runs today
#     phonetic  0.60    86.9%    5.70%
#     phonetic  0.70    76.6%    1.85%     <- this one
#     phonetic  0.75    71.0%    1.83%
#     phonetic  0.80    52.3%    1.45%
#     phonetic  0.85    35.5%    0.67%
#
# 0.70 is the bar at which this metric is exactly as permissive as the letter
# metric it would replace -- the same 76.6% kept -- so swapping it in cannot
# start rejecting clips that are accepted now. What it costs is the other
# column: 1.85% against 0.53%, three and a half times as many unrelated pairs
# called equal. That buys the 33 of 122 currently-unstable clips whose takes are
# one sound spelled differently, Aithlyn among them at 0.750. Whether that trade
# is worth making is a decision about this pack and not a fact about phonetics,
# which is why nothing here changes settle_words.py's AGREE.
AGREE_PHONETIC = 0.70


def prepare(text):
    """Uppercase, fold German letters to A-Z, and throw away everything else.

    Punctuation and spaces go rather than being treated as word boundaries,
    because the recogniser's word boundaries are themselves a guess: the same
    clip comes back as "Aye", "A.I.E." and "Ah ja". Running the letters together
    before coding means that guess cannot make two takes of one sound disagree.
    """
    text = unicodedata.normalize("NFC", str(text or "")).upper()
    text = "".join(FOLD.get(ch, ch) for ch in text)
    # Decompose whatever accents are left and drop the combining marks, so a
    # letter this table has never seen still lands on its base letter.
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return NOT_LETTERS.sub("", text)


def koelner(text):
    """The Koelner Phonetik code for a German string.

    Postel's table, in full, including the parts most one-page versions drop:
    C changes code depending on both the letter before it and the letter after
    it, and follows a wider rule at the start of a word than inside one (initial
    C before L or R is hard, as in Claus and Crux, where an inner C before the
    same letters is not). D and T before C, S or Z are the ts sound and code 8.
    P before H is F. X is two codes, 48, unless the k is already spoken by a
    preceding C, K or Q, in which case it is only the 8.

    Then the two clean-up passes, in this order and not the other: runs of the
    same code collapse to one, and every 0 is dropped except one that ends up
    first. The order matters -- LL collapses to a single 5, but L-vowel-L does
    not, because the 0 between them is still there when the collapse runs.
    """
    letters = prepare(text)
    codes = []
    for i, ch in enumerate(letters):
        prev = letters[i - 1] if i else ""
        nxt = letters[i + 1] if i + 1 < len(letters) else ""
        if ch in VOWELS:
            codes.append("0")
        elif ch == "H":
            # H is never a code of its own. It still matters as context, which
            # is why it is skipped here rather than removed in prepare().
            continue
        elif ch == "B":
            codes.append("1")
        elif ch == "P":
            codes.append("3" if nxt == "H" else "1")
        elif ch in "DT":
            codes.append("8" if nxt in BEFORE_DT_SOFT else "2")
        elif ch in "FVW":
            codes.append("3")
        elif ch in "GKQ":
            codes.append("4")
        elif ch == "C":
            if not i:
                codes.append("4" if nxt in BEFORE_C_INITIAL else "8")
            elif prev in AFTER_C_SOFT:
                codes.append("8")
            else:
                codes.append("4" if nxt in BEFORE_C_INNER else "8")
        elif ch == "X":
            codes.append("8" if prev in AFTER_X_HARD else "48")
        elif ch == "L":
            codes.append("5")
        elif ch in "MN":
            codes.append("6")
        elif ch == "R":
            codes.append("7")
        elif ch in "SZ":
            codes.append("8")

    code = "".join(codes)
    squeezed = []
    for digit in code:
        if not squeezed or squeezed[-1] != digit:
            squeezed.append(digit)
    if not squeezed:
        return ""
    return squeezed[0] + "".join(squeezed[1:]).replace("0", "")


def phonetic_similarity(a, b):
    """How alike two strings sound, 0..1, by difflib on their Koelner codes.

    Same shape as Tools/settle_words.py's similarity(), so the two can be swapped
    and compared, but normalise() is not used: prepare() already does the work,
    and does more of it -- casefolding alone leaves "Aislinn" and "Eislin" four
    edits apart.
    """
    x, y = koelner(a), koelner(b)
    if not x or not y:
        # Two strings with no codeable letters are not two strings that sound
        # alike, but SequenceMatcher scores a pair of empties 1.0. Left alone
        # that would let two takes the recogniser heard nothing in look like
        # perfect agreement, which is the exact failure this file exists to
        # avoid making. Nothing compared to nothing is no evidence.
        return 0.0
    return difflib.SequenceMatcher(None, x, y).ratio()


def agreement(transcripts):
    """Mean similarity of every take to every other, and the take nearest all.

    The contract of Tools/settle_words.py's agreement() exactly -- same return
    shape, same medoid choice, same (0.0, 0) for fewer than two takes -- scored
    by sound instead of by letters, so the two can be run over the same takes
    and the difference read off.

    The medoid rather than the first or the shortest: with the takes agreeing,
    the one closest to the rest is the one least likely to carry whatever oddity
    a single pass through the recogniser introduced. Note that it is still
    chosen on phonetic distance but returned as an index into the original
    transcripts, so the caller gets back a real spelling and not a code.
    """
    if len(transcripts) < 2:
        return 0.0, 0
    best_index, best_mean, total, pairs = 0, -1.0, 0.0, 0
    for i, one in enumerate(transcripts):
        mean = 0.0
        for j, other in enumerate(transcripts):
            if i == j:
                continue
            score = phonetic_similarity(one, other)
            mean += score
            if j > i:
                total += score
                pairs += 1
        mean /= len(transcripts) - 1
        if mean > best_mean:
            best_mean, best_index = mean, i
    return (total / pairs if pairs else 0.0), best_index


# ---------------------------------------------------------------------------
# Self-test.
#
# The letter-similarity side of the comparison is imported from
# Tools/settle_words.py rather than reimplemented here, so that "phonetics beats
# letters" is asserted against the code that is actually running in the
# pipeline. If that import breaks, the self-test fails loudly instead of
# quietly measuring itself against a copy that has drifted.
# ---------------------------------------------------------------------------

# The eight takes of Aithlyn, as settle_words.py recorded them. Five distinct
# spellings of one sound; the worked example the whole file is about.
AITHLYN = ["Aislinn", "Aislinn?", "Eithnen", "Eislin", "Etlin"]


def _letter_similarity():
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from settle_words import similarity
    return similarity


def _selftest():
    letter_similarity = _letter_similarity()
    checks = []

    def check(label, got, want):
        checks.append((label, got == want, got, want))

    def expect(label, condition, detail):
        checks.append((label, bool(condition), detail, "true"))

    # -- published reference codes. Every one of these was recomputed by hand
    # -- against Postel's table before being written down here.
    check("koelner('Wikipedia')", koelner("Wikipedia"), "3412")
    check("koelner('Meier')", koelner("Meier"), "67")
    check("koelner('Mayr')", koelner("Mayr"), "67")
    check("koelner('Breschnew')", koelner("Breschnew"), "17863")
    check("koelner('Müller-Lüdenscheidt')",
          koelner("Müller-Lüdenscheidt"), "65752682")
    check("koelner('Heinz')", koelner("Heinz"), "068")
    check("koelner('Hinz')", koelner("Hinz"), "068")

    # -- umlaut and eszett folding
    check("koelner('Müller') == koelner('Mueller')",
          koelner("Müller"), koelner("Mueller"))
    check("koelner('Müller')", koelner("Müller"), "657")
    check("koelner('Straße') == koelner('Strasse')",
          koelner("Straße"), koelner("Strasse"))
    # The capital eszett, which is the single entry FOLD exists for.
    check("koelner('STRAẞE')", koelner("STRAẞE"), "8278")
    check("koelner('Löwe') == koelner('Loewe')",
          koelner("Löwe"), koelner("Loewe"))
    # Most of the umlaut checks above pass even if the umlaut is thrown away
    # rather than folded, because a dropped vowel and a vowel coded 0 both
    # vanish in the clean-up. The difference only shows when the vowel is
    # holding two identical consonant codes apart, as the A does in Maenner: fold
    # it and the NN stays separated from the M, drop it and everything collapses
    # to 67. So this is the check that actually tests the folding.
    check("koelner('Männer')", koelner("Männer"), "667")
    check("koelner('Männer') == koelner('Manner')",
          koelner("Männer"), koelner("Manner"))

    # -- the context rules, each pinned by a pair that must agree only if the
    # -- rule is implemented, plus the raw code so a wrong-but-equal pair fails
    check("initial C soft: 'Cent' == 'Zent'", koelner("Cent"), koelner("Zent"))
    check("koelner('Cent')", koelner("Cent"), "862")
    check("initial C hard before R: 'Crux' == 'Krux'",
          koelner("Crux"), koelner("Krux"))
    check("inner C after S: 'Fischer'", koelner("Fischer"), "387")
    # Inner C before A is hard, so Cacao must read as Kakao. Checked against the
    # code as well as against the pair, because a soft inner C would give 48 and
    # an equality test alone would not notice if both sides moved.
    check("inner C hard before A: 'Cacao' == 'Kakao'",
          koelner("Cacao"), koelner("Kakao"))
    check("koelner('Cacao')", koelner("Cacao"), "44")
    check("D before S: 'Tsar' == 'Zar'", koelner("Tsar"), koelner("Zar"))
    check("word-final T is 2 not 8: 'Blut'", koelner("Blut"), "152")
    check("P before H: 'Phase' == 'Fase'", koelner("Phase"), koelner("Fase"))
    check("koelner('Phase')", koelner("Phase"), "38")
    check("X is 48: 'Axel' == 'Aksel'", koelner("Axel"), koelner("Aksel"))
    check("koelner('Axel')", koelner("Axel"), "0485")
    # The X-after-C/K/Q rule needs an odd probe, and it is worth saying why.
    # After K or Q the rule cannot be observed at all: those code 4, the full X
    # codes 48, and 4 followed by 48 collapses to 48 -- the same answer the rule
    # gives. The only place it shows is a *soft* C before X, which needs an S or
    # Z in front of the C. Hence Scx, where the rule gives 8 and its absence
    # gives 848. Szx is the control: Z is not in the set, so the X keeps both
    # digits and the two strings must not code alike.
    check("X after soft C is 8, not 48: 'Scx'", koelner("Scx"), "8")
    check("X after Z keeps both: 'Szx'", koelner("Szx"), "848")
    check("X is 48 elsewhere: 'Faxe'", koelner("Faxe"), "348")

    # -- the clean-up passes
    check("repeats collapse: 'Rolle' == 'Role'", koelner("Rolle"), koelner("Role"))
    check("a 0 between them does not: 'Lale'", koelner("Lale"), "55")
    check("leading 0 is kept: 'Ohm'", koelner("Ohm"), "06")
    check("nothing codeable is empty: '300'", koelner("300"), "")

    # -- the point of the file: every pair of Aithlyn's spellings must score
    # -- higher by sound than by letters
    core = ["Aislinn", "Eislin", "Etlin", "Eithnen"]
    for i in range(len(core)):
        for j in range(i + 1, len(core)):
            a, b = core[i], core[j]
            phon, lett = phonetic_similarity(a, b), letter_similarity(a, b)
            expect("%-9s/%-9s phonetic %.3f > letters %.3f" % (a, b, phon, lett),
                   phon > lett, "%.3f > %.3f" % (phon, lett))

    # -- and the whole set must clear the phonetic bar by more than it clears
    # -- the letter bar, which it currently scrapes past by 0.008
    score, medoid = agreement(AITHLYN)
    letters = sum(letter_similarity(AITHLYN[i], AITHLYN[j])
                  for i in range(len(AITHLYN))
                  for j in range(i + 1, len(AITHLYN)))
    letters /= len(AITHLYN) * (len(AITHLYN) - 1) / 2
    expect("agreement(AITHLYN) = %.3f >= AGREE_PHONETIC %.2f" % (score, AGREE_PHONETIC),
           score >= AGREE_PHONETIC, "%.3f" % score)
    expect("...clearing it by %.3f, against %.3f on letters against 0.6"
           % (score - AGREE_PHONETIC, letters - 0.6),
           score - AGREE_PHONETIC > letters - 0.6, "wider margin")
    expect("medoid %d is in range" % medoid, 0 <= medoid < len(AITHLYN), medoid)

    # -- the guard against the metric becoming a yes-machine. Esslo and Atriel
    # -- are different words the reader says differently and must stay under the
    # -- bar. Note what is *not* asserted: that they score below every Aithlyn
    # -- pair. They do not -- 0.571 against a worst pair of 0.500 -- because two
    # -- vowel-initial words share a leading 0 and there are only four digits
    # -- for it to be a quarter of. That overlap is real and is the reason
    # -- AGREE_PHONETIC is set on the mean of eight takes and not on one pair.
    apart = phonetic_similarity("Esslö", "Atriel")
    expect("phonetic_similarity('Esslo','Atriel') = %.3f < AGREE_PHONETIC" % apart,
           apart < AGREE_PHONETIC, "%.3f" % apart)
    expect("...and well under AITHLYN's %.3f" % score, score - apart > 0.15,
           "%.3f" % apart)
    for a, b in [("Cozzle", "Atriel"), ("Cyrce", "Aithlyn"), ("Krieger", "Blume")]:
        s = phonetic_similarity(a, b)
        expect("phonetic_similarity(%r,%r) = %.3f stays low" % (a, b, s),
               s < 0.6, "%.3f" % s)

    # -- agreement()'s contract, matched to Tools/settle_words.py
    check("agreement([]) ", agreement([]), (0.0, 0))
    check("agreement(['x'])", agreement(["x"]), (0.0, 0))
    check("agreement of identical takes", agreement(["Meier"] * 4), (1.0, 0))
    expect("empty transcripts do not agree",
           phonetic_similarity("", "") == 0.0 and agreement(["", "..."])[0] == 0.0,
           "0.0")

    width = max(len(label) for label, _, _, _ in checks)
    failed = 0
    for label, ok, got, want in checks:
        if ok:
            print("PASS  %s" % label)
        else:
            failed += 1
            print("FAIL  %-*s  got %r, wanted %r" % (width, label, got, want))
    print()
    print("%d checks, %d passed, %d failed" % (len(checks), len(checks) - failed, failed))
    print("ALL PASS" if not failed else "FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_selftest())
