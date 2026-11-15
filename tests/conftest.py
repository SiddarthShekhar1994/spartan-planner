"""Shared test setup for Spartan Planner.

Everything here runs offline:
- An autouse guard blocks real Claude calls and real network calls in every test that is not
  marked ``live``. A blocked attempt raises, and the test is failed at teardown even if the code
  under test swallowed the exception.
- API tests get a fake extractor that returns the fixture's model output, cleaned against the
  text the route sends it. Claude is never called.

Modules under test are loaded through fixtures (``source_check``, ``dates``, ``postprocess``,
``text_extraction``, ``extraction``, ``rate_limit``) instead of being imported at the top of each
test file. If one module is missing or broken, only the tests that use it fail; the rest of the
suite still runs and reports.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import os
import random
import tempfile
import zlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import docx
import httpx2
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from backend import clock
from backend.config import PROJECT_ROOT, Settings
from backend.schemas import ExtractionResult, ModelOutput

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
BACKEND_DIR = PROJECT_ROOT / "backend"

MIB = 1024 * 1024
TEST_API_KEY = "test-key-not-real"
TEST_MODEL = "claude-haiku-5-5"
TEST_CLIENT_ID = "62d2be7b-9837-42c9-8325-8f7737984f26"
OTHER_CLIENT_ID = "81af41fd-3235-44d6-83d9-1667418ac604"
THIRD_CLIENT_ID = "2f755841-6568-4838-81b7-d51afe7546db"
FROZEN_NOW = datetime(2026, 11, 15, 21, 30, 5, tzinfo=timezone.utc)
FROZEN_TODAY = date(2026, 11, 15)


# ---------------------------------------------------------------------------
# Fixture files
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sample_syllabus_text() -> str:
    """tests/fixtures/sample_syllabus.txt: curly quotes, en dashes, one sentence split over two lines."""
    return (FIXTURES_DIR / "sample_syllabus.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sample_model_output_json() -> str:
    """The fake Claude reply, as the raw JSON text Claude would send."""
    return (FIXTURES_DIR / "sample_model_output.json").read_text(encoding="utf-8")


@pytest.fixture
def sample_model_output(sample_model_output_json: str) -> ModelOutput:
    """The fake Claude reply, parsed. Function-scoped so a test can't change it for another test."""
    return ModelOutput.model_validate_json(sample_model_output_json)


