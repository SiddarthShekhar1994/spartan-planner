"""Opening the SQLite database and bringing its schema up to date.

Migrations are the numbered files in ``backend/db/migrations`` (``001_initial.sql``, ``002_...``).
``PRAGMA user_version`` records the last one applied, so each file runs once per database.
A migration file must not contain its own BEGIN or COMMIT: ``init_db`` wraps each one in a
transaction together with the version bump.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path

logger = logging.getLogger("spartan.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BUSY_TIMEOUT_SECONDS = 10
_MIGRATION_FILE = re.compile(r"(\d{3})_[^\\/]+\.sql")


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a connection: rows as ``sqlite3.Row``, foreign keys enforced.

    ``check_same_thread=False`` because FastAPI runs sync dependencies and sync routes on
    different threadpool threads. Each connection still serves one request at a time.
    """
    conn = sqlite3.connect(Path(database_path), timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON").close()
    except BaseException:
        conn.close()
        raise
    return conn


def _migration_files() -> list[tuple[int, Path]]:
    """``(number, path)`` for every ``NNN_name.sql`` file, lowest number first."""
    found: dict[int, Path] = {}
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = _MIGRATION_FILE.fullmatch(path.name)
        if match is None:
            continue
        number = int(match.group(1))
        if number in found:
            raise RuntimeError(f"two migration files use the number {number:03d}")
        found[number] = path
    return sorted(found.items())


def init_db(database_path: Path) -> None:
    """Create the database folder and apply every migration newer than ``PRAGMA user_version``.

    Each migration runs in its own ``BEGIN IMMEDIATE`` transaction that also sets
    ``user_version``, and the version is re-read inside that transaction, so a failed migration
    leaves no partial schema and two processes starting at once don't apply one twice.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = _migration_files()
    with closing(connect(path)) as conn:
        conn.autocommit = True  # no implicit transactions: the BEGIN/COMMIT below are explicit
        for number, migration in migrations:
            sql = migration.read_text(encoding="utf-8")
            conn.execute("BEGIN IMMEDIATE").close()
            try:
                with closing(conn.execute("PRAGMA user_version")) as cursor:
                    current = int(cursor.fetchone()[0])
                if number > current:
                    conn.executescript(sql).close()
                    conn.execute(f"PRAGMA user_version = {number:d}").close()
                    logger.info("db_migrated version=%d", number)
                conn.execute("COMMIT").close()
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK").close()
                raise
