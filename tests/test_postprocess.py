"""backend/services/postprocess.py: our own rules applied to Claude's items, plus the shared schemas.

``tests/fixtures/sample_expected.json`` is the acceptance test for ``clean_items``; the focused
tests below pin each rule from the contract one at a time.
"""

from __future__ import annotations

import importlib
import math
from datetime import date

import pytest
from pydantic import ValidationError

from backend.schemas import ITEM_TYPES, CleanItem, ModelItem, ModelOutput

# Indexes of the fixture's model items that survive dedupe (11 is the repeated midterm; 12, the
# grading-table final exam with no date phrase, stays as its own undated item).
KEPT_MODEL_INDEXES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]
COMPARED_FIELDS = ("title", "type", "due_date", "date_text", "weight", "date_was_ambiguous", "source_verified")

DOC = (
    "CS 101: Introduction to Programming\n"
    "The midterm exam is on Wednesday,\n"
    "October 14, in class.\n"
    "Quiz 2 is on Wednesday, October 21.\n"
    "Quiz 3 is on Wednesday, October 28.\n"
    "Quiz 4 is on Thursday, October 21.\n"
    "Project check-in meetings will be held Dec 7–11; sign up for a slot.\n"
    "Reading responses are due every Friday before class.\n"
    "Essay 2 draft is due Friday, November 6.\n"
)
MIDTERM_SOURCE = "The midterm exam is on Wednesday, October 14, in class."
UNVERIFIED_MIDTERM_SOURCE = "Midterm exam on Wednesday, October 14."
OTHER_UNVERIFIED_MIDTERM_SOURCE = "Midterm: Wednesday, October 14."


def model_item(**overrides: object) -> ModelItem:
    """A clean, fully supported item (the midterm in DOC); override fields to break one rule at a time."""
    values: dict[str, object] = {
        "title": "Midterm exam",
        "type": "exam",
        "due_date": "2026-10-14",
        "date_text": "Wednesday, October 14",
        "weight": 20,
        "source_text": MIDTERM_SOURCE,
        "date_was_ambiguous": False,
    }
    values.update(overrides)
    return ModelItem(**values)


def clean_one(postprocess, document: str = DOC, **overrides: object) -> CleanItem:
    [item] = postprocess.clean_items([model_item(**overrides)], document)
    return item


# ---------------------------------------------------------------------------
# Shared schemas and fixture files (backend/schemas.py is already written)
# ---------------------------------------------------------------------------
def test_fixture_model_output_parses(sample_model_output):
    assert sample_model_output.class_name == "CS 101: Introduction to Programming"
    assert sample_model_output.term == "Fall 2026"
    assert len(sample_model_output.items) == 14


def test_model_item_normalizes_the_type(sample_model_output):
    items = sample_model_output.items
    assert items[2].type == "exam"  # "Exam" in the fixture
    assert items[7].type == "other"  # "lab" in the fixture


@pytest.mark.parametrize(("raw", "expected"), [(" Quiz ", "quiz"), ("HOMEWORK", "homework"), ("lab", "other"), ("", "other"), ("midterm", "other")])
def test_lenient_item_type(raw, expected):
    assert model_item(type=raw).type == expected


def test_model_item_rejects_a_non_string_type():
    with pytest.raises(ValidationError):
        model_item(type=5)


def test_model_item_requires_every_field():
    with pytest.raises(ValidationError):
        ModelItem.model_validate({"title": "Quiz 1", "type": "quiz"})


def test_model_output_accepts_an_integer_weight_as_float(sample_model_output):
    weight = sample_model_output.items[1].weight
    assert weight == 10.0
    assert isinstance(weight, float)


def test_clean_item_type_is_strict():
    with pytest.raises(ValidationError):
        CleanItem(
            title="Lab", type="lab", due_date=None, date_text=None, weight=None,
            source_text="Lab", date_was_ambiguous=True, source_verified=False,
        )


def test_item_types_match_the_database_check():
    assert ITEM_TYPES == ("exam", "quiz", "project", "essay", "homework", "reading", "other")


