"""Upload a syllabus, list this browser's syllabi, rename one.

Uploads are read in a fixed order (see ``upload_syllabus``): cheap checks first, the uploaded
file is closed (which deletes Starlette's temporary copy) before Claude is called, and nothing
is saved unless extraction succeeds. Log lines carry counts and timings only: never syllabus
text, file names, client IDs or IP addresses.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from backend import clock
from backend.config import Settings
from backend.db.repository import (
    create_syllabus,
    get_syllabus,
    list_items,
    list_syllabi,
    recent_upload_stats,
    rename_syllabus,
)
from backend.errors import AppError
from backend.routes.deps import (
    Extractor,
    app_settings,
    client_ip,
    get_db,
    get_extractor,
    get_ip_limiter,
    require_client_id,
)
from backend.schemas import RenameRequest, SyllabusListResponse, SyllabusResponse, UploadResponse
from backend.services.postprocess import clean_class_name
from backend.services.rate_limit import SlidingWindowLimiter
from backend.services.text_extraction import detect_kind, extract_text, meaningful_length, normalize_text

logger = logging.getLogger("spartan.upload")

# Form parsing caps for this router. max_part_size applies to non-file fields (the pasted text);
# file parts are spooled to a temporary file and size-checked in the route.
MAX_FORM_FILES = 1
MAX_FORM_FIELDS = 5
MAX_FORM_PART_BYTES = 1024 * 1024  # 1 MiB

HEAD_BYTES = 1024  # enough to see a PDF or DOCX signature
MAX_STORED_FILENAME_CHARS = 255
MAX_DERIVED_CLASS_NAME_CHARS = 120
PASTED_CLASS_NAME = "Pasted syllabus"
MAX_ROW_ID = 2**63 - 1  # SQLite's largest integer; bigger path ids can't exist (and would overflow)


class CappedFormRequest(Request):
    """A request whose form parser accepts at most one file, five fields, and 1 MiB per field."""

    def form(
        self,
        *,
        max_files: int | float = MAX_FORM_FILES,
        max_fields: int | float = MAX_FORM_FIELDS,
        max_part_size: int = MAX_FORM_PART_BYTES,
    ) -> Any:
        return super().form(
            max_files=min(max_files, MAX_FORM_FILES),
            max_fields=min(max_fields, MAX_FORM_FIELDS),
            max_part_size=min(max_part_size, MAX_FORM_PART_BYTES),
        )


class CappedFormRoute(APIRoute):
    """FastAPI's documented custom route pattern: hand the endpoint a ``CappedFormRequest``."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def capped_handler(request: Request) -> Response:
            return await handler(CappedFormRequest(request.scope, request.receive))

        return capped_handler


router = APIRouter(prefix="/api", route_class=CappedFormRoute, tags=["syllabi"])


