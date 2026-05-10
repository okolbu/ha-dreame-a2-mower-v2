"""Shared optimistic-write helper for SETTINGS-driven entities.

Replaces the three near-identical helpers that lived in switch.py,
select.py, and number.py — keeping the persistent-notification format
and revert flow in one place so a UX change touches one file.

Pattern (used by every settings-mirroring switch / select / number):
    1. Save old MowerState value.
    2. Update coordinator.data optimistically + push to HA (instant UI).
    3. Call coordinator.write_settings(map_id, field, cloud_value).
    4. On success: cloud refresh confirms; nothing else to do.
    5. On failure: revert MowerState + fire persistent_notification.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


async def settings_optimistic_write(
    entity: "CoordinatorEntity",
    *,
    field: str,
    new_value: Any,
    state_field: str,
    map_id: int | None = None,
) -> None:
    """Optimistic write of one SETTINGS field with revert-on-failure.

    `new_value` is the entity-side value (bool / int / float). Bools are
    coerced to int for the wire (cloud SETTINGS stores all toggle fields
    as int 0/1, not booleans — see /tmp/probe_current_state.py output).
    The local MowerState keeps the entity-native type for clean UI reads.

    `map_id` selects which map to write to. When omitted (None), falls back to
    ``coord._active_map_id`` for backwards-compatible callers. Per-map entities
    should always supply an explicit ``map_id``.
    """
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    if map_id is None:
        map_id = coord._active_map_id
    if map_id is None:
        _LOGGER.warning(
            "%s: no active map — write of %s deferred",
            entity.entity_id, field,
        )
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    cloud_value = int(new_value) if isinstance(new_value, bool) else new_value
    ok = await coord.write_settings(
        map_id=map_id, field=field, value=cloud_value,
    )
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
