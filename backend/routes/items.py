"""List the deadlines found in this browser's syllabi."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.db.repository import list_items
from backend.routes.deps import get_db, require_client_id
from backend.schemas import ItemListResponse

router = APIRouter(prefix="/api", tags=["items"])


@router.get("/items", response_model=ItemListResponse)
def read_items(
    client_id: Annotated[str, Depends(require_client_id)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> ItemListResponse:
    """Every item from this browser's syllabi: dated ones first by date, then the ones needing a date."""
    return ItemListResponse(items=list_items(conn, client_id=client_id))
