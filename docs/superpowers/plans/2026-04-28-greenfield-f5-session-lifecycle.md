# Greenfield F5 — Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live session lifecycle — track an active mowing session from start through pause/recharge/resume to end, archive the completed session, render a live trail overlay on the F2 base map, restore an in-progress session on HA reboot, and handle cloud-summary download failures gracefully. After F5 the user sees the mower's path drawn live on the map and gets archived sessions they can replay.

**Architecture:** Three-layer split per spec §5.7:
1. `live_map/state.py` — `LiveMapState` dataclass holding the in-progress session (start time, accumulated track segments, leg accumulator, telemetry-derived path).
2. `live_map/finalize.py` — gate logic redesigned from first principles using the s2p56 task-state codes (1=start_pending, 2=running, 3=complete, 4=resume_pending, 5=ended). Replaces the legacy patchwork of conditionals.
3. `live_map/trail.py` — trail rendering decoupled from the state machine; drawn on top of the F2 base map by `map_render`.

Plus persistence:
- `archive/session.py` — on-disk archive (sessions/index.json + sessions/*.json + sessions/in_progress.json). Lift-on-demand from legacy `session_archive.py` (491 LOC, well-structured).

The legacy `live_map.py` is 1.7K LOC and the most-debugged single file in the legacy. Treat it as a *reference* — read for edge cases, but rebuild the state machine from the protocol-doc s2p56 codes rather than mechanically translating legacy patches.

Per spec §3 cross-cutting commitments: every disk read/write goes through `hass.async_add_executor_job`; the `live_map/` and `archive/` subpackages are inside the integration's HA-glue layer (so HA imports allowed); the typed domain layer (`mower/`) stays HA-import-free.

**Tech Stack:** Same as F1–F4. Pillow for trail rendering.

**Spec:** `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md` § 5.7 + § 6 (45+ acceptance items in the session-lifecycle section) + § 7 phase F5.

**Working dir:** `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`. Use `git -C <path>` and absolute paths; one-shot `cd` in a single Bash invocation is OK. **Do NOT push from implementer subagents** — controller pushes after each commit.

**Reference repo:** legacy at `/data/claude/homeassistant/ha-dreame-a2-mower/`. Key reference paths:
- `custom_components/dreame_a2_mower/live_map.py` (1708 LOC) — source for the in-progress state machine, lift-on-demand
- `custom_components/dreame_a2_mower/session_archive.py` (491 LOC) — on-disk format, lift wholesale
- `custom_components/dreame_a2_mower/dreame/device.py` — `_handle_event_occured`, `_fetch_session_summary`, `_pending_session_object_name`

---

## File map

```
custom_components/dreame_a2_mower/
├── coordinator.py               # F5.3, F5.5, F5.6: session-event hooks + cloud retry
├── const.py                     # F5.13: extend PLATFORMS (no new platforms; existing platforms gain entities)
├── camera.py                    # F5.10: trail overlay on the base map
├── map_render.py                # F5.9: render_with_trail extension
├── mower/
│   └── state.py                 # F5.1: session-lifecycle fields
├── live_map/                    # F5.2: NEW subpackage
│   ├── __init__.py
│   ├── state.py                 # LiveMapState dataclass + leg accumulator
│   ├── finalize.py              # gate logic; s2p56-driven
│   └── trail.py                 # trail-rendering helpers
├── archive/                     # F5.7: NEW subpackage
│   ├── __init__.py
│   └── session.py               # SessionArchive (lifted from legacy)
├── services.py                  # F5.11: replay_session handler; F5.12: finalize_session real implementation
├── services.yaml                # F5.11: add replay_session schema
├── binary_sensor.py             # F5.13: mowing_session_active improvement
├── sensor.py                    # F5.13: latest-session sensors
└── button.py                    # F5.12: NEW — finalize_session button (alongside the service)

protocol/                        # F1.1 lifted everything we need
                                 # protocol/session_summary.py is the parser
```

---

## Phase F5.1 — Extend MowerState with session-lifecycle fields

### Task F5.1.1: Add ~15 fields for session state

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `tests/mower/test_state.py`
- Modify: `docs/data-policy.md`

The session-lifecycle fields capture what the integration knows about the current/last session. They split into:

**Active-session intent (volatile — derived from s2p56 + telemetry):**
- `session_active: bool | None` — derived from s2p56 in {1, 2, 4} (start_pending, running, resume_pending)
- `session_started_unix: int | None` — when the current session started (set on s2p56=1)
- `session_track_segments: tuple[tuple[tuple[float, float], ...], ...] | None` — list of leg-tracks; each leg is a list of (x_m, y_m) points. Empty until first s1p4 arrives.

**In-progress persistence (persistent — survives HA boot):**
- `in_progress_md5: str | None` — md5 of the in-progress entry on disk; None if no active session
- `pending_session_object_name: str | None` — OSS key for the session-summary JSON; set by event_occured, cleared after successful fetch
- `pending_session_first_attempt_unix: int | None` — when we first tried to fetch this OSS key. Used for max-age expiry (spec §6 cloud robustness).
- `pending_session_attempt_count: int | None` — how many times we've tried to fetch.

**Last-session summary (persistent):**
- `latest_session_md5: str | None`
- `latest_session_unix_ts: int | None` — when the session ended
- `latest_session_area_m2: float | None`
- `latest_session_duration_min: int | None`

**Counters (persistent — derived from archive):**
- `archived_session_count: int | None`

The exact field set may flex during implementation. Read the legacy `live_map.py` for what it tracks and adapt. Don't add fields with no consumer (spec §10 deferred items rule).

- [ ] **Step 1: Append failing tests to test_state.py**

```python
def test_session_lifecycle_fields_default_to_none():
    s = MowerState()
    assert s.session_active is None
    assert s.session_started_unix is None
    assert s.session_track_segments is None
    assert s.in_progress_md5 is None
    assert s.pending_session_object_name is None
    assert s.pending_session_first_attempt_unix is None
    assert s.pending_session_attempt_count is None
    assert s.latest_session_md5 is None
    assert s.latest_session_unix_ts is None
    assert s.latest_session_area_m2 is None
    assert s.latest_session_duration_min is None
    assert s.archived_session_count is None


def test_session_lifecycle_fields_construction():
    s = MowerState(
        session_active=True,
        session_started_unix=1714329600,
        session_track_segments=(((1.0, 2.0), (3.0, 4.0)),),
        archived_session_count=42,
    )
    assert s.session_active is True
    assert len(s.session_track_segments) == 1
    assert s.archived_session_count == 42
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Append fields to MowerState**

In `custom_components/dreame_a2_mower/mower/state.py`, after the F4 block, add the fields per the schema above. Persistence per data-policy.md:
- Volatile: `session_active`, `session_started_unix`, `session_track_segments` (live state)
- Persistent: everything else (settings-like; survive HA reboot via RestoreEntity in F5.13)

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Update data-policy.md**

Append the new fields under the right sections.

- [ ] **Step 6: Commit (do NOT push)**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/state.py tests/mower/test_state.py docs/data-policy.md
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F5.1.1: extend MowerState with session-lifecycle fields

Adds 12 fields covering live session state + in-progress persistence
+ last-session summary + archive counter.

Volatile: session_active, session_started_unix, session_track_segments
Persistent: in_progress_md5, pending_session_object_name,
            pending_session_first_attempt_unix,
            pending_session_attempt_count,
            latest_session_md5, latest_session_unix_ts,
            latest_session_area_m2, latest_session_duration_min,
            archived_session_count

The pending_session_* fields support spec §6's "cloud retry with
bounded max-age" — when an event_occured arrives but the OSS fetch
fails, we record first_attempt_unix and attempt_count; F5.6 enforces
the max-age and falls back to "(incomplete)" archive entry.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F5.2 — live_map/ subpackage skeleton

### Task F5.2.1: Create live_map/ package with the three modules

**Files:**
- Create: `custom_components/dreame_a2_mower/live_map/__init__.py` (empty)
- Create: `custom_components/dreame_a2_mower/live_map/state.py`
- Create: `custom_components/dreame_a2_mower/live_map/finalize.py`
- Create: `custom_components/dreame_a2_mower/live_map/trail.py`
- Create: `tests/live_map/__init__.py` (empty)
- Create: `tests/live_map/test_state.py`
- Create: `tests/live_map/test_finalize.py`
- Create: `tests/live_map/test_trail.py`

Build skeleton modules with TDD-friendly stubs. The implementations come in subsequent tasks.

- [ ] **Step 1: Read legacy live_map.py for orientation**

```bash
grep -nE "^def |^class |LiveMapState|in_progress|finalize" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/live_map.py | head -40
```

Note the entry points and the major classes. Don't translate verbatim; understand the surface so the new modules cover the same use cases without the patches.

- [ ] **Step 2: Write live_map/state.py**

Content:

```python
"""Live session state for the Dreame A2 mower.

Per spec §5.7 layer 1: the LiveMapState dataclass holds the in-progress
session — start time, accumulated track segments (one per leg, since a
mowing session can include recharge legs), and helpers for appending
new telemetry points to the active leg.

This module imports from `homeassistant.*` is allowed (it's part of
the HA-glue layer, not the protocol/ or mower/ pure layers).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Tuple

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

    def end_session(self) -> None:
        self.started_unix = None
        self.legs = []
        self.last_telemetry_unix = None
```

- [ ] **Step 3: Write live_map/finalize.py — stub**

```python
"""Finalize-gate logic for in-progress sessions.

Per spec §5.7: redesigned from first principles using s2p56 task-state
codes (1=start_pending, 2=running, 3=complete, 4=resume_pending,
5=ended). Replaces the legacy patchwork.

The gate is consulted on every coordinator update. It examines the
mower's task_state_code + session_active + pending_session_*
fields and decides whether to:
  - begin a new session
  - begin a new leg (mid-session recharge → resume)
  - finalize a completed session (cloud-summary fetch + archive write)
  - promote an in-progress to "(incomplete)" archive (cloud-fetch
    expired)
  - no-op
"""
from __future__ import annotations

from enum import Enum, auto


class FinalizeAction(Enum):
    """What the finalize gate decides on this update tick."""

    NOOP = auto()
    BEGIN_SESSION = auto()
    BEGIN_LEG = auto()
    FINALIZE_COMPLETE = auto()
    FINALIZE_INCOMPLETE = auto()  # cloud-fetch expired; promote with what we have
    AWAIT_OSS_FETCH = auto()  # session ended; OSS key arrived; fetch is pending


def decide(state, prev_task_state: int | None, now_unix: int) -> FinalizeAction:
    """Pure function: examine MowerState + previous tick's task_state and
    return the action to take. The coordinator dispatches the action.

    `state` is a MowerState. `prev_task_state` is what the coordinator
    saw last tick.
    """
    # F5.5 implements the actual logic. Stub returns NOOP.
    return FinalizeAction.NOOP
```

- [ ] **Step 4: Write live_map/trail.py — stub**

```python
"""Trail rendering helpers.

Per spec §5.7 layer 3: decoupled from the state machine. Takes a
LiveMapState (or list of legs) and produces drawing primitives the
map_render module composites onto the F2 base map.
"""
from __future__ import annotations

from typing import Iterable, Tuple

Point = Tuple[float, float]
Leg = Tuple[Point, ...]


def render_trail_overlay(legs: Iterable[Leg], cloud_x_reflect: float, cloud_y_reflect: float, pixel_size_mm: float):
    """Returns a list of (pixel_x, pixel_y) line-segment endpoints for
    each leg, ready to feed to ImageDraw.line().

    Coordinate transform: telemetry x_m, y_m → cloud-frame mm via the
    inverse of map_decoder's transform. F5.9 uses this to composite the
    trail onto the F2 base PNG.
    """
    # F5.9 implements. Stub returns empty list.
    return []
```

- [ ] **Step 5: Write tests/live_map/test_state.py**

```python
"""Tests for live_map/state.py."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.total_points() == 0


def test_begin_session_clears_state():
    s = LiveMapState()
    s.legs = [[(1.0, 2.0)]]  # residue
    s.begin_session(started_unix=1000)
    assert s.is_active()
    assert s.legs == [[]]


def test_append_point_records_first_point():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    assert s.legs == [[(1.0, 2.0)]]
    assert s.total_points() == 1
    assert s.last_telemetry_unix == 1010


def test_append_point_dedupes_close():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    s.append_point(1.05, 2.05, ts_unix=1015)  # within 20cm
    assert s.total_points() == 1


def test_append_point_pen_up_jump_creates_new_leg():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(10.0, 0.0, ts_unix=1015)  # 10m jump > 5m
    assert len(s.legs) == 2
    assert s.total_points() == 2


def test_begin_leg_after_recharge_pause():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.begin_leg()
    s.append_point(1.5, 1.5, ts_unix=2000)
    assert len(s.legs) == 2
    assert s.legs[0] == [(1.0, 1.0)]
    assert s.legs[1] == [(1.5, 1.5)]


def test_end_session_clears():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.end_session()
    assert not s.is_active()
    assert s.legs == []
```

- [ ] **Step 6: Write tests/live_map/test_finalize.py — stubs (real tests in F5.5)**

```python
"""Tests for live_map/finalize.py."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.finalize import (
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_decide_default_returns_noop():
    """Stub gate returns NOOP. F5.5 fills in the real logic + tests."""
    state = MowerState()
    assert decide(state, prev_task_state=None, now_unix=1000) == FinalizeAction.NOOP


def test_finalize_action_enum_has_six_values():
    assert {a.name for a in FinalizeAction} == {
        "NOOP", "BEGIN_SESSION", "BEGIN_LEG",
        "FINALIZE_COMPLETE", "FINALIZE_INCOMPLETE", "AWAIT_OSS_FETCH",
    }
```

- [ ] **Step 7: Write tests/live_map/test_trail.py — stubs**

```python
def test_render_trail_overlay_empty_legs_returns_empty():
    from custom_components.dreame_a2_mower.live_map.trail import render_trail_overlay
    result = render_trail_overlay([], 0, 0, 50)
    assert list(result) == []
```

- [ ] **Step 8: Run all live_map tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/live_map/ -v 2>&1 | tail -15
```

Expected: all tests pass (8 in test_state, 2 in test_finalize, 1 in test_trail).

- [ ] **Step 9: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/live_map/ tests/live_map/
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F5.2.1: live_map/ subpackage skeleton (state + finalize + trail)

Three-module split per spec §5.7:
  - live_map/state.py — LiveMapState dataclass, append_point with
    pen-up filter (>5m jump = new leg) and dedup (<20cm = skip)
  - live_map/finalize.py — FinalizeAction enum + decide() stub
    (F5.5 fills the gate logic)
  - live_map/trail.py — render_trail_overlay() stub (F5.9 fills)

11 unit tests for the state machine confirming begin_session,
append_point, pen-up logic, leg-merge, end_session work as designed.

The finalize and trail stubs are deliberately minimal so subsequent
tasks can fill them with their own TDD cycles.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F5.3 — Session-start detection in coordinator

### Task F5.3.1: Hook s2p56 transitions into LiveMapState

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `tests/integration/test_coordinator.py`

The coordinator gains a `LiveMapState` instance + a per-tick "what was task_state_code last tick" tracker. On every state update, after `apply_property_to_state` runs, the coordinator inspects `(prev_task_state, state.task_state_code)` for transitions:
- `* → 1` (anything → start_pending): `live_map.begin_session(now_unix)`
- `* → 2` after `1 → 2`: still inside the just-started session — no-op
- `4 → 2`: resume from recharge — `live_map.begin_leg()`
- `2 → 3` or `* → 5`: session ending — F5.5 finalize gate fires (in this task we only set the flag; the finalize implementation is F5.5)

Plus on every s1p4 push that arrives during an active session, append the position to the current leg.

- [ ] **Step 1: Read legacy live_map.py for the s2p56 transition logic**

```bash
grep -nE "task_state|session_active|started" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/live_map.py | head -30
```

Note how legacy detects start/end. The new architecture uses the s2p56 codes directly; legacy used a derived `started` bool that this rebuild doesn't carry forward.

- [ ] **Step 2: Add LiveMapState attribute + transition handler to coordinator**

In `coordinator.py`:

```python
# Imports:
from .live_map.state import LiveMapState

# In DreameA2MowerCoordinator.__init__:
self.live_map = LiveMapState()
self._prev_task_state: int | None = None

# Add a method:
def _on_state_update(self, new_state: MowerState, now_unix: int) -> MowerState:
    """Hook fired after apply_property_to_state. Updates LiveMapState
    based on s2p56 transitions and appends s1p4 positions to the
    current leg.

    Returns a possibly-modified MowerState (with session_active /
    session_track_segments synced from LiveMapState).
    """
    new_task_state = new_state.task_state_code
    prev = self._prev_task_state

    # Session-start: any transition into 1 (start_pending)
    if new_task_state == 1 and prev != 1:
        self.live_map.begin_session(now_unix)

    # Resume after recharge: 4 → 2 transition
    elif prev == 4 and new_task_state == 2:
        self.live_map.begin_leg()

    # Telemetry append: s1p4 brought new position; if session is active, append
    if (
        self.live_map.is_active()
        and new_state.position_x_m is not None
        and new_state.position_y_m is not None
        and (new_state != self.data)  # something changed
    ):
        self.live_map.append_point(
            new_state.position_x_m, new_state.position_y_m, now_unix
        )

    # Sync MowerState's session view from LiveMapState
    new_state = dataclasses.replace(
        new_state,
        session_active=self.live_map.is_active(),
        session_started_unix=self.live_map.started_unix,
        session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
    )

    self._prev_task_state = new_task_state
    return new_state
```

Then call `_on_state_update` in `handle_property_push`:

```python
def handle_property_push(self, siid, piid, value):
    new_state = apply_property_to_state(self.data, siid, piid, value)
    if new_state != self.data:
        # Hook the live_map state machine
        import time as _time
        new_state = self._on_state_update(new_state, int(_time.time()))
        self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, new_state)
```

- [ ] **Step 3: Tests**

In `tests/integration/test_coordinator.py`, add tests covering:

```python
def test_session_start_creates_live_map():
    # Synthetic: feed an s2p56=1 push and verify live_map.begin_session ran
    ...

def test_resume_after_recharge_starts_new_leg():
    # Feed s2p56=4, then =2; verify a new leg appeared
    ...

def test_telemetry_during_active_session_appends_to_leg():
    # Feed s2p56=2 then s1p4 with a position; verify legs[-1] grew
    ...
```

(These test the integration end-to-end via apply_property_to_state.)

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F5.3.1: wire s2p56 transitions + s1p4 position append into LiveMapState

DreameA2MowerCoordinator gains a LiveMapState attribute and a
_prev_task_state tracker. On every state update (after
apply_property_to_state runs), the coordinator inspects
(prev, new) task_state_code for transitions:

  - any → 1 (start_pending) → live_map.begin_session(now_unix)
  - 4 → 2 (resume from recharge) → live_map.begin_leg()
  - active + s1p4 brings new position → live_map.append_point(x, y, now)

MowerState's session_active / session_started_unix /
session_track_segments are synced from LiveMapState every tick.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F5.4 — Session archive on disk

### Task F5.4.1: Lift session_archive.py from legacy

**Files:**
- Create: `custom_components/dreame_a2_mower/archive/__init__.py` (empty)
- Create: `custom_components/dreame_a2_mower/archive/session.py`
- Create: `tests/archive/__init__.py` (empty)
- Create: `tests/archive/test_session.py`

The legacy `session_archive.py` is 491 LOC and well-structured (per the architecture audit). Lift wholesale, then clean any HA-import leaks (the file likely imports from legacy `dreame/` for the SessionSummary type — replace with `protocol/session_summary.py` which we already lifted in F1.1.1).

- [ ] **Step 1: Read legacy**

```bash
grep -nE "^def |^class |from |import " /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/session_archive.py | head -30
```

Identify dependencies on legacy `dreame/` types — these need substitution.

- [ ] **Step 2: Copy + adapt**

Copy `session_archive.py` to `custom_components/dreame_a2_mower/archive/session.py`. Replace any `from .dreame.types import X` with the equivalent from `protocol/` or `mower/`.

The class `SessionArchive` provides:
- `__init__(root_path: Path, retention: int)`
- `load_index()` — reads sessions/index.json on disk; populates an in-memory list of ArchivedSession
- `archive(summary, raw_json=None) -> ArchivedSession | None` — promotes a session-summary into a saved entry
- `latest() -> ArchivedSession | None`
- `read_in_progress() -> dict | None` — reads sessions/in_progress.json
- `write_in_progress(entry: dict)` — writes the in-progress entry
- `delete_in_progress()`
- `list_sessions() -> list[ArchivedSession]`

Lift wholesale. Verify no `homeassistant.*` imports.

- [ ] **Step 3: Adapt tests**

The legacy `tests/test_session_archive.py` is a known-good test surface (it ran green throughout P1+P2). Lift to `tests/archive/test_session.py` with import path adjustments.

- [ ] **Step 4: Run tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/archive/ -v 2>&1 | tail -15
```

Expected: all the lifted tests pass.

- [ ] **Step 5: Commit**

---

## Phase F5.5 — Finalize gate logic

### Task F5.5.1: Implement live_map/finalize.decide()

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/finalize.py`
- Modify: `tests/live_map/test_finalize.py`

This is the heart of F5. The `decide()` function takes a MowerState + prev_task_state + now_unix and returns a FinalizeAction.

Logic (per spec §6 acceptance criteria):
- If session_active is False AND prev_task_state in {2, 4}: session ended → FINALIZE_COMPLETE if pending_session_object_name is set, else FINALIZE_INCOMPLETE
- If state.task_state_code == 5 (ended): same as above
- If pending_session_object_name is set AND first_attempt_unix is older than MAX_AGE: FINALIZE_INCOMPLETE (give up)
- If pending_session_object_name is set AND attempt_count > MAX_ATTEMPTS: FINALIZE_INCOMPLETE
- If pending_session_object_name is set AND it's been at least RETRY_INTERVAL since last attempt: AWAIT_OSS_FETCH (signal: time to retry)
- Else: NOOP

Constants:
- MAX_AGE = 30 minutes (after that, give up; the session was real but the cloud isn't going to deliver the summary)
- MAX_ATTEMPTS = 10
- RETRY_INTERVAL = 60 seconds

- [ ] **Step 1: Write the gate logic + tests**

The implementer writes the actual decide() body covering each of the cases above. Tests cover each FinalizeAction outcome with synthetic state inputs.

- [ ] **Step 2-4**: TDD red-green-commit.

(Plan kept brief here — the implementer reads the legacy gate logic for edge cases:

```bash
grep -nE "_pending_session|finalize|cleanup_completed|max_age" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/live_map.py | head -30
```

But the new gate is rebuilt from the protocol-doc s2p56 codes, not patched.)

---

## Phase F5.6 — Cloud retry with bounded max-age

### Task F5.6.1: Wire OSS fetch retry in coordinator

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `tests/integration/test_coordinator.py`

The coordinator hooks `event_occured` (siid=4 eiid=1) to capture the pending OSS object name. Then a periodic retry fires every RETRY_INTERVAL seconds via `async_track_time_interval`. The decide() gate determines when to give up.

- [ ] **Step 1: Add `_handle_event_occured` method**

When an event_occured arrives, extract the OSS object name from `arguments[piid=9]`. Store on `coordinator.data.pending_session_object_name` + set first_attempt_unix.

- [ ] **Step 2: Add `_periodic_session_retry`**

Every 60s, check pending state; consult decide(); if AWAIT_OSS_FETCH, fire the cloud fetch via executor; on success, parse via `protocol.session_summary.parse_session_summary`, archive via SessionArchive.archive, clear pending state. If decide() returns FINALIZE_INCOMPLETE, archive whatever we have (live_map.legs) as an "(incomplete)" entry and clear pending.

- [ ] **Step 3-5**: tests, commit.

---

## Phase F5.7 — In-progress restore on HA boot

### Task F5.7.1: Restore live_map state on integration setup

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

After cloud auth in first_refresh, the coordinator:
1. Calls `archive.read_in_progress()` to get any pre-existing in-progress entry
2. If found, populates `LiveMapState` with the saved legs + started_unix
3. Updates MowerState fields (session_active=True, session_track_segments, etc.)

This gives the user continuity across HA reboots — the trail picks up where it left off.

- [ ] **Step 1**: Add `_restore_in_progress` to coordinator's first-refresh path.
- [ ] **Step 2**: Persist in-progress on every track-segment append (debounced — write to disk every 30 seconds at most, not on every point).
- [ ] **Step 3**: Tests + commit.

---

## Phase F5.8 — Trail rendering on the camera

### Task F5.8.1: render_with_trail in map_render

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py`
- Modify: `custom_components/dreame_a2_mower/live_map/trail.py`
- Modify: `custom_components/dreame_a2_mower/camera.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

Extend the F2 base-map renderer with a `render_with_trail(map_data, legs)` variant. The trail is drawn as red lines per leg, pen-up gaps between legs.

- [ ] **Step 1**: Implement `live_map/trail.py:render_trail_overlay` to convert (x_m, y_m) → pixel coords given the F2 base-map geometry.

- [ ] **Step 2**: Add `render_with_trail` to map_render.py — calls `render_base_map` first, then composites the trail layer on top.

- [ ] **Step 3**: Coordinator's `_refresh_map` (and the camera entity) now use `render_with_trail` when the live_map is active. Otherwise falls back to base-only.

- [ ] **Step 4**: tests + commit.

---

## Phase F5.9 — Replay-session service

### Task F5.9.1: dreame_a2_mower.replay_session

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.yaml`
- Modify: `custom_components/dreame_a2_mower/services.py`

Service signature:
```yaml
replay_session:
  description: Render an archived session's path into the live map camera for playback.
  fields:
    session_md5:
      description: MD5 of the session to replay (matches sensor.archived_session_count's attributes)
      required: true
      example: "abcd1234..."
```

The handler:
1. Looks up the session by md5 in the SessionArchive
2. Loads its track segments
3. Renders the camera using the archived path instead of the live one
4. The user sees the replay in their dashboard's camera card

- [ ] **Step 1-3**: implementation, tests, commit.

---

## Phase F5.10 — Finalize-session service + button

### Task F5.10.1: Wire FINALIZE_SESSION

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — add a real implementation for the FINALIZE_SESSION action (was local_only stub in F3.5.1)
- Create: `custom_components/dreame_a2_mower/button.py` — a single button entity for the manual finalize escape hatch

The action calls into the live_map's finalize path: read whatever live_map has → archive as "(incomplete)" → clear in_progress.json → reset live_map.

- [ ] **Step 1-3**: implementation, button entity, services.py update, tests, commit.

---

## Phase F5.11 — Session sensors + active binary_sensor improvement

### Task F5.11.1: Update existing entities with real session data

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py`

`binary_sensor.mowing_session_active` was a starter in F2.5.1 (read from `task_state_code in {1, 2}`). Update to read from `MowerState.session_active` which is now the authoritative source.

Add new sensors:
- `sensor.latest_session_area_m2`
- `sensor.latest_session_duration_min`
- `sensor.latest_session_unix_ts`
- `sensor.archived_session_count`
- `sensor.session_track_point_count` (current trail length, helpful for diagnostics)

- [ ] **Step 1-3**: extension, tests, commit.

---

## Phase F5.12 — Wire-in + final sweep + tag

### Task F5.12.1: Update PLATFORMS + final sweep + tag v0.5.0a0

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py` — add `button` to PLATFORMS

After F5, PLATFORMS = lawn_mower, sensor, binary_sensor, device_tracker, camera, select, number, switch, time, button (10 entries).

- [ ] **Step 1**: Edit const.py.
- [ ] **Step 2**: Final pytest sweep.
- [ ] **Step 3**: Smoke-compile every Python file.
- [ ] **Step 4**: Commit + tag v0.5.0a0.

---

## Self-review checklist

- [ ] All MowerState session-lifecycle fields default to None.
- [ ] data-policy.md is up to date.
- [ ] live_map/state.py state machine has tests for begin/append/leg-merge/end.
- [ ] live_map/finalize.decide() covers every FinalizeAction with tests.
- [ ] archive/session.py lifted from legacy with HA-import leaks cleaned.
- [ ] Coordinator's `_on_state_update` runs after every property push.
- [ ] In-progress restore fires on HA boot.
- [ ] Trail layer composites on top of F2 base map; falls back gracefully when no trail.
- [ ] replay_session service works against an archived md5.
- [ ] Manual finalize button + service work as escape hatch.
- [ ] No `homeassistant.*` imports in `protocol/` or `mower/`.
- [ ] PLATFORMS has 10 entries (button added).
- [ ] pytest sweep is green.
- [ ] v0.5.0a0 tag created.

## What this plan does NOT do

Out-of-scope for F5:
- F6: observability layer (novel-token registry, schema validators, diagnostic sensor, download_diagnostics)
- F7: LiDAR popout + dashboard polish + cutover
- LiDAR archive (separate from session archive — F7 territory)
- Animated trail playback in replay (just renders the static path; the user sees the full session at once, not point-by-point — could be a F7 enhancement)
