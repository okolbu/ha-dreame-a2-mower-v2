"""Logbook describers for the integration's two EventEntity instances.

By default the HA logbook card renders an EventEntity state change as
"<friendly_name> detected an event" — which is technically correct
but loses the event_type and any payload (text / code) that makes
the event useful. This module overrides that formatting:

  - For event.dreame_a2_mower_lifecycle: "started mowing", "arrived
    at dock", etc.
  - For event.dreame_a2_mower_notification: the notification's `text`
    payload (the cloud's authoritative localised string when available),
    falling back to a per-event_type label.

The translations file (translations/en.json § entity.event) carries the
same labels for places HA reads the entity-state translation (entity
card, state badge). This logbook module guarantees the same labels reach
the logbook card too — EventEntity translations aren't currently picked
up by the logbook component on their own.
"""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN

# event_type → human message for the lifecycle entity.
_LIFECYCLE_MESSAGES: dict[str, str] = {
    "mowing_started": "started mowing",
    "mowing_paused": "paused mowing",
    "mowing_resumed": "resumed mowing",
    "mowing_ended": "finished mowing",
    "dock_arrived": "arrived at the dock",
    "dock_departed": "left the dock",
    "charging_started": "started charging",
    "charging_complete": "finished charging",
    "rain_delay_started": "paused for rain — waiting out the delay",
}

# event_type → human message for the notification entity. Used as a
# fallback when the bus event doesn't carry a 'text' field (which is
# the cloud's authoritative localised string — preferred when present).
_NOTIFICATION_MESSAGES: dict[str, str] = {
    "hanging": "is hanging (lifted off the ground)",
    "emergency_stop": "emergency stop activated",
    "human_detected": "detected a person nearby",
    "blades_worn": "blades severely worn — replace soon",
    "maintenance_reminder": "maintenance reminder",
    "positioning_failed_stuck": "stuck — positioning failed",
    "positioning_failed_transient": "brief positioning glitch",
    "failed_to_start_task": "failed to start task — please retry",
    "battery_temp_low_charging_paused": "stopped charging — battery too cold",
    "task_cancelled": "task cancelled",
    "mowing_complete": "mowing complete",
    "mowing_started": "started mowing",
    "scheduled_mowing_started": "scheduled mow started",
    "low_battery_return": "returning to dock for low battery",
    "rain_protection": "rain protection activated",
    "schedule_cancelled_busy": "schedule cancelled — mower busy",
    "continue_unfinished_task": "continuing unfinished task",
    "positioning_failure": "positioning failed",
    "top_cover_open": "top cover is open",
    "arrived_at_maintenance_point": "arrived at maintenance point",
    "robot_in_hidden_zone": "entered a hidden zone",
    "station_disconnected": "station disconnected",
    "unknown_s2p2": "notification (novel code)",
}


def _format(entity_id: str, event_type: str, attrs: dict[str, Any]) -> str | None:
    """Return the human message for one of our event entities."""
    if entity_id.endswith("_lifecycle"):
        return _LIFECYCLE_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
    if entity_id.endswith("_notification"):
        # The notification entity carries the cloud's authoritative
        # localised `text` in the payload; prefer it so context-rich
        # messages survive in the logbook. Fallback to the per-slug
        # message table below when 'text' is absent (cloud unreachable
        # at fire time, or a future code path that doesn't fetch text).
        text = attrs.get("text")
        if text:
            return str(text)
        return _NOTIFICATION_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
    return None


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[..., Any],
) -> None:
    """Register a logbook describer for our custom bus event.

    EventEntity state changes don't reach async_describe_event
    describers — HA logbook handles them as a PSEUDO_EVENT_STATE_CHANGED
    that bypasses the describer registry and falls through to a
    generic "detected an event" message. We work around that by
    firing a custom HA bus event (`<DOMAIN>_event`) from
    EventEntity.trigger() in addition to the entity-state update;
    custom bus events DO route through describers. This module
    formats those bus events.
    """

    @callback
    def describe(event: Event) -> dict[str, Any] | None:
        entity_id = event.data.get("entity_id", "")
        event_type = event.data.get("event_type", "")
        data = event.data.get("data") or {}
        if not entity_id or not event_type:
            return None
        message = _format(entity_id, event_type, data)
        if message is None:
            return None
        return {
            LOGBOOK_ENTRY_NAME: "Mower",
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    async_describe_event(DOMAIN, f"{DOMAIN}_event", describe)
