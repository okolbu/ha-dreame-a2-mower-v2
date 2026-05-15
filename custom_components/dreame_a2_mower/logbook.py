"""Logbook describers for the integration's two EventEntity instances.

By default the HA logbook card renders an EventEntity state change as
"<friendly_name> detected an event" — which is technically correct
but loses the event_type and any payload (text / code) that makes
the event useful. This module overrides that formatting:

  - For event.dreame_a2_mower_lifecycle: "started mowing", "arrived
    at dock", etc.
  - For event.dreame_a2_mower_alert: the alert's text payload if
    present, falling back to a per-event_type label.

The translations file (translations/en.json § entity.event) carries
the same labels for places HA reads the entity-state translation
(entity card, state badge). This logbook module guarantees the same
labels reach the logbook card too — it's not currently the case
that EventEntity translations are picked up by the logbook component.
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
}

# event_type → human message for the alert entity. Used as a fallback
# when the alert payload doesn't carry a 'text' field.
_ALERT_MESSAGES: dict[str, str] = {
    "hanging": "is hanging (lifted off the ground)",
    "human_detected": "detected a person nearby",
    "maintenance_reminder": "maintenance reminder",
    "positioning_failed_stuck": "stuck — positioning failed",
    "positioning_failed_transient": "brief positioning glitch",
    "battery_temp_low_charging_paused": "stopped charging — battery too cold",
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
}


def _format(entity_id: str, event_type: str, attrs: dict[str, Any]) -> str | None:
    """Return the human message for one of our event entities."""
    if entity_id.endswith("_lifecycle"):
        return _LIFECYCLE_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
    if entity_id.endswith("_alert"):
        # The alert entity carries an optional 'text' payload (the raw
        # notification string from the s2p2 dispatcher); prefer that if
        # present so context-rich notifications survive.
        text = attrs.get("text")
        if text:
            return str(text)
        return _ALERT_MESSAGES.get(
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
