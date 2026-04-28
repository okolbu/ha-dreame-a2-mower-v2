"""Tests for s2p51 multiplexed config decoder."""

from __future__ import annotations

import pytest

import json

from custom_components.dreame_a2_mower.protocol.config_s2p51 import (
    Setting,
    S2P51Event,
    S2P51DecodeError,
    decode_s2p51,
    encode_s2p51,
)


def test_decode_timestamp_event_returns_timestamp_kind():
    payload = {"time": "1776415722", "tz": "UTC"}
    ev = decode_s2p51(payload)
    assert ev.setting is Setting.TIMESTAMP
    assert ev.values == {"time": 1776415722, "tz": "UTC"}


def test_decode_ambiguous_toggle_value_one():
    ev = decode_s2p51({"value": 1})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 1}


def test_decode_ambiguous_toggle_value_zero():
    ev = decode_s2p51({"value": 0})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 0}


def test_decode_rejects_malformed_payload():
    with pytest.raises(S2P51DecodeError, match="unknown"):
        decode_s2p51({"nonsense": True})


def test_decode_rejects_empty_payload():
    with pytest.raises(S2P51DecodeError, match="empty"):
        decode_s2p51({})


def test_decode_dnd_event_extracts_start_end_enabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 1})
    assert ev.setting is Setting.DND
    assert ev.values == {"start_min": 1320, "end_min": 420, "enabled": True}


def test_decode_dnd_event_disabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 0})
    assert ev.setting is Setting.DND
    assert ev.values["enabled"] is False


def test_decode_low_speed_nighttime_three_element_list():
    # [enabled, start_min, end_min] — times clearly larger than 1
    ev = decode_s2p51({"value": [1, 1260, 360]})
    assert ev.setting is Setting.LOW_SPEED_NIGHT
    assert ev.values == {"enabled": True, "start_min": 1260, "end_min": 360}


def test_decode_rain_protection_two_element_list():
    # [enabled, resume_hours]
    ev = decode_s2p51({"value": [1, 3]})
    assert ev.setting is Setting.RAIN_PROTECTION
    assert ev.values == {"enabled": True, "resume_hours": 3}


def test_decode_anti_theft_three_element_all_binary():
    # [lift_alarm, offmap_alarm, realtime_location] — all 0 or 1
    ev = decode_s2p51({"value": [1, 0, 1]})
    assert ev.setting is Setting.ANTI_THEFT
    assert ev.values == {
        "lift_alarm": True,
        "offmap_alarm": False,
        "realtime_location": True,
    }


def test_decode_charging_six_element_list():
    # [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]
    ev = decode_s2p51({"value": [15, 95, 0, 0, 0, 0]})
    assert ev.setting is Setting.CHARGING
    assert ev.values == {
        "recharge_pct": 15,
        "resume_pct": 95,
        "unknown_flag": 0,
        "custom_charging": False,
        "start_min": 0,
        "end_min": 0,
    }


def test_decode_led_period_eight_element_list():
    # [enabled, start_min, end_min, standby, working, charging, error, reserved]
    ev = decode_s2p51({"value": [1, 360, 1320, 1, 1, 1, 1, 0]})
    assert ev.setting is Setting.LED_PERIOD
    assert ev.values == {
        "enabled": True,
        "start_min": 360,
        "end_min": 1320,
        "standby": True,
        "working": True,
        "charging": True,
        "error": True,
        "reserved": 0,
    }


def test_decode_four_bool_list_is_ambiguous():
    # Both CFG.MSG_ALERT (Notification Prefs) and CFG.VOICE (Voice
    # Prompt Modes) ride this 4-bool shape with no envelope key to
    # distinguish them. Decoder must surface AMBIGUOUS_4LIST so the
    # caller resolves via CFG diff.
    ev = decode_s2p51({"value": [1, 0, 1, 1]})
    assert ev.setting is Setting.AMBIGUOUS_4LIST
    assert ev.values == {"value": [True, False, True, True]}


def test_encode_rejects_ambiguous_4list():
    ev = S2P51Event(
        setting=Setting.AMBIGUOUS_4LIST,
        values={"value": [True, True, True, True]},
    )
    with pytest.raises(S2P51DecodeError, match="ambiguous"):
        encode_s2p51(ev)


def test_decode_human_presence_nine_element_list():
    # [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]
    # Example from probe log at 2026-04-17 11:13:57: [0,1,1,1,1,1,1,0,3]
    ev = decode_s2p51({"value": [0, 1, 1, 1, 1, 1, 1, 0, 3]})
    assert ev.setting is Setting.HUMAN_PRESENCE_ALERT
    assert ev.values == {
        "enabled": False,
        "sensitivity": 1,
        "standby": True,
        "mowing": True,
        "recharge": True,
        "patrol": True,
        "alert": True,
        "photos": False,
        "push_min": 3,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"time": "1776415722", "tz": "UTC"},
        # skip AMBIGUOUS_TOGGLE — no round trip without naming the setting
        {"end": 420, "start": 1320, "value": 1},
        {"value": [1, 1260, 360]},       # low-speed-night
        {"value": [1, 0, 1]},            # anti-theft
        {"value": [1, 3]},               # rain-protection
        {"value": [15, 95, 0, 0, 0, 0]}, # charging
        {"value": [1, 360, 1320, 1, 1, 1, 1, 0]},  # led-period
        {"value": [0, 1, 1, 1, 1, 1, 1, 0, 3]},    # human-presence
    ],
)
def test_encode_decode_roundtrip_for_identifiable_shapes(payload):
    ev = decode_s2p51(payload)
    reconstructed = encode_s2p51(ev)
    # Re-decode to normalize both sides (key order / bool vs int for value).
    assert decode_s2p51(reconstructed) == ev


def test_encode_rejects_ambiguous_toggle_without_specific_setting():
    # The caller must first promote AMBIGUOUS_TOGGLE to a concrete setting
    # using external context before encoding it back.
    ev = S2P51Event(setting=Setting.AMBIGUOUS_TOGGLE, values={"value": 1})
    with pytest.raises(S2P51DecodeError, match="ambiguous"):
        encode_s2p51(ev)


def test_decode_rejects_malformed_list_element_as_s2p51_error():
    # A non-numeric string where an int is expected should surface as
    # S2P51DecodeError, not raw ValueError.
    with pytest.raises(S2P51DecodeError, match="malformed"):
        decode_s2p51({"value": ["not", "a", "list"]})


def _load_s2p51_samples(fixtures_dir):
    with (fixtures_dir / "s2p51_samples.json").open() as fh:
        return json.load(fh)


def test_all_s2p51_samples_decode_without_error(fixtures_dir):
    """Every real payload collected from the RE session must decode cleanly."""
    samples = _load_s2p51_samples(fixtures_dir)
    assert len(samples) > 0, "expected at least one sample payload"
    for sample in samples:
        ev = decode_s2p51(sample)
        # Every sample must route to a concrete Setting value.
        assert ev.setting in Setting, f"decoded unknown setting for {sample!r}"
