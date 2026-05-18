"""render_base_map with obstacles= kwarg paints obstacle polygons.

Fix 2: the no-trail base for the replay card must include obstacles so the
replay card's background matches the static work_log.png (minus the trail).
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _OBSTACLE_FILL,
    _OBSTACLE_OUTLINE,
    render_base_map,
)


def _tiny_map() -> MapData:
    """10m × 10m map with one mowing zone."""
    return MapData(
        md5="test-obstacles",
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
                zone_id=1,
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


def _pixel_set(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


# A 2m×2m obstacle polygon in cloud-frame metres, centred in the lawn.
_OBSTACLE_POLY_M: list[list[tuple[float, float]]] = [
    [
        (3.0, 3.0),
        (5.0, 3.0),
        (5.0, 5.0),
        (3.0, 5.0),
    ]
]


def test_render_base_map_accepts_obstacles_kwarg():
    """render_base_map must accept an obstacles= keyword argument."""
    import inspect
    sig = inspect.signature(render_base_map)
    assert "obstacles" in sig.parameters, (
        "render_base_map must accept obstacles= kwarg for replay-card parity"
    )


def test_no_obstacles_no_obstacle_fill():
    """Without obstacles, _OBSTACLE_FILL colour must not appear in the output."""
    png = render_base_map(_tiny_map(), lawn_mode="dark", obstacles=None)
    px = _pixel_set(png)
    # _OBSTACLE_FILL has alpha=170; after alpha_composite the exact pixel
    # value will differ. Check that the FILL tuple is absent as a raw pixel.
    # (It would only appear unblended if drawn directly — direct draw is what
    # draw.polygon does, so the fill tuple WILL be present if obstacles are drawn.)
    assert _OBSTACLE_FILL not in px, (
        f"_OBSTACLE_FILL {_OBSTACLE_FILL!r} found in base render with no obstacles"
    )


def test_with_obstacles_obstacle_fill_present():
    """With obstacles=, the output must contain pixels from _OBSTACLE_FILL."""
    png = render_base_map(_tiny_map(), lawn_mode="dark", obstacles=_OBSTACLE_POLY_M)
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    px = list(img.getdata())
    # _OBSTACLE_FILL = (90, 140, 230, 170). The polygon is drawn directly on
    # the canvas without _composite_polygon, so the exact RGBA appears.
    assert _OBSTACLE_FILL in px, (
        f"Expected _OBSTACLE_FILL {_OBSTACLE_FILL!r} in base render with obstacles. "
        f"Unique colours found: {sorted(set(px), key=lambda c: -px.count(c))[:10]}"
    )


def test_obstacles_none_and_empty_list_produce_same_output():
    """Passing obstacles=None and obstacles=[] must produce identical PNG bytes."""
    png_none = render_base_map(_tiny_map(), lawn_mode="dark", obstacles=None)
    png_empty = render_base_map(_tiny_map(), lawn_mode="dark", obstacles=[])
    assert png_none == png_empty, (
        "obstacles=None and obstacles=[] should render identically"
    )


def test_without_obstacles_kwarg_produces_same_as_none():
    """Omitting obstacles= is backward-compatible with the pre-fix behaviour."""
    png_default = render_base_map(_tiny_map(), lawn_mode="dark")
    png_none = render_base_map(_tiny_map(), lawn_mode="dark", obstacles=None)
    assert png_default == png_none, (
        "Omitting obstacles= and passing obstacles=None must be identical"
    )
