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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ChargingStatus, MowerState


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
