"""Input normalisation for the extractor, with an offset map back to the original text.

A scam message is not typed for us. The ones a judge pastes in live arrive with Cyrillic "о" standing in for
Latin "o", zero-width spaces sprinkled inside words ("tra<ZWSP>nsf<ZWSP>er"), WhatsApp's mathematical-bold
letters, fullwidth digits and leetspeak ("arr3st"). None of that changes what the message says to a reader, and
all of it used to make our pattern tables see nothing at all: the homoglyph probe came back GREY while its
clean-ASCII twin came back AMBER on two hard rules.

So the extractor matches on a normalised copy. The one thing that must survive is grounding: every Span the
extractor stores is quoted back to the officer and drawn with a leader line onto the ORIGINAL characters, and
`extract.ground()` drops any field whose quote is not literally in `claim.text`. `normalise()` therefore returns
an index map, and `map_span()` turns normalised offsets back into original ones. Nothing downstream ever sees the
normalised string; `claim.text` stays exactly what was pasted.

What the pass does, per character, so that the map stays exact:
1. drops zero-width and soft-hyphen characters (U+200B-U+200D, U+2060, U+FEFF, U+00AD);
2. folds the Unicode confusables a scam actually uses (Cyrillic а е о р с х у і ј ѕ and capitals, Greek
   ο α ε ρ and capitals) to their Latin look-alikes;
3. maps the exotic spaces (NBSP and friends) to a plain space;
4. applies NFKC to each remaining character on its own. Per character rather than to the whole string, because
   one original character must map to a contiguous run of normalised characters for the index map to hold.
   That is what folds fullwidth "Ｔ" and WhatsApp's mathematical-bold letters. Composition is not needed: our
   Devanagari patterns are written with decomposed nukta (ज + ़), which is what NFKC produces anyway.
5. folds leetspeak digits back to letters, but only strictly inside a word (see `_deleet`), so "Rs 25,00,000",
   the 1600 helpline prefix, an IFSC and a 14-digit account number are never touched.
6. closes up intra-word separation ("t r a n s f e r", "t.r.a.n.s.f.e.r"), but only where the folded run
   reconstitutes a word the
   CALLER's lexicon already knows (see `_despace_drops`). The lexicon is passed in rather than defined here,
   because the only words it is ever safe to fold are the words the extractor's own tables look for; see
   `extract.DESPACE_LEXICON`. With no lexicon, step 6 does nothing at all.

Steps 1-5 are one-to-one or one-to-many per original character. Step 6 is the first step that DELETES a
character that a reader can see, so it is the one the index map had to be re-checked against: a deleted
separator only removes its own entry from `origin`, every surviving character keeps the original index it
already had, and the original slice a normalised match maps back to is therefore still the literal run of
characters in the message ("t r a n s f e r" / "t.r.a.n.s.f.e.r", separators included). That is what the
officer is shown and what `ground()` re-checks.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Dropped outright: ZWSP, ZWNJ, ZWJ, word joiner, BOM, soft hyphen. ZWNJ/ZWJ carry meaning in Devanagari
# shaping but never in our patterns, and scam text uses them exactly as it uses ZWSP: to break a word in half
# so a keyword list misses it.
_DROP = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD)}

# Exotic spaces, folded to a plain space. Written as code points so the table cannot silently collapse.
_SPACES = {chr(c) for c in (0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007,
                            0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000, 0x2028, 0x2029)}

# Look-alike letters, folded to Latin. Deliberately short: only the letters that appear in real homoglyph scam
# text. A wider table (the full Unicode confusables file, Cherokee, Armenian) would fold letters a Hindi or
# English message uses for real, and a wrong fold is a silent wrong quote.
_CONFUSABLE = {
    # Cyrillic, lower case
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԝ": "w", "һ": "h",
    # Cyrillic, upper case
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J",
    "Ѕ": "S", "З": "3",
    # Greek
    "ο": "o", "α": "a", "ε": "e", "ρ": "p", "ι": "i", "κ": "k", "τ": "t",
    "υ": "u", "χ": "x", "ν": "v",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    # Latin oddities used as look-alikes
    "ı": "i", "ɑ": "a", "ɡ": "g", "ɩ": "i",
}

_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b"}
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_LETTER = re.compile(r"[A-Za-z]")


def _deleet(chars: list[str]) -> None:
    """Fold leetspeak digits to letters in place, only where the digit is standing in for a letter.

    A digit is folded only when, inside its own alphanumeric token, every digit has a letter immediately before
    and immediately after it, and the token holds at least three letters. That is enough for "transf3r" and
    "arr3st" and provably cannot touch:
      - a bare number ("25,00,000", "1600033330", "50100248891776") - no letters in the token;
      - an identifier whose digits are a trailing block ("HDFC0000123", "DEMO0001234", "ED/DLZO/2026/4471");
      - a short mixed token ("B2B", "H2O", "A1") - fewer than three letters.
    The cost is that "p4y" (two letters) is not folded. A missed fold is a smaller lie than a mangled account
    number, which is why the bound sits here.
    """
    s = "".join(chars)
    for t in _TOKEN.finditer(s):
        tok = t.group(0)
        if len(_LETTER.findall(tok)) < 3:
            continue
        digits = [i for i, c in enumerate(tok) if c.isdigit()]
        if not digits or not all(tok[i] in _LEET for i in digits):
            continue
        if not all(0 < i < len(tok) - 1 and _LETTER.match(tok[i - 1]) and _LETTER.match(tok[i + 1]) for i in digits):
            continue
        for i in digits:
            chars[t.start() + i] = _LEET[tok[i]]


# ---- intra-word spacing ------------------------------------------------------------------------------------
# "You must t r a n s f e r Rs 38,00,000 to the verification account" read as instruction NONE and scored GREY,
# because spacing walks straight through everything above: there is no confusable, no zero-width and no digit to
# fold, just eight ordinary one-letter words. A judge found it on 18 Oct.
#
# Pass 5 closed the plain space. ONE character defeated it: "t.r.a.n.s.f.e.r", "t-r-a-n-s-f-e-r",
# "t_r_a_n_s_f_e_r" and "t·r·a·n·s·f·e·r" all read as no instruction, and because pass 5 also made a money
# demand NECESSARY for RED, a missed instruction now costs the whole band rather than one field. A judge found
# all four on 18 Oct. So the separator is a CLASS, not a space: the thing being evaded is "put something
# between the letters", and which character it is was never the point.
#
# THE RULE, exactly. A run of five or more single ASCII letters separated only by SEPARATORS (a plain space or
# one of `. - _ / * · ‧ • ∙`, in any mix, one or more per gap), with no letter or digit touching either end of
# the run, is scanned left to right; at each position the longest word of five or more letters that the caller's
# lexicon knows is taken, and only the separators INSIDE that word are deleted. Letters that no lexicon word
# starts at are left exactly as they are, separators and all.
#
# THE BOUND, and why it sits here:
#   - Lexicon membership is the real bound. "t r a n s f e r" folds because the extractor's tables already look
#     for "transfer"; "R A J E S H" does not fold, because nothing in this engine looks for that word. Folding a
#     run into a non-word could only ever invent text.
#   - The five-letter floor is the second bound, and widening the separator is exactly what makes it load-
#     bearing rather than incidental. It is what keeps spaced and PUNCTUATED initialisms and numbers out:
#     "I N R 5 0", "A/c No 500 100 234", "a/c", "C B I", "C.B.I.", "U.P.I.", "N.C.R.P.", "S E B I" each carry
#     at most four letters in a run, so none of them is even considered. "w.r.t.", "s/o", "d/o", "M. A., LL. B."
#     and "Smt. A. K." are out for the same reason. The cost is a real false negative: a punctuated "C.B.I." is
#     not read as an issuer and "a/c" is not read as a destination. Accepted. The alternative is folding three-
#     letter runs, which with any wider lexicon would start rewriting identifiers, and a false positive is worse
#     than a false negative here.
#   - Digits are never part of a run, so an amount, an IFSC or an account number cannot be touched by this step
#     at all. "3.0.0.1.1" is not a run and "H.D.F.C.0.0.0.0.1.2.3" carries only four letters before the digits.
#   - A separator is one of U+0020 and `. - _ / * · ‧ • ∙`, in any mix. Never a newline or a tab: a wrapped line
#     is not intra-word spacing, and a column of single letters in an OCR'd table must not become a word. Never
#     a comma or a colon either: those carry structure a reader uses, and a comma-separated list of single
#     letters is a list. The exotic spaces were already folded to U+0020 in step 3, and NFKC in step 4 has
#     already turned the fullwidth and compatibility forms (U+FF0D, U+2024) into the ASCII ones listed here.
# Not covered, deliberately: partially separated words ("tra n sfer", "tran.sfer") and Devanagari, where a
# letter is several code points with its matras and the same trick needs its own rule. Each would need its own
# probe set; neither is what the judge found.
_DESPACE_MIN = 5
_SEP_CHARS = ".-_/*·‧•∙"
_SEPS = frozenset(" " + _SEP_CHARS)
_DESPACE_SEP = rf"[\x20{re.escape(_SEP_CHARS)}]"
_SPACED_RUN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z](?:%s+[A-Za-z]){%d,}(?![A-Za-z0-9])"
                         % (_DESPACE_SEP, _DESPACE_MIN - 1))


def _despace_drops(chars: list[str], lexicon: frozenset[str]) -> set[int]:
    """Indices in `chars` of the separator characters that close up a separated lexicon word. See the rule above."""
    if not lexicon:
        return set()
    s = "".join(chars)
    longest = max(len(w) for w in lexicon)
    drops: set[int] = set()
    for run in _SPACED_RUN.finditer(s):
        at = [i for i in range(run.start(), run.end()) if s[i] not in _SEPS]   # index of each letter in the run
        letters = "".join(s[i] for i in at).lower()
        k = 0
        while k < len(letters):
            for n in range(min(longest, len(letters) - k), _DESPACE_MIN - 1, -1):
                if letters[k:k + n] in lexicon:
                    drops.update(i for i in range(at[k], at[k + n - 1]) if s[i] in _SEPS)
                    k += n
                    break
            else:
                k += 1
    return drops


@dataclass
class Normalised:
    """A normalised copy of a message plus the map that takes any slice of it back to the original."""
    original: str
    text: str
    origin: tuple[int, ...]      # origin[i] = index in `original` of the character that produced text[i]

    def map_span(self, start: int, end: int) -> tuple[int, int]:
        """Normalised [start:end) -> original [start:end). The original slice may be wider than the normalised
        one (it still holds the zero-width characters that were dropped inside it), which is exactly what we
        want to quote and highlight: the officer sees the characters that are really in the message."""
        n = len(self.origin)
        if n == 0:
            return 0, 0
        s = self.origin[start] if start < n else len(self.original)
        if end <= start:
            return s, s
        e = self.origin[min(end, n) - 1] + 1
        return s, max(s, e)

    def quote(self, start: int, end: int) -> str:
        s, e = self.map_span(start, end)
        return self.original[s:e]


def normalise(text: str, lexicon: frozenset[str] = frozenset()) -> Normalised:
    """Fold `text` for matching. `lexicon` enables step 6 (intra-word spacing) and nothing else; with the default
    empty lexicon no spacing is closed up, because the words it is safe to close up belong to the caller."""
    out: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if ch in _DROP:
            continue
        if ch in _SPACES:
            rep = " "
        elif ch in _CONFUSABLE:
            rep = _CONFUSABLE[ch]
        elif ch in "\n\t":
            rep = ch
        else:
            rep = unicodedata.normalize("NFKC", ch)
            if not rep:                      # NFKC can empty a formatting character
                continue
        for c in rep:
            out.append(c)
            origin.append(i)
    _deleet(out)
    drops = _despace_drops(out, lexicon)
    if drops:
        # Deleting a character keeps the map exact: every surviving character still carries the index of the
        # original character that produced it, so a span mapped back from normalised coordinates still quotes
        # the original run verbatim, spaces and all.
        out = [c for i, c in enumerate(out) if i not in drops]
        origin = [o for i, o in enumerate(origin) if i not in drops]
    return Normalised(original=text, text="".join(out), origin=tuple(origin))


def fold(text: str, lexicon: frozenset[str] = frozenset()) -> str:
    """The folded string on its own, for tests and probes."""
    return normalise(text, lexicon).text
