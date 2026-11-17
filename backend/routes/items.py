"""List the deadlines found in this browser's syllabi, and save a date the student sets.

Dates go into the plan without a confirm step. The student only touches a date to add one the
syllabus didn't give, to change one, or to say "Not sure yet". The date extraction found is kept
in ``extracted_due_date`` and never overwritten, so corrections can be counted later.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.db.repository import get_item, list_items, set_item_date
from backend.errors import AppError
from backend.routes.deps import get_db, require_client_id
from backend.schemas import ItemDateRequest, ItemListResponse, ItemResponse

router = APIRouter(prefix="/api", tags=["items"])

MAX_ROW_ID = 2**63 - 1  # SQLite's largest integer; bigger path ids can't exist (and would overflow)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A typed year such as 0026 or 20226 is a slip of the keyboard, not a deadline.
MIN_YEAR = 2000
MAX_YEAR = 2100


@router.get("/items", response_model=ItemListResponse)
def read_items(
    client_id: Annotated[str, Depends(require_client_id)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> ItemListResponse:
    """Every item from this browser's syllabi: dated ones first by date, then the ones needing a date."""
    return ItemListResponse(items=list_items(conn, client_id=client_id))


@router.patch("/items/{item_id}", response_model=ItemResponse)
def save_item_date(
    item_id: int,
    body: ItemDateRequest,
    client_id: Annotated[str, Depends(require_client_id)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> ItemResponse:
    """Set, change or clear one item's date, or mark it "Not sure yet".

    Sending the same body twice gives the same result, so a retry is safe.
    """
    due_date = _clean_date(body.due_date)
    if body.not_sure and due_date is not None:
        raise AppError("bad_request")
    if not 1 <= item_id <= MAX_ROW_ID:
        raise AppError("not_found")
    item = get_item(conn, client_id=client_id, item_id=item_id)
    if item is None:
        raise AppError("not_found")
    status = _status_for(due_date, extracted=item.extracted_due_date, not_sure=body.not_sure)
    if not set_item_date(conn, client_id=client_id, item_id=item_id, due_date=due_date, status=status):
        raise AppError("not_found")
    saved = get_item(conn, client_id=client_id, item_id=item_id)
    if saved is None:
        raise AppError("not_found")
    return ItemResponse(item=saved)


def _clean_date(value: str | None) -> str | None:
    """A real calendar day as YYYY-MM-DD, or None. Anything else is ``invalid_date``."""
    if value is None:
        return None
    text = value.strip()
    if not _ISO_DATE.fullmatch(text):
        raise AppError("invalid_date")
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise AppError("invalid_date") from None
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise AppError("invalid_date")
    return parsed.isoformat()


def _status_for(due_date: str | None, *, extracted: str | None, not_sure: bool) -> str:
    """'skipped' for "Not sure yet", 'unchecked' when the date is what extraction found, else 'edited'."""
    if due_date is None and not_sure:
        return "skipped"
    return "unchecked" if due_date == extracted else "edited"
