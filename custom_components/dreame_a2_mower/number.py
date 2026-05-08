"""Number platform — settable numeric settings for the Dreame A2 Mower.

F4.6.1: VOL (voice volume), auto_recharge_battery_pct, resume_battery_pct
        are settable via coordinator.write_setting.

        human_presence_alert_sensitivity is read-only in F4 because the
        REC wire list has 9 elements of which only 2 are decoded into
        MowerState; the remaining 7 (standby, mowing, recharge, patrol,
        alert, photo_consent, push_min) are not stored, so a safe full-list
        reconstruction is not possible.  It will appear in the UI as a
        read-only number (entity_category=DIAGNOSTIC).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2NumberEntityDescription(NumberEntityDescription):
    """Number descriptor with typed value_fn and optional write helpers.

    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, user_entered_value).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update that coordinator.write_setting applies.
    """

    value_fn: Callable[[MowerState], float | int | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, float], Any] | None = None
    field_updates_fn: Callable[[MowerState, float], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Wire-value builders
# ---------------------------------------------------------------------------

def _build_vol(state: MowerState, value: float) -> Any:
    """VOL wire value is just an integer 0..100."""
    return int(value)


def _vol_field_updates(state: MowerState, value: float) -> dict[str, Any]:
    return {"volume_pct": int(value)}


def _build_bat_auto_recharge(state: MowerState, value: float) -> list:
    """Build the full BAT list with auto_recharge_battery_pct overridden.

    CFG.BAT = list(6) [recharge_pct, resume_pct, unknown_flag(=1),
                        custom_charging, start_min, end_min].
    Confirmed on g2408 (docs/research §6.2 + coordinator._refresh_cfg).

    All 6 fields are present in MowerState (F4.3.1), so the full list
    can be reconstructed safely.  The unknown_flag at index 2 is set to
    1 (the only observed value).
    """
    return [
        int(value),                                     # [0] recharge_pct  (new)
        int(state.resume_battery_pct or 95),            # [1] resume_pct
        1,                                              # [2] unknown_flag (always 1)
        int(state.custom_charging_enabled or False),    # [3] custom_charging
        int(state.charging_start_min or 0),             # [4] start_min
        int(state.charging_end_min or 0),               # [5] end_min
    ]


def _bat_auto_recharge_field_updates(
    state: MowerState, value: float
) -> dict[str, Any]:
    return {"auto_recharge_battery_pct": int(value)}


def _build_bat_resume(state: MowerState, value: float) -> list:
    """Build the full BAT list with resume_battery_pct overridden.

    Same shape as _build_bat_auto_recharge; only index 1 changes.
    """
    return [
        int(state.auto_recharge_battery_pct or 15),    # [0] recharge_pct
        int(value),                                     # [1] resume_pct   (new)
        1,                                              # [2] unknown_flag (always 1)
        int(state.custom_charging_enabled or False),    # [3] custom_charging
        int(state.charging_start_min or 0),             # [4] start_min
        int(state.charging_end_min or 0),               # [5] end_min
    ]


def _bat_resume_field_updates(state: MowerState, value: float) -> dict[str, Any]:
    return {"resume_battery_pct": int(value)}


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------

NUMBERS: tuple[DreameA2NumberEntityDescription, ...] = (
    # ------------------------------------------------------------------
    # Settable: VOL (CFG key — direct single-value write)
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="volume",
        name="Voice volume",
        native_min_value=0,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.volume_pct,
        cfg_key="VOL",
        build_value_fn=_build_vol,
        field_updates_fn=_vol_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[0] — auto-recharge threshold
    # Wire shape confirmed: list(6), all 6 fields in MowerState.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="auto_recharge_battery_pct",
        name="Auto-recharge battery threshold",
        native_min_value=10,
        native_max_value=25,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.auto_recharge_battery_pct,
        cfg_key="BAT",
        build_value_fn=_build_bat_auto_recharge,
        field_updates_fn=_bat_auto_recharge_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[1] — resume-after-charge threshold
    # Wire shape confirmed: list(6), all 6 fields in MowerState.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="resume_battery_pct",
        name="Resume-after-charge battery threshold",
        native_min_value=80,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.resume_battery_pct,
        cfg_key="BAT",
        build_value_fn=_build_bat_resume,
        field_updates_fn=_bat_resume_field_updates,
    ),

    # ------------------------------------------------------------------
    # Read-only: REC[1] — human presence alert sensitivity
    #
    # The REC wire list has 9 elements.  Only [0] (enabled) and [1]
    # (sensitivity) are decoded into MowerState.  Elements [2..8]
    # (standby, mowing, recharge, patrol, alert, photo_consent, push_min)
    # are NOT stored — so a safe full-list reconstruction is impossible.
    #
    # Shipped as read-only (DIAGNOSTIC) in F4.  Will become settable once
    # the remaining REC fields are added to MowerState in a future task.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="human_presence_alert_sensitivity",
        name="Human presence alert sensitivity",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.human_presence_alert_sensitivity,
        # cfg_key intentionally omitted — read-only in F4
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [DreameA2Number(coordinator, desc) for desc in NUMBERS]
    entities.extend([
        DreameA2MowingHeightNumber(coordinator),
        DreameA2CutterPositionNumber(coordinator),
        DreameA2CutterPositionHeightNumber(coordinator),
        DreameA2EdgeMowingNumNumber(coordinator),
        DreameA2ObstacleAvoidanceHeightNumber(coordinator),
        DreameA2ObstacleAvoidanceDistanceNumber(coordinator),
        DreameA2ObstacleAvoidanceSensitivityNumber(coordinator),
        DreameA2ObstacleAvoidanceAiNumber(coordinator),
    ])
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2Number(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """A coordinator-backed number entity.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_set_native_value is called.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2NumberEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2NumberEntityDescription,
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
        )

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the mower via the coordinator."""
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "number.%s: no write path configured (read-only in F4); "
                "ignoring set_native_value(%r)",
                desc.key,
                value,
            )
            return

        # Build the full wire value expected by the firmware.
        if desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, value)
        else:
            wire_value = value

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, value)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "number.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )


# ---------------------------------------------------------------------------
# SETTINGS-driven entities (active-map follower pattern)
# ---------------------------------------------------------------------------

class DreameA2MowingHeightNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Mowing height (cm) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_mowing_height"
    _attr_name = "Mowing height"
    _attr_native_min_value = 2
    _attr_native_max_value = 7
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_mowing_height"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_mowing_height
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="mowingHeight",
            new_value=int(value),
            state_field="settings_mowing_height",
        )


class DreameA2CutterPositionNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Cutter position — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_cutter_position"
    _attr_name = "Cutter position"
    _attr_native_min_value = 0
    _attr_native_max_value = 3
    _attr_native_step = 1
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_cutter_position"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_cutter_position
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="cutterPosition", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2CutterPositionHeightNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Cutter height (cm) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_cutter_position_height"
    _attr_name = "Cutter height"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_cutter_position_height"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_cutter_position_height
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="cutterPositionHeight", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2EdgeMowingNumNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Edge passes — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_edge_mowing_num"
    _attr_name = "Edge passes"
    _attr_native_min_value = 1
    _attr_native_max_value = 3
    _attr_native_step = 1
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_edge_mowing_num"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_edge_mowing_num
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="edgeMowingNum", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2ObstacleAvoidanceHeightNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Obstacle avoidance height (cm) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_obstacle_avoidance_height"
    _attr_name = "Obstacle avoidance height"
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_obstacle_avoidance_height"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_obstacle_avoidance_height
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="obstacleAvoidanceHeight", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2ObstacleAvoidanceDistanceNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Obstacle avoidance distance (cm) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_obstacle_avoidance_distance"
    _attr_name = "Obstacle avoidance distance"
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_obstacle_avoidance_distance"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_obstacle_avoidance_distance
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="obstacleAvoidanceDistance", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2ObstacleAvoidanceSensitivityNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Obstacle avoidance sensitivity — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_obstacle_avoidance_sensitivity"
    _attr_name = "Obstacle avoidance sensitivity"
    _attr_native_min_value = 1
    _attr_native_max_value = 3
    _attr_native_step = 1
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_obstacle_avoidance_sensitivity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_obstacle_avoidance_sensitivity
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="obstacleAvoidanceSensitivity", value=int(value),
        )
        self.async_write_ha_state()


class DreameA2ObstacleAvoidanceAiNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Obstacle avoidance AI (bitfield) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_obstacle_avoidance_ai"
    _attr_name = "Obstacle avoidance AI"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_obstacle_avoidance_ai"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_obstacle_avoidance_ai
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="obstacleAvoidanceAi", value=int(value),
        )
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Module-level helper — reused by numbers, switches, selects
# ---------------------------------------------------------------------------

async def _settings_optimistic_write(
    entity: "CoordinatorEntity",
    *,
    field: str,
    new_value: Any,
    state_field: str,
) -> None:
    """Optimistic-update + revert-on-failure for SETTINGS-driven entities.

    1. Save old value
    2. Update coordinator.data immediately + push state (instant UI)
    3. Call coordinator.write_settings(map_id, field, value)
    4. On success: cloud refresh confirms (no visible change)
    5. On failure: revert state + fire persistent_notification

    Reused by all numbers/switches/selects writing to SETTINGS — keeps
    every entity's setter to a single line.
    """
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    if coord._active_map_id is None:
        LOGGER.warning(
            "%s: no active map — write of %s deferred", entity.entity_id, field
        )
        return
    map_id = coord._active_map_id
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_settings(map_id=map_id, field=field, value=new_value)
    if ok:
        return
    # Revert + notify
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The cloud rejected the write of {field}={new_value!r}. "
                f"Reverted to previous value ({old_value!r})."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
