"""backend/services/dates.py: strict date parsing and "does the date phrase really say that day?".

Privacy rule 8 (never guess a date) rests on these checks: a due date survives only when the
quoted date phrase names exactly that one day.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

MONTHS = [
    ("january", "jan", 1),
    ("february", "feb", 2),
    ("march", "mar", 3),
    ("april", "apr", 4),
    ("may", "may", 5),
    ("june", "jun", 6),
    ("july", "jul", 7),
    ("august", "aug", 8),
    ("september", "sep", 9),
    ("october", "oct", 10),
    ("november", "nov", 11),
    ("december", "dec", 12),
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def digits(text: str) -> list[str]:
    return re.findall(r"\d+", text)


# ---------------------------------------------------------------------------
# parse_iso_date
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-14", date(2026, 10, 14)),
        ("2026-01-01", date(2026, 1, 1)),
        ("2026-12-31", date(2026, 12, 31)),
        ("2028-02-29", date(2028, 2, 29)),  # leap year
    ],
)
def test_parse_iso_date_accepts_real_days(dates, value, expected):
    assert dates.parse_iso_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-31",  # November has 30 days
        "2026-02-29",  # 2026 is not a leap year
        "2026-02-30",
        "2026-13-01",
        "2026-00-10",
        "2026-10-00",
        "2026-10-32",
        "0000-01-01",
    ],
)
def test_parse_iso_date_rejects_impossible_days(dates, value):
    assert dates.parse_iso_date(value) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-1-5",
        "2026/10/14",
        "10/14/2026",
        "Oct 14, 2026",
        "20261014",  # date.fromisoformat accepts this; the contract's strict format does not
        "2026-W42-3",  # ISO week date, also accepted by date.fromisoformat
        "2026-10-14T00:00:00",
        "2026-10-14 ",
        " 2026-10-14",
        "2026-10-14\n",
        "TBA",
    ],
    ids=repr,
)
def test_parse_iso_date_is_strict_about_the_format(dates, value):
    assert dates.parse_iso_date(value) is None


# ---------------------------------------------------------------------------
# strip_times
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "kept_digits"),
    [
        ("Friday, October 2 by 11:59 PM", ["2"]),
        ("due 11:59pm", []),
        ("Monday, December 14, 9:45–12:00", ["14"]),
        ("Monday, December 14, 9:45-12:00", ["14"]),
        ("Office hours 1:00–2:30 PM", []),
        ("Quiz at 9am on Oct 14", ["14"]),
        ("Quiz at 11pm on Oct 14", ["14"]),
        ("Lab at 14:30, Oct 14", ["14"]),
        ("9:45 AM–12:00 PM", []),
    ],
)
def test_strip_times_removes_clock_times(dates, text, kept_digits):
    stripped = dates.strip_times(text)
    assert digits(stripped) == kept_digits
    assert not re.search(r"\b[ap]\.?m\b", stripped, flags=re.IGNORECASE)


@pytest.mark.parametrize(
    "text",
    ["Wednesday, October 14", "Dec 7–11", "10/14/2026", "2026-10-14", "14th of October", "Week 12"],
)
def test_strip_times_leaves_text_without_times_alone(dates, text):
    assert dates.strip_times(text) == text


# ---------------------------------------------------------------------------
# is_range
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Dec 7–11",  # en dash
        "Dec 7-11",
        "Dec 7—11",  # em dash
        "Dec 7 – 11",
        "December 7 to 11",
        "Dec 7 through Dec 11",
        "Dec 7 thru 11",
        "Dec 7 until Dec 11",
        "Dec 7 and 8",
        "Dec 7 & 8",
        "Oct 14 or Oct 21",  # two different days
        "Monday, Oct 12 – Friday, Oct 16",
        "10/14-10/16",
        "2026-10-14 to 2026-10-16",
        # a list of days, or a join after a comma or with "+"
        "Oct 14, 16",
        "Oct 14, 15, 16",
        "Oct 14 + 16",
        "Oct 14, and 16",
        "Sept 8, 10",
        # Excel-style day-month dates are still read as ranges
        "19-23 Oct",
        "Oct 19-23",
        "10-14",  # no year: month 10, day 14, or the 10th to the 14th
    ],
)
def test_is_range_spots_ranges(dates, text):
    assert dates.is_range(text)


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-14",  # a bare ISO date is one day, not "6-1"
        "Due 2026-10-14",
        "Oct 14",
        "Wednesday, October 14",
        "10/14",
        "10/14/2026",
        "Monday, December 14, 9:45–12:00",  # a time range is not a date range
        "Friday, October 2 by 11:59 PM",
        "Oct 14, 9am-11am",
        "Oct 14 (Wednesday, October 14)",  # the same day twice is still one day
        "TBA",
        "Oct 14, 2026",  # a year after the comma, not a second day
        "Oct 14, 9:45 AM",
        "Oct 14, 5pm",
        "19-Oct",
        "19-Oct-2026",
        "10-14-2026",
    ],
)
def test_is_range_leaves_single_days_alone(dates, text):
    assert not dates.is_range(text)


# ---------------------------------------------------------------------------
# find_month_days
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Oct 14",
        "Oct. 14",
        "October 14",
        "october 14",
        "OCTOBER 14",
        "October 14th",
        "14 October",
        "14th of October",
        "Wed, Oct 14",
        "Wednesday, October 14",
        "October 14, 2026",
        "10/14",
        "10/14/2026",
        "2026-10-14",
        "October 14 by 11:59 PM",
        "14-Oct",  # Excel's default d-mmm format
        "Wed 14-Oct",
        "14-Oct-2026",
        "14-Oct-26",
        "14–Oct",
        "10-14-2026",
        "10-14-26",
    ],
)
def test_find_month_days_reads_one_date_in_many_forms(dates, text):
    # Compared as a set: a harmless duplicate of the same day is fine (callers use set()).
    assert set(dates.find_month_days(text)) == {(10, 14)}


@pytest.mark.parametrize("text", ["Oct-19", "Oct-26"], ids=repr)
def test_find_month_days_does_not_read_month_dash_number(dates, text):
    # Excel's mmm-yy format: "Oct-26" is October 2026, with no day.
    assert dates.find_month_days(text) == []


@pytest.mark.parametrize(("full", "short", "month"), MONTHS, ids=[m[0] for m in MONTHS])
def test_find_month_days_knows_every_month(dates, full, short, month):
    assert set(dates.find_month_days(f"{full.title()} 3")) == {(month, 3)}
    assert set(dates.find_month_days(f"{short.title()} 3")) == {(month, 3)}
    assert set(dates.find_month_days(f"{short.title()}. 3")) == {(month, 3)}


@pytest.mark.parametrize("text", ["Sept 21", "Sept. 21", "Sep 21"])
def test_find_month_days_reads_sept(dates, text):
    assert set(dates.find_month_days(text)) == {(9, 21)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("October 1st", (10, 1)), ("October 2nd", (10, 2)), ("October 3rd", (10, 3)), ("October 21st", (10, 21)), ("22nd of May", (5, 22))],
)
def test_find_month_days_reads_ordinals(dates, text, expected):
    assert set(dates.find_month_days(text)) == {expected}


def test_find_month_days_finds_several_dates(dates):
    assert set(dates.find_month_days("Dec 7 and Dec 11")) == {(12, 7), (12, 11)}
    assert set(dates.find_month_days("10/14 or 10/21")) == {(10, 14), (10, 21)}


@pytest.mark.parametrize("text", ["13/14", "10/32", "Oct 32", "0/14", "14/10"], ids=repr)
def test_find_month_days_ignores_out_of_range_numbers(dates, text):
    assert dates.find_month_days(text) == []


@pytest.mark.parametrize("text", ["TBA", "last week of class", "every Friday", "Week 12", "finals week", ""], ids=repr)
def test_find_month_days_finds_nothing_in_vague_phrases(dates, text):
    assert dates.find_month_days(text) == []


# ---------------------------------------------------------------------------
# find_weekdays
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("index", "name"), list(enumerate(WEEKDAYS)), ids=WEEKDAYS)
def test_find_weekdays_reads_full_names(dates, index, name):
    assert dates.find_weekdays(name.title()) == [index]
    assert dates.find_weekdays(name) == [index]


@pytest.mark.parametrize(
    ("abbreviation", "index"),
    [("Mon", 0), ("Tue", 1), ("Tues", 1), ("Wed", 2), ("Thu", 3), ("Thur", 3), ("Thurs", 3), ("Fri", 4), ("Sat", 5), ("Sun", 6)],
)
def test_find_weekdays_reads_abbreviations(dates, abbreviation, index):
    assert dates.find_weekdays(f"{abbreviation}, Oct 14") == [index]


def test_find_weekdays_finds_several(dates):
    assert dates.find_weekdays("Monday or Wednesday") == [0, 2]


@pytest.mark.parametrize("text", ["Oct 14", "10/14", "Satisfy", "Wedding", "monthly", "Friend", ""], ids=repr)
def test_find_weekdays_ignores_text_without_a_weekday(dates, text):
    assert dates.find_weekdays(text) == []


# ---------------------------------------------------------------------------
# date_supported_by_text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("due", "text"),
    [
        (date(2026, 10, 14), "Wednesday, October 14"),
        (date(2026, 10, 14), "Oct 14"),
        (date(2026, 10, 14), "Wed, Oct 14"),
        (date(2026, 10, 14), "Wed 10/14"),
        (date(2026, 10, 14), "10/14/2026"),
        (date(2026, 10, 14), "2026-10-14"),
        (date(2026, 10, 14), "14th of October"),
        (date(2026, 10, 14), "Oct 14 (Wednesday, October 14)"),
        (date(2026, 10, 14), "Wednesday (Wed), Oct 14"),
        (date(2026, 9, 10), "Thursday, September 10"),
        (date(2026, 10, 2), "Friday, October 2 by 11:59 PM"),
        (date(2026, 12, 14), "Monday, December 14, 9:45–12:00"),
        (date(2026, 10, 19), "Oct 19"),
        (date(2026, 10, 14), "Oct 14, 2026"),
        (date(2026, 10, 14), "Oct 14, 9:45 AM"),
        (date(2026, 10, 14), "Oct 14, 5pm"),
        (date(2026, 10, 19), "19-Oct"),
        (date(2026, 10, 19), "Mon 19-Oct"),
        (date(2026, 10, 19), "19-Oct-2026"),
        (date(2026, 10, 19), "19-Oct-26"),
        (date(2026, 10, 14), "10-14-2026"),
        (date(2026, 10, 14), "10-14-26"),
    ],
)
def test_date_supported_when_the_phrase_names_exactly_that_day(dates, due, text):
    assert dates.date_supported_by_text(due, text)


@pytest.mark.parametrize(
    ("due", "text"),
    [
        (date(2026, 10, 14), "Thursday, October 14"),  # Oct 14, 2026 is a Wednesday
        (date(2026, 10, 14), "Thu 2026-10-14"),
        (date(2026, 10, 14), "Wed or Thu, Oct 14"),  # two different weekdays
        (date(2026, 10, 15), "Oct 14"),
        (date(2026, 9, 22), "Monday, September 21"),
        (date(2026, 12, 7), "Dec 7–11"),  # a range
        (date(2026, 12, 7), "Dec 7 through Dec 11"),
        (date(2026, 10, 14), "Oct 14 or Oct 21"),
        (date(2026, 10, 14), "Wednesday"),  # no month and day at all
        (date(2026, 10, 14), "TBA"),
        (date(2026, 10, 14), ""),
        # a year that disagrees, two possible days, or a vague span (approved Nov 15)
        (date(2026, 10, 14), "10/14/2025"),
        (date(2026, 10, 14), "Oct 14 or 16"),
        (date(2026, 10, 14), "Oct 14/16"),
        (date(2026, 11, 9), "the week of Nov 9"),
        (date(2026, 10, 2), "every Friday starting Oct 2"),
        # several days after a comma, a "+", or an "or" behind a comma or parenthesis
        (date(2026, 10, 14), "Oct 14, 16"),
        (date(2026, 10, 14), "Oct 14, 15, 16"),
        (date(2026, 10, 14), "Oct 14 + 16"),
        (date(2026, 10, 14), "Oct 14, or 16"),
        (date(2026, 10, 14), "Oct 14 (or 16 for Section 2)"),
        (date(2026, 9, 8), "Sept 8, 10"),
        (date(2026, 10, 13), "October 13, 15, and 20"),
        (date(2026, 12, 7), "Dec 7, 9, or 11"),
        # Excel and dashed dates
        (date(2026, 10, 19), "19-Oct-2025"),  # the year disagrees
        (date(2026, 10, 19), "Tue 19-Oct"),  # Oct 19, 2026 is a Monday
        (date(2026, 10, 19), "Oct-19"),  # Excel's mmm-yy, not a day
        (date(2026, 10, 19), "19-23 Oct"),
        (date(2026, 10, 19), "Oct 19-23"),
        (date(2026, 10, 14), "10-14-2025"),
        (date(2026, 10, 14), "10-14"),  # no year, so it could be a range
    ],
)
def test_date_not_supported_otherwise(dates, due, text):
    assert not dates.date_supported_by_text(due, text)


# ---------------------------------------------------------------------------
# date_phrase_span
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("source_text", "date_text", "span"),
    [
        ("Quiz 3 is on Thursday, October 14.", "October 14", "Thursday, October 14"),
        ("Project check-in meetings will be held Dec 7–11; sign up for a slot.", "Dec 7", "Dec 7–11"),
        ("Lab 4 is due the week of Nov 9.", "Nov 9", "the week of Nov 9"),
        ("Essay draft due Oct 14 or 16 (check Canvas).", "Oct 14", "Oct 14 or 16"),
        ("Essay draft due Oct 14 (or 16 for Section 2).", "Oct 14", "Oct 14 (or 16"),
        ("Homework 2 is due 10/14/2025 by 11:59 PM.", "10/14", "10/14/2025"),
        ("Presentations run Oct 12 – Oct 16.", "Oct 16", "Oct 12 – Oct 16"),
        ("Presentations run 10/12 – 10/16.", "10/16", "10/12 – 10/16"),
        ("Midterm Oct 14 (Thursday)", "Oct 14", "Oct 14 (Thursday"),
        ("Midterm is Oct 14, 2026.", "Oct 14", "Oct 14, 2026"),
        ("Quiz on Oct 14th", "Oct 14", "Oct 14th"),
        ("Held Dec 7–11.", "dec 7-11", "Dec 7–11"),  # letter case and the kind of dash don't matter
        # never a bare number on the left, and never a time of day on the right
        ("HW 3 – Oct 14", "Oct 14", "Oct 14"),
        ("Quiz 2, Oct 14", "Oct 14", "Oct 14"),
        ("Midterm Oct 14, 9:45–11:00", "Oct 14", "Oct 14"),
        ("Midterm: Oct 14, 2 pm", "Oct 14", "Oct 14"),
        ("Week 9 | Oct 19 | Homework 4 due", "Oct 19", "Oct 19"),
        ("The final exam is Monday, December 14, 9:45–12:00, in our usual room.", "December 14", "Monday, December 14"),
    ],
)
def test_date_phrase_span_takes_in_the_date_words_around_the_phrase(dates, source_text, date_text, span):
    assert dates.date_phrase_span(source_text, date_text) == span


@pytest.mark.parametrize(
    ("source_text", "date_text"),
    [
        ("The midterm exam is on Oct 14 in class.", "Oct 1"),  # only part of "14"
        ("The midterm exam is on Oct 14 in class.", "Oct 15"),
        ("The midterm exam is on Oct 14 in class.", "ct 14"),
        ("The midterm exam is on Oct 14 in class.", ""),
        ("The midterm exam is on Oct 14 in class.", None),
    ],
    ids=repr,
)
def test_date_phrase_span_is_none_when_the_phrase_is_not_in_the_quote(dates, source_text, date_text):
    assert dates.date_phrase_span(source_text, date_text) is None
