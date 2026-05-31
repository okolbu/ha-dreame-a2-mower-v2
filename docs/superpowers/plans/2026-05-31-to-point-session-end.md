# To-Point Session End (Option A) + Persistent Icon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** End a to-point (op=109) session when the mower ARRIVES at the point (not on dock-return), reset both session notions so it doesn't read "Charging mid-session", keep the return drive out of the session, and show the mower icon between sessions.

**Architecture:** A to-point run begins a `live_map` session on `s2p56 None→0` like a mow, but its task-end (`s2p56 0→2`, ~40s, then stuck at `[[1,2]]`) can be missed by the 60s finalize poll, and the non-mow finalize path waits 600s for the dock return (pulling the return into the session). Fix: trigger an immediate, dock-wait-free finalize for non-mow sessions on arrival — robustly via the `s2p2=75` (arrived_at_maintenance_point) event and the `s2p56 0→2` edge — that ends the `live_map` session AND resets the state-machine session. The return drive is `s2p1`-only (no `s2p56`), so once the session ends it can't be absorbed. Separately, render the mower icon at last-known position when no session is active.

**Tech Stack:** Python, pytest (`asyncio_mode=auto`), interpreter `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Conventions:** TDD per task; commit per task staging **explicit paths** (concurrent `add -A` process); on `main`; tests via `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v` from repo root; baseline ~1719 passed / 4 skipped.

**Reference:** spec `docs/superpowers/specs/2026-05-31-to-point-session-end-design.md`. Wire trace: `probe_log_20260520_131350.jsonl` 2026-05-31 15:51–15:59.

---

### Task 1: Pin the cause — reproduction test (RED, no fix yet)

**Goal:** Reproduce the traced to-point lifecycle through the state machine + finalize gate and assert the *current buggy* behavior, so the cause is documented before fixing. This task COMMITS a test that currently passes against the buggy code (it encodes today's behavior), then later tasks flip the assertions.

**Files:**
- Create: `tests/state_machine/test_to_point_session_end.py`
- Read first (understand APIs): `mower/state_machine.py` (snapshot, `_apply_s2p1_task_state`, `_apply_s2p50_task_envelope`, `mow_session`, `CurrentActivity`), `live_map/finalize.py:decide`, `coordinator/_session.py` (`_periodic_session_retry`, `_dispatch_finalize_action`, `_run_finalize_incomplete`, `_prev_task_state`, `_provisional_session_is_cloud_finalized`).

- [ ] **Step 1: Drive the lifecycle and capture current behavior.** Write a test that feeds the traced sequence into the state machine and the finalize gate and asserts WHAT HAPPENS TODAY (so it's green now). Cover at minimum: (a) after `s2p2=75` + `s2p1=2`, what is `mow_session` and `current_activity`; (b) `finalize.decide()` result on the `0→2` edge vs. on a later poll where `prev==2`; (c) the `s2p1=6` charge activity. Use the real classes; mock only I/O.

```python
"""Reproduce the to-point session-end bug (2026-05-31 trace). RED baseline."""
# Build the state machine; apply, in order:
#   s2p50 op=109 status:true ; s2p56 [[1,0]] ; s2p56 [[1,2]] ;
#   s2p1=2 ; s2p2=75 ; (dwell) ; s2p1=5 ; s2p1=6
# Assert the CURRENT outputs (mow_session, current_activity at the s2p1=6 step,
# and finalize.decide() on the 0->2 edge with prev=0 vs prev=2). Document via the
# assertions exactly what is stuck (e.g. session not ended / activity wrong).
```

- [ ] **Step 2: Run it green** (it encodes current behavior).

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/state_machine/test_to_point_session_end.py -v` → PASS.

