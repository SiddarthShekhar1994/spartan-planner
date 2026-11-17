"""backend/services/source_check.py: does a quote from Claude really appear in the syllabus?

Matching ignores whitespace, line breaks, dashes and hyphens, case, Unicode compatibility forms,
invisible format characters, and curly vs straight quotes. Anything else (a paraphrase, an added
word, an ellipsis) must not match.
"""

from __future__ import annotations

import pytest

MIDTERM_DOC = "Important dates\nThe midterm exam is on Wednesday,\nOctober 14, in class.\nBring a pencil."

# Single and double quote variants that must match a straight ' and ".
# (U+00B4 ACUTE and U+2033 DOUBLE PRIME are left out on purpose: NFKC, which the contract lists
# first, decomposes them before quotes are unified. See the test report.)
SINGLE_QUOTES = ["‘", "’", "‚", "‛", "′", "`"]
DOUBLE_QUOTES = ["“", "”", "„", "‟"]
DASHES = ["-", "‐", "‑", "‒", "–", "—", "―", "−", "﹘", "﹣", "－"]
FORMAT_CHARS = ["­", "​", "‌", "‍", "⁠", "﻿", "‎"]


# ---------------------------------------------------------------------------
# normalize_for_match
# ---------------------------------------------------------------------------
def test_min_match_chars_is_six(source_check):
    assert source_check.MIN_MATCH_CHARS == 6


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Quiz 1 is on Thursday, September 10.", "quiz1isonthursday,september10."),
        ("The midterm exam is on Wednesday,\nOctober 14", "themidtermexamisonwednesday,october14"),
        ("a\tb\r\nc d　e f", "abcdef"),
        ("STRASSE Straße", "strassestrasse"),
        ("ﬁnal Ｑｕｉｚ", "finalquiz"),  # ligature and fullwidth letters (NFKC)
        ("", ""),
    ],
    ids=["sentence", "line-break", "all-whitespace-kinds", "casefold", "nfkc", "empty"],
)
def test_normalize_for_match_examples(source_check, raw, expected):
    assert source_check.normalize_for_match(raw) == expected


@pytest.mark.parametrize("quote_char", SINGLE_QUOTES, ids=lambda c: f"U+{ord(c):04X}")
def test_normalize_for_match_unifies_single_quotes(source_check, quote_char):
    assert source_check.normalize_for_match(f"It{quote_char}s due") == "it'sdue"


@pytest.mark.parametrize("quote_char", DOUBLE_QUOTES, ids=lambda c: f"U+{ord(c):04X}")
def test_normalize_for_match_unifies_double_quotes(source_check, quote_char):
    assert source_check.normalize_for_match(f"{quote_char}Why Programs Fail{quote_char}") == '"whyprogramsfail"'


@pytest.mark.parametrize("dash", DASHES, ids=lambda c: f"U+{ord(c):04X}")
def test_normalize_for_match_removes_every_dash(source_check, dash):
    assert source_check.normalize_for_match(f"check{dash}in Dec 7{dash}11") == "checkindec711"


@pytest.mark.parametrize("invisible", FORMAT_CHARS, ids=lambda c: f"U+{ord(c):04X}")
def test_normalize_for_match_drops_invisible_format_characters(source_check, invisible):
    assert source_check.normalize_for_match(f"pre{invisible}sen{invisible}tation") == "presentation"


def test_normalize_for_match_keeps_other_punctuation(source_check):
    assert source_check.normalize_for_match("Week 9 | Oct 19 | 20% (final).") == "week9|oct19|20%(final)."


# ---------------------------------------------------------------------------
# SourceMatcher and source_appears_in
# ---------------------------------------------------------------------------
def test_exact_quote_matches(source_check):
    assert source_check.SourceMatcher(MIDTERM_DOC).contains("Bring a pencil.")


def test_quote_matches_across_a_line_break(source_check):
    assert source_check.SourceMatcher(MIDTERM_DOC).contains("The midterm exam is on Wednesday, October 14, in class.")


def test_quote_matches_with_extra_spaces_and_tabs(source_check):
    assert source_check.SourceMatcher(MIDTERM_DOC).contains("  The midterm exam  is on\tWednesday,  October 14,\n in class. ")


def test_straight_quotes_match_curly_quotes_in_the_document(source_check):
    document = "Essay 1, “Why Programs Fail,” is due Friday, October 2 by 11:59 PM."
    assert source_check.SourceMatcher(document).contains('Essay 1, "Why Programs Fail," is due Friday, October 2 by 11:59 PM.')


def test_curly_quotes_match_straight_quotes_in_the_document(source_check):
    document = "It's due Friday. Read 'The Pragmatic Programmer' first."
    assert source_check.SourceMatcher(document).contains("It’s due Friday. Read ‘The Pragmatic Programmer’ first.")


def test_hyphen_variants_and_missing_hyphens_match(source_check):
    document = "Project check-in meetings will be held Dec 7–11; sign up for a slot."
    matcher = source_check.SourceMatcher(document)
    assert matcher.contains("Project check‑in meetings will be held Dec 7-11; sign up for a slot.")
    assert matcher.contains("Project checkin meetings will be held Dec 711; sign up for a slot.")


def test_soft_hyphen_in_the_document_is_ignored(source_check):
    document = "Final project pre­sen­tations happen during the last week of class."
    assert source_check.SourceMatcher(document).contains("Final project presentations happen during the last week of class.")


