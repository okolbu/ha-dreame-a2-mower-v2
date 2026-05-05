"""Tests for the dedicated edge-mow select entity (`select.edge_target`).

The entity surfaces the cloud's contour-table composite IDs so users
can pick a single zone's perimeter (multi-zone lawns) or just rely on
the default "All perimeters" option that mirrors the Dreame app's
single Edge button on a single-zone lawn.

These tests exercise the label-generation and selection-resolution
logic without going through HA's RestoreEntity machinery — that's a
hass-required path covered by the manual integration walkthrough.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState
from custom_components.dreame_a2_mower.select import DreameA2EdgeSelect


def _build_select(available_contour_ids, mowing_zones=()):
    """Construct an Edge select bound to a stub coordinator.

    Skips the regular __init__ (which touches DeviceInfo / HA) and
    directly populates the fields the test needs.
    """
    coord = MagicMock()
    coord.data = MowerState()
    coord._cached_map_data = MagicMock()
    coord._cached_map_data.available_contour_ids = tuple(available_contour_ids)
    coord._cached_map_data.mowing_zones = tuple(mowing_zones)
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord._cloud = None

    sel = DreameA2EdgeSelect.__new__(DreameA2EdgeSelect)
    sel.coordinator = coord
    sel._label_to_contours = {}
    sel._attr_options = [DreameA2EdgeSelect._PLACEHOLDER]
    sel._attr_current_option = DreameA2EdgeSelect._PLACEHOLDER

    # _set_selected_contours uses async_set_updated_data; in production
    # that's a real method, but for unit tests we just want to capture
    # the new state.
    def _capture(new_state):
        coord.data = new_state
    coord.async_set_updated_data.side_effect = _capture

    return sel, coord


def _zone(zone_id, name):
    """Stand-in for `map_decoder.MowingZone` — only the fields the
    select reads (`zone_id`, `name`)."""
    z = MagicMock()
    z.zone_id = zone_id
    z.name = name
    return z


def test_no_map_yields_placeholder():
    """Until a map is cached, the select shows the placeholder."""
    sel, _ = _build_select([])
    sel._refresh()
    assert sel.options == [DreameA2EdgeSelect._PLACEHOLDER]
    assert sel.current_option == DreameA2EdgeSelect._PLACEHOLDER


def test_single_zone_collapses_to_single_perimeter_option():
    """One outer contour → just 'Perimeter' (no 'All perimeters' wrapper)."""
    sel, coord = _build_select([(1, 0)])
    sel._refresh()
    assert sel.options == ["Perimeter"]
    assert sel.current_option == "Perimeter"
    # Auto-commit: state now reflects the only available perimeter.
    assert coord.data.active_selection_edge_contours == ((1, 0),)


def test_single_zone_label_includes_zone_name_when_present():
    """When the cloud's mowing-zones table carries a name, append it.

    User-visible: "Perimeter Zone1" rather than just "Perimeter" so the
    HA dropdown matches the Dreame app's per-zone naming.
    """
    sel, _ = _build_select(
        [(1, 0)],
        mowing_zones=[_zone(zone_id=1, name="Zone1")],
    )
    sel._refresh()
    assert sel.options == ["Perimeter Zone1"]
    assert sel.current_option == "Perimeter Zone1"


def test_multi_zone_uses_zone_names_when_present():
    """Multi-zone with named zones → '<name> perimeter' per entry, plus 'All'."""
    sel, _ = _build_select(
        [(1, 0), (2, 0), (3, 0)],
        mowing_zones=[
            _zone(zone_id=1, name="Front"),
            _zone(zone_id=2, name="Back"),
            _zone(zone_id=3, name=""),  # unnamed → falls back to "Zone N"
        ],
    )
    sel._refresh()
    assert sel.options == [
        "All perimeters",
        "Front perimeter",
        "Back perimeter",
        "Zone 3 perimeter",
    ]


def test_single_zone_no_name_falls_back_to_perimeter():
    """Empty zone name → 'Perimeter' (legacy behaviour preserved)."""
    sel, _ = _build_select(
        [(1, 0)],
        mowing_zones=[_zone(zone_id=1, name="")],
    )
    sel._refresh()
    assert sel.options == ["Perimeter"]


def test_single_zone_with_seam_contours_still_shows_only_perimeter():
    """Sub-zone seams (second-int != 0) are hidden from the dropdown.

    Matches the Dreame app's UI which never exposes merged-zone seams.
    Advanced users can still pass seam contours via the `mow_edge`
    service with explicit `contour_ids`.
    """
    sel, _ = _build_select([(1, 0), (1, 1), (1, 2)])
    sel._refresh()
    assert sel.options == ["Perimeter"]


def test_multi_zone_offers_all_plus_per_zone_options():
    """Multi-zone lawn → 'All perimeters' default + per-zone entries."""
    sel, coord = _build_select([(1, 0), (1, 1), (2, 0), (3, 0), (3, 5)])
    sel._refresh()
    assert sel.options == [
        "All perimeters",
        "Zone 1 perimeter",
        "Zone 2 perimeter",
        "Zone 3 perimeter",
    ]
    # First-time refresh auto-commits to 'All perimeters' = every (N, 0).
    assert coord.data.active_selection_edge_contours == ((1, 0), (2, 0), (3, 0))
    assert sel.current_option == "All perimeters"


def test_user_pick_persists_and_reflects_in_dropdown():
    """Selecting a single zone's perimeter writes the right tuple."""
    sel, coord = _build_select([(1, 0), (2, 0), (3, 0)])
    sel._refresh()
    # Synchronously invoke the option setter (we skip the async_write_ha_state
    # since it touches HA).
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.new_event_loop().run_until_complete(
        sel.async_select_option("Zone 2 perimeter")
    )
    assert coord.data.active_selection_edge_contours == ((2, 0),)
    assert sel.current_option == "Zone 2 perimeter"


