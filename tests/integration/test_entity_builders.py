"""Tests for entity-layer wire-payload builders.

These pure functions are critical because they construct the exact bytes /
values that get sent to the mower firmware.  A bug here would send a
malformed array without any other test catching it.

All builder functions live in:
  - custom_components.dreame_a2_mower.number   (_build_vol, _build_bat_*)
  - custom_components.dreame_a2_mower.switch   (_build_cls, _build_dnd, ...)
  - custom_components.dreame_a2_mower.select   (_build_pre_efficiency,
                                                _build_wrp_resume_hours)

Tests cover:
  1. Smoke test — correct output shape and slot assignment with known state.
  2. Defaults test — sensible values when MowerState fields are None.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import (
    _build_bat_auto_recharge,
    _build_bat_resume,
    _build_vol,
)
from custom_components.dreame_a2_mower.select import (
    _PRE_PAD_DEFAULTS,
    _build_pre_efficiency,
    _build_wrp_resume_hours,
)
from custom_components.dreame_a2_mower.switch import (
    _build_ata_lift,
    _build_ata_offmap,
    _build_ata_realtime,
    _build_bat_custom_charging,
    _build_cls,
    _build_dnd,
    _build_low,
    _build_wrp,
)


# ---------------------------------------------------------------------------
# number.py builders
# ---------------------------------------------------------------------------

class TestBuildVol:
    def test_returns_int(self) -> None:
        state = MowerState(volume_pct=50)
        assert _build_vol(state, 75) == 75

    def test_truncates_float(self) -> None:
        state = MowerState()
        assert _build_vol(state, 33.9) == 33

    def test_zero(self) -> None:
        assert _build_vol(MowerState(), 0) == 0

    def test_100(self) -> None:
        assert _build_vol(MowerState(), 100) == 100


class TestBuildBatAutoRecharge:
    def test_shape(self) -> None:
        state = MowerState(
            auto_recharge_battery_pct=15,
            resume_battery_pct=95,
            custom_charging_enabled=False,
            charging_start_min=0,
            charging_end_min=0,
        )
        result = _build_bat_auto_recharge(state, 25)
        assert len(result) == 6

    def test_slot_0_is_new_value(self) -> None:
        state = MowerState(
            auto_recharge_battery_pct=15,
            resume_battery_pct=95,
            custom_charging_enabled=False,
            charging_start_min=0,
            charging_end_min=0,
        )
        result = _build_bat_auto_recharge(state, 20)
        assert result[0] == 20

    def test_slot_1_is_resume_pct(self) -> None:
        state = MowerState(resume_battery_pct=90, custom_charging_enabled=False,
                           charging_start_min=0, charging_end_min=0)
        result = _build_bat_auto_recharge(state, 15)
        assert result[1] == 90

    def test_slot_2_is_always_1(self) -> None:
        """unknown_flag at index 2 must always be 1 (only observed value)."""
        state = MowerState()
        result = _build_bat_auto_recharge(state, 15)
        assert result[2] == 1

    def test_slot_3_is_custom_charging(self) -> None:
        state = MowerState(custom_charging_enabled=True)
        result = _build_bat_auto_recharge(state, 15)
        assert result[3] == 1

    def test_slot_4_5_are_charging_window(self) -> None:
        state = MowerState(charging_start_min=480, charging_end_min=960)
        result = _build_bat_auto_recharge(state, 15)
        assert result[4] == 480
        assert result[5] == 960

    def test_none_defaults_resume(self) -> None:
        """resume_battery_pct None → defaults to 95."""
        result = _build_bat_auto_recharge(MowerState(), 15)
        assert result[1] == 95

    def test_none_defaults_custom_charging_off(self) -> None:
        result = _build_bat_auto_recharge(MowerState(), 15)
        assert result[3] == 0

    def test_none_defaults_charging_window_zero(self) -> None:
        result = _build_bat_auto_recharge(MowerState(), 15)
        assert result[4] == 0
        assert result[5] == 0


class TestBuildBatResume:
    def test_shape(self) -> None:
        result = _build_bat_resume(MowerState(), 95)
        assert len(result) == 6

    def test_slot_1_is_new_value(self) -> None:
        state = MowerState(auto_recharge_battery_pct=15)
        result = _build_bat_resume(state, 80)
        assert result[1] == 80

    def test_slot_0_is_auto_recharge(self) -> None:
        state = MowerState(auto_recharge_battery_pct=20)
        result = _build_bat_resume(state, 95)
        assert result[0] == 20

    def test_slot_2_is_always_1(self) -> None:
        result = _build_bat_resume(MowerState(), 95)
        assert result[2] == 1

    def test_none_defaults_auto_recharge(self) -> None:
        """auto_recharge_battery_pct None → defaults to 15."""
        result = _build_bat_resume(MowerState(), 95)
        assert result[0] == 15


# ---------------------------------------------------------------------------
# switch.py builders
# ---------------------------------------------------------------------------

class TestBuildCls:
    def test_true_gives_1(self) -> None:
        assert _build_cls(MowerState(), True) == 1

    def test_false_gives_0(self) -> None:
        assert _build_cls(MowerState(), False) == 0


class TestBuildDnd:
    def test_shape(self) -> None:
        result = _build_dnd(MowerState(), True)
        assert len(result) == 3

    def test_slot_0_is_enabled(self) -> None:
        assert _build_dnd(MowerState(), True)[0] == 1
        assert _build_dnd(MowerState(), False)[0] == 0

    def test_slot_1_is_start_min(self) -> None:
        state = MowerState(dnd_start_min=1320)
        assert _build_dnd(state, True)[1] == 1320

    def test_slot_2_is_end_min(self) -> None:
        state = MowerState(dnd_end_min=360)
        assert _build_dnd(state, True)[2] == 360

    def test_none_defaults_start(self) -> None:
        """dnd_start_min None → factory default 1200 (20:00)."""
        assert _build_dnd(MowerState(), True)[1] == 1200

    def test_none_defaults_end(self) -> None:
        """dnd_end_min None → factory default 480 (08:00)."""
        assert _build_dnd(MowerState(), True)[2] == 480


class TestBuildWrp:
    def test_shape(self) -> None:
        result = _build_wrp(MowerState(), True)
        assert len(result) == 2

    def test_slot_0_is_enabled(self) -> None:
        assert _build_wrp(MowerState(), True)[0] == 1
        assert _build_wrp(MowerState(), False)[0] == 0

    def test_slot_1_is_resume_hours(self) -> None:
        state = MowerState(rain_protection_resume_hours=4)
        assert _build_wrp(state, True)[1] == 4

    def test_none_defaults_resume_hours(self) -> None:
        """rain_protection_resume_hours None → 0 (don't auto-resume)."""
        assert _build_wrp(MowerState(), True)[1] == 0


class TestBuildLow:
    def test_shape(self) -> None:
        result = _build_low(MowerState(), True)
        assert len(result) == 3

    def test_slot_0_is_enabled(self) -> None:
        assert _build_low(MowerState(), True)[0] == 1
        assert _build_low(MowerState(), False)[0] == 0

    def test_slot_1_is_start_min(self) -> None:
        state = MowerState(low_speed_at_night_start_min=1320)
        assert _build_low(state, True)[1] == 1320

    def test_slot_2_is_end_min(self) -> None:
        state = MowerState(low_speed_at_night_end_min=360)
        assert _build_low(state, True)[2] == 360

    def test_none_defaults_start(self) -> None:
        assert _build_low(MowerState(), True)[1] == 1200

    def test_none_defaults_end(self) -> None:
        assert _build_low(MowerState(), True)[2] == 480


class TestBuildBatCustomCharging:
    def test_shape(self) -> None:
        result = _build_bat_custom_charging(MowerState(), True)
        assert len(result) == 6

    def test_slot_3_is_new_value(self) -> None:
        assert _build_bat_custom_charging(MowerState(), True)[3] == 1
        assert _build_bat_custom_charging(MowerState(), False)[3] == 0

    def test_slot_2_is_always_1(self) -> None:
        """unknown_flag hard-coded to 1 (same as number.py builders)."""
        assert _build_bat_custom_charging(MowerState(), True)[2] == 1

    def test_slot_0_is_auto_recharge(self) -> None:
        state = MowerState(auto_recharge_battery_pct=20)
        assert _build_bat_custom_charging(state, False)[0] == 20

    def test_slot_1_is_resume_pct(self) -> None:
        state = MowerState(resume_battery_pct=90)
        assert _build_bat_custom_charging(state, False)[1] == 90

    def test_slot_4_5_are_charging_window(self) -> None:
        state = MowerState(charging_start_min=480, charging_end_min=960)
        result = _build_bat_custom_charging(state, True)
        assert result[4] == 480
        assert result[5] == 960

    def test_none_defaults(self) -> None:
        result = _build_bat_custom_charging(MowerState(), False)
        assert result[0] == 15  # auto_recharge default
        assert result[1] == 95  # resume default
        assert result[4] == 0
        assert result[5] == 0


class TestBuildAtaLift:
    def test_shape(self) -> None:
        result = _build_ata_lift(MowerState(), True)
        assert len(result) == 3

    def test_slot_0_is_new_value(self) -> None:
        assert _build_ata_lift(MowerState(), True)[0] == 1
        assert _build_ata_lift(MowerState(), False)[0] == 0

    def test_slot_1_is_offmap(self) -> None:
        state = MowerState(anti_theft_offmap_alarm=True)
        assert _build_ata_lift(state, False)[1] == 1

    def test_slot_2_is_realtime(self) -> None:
        state = MowerState(anti_theft_realtime_location=True)
        assert _build_ata_lift(state, False)[2] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_lift(MowerState(), True)
        assert result[1] == 0
        assert result[2] == 0


class TestBuildAtaOffmap:
    def test_shape(self) -> None:
        result = _build_ata_offmap(MowerState(), True)
        assert len(result) == 3

    def test_slot_1_is_new_value(self) -> None:
        assert _build_ata_offmap(MowerState(), True)[1] == 1
        assert _build_ata_offmap(MowerState(), False)[1] == 0

    def test_slot_0_is_lift(self) -> None:
        state = MowerState(anti_theft_lift_alarm=True)
        assert _build_ata_offmap(state, False)[0] == 1

    def test_slot_2_is_realtime(self) -> None:
        state = MowerState(anti_theft_realtime_location=True)
        assert _build_ata_offmap(state, False)[2] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_offmap(MowerState(), True)
        assert result[0] == 0
        assert result[2] == 0


class TestBuildAtaRealtime:
    def test_shape(self) -> None:
        result = _build_ata_realtime(MowerState(), True)
        assert len(result) == 3

    def test_slot_2_is_new_value(self) -> None:
        assert _build_ata_realtime(MowerState(), True)[2] == 1
        assert _build_ata_realtime(MowerState(), False)[2] == 0

    def test_slot_0_is_lift(self) -> None:
        state = MowerState(anti_theft_lift_alarm=True)
        assert _build_ata_realtime(state, False)[0] == 1

    def test_slot_1_is_offmap(self) -> None:
        state = MowerState(anti_theft_offmap_alarm=True)
        assert _build_ata_realtime(state, False)[1] == 1

    def test_none_defaults_other_flags_false(self) -> None:
        result = _build_ata_realtime(MowerState(), True)
        assert result[0] == 0
        assert result[1] == 0


# ---------------------------------------------------------------------------
# select.py builders
# ---------------------------------------------------------------------------

class TestBuildPreEfficiency:
    def test_shape(self) -> None:
        """Builder must return exactly 10 elements."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert len(result) == 10

    def test_standard_sets_slot_1_to_0(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[1] == 0

    def test_efficient_sets_slot_1_to_1(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Efficient")
        assert result[1] == 1

    def test_slot_0_is_zone_id(self) -> None:
        state = MowerState(pre_zone_id=3)
        result = _build_pre_efficiency(state, "Standard")
        assert result[0] == 3

    def test_slot_2_is_height_mm(self) -> None:
        state = MowerState(pre_mowing_height_mm=55)
        result = _build_pre_efficiency(state, "Standard")
        assert result[2] == 55

    def test_slot_2_defaults_to_pre_pad_defaults_0(self) -> None:
        """height_mm None → uses _PRE_PAD_DEFAULTS[0] (60mm)."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[2] == _PRE_PAD_DEFAULTS[0]

    def test_trailing_slots_from_pre_pad_defaults(self) -> None:
        """Slots 3..9 must come from _PRE_PAD_DEFAULTS[1:]."""
        result = _build_pre_efficiency(MowerState(), "Standard")
        for i, expected in enumerate(_PRE_PAD_DEFAULTS[1:], start=3):
            assert result[i] == expected, f"slot {i} mismatch"

    def test_none_zone_id_defaults_to_0(self) -> None:
        result = _build_pre_efficiency(MowerState(), "Standard")
        assert result[0] == 0

    def test_pre_pad_defaults_length(self) -> None:
        """_PRE_PAD_DEFAULTS must supply indices 2..9 (8 elements)."""
        assert len(_PRE_PAD_DEFAULTS) == 8


class TestBuildWrpResumeHours:
    def test_shape(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "4 hours")
        assert len(result) == 2

    def test_slot_0_is_enabled(self) -> None:
        state_on = MowerState(rain_protection_enabled=True)
        state_off = MowerState(rain_protection_enabled=False)
        assert _build_wrp_resume_hours(state_on, "4 hours")[0] == 1
        assert _build_wrp_resume_hours(state_off, "4 hours")[0] == 0

    def test_slot_1_is_parsed_hours(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "6 hours")
        assert result[1] == 6

    def test_zero_hours(self) -> None:
        result = _build_wrp_resume_hours(MowerState(), "0 hours")
        assert result[1] == 0

    def test_single_hour_label(self) -> None:
        """'1 hour' (singular) must still parse correctly."""
        result = _build_wrp_resume_hours(MowerState(), "1 hour")
        assert result[1] == 1

    def test_none_enabled_defaults_false(self) -> None:
        """rain_protection_enabled None → treated as False (enabled=0)."""
        result = _build_wrp_resume_hours(MowerState(), "2 hours")
        assert result[0] == 0
