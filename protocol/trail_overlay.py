"""Stateful path-overlay layer for the camera PNG.

The camera serves a static PNG for the lawn + exclusion + dock base.
The mower's historical trail is *not* in that image — Lovelace map
cards like ``xiaomi-vacuum-map-card`` don't render the ``path``
attribute, and re-rendering the full map on every ``s1p4`` arrival
would be wasteful (5 s cadence × ~200 ms re-render).

Design: three in-memory surfaces, incrementally maintained.

- **Base layer** — the map PNG as the renderer already produces it.
  Refreshed rarely.
- **Trail layer** — an RGBA image the same size. We ``ImageDraw.line``
  one segment onto it per ``s1p4`` arrival (≈1 ms) or repaint the
  whole thing once on replay.
- **Composed cache** — the final PNG bytes. Recomputed only when
  either layer's version counter bumps, so camera fetches at 4 Hz
  don't trigger more work than the underlying data actually changed.

Coordinate convention: path points / obstacle polygons / dock position
arrive in **metres** in the mower / charger-relative frame (same shape
as :class:`live_map.LiveMapState`). Calibration points (from the base
renderer) are ``{mower:{x,y}, map:{x,y}}`` tuples — mower coords are
**mm**, map coords are **pixels**. We scale × 1000 internally.
"""

from __future__ import annotations

import base64
import io
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

# Lazy-loaded shared cache for the decoded mower top-down icon. The
# base renderer (DreameMowerMapRenderer.render_mower) uses the same
# asset; loading once at module level avoids repeated base64 decode
# + PIL image instantiation per camera fetch.
_MOWER_ICON_CACHE: dict[int, Image.Image] = {}


def _get_mower_icon(target_size_px: int) -> Image.Image:
    """Return a cached, square-resized RGBA Image of the mower icon.

    Decodes `MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK` once at first call and
    keeps a per-size cache so the trail overlay can paste it on every
    compose without a fresh resize-and-decode per call."""
    if target_size_px not in _MOWER_ICON_CACHE:
        from ..dreame.resources import MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK
        raw = Image.open(
            io.BytesIO(base64.b64decode(MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK))
        ).convert("RGBA")
        _MOWER_ICON_CACHE[target_size_px] = raw.resize(
            (target_size_px, target_size_px),
            resample=Image.Resampling.LANCZOS,
        )
    return _MOWER_ICON_CACHE[target_size_px]


