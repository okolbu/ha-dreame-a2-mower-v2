"""Base-map renderer: lawn, zones, exclusions, dock icon, obstacles.

Exports: render_base_map.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from ._geometry import (
    _DEFAULT_PALETTE,
    _DOCK_RADIUS_PX,
    _OBSTACLE_FILL,
    _OBSTACLE_OUTLINE,
    _cloud_to_px,
    _renderer_to_px,
)

if TYPE_CHECKING:
    from ..cloud_state import MowPathData
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

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

        from .._resources import MOWER_ICON_PNG_B64
        _MOWER_ICON_CACHE = Image.open(
            io.BytesIO(base64.b64decode(MOWER_ICON_PNG_B64))
        ).convert("RGBA")
    return _MOWER_ICON_CACHE


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
        from ..live_map.trail import render_obstacle_overlay

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
