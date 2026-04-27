"""Pytest configuration shared by protocol/ + mower/ + integration/ tests.

Per spec §3, the protocol/ + mower/ test suites must run in a vanilla
pytest venv (no Home Assistant required). The integration/ test suite
adds pytest-homeassistant-custom-component fixtures separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the top-level protocol/ package importable in tests
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures directory."""
    return FIXTURES
