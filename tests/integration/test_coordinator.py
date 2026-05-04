"""Coordinator tests — state update flow.

These use pytest-homeassistant-custom-component (added in F1.4.3).
F1.4.2 starts with a non-HA test that just verifies the
update-state-from-payload logic.
"""
from __future__ import annotations

import asyncio
import base64
import struct
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)
from custom_components.dreame_a2_mower.coordinator import (
    apply_property_to_state,
    DreameA2MowerCoordinator,
)


def test_apply_battery_level_property():
    """A (3, 1) property push updates MowerState.battery_level."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=1, value=72)
    assert new_state.battery_level == 72
    # Other fields unchanged
    assert new_state.state is None
    assert new_state.charging_status is None


def test_apply_state_property():
    """A (2, 1) property push updates MowerState.state."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=2, piid=1, value=1)
    assert new_state.state == State.WORKING


def test_apply_charging_status_property():
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=2, value=1)
    assert new_state.charging_status == ChargingStatus.CHARGING


def test_apply_unknown_property_returns_unchanged_state():
    """Unknown (siid, piid) is logged elsewhere; the state is unchanged."""
    state = MowerState(battery_level=50)
    new_state = apply_property_to_state(state, siid=99, piid=99, value="weird")
    assert new_state == state


def test_apply_property_with_invalid_state_value_keeps_field_none():
    """Invalid enum values are dropped (the integration logs NOVEL elsewhere)."""
    state = MowerState()
    # 999 is not a valid State enum
    new_state = apply_property_to_state(state, siid=2, piid=1, value=999)
    assert new_state.state is None


# ---------------------------------------------------------------------------
# F2.3.1 — s1.4 telemetry blob dispatch tests
# ---------------------------------------------------------------------------

def _pack_pose(x20: int, y20: int) -> bytes:
    """Pack (x20, y20) into 5 bytes using the apk's 20-bit signed format.

    The decoder uses _decode_pose which reverses this operation:
      x: 20-bit signed stored in b0[7:0], b1[7:0], b2[3:0]
      y: 20-bit signed stored in b2[7:4], b3[7:0], b4[7:0]
    Raw values are in map-scale millimetres (= actual_mm / 10 × 10).
    """
    if x20 < 0:
        x20 += 0x100000
    if y20 < 0:
        y20 += 0x100000
    b0 = x20 & 0xFF
    b1 = (x20 >> 8) & 0xFF
    b2 = ((y20 & 0x0F) << 4) | ((x20 >> 16) & 0x0F)
    b3 = (y20 >> 4) & 0xFF
    b4 = (y20 >> 12) & 0xFF
    return bytes([b0, b1, b2, b3, b4])


def _make_s1p4_frame_33b(
    x_m: float = 1.23,
    y_m: float = -4.56,
    phase: int = 2,
    distance_dm: int = 3450,
    area_mowed_cm2: int = 1250,
) -> bytes:
    """Construct a valid 33-byte s1.4 telemetry frame.

    Uses the apk's 20-bit signed packed pose encoding at bytes [1-5].
    Position arguments are in metres; the encoder converts to raw units
    (x20 = round(x_m * 1000 / 10), y20 = round(y_m * 1000 / 10)).

    distance_dm:    distance in decimetres (distance_m = distance_dm / 10)
    area_mowed_cm2: area in cm² (area_mowed_m2 = area_mowed_cm2 / 100)
    """
    # x20 and y20 are in map-scale millimetres divided by 10 (× 10 factor)
    x20 = round(x_m * 1000 / 10)   # x_mm / 10
    y20 = round(y_m * 1000 / 10)   # y_mm / 10
    pose = _pack_pose(x20, y20)

    frame = bytearray(33)
    frame[0] = 0xCE                                   # delimiter
    frame[1:6] = pose                                 # bytes 1-5: pose
    frame[6] = 0                                      # heading byte
    frame[7] = 0                                      # trace_start_index[0]
    frame[8] = phase                                  # phase byte
    # bytes 9-21: zeros (motion vectors, trace_start, etc.)
    frame[22] = 0                                     # region_id
    frame[23] = 0                                     # task_id
    struct.pack_into("<H", frame, 24, distance_dm)    # bytes 24-25: distance
    struct.pack_into("<H", frame, 26, 50000)          # bytes 26-27: total_area (filler)
    frame[28] = 0
    struct.pack_into("<H", frame, 29, area_mowed_cm2) # bytes 29-30: area_mowed
    frame[31] = 0
    frame[32] = 0xCE                                  # delimiter
    return bytes(frame)


def test_s1p4_blob_updates_position_area_phase():
    """A (1, 4) push (telemetry blob) decodes and updates multiple state fields."""
    state = MowerState()
    blob = _make_s1p4_frame_33b(
        x_m=1.23, y_m=-4.56, phase=2, distance_dm=3450, area_mowed_cm2=1250
    )
    # MQTT delivers the blob base64-encoded in the value field
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    assert new_state.mowing_phase == 2
    assert abs(new_state.area_mowed_m2 - 12.50) < 0.001


def test_s1p4_short_frame_updates_position_only():
    """8-byte BEACON short frames update only position_x_m and position_y_m."""
    state = MowerState(mowing_phase=5, area_mowed_m2=7.0)
    # Build an 8-byte beacon with the same pose as the 33-byte test
    x20 = round(1.23 * 1000 / 10)
    y20 = round(-4.56 * 1000 / 10)
    pose = _pack_pose(x20, y20)
    frame8 = bytearray(8)
    frame8[0] = 0xCE
    frame8[1:6] = pose
    frame8[7] = 0xCE
    value = base64.b64encode(bytes(frame8)).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    # Non-position fields are unchanged (still the original values)
    assert new_state.mowing_phase == 5
    assert new_state.area_mowed_m2 == 7.0


def test_s1p4_invalid_blob_returns_unchanged_state():
    """A malformed s1.4 blob is dropped (logged) without crashing."""
    state = MowerState(position_x_m=1.0)
    new_state = apply_property_to_state(state, siid=1, piid=4, value="not-base64-padded!!")
    # State is unchanged
    assert new_state == state


# ---------------------------------------------------------------------------
# F2.3.2 — s1.1 heartbeat blob dispatch tests
# ---------------------------------------------------------------------------

def _make_s1p1_frame_temp_low_set() -> bytes:
    """20-byte heartbeat with battery_temp_low bit asserted at byte[6] bit 3."""
    frame = bytearray(20)
    frame[0] = 0xCE   # delimiter
    frame[6] = 0x08   # bit 3 = battery_temp_low
    frame[19] = 0xCE  # delimiter
    return bytes(frame)


def test_s1p1_blob_sets_battery_temp_low():
    """A (1, 1) push with battery_temp_low bit set → state.battery_temp_low is True."""
    state = MowerState()
    blob = _make_s1p1_frame_temp_low_set()
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is True


def test_s1p1_blob_clears_battery_temp_low():
    """When the bit is unset, battery_temp_low → False (not None)."""
    state = MowerState(battery_temp_low=True)
    frame = bytearray(20)
    frame[0] = 0xCE   # delimiter
    frame[6] = 0x00   # bit 3 cleared
    frame[19] = 0xCE  # delimiter
    blob = bytes(frame)
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is False


# ---------------------------------------------------------------------------
# F4.2.1 — s2.51 multiplexed-config dispatch tests
#
# Payloads match those in tests/protocol/test_config_s2p51.py so they
# are known-good (the protocol decoder is already tested; here we verify
# the coordinator's dispatch plumbs through to the right MowerState fields).
# ---------------------------------------------------------------------------

