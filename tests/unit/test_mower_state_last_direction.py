"""Per-map last mow direction tracking — new MowerState field for Phase 3."""
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_default_is_empty_dict():
    s = MowerState()
    assert s.last_all_area_mow_direction_deg == {}


def test_can_record_per_map():
    s = MowerState()
    s.last_all_area_mow_direction_deg[0] = 45
    s.last_all_area_mow_direction_deg[1] = 90
    assert s.last_all_area_mow_direction_deg == {0: 45, 1: 90}
