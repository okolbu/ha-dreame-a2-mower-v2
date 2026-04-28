"""Sensor platform for the Dreame A2 Mower.

F1: battery_level + charging_status. F2 adds the rest of §2.1's
confirmed-source sensors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class DreameA2SensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], Any]


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
        key="total_distance_m",
        name="Session distance",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_distance_m,
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
        key="side_brush_life_pct",
        name="Side brush life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.side_brush_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="total_cleaning_time_min",
        name="Total cleaning time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_cleaning_time_min,
    ),
    DreameA2SensorEntityDescription(
        key="total_cleaned_area_m2",
        name="Total cleaned area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_cleaned_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="cleaning_count",
        name="Cleaning count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.cleaning_count,
    ),
    DreameA2SensorEntityDescription(
        key="first_cleaning_date",
        name="First cleaning date",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.first_cleaning_date,
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