def test_sample_expected_is_self_consistent(sample_expected):
    items = sample_expected["items"]
    counts = sample_expected["counts"]
    assert counts["item_count"] == len(items) == 13
    assert counts["dated_count"] == sum(item["due_date"] is not None for item in items)
    assert counts["needs_date_count"] == sum(item["due_date"] is None for item in items)
    assert counts["unverified_count"] == sum(not item["source_verified"] for item in items)
    assert all(item["date_was_ambiguous"] == (item["due_date"] is None) for item in items)
    assert len(KEPT_MODEL_INDEXES) == len(items)


# ---------------------------------------------------------------------------
# Acceptance: sample_model_output.json + sample_syllabus.txt -> sample_expected.json
# ---------------------------------------------------------------------------
def test_clean_items_matches_sample_expected(postprocess, sample_model_output, sample_syllabus_text, sample_expected):
    result = postprocess.clean_items(sample_model_output.items, sample_syllabus_text)
    expected_items = sample_expected["items"]
    assert [item.title for item in result] == [item["title"] for item in expected_items]
    for index, (got, want) in enumerate(zip(result, expected_items, strict=True)):
        assert isinstance(got, CleanItem)
        for name in COMPARED_FIELDS:
            assert getattr(got, name) == want[name], f"item {index} {want['title']!r}, field {name!r} ({want['why']})"
        raw_source = sample_model_output.items[KEPT_MODEL_INDEXES[index]].source_text
        assert got.source_text == " ".join(raw_source.split())


def test_clean_items_counts_match_sample_expected(postprocess, sample_model_output, sample_syllabus_text, sample_expected):
    result = postprocess.clean_items(sample_model_output.items, sample_syllabus_text)
    counts = {
        "item_count": len(result),
        "dated_count": sum(item.due_date is not None for item in result),
        "needs_date_count": sum(item.due_date is None for item in result),
        "unverified_count": sum(not item.source_verified for item in result),
    }
    assert counts == sample_expected["counts"]


def test_clean_items_never_keeps_a_date_it_cannot_back_up(postprocess, sample_model_output, sample_syllabus_text):
    for item in postprocess.clean_items(sample_model_output.items, sample_syllabus_text):
        assert item.date_was_ambiguous == (item.due_date is None)
        if item.due_date is not None:
            assert item.date_text is not None
            assert date.fromisoformat(item.due_date).isoformat() == item.due_date


def test_clean_items_does_not_change_its_input(postprocess, sample_model_output, sample_syllabus_text):
    before = [item.model_dump() for item in sample_model_output.items]
    postprocess.clean_items(sample_model_output.items, sample_syllabus_text)
    assert [item.model_dump() for item in sample_model_output.items] == before


def test_clean_items_of_nothing_is_nothing(postprocess):
    assert postprocess.clean_items([], DOC) == []


def test_a_fully_supported_item_keeps_everything(postprocess):
    item = clean_one(postprocess)
    assert item.model_dump() == {
        "title": "Midterm exam",
        "type": "exam",
        "due_date": "2026-10-14",
        "date_text": "Wednesday, October 14",
        "weight": 20.0,
        "source_text": MIDTERM_SOURCE,
        "date_was_ambiguous": False,
        "source_verified": True,
    }


# ---------------------------------------------------------------------------
# 1. title
# ---------------------------------------------------------------------------
def test_title_whitespace_is_collapsed(postprocess):
    assert clean_one(postprocess, title="  Midterm \n\t exam  ").title == "Midterm exam"


@pytest.mark.parametrize("title", ["", "   ", "\n\t"], ids=repr)
def test_empty_title_becomes_untitled_deadline(postprocess, title):
    assert clean_one(postprocess, title=title).title == "Untitled deadline"


def test_title_is_capped_at_200_characters(postprocess):
    assert clean_one(postprocess, title="A" * 250).title == "A" * 200


# ---------------------------------------------------------------------------
# 2. source_text and source_verified
# ---------------------------------------------------------------------------
def test_source_text_whitespace_is_collapsed(postprocess):
    item = clean_one(postprocess, source_text="  The midterm exam is on Wednesday,\n   October 14, in class.  ")
    assert item.source_text == MIDTERM_SOURCE
    assert item.source_verified is True


def test_quote_not_in_the_syllabus_is_kept_but_flagged(postprocess):
    item = clean_one(postprocess, source_text=UNVERIFIED_MIDTERM_SOURCE)
    assert item.source_text == UNVERIFIED_MIDTERM_SOURCE
    assert item.source_verified is False
    assert item.due_date == "2026-10-14"  # an unverified quote doesn't remove a date the quote supports