def test_zero_width_characters_are_ignored_on_both_sides(source_check):
    document = "Lab report 3:​ due date TBA."
    matcher = source_check.SourceMatcher(document)
    assert matcher.contains("Lab report 3: due date TBA.")
    assert matcher.contains("Lab‍ report﻿ 3: due date TBA.")


def test_case_differences_match(source_check):
    assert source_check.SourceMatcher(MIDTERM_DOC).contains("THE MIDTERM EXAM IS ON WEDNESDAY, OCTOBER 14, IN CLASS.")


def test_paraphrase_does_not_match(source_check):
    matcher = source_check.SourceMatcher(MIDTERM_DOC)
    assert not matcher.contains("The midterm is on Wednesday, October 14, in class.")
    assert not matcher.contains("Midterm exam: Wednesday, October 14.")


def test_added_words_or_ellipsis_do_not_match(source_check):
    matcher = source_check.SourceMatcher(MIDTERM_DOC)
    assert not matcher.contains("The midterm exam is on Wednesday, October 14, in class, worth 20%.")
    assert not matcher.contains("The midterm exam is on … October 14, in class.")
    assert not matcher.contains("The midterm exam is on ... October 14, in class.")


@pytest.mark.parametrize("quote", [None, "", "   ", "\n\t", "​­"], ids=["none", "empty", "spaces", "newline-tab", "invisible-only"])
def test_empty_quotes_never_match(source_check, quote):
    assert not source_check.SourceMatcher(MIDTERM_DOC).contains(quote)
    assert not source_check.source_appears_in(MIDTERM_DOC, quote)


def test_quotes_shorter_than_six_normalized_characters_never_match(source_check):
    document = "Quiz 1 is on Thursday. Essay 1 is due Friday."
    matcher = source_check.SourceMatcher(document)
    assert not matcher.contains("Quiz")  # 4 characters
    assert not matcher.contains("Quiz 1")  # "quiz1": 5 characters, even though it is in the document
    assert not matcher.contains("Quiz - 1")  # dashes and spaces don't count toward the length


def test_quote_of_exactly_six_normalized_characters_can_match(source_check):
    document = "Quiz 1 is on Thursday. Essay 1 is due Friday."
    assert source_check.SourceMatcher(document).contains("Essay 1")  # "essay1": 6 characters


def test_one_matcher_checks_many_quotes(source_check, sample_syllabus_text):
    matcher = source_check.SourceMatcher(sample_syllabus_text)
    assert matcher.contains("Quiz 1 is on Thursday, September 10, at the start of class.")
    assert matcher.contains("Lab report 3: due date TBA.")
    assert not matcher.contains("Homework 6 is due Friday, November 20.")
    assert matcher.contains("Quiz 1 is on Thursday, September 10, at the start of class.")


def test_source_appears_in_agrees_with_source_matcher(source_check, sample_syllabus_text, sample_model_output):
    matcher = source_check.SourceMatcher(sample_syllabus_text)
    for item in sample_model_output.items:
        assert source_check.source_appears_in(sample_syllabus_text, item.source_text) == matcher.contains(item.source_text)


def test_fixture_quotes_are_verified_except_the_invented_one(source_check, sample_syllabus_text, sample_model_output):
    """Every quote in the fake Claude reply is in the syllabus except "Homework 6 is due Friday, November 20."."""
    results = {item.source_text: source_check.source_appears_in(sample_syllabus_text, item.source_text) for item in sample_model_output.items}
    unverified = [quote for quote, found in results.items() if not found]
    assert unverified == ["Homework 6 is due Friday, November 20."]
    # Two that only match thanks to normalization:
    assert results['Essay 1, "Why Programs Fail," is due Friday, October 2 by 11:59 PM.']  # curly quotes
    assert results["The midterm exam is on Wednesday, October 14, in class."]  # line break in the syllabus
    assert results["Final exam  25%"]  # double space


# ---------------------------------------------------------------------------
# phrase_in (used for date_text inside source_text; no minimum length)
# ---------------------------------------------------------------------------
def test_phrase_in_finds_a_date_phrase(source_check):
    assert source_check.phrase_in("Quiz 1 is on Thursday, September 10, at the start of class.", "Thursday, September 10")


def test_phrase_in_has_no_minimum_length(source_check):
    assert source_check.phrase_in("Week 9 | Oct 19 | Homework 4 due", "Oct 19")  # "oct19": 5 characters
    assert source_check.phrase_in("Due 10/14 at noon.", "10/14")


def test_phrase_in_uses_the_same_normalization(source_check):
    assert source_check.phrase_in("Project check-in meetings will be held Dec 7–11.", "Dec 7-11")
    assert source_check.phrase_in("The midterm exam is on Wednesday,\nOctober 14, in class.", "wednesday, october 14")
    assert source_check.phrase_in("Essay 1, “Why Programs Fail,” is due Friday.", '"Why Programs Fail,"')


def test_phrase_in_rejects_a_phrase_that_is_not_there(source_check):
    assert not source_check.phrase_in("The midterm exam is on Wednesday, October 14, in class.", "Thursday, October 15")
    assert not source_check.phrase_in("", "Oct 14")


@pytest.mark.parametrize("phrase", [None, "", "   ", " – "], ids=["none", "empty", "spaces", "dash-only"])
def test_phrase_in_rejects_empty_phrases(source_check, phrase):
    assert not source_check.phrase_in("The midterm exam is on Wednesday, October 14, in class.", phrase)
