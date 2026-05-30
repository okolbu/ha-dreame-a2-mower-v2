# Non-mow session capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture head-to-maintenance-point and manual-drive runs as their own sessions (same archive, distinct label, 0-area handling), and fix the bug where several runs merge into one archive entry.

**Architecture:** Classify each session by *presence of mow-evidence* (positive signal, decided at finalize), branch the finalize path so non-mow runs finalize locally on dock-return (no cloud-md5 wait), add a new-task-command boundary so back-to-back runs without docking still split, and surface type/target/outcome in the archive + picker label. Pure helpers are unit-tested; integration points are minimal edits to existing coordinator code.

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest (run via `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`). Spec: `docs/superpowers/specs/2026-05-30-non-mow-session-capture-design.md`.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `custom_components/dreame_a2_mower/live_map/state.py` | in-progress session state | add fields `target_ids`, `last_task_op`, `area_ever_positive`; reset in `begin_session` |
| `custom_components/dreame_a2_mower/live_map/classify.py` | role smoothing (existing) | add pure `classify_session_type(...)` |
| `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` | MQTT routing / session grabber | feed s2p56 task_ids + s2p50 op + area-positive into live_map; new-task-command boundary |
| `custom_components/dreame_a2_mower/coordinator/_session.py` | finalize / persist / restore | branch finalize: local-finalize for non-mow on dock |
| `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` | archive raw_dict injection | write `session_type`/`outcome`/`target_ids`/`mow_type`/`start_mode` |
| `custom_components/dreame_a2_mower/protocol/session_summary.py` | OSS summary decode | expose `mode`→mow_type label + `start_mode` label |
| `custom_components/dreame_a2_mower/session_card.py` | picker label + card | type-aware prefix + outcome; 0-area card (phase 2) |

**Phasing:** Tasks 1-8 are Phase 1 (sessions split + typed + labelled — working, testable). Tasks 9-10 are Phase 2 (card polish). Phase 1 alone fixes the merge bug and is independently shippable.

---

## Task 1: LiveMapState — type-tracking fields

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py` (dataclass body ~line 62-118; `begin_session` ~line 125-139)
- Test: `tests/live_map/test_state_session_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/live_map/test_state_session_type.py
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_resets_type_tracking_fields():
    lm = LiveMapState()
    lm.target_ids = [9]
    lm.last_task_op = 103
    lm.area_ever_positive = True
    lm.begin_session(1000)
    assert lm.target_ids == []
    assert lm.last_task_op is None
    assert lm.area_ever_positive is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_state_session_type.py -q`
Expected: FAIL (`AttributeError: 'LiveMapState' object has no attribute 'target_ids'`).

- [ ] **Step 3: Add the fields + resets**

In the dataclass body (after `settings_snapshot` field, ~line 118) add:

```python
    target_ids: list[int] = field(default_factory=list)
    """Ordered, de-duplicated s2p56 task_ids (first element of each status
    entry) visited this session — the per-target selectors for point /
    spot / zone / edge runs. Empty for all-area mows."""

    last_task_op: int | None = None
    """Last s2p50 TASK op seen this session (15=manual, 100-103=mow
    subtypes, 109=cruise). None when the op never echoed (scheduled mows,
    most app head-to-point moves)."""

    area_ever_positive: bool = False
    """True once area_mowed_m2 > 0 at any point — a positive mow-evidence
    signal independent of the s2p2 50/53 start code."""
```

In `begin_session` (after `self.settings_snapshot = None`, ~line 139) add:

```python
        self.target_ids = []
        self.last_task_op = None
        self.area_ever_positive = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_state_session_type.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/live_map/test_state_session_type.py
