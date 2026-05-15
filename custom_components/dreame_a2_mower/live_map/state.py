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

# Type alias: a single track point is (x_m, y_m). A leg is a list of
# track points. A session is a list of legs.
Point = tuple[float, float]
Leg = tuple[Point, ...]
# WiFi sample: (x_m, y_m, rssi_dbm, ts_unix). Captured once per s1p1
# heartbeat while a session is active and a valid position is known.
WifiSample = tuple[float, float, int, int]
# Generic scalar telemetry sample: (ts_unix, value). Used for battery
# level, charging-status enum, mower-state enum and error-code stream.
# Value type varies per slot but is always representable as int for
# the streams we currently capture (s3p1/s3p2/s2p1/s2p2).
TelemetrySample = tuple[int, int]


@dataclass(slots=True)
class LiveMapState:
    """In-progress session state, in-memory only.

    Persistence to disk is handled by archive/session.py (F5.7).
    """

    started_unix: int | None = None
    legs: list[list[Point]] = field(default_factory=list)
    """List of legs; each leg is a list of (x_m, y_m) points. The CURRENT
    leg is legs[-1]. A new leg starts when task_state_code transitions
    from 4 (paused) → 0 (running) — i.e. mower resumes after a
    recharge round-trip."""

    last_telemetry_unix: int | None = None

    wifi_samples: list[WifiSample] = field(default_factory=list)
    """RSSI fingerprints captured during this session. Each entry is
    ``(x_m, y_m, rssi_dbm, ts_unix)`` — paired from the s1p1 heartbeat's
    ``wifi_rssi_dbm`` field and the most recent s1p4 position. Used by
    the WiFi heatmap → map_id correlator (v1.0.10a6+): when the cloud
    drops a fresh heatmap, the matcher scores each candidate session's
    samples against the heatmap grid (coverage × dBm-agreement) to
    assign the right map_id. Persisted in ``in_progress.json`` and in
    the finalized session archive blob under the same key."""

    battery_samples: list[TelemetrySample] = field(default_factory=list)
    """(ts_unix, pct) samples captured on every s3p1 push during an
    active session. Lets the archive consumer reconstruct the SoC
    curve without correlating against the global battery entity's
    history (which is sampled by HA, not by mower events). Debounced
    on identical-value follow-ups."""

    charging_status_samples: list[TelemetrySample] = field(default_factory=list)
    """(ts_unix, status_enum) samples captured on every s3p2 push.
    Detects mid-session recharge legs at archive time without needing
    a paired charging_status entity history."""

    state_samples: list[TelemetrySample] = field(default_factory=list)
    """(ts_unix, state_enum) samples captured on every s2p1 push.
    Encodes WORKING / PAUSED / RETURNING / CHARGING transitions."""

    error_samples: list[TelemetrySample] = field(default_factory=list)
    """(ts_unix, code) samples captured on every s2p2 push (error /
    notification stream). Sampled raw — interpretation happens at the
    consumer."""

    charge_at_start: int | None = None
    """Battery percentage snapshot taken when the session began.
    Together with the last ``battery_samples`` entry this gives a
    cheap start/end SoC pair for long-term graphing without parsing
    the full samples list."""

    def is_active(self) -> bool:
        return self.started_unix is not None

    def begin_session(self, started_unix: int) -> None:
        """Start a new session; clears any in-memory residue."""
        self.started_unix = started_unix
        self.legs = [[]]
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None

    def begin_leg(self) -> None:
        """Start a new leg (called on task_state_code 4 → 0 transition)."""
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

    def append_wifi_sample(
        self, x_m: float, y_m: float, rssi_dbm: int, ts_unix: int
    ) -> bool:
        """Append a (x_m, y_m, rssi_dbm, ts_unix) fingerprint.

        Returns True iff a new sample was actually appended. Same-
        position + same-RSSI samples are debounced so a stationary
        mower's heartbeats don't pile up; the timestamp tracker still
        advances via the live trail's append_point().
        """
        try:
            rssi_int = int(rssi_dbm)
            ts_int = int(ts_unix)
            x_f = float(x_m)
            y_f = float(y_m)
        except (TypeError, ValueError):
            return False
        if self.wifi_samples:
            last = self.wifi_samples[-1]
            # Drop a follow-up sample within 25 cm at the same RSSI —
            # mower's just sitting still and reporting the same
            # number on every 45-second heartbeat.
            if last[2] == rssi_int:
                dx = x_f - last[0]
                dy = y_f - last[1]
                if (dx * dx + dy * dy) < 0.0625:  # 25 cm squared
                    return False
        self.wifi_samples.append((x_f, y_f, rssi_int, ts_int))
        return True

    def append_telemetry_sample(
        self, samples: list[TelemetrySample], value: int | None, ts_unix: int
    ) -> bool:
        """Append (ts_unix, value) to a TelemetrySample list.

        Debounces consecutive identical values — the mower frequently
        re-emits the same level on its 30 s heartbeat. Returns True
        iff a new entry was appended.
        """
        if value is None:
            return False
        try:
            val_int = int(value)
            ts_int = int(ts_unix)
        except (TypeError, ValueError):
            return False
        if samples and samples[-1][1] == val_int:
            return False
        samples.append((ts_int, val_int))
        return True

    def end_session(self) -> None:
        self.started_unix = None
        self.legs = []
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None
