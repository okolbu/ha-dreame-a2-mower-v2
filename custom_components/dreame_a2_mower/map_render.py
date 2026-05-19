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
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .cloud_state import MowPathData
    from .live_map.trail import Leg
    from .map_decoder import MapData

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


def render_base_map(
    map_data: MapData,
    palette: dict | None = None,
    *,
    m_path: MowPathData | None = None,
    lawn_mode: str = "light",
    stripe_overlay: "Image.Image | None" = None,
    obstacles: "list[list[tuple[float, float]]] | None" = None,
) -> bytes:
    """Render the base map (no trail) as a PNG byte stream.

    Returns the PNG bytes ready to set as a camera entity's image content.

    Args:
        map_data: Decoded map geometry from :func:`.map_decoder.parse_cloud_map`.
        palette: Optional colour override dict.  Keys match :data:`_DEFAULT_PALETTE`.
                 Any key omitted in *palette* falls back to the default.
        lawn_mode: Controls the primary zone fill colour.

            - ``"light"`` (default): zone_fills[0] is used as-is (light
              grass-green). The idle baseline — renders the lawn in the
              resting "unmowed" palette.
            - ``"dark"``: replaces zone_fills[0] with ``dark_green`` so the
              lawn polygon paints dark green. Trail strokes in
              ``mow_trail_color`` (also light green) then overlay where the
              mower passed, producing the Dreame app's two-tone
              "lawn = dark, mowed = light" visual.
        stripe_overlay: Optional RGBA Image in PRE-FLIP pixel coordinates.
            When provided, it is alpha-composited onto the canvas RIGHT AFTER
            the mowing-zone fills (layer 2) and BEFORE any other zone shapes
            (exclusion, ignore, spot, nav, dock). The final y-flip applied at
            the end of this function handles orientation naturally — the caller
            must NOT pre-flip the overlay. This param is used by
            ``_render_pre_start_with_stripes`` to ensure stripes render at the
            correct z-order and share the same coordinate space as everything
            else on the canvas.
        obstacles: Optional list of obstacle polygons in cloud-frame metres
            (same format as ``render_with_trail``'s ``obstacle_polygons_m``).
            When provided, paints them as semi-transparent blue filled polygons
            using ``_OBSTACLE_FILL`` / ``_OBSTACLE_OUTLINE`` AFTER the dock
            icon (same z-order as the obstacles in ``render_with_trail``), so
            the replay card's no-trail background image includes obstacles and
            the animated SVG trail draws on top. The caller must supply the
            session-specific obstacle list — typically
            ``[list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3]``.

    Returns:
        Raw PNG bytes.  The image is ``map_data.width_px × map_data.height_px``
        pixels, RGBA, with a transparent background outside the lawn area.
    """
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)
    if lawn_mode == "dark":
        # Override the primary zone fill so the lawn polygon paints dark green.
        # Trail strokes (mow_trail_color) will overlay where mowed, giving the
        # two-tone "dark lawn / light mowed" visual matching the Dreame app.
        p["zone_fills"] = [p["dark_green"]] + list(p["zone_fills"][1:])

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
    # 2.5. Stripe overlay (pre-start preview) — composited immediately after
    #      the mowing-zone fills so that all subsequent zone layers (exclusion,
    #      ignore, spot, nav, dock) paint on top of the stripes and remain
    #      visible.  The overlay is in PRE-FLIP pixel coordinates, matching the
    #      canvas at this point in the pipeline — the final FLIP_TOP_BOTTOM at
    #      the end of this function handles orientation.  Callers must NOT
    #      pre-flip the overlay.
    # -----------------------------------------------------------------------
    if stripe_overlay is not None:
        image = Image.alpha_composite(image, stripe_overlay)
        draw = ImageDraw.Draw(image, "RGBA")
        _LOGGER.debug("render_base_map: composited stripe overlay")

    # -----------------------------------------------------------------------
    # 2.6. M_PATH overlay — cloud-persisted prior-session mow tracks.
    #      Drawn ABOVE mowing zones (so the cumulative track is visible
    #      over the alpha-200 zone fills) but BELOW exclusion / spot /
    #      nav / dock layers (those are interactive overlays the user
    #      cares about more than historical coverage).
    # -----------------------------------------------------------------------
    if m_path is not None and m_path.segments:
        m_path_color: tuple[int, int, int, int] = p.get(
            "m_path", (0, 0, 0, 255)
        )  # type: ignore[assignment]
        m_path_width: int = p.get("m_path_width_px", 4)  # type: ignore[assignment]
        drawn_segments = 0
        for seg in m_path.segments:
            if len(seg) < 2:
                continue
            seg_px = [
                _cloud_to_px(x_mm, y_mm, bx2, by2, grid)
                for (x_mm, y_mm) in seg
            ]
            draw.line(seg_px, fill=m_path_color, width=m_path_width, joint="curve")
            drawn_segments += 1
        _LOGGER.debug(
            "render_base_map: drew %d M_PATH segment(s)", drawn_segments
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
    # 3b. Spot zones — drawn the same way as exclusions but tracked
    #     separately so the UI can target individual spots by id+name.
    # -----------------------------------------------------------------------
    for sz in getattr(map_data, "spot_zones", ()):
        if len(sz.points) < 3:
            continue
        sz_px = [
            _renderer_to_px(rx, ry, bx1, by1, grid)
            for (rx, ry) in sz.points
        ]
        flat = [coord for pt in sz_px for coord in pt]
        _composite_polygon(flat, p["spot_fill"], p["spot_outline"], 1)
        _LOGGER.debug(
            "render_base_map: drew spot zone id=%d name=%r (%d corners)",
            sz.spot_id,
            sz.name,
            len(sz_px),
        )

    # -----------------------------------------------------------------------
    # 3c. Nav paths — gray wide polylines connecting adjacent map areas.
    #     Coordinates are cloud-frame mm (same origin as boundary/zones),
    #     so we use _cloud_to_px directly.  Drawn before the dock icon so
    #     the dock stays on top.  The canvas vertical-flip at the end of
    #     this function applies equally here.
    # -----------------------------------------------------------------------
    nav_paths = getattr(map_data, "nav_paths", ())
    if nav_paths:
        nav_color: tuple[int, int, int, int] = p.get("nav_path", (160, 160, 160, 255))  # type: ignore[assignment]
        nav_width_px: int = p.get("nav_path_width_px", 8)  # type: ignore[assignment]
        drawn_nav = 0
        for nav in nav_paths:
            if len(nav.path) < 2:
                continue
            pixel_pts: list[tuple[float, float]] = [
                _cloud_to_px(x_mm, y_mm, bx2, by2, grid)
                for x_mm, y_mm in nav.path
            ]
            draw.line(pixel_pts, fill=nav_color, width=nav_width_px, joint="curve")
            drawn_nav += 1
        _LOGGER.debug(
            "render_base_map: drew %d nav path(s)", drawn_nav
        )

    # -----------------------------------------------------------------------
    # 3.5. Maintenance points — light-brown 2× dock-radius circles with an
    #      "M" glyph. Drawn BEFORE the dock circle so the dock stays on top
    #      when they overlap (the dock is the more load-bearing landmark).
    #      cleanPoints come in cloud-frame mm — use _cloud_to_px.
    # -----------------------------------------------------------------------
    mp_radius_px = 2 * _DOCK_RADIUS_PX
    for mp in getattr(map_data, "maintenance_points", ()) or ():
        mpx, mpy = _cloud_to_px(
            float(mp.x_mm), float(mp.y_mm), bx2, by2, grid,
        )
        draw.ellipse(
            [mpx - mp_radius_px, mpy - mp_radius_px,
             mpx + mp_radius_px, mpy + mp_radius_px],
            fill=p["mp_fill"],
            outline=p["mp_outline"],
            width=2,
        )
        # Centre an "M" inside the circle. PIL's text placement varies by
        # font availability — load a TTF for consistent sizing; fall back
        # to the default bitmap font if the system has no TrueType.
        try:
            font = ImageFont.truetype(
                "DejaVuSans-Bold.ttf", size=int(mp_radius_px * 1.4)
            )
        except (OSError, IOError):
            font = ImageFont.load_default()
        # The whole canvas is FLIP_TOP_BOTTOM'd at the end so the rendered
        # map matches the Dreame app's orientation — which flips ALL pixel
        # content including text, leaving the "M" looking like a "W"
        # (upside-down M). Render the M onto a small RGBA overlay, rotate
        # it 180°, then paste at the maintenance-point centre — after the
        # canvas flip the rotation cancels and the M shows upright.
        glyph_size = int(mp_radius_px * 3)
        glyph = Image.new("RGBA", (glyph_size, glyph_size), (0, 0, 0, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        glyph_draw.text(
            (glyph_size / 2, glyph_size / 2),
            "M",
            fill=p["mp_text"],
            font=font,
            anchor="mm",
        )
        glyph = glyph.rotate(180)
        image.paste(
            glyph,
            (int(mpx - glyph_size / 2), int(mpy - glyph_size / 2)),
            glyph,
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
    # 4b. Obstacle polygons — semi-transparent blue filled polygons,
    #     same z-order and same drawing code as render_with_trail.
    #     Drawn AFTER the dock icon so they don't obscure it but BEFORE
    #     the final vertical flip (matching the base-map coordinate space).
    #     Used when the caller wants the no-trail background to include
    #     obstacles (e.g. _work_log_base_png for the replay card).
    #     Coordinates are cloud-frame metres — convert to pixels via
    #     _cloud_to_px (same as zone polygons above).
    # -----------------------------------------------------------------------
    if obstacles:
        from .live_map.trail import render_obstacle_overlay

        pixel_polys = render_obstacle_overlay(
            polygons=obstacles,
            bx2=bx2,
            by2=by2,
            pixel_size_mm=grid,
        )
        drawn_ob = 0
        for poly_px in pixel_polys:
            draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
            drawn_ob += 1
        _LOGGER.debug("render_base_map: drew %d obstacle polygon(s)", drawn_ob)

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

# _TRAIL_COLOR (70,70,70,220) removed in Phase 1 render-styling refresh
# (2026-05-17). Trail is now drawn in two passes: mowing strokes use
# _DEFAULT_PALETTE["mow_trail_color"] and traversal uses
# _DEFAULT_PALETTE["traversal_color"] — see render_with_trail.
#: Trail line width in pixels. v1.0.0a17: bumped from 2 to 3 so the
#: path is more visible against the lawn green.
_TRAIL_LINE_WIDTH: int = 3

# ---------------------------------------------------------------------------
# Replay-only obstacle overlay constants. Lifted from legacy
# protocol/trail_overlay.py:105-106 so the visual matches the pre-greenfield
# integration. RGBA — semi-transparent fill + slightly more opaque outline.
# ---------------------------------------------------------------------------
_OBSTACLE_FILL: tuple[int, int, int, int] = (90, 140, 230, 170)
_OBSTACLE_OUTLINE: tuple[int, int, int, int] = (40, 80, 200, 230)

#: Mower position marker. v1.0.0a19 lifts the legacy top-down
#: photograph of the A2 mower (originally
#: ``MAP_ROBOT_LIDAR_IMAGE_DREAME_LIGHT`` from
#: ``legacy/dreame/resources.py``) and rotates it by
#: ``MowerState.position_heading_deg`` so the icon's asymmetric front-
#: to-back shape shows the driving direction.
_MOWER_ICON_SIZE_PX: int = 32  # rendered footprint on the canvas

# Lazy-decoded icon cache — module-level singleton, decoded once.
_MOWER_ICON_CACHE: Image.Image | None = None


def _mower_icon() -> Image.Image:
    """Return the decoded RGBA mower icon, decoding on first call."""
    global _MOWER_ICON_CACHE
    if _MOWER_ICON_CACHE is None:
        import base64

        from ._resources import MOWER_ICON_PNG_B64
        _MOWER_ICON_CACHE = Image.open(
            io.BytesIO(base64.b64decode(MOWER_ICON_PNG_B64))
        ).convert("RGBA")
    return _MOWER_ICON_CACHE


# Cosmetic stripe-width tunable — wider than the literal blade width to
# produce visually distinct bands in the pre-start preview.
STRIPE_WIDTH_MM: int = 400


def render_main_view(
    map_data: MapData,
    *,
    legs: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    mower_position_m: tuple[float, float] | None = None,
    mower_heading_deg: float | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    palette: dict | None = None,
    lawn_mode: str = "dark",
    state: object | None = None,
    map_id: int = 0,
    mow_session: object | None = None,
    trail_width_px: int | None = None,
) -> bytes:
    """Render the active map's Main view: base + live trail + mower icon + obstacles.

    Main view never shows historical M_PATH (that's the per-map static
    cameras' job). Always renders against the active map's MapData.

    **Idle pre-start preview (T17)**:
    When ``state`` is provided and ``mow_session`` is not
    ``MowSession.IN_SESSION``, the renderer dispatches based on
    ``state.action_mode``:

    - ``ALL_AREAS`` or ``ZONE`` → dark-green lawn + light-green stripe
      overlay at the next-mow angle (using ``next_direction`` + the
      per-map ``state.last_all_area_mow_direction_deg``).
    - ``EDGE`` or ``SPOT`` → all-light-green base (no stripes); these
      modes follow the lawn boundary or individual spots, so a generic
      stripe is misleading.

    Legacy callers that omit ``state`` / ``mow_session`` get the
    existing trail render unchanged.

    Args:
        map_data: Decoded active map.
        legs: Live trail legs from LiveMapState.legs (None or empty → no trail).
        mower_position_m: Live mower position in cloud-frame metres.
        mower_heading_deg: Live mower heading in degrees (0-360).
        obstacle_polygons_m: Optional run-time obstacles (currently always
            empty until a live data source is identified — see spec
            "Non-goals" for context).
        palette: Optional palette override (forwarded to render_base_map).
        lawn_mode: Base lawn background mode. Defaults to ``"dark"`` because
            the main view is always rendered in a mow context (active session).
        state: Optional :class:`~.mower.state.MowerState`.  When provided
            (and the session is not active), enables the idle preview branch.
        map_id: Active map id used to look up per-map direction history in
            ``state.last_all_area_mow_direction_deg``.
        mow_session: Optional :class:`~.mower.state_snapshot.MowSession`.
            ``IN_SESSION`` forces the trail render regardless of ``state``.

    Returns:
        Raw PNG bytes.
    """
    # Deferred imports to avoid circular imports at module load.
    import time as _time
    from .mower.state_snapshot import MowSession
    from .mower.state import ActionMode
    from ._render_direction import next_direction
    from ._render_stripes import compute_stripe_overlay

    if state is not None and mow_session != MowSession.IN_SESSION:
        action = getattr(state, "action_mode", None)
        _t = _time.perf_counter()
        if action in (ActionMode.ALL_AREAS, ActionMode.ZONE):
            png = _render_pre_start_with_stripes(
                map_data,
                state=state,
                map_id=int(map_id),
                palette=palette,
                next_direction_fn=next_direction,
                compute_stripe_overlay_fn=compute_stripe_overlay,
            )
            _LOGGER.info(
                "[render-timing] _render_pre_start_with_stripes %.0fms png=%d",
                (_time.perf_counter() - _t) * 1000.0, len(png),
            )
            return png
        if action == ActionMode.EDGE:
            png = _render_pre_start_edge(map_data, palette=palette)
            _LOGGER.info(
                "[render-timing] _render_pre_start_edge %.0fms png=%d",
                (_time.perf_counter() - _t) * 1000.0, len(png),
            )
            return png
        if action == ActionMode.SPOT:
            png = _render_pre_start_spot(map_data, palette=palette)
            _LOGGER.info(
                "[render-timing] _render_pre_start_spot %.0fms png=%d",
                (_time.perf_counter() - _t) * 1000.0, len(png),
            )
            return png

    # Active session OR legacy caller (state=None) → existing trail render.
    return render_with_trail(
        map_data,
        legs,
        palette=palette,
        lawn_mode=lawn_mode,
        mower_position_m=mower_position_m,
        mower_heading_deg=mower_heading_deg,
        obstacle_polygons_m=obstacle_polygons_m,
        mowing_legs=mowing_legs,
        traversal_legs=traversal_legs,
        trail_width_px=trail_width_px,
    )


def _render_pre_start_with_stripes(
    map_data: MapData,
    *,
    state: object,
    map_id: int,
    palette: dict | None,
    next_direction_fn,
    compute_stripe_overlay_fn,
) -> bytes:
    """Dark-green base + stripe overlay at the next-mow angle.

    Used by ALL_AREAS / ZONE idle preview in ``render_main_view``.

    The stripe overlay is composited INSIDE ``render_base_map`` at the correct
    z-order (right after mowing-zone fills, before any other zone shapes) by
    passing it as the ``stripe_overlay`` kwarg.  This fixes two bugs present
    in the original post-composition approach:

    1. **Orientation**: The overlay is in PRE-FLIP pixel coordinates, matching
       the canvas BEFORE ``render_base_map``'s final FLIP_TOP_BOTTOM.
       Post-compositing after the flip caused stripes to appear upside-down
       relative to the underlying lawn.
    2. **Z-order**: Compositing after ``render_base_map`` placed stripes on top
       of every zone shape (exclusion, ignore-obstacle, spot zones), hiding
       them.  Inserting at layer 2.5 ensures subsequent zone layers paint on
       top of the stripes.
    """
    if not map_data.mowing_zones:
        # No zone to stripe; fall back to plain dark base.
        return render_base_map(map_data, palette=palette, lawn_mode="dark")

    # Compute next-mow angle using per-map direction history + pattern mode.
    last_dir = getattr(state, "last_all_area_mow_direction_deg", {}).get(map_id)
    mode = getattr(state, "settings_mowing_direction_mode", None)
    angle = next_direction_fn(last_direction_deg=last_dir, mode=mode)

    # Project the first mowing-zone polygon from cloud-frame mm to PRE-FLIP
    # pixel coordinates.  These match the canvas at composite-time inside
    # render_base_map (the final FLIP_TOP_BOTTOM hasn't happened yet).
    zone = map_data.mowing_zones[0]
    poly_px = [
        _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
        for x, y in zone.path
    ]

    # Resolve effective palette for colour lookup.
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    # Build the stripe overlay at canvas dimensions (pre-flip).
    width_px = int(map_data.width_px)
    height_px = int(map_data.height_px)
    stripe_width_px = STRIPE_WIDTH_MM / map_data.pixel_size_mm
    overlay = compute_stripe_overlay_fn(
        width=width_px,
        height=height_px,
        lawn_polygon_px=poly_px,
        angle_deg=angle,
        stripe_width_px=stripe_width_px,
        dark_color=p["dark_green"],
        light_color=p["zone_fills"][0],
    )

    # Pass the overlay into render_base_map to be composited at the correct
    # z-order (layer 2.5 — after mowing zones, before exclusion/spot/nav/dock).
    # The final FLIP_TOP_BOTTOM inside render_base_map handles orientation for
    # the overlay and all other layers uniformly.
    return render_base_map(
        map_data,
        palette=palette,
        lawn_mode="dark",
        stripe_overlay=overlay,
    )


def _render_pre_start_edge(map_data: MapData, *, palette: dict | None) -> bytes:
    """Light-green base + dotted darker-green lawn boundary.

    Idle preview for EDGE mode: shows the perimeter the mower will follow
    once start is pressed.  The dotted overlay is drawn POST-FLIP (after
    render_base_map's internal FLIP_TOP_BOTTOM) to keep orientation consistent
    with the base map.
    """
    from ._render_dotted import draw_dotted_polygon

    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for zone in map_data.mowing_zones:
        pts_px = [
            _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
            for x, y in zone.path
        ]
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _render_pre_start_spot(map_data: MapData, *, palette: dict | None) -> bytes:
    """Light-green base + dotted darker-green spot rectangles with interior fill.

    Idle preview for SPOT mode: shows each selectable spot zone as a filled
    dotted rectangle so the user can confirm which spots will be mowed.

    Spot zones are stored in *renderer* coords (post-midline-reflection) by the
    decoder, so we use ``_renderer_to_px`` (not ``_cloud_to_px``) to map them
    to pixel space.
    """
    from ._render_dotted import draw_dotted_polygon

    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for sz in getattr(map_data, "spot_zones", ()):
        if len(sz.points) < 3:
            continue
        pts_px = [
            _renderer_to_px(x, y, map_data.bx1, map_data.by1, map_data.pixel_size_mm)
            for x, y in sz.points
        ]
        # Interior fill: darker green for "this spot is eligible to mow".
        draw.polygon(pts_px, fill=(0, 100, 0, 110))
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def render_work_log(
    map_data: MapData,
    *,
    legs: list[Leg] | None = None,
    local_legs: list[Leg] | None = None,
    cloud_segments: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    legs_timeline: list[dict] | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    palette: dict | None = None,
    lawn_mode: str = "dark",
    trail_width_px: int | None = None,
) -> bytes:
    """Render an archived session: base + archived trail + archived obstacles.

    Differs from render_main_view: NO mower icon (the session is over,
    no live position), NO M_PATH (work logs are about ONE specific session,
    not cumulative history).

    Args:
        map_data: Decoded MapData for the map the session ran against.
        legs: Legacy single trail list (back-compat). Treated as
            ``cloud_segments`` by ``render_with_trail`` when ``local_legs``
            and ``cloud_segments`` are both absent. Prefer passing the two
            split kwargs explicitly.
        local_legs: Full s1p4 telemetry trail (includes traversal arcs).
            When supplied alongside ``cloud_segments``, the splitter
            classifies each point as mowing (green) or traversal (grey).
        cloud_segments: Cloud-curated mowing-only trail segments from
            session_summary.track_segments.
        legs_timeline: Ordered list of leg dicts, each with keys ``role``
            (``"mowing"`` | ``"traversal"``), ``start_ts``, ``end_ts``, and
            ``pts`` (list of ``(x_m, y_m)`` tuples).  When supplied,
            ``render_with_trail`` renders directly from this timeline,
            bypassing all splitter logic.  Preferred when the archive carries
            ``_legs_meta`` (Task 2+).
        obstacle_polygons_m: Archived obstacles in cloud-frame metres.
        palette: Optional palette override.
        lawn_mode: Base lawn background mode. Defaults to ``"dark"`` because
            work logs render a completed mow session context.
        trail_width_px: Trail stroke width in pixels. None → use the module
            default (_TRAIL_LINE_WIDTH). Forwarded to render_with_trail.

    Returns:
        Raw PNG bytes.
    """
    return render_with_trail(
        map_data,
        legs,
        local_legs=local_legs,
        cloud_segments=cloud_segments,
        mowing_legs=mowing_legs,
        traversal_legs=traversal_legs,
        legs_timeline=legs_timeline,
        palette=palette,
        lawn_mode=lawn_mode,
        mower_position_m=None,
        mower_heading_deg=None,
        obstacle_polygons_m=obstacle_polygons_m,
        trail_width_px=trail_width_px,
    )


def render_with_trail(
    map_data: MapData,
    legs: list[Leg] | None = None,
    palette: dict | None = None,
    mower_position_m: tuple[float, float] | None = None,
    mower_heading_deg: float | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    *,
    local_legs: list[Leg] | None = None,
    cloud_segments: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    legs_timeline: list[dict] | None = None,
    lawn_mode: str = "dark",
    trail_width_px: int | None = None,
) -> bytes:
    """Render the base map with a live trail overlay composited on top.

    Calls :func:`render_base_map` first to get the base PNG, then
    re-opens it with Pillow and draws trail polylines using
    :class:`PIL.ImageDraw`.  Pen-up gaps between legs are honoured —
    no line segment connects the last point of one leg to the first
    point of the next.

    Trail rendering uses a two-pass split so mowing strokes paint in
    ``mow_trail_color`` (light green) and traversal segments (dock
    returns, cross-map navigation not captured by cloud) paint in
    ``traversal_color`` (grey), drawn last so they stay on top.

    Args:
        map_data: Decoded map geometry (same as :func:`render_base_map`).
        legs: **Legacy positional arg.** List of legs from
            ``LiveMapState.legs`` (each leg is a list of ``(x_m, y_m)``
            tuples).  When ``cloud_segments`` is not supplied, ``legs``
            is treated as the cloud-authoritative mowing source (single-
            color grey trail, matching the pre-split behaviour).
        palette: Optional colour override forwarded to
            :func:`render_base_map`.
        mower_position_m: Optional mower position in metres (charger-relative).
        mower_heading_deg: Optional mower heading in degrees (0-360).
        obstacle_polygons_m: Optional list of obstacle polygons in
            metres-space (e.g. ``SessionSummary.obstacles``).  Drawn
            as semi-transparent blue filled polygons.  ``None`` (the
            default) or empty list draws nothing — used by every live
            caller; only the replay path passes non-empty data.
        local_legs: Full s1p4 telemetry trail in metres ``(x_m, y_m)``.
            Includes mowing strokes AND traversal (dock returns, cross-
            zone navigation).  When provided together with
            ``cloud_segments``, the splitter classifies each point.
        cloud_segments: Cloud-curated mowing-only segments in metres
            ``(x_m, y_m)``.  The authoritative "this was a cut" signal.
            When provided without ``local_legs``, behaves as the sole
            trail source (all mow-trail color, no traversal split).
        lawn_mode: Forwarded to :func:`render_base_map`. Defaults to
            ``"dark"`` — rendering a trail implies a mow context, so the
            lawn base uses dark-green and trail strokes in light-green
            overlay where mowed.
        trail_width_px: Trail stroke width in pixels. When ``None``,
            defaults to the module constant :data:`_TRAIL_LINE_WIDTH`.
            Controlled by the ``number.dreame_a2_mower_trail_render_width``
            entity (P4 render-styling refresh).
        legs_timeline: **Preferred path (v1.0.17+).** A list of leg
            records produced by :func:`session_card.build_legs_timeline`.
            Each record is a ``dict`` with keys:

            - ``role``: ``"mowing"`` | ``"traversal"``
            - ``start_ts``: capture epoch seconds (unused by renderer)
            - ``end_ts``: capture epoch seconds (unused by renderer)
            - ``pts``: ``list[tuple[float, float]]`` in metres

            When supplied this branch takes priority over all other leg
            arguments.  Records are painted in list order (later records
            paint over earlier ones) — unlike the legacy two-pass approach
            which always renders mowing first and traversal on top.

    Returns:
        Raw PNG bytes with the trail composited over the base map.
    """
    # Resolve effective trail width. Caller supplies None for the module
    # default so callers that don't care never have to know the constant.
    line_width: int = trail_width_px if trail_width_px is not None else _TRAIL_LINE_WIDTH
    from .live_map.trail import render_trail_overlay

    # -----------------------------------------------------------------------
    # NEW (v1.0.17): legs_timeline branch — paints records in capture order.
    # Takes priority over all legacy branches (early return).
    # -----------------------------------------------------------------------
    if legs_timeline is not None:
        base_png = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)

        # Resolve effective palette.
        p: dict = dict(_DEFAULT_PALETTE)
        if palette:
            p.update(palette)

        # Short-circuit when there's nothing to draw.
        if (
            not legs_timeline
            and mower_position_m is None
            and not obstacle_polygons_m
        ):
            return base_png

        # Flip back to unflipped coordinate frame for trail drawing.
        image = Image.open(io.BytesIO(base_png)).convert("RGBA")
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        draw = ImageDraw.Draw(image, "RGBA")

        mow_color: tuple = p.get("mow_trail_color", (178, 223, 138, 255))
        trav_color: tuple = p.get("traversal_color", (130, 130, 130, 220))

        drawn_legs = 0
        drawn_points = 0

        # One pass in record order — later records overwrite earlier ones.
        for rec in legs_timeline:
            pts = rec.get("pts", [])
            if len(pts) < 2:
                continue
            color = mow_color if rec.get("role") == "mowing" else trav_color
            leg_px = [
                (
                    (map_data.bx2 - x_m * 1000.0) / map_data.pixel_size_mm,
                    (map_data.by2 - y_m * 1000.0) / map_data.pixel_size_mm,
                )
                for x_m, y_m in pts
            ]
            draw.line(leg_px, fill=color, width=line_width)
            drawn_legs += 1
            drawn_points += len(leg_px)

        drawn_obstacles = 0
        if obstacle_polygons_m:
            from .live_map.trail import render_obstacle_overlay

            pixel_polys = render_obstacle_overlay(
                polygons=obstacle_polygons_m,
                bx2=map_data.bx2,
                by2=map_data.by2,
                pixel_size_mm=map_data.pixel_size_mm,
            )
            for poly_px in pixel_polys:
                draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
                drawn_obstacles += 1

        if mower_position_m is not None:
            try:
                mx = float(mower_position_m[0]) * 1000.0
                my = float(mower_position_m[1]) * 1000.0
                px_icon, py_icon = _cloud_to_px(
                    mx, my, map_data.bx2, map_data.by2, map_data.pixel_size_mm
                )
                icon = _mower_icon().resize(
                    (_MOWER_ICON_SIZE_PX, _MOWER_ICON_SIZE_PX),
                    resample=Image.Resampling.LANCZOS,
                )
                if mower_heading_deg is not None:
                    icon = icon.rotate(
                        -float(mower_heading_deg),
                        resample=Image.Resampling.BILINEAR,
                        expand=True,
                    )
                iw, ih = icon.size
                top_left = (int(round(px_icon - iw / 2)), int(round(py_icon - ih / 2)))
                image.alpha_composite(icon, dest=top_left)
                draw = ImageDraw.Draw(image, "RGBA")
            except (TypeError, ValueError, OSError):
                pass  # bad input or decode failure — drop the marker

        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        _LOGGER.debug(
            "render_with_trail(legs_timeline): drew %d legs / %d points / %d obstacles → %d-byte PNG",
            drawn_legs,
            drawn_points,
            drawn_obstacles,
            len(png_bytes),
        )
        return png_bytes

    # --- Resolve caller args ---
    # Preferred path (v1.0.17+): explicit mowing_legs/traversal_legs
    # already classified at capture time (no fuzzy matching needed).
    # `legs` positional is back-compat: treated as cloud_segments.
    have_explicit_split = mowing_legs is not None or traversal_legs is not None
    _local = local_legs or []
    _cloud = cloud_segments if cloud_segments is not None else (legs or [])

    # --- Start from the base-map PNG ---
    base_png = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)

    # Resolve effective palette so colour lookups don't repeat the merge.
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    # If we have nothing to overlay, the base map is the final output.
    if (
        not have_explicit_split
        and not _local
        and not _cloud
        and mower_position_m is None
        and not obstacle_polygons_m
    ):
        return base_png

    # --- Resolve mowing vs traversal lists ---
    if have_explicit_split:
        mowing_legs_resolved: list = list(mowing_legs or [])
        traversal_legs_resolved: list = list(traversal_legs or [])
    else:
        # No capture-time split available. Paint everything as mowing — the
        # fuzzy splitter was deleted along with TrailLayer in Task 11.
        mowing_legs_resolved = list(_local) if _local else list(_cloud)
        traversal_legs_resolved = []
    mowing_legs = mowing_legs_resolved
    traversal_legs = traversal_legs_resolved

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

    # --- Pass 1: mowing strokes in light-green ---
    mow_color: tuple = p.get("mow_trail_color", (178, 223, 138, 255))
    mow_pixel_legs = render_trail_overlay(
        legs=mowing_legs,
        bx2=map_data.bx2,
        by2=map_data.by2,
        pixel_size_mm=map_data.pixel_size_mm,
    )
    for leg_px in mow_pixel_legs:
        if len(leg_px) < 2:
            continue
        draw.line(leg_px, fill=mow_color, width=line_width)
        drawn_legs += 1
        drawn_points += len(leg_px)

    # --- Pass 2: traversal in grey — drawn LAST so it stays on top ---
    trav_color: tuple = p.get("traversal_color", (130, 130, 130, 220))
    trav_pixel_legs = render_trail_overlay(
        legs=traversal_legs,
        bx2=map_data.bx2,
        by2=map_data.by2,
        pixel_size_mm=map_data.pixel_size_mm,
    )
    for leg_px in trav_pixel_legs:
        if len(leg_px) < 2:
            continue
        draw.line(leg_px, fill=trav_color, width=line_width)
        drawn_legs += 1
        drawn_points += len(leg_px)

    drawn_obstacles = 0
    if obstacle_polygons_m:
        from .live_map.trail import render_obstacle_overlay

        pixel_polys = render_obstacle_overlay(
            polygons=obstacle_polygons_m,
            bx2=map_data.bx2,
            by2=map_data.by2,
            pixel_size_mm=map_data.pixel_size_mm,
        )
        for poly_px in pixel_polys:
            draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
            drawn_obstacles += 1

    # v1.0.0a19: mower-icon marker. Position is cloud-frame METERS
    # (MowerState.position_x_m / _y_m); heading is degrees (dock-relative
    # frame, 0..360). The icon's front points UP in the unrotated source
    # image — rotating CCW by heading aligns it with the cloud-frame
    # heading convention, then we paste at the converted pixel.
    if mower_position_m is not None:
        try:
            mx = float(mower_position_m[0]) * 1000.0
            my = float(mower_position_m[1]) * 1000.0
            px, py = _cloud_to_px(
                mx, my, map_data.bx2, map_data.by2, map_data.pixel_size_mm
            )
            icon = _mower_icon().resize(
                (_MOWER_ICON_SIZE_PX, _MOWER_ICON_SIZE_PX),
                resample=Image.Resampling.LANCZOS,
            )
            if mower_heading_deg is not None:
                # PIL rotate is CCW positive; cloud heading convention
                # appears to be CW from north. Negate so the icon faces
                # the actual driving direction.
                icon = icon.rotate(
                    -float(mower_heading_deg),
                    resample=Image.Resampling.BILINEAR,
                    expand=True,
                )
            iw, ih = icon.size
            top_left = (int(round(px - iw / 2)), int(round(py - ih / 2)))
            # alpha_composite-style paste so the icon's transparent
            # background doesn't replace the lawn under it.
            image.alpha_composite(icon, dest=top_left)
            draw = ImageDraw.Draw(image, "RGBA")
        except (TypeError, ValueError, OSError):
            pass  # bad input or decode failure — drop the marker

    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    _LOGGER.debug(
        "render_with_trail: drew %d legs / %d points / %d obstacles → %d-byte PNG",
        drawn_legs,
        drawn_points,
        drawn_obstacles,
        len(png_bytes),
    )
    return png_bytes


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
