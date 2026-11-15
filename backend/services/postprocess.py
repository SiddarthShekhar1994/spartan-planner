"""Our own rules on top of Claude's answer, applied before anything is saved.

Claude's reply is checked against the syllabus itself: a quote that isn't in the syllabus is
flagged, a due date is kept only when its quoted date phrase (and the date words right around
it in the quote) names that exact day and falls inside the term the syllabus states, weights
outside 0-100 are dropped, and the same deadline quoted twice is kept once.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from backend.schemas import CleanItem, ModelItem
from backend.services.dates import date_phrase_span, date_supported_by_text, parse_iso_date
from backend.services.source_check import SourceMatcher, normalize_for_match, phrase_in
from backend.services.terms import date_in_term, term_date_ranges

MAX_TITLE_CHARS = 200
MAX_SOURCE_TEXT_CHARS = 2000
MAX_DATE_TEXT_CHARS = 200
UNTITLED = "Untitled deadline"


def _collapse(value: str | None) -> str:
    """Whitespace runs (line breaks included) become one space; ends are stripped."""
    return " ".join((value or "").split())


def _cap(value: str, max_chars: int) -> str:
    return value[:max_chars].rstrip()


def clean_class_name(value: str | None, max_chars: int = 120) -> str | None:
    """A tidy class name, or None when there is nothing left."""
    return _cap(_collapse(value), max_chars) or None


def _clean_weight(weight: float | None) -> float | None:
    if weight is None:
        return None
    value = float(weight)
    if not 0 < value <= 100:  # also rejects NaN
        return None
    return round(value, 2)


def _clean_item(item: ModelItem, matcher: SourceMatcher, term_ranges: list[tuple[date, date]]) -> CleanItem:
    title = _cap(_collapse(item.title), MAX_TITLE_CHARS) or UNTITLED
    source_text = _cap(_collapse(item.source_text), MAX_SOURCE_TEXT_CHARS)
    source_verified = matcher.contains(item.source_text)

    date_text: str | None = _cap(_collapse(item.date_text), MAX_DATE_TEXT_CHARS) or None
    if date_text is not None and not phrase_in(source_text, date_text):
        date_text = None

    due = parse_iso_date(item.due_date)
    keep_date = False
    if not item.date_was_ambiguous and due is not None and date_text is not None:
        span = date_phrase_span(source_text, date_text)
        if span is None:  # not in the quote as whole words: "Oct 1" is not in "Oct 14"
            date_text = None
        else:
            # The date words right around the phrase count too, so a shortened date_text can't
            # hide a weekday, a year, a second day or "the week of" ("Dec 7" cut from "Dec 7–11").
            keep_date = date_supported_by_text(due, date_text) and date_supported_by_text(due, span)
    if keep_date and due is not None and term_ranges and not date_in_term(due, term_ranges):
        keep_date = False  # outside the term the syllabus states: most likely the wrong year
    due_date = due.isoformat() if keep_date and due is not None else None

    return CleanItem(
        title=title,
        type=item.type,
        due_date=due_date,
        date_text=date_text,
        weight=_clean_weight(item.weight),
        source_text=source_text,
        date_was_ambiguous=due_date is None,
        source_verified=source_verified,
    )


def _same_sentence(first_key: str, second_key: str) -> bool:
    """True when one quote contains the other. Both are already in ``normalize_for_match`` form."""
    return bool(first_key) and bool(second_key) and (first_key in second_key or second_key in first_key)


def _dedupe(items: list[CleanItem]) -> list[CleanItem]:
    """Drop copies of the same deadline, keeping the survivors in Claude's order.

    Items can be copies when they share a title (ignoring case and spacing) and a type. Among them,
    one item per due date stays (a verified quote beats an earlier unverified one). An undated item
    is dropped only when its sentence is a copy of one already kept (the same sentence, or one inside
    the other). Any other undated item is a different deadline that happens to share a name, such as
    "Lab report" in Week 3 and in Week 7, so it stays.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for index, item in enumerate(items):
        groups.setdefault((item.title.casefold(), item.type), []).append(index)
    # Quotes compared the way they are matched to the syllabus, worked out once per item.
    sentences = [normalize_for_match(item.source_text) for item in items]

    keep: set[int] = set()
    for indexes in groups.values():
        by_date: dict[str, int] = {}
        for index in indexes:
            due = items[index].due_date
            if due is None:
                continue
            current = by_date.get(due)
            if current is None or (items[index].source_verified and not items[current].source_verified):
                by_date[due] = index
        kept = list(by_date.values())
        for index in indexes:
            if items[index].due_date is None and not any(
                _same_sentence(sentences[index], sentences[other]) for other in kept
            ):
                kept.append(index)
        keep.update(kept)
    return [items[index] for index in sorted(keep)]


def clean_items(model_items: Sequence[ModelItem], document_text: str, term: str | None = None) -> list[CleanItem]:
    """Apply every rule to Claude's items. ``document_text`` is the syllabus text Claude read.

    ``term`` is the term Claude read from the syllabus ("Fall 2026"). It is only trusted when it
    really appears in the syllabus; then a due date outside that term is not kept.
    """
    matcher = SourceMatcher(document_text)
    term_ranges = term_date_ranges(term) if matcher.contains(term) else []
    return _dedupe([_clean_item(item, matcher, term_ranges) for item in model_items])
