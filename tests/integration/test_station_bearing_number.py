"""Tests for the station_bearing_deg number entity (config-option mirror)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.const import CONF_STATION_BEARING_DEG
from custom_components.dreame_a2_mower.coordinator import (
    DreameA2MowerCoordinator,
    _project_north_east,
)
from custom_components.dreame_a2_mower.number import DreameA2StationBearingNumber


def _make_coord(
    *,
    options: dict | None = None,
    snapshot_xy: tuple[float | None, float | None] | None = None,
):
    """Build a minimal coord stub with an entry.options dict.

    The number entity only touches:
      - coord.entry.entry_id / coord.entry.options (via station_bearing_deg)
      - coord.station_bearing_deg property
      - coord.data.hardware_serial (via mower_unique_id)
      - coord.state_machine.snapshot() / .handle_position() (for N/E re-projection)
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.entry.options = dict(options or {})
    coord.data = MagicMock()
    coord.data.hardware_serial = "TEST-SERIAL-1234"
    # State machine stub: snapshot returns a MagicMock whose
    # position_x_m / position_y_m are the requested values (or None).
    snap = MagicMock()
    if snapshot_xy is None:
        snap.position_x_m = None
        snap.position_y_m = None
    else:
        snap.position_x_m, snap.position_y_m = snapshot_xy
    coord.state_machine = MagicMock()
    coord.state_machine.snapshot.return_value = snap
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


@pytest.mark.asyncio
async def test_set_native_value_reprojects_north_east_from_current_xy():
    """Changing the bearing must immediately re-project N/E from the
    current snapshot x/y; otherwise the position_north_m / position_east_m
    sensors stay stale until the next s1p4 frame (which can be hours away
    when the mower is idle at the dock)."""
    # Snapshot has a known position. With bearing=90 deg:
    #   north = x*cos(90) - y*sin(90) = -y
    #   east  = x*sin(90) + y*cos(90) =  x
    # so for (x, y) = (1.0, 2.0): (north, east) = (-2.0, 1.0).
    coord = _make_coord(options={}, snapshot_xy=(1.0, 2.0))
    ent = DreameA2StationBearingNumber(coord)
    ent.hass = MagicMock()
    ent.hass.config_entries.async_update_entry.side_effect = (
        lambda entry, *, options: setattr(entry, "options", options)
    )
    ent.async_write_ha_state = MagicMock()

    await ent.async_set_native_value(90.0)

    # state_machine.handle_position called once with x/y unchanged and
    # north/east projected via _project_north_east.
    coord.state_machine.handle_position.assert_called_once()
    call_kwargs = coord.state_machine.handle_position.call_args.kwargs
    expected_north, expected_east = _project_north_east(1.0, 2.0, 90.0)
    assert call_kwargs["x_m"] == 1.0
    assert call_kwargs["y_m"] == 2.0
    assert call_kwargs["north_m"] == pytest.approx(expected_north)
    assert call_kwargs["east_m"] == pytest.approx(expected_east)
    # north/east must actually differ from x/y when bearing != 0
    assert call_kwargs["north_m"] != 1.0 or call_kwargs["east_m"] != 2.0
    # now_unix is required by handle_position
    assert isinstance(call_kwargs["now_unix"], int)


@pytest.mark.asyncio
async def test_set_native_value_skips_reprojection_when_position_unknown():
    """When the snapshot has no x/y yet (first install, never mowed),
    we can't project — handle_position must not be called."""
    coord = _make_coord(options={}, snapshot_xy=(None, None))
    ent = DreameA2StationBearingNumber(coord)
    ent.hass = MagicMock()
    ent.hass.config_entries.async_update_entry.side_effect = (
        lambda entry, *, options: setattr(entry, "options", options)
    )
    ent.async_write_ha_state = MagicMock()

    await ent.async_set_native_value(45.0)

    coord.state_machine.handle_position.assert_not_called()
    ent.async_write_ha_state.assert_called_once()
