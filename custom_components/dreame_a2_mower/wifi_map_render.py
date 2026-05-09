"""Render the WiFi signal heatmap fetched from OSS.

Source format (decoded from `cloud_client.fetch_wifi_map`):

    {
      "data":   list[int],   # width*height RSSI values; `1` = no data,
                             # negative = dBm
      "width":  int,
      "height": int,
      "resolution": int,
      "startX": int,
      "startY": int,
    }

This renderer produces a heat-mapped PNG suitable for a `camera`
entity (`/api/camera_proxy/...`). Color grading: red (-99 dBm, weak)
through yellow to green (-50 dBm, strong); transparent for `1`
(no-data) cells.

Standalone PNG only — does NOT overlay on the lawn map. A future
enhancement could composite the heatmap on top of the live-map
camera image using the `startX/startY/resolution` frame metadata
(matches the cloud-frame coordinate system the rest of the renderer
already uses, see `cloud-map-geometry.md`). Standalone is shipped
first because it avoids coupling to the live-map renderer.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw


# Each cell rendered at this many pixels per side. 32px gives a
# 16x18 cell map a 512x576 image — fits comfortably in a Lovelace
# picture-entity card.
CELL_PX: int = 32

# RSSI dBm range to colour-grade. Values stronger than `STRONGEST` clamp
# to full green; weaker than `WEAKEST` clamp to full red.
STRONGEST: int = -50
WEAKEST: int = -99


def _rssi_to_rgb(rssi: int) -> tuple[int, int, int, int]:
    """Map an RSSI integer to an RGBA tuple.

    `1` is the device's "no data" sentinel — return fully transparent.
    """
    if rssi == 1:
        return (0, 0, 0, 0)
    # Clamp + normalise to [0, 1] where 1 is strongest.
    normalised = (rssi - WEAKEST) / (STRONGEST - WEAKEST)
    normalised = max(0.0, min(1.0, normalised))
    # Red → Yellow → Green gradient.
    if normalised < 0.5:
        # Red → Yellow: red full, green ramps 0 → 255.
        red = 255
        green = int(round(normalised * 2 * 255))
    else:
        # Yellow → Green: green full, red ramps 255 → 0.
        red = int(round((1.0 - normalised) * 2 * 255))
        green = 255
    return (red, green, 0, 220)  # slight transparency so map underneath shows through


def render_wifi_map_png(decoded: dict[str, Any]) -> bytes | None:
    """Return PNG bytes for the wifi map, or None on bad input."""
    width = decoded.get("width")
    height = decoded.get("height")
    data = decoded.get("data")
    if not (isinstance(width, int) and isinstance(height, int) and isinstance(data, list)):
        return None
    if len(data) != width * height:
        return None
    if width <= 0 or height <= 0:
        return None

    img = Image.new("RGBA", (width * CELL_PX, height * CELL_PX), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
    except Exception:
        font = None

    # Mirror both axes to match the lawn-map renderer's orientation.
    # The cloud-frame coordinate system has its own X/Y conventions
    # that don't match HA/screen image space; the lawn-map renderer
    # already flips both via `(bx2 - cloud_x)`/`(by2 - cloud_y)` plus a
    # final `FLIP_TOP_BOTTOM` transpose. The wifi heatmap data array is
    # laid out in raw cloud-frame order so we apply the same flip here
    # by reversing both row and column indices when reading the data —
    # cells appear in lawn-map orientation and the text labels stay
    # right-side-up (we flip the grid layout, NOT the rendered image).
    # Verified 2026-05-09 by user: pre-flip was mirrored both ways.
    for row in range(height):
        for col in range(width):
            src_row = (height - 1) - row  # flip Y
            src_col = (width - 1) - col   # flip X
            rssi = data[src_row * width + src_col]
            colour = _rssi_to_rgb(rssi)
            if colour[3] == 0:
                continue  # no-data cell — leave white
            x0 = col * CELL_PX
            y0 = row * CELL_PX
            draw.rectangle((x0, y0, x0 + CELL_PX - 1, y0 + CELL_PX - 1), fill=colour)
            # Overlay the dBm value as small text for power users.
            if font is not None:
                draw.text((x0 + 4, y0 + 4), str(rssi), fill=(0, 0, 0, 255), font=font)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
