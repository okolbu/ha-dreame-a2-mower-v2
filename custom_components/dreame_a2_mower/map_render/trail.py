"""Trail renderer: base + live/archived trail polylines + mower icon.

Exports: render_with_trail.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from .._png import encode_png
from ._geometry import _DEFAULT_PALETTE, _OBSTACLE_FILL, _OBSTACLE_OUTLINE, _cloud_to_px
from .base_map import _MOWER_ICON_SIZE_PX, _mower_icon, render_base_map

if TYPE_CHECKING:
    from ..live_map.trail import Leg
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

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
    from ..live_map.trail import render_trail_overlay

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
            from ..live_map.trail import render_obstacle_overlay

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
        png_bytes = encode_png(image)

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
        from ..live_map.trail import render_obstacle_overlay

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
    png_bytes = encode_png(image)

    _LOGGER.debug(
        "render_with_trail: drew %d legs / %d points / %d obstacles → %d-byte PNG",
        drawn_legs,
        drawn_points,
        drawn_obstacles,
        len(png_bytes),
    )
    return png_bytes
