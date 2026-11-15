"""The stated term limits which days a due date can fall on (backend/services/terms.py)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.terms import date_in_term, term_date_ranges


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("Fall 2026", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Autumn 2026", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Spring 2027", [(date(2027, 1, 1), date(2027, 5, 31))]),
        ("Summer 2026", [(date(2026, 5, 1), date(2026, 8, 31))]),
        ("Winter 2027", [(date(2026, 12, 1), date(2027, 1, 31))]),
        ("fall semester 2026", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Summer Session 2026", [(date(2026, 5, 1), date(2026, 8, 31))]),
        ("Fall, 2026", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Fall '26", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Fall ’26", [(date(2026, 8, 1), date(2026, 12, 31))]),
        ("Section 02 · Fall 2026", [(date(2026, 8, 1), date(2026, 12, 31))]),
    ],
)
def test_term_date_ranges_reads_a_season_and_year(term, expected):
    assert term_date_ranges(term) == expected


def test_a_year_long_course_gives_one_range_per_term():
    assert term_date_ranges("Fall 2026 – Spring 2027") == [
        (date(2026, 8, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 5, 31)),
    ]


@pytest.mark.parametrize("term", [None, "", "Fall", "2026", "Semester 1", "Fall 20266", "Falls 2026", "Fall 1800"])
def test_no_season_with_a_year_means_nothing_to_check(term):
    assert term_date_ranges(term) == []


@pytest.mark.parametrize(
    ("due", "inside"),
    [
        (date(2026, 8, 1), True),
        (date(2026, 10, 14), True),
        (date(2026, 12, 31), True),
        (date(2026, 7, 31), False),
        (date(2025, 10, 14), False),
        (date(2027, 1, 1), False),
    ],
)
def test_date_in_term_checks_the_edges(due, inside):
    assert date_in_term(due, term_date_ranges("Fall 2026")) is inside


def test_date_in_term_with_several_terms():
    ranges = term_date_ranges("Fall 2026 - Spring 2027")
    assert date_in_term(date(2027, 2, 3), ranges)
    assert date_in_term(date(2026, 11, 3), ranges)
    assert not date_in_term(date(2027, 6, 1), ranges)
