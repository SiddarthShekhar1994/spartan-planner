"""The upload API end to end (backend/main.py, routes/, db/, services/rate_limit.py) through TestClient.

Claude is never called: the app gets a FakeExtractor (see conftest.py) that returns the fixture's
model output, cleaned against whatever text the route sends it. The config and error checks at the
top only need the already-written shared files.
"""

from __future__ import annotations

import contextlib
import importlib
import random
import re
import sqlite3
import tempfile
import threading
from datetime import date
from pathlib import Path

import httpx2
import pytest
import starlette.formparsers
from pydantic import ValidationError

from backend.config import FRONTEND_DIR, PROJECT_ROOT, Settings, resolve_path
from backend.errors import ERRORS, AppError
from backend.prompts import CURRENT_PROMPT_VERSION
from backend.schemas import ITEM_TYPES, RenameRequest

API = "/api/syllabi"
MIB = 1024 * 1024
WINDOW = 24 * 60 * 60
PRIVATE = "PRIVATE-SYLLABUS-TEXT-7f3a"
CLASS_NAME = "CS 101: Introduction to Programming"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SYLLABUS_KEYS = {"id", "class_name", "filename", "created_at", "item_count", "dated_count", "needs_date_count", "unverified_count"}
ITEM_KEYS = {
    "id", "syllabus_id", "title", "type", "due_date", "extracted_due_date", "date_text", "weight", "source_text",
    "date_was_ambiguous", "source_verified", "status", "created_at",
}
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TEXT_COUNTS = {"item_count": 13, "dated_count": 6, "needs_date_count": 7, "unverified_count": 1}
# The PDF has the same items, but three quotes can't be found in its text: the invented Homework 6,
# the "Reading responses" line (not in the PDF), and the table row (pypdf drops the | separators).
PDF_COUNTS = {"item_count": 13, "dated_count": 6, "needs_date_count": 7, "unverified_count": 3}
EXPECTED_ORDER = [
    # dated, by date
    "Quiz 1", "Essay 1: Why Programs Fail", "Midterm exam", "Homework 4", "Homework 6", "Final exam",
    # needs a date, in the order Claude listed them (the last is the grading table's "Final exam  25%")
    "Project proposal", "Project check-in meeting", "Final project presentation", "Lab report 3",
    "Reading response", "Read Chapter 5 of Think Python", "Final exam",
]
STATUS_TABLE = {
    400: ["missing_client_id", "no_input", "two_inputs", "bad_request", "invalid_class_name", "invalid_date"],
    404: ["not_found"],
    405: ["method_not_allowed"],
    413: ["file_too_large", "text_too_long"],
    415: ["unsupported_type"],
    422: ["validation_error", "unreadable_file", "no_text_found", "text_too_short", "extraction_refused", "extraction_too_long"],
    429: ["daily_limit", "network_limit"],
    500: ["internal_error"],
    502: ["extraction_failed"],
    503: ["extraction_unavailable", "extraction_not_configured"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def post_text(client, text: str, **kwargs):
    """Paste text the way the browser does: a multipart field named "text"."""
    return client.post(API, files={"text": (None, text.encode("utf-8"))}, **kwargs)


def post_file(client, filename: str, data: bytes, content_type: str = "application/octet-stream", **kwargs):
    return client.post(API, files={"file": (filename, data, content_type)}, **kwargs)


def post_pdf(client, data: bytes, filename: str = "cs101.pdf", **kwargs):
    return post_file(client, filename, data, "application/pdf", **kwargs)


def as_client(client_id: str) -> dict:
    return {"headers": {"X-Client-Id": client_id}}


def assert_error(response, status: int, code: str, message: str | None = None) -> dict:
    """The response is our error envelope with this status and code (and the standard message unless given)."""
    assert response.status_code == status, f"expected {status}, got {response.status_code}: {response.text[:300]}"
    body = response.json()
    assert list(body) == ["error"], body
    error = body["error"]
    assert set(error) <= {"code", "message", "retry_after_seconds"}, error
    assert error["code"] == code, error
    assert error["message"] == (message if message is not None else ERRORS[code].message)
    if "retry_after_seconds" not in error:
        assert "retry-after" not in response.headers
    return error


def counts(syllabus: dict) -> dict:
    return {key: syllabus[key] for key in TEXT_COUNTS}


def multipart_body(files) -> tuple[bytes, str]:
    """Encode a multipart body with httpx2, so a test can send it with or without Content-Length."""
    request = httpx2.Request("POST", "http://testserver" + API, files=files)
    return request.read(), request.headers["content-type"]


def daily_limit_message(limit: int) -> str:
    return f"You've hit today's limit of {limit} syllabi."


@pytest.fixture
def uploaded(client, sample_syllabus_text) -> dict:
    """One pasted syllabus for TEST_CLIENT_ID; the 201 body."""
    response = post_text(client, sample_syllabus_text)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def spool_files(spool_dir, monkeypatch) -> list:
    """Every SpooledTemporaryFile Starlette makes for an upload, and whether it rolled over to disk."""
    made: list = []

    class RecordingSpool(tempfile.SpooledTemporaryFile):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.rolled = False
            self.disk_path: Path | None = None
            made.append(self)

        def rollover(self) -> None:
            super().rollover()
            self.rolled = True
            name = getattr(self._file, "name", None)
            self.disk_path = Path(name) if isinstance(name, str) else None

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", RecordingSpool)
    return made


# ---------------------------------------------------------------------------
# Shared files: settings, errors, rename schema (already written)
# ---------------------------------------------------------------------------
def test_default_limits_match_what_the_frontend_tells_students(tmp_path):
    settings = Settings(anthropic_api_key=None, claude_model="claude-haiku-5-5", database_path=tmp_path / "x.db")
    assert settings.max_upload_bytes == 10 * MIB  # "up to 10 MB each"
    assert settings.max_text_chars == 150_000  # "more than 150,000 characters"
    assert settings.min_text_chars == 50
    assert settings.daily_uploads_per_client == 10
    assert settings.daily_uploads_per_ip == 50
    assert settings.rate_window_seconds == WINDOW
    assert settings.max_class_name_chars == 120
    assert settings.prompt_version == CURRENT_PROMPT_VERSION


def test_settings_repr_never_shows_the_api_key(tmp_path):
    secret = "secret-value-not-a-real-key"  # no real key prefix, so the README's search for keys stays empty
    settings = Settings(anthropic_api_key=secret, claude_model="claude-haiku-5-5", database_path=tmp_path / "x.db")
    assert secret not in repr(settings)


def test_relative_paths_resolve_from_the_project_root():
    assert resolve_path("data/spartan.db") == PROJECT_ROOT / "data" / "spartan.db"
    absolute = PROJECT_ROOT / "elsewhere" / "x.db"
    assert resolve_path(str(absolute)) == absolute


def test_every_error_code_has_the_status_in_the_api_table():
    table = {code: status for status, codes in STATUS_TABLE.items() for code in codes}
    assert {code: spec.status for code, spec in ERRORS.items()} == table


def test_app_error_body_shape():
    limited = AppError("daily_limit", message=daily_limit_message(2), retry_after_seconds=3600)
    assert limited.status == 429
    assert limited.to_body() == {"error": {"code": "daily_limit", "message": daily_limit_message(2), "retry_after_seconds": 3600}}
    assert AppError("not_found").to_body() == {"error": {"code": "not_found", "message": ERRORS["not_found"].message}}


def test_unknown_error_code_is_a_programming_error():
    with pytest.raises(ValueError):
        AppError("no_such_code")


def test_rename_request_forbids_extra_fields():
    assert RenameRequest.model_validate({"class_name": "CS 101"}).class_name == "CS 101"
    with pytest.raises(ValidationError):
        RenameRequest.model_validate({"class_name": "CS 101", "color": "#7AA2FF"})


# ---------------------------------------------------------------------------
# POST /api/syllabi: success
# ---------------------------------------------------------------------------
def test_text_upload_returns_201_with_counts_and_class_name(client, frozen_clock, sample_syllabus_text):
    response = post_text(client, sample_syllabus_text)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"syllabus", "items"}
    syllabus = body["syllabus"]
    assert set(syllabus) == SYLLABUS_KEYS
    assert type(syllabus["id"]) is int
    assert syllabus["class_name"] == CLASS_NAME
    assert syllabus["filename"] is None
    assert syllabus["created_at"] == "2026-11-15T21:30:05Z"
    assert counts(syllabus) == TEXT_COUNTS
    assert len(body["items"]) == 13


def test_upload_items_have_the_api_shape(uploaded, frozen_clock):
    for item in uploaded["items"]:
        assert set(item) == ITEM_KEYS
        assert type(item["id"]) is int
        assert item["syllabus_id"] == uploaded["syllabus"]["id"]
        assert item["status"] == "unchecked"
        assert type(item["date_was_ambiguous"]) is bool
        assert type(item["source_verified"]) is bool
        assert item["type"] in ITEM_TYPES
        assert ISO_UTC.match(item["created_at"])


def test_items_are_stamped_with_the_upload_time(client, frozen_clock, sample_syllabus_text):
    body = post_text(client, sample_syllabus_text).json()
    assert {item["created_at"] for item in body["items"]} == {"2026-11-15T21:30:05Z"}


def test_upload_items_match_the_cleaned_fixture(uploaded, sample_expected):
    # Keyed by title and date: the fixture has two "Final exam" items, one dated and one not.
    expected = {(item["title"], item["due_date"]): item for item in sample_expected["items"]}
    got = {(item["title"], item["due_date"]): item for item in uploaded["items"]}
    assert len(got) == len(uploaded["items"]) == len(sample_expected["items"])
    assert got.keys() == expected.keys()
    for key, item in got.items():
        for name in ("type", "due_date", "date_text", "weight", "date_was_ambiguous", "source_verified"):
            assert item[name] == expected[key][name], f"{key!r}: {name}"


def test_upload_items_are_dated_first_by_date_then_undated(uploaded):
    assert [item["title"] for item in uploaded["items"]] == EXPECTED_ORDER


def test_route_sends_normalized_text_and_today_to_the_extractor(client, frozen_clock, fake_extractor, sample_syllabus_text):
    messy = "  " + sample_syllabus_text.replace("\n", "\r\n") + "\r\n\r\n\r\n"
    assert post_text(client, messy).status_code == 201
    [(document, today)] = fake_extractor.calls
    assert document == sample_syllabus_text.strip()
    assert today == date(2026, 11, 15)


def test_pdf_upload_returns_201(client, fake_extractor, sample_pdf_bytes):
    response = post_pdf(client, sample_pdf_bytes)
    assert response.status_code == 201, response.text
    syllabus = response.json()["syllabus"]
    assert syllabus["filename"] == "cs101.pdf"
    assert syllabus["class_name"] == CLASS_NAME
    assert counts(syllabus) == PDF_COUNTS
    [(document, _today)] = fake_extractor.calls
    assert "Quiz 1 is on Thursday, September 10" in document


def test_docx_upload_returns_201(client, make_docx, sample_syllabus_text):
    data = make_docx(sample_syllabus_text.splitlines())
    response = post_file(client, "cs101.docx", data, DOCX_TYPE)
    assert response.status_code == 201, response.text
    syllabus = response.json()["syllabus"]
    assert syllabus["filename"] == "cs101.docx"
    assert counts(syllabus) == TEXT_COUNTS


def test_file_type_comes_from_its_name_and_bytes_not_the_browser(client, sample_pdf_bytes):
    assert post_file(client, "cs101.pdf", sample_pdf_bytes, "text/plain").status_code == 201


def test_file_with_blank_text_counts_as_just_the_file(client, sample_pdf_bytes):
    files = {"file": ("cs101.pdf", sample_pdf_bytes, "application/pdf"), "text": (None, b"   \n ")}
    assert client.post(API, files=files).status_code == 201


@pytest.mark.parametrize(
    "sent_name",
    ["folder/sub/cs101.pdf", "folder\\sub\\cs101.pdf", "C:\\fakepath\\cs101.pdf"],
    ids=["slash-path", "backslash-path", "browser-fakepath"],
)
def test_stored_filename_is_the_base_name_only(client, sample_pdf_bytes, sent_name):
    response = post_pdf(client, sample_pdf_bytes, filename=sent_name)
    assert response.status_code == 201, response.text
    assert response.json()["syllabus"]["filename"] == "cs101.pdf"


def test_stored_filename_is_at_most_255_characters(client, sample_pdf_bytes):
    response = post_pdf(client, sample_pdf_bytes, filename="a" * 300 + ".pdf")
    assert response.status_code == 201, response.text
    stored = response.json()["syllabus"]["filename"]
    assert 0 < len(stored) <= 255
    assert stored.startswith("a" * 200)


# ---------------------------------------------------------------------------
# Class names
# ---------------------------------------------------------------------------
def test_class_name_from_claude_is_cleaned(make_client, make_extractor, sample_syllabus_text):
    client = make_client(extractor=make_extractor(class_name="  CS 101:\n   Intro   to Programming  "))
    assert post_text(client, sample_syllabus_text).json()["syllabus"]["class_name"] == "CS 101: Intro to Programming"


def test_class_name_falls_back_to_the_file_name(make_client, make_extractor, sample_pdf_bytes):
    client = make_client(extractor=make_extractor(class_name=None))
    response = post_pdf(client, sample_pdf_bytes, filename="CS_146-Data__Structures  notes.pdf")
    assert response.json()["syllabus"]["class_name"] == "CS 146 Data Structures notes"


def test_blank_class_name_falls_back_to_the_file_name(make_client, make_extractor, sample_pdf_bytes):
    client = make_client(extractor=make_extractor(class_name="   "))
    assert post_pdf(client, sample_pdf_bytes, filename="cs101.pdf").json()["syllabus"]["class_name"] == "cs101"


def test_class_name_from_a_long_file_name_is_capped(make_client, make_extractor, sample_pdf_bytes):
    client = make_client(extractor=make_extractor(class_name=None))
    response = post_pdf(client, sample_pdf_bytes, filename="Very_long_class_name_" * 12 + ".pdf")
    class_name = response.json()["syllabus"]["class_name"]
    assert 0 < len(class_name) <= 120
    assert "_" not in class_name


def test_pasted_text_without_a_class_name_is_called_pasted_syllabus(make_client, make_extractor, sample_syllabus_text):
    client = make_client(extractor=make_extractor(class_name=None))
    assert post_text(client, sample_syllabus_text).json()["syllabus"]["class_name"] == "Pasted syllabus"


# ---------------------------------------------------------------------------
# X-Client-Id
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/syllabi"), ("GET", "/api/syllabi"), ("GET", "/api/items"), ("PATCH", "/api/syllabi/1")],
)
def test_missing_client_id_is_400(make_client, fake_extractor, method, path):
    anonymous = make_client(client_id=None)
    kwargs = {"json": {"class_name": "CS 101"}} if method == "PATCH" else {}
    assert_error(anonymous.request(method, path, **kwargs), 400, "missing_client_id")
    assert fake_extractor.calls == []


