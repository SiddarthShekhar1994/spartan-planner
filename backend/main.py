"""The FastAPI app: the API under /api, the frontend at /, and one JSON error shape for everything.

Run it locally with:  py -m uvicorn backend.main:app --reload --reload-dir backend --no-access-log

Every error body is ``{"error": {"code", "message", "retry_after_seconds"?}}`` (codes and messages
live in backend/errors.py), whether the error is our own AppError, a request that fails validation,
a Starlette error (404, 405, form limits), the body size limit, or an unexpected exception.
"""

from __future__ import annotations

import logging
import mimetypes
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.utils import is_body_allowed_for_status_code
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.config import Settings, get_settings
from backend.db.connection import init_db
from backend.errors import AppError
from backend.routes import items, syllabi
from backend.routes.deps import Extractor, make_default_extractor
from backend.services.rate_limit import SlidingWindowLimiter

# The Windows registry can map .js to text/plain, and browsers refuse to run modules served that way.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

logger = logging.getLogger("spartan.app")

# Room for multipart boundaries, part headers and a small text field around a maximum-size file.
BODY_SLACK_BYTES = 512 * 1024


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------
def error_response(
    error: AppError,
    *,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Our error envelope, plus a Retry-After header when the error carries a wait time."""
    response_headers = dict(headers or {})
    if error.retry_after_seconds is not None:
        response_headers["Retry-After"] = str(error.retry_after_seconds)
    return JSONResponse(error.to_body(), status_code=status_code or error.status, headers=response_headers)


def _error_for_http_status(status_code: int, detail: object) -> tuple[AppError, int]:
    """Map a Starlette HTTPException to one of our codes and the status to send."""
    if status_code == 404:
        return AppError("not_found"), 404
    if status_code == 405:
        return AppError("method_not_allowed"), 405
    if status_code == 413:
        return AppError("file_too_large"), 413
    if status_code == 400:
        # Starlette's form parser says "Part exceeded maximum size of 1024KB." for a huge text field.
        if isinstance(detail, str) and "maximum size" in detail.lower():
            error = AppError("text_too_long")
            return error, error.status
        return AppError("bad_request"), 400
    return AppError("internal_error"), status_code


async def handle_app_error(request: Request, exc: AppError) -> Response:
    logger.info("request_failed status=%d code=%s", exc.status, exc.code)
    return error_response(exc)


async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
    # The details quote the request's own content, so they go nowhere: not in the body, not in logs.
    logger.info("request_failed status=422 code=validation_error")
    return error_response(AppError("validation_error"))


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    headers = dict(exc.headers or {})
    if isinstance(exc, _BodyTooLarge):
        headers["Connection"] = "close"  # the rest of the body won't be read
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    error, status_code = _error_for_http_status(exc.status_code, exc.detail)
    log = logger.debug if status_code in (404, 405) else logger.info
    log("request_failed status=%d code=%s", status_code, error.code)
    return error_response(error, status_code=status_code, headers=headers)


async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
    # Backstop for ServerErrorMiddleware; UnhandledErrorMiddleware normally answers first.
    logger.error("unhandled_error error=%s", type(exc).__name__)
    return error_response(AppError("internal_error"))


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class _BodyTooLarge(StarletteHTTPException):
    """Raised from ``receive`` once a streamed body passes the limit.

    It is an HTTPException so FastAPI's body reader re-raises it unchanged and
    ``handle_http_exception`` answers with 413 ``file_too_large``.
    """

    def __init__(self) -> None:
        super().__init__(status_code=413)


def _declared_length(scope: Scope) -> int | None:
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


class BodySizeLimitMiddleware:
    """413 ``file_too_large`` for any request body over ``max_body_bytes``.

    A Content-Length over the limit is refused before any of the body is read. Bodies without one
    (chunked uploads) are counted as they arrive. Starlette's RequestBodyLimitMiddleware can't be
    used: it swaps any response for a plain-text one when Content-Length is over the limit.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            await _too_large_response()(scope, receive, send)
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            # Normally the route's exception handler answers; this covers anything that let it through.
            if response_started:
                raise
            await _too_large_response()(scope, receive, send)


def _too_large_response() -> JSONResponse:
    error = AppError("file_too_large")
    logger.info("request_failed status=%d code=%s", error.status, error.code)
    return error_response(error, headers={"Connection": "close"})


class UnhandledErrorMiddleware:
    """Any exception no handler took becomes a 500 ``internal_error`` envelope.

    Only the exception's class name is logged, and the exception is not passed on to the server:
    its traceback would carry the exception message, and pydantic and JSON errors quote their input,
    which can be syllabus text. If the response had already started, the connection is left for the
    server to close.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            logger.error("unhandled_error error=%s", type(exc).__name__)
            if not response_started:
                await error_response(AppError("internal_error"))(scope, receive, send)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
class _CurrentStderrHandler(logging.StreamHandler):
    """A StreamHandler that writes to whatever ``sys.stderr`` is right now (pytest swaps it)."""

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass


def _configure_logging() -> None:
    """Print the app's own log lines (loggers under "spartan") to stderr, once per process.

    uvicorn only sets up its own loggers, so without this INFO lines such as
    ``extraction_finished`` would be dropped. Records still propagate, so pytest's caplog sees them.
    """
    app_logger = logging.getLogger("spartan")
    if app_logger.level == logging.NOTSET:
        app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        handler = _CurrentStderrHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        app_logger.addHandler(handler)


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------
def _mount_frontend(app: FastAPI, directory: Path) -> None:
    if not directory.is_dir():
        # StaticFiles refuses a missing folder. Keep the API up; other paths answer 404 until it exists.
        logger.warning("frontend_missing")
        return
    app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")


def create_app(settings: Settings | None = None, *, extractor: Extractor | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and a fake extractor."""
    settings = settings if settings is not None else get_settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(settings.database_path)
        yield

    app = FastAPI(
        title="Spartan Planner",
        lifespan=lifespan,
        middleware=[
            Middleware(UnhandledErrorMiddleware),
            Middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_upload_bytes + BODY_SLACK_BYTES),
        ],
        exception_handlers={
            AppError: handle_app_error,
            RequestValidationError: handle_validation_error,
            StarletteHTTPException: handle_http_exception,
            Exception: handle_unexpected_error,
        },
    )
    app.state.settings = settings
    app.state.extractor = extractor if extractor is not None else make_default_extractor(settings)
    app.state.ip_limiter = SlidingWindowLimiter(settings.daily_uploads_per_ip, settings.rate_window_seconds)

    app.include_router(syllabi.router)
    app.include_router(items.router)
    # Last, because the mount matches every path the routes above don't.
    _mount_frontend(app, Path(settings.frontend_dir))
    return app


app = create_app()  # used by: py -m uvicorn backend.main:app
