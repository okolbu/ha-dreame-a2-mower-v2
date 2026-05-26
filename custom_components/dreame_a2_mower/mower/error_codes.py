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
    # 2026-05-25: fires on EVERY undock (14/14) — off-dock LiDAR relocate
    # marker, not a fault. The "Blades severely worn" push is app-side from
    # wear%, not this code. See inventory.yaml § s2p2.
    28: "Off-dock LiDAR relocating (not an error; fires every undock)",
    # 2026-05-05: two distinct paths into 31 — 33→31 (documented "task
    # errored out, now idle" pair after positioning fail / task-start
    # fail) and 48→31 direct (post-edge-mow auto-dock planner could not
    # route home from a stuck pose). Both surface the Dreame app's
    # "Failed to return to station" notification. See g2408-protocol.md
    # §4.1 row 31 + §4.6.1 for the wheel-bind chain.
    31: "Failed to return to station",
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


# ---------------------------------------------------------------------------
# s2p2 notification SLUG table — keyed off s2p2 value, value = HA event_type
# slug. Distinct from ERROR_CODE_DESCRIPTIONS above: the description table is
# a fault catalogue (apk FaultIndex + community remaps), while this table maps
# s2p2 values to the stable HA event_type slugs fired by
# `event.dreame_a2_mower_notification`.
#
# This is the pure, layer-2 module so external dev tools (mower_tail.py,
# probe_a2_mqtt.py) can import it WITHOUT pulling homeassistant via the
# coordinator package's __init__. The user-visible text per fire comes from
# the cloud (see coordinator/_notifications.py) — slugs only here.
#
# Source: docs/research/app-notification-history-2026-05-16.md § Empirical s2p2 mapping.
S2P2_EVENT_TYPES: dict[int, str] = {
    0:   "hanging",
    23:  "emergency_stop",
    27:  "human_detected",
    28:  "blades_worn",                     # cloud-verified 2026-05-26
    30:  "maintenance_reminder",            # cloud-verified 2026-05-26
    31:  "positioning_failed_stuck",
    33:  "positioning_failed_transient",
    36:  "failed_to_start_task",            # cloud-verified 2026-05-26
    43:  "battery_temp_low_charging_paused",
    47:  "task_cancelled",                  # mova [MOWER] community-confirmed
    48:  "mowing_complete",                 # cloud-verified 2026-05-26
    50:  "mowing_started",                  # cloud-verified 2026-05-26
    53:  "scheduled_mowing_started",
    54:  "low_battery_return",
    56:  "rain_protection",                 # cloud-verified 2026-05-26
    63:  "schedule_cancelled_busy",         # cloud-verified 2026-05-26
    70:  "continue_unfinished_task",        # cloud-verified 2026-05-26
    71:  "positioning_failure",
    73:  "top_cover_open",
    75:  "arrived_at_maintenance_point",
    78:  "robot_in_hidden_zone",
    117: "station_disconnected",
}

# Slug fired when s2p2 carries a value not in S2P2_EVENT_TYPES — the cloud
# still provides authoritative text in the event payload; the slug is generic
# so HA can register the event_type up-front.
S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"