def test_s2p51_rain_protection_updates_state():
    """s2.51 RAIN_PROTECTION payload sets rain_protection_* fields."""
    state = MowerState()
    # [enabled=1, resume_hours=3] — from test_decode_rain_protection_two_element_list
    payload = {"value": [1, 3]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.rain_protection_enabled is True
    assert new_state.rain_protection_resume_hours == 3
    # Unrelated fields unchanged
    assert new_state.dnd_enabled is None


def test_s2p51_rain_protection_disabled():
    """s2.51 RAIN_PROTECTION with enabled=0 sets field to False."""
    state = MowerState()
    payload = {"value": [0, 6]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.rain_protection_enabled is False
    assert new_state.rain_protection_resume_hours == 6


def test_s2p51_dnd_updates_state():
    """s2.51 DND payload updates dnd_enabled, dnd_start_min, dnd_end_min."""
    state = MowerState()
    # {"end": 420, "start": 1320, "value": 1} — from test_decode_dnd_event_extracts_start_end_enabled
    payload = {"end": 420, "start": 1320, "value": 1}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.dnd_enabled is True
    assert new_state.dnd_start_min == 1320
    assert new_state.dnd_end_min == 420


def test_s2p51_dnd_disabled():
    """s2.51 DND with value=0 sets dnd_enabled to False."""
    state = MowerState()
    payload = {"end": 420, "start": 1320, "value": 0}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.dnd_enabled is False


def test_s2p51_charging_updates_battery_thresholds():
    """s2.51 CHARGING payload updates auto_recharge_battery_pct and resume_battery_pct."""
    state = MowerState()
    # [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]
    # From test_decode_charging_six_element_list
    payload = {"value": [15, 95, 0, 0, 0, 0]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.auto_recharge_battery_pct == 15
    assert new_state.resume_battery_pct == 95
    assert new_state.custom_charging_enabled is False
    assert new_state.charging_start_min == 0
    assert new_state.charging_end_min == 0


def test_s2p51_charging_with_custom_schedule():
    """s2.51 CHARGING with custom_charging=1 sets correct fields."""
    state = MowerState()
    payload = {"value": [20, 80, 0, 1, 480, 720]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.auto_recharge_battery_pct == 20
    assert new_state.resume_battery_pct == 80
    assert new_state.custom_charging_enabled is True
    assert new_state.charging_start_min == 480
    assert new_state.charging_end_min == 720


def test_s2p51_led_period_updates_state():
    """s2.51 LED_PERIOD payload updates led_period_enabled and scenario bools."""
    state = MowerState()
    # [enabled, start_min, end_min, standby, working, charging, error, reserved]
    # From test_decode_led_period_eight_element_list
    payload = {"value": [1, 360, 1320, 1, 1, 1, 1, 0]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.led_period_enabled is True
    assert new_state.led_in_standby is True
    assert new_state.led_in_working is True
    assert new_state.led_in_charging is True
    assert new_state.led_in_error is True


def test_s2p51_low_speed_night_updates_state():
    """s2.51 LOW_SPEED_NIGHT payload updates low_speed_at_night_* fields."""
    state = MowerState()
    # [enabled=1, start_min=1260, end_min=360] — from test_decode_low_speed_nighttime
    payload = {"value": [1, 1260, 360]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.low_speed_at_night_enabled is True
    assert new_state.low_speed_at_night_start_min == 1260
    assert new_state.low_speed_at_night_end_min == 360


def test_s2p51_anti_theft_updates_state():
    """s2.51 ANTI_THEFT payload updates all three alarm bools."""
    state = MowerState()
    # [lift_alarm=1, offmap_alarm=0, realtime_location=1]
    # From test_decode_anti_theft_three_element_all_binary
    payload = {"value": [1, 0, 1]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.anti_theft_lift_alarm is True
    assert new_state.anti_theft_offmap_alarm is False
    assert new_state.anti_theft_realtime_location is True


def test_s2p51_human_presence_alert_updates_state():
    """s2.51 HUMAN_PRESENCE_ALERT payload updates enabled + sensitivity."""
    state = MowerState()
    # [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]
    # From test_decode_human_presence_nine_element_list
    payload = {"value": [0, 1, 1, 1, 1, 1, 1, 0, 3]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.human_presence_alert_enabled is False
    assert new_state.human_presence_alert_sensitivity == 1


def test_s2p51_language_updates_state():
    """s2.51 LANGUAGE payload updates language_text_idx and language_voice_idx."""
    state = MowerState()
    # From test_decode: {'text': 2, 'voice': 7} → text_idx=2, voice_idx=7
    payload = {"text": 2, "voice": 7}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.language_text_idx == 2
    assert new_state.language_voice_idx == 7


def test_s2p51_timestamp_updates_last_settings_change():
    """s2.51 TIMESTAMP payload updates last_settings_change_unix."""
    state = MowerState()
    payload = {"time": "1776415722", "tz": "UTC"}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.last_settings_change_unix == 1776415722


def test_s2p51_ambiguous_toggle_drops_silently():
    """AMBIGUOUS_TOGGLE leaves state unchanged (no field to map to)."""
    state = MowerState(rain_protection_enabled=True)
    payload = {"value": 1}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state == state


def test_s2p51_ambiguous_4list_drops_silently():
    """AMBIGUOUS_4LIST leaves state unchanged (cannot distinguish MSG_ALERT vs VOICE)."""
    state = MowerState(dnd_enabled=True)
    payload = {"value": [1, 0, 1, 1]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state == state


def test_s2p51_invalid_payload_not_dict_drops_silently():
    """A non-dict payload (string, list, etc.) is dropped; state unchanged."""
    state = MowerState(rain_protection_enabled=True)
    new_state = apply_property_to_state(state, siid=2, piid=51, value="not-a-dict")
    assert new_state == state


def test_s2p51_malformed_dict_drops_silently():
    """A dict with unknown shape is dropped (S2P51DecodeError); state unchanged."""
    state = MowerState(dnd_enabled=False)
    new_state = apply_property_to_state(state, siid=2, piid=51, value={"nonsense": True})
    assert new_state == state


def test_s2p51_empty_dict_drops_silently():
    """An empty dict payload is dropped (S2P51DecodeError); state unchanged."""
    state = MowerState(battery_level=80)
    new_state = apply_property_to_state(state, siid=2, piid=51, value={})
    assert new_state == state


def test_s6p2_multi_field_extracts_mowing_settings():
    """s6.2 is [height_mm, mow_mode, edgemaster, ?]; multi_field extracts all three."""
    state = MowerState()
    value = [60, 1, True, 2]
    new_state = apply_property_to_state(state, siid=6, piid=2, value=value)
    assert new_state.pre_mowing_height_mm == 60
    assert new_state.pre_mowing_efficiency == 1
    assert new_state.pre_edgemaster is True


def test_s6p2_multi_field_handles_short_list():
    """s6.2 multi_field extractors handle too-short lists gracefully."""
    state = MowerState()
    value = [55]  # Only element [0]
    new_state = apply_property_to_state(state, siid=6, piid=2, value=value)
    assert new_state.pre_mowing_height_mm == 55
    assert new_state.pre_mowing_efficiency is None
    assert new_state.pre_edgemaster is None


# ---------------------------------------------------------------------------
# F4.5.1 — write_setting tests
# ---------------------------------------------------------------------------

def _make_coordinator_with_cloud(set_cfg_return=True, set_pre_return=True):
    """Return a minimal DreameA2MowerCoordinator stub with a mock cloud client.

    The coordinator is not fully initialised (no hass, no MQTT).  Tests call
    the async write_setting coroutine via ``asyncio.run()`` to avoid needing
    pytest-asyncio.  The hass.async_add_executor_job side-effect runs the
    blocking callable synchronously so no real thread pool is needed.
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    # Minimal attributes required by write_setting
    coord.data = MowerState()
    coord.logger = MagicMock()

    cloud = MagicMock()
    cloud.set_cfg.return_value = set_cfg_return
    cloud.set_pre.return_value = set_pre_return
    coord._cloud = cloud

    # hass mock: async_add_executor_job runs the callable synchronously in
    # the test (no actual thread pool needed).
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    coord.hass = hass

    # async_set_updated_data updates coord.data (mirrors real coordinator).
    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    return coord


def test_write_setting_cls_success():
    """write_setting('CLS', True) calls cloud.set_cfg and returns True."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    result = asyncio.run(coord.write_setting("CLS", True))
    assert result is True
    coord._cloud.set_cfg.assert_called_once_with("CLS", True)


def test_write_setting_vol_success():
    """write_setting('VOL', 80) calls cloud.set_cfg('VOL', 80)."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    result = asyncio.run(coord.write_setting("VOL", 80))
    assert result is True
    coord._cloud.set_cfg.assert_called_once_with("VOL", 80)


def test_write_setting_dnd_full_array():
    """write_setting('DND', [1, 1320, 420]) calls set_cfg with the full list."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    dnd_value = [1, 1320, 420]
    result = asyncio.run(coord.write_setting("DND", dnd_value))
    assert result is True
    coord._cloud.set_cfg.assert_called_once_with("DND", dnd_value)


def test_write_setting_pre_uses_set_pre():
    """write_setting('PRE', [...]) delegates to cloud.set_pre, not set_cfg."""
    coord = _make_coordinator_with_cloud(set_pre_return=True)
    pre_array = [0, 1, 50, 0, 0, 0, 0, 0, True, False]
    result = asyncio.run(coord.write_setting("PRE", pre_array))
    assert result is True
    coord._cloud.set_pre.assert_called_once_with(pre_array)
    coord._cloud.set_cfg.assert_not_called()


def test_write_setting_unknown_key_returns_false():
    """write_setting with an unrecognised cfg_key returns False without calling cloud."""
    coord = _make_coordinator_with_cloud()
    result = asyncio.run(coord.write_setting("BOGUS", 42))
    assert result is False
    coord._cloud.set_cfg.assert_not_called()
    coord._cloud.set_pre.assert_not_called()


def test_write_setting_no_cloud_returns_false():
    """write_setting returns False immediately when cloud client is not ready."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.logger = MagicMock()
    coord.hass = MagicMock()
    coord.async_set_updated_data = MagicMock()
    # No _cloud attribute — simulates pre-init state.
    result = asyncio.run(coord.write_setting("CLS", True))
    assert result is False


def test_write_setting_optimistic_update_applied_on_success():
    """field_updates are applied to MowerState before the cloud call."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    assert coord.data.child_lock_enabled is None

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    assert result is True
    assert coord.data.child_lock_enabled is True


def test_write_setting_optimistic_update_reverted_on_failure():
    """field_updates are reverted when the cloud write returns False."""
    coord = _make_coordinator_with_cloud(set_cfg_return=False)
    assert coord.data.child_lock_enabled is None

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    assert result is False
    # State reverted — child_lock_enabled should be back to None.
    assert coord.data.child_lock_enabled is None


def test_write_setting_all_cfg_keys_accepted():
    """All documented CFG keys are accepted (no unknown-key warning)."""
    known_keys = ["CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC"]
    for key in known_keys:
        coord = _make_coordinator_with_cloud(set_cfg_return=True)
        result = asyncio.run(coord.write_setting(key, "dummy_value"))
        assert result is True, f"Expected True for key {key!r}"


def test_write_setting_pre_non_list_returns_false():
    """write_setting('PRE', non-list) returns False without calling set_pre."""
    coord = _make_coordinator_with_cloud()
    result = asyncio.run(coord.write_setting("PRE", {"not": "a list"}))
    assert result is False
    coord._cloud.set_pre.assert_not_called()


# ---------------------------------------------------------------------------
# F5.3.1 — _on_state_update: s2p56 transition + s1p4 position append
# ---------------------------------------------------------------------------

def _make_coordinator_for_session_tests():
    """Return a minimal DreameA2MowerCoordinator stub with live_map initialised.

    Uses object.__new__ (like the write_setting tests above) to avoid the
    full HA initialisation path; sets the minimal attributes that
    _on_state_update requires.
    """
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState

    from custom_components.dreame_a2_mower.observability import FreshnessTracker, NovelObservationRegistry

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    # v1.0.0a18: live-trail re-render needs these in __init__-bypassing fixtures.
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._cached_map_data = None
    coord.cached_map_png = None
    return coord


def test_session_start_creates_live_map():
    """Feeding an s2p56=1 push causes live_map.begin_session to run.

    After the push:
    - live_map.is_active() is True
    - MowerState.session_active is True
    - MowerState.session_started_unix is set to the supplied now_unix
    - MowerState.session_track_segments is an empty tuple-of-legs
    """
    coord = _make_coordinator_for_session_tests()

    # Simulate an s2p56=1 push (task_state_code = 1 = start_pending)
    new_state = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    assert new_state != coord.data  # sanity: state actually changed

    now = 1_714_329_600  # arbitrary fixed timestamp
    result = coord._on_state_update(new_state, now)

    assert coord.live_map.is_active()
    assert result.session_active is True
    assert result.session_started_unix == now
    # segments is a tuple of legs; begin_session starts with one empty leg
    assert isinstance(result.session_track_segments, tuple)
    assert coord._prev_task_state == 0  # status[0][1]=0 → running (v1.0.0a18 semantics)


def test_resume_after_recharge_starts_new_leg():
    """4 → 2 transition calls live_map.begin_leg(), adding a new leg.

    Setup:
    1. Start a session (task_state=1 → begin_session).
    2. Append a point so the first leg is non-empty.
    3. Feed task_state=4 (resume_pending).
    4. Feed task_state=2 (running again) — should call begin_leg().
    5. Verify legs count grew.
    """
    coord = _make_coordinator_for_session_tests()
    now = 1_714_329_600

    # Step 1: start session
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Step 2: append a point to the first leg
    coord.live_map.append_point(1.0, 1.0, now + 10)

    # Step 3: feed task_state=4 (resume_pending — going to charge station)
    state_ts4 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 4]]})
    coord.data = coord._on_state_update(state_ts4, now + 100)
    assert coord._prev_task_state == 4

    # Step 4: feed task_state=2 (running again)
    state_ts2 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    result = coord._on_state_update(state_ts2, now + 200)

    # Step 5: a new leg was started
    assert len(coord.live_map.legs) == 2
    assert result.session_active is True
    assert coord._prev_task_state == 0  # status[0][1]=0 → running (v1.0.0a18 semantics)


def test_telemetry_during_active_session_appends_to_leg():
    """s1p4 telemetry arriving during an active session appends a point to the leg.

    Setup:
    1. Start session (task_state=1).
    2. Feed a valid s1p4 blob carrying a new position.
    3. Verify live_map.total_points() == 1 and the point is in MowerState.
    """
    coord = _make_coordinator_for_session_tests()
    now = 1_714_329_600

    # Step 1: start session
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Step 2: build a 33-byte s1p4 frame with a known position and push it
    blob = _make_s1p4_frame_33b(x_m=3.5, y_m=7.2)
    value = base64.b64encode(blob).decode("ascii")
    state_with_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    assert state_with_pos != coord.data  # position actually changed

    result = coord._on_state_update(state_with_pos, now + 30)

    # Step 3: position was appended to the active leg
    assert coord.live_map.total_points() == 1
    assert len(coord.live_map.legs[0]) == 1
    leg_pt = coord.live_map.legs[0][0]
    assert abs(leg_pt[0] - 3.5) < 0.01
    assert abs(leg_pt[1] - 7.2) < 0.01

    # MowerState.session_track_segments reflects the leg
    assert result.session_track_segments is not None
    assert len(result.session_track_segments) == 1
    assert len(result.session_track_segments[0]) == 1


# ---------------------------------------------------------------------------
# F5.6.1 — _handle_event_occured + _periodic_session_retry + _dispatch_finalize_action
# ---------------------------------------------------------------------------

def _make_coordinator_for_finalize_tests(
    pending_object_name: str | None = None,
    pending_first_attempt_unix: int | None = None,
    pending_attempt_count: int | None = None,
    task_state_code: int | None = None,
    session_active: bool | None = None,
    area_mowed_m2: float | None = None,
    session_started_unix: int | None = None,
    cloud_get_interim_file_url_return: str | None = "https://oss.example.com/signed",
    cloud_get_file_return: bytes | None = None,
):
    """Build a coordinator stub suitable for testing finalize/OSS-fetch methods.

    Wires a mock cloud client, a mock session_archive, and a mock hass
    (async_add_executor_job runs callables synchronously in tests).
    live_map is initialised so end_session() is callable.
    """
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(
        pending_session_object_name=pending_object_name,
        pending_session_first_event_unix=pending_first_attempt_unix,
        pending_session_last_attempt_unix=pending_first_attempt_unix,
        pending_session_attempt_count=pending_attempt_count,
        task_state_code=task_state_code,
        session_active=session_active,
        area_mowed_m2=area_mowed_m2,
        session_started_unix=session_started_unix,
    )
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    from custom_components.dreame_a2_mower.observability import FreshnessTracker, NovelObservationRegistry
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()

    # Mock cloud client.
    cloud = MagicMock()
    cloud.get_interim_file_url.return_value = cloud_get_interim_file_url_return
    cloud.get_file.return_value = cloud_get_file_return
    coord._cloud = cloud

    # Mock session_archive with a minimal real-ish count behaviour.
    archive = MagicMock(spec=SessionArchive)
    archive.count = 0
    coord.session_archive = archive

    # F7.2.2 — tests that need lidar_archive / _last_lidar_object_name set it explicitly.
    coord.lidar_archive = None
    coord._last_lidar_object_name = None

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    # async_set_updated_data updates coord.data.
    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


# ---------------------------------------------------------------------------
# _handle_event_occured tests
# ---------------------------------------------------------------------------


def test_handle_event_occured_sets_pending_fields():
    """_handle_event_occured with piid=9 sets pending_session_object_name + first_event_unix."""
    coord = _make_coordinator_for_finalize_tests()
    arguments = [{"piid": 9, "value": "d/xxx/sessions/abc123.json"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    assert coord.data.pending_session_object_name == "d/xxx/sessions/abc123.json"
    assert coord.data.pending_session_first_event_unix is not None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count == 0


def test_handle_event_occured_no_piid9_logs_warning():
    """_handle_event_occured with no piid=9 argument does not crash and leaves state unchanged."""
    coord = _make_coordinator_for_finalize_tests()
    arguments = [{"piid": 1, "value": "something"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    # State unchanged — no pending_session_object_name set.
    assert coord.data.pending_session_object_name is None


def test_handle_event_occured_empty_arguments_does_not_crash():
    """_handle_event_occured with empty arguments list gracefully does nothing."""
    coord = _make_coordinator_for_finalize_tests()

    import asyncio
    asyncio.run(coord._handle_event_occured([]))

    assert coord.data.pending_session_object_name is None


def test_handle_event_occured_overwrites_existing_pending():
    """A second event_occured replaces the first pending object name."""
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="old/key.json",
    )
    arguments = [{"piid": 9, "value": "new/key.json"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    assert coord.data.pending_session_object_name == "new/key.json"
    assert coord.data.pending_session_attempt_count == 0


# ---------------------------------------------------------------------------
# _on_mqtt_message event_occured branch
# ---------------------------------------------------------------------------


def test_on_mqtt_message_event_occured_schedules_handle():
    """event_occured method with siid=4 eiid=1 calls call_soon_threadsafe."""
    coord = _make_coordinator_for_finalize_tests()

    # Track what call_soon_threadsafe is called with.
    scheduled = []
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: scheduled.append(fn)

    payload = {
        "method": "event_occured",
        "params": {
            "siid": 4,
            "eiid": 1,
            "arguments": [{"piid": 9, "value": "d/sessions/abc.json"}],
        },
    }
    coord._on_mqtt_message("topic", payload)

    assert len(scheduled) == 1, "call_soon_threadsafe should be called once"


def test_on_mqtt_message_event_occured_wrong_siid_ignored():
    """event_occured with siid != 4 is ignored (no call_soon_threadsafe)."""
    coord = _make_coordinator_for_finalize_tests()
    coord.hass.loop.call_soon_threadsafe.side_effect = None  # reset

    payload = {
        "method": "event_occured",
        "params": {"siid": 99, "eiid": 1, "arguments": []},
    }
    coord._on_mqtt_message("topic", payload)
    coord.hass.loop.call_soon_threadsafe.assert_not_called()


def test_on_mqtt_message_properties_changed_still_works():
    """properties_changed still dispatches to handle_property_push after refactor."""
    coord = _make_coordinator_for_finalize_tests()
    # Give coord a real data so handle_property_push can use it.
    coord.data = MowerState()
    coord.live_map.started_unix = None

    called = []
    original_hpp = DreameA2MowerCoordinator.handle_property_push

    def _spy(self, siid, piid, value):
        called.append((siid, piid, value))

    DreameA2MowerCoordinator.handle_property_push = _spy
    try:
        payload = {
            "method": "properties_changed",
            "params": [{"siid": 3, "piid": 1, "value": 85}],
        }
        coord._on_mqtt_message("topic", payload)
    finally:
        DreameA2MowerCoordinator.handle_property_push = original_hpp

    assert called == [(3, 1, 85)]


# ---------------------------------------------------------------------------
# _do_oss_fetch tests
# ---------------------------------------------------------------------------

# Minimal valid session-summary JSON that parse_session_summary can consume.
_MINIMAL_SUMMARY_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "abc123",
    "areas": 120.5,
    "map_area": 5000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "obstacle": [],
    "map": [],
    "trajectory": [],
}


def test_do_oss_fetch_success_clears_pending_and_updates_state():
    """Successful OSS fetch archives session and clears pending_session_* fields."""
    import asyncio
    import json

    raw_bytes = json.dumps(_MINIMAL_SUMMARY_JSON).encode()

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )
    coord.session_archive.count = 1  # simulate first archive

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # latest_session_* fields populated.
    assert coord.data.latest_session_md5 == "abc123"
    assert coord.data.latest_session_area_m2 == 120.5
    assert coord.data.latest_session_duration_min == 60

    # live_map reset.
    assert not coord.live_map.is_active()


def test_do_oss_fetch_no_cloud_returns_early():
    """_do_oss_fetch with no cloud client does nothing (early boot guard)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
    )
    del coord._cloud  # simulate early boot

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # State unchanged — no cloud client.
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_no_object_name_returns_early():
    """_do_oss_fetch with no pending object name does nothing."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord._cloud.get_interim_file_url.assert_not_called()


def test_do_oss_fetch_signed_url_none_does_not_archive():
    """If get_interim_file_url returns None, fetch is aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_interim_file_url_return=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # Attempt count incremented (fetch was attempted).
    assert coord.data.pending_session_attempt_count == 1
    # Archive not called.
    coord.session_archive.archive.assert_not_called()
    # Pending object name still set (not cleared on failure).
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_raw_bytes_none_does_not_archive():
    """If get_file returns None, fetch aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_file_return=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord.session_archive.archive.assert_not_called()
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_invalid_json_does_not_archive():
    """If raw bytes are not valid JSON, fetch aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_file_return=b"this is not json {{{",
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord.session_archive.archive.assert_not_called()


# ---------------------------------------------------------------------------
# _run_finalize_incomplete tests (F5.10.1 rename from _do_finalize_incomplete)
# ---------------------------------------------------------------------------


def test_run_finalize_incomplete_clears_pending_and_ends_session():
    """_run_finalize_incomplete archives an incomplete entry, clears pending state."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/old.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=11,
        session_active=True,
        session_started_unix=1_700_000_000,
        area_mowed_m2=50.0,
    )
    coord.live_map.begin_session(1_700_000_000)
    coord.session_archive.count = 1

    asyncio.run(coord._run_finalize_incomplete(now_unix=1_700_003_700))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # Session ended.
    assert not coord.live_map.is_active()

    # Archive was called.
    coord.session_archive.archive.assert_called_once()


def test_run_finalize_incomplete_no_live_session_still_clears_pending():
    """Even with no live_map session, _run_finalize_incomplete clears pending."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/old.json",
        pending_attempt_count=12,
    )
    # live_map not started — started_unix is None.
    coord.session_archive.count = 0

    asyncio.run(coord._run_finalize_incomplete(now_unix=1_700_003_700))

    assert coord.data.pending_session_object_name is None


# ---------------------------------------------------------------------------
# F5.10.1 — dispatch_action(FINALIZE_SESSION) tests
# ---------------------------------------------------------------------------


def test_dispatch_action_finalize_session_calls_run_finalize_incomplete():
    """dispatch_action(FINALIZE_SESSION) runs the finalize-incomplete path."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/stuck.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=5,
        session_active=True,
        session_started_unix=1_700_000_000,
        area_mowed_m2=30.0,
    )
    coord.live_map.begin_session(1_700_000_000)
    coord.session_archive.count = 2

    from custom_components.dreame_a2_mower.mower.actions import MowerAction
    asyncio.run(coord.dispatch_action(MowerAction.FINALIZE_SESSION, {}))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # Session ended.
    assert not coord.live_map.is_active()

    # Archive was called with the incomplete sentinel.
    coord.session_archive.archive.assert_called_once()


def test_dispatch_action_finalize_session_no_active_session_noop_cleanly():
    """dispatch_action(FINALIZE_SESSION) with no active session clears state cleanly."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # No live session, no pending — just verify no crash.
    coord.session_archive.count = 0

    from custom_components.dreame_a2_mower.mower.actions import MowerAction
    asyncio.run(coord.dispatch_action(MowerAction.FINALIZE_SESSION, {}))

    # Pending still None — nothing to clear.
    assert coord.data.pending_session_object_name is None
    # Archive still called (archives an empty/zero session).
    coord.session_archive.archive.assert_called_once()


# ---------------------------------------------------------------------------
# _periodic_session_retry dispatch tests
# ---------------------------------------------------------------------------


def test_periodic_session_retry_noop_when_no_pending():
    """_periodic_session_retry does nothing when no pending object and session idle."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # No pending, no task_state — decide() should return NOOP.

    asyncio.run(coord._periodic_session_retry())

    coord._cloud.get_interim_file_url.assert_not_called()
    coord.session_archive.archive.assert_not_called()


def test_periodic_session_retry_fires_oss_fetch_when_pending_ready():
    """When pending object name is set and retry window has elapsed, fetch fires."""
    import asyncio
    import json

    raw_bytes = json.dumps(_MINIMAL_SUMMARY_JSON).encode()

    # Set first_attempt_unix far in the past so decide() returns AWAIT_OSS_FETCH.
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        pending_first_attempt_unix=1_700_000_000,   # far past
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )
    coord.session_archive.count = 1

    asyncio.run(coord._periodic_session_retry())

    # Pending should be cleared after successful fetch.
    assert coord.data.pending_session_object_name is None


def test_periodic_session_retry_finalize_incomplete_when_max_age_expired():
    """When max-age expired, _periodic_session_retry calls _run_finalize_incomplete."""
    import asyncio
    import time as _time
    from custom_components.dreame_a2_mower.live_map.finalize import MAX_AGE_SECONDS

    # first_attempt so old it's past MAX_AGE_SECONDS
    first_attempt = int(_time.time()) - MAX_AGE_SECONDS - 3600

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/expired.json",
        pending_first_attempt_unix=first_attempt,
        pending_attempt_count=0,
    )
    coord.live_map.begin_session(first_attempt)
    coord.session_archive.count = 1

    asyncio.run(coord._periodic_session_retry())

    # decide() returns FINALIZE_INCOMPLETE → _run_finalize_incomplete ran.
    assert coord.data.pending_session_object_name is None
    coord.session_archive.archive.assert_called_once()


# ---------------------------------------------------------------------------
# F5.7.1 — _restore_in_progress + _persist_in_progress
# ---------------------------------------------------------------------------


def _make_coordinator_for_persist_tests(
    live_map_legs: list | None = None,
    live_map_started_unix: int | None = None,
    live_map_dirty: bool = False,
    area_mowed_m2: float | None = None,
    write_in_progress_side_effect=None,
    read_in_progress_return=None,
):
    """Build a minimal coordinator stub suitable for restore/persist tests.

    Uses a real SessionArchive mock (not spec-locked) so read_in_progress
    and write_in_progress can be configured independently.
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(area_mowed_m2=area_mowed_m2)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._live_map_dirty = live_map_dirty

    if live_map_started_unix is not None:
        coord.live_map.started_unix = live_map_started_unix
        coord.live_map.legs = live_map_legs if live_map_legs is not None else [[]]

    # Mock session_archive.
    archive = MagicMock(spec=SessionArchive)
    archive.read_in_progress.return_value = read_in_progress_return
    if write_in_progress_side_effect is not None:
        archive.write_in_progress.side_effect = write_in_progress_side_effect
    coord.session_archive = archive

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


# ---- _restore_in_progress ----

def test_restore_in_progress_populates_live_map_from_disk():
    """On HA boot with a valid in_progress.json, live_map is repopulated.

    After _restore_in_progress:
    - live_map.started_unix matches session_start_ts from disk
    - live_map.legs contains the restored track
    - MowerState.session_active is True
    - MowerState.session_track_segments reflects the legs
    """
    import asyncio

    disk_payload = {
        "session_start_ts": 1_714_329_600,
        "legs": [[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0]]],
        "area_mowed_m2": 42.0,
        "map_area_m2": 0,
        "last_update_ts": 1_714_329_700,
    }
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.started_unix == 1_714_329_600
    assert len(coord.live_map.legs) == 2
    assert coord.live_map.legs[0] == [(1.0, 2.0), (3.0, 4.0)]
    assert coord.live_map.legs[1] == [(5.0, 6.0)]
    assert coord.live_map.total_points() == 3

    assert coord.data.session_active is True
    assert coord.data.session_started_unix == 1_714_329_600
    assert isinstance(coord.data.session_track_segments, tuple)
    assert len(coord.data.session_track_segments) == 2
    assert coord.data.session_track_segments[0] == ((1.0, 2.0), (3.0, 4.0))
    assert coord.data.session_track_segments[1] == ((5.0, 6.0),)


def test_restore_in_progress_no_file_leaves_state_unchanged():
    """When read_in_progress returns None, live_map stays idle and MowerState unchanged."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(read_in_progress_return=None)
    original_state = coord.data

    asyncio.run(coord._restore_in_progress())

    assert not coord.live_map.is_active()
    # MowerState unchanged — async_set_updated_data not called.
    assert coord.data is original_state


def test_restore_in_progress_skips_if_live_map_already_active():
    """If MQTT arrived first and live_map is already active, restore is skipped."""
    import asyncio

    disk_payload = {
        "session_start_ts": 1_000_000,
        "legs": [[[0.0, 0.0]]],
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    }
    # Pre-start a session in live_map (simulates MQTT arriving before restore).
    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=2_000_000,  # a *different* (newer) session
        live_map_legs=[[(9.0, 9.0)]],
        read_in_progress_return=disk_payload,
    )

    asyncio.run(coord._restore_in_progress())

    # live_map should still have the MQTT-driven session, not the disk one.
    assert coord.live_map.started_unix == 2_000_000
    assert coord.live_map.legs == [[(9.0, 9.0)]]
    # async_set_updated_data should NOT have been called (state unchanged).
    assert coord.data.session_active is None


def test_restore_in_progress_zero_start_ts_discards():
    """An in-progress entry with session_start_ts=0 is treated as invalid."""
    import asyncio

    disk_payload = {"session_start_ts": 0, "legs": [], "area_mowed_m2": 0.0}
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert not coord.live_map.is_active()


def test_restore_in_progress_empty_legs_starts_with_one_empty_leg():
    """An in-progress entry with an empty legs list still sets live_map active."""
    import asyncio

    disk_payload = {"session_start_ts": 1_714_329_600, "legs": [], "area_mowed_m2": 0.0}
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.is_active()
    # When legs is empty on disk, restore falls back to [[]] so live_map has
    # at least one leg ready for incoming telemetry.
    assert coord.live_map.legs == [[]]
    assert coord.data.session_active is True


# ---- _persist_in_progress ----

def test_persist_in_progress_writes_when_dirty():
    """_persist_in_progress calls write_in_progress when active and dirty."""
    import asyncio

    legs = [[(1.0, 2.0), (3.0, 4.0)]]
    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_legs=legs,
        live_map_dirty=True,
        area_mowed_m2=25.0,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_called_once()
    written_payload = coord.session_archive.write_in_progress.call_args[0][0]
    assert written_payload["session_start_ts"] == 1_714_329_600
    assert written_payload["area_mowed_m2"] == 25.0
    # legs serialised as list of list of [x, y] pairs
    assert written_payload["legs"] == [[[1.0, 2.0], [3.0, 4.0]]]
    # Dirty flag cleared after successful write.
    assert coord._live_map_dirty is False


def test_persist_in_progress_skips_when_not_dirty():
    """_persist_in_progress does NOT write when dirty flag is False."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_dirty=False,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_not_called()
    # Dirty flag stays False.
    assert coord._live_map_dirty is False


def test_persist_in_progress_skips_when_session_not_active():
    """_persist_in_progress is a no-op when live_map.is_active() is False."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=None,  # not active
        live_map_dirty=True,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_not_called()


def test_persist_in_progress_does_not_clear_dirty_on_exception():
    """When write_in_progress raises, dirty flag remains True for next retry."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_dirty=True,
        write_in_progress_side_effect=OSError("disk full"),
    )

    asyncio.run(coord._persist_in_progress())

    # Write was attempted.
    coord.session_archive.write_in_progress.assert_called_once()
    # But dirty flag was NOT cleared (so next tick retries).
    assert coord._live_map_dirty is True


def test_on_state_update_sets_dirty_flag_on_new_point():
    """_on_state_update sets _live_map_dirty when a new point is appended."""
    import base64

    coord = _make_coordinator_for_session_tests()
    coord._live_map_dirty = False

    # Start a session.
    now = 1_714_329_600
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Feed a telemetry blob carrying a new position.
    blob = _make_s1p4_frame_33b(x_m=2.0, y_m=3.0)
    value = base64.b64encode(blob).decode("ascii")
    state_with_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    assert state_with_pos != coord.data  # position actually changed

    coord._on_state_update(state_with_pos, now + 30)

    # A point was added — dirty flag should be set.
    assert coord._live_map_dirty is True


def test_on_state_update_does_not_set_dirty_when_point_deduped():
    """_live_map_dirty is not set when append_point dedupes (no new point added)."""
    import base64

    coord = _make_coordinator_for_session_tests()
    coord._live_map_dirty = False

    now = 1_714_329_600
    # Start session + add one real point.
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    blob = _make_s1p4_frame_33b(x_m=2.0, y_m=3.0)
    value = base64.b64encode(blob).decode("ascii")
    state_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    coord.data = coord._on_state_update(state_pos, now + 10)
    # Reset dirty after first real point.
    coord._live_map_dirty = False

    # Send the same (almost identical) position — dedup kicks in (< 20cm).
    blob2 = _make_s1p4_frame_33b(x_m=2.01, y_m=3.01)  # 14cm from first point
    value2 = base64.b64encode(blob2).decode("ascii")
    state_pos2 = apply_property_to_state(coord.data, siid=1, piid=4, value=value2)
    # state_pos2 differs from coord.data (position changed slightly) so
    # _on_state_update's "something changed" guard passes, but append_point
    # dedup should skip the point.
    coord._on_state_update(state_pos2, now + 20)

    # Dirty should NOT be set — the dedup ate the point.
    assert coord._live_map_dirty is False


# ---------------------------------------------------------------------------
# F5.8.1 — _refresh_map routes to render_with_trail / render_base_map
# ---------------------------------------------------------------------------


def _make_coordinator_for_refresh_map_tests(
    live_map_active: bool = False,
    live_map_legs: list | None = None,
    last_map_md5: str | None = None,
):
    """Minimal coordinator stub for _refresh_map routing tests.

    Sets up:
    - A fake cloud client whose fetch_map returns a parsed-compatible payload.
    - A real LiveMapState (optionally started).
    - hass.async_add_executor_job that runs fns synchronously (no threads).
    - async_set_updated_data that updates coord.data.
    """
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._live_map_dirty = False
    coord._last_map_md5 = last_map_md5
    coord.cached_map_png = None

    if live_map_active:
        coord.live_map.begin_session(1_714_329_600)
        if live_map_legs:
            coord.live_map.legs = live_map_legs

    # Fake cloud client — fetch_map returns a copy of _MINIMAL_MAP.
    import copy
    cloud_mock = MagicMock()
    cloud_mock.fetch_map.return_value = copy.deepcopy(_MINIMAL_MAP)
    coord._cloud = cloud_mock

    # hass — runs executor jobs synchronously.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


def test_refresh_map_calls_render_base_map_when_live_map_inactive():
    """When live_map is inactive, _refresh_map uses render_base_map (not render_with_trail).

    The functions are imported inside _refresh_map, so we patch them at
    the map_render module level where the import resolves.
    """
    import asyncio
    from unittest.mock import patch

    coord = _make_coordinator_for_refresh_map_tests(live_map_active=False)

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_trail, patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base:
        asyncio.run(coord._refresh_map())

        mock_base.assert_called_once()
        mock_trail.assert_not_called()

    # cached_map_png should be set.
    assert coord.cached_map_png is not None


def test_refresh_map_calls_render_with_trail_when_live_map_active():
    """When live_map is active, _refresh_map uses render_with_trail."""
    import asyncio
    from unittest.mock import patch

    legs = [[(1.0, 1.0), (2.0, 1.0)]]
    coord = _make_coordinator_for_refresh_map_tests(
        live_map_active=True,
        live_map_legs=legs,
    )

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_trail, patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base:
        asyncio.run(coord._refresh_map())

        mock_trail.assert_called_once()
        mock_base.assert_not_called()

    # cached_map_png should be set.
    assert coord.cached_map_png is not None


def test_refresh_map_base_map_skips_if_md5_unchanged():
    """When live_map is inactive and md5 matches the last render, no re-render occurs."""
    import asyncio
    from unittest.mock import patch

    # First pass: get the real md5 by parsing _MINIMAL_MAP
    from custom_components.dreame_a2_mower.map_decoder import parse_cloud_map
    from tests.integration.test_map_decoder import _MINIMAL_MAP
    import copy
    md = parse_cloud_map(copy.deepcopy(_MINIMAL_MAP))
    assert md is not None

    coord = _make_coordinator_for_refresh_map_tests(
        live_map_active=False,
        last_map_md5=md.md5,  # already have this md5
    )

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base:
        asyncio.run(coord._refresh_map())
        # md5 matches — no re-render.
        mock_base.assert_not_called()

    # cached_map_png still None (no render happened).
    assert coord.cached_map_png is None


def test_refresh_map_trail_always_rerenders_even_if_md5_unchanged():
    """When live_map is active, _refresh_map re-renders regardless of md5 match.

    The trail changes with every new telemetry point even if the base map
    hasn't changed, so we skip the md5 dedup when the session is active.
    """
    import asyncio
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.map_decoder import parse_cloud_map
    from tests.integration.test_map_decoder import _MINIMAL_MAP
    import copy
    md = parse_cloud_map(copy.deepcopy(_MINIMAL_MAP))
    assert md is not None

    legs = [[(1.0, 1.0), (2.0, 1.0)]]
    coord = _make_coordinator_for_refresh_map_tests(
        live_map_active=True,
        live_map_legs=legs,
        last_map_md5=md.md5,  # same md5 — but trail is active
    )

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_trail:
        asyncio.run(coord._refresh_map())
        # Should have called render_with_trail despite md5 match.
        mock_trail.assert_called_once()

    assert coord.cached_map_png is not None


# ---------------------------------------------------------------------------
# F5.9.1 — replay_session
# ---------------------------------------------------------------------------


def _make_coordinator_for_replay_tests(
    sessions: list | None = None,
    load_return: dict | None = None,
    fetch_map_return=None,
    last_map_md5: str | None = "old-md5",
):
    """Minimal coordinator stub for replay_session tests.

    ``sessions`` is the list returned by session_archive.list_sessions().
    ``load_return`` is what session_archive.load() returns for any entry.
    ``fetch_map_return`` is what cloud.fetch_map() returns.
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._live_map_dirty = False
    coord._last_map_md5 = last_map_md5
    coord.cached_map_png = None

    # Mock archive.
    archive = MagicMock(spec=SessionArchive)
    archive.list_sessions.return_value = sessions if sessions is not None else []
    archive.load.return_value = load_return
    coord.session_archive = archive

    # Mock cloud.
    cloud = MagicMock()
    cloud.fetch_map.return_value = fetch_map_return
    coord._cloud = cloud

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


# Minimal session-summary JSON that parse_session_summary can consume,
# with a simple 3-point track (no break markers).
_REPLAY_SUMMARY_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "replay-md5",
    "areas": 80.0,
    "map_area": 4000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "obstacle": [],
    "trajectory": [],
    "map": [
        {
            "id": 0,
            "type": 0,  # BoundaryLayer
            "name": "Main Lawn",
            "area": 80.0,
            "etime": 0,
            "time": 60,
            "data": [
                [0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0],
            ],
            "track": [
                [100, 100], [200, 200], [300, 300],
            ],
        }
    ],
}


def test_replay_session_unknown_md5_returns_early():
    """replay_session with an unknown md5 logs a warning and returns without rendering."""
    import asyncio
    from unittest.mock import patch

    coord = _make_coordinator_for_replay_tests(sessions=[])

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
    ) as mock_trail:
        asyncio.run(coord.replay_session("does-not-exist"))
        mock_trail.assert_not_called()

    assert coord.cached_map_png is None


def test_replay_session_load_failure_returns_early():
    """replay_session aborts when archive.load() returns None."""
    import asyncio
    from unittest.mock import patch, MagicMock

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession

    entry = ArchivedSession(
        filename="session_abc.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="abc123",
    )
    coord = _make_coordinator_for_replay_tests(sessions=[entry], load_return=None)

    with patch("custom_components.dreame_a2_mower.map_render.render_with_trail") as mock_trail:
        asyncio.run(coord.replay_session("abc123"))
        mock_trail.assert_not_called()

    assert coord.cached_map_png is None


def test_replay_session_renders_archived_trail():
    """Happy-path replay_session fetches the archived path and renders it.

    Verifies:
    - render_with_trail is called once with map_data and the parsed legs.
    - cached_map_png is populated with the returned PNG bytes.
    - _last_map_md5 is cleared (so the next _refresh_map re-renders).
    """
    import asyncio
    import copy
    from unittest.mock import patch, MagicMock

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=fake_png,
    ) as mock_trail:
        asyncio.run(coord.replay_session("replay-md5"))

        mock_trail.assert_called_once()
        # First positional arg is map_data, second is legs.
        call_legs = mock_trail.call_args[0][1]
        # The summary has 3 track points in one segment.
        assert isinstance(call_legs, list)
        assert len(call_legs) == 1
        assert len(call_legs[0]) == 3

    assert coord.cached_map_png == fake_png
    # md5 cache invalidated so next _refresh_map re-renders unconditionally.
    assert coord._last_map_md5 is None