git commit -m "feat(live_map): add session-type tracking fields to LiveMapState"
```

---

## Task 2: Pure `classify_session_type` helper

This is the heart of the feature — a pure function so it's fully unit-testable.

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/classify.py` (append)
- Test: `tests/live_map/test_classify_session_type.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/live_map/test_classify_session_type.py
from custom_components.dreame_a2_mower.live_map.classify import (
    classify_session_type,
)


def test_manual_when_op_15():
    assert classify_session_type(
        last_task_op=15, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None,
    ) == ("manual_drive", None)


def test_mow_when_start_code_seen():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=True, area_ever_positive=False,
        last_point_end_code=None,
    )[0] == "mow"


def test_mow_when_area_positive_even_without_start_code():
    # spot mow blades-up-traverses first, but area>0 once it cuts
    assert classify_session_type(
        last_task_op=103, saw_mow_start=False, area_ever_positive=True,
        last_point_end_code=None,
    )[0] == "mow"


def test_maintenance_run_arrived():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=75,
    ) == ("maintenance_run", "arrived")


def test_maintenance_run_could_not_reach():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=76,
    ) == ("maintenance_run", "could_not_reach")


def test_maintenance_run_unknown_outcome_on_midrun_abort():
    # failed mid-way, returned, no 75/76 — still a non-mow run, outcome unknown
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None,
    ) == ("maintenance_run", "unknown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify_session_type.py -q`
Expected: FAIL (`ImportError: cannot import name 'classify_session_type'`).

- [ ] **Step 3: Implement the helper**

Append to `custom_components/dreame_a2_mower/live_map/classify.py`:

```python
def classify_session_type(
    *,
    last_task_op: int | None,
    saw_mow_start: bool,
    area_ever_positive: bool,
    last_point_end_code: int | None,
) -> tuple[str, str | None]:
    """Resolve (session_type, outcome) at finalize.

    Order (positive signals first):
      1. manual_drive  — s2p50 op=15 seen (manual/remote control).
      2. mow           — s2p2 50/53 start code seen OR area_mowed ever > 0.
      3. maintenance_run — the default non-mow run; outcome from the last
         point end-code: 75=arrived, 76=could_not_reach, else unknown.

    Returns (session_type, outcome). outcome is None for mow/manual_drive.
    """
    if last_task_op == 15:
        return "manual_drive", None
    if saw_mow_start or area_ever_positive:
        return "mow", None
    outcome = {75: "arrived", 76: "could_not_reach"}.get(
        last_point_end_code, "unknown"
    )
    return "maintenance_run", outcome
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify_session_type.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/classify.py tests/live_map/test_classify_session_type.py
git commit -m "feat(live_map): pure classify_session_type (mow-evidence rule)"
```

---

## Task 3: `mode`/`start_mode` → labels in session_summary

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/session_summary.py`
- Test: `tests/protocol/test_session_summary_mode.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_session_summary_mode.py
from custom_components.dreame_a2_mower.protocol.session_summary import (
    mow_type_from_mode, start_mode_label,
)


def test_mow_type_from_mode():
    assert mow_type_from_mode(100) == "all_areas"
    assert mow_type_from_mode(101) == "edge"
    assert mow_type_from_mode(102) == "zone"
    assert mow_type_from_mode(103) == "spot"
    assert mow_type_from_mode(999) is None  # unknown → None, raw int kept by caller


def test_start_mode_label():
    assert start_mode_label(1) == "scheduled"
    assert start_mode_label(0) == "manual"
    assert start_mode_label(7) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_session_summary_mode.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

Append to `custom_components/dreame_a2_mower/protocol/session_summary.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_session_summary_mode.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/session_summary.py tests/protocol/test_session_summary_mode.py
git commit -m "feat(protocol): mode→mow_type + start_mode labels"
```

---

## Task 4: Capture s2p56 task_ids, s2p50 op, area-positive into live_map

**Read first:** `coordinator/_mqtt_handlers.py` — the property-dispatch method that handles individual `(siid, piid)` pushes (search for `piid==56`, `piid==50`, and where `error_samples`/`state_samples` are appended). You are adding three small captures alongside the existing sample captures, all guarded by `self.live_map.is_active()`.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py`
- Test: `tests/integration/test_session_type_capture.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_session_type_capture.py
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.coordinator import _mqtt_handlers as MH


