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


def render_wifi_map_png(
    decoded: dict[str, Any],
    flip_x: bool = False,
    flip_y: bool = False,
) -> bytes | None:
    """Return PNG bytes for the wifi map, or None on bad input.

    Canonical orientation: image-top = array row 0 (= max Y in cloud
    frame); image-right = array col 0 (= max X). Cloud convention is
    array index 0 = max coordinate on both axes, so default rendering
    reverses X (col → w-1-col) but NOT Y (row → row).

    `flip_x` / `flip_y` invert each axis from its canonical default,
    as escape hatches for firmware variants whose convention differs.
    """
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

    for row in range(height):
        for col in range(width):
            # Y default: image row = array row (no reversal).
            src_row = (height - 1) - row if flip_y else row
            # X default: image col 0 = array col w-1 (reversed).
            src_col = col if flip_x else (width - 1) - col
            rssi = data[src_row * width + src_col]
            colour = _rssi_to_rgb(rssi)
            if colour[3] == 0:
                continue
            x0 = col * CELL_PX
            y0 = row * CELL_PX
            draw.rectangle((x0, y0, x0 + CELL_PX - 1, y0 + CELL_PX - 1), fill=colour)
            if font is not None:
                draw.text((x0 + 4, y0 + 4), str(rssi), fill=(0, 0, 0, 255), font=font)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