TRAIL_COLOR = (70, 70, 70, 220)             # dark grey — matches app
# Blades-up transit / return-to-dock — vivid medium blue, distinct
# from the dark grey mowing strokes so diagonal relocation lines
# read at a glance as "moving but not cutting". Earlier muted
# (90, 115, 170, 180) was too close to TRAIL_COLOR's value to
# distinguish on a low-contrast lawn background (field report
# 2026-04-22). Matches phase ∈ {1, 3} segments per s1p4 byte[8].
TRANSIT_COLOR = (50, 130, 230, 220)
TRAIL_WIDTH_PX = 4
# Live mower-position marker painted on the overlay at the end of the
# trail. The base renderer also paints a mower icon but only updates
# when the camera entity re-runs `update()` (heavy, throttled), so a
# live icon on the overlay — which recomposes on every telemetry frame
# via `extend_live` → `version++` — is the cheapest way to get real-
# time movement. Was previously a saturated orange-red dot; the user
# requested a larger icon (matching the dock's top-down photograph)
# 2026-04-27 for visibility on a busy lawn map.
MOWER_MARKER_ICON_SIZE_PX = 32     # noticeable but doesn't dominate
MOWER_MARKER_OUTLINE_RADIUS_PX = 18  # white halo behind the icon for contrast
# Direction triangle — small orange tag at the icon's "front" so the
# user can see which way the mower is facing without the icon
# rotating (icons are static top-down photographs and would require
# careful asset prep to look right at every angle). Matches the
# Dreame app's visual convention.
DIRECTION_TRIANGLE_COLOR = (255, 140, 30, 255)
DIRECTION_TRIANGLE_OUTLINE = (255, 255, 255, 255)
DIRECTION_TRIANGLE_SIZE_PX = 10
# Distance from icon centre out to the triangle apex.
DIRECTION_TRIANGLE_OFFSET_PX = (MOWER_MARKER_ICON_SIZE_PX // 2) + 2
# Live-trail pen-up threshold — consecutive s1p4 samples more than this
# far apart (metres) are treated as a session boundary / dock visit
# rather than a connected segment. Mower mow speed is <0.5 m/s over 5 s
# telemetry; normal frame-to-frame travel is ~2 m. Lowered from 5.0 to
# 3.0 (alpha.165) after user reported return-to-dock paths drawing
# straight lines through indoor regions — at the old 5 m threshold,
# frames where the mower's actual route curved around the lawn
# perimeter still connected as straight lines that crossed walls.
# At 3 m we err on breaking more often (= visible gaps where the
# return path is segmented) which the user prefers over plausible-but-
# wrong lines. Slightly above the typical-frame distance to avoid
# false pen-ups during sharp turns.
LIVE_GAP_PENUP_M = 3.0
DOCK_RADIUS_PX = 14
DOCK_COLOR = (50, 180, 50, 255)
DOCK_OUTLINE = (255, 255, 255, 255)
OBSTACLE_COLOR = (90, 140, 230, 170)         # blue — matches app
OBSTACLE_OUTLINE = (40, 80, 200, 230)

# Edge-mow visualisation — engaged when device._active_task_kind == "edge"
# (set by the op:101 firings in button.py). Mirrors the Dreame app's
# convention reported by the user 2026-04-27: light-green wash over the
# whole map, dotted-green perimeter on the unmowed edge, solid wider
# green for the mower's actual path-so-far.
EDGE_MOW_TINT_COLOR = (140, 220, 140, 50)        # light green wash
EDGE_MOW_PERIMETER_COLOR = (40, 160, 40, 230)    # dotted-line green
EDGE_MOW_PERIMETER_WIDTH = 3
EDGE_MOW_PERIMETER_DASH_ON_PX = 10
EDGE_MOW_PERIMETER_DASH_OFF_PX = 8
EDGE_MOW_TRAIL_COLOR = (40, 160, 40, 240)        # solid bright green
EDGE_MOW_TRAIL_WIDTH_PX = 6                      # marginally wider than 4


def _affine_from_calibration(
    calibration_points: Sequence[dict],
) -> tuple[float, float, float, float, float, float]:
    if not isinstance(calibration_points, (list, tuple)) or len(calibration_points) < 3:
        raise ValueError("need at least three calibration points")
    rows = []
    for cp in calibration_points[:3]:
        try:
            rows.append((
                float(cp["mower"]["x"]),
                float(cp["mower"]["y"]),
                float(cp["map"]["x"]),
                float(cp["map"]["y"]),
            ))
        except (TypeError, KeyError, ValueError) as ex:
            raise ValueError(f"malformed calibration point: {cp!r} ({ex})") from ex
    (x0, y0, u0, v0), (x1, y1, u1, v1), (x2, y2, u2, v2) = rows
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        raise ValueError("calibration points are colinear — cannot invert")
    a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det
    b = ((x1 - x0) * (u2 - u0) - (x2 - x0) * (u1 - u0)) / det
    c = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det
    d = ((x1 - x0) * (v2 - v0) - (x2 - x0) * (v1 - v0)) / det
    tx = u0 - a * x0 - b * y0
    ty = v0 - c * x0 - d * y0
    return a, b, c, d, tx, ty


class TrailLayer:
    """Incremental trail + dock + obstacle overlay, composited on demand.

    Same instance serves live and replay use cases. Live appends one
    point per tick (``extend_live``); replay repopulates the whole
    layer in one call (``reset_to_session``).

    Lifecycle:
        layer = TrailLayer(base_size=(2660, 2916), calibration=[...])
        layer.extend_live([1.0, 2.0])              # per s1p4 tick
        layer.set_dock([0.0, 0.0])                 # once on map rebuild
        layer.set_obstacles([[...], [...]])        # once per replay / new session
        png = layer.compose(base_png_bytes)        # per camera fetch
    """

    def __init__(
        self,
        base_size: tuple[int, int],
        calibration: Sequence[dict],
        trail_color: tuple[int, int, int, int] = TRAIL_COLOR,
        trail_width_px: int = TRAIL_WIDTH_PX,
        x_reflect_mm: float | None = None,
        y_reflect_mm: float | None = None,
    ) -> None:
        """``x_reflect_mm`` / ``y_reflect_mm`` — when supplied, reflect
        each input mower-mm coordinate through the given value before
        applying the calibration affine. Use this for the g2408's
        cloud-built map where the lawn mask drawn by the renderer
        lives in an X+Y-flipped frame relative to the calibration's
        naive `(x - bx1)/grid` transform. Set to `bx1 + bx2` / `by1 + by2`
        respectively to align the trail with the lawn.
        """
        self._size = base_size
        self._aff = _affine_from_calibration(calibration)
        self._x_reflect_mm = x_reflect_mm
        self._y_reflect_mm = y_reflect_mm
        self._trail_color = trail_color
        self._trail_width = trail_width_px
        self._trail = Image.new("RGBA", base_size, (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._trail, "RGBA")
        self._last_point: tuple[float, float] | None = None
        # Metres version of `_last_point` for the pen-up jump test.
        self._last_point_m: tuple[float, float] | None = None
        self._dock: tuple[float, float] | None = None
        self._obstacle_polys: list[list[tuple[float, float]]] = []
        # Latest mower heading in degrees, populated externally by the
        # camera entity from MOWING_TELEMETRY.heading_deg. None hides
        # the direction-triangle on the live-icon overlay; any float
        # value is interpreted as the same convention the s1p4 byte[6]
        # decoder uses (see protocol/telemetry.py).
        self.last_heading_deg: float | None = None
        # Edge-mow visualisation flag and per-zone perimeter polygons
        # in PIXEL coords. When active, compose() applies a light-green
        # wash + dotted perimeter and `extend_live` paints in solid
        # bright green / wider stroke. See `set_edge_mow_active` and
        # `set_zone_perimeters`.
        self._edge_mow_active: bool = False
        self._zone_perimeters_px: list[list[tuple[float, float]]] = []
        self._default_trail_color = trail_color
        self._default_trail_width = trail_width_px
        # Version bumped on every mutation; used by callers to cache
        # composed PNG bytes.
        self.version: int = 0

    # ------------------- live path -------------------

    def extend_live(self, point_m: Sequence[float]) -> None:
        """Draw a segment from the previous live point to ``point_m``.

        Call this once per ``s1p4`` arrival. The first call after a
        reset / new session only remembers the point without drawing
        (there's no previous point to connect to).

        Jumps larger than ``LIVE_GAP_PENUP_M`` metres are treated as a
        pen-up / new segment (the mower can't physically travel that
        far in one 5-second telemetry interval, so it's a dock visit,
        a GPS correction, or a telemetry drop — drawing a straight
        line across would produce a ghost segment).

        ``point_m`` may be a 2-element ``[x, y]`` (legacy / no phase)
        or a 3-element ``[x, y, phase]`` where phase is the s1p4
        byte[8]. When phase is 1 (TRANSIT) or 3 (RETURNING) the
        segment renders in TRANSIT_COLOR — visually distinct from
        normal mowing strokes so the diagonal relocation lines
        characteristic of irregular lawns can be seen without
        being mistaken for cut area.
        """
        if point_m is None or len(point_m) < 2:
            return
        new_x_m = float(point_m[0])
        new_y_m = float(point_m[1])
        phase = int(point_m[2]) if len(point_m) >= 3 else None
        px = self._m_to_px(new_x_m, new_y_m)
        if self._last_point is not None and self._last_point_m is not None:
            dx = new_x_m - self._last_point_m[0]
            dy = new_y_m - self._last_point_m[1]
            if (dx * dx + dy * dy) ** 0.5 <= LIVE_GAP_PENUP_M:
                # The 3rd element is now a derived "cutting" flag
                # (alpha.73): 1 = firmware area_mowed_m2 ticked
                # forward in this segment; 0 = it stayed constant
                # (blades-up transit). Use TRANSIT_COLOR when we
                # know cutting=0, otherwise default colour.
                color = (
                    TRANSIT_COLOR if phase == 0 else self._trail_color
                )
                self._draw.line(
                    [self._last_point, px],
                    fill=color,
                    width=self._trail_width,
                    joint="curve",
                )
                self.version += 1
        self._last_point = px
        self._last_point_m = (new_x_m, new_y_m)

    # ------------------- replay -------------------

    def reset(self) -> None:
        """Clear the trail + dock + obstacles; bump version."""
        self._trail = Image.new("RGBA", self._size, (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._trail, "RGBA")
        self._last_point = None
        self._last_point_m = None
        self._obstacle_polys = []
        self._dock = None
        self.version += 1

    def reset_to_session(
        self,
        completed_track: Iterable[Iterable[Sequence[float]]] | None = None,
        path: Iterable[Sequence[float]] | None = None,
        obstacle_polygons: Iterable[Iterable[Sequence[float]]] | None = None,
        dock_position: Sequence[float] | None = None,
    ) -> None:
        """Repaint the layer from a complete session snapshot (replay)."""
        self.reset()
        if completed_track:
            for seg in completed_track:
                pts = [self._m_to_px(p[0], p[1]) for p in seg if len(p) >= 2]
                if len(pts) >= 2:
                    self._draw.line(
                        pts, fill=self._trail_color, width=self._trail_width, joint="curve"
                    )
        if path:
            # Group consecutive entries by colour (alpha.73): the
            # 3rd element is the derived cutting flag (1 = blades
            # down, 0 = blades up transit, None = unknown / legacy).
            # Each contiguous same-colour run becomes one
            # ImageDraw.line so curve smoothing is preserved within
            # the run; we carry the last point of the previous run
            # as the first point of the next so colour transitions
            # join visually without a gap.
            current_color = None
            current_pts: list[tuple[float, float]] = []
            last_pt: tuple[float, float] | None = None
            for entry in path:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                cutting = int(entry[2]) if len(entry) >= 3 else None
                color = TRANSIT_COLOR if cutting == 0 else self._trail_color
                px = self._m_to_px(entry[0], entry[1])
                if color != current_color:
                    if current_color is not None and len(current_pts) >= 2:
                        self._draw.line(
                            current_pts, fill=current_color,
                            width=self._trail_width, joint="curve",
                        )
                    current_pts = [last_pt] if last_pt is not None else []
                    current_color = color
                current_pts.append(px)
                last_pt = px
            if current_color is not None and len(current_pts) >= 2:
                self._draw.line(
                    current_pts, fill=current_color,
                    width=self._trail_width, joint="curve",
                )
            if last_pt is not None:
                self._last_point = last_pt
        if obstacle_polygons:
            self.set_obstacles(obstacle_polygons)
        if dock_position is not None:
            self.set_dock(dock_position)
        self.version += 1

    # ------------------- static layers -------------------

    def set_dock(self, dock_m: Sequence[float] | None) -> None:
        if not dock_m or len(dock_m) < 2:
            self._dock = None
        else:
            self._dock = self._m_to_px(float(dock_m[0]), float(dock_m[1]))
        self.version += 1

    def set_obstacles(
        self, polygons: Iterable[Iterable[Sequence[float]]] | None
    ) -> None:
        self._obstacle_polys = []
        if polygons:
            for poly in polygons:
                pts = [self._m_to_px(p[0], p[1]) for p in poly if len(p) >= 2]
                if len(pts) >= 3:
                    self._obstacle_polys.append(pts)
        self.version += 1

    def set_zone_perimeters(
        self,
        zones_m: Iterable[Iterable[Sequence[float]]] | None,
    ) -> None:
        """Store zone polygons (in metres) as pixel coords for the
        edge-mow dotted-perimeter render. Caller passes one polygon
        per zone — no need to close (the polygon draw closes itself).

        Idempotent / cheap: if `compose()` re-runs without `set_*`
        calls in between, the already-converted pixel polygons are
        reused.
        """
        self._zone_perimeters_px = []
        if zones_m:
            for poly in zones_m:
                pts = [
                    self._m_to_px(p[0], p[1])
                    for p in poly
                    if isinstance(p, (list, tuple)) and len(p) >= 2
                ]
                if len(pts) >= 3:
                    self._zone_perimeters_px.append(pts)
        self.version += 1

    def set_edge_mow_active(self, active: bool) -> None:
        """Toggle the edge-mow visualisation mode.

        While active:
          - `compose()` paints a light-green wash over the base PNG
            and draws each stored zone perimeter as a dotted green
            line (the "unmowed edge" effect).
          - `extend_live` paints new segments with a brighter green
            and a slightly wider stroke (the "solid line where mowed"
            effect — past segments stay in their original colour).

        Toggling off restores the default trail colour / width for
        future strokes; existing strokes keep whatever colour they
        were drawn with.
        """
        if bool(active) == self._edge_mow_active:
            return
        self._edge_mow_active = bool(active)
        if self._edge_mow_active:
            self._trail_color = EDGE_MOW_TRAIL_COLOR
            self._trail_width = EDGE_MOW_TRAIL_WIDTH_PX
        else:
            self._trail_color = self._default_trail_color
            self._trail_width = self._default_trail_width
        self.version += 1

    # ------------------- compose -------------------

    def compose(self, base_png: bytes) -> bytes:
        """Composite base + trail + obstacles + dock into a PNG."""
        base = Image.open(io.BytesIO(base_png)).convert("RGBA")
        if base.size != self._size:
            # Base came out a different size than we sized the trail for
            # (e.g. the renderer applied a different crop). Resize the
            # trail to match so the compose still works, even though the
            # geometry will be slightly off until the next reset.
            self._trail = self._trail.resize(base.size, Image.Resampling.BILINEAR)
            self._size = base.size

        # Edge-mow visualisation — translucent green wash painted on
        # the base, then each zone perimeter drawn as a dotted line.
        # Done before the trail composite so the trail strokes ride
        # on top of the wash and read as "what's been covered so far".
        if self._edge_mow_active:
            wash = Image.new("RGBA", base.size, EDGE_MOW_TINT_COLOR)
            base = Image.alpha_composite(base, wash)
            if self._zone_perimeters_px:
                perim_draw = ImageDraw.Draw(base, "RGBA")
                for poly in self._zone_perimeters_px:
                    self._draw_dotted_polygon(
                        perim_draw,
                        poly,
                        EDGE_MOW_PERIMETER_COLOR,
                        EDGE_MOW_PERIMETER_WIDTH,
                        EDGE_MOW_PERIMETER_DASH_ON_PX,
                        EDGE_MOW_PERIMETER_DASH_OFF_PX,
                    )

        # Single alpha-composite per layer — `paste` with mask would
        # dim the colours a second time (trail alpha gets multiplied
        # by overlay alpha), so we start from the trail image directly
        # and draw obstacles + dock onto IT, then compose once.
        overlay = self._trail.copy()
        draw = ImageDraw.Draw(overlay, "RGBA")

        # Live mower position: paste the mower icon at the last
        # telemetry point. Updates on every `extend_live` call, so
        # the icon follows the mower without waiting for the heavy
        # base-PNG re-render. The base renderer's mower icon may
        # lag wherever update() last painted it (typically dock)
        # until the camera's next throttled refresh — this overlay
        # icon is what actually shows the current position.
        # White halo behind for contrast against grass/trail. Small
        # orange triangle at the heading direction shows facing.
        if self._last_point is not None:
            px, py = self._last_point
            halo_r = MOWER_MARKER_OUTLINE_RADIUS_PX
            draw.ellipse(
                [(px - halo_r, py - halo_r), (px + halo_r, py + halo_r)],
                fill=(255, 255, 255, 220),
            )
            icon = _get_mower_icon(MOWER_MARKER_ICON_SIZE_PX)
            half = MOWER_MARKER_ICON_SIZE_PX // 2
            overlay.paste(
                icon,
                (int(px) - half, int(py) - half),
                icon,
            )
            heading = self.last_heading_deg
            if heading is not None:
                import math
                # Heading convention: byte[6] is `(byte/255)*360` per
                # protocol/telemetry.py. PIL Y axis grows downward, so
                # for "0° = north / up" we use (sin, -cos). If the
                # triangle ends up pointing the wrong way the user
                # will spot it immediately and we rotate the
                # convention by 90/180.
                rad = math.radians(heading)
                dx = math.sin(rad)
                dy = -math.cos(rad)
                cx = px + dx * DIRECTION_TRIANGLE_OFFSET_PX
                cy = py + dy * DIRECTION_TRIANGLE_OFFSET_PX
                # Triangle apex at (cx, cy) projected forward another
                # half-size; base at (cx, cy) with two corners
                # perpendicular to the heading vector.
                apex_x = cx + dx * (DIRECTION_TRIANGLE_SIZE_PX * 0.7)
                apex_y = cy + dy * (DIRECTION_TRIANGLE_SIZE_PX * 0.7)
                # Perpendicular direction for the triangle base.
                perp_x = -dy
                perp_y = dx
                base_half = DIRECTION_TRIANGLE_SIZE_PX * 0.5
                base_l = (cx + perp_x * base_half, cy + perp_y * base_half)
                base_r = (cx - perp_x * base_half, cy - perp_y * base_half)
                draw.polygon(
                    [(apex_x, apex_y), base_l, base_r],
                    fill=DIRECTION_TRIANGLE_COLOR,
                    outline=DIRECTION_TRIANGLE_OUTLINE,
                )

        for poly in self._obstacle_polys:
            draw.polygon(poly, fill=OBSTACLE_COLOR, outline=OBSTACLE_OUTLINE)

        # Note: dock marker intentionally NOT drawn here. The upstream
        # DreameMowerMapRenderer already paints a charger icon at
        # `map_data.charger_position` (set in `_build_map_from_cloud_data`
        # to the reflected cloud-origin + physical-station offset).
        # Drawing another disc here caused a visible doubling with the
        # TrailLayer's version a few pixels off because the two sources
        # derive the coord differently — the upstream uses cloud (0,0)
        # + 800 mm reflect, while ours pulled from each session's
        # summary `dock` field which varies per recording. Kept
        # `self._dock` state + setter for API compatibility in case a
        # future consumer wants to draw a secondary marker.

        composed = Image.alpha_composite(base, overlay)
        # Preserve the alpha channel — "outside the lawn" pixels are
        # fully transparent in the upstream renderer's colour scheme,
        # and flattening to RGB here would fill them with black. Keep
        # the PNG in RGBA so the Lovelace card's page background shows
        # through the way the app does it.
        buf = io.BytesIO()
        composed.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    # ------------------- helpers -------------------

    @staticmethod
    def _draw_dotted_polygon(
        draw: ImageDraw.ImageDraw,
        pts: Sequence[tuple[float, float]],
        color: tuple[int, int, int, int],
        width: int,
        dash_on_px: int,
        dash_off_px: int,
    ) -> None:
        """Draw a closed polygon as a dotted line using PIL primitives.

        PIL's `ImageDraw.line` doesn't support dashes natively; we walk
        each polygon edge and emit short line segments at `dash_on_px`
        intervals separated by `dash_off_px` gaps. Cheap (a few hundred
        segments per zone perimeter at most) and avoids dragging in a
        heavier dependency just for this visual flourish.
        """
        if len(pts) < 2:
            return
        period = dash_on_px + dash_off_px
        loop = list(pts) + [pts[0]]  # close the polygon
        carry = 0.0  # leftover dash budget across edges so dashes
                    # don't visually reset at every vertex
        for (x1, y1), (x2, y2) in zip(loop[:-1], loop[1:]):
            dx = x2 - x1
            dy = y2 - y1
            edge_len = (dx * dx + dy * dy) ** 0.5
            if edge_len < 1e-3:
                continue
            ux = dx / edge_len
            uy = dy / edge_len
            t = -carry  # negative t means we still owe a dash from the
                       # previous edge — start mid-cycle
            while t < edge_len:
                seg_start = max(t, 0.0)
                seg_end = min(t + dash_on_px, edge_len)
                if seg_end > seg_start:
                    sx = x1 + ux * seg_start
                    sy = y1 + uy * seg_start
                    ex = x1 + ux * seg_end
                    ey = y1 + uy * seg_end
                    draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
                t += period
            # `t` is now the position of the next dash start; the
            # carry-over for the next edge is how far past edge_len
            # that next dash start is.
            carry = t - edge_len

    def _m_to_px(self, x_m: float, y_m: float) -> tuple[float, float]:
        a, b, c, d, tx, ty = self._aff
        mm_x = x_m * 1000.0
        mm_y = y_m * 1000.0
        if self._x_reflect_mm is not None:
            mm_x = self._x_reflect_mm - mm_x
        if self._y_reflect_mm is not None:
            mm_y = self._y_reflect_mm - mm_y
        return (a * mm_x + b * mm_y + tx, c * mm_x + d * mm_y + ty)