@pytest.fixture(scope="session")
def sample_expected() -> dict:
    """What clean_items must produce from the two fixtures above."""
    return json.loads((FIXTURES_DIR / "sample_expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    """A real one-page PDF printed by Edge from sample_syllabus.html."""
    return (FIXTURES_DIR / "sample_syllabus.pdf").read_bytes()


# ---------------------------------------------------------------------------
# Documents built at test time
# ---------------------------------------------------------------------------
def _pdf_bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def blank_pdf_bytes() -> bytes:
    """A valid PDF with one empty page (what a scan without OCR looks like to a text extractor)."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    return _pdf_bytes(writer)


@pytest.fixture(scope="session")
def large_pdf_bytes(sample_pdf_bytes: bytes) -> bytes:
    """The fixture page plus a ~1.5 MB attachment, so Starlette spools the upload to disk (> 1 MiB)."""
    writer = PdfWriter(clone_from=io.BytesIO(sample_pdf_bytes))
    writer.add_attachment("padding.bin", random.Random(20261115).randbytes(1_500_000))
    data = _pdf_bytes(writer)
    assert len(data) > MIB + 100_000, "the large PDF must be well over Starlette's 1 MiB spool size"
    return data


def build_shared_stream_pdf(pages: int, *, lines: int, line_chars: int = 1000) -> bytes:
    """A PDF whose pages all draw the same compressed content stream of ``lines`` lines of text.

    The file stays a few KB however many pages it has, but every page's text is the whole stream,
    so the text grows with each page added (the PDF version of a zip bomb).
    """
    content = b"BT /F1 1 Tf 1 TL 0 0 Td\n" + (b"(" + b"B" * line_chars + b") Tj T*\n") * lines + b"ET\n"
    stream = zlib.compress(content, 9)
    kids = b" ".join(b"%d 0 R" % (6 + page) for page in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % pages,
        b"<< /Font << /F1 4 0 R >> >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    objects += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources 3 0 R /Contents 5 0 R >>"] * pages
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return bytes(out)


@pytest.fixture(scope="session")
def shared_stream_pdf_bytes() -> bytes:
    """30 pages that each repeat one ~100,000-character stream: about 3 million characters from a tiny file."""
    return build_shared_stream_pdf(30, lines=100)


@pytest.fixture(scope="session")
def fixture_pdf_page_text(sample_pdf_bytes: bytes) -> str:
    """What pypdf itself reads from the fixture page (used to check the module joins pages correctly)."""
    return PdfReader(io.BytesIO(sample_pdf_bytes)).pages[0].extract_text()


TableRows = Sequence[Sequence[str | None]]


def build_docx(blocks: Sequence[str | TableRows], *, header: str | None = None) -> bytes:
    """Build a .docx in memory with python-docx.

    ``blocks`` are body content in order: a ``str`` is a paragraph, a list of rows is a table.
    In a table row, ``None`` means "this cell is merged into the cell on its left" (a horizontal
    merge), so ``["Week 9", "Oct 19", "Homework 4 due", None]`` makes the last two grid cells one cell.
    """
    document = docx.Document()
    if header is not None:
        section_header = document.sections[0].header
        section_header.is_linked_to_previous = False
        section_header.paragraphs[0].text = header
    for block in blocks:
        if isinstance(block, str):
            document.add_paragraph(block)
            continue
        rows = list(block)
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        for row_index, values in enumerate(rows):
            cells = table.rows[row_index].cells
            start = 0
            while start < len(values):
                end = start
                while end + 1 < len(values) and values[end + 1] is None:
                    end += 1
                cell = cells[start] if end == start else cells[start].merge(cells[end])
                cell.text = values[start] or ""
                start = end + 1
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def make_docx() -> Callable[..., bytes]:
    """``make_docx(blocks, header=...)`` -> .docx bytes. See ``build_docx``."""
    return build_docx


# ---------------------------------------------------------------------------
# Modules under test (loaded lazily, see the module docstring)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def source_check() -> ModuleType:
    return importlib.import_module("backend.services.source_check")


@pytest.fixture(scope="session")
def dates() -> ModuleType:
    return importlib.import_module("backend.services.dates")


@pytest.fixture(scope="session")
def postprocess() -> ModuleType:
    return importlib.import_module("backend.services.postprocess")


@pytest.fixture(scope="session")
def text_extraction() -> ModuleType:
    return importlib.import_module("backend.services.text_extraction")


@pytest.fixture(scope="session")
def extraction() -> ModuleType:
    return importlib.import_module("backend.services.extraction")


@pytest.fixture(scope="session")
def rate_limit() -> ModuleType:
    return importlib.import_module("backend.services.rate_limit")


# ---------------------------------------------------------------------------
# Guard: no real Claude calls, no real network
# ---------------------------------------------------------------------------
@dataclass
class RealCallGuard:
    """What the autouse guard blocked, plus the real ``make_client`` for the one test that inspects it."""

    attempts: list[str] = field(default_factory=list)
    original_make_client: Callable | None = None


@pytest.fixture(autouse=True)
def no_real_claude(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[RealCallGuard | None]:
    """Fail loudly if a test that isn't marked ``live`` tries to build a real client or open a socket."""
    if request.node.get_closest_marker("live") is not None:
        yield None
        return

    guard = RealCallGuard()

    def refuse_network(self: httpx2.HTTPTransport, http_request: httpx2.Request) -> httpx2.Response:
        guard.attempts.append(f"network request to {http_request.url.host}")
        raise RuntimeError("real network call attempted in a test")

    # Every real httpx2 client (the Anthropic SDK's included) sends through HTTPTransport.
    # MockTransport and Starlette's TestClient transport are separate classes, so tests still work.
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse_network)

    try:
        extraction_module = importlib.import_module("backend.services.extraction")
    except ImportError:
        extraction_module = None  # not written yet: the tests that need it fail on their own
    if extraction_module is not None and hasattr(extraction_module, "make_client"):
        guard.original_make_client = extraction_module.make_client

        def refuse_client(*args: object, **kwargs: object) -> None:
            guard.attempts.append("make_client")
            raise RuntimeError("real Claude call attempted in a test")

        monkeypatch.setattr(extraction_module, "make_client", refuse_client)

    yield guard

    assert not guard.attempts, f"real Claude call attempted in a test: {guard.attempts}"


# ---------------------------------------------------------------------------
# Fake extractor and the app under test
# ---------------------------------------------------------------------------
class FakeExtractor:
    """Stands in for ``run_extraction`` in API tests.

    Returns the fixture's model output, cleaned against the exact text the route sends, and records
    every call. ``fail_next(error)`` queues an exception for the next call. ``on_call`` lets a test
    look at the world at the moment Claude would be called (for example, the upload spool folder).
    """

    def __init__(self, output: ModelOutput) -> None:
        self.output = output
        self.calls: list[tuple[str, date]] = []
        self.errors: list[BaseException] = []
        self.on_call: Callable[[str, date], None] | None = None

    def fail_next(self, error: BaseException) -> None:
        self.errors.append(error)

    def __call__(self, document_text: str, today: date) -> ExtractionResult:
        self.calls.append((document_text, today))
        if self.on_call is not None:
            self.on_call(document_text, today)
        if self.errors:
            raise self.errors.pop(0)
        postprocess_module = importlib.import_module("backend.services.postprocess")
        return ExtractionResult(
            class_name=self.output.class_name,
            items=postprocess_module.clean_items(self.output.items, document_text),
            model="fake-model",
            prompt_version="v1",
        )


@pytest.fixture
def make_extractor(sample_model_output: ModelOutput) -> Callable[..., FakeExtractor]:
    """``make_extractor(class_name=None)`` -> a FakeExtractor whose model output has those fields replaced."""

    def _make(**output_overrides: object) -> FakeExtractor:
        output = sample_model_output.model_copy(update=output_overrides) if output_overrides else sample_model_output
        return FakeExtractor(output)

    return _make


@pytest.fixture
def fake_extractor(make_extractor: Callable[..., FakeExtractor]) -> FakeExtractor:
    """The extractor the default ``client`` uses."""
    return make_extractor()


@pytest.fixture
def stub_frontend(tmp_path: Path) -> Path:
    """A tiny frontend folder, so API tests don't depend on the real frontend being finished."""
    root = tmp_path / "frontend"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "index.html").write_text(
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Stub</title></head>'
        '<body><main id="main" tabindex="-1">stub</main></body></html>\n',
        encoding="utf-8",
    )
    (root / "js" / "app.js").write_text("export const stub = true;\n", encoding="utf-8")
    (root / "css" / "base.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    return root


@pytest.fixture
def make_settings(tmp_path: Path, stub_frontend: Path) -> Callable[..., Settings]:
    """``make_settings(**overrides)`` -> Settings with a fake key, a fresh database under tmp_path, and the stub frontend."""

    def _make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "anthropic_api_key": TEST_API_KEY,
            "claude_model": TEST_MODEL,
            "database_path": tmp_path / "db" / "test.db",
            "frontend_dir": stub_frontend,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def client_id() -> str:
    return TEST_CLIENT_ID


@pytest.fixture
def other_client_id() -> str:
    return OTHER_CLIENT_ID


@pytest.fixture
def third_client_id() -> str:
    return THIRD_CLIENT_ID


@pytest.fixture
def make_client(
    make_settings: Callable[..., Settings], fake_extractor: FakeExtractor
) -> Iterator[Callable[..., TestClient]]:
    """``make_client(extractor=None, client_id=..., raise_server_exceptions=True, **settings_overrides)``.

    Builds ``create_app(settings, extractor=...)`` and enters a TestClient (so the lifespan runs).
    Every request carries ``X-Client-Id`` unless ``client_id=None``. Clients made in one test share
    one database file, which is how restart tests work.
    """
    with contextlib.ExitStack() as stack:

        def _make(
            *,
            extractor: Callable[[str, date], ExtractionResult] | None = None,
            client_id: str | None = TEST_CLIENT_ID,
            raise_server_exceptions: bool = True,
            **overrides: object,
        ) -> TestClient:
            main = importlib.import_module("backend.main")
            settings = make_settings(**overrides)
            app = main.create_app(settings, extractor=extractor if extractor is not None else fake_extractor)
            headers = {"X-Client-Id": client_id} if client_id else {}
            test_client = TestClient(app, headers=headers, raise_server_exceptions=raise_server_exceptions)
            stack.enter_context(test_client)
            return test_client

        yield _make


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    """The app with default settings and the default fake extractor, as TEST_CLIENT_ID."""
    return make_client()


# ---------------------------------------------------------------------------
# Time, temp files, logs
# ---------------------------------------------------------------------------
class FrozenClock:
    """Replaces ``backend.clock.now_utc`` / ``today_local``. ``advance(seconds)`` moves time forward."""

    def __init__(self, start: datetime, today: date) -> None:
        self.now = start
        self.today = today

    def now_utc(self) -> datetime:
        return self.now

    def today_local(self) -> date:
        return self.today

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    """Freeze time at 2026-11-15T21:30:05Z (today 2026-11-15) for code that uses ``backend.clock``."""
    frozen = FrozenClock(FROZEN_NOW, FROZEN_TODAY)
    monkeypatch.setattr(clock, "now_utc", frozen.now_utc)
    monkeypatch.setattr(clock, "today_local", frozen.today_local)
    return frozen


@pytest.fixture
def spool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty folder that every temp file goes to (Starlette spools uploads over 1 MiB there)."""
    folder = tmp_path / "spool"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


class LogCapture(logging.Handler):
    """Collects every log record, from every logger, at every level."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self._seen: set[int] = set()
        self._formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")

    def emit(self, record: logging.LogRecord) -> None:
        if id(record) not in self._seen:  # the handler sits on two loggers; keep each record once
            self._seen.add(id(record))
            self.records.append(record)

    def ours(self) -> list[logging.LogRecord]:
        """Records from our code: a ``spartan.*`` logger, or emitted from a file under backend/."""
        backend_dir = os.path.normcase(str(BACKEND_DIR))
        return [
            record
            for record in self.records
            if record.name == "spartan"
            or record.name.startswith("spartan.")
            or os.path.normcase(record.pathname).startswith(backend_dir)
        ]

    def text(self, records: Sequence[logging.LogRecord] | None = None) -> str:
        """Each record fully formatted (message plus any traceback), one per line."""
        chosen = self.ours() if records is None else records
        return "\n".join(self._formatter.format(record) for record in chosen)


@pytest.fixture
def captured_logs() -> Iterator[LogCapture]:
    """Capture log records at DEBUG from the root logger and the ``spartan`` tree."""
    handler = LogCapture()
    loggers = [logging.getLogger(), logging.getLogger("spartan")]
    saved_levels = [(logger, logger.level) for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        for logger, level in saved_levels:
            logger.removeHandler(handler)
            logger.setLevel(level)
