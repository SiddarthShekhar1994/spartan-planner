"""Shared FastAPI dependencies: the client ID, settings, a database connection, and the extractor.

Everything here reads from ``request.app.state``, which ``backend.main.create_app`` fills in,
so tests can build an app with their own settings and a fake extractor.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import date

from fastapi import Header, Request

from backend.config import Settings
from backend.db.connection import connect
from backend.errors import AppError
from backend.schemas import ExtractionResult
from backend.services.extraction import run_extraction
from backend.services.rate_limit import SlidingWindowLimiter

Extractor = Callable[[str, date], ExtractionResult]
"""``(document_text, today) -> ExtractionResult``. The real one calls Claude; tests pass a fake."""

_UUID_TEXT = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


def require_client_id(x_client_id: str | None = Header(default=None, alias="X-Client-Id")) -> str:
    """The browser's random ID from the ``X-Client-Id`` header, in canonical lowercase form.

    It must look like a UUID (8-4-4-4-12 hex digits); anything else is ``missing_client_id``.
    """
    value = x_client_id.strip() if isinstance(x_client_id, str) else ""
    if not _UUID_TEXT.fullmatch(value):
        raise AppError("missing_client_id")
    return str(uuid.UUID(value))


def app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """A connection for this request, closed when the request is done."""
    with closing(connect(app_settings(request).database_path)) as conn:
        yield conn


def get_extractor(request: Request) -> Extractor:
    return request.app.state.extractor


def get_ip_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.ip_limiter


MAX_IP_HEADER_CHARS = 64  # longer than any IPv4 or IPv6 address


def client_ip(request: Request) -> str:
    """The visitor's address, used only for the in-memory upload limit. Never stored, never logged.

    Behind the host's proxy (``trust_proxy``), every request arrives from the proxy, so the
    visitor's own address is read from the ``X-Real-IP`` header the proxy sets. Without that
    setting the header is ignored, because anyone could send it.
    """
    if app_settings(request).trust_proxy:
        forwarded = (request.headers.get("x-real-ip") or "").strip()
        if forwarded and len(forwarded) <= MAX_IP_HEADER_CHARS:
            return forwarded
    client = request.client
    if client is None or not client.host:
        return "unknown"
    return client.host


def make_default_extractor(settings: Settings) -> Extractor:
    """The real extractor: reads a syllabus with Claude using the configured model and prompt."""

    def extract(document_text: str, today: date) -> ExtractionResult:
        return run_extraction(
            document_text,
            today=today,
            model=settings.claude_model,
            prompt_version=settings.prompt_version,
            api_key=settings.anthropic_api_key,
        )

    return extract
