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
from typing import Any, Literal

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


@dataclass(slots=True, frozen=True)
class TrackPoint:
    """One captured position with everything needed to replay + classify it.

    t:           unix seconds, ms precision (float).
    x_m, y_m:    cloud-frame metres, charger-relative.
    area_m2:     cumulative mowed area from this same s1p4 push.
    heading_deg: mower heading if the frame carried it (None for 8-byte beacons).
    task_state:  latest-known s2p1 code at capture time (diagnostic only).
    role:        "mowing" | "traversal" — assigned by the classifier.
    """
    t: float
    x_m: float
    y_m: float
    area_m2: float
    heading_deg: float | None
    task_state: int
    role: Literal["mowing", "traversal"]


@dataclass(slots=True)
class LiveMapState:
    """In-progress session state, in-memory only.

    Persistence to disk is handled by archive/session.py (F5.7).
    """

    started_unix: int | None = None

    track: list[TrackPoint] = field(default_factory=list)
    """Time-ordered per-point capture; the single source of truth for replay."""

    session_ending: bool = False
    """Set True when the cloud signals end-of-session. Capture continues
    until the mower is observed docked (see coordinator lifecycle)."""

    _last_task_state: int = -1
    _last_area_m2: float = 0.0

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

    settings_snapshot: dict[str, Any] | None = None
    """Per-map cloud_state.settings snapshot captured at session_begin.
    Holds the settings that were in effect when the session started
    (edgemaster, edge_walk_mode, mowing_height_mm, etc.) so the
    archive carries an authoritative view independent of the current
    cloud state. None for pre-v1.0.13a1 archives."""

    def is_active(self) -> bool:
        return self.started_unix is not None

    def begin_session(self, started_unix: int) -> None:
        """Start a new session; clears any in-memory residue."""
        self.started_unix = started_unix
        self.track = []
        self.session_ending = False
        self._last_task_state = -1
        self._last_area_m2 = 0.0
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None
        self.settings_snapshot = None

    def update_task_state(self, t: float, code: int) -> None:
        """Record an s2p1 sample and remember the latest code for tagging.

        Called on every s2p1 push. Records (int(t), code) under
        state_samples (debounced on identical value) and updates
        _last_task_state so the next append_point tags its point with it.
        """
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            return
        self._last_task_state = code_int
        self.append_telemetry_sample(self.state_samples, code_int, int(t))

    def append_point(
        self,
        t: float,
        x_m: float,
        y_m: float,
        area_m2: float,
        heading_deg: float | None,
    ) -> None:
        """Append one captured position, classified inline by area delta.

        Dedup: skip when within 20 cm of the last point AND < 500 ms have
        elapsed (a stationary mower's heartbeats; still advances the time
        tracker). A point far in space OR far in time from the last is kept.
        """
        t = float(t)
        x_m = float(x_m)
        y_m = float(y_m)
        area_m2 = float(area_m2)
        if self.track:
            last = self.track[-1]
            dx = x_m - last.x_m
            dy = y_m - last.y_m
            close_space = (dx * dx + dy * dy) < 0.04  # 20 cm squared
            close_time = (t - last.t) < 0.5
            if close_space and close_time:
                self.last_telemetry_unix = t
                return
        prev_area = self._last_area_m2 if self.track else 0.0
        role = "mowing" if (area_m2 - prev_area) > 0.0 else "traversal"
        self.track.append(
            TrackPoint(
                t=t, x_m=x_m, y_m=y_m, area_m2=area_m2,
                heading_deg=(None if heading_deg is None else float(heading_deg)),
                task_state=self._last_task_state, role=role,
            )
        )
        self._last_area_m2 = area_m2
        self.last_telemetry_unix = t

    @property
    def mowing_legs(self) -> list[list[Point]]:
        """Legs captured while current_activity was MOWING."""
        return [
            list(leg)
            for leg, is_mowing in zip(self.legs, self.leg_is_mowing)
            if is_mowing and leg
        ]

    @property
    def traversal_legs(self) -> list[list[Point]]:
        """Legs captured while current_activity was anything but MOWING.

        Includes RETURNING (dock-return arc), CHARGE_RESUME (charging
        at-dock observations), CRUISING_TO_POINT, etc. Renderers draw
        these in grey ON TOP of mowing strokes so they remain visible.
        """
        return [
            list(leg)
            for leg, is_mowing in zip(self.legs, self.leg_is_mowing)
            if not is_mowing and leg
        ]

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

    def dump_to_payload(self) -> dict:
        """Snapshot the in-memory state into the in_progress.json payload shape.

        Mirrors the structure built by _persist_in_progress so the
        restore-merge helper can compare apples-to-apples.
        """
        return {
            "session_start_ts": self.started_unix,
            "legs": [list(list(pt) for pt in leg) for leg in self.legs],
            "leg_is_mowing": list(self.leg_is_mowing),
            "leg_start_ts": list(self.leg_start_ts),
            "leg_end_ts": list(self.leg_end_ts),
            "wifi_samples": [list(s) for s in self.wifi_samples],
            "battery_samples": [list(s) for s in self.battery_samples],
            "charging_status_samples": [list(s) for s in self.charging_status_samples],
            "state_samples": [list(s) for s in self.state_samples],
            "error_samples": [list(s) for s in self.error_samples],
            "charge_at_start": self.charge_at_start,
            "settings_snapshot": self.settings_snapshot,
        }

    def hydrate_from_payload(self, payload: dict) -> None:
        """Replace in-memory state from a merged payload (after restore-merge).

        Inverse of dump_to_payload / _persist_in_progress serialisation.
        JSON round-trip gives lists everywhere; we restore the internal
        types (legs of tuples, samples as tuples).
        """
        self.started_unix = payload.get("session_start_ts")
        raw_legs = payload.get("legs") or []
        legs: list[list[Point]] = []
        for raw_leg in raw_legs:
            legs.append([(float(pt[0]), float(pt[1])) for pt in raw_leg])
        self.legs = legs if legs else [[]]
        # leg_is_mowing parallels legs; default to True (mowing) for any
        # entry missing in the payload (pre-v1.0.16a6 in_progress.json).
        raw_flags = payload.get("leg_is_mowing") or []
        self.leg_is_mowing = [bool(raw_flags[i]) if i < len(raw_flags) else True
                              for i in range(len(self.legs))]
        # leg_start_ts / leg_end_ts: back-compat default for payloads that
        # predate per-leg timestamps — synthesize from started_unix.
        started = self.started_unix or 0
        raw_start = payload.get("leg_start_ts") or []
        self.leg_start_ts = [int(raw_start[i]) if i < len(raw_start) else started
                             for i in range(len(self.legs))]
        raw_end = payload.get("leg_end_ts") or []
        self.leg_end_ts = [int(raw_end[i]) if i < len(raw_end) else started
                           for i in range(len(self.legs))]
        self.wifi_samples = [
            (float(s[0]), float(s[1]), int(s[2]), int(s[3]))
            for s in (payload.get("wifi_samples") or [])
        ]
        self.battery_samples = [
            (int(s[0]), int(s[1]))
            for s in (payload.get("battery_samples") or [])
        ]
        self.charging_status_samples = [
            (int(s[0]), int(s[1]))
            for s in (payload.get("charging_status_samples") or [])
        ]
        self.state_samples = [
            (int(s[0]), int(s[1]))
            for s in (payload.get("state_samples") or [])
        ]
        self.error_samples = [
            (int(s[0]), int(s[1]))
            for s in (payload.get("error_samples") or [])
        ]
        self.charge_at_start = payload.get("charge_at_start")
        self.settings_snapshot = payload.get("settings_snapshot")

    def end_session(self) -> None:
        self.started_unix = None
        self.track = []
        self.session_ending = False
        self._last_task_state = -1
        self._last_area_m2 = 0.0
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None
        self.settings_snapshot = None
