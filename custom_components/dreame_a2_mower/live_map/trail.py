"""Trail rendering helpers.

Per spec §5.7 layer 3: decoupled from the state machine. Takes a
LiveMapState (or list of legs) and produces drawing primitives the
map_render module composites onto the F2 base map.
"""
from __future__ import annotations

from typing import Iterable, Tuple

Point = Tuple[float, float]
Leg = Tuple[Point, ...]


def render_trail_overlay(legs: Iterable[Leg], cloud_x_reflect: float, cloud_y_reflect: float, pixel_size_mm: float):
    """Returns a list of (pixel_x, pixel_y) line-segment endpoints for
    each leg, ready to feed to ImageDraw.line().

    Coordinate transform: telemetry x_m, y_m → cloud-frame mm via the
    inverse of map_decoder's transform. F5.9 uses this to composite the
    trail onto the F2 base PNG.
    """
    # F5.9 implements. Stub returns empty list.
    return []
