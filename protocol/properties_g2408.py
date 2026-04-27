"""g2408-specific siid/piid map and state-code translations.

This replaces the multi-model property registry from upstream's dreame/types.py
with values observed on the Dreame A2 (model dreame.mower.g2408) via MQTT
probing. Upstream's mapping was built for A1 Pro and earlier vacuum-derived
mowers, which use different siid/piid assignments — the reason so many entities
show "Unavailable" on a g2408 with the upstream integration.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final


class Property(StrEnum):
    BATTERY_LEVEL = "battery_level"
    STATE = "state"
    CHARGING_STATUS = "charging_status"
    MOWING_TELEMETRY = "mowing_telemetry"
    HEARTBEAT = "heartbeat"
    OBSTACLE_FLAG = "obstacle_flag"
    MULTIPLEXED_CONFIG = "multiplexed_config"


PROPERTY_MAP: Final[dict[Property, tuple[int, int]]] = {
    Property.BATTERY_LEVEL: (3, 1),
    Property.STATE: (2, 2),
    Property.CHARGING_STATUS: (3, 2),
    Property.MOWING_TELEMETRY: (1, 4),
    Property.HEARTBEAT: (1, 1),
    Property.OBSTACLE_FLAG: (1, 53),
    Property.MULTIPLEXED_CONFIG: (2, 51),
}

_REVERSE_MAP: Final[dict[tuple[int, int], Property]] = {
    v: k for k, v in PROPERTY_MAP.items()
}


def siid_piid(prop: Property) -> tuple[int, int]:
    """Return the g2408 (siid, piid) tuple for a Property."""
    return PROPERTY_MAP[prop]


def property_for(siid: int, piid: int) -> Property | None:
    """Reverse-lookup a Property from a (siid, piid) tuple, or None if unknown."""
    return _REVERSE_MAP.get((siid, piid))


class StateCode(IntEnum):
    SESSION_STARTED = 50          # manual start from app
    SESSION_STARTED_SCHEDULED = 53  # scheduled start (confirmed 2026-04-20)
    MOWING = 70
    RETURNING = 54
    MOWING_COMPLETE = 48          # transient, ~5 s before POST_SESSION_IDLE
    IDLE = 27                     # powered but no session yet (pre-start)
    POST_SESSION_IDLE = 31        # parked at dock after mowing_complete;
                                  # persists until next session_started.
                                  # Confirmed 2026-04-24 at end-of-run.
    RAIN_PROTECTION = 56          # water detected on LiDAR → dock (2026-04-19)
    POSITIONING_FAILED = 71       # SLAM relocate needed (2026-04-20)


_STATE_LABELS: Final[dict[int, str]] = {
    StateCode.SESSION_STARTED: "session_started",
    StateCode.SESSION_STARTED_SCHEDULED: "session_started_scheduled",
    StateCode.MOWING: "mowing",
    StateCode.RETURNING: "returning",
    StateCode.MOWING_COMPLETE: "mowing_complete",
    StateCode.IDLE: "idle",
    StateCode.POST_SESSION_IDLE: "post_session_idle",
    StateCode.RAIN_PROTECTION: "rain_protection",
    StateCode.POSITIONING_FAILED: "positioning_failed",
}


def state_label(code: int) -> str:
    """Translate a raw s2p2 code into a human-readable label."""
    return _STATE_LABELS.get(int(code), f"unknown_{int(code)}")


class ChargingStatus(IntEnum):
    # Upstream enum starts at 1; g2408 includes 0 = not_charging.
    NOT_CHARGING = 0
    CHARGING = 1
    CHARGED = 2


_CHARGING_LABELS: Final[dict[int, str]] = {
    ChargingStatus.NOT_CHARGING: "not_charging",
    ChargingStatus.CHARGING: "charging",
    ChargingStatus.CHARGED: "charged",
}


def charging_label(code: int) -> str:
    return _CHARGING_LABELS.get(int(code), f"unknown_{int(code)}")
