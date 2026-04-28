def test_render_trail_overlay_empty_legs_returns_empty():
    from custom_components.dreame_a2_mower.live_map.trail import render_trail_overlay
    result = render_trail_overlay([], 0, 0, 50)
    assert list(result) == []
