"""CloudState — unified container for all cloud-fetched data.

Replaces the scattered `_cached_*` attributes on the coordinator.
Populated by `_refresh_cloud_state()` (every 10 min) plus
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
class ScheduleSlot:
    """One slot from the SCHEDULE batch."""

    slot_id: int
    name: str
    raw_blob_b64: str  # decoded later when format known


@dataclass(frozen=True, slots=True)
class ScheduleData:
    """Cloud-side schedule data (header-only decode in this PR)."""

    version: int
    slots: tuple[ScheduleSlot, ...]


@dataclass(frozen=True, slots=True)
class SettingsRoot:
    """Per-map mowing-behaviour settings.

    Preserves the dual-level structure observed on g2408 fw 4.3.6_0550
    (two top-level entries, both `mode: 0` with the same map_id keys
    inside). The semantic of the two entries is unknown; we read
    entry 0 as canonical and read-modify-write the FULL `raw` list
    on writes so entry 1's content is preserved unchanged.
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
