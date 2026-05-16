"""Binary sensor platform for the Dreame A2 Mower."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState
from .mower.state_snapshot import Location, MowSession


@dataclass(frozen=True, kw_only=True)
class DreameA2BinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor descriptor with a typed value_fn.

    value_fn receives the coordinator (not MowerState) so snapshot-backed
    sensors can call coordinator.state_machine.snapshot() directly.
    Sensors that still read from MowerState use coordinator.data.
    """

    value_fn: Callable[[DreameA2MowerCoordinator], bool | None]


BINARY_SENSORS: tuple[DreameA2BinarySensorEntityDescription, ...] = (
    DreameA2BinarySensorEntityDescription(
        key="obstacle_detected",
        translation_key="obstacle_detected",
        name="Obstacle detected",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda coord: bool(coord.data.obstacle_flag),
    ),
    DreameA2BinarySensorEntityDescription(
        key="rain_protection_active",
        translation_key="rain_protection_active",
        name="Rain protection active",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda coord: coord.data.error_code == 56,
    ),
    DreameA2BinarySensorEntityDescription(
        key="positioning_failed",
        translation_key="positioning_failed",
        name="Positioning failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: coord.data.error_code == 71,
    ),
    DreameA2BinarySensorEntityDescription(
        key="failed_to_return_to_station",
        translation_key="failed_to_return_to_station",
        name="Failed to return to station",
        device_class=BinarySensorDeviceClass.PROBLEM,
        # s2p2 = 31. Two paths in: 33→31 (positioning / task-start
        # failure) and 48→31 direct (edge-mow auto-dock planner couldn't
        # route home from a stuck pose). Both surface the Dreame app's
        # "Failed to return to station" notification. Recovery is a
        # user-tapped Recharge from the app — the integration does not
        # auto-recover. See g2408-protocol.md §4.6.1.
        value_fn=lambda coord: coord.data.error_code == 31,
    ),
    DreameA2BinarySensorEntityDescription(
        key="battery_temp_low",
        translation_key="battery_temp_low",
        name="Battery temperature low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: bool(coord.data.battery_temp_low),
    ),
    DreameA2BinarySensorEntityDescription(
        key="mowing_session_active",
        translation_key="mowing_session_active",
        name="Mowing session active",
        device_class=BinarySensorDeviceClass.RUNNING,
        # SM-12: reads from state_machine snapshot. MowSession.IN_SESSION
        # is only set during a real mow (all-area / zone / spot / edge).
        # Cruise-to-point leaves mow_session=BETWEEN_SESSIONS, so this
        # sensor correctly stays OFF during a cruise — unlike the old
        # MowerState.session_active which fired for any active task type.
        value_fn=lambda coord: (
            coord.state_machine.snapshot().mow_session == MowSession.IN_SESSION
        ),
    ),

    # s1.1 error bit-mask sensors - confirmed 2026-04-30 19:37-19:39
    # against corresponding app notifications.
    DreameA2BinarySensorEntityDescription(
        key="drop_tilt",
        translation_key="drop_tilt",
        name="Robot tilted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: bool(coord.data.drop_tilt),
    ),
    DreameA2BinarySensorEntityDescription(
        key="bumper",
        translation_key="bumper",
        name="Bumper error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: bool(coord.data.bumper),
    ),
    DreameA2BinarySensorEntityDescription(
        key="lift",
        translation_key="lift",
        name="Robot lifted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: bool(coord.data.lift),
    ),
    DreameA2BinarySensorEntityDescription(
        key="emergency_stop",
        translation_key="emergency_stop",
        name="Emergency stop activated",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: bool(coord.data.emergency_stop),
    ),
    DreameA2BinarySensorEntityDescription(
        # byte[10] bit 1 — one-shot active-alert flag confirmed during
        # the 2026-05-04 controlled-lift test series. Sets ~1s after
        # the safety event, self-clears 30-90s later regardless of
        # whether the user typed PIN or closed the lid. Pairs with the
        # Dreame app's "Emergency stop activated" push notification +
        # the mower's red LED + voice prompt. The actual persistent
        # PIN-required latch is `binary_sensor.emergency_stop_activated`
        # (byte[3] bit 7), which only clears on PIN entry.
        key="safety_alert_active",
        translation_key="safety_alert_active",
        name="Safety alert active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda coord: bool(coord.data.safety_alert_active),
    ),
    DreameA2BinarySensorEntityDescription(
        key="top_cover_open",
        translation_key="top_cover_open",
        name="Top cover open",
        device_class=BinarySensorDeviceClass.OPENING,
        # apk fault index `73 = TOP_COVER_OPEN`. Confirmed 2026-04-30
        # 19:39:35 — fired exactly when the user opened the top cover to
        # type the security PIN after an emergency-stop trip.
        value_fn=lambda coord: coord.data.error_code == 73,
    ),
    DreameA2BinarySensorEntityDescription(
        key="mower_in_dock",
        translation_key="mower_in_dock",
        name="Mower in dock",
        # SM-12: reads from state_machine snapshot. Location.AT_DOCK is
        # set by handle_cloud_poll when CFG.DOCK.connect_status is truthy,
        # and cleared by handle_mqtt_property when s2p2 transitions to an
        # active task state. This avoids the ~1-hour CFG poll staleness
        # that caused mower_in_dock to stay True throughout an entire mow.
        value_fn=lambda coord: (
            coord.state_machine.snapshot().location == Location.AT_DOCK
        ),
    ),
    DreameA2BinarySensorEntityDescription(
        key="dock_in_lawn_region",
        translation_key="dock_in_lawn_region",
        name="Dock inside lawn region",
        entity_category=EntityCategory.DIAGNOSTIC,
        # CFG.DOCK.in_region — flips depending on whether the dock was
        # placed inside or outside the mowable lawn polygon.
        value_fn=lambda coord: coord.data.dock_in_lawn_region,
    ),
    DreameA2BinarySensorEntityDescription(
        key="wheel_bind_active",
        translation_key="wheel_bind_active",
        name="Wheel bind detected",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Cross-frame s1.4 diagnostic: position held within 50 mm
        # while area_mowed advanced > 0.05 m². Reproduced 2026-05-05
        # during integration-launched edge runs that hit FTRTS — the
        # firmware's area integrator keeps counting while the wheels
        # are physically stalled in tight maneuvering spots, draining
        # the edge-mode budget while wedged. See
        # docs/research/g2408-protocol.md §4.6 and
        # custom_components/dreame_a2_mower/protocol/wheel_bind.py.
        value_fn=lambda coord: bool(coord.data.wheel_bind_active),
    ),
    DreameA2BinarySensorEntityDescription(
        # Privacy-policy acceptance for the "Capture Photos of AI-Detected
        # Obstacles" feature (CFG.AOP toggle = switch.ai_obstacle_photos).
        # Stored in CFG.REC[7] (`photo_consent`); accepted/declined via
        # the Dreame app's privacy-policy sub-page — read-only on this
        # firmware (REC writes return r=-3, and a privacy policy that
        # flips without an explicit accept-screen would be a UX bug).
        # When this is `off`, toggling switch.ai_obstacle_photos on may
        # silently no-op on the device side. Use the
        # dreame_a2_mower.show_photo_privacy_policy service to view the
        # full policy text before accepting in the Dreame app.
        key="photo_consent",
        translation_key="photo_consent",
        name="AI photo capture consent",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.photo_consent,
    ),
    # ───── Human Presence sub-page diagnostics (REC[2..6]) ─────
    # All read-only on g2408 firmware (REC writes return r=-3 — same
    # surface as photo_consent). Decoded from REC complex CFG payload
    # in _refreshers.py; mirrored on s2p51 push via _property_apply.
    DreameA2BinarySensorEntityDescription(
        key="human_presence_scenario_standby",
        translation_key="human_presence_scenario_standby",
        name="Human presence scenario: standby",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.human_presence_scenario_standby,
    ),
    DreameA2BinarySensorEntityDescription(
        key="human_presence_scenario_mowing",
        translation_key="human_presence_scenario_mowing",
        name="Human presence scenario: mowing",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.human_presence_scenario_mowing,
    ),
    DreameA2BinarySensorEntityDescription(
        key="human_presence_scenario_recharge",
        translation_key="human_presence_scenario_recharge",
        name="Human presence scenario: recharge",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.human_presence_scenario_recharge,
    ),
    DreameA2BinarySensorEntityDescription(
        key="human_presence_scenario_patrol",
        translation_key="human_presence_scenario_patrol",
        name="Human presence scenario: patrol",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.human_presence_scenario_patrol,
    ),
    DreameA2BinarySensorEntityDescription(
        key="human_presence_alert_voice",
        translation_key="human_presence_alert_voice",
        name="Human presence voice + push alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.data.human_presence_alert_voice,
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
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)
