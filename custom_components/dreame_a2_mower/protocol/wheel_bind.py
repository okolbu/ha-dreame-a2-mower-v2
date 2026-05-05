"""Wheel-bind detector for the Dreame A2 mower.

Detects the failure mode reproduced 2026-05-05 across two integration-launched
edge runs (`{"edge": []}` payload, since fixed): the mower's wheels physically
stall in a tight maneuvering spot while the firmware's odometry / area
integrator continues to advance the `area_mowed_cent` and `dist_dm` counters
in s1p4 telemetry. When the firmware's edge-mode budget cap fires
(`area_mowed = 7.00 m²`, `dist = 1000 m`) while the mower is still wedged,
the auto-dock planner cannot route home from the stuck pose →
`s2p2: 48 → 31` (Failed to return to station).

The signal is a simple cross-frame comparison:

    Δposition < 50 mm  AND  Δarea_mowed > 0.05 m²
    across consecutive 33-byte s1p4 frames

We require ≥2 consecutive bind-shaped frames to set ``active = True`` —
single-frame events fire occasionally during pivot turns where the mower
is genuinely stationary while completing a tight maneuver. The 2-frame
threshold (≈10 s of physical immobility while the area counter keeps
advancing) was empirically the right cut on the 2026-05-05 captures:
the failed runs each had 4 consecutive bind frames; the successful
app-launched run had 1 isolated bind frame and recovered.

Pure function — no I/O, no homeassistant imports. Intended to be called
from coordinator._apply_s1p4_telemetry with the prior MowerState plus
the freshly-decoded MowingTelemetry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# Detection thresholds. Tuned to the 2026-05-05 captures; revisit if
# false positives fire during normal tight-area mowing.
POSITION_HOLD_MM = 50.0   # Δposition under this is "stationary"
AREA_ADVANCE_M2 = 0.05    # Δarea above this is "counter advancing"
BIND_ACTIVE_FRAMES = 2    # consecutive bind frames before active=True


@dataclass(frozen=True)
class WheelBindUpdate:
    """Per-frame update to the wheel-bind diagnostic state."""

    active: bool
    """True once ``BIND_ACTIVE_FRAMES`` consecutive bind frames have been
    seen. Stays True until a single non-bind frame clears it."""

    consecutive_frames: int
    """Number of consecutive bind-shaped frames including the current one.
    Resets to 0 on motion. Useful for diagnostics / debugging."""


def detect_wheel_bind(
    prev_x_m: float | None,
    prev_y_m: float | None,
    prev_area_mowed_m2: float | None,
    prev_consecutive_frames: int,
    new_x_m: float,
    new_y_m: float,
    new_area_mowed_m2: float,
) -> WheelBindUpdate:
    """Return updated wheel-bind state for the latest telemetry frame.

    All inputs in metres / m². ``prev_*`` may be ``None`` on the first
    frame of a session (or after a reset); in that case the function
    returns ``active=False, consecutive_frames=0`` and waits for a
    second frame to evaluate.
    """
    if (
        prev_x_m is None
        or prev_y_m is None
        or prev_area_mowed_m2 is None
    ):
        return WheelBindUpdate(active=False, consecutive_frames=0)

    dx_mm = (new_x_m - prev_x_m) * 1000.0
    dy_mm = (new_y_m - prev_y_m) * 1000.0
    distance_mm = math.hypot(dx_mm, dy_mm)
    darea_m2 = new_area_mowed_m2 - prev_area_mowed_m2

    is_bind_frame = distance_mm < POSITION_HOLD_MM and darea_m2 > AREA_ADVANCE_M2
    if is_bind_frame:
        frames = prev_consecutive_frames + 1
    else:
        frames = 0

    return WheelBindUpdate(
        active=frames >= BIND_ACTIVE_FRAMES,
        consecutive_frames=frames,
    )
