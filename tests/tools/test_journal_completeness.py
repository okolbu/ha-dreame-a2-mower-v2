"""Tests for the orphan-paragraph completeness check."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "journal_complete"
TOOL = Path(__file__).parents[2] / "tools" / "journal_completeness_check.py"


def _run(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *extra_args],
        capture_output=True, text=True, check=False,
    )


def test_passes_when_every_paragraph_accounted_for() -> None:
    """If every paragraph in OLD appears in one of the destinations, exit 0."""
    result = _run([
        "--old", str(FIXTURES / "old_complete.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
    ])
    assert result.returncode == 0, result.stdout + result.stderr


def test_reports_orphan_when_paragraph_is_missing() -> None:
    """If OLD has a paragraph that doesn't appear in any destination,
    exit non-zero and the report names the paragraph."""
    result = _run([
        "--old", str(FIXTURES / "old_with_orphan.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
    ])
    assert result.returncode != 0
    assert "orphan" in result.stdout.lower()
    assert "this paragraph is unique" in result.stdout.lower()


def test_allowlist_skips_intentionally_dropped() -> None:
    """A paragraph in the allowlist is not flagged as an orphan."""
    result = _run([
        "--old", str(FIXTURES / "old_with_orphan.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
        "--allowlist", str(FIXTURES / "allowlist.txt"),
    ])
    assert result.returncode == 0, result.stdout