@pytest.mark.parametrize(
    "bad_id",
    [
        "not-a-uuid",
        "12345",
        "62d2be7b983742c983258f7737984f26",  # no dashes
        "{62d2be7b-9837-42c9-8325-8f7737984f26}",
        "urn:uuid:62d2be7b-9837-42c9-8325-8f7737984f26",
        "62d2be7b-9837-42c9-8325-8f7737984f2",  # one short
        "62d2be7b-9837-42c9-8325-8f7737984f26a",  # one long
        "62d2be7b-9837-42c9-8325-8f7737984g26",  # not hex
        "",
    ],
    ids=repr,
)
def test_malformed_client_id_is_400(client, fake_extractor, sample_syllabus_text, bad_id):
    assert_error(post_text(client, sample_syllabus_text, **as_client(bad_id)), 400, "missing_client_id")
    assert fake_extractor.calls == []


def test_client_id_is_checked_before_anything_else(make_client):
    anonymous = make_client(client_id=None)
    assert_error(anonymous.post(API), 400, "missing_client_id")  # not no_input


def test_uppercase_client_id_is_the_same_client(client, client_id, sample_syllabus_text):
    response = post_text(client, sample_syllabus_text, **as_client(client_id.upper()))
    assert response.status_code == 201, response.text
    listed = client.get("/api/syllabi").json()["syllabi"]  # default header is lowercase
    assert [syllabus["id"] for syllabus in listed] == [response.json()["syllabus"]["id"]]


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def test_no_input_is_400(client):
    assert_error(client.post(API), 400, "no_input")


