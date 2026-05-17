"""Stripe overlay for pre-start mow visualization (P3 of render-styling design).

Renders alternating dark-green / light-green bands of ``stripe_width_px``
oriented at ``angle_deg`` (from horizontal), clipped to the lawn polygon
on a transparent RGBA canvas of ``width x height``. The caller composites
this overlay onto the base map.

Coordinate convention
---------------------
``angle_deg`` is measured from the horizontal (positive X axis), increasing
counter-clockwise as per standard mathematics.  The *stripe direction* is the
axis the mower travels along; the *perp direction* is perpendicular to it
(across bands).

    stripe_dir = (cos θ,  sin θ)    # along the band
    perp_dir   = (−sin θ, cos θ)    # across bands

A pixel at canvas position (x, y) projects onto the perp axis as:

    perp_proj = x * perp_x + y * perp_y

The band index is ``floor(perp_proj / stripe_width_px)``.  Moving along
``stripe_dir`` keeps ``perp_proj`` constant — that is the invariant the tests
verify.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw


def compute_stripe_overlay(
    *,
    width: int,
    height: int,
    lawn_polygon_px: list[tuple[float, float]],
    angle_deg: int,
    stripe_width_px: float,
    dark_color: tuple[int, int, int, int],
    light_color: tuple[int, int, int, int],
) -> Image.Image:
    """Return a transparent RGBA overlay with stripes clipped to the polygon.

    The stripes run PARALLEL to ``angle_deg`` (from horizontal).  Bands of
    width ``stripe_width_px`` alternate dark/light.  Pixels outside
    ``lawn_polygon_px`` are alpha 0.

    Parameters
    ----------
    width, height:
        Canvas size in pixels — the returned image has exactly this size.
    lawn_polygon_px:
        Polygon vertices in canvas-pixel coordinates.  Must be a closed
        (implicitly) convex or non-self-intersecting polygon.
    angle_deg:
        Stripe direction measured from the positive-X axis, in degrees.
    stripe_width_px:
        Width of each individual band (dark *or* light) in pixels.
    dark_color, light_color:
        RGBA tuples for the two alternating band colours.
    """
    angle_rad = math.radians(angle_deg)

    # Orthonormal basis.
    # stripe_dir: the direction the mower travels (along a band).
    stripe_dx = math.cos(angle_rad)
    stripe_dy = math.sin(angle_rad)
    # perp_dir: perpendicular to stripe_dir (across bands).
    perp_x = -math.sin(angle_rad)
    perp_y = math.cos(angle_rad)

    # Project the four canvas corners onto the perp axis to find coverage.
    corners = [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]
    perp_vals = [cx * perp_x + cy * perp_y for cx, cy in corners]
    perp_min = min(perp_vals)
    perp_max = max(perp_vals)

    # A diagonal long enough to reach both ends of the canvas from any point.
    half_diag = math.hypot(width, height) + 1.0

    # Fill stripe field on a blank canvas.
    field = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(field, "RGBA")

    # Find the first band boundary at or below perp_min.
    first_band = math.floor(perp_min / stripe_width_px)

    perp_pos = first_band * stripe_width_px
    while perp_pos < perp_max + stripe_width_px:
        edge_a = perp_pos
        edge_b = perp_pos + stripe_width_px

        # Map the four corners of this band rectangle from the (perp, stripe)
        # orthonormal basis back to canvas (x, y):
        #   (x, y) = perp_val * (perp_x, perp_y) + stripe_val * (stripe_dx, stripe_dy)
        cor1 = (
            edge_a * perp_x - half_diag * stripe_dx,
            edge_a * perp_y - half_diag * stripe_dy,
        )
        cor2 = (
            edge_a * perp_x + half_diag * stripe_dx,
            edge_a * perp_y + half_diag * stripe_dy,
        )
        cor3 = (
            edge_b * perp_x + half_diag * stripe_dx,
            edge_b * perp_y + half_diag * stripe_dy,
        )
        cor4 = (
            edge_b * perp_x - half_diag * stripe_dx,
            edge_b * perp_y - half_diag * stripe_dy,
        )

        band_index = round((perp_pos - first_band * stripe_width_px) / stripe_width_px)
        color = dark_color if band_index % 2 == 0 else light_color
        draw.polygon([cor1, cor2, cor3, cor4], fill=color)

        perp_pos += stripe_width_px

    # Build a mask from the lawn polygon: 255 inside, 0 outside.
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(lawn_polygon_px, fill=255)

    # Composite: keep field where mask=255, transparent elsewhere.
    transparent = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out = Image.composite(field, transparent, mask)
    return out
