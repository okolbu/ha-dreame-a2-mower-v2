"""Infer dominant mow direction from cloud track_segments."""
from custom_components.dreame_a2_mower._render_direction import infer_mow_direction


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
