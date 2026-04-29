"""Live session state for the Dreame A2 mower.

Per spec §5.7 layer 2: the LiveMapState dataclass holds the in-progress
session — start time, accumulated track segments (one per leg, since a
mowing session can include recharge legs), and helpers for appending
new telemetry points to the active leg.

Layer-2 module: no ``homeassistant.*`` imports permitted here. HA-glue
belongs in the coordinator (layer 3) or entity layer (layer 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

# Type alias: a single track point is (x_m, y_m). A leg is a list of
# track points. A session is a list of legs.
Point = Tuple[float, float]
Leg = Tuple[Point, ...]


@dataclass(slots=True)
class LiveMapState:
    """In-progress session state, in-memory only.

    Persistence to disk is handled by archive/session.py (F5.7).
    """

    started_unix: int | None = None
    legs: list[list[Point]] = field(default_factory=list)
    """List of legs; each leg is a list of (x_m, y_m) points. The CURRENT
    leg is legs[-1]. A new leg starts on s2p56=4 (resume_pending) → s2p56=2
    (running) transition."""

    last_telemetry_unix: int | None = None

    def is_active(self) -> bool:
        return self.started_unix is not None

    def begin_session(self, started_unix: int) -> None:
        """Start a new session; clears any in-memory residue."""
        self.started_unix = started_unix
        self.legs = [[]]
        self.last_telemetry_unix = None

    def begin_leg(self) -> None:
        """Start a new leg (called on s2p56=4 → s2p56=2 transition)."""
        if not self.legs or self.legs[-1]:
            self.legs.append([])

    def append_point(self, x_m: float, y_m: float, ts_unix: int) -> None:
        if not self.legs:
            self.legs = [[]]
        # Pen-up filter: if jump > 5m, start a new leg
        current_leg = self.legs[-1]
        if current_leg:
            last_x, last_y = current_leg[-1]
            dx = x_m - last_x
            dy = y_m - last_y
            if (dx * dx + dy * dy) > 25.0:  # 5m squared
                self.legs.append([])
                current_leg = self.legs[-1]
        # Dedup: don't append if very close to last
        if current_leg:
            last_x, last_y = current_leg[-1]
            dx = x_m - last_x
            dy = y_m - last_y
            if (dx * dx + dy * dy) < 0.04:  # 20cm squared
                self.last_telemetry_unix = ts_unix
                return
        current_leg.append((x_m, y_m))
        self.last_telemetry_unix = ts_unix

    def total_points(self) -> int:
        return sum(len(leg) for leg in self.legs)

    def total_distance_m(self) -> float:
        """Cumulative session distance in metres.

        Sum of pairwise euclidean distances within each leg. Pen-up
        gaps between legs (>5 m jumps) are intentionally excluded —
        those represent leg boundaries (e.g. recharge segments where
        we lost telemetry), not actual mower travel. Same-leg
        consecutive points are >= 20 cm apart due to the dedup filter
        in append_point, so we don't pay GPS-noise tax.

        Cheap to recompute on every state push (one O(N) sweep over
        every leg's points), and N stays small thanks to the dedup
        filter — typical sessions hold a few thousand points at most.
        """
        from math import hypot

        total = 0.0
        for leg in self.legs:
            for i in range(1, len(leg)):
                ax, ay = leg[i - 1]
                bx, by = leg[i]
                total += hypot(bx - ax, by - ay)
        return total

    def end_session(self) -> None:
        self.started_unix = None
        self.legs = []
        self.last_telemetry_unix = None