def test_long_source_text_is_capped_but_verified_in_full(postprocess):
    document = "x" * 2000 + " end."
    long_quote = "x" * 2000 + "y" * 600
    item = clean_one(postprocess, document, source_text=long_quote, date_text=None, due_date=None, date_was_ambiguous=True)
    assert item.source_text == "x" * 2000
    assert item.source_verified is False  # the first 2000 characters are in the document; the whole quote isn't


def test_long_source_text_found_in_full_is_verified(postprocess):
    long_quote = "x" * 2600
    item = clean_one(postprocess, long_quote, source_text=long_quote, date_text=None, due_date=None, date_was_ambiguous=True)
    assert len(item.source_text) == 2000
    assert item.source_verified is True


def test_empty_source_text_is_kept_unverified_and_undated(postprocess):
    item = clean_one(postprocess, source_text="")
    assert item.source_text == ""
    assert item.source_verified is False
    assert item.date_text is None
    assert item.due_date is None
    assert item.date_was_ambiguous is True


# ---------------------------------------------------------------------------
# 3. date_text
# ---------------------------------------------------------------------------
def test_date_text_whitespace_is_collapsed(postprocess):
    item = clean_one(postprocess, date_text=" Wednesday,\n October 14 ")
    assert item.date_text == "Wednesday, October 14"
    assert item.due_date == "2026-10-14"


@pytest.mark.parametrize("date_text", ["", "   "], ids=repr)
def test_empty_date_text_becomes_none(postprocess, date_text):
    item = clean_one(postprocess, date_text=date_text)
    assert item.date_text is None
    assert item.due_date is None
    assert item.date_was_ambiguous is True


def test_date_text_not_inside_the_quote_is_dropped(postprocess):
    item = clean_one(postprocess, date_text="Thursday, October 15", due_date="2026-10-15")
    assert item.date_text is None
    assert item.due_date is None
    assert item.date_was_ambiguous is True


def test_date_text_containment_ignores_dash_style(postprocess):
    item = clean_one(
        postprocess,
        title="Project check-in meeting",
        type="project",
        source_text="Project check-in meetings will be held Dec 7–11; sign up for a slot.",
        date_text="Dec 7-11",
        due_date="2026-12-07",
        weight=None,
    )
    assert item.date_text == "Dec 7-11"
    assert item.due_date is None  # still a range


def test_date_text_is_capped_at_200_characters(postprocess):
    source = "Due " + "z" * 300 + "."
    item = clean_one(postprocess, source, source_text=source, date_text="z" * 300, due_date=None, date_was_ambiguous=True)
    assert item.date_text == "z" * 200


# ---------------------------------------------------------------------------
# 4. due_date (never guess)
# ---------------------------------------------------------------------------
def test_model_flagged_ambiguous_removes_the_date(postprocess):
    item = clean_one(postprocess, date_was_ambiguous=True)
    assert item.due_date is None
    assert item.date_was_ambiguous is True
    assert item.date_text == "Wednesday, October 14"


@pytest.mark.parametrize("due_date", ["2026-10-32", "2026-11-31", "10/14/2026", "October 14", "", None], ids=repr)
def test_unusable_due_date_is_removed(postprocess, due_date):
    item = clean_one(postprocess, due_date=due_date)
    assert item.due_date is None
    assert item.date_was_ambiguous is True


def test_missing_date_text_removes_the_date(postprocess):
    item = clean_one(postprocess, date_text=None)
    assert item.due_date is None
    assert item.date_was_ambiguous is True


def test_date_that_disagrees_with_the_date_text_is_removed(postprocess):
    item = clean_one(postprocess, due_date="2026-10-15")
    assert item.due_date is None
    assert item.date_text == "Wednesday, October 14"


def test_weekday_that_contradicts_the_date_removes_it(postprocess):
    # The syllabus says "Thursday, October 21", but Oct 21, 2026 is a Wednesday. Let the student decide.
    item = clean_one(
        postprocess,
        title="Quiz 4",
        type="quiz",
        source_text="Quiz 4 is on Thursday, October 21.",
        date_text="Thursday, October 21",
        due_date="2026-10-21",
        weight=None,
    )
    assert item.due_date is None
    assert item.source_verified is True


