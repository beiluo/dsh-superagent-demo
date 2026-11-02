#!/usr/bin/env python3
"""Fail if a tracked file appears to contain a real secret.

The static GitHub Pages site cannot keep a secret, so this check runs in CI and
in ``make validate``.  It deliberately ignores placeholder values such as
``LLM_API_KEY=``, ``<your-key>`` and ``sk-...`` inside prose.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "docs/evidence"}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".json",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ttl",
    ".rq",
    ".example",
    ".sh",
    ".env",
    ".cfg",
    ".ini",
}

PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "OpenAI-style key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub fine-grained token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (
        re.compile(
            r"(?i)\b(?:llm_api_key|openai_api_key|api_secret|secret_key)\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9_\-]{16,})"
        ),
        "assigned secret",
    ),
)

ALLOWED_PLACEHOLDERS = {
    "your-key",
    "your_api_key",
    "replace-me",
    "changeme",
    "test-only",
    "unit-test-only-value",
    "fake-key",
}


def tracked_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        names = [name for name in output.decode("utf-8", "ignore").split("\0") if name]
        return [ROOT / name for name in names]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            files.append(path)
        return files


def is_text(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".env.example", ".gitignore"}:
        return False
    try:
        if path.stat().st_size > 1_000_000:
            return False
        with path.open("rb") as handle:
            chunk = handle.read(2048)
        return b"\0" not in chunk
    except OSError:
        return False


def scan() -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    for path in tracked_files():
        if not is_text(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in PATTERNS:
                for match in pattern.finditer(line):
                    captured = match.group(1) if match.groups() else match.group(0)
                    if captured.lower() in ALLOWED_PLACEHOLDERS:
                        continue
                    if captured.lower().startswith(("your-", "replace-", "example-")):
                        continue
                    findings.append((path.relative_to(ROOT), line_number, label, line.strip()[:160]))
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("No secrets found in tracked files.")
        return 0
    print("Potential secrets found:", file=sys.stderr)
    for path, line_number, label, excerpt in findings:
        print(f"  {path}:{line_number}: {label}: {excerpt}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
