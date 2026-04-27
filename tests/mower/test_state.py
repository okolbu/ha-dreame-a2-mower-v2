"""Regression tests for MowerState — the typed domain model."""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)


def test_mower_state_defaults_are_unknown():
    """Fresh MowerState has unknown values — represents 'no data yet'."""
    s = MowerState()
    assert s.state is None
    assert s.battery_level is None
    assert s.charging_status is None


def test_state_enum_covers_g2408_apk_values():
    """The State enum must include every value the apk decompilation
    documents on g2408 per protocol-doc §2.1."""
    expected = {1, 2, 3, 5, 6, 11, 13, 14}
    actual = {s.value for s in State}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_charging_status_enum_covers_g2408_values():
    """ChargingStatus enum covers the {0, 1, 2} range observed on g2408."""
    expected = {0, 1, 2}
    actual = {c.value for c in ChargingStatus}
    assert expected == actual


def test_mower_state_with_all_fields_set():
    """MowerState supports keyword construction with all fields."""
    s = MowerState(
        state=State.WORKING,
        battery_level=72,
        charging_status=ChargingStatus.NOT_CHARGING,
    )
    assert s.state == State.WORKING
    assert s.battery_level == 72
    assert s.charging_status == ChargingStatus.NOT_CHARGING


def test_mower_state_f2_fields_default_to_none():
    """All F2 fields default to None on a fresh MowerState."""
    s = MowerState()
    assert s.error_code is None
    assert s.obstacle_flag is None
    assert s.area_mowed_m2 is None
    assert s.total_distance_m is None
    assert s.total_lawn_area_m2 is None
    assert s.mowing_phase is None
    assert s.position_x_m is None
    assert s.position_y_m is None
    assert s.position_north_m is None
    assert s.position_east_m is None
    assert s.position_lat is None
    assert s.position_lon is None
    assert s.wifi_rssi_dbm is None
    assert s.cloud_connected is None
    assert s.battery_temp_low is None
    assert s.slam_task_label is None
    assert s.task_state_code is None
    assert s.blades_life_pct is None
    assert s.side_brush_life_pct is None
    assert s.total_cleaning_time_min is None
    assert s.total_cleaned_area_m2 is None
    assert s.cleaning_count is None
    assert s.first_cleaning_date is None
    assert s.station_bearing_deg is None
    assert s.manual_mode is None


def test_mower_state_f2_construction_with_all_fields():
    """All F2 fields accept positional/keyword construction."""
    s = MowerState(
        state=State.WORKING,
        battery_level=72,
        charging_status=ChargingStatus.NOT_CHARGING,
        error_code=0,
        obstacle_flag=False,
        area_mowed_m2=12.5,
        total_distance_m=345.0,
        total_lawn_area_m2=378.3,
        mowing_phase=2,
        position_x_m=1.23,
        position_y_m=-4.56,
        position_north_m=1.23,
        position_east_m=-4.56,
        position_lat=59.123,
        position_lon=10.456,
        wifi_rssi_dbm=-65,
        cloud_connected=True,
        battery_temp_low=False,
        slam_task_label="TASK_SLAM_RELOCATE",
        task_state_code=2,
        blades_life_pct=85.0,
        side_brush_life_pct=90.0,
        total_cleaning_time_min=1234,
        total_cleaned_area_m2=5678.0,
        cleaning_count=42,
        first_cleaning_date="2026-04-01",
        station_bearing_deg=45.0,
        manual_mode=False,
    )
    assert s.error_code == 0
    assert s.position_lat == 59.123
    assert s.station_bearing_deg == 45.0
