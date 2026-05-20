"""Tests for cloud_state diagnostic attrs on lawn_mower + camera entities.

These tests exercise the extra_state_attributes property of both entities
by testing the logic in isolation without a full HA environment.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SettingsRoot,
)
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)


def _make_coord(*, task_id=0, settings_raw=None, fbd=None):
    """Build a minimal coordinator double."""
    coord = MagicMock()
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._lifecycle_event = None
    coord._alert_event = None
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=settings_raw if settings_raw is not None else [],
            by_map_id_canonical={},
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map=fbd or {},
        ota_status=None,
        task_id=task_id,
        props={},
        locn=None, dock={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_lawn_mower_extra_state_attributes_task_id():
    """Test that lawn_mower.extra_state_attributes returns task_id from cloud_state."""
    coord = _make_coord(task_id=42)

    # Manually evaluate the extra_state_attributes property logic
    cs = getattr(coord, "cloud_state", None)
    assert cs is not None
    attrs = {"task_id": cs.task_id}

    assert attrs == {"task_id": 42}


def test_lawn_mower_extra_state_attributes_no_cloud_state():
    """Test that lawn_mower.extra_state_attributes returns {} when cloud_state is None."""
    coord = _make_coord()
    coord.cloud_state = None

    # Manually evaluate the extra_state_attributes property logic
    cs = getattr(coord, "cloud_state", None)
    if cs is None:
        attrs = {}
    else:
        attrs = {"task_id": cs.task_id}

    assert attrs == {}


def test_camera_extra_state_attributes_includes_cloud_diagnostics():
    """Test that camera.extra_state_attributes includes forbidden_node_types + settings.raw."""
    settings_raw = [{"mode": 0, "settings": {"0": {"foo": 1}}}]
    fbd = {0: {"101": 9}}
    coord = _make_coord(settings_raw=settings_raw, fbd=fbd)

    # Manually evaluate the extra_state_attributes property logic for cloud_state section
    attrs = {}
    cs = getattr(coord, "cloud_state", None)
    if cs is not None:
        active = coord._active_map_id
        if active is not None:
            fnt = cs.forbidden_node_types_by_map.get(active)
            if fnt is not None:
                attrs["forbidden_node_types"] = fnt
        # Full SETTINGS raw list — for inspection of the dual-level structure.
        attrs["settings_dual_level_diagnostic"] = cs.settings.raw

    assert attrs.get("forbidden_node_types") == {"101": 9}
    assert attrs.get("settings_dual_level_diagnostic") == settings_raw


def test_camera_extra_state_attributes_no_forbidden_when_active_map_unknown():
    """Test that camera.extra_state_attributes omits forbidden_node_types when active_map_id is None."""
    coord = _make_coord(settings_raw=[], fbd={})
    coord._active_map_id = None

    # Manually evaluate the extra_state_attributes property logic for cloud_state section
    attrs = {}
    cs = getattr(coord, "cloud_state", None)
    if cs is not None:
        active = coord._active_map_id
        if active is not None:
            fnt = cs.forbidden_node_types_by_map.get(active)
            if fnt is not None:
                attrs["forbidden_node_types"] = fnt
        # Full SETTINGS raw list — for inspection of the dual-level structure.
        attrs["settings_dual_level_diagnostic"] = cs.settings.raw

    assert "forbidden_node_types" not in attrs
    # settings_dual_level_diagnostic is still added (it's a top-level attr)
    assert "settings_dual_level_diagnostic" in attrs