def test_replay_session_no_cloud_returns_early():
    """replay_session aborts gracefully when _cloud is not set (pre-init)."""
    import asyncio
    import copy

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),
    )
    # Remove _cloud to simulate pre-init state.
    del coord._cloud

    from unittest.mock import patch
    with patch("custom_components.dreame_a2_mower.map_render.render_with_trail") as mock_trail:
        asyncio.run(coord.replay_session("replay-md5"))
        mock_trail.assert_not_called()

    assert coord.cached_map_png is None


# Session-summary JSON with 7 obstacles (mirroring the 2026-04-18 fixture).
# Points are in cm on the wire; parse_session_summary converts to metres.
_REPLAY_SUMMARY_WITH_OBSTACLES_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "obs-md5",
    "areas": 80.0,
    "map_area": 4000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "trajectory": [],
    "obstacle": [
        {"id": 1, "type": 0, "data": [[-110, 1163], [-145, 1173], [-190, 1228], [-195, 1298], [-150, 1358], [-80, 1363], [-10, 1318], [9, 1248], [-35, 1188]]},
        {"id": 2, "type": 0, "data": [[200, 300], [250, 310], [260, 360], [210, 380], [170, 350], [175, 305]]},
        {"id": 3, "type": 0, "data": [[500, 600], [550, 610], [560, 660], [510, 680], [470, 650], [475, 605]]},
        {"id": 4, "type": 0, "data": [[100, 100], [150, 110], [160, 160], [110, 180], [70, 150], [75, 105]]},
        {"id": 5, "type": 0, "data": [[-300, 400], [-250, 410], [-240, 460], [-290, 480], [-330, 450], [-325, 405]]},
        {"id": 6, "type": 0, "data": [[700, 200], [750, 210], [760, 260], [710, 280], [670, 250], [675, 205]]},
        {"id": 7, "type": 0, "data": [[-500, -200], [-450, -190], [-440, -140], [-490, -120], [-530, -150], [-525, -195]]},
    ],
    "map": [
        {
            "id": 0,
            "type": 0,  # BoundaryLayer
            "name": "Main Lawn",
            "area": 80.0,
            "etime": 0,
            "time": 60,
            "data": [
                [0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0],
            ],
            "track": [
                [100, 100], [200, 200], [300, 300],
            ],
        }
    ],
}


