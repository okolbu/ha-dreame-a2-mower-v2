"""Calendar entity exposing archived sessions as events.

Each ArchivedSession becomes a CalendarEvent. Read-only — there is no
add/edit/delete; HA's calendar UI surfaces them in agenda/day/week/month
views via the built-in calendar card.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2SessionCalendar(coordinator)])


class DreameA2SessionCalendar(
    CoordinatorEntity["DreameA2MowerCoordinator"], CalendarEntity
):
    """Read-only calendar of archived mow sessions."""

    _attr_has_entity_name = True
    _attr_name = "Sessions"
    _attr_translation_key = "session_calendar"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: "DreameA2MowerCoordinator") -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "session_calendar")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def event(self) -> CalendarEvent | None:
        """Most-recent session — HA shows this in the entity state line."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return None
        entries = archive.list_sessions()
        if not entries:
            return None
        # list_sessions returns most-recent-first by end_ts; take the head.
        return _event_from_entry(entries[0])

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within [start_date, end_date]."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return []
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()
        events: list[CalendarEvent] = []
        for entry in archive.list_sessions():
            if entry.start_ts < start_ts or entry.start_ts > end_ts:
                continue
            events.append(_event_from_entry(entry))
        return events


def _event_from_entry(entry) -> CalendarEvent:
    """Render an ArchivedSession as a CalendarEvent."""
    start = datetime.fromtimestamp(entry.start_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(entry.end_ts, tz=timezone.utc)
    map_label = f"Map {entry.map_id + 1}" if entry.map_id >= 0 else "Map ?"
    summary = f"Mow {map_label} — {entry.area_mowed_m2:.1f} m²"
    description_parts = [
        f"Duration: {entry.duration_min} min",
        f"Area mowed: {entry.area_mowed_m2:.1f} m²",
    ]
    if entry.session_distance_m:
        description_parts.append(f"Distance: {entry.session_distance_m:.0f} m")
    description_parts.append(f"Map area: {entry.map_area_m2} m²")
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description="\n".join(description_parts),
        uid=f"dreame_a2_session_{entry.md5}_{entry.start_ts}",
    )
