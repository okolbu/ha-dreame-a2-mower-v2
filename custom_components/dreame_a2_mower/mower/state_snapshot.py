"""StateSnapshot dataclass + dimension enums.

Defined in a separate file from MowerStateMachine to keep the type
surface importable without pulling the state-machine logic (avoids
circular imports across the package).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MowSession(Enum):
    IN_SESSION = "in_session"
    BETWEEN_SESSIONS = "between_sessions"


class CurrentActivity(Enum):
    MOWING = "mowing"
    PAUSED = "paused"
    REPOSITIONING = "repositioning"
    RETURNING = "returning"
    CHARGE_RESUME = "charge_resume"
    CRUISING_TO_POINT = "cruising_to_point"
    AT_POINT = "at_point"
    FAST_MAPPING = "fast_mapping"
    DRIVING_BLADES_UP = "driving_blades_up"
    IDLE = "idle"


class Location(Enum):
    AT_DOCK = "at_dock"
    ON_LAWN = "on_lawn"
    AT_POINT = "at_point"
    OUTSIDE_KNOWN_AREA = "outside_known_area"


class PositioningHealth(Enum):
    LOCALIZED = "localized"
    RELOCATING = "relocating"
    STUCK = "stuck"


class Connectivity(Enum):
    ONLINE = "online"
    STALE = "stale"


class RpcHealth(Enum):
    OK = "ok"
    FAILING = "failing"


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable multi-dim mower state. Replace via `dataclasses.replace`."""

    # Multi-dim state
    mow_session: MowSession
    current_activity: CurrentActivity
    location: Location
    positioning_health: PositioningHealth
    charging: bool
    errors: frozenset[int]
    pin_required: bool
    mqtt_connectivity: Connectivity
    cloud_rpc_health: RpcHealth

    # Provenance + freshness
    last_heartbeat_unix: int | None
    field_freshness: dict[str, int]

    # Pre-disambiguation / debug
    paused_from: CurrentActivity | None
    last_task_op: int | None
    raw_s2p1: int | None
    raw_s2p2: int | None

    # Scalars
    battery_percent: int | None
    position_x_m: float | None
    position_y_m: float | None
    position_north_m: float | None
    position_east_m: float | None
    wifi_rssi_dbm: int | None
    mowing_phase: int | None
    task_state_code: int | None
    slam_task_label: str | None

    @classmethod
    def initial(cls) -> "StateSnapshot":
        return cls(
            mow_session=MowSession.BETWEEN_SESSIONS,
            current_activity=CurrentActivity.IDLE,
            location=Location.AT_DOCK,
            positioning_health=PositioningHealth.LOCALIZED,
            charging=False,
            errors=frozenset(),
            pin_required=False,
            mqtt_connectivity=Connectivity.STALE,
            cloud_rpc_health=RpcHealth.OK,
            last_heartbeat_unix=None,
            field_freshness={},
            paused_from=None,
            last_task_op=None,
            raw_s2p1=None,
            raw_s2p2=None,
            battery_percent=None,
            position_x_m=None,
            position_y_m=None,
            position_north_m=None,
            position_east_m=None,
            wifi_rssi_dbm=None,
            mowing_phase=None,
            task_state_code=None,
            slam_task_label=None,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-able serialisation. Enums → name strings, frozenset → sorted list."""
        d: dict[str, Any] = {
            "mow_session": self.mow_session.name,
            "current_activity": self.current_activity.name,
            "location": self.location.name,
            "positioning_health": self.positioning_health.name,
            "charging": self.charging,
            "errors": sorted(self.errors),
            "pin_required": self.pin_required,
            "mqtt_connectivity": self.mqtt_connectivity.name,
            "cloud_rpc_health": self.cloud_rpc_health.name,
            "last_heartbeat_unix": self.last_heartbeat_unix,
            "field_freshness": dict(self.field_freshness),
            "paused_from": self.paused_from.name if self.paused_from else None,
            "last_task_op": self.last_task_op,
            "raw_s2p1": self.raw_s2p1,
            "raw_s2p2": self.raw_s2p2,
            "battery_percent": self.battery_percent,
            "position_x_m": self.position_x_m,
            "position_y_m": self.position_y_m,
            "position_north_m": self.position_north_m,
            "position_east_m": self.position_east_m,
            "wifi_rssi_dbm": self.wifi_rssi_dbm,
            "mowing_phase": self.mowing_phase,
            "task_state_code": self.task_state_code,
            "slam_task_label": self.slam_task_label,
        }
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StateSnapshot":
        return cls(
            mow_session=MowSession[raw["mow_session"]],
            current_activity=CurrentActivity[raw["current_activity"]],
            location=Location[raw["location"]],
            positioning_health=PositioningHealth[raw["positioning_health"]],
            charging=bool(raw["charging"]),
            errors=frozenset(int(c) for c in raw.get("errors") or []),
            pin_required=bool(raw["pin_required"]),
            mqtt_connectivity=Connectivity[raw["mqtt_connectivity"]],
            cloud_rpc_health=RpcHealth[raw["cloud_rpc_health"]],
            last_heartbeat_unix=raw.get("last_heartbeat_unix"),
            field_freshness=dict(raw.get("field_freshness") or {}),
            paused_from=(
                CurrentActivity[raw["paused_from"]]
                if raw.get("paused_from") else None
            ),
            last_task_op=raw.get("last_task_op"),
            raw_s2p1=raw.get("raw_s2p1"),
            raw_s2p2=raw.get("raw_s2p2"),
            battery_percent=raw.get("battery_percent"),
            position_x_m=raw.get("position_x_m"),
            position_y_m=raw.get("position_y_m"),
            position_north_m=raw.get("position_north_m"),
            position_east_m=raw.get("position_east_m"),
            wifi_rssi_dbm=raw.get("wifi_rssi_dbm"),
            mowing_phase=raw.get("mowing_phase"),
            task_state_code=raw.get("task_state_code"),
            slam_task_label=raw.get("slam_task_label"),
        )
