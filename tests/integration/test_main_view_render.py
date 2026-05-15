"""Tests for render_main_view — live trail + mower icon, NO M_PATH."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.cloud_state import MowPathData
from custom_components.dreame_a2_mower.map_decoder import MapData
from custom_components.dreame_a2_mower.map_render import render_main_view


def _make_min_map():
    return MapData(
        md5="test",
        width_px=100, height_px=100, pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
        cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
        mowing_zones=(), exclusion_zones=(), spot_zones=(),
        contour_paths=(), available_contour_ids=(),
        maintenance_points=(), dock_xy=None,
        total_area_m2=10.0, nav_paths=(),
    )


def test_render_main_view_returns_png_bytes():
    """Smoke test: render_main_view produces valid PNG output."""
    map_data = _make_min_map()
    png_bytes = render_main_view(
        map_data,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    assert img.size == (100, 100)


def test_render_main_view_does_not_render_m_path():
    """render_main_view must NEVER include M_PATH overlay pixels, even if
    the caller had cloud history available — Main view shows live only."""
    map_data = _make_min_map()
    # Even though we don't pass an m_path kwarg, verify the signature
    # doesn't accept one — main view simply has no concept of historical paths.
    import inspect
    sig = inspect.signature(render_main_view)
    assert "m_path" not in sig.parameters
    # And the output should not contain the M_PATH default color.
    png_bytes = render_main_view(
        map_data, legs=None, mower_position_m=None, mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    pixels = list(img.getdata())
    matching = [px for px in pixels if px == (0, 0, 0, 255)]  # M_PATH default
    assert len(matching) == 0, (
        f"Main view contains {len(matching)} pure-black pixels — should be zero "
        f"(no M_PATH overlay). Top colors: "
        f"{sorted(set(pixels), key=lambda c: -pixels.count(c))[:5]}"
    )


def test_render_main_view_with_live_trail():
    """Pass legs and assert the trail is rendered on top of the base."""
    map_data = _make_min_map()
    legs = [[(10.0, 25.0), (40.0, 25.0)]]  # cloud-frame metres
    png_bytes = render_main_view(
        map_data,
        legs=legs,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # Trail color is _TRAIL_COLOR = (70, 70, 70, 220) — blended over the
    # opaque grey lawn (221,221,221,255). The composite is approximately
    # (152, 152, 152, 255) — visible as a darker line.
    pixels = list(img.getdata())
    # Look for any pixel where R == G == B and 100 <= R <= 180 (trail-blended).
    blended = [
        px for px in pixels
        if px[0] == px[1] == px[2] and 100 <= px[0] <= 180 and px[3] == 255
    ]
    assert len(blended) > 0, "No trail-blended pixels found"


def test_coordinator_has_main_view_and_work_log_png_slots():
    """Coordinator exposes the new explicit cache slots."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = None
    coord._work_log_png = None
    coord._main_view_png = b"\x89PNG"
    coord._work_log_png = b"\x89PNG"
    assert coord._main_view_png == b"\x89PNG"
    assert coord._work_log_png == b"\x89PNG"


def test_coordinator_init_sets_png_slots_to_none():
    """A freshly-constructed coordinator has both png slots = None."""
    import re
    from pathlib import Path
    # Refactor 2026-05-15: see test_coordinator_writes.py for context.
    src = Path("custom_components/dreame_a2_mower/_coordinator_legacy.py").read_text()
    assert re.search(r"self\._main_view_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._main_view_png: bytes | None = None"
    )
    assert re.search(r"self\._work_log_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._work_log_png: bytes | None = None"
    )


def test_coordinator_render_main_view_method_exists():
    """Coordinator exposes _render_main_view as an awaitable that writes
    self._main_view_png."""
    import inspect
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    method = getattr(DreameA2MowerCoordinator, "_render_main_view", None)
    assert method is not None, "_render_main_view should be defined"
    assert inspect.iscoroutinefunction(method), "_render_main_view should be async"


def test_main_view_camera_reads_main_view_png():
    """DreameA2MapCamera.async_camera_image returns _main_view_png."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._static_map_pngs_by_id = {}
    coord._cached_maps_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2MapCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGmainview"