def test_range_date_text_removes_the_date(postprocess):
    item = clean_one(
        postprocess,
        title="Project check-in meeting",
        type="project",
        source_text="Project check-in meetings will be held Dec 7–11; sign up for a slot.",
        date_text="Dec 7–11",
        due_date="2026-12-07",
        weight=None,
    )
    assert item.due_date is None
    assert item.date_was_ambiguous is True


def test_ambiguous_follows_the_final_due_date(postprocess):
    # The model left the date out but said it wasn't ambiguous: we still mark it as needing a date.
    item = clean_one(postprocess, due_date=None, date_was_ambiguous=False)
    assert item.due_date is None
    assert item.date_was_ambiguous is True


@pytest.mark.parametrize(
    ("source_text", "date_text", "due_date"),
    [
        ("Project check-in meetings will be held Dec 7–11; sign up for a slot.", "Dec 7", "2026-12-07"),
        ("Lab 4 is due the week of Nov 9.", "Nov 9", "2026-11-09"),
        ("Essay draft due Oct 14 or 16 (check Canvas).", "Oct 14", "2026-10-14"),
        ("Quiz 3 is on Thursday, October 14.", "October 14", "2026-10-14"),  # Oct 14, 2026 is a Wednesday
        ("Homework 2 is due 10/14/2025 by 11:59 PM.", "10/14", "2026-10-14"),
        ("Midterm Oct 14 (Thursday)", "Oct 14", "2026-10-14"),
        ("Midterm is Oct 14, 2025.", "Oct 14", "2026-10-14"),
        ("Essay draft due Oct 14, or 16 for Section 2.", "Oct 14", "2026-10-14"),
        ("Essay draft due Oct 14 (or 16 for Section 2).", "Oct 14", "2026-10-14"),
        ("Presentations run Oct 12 – Oct 16.", "Oct 16", "2026-10-16"),
        ("Presentations run 10/12 – 10/16.", "10/16", "2026-10-16"),
        ("Quiz 3 is Mon or Wed, Oct 14, by section.", "Oct 14", "2026-10-14"),
    ],
    ids=[
        "range-cut-short", "week-of-cut", "or-cut", "weekday-cut", "year-cut", "weekday-after", "year-after",
        "comma-or", "paren-or", "range-start-cut", "numeric-range-start-cut", "two-weekdays",
    ],
)
def test_date_words_left_out_of_date_text_still_count(postprocess, source_text, date_text, due_date):
    item = clean_one(postprocess, source_text, source_text=source_text, date_text=date_text, due_date=due_date, weight=None)
    assert item.due_date is None
    assert item.date_was_ambiguous is True
    assert item.date_text == date_text  # Claude's phrase is kept; only the date goes


def test_date_text_that_is_only_part_of_a_word_is_dropped(postprocess):
    # "Oct 1" is inside "Oct 14" letter for letter, but the quote never names Oct 1.
    source = "The midterm exam is on Oct 14 in class."
    item = clean_one(postprocess, source, source_text=source, date_text="Oct 1", due_date="2026-10-01")
    assert item.date_text is None
    assert item.due_date is None
    assert item.date_was_ambiguous is True


@pytest.mark.parametrize(
    ("source_text", "date_text", "due_date"),
    [
        ("HW 3 – Oct 14", "Oct 14", "2026-10-14"),
        ("Quiz 2, Oct 14", "Oct 14", "2026-10-14"),
        ("Midterm Oct 14, 9:45–11:00", "Oct 14", "2026-10-14"),
        ("Midterm: Oct 14, 2 pm", "Oct 14", "2026-10-14"),
        ("Week 9 | Oct 19 | Homework 4 due", "Oct 19", "2026-10-19"),
        ("The final exam is Monday, December 14, 9:45–12:00, in our usual room.", "Monday, December 14", "2026-12-14"),
        ("The final exam is Monday, December 14, 9:45–12:00, in our usual room.", "December 14", "2026-12-14"),
        ("Midterm is Oct 14, 2026.", "Oct 14", "2026-10-14"),
        ("Midterm Oct 14 (Wednesday)", "Oct 14", "2026-10-14"),
        ("Quiz on Oct 14th", "Oct 14", "2026-10-14"),
        ("Week 9 | 19-Oct | Homework 4 due", "19-Oct", "2026-10-19"),
        ("Homework 4 is due 10-14-2026.", "10-14-2026", "2026-10-14"),
    ],
)
def test_date_words_around_date_text_that_agree_keep_the_date(postprocess, source_text, date_text, due_date):
    item = clean_one(postprocess, source_text, source_text=source_text, date_text=date_text, due_date=due_date, weight=None)
    assert item.due_date == due_date
    assert item.date_text == date_text
    assert item.date_was_ambiguous is False


