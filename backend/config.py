"""Settings, read from environment variables and the local .env file.

Real environment variables win over .env, so Railway's settings override local ones.
The API key is kept out of ``repr()`` so it can never land in a log line by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from backend.prompts import CURRENT_PROMPT_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_DATABASE_PATH = "data/spartan.db"
MB = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None = field(repr=False)
    claude_model: str
    database_path: Path
    prompt_version: str = CURRENT_PROMPT_VERSION
    frontend_dir: Path = FRONTEND_DIR
    # Upload and text limits
    max_upload_bytes: int = 10 * MB
    max_text_chars: int = 150_000
    min_text_chars: int = 50  # non-whitespace characters; fewer than this means a scan or an empty paste
    # Rate limits (rolling window)
    daily_uploads_per_client: int = 10  # successful syllabi per client ID
    daily_uploads_per_ip: int = 50  # extraction attempts per IP, counted in memory only
    rate_window_seconds: int = 24 * 60 * 60
    # Class names
    max_class_name_chars: int = 120
    # Hosting
    production: bool = False  # APP_ENV=production: no API docs pages, and browsers are told to use HTTPS only
    trust_proxy: bool = False  # TRUST_PROXY=1: read the visitor's address from the host's X-Real-IP header


def resolve_path(path_value: str) -> Path:
    """Relative paths are relative to the project root, not the current folder."""
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_settings() -> Settings:
    """Read settings now. Loads .env first without overriding real environment variables."""
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig", override=False)
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None
    model = (os.environ.get("CLAUDE_MODEL") or "").strip() or DEFAULT_MODEL
    database_path = (os.environ.get("DATABASE_PATH") or "").strip() or DEFAULT_DATABASE_PATH
    return Settings(
        anthropic_api_key=api_key,
        claude_model=model,
        database_path=resolve_path(database_path),
        production=(os.environ.get("APP_ENV") or "").strip().lower() == "production",
        trust_proxy=(os.environ.get("TRUST_PROXY") or "").strip().lower() in {"1", "true", "yes"},
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings for the running app, loaded once."""
    return load_settings()
