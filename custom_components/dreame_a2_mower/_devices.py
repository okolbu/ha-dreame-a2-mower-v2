"""Identifier and DeviceInfo factories for the mower + map sub-devices.

Centralises the SN-based keying introduced in Phase 2. All entities
should construct their unique_id and device_info via these helpers so
the migration in `_migration.py` has a single source of truth.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)

from .const import DEFAULT_MODEL, DEFAULT_NAME, DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from .coordinator import DreameA2MowerCoordinator


def _stable_id(coord: DreameA2MowerCoordinator) -> str:
    """Return the most stable identifier available for this mower.

    Prefers the hardware SN. Falls back to mac (prefixed `mac:`) and
    finally to the config entry id (`entry:`). The fallback prefixes
    keep the namespace explicit so the migration can detect them.
    """
    sn = getattr(coord, "sn", None)
    if sn:
        return sn
    client = getattr(coord, "_cloud", None)
    mac = getattr(client, "mac_address", None) if client is not None else None
    if mac:
        return f"mac:{mac}"
    return f"entry:{coord.entry.entry_id}"


def mower_identifiers(coord: DreameA2MowerCoordinator) -> set[tuple[str, str]]:
    return {(DOMAIN, _stable_id(coord))}


def map_identifiers(
    coord: DreameA2MowerCoordinator, map_id: int
) -> set[tuple[str, str]]:
    return {(DOMAIN, f"{_stable_id(coord)}_map_{map_id}")}


def mower_unique_id(coord: DreameA2MowerCoordinator, key: str) -> str:
    return f"{_stable_id(coord)}_{key}"


def map_unique_id(
    coord: DreameA2MowerCoordinator, map_id: int, key: str
) -> str:
    return f"{_stable_id(coord)}_map_{map_id}_{key}"


def mower_device_info(coord: DreameA2MowerCoordinator) -> DeviceInfo:
    client = getattr(coord, "_cloud", None)
    model = getattr(client, "model", None) if client is not None else None
    mac = getattr(client, "mac_address", None) if client is not None else None
    sn = getattr(coord, "sn", None)
    info: dict[str, Any] = {
        "identifiers": mower_identifiers(coord),
        "manufacturer": MANUFACTURER,
        "model": model or DEFAULT_MODEL,
        "name": DEFAULT_NAME,
    }
    if sn:
        info["serial_number"] = sn
    if mac:
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return DeviceInfo(**info)


def map_device_info(
    coord: DreameA2MowerCoordinator,
    map_id: int,
    name: str | None,
) -> DeviceInfo:
    display_name = name or f"Map {map_id + 1}"
    return DeviceInfo(
        identifiers=map_identifiers(coord, map_id),
        via_device=(DOMAIN, _stable_id(coord)),
        manufacturer=MANUFACTURER,
        name=display_name,
    )
