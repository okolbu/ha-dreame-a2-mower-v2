"""Tests for the station_bearing_deg number entity (config-option mirror)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.const import CONF_STATION_BEARING_DEG
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.number import DreameA2StationBearingNumber


def _make_coord(*, options: dict | None = None):
    """Build a minimal coord stub with an entry.options dict.

    The number entity only touches:
      - coord.entry.entry_id / coord.entry.options (via station_bearing_deg)
      - coord.station_bearing_deg property
      - coord.data.hardware_serial (via mower_unique_id)
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.entry.options = dict(options or {})
    coord.data = MagicMock()
    coord.data.hardware_serial = "TEST-SERIAL-1234"
    return coord


def test_native_value_defaults_to_zero_when_option_unset():
    coord = _make_coord(options={})
    ent = DreameA2StationBearingNumber(coord)
    assert ent.native_value == 0.0


def test_native_value_reads_option():
    coord = _make_coord(options={CONF_STATION_BEARING_DEG: 137})
    ent = DreameA2StationBearingNumber(coord)
    assert ent.native_value == 137.0


def test_class_attributes_match_spec():
    """Sanity-check the class attributes per requirements."""
    cls = DreameA2StationBearingNumber
    assert cls._attr_translation_key == "station_bearing_deg"
    assert cls._attr_native_min_value == 0
    assert cls._attr_native_max_value == 359
    assert cls._attr_native_step == 1
    assert cls._attr_native_unit_of_measurement == "°"
    assert cls._attr_has_entity_name is True


@pytest.mark.asyncio
async def test_set_native_value_updates_entry_options():
    coord = _make_coord(options={CONF_STATION_BEARING_DEG: 0})
    ent = DreameA2StationBearingNumber(coord)

    # Stub hass + the update_entry call so the entity write path runs.
    captured: dict = {}

    def _update_entry(entry, *, options):
        captured["entry"] = entry
        captured["options"] = options
        # Mirror the real HA behavior: options dict is replaced atomically.
        entry.options = options

    ent.hass = MagicMock()
    ent.hass.config_entries.async_update_entry.side_effect = _update_entry
    ent.async_write_ha_state = MagicMock()

    await ent.async_set_native_value(213.0)

    assert captured["entry"] is coord.entry
    assert captured["options"][CONF_STATION_BEARING_DEG] == 213
    # After the write, the native_value reflects the new option.
    assert ent.native_value == 213.0
    # HA state push was scheduled exactly once.
    ent.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_set_native_value_coerces_float_to_int():
    coord = _make_coord(options={})
    ent = DreameA2StationBearingNumber(coord)
    ent.hass = MagicMock()
    ent.async_write_ha_state = MagicMock()

    captured = {}

    def _update_entry(entry, *, options):
        captured["options"] = options
        entry.options = options

    ent.hass.config_entries.async_update_entry.side_effect = _update_entry

    await ent.async_set_native_value(45.7)

    assert captured["options"][CONF_STATION_BEARING_DEG] == 45  # int() truncates
