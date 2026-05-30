"""The canonical mode/op enum — single source of truth for 100-103/108."""
from custom_components.dreame_a2_mower.protocol.mode_enum import (
    MODE_BY_CODE,
    MOW_MODE_CODES,
    mode_label,
    mode_slug,
)


def test_slugs_and_labels():
    assert mode_slug(100) == "all_areas"
    assert mode_slug(101) == "edge"
    assert mode_slug(102) == "zone"
    assert mode_slug(103) == "spot"
    assert mode_slug(108) == "patrol"
    assert mode_label(100) == "All areas"
    assert mode_label(102) == "Zone"  # regression: was once mislabelled "All areas"
    assert mode_label(108) == "Patrol"


def test_unknown_code_is_none():
    assert mode_slug(999) is None
    assert mode_label(999) is None


def test_mow_codes_exclude_patrol():
    """100-103 are blades-down mows; 108 (patrol) is NOT — it must not open a
    mow_session in the state machine."""
    assert MOW_MODE_CODES == frozenset({100, 101, 102, 103})
    assert 108 not in MOW_MODE_CODES
    assert MODE_BY_CODE[108].is_mow is False
    assert all(MODE_BY_CODE[c].is_mow for c in (100, 101, 102, 103))


def test_slug_matches_action_mode_values_for_mows():
    """The mow slugs must equal mower.state.ActionMode values so the two enums
    don't drift."""
    from custom_components.dreame_a2_mower.mower.state import ActionMode

    assert mode_slug(100) == ActionMode.ALL_AREAS.value
    assert mode_slug(101) == ActionMode.EDGE.value
    assert mode_slug(102) == ActionMode.ZONE.value
    assert mode_slug(103) == ActionMode.SPOT.value
