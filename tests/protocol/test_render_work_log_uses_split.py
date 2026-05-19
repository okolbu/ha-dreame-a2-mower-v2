"""Verify render_work_log correctly forwards leg arguments to render_with_trail.

Note: the fuzzy split_trail classifier was deleted in Task 11. The test
``test_render_work_log_local_plus_cloud_gives_both_colors`` (which asserted
both green + grey from the splitter) has been removed. Traversal classification
now requires mowing_legs/traversal_legs (explicit split) or legs_timeline
(capture-time metadata). The remaining tests guard back-compat and the
legs_timeline fast path.

Original context: the Phase 1 plumbing regression that sparked this file was
render_work_log_session passing only legs= (cloud track_segments) without
local_legs=. The plumbing fix survives; only the fuzzy-split pixel assertion
was removed.
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_work_log,
    render_with_trail,
)


# ---------------------------------------------------------------------------
# Tiny reusable MapData — 10 m × 10 m, pixel_size=50 mm
# ---------------------------------------------------------------------------

def _tiny_map() -> MapData:
    return MapData(
        md5="test-worklog-split",
        width_px=200,
        height_px=200,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=10000.0,
        by2=10000.0,
        cloud_x_reflect=10000.0,
        cloud_y_reflect=10000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0),
            (10000.0, 0.0),
            (10000.0, 10000.0),
            (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=0,
                name="lawn",
                path=(
                    (0.0, 0.0),
                    (10000.0, 0.0),
                    (10000.0, 10000.0),
                    (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


def _pixels(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_work_log_legacy_legs_kwarg_still_works():
    """Back-compat: old callers passing legs= alone still get a valid PNG."""
    legs = [[(2.0, 5.0), (4.0, 5.0)]]
    png = render_work_log(_tiny_map(), legs=legs)
    assert isinstance(png, bytes) and len(png) > 0


def test_render_work_log_empty_legs_does_not_crash():
    """Empty inputs fall through to base-map render (no trail) gracefully."""
    png = render_work_log(_tiny_map(), local_legs=[], cloud_segments=[])
    assert isinstance(png, bytes) and len(png) > 0


def test_render_work_log_only_cloud_segments_all_mowing():
    """Supplying only cloud_segments (no local) → everything classified as mowing."""
    cloud = [[(2.0, 5.0), (4.0, 5.0)]]
    png = render_work_log(_tiny_map(), cloud_segments=cloud)
    px = _pixels(png)

    mow_color = _DEFAULT_PALETTE["mow_trail_color"]
    trav_color = _DEFAULT_PALETTE["traversal_color"]

    assert mow_color in px, "mowing color missing when only cloud_segments provided"
    assert trav_color not in px, (
        "traversal color should not appear when no local_legs provided"
    )


def test_render_work_log_legs_timeline_forwarded_to_render_with_trail():
    """render_work_log passes legs_timeline= through to render_with_trail.

    Regression guard for Task 5: the new kwarg must flow from
    render_work_log → render_with_trail so the renderer uses the
    pre-classified timeline rather than the fuzzy splitter.
    """
    from unittest.mock import patch, call

    timeline = [
        {"role": "mowing",   "start_ts": 100, "end_ts": 200, "pts": [(2.0, 5.0), (4.0, 5.0)]},
        {"role": "traversal","start_ts": 200, "end_ts": 250, "pts": [(4.0, 5.0), (8.0, 8.0)]},
    ]

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=b"\x89PNG",
    ) as mock_rwt:
        render_work_log(_tiny_map(), legs_timeline=timeline)

    assert mock_rwt.called, "render_with_trail was not called"
    _, kwargs = mock_rwt.call_args
    assert kwargs.get("legs_timeline") is timeline, (
        f"legs_timeline not forwarded; render_with_trail got kwargs={kwargs}"
    )


def test_render_work_log_legs_timeline_both_colors():
    """legs_timeline with mixed roles produces both mowing (green) and traversal (grey).

    End-to-end pixel check: render_work_log → render_with_trail → actual
    drawing.  Verifies the new branch produces visually distinct output.
    """
    mow_color = _DEFAULT_PALETTE["mow_trail_color"]
    trav_color = _DEFAULT_PALETTE["traversal_color"]

    timeline = [
        {"role": "mowing",   "start_ts": 100, "end_ts": 200, "pts": [(2.0, 5.0), (4.0, 5.0)]},
        {"role": "traversal","start_ts": 200, "end_ts": 250, "pts": [(4.0, 5.0), (8.0, 8.0)]},
    ]

    png = render_work_log(_tiny_map(), legs_timeline=timeline)
    px = _pixels(png)

    assert mow_color in px, f"mow_trail_color {mow_color} missing — mowing leg not rendered"
    assert trav_color in px, f"traversal_color {trav_color} missing — traversal leg not rendered"
