"""Shared base classes and description dataclass for the switch platform.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a switch platform.  It is imported by switch_global.py,
switch_map.py, and switch.py.

Acyclic import order:
    _switch_base  ←  switch_global / switch_map  ←  switch.py
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, mower_device_info, mower_unique_id
from .const import LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2SwitchEntityDescription(SwitchEntityDescription):
    """Switch descriptor with typed value_fn and optional write helpers.

    ``value_fn``       — reads the current bool from MowerState.
    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
                         If None, the switch is read-only in F4.
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, new_enabled_bool).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update applied by coordinator.write_setting.
    """

    value_fn: Callable[[MowerState], bool | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, bool], Any] | None = None
    field_updates_fn: Callable[[MowerState, bool], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2Switch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """A coordinator-backed switch entity.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_turn_on / async_turn_off is called.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2SwitchEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Mark unavailable until the first state read populates ``is_on``.

        HA renders a SwitchEntity with ``is_on=None`` using its
        assumed-state widget (two separate Turn-On / Turn-Off buttons),
        which loses the visual state-on-page. Returning ``available=False``
        instead surfaces the entity as a greyed-out single toggle until
        the periodic CFG fetch populates the backing field — much closer
        to the user expectation of "a switch I can read and write".
        Once the value is non-None, super().available reflects the
        coordinator's normal availability logic.
        """
        if self.entity_description.value_fn(self.coordinator.data) is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_value(False)

    async def _async_set_value(self, enabled: bool) -> None:
        """Write the new state to the mower via the coordinator."""
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "switch.%s: no write path configured (read-only in F4); "
                "ignoring turn_%s",
                desc.key,
                "on" if enabled else "off",
            )
            return

        # Build the full wire value expected by the firmware.
        if desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, enabled)
        else:
            wire_value = int(enabled)

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, enabled)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "switch.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )


# ---------------------------------------------------------------------------
# AI obstacle recognition bit-switches (Task 14) — shared base
# ---------------------------------------------------------------------------

_AI_HUMANS_BIT = 1 << 0
_AI_ANIMALS_BIT = 1 << 1
_AI_OBJECTS_BIT = 1 << 2


class _AiRecognitionBitSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Common base for the 3 AI obstacle recognition bit switches.

    Each subclass sets _BIT (one of _AI_HUMANS_BIT / _ANIMALS_BIT /
    _OBJECTS_BIT) and the entity-name / unique-id attrs.
    Per-map: each instance is bound to a specific map_id.
    """

    _BIT: int = 0
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceAi")
        if raw is None:
            return None
        return bool(raw & self._BIT)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def _toggle(self, on: bool) -> None:
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        if cs is None:
            LOGGER.warning("%s: no cloud_state — toggle deferred", self.entity_id)
            return
        old = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceAi") or 0
        new = (old | self._BIT) if on else (old & ~self._BIT)
        if new == old:
            return
        # Optimistic update on MowerState mirror (used by other entities on same map).
        coord.data = dataclasses.replace(
            coord.data, settings_obstacle_avoidance_ai=new
        )
        self.async_write_ha_state()
        ok = await coord.write_settings(
            map_id=self._map_id,
            field="obstacleAvoidanceAi",
            value=new,
        )
        if ok:
            return
        coord.data = dataclasses.replace(
            coord.data, settings_obstacle_avoidance_ai=old
        )
        self.async_write_ha_state()
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    f"The cloud rejected the AI recognition toggle. "
                    f"Previous bitfield value: 0b{old:03b}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle(False)
