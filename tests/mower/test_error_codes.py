"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
    ERROR_CODE_DESCRIPTIONS,
    describe_error,
)


def test_known_error_codes_mapped():
    """The most-confirmed error codes from protocol-doc §2.1 row s2.2 are mapped."""
    assert "HANGING" in ERROR_CODE_DESCRIPTIONS[0].upper()
    assert "BATTERY" in ERROR_CODE_DESCRIPTIONS[24].upper()
    assert "HUMAN" in ERROR_CODE_DESCRIPTIONS[27].upper()
    assert "WEATHER" in ERROR_CODE_DESCRIPTIONS[56].upper() or "RAIN" in ERROR_CODE_DESCRIPTIONS[56].upper()
    assert "COVER" in ERROR_CODE_DESCRIPTIONS[73].upper()


def test_describe_known_returns_description():
    assert describe_error(24) == ERROR_CODE_DESCRIPTIONS[24]


def test_describe_unknown_returns_fallback():
    """Unknown codes return a fallback description."""
    s = describe_error(9999)
    assert "9999" in s
    assert "unknown" in s.lower()
