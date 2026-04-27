"""Tests for the stateful TrailLayer overlay compositor."""

from __future__ import annotations

import io

from PIL import Image
import numpy as np

from protocol.trail_overlay import TrailLayer, _affine_from_calibration


CALIBRATION = [
    {"mower": {"x": 0, "y": 0}, "map": {"x": 100, "y": 100}},
    {"mower": {"x": 1000, "y": 0}, "map": {"x": 200, "y": 100}},
    {"mower": {"x": 0, "y": 1000}, "map": {"x": 100, "y": 200}},
]


def _blank_png(w: int = 256, h: int = 256, color=(0, 0, 0)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _trail_pixels(png_bytes: bytes) -> int:
    """Count pixels coloured by the trail overlay.

    The trail is dark grey on a black base, so any pixel with
    R=G=B in roughly the 40–120 range counts. That keeps the test
    independent of the exact TRAIL_COLOR tuple while still
    distinguishing "trail present" from "all black".
    """
    arr = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mask = (r > 30) & (r < 150) & (abs(r.astype(int) - g.astype(int)) < 20) & (abs(r.astype(int) - b.astype(int)) < 20)
    return int(mask.sum())


# Back-compat alias — older tests still reference this name.
_red_pixels = _trail_pixels


# ---------- affine ----------

def test_affine_forward_maps_calibration_anchors():
    a, b, c, d, tx, ty = _affine_from_calibration(CALIBRATION)
    assert abs(tx - 100.0) < 1e-6 and abs(ty - 100.0) < 1e-6
    assert abs(a * 1000 + tx - 200.0) < 1e-6
    assert abs(d * 1000 + ty - 200.0) < 1e-6


def test_affine_rejects_colinear():
    with pytest.raises(ValueError):
        _affine_from_calibration([
            {"mower": {"x": 0, "y": 0}, "map": {"x": 0, "y": 0}},
            {"mower": {"x": 1, "y": 0}, "map": {"x": 1, "y": 0}},
            {"mower": {"x": 2, "y": 0}, "map": {"x": 2, "y": 0}},
        ])


# ---------- live path ----------

def test_first_live_point_does_not_draw():
    """Nothing to connect to on the first point; layer should remain empty."""
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) == 0


def test_second_live_point_draws_segment():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_version_bumps_on_each_new_segment():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    v0 = layer.version
    layer.extend_live([0.0, 0.0])
    # First point — no drawing, no bump.
    assert layer.version == v0
    layer.extend_live([1.0, 0.0])
    v1 = layer.version
    assert v1 > v0
    layer.extend_live([1.0, 1.0])
    assert layer.version > v1


def test_compose_is_idempotent_without_changes():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    png1 = layer.compose(_blank_png())
    png2 = layer.compose(_blank_png())
    assert png1 == png2


# ---------- replay / reset ----------

def test_reset_clears_trail():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    layer.reset()
    png = layer.compose(_blank_png())
    assert _red_pixels(png) == 0


def test_reset_to_session_paints_completed_track():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.reset_to_session(
        completed_track=[
            [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]],
            [[0.0, 0.5], [0.5, 0.5]],
        ],
    )
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_reset_to_session_accepts_flat_path_too():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.reset_to_session(path=[[0.0, 0.0], [1.0, 0.0]])
    png = layer.compose(_blank_png())
    assert _red_pixels(png) > 0


def test_set_dock_accepted_but_not_rendered():
    """Dock drawing is delegated to the upstream map renderer (it
    paints the charger icon from `map_data.charger_position`).
    `set_dock()` remains on the TrailLayer API so a future consumer
    could draw a secondary marker, but compose() should NOT produce
    a dock disc today — doing so caused visible doubling against the
    upstream charger icon (observed 2026-04-19)."""
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.set_dock([0.0, 0.0])
    png = layer.compose(_blank_png())
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    # No trail, no obstacles, no dock draw — expect an empty canvas.
    assert (arr.sum(axis=2) > 0).sum() == 0


def test_obstacle_polygon_blends_over_base():
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    layer.set_obstacles([poly])
    png = layer.compose(_blank_png(color=(0, 255, 0)))
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    # Blue obstacle over green base — expect blue channel elevated and
    # red muted (obstacle is a blue-dominant translucent fill).
    blue_px = ((arr[:, :, 2] > 80) & (arr[:, :, 0] < 120)).sum()
    assert blue_px > 0


# ---------- compose ----------

def test_compose_output_dimensions_match_base():
    layer = TrailLayer(base_size=(321, 123), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([0.5, 0.0])
    png = layer.compose(_blank_png(w=321, h=123))
    assert Image.open(io.BytesIO(png)).size == (321, 123)


def test_compose_handles_base_size_mismatch():
    """If the base PNG changes size the trail is resized to match —
    compose still succeeds rather than throwing."""
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([1.0, 0.0])
    # Hand it a differently-sized base.
    png = layer.compose(_blank_png(w=300, h=200))
    assert Image.open(io.BytesIO(png)).size == (300, 200)


def test_live_pen_up_on_large_jump():
    """A jump greater than LIVE_GAP_PENUP_M should start a new
    segment — no line drawn across the gap — otherwise dock visits
    and telemetry glitches produce ghost trails.

    Note: as of 2026-04-22, the layer also paints a live mower-
    position marker (filled circle ~10 px radius with white outline)
    at `_last_point` — anti-aliased edge of that outline lands a
    handful of grey pixels in `_trail_pixels`'s grey-band filter.
    Use a more permissive threshold that still catches the bug:
    drawing a real line across a 14 m gap on a 256×256 canvas
    paints hundreds of pixels, well above any marker noise.
    """
    layer = TrailLayer(base_size=(256, 256), calibration=CALIBRATION)
    layer.extend_live([0.0, 0.0])
    layer.extend_live([0.1, 0.0])
    red_after_short = _red_pixels(layer.compose(_blank_png()))
    layer.extend_live([10.0, 10.0])  # big jump — pen up
    layer.extend_live([10.1, 10.0])  # short follow-up — pen down again
    red_after_jump = _red_pixels(layer.compose(_blank_png()))
    # Bound drawn-across overhead: a drawn-across line would add
    # hundreds of pixels (far more than any plausible marker-edge
    # contribution); generous absolute cap catches the real bug.
    assert red_after_jump < red_after_short + 200


def test_x_reflect_mirrors_trail_horizontally():
    """When ``x_reflect_mm`` is set, an input X of 0 should produce
    the same pixel as an input X of the reflection value without a
    reflect. I.e. (x, y) → (reflect - x, y) in mower-mm space."""
    layer_flip = TrailLayer(
        base_size=(256, 256),
        calibration=CALIBRATION,
        x_reflect_mm=1000.0,
    )
    layer_noflip = TrailLayer(
        base_size=(256, 256),
        calibration=CALIBRATION,
    )
    # Metres: 1.0 m → mm 1000. Reflected via x_reflect_mm=1000: 1000-1000=0.
    # So `layer_flip._m_to_px(1.0, 0)` should equal `layer_noflip._m_to_px(0, 0)`.
    a = layer_flip._m_to_px(1.0, 0.0)
    b = layer_noflip._m_to_px(0.0, 0.0)
    assert abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


# pytest import needs to be present for `pytest.raises`
import pytest  # noqa: E402
