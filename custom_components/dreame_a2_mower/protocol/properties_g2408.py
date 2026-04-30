"""g2408-specific siid/piid map and state-code translations.

This replaces the multi-model property registry from upstream's dreame/types.py
with values observed on the Dreame A2 (model dreame.mower.g2408) via MQTT
probing. Upstream's mapping was built for A1 Pro and earlier vacuum-derived
mowers, which use different siid/piid assignments — the reason so many entities
show "Unavailable" on a g2408 with the upstream integration.

Note: an earlier revision of this module exposed a ``StateCode`` enum and
``state_label()`` helper that mapped (2, 2) to a "STATE" property. That
reading was wrong: (2, 2) carries the apk fault index, not a state machine,
and (2, 1) is the small enum that actually reflects mower state. The dead
``Property.STATE = (2, 2)``, ``StateCode``, ``state_label`` symbols were
removed 2026-04-30; the runtime dispatch in ``mower/property_mapping.py``
has always routed (2, 2) to ``error_code`` and (2, 1) to ``state``.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final


class Property(StrEnum):
    BATTERY_LEVEL = "battery_level"
    CHARGING_STATUS = "charging_status"
    MOWING_TELEMETRY = "mowing_telemetry"
    HEARTBEAT = "heartbeat"
    OBSTACLE_FLAG = "obstacle_flag"
    MULTIPLEXED_CONFIG = "multiplexed_config"


PROPERTY_MAP: Final[dict[Property, tuple[int, int]]] = {
    Property.BATTERY_LEVEL: (3, 1),
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