def test_unrelated_fields_only_is_no_input(client):
    assert_error(client.post(API, files={"notes": (None, b"hello there")}), 400, "no_input")


@pytest.mark.parametrize("blank", ["", "   ", "\n\t \r\n"], ids=repr)
def test_blank_text_is_no_input(client, blank):
    assert_error(post_text(client, blank), 400, "no_input")


def test_file_and_text_together_is_two_inputs(client, fake_extractor, sample_pdf_bytes, sample_syllabus_text):
    files = {"file": ("cs101.pdf", sample_pdf_bytes, "application/pdf"), "text": (None, sample_syllabus_text.encode("utf-8"))}
    assert_error(client.post(API, files=files), 400, "two_inputs")
    assert fake_extractor.calls == []


def test_more_than_one_file_is_bad_request(client, fake_extractor, sample_pdf_bytes):
    files = [("file", ("a.pdf", sample_pdf_bytes, "application/pdf")), ("file", ("b.pdf", sample_pdf_bytes, "application/pdf"))]
    assert_error(client.post(API, files=files), 400, "bad_request")
    assert fake_extractor.calls == []


def test_more_than_five_fields_is_bad_request(client, sample_syllabus_text):
    files = [("text", (None, sample_syllabus_text.encode("utf-8")))] + [(f"extra{i}", (None, b"x")) for i in range(5)]
    assert_error(client.post(API, files=files), 400, "bad_request")


