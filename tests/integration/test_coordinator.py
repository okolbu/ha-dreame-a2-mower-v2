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


def test_s1p4_blob_updates_position_area_distance_phase():
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
    assert abs(new_state.total_distance_m - 345.0) < 0.001


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
