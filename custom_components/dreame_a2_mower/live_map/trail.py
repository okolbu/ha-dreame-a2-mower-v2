"""Trail rendering helpers.

Per spec §5.7 layer 3: decoupled from the state machine. Takes a
LiveMapState (or list of legs) and produces drawing primitives the
map_render module composites onto the F2 base map.

Coordinate transform
--------------------
Telemetry points arrive as (x_m, y_m) in metres, charger-relative,
in the same cloud frame as the F2 map geometry.  Converting to cloud-
frame millimetres: ``cloud_x = x_m * 1000``.

The F2 base-map renderer then maps cloud-frame mm to pixel coords via
the same ``_cloud_to_px`` flip formula:

    px = (bx2 - cloud_x) / pixel_size_mm
    py = (by2 - cloud_y) / pixel_size_mm

where ``bx2 = cloud_x_reflect - bx1`` (the right edge of the bounding
box) and ``pixel_size_mm = GRID_SIZE_MM = 50`` for the g2408.

``cloud_x_reflect`` from the decoder equals ``bx1 + bx2``, so bx2
equals ``cloud_x_reflect - bx1``.  However, ``render_trail_overlay``
receives ``bx2`` directly (it is stored as ``MapData.bx2``).  Callers
must pass ``bx2`` from the same ``MapData`` that produced the base PNG,
so the trail aligns with the lawn polygon.
"""
from __future__ import annotations

from typing import Iterable, Tuple

Point = Tuple[float, float]
Leg = Tuple[Point, ...]

# How many millimetres per metre — used to convert telemetry metres to
# the cloud-frame millimetre coords the map geometry uses.
_MM_PER_M = 1000.0


def render_trail_overlay(
    legs: Iterable[Leg],
    bx2: float,
    by2: float,
    pixel_size_mm: float,
) -> list[list[tuple[float, float]]]:
    """Convert (x_m, y_m) telemetry legs to pixel-coord leg paths.

    Applies the same ``_cloud_to_px`` flip formula as the F2 base-map
    renderer so the trail aligns visually with the lawn polygon:

        cloud_x = x_m * 1000
        cloud_y = y_m * 1000
        px = (bx2 - cloud_x) / pixel_size_mm
        py = (by2 - cloud_y) / pixel_size_mm

    Args:
        legs: Iterable of legs; each leg is an iterable of (x_m, y_m)
            tuples.  Points within a leg are connected by line segments.
            The pen lifts between legs (no segment bridging leg end to
            next leg start).
        bx2: Right edge of the map bounding box in cloud-frame mm.
            Must match the ``MapData.bx2`` used to render the base PNG.
        by2: Bottom edge of the map bounding box in cloud-frame mm.
            Must match the ``MapData.by2`` used to render the base PNG.
        pixel_size_mm: Grid resolution in mm/pixel (50.0 for g2408).

    Returns:
        List of pixel-coord legs.  Each element is a list of
        ``(px, py)`` float tuples corresponding to one input leg.
        Empty legs (0 or 1 points) are included as-is (ImageDraw.line
        silently ignores <2-point paths).  If ``legs`` is empty or all
        legs are empty the return value is an empty list.
    """
    result: list[list[tuple[float, float]]] = []
    for leg in legs:
        leg_px: list[tuple[float, float]] = []
        for x_m, y_m in leg:
            cloud_x = x_m * _MM_PER_M
            cloud_y = y_m * _MM_PER_M
            px = (bx2 - cloud_x) / pixel_size_mm
            py = (by2 - cloud_y) / pixel_size_mm
            leg_px.append((px, py))
        result.append(leg_px)
    return result