# ---------------------------------------------------------------------------
# 5. weight
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (20, 20.0),
        (20.0, 20.0),
        (12.3456, 12.35),
        (33.333333, 33.33),
        (0.5, 0.5),
        (100, 100.0),
        (0, None),
        (-5, None),
        (100.5, None),
        (150, None),
        (None, None),
        (math.nan, None),
        (math.inf, None),
    ],
    ids=repr,
)
def test_weight_is_kept_only_between_0_and_100(postprocess, weight, expected):
    assert clean_one(postprocess, weight=weight).weight == expected


# ---------------------------------------------------------------------------
# 6. type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("raw", "expected"), [("Quiz", "quiz"), (" ESSAY ", "essay"), ("lab", "other")])
def test_type_comes_through_normalized(postprocess, raw, expected):
    assert clean_one(postprocess, type=raw).type == expected


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
def test_exact_duplicates_keep_the_first(postprocess):
    result = postprocess.clean_items([model_item(), model_item()], DOC)
    assert len(result) == 1


def test_duplicate_key_ignores_case_and_spacing_in_the_title(postprocess):
    result = postprocess.clean_items([model_item(title="Midterm exam"), model_item(title="  MIDTERM \n exam ")], DOC)
    assert [item.title for item in result] == ["Midterm exam"]


def test_same_title_with_different_types_are_both_kept(postprocess):
    result = postprocess.clean_items(
        [model_item(title="Final project", type="project"), model_item(title="Final project", type="essay")], DOC
    )
    assert [item.type for item in result] == ["project", "essay"]


def test_same_key_on_different_days_keeps_one_per_day(postprocess):
    quiz_2 = model_item(title="Quiz", type="quiz", weight=None, due_date="2026-10-21", date_text="Wednesday, October 21",
                        source_text="Quiz 2 is on Wednesday, October 21.")
    quiz_3 = model_item(title="Quiz", type="quiz", weight=None, due_date="2026-10-28", date_text="Wednesday, October 28",
                        source_text="Quiz 3 is on Wednesday, October 28.")
    result = postprocess.clean_items([quiz_2, quiz_3, quiz_2], DOC)
    assert [item.due_date for item in result] == ["2026-10-21", "2026-10-28"]


@pytest.mark.parametrize(
    ("first_source", "second_source", "kept_source"),
    [
        (UNVERIFIED_MIDTERM_SOURCE, MIDTERM_SOURCE, MIDTERM_SOURCE),  # a later verified copy wins
        (MIDTERM_SOURCE, UNVERIFIED_MIDTERM_SOURCE, MIDTERM_SOURCE),
        (UNVERIFIED_MIDTERM_SOURCE, OTHER_UNVERIFIED_MIDTERM_SOURCE, UNVERIFIED_MIDTERM_SOURCE),
        (MIDTERM_SOURCE, "The midterm exam is on Wednesday, October 14,", MIDTERM_SOURCE),
    ],
    ids=["unverified-then-verified", "verified-then-unverified", "both-unverified", "both-verified"],
)
def test_same_day_duplicates_prefer_a_verified_quote(postprocess, first_source, second_source, kept_source):
    result = postprocess.clean_items([model_item(source_text=first_source), model_item(source_text=second_source)], DOC)
    assert [item.source_text for item in result] == [kept_source]
    assert result[0].due_date == "2026-10-14"


def test_undated_copy_is_dropped_when_a_dated_copy_exists(postprocess):
    undated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date=None, date_text=None,
                         date_was_ambiguous=True, source_text="Essay 2 draft is due Friday, November 6.")
    dated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date="2026-11-06", date_text="Friday, November 6",
                       source_text="Essay 2 draft is due Friday, November 6.")
    result = postprocess.clean_items([undated, dated], DOC)
    assert [(item.title, item.due_date) for item in result] == [("Essay 2 draft", "2026-11-06")]


