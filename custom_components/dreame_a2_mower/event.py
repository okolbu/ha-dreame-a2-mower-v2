"""Event entity platform for the Dreame A2 Mower integration.

Exposes lifecycle moments (mowing started/paused/resumed/ended, dock
arrived/departed) plus cloud-sourced notifications (s2p2 transitions
relayed verbatim from /dreame-messaging/user/device-messages/v2 with
multilingual texts).

Per spec docs/superpowers/specs/2026-05-07-event-surface-design.md:
the coordinator's _fire_lifecycle / _fire_notification dispatchers call
each entity's _trigger_event(event_type, event_data) on the relevant
transition. Logbook integration is automatic — HA renders firings as
entries.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ._devices import mower_device_info, mower_unique_id
from .const import (
    NOTIFICATION_EVENT_TYPES,
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
    notification = DreameA2NotificationEventEntity(coordinator)
    coordinator.register_event_entities(lifecycle=lifecycle, notification=notification)
    async_add_entities([lifecycle, notification])


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
        self._attr_unique_id = mower_unique_id(coordinator, unique_suffix)
        self._attr_translation_key = translation_key
        self._attr_event_types = list(event_types)
        self._attr_device_info = mower_device_info(coordinator)

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
        # Also fire on the HA bus so logbook.py's describer can render
        # nice messages. EventEntity state changes don't reach the
        # describer (HA logbook handles them as PSEUDO_EVENT_STATE_CHANGED
        # without consulting registered describers — they fall through
        # to the generic "detected an event" message). A custom bus
        # event IS routed through describers, so we fire one with the
        # same payload.
        # Use getattr so unit tests that construct the entity without
        # an HA platform attached don't trip on a missing hass attr.
        hass = getattr(self, "hass", None)
        if hass is not None:
            hass.bus.async_fire(
                f"{DOMAIN}_event",
                {
                    "entity_id": self.entity_id,
                    "event_type": event_type,
                    "data": cleaned,
                },
            )


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


class DreameA2NotificationEventEntity(_DreameA2EventEntityBase):
    """Cloud-sourced s2p2 notifications.

    Fires once per cloud push (text from the cloud's localizationContents,
    no hardcoded strings in this integration). The coordinator's
    `_NotificationsMixin` resolves the text on every MQTT s2p2 transition
    and calls `trigger(event_type, payload)` here. Payload carries
    `text`, `code`, `siid`, `piid`, `send_time`, `message_id`, `source`.

    Entity ID: `event.dreame_a2_mower_notification` (renamed from
    `event.dreame_a2_mower_alert` 2026-05-26 — no backcompat in
    pre-production).
    """

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_suffix="notification",
            translation_key="notification",
            event_types=NOTIFICATION_EVENT_TYPES,
        )
        self._attr_name = "Notification"
