"""Mower error code → human description map.

Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.2``.

The s2.2 push on g2408 carries an error code per the apk fault index
(originally reverse-engineered from the Dreame Smart Life app's
decompiled APK; cross-validated against live captures during P1+P2).

Some s2.2 values that arrive on g2408 are actually phase / mode codes
that the apk does not classify as faults (e.g., 56 = rain protection,
71 = positioning failed). These are routed to dedicated binary_sensor
entities in F2; the error-code description map here only covers
genuine faults.

Codes documented but not in this map yield a fallback "Unknown error N"
description. The coordinator emits a [NOVEL/error_code] warning when
it sees a code not in this table.
"""
from __future__ import annotations


# Confirmed entries from docs/research/g2408-protocol.md §2.1 plus
# names lifted from legacy DreameMowerErrorCode enum (originally apk-
# decompiled). Some codes are status / phase indicators rather than
# faults — the integration still surfaces them via the "Error code"
# entity for visibility, but the description signals the non-fault
# nature where applicable.
ERROR_CODE_DESCRIPTIONS: dict[int, str] = {
    # 2026-04-30: empirical baseline is `s2p2 = 0` while the mower is
    # mowing or charging without any fault — so the apk-derived
    # "Hanging" label was wrong for the g2408 (likely model-specific).
    0: "No error / OK",
    # Confirmed 2026-04-30 against app notifications during a deliberate
    # tilt / lift / lift-lockout test (g2408-protocol §3.4 byte[1..3]).
    1: "Robot tilted (drop sensor)",
    9: "Robot lifted",
    23: "Lift lockout — PIN required on device",
    24: "Battery low",
    27: "Human detected",
    37: "Right magnet",
    38: "Flow error",
    39: "Infrared fault",
    40: "Camera fault",
    41: "Strong magnet",
    43: "RTC clock error",
    44: "Auto key triggered",
    45: "3.3 V power error",
    46: "Camera idle",
    47: "Scheduled task cancelled (not an error)",
    48: "Mowing complete (not an error)",
    49: "Bumper / LDS",
    50: "Status 50 (unnamed; observed during state transitions)",
    51: "Filter blocked",
    53: "Session starting (scheduled — not an error)",
    54: "Edge fault",
    56: "Bad weather (rain protection active)",
    57: "Edge fault (alt)",
    58: "Ultrasonic fault",
    59: "No-go zone reached",
    61: "Route error",
    62: "Route error (alt)",
    63: "Blocked",
    64: "Blocked (alt)",
    65: "Restricted area",
    66: "Restricted area (alt)",
    67: "Restricted area (alt 2)",
    71: "Positioning failed (SLAM relocation needed)",
    73: "Top cover open",
    75: "Low battery turn-off",
    78: "Robot in hidden zone",
    117: "Station disconnected",
}


def describe_error(code: int) -> str:
    """Return a human-readable description for the given error code.

    Returns a fallback string for unknown codes — the caller is
    responsible for emitting a [NOVEL/error_code] warning.
    """
    if code in ERROR_CODE_DESCRIPTIONS:
        return ERROR_CODE_DESCRIPTIONS[code]
    return f"Unknown error {code}"
