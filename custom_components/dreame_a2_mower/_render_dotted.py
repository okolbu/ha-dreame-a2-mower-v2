"""Dotted-polygon drawing helper.

Extracted from the dead `TrailLayer._draw_dotted_polygon`. Used by the
EDGE / SPOT idle-preview branches in `map_render.render_main_view` to
outline the lawn boundary or each spot rectangle.
"""
from __future__ import annotations

from collections.abc import Sequence


def draw_dotted_polygon(
    draw,
    pts: Sequence[tuple[float, float]],
    color: tuple[int, int, int, int],
    width: int,
    dash_on_px: int,
    dash_off_px: int,
) -> None:
    """Draw a closed polygon as a dotted line using PIL primitives.

    Walks each edge of the polygon and emits short segments at
    `dash_on_px` intervals separated by `dash_off_px` gaps. Carries the
    dash budget across vertices so dashes don't visually reset at every
    corner.
    """
    if len(pts) < 2:
        return
    period = dash_on_px + dash_off_px
    loop = list(pts) + [pts[0]]  # close the polygon
    carry = 0.0  # leftover dash budget across edges
    for (x1, y1), (x2, y2) in zip(loop[:-1], loop[1:]):
        dx = x2 - x1
        dy = y2 - y1
        edge_len = (dx * dx + dy * dy) ** 0.5
        if edge_len < 1e-3:
            continue
        ux = dx / edge_len
        uy = dy / edge_len
        t = -carry  # negative t means we still owe a dash from prev edge
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
        carry = t - edge_len
