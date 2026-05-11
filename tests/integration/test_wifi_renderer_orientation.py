"""Tests for wifi_map_render canonical orientation + flip toggles."""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from custom_components.dreame_a2_mower.wifi_map_render import (
    CELL_PX,
    render_wifi_map_png,
)


def _decode_png(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGBA")


def _make_decoded(w: int, h: int, marker_row: int, marker_col: int) -> dict:
    """Build a wifi-map dict where one cell at (marker_col, marker_row) is
    a distinct RSSI value; all other cells are 'no data' (sentinel 1)."""
    data = [1] * (w * h)
    data[marker_row * w + marker_col] = -50  # strongest = full green
    return {"data": data, "width": w, "height": h, "resolution": 2,
            "startX": 0, "startY": 0}


def _green_cell_position(img: Image.Image) -> tuple[int, int]:
    """Return (col, row) of the centre-of-cell that is mostly green."""
    w, h = img.size
    cells_w = w // CELL_PX
    cells_h = h // CELL_PX
    for cr in range(cells_h):
        for cc in range(cells_w):
            px = img.getpixel((cc * CELL_PX + CELL_PX // 2,
                               cr * CELL_PX + CELL_PX // 2))
            r, g, b, _a = px
            if g > 200 and r < 100:
                return cc, cr
    raise AssertionError("no green cell found in image")


def test_canonical_orientation_row0_at_image_top():
    """Cell at array (col=3, row=0) appears at image (col=0, row=0) (top-left).

    Because X is reversed: array col 0 = image right; array col w-1 = image left.
    So array col 3 in a w=4 grid maps to image col 0.
    """
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (0, 0), (
        f"expected (0, 0), got ({cc}, {cr})"
    )


def test_canonical_orientation_col0_at_image_right():
    """Cell at array (col=0, row=0) appears at image (col=3, row=0)
    (top-right) in a w=4 grid because X is reversed by default."""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=0)
    png = render_wifi_map_png(decoded)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 0)


def test_flip_y_inverts_row_mapping():
    """With flip_y=True, array (col=3, row=0) appears at image bottom-left,
    not top-left. (h=3 → image row index 2.)"""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_y=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (0, 2)


def test_flip_x_inverts_column_mapping():
    """With flip_x=True, array (col=3, row=0) appears at image top-right
    (col=3) because X is no longer reversed."""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_x=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 0)


def test_flip_both_inverts_both_axes():
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_x=True, flip_y=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 2)
