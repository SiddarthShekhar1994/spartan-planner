"""One place for "now", so every timestamp has the same format and tests can freeze time.

Always call these through the module (``from backend import clock`` then ``clock.now_utc()``),
never ``from backend.clock import now_utc``, so a test can monkeypatch ``backend.clock.now_utc``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> datetime:
    """Current time in UTC, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(moment: datetime) -> str:
    """Format an aware datetime as an ISO 8601 UTC string, e.g. 2026-11-15T21:30:05Z."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime(ISO_FORMAT)


def from_iso(value: str) -> datetime:
    """Parse a string written by ``to_iso`` back into an aware UTC datetime."""
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=timezone.utc)


def today_local() -> date:
    """Today's date on the server. Used to pick the year when a syllabus states no term."""
    return date.today()
