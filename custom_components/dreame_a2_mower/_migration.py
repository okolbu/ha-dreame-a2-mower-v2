"""Entity-registry migration v1 -> v2: SN-based unique_ids.

Rewrites unique_ids from `{entry_id}_*` (and `{entry_id}_map_{N}_*`) to
`{stable_id}_*` (and `{stable_id}_map_{N}_*`). Stable id is the hardware
SN when available, falling back to mac then entry_id.

The rewrite map is built per task as entities are migrated to their new
shapes. Unmapped legacy entities are surfaced via persistent_notification
for manual cleanup via WS `config/entity_registry/remove`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Run unique_id rewrites and bump entry version."""
    if entry.version >= 2:
        return True

    _LOGGER.info(
        "%s: migrating config entry %s from v%d to v2 (SN-based unique_ids)",
        DOMAIN, entry.entry_id, entry.version,
    )

    rewrites = _collect_rewrites(hass, entry)
    rewritten, orphans = await _apply_rewrites(hass, entry, rewrites)

    if orphans:
        await _notify_orphans(hass, entry, orphans)

    hass.config_entries.async_update_entry(entry, version=2)
    _LOGGER.info(
        "%s: migration complete: %d entities rewritten, %d orphans",
        DOMAIN, len(rewritten), len(orphans),
    )
    return True


def _collect_rewrites(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Build the {old_unique_id: new_unique_id} map.

    Populated incrementally as entities migrate in subsequent tasks.
    Today returns empty (no entity has migrated yet).
    """
    return {}


async def _apply_rewrites(
    hass: HomeAssistant,
    entry: ConfigEntry,
    rewrites: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Apply rewrites to the entity registry.

    Returns (rewritten_entity_ids, orphan_entity_ids).
    """
    registry = er.async_get(hass)
    rewritten: list[str] = []
    orphans: list[str] = []
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue
        if entity.unique_id in rewrites:
            new = rewrites[entity.unique_id]
            registry.async_update_entity(entity.entity_id, new_unique_id=new)
            rewritten.append(entity.entity_id)
            _LOGGER.debug(
                "%s migration: %s unique_id %r -> %r",
                DOMAIN, entity.entity_id, entity.unique_id, new,
            )
        elif entity.unique_id.startswith(f"{entry.entry_id}_"):
            orphans.append(entity.entity_id)
    return rewritten, orphans


async def _notify_orphans(
    hass: HomeAssistant,
    entry: ConfigEntry,
    orphans: list[str],
) -> None:
    """Surface unmapped legacy entities via persistent_notification."""
    title = f"{DOMAIN}: migration left orphan entities"
    message = (
        "The Dreame A2 Mower integration migrated to SN-based entity ids. "
        "The following entities have legacy ids with no mapping and should "
        "be removed manually (Settings → Devices → entity → '...' menu):\n\n"
        + "\n".join(f"- `{eid}`" for eid in orphans)
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": title,
            "message": message,
            "notification_id": f"{DOMAIN}_migration_v2_orphans",
        },
        blocking=False,
    )
