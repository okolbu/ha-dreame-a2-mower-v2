"""Integration test: MIHIS+SETTINGS fields populate at startup via cloud_state.

Validates that after _apply_cloud_state_to_mower_state runs once with a
populated cloud_state, the entities reading MowerState fields no longer
need to wait for MQTT pushes. This is the cloud-state-makes-it-fast
guarantee that Task 17 documents.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)


def _make_coord_with_full_cloud_state():
    coord = object.__new__(DreameA2MowerCoordinator)
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
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[
                {
                    "mode": 0,
                    "settings": {
                        "0": {
                            "mowingHeight": 5,
                            "mowingDirection": 0,
                            "edgeMowingAuto": 1,
                        }
                    },
                }
            ],
            by_map_id_canonical={
                0: {
                    "mowingHeight": 5,
                    "mowingDirection": 0,
                    "edgeMowingAuto": 1,
                },
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={"area": 1234.5, "time": 678, "count": 9},
        fetched_at_unix=1700000000,
    )

    # Stub async_set_updated_data — the helper bypasses HA's listener machinery
    # in unit tests.
    def _set(new_state):
        coord.data = new_state
    coord.async_set_updated_data = _set
    return coord


def test_mihis_fields_populated_at_startup():
    """Once _apply_cloud_state_to_mower_state runs, MIHIS-derived fields
    are non-None — entities don't need to wait for MQTT pushes."""
    coord = _make_coord_with_full_cloud_state()
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.total_mowed_area_m2 == 1234.5
    assert coord.data.total_mowing_time_min == 678
    assert coord.data.mowing_count == 9


def test_settings_fields_populated_at_startup():
    """SETTINGS fields populate from active-map canonical settings."""
    coord = _make_coord_with_full_cloud_state()
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.settings_mowing_height == 5
    assert coord.data.settings_mowing_direction == 0
    assert coord.data.settings_edge_mowing_auto is True


def test_mower_state_fields_remain_none_when_not_in_cloud():
    """Fields without a cloud source stay None at startup (e.g. live position)."""
    coord = _make_coord_with_full_cloud_state()
    coord._apply_cloud_state_to_mower_state()
    # position_x_m / position_y_m come from s1.4 telemetry, not cloud.
    assert coord.data.position_x_m is None
    assert coord.data.position_y_m is None


def test_cfg_settings_ported_via_cloud_state():
    """CFG settings reach MowerState through the cloud_state path now that
    cfg_to_state_updates is folded in."""
    coord = _make_coord_with_full_cloud_state()
    coord.cloud_state = dataclasses.replace(
        coord.cloud_state, cfg={"CLS": 1, "VOL": 42, "WRP": [1, 0]}
    )
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.child_lock_enabled is True
    assert coord.data.volume_pct == 42
    assert coord.data.rain_protection_enabled is True


def test_cfg_does_not_clobber_push_owned_pre_fields():
    """A cloud_state refresh whose CFG lacks PRE height/edgemaster must leave
    push-set values intact (the old _refresh_cfg nulled them every tick)."""
    coord = _make_coord_with_full_cloud_state()
    coord.data = dataclasses.replace(
        coord.data, pre_edgemaster=True, pre_mowing_height_mm=25
    )
    coord.cloud_state = dataclasses.replace(coord.cloud_state, cfg={"PRE": [3, 1]})
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.pre_edgemaster is True
    assert coord.data.pre_mowing_height_mm == 25
    assert coord.data.pre_zone_id == 3
