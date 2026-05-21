"""Work-log renderer: archived session base + trail + obstacles.

Exports: render_work_log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..live_map.trail import Leg
    from ..map_decoder import MapData

_LOGGER = logging.getLogger(__name__)


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
    from . import render_with_trail
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