@router.post("/syllabi", status_code=201, response_model=UploadResponse)
def upload_syllabus(
    request: Request,
    client_id: Annotated[str, Depends(require_client_id)],
    settings: Annotated[Settings, Depends(app_settings)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    extractor: Annotated[Extractor, Depends(get_extractor)],
    ip_limiter: Annotated[SlidingWindowLimiter, Depends(get_ip_limiter)],
    file: Annotated[UploadFile | None, File(description="A PDF or .docx syllabus.")] = None,
    text: Annotated[str | None, Form(description="Pasted syllabus text.")] = None,
) -> UploadResponse:
    """Read one syllabus (a file or pasted text), find its deadlines, and save them."""
    started = time.perf_counter()
    has_file = file is not None and bool(file.filename)
    try:
        has_text = text is not None and bool(text.strip())
        if has_file and has_text:
            raise AppError("two_inputs")
        if not has_file and not has_text:
            raise AppError("no_input")
        _check_daily_limit(conn, client_id=client_id, settings=settings)
        if has_file:
            assert file is not None
            raw, filename = _read_upload(file, settings)
        else:
            assert text is not None
            raw, filename = text, None
    finally:
        # Closing deletes Starlette's spooled copy. It happens on every path, before Claude is called.
        if file is not None:
            _close_upload(file)

    document = normalize_text(raw)
    if meaningful_length(document) < settings.min_text_chars:
        raise AppError("no_text_found" if has_file else "text_too_short")
    if len(document) > settings.max_text_chars:
        raise AppError("text_too_long")

    retry_after = ip_limiter.hit(client_ip(request))
    if retry_after is not None:
        raise AppError("network_limit", retry_after_seconds=retry_after)

    # An AppError from the extractor propagates unchanged, and nothing has been saved yet.
    result = extractor(document, clock.today_local())

    class_name = (
        clean_class_name(result.class_name) or _class_name_from_filename(filename) or PASTED_CLASS_NAME
    )
    syllabus_id = create_syllabus(
        conn,
        client_id=client_id,
        class_name=class_name,
        filename=filename,
        extraction_model=result.model,
        prompt_version=result.prompt_version,
        items=result.items,
        created_at=clock.to_iso(clock.now_utc()),
    )
    syllabus = get_syllabus(conn, client_id=client_id, syllabus_id=syllabus_id)
    if syllabus is None:
        raise AppError("internal_error")
    items = list_items(conn, client_id=client_id, syllabus_id=syllabus_id)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info("extraction_finished items=%d ms=%d", len(items), elapsed_ms)
    return UploadResponse(syllabus=syllabus, items=items)


@router.get("/syllabi", response_model=SyllabusListResponse)
def read_syllabi(
    client_id: Annotated[str, Depends(require_client_id)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> SyllabusListResponse:
    """This browser's syllabi, oldest first."""
    return SyllabusListResponse(syllabi=list_syllabi(conn, client_id=client_id))


@router.patch("/syllabi/{syllabus_id}", response_model=SyllabusResponse)
def rename_class(
    syllabus_id: int,
    body: RenameRequest,
    client_id: Annotated[str, Depends(require_client_id)],
    settings: Annotated[Settings, Depends(app_settings)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> SyllabusResponse:
    """Rename one of this browser's classes."""
    class_name = " ".join(body.class_name.split())
    if not class_name or len(class_name) > settings.max_class_name_chars:
        raise AppError("invalid_class_name")
    if not 1 <= syllabus_id <= MAX_ROW_ID:
        raise AppError("not_found")
    if not rename_syllabus(conn, client_id=client_id, syllabus_id=syllabus_id, class_name=class_name):
        raise AppError("not_found")
    syllabus = get_syllabus(conn, client_id=client_id, syllabus_id=syllabus_id)
    if syllabus is None:
        raise AppError("not_found")
    return SyllabusResponse(syllabus=syllabus)


def _check_daily_limit(conn: sqlite3.Connection, *, client_id: str, settings: Settings) -> None:
    """Raise ``daily_limit`` once this client has saved the allowed number of syllabi in the window."""
    now = clock.now_utc()
    window = timedelta(seconds=settings.rate_window_seconds)
    count, oldest = recent_upload_stats(conn, client_id=client_id, since=clock.to_iso(now - window))
    limit = settings.daily_uploads_per_client
    if count < limit:
        return
    raise AppError(
        "daily_limit",
        message=f"You've hit today's limit of {limit} syllabi.",
        retry_after_seconds=_seconds_until_free(oldest, window=window, now=now),
    )


def _seconds_until_free(oldest: str | None, *, window: timedelta, now: datetime) -> int:
    """Whole seconds until the oldest counted upload leaves the window (at least 1)."""
    if oldest is None:  # only possible when the limit is 0
        return max(1, math.ceil(window.total_seconds()))
    remaining = clock.from_iso(oldest) + window - now
    return max(1, math.ceil(remaining.total_seconds()))


def _read_upload(upload: UploadFile, settings: Settings) -> tuple[str, str | None]:
    """Check the upload's size and type, then return ``(raw text, filename to store)``."""
    stream = upload.file
    if _upload_size(upload) > settings.max_upload_bytes:
        raise AppError("file_too_large")
    stream.seek(0)
    head = stream.read(HEAD_BYTES)
    stream.seek(0)
    kind = detect_kind(upload.filename, head)
    if kind is None:
        raise AppError("unsupported_type")
    raw = extract_text(stream, kind)
    return raw, _stored_filename(upload.filename or "")


def _upload_size(upload: UploadFile) -> int:
    if upload.size is not None:
        return upload.size
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _close_upload(upload: UploadFile) -> None:
    try:
        upload.file.close()
    except Exception as exc:  # never hide the real outcome of the request behind a close failure
        logger.warning("upload_close_failed error=%s", type(exc).__name__)


def _stored_filename(filename: str) -> str | None:
    """The file's own name without any folder path, at most 255 characters (keeping the extension)."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if len(name) > MAX_STORED_FILENAME_CHARS:
        stem, dot, extension = name.rpartition(".")
        if dot and stem and len(extension) <= 10:
            name = stem[: MAX_STORED_FILENAME_CHARS - len(extension) - 1] + "." + extension
        else:
            name = name[:MAX_STORED_FILENAME_CHARS]
    return name or None


def _class_name_from_filename(filename: str | None) -> str | None:
    """'cs_101-fall.pdf' -> 'cs 101 fall'. None when there's no usable name."""
    if not filename:
        return None
    stem = filename.rpartition(".")[0] if "." in filename else filename
    return clean_class_name(stem.replace("_", " ").replace("-", " "), max_chars=MAX_DERIVED_CLASS_NAME_CHARS)
