"""Unit tests for the pure CFG -> MowerState updates helper."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator._property_apply import (
    cfg_to_state_updates,
)


def test_present_keys_are_ported():
    cfg = {
        "CLS": 1,
        "VOL": 60,
        "DND": [1, 1200, 480],
        "WRP": [1, 0],
        "BAT": [80, 60, 1, 1, 1200, 480],
        "PROT": 1,
    }
    out = cfg_to_state_updates(cfg)
    assert out["child_lock_enabled"] is True
    assert out["volume_pct"] == 60
    assert out["dnd_enabled"] is True
    assert out["dnd_start_min"] == 1200
    assert out["dnd_end_min"] == 480
    assert out["rain_protection_enabled"] is True
    assert out["rain_protection_resume_hours"] == 0
    assert out["auto_recharge_battery_pct"] == 80
    assert out["custom_charging_enabled"] is True
    assert out["navigation_path_smart"] is True


def test_absent_keys_are_omitted_not_nulled():
    """A CFG dict missing a key must not emit that key at all, so the
    caller leaves the prior MowerState value untouched."""
    out = cfg_to_state_updates({"CLS": 0})
    assert out == {"child_lock_enabled": False}
    assert "volume_pct" not in out
    assert "dnd_enabled" not in out
    assert "blades_life_pct" not in out


def test_push_owned_pre_fields_never_emitted():
    """pre_mowing_height_mm / pre_edgemaster belong to the s6.2 push,
    not CFG — even a full-length PRE list must not produce them."""
    out = cfg_to_state_updates({"PRE": [3, 1, 25, 0, 0, 0, 0, 0, 1]})
    assert out["pre_zone_id"] == 3
    assert out["pre_mowing_efficiency"] == 1
    assert "pre_mowing_height_mm" not in out
    assert "pre_edgemaster" not in out


def test_cms_wear_percentages():
    # CMS = [blades_min, cleaning_brush_min, robot_maintenance_min, link]
    # thresholds (min) = (6000, 30000, 3600); pct remaining = 100 - used/threshold*100
    out = cfg_to_state_updates({"CMS": [1000, 2000, 3000, 0]})
    assert out["blades_life_pct"] == 83.3              # 100 - 1000/6000*100
    assert out["cleaning_brush_life_pct"] == 93.3      # 100 - 2000/30000*100
    assert out["robot_maintenance_life_pct"] == 16.7   # 100 - 3000/3600*100


def test_malformed_value_is_skipped_not_raised():
    """A malformed CFG value is logged and skipped, not fatal."""
    out = cfg_to_state_updates({"VOL": "not-an-int", "CLS": 1})
    assert "volume_pct" not in out
    assert out["child_lock_enabled"] is True


def test_empty_cfg_returns_empty_dict():
    assert cfg_to_state_updates({}) == {}
