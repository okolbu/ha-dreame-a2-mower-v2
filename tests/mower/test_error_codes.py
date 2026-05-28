"""Error code → human description map per apk fault index."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.error_codes import (
    ERROR_CODE_DESCRIPTIONS,
    S2P2_EVENT_TYPES,
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


def test_cloud_verified_s2p2_labels_reconciled():
    """ERROR_CODE_DESCRIPTIONS must agree with the 2026-05-26 cloud-verified
    s2p2→text mapping (inventory.yaml § s2p2). These were vacuum-derived
    guesses that contradicted verified facts — see the reconcile-with-s2p2 TODO.
    """
    d = ERROR_CODE_DESCRIPTIONS
    # 63: was "Blocked" → cloud "Robot is working. Scheduled task cancelled."
    assert "cancel" in d[63].lower() and "blocked" not in d[63].lower()
    # 50: was "Status 50 (unnamed)" → cloud "Mowing task started."
    assert "start" in d[50].lower()
    # 54: was vacuum "Edge fault" → low_battery_return (TODO-flagged conflict)
    assert "batter" in d[54].lower() and d[54].lower().count("edge") == 0
    # 28: off-dock undock marker; cloud relays as blades-worn (wear%-gated)
    assert "undock" in d[28].lower() or "blade" in d[28].lower()
    # cloud-verified codes now present in the description table:
    assert "maintenance" in d[30].lower()
    assert "start" in d[36].lower() or "retry" in d[36].lower()
    assert "continue" in d[70].lower() or "unfinished" in d[70].lower()


def test_descriptions_do_not_contradict_event_slugs():
    """For the cloud-verified set, each description must be compatible with its
    S2P2_EVENT_TYPES slug (the two tables are different views of the same code
    and must not disagree on meaning)."""
    expect = {48: "complete", 50: "start", 56: "rain", 63: "cancel",
              70: "continue", 30: "maintenance", 36: "start"}
    for code, kw in expect.items():
        assert code in S2P2_EVENT_TYPES, code
        assert code in ERROR_CODE_DESCRIPTIONS, code
        assert kw in ERROR_CODE_DESCRIPTIONS[code].lower(), (code, ERROR_CODE_DESCRIPTIONS[code])
