"""Check that a quote Claude gives back really appears in the syllabus.

Both sides are normalized the same way before comparing, so differences that don't change the
words don't count: line breaks and spacing, curly vs straight quotes, hyphens and dashes
(including a word hyphenated across a line break), invisible characters, and letter case.
"""

from __future__ import annotations

import re
import unicodedata

MIN_MATCH_CHARS = 6

_QUOTES = str.maketrans(
    {
        "‘": "'",  # left single quotation mark
        "’": "'",  # right single quotation mark
        "‚": "'",  # single low-9 quotation mark
        "‛": "'",  # single high-reversed-9 quotation mark
        "′": "'",  # prime
        "`": "'",
        "´": "'",  # acute accent
        "“": '"',  # left double quotation mark
        "”": '"',  # right double quotation mark
        "„": '"',  # double low-9 quotation mark
        "‟": '"',  # double high-reversed-9 quotation mark
        "″": '"',  # double prime
    }
)

# Hyphen-minus, hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar,
# minus sign, small em dash, small hyphen-minus, fullwidth hyphen-minus.
DASH_CHARS = "-‐‑‒–—―−﹘﹣－"

_WHITESPACE_AND_DASHES = re.compile(f"[\\s{re.escape(DASH_CHARS)}]+")


def normalize_for_match(text: str) -> str:
    """The form both the quote and the syllabus are compared in.

    Quotes are unified before NFKC as well as after it, because NFKC rewrites two of them
    (the acute accent becomes a space plus a combining accent, the double prime becomes two
    primes) and the mapping would otherwise never see them.
    """
    text = text.translate(_QUOTES)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero-width, soft hyphen
    text = text.translate(_QUOTES)
    text = _WHITESPACE_AND_DASHES.sub("", text)
    return text.casefold()


class SourceMatcher:
    """Normalizes the syllabus once, then checks any number of quotes against it."""

    def __init__(self, document_text: str) -> None:
        self._document = normalize_for_match(document_text or "")

    def contains(self, quote: str | None) -> bool:
        """True when the quote appears in the syllabus. Very short quotes never count."""
        if not quote:
            return False
        needle = normalize_for_match(quote)
        if len(needle) < MIN_MATCH_CHARS:
            return False
        return needle in self._document


def source_appears_in(document_text: str, quote: str | None) -> bool:
    """One-off version of ``SourceMatcher(document_text).contains(quote)``."""
    return SourceMatcher(document_text).contains(quote)


def phrase_in(container: str, phrase: str | None) -> bool:
    """True when ``phrase`` appears inside ``container``. Any length counts, but not an empty phrase."""
    if not phrase:
        return False
    needle = normalize_for_match(phrase)
    if not needle:
        return False
    return needle in normalize_for_match(container or "")
