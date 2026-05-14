"""Tests for wifi_match.py: heatmap → session fingerprint matcher."""
from __future__ import annotations

from custom_components.dreame_a2_mower.wifi_match import (
    NO_DATA_SENTINEL,
    match_heatmap_to_session,
    score_candidates,
)


def _grid(width: int, height: int, fill: int = -55):
    """Helper: build a flat row-major dBm grid of size width*height."""
    return [fill] * (width * height)


def test_match_returns_none_when_no_candidates():
    out = match_heatmap_to_session(
        heatmap_grid=_grid(4, 4),
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[],
    )
    assert out is None


def test_match_returns_none_when_all_candidates_outside_bbox():
    """A candidate whose samples are all outside the heatmap's bbox
    scores zero — no winner."""
    out = match_heatmap_to_session(
        heatmap_grid=_grid(4, 4),
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            (0, [(100.0, 100.0, -55, 1)]),
            (1, [(-50.0, -50.0, -55, 2)]),
        ],
    )
    assert out is None


def test_match_picks_higher_coverage_when_dbm_matches_both():
    """Two candidates with identical dBm agreement, but one's samples
    fall mostly inside the bbox while the other's mostly outside."""
    grid = _grid(4, 4, fill=-55)
    out = match_heatmap_to_session(
        heatmap_grid=grid,
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            # map 0: 1 of 4 samples inside (cell 0,0)
            (0, [
                (1.0, 1.0, -55, 1),
                (100.0, 0.0, -55, 2),
                (100.0, 1.0, -55, 3),
                (100.0, 2.0, -55, 4),
            ]),
            # map 1: 4 of 4 samples inside
            (1, [
                (1.0, 1.0, -55, 1),
                (3.0, 1.0, -55, 2),
                (5.0, 1.0, -55, 3),
                (7.0, 1.0, -55, 4),
            ]),
        ],
    )
    assert out == 1


def test_match_prefers_better_rssi_agreement_at_same_coverage():
    """Two candidates with full coverage but one's RSSI matches the
    grid exactly while the other is 20 dBm off — the matching one
    wins."""
    grid = _grid(4, 4, fill=-55)
    out = match_heatmap_to_session(
        heatmap_grid=grid,
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            (0, [
                (1.0, 1.0, -75, 1),
                (3.0, 1.0, -75, 2),
                (5.0, 1.0, -75, 3),
            ]),
            (1, [
                (1.0, 1.0, -55, 1),
                (3.0, 1.0, -55, 2),
                (5.0, 1.0, -55, 3),
            ]),
        ],
    )
    assert out == 1


def test_match_skips_no_data_cells_when_computing_delta():
    """Cells with value 1 (NO_DATA) must not count toward
    mean_delta — they only contribute to coverage."""
    # Grid: row 0 has real -55 values; row 1+ has NO_DATA.
    width, height = 4, 4
    grid = [-55] * width + [NO_DATA_SENTINEL] * (width * (height - 1))
    scores = score_candidates(
        heatmap_grid=grid,
        heatmap_width=width,
        heatmap_height=height,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            # All samples land in NO_DATA row → coverage=1 but delta=100 (fallback).
            (0, [
                (1.0, 4.0, -55, 1),
                (3.0, 4.0, -55, 2),
            ]),
            # All samples land in real row → coverage=1, delta=0 (perfect).
            (1, [
                (1.0, 1.0, -55, 1),
                (3.0, 1.0, -55, 2),
            ]),
        ],
    )
    by_id = {s.map_id: s for s in scores}
    assert by_id[1].score > by_id[0].score
    # Map 1 has zero delta and full coverage → score should be 1.0
    assert abs(by_id[1].score - 1.0) < 1e-9
    # Map 0 has full coverage but fallback delta=100 → score 1/(1+10) = 1/11
    assert abs(by_id[0].score - (1.0 / 11.0)) < 1e-9


def test_score_diagnostics_populated():
    """Score dataclass exposes coverage / mean_delta / counts."""
    scores = score_candidates(
        heatmap_grid=_grid(4, 4, fill=-50),
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            (5, [
                (1.0, 1.0, -55, 1),  # inside, delta=5
                (1.0, 1.0, -60, 2),  # inside, delta=10
                (100.0, 100.0, -55, 3),  # outside
            ]),
        ],
    )
    assert len(scores) == 1
    s = scores[0]
    assert s.map_id == 5
    assert s.samples_total == 3
    assert s.samples_in_bbox == 2
    assert abs(s.coverage - (2 / 3)) < 1e-9
    # mean delta = (5 + 10) / 2 = 7.5
    assert abs(s.mean_delta - 7.5) < 1e-9
    # score = (2/3) / (1 + 7.5/10) = (2/3) / 1.75
    assert abs(s.score - ((2 / 3) / 1.75)) < 1e-9


def test_match_handles_empty_samples_gracefully():
    """A candidate with zero samples scores 0 (not a crash)."""
    out = match_heatmap_to_session(
        heatmap_grid=_grid(4, 4),
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            (0, []),
            (1, [(1.0, 1.0, -55, 1)]),
        ],
    )
    assert out == 1


def test_match_handles_garbage_sample_rows():
    """Samples with non-numeric entries are silently skipped."""
    scores = score_candidates(
        heatmap_grid=_grid(4, 4, fill=-55),
        heatmap_width=4,
        heatmap_height=4,
        heatmap_resolution_m=2,
        heatmap_start_x_m=0.0,
        heatmap_start_y_m=0.0,
        candidates=[
            (0, [
                (1.0, 1.0, -55, 1),
                ("bad", "data", "row", "x"),  # type: ignore[list-item]
                (3.0, 1.0, -55, 2),
            ]),
        ],
    )
    # 2 of 3 (the bad row was filtered at iter time, so n_total is
    # still 3 but inside is 2).
    assert scores[0].samples_in_bbox == 2


def test_match_with_realistic_g2408_geometry():
    """Realistic-sized heatmap: 16×18 cells at 2 m resolution, dock-origin frame.

    Verifies the indexing math holds at full scale.
    """
    width, height, res = 16, 18, 2
    grid = _grid(width, height, fill=-60)
    # Start_x = -11 m, start_y = -15 m (typical observed values:
    # -1100 cm / 100 → -11 m).
    sx, sy = -11.0, -15.0
    # Sample at (0,0) is inside cell ((0-(-11))/2, (0-(-15))/2) = (5, 7).
    out = match_heatmap_to_session(
        heatmap_grid=grid,
        heatmap_width=width,
        heatmap_height=height,
        heatmap_resolution_m=res,
        heatmap_start_x_m=sx,
        heatmap_start_y_m=sy,
        candidates=[
            (3, [(0.0, 0.0, -60, 1)]),
        ],
    )
    assert out == 3
