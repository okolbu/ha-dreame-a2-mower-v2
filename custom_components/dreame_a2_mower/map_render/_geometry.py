"""Shared geometry helpers and colour palette for the map renderer.

Contains: _DEFAULT_PALETTE, _DOCK_RADIUS_PX, _cloud_to_px, _renderer_to_px,
_OBSTACLE_FILL, _OBSTACLE_OUTLINE, and extract_projection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default palette (RGBA tuples).
# Lifted from legacy dreame/types.py MapRendererColorScheme (v1 repo line 2458).
# ---------------------------------------------------------------------------

_DEFAULT_PALETTE: dict[str, tuple[int, int, int, int]] = {
    # Lawn background — fills the bbox rectangle. Light grey lifted
    # from legacy `MapRendererColorScheme.floor` so the LiDAR card's
    # desaturated map-underlay reads as a calm grey background under
    # the 3D points instead of a glaring white sheet. The actual lawn
    # appears as the union of the mowing-zone polygons rendered on top.
    "lawn_fill": (221, 221, 221, 255),
    "lawn_outline": (160, 160, 160, 255),
    # Mowing zones — these now serve as the visual lawn shape over the
    # grey bbox. Zone 0 is fully opaque (α255) so the bbox-grey background
    # never bleeds through the primary lawn fill. First zone uses the legacy
    # "Dreame Light" scheme's primary grass-green; subsequent zones rotate
    # through the scheme at α200.
    "zone_fills": [
        (178, 223, 138, 255),   # zone 0: light grass-green (was α200)
        (249, 224, 125, 200),   # zone 1: warm yellow-green
        (184, 227, 255, 200),   # zone 2: light blue
        (184, 217, 141, 200),   # zone 3: muted green
    ],
    "zone_outline": (100, 160, 70, 255),
    # Exclusion zones (forbiddenAreas) — semi-transparent red.
    # Legacy: no_go=(177, 0, 0, 50), no_go_outline=(199, 0, 0, 200).
    "excl_fill": (177, 0, 0, 50),
    "excl_outline": (199, 0, 0, 200),
    # Ignore-obstacle zones (notObsAreas) — semi-transparent blueish-green,
    # matches the Dreame app's blueish-green ignore-zone rendering.
    # Legacy values: ignore_obstacle=(0, 177, 0, 50), ignore_obstacle_outline=(0, 149, 0, 200).
    "ignore_fill": (90, 140, 230, 90),
    "ignore_outline": (60, 110, 200, 220),
    # Spot zones — muted grey.
    # Legacy: spot_zone=(160, 160, 160, 50), spot_zone_outline=(96, 96, 96, 200).
    "spot_fill": (160, 160, 160, 50),
    "spot_outline": (96, 96, 96, 200),
    # Nav paths — gray wide line, matching the Dreame app's inter-map
    # connecting-route style (the app draws these as wide gray polylines
    # between adjacent map areas).
    "nav_path": (160, 160, 160, 255),
    "nav_path_width_px": 8,
    # M_PATH overlay — cloud-persisted mow trajectories from prior sessions.
    # Black so it visually distinguishes from the live trail's light-green
    # mow_trail_color. Drawn above the mowing zones (Section 2.6 in
    # render_base_map) so it's visible over the alpha-200 zone fills.
    "m_path": (0, 0, 0, 255),
    "m_path_width_px": 4,
    # Dock / charger icon — solid blue circle.
    "dock_fill": (34, 109, 242, 255),
    "dock_outline": (20, 70, 160, 255),
    # Maintenance points — light-brown circle 2x dock radius with white "M".
    "mp_fill": (180, 130, 80, 220),
    "mp_outline": (110, 70, 30, 255),
    "mp_text": (255, 255, 255, 255),
    # ------ Phase 1 (2026-05-17 render-styling refresh) ------
    # Dark green — alias of zone_outline RGB but used as a fill color in
    # the pre-mow / cutting-target / active-mow-background contexts.
    "dark_green": (100, 160, 70, 255),
    # Mowing trail strokes — same RGB as lawn (light-green); a session's
    # mowed area visually merges with the lawn baseline when on top of
    # dark_green backgrounds.
    "mow_trail_color": (178, 223, 138, 255),
    # Thin-mode mowing trail — used by the replay card's "thin" toggle so
    # individual passes stand out. Dark green α220 for high contrast on
    # the light-green lawn.
    "mow_trail_thin_color": (50, 100, 30, 220),
    # Traversal segments (dock-return / cross-map navigation). Drawn LAST
    # in render_with_trail so it stays visible over mowing strokes.
    "traversal_color": (130, 130, 130, 220),
}

# How many pixels across the dock icon is (before scaling).
_DOCK_RADIUS_PX = 4

# ---------------------------------------------------------------------------
# Replay-only obstacle overlay constants. Lifted from legacy
# protocol/trail_overlay.py:105-106 so the visual matches the pre-greenfield
# integration. RGBA — semi-transparent fill + slightly more opaque outline.
# ---------------------------------------------------------------------------
_OBSTACLE_FILL: tuple[int, int, int, int] = (90, 140, 230, 170)
_OBSTACLE_OUTLINE: tuple[int, int, int, int] = (40, 80, 200, 230)


def _cloud_to_px(
    cloud_x: float,
    cloud_y: float,
    bx2: float,
    by2: float,
    pixel_size_mm: float,
) -> tuple[float, float]:
    """Convert a cloud-frame mm coord to renderer pixel coords.

    Applies the pixel-flip formula:
        px = (bx2 - cloud_x) / pixel_size_mm
        py = (by2 - cloud_y) / pixel_size_mm

    Both axes are flipped relative to the cloud frame (the origin is
    the mower nose at dock entry; pixel (0,0) is the top-left corner
    of the canvas, which corresponds to cloud ``(bx2, by2)``).
    """
    return (
        (bx2 - cloud_x) / pixel_size_mm,
        (by2 - cloud_y) / pixel_size_mm,
    )


def _renderer_to_px(
    renderer_x: float,
    renderer_y: float,
    bx1: float,
    by1: float,
    pixel_size_mm: float,
) -> tuple[float, float]:
    """Convert renderer-frame mm coord (post-midline-reflection) to pixels.

    Exclusion-zone corners and ``dock_xy`` are stored in renderer coords
    by the decoder via ``(bx1+bx2 - X, by1+by2 - Y)``.  To land on the
    same pixel the lawn formula picks for the original cloud point
    ``(X, Y)``, subtract ``bx1``/``by1`` before dividing by grid:

        rx - bx1 = bx2 - X     ← matches `_cloud_to_px` X formula
        ry - by1 = by2 - Y     ← matches `_cloud_to_px` Y formula

    Without the subtraction every renderer-coord overlay is offset by
    ``(bx1/grid, by1/grid)`` pixels from the lawn — which is what made
    the dock and exclusion zones land on the wrong side of the canvas
    pre-v1.0.0a3.
    """
    return (
        (renderer_x - bx1) / pixel_size_mm,
        (renderer_y - by1) / pixel_size_mm,
    )


def extract_projection(map_data: MapData | None) -> dict | None:
    """Expose the projection params the card needs to reproduce render_with_trail.

    Returns the five fields the card consumes to project (x_m, y_m) to
    pixel coords matching the base PNG:

      cloud_x = x_m * 1000
      cloud_y = y_m * 1000
      px      = (bx2_mm - cloud_x) / pixel_size_mm
      py_pre  = (by2_mm - cloud_y) / pixel_size_mm
      py      = height_px - py_pre  # FLIP_TOP_BOTTOM applied to base PNG

    Returns None when called with no MapData, OR when the supplied
    object is missing any of the five required attributes (e.g. a
    half-built MapData during a cloud fetch failure, or a test fixture
    using a stub). The card's "no projection yet" branch handles None
    gracefully.
    """
    if map_data is None:
        return None
    try:
        proj: dict = {
            "bx1_mm": map_data.bx1,
            "by1_mm": map_data.by1,
            "bx2_mm": map_data.bx2,
            "by2_mm": map_data.by2,
            "pixel_size_mm": map_data.pixel_size_mm,
            "width_px": map_data.width_px,
            "height_px": map_data.height_px,
        }
        if map_data.dock_xy is not None:
            proj["dock_xy_mm"] = list(map_data.dock_xy)
        return proj
    except AttributeError:
        return None
