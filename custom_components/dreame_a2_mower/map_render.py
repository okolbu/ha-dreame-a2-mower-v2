"""PNG renderer for the Dreame A2 Mower base map.

Takes a :class:`~.map_decoder.MapData` produced by
:func:`~.map_decoder.parse_cloud_map` and returns PNG bytes containing:

1. The lawn boundary polygon (filled, grass-green).
2. All mowing zones (overlaid, lighter grass-green) — cloud-frame mm
   transformed to pixel coords via the ``(bx2-x)/grid, (by2-y)/grid``
   flip formula.
3. Exclusion zones (semi-transparent overlays) — already in renderer
   pixel coords from the decoder; drawn as-is.
4. Dock / charger icon (blue circle) at ``dock_xy``, also in renderer
   pixel coords.

No trail, no live mower icon, no WiFi heatmap — those are F5+ concerns.

Palette lifted from legacy ``dreame/types.py::MapRendererColorScheme``
(lines 2458–2502 of the A2-mower v1 repo).

Coordinate convention
---------------------
Pixel coords for mowing zones are derived by the *renderer pixel-flip*::

    px = (bx2 - cloud_x) / pixel_size_mm
    py = (by2 - cloud_y) / pixel_size_mm

For exclusion zones and ``dock_xy`` the decoder (F2.8.1) has already
applied the midline-reflection ``(bx1+bx2 - cloud_x, by1+by2 - cloud_y)``,
which in pixel space is equivalent to the formula above (both bbox edges
cancel to the same result when the zone fits inside the bbox).  So those
coords are used directly, divided by ``pixel_size_mm``.

See ``docs/research/cloud-map-geometry.md §3.3`` for the full derivation.
"""

from __future__ import annotations

import io
import logging
import math
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from .map_decoder import MapData
    from .live_map.trail import Leg

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default palette (RGBA tuples).
# Lifted from legacy dreame/types.py MapRendererColorScheme (v1 repo line 2458).
# ---------------------------------------------------------------------------

_DEFAULT_PALETTE: dict[str, tuple[int, int, int, int]] = {
    # Lawn background — the overall mow-able area bounding rectangle.
    # Slightly darker grass-green than zone fills so zones are visible.
    "lawn_fill": (156, 214, 120, 255),
    "lawn_outline": (100, 160, 70, 255),
    # Mowing zones — first zone uses the primary grass-green pair.
    # Subsequent zones rotate through the four scheme colours. Alpha
    # 100/255 (~40%) so the lawn fill shows through; v1.0.0a6 dropped
    # this from full opacity per user request to see lawn under zones.
    "zone_fills": [
        (178, 223, 138, 100),   # zone 0: light grass-green
        (249, 224, 125, 100),   # zone 1: warm yellow-green
        (184, 227, 255, 100),   # zone 2: light blue
        (184, 217, 141, 100),   # zone 3: muted green
    ],
    "zone_outline": (100, 160, 70, 255),
    # Exclusion zones (forbiddenAreas) — semi-transparent red.
    # Legacy: no_go=(177, 0, 0, 50), no_go_outline=(199, 0, 0, 200).
    "excl_fill": (177, 0, 0, 50),
    "excl_outline": (199, 0, 0, 200),
    # Ignore-obstacle zones (notObsAreas) — semi-transparent green (app draws green).
    # Legacy: ignore_obstacle=(0, 177, 0, 50), ignore_obstacle_outline=(0, 149, 0, 200).
    "ignore_fill": (0, 177, 0, 50),
    "ignore_outline": (0, 149, 0, 200),
    # Spot zones — muted grey.
    # Legacy: spot_zone=(160, 160, 160, 50), spot_zone_outline=(96, 96, 96, 200).
    "spot_fill": (160, 160, 160, 50),
    "spot_outline": (96, 96, 96, 200),
    # Dock / charger icon — solid blue circle.
    "dock_fill": (34, 109, 242, 255),
    "dock_outline": (20, 70, 160, 255),
}

# How many pixels across the dock icon is (before scaling).
_DOCK_RADIUS_PX = 4


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


