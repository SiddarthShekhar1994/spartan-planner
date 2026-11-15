"""Read the day out of a short date phrase, such as "Wed, Oct 14", "10/14" or "Dec 7–11".

postprocess.py uses this to double-check Claude: a due date is kept only when the date phrase
Claude quoted, and the date words right around it in the quote, name that one day and nothing
else. Every check here can only take a date away, never add one, so when a phrase is unclear
the student picks the day (never guess a date).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from backend.services.source_check import DASH_CHARS

_DASH = f"[{re.escape(DASH_CHARS)}]"
_ORDINAL = r"(?:st|nd|rd|th)?"
_MONTH_WORDS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
    )
}
_WEEKDAY_WORDS = (
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:s|nesday)?|thu(?:r(?:s(?:day)?)?)?"
    r"|fri(?:day)?|sat(?:urday)?|sun(?:day)?"
)
_WEEKDAY_NUMBERS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# --- Times of day ("9:45", "11:59 PM", "9am", "9:45–12:00") -----------------------------------
_MERIDIEM = r"[ap]\.?\s?m\b\.?"
_CLOCK = rf"\d{{1,2}}:\d{{2}}(?::\d{{2}})?(?:\s*{_MERIDIEM})?"
_HOUR_MERIDIEM = rf"\d{{1,2}}\s*{_MERIDIEM}"
_TIME = rf"(?:{_CLOCK}|{_HOUR_MERIDIEM})"
_TIME_JOIN = rf"\s*(?:{_DASH}|\b(?:to|until|till|through|thru)\b)\s*"

_TIME_RANGE = re.compile(rf"(?<![\d:]){_TIME}{_TIME_JOIN}{_TIME}(?![\d:])", re.IGNORECASE)
# "9–11am" or "9-10:15 AM": a bare hour, then a time.
_OPEN_START_RANGE = re.compile(
    rf"(?<![\d:])\d{{1,2}}{_TIME_JOIN}(?P<time>{_TIME})(?![\d:])", re.IGNORECASE
)
# "9:45–12": a time, then a bare hour.
_OPEN_END_RANGE = re.compile(rf"(?<![\d:]){_TIME}{_TIME_JOIN}\d{{1,2}}(?![\d:])", re.IGNORECASE)
_SINGLE_TIME = re.compile(rf"(?<![\d:]){_TIME}(?![\d:])", re.IGNORECASE)
# Text just before a bare number that makes the number a day: "Oct 14 – 9:45", "10/14 – 9:45".
_DAY_CONTEXT_BEFORE = re.compile(
    rf"(?:(?<![a-z])(?:{_MONTH_WORDS})(?![a-z])\.?\s*|\d\s*[/{re.escape(DASH_CHARS)}]\s*)$", re.IGNORECASE
)

# --- Calendar days ----------------------------------------------------------------------------
_ISO_DATE = re.compile(r"(?<![\d-])(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?![\d-])")
# "10-14-2026" or "10-14-26". The year is required, so a bare "10-14" stays unclear.
_DASHED_DATE = re.compile(
    rf"(?<![\d{re.escape(DASH_CHARS)}])(?P<month>\d{{1,2}}){_DASH}(?P<day>\d{{1,2}}){_DASH}"
    rf"(?P<year>\d{{4}}|\d{{2}})(?![\d{re.escape(DASH_CHARS)}])"
)
_NUMERIC_DATE = re.compile(
    r"(?<![\d/])(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{4}|\d{2}))?(?![\d/])"
)
_MONTH_DAY = re.compile(
    rf"(?<![a-z])(?P<month>{_MONTH_WORDS})(?![a-z])\.?\s*(?P<day>\d{{1,2}}){_ORDINAL}(?!\d)", re.IGNORECASE
)
# "14 October", "14th of October", and Excel's "14-Oct" or "14-Oct-2026".
_DAY_MONTH = re.compile(
    rf"(?<![\d/:])(?P<day>\d{{1,2}}){_ORDINAL}(?:\s+(?:of\s+)?|\s*{_DASH}\s*)(?P<month>{_MONTH_WORDS})(?![a-z])\.?"
    rf"(?:{_DASH}(?P<year>\d{{4}}|\d{{2}})(?!\d))?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_WEEKDAY = re.compile(rf"(?<![a-z])(?P<day>{_WEEKDAY_WORDS})(?![a-z])\.?", re.IGNORECASE)

# --- Phrases that cover more than one day -----------------------------------------------------
# Run on the phrase after each recognized date is masked, so "2026-10-14" is not a range.
_RANGE_JOIN = re.compile(
    rf"\d{_ORDINAL}\s*[,(]?\s*(?:{_DASH}|&|\+|\b(?:to|through|thru|until|and)\b)\s*(?:the\s+)?\d", re.IGNORECASE
)
# Two possible days: "Oct 14 or 16", "Oct 14/16" (sections), "Oct 14 till 16", "Oct 14 (or 16 ...)".
_ALTERNATIVE_DAYS = re.compile(rf"\d{_ORDINAL}\s*[,(]?\s*(?:/|\b(?:or|till)\b)\s*(?:the\s+)?\d", re.IGNORECASE)
# A list of days: "Oct 14, 16" or "Sept 8, 10". A year ("Oct 14, 2026") has four digits, and times
# of day are removed first, so "Oct 14, 9:45 AM" and "Oct 14, 5pm" are still one day.
_DAY_LIST = re.compile(rf"\d{_ORDINAL}\s*,\s*(?:the\s+)?\d{{1,2}}{_ORDINAL}(?![\d:])", re.IGNORECASE)
# Vague by the prompt's own definition: "the week of Nov 9", "every Friday starting Oct 2".
_VAGUE_WORDS = re.compile(r"\bweek\s+of\b|\bevery\b", re.IGNORECASE)

# --- The whole date expression around a date phrase in its quote ------------------------------
# Claude's date_text can leave out words that change the answer: "Thursday, October 14" cut to
# "October 14", "Dec 7–11" cut to "Dec 7", "the week of Nov 9" cut to "Nov 9". date_phrase_span
# finds the phrase in the quote and widens it over the date words right next to it.
_SPAN_JOIN = rf"(?:[,/&+(]|{_DASH}|\b(?:to|through|thru|until|till|and|or)\b)"
# A month or weekday name, or a number that isn't a time of day ("9:45", "2 pm").
_SPAN_TOKEN = (
    rf"(?:(?:{_MONTH_WORDS}|{_WEEKDAY_WORDS})(?![a-z])\.?"
    rf"|\d{{1,4}}{_ORDINAL}(?![\d:])(?!\s*{_MERIDIEM}))"
)
_SPAN_RIGHT = re.compile(rf"(?:(?:\s*{_SPAN_JOIN})*\s*(?:the\s+)?{_SPAN_TOKEN})+", re.IGNORECASE)
# To the left, only words that change what the date means: "the week of", "every", a weekday, or
# the start of a range such as "Dec 7 –" or "10/12 –". Never a bare number, so "HW 3 – Oct 14"
# stays "Oct 14".
_SPAN_LEFT = re.compile(
    rf"(?:(?:\b(?:the\s+)?week\s+of|\bevery|\b(?:{_WEEKDAY_WORDS})(?![a-z])\.?(?:\s*{_SPAN_JOIN})*"
    rf"|\b(?:{_MONTH_WORDS})(?![a-z])\.?\s*\d{{1,2}}{_ORDINAL}(?:\s*{_SPAN_JOIN})+"
    rf"|(?<![\d/])\d{{1,2}}/\d{{1,2}}(?:/(?:\d{{4}}|\d{{2}}))?(?:\s*{_SPAN_JOIN})+)\s*)+$",
    re.IGNORECASE,
)
_SPAN_LOOKBACK_CHARS = 80
_PHRASE_PARTS = re.compile(r"[^\W\d_]+|\d+|[^\w\s]|_")  # letter runs, digit runs, single marks

_STRICT_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_iso_date(value: str | None) -> date | None:
    """A real calendar day written exactly as YYYY-MM-DD, else None."""
    if not isinstance(value, str) or not _STRICT_ISO.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:  # e.g. 2026-11-31
        return None


def _keep_day_drop_time(match: re.Match[str]) -> str:
    before = match.string[: match.start()]
    if _DAY_CONTEXT_BEFORE.search(before):
        # The bare number is a day ("Oct 14 – 9:45"), so only the time goes.
        return match.group(0)[: match.start("time") - match.start()] + " "
    return " "


def strip_times(text: str) -> str:
    """The phrase without times of day such as "9:45", "11:59 PM", "9am" or "9:45–12:00"."""
    text = _TIME_RANGE.sub(" ", text)
    text = _OPEN_START_RANGE.sub(_keep_day_drop_time, text)
    text = _OPEN_END_RANGE.sub(" ", text)
    text = _SINGLE_TIME.sub(" ", text)
    return " ".join(text.split())


def _prepare(date_text: str | None) -> str:
    return strip_times(unicodedata.normalize("NFKC", date_text or ""))


def _full_year(digits: str | None) -> int | None:
    if digits is None:
        return None
    return int(digits) if len(digits) == 4 else 2000 + int(digits)


@dataclass(frozen=True)
class _Scan:
    pairs: tuple[tuple[int, int], ...]  # (month, day) in reading order
    years: frozenset[int]
    rest: str  # the phrase with each recognized date blanked out, keeping a "0" where it ended


def _scan(date_text: str | None) -> _Scan:
    text = _prepare(date_text)
    found: list[tuple[int, tuple[int, int]]] = []
    years: set[int] = set()

    def record(match: re.Match[str], month: int, day: int, year: int | None = None) -> str:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        found.append((match.start(), (month, day)))
        if year is not None:
            years.add(year)
        # Same length as the match, so positions found by later passes still line up.
        return " " * (match.end() - match.start() - 1) + "0"

    text = _ISO_DATE.sub(lambda m: record(m, int(m["month"]), int(m["day"]), int(m["year"])), text)
    text = _DASHED_DATE.sub(lambda m: record(m, int(m["month"]), int(m["day"]), _full_year(m["year"])), text)
    text = _NUMERIC_DATE.sub(lambda m: record(m, int(m["month"]), int(m["day"]), _full_year(m["year"])), text)
    text = _MONTH_DAY.sub(lambda m: record(m, _MONTH_NUMBERS[m["month"][:3].lower()], int(m["day"])), text)
    text = _DAY_MONTH.sub(
        lambda m: record(m, _MONTH_NUMBERS[m["month"][:3].lower()], int(m["day"]), _full_year(m["year"])), text
    )
    years.update(int(year) for year in _YEAR.findall(text))
    found.sort(key=lambda entry: entry[0])
    return _Scan(pairs=tuple(pair for _, pair in found), years=frozenset(years), rest=text)


def _covers_several_days(scan: _Scan) -> bool:
    return bool(_RANGE_JOIN.search(scan.rest) or _DAY_LIST.search(scan.rest)) or len(set(scan.pairs)) >= 2


def is_range(date_text: str) -> bool:
    """True for phrases covering more than one day: "Dec 7–11", "Dec 7 to 11", "Oct 14 and Oct 16", "Oct 14, 16".

    Times are removed first, so "9:45–12:00" is not a range, and neither is "2026-10-14".
    """
    return _covers_several_days(_scan(date_text))


def find_month_days(date_text: str) -> list[tuple[int, int]]:
    """Every (month, day) the phrase names, in reading order.

    Reads "Oct 14", "Sept. 14", "October 14th", "14 October", "14th of October", "14-Oct",
    "10/14", "10/14/2026", "10-14-2026" and "2026-10-14". Times of day are ignored.
    """
    return list(_scan(date_text).pairs)


def find_weekdays(date_text: str) -> list[int]:
    """Weekdays named in the phrase, Monday=0 to Sunday=6, in reading order."""
    return [_WEEKDAY_NUMBERS[m["day"][:3].lower()] for m in _WEEKDAY.finditer(_prepare(date_text))]


def date_supported_by_text(due: date, date_text: str) -> bool:
    """True when the phrase names exactly the day ``due`` and nothing that contradicts it."""
    if not date_text:
        return False
    scan = _scan(date_text)
    if _covers_several_days(scan):
        return False
    if set(scan.pairs) != {(due.month, due.day)}:
        return False
    weekdays = set(find_weekdays(date_text))
    if weekdays and weekdays != {due.weekday()}:
        return False
    # Stricter than a plain day match: a stated year must agree, and phrases that name a second
    # possible day or a vague span ("the week of Nov 9") don't pin down one day.
    if scan.years and scan.years != {due.year}:
        return False
    if _ALTERNATIVE_DAYS.search(scan.rest) or _VAGUE_WORDS.search(scan.rest):
        return False
    return True


def _without_format_characters(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero-width, soft hyphen


def date_phrase_span(source_text: str, date_text: str | None) -> str | None:
    """The whole date expression around ``date_text`` in ``source_text``, or None when it isn't there.

    The phrase must appear as whole words, so "Oct 1" is not found inside "Oct 14". Spacing, letter
    case and the kind of dash don't matter. The span then takes in the date words right next to the
    phrase: "October 14" in "Thursday, October 14." gives "Thursday, October 14", and "Dec 7" in
    "Dec 7–11; sign up" gives "Dec 7–11".
    """
    source = _without_format_characters(source_text or "")
    parts = _PHRASE_PARTS.findall(_without_format_characters(date_text or ""))
    if not parts:
        return None
    pieces = []
    for part in parts:
        if part in DASH_CHARS:
            pieces.append(_DASH)
        elif part.isdigit():
            pieces.append(re.escape(part) + _ORDINAL)  # "Oct 14" still finds "Oct 14th"
        else:
            pieces.append(re.escape(part))
    pattern = r"\s*".join(pieces)
    if parts[0][0].isalnum():
        pattern = r"(?<![^\W_])" + pattern
    if parts[-1][-1].isalnum():
        pattern += r"(?![^\W_])"
    match = re.search(pattern, source, re.IGNORECASE)
    if match is None:
        return None
    left = _SPAN_LEFT.search(source, max(0, match.start() - _SPAN_LOOKBACK_CHARS), match.start())
    right = _SPAN_RIGHT.match(source, match.end())
    return (left.group(0) if left else "") + match.group(0) + (right.group(0) if right else "")
