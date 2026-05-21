"""Unit tests for the shared PNG helpers."""
from io import BytesIO
from PIL import Image
from custom_components.dreame_a2_mower._png import encode_png


def test_encode_png_returns_valid_png():
    img = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
    data = encode_png(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(BytesIO(data)).size == (4, 4)


def test_encode_png_optimize_is_valid_png():
    data = encode_png(Image.new("RGB", (8, 8), (10, 20, 30)), optimize=True)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
