"""Finalize-stage track classifier (smoothing only).

Stage 1 (area-delta) runs inline in LiveMapState.append_point and is
**authoritative**: the mowed-area counter grew between two points ⇒ blades
cut new grass ⇒ ``"mowing"``; it stayed flat ⇒ ``"traversal"``.

This module is stage 2: it only smooths isolated single-point role stutters.
It deliberately does NOT use the cloud mowing track for a coverage "rescue".
On a full-lawn mow the cloud's blades-down segments blanket the whole lawn,
so a cross-area traversal — which drives over grass mowed earlier — sits
right on top of a past mowing segment. Proximity to the cloud path therefore
cannot distinguish "mowing now" from "driving over what I already mowed"
(both are area-flat). Only area-delta separates them, so it wins outright.
(Measured 2026-05-28 on a 2613-point all-area mow: every traversal point AND
every mowing point was ≤0.6 m from the cloud path — rescue flipped all 478
genuine traversals green.)

Pure (layer 2 — no HA imports) so it is unit-testable and reusable by the
probe-log rebuild / migration tools.
"""
from __future__ import annotations

from typing import Any


def classify_track(
    track: list[dict[str, Any]],
    *,
    smooth_passes: int = 3,
) -> list[dict[str, Any]]:
    """Smooth isolated role stutters (returns the same list, mutated in place).

    Any interior point whose role differs from BOTH neighbours flips to the
    neighbour role; repeated up to ``smooth_passes`` times. Neighbour roles
    are read from a per-pass snapshot so the result is scan-order independent.

    The per-point ``role`` it operates on was set authoritatively by the
    area-delta classifier at capture/reconstruction time; this pass only
    removes single-sample jitter at strip boundaries.
    """
    if not track:
        return track

    for _ in range(max(0, smooth_passes)):
        roles = [p["role"] for p in track]  # snapshot — order-independent pass
        changed = False
        for i in range(1, len(track) - 1):
            if roles[i - 1] == roles[i + 1] and track[i]["role"] != roles[i - 1]:
                track[i]["role"] = roles[i - 1]
                changed = True
        if not changed:
            break
    return track


# Session types whose finalize waits for the cloud OSS session-summary (md5)
# rather than finalizing locally. A mow obviously produces one; a PATROL does
# too — verified 2026-05-30 against the real patrol archive (mode=108, md5
# present, area≈0). The other non-mow types (maintenance_run / manual_drive)
# produce NO cloud summary and must finalize locally, else the finalize wait
# hangs and the next run merges in. Used by the coordinator's finalize-routing
# and new-command-split guards.
CLOUD_FINALIZED_SESSION_TYPES = frozenset({"mow", "patrol"})


def classify_session_type(
    *,
    last_task_op: int | None,
    saw_mow_start: bool,
    area_ever_positive: bool,
    last_point_end_code: int | None,
    saw_patrol_start: bool = False,
) -> tuple[str, str | None]:
    """Resolve (session_type, outcome) at finalize.

    Order (positive signals first):
      1. manual_drive  — s2p50 op=15 seen (manual/remote control).
      2. patrol        — s2p50 op=108 (cruise-side) OR s2p2=51 (patrol started).
         Blades-up, area=0, but produces a cloud OSS summary (mode=108) so it
         finalizes via the cloud path, NOT locally. Checked before `mow` and
         the maintenance default so a patrol that drifts past the dock (75/76)
         is still typed patrol.
      3. mow           — s2p2 50/53 start code seen OR area_mowed ever > 0.
      4. maintenance_run — the default non-mow run; outcome from the last
         point end-code: 75=arrived, 76=could_not_reach, else unknown.

    Returns (session_type, outcome). outcome is None for mow/patrol/manual_drive.
    """
    if last_task_op == 15:
        return "manual_drive", None
    if last_task_op == 108 or saw_patrol_start:
        return "patrol", None
    if saw_mow_start or area_ever_positive:
        return "mow", None
    outcome = {75: "arrived", 76: "could_not_reach"}.get(
        last_point_end_code, "unknown"
    )
    return "maintenance_run", outcome
