"""WiFi archive select must populate _wifi_render_entry on initial setup.

Without this, the camera shows blank until the user manually changes
the dropdown. The dropdown's apparent default value (first entry)
isn't backed by a coordinator render entry until selection fires.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace


def _coord_with_archive_entries(*object_names):
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_render_entry = None
    coord._wifi_archive_index = [
        SimpleNamespace(object_name=name, unix_ts=1_700_000_000 + i, map_id=None)
        for i, name in enumerate(object_names)
    ]
    coord.set_wifi_render_entry = MagicMock(
        side_effect=lambda m, o: setattr(coord, "_wifi_render_entry", (m, o))
    )
    return coord


def _make_sel(coord):
    from custom_components.dreame_a2_mower.select import (
        DreameA2WifiArchiveSelect,
    )
    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_current_option = sel._placeholder
    sel._attr_options = [sel._placeholder]
    sel._label_to_entry = {}
    sel.async_write_ha_state = MagicMock()
    return sel


def test_initial_setup_sets_render_entry_for_top_option():
    coord = _coord_with_archive_entries("obj_a", "obj_b")
    sel = _make_sel(coord)

    # Exercise the helper directly — the full async_added_to_hass calls
    # super() which isn't set up in the bare-__new__ fixture, but the
    # behaviour-of-interest is encapsulated in _seed_initial_render().
    sel._rebuild_options()
    sel._seed_initial_render()

    coord.set_wifi_render_entry.assert_called()
    args = coord.set_wifi_render_entry.call_args.args
    assert args[1] in ("obj_a", "obj_b")


def test_initial_setup_no_op_when_no_archive_entries():
    coord = _coord_with_archive_entries()  # empty
    sel = _make_sel(coord)

    sel._rebuild_options()
    sel._seed_initial_render()

    coord.set_wifi_render_entry.assert_not_called()


def test_initial_setup_preserves_existing_render_entry():
    """If a previous selection was already set (e.g. across reload), don't
    overwrite with the top option."""
    coord = _coord_with_archive_entries("obj_a", "obj_b")
    coord._wifi_render_entry = (None, "obj_a")  # already set
    sel = _make_sel(coord)

    sel._rebuild_options()
    sel._seed_initial_render()

    coord.set_wifi_render_entry.assert_not_called()
