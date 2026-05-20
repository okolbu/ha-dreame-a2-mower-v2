"""Shared base classes and description dataclasses for the sensor platform.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a sensor platform.  It is imported by sensor_device.py,
sensor_map.py, sensor_session.py, and sensor.py.

Acyclic import order:
    _sensor_base  ←  sensor_device / sensor_map / sensor_session  ←  sensor.py
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2SensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], Any]


@dataclass(frozen=True, kw_only=True)
class DreameA2DiagnosticSensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor for diagnostic entities that read coordinator state.

    Unlike ``DreameA2SensorEntityDescription`` whose ``value_fn`` takes
    a ``MowerState``, diagnostic sensors need access to the coordinator
    itself (for the registry, freshness tracker, endpoint log). The
    ``value_fn`` here takes the coordinator.
    """

    value_fn: Callable[[Any], Any]
    extra_state_attributes_fn: Callable[[Any], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# _SnapshotEnumSensorBase — used by device-level enum sensors
# ---------------------------------------------------------------------------

class _SnapshotEnumSensorBase(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Common base for ENUM sensors that read an enum field from the snapshot."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _SNAPSHOT_FIELD: str = "override-me"
    _KEY: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, self._KEY)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        snap = self.coordinator.state_machine.snapshot()
        val = getattr(snap, self._SNAPSHOT_FIELD)
        return val.value if val is not None else None


# ---------------------------------------------------------------------------
# _DreameA2PerMapSensorBase — base for all per-map sensors
# ---------------------------------------------------------------------------

class _DreameA2PerMapSensorBase(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Base for per-map sensors. Subclasses set _KEY and override _compute_value."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _KEY: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, self._KEY)
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, map_name)

    def _map(self):
        return self.coordinator.cloud_state.maps_by_id.get(self._map_id)

    def _compute_value(self, map_data):
        raise NotImplementedError

    @property
    def native_value(self):
        m = self._map()
        if m is None:
            return None
        return self._compute_value(m)


# ---------------------------------------------------------------------------
# _DreameA2PerMapPreShadowBase — PRE-shadow sensors
# ---------------------------------------------------------------------------

class _DreameA2PerMapPreShadowBase(_DreameA2PerMapSensorBase):
    """Base for per-map sensors that read from the state-machine PRE shadow."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _shadow_entry(self) -> dict | None:
        sm = getattr(self.coordinator, "state_machine", None)
        if sm is None:
            return None
        try:
            snap = sm.snapshot()
        except Exception:
            return None
        shadow = getattr(snap, "pre_shadow_by_map_id", None) or {}
        entry = shadow.get(self._map_id)
        if not isinstance(entry, dict):
            return None
        return entry

    @property
    def native_value(self):
        # Override the base (which reads MapData via _map()); shadow lives
        # on the snapshot, not on MapData. Returns None when the shadow
        # has no entry for this map yet (user hasn't saved settings on
        # this map since install).
        entry = self._shadow_entry()
        if entry is None:
            return None
        return self._compute_shadow_value(entry)

    def _compute_shadow_value(self, entry: dict):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# _DreameA2PerMapSessionSensorBase — session-archive aggregators
# ---------------------------------------------------------------------------

class _DreameA2PerMapSessionSensorBase(_DreameA2PerMapSensorBase):
    """Per-map aggregator over the session archive index.

    Reads ``session_archive._index`` directly instead of calling the
    public ``list_sessions()`` because the latter is executor-only
    (re-reads disk via ``load_index()`` + sorts). The ``_index`` list
    is preloaded at boot and safe to read from the event loop. The
    legacy/unknown `map_id == -1` entries are naturally excluded by
    the `== self._map_id` filter (never matches a real map_id).
    """

    def _sessions_for_map(self):
        archive = getattr(self.coordinator, "session_archive", None)
        index = getattr(archive, "_index", None) or []
        return [s for s in index if getattr(s, "map_id", None) == self._map_id]
