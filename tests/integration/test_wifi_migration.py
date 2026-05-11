"""Smoke test for the per-map WiFi orphan cleanup (Task 9 / Task 8 follow-up)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.dreame_a2_mower._migration import remove_per_map_wifi_orphans


def _make_entry(entity_id: str, unique_id: str, config_entry_id: str) -> MagicMock:
    e = MagicMock()
    e.entity_id = entity_id
    e.unique_id = unique_id
    e.config_entry_id = config_entry_id
    return e


def test_removes_orphan_request_wifi_map_and_wifi_heatmap():
    """Orphan button + camera are removed; keeper and other-entry untouched."""
    keeper = _make_entry(
        "camera.dreame_a2_mower_wifi_heatmap_selected",
        "SN123_wifi_heatmap_selected",
        "fake_entry",
    )
    orphan_button = _make_entry(
        "button.dreame_a2_mower_map_0_request_wifi_map",
        "SN123_map_0_request_wifi_map",
        "fake_entry",
    )
    orphan_camera = _make_entry(
        "camera.dreame_a2_mower_map_0_wifi_heatmap",
        "SN123_map_0_wifi_heatmap",
        "fake_entry",
    )
    unrelated = _make_entry(
        "button.other_request_wifi_map",
        "OTHER_request_wifi_map",
        "OTHER_ENTRY",
    )

    reg = MagicMock()
    reg.entities = {
        keeper.entity_id: keeper,
        orphan_button.entity_id: orphan_button,
        orphan_camera.entity_id: orphan_camera,
        unrelated.entity_id: unrelated,
    }
    reg.async_remove = MagicMock()

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "fake_entry"

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=reg,
    ):
        asyncio.run(remove_per_map_wifi_orphans(hass, entry))

    removed = {c.args[0] for c in reg.async_remove.call_args_list}
    assert orphan_button.entity_id in removed
    assert orphan_camera.entity_id in removed
    assert keeper.entity_id not in removed
    assert unrelated.entity_id not in removed


def test_keeper_wifi_heatmap_selected_not_removed():
    """Exact-suffix match: ``_wifi_heatmap_selected`` must never be removed."""
    # Map-level heatmap with map_id=5 — also should not be touched since it
    # ends with ``_wifi_heatmap`` only as the last segment.  This variant
    # double-checks the suffix boundary.
    keeper_selected = _make_entry(
        "camera.dreame_a2_mower_wifi_heatmap_selected",
        "SN123_wifi_heatmap_selected",
        "entry_a",
    )
    # Make sure a unique_id that merely *contains* the substring but ends
    # differently is not removed.
    contains_only = _make_entry(
        "camera.dreame_a2_mower_wifi_heatmap_overlay",
        "SN123_wifi_heatmap_overlay",
        "entry_a",
    )

    reg = MagicMock()
    reg.entities = {
        keeper_selected.entity_id: keeper_selected,
        contains_only.entity_id: contains_only,
    }
    reg.async_remove = MagicMock()

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry_a"

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=reg,
    ):
        asyncio.run(remove_per_map_wifi_orphans(hass, entry))

    reg.async_remove.assert_not_called()


def test_no_entities_is_a_noop():
    """Empty registry does not raise."""
    reg = MagicMock()
    reg.entities = {}
    reg.async_remove = MagicMock()

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry_a"

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=reg,
    ):
        asyncio.run(remove_per_map_wifi_orphans(hass, entry))

    reg.async_remove.assert_not_called()