- [ ] **Step 3: Record the pinned cause** in the test module docstring (which of: edge missed by poll / finalize-fires-but-doesn't-clear / mow_session re-set to IN_SESSION).

- [ ] **Step 4: Commit.**
```
git add tests/state_machine/test_to_point_session_end.py
git commit -m "test(to-point): reproduce session-end bug (RED baseline + pinned cause)"
```

**Controller note:** After Task 1, the implementer's report states the pinned cause. Use it to confirm/adjust Tasks 2–3's exact hook before dispatching them.

---

### Task 2: Finalize non-mow sessions on arrival, no dock-wait + reset both session notions

**Goal:** When a NON-cloud-finalized (non-mow: maintenance/manual) session ends, finalize immediately and reset both the `live_map` session and the state-machine `mow_session`, so `live_map.is_active()` is false and a later charge reads Idle/Docked.

**Files:**
- Modify: `coordinator/_session.py` — the non-cloud-finalized branch in `_dispatch_finalize_action` (around lines 565–576): drop the `_wait_for_dock_return(timeout_s=600)` for the non-mow path; finalize immediately. Ensure `_run_finalize_incomplete` (599–772) ends the `live_map` session AND resets the state-machine session (add a state-machine close if it doesn't already — read the state-machine's session-reset API; do NOT poke private fields if a method exists).
- Test: extend `tests/state_machine/test_to_point_session_end.py`.

- [ ] **Step 1: Flip the assertions (RED).** Change the Task-1 test (or add sibling tests) to assert the DESIRED behavior: after arrival (`s2p56 0→2` and/or `s2p2=75`), the non-mow session finalizes immediately (no dock-wait), `live_map.is_active()` is False, and the subsequent `s2p1=6` yields `current_activity` Idle/Docked (NOT `charge_resume`).

- [ ] **Step 2: Run → FAIL** (current code waits / doesn't reset).

- [ ] **Step 3: Implement.** In `_dispatch_finalize_action`'s non-cloud-finalized branch, do not call `_wait_for_dock_return` — call `_run_finalize_incomplete(now_unix)` directly. In `_run_finalize_incomplete`, after `live_map.end_session()`, ensure the state-machine session is closed (use the state machine's existing reset/transition API; if none exists, add a minimal `end_session()`/`set_between_sessions()` method on the state machine and call it). Keep the mow/patrol (cloud-finalized) path unchanged (it still waits for dock).

- [ ] **Step 4: Run → PASS**, then the full session + state-machine suites:
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/state_machine/ tests/integration/ -q` → no regressions.

- [ ] **Step 5: Commit** (explicit paths for `_session.py`, any `state_machine.py` change, the test).

---

### Task 3: `s2p2=75` backstop finalize trigger for to-point

**Goal:** Make end-on-arrival robust to a missed/late `s2p56 0→2` edge by also finalizing the to-point session on `s2p2=75` (arrived_at_maintenance_point), when a non-mow session is active.

**Files:**
- Modify: the `s2p2=75` handling (`mower/state_machine.py:180-184` sets `location/current_activity`) and/or the coordinator event hook that reacts to s2p2 codes — wire it to request a non-mow finalize when a session is active and the provisional type is non-cloud-finalized. (Read how s2p2 events reach the coordinator: `coordinator/_mqtt_handlers.py` / `_lidar_oss.py:168` records 75 for classification — find the live hook.)
- Test: extend the to-point test — a run that emits `s2p2=75` but whose `s2p56` stays `[[1,0]]` (edge never delivered) still finalizes on 75.

- [ ] **Step 1: Test (RED)** — drive `s2p56 [[1,0]]` then `s2p2=75` (no `0→2`), assert session finalizes + `is_active()` False.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the 75-triggered finalize for an active non-mow session (guard: only when a session is active AND provisional type is non-cloud-finalized — never finalize a mow on 75).
- [ ] **Step 4: Run → PASS** + targeted suites green.
- [ ] **Step 5: Commit** (explicit paths).

---

### Task 4: Regression — return drive is not absorbed into the session

**Goal:** Lock the user's constraint: after the to-point session ends at arrival, the `s2p1` RETURNING/CHARGING drive is NOT in the archived session and does NOT seed the next session.

**Files:**
- Test only: extend `tests/state_machine/test_to_point_session_end.py` (or a sibling in `tests/live_map/` if archive assembly is needed).

- [ ] **Step 1: Test (RED→GREEN with Task 2/3 fix).** Drive arrival→finalize, then `s2p1 2→5→6` (return), then a NEW `s2p56 []→[[1,0]]` (next session). Assert: (a) no `begin_session` fired for the return (no `s2p56` change during it), (b) the archived to-point session's points end at the arrival point (no return points), (c) the next session starts with an empty trail (no carried-over points).
- [ ] **Step 2: Run → PASS** (the Task 2/3 fix should make this green; if not, the fix is incomplete — fix it).
- [ ] **Step 3: Commit** (explicit path).

---

### Task 5: Persistent mower icon between sessions

**Goal:** Draw the mower at its last-known position (state-machine snapshot) on the main view when `live_map.is_active()` is False, so the return/idle is visible without an open session.

**Files:**
- Read: `coordinator/_rendering.py` (`_render_main_view`, `_current_mower_position` 84–108, the `is_active()` gate at line 130), `map_render/main_view.py` / `base_map.py` / `trail.py` (icon draw).
- Modify: whichever of the render path currently omits the icon between sessions — ensure `render_main_view` draws the icon at `_current_mower_position()` even with no active session, and that a position update between sessions triggers a re-render (so it's not stale at the last MAPL render).
- Test: `tests/` render test asserting the main-view image has the mower icon at the snapshot position when no session is active.

- [ ] **Step 1: Test (RED)** — render the main view with `live_map.is_active()` False and a known snapshot position; assert the icon pixels are present at the expected location (mirror the existing render tests' pixel-checking approach, e.g. `tests/protocol/test_render_main_view_idle.py`).
- [ ] **Step 2: Run → FAIL** (if currently omitted) — if it already passes, record that no code change is needed and skip to Step 4 (the spec flagged this as possibly already working; verify, don't assume).
- [ ] **Step 3: Implement** the persistent-icon draw / re-render trigger.
- [ ] **Step 4: Run → PASS** + render suite green.
- [ ] **Step 5: Commit** (explicit paths).

---

### Task 6: Full suite + ship

- [ ] **Step 1:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q` → all green (baseline + new), 0 failures.
- [ ] **Step 2:** Update `inventory.yaml` (s2p2=75 now drives to-point finalize) and/or `entity-inventory.yaml` only if a surfaced behavior/source changed; otherwise skip (no entity added).
- [ ] **Step 3:** Bump + release via `PATH=/data/claude/homeassistant/.venv-vanilla/bin:$PATH tools/release.sh` (auto-bumps the alpha; honors the digit-boundary patch-bump rule). Pre-flight: clean tree, push main first if local is ahead of origin (fast-forward), back-to-back to dodge the concurrent-sweep sync check.
- [ ] **Step 4:** Move the spec + plan to `OLD/ha-dreame-a2-mower-docs/superpowers/` (doc-lifecycle rule) once shipped; do the same for the go-to-point spec/plan now that that feature shipped.

---

## Self-review notes
- **Spec coverage:** finalize-on-arrival + reset both sessions (T2), s2p2=75 backstop (T3), return-not-absorbed (T4), persistent icon (T5), pin-cause-first (T1), ship + doc-lifecycle (T6). All spec requirements mapped.
- **Diagnosis-first:** T1 pins the cause; the controller confirms it before T2/T3 exact hooks. Fix tasks specify behavior + verified hook ranges + tests (success = tests), and instruct reading surrounding code for the precise edit — appropriate for a debugging fix.
- **Risk flags:** (a) the state-machine session-reset API may not exist — add a minimal method rather than poking privates; (b) T5 may be a no-op if the icon already persists — verify with the RED test, don't assume; (c) never finalize a mow/patrol on `s2p2=75` (guard on non-cloud-finalized provisional type).
