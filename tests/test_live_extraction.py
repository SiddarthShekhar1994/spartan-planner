"""One real Claude call on the sample syllabus. Costs a fraction of a cent.

Skipped by default (pytest.ini runs ``-m "not live"``). Run it on purpose with:
    .\\.venv\\Scripts\\python.exe -m pytest -m live
It skips itself when no ANTHROPIC_API_KEY is configured. The key is never printed.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from backend.config import load_settings

pytestmark = pytest.mark.live

TODAY = date(2026, 11, 15)


@pytest.fixture
def live_settings():
    """Settings from .env / the environment, with os.environ put back afterwards (load_dotenv writes to it)."""
    saved = dict(os.environ)
    try:
        settings = load_settings()
        if not settings.anthropic_api_key:
            pytest.skip("No ANTHROPIC_API_KEY in .env or the environment")
        yield settings
    finally:
        os.environ.clear()
        os.environ.update(saved)


def describe(item) -> str:
    """Title and quote together, lowercased, for lenient matching."""
    return f"{item.title} {item.source_text}".casefold()


def test_live_extraction_on_the_sample_syllabus(extraction, live_settings, sample_syllabus_text):
    result = extraction.run_extraction(
        sample_syllabus_text,
        today=TODAY,
        model=live_settings.claude_model,
        prompt_version=live_settings.prompt_version,
        api_key=live_settings.anthropic_api_key,
    )
    items = result.items
    assert result.model == live_settings.claude_model
    assert result.prompt_version == live_settings.prompt_version
    assert result.class_name is not None and "CS 101" in result.class_name
    assert items, "no deadlines found"

    def matching(*words: str) -> list:
        return [item for item in items if all(word in describe(item) for word in words)]

    def show(found: list) -> str:
        """What Claude and our checks produced, so a failure explains itself (the sample is made up)."""
        return "; ".join(
            f"{item.title!r} due={item.due_date} date_text={item.date_text!r} source={item.source_text!r}" for item in found
        ) or "no matching items"

    # Clear, single dates are found.
    for words, due in [(("quiz 1",), "2026-09-10"), (("midterm",), "2026-10-14"), (("final exam",), "2026-12-14")]:
        found = matching(*words)
        assert any(item.due_date == due for item in found), f"{words[0]} on {due}; got: {show(found or items)}"

    # Vague timing is listed with no date, never guessed.
    for words, label in [(("lab report",), "TBA lab report"), (("presentation",), "last-week presentations"), (("reading response",), "every-Friday reading responses")]:
        found = matching(*words)
        assert found, f"the {label} should still be listed"
        assert all(item.due_date is None for item in found), f"the {label} must not get a date"

    # The Dec 7-11 range never becomes Dec 7; drop dates and holidays aren't deadlines.
    assert not [item for item in items if item.due_date == "2026-12-07"]
    assert not [item for item in items if "drop" in describe(item) or "veterans" in describe(item)]

    verified = sum(item.source_verified for item in items)
    assert verified >= 0.8 * len(items), f"only {verified} of {len(items)} quotes were found in the syllabus"
