"""What the live site needs: a health check, the visitor's address behind the host's proxy,
browser safety headers, frontend files that don't go stale, and no API docs pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import FRONTEND_DIR, PROJECT_ROOT, load_settings
from backend.main import CONTENT_SECURITY_POLICY

SYLLABI = "/api/syllabi"


def upload(client, text: str, **kwargs):
    return client.post(SYLLABI, files={"text": (None, text.encode("utf-8"))}, **kwargs)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def test_health_answers_without_a_browser_id(make_client):
    client = make_client(client_id=None)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_answers_for_the_hosts_own_hostname(client):
    assert client.get("/health", headers={"Host": "healthcheck.railway.app"}).status_code == 200


# ---------------------------------------------------------------------------
# The visitor's address behind the proxy
# ---------------------------------------------------------------------------
def test_behind_the_proxy_each_visitor_has_their_own_upload_limit(make_client, sample_syllabus_text, other_client_id):
    client = make_client(trust_proxy=True, daily_uploads_per_ip=1)
    assert upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.7"}).status_code == 201
    second = upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.7", "X-Client-Id": other_client_id})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "network_limit"
    other_visitor = upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.8", "X-Client-Id": other_client_id})
    assert other_visitor.status_code == 201


def test_without_the_proxy_setting_the_header_is_ignored(make_client, sample_syllabus_text, other_client_id):
    client = make_client(daily_uploads_per_ip=1)
    assert upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.7"}).status_code == 201
    # A different claimed address must not get around the limit.
    spoofed = upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.8", "X-Client-Id": other_client_id})
    assert spoofed.status_code == 429


def test_an_oversized_address_header_is_ignored(make_client, sample_syllabus_text, other_client_id):
    client = make_client(trust_proxy=True, daily_uploads_per_ip=1)
    assert upload(client, sample_syllabus_text, headers={"X-Real-IP": "9" * 500}).status_code == 201
    again = upload(client, sample_syllabus_text, headers={"X-Real-IP": "8" * 500, "X-Client-Id": other_client_id})
    assert again.status_code == 429, "both fell back to the connecting address"


def test_the_visitor_address_is_never_logged_or_returned(make_client, sample_syllabus_text, caplog):
    client = make_client(trust_proxy=True)
    with caplog.at_level("DEBUG"):
        response = upload(client, sample_syllabus_text, headers={"X-Real-IP": "203.0.113.77"})
    assert response.status_code == 201
    assert "203.0.113.77" not in response.text
    assert "203.0.113.77" not in caplog.text


# ---------------------------------------------------------------------------
# Browser safety headers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/js/app.js", "/api/syllabi", "/health", "/nope"])
def test_every_response_carries_the_safety_headers(client, path):
    response = client.get(path)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_the_policy_allows_only_our_files_and_google_fonts():
    assert "default-src 'self'" in CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "*" not in CONTENT_SECURITY_POLICY
    hosts = {part for part in CONTENT_SECURITY_POLICY.replace(";", " ").split() if part.startswith("http")}
    assert hosts == {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}


def test_the_real_pages_have_nothing_the_policy_would_block():
    for name in ("index.html", "privacy.html"):
        page = (FRONTEND_DIR / name).read_text(encoding="utf-8")
        assert "<style" not in page, f"{name} has an inline style block"
        assert " style=" not in page, f"{name} has an inline style attribute"
        assert " onclick=" not in page and " onload=" not in page
        for tag in page.split("<script")[1:]:
            assert "src=" in tag.split(">", 1)[0], f"{name} has an inline script"


def test_https_only_is_sent_on_the_live_site_and_not_in_development(make_client):
    assert "strict-transport-security" not in make_client().get("/health").headers
    live = make_client(production=True).get("/health")
    assert live.headers["strict-transport-security"] == "max-age=31536000"


# ---------------------------------------------------------------------------
# API docs pages
# ---------------------------------------------------------------------------
def test_api_docs_pages_work_in_development(client):
    assert client.get("/openapi.json").status_code == 200
    assert "content-security-policy" not in client.get("/docs").headers


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_pages_are_off_on_the_live_site(make_client, path):
    assert make_client(production=True).get(path).status_code == 404


# ---------------------------------------------------------------------------
# Frontend files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/js/app.js", "/css/base.css"])
def test_frontend_files_are_checked_for_a_newer_copy_every_visit(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_an_unchanged_frontend_file_is_not_sent_again(client):
    first = client.get("/js/app.js")
    again = client.get("/js/app.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_the_privacy_note_is_served_and_says_the_main_things(make_client):
    client = make_client(frontend_dir=FRONTEND_DIR)
    response = client.get("/privacy.html")
    assert response.status_code == 200
    text = response.text
    for phrase in ("extended-time number", "never sent", "deleted as soon as", "Anthropic", "I never ask", "It can be wrong"):
        assert phrase in text, phrase
    assert 'href="privacy.html"' in client.get("/").text


# ---------------------------------------------------------------------------
# Settings and the image
# ---------------------------------------------------------------------------
def test_hosting_settings_come_from_the_environment(monkeypatch, tmp_path):
    volume_file = tmp_path / "data" / "spartan.db"  # stands in for /data/spartan.db on the host's volume
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("DATABASE_PATH", str(volume_file))
    settings = load_settings()
    assert settings.production is True
    assert settings.trust_proxy is True
    assert settings.database_path == Path(volume_file)


def test_hosting_settings_are_off_unless_asked_for(monkeypatch):
    monkeypatch.setenv("APP_ENV", "")
    monkeypatch.setenv("TRUST_PROXY", "")
    settings = load_settings()
    assert settings.production is False
    assert settings.trust_proxy is False


def test_the_image_never_contains_secrets_or_local_data():
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for name in (".env", ".git", "data", ".venv", "tests"):
        assert name in ignored, f"{name} is not in .dockerignore"
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in dockerfile, "the key is set in the host's dashboard, never in the image"
    assert "COPY . " not in dockerfile, "copy only backend/ and frontend/"
    assert "--no-access-log" in dockerfile
    assert "${PORT" in dockerfile