def test_all_undated_copies_keep_only_the_first(postprocess):
    sources = [
        "Reading responses are due every Friday before class.",
        "Reading responses are due every Friday",
        "responses are due every Friday before class.",
    ]
    copies = [
        model_item(title="Reading response", type="reading", weight=None, due_date=None, date_text=None,
                   date_was_ambiguous=True, source_text=source)
        for source in sources
    ]
    result = postprocess.clean_items(copies, DOC)
    assert [item.source_text for item in result] == [sources[0]]


def test_undated_part_of_a_kept_sentence_is_a_copy(postprocess):
    dated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date="2026-11-06", date_text="Friday, November 6",
                       source_text="Essay 2 draft is due Friday, November 6.")
    undated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date=None, date_text=None,
                         date_was_ambiguous=True, source_text="Essay 2 draft is due Friday")
    result = postprocess.clean_items([dated, undated], DOC)
    assert [(item.source_text, item.due_date) for item in result] == [(dated.source_text, "2026-11-06")]


def test_undated_items_with_different_sentences_are_all_kept(postprocess):
    # Three different lab reports that Claude named the same way: none of them is a copy of another.
    sources = ["Week 3 | Loops | Lab report due", "Week 7 | Files | Lab report due", "Week 12 | Review | Lab report due"]
    copies = [
        model_item(title="Lab report", type="homework", weight=None, due_date=None, date_text=None,
                   date_was_ambiguous=True, source_text=source)
        for source in sources
    ]
    result = postprocess.clean_items(copies, "\n".join(sources))
    assert [item.source_text for item in result] == sources
    assert all(item.due_date is None for item in result)


def test_undated_rule_next_to_a_dated_item_with_the_same_title_is_kept(postprocess):
    rule = model_item(title="Reading response", type="reading", weight=None, due_date=None, date_text=None,
                      date_was_ambiguous=True, source_text="Reading responses are due every Friday before class.")
    first = model_item(title="Reading response", type="reading", weight=None, due_date="2026-09-04",
                       date_text="Friday, September 4", source_text="Reading response 1 is due Friday, September 4.")
    document = f"{rule.source_text}\n{first.source_text}\n"
    result = postprocess.clean_items([rule, first], document)
    assert [(item.source_text, item.due_date) for item in result] == [(rule.source_text, None), (first.source_text, "2026-09-04")]


def test_undated_quiz_next_to_a_dated_quiz_is_kept(postprocess):
    dated = model_item(title="Quiz", type="quiz", weight=None, due_date="2026-10-21", date_text="Wednesday, October 21",
                       source_text="A quiz is on Wednesday, October 21.")
    undated = model_item(title="Quiz", type="quiz", weight=None, due_date=None, date_text=None, date_was_ambiguous=True,
                         source_text="Another quiz happens in Week 12; I'll announce the day in class.")
    document = f"{dated.source_text}\n{undated.source_text}\n"
    result = postprocess.clean_items([dated, undated], document)
    assert [(item.source_text, item.due_date) for item in result] == [(dated.source_text, "2026-10-21"), (undated.source_text, None)]


def test_dedupe_keeps_model_order_across_different_items(postprocess):
    quiz = model_item(title="Quiz 2", type="quiz", weight=None, due_date="2026-10-21", date_text="Wednesday, October 21",
                      source_text="Quiz 2 is on Wednesday, October 21.")
    result = postprocess.clean_items([model_item(), quiz, model_item()], DOC)
    assert [item.title for item in result] == ["Midterm exam", "Quiz 2"]


def test_dropping_an_undated_copy_leaves_other_items_alone(postprocess):
    undated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date=None, date_text=None,
                         date_was_ambiguous=True, source_text="Essay 2 draft is due Friday, November 6.")
    quiz = model_item(title="Quiz 2", type="quiz", weight=None, due_date="2026-10-21", date_text="Wednesday, October 21",
                      source_text="Quiz 2 is on Wednesday, October 21.")
    dated = model_item(title="Essay 2 draft", type="essay", weight=None, due_date="2026-11-06", date_text="Friday, November 6",
                       source_text="Essay 2 draft is due Friday, November 6.")
    result = postprocess.clean_items([undated, quiz, dated], DOC)
    # Order between the two survivors isn't pinned by the contract; which items survive is.
    assert sorted((item.title, item.due_date) for item in result) == [("Essay 2 draft", "2026-11-06"), ("Quiz 2", "2026-10-21")]


