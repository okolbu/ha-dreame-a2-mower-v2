"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
    ERROR_CODE_DESCRIPTIONS,
    describe_error,
)


def test_known_error_codes_mapped():
    """The most-confirmed error codes from protocol-doc §2.1 row s2.2 are mapped.

    Code 0 was originally labelled "Hanging" from the apk decompilation but
    that's the steady-state baseline on g2408 — corrected to "No error / OK"
    on 2026-04-30 after live observation.
    """
    assert "OK" in ERROR_CODE_DESCRIPTIONS[0].upper() or "NO ERROR" in ERROR_CODE_DESCRIPTIONS[0].upper()
    assert "TILT" in ERROR_CODE_DESCRIPTIONS[1].upper() or "DROP" in ERROR_CODE_DESCRIPTIONS[1].upper()
    assert "LIFT" in ERROR_CODE_DESCRIPTIONS[9].upper()
    assert "PIN" in ERROR_CODE_DESCRIPTIONS[23].upper() or "LOCKOUT" in ERROR_CODE_DESCRIPTIONS[23].upper()
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
