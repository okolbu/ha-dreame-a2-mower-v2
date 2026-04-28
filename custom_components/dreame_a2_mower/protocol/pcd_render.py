"""PNG renderer for LiDAR point clouds.

The firmware bakes a height-gradient into the ``rgb`` field (green at
ground, blue for walls, magenta/red for roof peaks), so we just need
to project XYZ to pixels with painter's-algorithm depth sorting and
colour each surviving sample with its own RGB.

Two projections are supported:

- ``tilt_deg=0`` — pure orthographic top-down (legacy default).
- ``tilt_deg>0`` — oblique/bird's-eye. The camera sits south of the
  scene, elevated, pitched forward by ``tilt_deg``. High-Z points
  appear higher in the image than their ground footprint ("roofs
  leaning north"), giving a recognisable 3D-ish sense of structure
  without actually rotating the view azimuth. 45° is the classic
  sweet spot.

Intentionally dependency-free beyond Pillow and NumPy (both already
required by the integration's map renderer).
"""

from __future__ import annotations

import io
import math
from typing import Tuple

import numpy as np
from PIL import Image

from .pcd import PointCloud


def render_top_down(
    cloud: PointCloud,
    width: int = 512,
    height: int = 512,
    margin_px: int = 8,
    background: Tuple[int, int, int] = (0, 0, 0),
    tilt_deg: float = 0.0,
) -> bytes:
    """Render ``cloud`` as a PNG and return the encoded bytes.

    Parameters
    ----------
    cloud
        Parsed point cloud. Must carry non-empty ``xyz`` and ``rgb``.
    width, height
        Output image dimensions in pixels.
    margin_px
        Padding around the projected bounding box. Keeps edge points
        off the literal edge.
    background
        RGB tuple painted on empty pixels (default black — matches the
        Dreame app's dark-themed 3D view).
    tilt_deg
        Camera pitch in degrees. ``0`` = pure top-down. ``45`` = classic
        bird's-eye. Camera azimuth is fixed looking north; only pitch
        is adjustable.
    """
    xyz = cloud.xyz
    rgb = cloud.rgb
    if xyz.size == 0:
        return _encode_empty(width, height, background)

    # Pitch-only rotation: tilt the scene forward so +Z contributes to the
    # projected vertical axis. At tilt=0 this is a no-op and y_eff == y.
    tilt_rad = math.radians(tilt_deg)
    cos_t, sin_t = math.cos(tilt_rad), math.sin(tilt_rad)
    y_eff = xyz[:, 1] * cos_t + xyz[:, 2] * sin_t

    x_min, x_max = float(xyz[:, 0].min()), float(xyz[:, 0].max())
    y_eff_min, y_eff_max = float(y_eff.min()), float(y_eff.max())

    span_x = max(x_max - x_min, 1e-6)
    span_y = max(y_eff_max - y_eff_min, 1e-6)

    usable_w = max(width - 2 * margin_px, 1)
    usable_h = max(height - 2 * margin_px, 1)
    # Aspect-preserving scale.
    scale = min(usable_w / span_x, usable_h / span_y)

    # Center the cloud in the canvas.
    content_w = span_x * scale
    content_h = span_y * scale
    offset_x = margin_px + (usable_w - content_w) * 0.5
    offset_y = margin_px + (usable_h - content_h) * 0.5

    px = ((xyz[:, 0] - x_min) * scale + offset_x).astype(np.int32)
    # Image y grows downward. World +Y and high Z both shift the projected
    # point "north" in the image — so bigger y_eff → smaller screen_y.
    py = ((y_eff_max - y_eff) * scale + offset_y).astype(np.int32)

    valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    px = px[valid]
    py = py[valid]
    rgb_v = rgb[valid]
    y_v = xyz[:, 1][valid]
    z_v = xyz[:, 2][valid]

    # Painter's algorithm — draw far-from-camera points first so near
    # points overdraw them at shared pixels. Depth grows northward and
    # shrinks with height: camera sits south, elevated, looking north+
    # down. At tilt=0 this collapses to sorting by -z ascending, which
    # is equivalent to "tallest on top" (the previous behaviour).
    depth = y_v * sin_t - z_v * cos_t
    order = np.argsort(-depth, kind="stable")
    px = px[order]
    py = py[order]
    rgb_v = rgb_v[order]

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    if background != (0, 0, 0):
        canvas[:] = background

    canvas[py, px] = rgb_v

    img = Image.fromarray(canvas, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _encode_empty(width: int, height: int, background: Tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), background)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