# ---------------------------------------------------------------------------
# clean_class_name
# ---------------------------------------------------------------------------
def test_class_name_whitespace_is_collapsed(postprocess):
    assert postprocess.clean_class_name("  CS 101:\n Introduction   to Programming ") == "CS 101: Introduction to Programming"


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t"], ids=repr)
def test_empty_class_name_is_none(postprocess, value):
    assert postprocess.clean_class_name(value) is None


def test_class_name_is_capped_at_120_by_default(postprocess):
    assert postprocess.clean_class_name("A" * 150) == "A" * 120


def test_class_name_cap_can_be_changed(postprocess):
    assert postprocess.clean_class_name("A" * 50, max_chars=10) == "A" * 10


def test_short_class_name_is_unchanged(postprocess):
    assert postprocess.clean_class_name("CS 101") == "CS 101"


def test_model_output_class_name_from_fixture_is_already_clean(postprocess, sample_model_output: ModelOutput):
    assert postprocess.clean_class_name(sample_model_output.class_name) == "CS 101: Introduction to Programming"


# ---------------------------------------------------------------------------
# Term check: a due date must fall inside the term the syllabus states
# ---------------------------------------------------------------------------
TERM_DOC = (
    "CS 101: Introduction to Programming\n"
    "Section 02 · Fall 2026\n"
    "Midterm: Oct 14 in class.\n"
    "Spring reading: Feb 3.\n"
)
TERM_SOURCE = "Midterm: Oct 14 in class."


def _term_item(due_date: str, date_text: str = "Oct 14", source_text: str = TERM_SOURCE) -> ModelItem:
    return model_item(due_date=due_date, date_text=date_text, source_text=source_text)


def test_a_date_in_the_wrong_year_for_the_stated_term_needs_a_date(postprocess):
    [item] = postprocess.clean_items([_term_item("2025-10-14")], TERM_DOC, term="Fall 2026")
    assert item.due_date is None
    assert item.date_was_ambiguous is True
    assert item.date_text == "Oct 14"


def test_a_date_inside_the_stated_term_is_kept(postprocess):
    [item] = postprocess.clean_items([_term_item("2026-10-14")], TERM_DOC, term="Fall 2026")
    assert item.due_date == "2026-10-14"
    assert item.date_was_ambiguous is False


def test_without_a_term_the_year_is_not_checked(postprocess):
    [item] = postprocess.clean_items([_term_item("2025-10-14")], TERM_DOC, term=None)
    assert item.due_date == "2025-10-14"


def test_a_term_that_is_not_in_the_syllabus_is_not_trusted(postprocess):
    # Claude says "Fall 2025", but the syllabus says Fall 2026: no check, the date stands.
    [item] = postprocess.clean_items([_term_item("2026-10-14")], TERM_DOC, term="Fall 2025")
    assert item.due_date == "2026-10-14"


def test_a_year_long_course_accepts_dates_in_either_term(postprocess):
    doc = "Biology 1A/1B, Fall 2026 – Spring 2027\nSpring reading: Feb 3.\n"
    item = _term_item("2027-02-03", date_text="Feb 3", source_text="Spring reading: Feb 3.")
    [cleaned] = postprocess.clean_items([item], doc, term="Fall 2026 – Spring 2027")
    assert cleaned.due_date == "2027-02-03"


def test_run_extraction_passes_the_term_to_the_checks(monkeypatch):
    extraction = importlib.import_module("backend.services.extraction")
    output = ModelOutput(
        class_name="CS 101: Introduction to Programming",
        term="Fall 2026",
        items=[_term_item("2025-10-14")],
    )
    monkeypatch.setattr(extraction, "call_model", lambda *args, **kwargs: output)
    result = extraction.run_extraction(
        TERM_DOC, today=date(2026, 11, 15), model="fake-model", prompt_version="v1", api_key="test-key-not-real"
    )
    assert [item.due_date for item in result.items] == [None]
