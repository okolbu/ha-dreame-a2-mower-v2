"""Stripe overlay: alternating dark/light bands rotated to mow direction, clipped to lawn."""
from custom_components.dreame_a2_mower._render_stripes import compute_stripe_overlay
from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE


def test_overlay_size_matches_canvas():
    """Returned overlay must be the same size as the canvas it'll composite onto."""
    overlay = compute_stripe_overlay(
        width=200, height=150,
        lawn_polygon_px=[(0, 0), (200, 0), (200, 150), (0, 150)],
        angle_deg=0, stripe_width_px=40,
        dark_color=_DEFAULT_PALETTE["dark_green"],
        light_color=_DEFAULT_PALETTE["zone_fills"][0],
    )
    assert overlay.size == (200, 150)


def test_overlay_horizontal_stripes_when_angle_zero():
    """angle=0 → horizontal stripes. Sample column at x=100: alternates dark/light."""
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(0, 0), (200, 0), (200, 200), (0, 200)],
        angle_deg=0, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    col = [overlay.getpixel((100, y)) for y in (5, 25, 45, 65)]
    # Bands cycle; band 0 (y=0..20) one color, band 1 (y=20..40) other color, etc.
    assert col[0] != col[1]  # different bands
    assert col[0] == col[2]  # same band 2 rows away


def test_overlay_clipped_to_polygon():
    """Outside the lawn polygon → transparent."""
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(50, 50), (150, 50), (150, 150), (50, 150)],
        angle_deg=0, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    # Outside polygon (10, 10) → alpha 0.
    assert overlay.getpixel((10, 10))[3] == 0
    # Inside polygon (100, 100) → some color.
    assert overlay.getpixel((100, 100))[3] != 0


def test_overlay_angle_45_diagonal_stripes():
    """angle=45 → stripes oriented at 45° (top-left to bottom-right or vice versa).

    Along the stripe DIRECTION (45° diagonal), pixels stay in the same band.
    """
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(0, 0), (200, 0), (200, 200), (0, 200)],
        angle_deg=45, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    # Step 10px along the 45° stripe direction — should stay in same band.
    a = overlay.getpixel((50, 50))
    b = overlay.getpixel((60, 60))  # +10 along stripe direction
    assert a == b, f"moving along the stripe direction should stay in the same band; got {a} vs {b}"
