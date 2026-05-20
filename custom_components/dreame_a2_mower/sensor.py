"""Sensor platform for the Dreame A2 Mower.

This file is the HA platform entry: it owns `async_setup_entry` only. The
entity classes are split across sibling modules (B3a):
  - `_sensor_base.py`     — shared bases + EntityDescription dataclasses
  - `sensor_device.py`    — device-level sensors + the SENSORS / DIAGNOSTIC_SENSORS tables
  - `sensor_map.py`       — per-map metadata sensors
  - `sensor_session.py`   — per-map session-total sensors
The re-export block below keeps `from ...sensor import <X>` working for tests
and tools that import entity classes / helpers directly from this module.
"""
from __future__ import annotations

import time  # noqa: F401 — re-exported so tests can patch sensor.time.time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .sensor_device import (
    DIAGNOSTIC_SENSORS,
    SENSORS,
    DreameA2ApiEndpointSensor,
    DreameA2CurrentActivitySensor,
    DreameA2DiagnosticSensor,
    DreameA2IntegrationVersionSensor,
    DreameA2LastNotificationSensor,
    DreameA2LocationSensor,
    DreameA2MqttConnectivitySensor,
    DreameA2OtaStatusSensor,
    DreameA2PickedSessionSensor,
    DreameA2PositioningHealthSensor,
    DreameA2ScheduleCountSensor,
    DreameA2Sensor,
    DreameA2WifiHeatmapAgeSensor,
    DreameA2WifiRefreshStatusSensor,
    _api_endpoints_value,
    _describe_error_or_none,
    _format_active_selection,
    _freshness_value,
)
from .sensor_map import (
    DreameA2ExclusionZonesSensor,
    DreameA2IgnoreObstacleZonesSensor,
    DreameA2MaintenancePointsSensor,
    DreameA2MapAreaSensor,
    DreameA2MapNameSensor,
    DreameA2MapPreEdgemasterSensor,
    DreameA2MapPreMowingHeightSensor,
    DreameA2MapSegmentCountSensor,
    DreameA2SpotsCountSensor,
)
from .sensor_session import (
    DreameA2MapSessionAreaTotalSensor,
    DreameA2MapSessionCountSensor,
    DreameA2MapSessionTimeTotalSensor,
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = (
        [DreameA2Sensor(coordinator, desc) for desc in SENSORS]
        + [DreameA2DiagnosticSensor(coordinator, desc) for desc in DIAGNOSTIC_SENSORS]
        + [
            DreameA2OtaStatusSensor(coordinator),
            DreameA2ScheduleCountSensor(coordinator),
            DreameA2WifiRefreshStatusSensor(coordinator),
            DreameA2WifiHeatmapAgeSensor(coordinator),
            DreameA2LastNotificationSensor(coordinator),
            DreameA2CurrentActivitySensor(coordinator),
            DreameA2LocationSensor(coordinator),
            DreameA2PositioningHealthSensor(coordinator),
            DreameA2MqttConnectivitySensor(coordinator),
            DreameA2ApiEndpointSensor(coordinator),
            DreameA2IntegrationVersionSensor(coordinator),
            DreameA2PickedSessionSensor(coordinator),
        ]
    )
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.extend([
            DreameA2MapNameSensor(coordinator, map_id=map_id),
            DreameA2MapAreaSensor(coordinator, map_id=map_id),
            DreameA2MapSegmentCountSensor(coordinator, map_id=map_id),
            DreameA2MaintenancePointsSensor(coordinator, map_id=map_id),
            DreameA2ExclusionZonesSensor(coordinator, map_id=map_id),
            DreameA2IgnoreObstacleZonesSensor(coordinator, map_id=map_id),
            DreameA2SpotsCountSensor(coordinator, map_id=map_id),
            DreameA2MapPreMowingHeightSensor(coordinator, map_id=map_id),
            # DreameA2MapPreMowingEfficiencySensor removed 2026-05-15 —
            # superseded by select.dreame_a2_mower_map_N_mowing_efficiency
            # (DreameA2MapMowingEfficiencySelect in select.py).
            DreameA2MapPreEdgemasterSensor(coordinator, map_id=map_id),
            DreameA2MapSessionAreaTotalSensor(coordinator, map_id=map_id),
            DreameA2MapSessionTimeTotalSensor(coordinator, map_id=map_id),
            DreameA2MapSessionCountSensor(coordinator, map_id=map_id),
        ])
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Backward-compat re-exports for tests and audit tools
# ---------------------------------------------------------------------------
# Each name below is imported from sensor.py in at least one test or tool file.
# Moving a name to a group module without re-exporting it here would break
# those callers.  Do NOT add names here unless a caller actually imports them.
#
# tests/integration/test_cloud_state_sensors.py: DreameA2OtaStatusSensor,
#     DreameA2ScheduleCountSensor
# tests/integration/test_coordinator.py: DIAGNOSTIC_SENSORS
# tests/integration/test_diagnostic_sensors_new.py: DIAGNOSTIC_SENSORS,
#     DreameA2ApiEndpointSensor, DreameA2IntegrationVersionSensor
# tests/integration/test_maintenance_points_sensor.py: DreameA2MaintenancePointsSensor
# tests/integration/test_per_map_cameras.py: DreameA2WifiRefreshStatusSensor,
#     DreameA2WifiHeatmapAgeSensor
# tests/integration/test_per_map_metadata_sensors.py: DreameA2MapNameSensor,
#     DreameA2MapAreaSensor, DreameA2MapSegmentCountSensor
# tests/integration/test_per_map_sensors.py: DreameA2MapAreaSensor,
#     DreameA2MapSegmentCountSensor, DreameA2MapNameSensor,
#     DreameA2MapPreMowingHeightSensor
# tests/integration/test_per_map_session_totals.py: DreameA2MapSessionAreaTotalSensor,
#     DreameA2MapSessionTimeTotalSensor, DreameA2MapSessionCountSensor
# tests/integration/test_picked_session.py: DreameA2PickedSessionSensor
# tests/integration/test_pre_shadow_sensors.py: DreameA2MapPreMowingHeightSensor,
#     DreameA2MapPreEdgemasterSensor
# tests/state_machine/test_new_dimension_sensors.py: DreameA2CurrentActivitySensor,
#     DreameA2LocationSensor, DreameA2PositioningHealthSensor,
#     DreameA2MqttConnectivitySensor
# tools/state_machine_audit_fake_coord.py: _describe_error_or_none,
#     _format_active_selection, _api_endpoints_value, _freshness_value
#
# All names are already imported above and therefore available as attributes
# of this module — no additional assignment needed.