def render_base_map(map_data: "MapData", palette: dict | None = None) -> bytes:
    """Render the base map (no trail) as a PNG byte stream.

    Returns the PNG bytes ready to set as a camera entity's image content.

    Args:
        map_data: Decoded map geometry from :func:`.map_decoder.parse_cloud_map`.
        palette: Optional colour override dict.  Keys match :data:`_DEFAULT_PALETTE`.
                 Any key omitted in *palette* falls back to the default.

    Returns:
        Raw PNG bytes.  The image is ``map_data.width_px × map_data.height_px``
        pixels, RGBA, with a transparent background outside the lawn area.
    """
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    width = map_data.width_px
    height = map_data.height_px
    grid = map_data.pixel_size_mm  # 50.0 mm/pixel for g2408
    bx2 = map_data.bx2
    by2 = map_data.by2

    # Sanity guard.
    if width <= 0 or height <= 0:
        _LOGGER.warning(
            "render_base_map: degenerate canvas %dx%d — returning empty PNG",
            width,
            height,
        )
        width = max(width, 1)
        height = max(height, 1)

    # -----------------------------------------------------------------------
    # Create canvas — transparent RGBA.
    # -----------------------------------------------------------------------
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    def _composite_polygon(
        flat_pts: list[float],
        fill_colour: tuple[int, int, int, int],
        outline_colour: tuple[int, int, int, int],
        outline_width: int,
    ) -> None:
        """Alpha-blend a polygon onto ``image``.

        v1.0.0a15: PIL's ImageDraw.polygon(fill=...) REPLACES pixels
        with the source RGBA tuple — it doesn't blend the alpha against
        the underlying canvas. So a fill like (177, 0, 0, 50) on top of
        an opaque-green lawn produced pixels with alpha=50 and the lawn
        green was lost; the user saw the zone color over HA's dark
        theme background instead of through the lawn. To get correct
        alpha blending we draw the polygon onto a transparent overlay
        with full alpha, then alpha_composite the overlay onto image.
        Outline keeps its original alpha (typically 200/255) for
        visibility.
        """
        nonlocal image, draw
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay, "RGBA")
        ov_draw.polygon(
            flat_pts,
            fill=fill_colour,
            outline=outline_colour,
            width=outline_width,
        )
        image = Image.alpha_composite(image, overlay)
        draw = ImageDraw.Draw(image, "RGBA")

    # -----------------------------------------------------------------------
    # 1. Lawn boundary polygon (4-corner bbox in cloud-frame mm).
    #    boundary_polygon = [(bx1,by1),(bx2,by1),(bx2,by2),(bx1,by2)].
    #    Convert each corner through the cloud→pixel flip.
    # -----------------------------------------------------------------------
    if map_data.boundary_polygon and len(map_data.boundary_polygon) >= 3:
        boundary_px = [
            _cloud_to_px(cx, cy, bx2, by2, grid)
            for (cx, cy) in map_data.boundary_polygon
        ]
        flat = [coord for pt in boundary_px for coord in pt]
        # Lawn is fully opaque (alpha 255) — paint directly.
        draw.polygon(
            flat,
            fill=p["lawn_fill"],
            outline=p["lawn_outline"],
            width=2,
        )
        _LOGGER.debug(
            "render_base_map: drew boundary polygon (%d corners)",
            len(boundary_px),
        )

    # -----------------------------------------------------------------------
    # 2. Mowing zones — cloud-frame mm → pixel flip.
    #    Each MowingZone.path is raw cloud-frame mm (not reflected).
    # -----------------------------------------------------------------------
    zone_fills: list[tuple[int, int, int, int]] = p["zone_fills"]  # type: ignore[assignment]
    for zone in map_data.mowing_zones:
        if len(zone.path) < 3:
            continue
        zone_px = [
            _cloud_to_px(cx, cy, bx2, by2, grid)
            for (cx, cy) in zone.path
        ]
        flat = [coord for pt in zone_px for coord in pt]
        # Rotate through the colour list by (zone_id - 1) so zone 1 = index 0.
        fill_colour = zone_fills[(zone.zone_id - 1) % len(zone_fills)]
        _composite_polygon(flat, fill_colour, p["zone_outline"], 1)
        _LOGGER.debug(
            "render_base_map: drew mowing zone %d '%s' (%d corners)",
            zone.zone_id,
            zone.name,
            len(zone_px),
        )

    # -----------------------------------------------------------------------
    # 3. Exclusion zones — already in renderer pixel coords (post-reflection).
    #    Divide by pixel_size_mm to get pixel offsets.
    # -----------------------------------------------------------------------
    bx1 = map_data.bx1
    by1 = map_data.by1
    for ez in map_data.exclusion_zones:
        if len(ez.points) < 3:
            continue
        ez_px = [
            _renderer_to_px(rx, ry, bx1, by1, grid)
            for (rx, ry) in ez.points
        ]
        flat = [coord for pt in ez_px for coord in pt]
        if ez.subtype == "ignore":
            fill_colour = p["ignore_fill"]
            outline_colour = p["ignore_outline"]
        elif ez.subtype == "spot":
            fill_colour = p["spot_fill"]
            outline_colour = p["spot_outline"]
        else:
            fill_colour = p["excl_fill"]
            outline_colour = p["excl_outline"]
        _composite_polygon(flat, fill_colour, outline_colour, 1)
        _LOGGER.debug(
            "render_base_map: drew exclusion zone (subtype=%r, %d corners)",
            ez.subtype,
            len(ez_px),
        )

    # -----------------------------------------------------------------------
    # 4. Dock / charger icon — filled circle at dock_xy.
    #    dock_xy is in renderer-frame mm (post-reflection + CHARGER_OFFSET_MM);
    #    divide by pixel_size_mm for pixel coords.
    # -----------------------------------------------------------------------
    if map_data.dock_xy is not None:
        dx, dy = _renderer_to_px(
            map_data.dock_xy[0], map_data.dock_xy[1],
            map_data.bx1, map_data.by1, grid,
        )
        r = _DOCK_RADIUS_PX
        draw.ellipse(
            [dx - r, dy - r, dx + r, dy + r],
            fill=p["dock_fill"],
            outline=p["dock_outline"],
            width=1,
        )
        _LOGGER.debug(
            "render_base_map: drew dock icon at pixel (%.1f, %.1f) r=%d",
            dx,
            dy,
            r,
        )

    # -----------------------------------------------------------------------
    # Vertical flip — the cloud-to-pixel math puts high-Y at the top of
    # the image (low py), but the app shows low-Y at the top. Flip the
    # finished canvas so the rendered map matches what the user sees in
    # the Dreame app. (v1.0.0a5)
    # -----------------------------------------------------------------------
    image = image.transpose(Image.FLIP_TOP_BOTTOM)

    # -----------------------------------------------------------------------
    # Encode to PNG bytes.
    # -----------------------------------------------------------------------
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    _LOGGER.debug(
        "render_base_map: rendered %dx%d PNG (%d bytes)",
        width,
        height,
        len(png_bytes),
    )
    return png_bytes


