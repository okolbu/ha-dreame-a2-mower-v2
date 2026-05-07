"""Event entity platform for the Dreame A2 Mower integration.

Exposes lifecycle moments (mowing started/paused/resumed/ended, dock
arrived/departed) and reserves an alert entity for the follow-up
alert-tier PR.

Per spec docs/superpowers/specs/2026-05-07-event-surface-design.md:
the coordinator's _fire_lifecycle dispatcher calls each entity's
_trigger_event(event_type, event_data) on the relevant transition.
Logbook integration is automatic — HA renders firings as entries.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ALERT_EVENT_TYPES,
    DOMAIN,
    LIFECYCLE_EVENT_TYPES,
    LOGGER,
)
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entities and register them with the coordinator."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    lifecycle = DreameA2LifecycleEventEntity(coordinator)
    alert = DreameA2AlertEventEntity(coordinator)
    coordinator.register_event_entities(lifecycle=lifecycle, alert=alert)
    async_add_entities([lifecycle, alert])


class _DreameA2EventEntityBase(EventEntity):
    """Common boilerplate for the integration's event entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        unique_suffix: str,
        translation_key: str,
        event_types: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_translation_key = translation_key
        self._attr_event_types = list(event_types)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @callback
    def trigger(self, event_type: str, event_data: dict[str, Any] | None) -> None:
        """Public API the coordinator calls to fire an event.

        Drops keys whose values are None so automation templates don't
        have to default-guard nullable payload fields.
        """
        if event_type not in self._attr_event_types:
            LOGGER.debug(
                "[event] dropping unknown event_type=%r on %s; declared=%r",
                event_type, self.entity_id, self._attr_event_types,
            )
            return
        cleaned = (
            {k: v for k, v in event_data.items() if v is not None}
            if event_data
            else {}
        )
        self._trigger_event(event_type, cleaned)
        self.async_write_ha_state()


class DreameA2LifecycleEventEntity(_DreameA2EventEntityBase):
    """Lifecycle moments — mowing started/paused/resumed/ended + dock."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_suffix="lifecycle",
            translation_key="lifecycle",
            event_types=LIFECYCLE_EVENT_TYPES,
        )
        self._attr_name = "Lifecycle"


class DreameA2AlertEventEntity(_DreameA2EventEntityBase):
    """Alert moments — populated in the follow-up alert-tier PR.

    Declared with empty event_types today so the entity exists from
    this PR onwards and users can pre-register automations against the
    stable entity_id.
    """

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_suffix="alert",
            translation_key="alert",
            event_types=ALERT_EVENT_TYPES,
        )
        self._attr_name = "Alert"
