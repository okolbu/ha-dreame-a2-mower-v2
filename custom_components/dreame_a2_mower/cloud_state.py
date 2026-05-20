"""CloudState — unified container for all cloud-fetched data.

Replaces the scattered `_cached_*` attributes on the coordinator.
Populated by `_refresh_cloud_state()` (every 2 min) plus
fast-cadence probe updates (LOCN, DOCK, MAPL — separate timers).

All sub-dataclasses are frozen + slots for O(1) attribute access
and immutability semantics. Mutation goes through coordinator
helpers that build a new CloudState and replace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .map_decoder import MapData


@dataclass(frozen=True, slots=True)
class MowPathData:
    """Per-map persisted mow-trajectory history from M_PATH.* batch.

    Each segment is a tuple of (x_mm, y_mm) pairs; segment boundaries
    correspond to the firmware's `[32767, -32768]` pen-up sentinel
    in the raw stream.
    """

    map_id: int
    segments: tuple[tuple[tuple[int, int], ...], ...]


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    """One scheduled mow within a ScheduleSlot.

    A plan triggers a mow at `time_min` (minute-of-day, 0..1439) on every
    weekday whose bit is set in `weekday_mask` (bit 0 = Mon, bit 6 = Sun).
    `action_type`: 0 = All-area, 1 = Zone, 2 = Edge.

    `zone_id` is set for Zone (action=1) and Edge (action=2) plans (the
    target zone in the active map's mowing-zone list); None for All-area.

    `extra_bytes` preserves any trailing bytes the wire format includes
    that we don't yet fully decode (Edge has 1 trailing reserved byte).
    Lets the encoder round-trip byte-identical even when semantics are
    not fully known.
    """

    time_min: int
    weekday_mask: int
    action_type: int
    zone_id: int | None = None
    extra_bytes: bytes = b""


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    """One slot from the SCHEDULE batch.

    The cloud carries up to two slots per map ("Spr & Sum" + "Aut & Win"
    on g2408). Wire shape is `[slot_id, mode, name, blob_b64]`.

    `plans` is the decoded list of mows; `raw_blob_b64` is the untouched
    on-wire bytes preserved for round-trip / debugging.

    `mode` is the second wire-element (live g2408 cloud emits 1 for the
    primary/active slot and 0 for an empty/inactive one). Its exact
    semantic is not fully decoded, but it MUST be round-tripped: writes
    that hardcode 0 silently flip an active slot off. Default 0 matches
    new/empty slots; the parser fills it from the wire on read.
    """

    slot_id: int
    name: str
    raw_blob_b64: str
    plans: tuple[SchedulePlan, ...] = ()
    mode: int = 0


@dataclass(frozen=True, slots=True)
class ScheduleData:
    """Cloud-side schedule data (header-only decode in this PR)."""

    version: int
    slots: tuple[ScheduleSlot, ...]


@dataclass(frozen=True, slots=True)
class SettingsRoot:
    """Per-map mowing-behaviour settings.

    Preserves the dual-level structure observed on g2408 fw 4.3.6_0550
    (two top-level entries, both `mode: 0`, each keyed by the same map
    ids but holding DIFFERENT values). Roles confirmed 2026-05-09 via
    controlled diffs of a cloud `getDeviceData` batch around app saves:
    entry 0 holds user-saved settings (what the app and HA both read
    and write; `version` increments on each save), entry 1 is a
    firmware-applied mirror that lags arbitrarily and stays at
    `version: 0` until the device pushes its applied state back.

    `by_map_id_canonical` reflects entry 0; writes propagate to every
    entry to keep them mutually consistent until the firmware updates
    entry 1 on its own schedule.
    """

    raw: list[dict[str, Any]]
    by_map_id_canonical: dict[int, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CloudState:
    """Unified container for all cloud-fetched device state."""

    cfg: dict[str, Any]
    maps_by_id: dict[int, MapData]
    mow_paths_by_map_id: dict[int, MowPathData]
    settings: SettingsRoot
    schedule: ScheduleData
    ai_human_enabled: bool | None
    forbidden_node_types_by_map: dict[int, dict[str, Any]]
    ota_status: tuple[int, int] | None
    task_id: int
    props: dict[str, str]
    locn: tuple[float, float] | None
    dock: dict[str, Any]
    mapl: list[list[Any]] | None
    mihis: dict[str, Any]
    fetched_at_unix: int
