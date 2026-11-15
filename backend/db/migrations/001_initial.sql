-- Build 1: syllabi and their extracted items.
-- Rows are keyed by the browser's random client ID (no accounts, no names, no emails).
-- Never add a column for the extended-time multiplier, free hours, or block durations.

CREATE TABLE IF NOT EXISTS syllabi (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id        TEXT    NOT NULL,
    class_name       TEXT    NOT NULL,
    filename         TEXT,                      -- original file name, NULL for pasted text
    extraction_model TEXT    NOT NULL,          -- e.g. claude-haiku-5-5
    prompt_version   TEXT    NOT NULL,          -- e.g. v1 (see backend/prompts.py)
    created_at       TEXT    NOT NULL           -- ISO 8601 UTC, e.g. 2026-11-15T21:30:05Z
);

CREATE INDEX IF NOT EXISTS idx_syllabi_client_created ON syllabi (client_id, created_at);

CREATE TABLE IF NOT EXISTS items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    syllabus_id        INTEGER NOT NULL REFERENCES syllabi (id) ON DELETE CASCADE,
    title              TEXT    NOT NULL,
    type               TEXT    NOT NULL
                       CHECK (type IN ('exam', 'quiz', 'project', 'essay', 'homework', 'reading', 'other')),
    due_date           TEXT,                    -- YYYY-MM-DD, NULL means "needs a date"
    date_text          TEXT,                    -- exact date phrase from source_text
    weight             REAL,                    -- percent of the course grade, NULL if not stated
    source_text        TEXT    NOT NULL,        -- the sentence the deadline came from
    date_was_ambiguous INTEGER NOT NULL CHECK (date_was_ambiguous IN (0, 1)),
    source_verified    INTEGER NOT NULL CHECK (source_verified IN (0, 1)),
    status             TEXT    NOT NULL DEFAULT 'unchecked',
    created_at         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_syllabus ON items (syllabus_id);