def test_replay_session_passes_obstacles_to_renderer():
    """replay_session should extract Obstacle.polygon tuples and pass
    them to render_with_trail under the obstacle_polygons_m kwarg."""
    import asyncio
    import copy
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_obs.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="obs-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_WITH_OBSTACLES_JSON),
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    captured: dict = {}

    def fake_render(map_data, legs, *args, **kwargs):
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        side_effect=fake_render,
    ):
        asyncio.run(coord.replay_session("obs-md5"))

    polys = captured.get("kwargs", {}).get("obstacle_polygons_m")
    assert polys is not None, "replay_session must pass obstacle_polygons_m"
    assert len(polys) == 7, f"fixture has 7 obstacle polygons, got {len(polys)}"
    # Each polygon is a list/tuple of (x_m, y_m) pairs in metres.
    for poly in polys:
        assert len(poly) >= 3, "each polygon must have >= 3 points"
        for x, y in poly:
            assert isinstance(x, float), f"x must be float, got {type(x)}"
            assert isinstance(y, float), f"y must be float, got {type(y)}"
    # Spot-check: first obstacle first point is [-110cm, 1163cm] => [-1.1m, 11.63m].
    assert abs(polys[0][0][0] - (-1.1)) < 1e-9
    assert abs(polys[0][0][1] - 11.63) < 1e-9


