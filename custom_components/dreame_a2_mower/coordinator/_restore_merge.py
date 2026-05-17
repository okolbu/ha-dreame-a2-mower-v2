"""Pure restore-then-merge logic for in_progress.json reconciliation.

When the integration restarts mid-session, MowerState may begin
re-accumulating events before the on-disk in_progress.json has been
read. This module merges the two views into a single payload without
losing data from either side. No HA imports — pure Python so the
logic is unit-testable in isolation.
"""
from __future__ import annotations

from typing import Any

# Tolerance for "same session" detection — disk start_ts vs memory
# start_ts. Wider than wall-clock drift between cloud-stamped and
# locally-stamped session-start values; narrower than any plausible
# gap between two consecutive sessions.
SAME_SESSION_TOLERANCE_S = 300


_SAMPLE_KEYS = (
    "battery_samples",
    "charging_status_samples",
    "state_samples",
    "error_samples",
)


def _merge_samples(a: list, b: list) -> list:
    """Union two `[ts, value]` sample lists, dedup full-tuple, sort by ts."""
    seen: set[tuple[Any, ...]] = set()
    out: list = []
    for src in (a or [], b or []):
        for s in src:
            key = tuple(s)
            if key in seen:
                continue
            seen.add(key)
            out.append(list(s))
    out.sort(key=lambda s: s[0])
    return out


def _merge_wifi(a: list, b: list) -> list:
    """Union two wifi-sample lists, dedup full-tuple, sort by ts (idx 3)."""
    seen: set[tuple[Any, ...]] = set()
    out: list = []
    for src in (a or [], b or []):
        for s in src:
            key = tuple(s)
            if key in seen:
                continue
            seen.add(key)
            out.append(list(s))
    out.sort(key=lambda s: s[3] if len(s) > 3 else 0)
    return out


def _merge_legs(a: list, b: list) -> list:
    """Union two leg lists; dedup points within each leg, preserve disk-first order.

    Concat both sides, walk through dedupping any point tuple already
    seen. Keeps first-occurrence ordering, so disk points (read first)
    anchor the leg shape. Pen-up splits get re-detected on next render.
    """
    seen: set[tuple[float, float]] = set()
    out_leg: list = []
    for src in (a or [], b or []):
        for leg in src:
            for pt in leg:
                key = (float(pt[0]), float(pt[1]))
                if key in seen:
                    continue
                seen.add(key)
                out_leg.append([pt[0], pt[1]])
    if not out_leg:
        return []
    return [out_leg]


def merge_in_progress_payloads(
    *,
    disk: dict[str, Any] | None,
    memory: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile a disk in_progress payload with the in-memory snapshot.

    Returns a new payload dict — neither input mutated. Caller assigns
    the result back into live_map.

    Decision rules:
    - disk is None → memory wins as-is.
    - memory has no session (session_start_ts is None / 0) → disk wins.
    - both have a session and start_ts agree (within SAME_SESSION_TOLERANCE_S)
      → merge legs/samples; charge_at_start and settings_snapshot favour
      memory if set, fall back to disk.
    - both have a session but start_ts diverge → memory wins (disk is
      stale residue from prior session).
    """
    if disk is None:
        return dict(memory)

    mem_start = memory.get("session_start_ts") or 0
    if not mem_start:
        return dict(disk)

    disk_start = disk.get("session_start_ts") or 0
    if disk_start and abs(disk_start - mem_start) > SAME_SESSION_TOLERANCE_S:
        return dict(memory)

    out: dict[str, Any] = dict(memory)
    out["legs"] = _merge_legs(disk.get("legs"), memory.get("legs"))
    for k in _SAMPLE_KEYS:
        out[k] = _merge_samples(disk.get(k), memory.get(k))
    out["wifi_samples"] = _merge_wifi(disk.get("wifi_samples"), memory.get("wifi_samples"))
    if memory.get("charge_at_start") is None and disk.get("charge_at_start") is not None:
        out["charge_at_start"] = disk["charge_at_start"]
    if memory.get("settings_snapshot") is None and disk.get("settings_snapshot") is not None:
        out["settings_snapshot"] = disk["settings_snapshot"]
    return out