def test_capture_helpers_update_live_map():
    lm = LiveMapState()
    lm.begin_session(1000)
    # task_ids from an s2p56 status list (multi-target queue)
    MH.capture_session_type_signals(
        lm, s2p56_status=[[1, 0], [2, -1]], s2p50_op=None, area_m2=0.0,
    )
    assert lm.target_ids == [1, 2]
    # op echo
    MH.capture_session_type_signals(
        lm, s2p56_status=None, s2p50_op=103, area_m2=0.0,
    )
    assert lm.last_task_op == 103
    # area positive latches
    MH.capture_session_type_signals(
        lm, s2p56_status=None, s2p50_op=None, area_m2=1.4,
    )
    assert lm.area_ever_positive is True
    # dedup consecutive duplicate target_ids
    MH.capture_session_type_signals(
        lm, s2p56_status=[[2, 0]], s2p50_op=None, area_m2=0.0,
    )
    assert lm.target_ids == [1, 2]  # unchanged (2 already last)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_session_type_capture.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'capture_session_type_signals'`).

- [ ] **Step 3: Add the pure helper + wire the call sites**

Add this module-level function to `coordinator/_mqtt_handlers.py` (top level, near other helpers):

```python
def capture_session_type_signals(
    live_map,
    *,
    s2p56_status: list | None,
    s2p50_op: int | None,
    area_m2: float | None,
) -> None:
    """Feed mow-evidence / target signals into the active live_map session.

    - s2p56_status: list of [task_id, stage] entries → append the task_ids
      (dedup against the running tail).
    - s2p50_op: TASK op (15 manual, 100-103 mow, 109 cruise).
    - area_m2: latches area_ever_positive when > 0.
    """
    if s2p56_status:
        for entry in s2p56_status:
            if isinstance(entry, list) and entry:
                tid = entry[0]
                if not live_map.target_ids or live_map.target_ids[-1] != tid:
                    live_map.target_ids.append(tid)
    if s2p50_op is not None:
        live_map.last_task_op = s2p50_op
    if area_m2 is not None and area_m2 > 0:
        live_map.area_ever_positive = True
```

Then wire it at the existing push-handling sites (all guarded by `self.live_map.is_active()`):
- where `(2,56)` is handled: `capture_session_type_signals(self.live_map, s2p56_status=value.get("status"), s2p50_op=None, area_m2=None)`
- where `(2,50)` TASK envelopes are handled: extract `op = value.get("d", {}).get("o")` and call `capture_session_type_signals(self.live_map, s2p56_status=None, s2p50_op=op, area_m2=None)`
- in the telemetry-append block (~line 408, where `append_point` is called): `capture_session_type_signals(self.live_map, s2p56_status=None, s2p50_op=None, area_m2=new_state.area_mowed_m2)`

- [ ] **Step 4: Run test + full suite slice to verify**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_session_type_capture.py tests/integration -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/integration/test_session_type_capture.py
git commit -m "feat(coordinator): capture s2p56 target_ids / s2p50 op / area into live_map"
```

---

## Task 5: Archive injection — write session_type / outcome / target_ids

**Read first:** `coordinator/_lidar_oss.py:114` `_inject_live_map_into_raw_dict` — note how it writes `track`, `state_samples`, `error_samples` from `self.live_map`. You append the new keys here. The classifier inputs come from: `saw_mow_start` = any `error_samples` code in {50,53}; `area_ever_positive`, `last_task_op`, `target_ids` from live_map; `last_point_end_code` = last `error_samples` code in {75,76}.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
- Test: `tests/integration/test_archive_session_type.py` (create)

- [ ] **Step 1: Write the failing test** — a maintenance run (no mow-evidence, end-code 75) writes `session_type="maintenance_run"`, `outcome="arrived"`, `target_ids` from live_map.

```python
# tests/integration/test_archive_session_type.py
from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    _LidarOssMixin,
)


def _coord_with(lm):
    c = MagicMock(spec=_LidarOssMixin)
    c.live_map = lm
    return c


def test_inject_writes_maintenance_run_fields():
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.target_ids = [2]
    lm.error_samples = [(1001, 75)]  # arrived at maintenance point, no 50/53
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "maintenance_run"
    assert raw["outcome"] == "arrived"
    assert raw["target_ids"] == [2]


def test_inject_writes_mow_fields():
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.error_samples = [(1001, 50), (1100, 48)]  # mow start + complete
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "mow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_archive_session_type.py -q`
Expected: FAIL (`KeyError: 'session_type'`).

- [ ] **Step 3: Implement** — inside `_inject_live_map_into_raw_dict`, after the existing `error_samples` write, add:

```python
        from ..live_map.classify import classify_session_type
        lm = self.live_map
        codes = [code for _, code in (lm.error_samples or [])]
        saw_mow_start = any(c in (50, 53) for c in codes)
        end_codes = [c for c in codes if c in (75, 76)]
        last_point_end_code = end_codes[-1] if end_codes else None
        session_type, outcome = classify_session_type(
            last_task_op=lm.last_task_op,
            saw_mow_start=saw_mow_start,
            area_ever_positive=lm.area_ever_positive,
            last_point_end_code=last_point_end_code,
        )
        raw_dict["session_type"] = session_type
        if outcome is not None:
            raw_dict["outcome"] = outcome
        if lm.target_ids:
            raw_dict["target_ids"] = list(lm.target_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_archive_session_type.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_archive_session_type.py
git commit -m "feat(coordinator): write session_type/outcome/target_ids into the archive"
```

---

## Task 6: mow_type from the cloud summary

**Read first:** `coordinator/_session.py` and `_lidar_oss.py` — find where the parsed OSS summary (`SessionSummary` with `.mode` / `.start_mode`) is merged into the archive raw_dict on the mow path. Add the decoded labels there.

**Files:**
- Modify: `coordinator/_lidar_oss.py` (or wherever the summary merges into raw_dict)
- Test: `tests/integration/test_archive_mow_type.py` (create)

- [ ] **Step 1: Write the failing test** — given a parsed summary with `mode=103, start_mode=0`, the merged archive carries `mow_type="spot"`, `mow_type_raw=103`, `start_mode_label="manual"`.

```python
# tests/integration/test_archive_mow_type.py
from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    merge_mow_type_fields,
)


def test_merge_mow_type_fields():
    raw: dict = {}
    merge_mow_type_fields(raw, mode=103, start_mode=0)
    assert raw["mow_type"] == "spot"
    assert raw["mow_type_raw"] == 103
    assert raw["start_mode_label"] == "manual"


def test_merge_mow_type_unknown_mode_keeps_raw():
    raw: dict = {}
    merge_mow_type_fields(raw, mode=999, start_mode=1)
    assert raw.get("mow_type") is None
    assert raw["mow_type_raw"] == 999
    assert raw["start_mode_label"] == "scheduled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_archive_mow_type.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** the helper in `_lidar_oss.py` and call it where the summary merges:

```python
def merge_mow_type_fields(raw_dict: dict, *, mode: int, start_mode: int) -> None:
    """Write mow_type / mow_type_raw / start_mode_label from the OSS summary."""
    from ..protocol.session_summary import mow_type_from_mode, start_mode_label
    label = mow_type_from_mode(mode)
    if label is not None:
        raw_dict["mow_type"] = label
    raw_dict["mow_type_raw"] = mode
    sm = start_mode_label(start_mode)
    if sm is not None:
        raw_dict["start_mode_label"] = sm
```

Call `merge_mow_type_fields(raw_dict, mode=summary.mode, start_mode=summary.start_mode)` at the summary-merge site (mow path only).

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_archive_mow_type.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_archive_mow_type.py
git commit -m "feat(coordinator): archive mow_type/start_mode from OSS summary"
```

---

## Task 7: Boundary + finalize branch (the merge fix)

**Read first (critical):** Trace the finalize flow before editing:
1. `coordinator/_mqtt_handlers.py` — `_on_state_update` task_state transition block (~line 277-466): `begin_session` on inactive→active (~310), and where the session-end / `_periodic_session_retry` is triggered.
2. `coordinator/_session.py` — `_run_finalize_incomplete`, `_periodic_session_retry`, `_wait_for_dock_return`, and the mow finalize that awaits the cloud OSS summary (md5). Identify the exact point where, for a mow, the code *waits* for the cloud summary.

**The two edits (per spec §Boundary):**

(a) **Local-finalize for non-mow on dock-return.** At the finalize decision point, compute the provisional type from the same inputs as Task 5 (`saw_mow_start` / `area_ever_positive` / `last_task_op`). If it is NOT a mow (i.e. `manual_drive` or `maintenance_run`), finalize **locally** — inject the archive (Task 5 already classifies + writes the fields) and write the entry **without awaiting the cloud md5**. Only the mow path keeps the existing cloud-summary wait.