def test_replay_session_with_no_obstacles_passes_empty_list():
    """A session with zero obstacles still passes an empty list (not
    None) to the renderer so the overlay branch is consistent."""
    import asyncio
    import copy
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),  # obstacle: []
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    captured: dict = {}

    def fake_render(map_data, legs, *args, **kwargs):
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        side_effect=fake_render,
    ):
        asyncio.run(coord.replay_session("replay-md5"))

    polys = captured.get("kwargs", {}).get("obstacle_polygons_m")
    assert polys == [], f"expected empty list for no obstacles, got {polys!r}"


# ---------------------------------------------------------------------------
# F5.10.1 — DreameA2FinalizeSessionButton entity tests
# ---------------------------------------------------------------------------


def test_finalize_session_button_async_press_dispatches_action():
    """async_press() calls coordinator.dispatch_action(FINALIZE_SESSION)."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock

    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    # Build a minimal coordinator mock.
    coord = MagicMock()
    coord.dispatch_action = AsyncMock()
    # entry.entry_id is used for unique_id.
    coord.entry = MagicMock()
    coord.entry.entry_id = "test-entry-id"
    # _cloud may be None; the entity reads device_id / model from it.
    coord._cloud = None

    button = DreameA2FinalizeSessionButton.__new__(DreameA2FinalizeSessionButton)
    # Manually set attributes that __init__ would set (bypass CoordinatorEntity).
    button.coordinator = coord
    button._attr_unique_id = f"{coord.entry.entry_id}_finalize_session"

    asyncio.run(button.async_press())

    coord.dispatch_action.assert_awaited_once_with(MowerAction.FINALIZE_SESSION, {})


def test_finalize_session_button_lives_in_main_controls():
    """v1.0.0a27: Finalize joins Start/Pause/Stop/Recharge in the main
    controls section (no entity_category), so all five mow-control
    buttons cluster together on the device page."""
    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton

    assert getattr(DreameA2FinalizeSessionButton, "_attr_entity_category", None) is None


def test_finalize_session_button_unique_id_uses_entry_id():
    """unique_id is stable: {entry_id}_finalize_session."""
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton

    coord = MagicMock()
    coord.entry.entry_id = "abc-123"
    coord._cloud = None

    # Bypass super().__init__ to avoid HA coordinator plumbing.
    button = DreameA2FinalizeSessionButton.__new__(DreameA2FinalizeSessionButton)
    button.coordinator = coord
    button._attr_unique_id = f"{coord.entry.entry_id}_finalize_session"

    assert button._attr_unique_id == "abc-123_finalize_session"


# ---------------------------------------------------------------------------
# F6.2.1: novelty registry wiring
# ---------------------------------------------------------------------------


def test_unknown_siid_piid_triggers_property_novelty():
    """A property push with an unmapped (siid, piid) pair adds a
    'property' observation to the registry exactly once."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    coord.handle_property_push(siid=99, piid=42, value=7)
    coord.handle_property_push(siid=99, piid=42, value=8)  # dupe

    obs = coord.novel_registry.snapshot().observations
    property_obs = [o for o in obs if o.category == "property"]
    assert len(property_obs) == 1, f"expected 1 property obs, got {len(property_obs)}"
    assert property_obs[0].detail == "siid=99 piid=42"


