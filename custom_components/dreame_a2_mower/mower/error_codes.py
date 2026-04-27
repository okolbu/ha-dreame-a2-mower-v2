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


# Confirmed entries from docs/research/g2408-protocol.md §2.1.
# Add codes here when an apk-confirmed fault description becomes
# available; the table stays purely g2408 (no upstream-vacuum codes).
ERROR_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Hanging — mower is stuck or hanging",
    24: "Battery low",
    27: "Human detected",
    56: "Bad weather (rain protection active)",
    71: "Positioning failed (SLAM relocation needed)",
    73: "Top cover open",
}


def describe_error(code: int) -> str:
    """Return a human-readable description for the given error code.

    Returns a fallback string for unknown codes — the caller is
    responsible for emitting a [NOVEL/error_code] warning.
    """
    if code in ERROR_CODE_DESCRIPTIONS:
        return ERROR_CODE_DESCRIPTIONS[code]
    return f"Unknown error {code}"
