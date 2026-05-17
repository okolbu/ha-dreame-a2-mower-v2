"""Infer dominant mow direction from cloud track_segments."""
import pytest
from custom_components.dreame_a2_mower._render_direction import infer_mow_direction, next_direction


def test_horizontal_passes_return_zero():
    """Straight east-west mowing (along the X axis) → 0 degrees."""
    segs = [
        [(0.0, 0.0), (10000.0, 0.0)],
        [(0.0, 200.0), (10000.0, 200.0)],
        [(0.0, 400.0), (10000.0, 400.0)],
    ]
    assert infer_mow_direction(segs) == 0


def test_vertical_passes_return_ninety():
    segs = [
        [(0.0, 0.0), (0.0, 10000.0)],
        [(200.0, 0.0), (200.0, 10000.0)],
    ]
    assert infer_mow_direction(segs) == 90


def test_diagonal_45_returns_forty_five():
    segs = [
        [(0.0, 0.0), (10000.0, 10000.0)],
        [(200.0, 0.0), (10200.0, 10000.0)],
    ]
    assert infer_mow_direction(segs) == 45


def test_returns_none_for_no_qualifying_segments():
    """Empty or all-too-short segments → None (renderer falls back to 0°)."""
    assert infer_mow_direction([]) is None
    assert infer_mow_direction([[(0.0, 0.0), (10.0, 10.0)]]) is None  # below MIN_SEGMENT_M


def test_result_in_0_to_179_inclusive():
    """135° vs 315° are the SAME stripe direction — reduce mod 180."""
    segs = [
        [(10000.0, 0.0), (0.0, 10000.0)],  # heading northwest = 135°
    ]
    assert infer_mow_direction(segs) == 135


def test_circular_mean_weighted_by_segment_length():
    """A long horizontal and a short diagonal: result should lean horizontal."""
    segs = [
        [(0.0, 0.0), (20000.0, 0.0)],     # length 20m, direction 0°
        [(0.0, 0.0), (1000.0, 1000.0)],   # length ≈1.4m, direction 45°
    ]
    d = infer_mow_direction(segs)
    assert 0 <= d <= 15, f"long horizontal should dominate; got {d}"


# ---------------------------------------------------------------------------
# next_direction — mowing-pattern mode transitions (T13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode,last,expected", [
    # Striped (0) — same as last
    (0, 0, 0), (0, 45, 45), (0, 90, 90), (0, 135, 135),
    # Crisscross (1) — last + 45 mod 180
    (1, 0, 45), (1, 45, 90), (1, 90, 135), (1, 135, 0),
    # Chequerboard (2) — last + 90 mod 180
    (2, 0, 90), (2, 45, 135), (2, 90, 0), (2, 135, 45),
])
def test_next_direction_table(mode, last, expected):
    assert next_direction(last_direction_deg=last, mode=mode) == expected


def test_next_direction_none_last_returns_zero():
    """First mow ever → no prior direction → default 0°."""
    assert next_direction(last_direction_deg=None, mode=0) == 0
    assert next_direction(last_direction_deg=None, mode=1) == 0
    assert next_direction(last_direction_deg=None, mode=2) == 0


def test_next_direction_unknown_mode_treated_as_same():
    assert next_direction(last_direction_deg=45, mode=99) == 45