def test_known_siid_piid_with_novel_value_triggers_value_novelty():
    """A property push with a mapped (siid, piid) but never-before-seen
    value adds a 'value' observation."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    # s2.2 (error_code) is in PROPERTY_MAPPING. Use a novel value.
    coord.handle_property_push(siid=2, piid=2, value=999)
    coord.handle_property_push(siid=2, piid=2, value=999)  # dupe

    value_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "value"
    ]
    assert len(value_obs) == 1
    assert "siid=2 piid=2" in value_obs[0].detail
    assert "value=999" in value_obs[0].detail
    # And no property novelty fired — slot is mapped.
    property_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "property"
    ]
    assert property_obs == []


# ---------------------------------------------------------------------------
# F6.4.1: session_summary novel-key detection
# ---------------------------------------------------------------------------


def test_do_oss_fetch_novel_key_logs_and_records(monkeypatch, caplog):
    """An OSS session_summary fetch where the JSON contains a key not in
    SCHEMA_SESSION_SUMMARY logs [NOVEL_KEY/session_summary] WARNING once
    and adds a 'key' observation to the registry."""
    import json

    # Build a payload that is valid for parse_session_summary AND contains
    # a key SCHEMA_SESSION_SUMMARY does not list.
    payload = dict(_MINIMAL_SUMMARY_JSON)
    payload["weird_field"] = 42
    raw_bytes = json.dumps(payload).encode()

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/abc.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )

    with caplog.at_level("WARNING"):
        asyncio.run(coord._do_oss_fetch(1_700_000_000))
        # Run a SECOND time — dupe should not log again.
        # Reset pending so the second fetch proceeds too.
        coord.data = MowerState(
            pending_session_object_name="d/sessions/abc.json",
            pending_session_first_event_unix=1_700_000_000,
            pending_session_attempt_count=0,
        )
        asyncio.run(coord._do_oss_fetch(1_700_000_005))

    novel = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "key"
    ]
    novel_details = [o.detail for o in novel]
    assert "session_summary.weird_field" in novel_details, (
        f"expected 'session_summary.weird_field' in key observations, got: {novel_details}"
    )

    warns = [r for r in caplog.records if "[NOVEL_KEY/session_summary]" in r.getMessage()]
    assert len(warns) >= 1, f"expected at least 1 NOVEL_KEY warning, got {len(warns)}"

    # Second run produced no additional key observations (gate held).
    key_obs_after_run1 = len(novel)
    # All the weird_field warnings should be exactly 1 (once per process).
    weird_warns = [r for r in warns if "weird_field" in r.getMessage()]
    assert len(weird_warns) == 1, f"expected exactly 1 weird_field warning, got {len(weird_warns)}"


# ---------------------------------------------------------------------------
# F6.5.1: novel_observations sensor
# ---------------------------------------------------------------------------


def test_novel_observations_sensor_value_fn_returns_count():
    from custom_components.dreame_a2_mower.sensor import (
        DIAGNOSTIC_SENSORS,
    )
    from custom_components.dreame_a2_mower.observability import (
        NovelObservationRegistry,
    )

    reg = NovelObservationRegistry()
    reg.record_property(siid=99, piid=42, now_unix=1700000000)
    reg.record_value(siid=2, piid=2, value=999, now_unix=1700000005)
    reg.record_key(namespace="session_summary", key="weird", now_unix=1700000010)

    coord_like = type("C", (), {"novel_registry": reg})()
    descs = [d for d in DIAGNOSTIC_SENSORS if d.key == "novel_observations"]
    assert len(descs) == 1
    desc = descs[0]
    assert desc.value_fn(coord_like) == 3


def test_novel_observations_sensor_attrs_lists_observations():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    from custom_components.dreame_a2_mower.observability import (
        NovelObservationRegistry,
    )
    from homeassistant.helpers.entity import EntityCategory

    reg = NovelObservationRegistry()
    reg.record_property(siid=99, piid=42, now_unix=1700000000)
    coord_like = type("C", (), {"novel_registry": reg})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "novel_observations")
    attrs = desc.extra_state_attributes_fn(coord_like)
    assert "observations" in attrs
    assert len(attrs["observations"]) == 1
    sample = attrs["observations"][0]
    assert set(sample.keys()) == {"category", "detail", "first_seen_unix"}
    assert sample["category"] == "property"
    assert sample["detail"] == "siid=99 piid=42"
    assert sample["first_seen_unix"] == 1700000000
    assert desc.entity_category is EntityCategory.DIAGNOSTIC


# ---------------------------------------------------------------------------
# F6.7.1: data_freshness sensor
# ---------------------------------------------------------------------------


def test_data_freshness_sensor_native_value_is_age_of_oldest_field():
    """Single-number 'how stale is the integration overall?' reading.
    Equals age of the oldest stamp."""
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    from custom_components.dreame_a2_mower.observability import FreshnessTracker
    from unittest.mock import patch

    tracker = FreshnessTracker()
    tracker._last_updated = {
        "battery_level": 1700000000,  # oldest, age=20
        "state": 1700000005,           # age=15
        "position_x_m": 1700000010,    # age=10
    }
    coord_like = type("C", (), {"freshness": tracker})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "data_freshness")
    with patch("custom_components.dreame_a2_mower.sensor.time.time", return_value=1700000020):
        value = desc.value_fn(coord_like)
    assert value == 20


def test_data_freshness_sensor_attrs_per_field_ages():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    from custom_components.dreame_a2_mower.observability import FreshnessTracker
    from unittest.mock import patch

    tracker = FreshnessTracker()
    tracker._last_updated = {
        "battery_level": 1700000000,
        "state": 1700000005,
    }
    coord_like = type("C", (), {"freshness": tracker})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "data_freshness")
    with patch("custom_components.dreame_a2_mower.sensor.time.time", return_value=1700000020):
        attrs = desc.extra_state_attributes_fn(coord_like)
    assert attrs == {"battery_level_age_s": 20, "state_age_s": 15}


def test_data_freshness_sensor_returns_none_when_no_tracked_fields():
    """Before any state mutation, snapshot is empty — native_value should
    be None (not 0, which would falsely imply 'just updated')."""
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    from custom_components.dreame_a2_mower.observability import FreshnessTracker

    tracker = FreshnessTracker()
    coord_like = type("C", (), {"freshness": tracker})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "data_freshness")
    assert desc.value_fn(coord_like) is None


# ---------------------------------------------------------------------------
# F6.8.1: cloud endpoint_log + api_endpoints_supported sensor
# ---------------------------------------------------------------------------


def test_cloud_routed_action_records_accepted():
    """A successful routed_action records 'accepted' for that op."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    # Build a barebones client without invoking the real __init__.
    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    # Simulate self.action returning a non-None result (success).
    with patch.object(client, "action", return_value={"ok": True}):
        client.routed_action(op=100)

    assert client.endpoint_log["routed_action_op=100"] == "accepted"


