"""Every SQL query the app runs.

Each function takes an open connection and keyword arguments. Every query filters by
``client_id``, so one browser can never read or change another browser's rows.
Booleans come back as ``bool`` and ids as ``int``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from backend.schemas import CleanItem, ItemOut, SyllabusOut

_SYLLABUS_SELECT = """
SELECT
    s.id AS id,
    s.class_name AS class_name,
    s.filename AS filename,
    s.created_at AS created_at,
    COUNT(i.id) AS item_count,
    SUM(CASE WHEN i.id IS NOT NULL AND i.due_date IS NOT NULL THEN 1 ELSE 0 END) AS dated_count,
    SUM(CASE WHEN i.id IS NOT NULL AND i.due_date IS NULL THEN 1 ELSE 0 END) AS needs_date_count,
    SUM(CASE WHEN i.id IS NOT NULL AND i.source_verified = 0 THEN 1 ELSE 0 END) AS unverified_count
FROM syllabi AS s
LEFT JOIN items AS i ON i.syllabus_id = s.id
WHERE s.client_id = ?
"""

_ITEM_SELECT = """
SELECT
    i.id AS id,
    i.syllabus_id AS syllabus_id,
    i.title AS title,
    i.type AS type,
    i.due_date AS due_date,
    i.extracted_due_date AS extracted_due_date,
    i.date_text AS date_text,
    i.weight AS weight,
    i.source_text AS source_text,
    i.date_was_ambiguous AS date_was_ambiguous,
    i.source_verified AS source_verified,
    i.status AS status,
    i.created_at AS created_at
