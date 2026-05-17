"""build_settings_snapshot_v2: full firmware-state capture at session-start.

Field names in the mocks match EXACT MowerState attribute names from
mower/state.py (verified 2026-05-17). See _snapshot.py module docstring
for the plan-vs-actual name mapping.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator._snapshot import (
    SNAPSHOT_VERSION,
    build_settings_snapshot_v2,
)


def _mk_coordinator(per_map_settings, mower_state_attrs: dict):
    """Build a minimal coordinator mock with cloud_state and data stubs."""
    coord = MagicMock()
    coord._active_map_id = 0

    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: per_map_settings}
    coord.cloud_state = cs

    # Use spec_set so that accessing an attribute NOT in mower_state_attrs
    # raises AttributeError, making the "missing fields → None" test meaningful.
    if mower_state_attrs:
        state = MagicMock(spec_set=list(mower_state_attrs.keys()), **mower_state_attrs)
    else:
        # Empty spec_set — every attribute access raises AttributeError
        state = MagicMock(spec_set=[])
    coord.data = state
    return coord


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_snapshot_has_version_and_captured_at():
    coord = _mk_coordinator({}, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["version"] == SNAPSHOT_VERSION
    assert snap["version"] == 2
    assert snap["captured_at_unix"] == 1234567890


def test_snapshot_has_all_four_sections():
    coord = _mk_coordinator({}, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1)
    assert "per_map" in snap
    assert "device_wide" in snap
    assert "peripheral" in snap
    assert "forensic" in snap


# ---------------------------------------------------------------------------
# per_map section
# ---------------------------------------------------------------------------

def test_per_map_section_populated_from_cloud_settings():
    per_map = {"mowingHeight": 4, "edgeMowingAuto": 1, "obstacleAvoidanceAi": 2}
    coord = _mk_coordinator(per_map, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["per_map"]["mowingHeight"] == 4
    assert snap["per_map"]["edgeMowingAuto"] == 1
    assert snap["per_map"]["obstacleAvoidanceAi"] == 2


def test_per_map_none_when_no_active_map():
    coord = _mk_coordinator({}, {})
    coord._active_map_id = None
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["per_map"] is None


def test_per_map_none_when_cloud_state_missing():
    coord = _mk_coordinator({}, {})
    coord.cloud_state = None
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["per_map"] is None


# ---------------------------------------------------------------------------
# device_wide section  (actual MowerState field names)
# ---------------------------------------------------------------------------

def test_device_wide_section_from_mower_state():
    coord = _mk_coordinator({}, {
        "rain_protection_enabled": True,
        "rain_protection_resume_hours": 4,
        "frost_protection_enabled": True,
        "navigation_path_smart": False,
        "auto_recharge_battery_pct": 15,
        "auto_recharge_standby_enabled": True,
        "custom_charging_enabled": False,
        "dnd_enabled": False,
        "low_speed_at_night_enabled": True,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    dw = snap["device_wide"]
    assert dw["rain_protection_enabled"] is True
    assert dw["rain_protection_resume_hours"] == 4
    assert dw["frost_protection_enabled"] is True
    assert dw["navigation_path_smart"] is False
    assert dw["auto_recharge_battery_pct"] == 15
    assert dw["auto_recharge_standby_enabled"] is True
    assert dw["custom_charging_enabled"] is False
    assert dw["dnd_enabled"] is False
    assert dw["low_speed_at_night_enabled"] is True


# ---------------------------------------------------------------------------
# peripheral section
# ---------------------------------------------------------------------------

def test_peripheral_section_has_human_presence():
    coord = _mk_coordinator({}, {
        "human_presence_alert_enabled": True,
        "human_presence_alert_sensitivity": 1,
        "human_presence_scenario_standby": True,
        "human_presence_scenario_mowing": True,
        "human_presence_scenario_recharge": True,
        "human_presence_scenario_patrol": True,
        "human_presence_alert_voice": False,
        "human_presence_alert_push_interval_min": 3,
        "photo_consent": True,
        "ai_obstacle_photos_enabled": True,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    p = snap["peripheral"]
    assert p["human_presence_alert_enabled"] is True
    assert p["human_presence_alert_sensitivity"] == 1
    assert p["human_presence_alert_push_interval_min"] == 3
    assert p["photo_consent"] is True
    assert p["ai_obstacle_photos_enabled"] is True


# ---------------------------------------------------------------------------
# forensic section  (actual MowerState field names)
# ---------------------------------------------------------------------------

def test_forensic_section_collects_led_voice_security():
    coord = _mk_coordinator({}, {
        "led_in_standby": True,
        "led_in_error": True,
        "led_in_charging": True,
        "led_in_working": True,
        "led_period_enabled": False,
        "language_voice_idx": 7,
        "language_text_idx": 7,
        "anti_theft_lift_alarm": False,
        "anti_theft_offmap_alarm": False,
        "anti_theft_realtime_location": True,
        "child_lock_enabled": False,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    f = snap["forensic"]
    assert f["led_in_standby"] is True
    assert f["led_in_error"] is True
    assert f["led_in_charging"] is True
    assert f["led_in_working"] is True
    assert f["led_period_enabled"] is False
    assert f["language_voice_idx"] == 7
    assert f["language_text_idx"] == 7
    assert f["anti_theft_offmap_alarm"] is False
    assert f["anti_theft_realtime_location"] is True
    assert f["child_lock_enabled"] is False


# ---------------------------------------------------------------------------
# Missing-field robustness
# ---------------------------------------------------------------------------

def test_missing_fields_become_none():
    """spec_set=[] means every getattr raises AttributeError; _safe returns None."""
    coord = _mk_coordinator({}, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert all(v is None for v in snap["device_wide"].values())
    assert all(v is None for v in snap["peripheral"].values())
    assert all(v is None for v in snap["forensic"].values())
