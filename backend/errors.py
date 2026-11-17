"""Every error the API can return: its code, HTTP status, and a friendly first-person message.

Routes and services raise ``AppError("some_code")``. ``backend/main.py`` turns it into
``{"error": {"code": ..., "message": ..., "retry_after_seconds": ...}}``. The frontend shows
``message`` as-is, so keep messages short, kind, and specific, with one next step.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str


ERRORS: dict[str, ErrorSpec] = {
    # 400: the request itself is wrong
    "missing_client_id": ErrorSpec(400, "I need a browser ID to keep your classes separate. Reload the page and try again."),
    "no_input": ErrorSpec(400, "Send me a PDF, a Word file, or some pasted text."),
    "two_inputs": ErrorSpec(400, "Send me a file or pasted text, not both at once."),
    "bad_request": ErrorSpec(400, "Something in that request didn't look right. Try again."),
    "invalid_class_name": ErrorSpec(400, "Class names need 1 to 120 characters."),
    # 404 / 405
    "not_found": ErrorSpec(404, "I couldn't find that."),
    "method_not_allowed": ErrorSpec(405, "That isn't something I can do here."),
    # 413: too big
    "file_too_large": ErrorSpec(413, "That file is over 10 MB. Try a smaller copy, or paste the text instead."),
    "text_too_long": ErrorSpec(413, "That's more text than any syllabus I've seen. Try pasting just the schedule and grading parts."),
    # 415: wrong kind of file
    "unsupported_type": ErrorSpec(415, "I can read PDF and Word (.docx) files. Save it as one of those, or paste the text."),
    # 422: understood the request, couldn't use the content
    "validation_error": ErrorSpec(422, "Something in that request didn't look right. Try again."),
    "unreadable_file": ErrorSpec(422, "I couldn't open that file. It might be damaged or locked. Try pasting the text instead."),
    "no_text_found": ErrorSpec(422, "I couldn't find any text in that file. If it's a scan, paste the text instead."),
    "text_too_short": ErrorSpec(422, "That's too short to be a syllabus. Paste the whole thing?"),
    "extraction_refused": ErrorSpec(422, "I wasn't able to read that one. Try pasting just the schedule part."),
    "extraction_too_long": ErrorSpec(422, "That syllabus has more deadlines than I can list in one go. Try pasting it in two parts."),
    # 429: limits (routes pass retry_after_seconds)
    "daily_limit": ErrorSpec(429, "You've hit today's limit of 10 syllabi."),
    "network_limit": ErrorSpec(429, "Lots of uploads from your network today."),
    # 5xx: our side
    "internal_error": ErrorSpec(500, "Something broke on my end. Try again in a minute."),
    "extraction_failed": ErrorSpec(502, "Something went wrong while I was reading that one. Try again."),
    "extraction_unavailable": ErrorSpec(503, "I couldn't reach my reading service. Try again in a minute."),
    "extraction_not_configured": ErrorSpec(503, "I'm not set up to read syllabi yet: the server is missing its API key."),
}


class AppError(Exception):
    """An error with a known code. Safe to show to the student."""

    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        if code not in ERRORS:
            raise ValueError(f"unknown error code: {code}")
        spec = ERRORS[code]
        self.code = code
        self.status = spec.status
        self.message = message or spec.message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)

    def to_body(self) -> dict:
        """The JSON body the API sends for this error."""
        body: dict = {"code": self.code, "message": self.message}
        if self.retry_after_seconds is not None:
            body["retry_after_seconds"] = self.retry_after_seconds
        return {"error": body}
