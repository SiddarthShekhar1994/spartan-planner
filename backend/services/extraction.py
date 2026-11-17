"""Ask Claude for every deadline in one syllabus, then apply our own checks to its answer.

This module knows nothing about HTTP, the database or settings: callers pass the model, prompt
version and API key in, so Build 3's eval scripts can call ``run_extraction`` directly.
The prompt text lives in backend/prompts.py.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import anthropic

from backend.errors import AppError
from backend.prompts import get_prompt
from backend.schemas import ExtractionResult, ModelOutput
from backend.services.postprocess import clean_class_name, clean_items

logger = logging.getLogger("spartan.extraction")

DEFAULT_MAX_TOKENS = 16000
# The SDK's own timeout for a long non-streaming call: the reply only arrives once Claude has
# finished writing it, and the SDK expects up to 450 s for max_tokens=16000. A shorter timeout
# cuts a long reply off, and the retries then write it again from the start.
REQUEST_TIMEOUT = anthropic.Timeout(600.0, connect=5.0)
EFFORT = "medium"
# The structured-output schema Claude's reply must match, built once.
SCHEMA = anthropic.transform_schema(ModelOutput)

_KEY_REJECTED_MESSAGE = "I'm not set up to read syllabi yet: the server's API key didn't work."
# Both mean the reply was cut off before the JSON could finish.
_CUT_OFF_STOP_REASONS = frozenset({"max_tokens", "model_context_window_exceeded"})


def make_client(api_key: str) -> anthropic.Anthropic:
    """The only place a real Claude client is built. Tests replace this function."""
    return anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=2)


def _request(client: anthropic.Anthropic, *, model: str, system: str, user_message: str) -> anthropic.types.Message:
    """Send the request, turning every SDK failure into an AppError. Logs status codes and class names only."""
    try:
        return client.messages.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_message}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        logger.error("extraction_call_failed status=%s error=%s", exc.status_code, type(exc).__name__)
        raise AppError("extraction_not_configured", message=_KEY_REJECTED_MESSAGE) from None
    except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:  # 429, and 5xx incl. 529
        logger.warning("extraction_call_failed status=%s error=%s", exc.status_code, type(exc).__name__)
        raise AppError("extraction_unavailable") from None
    except anthropic.APIConnectionError as exc:  # includes APITimeoutError
        logger.warning("extraction_call_failed error=%s", type(exc).__name__)
        raise AppError("extraction_unavailable") from None
    except anthropic.APIStatusError as exc:
        logger.error("extraction_call_failed status=%s error=%s", exc.status_code, type(exc).__name__)
        raise AppError("extraction_failed") from None
    except Exception as exc:  # anything unexpected; never let it reach the student as a 500
        logger.error("extraction_call_failed error=%s", type(exc).__name__)
        raise AppError("extraction_failed") from None


def call_model(
    document_text: str,
    *,
    today: date,
    model: str,
    prompt_version: str,
    api_key: str | None,
    client: anthropic.Anthropic | None = None,
) -> ModelOutput:
    """Claude's raw answer for this syllabus, parsed into ``ModelOutput``."""
    prompt = get_prompt(prompt_version)  # an unknown version is a setup error, so it is not caught
    user_message = prompt.build_user_message(document_text, today)

    owns_client = client is None
    if client is None:
        if not api_key:
            logger.error("extraction_not_configured")
            raise AppError("extraction_not_configured")
        client = make_client(api_key)

    started = time.perf_counter()
    try:
        message = _request(client, model=model, system=prompt.system, user_message=user_message)
    finally:
        if owns_client:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    stop_reason = getattr(message, "stop_reason", None)
    usage = getattr(message, "usage", None)
    logger.info(
        "extraction_call_finished model=%s stop_reason=%s input_tokens=%s output_tokens=%s ms=%d",
        model,
        stop_reason,
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        elapsed_ms,
    )

    # Check why Claude stopped before reading anything it wrote.
    if stop_reason == "refusal":
        raise AppError("extraction_refused")
    if stop_reason in _CUT_OFF_STOP_REASONS:
        raise AppError("extraction_too_long")

    # A reply starts with thinking blocks; only text blocks carry the JSON.
    blocks = getattr(message, "content", None) or []
    text_blocks = [block for block in blocks if getattr(block, "type", None) == "text"]
    text = "".join(getattr(block, "text", None) or "" for block in text_blocks)
    if not text.strip():
        logger.warning("extraction_output_invalid error=empty")
        raise AppError("extraction_failed")
    try:
        return ModelOutput.model_validate_json(text)
    except Exception as exc:  # pydantic's message would echo Claude's reply, so log the class name only
        logger.warning("extraction_output_invalid error=%s", type(exc).__name__)
        raise AppError("extraction_failed") from None


def run_extraction(
    document_text: str,
    *,
    today: date,
    model: str,
    prompt_version: str,
    api_key: str | None,
    client: anthropic.Anthropic | None = None,
) -> ExtractionResult:
    """Claude's answer after our checks: verified quotes, supported dates, no repeats."""
    output = call_model(
        document_text, today=today, model=model, prompt_version=prompt_version, api_key=api_key, client=client
    )
    return ExtractionResult(
        class_name=clean_class_name(output.class_name),
        items=clean_items(output.items, document_text, term=output.term),
        model=model,
        prompt_version=prompt_version,
    )
