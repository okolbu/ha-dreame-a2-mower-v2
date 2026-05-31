# To-Point session end + persistent mower icon — design

**Date:** 2026-05-31
**Status:** approved (design direction = Option A), pre-implementation
**Follows:** the go-to-point feature (op=109, shipped v1.0.20a4). This fixes the
session *lifecycle* for to-point runs.

## Problem (observed + traced)

After a Head-to-Point run + Recharge, the integration stays stuck:
`current_activity = "Charging mid-session"` and the live map keeps showing the
to-point trail **and** the return drive (i.e. the session never ends).

**Wire trace (2026-05-31, probe_log_20260520_131350.jsonl):**
```
15:51:25  s2p50 o=109 status:true ; s2p56 [] → [[1,0]]   (session BEGIN, task_state 0)
15:52:05  s2p56 [[1,0]] → [[1,2]]                          (ARRIVED, task_state 2) — stays [[1,2]]
15:52:06  s2p1 1→2 (MOWING→IDLE) ; s2p2 48→75 (arrived_at_maintenance_point)
15:57:44  s2p1 2→5 (IDLE→RETURNING)                        (user Recharge)
15:59:07  s2p1 5→6 (RETURNING→CHARGING)                    (docked)
```

Key facts:
- The **return drive emits NO s2p56 task** — it is pure `s2p1` state changes. So
  it cannot trigger `begin_session` (keyed on s2p56 `None→non-None`). The ONLY way
  the return gets absorbed into a session is if the to-point session **stays open**
  through it — which is the current bug.
- `s2p56` reaches `[[1,2]]` (task_state 2) at arrival and **never returns to `[]`**.
- There are **two** session notions, both of which must end cleanly:
  1. `live_map` session — `begin_session`/`end_session`/`is_active`
     (`coordinator/_mqtt_handlers.py:362`, `live_map/`). Drives the trail render.
  2. state-machine `mow_session` (`IN_SESSION`/`BETWEEN_SESSIONS`,
     `mower/state_machine.py`). Drives `current_activity`; `charge_resume`
     ("Charging mid-session") fires only when `mow_session == IN_SESSION`
     (`state_machine.py:98-106`).
- The current **non-mow finalize path deliberately waits for the dock return**
  (`coordinator/_session.py:565-576` → `_wait_for_dock_return(timeout_s=600)`),
  which is the *opposite* of what Option A wants and would pull the return into the
  session.

## Decision: Option A — end the to-point session on ARRIVAL

The "head to point" task is complete when the mower reaches the point. End the
session there; the return-to-dock is shown by a persistent mower icon, not a
session trail.

### Requirements

1. **Finalize non-mow sessions immediately on task-end** (`s2p56` `0/4 → 2`),
   WITHOUT the dock-return wait. End the `live_map` session at the point. (Mow and
   patrol — cloud-finalized types — keep their existing dock-wait behaviour;
   this changes ONLY the non-cloud-finalized / non-mow path.)
2. **Reset BOTH session notions on that finalize** so a subsequent dock reads
   `Idle`/`Docked` (not `Charging mid-session`) and `live_map.is_active()` is false.
3. **`s2p2=75` (arrived_at_maintenance_point) backstop:** also trigger the
   to-point finalize on s2p2=75, so end-on-arrival is robust if the `s2p56` stage-2
   push is delayed or missed.
4. **Do not absorb the return into the next session** (explicit user constraint):
   because the return is s2p1-only and the session is ended at arrival, the return
   points are not captured and cannot seed the next session. This must be pinned by
   a regression test.
5. **Persistent mower icon:** draw the mower at its last-known position
   (state-machine snapshot) on the main view between sessions, so the return and
   idle-at-dock remain visible without an open session.

### Out of scope
- Capturing the return-to-dock as part of the session record (that was Option B).
- Mow/patrol finalize behaviour (unchanged).

## Hook points (from code read; to be confirmed in Task 1)

- Finalize gate (fires on `0/4 → 2/None`): `live_map/finalize.py:95-103`.
- Non-mow dispatch (the 600s wait to remove for non-mow): `coordinator/_session.py:565-576`.
- `_run_finalize_incomplete` (must end live_map AND reset state-machine session):
  `coordinator/_session.py:599-772`.
- `s2p2=75` handling: `mower/state_machine.py:180-184`.
- `charge_resume` derivation: `mower/state_machine.py:98-106`; `s2p1=2`→
  `mow_session=BETWEEN_SESSIONS`: `state_machine.py:112-113`.
- op-type → session-type classification (`maintenance_run` is non-cloud-finalized):
  `_provisional_session_is_cloud_finalized` `coordinator/_session.py:524-533`.
- Mower-icon render between sessions: `coordinator/_rendering.py:_render_main_view`
  (uses `_current_mower_position` snapshot, `_rendering.py:84-108`); icon draw in
  `map_render/trail.py` / `base_map.py`.

## Open question to pin first (plan Task 1)

Static reading is contradictory with the observed `Charging mid-session`: `s2p1=2`
at arrival *should* set `mow_session=BETWEEN_SESSIONS`, yet the mower later reads
`charge_resume` (which needs `IN_SESSION`). So either the finalize never fires, or
it fires but doesn't clear one of the two session notions, or `mow_session` is
re-set to `IN_SESSION` somewhere on the to-point path. Task 1 reproduces the traced
lifecycle in a unit test to pin which, so the fix addresses the real cause rather
than papering over it.

## Testing (TDD)
- Reproduce the traced to-point lifecycle (`s2p56 []→[[1,0]]→[[1,2]]`, `s2p1
  1→2→5→6`, `s2p2 75`) and assert: session finalizes at arrival; `live_map.is_active()`
  false afterward; `current_activity` on the later `s2p1=6` is Idle/Docked (not
  `charge_resume`).
- Return-not-absorbed: after finalize, the s2p1 RETURNING/CHARGING points are NOT in
  the archived to-point session, and a subsequent real session begins with no
  carried-over points.
- `s2p2=75` backstop: a to-point run that emits 75 but a delayed `s2p56` still
  finalizes on 75.
- Persistent icon: `_render_main_view` produces an image with the mower icon at the
  snapshot position when `live_map.is_active()` is false.
