"""Main-view renderer: base + live trail + mower icon + pre-start previews.

Exports: render_main_view.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from .._png import encode_png
from ._geometry import _DEFAULT_PALETTE, _cloud_to_px, _renderer_to_px
from .base_map import render_base_map

if TYPE_CHECKING:
    from ..live_map.trail import Leg
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)

# Cosmetic stripe-width tunable — wider than the literal blade width to
# produce visually distinct bands in the pre-start preview.
STRIPE_WIDTH_MM: int = 400


def render_main_view(
    map_data: MapData,
    *,
    legs: list[Leg] | None = None,
    mowing_legs: list[Leg] | None = None,
    traversal_legs: list[Leg] | None = None,
    legs_timeline: list[dict] | None = None,
    mower_position_m: tuple[float, float] | None = None,
    mower_heading_deg: float | None = None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
    palette: dict | None = None,
    lawn_mode: str = "dark",
    state: object | None = None,
    map_id: int = 0,
    mow_session: object | None = None,
    trail_width_px: int | None = None,
    last_task_op: int | None = None,
    live_map_active: bool = False,
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
        legs_timeline: Preferred track-derived leg records (from
            ``session_card.derive_render_legs``). Forwarded to
            ``render_with_trail``, which prefers it over all other leg args.
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
        last_task_op: Optional last s2p50 TASK op code. Retained for
            diagnostics / logging only — the render decision no longer keys
            on it (see ``live_map_active``).  ``last_task_op`` is a PERSISTED
            snapshot field: after an HA reboot while idle AT a maintenance
            point, a finished to-point run is restored with ``last_task_op``
            still 109, which used to wrongly force the flat-green cruise view.
        live_map_active: Whether a live_map session is genuinely active RIGHT
            NOW (``coordinator.live_map.is_active()``).  This is the actual
            "a session is in progress" signal and the basis for skipping the
            idle pre-start preview — unlike ``last_task_op`` it reflects
            current state, so it is correctly False after a reboot-at-point.

    Returns:
        Raw PNG bytes.
    """
    # Deferred imports to avoid circular imports at module load.
    from ..mower.state_snapshot import MowSession
    from ..mower.state import ActionMode
    from .._render_direction import next_direction
    from .._render_stripes import compute_stripe_overlay

    # Reboot-survival fix: the idle-vs-active render decision keys on the
    # ACTUAL current state, never on the persisted ``last_task_op``.
    #
    # ``last_task_op`` is a PERSISTED snapshot field.  A to-point run (op=109)
    # that finished before an HA reboot is RESTORED with last_task_op=109 still
    # set — keying the "active non-mow session" skip on that value made the map
    # show flat green (the active-cruise view) instead of the striped idle
    # preview when the mower was actually parked at the maintenance point.
    #
    # The genuine "a session is in progress now" signal is
    # ``live_map.is_active()`` (passed as ``live_map_active``).  During a real
    # to-point cruise live_map is active (s2p1=1 → task_state_code becomes
    # active → begin_session fires) and the trail render is correct.  After a
    # reboot-at-point the session is finalized, live_map is NOT active, and the
    # striped preview is correct — regardless of the stale last_task_op.
    _is_active_session = bool(live_map_active)
    # REPOSITIONING: the mower has left the dock (~42s before the op echo).
    # mow_session is still BETWEEN_SESSIONS (s2p56 comes with the echo) and
    # live_map may not be active yet, but showing the striped pre-start preview
    # here would be wrong — a task IS underway, we just don't know which kind
    # yet. Treat REPOSITIONING as active so the plain dark-green base (trail
    # path) is shown instead.
    from ..mower.state_snapshot import CurrentActivity as _CurrentActivity
    _current_activity = getattr(state, "current_activity", None)
    _is_repositioning = _current_activity == _CurrentActivity.REPOSITIONING
    if state is not None and mow_session != MowSession.IN_SESSION and not _is_active_session and not _is_repositioning:
        action = getattr(state, "action_mode", None)
        if action in (ActionMode.ALL_AREAS, ActionMode.ZONE):
            png = _render_pre_start_with_stripes(
                map_data,
                state=state,
                map_id=int(map_id),
                palette=palette,
                next_direction_fn=next_direction,
                compute_stripe_overlay_fn=compute_stripe_overlay,
            )
            return _composite_mower_icon(
                png, map_data, mower_position_m, mower_heading_deg
            )
        if action == ActionMode.EDGE:
            png = _render_pre_start_edge(map_data, palette=palette)
            return _composite_mower_icon(
                png, map_data, mower_position_m, mower_heading_deg
            )
        if action == ActionMode.SPOT:
            png = _render_pre_start_spot(map_data, palette=palette)
            return _composite_mower_icon(
                png, map_data, mower_position_m, mower_heading_deg
            )

    # Active session OR legacy caller (state=None) → existing trail render.
    from .trail import render_with_trail
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
        legs_timeline=legs_timeline,
        trail_width_px=trail_width_px,
    )


def _composite_mower_icon(
    png: bytes,
    map_data: "MapData",
    mower_position_m: tuple[float, float] | None,
    mower_heading_deg: float | None,
) -> bytes:
    """Composite the mower icon onto *png* at *mower_position_m* and return
    the updated PNG.

    Called after every idle pre-start preview branch so the mower icon is
    visible between sessions — matching the Dreame app's "show the mower at
    its last-known position" behaviour.

    When *mower_position_m* is ``None`` the input PNG is returned unchanged
    (no allocation, no PIL round-trip).
    """
    if mower_position_m is None:
        return png

    from .base_map import _MOWER_ICON_SIZE_PX, _mower_icon
    from ._geometry import _cloud_to_px

    try:
        mx = float(mower_position_m[0]) * 1000.0
        my = float(mower_position_m[1]) * 1000.0
        px_icon, py_icon = _cloud_to_px(
            mx, my, map_data.bx2, map_data.by2, map_data.pixel_size_mm
        )
        # The pre-start renders apply FLIP_TOP_BOTTOM at the end; the icon
        # coordinate must be in the POST-FLIP pixel space (i.e. the y-axis
        # has already been inverted). py_icon from _cloud_to_px is PRE-FLIP,
        # so flip it here to match the output canvas.
        py_flipped = map_data.height_px - 1 - py_icon

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
        top_left = (
            int(round(px_icon - iw / 2)),
            int(round(py_flipped - ih / 2)),
        )
        image = Image.open(io.BytesIO(png)).convert("RGBA")
        image.alpha_composite(icon, dest=top_left)
        return encode_png(image)
    except (TypeError, ValueError, OSError):
        return png  # bad input or decode failure — return the unmodified base


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
    from .._render_dotted import draw_dotted_polygon

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
    return encode_png(image)


def _render_pre_start_spot(map_data: MapData, *, palette: dict | None) -> bytes:
    """Light-green base + dotted darker-green spot rectangles with interior fill.

    Idle preview for SPOT mode: shows each selectable spot zone as a filled
    dotted rectangle so the user can confirm which spots will be mowed.

    Spot zones are stored in *renderer* coords (post-midline-reflection) by the
    decoder, so we use ``_renderer_to_px`` (not ``_cloud_to_px``) to map them
    to pixel space.
    """
    from .._render_dotted import draw_dotted_polygon

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
    return encode_png(image)
