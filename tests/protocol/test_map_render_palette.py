"""Palette constants for the new mower-path render styling (Phase 1)."""
from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE


def test_dark_green_key_present():
    assert _DEFAULT_PALETTE["dark_green"] == (100, 160, 70, 255)


def test_mow_trail_color_matches_light_green_lawn():
    """Trail strokes should be the same color as the lawn baseline so the
    'mowed area becomes light green' visual works."""
    assert _DEFAULT_PALETTE["mow_trail_color"] == (178, 223, 138, 255)


def test_mow_trail_thin_color_dark_green_alpha():
    """Thin mode in the replay card uses dark-green α220 for visibility
    of individual passes."""
    assert _DEFAULT_PALETTE["mow_trail_thin_color"] == (50, 100, 30, 220)


def test_traversal_color_medium_grey():
    """Dock-return / cross-map traversal rendered in muted grey, drawn
    last so it stays on top."""
    assert _DEFAULT_PALETTE["traversal_color"] == (130, 130, 130, 220)


def test_zone_fills_lawn_opaque():
    """The primary lawn fill (zone 0) is fully opaque so the bbox-grey
    background never bleeds through. Pre-refresh value was α200."""
    assert _DEFAULT_PALETTE["zone_fills"][0] == (178, 223, 138, 255)


def test_ignore_fill_blueish_green():
    """Ignore-obstacle zones recoloured to semi-transparent blueish-green
    to match the Dreame app. Pre-refresh value was greenish (0,177,0,50)."""
    assert _DEFAULT_PALETTE["ignore_fill"] == (90, 140, 230, 90)


def test_ignore_outline_blueish_green():
    assert _DEFAULT_PALETTE["ignore_outline"] == (60, 110, 200, 220)