def test_five_fields_are_fine(client, sample_syllabus_text):
    files = [("text", (None, sample_syllabus_text.encode("utf-8")))] + [(f"extra{i}", (None, b"x")) for i in range(4)]
    assert client.post(API, files=files).status_code == 201


@pytest.mark.parametrize(
    ("filename", "data", "content_type"),
    [
        ("notes.txt", b"Quiz 1 is on Thursday, September 10, at the start of class.", "text/plain"),
        ("syllabus.pdf", b"This is plain text that someone named .pdf", "application/pdf"),
        ("syllabus.docx", b"This is plain text that someone named .docx", DOCX_TYPE),
        ("syllabus.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200, "application/msword"),
        ("syllabus.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "image/png"),
    ],
    ids=["txt", "fake-pdf", "fake-docx", "old-doc", "image"],
)
def test_unsupported_files_are_415(client, fake_extractor, filename, data, content_type):
    assert_error(post_file(client, filename, data, content_type), 415, "unsupported_type")
    assert fake_extractor.calls == []


def test_corrupt_pdf_is_unreadable_file(client, fake_extractor, sample_pdf_bytes):
    assert_error(post_pdf(client, sample_pdf_bytes[: len(sample_pdf_bytes) // 2]), 422, "unreadable_file")
    assert fake_extractor.calls == []


def test_short_pasted_text_is_text_too_short(client, fake_extractor):
    assert_error(post_text(client, "Quiz on Friday."), 422, "text_too_short")
    assert fake_extractor.calls == []


@pytest.mark.parametrize(("letters", "status"), [(49, 422), (50, 201)])
def test_minimum_length_counts_only_non_whitespace(client, letters, status):
    assert post_text(client, " ".join("a" * letters)).status_code == status


def test_blank_pdf_is_no_text_found(client, fake_extractor, blank_pdf_bytes):
    assert_error(post_pdf(client, blank_pdf_bytes, filename="scan.pdf"), 422, "no_text_found")
    assert fake_extractor.calls == []


def test_long_text_is_text_too_long(make_client, fake_extractor):
    client = make_client(max_text_chars=1000)
    assert_error(post_text(client, "a" * 1001), 413, "text_too_long")
    assert fake_extractor.calls == []


def test_text_length_is_measured_after_cleanup(make_client):
    client = make_client(max_text_chars=1000)
    assert post_text(client, "a" * 1000 + "\r\n\r\n\r\n   ").status_code == 201


def test_long_file_text_is_text_too_long(make_client, sample_pdf_bytes):
    client = make_client(max_text_chars=500)  # the fixture PDF has about 1,000 characters of text
    assert_error(post_pdf(client, sample_pdf_bytes), 413, "text_too_long")


def test_pdf_whose_pages_repeat_one_huge_stream_is_text_too_long(client, fake_extractor, spool_dir, shared_stream_pdf_bytes):
    assert_error(post_pdf(client, shared_stream_pdf_bytes), 413, "text_too_long")
    assert list(spool_dir.iterdir()) == []
    assert fake_extractor.calls == []


def test_text_field_over_1_mib_is_text_too_long(client, fake_extractor):
    assert_error(post_text(client, "word " * 220_000), 413, "text_too_long")
    assert fake_extractor.calls == []


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------
def test_body_over_10_mb_is_413_in_our_envelope(client, fake_extractor):
    assert_error(post_pdf(client, b"%PDF-1.7\n" + b"\x00" * (11 * MIB)), 413, "file_too_large")
    assert fake_extractor.calls == []


def test_file_just_over_10_mb_is_413_and_deleted(client, fake_extractor, spool_dir):
    data = b"%PDF-1.7\n" + b"\x00" * (10 * MIB + 1 - 9)
    assert len(data) == 10 * MIB + 1
    assert_error(post_pdf(client, data), 413, "file_too_large")
    assert list(spool_dir.iterdir()) == []
    assert fake_extractor.calls == []


def test_file_one_byte_over_the_limit_is_too_large(make_client, sample_pdf_bytes):
    client = make_client(max_upload_bytes=len(sample_pdf_bytes) - 1)
    assert_error(post_pdf(client, sample_pdf_bytes), 413, "file_too_large")


def test_file_exactly_at_the_limit_is_accepted(make_client, sample_pdf_bytes):
    client = make_client(max_upload_bytes=len(sample_pdf_bytes))
    assert post_pdf(client, sample_pdf_bytes).status_code == 201


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
def test_body_limit_counts_the_whole_request(make_client, fake_extractor, chunked):
    """A file exactly at max_upload_bytes plus 600 KiB of another field is over max_upload_bytes + 512 KiB."""
    limit = 64 * 1024
    client = make_client(max_upload_bytes=limit)
    files = [
        ("file", ("cs101.pdf", b"%PDF-1.7\n" + b"\x00" * (limit - 9), "application/pdf")),
        ("notes", (None, b"n" * (600 * 1024))),
    ]
    body, content_type = multipart_body(files)
    assert len(body) > limit + 512 * 1024
    if chunked:
        response = client.post(API, content=iter([body]), headers={"Content-Type": content_type})
        assert "content-length" not in response.request.headers
    else:
        response = client.post(API, content=body, headers={"Content-Type": content_type})
    assert_error(response, 413, "file_too_large")
    assert fake_extractor.calls == []


# ---------------------------------------------------------------------------
# Uploaded files are deleted (privacy rule 6)
# ---------------------------------------------------------------------------
def test_large_upload_is_deleted_before_claude_is_called(client, fake_extractor, spool_files, spool_dir, large_pdf_bytes):
    files_at_call: list[list[str]] = []
    fake_extractor.on_call = lambda text, today: files_at_call.append(sorted(p.name for p in spool_dir.iterdir()))
    response = post_pdf(client, large_pdf_bytes)
    assert response.status_code == 201, response.text
    assert files_at_call == [[]], "the upload must be closed (which deletes it) before Claude is called"
    assert list(spool_dir.iterdir()) == []
    rolled = [spool for spool in spool_files if spool.rolled]
    assert rolled, "an upload over 1 MiB should have been spooled to disk"
    assert all(spool.disk_path is None or spool.disk_path.parent == spool_dir for spool in rolled)
    assert all(spool.closed for spool in spool_files)


def test_failed_large_upload_is_deleted(client, fake_extractor, spool_files, spool_dir):
    junk = b"%PDF-1.7\n" + random.Random(1115).randbytes(1_300_000)
    assert_error(post_pdf(client, junk), 422, "unreadable_file")
    assert list(spool_dir.iterdir()) == []
    assert any(spool.rolled for spool in spool_files), "an upload over 1 MiB should have been spooled to disk"
    assert all(spool.closed for spool in spool_files)
    assert fake_extractor.calls == []


# ---------------------------------------------------------------------------
# Daily limit per client (counts saved syllabi in the database)
# ---------------------------------------------------------------------------
def test_daily_limit(make_client, frozen_clock, fake_extractor, sample_syllabus_text, other_client_id):
    client = make_client(daily_uploads_per_client=2)
    assert post_text(client, sample_syllabus_text).status_code == 201  # T0
    frozen_clock.advance(10)
    assert post_text(client, sample_syllabus_text).status_code == 201  # T0 + 10 s
    frozen_clock.advance(10)
    calls_before = len(fake_extractor.calls)
    response = post_text(client, sample_syllabus_text)  # T0 + 20 s
    error = assert_error(response, 429, "daily_limit", message=daily_limit_message(2))
    assert error["retry_after_seconds"] == WINDOW - 20  # the T0 upload leaves the window at T0 + 24 h
    assert response.headers["Retry-After"] == str(WINDOW - 20)
    assert len(fake_extractor.calls) == calls_before
    assert post_text(client, sample_syllabus_text, **as_client(other_client_id)).status_code == 201


def test_failed_uploads_do_not_count_toward_the_daily_limit(make_client, fake_extractor, sample_syllabus_text):
    client = make_client(daily_uploads_per_client=2)
    fake_extractor.fail_next(AppError("extraction_unavailable"))
    assert_error(post_text(client, sample_syllabus_text), 503, "extraction_unavailable")
    assert_error(post_text(client, "Too short."), 422, "text_too_short")
    assert post_text(client, sample_syllabus_text).status_code == 201
    assert post_text(client, sample_syllabus_text).status_code == 201
    assert_error(post_text(client, sample_syllabus_text), 429, "daily_limit", message=daily_limit_message(2))


def test_daily_limit_rolls_over_after_24_hours(make_client, frozen_clock, sample_syllabus_text):
    client = make_client(daily_uploads_per_client=2)
    assert post_text(client, sample_syllabus_text).status_code == 201  # T0
    frozen_clock.advance(10)
    assert post_text(client, sample_syllabus_text).status_code == 201  # T0 + 10 s
    frozen_clock.advance(WINDOW - 10)  # exactly T0 + 24 h: the T0 upload is still inside the window
    error = assert_error(post_text(client, sample_syllabus_text), 429, "daily_limit", message=daily_limit_message(2))
    assert error["retry_after_seconds"] == 1  # never less than 1
    frozen_clock.advance(1)
    assert post_text(client, sample_syllabus_text).status_code == 201


def test_daily_limit_is_checked_after_input_and_before_the_file(make_client, sample_syllabus_text):
    client = make_client(daily_uploads_per_client=1)
    assert post_text(client, sample_syllabus_text).status_code == 201
    assert_error(client.post(API), 400, "no_input")
    assert_error(post_file(client, "notes.txt", b"plain text", "text/plain"), 429, "daily_limit", message=daily_limit_message(1))


# ---------------------------------------------------------------------------
# Per-IP limit (in memory)
# ---------------------------------------------------------------------------
def test_network_limit_across_client_ids(make_client, fake_extractor, sample_syllabus_text, client_id, other_client_id, third_client_id):
    client = make_client(daily_uploads_per_ip=2)
    assert post_text(client, sample_syllabus_text, **as_client(client_id)).status_code == 201
    assert post_text(client, sample_syllabus_text, **as_client(other_client_id)).status_code == 201
    response = post_text(client, sample_syllabus_text, **as_client(third_client_id))
    error = assert_error(response, 429, "network_limit")
    assert type(error["retry_after_seconds"]) is int
    assert error["retry_after_seconds"] >= 1
    assert response.headers["Retry-After"] == str(error["retry_after_seconds"])
    assert len(fake_extractor.calls) == 2


def test_rejected_input_does_not_use_up_the_network_limit(make_client, sample_syllabus_text, other_client_id, third_client_id):
    client = make_client(daily_uploads_per_ip=2)
    for _ in range(3):
        assert_error(post_text(client, "Too short."), 422, "text_too_short")
    assert_error(post_file(client, "notes.txt", b"plain text", "text/plain"), 415, "unsupported_type")
    assert post_text(client, sample_syllabus_text).status_code == 201
    assert post_text(client, sample_syllabus_text, **as_client(other_client_id)).status_code == 201
    assert_error(post_text(client, sample_syllabus_text, **as_client(third_client_id)), 429, "network_limit")


def test_failed_extractions_count_toward_the_network_limit(make_client, fake_extractor, sample_syllabus_text, other_client_id, third_client_id):
    client = make_client(daily_uploads_per_ip=2)
    fake_extractor.fail_next(AppError("extraction_unavailable"))
    fake_extractor.fail_next(AppError("extraction_unavailable"))
    assert_error(post_text(client, sample_syllabus_text), 503, "extraction_unavailable")
    assert_error(post_text(client, sample_syllabus_text, **as_client(other_client_id)), 503, "extraction_unavailable")
    assert_error(post_text(client, sample_syllabus_text, **as_client(third_client_id)), 429, "network_limit")
    assert len(fake_extractor.calls) == 2


def test_network_limit_lives_in_memory_only(make_client, sample_syllabus_text, other_client_id):
    first = make_client(daily_uploads_per_ip=1)
    assert post_text(first, sample_syllabus_text).status_code == 201
    assert_error(post_text(first, sample_syllabus_text, **as_client(other_client_id)), 429, "network_limit")
    restarted = make_client(daily_uploads_per_ip=1)  # same database, new process state
    assert post_text(restarted, sample_syllabus_text, **as_client(other_client_id)).status_code == 201


# ---------------------------------------------------------------------------
# SlidingWindowLimiter (backend/services/rate_limit.py)
# ---------------------------------------------------------------------------
class FakeTime:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_the_limit_then_says_when_to_retry(rate_limit):
    now = FakeTime()
    limiter = rate_limit.SlidingWindowLimiter(2, 100, clock=now)
    assert limiter.hit("203.0.113.7") is None  # t=1000
    now.now = 1010.0
    assert limiter.hit("203.0.113.7") is None
    now.now = 1020.0
    retry = limiter.hit("203.0.113.7")
    assert type(retry) is int
    assert retry in (80, 81)  # the t=1000 attempt leaves the window at t=1100


def test_limiter_does_not_record_rejected_attempts(rate_limit):
    now = FakeTime()
    limiter = rate_limit.SlidingWindowLimiter(2, 100, clock=now)
    limiter.hit("ip")  # t=1000
    now.now = 1010.0
    limiter.hit("ip")
    now.now = 1020.0
    assert limiter.hit("ip") is not None  # rejected, so not recorded
    now.now = 1101.0
    assert limiter.hit("ip") is None  # only the t=1010 attempt is still in the window
    now.now = 1102.0
    assert limiter.hit("ip") is not None  # t=1010 and t=1101 fill it again


def test_limiter_keys_are_independent(rate_limit):
    limiter = rate_limit.SlidingWindowLimiter(1, 100, clock=FakeTime())
    assert limiter.hit("a") is None
    assert limiter.hit("b") is None
    assert limiter.hit("a") is not None


def test_limiter_retry_after_is_at_least_one_second(rate_limit):
    now = FakeTime()
    limiter = rate_limit.SlidingWindowLimiter(1, 10, clock=now)
    limiter.hit("ip")
    now.now += 9.8
    assert limiter.hit("ip") == 1


def test_limiter_is_thread_safe(rate_limit):
    limiter = rate_limit.SlidingWindowLimiter(10, 3600)
    start = threading.Barrier(20)
    results: list[int | None] = []
    results_lock = threading.Lock()

    def worker() -> None:
        start.wait()
        for _ in range(5):
            outcome = limiter.hit("198.51.100.4")
            with results_lock:
                results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(None) == 10
    assert all(type(outcome) is int and outcome >= 1 for outcome in results if outcome is not None)


# ---------------------------------------------------------------------------
# Extraction errors
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code", ["extraction_unavailable", "extraction_failed", "extraction_refused", "extraction_too_long", "extraction_not_configured"]
)
def test_extractor_errors_pass_through_and_nothing_is_saved(client, fake_extractor, sample_syllabus_text, code):
    fake_extractor.fail_next(AppError(code))
    assert_error(post_text(client, sample_syllabus_text), ERRORS[code].status, code)
    assert client.get("/api/syllabi").json() == {"syllabi": []}
    assert client.get("/api/items").json() == {"items": []}


def test_extractor_error_keeps_its_own_message(client, fake_extractor, sample_syllabus_text):
    message = "I'm not set up to read syllabi yet: the server's API key didn't work."
    fake_extractor.fail_next(AppError("extraction_not_configured", message=message))
    assert_error(post_text(client, sample_syllabus_text), 503, "extraction_not_configured", message=message)


def test_unexpected_error_is_a_500_envelope_and_nothing_is_saved(make_client, fake_extractor, sample_syllabus_text):
    client = make_client(raise_server_exceptions=False)
    fake_extractor.fail_next(RuntimeError("boom"))
    assert_error(post_text(client, sample_syllabus_text), 500, "internal_error")
    assert client.get("/api/syllabi").json() == {"syllabi": []}


def test_unexpected_error_does_not_escape_the_app(client, fake_extractor, sample_syllabus_text):
    """If an exception escapes the ASGI app, uvicorn logs its message and traceback, which can hold
    syllabus text. Starlette re-raises after a plain ``exception_handler(Exception)`` 500, and this
    TestClient (raise_server_exceptions=True) would then raise here instead of returning a response."""
    fake_extractor.fail_next(RuntimeError(f"boom {PRIVATE}"))
    assert_error(post_text(client, sample_syllabus_text), 500, "internal_error")


# ---------------------------------------------------------------------------
# GET /api/syllabi, GET /api/items, client isolation
# ---------------------------------------------------------------------------
def test_upload_response_matches_the_lists(client, uploaded):
    assert client.get("/api/syllabi").json() == {"syllabi": [uploaded["syllabus"]]}
    assert client.get("/api/items").json() == {"items": uploaded["items"]}


def test_syllabi_are_listed_oldest_first(client, sample_syllabus_text, sample_pdf_bytes):
    ids = [
        post_text(client, sample_syllabus_text).json()["syllabus"]["id"],
        post_pdf(client, sample_pdf_bytes).json()["syllabus"]["id"],
        post_text(client, sample_syllabus_text).json()["syllabus"]["id"],
    ]
    listed = client.get("/api/syllabi").json()["syllabi"]
    assert [syllabus["id"] for syllabus in listed] == ids == sorted(ids)


def test_items_from_several_syllabi_are_ordered_by_date_then_syllabus(client, sample_syllabus_text, sample_pdf_bytes):
    first = post_text(client, sample_syllabus_text).json()["syllabus"]["id"]
    second = post_pdf(client, sample_pdf_bytes).json()["syllabus"]["id"]
    items = client.get("/api/items").json()["items"]
    assert len(items) == 26
    keys = [(item["due_date"] is None, item["due_date"] or "", item["syllabus_id"], item["id"]) for item in items]
    assert keys == sorted(keys)
    assert [(item["title"], item["syllabus_id"]) for item in items[:2]] == [("Quiz 1", first), ("Quiz 1", second)]
    assert sum(item["due_date"] is None for item in items) == 14


def test_other_clients_see_nothing(client, uploaded, other_client_id):
    other = as_client(other_client_id)
    assert client.get("/api/syllabi", **other).json() == {"syllabi": []}
    assert client.get("/api/items", **other).json() == {"items": []}
    syllabus_id = uploaded["syllabus"]["id"]
    assert_error(client.patch(f"{API}/{syllabus_id}", json={"class_name": "Not mine"}, **other), 404, "not_found")
    assert client.get("/api/syllabi").json()["syllabi"][0]["class_name"] == CLASS_NAME
    assert len(client.get("/api/items").json()["items"]) == 13


# ---------------------------------------------------------------------------
# PATCH /api/syllabi/{id}
# ---------------------------------------------------------------------------
def test_rename_collapses_whitespace_and_trims(client, uploaded):
    syllabus_id = uploaded["syllabus"]["id"]
    response = client.patch(f"{API}/{syllabus_id}", json={"class_name": "  CS 101 \n  Intro   to Python  "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"syllabus"}
    assert body["syllabus"] == {**uploaded["syllabus"], "class_name": "CS 101 Intro to Python"}
    assert client.get("/api/syllabi").json()["syllabi"] == [body["syllabus"]]


def test_rename_allows_exactly_120_characters(client, uploaded):
    name = "x" * 120
    response = client.patch(f"{API}/{uploaded['syllabus']['id']}", json={"class_name": name})
    assert response.status_code == 200, response.text
    assert response.json()["syllabus"]["class_name"] == name


@pytest.mark.parametrize("name", ["", "   ", "\n\t", "x" * 121], ids=["empty", "spaces", "newline-tab", "121-chars"])
def test_rename_rejects_empty_or_long_names(client, uploaded, name):
    response = client.patch(f"{API}/{uploaded['syllabus']['id']}", json={"class_name": name})
    assert_error(response, 400, "invalid_class_name")
    assert client.get("/api/syllabi").json()["syllabi"][0]["class_name"] == CLASS_NAME


@pytest.mark.parametrize(
    "payload",
    [{"class_name": "CS 101", "color": "#7AA2FF"}, {}, {"class_name": 5}, {"name": "CS 101"}, ["CS 101"]],
    ids=["extra-field", "empty", "not-a-string", "wrong-key", "not-an-object"],
)
def test_rename_with_a_bad_body_is_validation_error(client, uploaded, payload):
    error = assert_error(client.patch(f"{API}/{uploaded['syllabus']['id']}", json=payload), 422, "validation_error")
    assert set(error) == {"code", "message"}  # no pydantic details


def test_rename_with_broken_json_is_validation_error(client, uploaded):
    response = client.patch(f"{API}/{uploaded['syllabus']['id']}", content=b"{not json", headers={"Content-Type": "application/json"})
    assert_error(response, 422, "validation_error")


def test_rename_unknown_syllabus_is_not_found(client):
    assert_error(client.patch(f"{API}/999999", json={"class_name": "CS 101"}), 404, "not_found")


def test_rename_with_a_non_numeric_id_is_validation_error(client):
    assert_error(client.patch(f"{API}/abc", json={"class_name": "CS 101"}), 422, "validation_error")


# ---------------------------------------------------------------------------
# Every error is our envelope
# ---------------------------------------------------------------------------
def test_unknown_api_path_is_404_envelope(client):
    assert_error(client.get("/api/does-not-exist"), 404, "not_found")


def test_unknown_page_is_404_envelope(client):
    assert_error(client.get("/no-such-page.html"), 404, "not_found")


def test_wrong_method_is_405_envelope(client):
    assert_error(client.delete(API), 405, "method_not_allowed")


# ---------------------------------------------------------------------------
# Privacy: responses and logs
# ---------------------------------------------------------------------------
def test_no_response_contains_the_client_id(client, client_id, sample_syllabus_text):
    responses = [post_text(client, sample_syllabus_text)]
    syllabus_id = responses[0].json()["syllabus"]["id"]
    responses += [
        client.get("/api/syllabi"),
        client.get("/api/items"),
        client.patch(f"{API}/{syllabus_id}", json={"class_name": "CS 101"}),
        client.patch(f"{API}/{syllabus_id}", json={"class_name": ""}),
        client.patch(f"{API}/999999", json={"class_name": "CS 101"}),
        client.patch(f"{API}/{syllabus_id}", json={"class_name": "CS 101", "extra": True}),
        client.post(API),
        post_text(client, "Too short."),
        client.get("/api/does-not-exist"),
    ]
    for response in responses:
        assert client_id not in response.text
        assert client_id.upper() not in response.text
        assert "client_id" not in response.text
        assert client_id not in str(response.headers)


def test_documented_run_commands_keep_the_access_log_off():
    """uvicorn's access log puts the visitor's IP address on every line, so every documented way to run the app turns it off."""
    main = importlib.import_module("backend.main")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    commands = [
        line.strip()
        for line in (main.__doc__ or "").splitlines() + readme.splitlines()
        if "uvicorn backend.main:app" in line
    ]
    assert len(commands) >= 3  # main.py's docstring, README's Run section and its other-port example
    for command in commands:
        assert "--no-access-log" in command, command


def test_logs_hold_no_private_data(client, captured_logs, client_id, fake_extractor, make_settings, sample_syllabus_text, sample_pdf_bytes):
    filename = "Rivera-CS101-private.pdf"
    assert post_text(client, sample_syllabus_text).status_code == 201
    assert post_pdf(client, sample_pdf_bytes, filename=filename).status_code == 201
    fake_extractor.fail_next(AppError("extraction_failed"))
    assert post_text(client, sample_syllabus_text).status_code == 502
    assert post_text(client, "Too short.").status_code == 422
    assert post_file(client, "secret-notes.txt", b"plain", "text/plain").status_code == 415
    assert client.patch(f"{API}/1", json={"class_name": "CS 101", "secret": PRIVATE}).status_code == 422
    assert client.patch(f"{API}/1", json={"class_name": f"Renamed {PRIVATE}"}).status_code == 200
    client.get("/api/syllabi")
    client.get("/api/items")

    ours = captured_logs.ours()
    text = captured_logs.text(ours)
    forbidden = [
        client_id, client_id.upper(), "testclient",  # client ID, client IP (TestClient's host) and user agent
        filename, "secret-notes", CLASS_NAME, "Introduction to Programming", PRIVATE,
        "Quiz 1 is on Thursday", "Why Programs Fail", "Homework 4 due",
        make_settings().anthropic_api_key,
    ]
    for value in forbidden:
        assert value not in text, f"{value!r} appeared in a log line"
    for record in ours:
        assert record.name == "spartan" or record.name.startswith("spartan."), f"log from logger {record.name!r}; use a spartan.* logger"
    assert "extraction_finished" in text
    assert "items=13" in text
    assert "ms=" in text


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# Words that must never appear in a column name (privacy rules 1-5: no multiplier, hours,
# block durations, identity or health data on the server).
BANNED_COLUMN_WORDS = {
    "multiplier", "extended", "hour", "hours", "duration", "minutes", "accommodation",
    "diagnosis", "health", "email", "ip", "address", "user", "student",
}


@pytest.fixture(scope="module")
def db_connection():
    return importlib.import_module("backend.db.connection")


def test_startup_creates_the_database_and_runs_migrations(make_client, tmp_path):
    make_client()
    db_path = tmp_path / "db" / "test.db"
    assert db_path.is_file()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        columns = {
            f"{table}.{row[1]}": row[1] for table in tables for row in conn.execute(f"PRAGMA table_info({table})")
        }
    assert {"syllabi", "items"} <= tables
    for qualified, column in columns.items():
        assert not BANNED_COLUMN_WORDS & set(column.lower().split("_")), f"column {qualified} looks like private data"


def test_connect_is_ready_for_fastapi_threads(db_connection, tmp_path):
    path = tmp_path / "nested" / "folder" / "spartan.db"
    db_connection.init_db(path)  # creates the parent folders
    assert path.is_file()
    with contextlib.closing(db_connection.connect(path)) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        errors: list[Exception] = []

        def use_from_another_thread() -> None:
            try:
                conn.execute("SELECT COUNT(*) FROM syllabi").fetchone()
            except Exception as exc:  # reported by the assert below, on the main thread
                errors.append(exc)

        worker = threading.Thread(target=use_from_another_thread)
        worker.start()
        worker.join()
        assert errors == [], "connections must allow use from FastAPI's threadpool (check_same_thread=False)"


def test_init_db_twice_is_harmless(db_connection, tmp_path):
    path = tmp_path / "db" / "twice.db"
    db_connection.init_db(path)
    db_connection.init_db(path)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_init_db_only_applies_migrations_newer_than_user_version(db_connection, tmp_path):
    path = tmp_path / "db" / "already-current.db"
    path.parent.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 2")
    db_connection.init_db(path)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "syllabi" not in tables, "every migration must be skipped when user_version is already the newest"


def test_syllabus_row_records_the_model_and_prompt_version(client, tmp_path, client_id, sample_syllabus_text):
    assert post_text(client, sample_syllabus_text).status_code == 201
    with contextlib.closing(sqlite3.connect(tmp_path / "db" / "test.db")) as conn:
        row = conn.execute("SELECT client_id, class_name, filename, extraction_model, prompt_version FROM syllabi").fetchone()
    assert row == (client_id, CLASS_NAME, None, "fake-model", "v1")


def test_syllabi_survive_an_app_restart(make_client, sample_syllabus_text):
    first = make_client()
    created = post_text(first, sample_syllabus_text).json()
    restarted = make_client()
    assert restarted.get("/api/syllabi").json() == {"syllabi": [created["syllabus"]]}
    assert restarted.get("/api/items").json() == {"items": created["items"]}


# ---------------------------------------------------------------------------
# Static files and docs
# ---------------------------------------------------------------------------
def test_root_serves_html_without_a_client_id(make_client):
    response = make_client(client_id=None).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_javascript_is_served_as_javascript(client):
    response = client.get("/js/app.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_css_is_served_as_css(client):
    response = client.get("/css/base.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_docs_page_is_available_in_build_1(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_real_frontend_index_is_served(make_client):
    if not (FRONTEND_DIR / "index.html").is_file():
        pytest.skip("frontend/index.html isn't written yet")
    response = make_client(frontend_dir=FRONTEND_DIR, client_id=None).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_real_frontend_javascript_content_type(make_client):
    if not (FRONTEND_DIR / "js" / "app.js").is_file():
        pytest.skip("frontend/js/app.js isn't written yet")
    response = make_client(frontend_dir=FRONTEND_DIR, client_id=None).get("/js/app.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
