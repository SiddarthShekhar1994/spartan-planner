"""Runs the browser-side unit tests (tests/js/*.test.mjs) with Node's built-in test runner.

They cover the pure modules the screens are built on: sorting dates into weeks, finding the
date words in a source sentence, and formatting. No packages are installed. If Node isn't on
this machine the test is skipped, not failed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


def test_frontend_unit_tests_pass() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed, so the browser-side unit tests were not run")
    files = sorted(str(path) for path in JS_TESTS.glob("*.test.mjs"))
    assert files, "no browser-side test files found"
    result = subprocess.run(
        [node, "--test", *files], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
