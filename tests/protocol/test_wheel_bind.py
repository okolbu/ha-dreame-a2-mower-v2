"""Tests for protocol.wheel_bind — wheel-bind detector."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.wheel_bind import (
    BIND_ACTIVE_FRAMES,
    detect_wheel_bind,
)


def test_first_frame_returns_inactive():
    """No prior state → no detection (need a baseline frame)."""
    out = detect_wheel_bind(
        prev_x_m=None,
        prev_y_m=None,
        prev_area_mowed_m2=None,
        prev_consecutive_frames=0,
        new_x_m=10.0,
        new_y_m=2.0,
        new_area_mowed_m2=1.5,
    )
    assert out.active is False
    assert out.consecutive_frames == 0


def test_normal_motion_does_not_trigger():
    """Position moving + area advancing = healthy mowing."""
    out = detect_wheel_bind(
        prev_x_m=10.0,
        prev_y_m=2.0,
        prev_area_mowed_m2=1.5,
        prev_consecutive_frames=0,
        new_x_m=10.5,  # 50 cm motion
        new_y_m=2.1,
        new_area_mowed_m2=1.55,  # +0.05 m²
    )
    assert out.active is False
    assert out.consecutive_frames == 0


def test_single_bind_frame_does_not_set_active():
    """One bind-shaped frame — could be a pivot turn. Don't fire yet."""
    out = detect_wheel_bind(
        prev_x_m=12.44,
        prev_y_m=-2.51,
        prev_area_mowed_m2=4.30,
        prev_consecutive_frames=0,
        new_x_m=12.44,
        new_y_m=-2.51,
        new_area_mowed_m2=6.38,  # +2.08 m² with no motion (run 2 actual)
    )
    assert out.active is False
    assert out.consecutive_frames == 1


def test_two_consecutive_bind_frames_set_active():
    """≥BIND_ACTIVE_FRAMES consecutive bind frames → active=True."""
    # First bind frame.
    out1 = detect_wheel_bind(
        prev_x_m=12.44,
        prev_y_m=-2.51,
        prev_area_mowed_m2=4.30,
        prev_consecutive_frames=0,
        new_x_m=12.44,
        new_y_m=-2.51,
        new_area_mowed_m2=6.38,
    )
    assert out1.consecutive_frames == 1
    assert out1.active is False
    # Second bind frame in a row.
    out2 = detect_wheel_bind(
        prev_x_m=12.44,
        prev_y_m=-2.51,
        prev_area_mowed_m2=6.38,
        prev_consecutive_frames=out1.consecutive_frames,
        new_x_m=12.45,
        new_y_m=-2.51,
        new_area_mowed_m2=6.72,  # +0.34 m² with 1 cm motion
    )
    assert out2.consecutive_frames == 2
    assert out2.active is True
    assert BIND_ACTIVE_FRAMES == 2  # invariant


def test_motion_clears_active_state():
    """A non-bind frame after activation resets consecutive_frames to 0."""
    out = detect_wheel_bind(
        prev_x_m=12.44,
        prev_y_m=-2.51,
        prev_area_mowed_m2=6.72,
        prev_consecutive_frames=4,
        new_x_m=11.79,  # 65 cm motion = real travel
        new_y_m=-3.20,
        new_area_mowed_m2=6.99,
    )
    assert out.consecutive_frames == 0
    assert out.active is False


def test_threshold_boundary_position_held_exactly_at_50mm():
    """At the threshold, distance < 50 mm is required (strict inequality)."""
    # Position exactly 50 mm displaced — not a bind.
    out = detect_wheel_bind(
        prev_x_m=10.000,
        prev_y_m=2.000,
        prev_area_mowed_m2=1.0,
        prev_consecutive_frames=0,
        new_x_m=10.050,  # exactly 50 mm
        new_y_m=2.000,
        new_area_mowed_m2=1.20,
    )
    assert out.consecutive_frames == 0
    assert out.active is False


def test_small_area_advance_below_threshold_does_not_trigger():
    """Δarea below the 0.05 m² threshold = noise, not a bind."""
    out = detect_wheel_bind(
        prev_x_m=10.0,
        prev_y_m=2.0,
        prev_area_mowed_m2=1.000,
        prev_consecutive_frames=0,
        new_x_m=10.0,  # zero motion
        new_y_m=2.0,
        new_area_mowed_m2=1.040,  # +0.04 m² — below threshold
    )
    assert out.consecutive_frames == 0
    assert out.active is False


def test_real_run2_runaway_sequence_matches_observation():
    """Replay the 2026-05-05 09:21:30→09:21:50 runaway sequence (run 2).

    The actual log showed 4 consecutive bind frames; the detector should
    flag active=True from the second frame onward and stay True until
    motion resumes.
    """
    # Stationary at (+12.44, -2.51) with area racing 4.30 → 6.38 → 6.72 → 6.98 → 7.05
    frames = [
        (12.44, -2.51, 4.30),  # baseline
        (12.44, -2.51, 6.38),  # +2.08 m² no motion → bind frame 1
        (12.45, -2.51, 6.72),  # +0.34 m² 1 cm motion → bind frame 2 (active!)
        (12.45, -2.51, 6.98),  # +0.26 m² no motion → bind frame 3
        (12.45, -2.53, 7.05),  # +0.07 m² 2 mm motion → bind frame 4
        (11.79, -3.20, 7.05),  # 65 cm motion, no area change → cleared
    ]
    state = (None, None, None, 0)  # prev_x, prev_y, prev_area, prev_frames
    actives = []
    for x, y, m in frames:
        out = detect_wheel_bind(
            prev_x_m=state[0],
            prev_y_m=state[1],
            prev_area_mowed_m2=state[2],
            prev_consecutive_frames=state[3],
            new_x_m=x,
            new_y_m=y,
            new_area_mowed_m2=m,
        )
        actives.append(out.active)
        state = (x, y, m, out.consecutive_frames)

    # baseline=False, frame1=False(1), frame2=True(2), frame3=True(3),
    # frame4=True(4), recovery=False(0)
    assert actives == [False, False, True, True, True, False]