(b) **New-task-command boundary.** When a NEW task command begins (`s2p56` transitions empty→active with a fresh target set, OR a new `s2p2 ∈ {50,53}`, OR a new `s2p50` op) while `live_map.is_active()` and the prior run has already reached task-done (`task_state` 2/None) or is otherwise distinct, finalize the prior session first (path (a) if non-mow, else the mow path), then `begin_session` for the new one. This splits the manual→spot (no-dock) case.

**Files:**
- Modify: `coordinator/_session.py`, `coordinator/_mqtt_handlers.py`
- Test: `tests/integration/test_session_boundary_split.py` (create)

- [ ] **Step 1: Write the failing test** — drive two non-mow runs through the coordinator's MQTT path with a dock between, assert **two** archive entries (regression for the 2026-05-30 four-merged bug). Use the existing coordinator test fixtures (see `tests/integration/test_coordinator.py` for the fake-coordinator pattern) to feed: undock → s2p56 active (task_id 1) → s2p2=75 → dock; undock → s2p56 active (task_id 2) → s2p2=75 → dock. Assert the archive write was called twice with `session_type="maintenance_run"`.

```python
# tests/integration/test_session_boundary_split.py
# (Construct via the existing fake-coordinator helper; pseudocode skeleton —
#  fill the fixture calls to match tests/integration/test_coordinator.py.)
def test_two_maintenance_runs_with_dock_between_produce_two_entries(make_coord):
    coord = make_coord()
    archived = []
    coord._write_archive_entry = lambda raw: archived.append(raw)  # adapt to real name
    # run 1
    feed_undock(coord); feed_s2p56(coord, [[1, 0]]); feed_s2p2(coord, 75); feed_dock(coord)
    # run 2
    feed_undock(coord); feed_s2p56(coord, [[2, 0]]); feed_s2p2(coord, 75); feed_dock(coord)
    assert len(archived) == 2
    assert all(a["session_type"] == "maintenance_run" for a in archived)
    assert [a["target_ids"] for a in archived] == [[1], [2]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_session_boundary_split.py -q`
Expected: FAIL (one entry, or never finalizes) — reproduces the merge bug.

- [ ] **Step 3: Implement edits (a) and (b)** as specified above in `_session.py` / `_mqtt_handlers.py`. Keep the mow path unchanged.

- [ ] **Step 4: Run test + the finalize/session suites**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration tests/live_map -q`
Expected: PASS, no regressions in existing session/finalize tests.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/integration/test_session_boundary_split.py
git commit -m "fix(coordinator): split non-mow runs (local finalize + new-command boundary)"
```

---

## Task 8: Picker label by type

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py` `format_session_label` (~line 386-413)
- Test: `tests/integration/test_session_label_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_session_label_type.py
from types import SimpleNamespace
from custom_components.dreame_a2_mower.session_card import format_session_label


def _entry(**kw):
    base = dict(start_ts=1717081740, end_ts=1717083000, map_id=1,
                area_mowed_m2=0.0, duration_min=21, local_trail_complete=True)
    base.update(kw); return SimpleNamespace(**base)


def test_mow_label_unchanged():
    lbl = format_session_label(_entry(session_type="mow", area_mowed_m2=42.0))
    assert lbl.startswith("[Mowing] [Map 2]")


def test_maintenance_run_label():
    lbl = format_session_label(_entry(session_type="maintenance_run", outcome="could_not_reach"))
    assert lbl.startswith("[To Point] [Map 2]")
    assert "(blocked)" in lbl


