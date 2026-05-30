from custom_components.dreame_a2_mower.protocol.session_summary import (
    mow_type_from_mode, start_mode_label,
)


def test_mow_type_from_mode():
    assert mow_type_from_mode(100) == "all_areas"
    assert mow_type_from_mode(101) == "edge"
    assert mow_type_from_mode(102) == "zone"
    assert mow_type_from_mode(103) == "spot"
    assert mow_type_from_mode(999) is None


def test_start_mode_label():
    assert start_mode_label(1) == "scheduled"
    assert start_mode_label(0) == "manual"
    assert start_mode_label(7) is None
