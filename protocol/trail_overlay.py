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

# Mower top-down icon (base64-encoded PNG). Originally lives in
# dreame/resources.py in the HA integration layer; inlined here so
# protocol/ is self-contained with no cross-package dependencies.
_MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK = (
    "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAABHEElEQVR42u29eZRkd3Xn+fktb4s119pVJam0oH1nEQgLgcA9NNiApbbbbdpusHHjoe2xPed4pj2npOPejpdu2+22Dfa4x810DyPZNKYxO5QwloRBMkIbQoKqUu1LbhGREfHivff7/eaPt2RkVmZJ2KSs6p4452VkRsb23u/+7vK9936v4GVyc84JIYRbWlp+c7td/wshRPzBD37Qe9/73peued4dQogvFr9f1Oksv/qaa64xH/jAz/wmiO39ft8tLCwIz/MQQnD8+HF838cYg3MOay3PHzqEkBJjLUopnHM0m0327NnDaDTCOUeWZUxMTFCr1VBKEYYhnufZLVu2yD+5//5feu97f/L5u+5655IQ4tMbnJLYt2+fuPfeey0v45t4uQnA4mLv9omJxleEEAlgnXM+EC4uLoqpqSn38MMP/4M0NW975pln0mef/daN3/nOgQufeOIJjh49SpIk1Go1pJR4nkeapjSbTYwx+L6PtRZjDLVaDQcIKbHGoJQiTVOUUgghMMbgeR7D4ZAkSfB9H4AkSegvLzM5NcU111zDNddcwwW7L/iTG66/UfX63fs/8P73//k//+e/Jn/8x3/Q1uv17mAw4DOf+Uz9zW9+cwxYIYT7/wVgg9t99zm1uPghWe74MAz40pf+4h9+9rNf+N/m5+cu/fa3v+2+/vWvi9OnT/YvvviSqSRJGY1igKxWq1Gv15VSSqRpWu1iz/PwfR/nHM7l197zPJIkIarVcM6hlGJ5eZlWq4WUElMIRPn6QjgBqNfrJEmCc850Oh03GAz09PQ0YRjS6/UYDAajSy+/xF55xRXyC5/7/O//yr/8l507br/9uBDig4D4vu/7PvUbv/Eb4uabb07/hxOA++67Tz311FPu3nvvdc45hBDs27dPABLg3nvvzYqL3QS8f//vf++e/fu/+IHPfvYzaK1pt9vUajXCMCTLsiyOY3zfl0opmSRJtYuFEAghSNMUz/PIsqxaRGMM9Xqd4XCIlJLMGFqtFsvLy7TbbZaWlmi1WlhrkVJWqn80GhFFEXEc02w2WV5eZnJyEs/zXJZlRimF53nKWiO0r+kvLxMPY6amp3jTm9705A+964c+vW3r1n8thFgoLofav3+/OHPmjLv77rttKWBCCO677z55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L5pZa/tLAUiKvsV6vc6nP/1pTp86jRCCU6dOccP116c/8AM/cEIIYTfT+39JBEAIYR555BF9zz33PPPa1772z2655Ra5sLCYBUHAqVMnefTRvybLMgaDwcYsHhtc7HN85lnQrNaaK664gle/6lU0m21uf+MdzMzM0h+MaLcnee1rb+N1r3s9k5PT3HTTzQhZIoE5XFtqqrWfs5EfcC68P8sy4tGIqFbjyOHneeCBB8oUsNu9e7d3yy23ZFu3bv2l4jOyzRaATXczb7rppuzmm292zrl9Dz/88D/6xje+oaSUzjknHnzwL7nhxhvxC149oEi7roZM/zYTO0oOX2stN954I7t37+axxx5j587tCJsipcb3A/buvZhdu/ZUoYQsqofKjqa1MvdCM4bHVf84EabJMqwxSN/j4x//b5w8eZLt27c5IYR9/etf37vsslf8TJIk8v777xebkf59yQVACOGcc1IIcejhhx/+j1/+8pff85WvfMW0Wm31/KEDfPELX+AHf/AH6ff71Gq1KgtXOlBSSsSaC7zetPH1iJfH77XWZFnGli1bePOb35z329m8eGOF3dMxTmezqrT7HLZ//PPLhtYSBhZCEMcxUZTXLSRpivY8Dh08yGc++xnqjTrz8/PZbbfdJq+7/oZP7ty57b988IMf9N73vvelvAS3l2psnNu3b5//mte85r1vfvObH9i5c4dcXFxMG802f/mXf8mxY8eqUGk4HFb28lw7az0OoI3uS/+i1Aa5gFmsE/kQCuNI06wCnVa4gfJjI5DnXDDwqrEzxd9JklSP/d7v/z79/qD0LfSb33yneutb3/zL+/btkz/1Uz+VvUTr8pJNDnVXXXWVAXj3u9/97974xjc6QNRqNYbDIZ/4xCeIooh+v0+aptWx1pFau/hrncEXQwWzyk9wCpAlGx84iXOiApBKAahQhnMI2npwdunUln5OyZX0xS98ga9//et4WtPv97N3vOOd4pW3vPKPhBAH77nnHjYL9/+71ADcfffdZt++fXLXrl0ff+97f/KZ17zmVj0/P2+jKOKJJ57gscceo1arMRqNVpmA9ZypFxN+rbfwqx9jjMhx7FhLa+x4wc9du9NLDVZqsdIsWJsnpT70oQ8xMzNDfzDIXvnKV6q3ve3v/+Urrrz0PR/84Ac94CVb/JdUAADuuece7rvvPv+WW255y1vf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"
)

# Lazy-loaded shared cache for the decoded mower top-down icon.
_MOWER_ICON_CACHE: dict[int, Image.Image] = {}


def _get_mower_icon(target_size_px: int) -> Image.Image:
    """Return a cached, square-resized RGBA Image of the mower icon.

    Decodes `_MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK` once at first call and
    keeps a per-size cache so the trail overlay can paste it on every
    compose without a fresh resize-and-decode per call."""
    if target_size_px not in _MOWER_ICON_CACHE:
        raw = Image.open(
            io.BytesIO(base64.b64decode(_MAP_ROBOT_LIDAR_IMAGE_DREAME_DARK))
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
        # Only render the icon once at least one segment has been drawn
        # (version > 0 after the second point). This avoids painting a
        # spurious marker on the first telemetry frame where we have a
        # starting position but no confirmed travel yet.
        if self._last_point is not None and self.version > 0:
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