def test_manual_drive_label():
    lbl = format_session_label(_entry(session_type="manual_drive"))
    assert lbl.startswith("[Manual] [Map 2]")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_session_label_type.py -q`
Expected: FAIL (everything labelled `[Mowing]`).

- [ ] **Step 3: Implement** — replace the hardcoded prefix in `format_session_label`:

```python
    session_type = getattr(entry, "session_type", "mow")
    map_id = getattr(entry, "map_id", -1)
    map_prefix = "[Map ?]" if map_id == -1 else f"[Map {map_id + 1}]"
    if session_type == "maintenance_run":
        outcome = getattr(entry, "outcome", None)
        suffix = {"arrived": " (arrived)", "could_not_reach": " (blocked)"}.get(outcome, "")
        base = f"[To Point] {map_prefix} {ts_str}{suffix}"
    elif session_type == "manual_drive":
        base = f"[Manual] {map_prefix} {ts_str}"
    else:
        base = (
            f"[Mowing] {map_prefix} {ts_str}"
            f" — {entry.area_mowed_m2:.1f} m² / {entry.duration_min}min"
        )
    if not getattr(entry, "local_trail_complete", True):
        return f"⚠ {base} (partial trail)"
    return base
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_session_label_type.py -q`
Expected: PASS. Also run the existing label test to confirm back-compat: `... -m pytest tests/integration -k label -q`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/integration/test_session_label_type.py
git commit -m "feat(session_card): type-aware picker label ([To Point]/[Manual])"
```

---

## Task 9 (Phase 2): Back-compat default + full-suite gate

- [ ] **Step 1:** Add a test that an archive entry dict **without** `session_type` (old archive) → `format_session_label` and the card treat it as `mow`. (Tasks 5/8 already default to `mow`; this pins it.)
- [ ] **Step 2:** Run the full suite: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`. Expected: all pass (baseline 901+).
- [ ] **Step 3:** Run `/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.inventory_audit` if any inventory changed; validate `inventory.yaml`.
- [ ] **Step 4: Commit** any test additions.

---

## Task 10 (Phase 2): Card 0-area handling

**Files:** `session_card.py` (the picked-session card builder — `build_picked_session_summary` / `_summary_identity`).

- [ ] **Step 1:** Test that for `session_type in {maintenance_run, manual_drive}` the card summary suppresses mow stats (area/coverage/mowing-time = 0/N-A) and surfaces `session_type`, `outcome`, `target_ids` (display number resolved from the active map's point list when available, else raw id), and the 3-leg duration.
- [ ] **Step 2-5:** Implement minimal card branch, run card tests (`tests/integration -k session_card`), commit.

---

## Spec coverage check

| Spec section | Task |
|---|---|
| Classification (op=15/mow-evidence/default) | 2, 5 |
| Boundary (dock OR new-command) + local finalize | 7 |
| `session_type` / `outcome` / `target_ids` archive | 1, 5 |
| `mow_type` from summary `mode` + `start_mode` | 3, 6 |
| Multi-target from s2p56 list | 4 |
| `manual_drive` (op=15) | 2, 5, 8 |
| Labels `[To Point]`/`[Manual]` + outcome | 8 |
| 0-area card | 10 |
| Back-compat default `mow` | 9 |
| Inferred-start note | spec + inventory (no code) |

## Notes / risks for the implementer

- **Run path prefix:** all pytest commands use `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest` (the vanilla stubbed-HA venv; system python3 is 3.14 and broken).
- **Task 7 is the only intricate one** — do the "read first" trace before editing; keep the mow path byte-for-byte unchanged and only *add* the non-mow local-finalize branch and the new-command boundary.
- **Display "Point N":** the s2p56 task_id is a stable per-target id, NOT the app's display number — resolve the number from the map's point list at render time (Task 10); store the raw id.
- **3-element s2p56 arrays — do NOT touch the stage element for this feature.** The
  new capture reads ONLY element[0] (task_id) of each entry. The middle/last element
  (the stage) is *unsettled*: the integration currently reads the MIDDLE (`status[0][1]`)
  as task_state, but a 2026-05-30 observation suggests the LAST element may be the
  start(0)/done(2) flag for 3-element entries, and `[1,0,2]` has been seen both
  mid-session (2026-05-09, ran 19 h after) and at session-end (current log) — i.e. it
  is NOT a reliable end signal. This feature is safe because non-mow runs (points,
  manual) are 2-element (unambiguous) and the 3-element scheduled-mow path is unchanged.
  If a future change needs the 3-element stage, resolve the open question first
  (`inventory.yaml § s2p56` open_questions / `knowledge-gaps.md`): corpus-validate
  middle-vs-last and mid-vs-end across all `[1,0,2]` occurrences.
</content>
