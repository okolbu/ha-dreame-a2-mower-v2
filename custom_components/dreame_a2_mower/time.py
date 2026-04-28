"""Time platform — schedule slot display-only entities for the Dreame A2 Mower.

F4.6.4: Six read-only TimeEntity instances backed by MowerState's
        integer-minute fields:

  - time.dnd_start_time / dnd_end_time
  - time.low_speed_at_night_start_time / _end_time
  - time.charging_start_time / _end_time

All are DIAGNOSTIC (display-only). Schedule editing on g2408 is BT-only
per protocol-doc §1.1; these entities show the user's current schedule
without claiming write capability. Any service-call attempt to edit
logs a "write deferred" warning and no-ops.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
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
class DreameA2TimeEntityDescription(TimeEntityDescription):
    """Time entity descriptor with a typed minutes_fn.

    ``minutes_fn`` — extracts the int-minutes field from MowerState.
    """

    minutes_fn: Callable[[MowerState], int | None]


# ---------------------------------------------------------------------------
# Helper: convert minutes-since-midnight to datetime.time
# ---------------------------------------------------------------------------


def _to_time(minutes: int | None) -> time | None:
    """Convert integer minutes-since-midnight to datetime.time object.

    Args:
        minutes: 0..1439 (0 = 00:00, 1439 = 23:59). None is returned as None.

    Returns:
        A datetime.time object, or None if minutes is None or out of range.
    """
    if minutes is None or not (0 <= minutes <= 1439):
        return None
    return time(hour=minutes // 60, minute=minutes % 60)


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------


TIMES: tuple[DreameA2TimeEntityDescription, ...] = (
    DreameA2TimeEntityDescription(
        key="dnd_start_time",
        name="DND start time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.dnd_start_min,
    ),
    DreameA2TimeEntityDescription(
        key="dnd_end_time",
        name="DND end time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.dnd_end_min,
    ),
    DreameA2TimeEntityDescription(
        key="low_speed_at_night_start_time",
        name="Low speed at night start time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.low_speed_at_night_start_min,
    ),
    DreameA2TimeEntityDescription(
        key="low_speed_at_night_end_time",
        name="Low speed at night end time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.low_speed_at_night_end_min,
    ),
    DreameA2TimeEntityDescription(
        key="charging_start_time",
        name="Charging start time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.charging_start_min,
    ),
    DreameA2TimeEntityDescription(
        key="charging_end_time",
        name="Charging end time",
        entity_category=EntityCategory.DIAGNOSTIC,
        minutes_fn=lambda s: s.charging_end_min,
    ),
)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------


class DreameA2Time(CoordinatorEntity[DreameA2MowerCoordinator], TimeEntity):
    """Read-only time entity backed by MowerState int-minutes field.

    Displays schedule slot start/end times. async_set_value is a no-op
    with a warning — schedule editing is BT-only on g2408 in F4.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2TimeEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2TimeEntityDescription,
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
    def native_value(self) -> time | None:
        """Return the current time value (HH:MM) or None."""
        minutes = self.entity_description.minutes_fn(self.coordinator.data)
        return _to_time(minutes)

    async def async_set_value(self, value: time) -> None:
        """Read-only in F4 — log warning and no-op.

        Schedule editing on g2408 is BT-only per protocol-doc §1.1.
        F5+ may add write support after validation on a live mower.
        """
        LOGGER.warning(
            "time.%s: write deferred (schedule editing on g2408 is BT-only or not yet validated)",
            self.entity_description.key,
        )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2Time(coordinator, desc) for desc in TIMES])
