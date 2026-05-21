"""Shared PNG (de)serialisation helpers."""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


def encode_png(image: "Image.Image", *, optimize: bool = False) -> bytes:
    """Serialise a PIL image to PNG bytes."""
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=optimize)
    return buf.getvalue()


def png_response(body: bytes, *, cache: str = "no-store, max-age=0",
                 extra_headers: dict[str, str] | None = None):
    """aiohttp Response for a PNG body with an explicit Cache-Control."""
    from aiohttp import web  # deferred so encode_png importers don't pull aiohttp
    headers = {"Cache-Control": cache}
    if extra_headers:
        headers.update(extra_headers)
    return web.Response(body=body, content_type="image/png", headers=headers)
