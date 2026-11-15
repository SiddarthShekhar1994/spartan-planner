"""The days a syllabus's stated term can cover, so a due date in the wrong year is caught.

Claude is told to take the year from the term ("Fall 2026"), but a date phrase such as "Oct 14"
has no year of its own to check against. postprocess.py uses ``term_date_ranges`` to drop any due
date that falls outside the stated term, which sends the item to "Needs a date" (never guess a date).
Like every date check, this can only take a date away, never add one.
"""

from __future__ import annotations

import re
from datetime import date

# A season word, an optional "semester"/"session"/"term"/"quarter", then a 4-digit year or '26.
_TERM = re.compile(
    r"(?<![a-z])(?P<season>fall|autumn|spring|summer|winter)(?![a-z])"
    r"(?:\s+(?:semester|session|term|quarter))?"
    r"[\s,]*(?:(?P<year>(?:19|20)\d{2})|['’](?P<short>\d{2}))(?!\d)",
    re.IGNORECASE,
)


def term_date_ranges(term: str | None) -> list[tuple[date, date]]:
    """First and last day each stated term can cover; an empty list means "don't check".

    Fall runs August to December, Spring January to May, Summer May to August, and Winter from
    December of the year before through January. A year-long course ("Fall 2026 – Spring 2027")
    gives one range per term. A season without a year ("Fall") gives nothing to check against.
    """
    ranges: list[tuple[date, date]] = []
    for match in _TERM.finditer(term or ""):
        year = int(match.group("year")) if match.group("year") else 2000 + int(match.group("short"))
        season = match.group("season").lower()
        if season in ("fall", "autumn"):
            ranges.append((date(year, 8, 1), date(year, 12, 31)))
        elif season == "spring":
            ranges.append((date(year, 1, 1), date(year, 5, 31)))
        elif season == "summer":
            ranges.append((date(year, 5, 1), date(year, 8, 31)))
        else:  # winter
            ranges.append((date(year - 1, 12, 1), date(year, 1, 31)))
    return ranges


def date_in_term(due: date, ranges: list[tuple[date, date]]) -> bool:
    """True when ``due`` falls inside any of the term ranges."""
    return any(start <= due <= end for start, end in ranges)
