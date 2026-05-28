# Session Replay Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the leg-based session-replay storage and rendering with a per-point time-coded event stream so animated replays reflect the true chronology, classification (mowing vs traversal), and pauses of a mow.

**Architecture:** Every s1p4 push is captured as a `TrackPoint(t, x_m, y_m, area_m2, heading_deg, task_state, role)` in `LiveMapState.track`. Role is classified at append time (`area_delta > 0 → mowing`) and refined at finalize (cloud-coverage rescue + smoothing). The cloud session-summary track is stored verbatim as `cloud_track`. The dashboard card replays the stream in real wall-clock order, scaled by a fixed compression factor with a user speed slider. Legs become a render-time derivation; `set_mowing` and all `leg_*` arrays are deleted. Clean break on archive format — old archives are rebuilt via `tools/rebuild_session.py`.

**Tech Stack:** Python 3.13 (Home Assistant custom integration), pytest (vanilla stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`), vanilla JS ES6 custom Lovelace card, PIL for static PNG render.

**Spec:** `docs/superpowers/specs/2026-05-27-session-replay-rewrite-design.md`

**Test command (use everywhere):**
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && \
  /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest
```

---

## File Structure

**Created:**
- `custom_components/dreame_a2_mower/live_map/classify.py` — finalize-stage classifier (cloud rescue + smoothing). Pure, layer-2, no HA imports.
- `tools/_rebuild_session_lib/track_replay.py` — per-point `track` reconstruction from probe logs (replaces `legs_replay.py`'s role).
- `tests/live_map/test_classify.py`
- `tests/live_map/test_track_point.py`
- `tests/coordinator/test_track_derive_legs.py`
- `tests/tools/test_track_replay.py`

**Modified:**
- `custom_components/dreame_a2_mower/live_map/state.py` — `TrackPoint` + `track`-based `LiveMapState`.
- `custom_components/dreame_a2_mower/session_card.py` — `derive_render_legs`, single-path `_summary_trail_legs`, `_compute_distance_m(track)`.
- `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` — `update_task_state`, `append_point(area, heading)`, lifecycle signal.
- `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` — `_inject_live_map_into_raw_dict` writes `track`/`cloud_track`; classifier hook.
- `custom_components/dreame_a2_mower/coordinator/_session.py` — render path derives legs from `track`; `_wait_for_dock_return` timeout.
- `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` — time-coded engine, speed slider, pause overlay.
- `tools/rebuild_session.py` — emit new shape, run classifier.
- `custom_components/dreame_a2_mower/inventory.yaml`, `entity-inventory.yaml` — fact records.

**Deleted (content, not files):**
- `LiveMapState.set_mowing/begin_leg/mowing_legs/traversal_legs/leg_*` (state.py).
- `protocol/trail_diff.py:compute_legs_timeline_from_diff` (grid helpers retained).

---

## Phase A — Data model + capture

### Task 1: `TrackPoint` dataclass + track-based session lifecycle

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py`
- Test: `tests/live_map/test_track_point.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/live_map/test_track_point.py
"""Tests for TrackPoint + track-based LiveMapState lifecycle."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import (
    LiveMapState,
    TrackPoint,
)


def test_trackpoint_fields():
    p = TrackPoint(
        t=1000.5, x_m=1.0, y_m=2.0, area_m2=3.0,
        heading_deg=90.0, task_state=0, role="mowing",
    )
    assert p.t == 1000.5
    assert p.x_m == 1.0
    assert p.y_m == 2.0
    assert p.area_m2 == 3.0
    assert p.heading_deg == 90.0
    assert p.task_state == 0
    assert p.role == "mowing"


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.track == []


def test_begin_session_clears_track():
    s = LiveMapState()
    s.track = [TrackPoint(1.0, 1.0, 2.0, 0.0, None, -1, "traversal")]
    s.begin_session(started_unix=1000)
    assert s.is_active()
    assert s.track == []
    assert s.started_unix == 1000


def test_end_session_clears_track():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.track = [TrackPoint(1.0, 1.0, 2.0, 0.0, None, -1, "traversal")]
    s.end_session()
    assert not s.is_active()
    assert s.track == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py -v`
Expected: FAIL — `ImportError: cannot import name 'TrackPoint'`

- [ ] **Step 3: Add `TrackPoint` and rework the lifecycle fields**

In `state.py`, replace the `Leg`/`leg_*` field block and `begin_session`/`end_session` bodies. First add the dataclass near the top (after the existing `TelemetrySample` alias, before `@dataclass class LiveMapState`):

```python
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
    role: str
```

Then, inside `LiveMapState`, delete these fields entirely:
`legs`, `leg_is_mowing`, `leg_start_ts`, `leg_end_ts`, `_current_is_mowing`
and add:

```python
    track: list[TrackPoint] = field(default_factory=list)
    """Time-ordered per-point capture; the single source of truth for replay."""

    session_ending: bool = False
    """Set True when the cloud signals end-of-session. Capture continues
    until the mower is observed docked (see coordinator lifecycle)."""

    _last_task_state: int = -1
    _last_area_m2: float = 0.0
```

Rewrite `begin_session` and `end_session`:

```python
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
```

Leave `is_active`, `append_wifi_sample`, `append_telemetry_sample` unchanged.
(`append_point`, `total_points`, `total_distance_m`, `dump_to_payload`,
`hydrate_from_payload`, `set_mowing`, `begin_leg`, the `mowing_legs`/`traversal_legs`
properties will be addressed in Tasks 2-4 — they will fail to import until then,
which is expected and handled within this phase.)

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py -v`
Expected: PASS (4 tests). The wider suite is still red until Phase A completes.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/live_map/test_track_point.py
git commit -m "feat(live_map): add TrackPoint + track-based session lifecycle"
```

---

### Task 2: `update_task_state` + `append_point` rewrite with inline classification

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py`
- Test: `tests/live_map/test_track_point.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/live_map/test_track_point.py`:

```python
def _begun():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    return s


def test_append_point_records_first_point():
    s = _begun()
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=90.0)
    assert len(s.track) == 1
    p = s.track[0]
    assert (p.x_m, p.y_m, p.t) == (1.0, 2.0, 1010.0)
    assert s.last_telemetry_unix == 1010.0


def test_first_point_with_area_is_mowing():
    # All-area mow that cuts immediately: first point already has area>0.
    s = _begun()
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.5, heading_deg=0.0)
    assert s.track[0].role == "mowing"


def test_first_point_without_area_is_traversal():
    # Spot mow: drives out before cutting; first points have area==0.
    s = _begun()
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=0.0)
    assert s.track[0].role == "traversal"


def test_area_growth_is_mowing_no_growth_is_traversal():
    s = _begun()
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=0.0)
    s.append_point(t=1011.0, x_m=2.0, y_m=2.0, area_m2=0.2, heading_deg=0.0)  # +0.2
    s.append_point(t=1012.0, x_m=3.0, y_m=2.0, area_m2=0.2, heading_deg=0.0)  # +0.0
    assert s.track[1].role == "mowing"
    assert s.track[2].role == "traversal"


def test_append_point_dedupes_close_in_space_and_time():
    s = _begun()
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=0.0)
    s.append_point(t=1010.3, x_m=1.05, y_m=2.05, area_m2=0.0, heading_deg=0.0)
    assert len(s.track) == 1
    # dedup still advances the time tracker
    assert s.last_telemetry_unix == 1010.3


def test_update_task_state_tags_following_point():
    s = _begun()
    s.update_task_state(t=1009.0, code=0)
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.5, heading_deg=0.0)
    assert s.track[0].task_state == 0
    # update_task_state also records a state_sample
    assert s.state_samples == [(1009, 0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py -v`
Expected: FAIL — `append_point()` got an unexpected keyword / `update_task_state` missing.

- [ ] **Step 3: Implement `update_task_state` and rewrite `append_point`**

In `state.py`, delete `set_mowing` and `begin_leg` entirely and replace the old
`append_point` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/live_map/test_track_point.py
git commit -m "feat(live_map): track-based append_point + update_task_state with inline classify"
```

---

### Task 3: `total_distance_m`, `total_points`, dump/hydrate over `track`

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py`
- Test: `tests/live_map/test_track_point.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/live_map/test_track_point.py`:

```python
def test_total_points_and_distance_over_track():
    s = _begun()
    s.append_point(t=1010.0, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    s.append_point(t=1011.0, x_m=3.0, y_m=0.0, area_m2=0.5, heading_deg=0.0)
    s.append_point(t=1012.0, x_m=3.0, y_m=4.0, area_m2=1.0, heading_deg=0.0)
    assert s.total_points() == 3
    assert s.total_distance_m() == 7.0  # 3 + 4


def test_distance_excludes_pen_up_time_gap():
    s = _begun()
    s.append_point(t=1010.0, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    # 60 s later, 10 m away — a dock-return/charge gap, must NOT count.
    s.append_point(t=1070.0, x_m=10.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    assert s.total_distance_m() == 0.0


def test_dump_and_hydrate_round_trip():
    s = _begun()
    s.update_task_state(t=1009.0, code=0)
    s.append_point(t=1010.0, x_m=1.0, y_m=2.0, area_m2=0.5, heading_deg=90.0)
    s.append_point(t=1011.0, x_m=2.0, y_m=2.0, area_m2=0.5, heading_deg=80.0)
    payload = s.dump_to_payload()
    s2 = LiveMapState()
    s2.hydrate_from_payload(payload)
    assert s2.started_unix == 1000
    assert len(s2.track) == 2
    assert s2.track[0].role == "mowing"
    assert s2.track[1].role == "traversal"
    assert s2.track[0].heading_deg == 90.0
    assert s2.state_samples == [(1009, 0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py::test_total_points_and_distance_over_track tests/live_map/test_track_point.py::test_dump_and_hydrate_round_trip -v`
Expected: FAIL — `total_distance_m`/`dump_to_payload` still reference `self.legs`.

- [ ] **Step 3: Rewrite the four methods**

Replace `total_points`, `total_distance_m`, `dump_to_payload`, `hydrate_from_payload`:

```python
    _PEN_UP_GAP_S: float = 30.0

    def total_points(self) -> int:
        return len(self.track)

    def total_distance_m(self) -> float:
        """Sum of euclidean distances between consecutive track points,
        excluding pen-up boundaries (time gap > _PEN_UP_GAP_S)."""
        from math import hypot

        total = 0.0
        for i in range(1, len(self.track)):
            a = self.track[i - 1]
            b = self.track[i]
            if (b.t - a.t) > self._PEN_UP_GAP_S:
                continue
            total += hypot(b.x_m - a.x_m, b.y_m - a.y_m)
        return total

    def dump_to_payload(self) -> dict:
        """Snapshot in-memory state to the in_progress.json payload shape."""
        return {
            "session_start_ts": self.started_unix,
            "session_ending": self.session_ending,
            "track": [
                [p.t, p.x_m, p.y_m, p.area_m2, p.heading_deg, p.task_state, p.role]
                for p in self.track
            ],
            "wifi_samples": [list(s) for s in self.wifi_samples],
            "battery_samples": [list(s) for s in self.battery_samples],
            "charging_status_samples": [list(s) for s in self.charging_status_samples],
            "state_samples": [list(s) for s in self.state_samples],
            "error_samples": [list(s) for s in self.error_samples],
            "charge_at_start": self.charge_at_start,
            "settings_snapshot": self.settings_snapshot,
        }

    def hydrate_from_payload(self, payload: dict) -> None:
        """Replace in-memory state from a merged payload (after restore-merge)."""
        self.started_unix = payload.get("session_start_ts")
        self.session_ending = bool(payload.get("session_ending", False))
        track: list[TrackPoint] = []
        for row in payload.get("track") or []:
            try:
                t, x, y, area, heading, ts_code, role = (
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                )
            except (IndexError, TypeError):
                continue
            track.append(TrackPoint(
                t=float(t), x_m=float(x), y_m=float(y), area_m2=float(area),
                heading_deg=(None if heading is None else float(heading)),
                task_state=int(ts_code), role=str(role),
            ))
        self.track = track
        self._last_area_m2 = track[-1].area_m2 if track else 0.0
        self._last_task_state = track[-1].task_state if track else -1
        self.last_telemetry_unix = track[-1].t if track else None
        self.wifi_samples = [
            (float(s[0]), float(s[1]), int(s[2]), int(s[3]))
            for s in (payload.get("wifi_samples") or [])
        ]
        self.battery_samples = [
            (int(s[0]), int(s[1])) for s in (payload.get("battery_samples") or [])
        ]
        self.charging_status_samples = [
            (int(s[0]), int(s[1])) for s in (payload.get("charging_status_samples") or [])
        ]
        self.state_samples = [
            (int(s[0]), int(s[1])) for s in (payload.get("state_samples") or [])
        ]
        self.error_samples = [
            (int(s[0]), int(s[1])) for s in (payload.get("error_samples") or [])
        ]
        self.charge_at_start = payload.get("charge_at_start")
        self.settings_snapshot = payload.get("settings_snapshot")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_track_point.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/live_map/test_track_point.py
git commit -m "feat(live_map): distance/dump/hydrate over track stream"
```

---

### Task 4: Remove dead leg API + fix the old state tests

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py`
- Modify/Delete: `tests/live_map/test_state.py`, `tests/live_map/test_state_leg_timestamps.py`

- [ ] **Step 1: Confirm what still references the dead API**

Run:
```bash
grep -rn "\.set_mowing\|\.begin_leg\|leg_is_mowing\|leg_start_ts\|leg_end_ts\|\.mowing_legs\|\.traversal_legs\|\.legs\b" custom_components tests tools | grep -v __pycache__
```
Expected: hits in `state.py` (the property defs — already removed in Task 1-3 if any remain), `tests/live_map/test_state.py`, `tests/live_map/test_state_leg_timestamps.py`, plus coordinator/session_card/tools sites handled in later tasks. Note them; this task only fixes `state.py` + the two `live_map` state tests.

- [ ] **Step 2: Delete the `mowing_legs` / `traversal_legs` properties from `state.py`**

Remove the `@property def mowing_legs` and `@property def traversal_legs` blocks (state.py lines ~217-238 in the original). Confirm no `set_mowing`/`begin_leg`/`leg_*` remain:
```bash
grep -n "set_mowing\|begin_leg\|leg_is_mowing\|leg_start_ts\|leg_end_ts\|mowing_legs\|traversal_legs" custom_components/dreame_a2_mower/live_map/state.py
```
Expected: no output.

- [ ] **Step 3: Replace the obsolete tests**

`tests/live_map/test_state_leg_timestamps.py` tests leg timestamp behavior that no longer exists — delete it:
```bash
git rm tests/live_map/test_state_leg_timestamps.py
```

Rewrite `tests/live_map/test_state.py` to keep only the still-valid cases (sample buffers, wifi, telemetry dedup) and drop every `legs`/`set_mowing`/`begin_leg` test. Replace its full content with:

```python
"""Tests for live_map/state.py — sample buffers + lifecycle."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.total_points() == 0


def test_append_telemetry_sample_debounces_identical():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_telemetry_sample(s.battery_samples, 80, 1010) is True
    assert s.append_telemetry_sample(s.battery_samples, 80, 1020) is False
    assert s.append_telemetry_sample(s.battery_samples, 79, 1030) is True
    assert s.battery_samples == [(1010, 80), (1030, 79)]


def test_append_wifi_sample_debounces_stationary():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_wifi_sample(1.0, 2.0, -50, 1010) is True
    assert s.append_wifi_sample(1.05, 2.05, -50, 1020) is False  # within 25cm same RSSI
    assert s.append_wifi_sample(1.0, 2.0, -55, 1030) is True     # RSSI changed
    assert len(s.wifi_samples) == 2
```

- [ ] **Step 4: Run the live_map test directory**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/ -v`
Expected: PASS (test_track_point.py, test_state.py, test_finalize.py, test_trail.py). `test_state_leg_timestamps.py` is gone.

- [ ] **Step 5: Commit**

```bash
git add -A custom_components/dreame_a2_mower/live_map/state.py tests/live_map/
git commit -m "refactor(live_map): drop leg API; track stream is the only model"
```

---

## Phase B — Classifier

### Task 5: Finalize-stage classifier (cloud rescue + smoothing)

**Files:**
- Create: `custom_components/dreame_a2_mower/live_map/classify.py`
- Test: `tests/live_map/test_classify.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/live_map/test_classify.py
"""Tests for the finalize-stage track classifier."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.classify import classify_track


def _pt(t, x, y, role):
    # Helper: dict-shaped point (the in-archive form classify_track operates on).
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_cloud_rescue_upgrades_traversal_on_path():
    # A point sitting on a cloud mowing segment but flagged traversal
    # (re-mow over already-cut grass) should upgrade to mowing.
    track = [_pt(0, 0.0, 0.0, "traversal"), _pt(1, 1.0, 0.0, "traversal")]
    cloud = [[(0.0, 0.0), (1.0, 0.0)]]  # a mowing polyline along y=0
    out = classify_track(track, cloud_track=cloud, tol_m=0.6)
    assert [p["role"] for p in out] == ["mowing", "mowing"]


def test_cloud_rescue_leaves_far_traversal_grey():
    track = [_pt(0, 0.0, 5.0, "traversal"), _pt(1, 1.0, 5.0, "traversal")]
    cloud = [[(0.0, 0.0), (1.0, 0.0)]]  # 5 m away
    out = classify_track(track, cloud_track=cloud, tol_m=0.6)
    assert [p["role"] for p in out] == ["traversal", "traversal"]


def test_smoothing_collapses_single_point_stutter():
    track = [
        _pt(0, 0.0, 0.0, "mowing"),
        _pt(1, 1.0, 0.0, "traversal"),  # lone stutter between two mowing
        _pt(2, 2.0, 0.0, "mowing"),
    ]
    out = classify_track(track, cloud_track=None)
    assert [p["role"] for p in out] == ["mowing", "mowing", "mowing"]


def test_no_cloud_keeps_area_delta_roles_then_smooths():
    track = [_pt(0, 0.0, 0.0, "traversal"), _pt(1, 1.0, 0.0, "traversal")]
    out = classify_track(track, cloud_track=None)
    assert [p["role"] for p in out] == ["traversal", "traversal"]


def test_empty_track_returns_empty():
    assert classify_track([], cloud_track=[[(0.0, 0.0)]]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the classifier**

```python
# custom_components/dreame_a2_mower/live_map/classify.py
"""Finalize-stage track classifier.

Stage 1 (area-delta) runs inline in LiveMapState.append_point. This module
is stage 2: cloud-coverage rescue + smoothing, applied once at finalize when
the full track and the cloud session-summary path are both available.

Pure (layer 2 — no HA imports) so it is unit-testable and reusable by the
probe-log rebuild tool.
"""
from __future__ import annotations

from typing import Any, Sequence

# Reuse the well-tested spatial grid from the existing trail-diff module.
from ..protocol.trail_diff import _build_cloud_grid, _make_coverage_check


def classify_track(
    track: list[dict[str, Any]],
    cloud_track: Sequence[Sequence[Sequence[float]]] | None,
    *,
    tol_m: float = 0.6,
    smooth_passes: int = 3,
) -> list[dict[str, Any]]:
    """Refine per-point ``role`` in place-equivalent (returns the same list).

    1. Cloud rescue: any point flagged "traversal" that lies within tol_m of
       a cloud mowing segment is upgraded to "mowing".
    2. Smoothing: any point whose role differs from BOTH neighbours flips to
       the neighbour role. Run smooth_passes times.

    track points are plain dicts with at least keys x_m, y_m, role.
    """
    if not track:
        return track

    if cloud_track:
        cell = float(tol_m)
        grid = _build_cloud_grid(cloud_track, cell)
        if grid:
            is_covered = _make_coverage_check(grid, cell, cell * cell)
            for p in track:
                if p["role"] == "traversal" and is_covered(p["x_m"], p["y_m"]):
                    p["role"] = "mowing"

    for _ in range(max(0, smooth_passes)):
        changed = False
        for i in range(1, len(track) - 1):
            prev_r = track[i - 1]["role"]
            next_r = track[i + 1]["role"]
            if prev_r == next_r and track[i]["role"] != prev_r:
                track[i]["role"] = prev_r
                changed = True
        if not changed:
            break
    return track
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/classify.py tests/live_map/test_classify.py
git commit -m "feat(live_map): finalize-stage classifier (cloud rescue + smoothing)"
```

---

## Phase C — Render-time derivation (session_card)

### Task 6: `derive_render_legs(track)`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Test: `tests/coordinator/test_track_derive_legs.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/coordinator/test_track_derive_legs.py
"""Tests for session_card.derive_render_legs."""
from __future__ import annotations

from custom_components.dreame_a2_mower.session_card import derive_render_legs


def _pt(t, x, y, role):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_role_flip_breaks_legs():
    track = [_pt(0, 0, 0, "traversal"), _pt(1, 1, 0, "traversal"),
             _pt(2, 2, 0, "mowing"), _pt(3, 3, 0, "mowing")]
    legs = derive_render_legs(track)
    assert len(legs) == 2
    assert legs[0]["role"] == "traversal"
    assert legs[0]["start_ts"] == 0 and legs[0]["end_ts"] == 1
    assert legs[1]["role"] == "mowing"
    # Boundary point is shared so polylines visually touch.
    assert legs[0]["pts"][-1] == legs[1]["pts"][0]


def test_time_gap_breaks_legs():
    track = [_pt(0, 0, 0, "mowing"), _pt(1, 1, 0, "mowing"),
             _pt(100, 2, 0, "mowing")]  # 99 s gap → pen-up
    legs = derive_render_legs(track, pen_up_gap_s=30.0)
    assert len(legs) == 2
    # Pen-up legs do NOT share a boundary point (no connecting stroke).
    assert legs[0]["pts"][-1] != legs[1]["pts"][0]


def test_contiguous_same_role_is_one_leg():
    track = [_pt(0, 0, 0, "mowing"), _pt(1, 1, 0, "mowing"), _pt(2, 2, 0, "mowing")]
    legs = derive_render_legs(track)
    assert len(legs) == 1
    assert len(legs[0]["pts"]) == 3


def test_empty_track():
    assert derive_render_legs([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_track_derive_legs.py -v`
Expected: FAIL — `derive_render_legs` not defined.

- [ ] **Step 3: Add `derive_render_legs` to `session_card.py`**

Add near the top of `session_card.py` (after the label tables, before `_normalise_settings_snapshot`):

```python
PEN_UP_GAP_S_DEFAULT: float = 30.0


def derive_render_legs(
    track: list[dict],
    *,
    pen_up_gap_s: float = PEN_UP_GAP_S_DEFAULT,
) -> list[dict]:
    """Split a per-point track into render legs.

    A new leg starts on a role flip OR a pen-up boundary (time gap >
    pen_up_gap_s). On a role flip the boundary point is shared between the
    closing and opening legs so the polylines visually touch. On a pen-up
    boundary the legs do NOT share a point (the connecting stroke is
    suppressed at render time).

    Returns list of {role, start_ts, end_ts, pts:[(x,y),...]}.
    """
    if not track:
        return []
    legs: list[dict] = []
    cur: dict | None = None
    for i, p in enumerate(track):
        role = p["role"]
        xy = (p["x_m"], p["y_m"])
        pen_up = (
            i > 0 and (p["t"] - track[i - 1]["t"]) > pen_up_gap_s
        )
        if cur is None:
            cur = {"role": role, "start_ts": p["t"], "end_ts": p["t"], "pts": [xy]}
            continue
        if pen_up:
            legs.append(cur)
            cur = {"role": role, "start_ts": p["t"], "end_ts": p["t"], "pts": [xy]}
        elif role != cur["role"]:
            # Share the boundary point with the previous leg, then open new.
            legs.append(cur)
            prev_xy = track[i - 1]["x_m"], track[i - 1]["y_m"]
            cur = {"role": role, "start_ts": track[i - 1]["t"],
                   "end_ts": p["t"], "pts": [prev_xy, xy]}
        else:
            cur["pts"].append(xy)
            cur["end_ts"] = p["t"]
    if cur is not None:
        legs.append(cur)
    # Drop degenerate single-point legs (a stroke needs >= 2 points).
    return [leg for leg in legs if len(leg["pts"]) >= 2]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_track_derive_legs.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/coordinator/test_track_derive_legs.py
git commit -m "feat(session_card): derive_render_legs from per-point track"
```

---

### Task 7: `_compute_distance_m(track)` + role split

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Test: `tests/coordinator/test_track_derive_legs.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/coordinator/test_track_derive_legs.py`:

```python
from custom_components.dreame_a2_mower.session_card import compute_track_distances


def test_compute_distances_total_and_split():
    track = [
        {"t": 0, "x_m": 0.0, "y_m": 0.0, "area_m2": 0.0, "heading_deg": None,
         "task_state": 0, "role": "traversal"},
        {"t": 1, "x_m": 3.0, "y_m": 0.0, "area_m2": 0.0, "heading_deg": None,
         "task_state": 0, "role": "traversal"},   # 3 m traversal
        {"t": 2, "x_m": 3.0, "y_m": 4.0, "area_m2": 1.0, "heading_deg": None,
         "task_state": 0, "role": "mowing"},       # 4 m mowing
    ]
    d = compute_track_distances(track)
    assert d["distance_m"] == 7.0
    assert d["distance_traversal_m"] == 3.0
    assert d["distance_mowing_m"] == 4.0


def test_compute_distances_excludes_pen_up():
    track = [
        {"t": 0, "x_m": 0.0, "y_m": 0.0, "area_m2": 0.0, "heading_deg": None,
         "task_state": 0, "role": "mowing"},
        {"t": 100, "x_m": 10.0, "y_m": 0.0, "area_m2": 0.0, "heading_deg": None,
         "task_state": 0, "role": "mowing"},  # 100 s gap → pen-up, excluded
    ]
    d = compute_track_distances(track)
    assert d["distance_m"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_track_derive_legs.py -k compute_distances -v`
Expected: FAIL — `compute_track_distances` not defined.

- [ ] **Step 3: Add `compute_track_distances`, retire the legs-based `_compute_distance_m`**

In `session_card.py`, add:

```python
def compute_track_distances(
    track: list[dict],
    *,
    pen_up_gap_s: float = PEN_UP_GAP_S_DEFAULT,
) -> dict[str, float]:
    """Total/mowing/traversal distance in metres over the track.

    A segment's role is the role of its END point. Segments across a pen-up
    boundary (time gap > pen_up_gap_s) are excluded from all three totals.
    """
    from math import hypot

    total = mow = trav = 0.0
    for i in range(1, len(track)):
        a, b = track[i - 1], track[i]
        if (b["t"] - a["t"]) > pen_up_gap_s:
            continue
        d = hypot(b["x_m"] - a["x_m"], b["y_m"] - a["y_m"])
        total += d
        if b["role"] == "mowing":
            mow += d
        else:
            trav += d
    return {"distance_m": total, "distance_mowing_m": mow, "distance_traversal_m": trav}
```

Delete the old `_compute_distance_m(raw_dict, summary)` function (it referenced
`_local_legs` / `summary.track_segments`). Its only caller is
`_summary_coverage_efficiency`, rewired in Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_track_derive_legs.py -k compute_distances -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/coordinator/test_track_derive_legs.py
git commit -m "feat(session_card): track-based distance with mowing/traversal split"
```

---

### Task 8: Single-path `_summary_trail_legs` + coverage rewire

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Test: `tests/test_session_card_timeline.py` (rewrite)

- [ ] **Step 1: Rewrite the timeline test**

Replace the full content of `tests/test_session_card_timeline.py`:

```python
"""Tests for session_card trail/legs assembly from the per-point track."""
from __future__ import annotations

from custom_components.dreame_a2_mower.session_card import _summary_trail_legs


def _pt(t, x, y, role, area=0.0):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": area,
            "heading_deg": None, "task_state": 0, "role": role}


def test_legs_timeline_built_from_track():
    raw = {"track": [
        _pt(0, 0, 0, "traversal"), _pt(1, 1, 0, "traversal"),
        _pt(2, 2, 0, "mowing", area=0.5), _pt(3, 3, 0, "mowing", area=1.0),
    ]}
    out = _summary_trail_legs(raw, summary=None, map_projection={"width_px": 10})
    tl = out["legs_timeline"]
    assert [leg["role"] for leg in tl] == ["traversal", "mowing"]
    assert out["track_first_ts"] == 0
    assert out["track_last_ts"] == 3
    assert out["map_projection"] == {"width_px": 10}


def test_empty_track_yields_empty_timeline():
    out = _summary_trail_legs({"track": []}, summary=None, map_projection=None)
    assert out["legs_timeline"] == []
    assert out["track_first_ts"] is None
    assert out["track_last_ts"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_session_card_timeline.py -v`
Expected: FAIL — current `_summary_trail_legs` reads `_local_legs`/`summary.track_segments`.

- [ ] **Step 3: Rewrite `_summary_trail_legs` to a single track path**

Replace the entire `_summary_trail_legs` function body with:

```python
def _summary_trail_legs(raw_dict, summary, map_projection):
    """Trail/legs section, derived purely from the per-point track."""
    track = raw_dict.get("track") or []
    legs = derive_render_legs(track)
    legs_timeline = [
        {"role": leg["role"], "start_ts": int(leg["start_ts"]),
         "end_ts": int(leg["end_ts"]),
         "pts": [[float(x), float(y)] for (x, y) in leg["pts"]]}
        for leg in legs
    ]
    out: dict[str, Any] = {
        "legs_timeline": legs_timeline,
        "track_first_ts": int(track[0]["t"]) if track else None,
        "track_last_ts": int(track[-1]["t"]) if track else None,
        "map_projection": map_projection,
    }
    _ts_for_url = (summary.start_ts if summary is not None else None) or (
        track[0]["t"] if track else 0
    )
    out["base_map_image_url"] = f"/api/dreame_a2_mower/work_log.png?ts={int(_ts_for_url)}"
    out["base_map_image_url_no_trail"] = (
        f"/api/dreame_a2_mower/work_log.png?ts={int(_ts_for_url)}&trail=false"
    )
    return out
```

Then in `_summary_coverage_efficiency`, replace the distance line:

```python
    # old: out["distance_m"] = _compute_distance_m(raw_dict, summary)
    _dist = compute_track_distances(raw_dict.get("track") or [])
    out["distance_m"] = _dist["distance_m"]
    out["distance_mowing_m"] = _dist["distance_mowing_m"]
    out["distance_traversal_m"] = _dist["distance_traversal_m"]
```

- [ ] **Step 4: Run the session_card tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_session_card_timeline.py tests/coordinator/test_track_derive_legs.py -v`
Expected: PASS. Also run any `test_session_card*` to catch fallout:
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -k session_card -v`
Expected: PASS (fix any test still asserting `legs`/`mowing_legs`/`local_leg_count` by removing those assertions — those attributes are gone by design).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/test_session_card_timeline.py
git commit -m "refactor(session_card): single track-derived legs_timeline path"
```

---

## Phase D — Coordinator wiring

### Task 9: MQTT handler — task-state + area/heading append

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py`

- [ ] **Step 1: Rewire the s1p4 append call (lines ~352-392)**

Replace the `set_mowing` block and the `append_point` call. The new block:

```python
        if (
            self.live_map.is_active()
            and new_state.position_x_m is not None
            and new_state.position_y_m is not None
            and (new_state != self.data)  # something changed
        ):
            before_pts = self.live_map.total_points()
            self.live_map.append_point(
                t=float(now_unix),
                x_m=new_state.position_x_m,
                y_m=new_state.position_y_m,
                area_m2=(new_state.area_mowed_m2 or 0.0),
                heading_deg=new_state.position_heading_deg,
            )
            if self.live_map.total_points() > before_pts:
                self._live_map_dirty = True
                self._live_trail_dirty = True
                # ... (KEEP the existing throttled _rerender_live_trail block below
                #      verbatim — only the append_point call + set_mowing removal change)
```

Delete the `from ..mower.state_snapshot import CurrentActivity` import inside this
function and the `sm = getattr(self, "state_machine", None)` / `cur_activity` /
`is_mowing` / `LOGGER.info("[live_map] set_mowing...")` / `self.live_map.set_mowing(...)`
lines. Keep the throttled `_rerender_live_trail` scheduling exactly as-is.

- [ ] **Step 2: Route s2p1 capture through `update_task_state`**

In `_capture_telemetry_sample` (lines ~599-627), change the `(2, 1)` branch so it
calls `update_task_state` instead of the generic buffer append:

```python
        lm = self.live_map
        if key == (3, 1):
            buf = lm.battery_samples
        elif key == (3, 2):
            buf = lm.charging_status_samples
        elif key == (2, 1):
            # state_samples + latest-task-state tagging for the track.
            lm.update_task_state(float(now_unix), v_int)
            self._live_map_dirty = True
            return
        elif key == (2, 2):
            buf = lm.error_samples
        else:
            return
        if lm.append_telemetry_sample(buf, v_int, now_unix):
            self._live_map_dirty = True
```

- [ ] **Step 3: Run the coordinator mqtt-handler tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/ -k "mqtt or handler or live_map or trail" -v`
Expected: PASS, or surface tests asserting `set_mowing`/`leg_is_mowing` — update those to assert `track` contents + roles instead (e.g., after feeding an s1p4 with growing area, assert `live_map.track[-1].role == "mowing"`).

- [ ] **Step 4: Run the full suite to catch broad fallout**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: failures only in the coordinator finalize/session + tools areas (handled in Tasks 10-13, 18-19). Note them; do not fix unrelated areas here.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/coordinator/
git commit -m "feat(coordinator): capture track points with area/heading; task-state tagging"
```

---

### Task 10: `_inject_live_map_into_raw_dict` writes `track`, drops legacy keys

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
- Test: `tests/coordinator/test_inject_live_map_meta.py` (rewrite)

- [ ] **Step 1: Rewrite the inject test**

Replace `tests/coordinator/test_inject_live_map_meta.py` content:

```python
"""Tests for _inject_live_map_into_raw_dict — writes the per-point track."""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._lidar_oss import _LidarOssMixin
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _coord_with_track():
    lm = LiveMapState()
    lm.begin_session(started_unix=1000)
    lm.update_task_state(1000.0, 0)
    lm.append_point(1001.0, 0.0, 0.0, 0.0, 0.0)        # traversal
    lm.append_point(1002.0, 1.0, 0.0, 0.5, 0.0)        # mowing
    obj = types.SimpleNamespace(live_map=lm)
    obj._inject_live_map_into_raw_dict = types.MethodType(
        _LidarOssMixin._inject_live_map_into_raw_dict, obj
    )
    return obj


def test_inject_writes_track():
    obj = _coord_with_track()
    raw: dict = {}
    obj._inject_live_map_into_raw_dict(raw)
    assert "track" in raw
    assert len(raw["track"]) == 2
    first = raw["track"][0]
    # serialized as a list row [t, x, y, area, heading, task_state, role]
    assert first[6] == "traversal"
    assert raw["track"][1][6] == "mowing"
    # legacy keys must NOT be present
    for dead in ("_local_legs", "_mowing_legs", "_traversal_legs", "_legs_meta"):
        assert dead not in raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_inject_live_map_meta.py -v`
Expected: FAIL — current inject still writes `_local_legs`.

- [ ] **Step 3: Rewrite the legs block in `_inject_live_map_into_raw_dict`**

Replace the entire `if self.live_map.legs and any(self.live_map.legs): ...`
block (lines ~94-130) with:

```python
        if self.live_map.track:
            raw_dict["track"] = [
                [p.t, p.x_m, p.y_m, p.area_m2, p.heading_deg, p.task_state, p.role]
                for p in self.live_map.track
            ]
```

Leave the wifi/battery/charging/state/error/charge_at_start/settings_snapshot
blocks below unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_inject_live_map_meta.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/coordinator/test_inject_live_map_meta.py
git commit -m "feat(coordinator): archive per-point track, drop legacy leg keys"
```

---

### Task 11: Classifier hook + `cloud_track` storage at finalize

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
- Test: `tests/coordinator/test_inject_live_map_meta.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/coordinator/test_inject_live_map_meta.py`:

```python
from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    finalize_classify_raw_dict,
)


def test_finalize_classify_stores_cloud_track_and_rescues():
    raw = {
        "track": [
            [0, 0.0, 0.0, 0.0, None, 0, "traversal"],
            [1, 1.0, 0.0, 0.0, None, 0, "traversal"],  # on cloud path → rescue
        ],
    }
    cloud_segments = [[(0.0, 0.0), (1.0, 0.0)]]
    finalize_classify_raw_dict(raw, cloud_segments)
    assert raw["cloud_track"] == [[[0.0, 0.0], [1.0, 0.0]]]
    assert [row[6] for row in raw["track"]] == ["mowing", "mowing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_inject_live_map_meta.py::test_finalize_classify_stores_cloud_track_and_rescues -v`
Expected: FAIL — `finalize_classify_raw_dict` not defined.

- [ ] **Step 3: Add `finalize_classify_raw_dict` and call it in `_do_oss_fetch`**

Add as a module-level function in `_lidar_oss.py`:

```python
def finalize_classify_raw_dict(raw_dict, cloud_segments) -> None:
    """Run stage-2 classification on raw_dict['track'] and store cloud_track.

    cloud_segments: parsed SessionSummary.track_segments (iterable of legs of
    (x,y)). Stored verbatim under 'cloud_track' for re-classification later.
    """
    from ..live_map.classify import classify_track

    cloud = [[[float(p[0]), float(p[1])] for p in seg] for seg in (cloud_segments or [])]
    raw_dict["cloud_track"] = cloud
    track_rows = raw_dict.get("track") or []
    # Operate on dict views so classify_track can mutate role, then write back.
    points = [
        {"t": r[0], "x_m": r[1], "y_m": r[2], "area_m2": r[3],
         "heading_deg": r[4], "task_state": r[5], "role": r[6]}
        for r in track_rows
    ]
    classify_track(points, cloud_track=cloud or None)
    raw_dict["track"] = [
        [p["t"], p["x_m"], p["y_m"], p["area_m2"], p["heading_deg"],
         p["task_state"], p["role"]]
        for p in points
    ]
```

In `_do_oss_fetch`, after `summary = _session_summary.parse_session_summary(raw_dict)`
succeeds (line ~499) and BEFORE the archive call (line ~510), add:

```python
        finalize_classify_raw_dict(raw_dict, summary.track_segments)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_inject_live_map_meta.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/coordinator/test_inject_live_map_meta.py
git commit -m "feat(coordinator): finalize classifier + verbatim cloud_track storage"
```

---

### Task 12: Lifecycle — capture until docked

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py`

- [ ] **Step 1: Stop the premature `task_idle` finalize signal**

In `_mqtt_handlers.py` (lines ~532-548), the dock-return wait currently completes
on `task_idle` OR `charging`. `task_idle` fires the instant the session ends —
before the mower drives home. Remove the `task_idle` early-complete so the wait
only ends on physical dock (charging) or timeout:

```python
        done_event = getattr(self, "_pending_finalize_done", None)
        if done_event is not None and not done_event.is_set():
            is_charging = False
            cs = new_state.charging_status
            if cs is not None:
                cs_val = cs.value if hasattr(cs, "value") else int(cs)
                is_charging = cs_val == 1  # ChargingStatus.CHARGING
            if is_charging:
                self._pending_finalize_done_reason = "charging"
                done_event.set()
```

- [ ] **Step 2: Extend the wait timeout to 10 min**

In `_session.py` `_dispatch_finalize_action`, change both `_wait_for_dock_return(timeout_s=300)`
calls to `timeout_s=600` (10 min, per spec watchdog). Update the two log strings
from "≤5 min" to "≤10 min".

- [ ] **Step 3: Verify live_map stays active across the wait**

Confirm (read-only) that `end_session()` is only called from the archive path
AFTER `_do_oss_fetch` / `_run_finalize_incomplete`, never during the wait:
```bash
grep -rn "\.end_session()" custom_components/dreame_a2_mower/coordinator/ | grep -v __pycache__
```
Expected: only post-archive call sites. If `end_session()` is called before the
wait anywhere, move it to after the archive write. (No code change expected here —
this is a guard check.)

- [ ] **Step 4: Run the session/finalize tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/ -k "finalize or session or dock" -v`
Expected: PASS, or update any test asserting the 300 s timeout / `task_idle`
reason to the new 600 s / charging-only behavior.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py custom_components/dreame_a2_mower/coordinator/_session.py tests/coordinator/
git commit -m "feat(coordinator): capture until docked (charging-only finalize signal, 10 min watchdog)"
```

---

### Task 13: Static render path derives legs from `track`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py`

- [ ] **Step 1: Replace the legs-assembly block in the render path**

In `_session.py`'s `render_work_log_session` (lines ~185-256, the `cloud_legs` /
`local_legs` / `_legs_from` / `_legs_meta` assembly), replace with a single
track-derived timeline:

```python
        from ..session_card import derive_render_legs

        track_rows = raw_dict.get("track") or []
        track = [
            {"t": r[0], "x_m": r[1], "y_m": r[2], "area_m2": r[3],
             "heading_deg": r[4], "task_state": r[5], "role": r[6]}
            for r in track_rows
        ]
        legs_timeline: list[dict] | None = derive_render_legs(track) or None
```

- [ ] **Step 2: Simplify the render-kwargs selection (lines ~358-380)**

Replace the `if legs_timeline / elif have_split_archive / elif local_legs and cloud_legs / else`
chain with:

```python
        render_kwargs = {"legs_timeline": legs_timeline} if legs_timeline else {}
```

Remove the now-dead `compute_legs_timeline_from_diff` import and the
`have_split_archive` / `mowing_legs_archive` / `traversal_legs_archive` /
`cloud_legs` / `local_legs` locals from this function. Keep `obstacle_polygons_m`.

- [ ] **Step 3: Fix `session_track_segments` source (line ~881)**

`_persist_in_progress` builds an MMTask payload from `self.live_map.legs`
(line ~881) — that attribute is gone. Replace with the track xy sequence:

```python
            session_track_segments=tuple(
                ((p.x_m, p.y_m) for p in self.live_map.track),
            ) if self.live_map.track else (),
```

Note: `session_track_segments` here is a single flat path (the live trail), used
by the in-progress snapshot. Confirm its consumer wants a tuple-of-legs vs a flat
path by reading the `_snapshot.py` / MMTask field; if it expects legs, wrap as
`(tuple((p.x_m, p.y_m) for p in self.live_map.track),)`. Adjust to match.

- [ ] **Step 4: Run the replay/render tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "render or replay or work_log or session" -v`
Expected: PASS, or update tests that fed `_local_legs`/`_legs_meta` to feed
`track` instead. `tests/test_render_timeline_order.py` and
`tests/integration/test_replay_cross_map.py` are the likely ones — convert their
fixtures to the `track` row shape.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py tests/
git commit -m "refactor(coordinator): static render derives legs from track"
```

---

## Phase E — Dashboard card (JS)

> JS has no unit-test harness in this repo. Each JS task ends with a manual
> verification in a live HA dashboard. Keep the diffs surgical.

### Task 14: Time-coded engine — producer attrs + `_startAnimation`/`_renderAt`

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

- [ ] **Step 1: Simplify `_render`'s leg-spec selection**

In `_render`, replace the `rawTimeline`/`mowing_legs`/`traversal_legs`/`legs`
fallback chain (lines ~157-181) with a single source:

```javascript
    const rawTimeline = a.legs_timeline || [];
    const legSpecs = rawTimeline
      .filter(rec => rec && rec.pts && rec.pts.length >= 2
                     && (rec.role === 'mowing' || rec.role === 'traversal'))
      .map(rec => ({
        pts: rec.pts, role: rec.role,
        start_ts: rec.start_ts, end_ts: rec.end_ts,
      }));
```

Keep the `this._pathRoles` / `this._legSpecs` / `paths` SVG generation below it.

- [ ] **Step 2: Replace the timing core of `_startAnimation`**

Delete `_computePauseIntervals` (whole method) and inside `_startAnimation` delete
the `TARGET_M_PER_S`/`MIN_MS`/`MAX_MS`/`distance_m` block, the `pauses`/
`pauseSeconds`/`drawBudgetMs`/`pauseBudgetMs` block, the `legGapMs` block, and the
`hasRealTimes` branch. Replace with a single time-coded timeline:

```javascript
    // --- Time-coded timeline (single source of truth) ---
    const FIRST_T = Number(a.track_first_ts);
    const LAST_T  = Number(a.track_last_ts);
    const wallDurMs = Math.max(1, (LAST_T - FIRST_T) * 1000);
    const compression = this._currentReplaySpeed();      // Task 15
    const MIN_MS = 3000, MAX_MS = 90000;
    this._totalMs = Math.min(MAX_MS, Math.max(MIN_MS, wallDurMs / compression));
    const scale = this._totalMs / wallDurMs;

    const specs = this._legSpecs || [];
    this._timeline = specs.map((leg, i) => {
      const startMs = (leg.start_ts - FIRST_T) * 1000 * scale;
      const endMs   = (leg.end_ts   - FIRST_T) * 1000 * scale;
      return { leg: i, start_ms: startMs, end_ms: Math.max(startMs + 1, endMs),
               dur: Math.max(1, (endMs - startMs)) };
    });
```

Keep the charging-window detection block and the dock-pixel block, but change the
charging window time mapping from `(tsUnix - sessionStartUnix) * 1000` to
`(tsUnix - FIRST_T) * 1000 * scale` so it lands on the same compressed axis.

Keep the path-init (`strokeDasharray`/`strokeDashoffset`), `_applyRenderStyle`,
marker visibility, and the `_playheadMs = 0; _isPlaying = true; _ensureRaf()` tail.

- [ ] **Step 3: Add the pen-up gap awareness to `_renderAt`'s icon interpolation**

In `_renderAt`, the between-leg interpolation (lines ~601-633) must NOT draw a
straight line across a pen-up gap. A pen-up gap is a between-leg gap where the
previous leg's last point and the next leg's first point differ (role-flip legs
share a boundary point; pen-up legs do not). Replace the `prevIdx>=0 && nextIdx>=0`
interpolation branch with:

```javascript
        if (prevIdx >= 0 && nextIdx >= 0) {
          const prevEnd = paths[prevIdx].getPointAtLength(lengths[prevIdx]);
          const nextStart = paths[nextIdx].getPointAtLength(0);
          const samePoint =
            Math.abs(prevEnd.x - nextStart.x) < 0.5 &&
            Math.abs(prevEnd.y - nextStart.y) < 0.5;
          if (samePoint) {
            // role-flip gap: glide along the (zero-length) join.
            iconX = prevEnd.x; iconY = prevEnd.y;
          } else {
            // pen-up gap: freeze at prev endpoint until the next leg starts.
            iconX = prevEnd.x; iconY = prevEnd.y;
          }
        } else if (prevIdx >= 0) {
```

(Both branches freeze at `prevEnd` — the explicit `samePoint` split documents
intent and leaves room for a future glide animation. The key change is: no
straight-line interpolation across pen-up gaps.)

- [ ] **Step 4: Manual verification**

Deploy the card JS to HA (per `reference_ha_dashboard_deploy` — SCP the www file
or reload the integration so the static path re-serves it; hard-refresh the
browser). Pick the `2026-05-27 07:58` session. Verify the lawn fills in
chronological order (no "half the lawn on frame 2"). Check the browser console for
errors.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "feat(card): time-coded replay engine driven by track_first/last_ts"
```

---

### Task 15: Replay-speed slider + compression mapping

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

- [ ] **Step 1: Add the speed slider to the controls markup**

In `_render`, inside the `.controls` div (after the scrub input), add:

```html
          <label style="display:flex;align-items:center;gap:4px;font-size:12px;">
            speed
            <input id="speed" type="range" min="0" max="1000" value="500"
                   style="width:90px;" />
          </label>
```

- [ ] **Step 2: Add `_currentReplaySpeed` + persistence**

Add methods:

```javascript
  _currentReplaySpeed() {
    // Log-scaled compression 50x .. 800x; slider 0..1000, default mid (≈200x).
    const el = this.shadowRoot && this.shadowRoot.getElementById("speed");
    let frac = 0.5;
    if (el) frac = parseInt(el.value, 10) / 1000;
    else {
      const saved = parseFloat(localStorage.getItem("dreame_a2_mower_replay_speed"));
      if (Number.isFinite(saved)) frac = saved;
    }
    const MIN = Math.log(50), MAX = Math.log(800);
    return Math.exp(MIN + (MAX - MIN) * frac);
  }
```

- [ ] **Step 3: Wire the slider's `oninput`**

In `_render`, after wiring the scrub handlers, add:

```javascript
    const speed = this.shadowRoot.getElementById("speed");
    if (speed) {
      const saved = parseFloat(localStorage.getItem("dreame_a2_mower_replay_speed"));
      if (Number.isFinite(saved)) speed.value = String(Math.round(saved * 1000));
      speed.oninput = () => {
        localStorage.setItem(
          "dreame_a2_mower_replay_speed",
          String(parseInt(speed.value, 10) / 1000),
        );
        // Rebuild the timeline at the new compression, preserving the
        // current fractional playhead position.
        const frac = this._totalMs ? this._playheadMs / this._totalMs : 0;
        this._startAnimation(this._lastAttrs || {});
        this._playheadMs = frac * (this._totalMs || 1);
        this._renderAt(this._playheadMs);
      };
    }
```

In `_render`, stash the attrs for the rebuild: add `this._lastAttrs = a;` right
before `this._startAnimation(a);`.

- [ ] **Step 4: Manual verification**

Reload the card. Drag the speed slider — a short mow should visibly speed up/slow
down; the position persists after a browser refresh. No console errors.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "feat(card): replay-speed slider with log-scaled compression + persistence"
```

---

### Task 16: Pause overlay labels

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

- [ ] **Step 1: Build pause windows from state_samples in `_startAnimation`**

After the charging-window block, add rain/fault windows on the same compressed
axis. Use the existing s2p2 error codes (rain = 56) and charging code = 6:

```javascript
    // Pause overlay windows: [{start_ms, end_ms, label}] on the compressed axis.
    this._pauseWindows = [];
    const addWindows = (samples, matchFn, label) => {
      let runStart = null, runStartUnix = null;
      for (const s of samples || []) {
        if (!Array.isArray(s) || s.length < 2) continue;
        const [tsUnix, code] = s;
        const ms = (tsUnix - FIRST_T) * 1000 * scale;
        if (matchFn(code) && runStart === null) { runStart = ms; runStartUnix = tsUnix; }
        else if (!matchFn(code) && runStart !== null) {
          this._pauseWindows.push({ start_ms: runStart, end_ms: ms,
            label: `${label} — ${Math.round((tsUnix - runStartUnix) / 60)} min` });
          runStart = null;
        }
      }
      if (runStart !== null) {
        this._pauseWindows.push({ start_ms: runStart, end_ms: this._totalMs,
          label });
      }
    };
    addWindows(a.state_samples, c => c === 6, "🔋 charging");
    addWindows(a.error_samples, c => c === 56, "🌧 rain delay");
```

- [ ] **Step 2: Add an overlay `<text>` and render it in `_renderAt`**

In the SVG markup (in `_render`), add after the `<circle id="head" ...>`:

```html
          <text id="pause-label" x="50%" y="14" text-anchor="middle"
                font-size="13" fill="white"
                style="paint-order:stroke;stroke:black;stroke-width:3px;"
                visibility="hidden"></text>
```

At the end of `_renderAt`, add:

```javascript
    const label = this.shadowRoot.getElementById("pause-label");
    if (label) {
      const win = (this._pauseWindows || []).find(w => ms >= w.start_ms && ms <= w.end_ms);
      if (win) { label.textContent = win.label; label.setAttribute("visibility", "visible"); }
      else { label.setAttribute("visibility", "hidden"); }
    }
```

- [ ] **Step 3: Manual verification**

Pick a session with a mid-mow recharge (e.g. `2026-05-20 07:58`). Verify the
`🔋 charging — N min` label appears during the dock freeze and disappears when
mowing resumes. Pick a rain-delay session; verify the `🌧 rain delay` label.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "feat(card): pause overlay labels for charging + rain windows"
```

- [ ] **Step 5: Dead-code sweep**

Confirm the deleted machinery is gone:
```bash
grep -n "_computePauseIntervals\|legGapMs\|pauseBudgetMs\|hasRealTimes\|TARGET_M_PER_S\|mowing_legs\|traversal_legs" custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
```
Expected: no output. If any remain, remove them and re-commit.

---

## Phase F — Migration tool

### Task 17: `track_replay.py` — per-point reconstruction from probe logs

**Files:**
- Create: `tools/_rebuild_session_lib/track_replay.py`
- Test: `tests/tools/test_track_replay.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_track_replay.py
"""Tests for per-point track reconstruction from probe events."""
from __future__ import annotations

from tools._rebuild_session_lib.track_replay import reconstruct_track


class _FakeReader:
    """Minimal stand-in exposing events_for_slot like ProbeReader."""
    def __init__(self, s1p4, s2p1):
        self._s1p4 = s1p4
        self._s2p1 = s2p1

    def events_for_slot(self, siid, piid, *, start_ts, end_ts):
        if (siid, piid) == (1, 4):
            return [(t, v) for (t, v) in self._s1p4 if start_ts <= t <= end_ts]
        if (siid, piid) == (2, 1):
            return [(t, v) for (t, v) in self._s2p1 if start_ts <= t <= end_ts]
        return []


def test_reconstruct_track_classifies_by_area():
    # Two decoded positions: second grows area → mowing.
    decoded = {
        b"\x01": (0.0, 0.0, 0.0, 0.0),    # x, y, area, heading
        b"\x02": (1.0, 0.0, 0.5, 10.0),
    }
    reader = _FakeReader(s1p4=[(1001, b"\x01"), (1002, b"\x02")], s2p1=[(1000, 0)])
    track = reconstruct_track(
        reader, start_ts=1000, end_ts=2000,
        _decoder=lambda blob: decoded[blob],
    )
    assert [p["role"] for p in track] == ["traversal", "mowing"]
    assert track[0]["task_state"] == 0
    assert track[1]["heading_deg"] == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_track_replay.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `reconstruct_track`**

```python
# tools/_rebuild_session_lib/track_replay.py
"""Reconstruct the per-point `track` from probe s1p4 (position+area+heading)
+ s2p1 (task_state) events.

Mirrors the live LiveMapState.append_point classification (area-delta) and
update_task_state tagging, so rebuilt archives are byte-compatible with
live-captured ones (before the finalize classifier runs).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wifi_replay import _coerce_blob

_DEDUP_SQ = 0.04   # 20 cm squared — matches live append_point


def _default_decoder(blob: bytes) -> tuple[float, float, float, float] | None:
    """Decode (x_m, y_m, area_m2, heading_deg) from a full s1p4 frame.

    Returns None for non-full frames (8-byte beacons carry no area/heading;
    they are skipped — a docked/idle beacon adds no trail value)."""
    from custom_components.dreame_a2_mower.protocol.telemetry import (
        decode_s1p4,
        InvalidS1P4Frame,
    )
    try:
        tm = decode_s1p4(blob)
    except InvalidS1P4Frame:
        return None
    return (tm.x_m, tm.y_m, tm.area_mowed_m2, tm.heading_deg)


def reconstruct_track(
    reader: Any,
    start_ts: int,
    end_ts: int,
    *,
    _decoder: Callable[[bytes], tuple[float, float, float, float] | None] | None = None,
) -> list[dict]:
    """Return a list of track-point dicts for the session window."""
    decode = _decoder or _default_decoder
    s1p4 = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)
    s2p1 = reader.events_for_slot(2, 1, start_ts=start_ts, end_ts=end_ts)

    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p4:
        timeline.append((ts, "pos", val))
    for ts, val in s2p1:
        timeline.append((ts, "task", val))
    timeline.sort(key=lambda t: t[0])

    track: list[dict] = []
    last_task = -1
    last_area = 0.0
    for ts, kind, val in timeline:
        if kind == "task":
            try:
                last_task = int(val)
            except (TypeError, ValueError):
                pass
            continue
        blob = _coerce_blob(val)
        if blob is None:
            continue
        dec = decode(blob)
        if dec is None:
            continue
        x_m, y_m, area_m2, heading = dec
        if track:
            dx = x_m - track[-1]["x_m"]
            dy = y_m - track[-1]["y_m"]
            if (dx * dx + dy * dy) < _DEDUP_SQ and (ts - track[-1]["t"]) < 0.5:
                continue
        role = "mowing" if (area_m2 - last_area) > 0.0 else "traversal"
        track.append({
            "t": float(ts), "x_m": float(x_m), "y_m": float(y_m),
            "area_m2": float(area_m2), "heading_deg": float(heading),
            "task_state": last_task, "role": role,
        })
        last_area = area_m2
    return track
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_track_replay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/_rebuild_session_lib/track_replay.py tests/tools/test_track_replay.py
git commit -m "feat(rebuild): per-point track reconstruction from probe logs"
```

---

### Task 18: Wire `rebuild_session.py` to emit the new shape

**Files:**
- Modify: `tools/rebuild_session.py`
- Modify/Delete: `tools/_rebuild_session_lib/legs_replay.py`, `tests/tools/test_legs_replay.py`

- [ ] **Step 1: Swap the reconstruction call**

In `rebuild_session.py`, replace the `from tools._rebuild_session_lib.legs_replay import reconstruct_legs`
import with `from tools._rebuild_session_lib.track_replay import reconstruct_track`.
Find where `reconstruct_legs(...)` is called and where `_local_legs` / `_legs_meta`
are written into the rebuilt `raw_dict`. Replace with:

```python
    track = reconstruct_track(reader, start_ts=window.start_ts, end_ts=window.end_ts)
    raw_dict["track"] = [
        [p["t"], p["x_m"], p["y_m"], p["area_m2"], p["heading_deg"],
         p["task_state"], p["role"]]
        for p in track
    ]
    # Stage-2 classify against the archive's cloud track (verbatim store).
    from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
        finalize_classify_raw_dict,
    )
    cloud_segments = raw_dict.get("cloud_track") or _cloud_segments_from_summary(raw_dict)
    finalize_classify_raw_dict(raw_dict, cloud_segments)
```

Remove any writes of `_local_legs`, `_mowing_legs`, `_traversal_legs`, `_legs_meta`
in this tool. Add a small helper `_cloud_segments_from_summary(raw_dict)` that pulls
`map[].track` (or the existing parsed track_segments) from the archive's pre-existing
cloud JSON, mirroring how `parse_session_summary` reads it — reuse the parser:

```python
def _cloud_segments_from_summary(raw_dict):
    from custom_components.dreame_a2_mower.protocol import session_summary as ss
    try:
        return ss.parse_session_summary(raw_dict).track_segments
    except Exception:
        return []
```

- [ ] **Step 2: Delete the obsolete legs reconstruction + its test**

```bash
git rm tools/_rebuild_session_lib/legs_replay.py tests/tools/test_legs_replay.py
grep -rn "legs_replay\|reconstruct_legs" tools tests | grep -v __pycache__
```
Expected: no remaining references after the import swap in Step 1.

- [ ] **Step 3: Run the tools test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/ -v`
Expected: PASS (test_track_replay, test_samples_replay, test_state_replay,
test_wifi_replay). Update any tool test asserting the old `_local_legs` output.

- [ ] **Step 4: Dry-run the tool on one real archive (dev box)**

Run (read-only inspection — confirm it produces `track` + `cloud_track`):
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/rebuild_session.py --help
```
Expected: help text. (Actual rebuild against live archives is a manual migration
step the user runs after merge; do not mutate archives in CI.)

- [ ] **Step 5: Commit**

```bash
git add -A tools/ tests/tools/
git commit -m "feat(rebuild): emit per-point track + cloud_track, drop legs reconstruction"
```

---

## Phase G — Inventory, cleanup, full sweep

### Task 19: Remove `compute_legs_timeline_from_diff`, confirm grid helpers retained

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/trail_diff.py`
- Modify: `tests/coordinator/test_legs_timeline_build.py`, `tests/test_render_timeline_order.py`

- [ ] **Step 1: Find remaining callers**

```bash
grep -rn "compute_legs_timeline_from_diff\|compute_traversal_from_diff" custom_components tests tools | grep -v __pycache__
```
Expected after Phase C/D: no production callers of `compute_legs_timeline_from_diff`.
If `compute_traversal_from_diff` is also unused, both go; `_build_cloud_grid` and
`_make_coverage_check` MUST stay (used by `live_map/classify.py`).

- [ ] **Step 2: Delete the unused functions (keep grid helpers)**

Remove `compute_legs_timeline_from_diff` (and `compute_traversal_from_diff` if Step 1
showed it unused) from `trail_diff.py`. Keep `_dist_sq_point_segment`,
`_build_cloud_grid`, `_make_coverage_check`.

- [ ] **Step 3: Prune the dead tests**

`tests/coordinator/test_legs_timeline_build.py` tests `_legs_meta`-based timeline
building that no longer exists — delete it:
```bash
git rm tests/coordinator/test_legs_timeline_build.py
```
Update `tests/test_render_timeline_order.py` to feed a `track` and assert
`derive_render_legs` ordering instead of the diff timeline (convert fixtures to the
row shape). If it only tested the removed diff function, delete it too.

- [ ] **Step 4: Run the protocol + coordinator tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_replay.py tests/coordinator/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A custom_components/dreame_a2_mower/protocol/trail_diff.py tests/
git commit -m "refactor(protocol): drop legs-timeline diff; keep grid helpers for classifier"
```

---

### Task 20: Inventory + entity-inventory fact records

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Add/retract the protocol-surface records**

In `inventory.yaml`, add a `verifications:` entry (today's date) to the
`summary_track_segments` entry recording the semantic change (parser yields it;
integration stores verbatim under `cloud_track`, no longer surfaced to dashboard).
Add new entries `archive_track` (per-point stream: t, x_m, y_m, area_m2,
heading_deg, task_state, role; classified inline + finalize) and
`archive_cloud_track` (verbatim cloud blob). Retract any `_local_legs`,
`_legs_meta`, `_mowing_legs`, `_traversal_legs` mentions with
`status: retracted` + a `retracts:` quoting the prior claim text. Set
`status.last_seen` to today.

- [ ] **Step 2: Update entity-inventory for `picked_session` attrs**

In `entity-inventory.yaml`, update the `sensor.dreame_a2_mower_picked_session`
attribute list: remove `legs`, `mowing_legs`, `traversal_legs`, `local_leg_count`;
add `legs_timeline` (now track-derived), `track_first_ts`, `track_last_ts`,
`distance_mowing_m`, `distance_traversal_m`. Add a `verifications:` entry dated
today describing the source change (now derived from archive `track`).

- [ ] **Step 3: Run the inventory audit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_audit.py`
Expected: passes (no orphaned/contradicted entries). Fix any flagged
inconsistency.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "docs(inventory): record track/cloud_track surfaces; retract leg keys"
```

---

### Task 21: Full suite, observability schema, CLAUDE.md note

**Files:**
- Modify: `custom_components/dreame_a2_mower/observability/schemas.py`
- Modify: `custom_components/dreame_a2_mower/CLAUDE.md`

- [ ] **Step 1: Update the archive schema allow-list**

In `observability/schemas.py`, the archive schema lists `_legs_meta: True` (and
likely `_local_legs` etc.). Replace those keys with `track: True` and
`cloud_track: True`. Remove the dead leg keys.

- [ ] **Step 2: Run the FULL test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass. Baseline before this work was 1591 passed / 4 skipped; expect a
similar count minus the deleted tests plus the new ones. Investigate and fix any
failure — do NOT leave reds.

- [ ] **Step 3: Add a CLAUDE.md section**

Add a "Session replay data model (load-bearing)" section to
`custom_components/dreame_a2_mower/CLAUDE.md` documenting: per-point `track` is the
only trail storage; `role` classified inline (area-delta) + finalize (cloud rescue
+ smoothing); legs are render-time only via `derive_render_legs`; `cloud_track`
stored verbatim; capture continues until docked; old archives need
`tools/rebuild_session.py`. Reference this spec + plan.

- [ ] **Step 4: Verify no stragglers reference the old model**

```bash
grep -rn "_local_legs\|_legs_meta\|_mowing_legs\|_traversal_legs\|set_mowing\|\.leg_is_mowing\|local_leg_count" custom_components tools | grep -v __pycache__
```
Expected: no output. Fix any straggler.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/observability/schemas.py custom_components/dreame_a2_mower/CLAUDE.md
git commit -m "chore: archive schema + CLAUDE.md for track-based replay; remove leg references"
```

---

### Task 22: Live validation

**Files:** none (manual acceptance against real sessions)

- [ ] **Step 1: Rebuild existing archives**

On the dev box, run `tools/rebuild_session.py` against the sessions directory so
existing archives gain `track` + `cloud_track`. Confirm a sample archive now has
both keys and no `_local_legs`/`_legs_meta`.

- [ ] **Step 2: Spot-mow check**

Pick a recent spot mow in the dashboard. Verify: dock→spot traversal is grey, the
spot is green, dock-return is grey, the last grey segment ends exactly where green
begins. No console errors.

- [ ] **Step 3: Long-mow-with-recharge check**

Pick `2026-05-20 07:58` (or any session with a mid-mow recharge). Verify: lawn
fills chronologically (no parallel-mower illusion), the mower freezes at the dock
during the recharge with the `🔋 charging` label, green resumes from the
post-recharge point.

- [ ] **Step 4: Rain + speed-slider check**

Pick a rain-delay session: verify the `🌧 rain delay` overlay and that total
animation stays ≤90 s even for a 19 h session. Drag the speed slider across its
range and confirm smooth scaling + persistence after refresh.

- [ ] **Step 5: Final commit / push**

If everything passes, push per `feedback_push_upstream_regularly` and cut a release
per `feedback_tag_after_push` (HACS needs a GitHub Release):
```bash
git push origin main
# then bump + tag + release via the repo's release.sh
```

---

## Self-Review notes

- **Spec coverage:** per-point capture (T1-3), classifier area-delta + cloud rescue + smoothing (T2, T5, T11), capture-until-docked (T12), clean break / no back-compat (T4, T8, T10, T18-21), cloud_track verbatim (T11), task_state per-point (T1-2), render-time leg derivation (T6, T8, T13), time-coded JS engine (T14), fixed compression + speed slider + clamp (T14-15), pause overlays (T16), probe-log rebuild (T17-18), inventory discipline (T20), live validation incl. the three spec scenarios (T22). All spec sections map to a task.
- **Type consistency:** `TrackPoint` field order `(t, x_m, y_m, area_m2, heading_deg, task_state, role)` is identical in the dataclass (T1), `append_point` (T2), dump/hydrate rows (T3), inject rows (T10), classify dict view (T11), derive_render_legs input (T6), and probe reconstruction (T17). `legs_timeline` leg dict keys `{role, start_ts, end_ts, pts}` are consistent across T6/T8/T13/T14. `compute_track_distances` returns `{distance_m, distance_mowing_m, distance_traversal_m}` consumed identically in T8.
- **Known divergence from spec:** the spec described a new `session_ending` flag for lifecycle; the codebase already has `_wait_for_dock_return` that keeps `live_map` active after end-of-session. T12 reuses that mechanism (drop the premature `task_idle` signal; extend timeout to 10 min) rather than adding a parallel flag — same behavior, less churn. The `session_ending` field is still added (T1/T3) for the in-progress payload but the lifecycle is driven by the existing wait.
