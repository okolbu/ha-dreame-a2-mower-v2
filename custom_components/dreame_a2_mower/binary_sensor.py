"""Binary sensor platform for the Dreame A2 Mower."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


@dataclass(frozen=True, kw_only=True)
class DreameA2BinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], bool | None]


BINARY_SENSORS: tuple[DreameA2BinarySensorEntityDescription, ...] = (
    DreameA2BinarySensorEntityDescription(
        key="obstacle_detected",
        name="Obstacle detected",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda s: s.obstacle_flag,
    ),
    DreameA2BinarySensorEntityDescription(
        key="rain_protection_active",
        name="Rain protection active",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda s: (s.error_code == 56) if s.error_code is not None else None,
    ),
    DreameA2BinarySensorEntityDescription(
        key="positioning_failed",
        name="Positioning failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: (s.error_code == 71) if s.error_code is not None else None,
    ),
    DreameA2BinarySensorEntityDescription(
        key="battery_temp_low",
        name="Battery temperature low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery_temp_low,
    ),
    DreameA2BinarySensorEntityDescription(
        key="mowing_session_active",
        name="Mowing session active",
        device_class=BinarySensorDeviceClass.RUNNING,
        # F5.11.1: read MowerState.session_active directly — the
        # authoritative source populated by _on_state_update from
        # live_map.is_active(). (Replaces an early prototype that
        # peeked at task_state_code with legacy semantic codes.)
        value_fn=lambda s: s.session_active,
    ),

    # s1.1 error bit-mask sensors — confirmed 2026-04-30 19:37–19:39
    # against corresponding app notifications.
    DreameA2BinarySensorEntityDescription(
        key="drop_tilt",
        name="Robot tilted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.drop_tilt,
    ),
    DreameA2BinarySensorEntityDescription(
        key="bumper",
        name="Bumper error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.bumper,
    ),
    DreameA2BinarySensorEntityDescription(
        key="lift",
        name="Robot lifted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.lift,
    ),
    DreameA2BinarySensorEntityDescription(
        key="emergency_stop",
        name="Emergency stop activated",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.emergency_stop,
    ),
    DreameA2BinarySensorEntityDescription(
        # byte[10] bit 1 — one-shot active-alert flag confirmed during
        # the 2026-05-04 controlled-lift test series. Sets ~1s after
        # the safety event, self-clears 30–90s later regardless of
        # whether the user typed PIN or closed the lid. Pairs with the
        # Dreame app's "Emergency stop activated" push notification +
        # the mower's red LED + voice prompt. The actual persistent
        # PIN-required latch is `binary_sensor.emergency_stop_activated`
        # (byte[3] bit 7), which only clears on PIN entry.
        key="safety_alert_active",
        name="Safety alert active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.safety_alert_active,
    ),
    DreameA2BinarySensorEntityDescription(
        key="top_cover_open",
        name="Top cover open",
        device_class=BinarySensorDeviceClass.OPENING,
        # apk fault index `73 = TOP_COVER_OPEN`. Confirmed 2026-04-30
        # 19:39:35 — fired exactly when the user opened the top cover to
        # type the security PIN after an emergency-stop trip.
        value_fn=lambda s: (s.error_code == 73) if s.error_code is not None else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DreameA2BinarySensor(coordinator, desc) for desc in BINARY_SENSORS]
    )


class DreameA2BinarySensor(
    CoordinatorEntity[DreameA2MowerCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    entity_description: DreameA2BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        # Same DeviceInfo as the lawn_mower / sensor entities — clusters under one device.
        client = coordinator._cloud
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
