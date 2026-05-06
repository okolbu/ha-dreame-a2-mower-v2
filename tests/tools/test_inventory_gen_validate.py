"""Tests for inventory_gen.py's schema validator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_gen.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_accepts_good_fixture() -> None:
    result = _run(["--validate-only", str(FIXTURES / "good_inventory.yaml")])
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout.lower()


def test_validate_rejects_unknown_unit_wire() -> None:
    result = _run(["--validate-only", str(FIXTURES / "bad_unit_vocab.yaml")])
    assert result.returncode != 0
    assert "unit.wire" in result.stderr
    assert "unknown_unit_xyz" in result.stderr


def test_validate_rejects_invalid_status_decoded() -> None:
    result = _run(["--validate-only", str(FIXTURES / "bad_status.yaml")])
    assert result.returncode != 0
    assert "decoded" in result.stderr
    assert "maybe_sometimes" in result.stderr


def test_validate_rejects_unit_as_string() -> None:
    """unit must be a dict, not a bare string."""
    result = _run(["--validate-only", str(FIXTURES / "bad_unit_type.yaml")])
    assert result.returncode != 0
    assert "unit" in result.stderr
    assert "expected dict" in result.stderr


def test_validate_rejects_status_as_string() -> None:
    """status must be a dict, not a bare string."""
    result = _run(["--validate-only", str(FIXTURES / "bad_status_type.yaml")])
    assert result.returncode != 0
    assert "status" in result.stderr
    assert "expected dict" in result.stderr


def test_validate_rejects_non_bool_runtime_suppress() -> None:
    """runtime.suppress must be a bool, not a string or other."""
    result = _run(["--validate-only", str(FIXTURES / "bad_runtime_suppress.yaml")])
    assert result.returncode != 0
    assert "runtime.suppress" in result.stderr
    assert "bool" in result.stderr.lower()