FROM items AS i
JOIN syllabi AS s ON s.id = i.syllabus_id
WHERE s.client_id = ?
"""

# Dated items first, by date; then the ones that still need a date. Ties keep upload order.
_ITEM_ORDER = " ORDER BY (i.due_date IS NULL), i.due_date, i.syllabus_id, i.id"

_INSERT_SYLLABUS = """
INSERT INTO syllabi (client_id, class_name, filename, extraction_model, prompt_version, created_at)
VALUES (?, ?, ?, ?, ?, ?)
"""

_INSERT_ITEM = """
INSERT INTO items (syllabus_id, title, type, due_date, extracted_due_date, date_text, weight, source_text,
                   date_was_ambiguous, source_verified, status, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unchecked', ?)
"""


def _fetchall(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> list[sqlite3.Row]:
    with closing(conn.execute(sql, tuple(params))) as cursor:
        return cursor.fetchall()


def _syllabus_from_row(row: sqlite3.Row) -> SyllabusOut:
    return SyllabusOut(
        id=int(row["id"]),
        class_name=row["class_name"],
        filename=row["filename"],
        created_at=row["created_at"],
        item_count=int(row["item_count"] or 0),
        dated_count=int(row["dated_count"] or 0),
        needs_date_count=int(row["needs_date_count"] or 0),
        unverified_count=int(row["unverified_count"] or 0),
    )


def _item_from_row(row: sqlite3.Row) -> ItemOut:
    weight = row["weight"]
    return ItemOut(
        id=int(row["id"]),
        syllabus_id=int(row["syllabus_id"]),
        title=row["title"],
        type=row["type"],
        due_date=row["due_date"],
        extracted_due_date=row["extracted_due_date"],
        date_text=row["date_text"],
        weight=None if weight is None else float(weight),
        source_text=row["source_text"],
        date_was_ambiguous=bool(row["date_was_ambiguous"]),
        source_verified=bool(row["source_verified"]),
        status=row["status"],
        created_at=row["created_at"],
    )


def create_syllabus(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    class_name: str,
    filename: str | None,
    extraction_model: str,
    prompt_version: str,
    items: Sequence[CleanItem],
    created_at: str,
) -> int:
    """Save a syllabus and its items in one transaction. Items start as 'unchecked'. Returns the new id."""
    with conn:
        with closing(
            conn.execute(
                _INSERT_SYLLABUS,
                (client_id, class_name, filename, extraction_model, prompt_version, created_at),
            )
        ) as cursor:
            syllabus_id = int(cursor.lastrowid)
        item_rows = [
            (
                syllabus_id,
                item.title,
                item.type,
                item.due_date,
                item.due_date,  # extracted_due_date: what the syllabus said, kept as it was
                item.date_text,
                item.weight,
                item.source_text,
                int(item.date_was_ambiguous),
                int(item.source_verified),
                created_at,
            )
            for item in items
        ]
        if item_rows:
            conn.executemany(_INSERT_ITEM, item_rows).close()
    return syllabus_id


def get_syllabus(conn: sqlite3.Connection, *, client_id: str, syllabus_id: int) -> SyllabusOut | None:
    """One of this client's syllabi with its item counts, or None if it isn't theirs or doesn't exist."""
    rows = _fetchall(conn, _SYLLABUS_SELECT + " AND s.id = ? GROUP BY s.id", (client_id, syllabus_id))
    return _syllabus_from_row(rows[0]) if rows else None


def list_syllabi(conn: sqlite3.Connection, *, client_id: str) -> list[SyllabusOut]:
    """This client's syllabi, oldest first (so class colors stay stable as more are added)."""
    rows = _fetchall(conn, _SYLLABUS_SELECT + " GROUP BY s.id ORDER BY s.id ASC", (client_id,))
    return [_syllabus_from_row(row) for row in rows]


def list_items(conn: sqlite3.Connection, *, client_id: str, syllabus_id: int | None = None) -> list[ItemOut]:
    """This client's items (optionally one syllabus's): dated first by date, then the ones needing a date."""
    sql = _ITEM_SELECT
    params: list[Any] = [client_id]
    if syllabus_id is not None:
        sql += " AND i.syllabus_id = ?"
        params.append(syllabus_id)
    rows = _fetchall(conn, sql + _ITEM_ORDER, params)
    return [_item_from_row(row) for row in rows]


def get_item(conn: sqlite3.Connection, *, client_id: str, item_id: int) -> ItemOut | None:
    """One of this client's items, or None if it isn't theirs or doesn't exist."""
    rows = _fetchall(conn, _ITEM_SELECT + " AND i.id = ?", (client_id, item_id))
    return _item_from_row(rows[0]) if rows else None


def set_item_date(
    conn: sqlite3.Connection, *, client_id: str, item_id: int, due_date: str | None, status: str
) -> bool:
    """Set an item's date and status. False if the item isn't this client's (or doesn't exist).

    ``extracted_due_date`` is never touched: it stays what the syllabus said.
    """
    with conn:
        with closing(
            conn.execute(
                "UPDATE items SET due_date = ?, status = ? "
                "WHERE id = ? AND syllabus_id IN (SELECT id FROM syllabi WHERE client_id = ?)",
                (due_date, status, item_id, client_id),
            )
        ) as cursor:
            changed = cursor.rowcount
    return changed == 1


def rename_syllabus(conn: sqlite3.Connection, *, client_id: str, syllabus_id: int, class_name: str) -> bool:
    """Set a syllabus's class name. False if the syllabus isn't this client's (or doesn't exist)."""
    with conn:
        with closing(
            conn.execute(
                "UPDATE syllabi SET class_name = ? WHERE id = ? AND client_id = ?",
                (class_name, syllabus_id, client_id),
            )
        ) as cursor:
            changed = cursor.rowcount
    return changed == 1


def recent_upload_stats(conn: sqlite3.Connection, *, client_id: str, since: str) -> tuple[int, str | None]:
    """``(count, oldest created_at)`` of this client's syllabi saved at or after ``since`` (ISO UTC)."""
    rows = _fetchall(
        conn,
        "SELECT COUNT(*) AS upload_count, MIN(created_at) AS oldest FROM syllabi WHERE client_id = ? AND created_at >= ?",
        (client_id, since),
    )
    row = rows[0]
    return int(row["upload_count"]), row["oldest"]
