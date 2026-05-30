"""Decoder for the Dreame A2 (`g2408`) session-summary JSON.

The mower uploads a summary JSON blob to an Aliyun OSS bucket after every
completed mowing session. The integration learns about it via the
`event_occured` MQTT message (siid=4, eiid=1, piid=9 = object key) and can
fetch it through the Dreame cloud's `getDownloadUrl` API.

This module owns the JSON → typed-dataclass conversion. It has zero HA
dependency and is unit-testable in isolation.

Coordinate convention
---------------------
All `(x, y)` tuples in the JSON are in **centimetres** on both axes (unlike
`s1p4` which uses cm on X and mm on Y). The decoder converts everything to
**metres** so downstream consumers do not need to care.

The special value `2147483647` (max int32) appears in `map[0].track` as a
segment-break marker — the mower "lifted the pen" between continuous paths.
We split the track into a list of segments.

See `docs/research/g2408-protocol.md` §7.4–7.7 for the full wire schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TRACK_BREAK_MARKER = 2147483647


@dataclass(frozen=True)
class Obstacle:
    """One obstacle polygon encountered during the session."""

    id: int
    type: int
    polygon: tuple[tuple[float, float], ...]  # metres


@dataclass(frozen=True)
class BoundaryLayer:
    """Lawn boundary + the complete mow track with segment breaks.

    `type == 0` on the wire. The boundary polygon self-closes (last point
    ≈ first point). The `track` is a list of continuous segments; each
    segment is a list of `(x_m, y_m)` points.
    """

    id: int
    name: str
    area_m2: float
    etime: int
    time: int
    boundary: tuple[tuple[float, float], ...]  # closed polygon, metres
    track: tuple[tuple[tuple[float, float], ...], ...]  # segments of metres


@dataclass(frozen=True)
class ExclusionLayer:
    """Exclusion / restricted zone polygon.

    `type == 2` on the wire. Points are typically 4 (quad), but the shape
    is not constrained — store whatever the wire sends.
    """

    id: int
    points: tuple[tuple[float, float], ...]  # metres


@dataclass(frozen=True)
class SpotLayer:
    """One spot-mow area definition + (when this is the mowed spot) the path.

    Lives in the top-level ``spot[]`` JSON array (NOT inside ``map[]``), with
    ``type == 3`` on the wire. Every spot-defined-on-lawn appears in
    ``spot[]`` for every session, but only the spot that was actually mowed
    THIS session has its ``track`` populated. The other spots in the same
    array have ``corners`` only and ``track == ()``.

    Corners is the 4-point polygon defining the spot's bounding rectangle.
    Track follows the same segment-break convention as ``BoundaryLayer.track``
    (sentinel ``TRACK_BREAK_MARKER`` rows separate continuous segments).

    Verified 2026-05-26 across 4 spot OSS blobs — see
    ``inventory.yaml`` ``summary_spot_track``.
    """

    id: int
    corners: tuple[tuple[float, float], ...]  # metres, typically 4-point quad
    track: tuple[tuple[tuple[float, float], ...], ...]  # segments of metres


@dataclass(frozen=True)
class Trajectory:
    """Top-level ``trajectory[]`` entry. Holds the lawn outline (`points`,
    from the wire's ``data`` field) AND — for edge mowing only — the actual
    mowed path (`track`, segmented like boundary.track).

    Mode-to-field mapping (verified 2026-05-26 across 17 OSS blobs):

    - mode 100 (ALL_AREAS) / mode 102 / zone mow — path is in
      ``BoundaryLayer.track``; ``trajectory[].track`` is empty.
    - mode 101 (EDGE) — path is in ``trajectory[].track``; boundary.track
      and spot.track are empty.
    - mode 103 (SPOT) — path is in ``spot[N].track`` for the mowed spot;
      ``trajectory[].track`` is empty.

    ``points`` is always the closed lawn-boundary polygon (~100 pts),
    identical across every session captured against the same lawn snapshot.
    """

    id: tuple[int, ...]
    points: tuple[tuple[float, float], ...]  # metres, lawn outline
    track: tuple[tuple[tuple[float, float], ...], ...]  # segments of metres


@dataclass(frozen=True)
class SessionSummary:
    """Fully-decoded session-summary JSON."""

    start_ts: int
    end_ts: int
    duration_min: int
    mode: int
    result: int
    stop_reason: int
    start_mode: int
    pre_type: int
    md5: str
    area_mowed_m2: float
    map_area_m2: int
    dock: tuple[float, float, int] | None  # (x_m, y_m, heading)
    pref: tuple[int, ...]
    region_status: tuple[tuple[int, ...], ...]
    faults: tuple[Any, ...]
    spots: tuple[SpotLayer, ...]
    ai_obstacle: tuple[Any, ...]
    obstacles: tuple[Obstacle, ...]
    boundary: BoundaryLayer | None
    exclusions: tuple[ExclusionLayer, ...]
    trajectories: tuple[Trajectory, ...]
    # v1.0.12a2+: integration-side enrichments. Populated when the
    # archive payload carries the corresponding keys (added by the
    # coordinator in _lidar_oss.py / _session.py). Cloud-only blobs
    # parsed in isolation will keep these empty / None.
    battery_samples: tuple[tuple[int, int], ...] = ()
    charging_status_samples: tuple[tuple[int, int], ...] = ()
    state_samples: tuple[tuple[int, int], ...] = ()
    error_samples: tuple[tuple[int, int], ...] = ()
    wifi_samples: tuple[tuple[float, float, int, int], ...] = ()
    charge_at_start: int | None = None

    # Convenience properties for the camera/live-map overlay.

    @property
    def track_segments(self) -> tuple[tuple[tuple[float, float], ...], ...]:
        """Mow path, split into continuous segments.

        Source depends on mode:
          - Full mow / zone / mode 100 / mode 102 → ``boundary.track``
          - Edge mow / mode 101 → ``trajectory[].track`` (lawn-outline-
            following arc)
          - Spot mow / mode 103 → ``spot[N].track`` for the mowed spot

        Returns the concatenated segments from whichever source is
        populated. Verified 2026-05-26 across the four mode classes.
        """
        if self.boundary and self.boundary.track:
            return self.boundary.track
        # Spot-mow fallback: scan spots[] for any with a populated track.
        # In practice only one spot per session carries .track (the mowed
        # one), but we concatenate defensively in case the firmware ever
        # mows multiple spots in one session.
        spot_segments: list[tuple[tuple[float, float], ...]] = []
        for spot in self.spots:
            spot_segments.extend(spot.track)
        if spot_segments:
            return tuple(spot_segments)
        # Edge-mow fallback: trajectory[].track. Concatenate across all
        # trajectories defensively, though the wire only ever carries one.
        traj_segments: list[tuple[tuple[float, float], ...]] = []
        for t in self.trajectories:
            traj_segments.extend(t.track)
        return tuple(traj_segments)

    @property
    def lawn_polygon(self) -> tuple[tuple[float, float], ...]:
        """Closed lawn boundary polygon. Empty tuple if no boundary layer."""
        return self.boundary.boundary if self.boundary else ()


class InvalidSessionSummary(ValueError):
    """Raised when the JSON does not match the expected top-level shape."""


def _pt(raw: list[int]) -> tuple[float, float]:
    """Convert one `[x_cm, y_cm]` pair from the wire to `(x_m, y_m)`."""
    if not isinstance(raw, list) or len(raw) < 2:
        raise InvalidSessionSummary(f"point must be [x, y], got {raw!r}")
    return (raw[0] / 100.0, raw[1] / 100.0)


def _split_track(track: list[list[int]]) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Split a track list on `TRACK_BREAK_MARKER` into continuous segments."""
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for raw in track or []:
        if not isinstance(raw, list) or len(raw) < 2:
            continue
        if raw[0] == TRACK_BREAK_MARKER:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(_pt(raw))
    if current:
        segments.append(current)
    return tuple(tuple(seg) for seg in segments)


def _decode_obstacle(raw: dict[str, Any]) -> Obstacle:
    polygon = tuple(_pt(p) for p in raw.get("data", []) if isinstance(p, list))
    return Obstacle(
        id=int(raw.get("id", 0)),
        type=int(raw.get("type", 0)),
        polygon=polygon,
    )


def _decode_map_layer(raw: dict[str, Any]) -> BoundaryLayer | ExclusionLayer | None:
    layer_type = raw.get("type")
    if layer_type == 0:
        boundary = tuple(_pt(p) for p in raw.get("data", []) if isinstance(p, list))
        return BoundaryLayer(
            id=int(raw.get("id", 0)),
            name=str(raw.get("name", "")),
            area_m2=float(raw.get("area", 0.0)),
            etime=int(raw.get("etime", 0)),
            time=int(raw.get("time", 0)),
            boundary=boundary,
            track=_split_track(raw.get("track", [])),
        )
    if layer_type == 2:
        desc = raw.get("description") or {}
        points = tuple(_pt(p) for p in desc.get("points", []) if isinstance(p, list))
        return ExclusionLayer(
            id=int(raw.get("id", 0)),
            points=points,
        )
    return None


def _decode_spot_layer(raw: dict[str, Any]) -> SpotLayer | None:
    """Decode one ``spot[]`` entry into a typed ``SpotLayer``.

    The entry must have ``type == 3``; corners are taken from ``data`` (the
    bounding-rectangle quad), and ``track`` (when present) is split on the
    same int32-max sentinel as ``boundary.track``. Returns ``None`` for any
    entry with a non-spot type so callers can filter cleanly.
    """
    if raw.get("type") != 3:
        return None
    corners = tuple(
        _pt(p) for p in raw.get("data", []) if isinstance(p, list)
    )
    track = _split_track(raw.get("track", []))
    return SpotLayer(
        id=int(raw.get("id", 0)),
        corners=corners,
        track=track,
    )


def _decode_trajectory(raw: dict[str, Any]) -> Trajectory:
    raw_id = raw.get("id", [])
    trajectory_id = tuple(int(x) for x in raw_id) if isinstance(raw_id, list) else ()
    points = tuple(_pt(p) for p in raw.get("data", []) if isinstance(p, list))
    # `track` is populated only for edge mows (mode 101); split on the same
    # int32-max sentinel as boundary.track / spot.track so we get clean
    # continuous segments.
    track = _split_track(raw.get("track", []))
    return Trajectory(id=trajectory_id, points=points, track=track)


def _decode_dock(raw: Any) -> tuple[float, float, int] | None:
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    try:
        return (raw[0] / 100.0, raw[1] / 100.0, int(raw[2]))
    except (TypeError, ValueError):
        return None


def parse_session_summary(data: dict[str, Any]) -> SessionSummary:
    """Parse a session-summary JSON dict into a typed `SessionSummary`."""
    if not isinstance(data, dict):
        raise InvalidSessionSummary(f"top-level must be a dict, got {type(data).__name__}")

    maps = data.get("map") or []
    boundary: BoundaryLayer | None = None
    exclusions: list[ExclusionLayer] = []
    for m in maps:
        if not isinstance(m, dict):
            continue
        layer = _decode_map_layer(m)
        if isinstance(layer, BoundaryLayer):
            # Keep the first boundary layer we see; later ones are unexpected.
            if boundary is None:
                boundary = layer
        elif isinstance(layer, ExclusionLayer):
            exclusions.append(layer)

    obstacles = tuple(
        _decode_obstacle(o) for o in (data.get("obstacle") or []) if isinstance(o, dict)
    )
    trajectories = tuple(
        _decode_trajectory(t)
        for t in (data.get("trajectory") or [])
        if isinstance(t, dict)
    )

    def _decode_int_samples(key: str) -> tuple[tuple[int, int], ...]:
        out: list[tuple[int, int]] = []
        for s in data.get(key) or ():
            if not isinstance(s, (list, tuple)) or len(s) < 2:
                continue
            try:
                out.append((int(s[0]), int(s[1])))
            except (TypeError, ValueError):
                continue
        return tuple(out)

    wifi_samples_out: list[tuple[float, float, int, int]] = []
    for s in data.get("wifi_samples") or ():
        if not isinstance(s, (list, tuple)) or len(s) < 4:
            continue
        try:
            wifi_samples_out.append(
                (float(s[0]), float(s[1]), int(s[2]), int(s[3]))
            )
        except (TypeError, ValueError):
            continue

    raw_charge_at_start = data.get("charge_at_start")
    charge_at_start: int | None
    try:
        charge_at_start = (
            int(raw_charge_at_start) if raw_charge_at_start is not None else None
        )
    except (TypeError, ValueError):
        charge_at_start = None

    return SessionSummary(
        start_ts=int(data.get("start", 0)),
        end_ts=int(data.get("end", 0)),
        duration_min=int(data.get("time", 0)),
        mode=int(data.get("mode", 0)),
        result=int(data.get("result", 0)),
        stop_reason=int(data.get("stop_reason", 0)),
        start_mode=int(data.get("start_mode", 0)),
        pre_type=int(data.get("pre_type", 0)),
        md5=str(data.get("md5", "")),
        area_mowed_m2=float(data.get("areas", 0.0)),
        map_area_m2=int(data.get("map_area", 0)),
        dock=_decode_dock(data.get("dock")),
        pref=tuple(int(x) for x in (data.get("pref") or []) if isinstance(x, (int, float))),
        region_status=tuple(
            tuple(int(x) for x in row)
            for row in (data.get("region_status") or [])
            if isinstance(row, list)
        ),
        faults=tuple(data.get("faults") or ()),
        spots=tuple(
            sl
            for sl in (
                _decode_spot_layer(s)
                for s in (data.get("spot") or [])
                if isinstance(s, dict)
            )
            if sl is not None
        ),
        ai_obstacle=tuple(data.get("ai_obstacle") or ()),
        obstacles=obstacles,
        boundary=boundary,
        exclusions=tuple(exclusions),
        trajectories=trajectories,
        battery_samples=_decode_int_samples("battery_samples"),
        charging_status_samples=_decode_int_samples("charging_status_samples"),
        state_samples=_decode_int_samples("state_samples"),
        error_samples=_decode_int_samples("error_samples"),
        wifi_samples=tuple(wifi_samples_out),
        charge_at_start=charge_at_start,
    )


_MOW_TYPE_BY_MODE: dict[int, str] = {
    100: "all_areas", 101: "edge", 102: "zone", 103: "spot",
}


def mow_type_from_mode(mode: int) -> str | None:
    """Map the OSS summary `mode` int to a mow-type label (100=all_areas,
    101=edge, 102=zone, 103=spot). None for unknown — caller keeps raw int.
    Verified across 10 OSS dumps 2026-05-30; inventory.yaml § summary_mode."""
    return _MOW_TYPE_BY_MODE.get(mode)


def start_mode_label(start_mode: int) -> str | None:
    """1=scheduled, 0=manual/app (partial — voice/HA-service not yet pinned)."""
    return {1: "scheduled", 0: "manual"}.get(start_mode)
