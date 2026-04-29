"""Sensor platform for the Dreame A2 Mower.

F1: battery_level + charging_status. F2 adds the rest of §2.1's
confirmed-source sensors.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.error_codes import describe_error
from .mower.state import ChargingStatus, MowerState


def _describe_error_or_none(code: int | None) -> str | None:
    return describe_error(code) if code is not None else None


def _format_active_selection(state: MowerState) -> str | None:
    """Format zone/spot selection for display.

    Examples:
      action_mode=all_areas → 'All areas'
      action_mode=edge → 'Edge mow'
      action_mode=zone, zones=(3, 1, 2) → 'Zones 3 → 1 → 2'
      action_mode=zone, zones=() → 'No zones selected'
      action_mode=spot, spots=() → 'No spots selected'
    """
    from .mower.state import ActionMode
    mode = state.action_mode
    if mode == ActionMode.ALL_AREAS:
        return "All areas"
    if mode == ActionMode.EDGE:
        return "Edge mow"
    if mode == ActionMode.ZONE:
        zones = state.active_selection_zones
        if not zones:
            return "No zones selected"
        return "Zones " + " → ".join(str(z) for z in zones)
    if mode == ActionMode.SPOT:
        spots = state.active_selection_spots
        if not spots:
            return "No spots selected"
        return "Spots " + " → ".join(str(s) for s in spots)
    return None


def _api_endpoints_value(coord) -> int:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return 0
    return sum(1 for v in cloud.endpoint_log.values() if v == "accepted")


def _api_endpoints_attrs(coord) -> dict[str, list[str]]:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return {"accepted": [], "rejected_80001": [], "error": []}
    log = cloud.endpoint_log
    return {
        "accepted": sorted(k for k, v in log.items() if v == "accepted"),
        "rejected_80001": sorted(k for k, v in log.items() if v == "rejected_80001"),
        "error": sorted(k for k, v in log.items() if v == "error"),
    }


def _freshness_value(coord) -> int | None:
    """Age in seconds of the oldest tracked field, or None if nothing
    has been stamped yet."""
    snap = coord.freshness.snapshot()
    if not snap:
        return None
    now = int(time.time())
    return now - min(snap.values())


def _freshness_attrs(coord) -> dict[str, int]:
    """Per-field age in seconds, keyed as ``{field}_age_s``."""
    snap = coord.freshness.snapshot()
    now = int(time.time())
    return {f"{name}_age_s": now - ts for name, ts in snap.items()}


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


SENSORS: tuple[DreameA2SensorEntityDescription, ...] = (
    DreameA2SensorEntityDescription(
        key="battery_level",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.battery_level,
    ),
    DreameA2SensorEntityDescription(
        key="charging_status",
        name="Charging status",
        device_class=SensorDeviceClass.ENUM,
        options=[c.name.lower() for c in ChargingStatus],
        value_fn=lambda s: (s.charging_status.name.lower() if s.charging_status is not None else None),
    ),

    # Position trio:
    DreameA2SensorEntityDescription(
        key="position_x_m",
        name="Position X",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.position_x_m,
    ),
    DreameA2SensorEntityDescription(
        key="position_y_m",
        name="Position Y",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.position_y_m,
    ),
    DreameA2SensorEntityDescription(
        key="position_north_m",
        name="Position North",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.position_north_m,
    ),
    DreameA2SensorEntityDescription(
        key="position_east_m",
        name="Position East",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.position_east_m,
    ),

    # Telemetry-derived:
    DreameA2SensorEntityDescription(
        key="area_mowed_m2",
        name="Area mowed",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.area_mowed_m2,
    ),
    DreameA2SensorEntityDescription(
        key="mowing_phase",
        name="Mowing phase",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.mowing_phase,
    ),

    # State-related:
    DreameA2SensorEntityDescription(
        key="error_code",
        name="Error code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.error_code,
    ),
    DreameA2SensorEntityDescription(
        key="error_description",
        name="Error",
        value_fn=lambda s: _describe_error_or_none(s.error_code),
    ),
    DreameA2SensorEntityDescription(
        key="task_state_code",
        name="Task state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.task_state_code,
    ),
    DreameA2SensorEntityDescription(
        key="slam_task_label",
        name="SLAM task",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.slam_task_label,
    ),

    # Lawn / environment:
    DreameA2SensorEntityDescription(
        key="total_lawn_area_m2",
        name="Total lawn area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_lawn_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="wifi_rssi_dbm",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.wifi_rssi_dbm,
    ),

    # CFG-derived consumables:
    DreameA2SensorEntityDescription(
        key="blades_life_pct",
        name="Blades life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.blades_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="cleaning_brush_life_pct",
        name="Cleaning brush life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.cleaning_brush_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowing_time_min",
        name="Total mowing time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_mowing_time_min,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowed_area_m2",
        name="Total mowed area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_mowed_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="mowing_count",
        name="Mowing count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.mowing_count,
    ),
    DreameA2SensorEntityDescription(
        key="first_mowing_date",
        name="First mowing date",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.first_mowing_date,
    ),
    DreameA2SensorEntityDescription(
        key="active_selection",
        name="Active selection",
        value_fn=_format_active_selection,
    ),

    # Settings-derived (s2.51) observability:
    DreameA2SensorEntityDescription(
        key="last_settings_change_unix",
        name="Last settings change",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_settings_change_unix,
    ),
    DreameA2SensorEntityDescription(
        key="language_text_idx",
        name="Language text index",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.language_text_idx,
    ),
    DreameA2SensorEntityDescription(
        key="language_voice_idx",
        name="Language voice index",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.language_voice_idx,
    ),

    # ------ v1.0.0a11: raw protocol diagnostic sensors per spec §5.6 ------
    DreameA2SensorEntityDescription(
        key="s5p104_raw",
        name="s5.104 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p104_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p105_raw",
        name="s5.105 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p105_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p106_raw",
        name="s5.106 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p106_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p107_raw",
        name="s5.107 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p107_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s6p1_raw",
        name="s6.1 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s6p1_raw,
    ),

    # ------ F5.11.1: session history sensors ------

    DreameA2SensorEntityDescription(
        key="latest_session_area_m2",
        name="Latest session area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.latest_session_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_duration_min",
        name="Latest session duration",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.latest_session_duration_min,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_unix_ts",
        name="Latest session time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: (
            datetime.fromtimestamp(s.latest_session_unix_ts, tz=timezone.utc)
            if s.latest_session_unix_ts is not None
            else None
        ),
    ),
    DreameA2SensorEntityDescription(
        key="archived_session_count",
        name="Archived session count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_session_count,
    ),
    DreameA2SensorEntityDescription(
        key="lidar_archive_count",
        translation_key="lidar_archive_count",
        icon="mdi:cube-scan",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_lidar_count,
    ),
    DreameA2SensorEntityDescription(
        key="session_track_point_count",
        name="Session track point count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            sum(len(leg) for leg in s.session_track_segments)
            if s.session_track_segments is not None
            else None
        ),
    ),
)


DIAGNOSTIC_SENSORS: tuple[DreameA2DiagnosticSensorEntityDescription, ...] = (
    DreameA2DiagnosticSensorEntityDescription(
        key="novel_observations",
        translation_key="novel_observations",
        icon="mdi:eye-question",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        value_fn=lambda coord: coord.novel_registry.snapshot().count,
        extra_state_attributes_fn=lambda coord: {
            "observations": [
                {
                    "category": o.category,
                    "detail": o.detail,
                    "first_seen_unix": o.first_seen_unix,
                }
                for o in coord.novel_registry.snapshot().observations
            ],
        },
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="data_freshness",
        translation_key="data_freshness",
        native_unit_of_measurement="s",
        icon="mdi:clock-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_freshness_value,
        extra_state_attributes_fn=_freshness_attrs,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="api_endpoints_supported",
        translation_key="api_endpoints_supported",
        icon="mdi:api",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_api_endpoints_value,
        extra_state_attributes_fn=_api_endpoints_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DreameA2Sensor(coordinator, desc) for desc in SENSORS]
        + [DreameA2DiagnosticSensor(coordinator, desc) for desc in DIAGNOSTIC_SENSORS]
    )


class DreameA2Sensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed sensor entity."""

    _attr_has_entity_name = True
    entity_description: DreameA2SensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        client = coordinator._cloud  # may be None during very-early setup
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class DreameA2DiagnosticSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed diagnostic sensor.

    Reads from the coordinator directly (registry, freshness tracker,
    endpoint log) rather than from MowerState. Uses
    ``DreameA2DiagnosticSensorEntityDescription`` with ``value_fn``
    accepting a coordinator and an optional
    ``extra_state_attributes_fn``.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2DiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2DiagnosticSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        client = coordinator._cloud
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.extra_state_attributes_fn
        if fn is None:
            return None
        return fn(self.coordinator)
