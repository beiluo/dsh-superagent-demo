"""The repository must never contain a real LLM key or bearer token."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_secret_scan_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_secrets.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_browser_assets_do_not_contain_credentials():
    static_files = [
        ROOT / "index.html",
        ROOT / "assets" / "js" / "agent.js",
        ROOT / "assets" / "js" / "agent-config.js",
        ROOT / "assets" / "js" / "app.js",
        ROOT / "assets" / "js" / "data.js",
    ]
    for path in static_files:
        text = path.read_text(encoding="utf-8")
        assert "Authorization" not in text, path
        assert "Bearer " not in text, path
        assert re.search(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]", text) is None, path
        assert "LLM_API_KEY=" not in text, path
