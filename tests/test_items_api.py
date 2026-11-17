"""PATCH /api/items/{id}: the student adds, changes or clears a date, or says "Not sure yet".

Dates go into the plan without a confirm step, so this is the only way a date changes after
extraction. The date extraction found stays in ``extracted_due_date`` whatever the student does.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from backend.db.connection import MIGRATIONS_DIR, init_db
from backend.errors import ERRORS

SYLLABI = "/api/syllabi"
ITEMS = "/api/items"


def upload(client, text: str) -> dict:
    response = client.post(SYLLABI, files={"text": (None, text.encode("utf-8"))})
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, item_id, body: dict, **kwargs):
    return client.patch(f"{ITEMS}/{item_id}", json=body, **kwargs)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text[:300]
    assert response.json() == {"error": {"code": code, "message": ERRORS[code].message}}


def by_title(items: list[dict], title: str, *, dated: bool) -> dict:
    matches = [item for item in items if item["title"] == title and (item["due_date"] is not None) == dated]
    assert len(matches) == 1, f"{title}: {matches}"
    return matches[0]


@pytest.fixture
def uploaded(client, sample_syllabus_text) -> dict:
    return upload(client, sample_syllabus_text)


@pytest.fixture
def dated(uploaded) -> dict:
    """Quiz 1, which the syllabus dates 2026-09-10."""
    return by_title(uploaded["items"], "Quiz 1", dated=True)


@pytest.fixture
def undated(uploaded) -> dict:
    """Project check-in meeting: the syllabus gives a range, so it has no date."""
    return by_title(uploaded["items"], "Project check-in meeting", dated=False)


# ---------------------------------------------------------------------------
# What extraction stores
# ---------------------------------------------------------------------------
def test_new_items_keep_the_extracted_date_beside_the_plan_date(uploaded):
    for item in uploaded["items"]:
        assert item["extracted_due_date"] == item["due_date"]
        assert item["status"] == "unchecked"


# ---------------------------------------------------------------------------
# Adding and changing a date
# ---------------------------------------------------------------------------
def test_adding_a_date_to_an_undated_item(client, uploaded, undated):
    response = patch(client, undated["id"], {"due_date": "2026-12-08"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "item": {**undated, "due_date": "2026-12-08", "extracted_due_date": None, "status": "edited"}
    }

    syllabus = client.get(SYLLABI).json()["syllabi"][0]
    before = uploaded["syllabus"]
    assert syllabus["dated_count"] == before["dated_count"] + 1
    assert syllabus["needs_date_count"] == before["needs_date_count"] - 1
    assert syllabus["item_count"] == before["item_count"]


def test_changing_a_date_keeps_what_the_syllabus_said(client, dated):
    item = patch(client, dated["id"], {"due_date": "2026-09-11"}).json()["item"]
    assert item["due_date"] == "2026-09-11"
    assert item["extracted_due_date"] == "2026-09-10"
    assert item["status"] == "edited"

    again = patch(client, dated["id"], {"due_date": "2026-09-17"}).json()["item"]
    assert again["due_date"] == "2026-09-17"
    assert again["extracted_due_date"] == "2026-09-10"


def test_undoing_a_change_puts_the_item_back_as_extracted(client, dated):
    patch(client, dated["id"], {"due_date": "2026-09-11"})
    response = patch(client, dated["id"], {"due_date": "2026-09-10"})
    assert response.json() == {"item": dated}


def test_undoing_an_added_date_puts_the_item_back_as_extracted(client, undated):
    patch(client, undated["id"], {"due_date": "2026-12-08"})
    response = patch(client, undated["id"], {"due_date": None})
    assert response.json() == {"item": undated}


def test_the_same_request_twice_gives_the_same_answer(client, undated):
    first = patch(client, undated["id"], {"due_date": "2026-12-08"})
    second = patch(client, undated["id"], {"due_date": "2026-12-08"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_a_changed_date_moves_the_item_in_the_list(client, uploaded, undated):
    patch(client, undated["id"], {"due_date": "2026-09-01"})
    listed = client.get(ITEMS).json()["items"]
    assert listed[0]["id"] == undated["id"]
    assert len(listed) == len(uploaded["items"])


def test_surrounding_spaces_are_ignored(client, undated):
    assert patch(client, undated["id"], {"due_date": " 2026-12-08 "}).json()["item"]["due_date"] == "2026-12-08"


def test_clearing_a_date_the_syllabus_gave_counts_as_an_edit(client, dated):
    item = patch(client, dated["id"], {"due_date": None}).json()["item"]
    assert item["due_date"] is None
    assert item["extracted_due_date"] == "2026-09-10"
    assert item["status"] == "edited"


# ---------------------------------------------------------------------------
# Not sure yet
# ---------------------------------------------------------------------------
def test_not_sure_yet_marks_the_item_skipped_and_leaves_it_undated(client, undated):
    response = patch(client, undated["id"], {"due_date": None, "not_sure": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"item": {**undated, "status": "skipped"}}


def test_undoing_not_sure_yet(client, undated):
    patch(client, undated["id"], {"due_date": None, "not_sure": True})
    assert patch(client, undated["id"], {"due_date": None}).json() == {"item": undated}


def test_a_skipped_item_can_get_a_date_later(client, undated):
    patch(client, undated["id"], {"due_date": None, "not_sure": True})
    item = patch(client, undated["id"], {"due_date": "2026-12-09"}).json()["item"]
    assert (item["due_date"], item["status"]) == ("2026-12-09", "edited")


def test_not_sure_with_a_date_is_refused(client, undated):
    assert_error(patch(client, undated["id"], {"due_date": "2026-12-08", "not_sure": True}), 400, "bad_request")
    assert client.get(ITEMS).json()["items"].count(undated) == 1


# ---------------------------------------------------------------------------
# Dates that aren't dates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        "", "tomorrow", "12/08/2026", "2026-12-8", "2026-2-30", "2026-02-30", "2026-13-01", "2026-00-10",
        "2026-12-08T09:00", "20261208", "1999-12-31", "2101-01-01", "0026-12-08", "2026-12-08; DROP TABLE items",
    ],
)
def test_a_bad_date_is_refused_and_nothing_changes(client, dated, value):
    assert_error(patch(client, dated["id"], {"due_date": value}), 400, "invalid_date")
    assert by_title(client.get(ITEMS).json()["items"], "Quiz 1", dated=True) == dated


@pytest.mark.parametrize("value", ["2000-01-01", "2100-12-31", "2028-02-29"])
def test_edge_dates_are_accepted(client, dated, value):
    assert patch(client, dated["id"], {"due_date": value}).json()["item"]["due_date"] == value


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"not_sure": True},
        {"due_date": 20261208},
        {"due_date": ["2026-12-08"]},
        {"due_date": "2026-12-08", "not_sure": "maybe"},
        {"due_date": "2026-12-08", "multiplier": 1.5},
        {"due_date": "2026-12-08", "title": "Something else"},
        {"due_date": "2026-12-08", "status": "skipped"},
    ],
)
def test_a_body_with_the_wrong_shape_is_refused(client, dated, body):
    assert_error(patch(client, dated["id"], body), 422, "validation_error")
    assert by_title(client.get(ITEMS).json()["items"], "Quiz 1", dated=True) == dated


# ---------------------------------------------------------------------------
# Whose item it is
# ---------------------------------------------------------------------------
def test_another_browser_cannot_change_my_item(client, dated, other_client_id):
    response = patch(client, dated["id"], {"due_date": "2026-09-11"}, headers={"X-Client-Id": other_client_id})
    assert_error(response, 404, "not_found")
    assert by_title(client.get(ITEMS).json()["items"], "Quiz 1", dated=True) == dated


def test_a_browser_id_is_required(client, dated):
    response = patch(client, dated["id"], {"due_date": "2026-09-11"}, headers={"X-Client-Id": ""})
    assert_error(response, 400, "missing_client_id")


@pytest.mark.parametrize("item_id", [0, -1, 999_999, 2**63, 10**30])
def test_an_item_that_does_not_exist(client, uploaded, item_id):
    assert_error(patch(client, item_id, {"due_date": "2026-09-11"}), 404, "not_found")


def test_an_item_id_that_is_not_a_number(client, uploaded):
    assert_error(patch(client, "abc", {"due_date": "2026-09-11"}), 422, "validation_error")


# ---------------------------------------------------------------------------
# Migration 002 on a database made by Build 1
# ---------------------------------------------------------------------------
def test_migration_fills_in_the_extracted_date_for_build_1_rows(tmp_path):
    path = tmp_path / "old.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript((MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO syllabi (client_id, class_name, filename, extraction_model, prompt_version, created_at) "
            "VALUES ('c', 'CS 101', NULL, 'm', 'v1', '2026-11-15T21:30:05Z')"
        )
        conn.executemany(
            "INSERT INTO items (syllabus_id, title, type, due_date, date_text, weight, source_text, "
            "date_was_ambiguous, source_verified, status, created_at) "
            "VALUES (1, ?, 'quiz', ?, NULL, NULL, 's', 0, 1, 'unchecked', '2026-11-15T21:30:05Z')",
            [("Quiz 1", "2026-09-10"), ("Quiz 2", None)],
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    init_db(path)
    init_db(path)  # a second start must not run it again

    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT title, due_date, extracted_due_date, status FROM items ORDER BY id").fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert rows == [("Quiz 1", "2026-09-10", "2026-09-10", "unchecked"), ("Quiz 2", None, None, "unchecked")]
    assert version == 2


def test_the_items_table_has_no_column_that_could_hold_private_settings(tmp_path):
    path = tmp_path / "new.db"
    init_db(path)
    with closing(sqlite3.connect(path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    assert columns == {
        "id", "syllabus_id", "title", "type", "due_date", "extracted_due_date", "date_text", "weight",
        "source_text", "date_was_ambiguous", "source_verified", "status", "created_at",
    }