def test_unknown_option_is_ignored():
    """A bogus option string does not corrupt the selection."""
    sel, coord = _build_select([(1, 0), (2, 0)])
    sel._refresh()
    pre = coord.data.active_selection_edge_contours
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.new_event_loop().run_until_complete(
        sel.async_select_option("Mystery option")
    )
    assert coord.data.active_selection_edge_contours == pre


# ---------------------------------------------------------------------------
# button.py edge-mow dispatch wiring
# ---------------------------------------------------------------------------


def test_button_dispatches_explicit_edge_pick():
    """Pressing Start with action_mode=EDGE forwards the picker's selection."""
    from custom_components.dreame_a2_mower.button import DreameA2StartMowingButton
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = MagicMock()
    coord.data = MowerState(
        action_mode=ActionMode.EDGE,
        active_selection_edge_contours=((2, 0),),
    )
    coord._cached_map_data = MagicMock()
    coord._cached_map_data.available_contour_ids = ((1, 0), (2, 0))

    btn = DreameA2StartMowingButton.__new__(DreameA2StartMowingButton)
    btn.coordinator = coord
    btn._attr_unique_id = "test_button_start"

    # dispatch_action is async; capture call args.
    captured = {}

    async def _cap(action, params):
        captured["action"] = action
        captured["params"] = params

    coord.dispatch_action.side_effect = _cap

    import asyncio
    asyncio.new_event_loop().run_until_complete(btn.async_press())

    assert captured["action"] == MowerAction.START_EDGE_MOW
    assert captured["params"] == {"contour_ids": [[2, 0]]}


def test_button_empty_selection_falls_through_to_dispatcher_default():
    """Empty edge selection → empty contour_ids → dispatcher resolves the default.

    The dispatcher's default-resolution path (tested in test_coordinator.py
    `test_dispatch_edge_mow_defaults_to_*`) handles this — the button just
    forwards the user's pick faithfully without second-guessing.
    """
    from custom_components.dreame_a2_mower.button import DreameA2StartMowingButton
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = MagicMock()
    coord.data = MowerState(
        action_mode=ActionMode.EDGE,
        active_selection_edge_contours=(),  # no explicit pick
    )

    btn = DreameA2StartMowingButton.__new__(DreameA2StartMowingButton)
    btn.coordinator = coord
    btn._attr_unique_id = "test_button_start"

    captured = {}

    async def _cap(action, params):
        captured["action"] = action
        captured["params"] = params

    coord.dispatch_action.side_effect = _cap

    import asyncio
    asyncio.new_event_loop().run_until_complete(btn.async_press())

    assert captured["action"] == MowerAction.START_EDGE_MOW
    assert captured["params"] == {"contour_ids": []}