def test_cloud_routed_action_records_80001():
    """When self.action returns None AND _last_send_error_code is 80001,
    the endpoint is marked rejected_80001."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = 80001
        return None

    with patch.object(client, "action", side_effect=_fake_action):
        client.routed_action(op=999)

    assert client.endpoint_log["routed_action_op=999"] == "rejected_80001"


def test_cloud_routed_action_records_error_for_other_failures():
    """Any non-80001 failure (None return + other error code) is logged
    as 'error'."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = -7  # arbitrary non-80001 code
        return None

    with patch.object(client, "action", side_effect=_fake_action):
        client.routed_action(op=42)

    assert client.endpoint_log["routed_action_op=42"] == "error"


def test_api_endpoints_supported_sensor_value_fn_counts_accepted():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    cloud_like = type("Cloud", (), {"endpoint_log": {
        "routed_action_op=100": "accepted",
        "routed_action_op=101": "accepted",
        "routed_action_op=999": "rejected_80001",
        "routed_action_op=42": "error",
    }})()
    coord_like = type("C", (), {"_cloud": cloud_like})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    assert desc.value_fn(coord_like) == 2


def test_api_endpoints_supported_sensor_attrs_buckets_by_outcome():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    cloud_like = type("Cloud", (), {"endpoint_log": {
        "routed_action_op=100": "accepted",
        "routed_action_op=999": "rejected_80001",
        "routed_action_op=42": "error",
    }})()
    coord_like = type("C", (), {"_cloud": cloud_like})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    attrs = desc.extra_state_attributes_fn(coord_like)
    assert attrs == {
        "accepted": ["routed_action_op=100"],
        "rejected_80001": ["routed_action_op=999"],
        "error": ["routed_action_op=42"],
    }


