from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    merge_mow_type_fields,
)


def test_merge_mow_type_fields():
    raw: dict = {}
    merge_mow_type_fields(raw, mode=103, start_mode=0)
    assert raw["mow_type"] == "spot"
    assert raw["mow_type_raw"] == 103
    assert raw["start_mode_label"] == "manual"


def test_merge_mow_type_unknown_mode_keeps_raw():
    raw: dict = {}
    merge_mow_type_fields(raw, mode=999, start_mode=1)
    assert raw.get("mow_type") is None
    assert raw["mow_type_raw"] == 999
    assert raw["start_mode_label"] == "scheduled"