# ---------------------------------------------------------------------------
# Trail colour / style
# ---------------------------------------------------------------------------

#: Trail polyline colour — solid red, fully opaque.
_TRAIL_COLOR: tuple[int, int, int, int] = (220, 30, 30, 255)
#: Trail line width in pixels.
_TRAIL_LINE_WIDTH: int = 2


def render_with_trail(
    map_data: "MapData",
    legs: "list[Leg] | None",
    palette: dict | None = None,
) -> bytes:
    """Render the base map with a live trail overlay composited on top.

    Calls :func:`render_base_map` first to get the base PNG, then
    re-opens it with Pillow and draws each leg as a red polyline using
    :class:`PIL.ImageDraw`.  Pen-up gaps between legs are honoured —
    no line segment connects the last point of one leg to the first
    point of the next.

    Args:
        map_data: Decoded map geometry (same as :func:`render_base_map`).
        legs: List of legs from ``LiveMapState.legs`` (each leg is a
            list of ``(x_m, y_m)`` tuples).  Pass ``None`` or an empty
            list to get the same output as :func:`render_base_map`.
        palette: Optional colour override forwarded to
            :func:`render_base_map`.

    Returns:
        Raw PNG bytes with the trail composited over the base map.
    """
    # Start from the base-map PNG.
    base_png = render_base_map(map_data, palette=palette)

    if not legs:
        # No trail — return base map unchanged.
        return base_png

    from .live_map.trail import render_trail_overlay

    # Convert (x_m, y_m) legs to pixel-coord legs using the same geometry
    # as the base renderer so the trail aligns with the lawn polygon.
    pixel_legs = render_trail_overlay(
        legs=legs,
        bx2=map_data.bx2,
        by2=map_data.by2,
        pixel_size_mm=map_data.pixel_size_mm,
    )

    if not pixel_legs:
        return base_png

    # Re-open the base PNG in RGBA. render_base_map already flipped it
    # vertically (v1.0.0a5) to match the app's orientation, but the
    # trail's pixel coords come from render_trail_overlay using the
    # unflipped (by2 - cy)/grid formula. Flip back, draw trail, flip
    # forward — so the trail lands on the correct side and the final
    # image keeps the app-matching orientation.
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")

    drawn_legs = 0
    drawn_points = 0
    for leg_px in pixel_legs:
        if len(leg_px) < 2:
            # Single point (or empty) — nothing to draw with line(); skip.
            continue
        # ImageDraw.line expects a flat sequence of (x, y) tuples or
        # alternating x,y values.  We pass a list of (x, y) tuples directly.
        draw.line(leg_px, fill=_TRAIL_COLOR, width=_TRAIL_LINE_WIDTH)
        drawn_legs += 1
        drawn_points += len(leg_px)

    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    _LOGGER.debug(
        "render_with_trail: drew %d legs / %d points → %d-byte PNG",
        drawn_legs,
        drawn_points,
        len(png_bytes),
    )
    return png_bytes