def test_api_endpoints_supported_sensor_handles_no_cloud_yet():
    """Before the cloud client is connected, _cloud is None — sensor
    should return 0 / empty attrs rather than crash."""
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    coord_like = type("C", (), {"_cloud": None})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    assert desc.value_fn(coord_like) == 0
    assert desc.extra_state_attributes_fn(coord_like) == {
        "accepted": [], "rejected_80001": [], "error": [],
    }


def test_apply_lidar_object_name_property_updates_state():
    """F7.2.1: dispatching (99, 20) writes latest_lidar_object_name."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.mower.state import MowerState

    state = MowerState()
    new = apply_property_to_state(state, 99, 20, "dreame/lidar/abcdef.pcd")
    assert new.latest_lidar_object_name == "dreame/lidar/abcdef.pcd"
    # Round-trip with same value yields equal state (no spurious change).
    same = apply_property_to_state(new, 99, 20, "dreame/lidar/abcdef.pcd")
    assert same == new


# ---------------------------------------------------------------------------
# F7.2.2: LiDAR scan fetch on s99p20
# ---------------------------------------------------------------------------


def test_lidar_object_name_change_triggers_fetch_and_archive(tmp_path):
    """A new latest_lidar_object_name causes _handle_lidar_object_name
    to fetch the OSS blob, dedup by md5, and write to the archive."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    coord.lidar_archive = LidarArchive(tmp_path / "lidar")
    coord._last_lidar_object_name = None
    coord.data = MowerState()

    fake_pcd = b"# .PCD v0.7\nDUMMY-LIDAR-PAYLOAD"

    def _fake_url(_obj_name):
        return "https://example/abc.pcd"

    def _fake_get(_url):
        return fake_pcd

    coord._cloud.get_interim_file_url = _fake_url
    coord._cloud.get_file = _fake_get

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    async def _run():
        await coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000000)
        # Same object_name again — should be skipped (idempotent guard).
        await coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000005)

    asyncio.run(_run())

    assert coord.lidar_archive.count == 1
    latest = coord.lidar_archive.latest()
    assert latest is not None
    assert latest.object_name == "dreame/lidar/abc.pcd"


def test_lidar_object_name_unchanged_skips_fetch(tmp_path):
    """If _handle_lidar_object_name receives the same object_name as
    last time, no cloud fetch is attempted at all."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    coord.lidar_archive = LidarArchive(tmp_path / "lidar")
    coord._last_lidar_object_name = "dreame/lidar/already.pcd"

    fetch_count = 0

    def _fake_url(_obj_name):
        nonlocal fetch_count
        fetch_count += 1
        return None

    coord._cloud.get_interim_file_url = _fake_url

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    asyncio.run(
        coord._handle_lidar_object_name("dreame/lidar/already.pcd", now_unix=1700000000)
    )
    assert fetch_count == 0


def test_lidar_object_name_handles_url_fetch_failure_gracefully(tmp_path):
    """When get_interim_file_url returns None or raises, log + swallow,
    do not crash."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    coord.lidar_archive = LidarArchive(tmp_path / "lidar")
    coord._last_lidar_object_name = None
    coord.data = MowerState()

    def _fake_url(_obj_name):
        return None

    coord._cloud.get_interim_file_url = _fake_url

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    # Should not raise.
    asyncio.run(
        coord._handle_lidar_object_name("dreame/lidar/sad.pcd", now_unix=1700000000)
    )
    assert coord.lidar_archive.count == 0


# ---------------------------------------------------------------------------
# F7.6.1: show_lidar_fullscreen service
# ---------------------------------------------------------------------------


def test_show_lidar_fullscreen_fires_bus_event():
    """The service handler fires a dreame_a2_mower_lidar_fullscreen
    event on the bus. Lovelace cards listen for it to pop up the
    fullscreen LiDAR view."""
    import asyncio
    from custom_components.dreame_a2_mower.services import (
        _handle_show_lidar_fullscreen,
    )
    from unittest.mock import MagicMock

    hass = MagicMock()
    hass.bus.async_fire = MagicMock()

    call = MagicMock()
    call.hass = hass
    call.data = {}

    asyncio.run(_handle_show_lidar_fullscreen(call))

    hass.bus.async_fire.assert_called_once_with(
        "dreame_a2_mower_lidar_fullscreen", {}
    )


# ---------------------------------------------------------------------------
# F7.fix1: select_first_g2408
# ---------------------------------------------------------------------------


def test_select_first_g2408_picks_dreame_mower_model_and_pins_did():
    """Picks the first dreame.mower.* device, calls _handle_device_info
    so _did + _host get populated for subsequent get_device_info /
    mqtt_host_port calls."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True
    client._strings = None  # _handle_device_info reads strings via _ensure_strings

    devices_payload = {
        "page": {
            "records": [
                {"did": "12345", "model": "dreame.vacuum.r2227", "name": "robovac"},
                {"did": "67890", "model": "dreame.mower.g2408", "name": "the mower"},
            ]
        }
    }

    captured = {}
    def _fake_handle(self, info):
        captured["info"] = info
        self._did = info["did"]
        self._model = info["model"]
        self._host = "fake.mqtt.host:8883"
        self._uid = "fake-uid"

    with patch.object(client, "get_devices", return_value=devices_payload):
        with patch.object(
            DreameA2CloudClient, "_handle_device_info",
            new=_fake_handle,
        ):
            picked = client.select_first_g2408()

    assert picked["did"] == "67890"
    assert picked["model"] == "dreame.mower.g2408"
    assert client._did == "67890"
    assert client._host == "fake.mqtt.host:8883"


def test_select_first_g2408_raises_when_not_logged_in():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = False
    try:
        client.select_first_g2408()
    except ValueError as ex:
        assert "login()" in str(ex)
    else:
        raise AssertionError("expected ValueError")


def test_select_first_g2408_raises_when_no_matching_device():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True

    payload = {
        "page": {
            "records": [
                {"did": "1", "model": "dreame.vacuum.r2227"},
            ]
        }
    }
    with patch.object(client, "get_devices", return_value=payload):
        try:
            client.select_first_g2408()
        except ValueError as ex:
            assert "dreame.mower" in str(ex)
        else:
            raise AssertionError("expected ValueError")


def test_select_first_g2408_raises_on_empty_response():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True

    with patch.object(client, "get_devices", return_value=None):
        try:
            client.select_first_g2408()
        except ValueError as ex:
            assert "no data" in str(ex) or "auth" in str(ex).lower()
        else:
            raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# v1.0.0a4 regressions: blob-list payload + novelty noise on blob slots
# ---------------------------------------------------------------------------


def test_apply_s1p1_accepts_list_payload():
    """g2408 over MQTT delivers s1.1 as a JSON-list of ints, not bytes
    or base64. The blob applier must accept lists (Python list of int)."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.mower.state import MowerState

    state = MowerState()
    # Realistic 20-byte heartbeat blob shape (all-zeros except the
    # battery-temp byte at offset 6).
    blob_list = [0] * 20
    blob_list[6] = 1  # battery_temp_low bit set
    new = apply_property_to_state(state, 1, 1, blob_list)
    # battery_temp_low should now be set (or at least decode shouldn't crash).
    # The exact decoded value depends on the heartbeat schema, but the
    # state should change in some way (or stay equal if the blob is
    # all-default). Most importantly: no exception.
    assert isinstance(new, MowerState)


def test_apply_s1p4_accepts_list_payload():
    """Same coercion path for s1.4 telemetry."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.mower.state import MowerState

    state = MowerState()
    # 8-byte BEACON frame so position-only decode applies.
    blob_list = [0, 0, 1, 0, 0, 0, 1, 0]
    new = apply_property_to_state(state, 1, 4, blob_list)
    assert isinstance(new, MowerState)


def test_blob_slots_do_not_trigger_novelty_noise(tmp_path):
    """s1.1 / s1.4 / s2.51 must NOT log [NOVEL/property] or [NOVEL/value]
    on every push — they're dispatched via dedicated blob handlers."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    # Two pushes for each blob slot.
    blob_list = [0] * 20
    coord.handle_property_push(siid=1, piid=1, value=blob_list)
    coord.handle_property_push(siid=1, piid=1, value=blob_list)

    # The novel-registry must contain ZERO entries for blob slots —
    # the slots are known, but their per-tick blob bytes don't go
    # through the value-novelty path.
    obs = coord.novel_registry.snapshot().observations
    blob_obs = [
        o for o in obs
        if "siid=1 piid=1" in o.detail or "siid=1 piid=4" in o.detail or "siid=2 piid=51" in o.detail
    ]
    assert blob_obs == [], f"Expected no novelty observations for blob slots, got: {blob_obs}"
