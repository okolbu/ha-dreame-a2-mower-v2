# Session-summary card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the picked session's stats on the Sessions dashboard tab via a new attribute-rich sensor + 5 new cards + 2 apexcharts series. Add a `settings_snapshot` capture so future archives also carry the per-map settings in effect.

**Architecture:** A new pure module `session_card.py` builds a flat attribute dict from an archived session's raw JSON + parsed `SessionSummary`. A new `DreameA2PickedSessionSensor` exposes that dict. The work-log select entity already calls `coordinator.render_work_log_session(filename)` on every pick — we extend that path to stash the summary on the coordinator. `LiveMapState.settings_snapshot` captures the per-map cloud-state settings at session_begin and persists alongside `charge_at_start`. The Sessions tab is restructured: cross-session widgets + picker stay top-left, the replay map goes top-right, all per-session detail cards go below a visibility-gated divider.

**Tech Stack:** Home Assistant 2026.x core, custom integration `dreame_a2_mower`, pytest, apexcharts-card (HACS).

**Spec:** `docs/superpowers/specs/2026-05-15-session-summary-card-design.md`

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/session_card.py` | **Create** | Pure builder `build_picked_session_summary` + label tables + `format_session_label` helper |
| `tests/protocol/test_session_card.py` | **Create** | Unit tests for the builder (golden + edge cases) |
| `tests/protocol/data/sessions/short.json` | **Create** | Real fixture (copied from backfilled `2026-04-26_1777233426_7bff1b02.json`) |
| `tests/protocol/data/sessions/short.expected.json` | **Create** | Golden output for `short.json` |
| `tests/protocol/data/sessions/long_with_recharges.json` | **Create** | Real fixture (copied from `2026-05-13_1778697514_7bff1b02.json`) |
| `tests/protocol/data/sessions/long_with_recharges.expected.json` | **Create** | Golden output |
| `tests/protocol/data/sessions/incomplete.json` | **Create** | Real fixture (copied from `2026-05-10_1778448356_(incompl.json`) |
| `tests/protocol/data/sessions/incomplete.expected.json` | **Create** | Golden output |
| `custom_components/dreame_a2_mower/const.py` | **Modify** | Add `WORK_LOG_PLACEHOLDER` constant |
| `custom_components/dreame_a2_mower/live_map/state.py` | **Modify** | Add `settings_snapshot` field, clear in `begin_session` + `end_session` |
| `custom_components/dreame_a2_mower/coordinator/_core.py` | **Modify** | Add `_picked_session_summary` slot to `__init__` |
| `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` | **Modify** | Capture `settings_snapshot` at session_begin |
| `custom_components/dreame_a2_mower/coordinator/_session.py` | **Modify** | Persist/restore `settings_snapshot`; populate/clear `_picked_session_summary` in `render_work_log_session` |
| `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` | **Modify** | Inject `settings_snapshot` into archive payload |
| `custom_components/dreame_a2_mower/sensor.py` | **Modify** | Add `DreameA2PickedSessionSensor` class + register in setup |
| `custom_components/dreame_a2_mower/select.py` | **Modify** | Use `WORK_LOG_PLACEHOLDER` constant; clear `_picked_session_summary` when placeholder picked; reuse `format_session_label` |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | **Modify** | Add verification record for the new sensor |
| `dashboards/mower/dashboard.yaml` | **Modify** | Restructure Sessions tab |
| `tests/integration/test_picked_session.py` | **Create** | Integration tests for coordinator + select + sensor wiring |
| `tests/protocol/regenerate_session_card_fixtures.py` | **Create** | Maintenance script — regenerate `.expected.json` files when the builder format intentionally changes |

---

### Task 1: Add `settings_snapshot` to LiveMapState

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py`
- Test: `tests/protocol/test_live_map_state.py` (existing or new)

- [ ] **Step 1: Write the failing test**

If `tests/protocol/test_live_map_state.py` doesn't exist, create it. Otherwise add to it. Open file and add at the end:

```python
def test_begin_session_clears_settings_snapshot():
    state = LiveMapState()
    state.settings_snapshot = {"foo": 1}
    state.begin_session(123456)
    assert state.settings_snapshot is None


def test_end_session_clears_settings_snapshot():
    state = LiveMapState()
    state.begin_session(123456)
    state.settings_snapshot = {"foo": 1}
    state.end_session()
    assert state.settings_snapshot is None


def test_settings_snapshot_defaults_none():
    state = LiveMapState()
    assert state.settings_snapshot is None
```

Make sure the test file has `from custom_components.dreame_a2_mower.live_map.state import LiveMapState` at the top.

- [ ] **Step 2: Run tests to confirm failure**

Run: `pytest tests/protocol/test_live_map_state.py -v -k settings_snapshot`

Expected: 3 failures with `AttributeError: 'LiveMapState' object has no attribute 'settings_snapshot'`.

- [ ] **Step 3: Add the field + clear-points in `live_map/state.py`**

Add the field right after `charge_at_start`:

```python
    settings_snapshot: dict[str, Any] | None = None
    """Per-map cloud_state.settings snapshot captured at session_begin.
    Holds the settings that were in effect when the session started
    (edgemaster, edge_walk_mode, mowing_height_mm, etc.) so the
    archive carries an authoritative view independent of the current
    cloud state. None for pre-v1.0.13a1 archives."""
```

And add `from typing import Any` to imports at the top if not already there. Update `begin_session` to clear:

```python
    def begin_session(self, started_unix: int) -> None:
        """Start a new session; clears any in-memory residue."""
        self.started_unix = started_unix
        self.legs = [[]]
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None
        self.settings_snapshot = None
```

Update `end_session` similarly:

```python
    def end_session(self) -> None:
        self.started_unix = None
        self.legs = []
        self.last_telemetry_unix = None
        self.wifi_samples = []
        self.battery_samples = []
        self.charging_status_samples = []
        self.state_samples = []
        self.error_samples = []
        self.charge_at_start = None
        self.settings_snapshot = None
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `pytest tests/protocol/test_live_map_state.py -v -k settings_snapshot`

Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/protocol/test_live_map_state.py
git commit -m "LiveMapState: add settings_snapshot field"
```

---

### Task 2: Capture settings_snapshot at session_begin in MQTT handler

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py:_on_state_update`
- Test: `tests/integration/test_coordinator.py` (existing — add a test)

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_coordinator.py` (find the section with `_on_state_update` tests, or append at the end):

```python
def test_on_state_update_captures_settings_snapshot_at_session_begin():
    """When task_state_code transitions idle → running, the coordinator
    copies cloud_state.settings.by_map_id_canonical[active_map_id]
    into live_map.settings_snapshot."""
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, SettingsState,
    )

    coord = _make_coord()  # existing helper in this test file
    coord._active_map_id = 0
    coord.cloud_state = CloudState(
        settings=SettingsState(
            raw_settings={},
            by_map_id_canonical={
                0: {
                    "settings_edgemaster": True,
                    "settings_mowing_height_mm": 30,
                    "settings_obstacle_avoidance_ai": False,
                }
            },
        ),
    )
    coord._prev_task_state = None  # idle
    coord.data = MowerState(battery_level=87)

    new_state = MowerState(task_state_code=0, battery_level=87)
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    coord._on_state_update(new_state, now_unix=1700000000)

    assert coord.live_map.settings_snapshot == {
        "settings_edgemaster": True,
        "settings_mowing_height_mm": 30,
        "settings_obstacle_avoidance_ai": False,
    }


def test_on_state_update_settings_snapshot_none_when_cloud_state_missing():
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord = _make_coord()
    coord._active_map_id = 0
    coord.cloud_state = None
    coord._prev_task_state = None
    coord.data = MowerState()

    new_state = MowerState(task_state_code=0)
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    coord._on_state_update(new_state, now_unix=1700000000)

    assert coord.live_map.settings_snapshot is None
```

Note: `_make_coord` is the existing helper in `test_coordinator.py`. If your test framework uses a different fixture, adapt the prelude lines to match. If `SettingsState` field names differ, adjust to whatever `cloud_state.SettingsState` actually exports — see `custom_components/dreame_a2_mower/cloud_state.py` for the real shape and use that.

- [ ] **Step 2: Run tests to confirm failure**

Run: `pytest tests/integration/test_coordinator.py -v -k settings_snapshot`

Expected: 2 failures with `AssertionError: None != {...}`.

- [ ] **Step 3: Modify `_on_state_update` in `_mqtt_handlers.py`**

Find the existing begin_session block (around lines 256-280 of `_mqtt_handlers.py`):

```python
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # ...
            self.live_map.begin_session(now_unix)
            # Snapshot battery % at session start ...
            if new_state.battery_level is not None:
                try:
                    self.live_map.charge_at_start = int(new_state.battery_level)
                except (TypeError, ValueError):
                    pass
```

Append the settings_snapshot capture right after `charge_at_start`:

```python
            # Snapshot the per-map cloud-state settings in effect at
            # session start so the archive carries an authoritative
            # view of edgemaster / edge_walk / obstacle-avoidance /
            # mowing_height etc., independent of the live cloud_state
            # which can change mid-mow.
            cloud_state = getattr(self, "cloud_state", None)
            active_map = getattr(self, "_active_map_id", None)
            if cloud_state is not None and active_map is not None:
                settings = getattr(cloud_state, "settings", None)
                per_map = (
                    getattr(settings, "by_map_id_canonical", {}).get(int(active_map))
                    if settings is not None
                    else None
                )
                if isinstance(per_map, dict):
                    self.live_map.settings_snapshot = dict(per_map)
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `pytest tests/integration/test_coordinator.py -v -k settings_snapshot`

Expected: 2 passes.

- [ ] **Step 5: Confirm no regressions**

Run: `pytest tests/integration/test_coordinator.py -q`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/integration/test_coordinator.py
git commit -m "coordinator: capture cloud_state settings at session_begin"
```

---

### Task 3: Persist + restore settings_snapshot in in_progress.json

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` — `_persist_in_progress` (~lines 670-700) and `_restore_in_progress` (~lines 615)
- Test: `tests/integration/test_coordinator.py` or a sister test file. Use existing `test_persist_in_progress*` test patterns.

- [ ] **Step 1: Write the failing tests**

Append to the existing test file (after the persist_in_progress tests already there):

```python
async def test_persist_in_progress_includes_settings_snapshot(tmp_path):
    coord = _make_coord_with_archive(tmp_path)  # existing helper
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = {"settings_edgemaster": True}
    coord._live_map_dirty = True

    await coord._persist_in_progress(None)

    import json
    blob = json.loads((tmp_path / "sessions" / "in_progress.json").read_text())
    assert blob["settings_snapshot"] == {"settings_edgemaster": True}


async def test_restore_in_progress_rehydrates_settings_snapshot(tmp_path):
    coord = _make_coord_with_archive(tmp_path)
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    import json
    (tmp_path / "sessions" / "in_progress.json").write_text(json.dumps({
        "session_start_ts": 1700000000,
        "legs": [[]],
        "wifi_samples": [],
        "battery_samples": [],
        "charging_status_samples": [],
        "state_samples": [],
        "error_samples": [],
        "charge_at_start": 87,
        "settings_snapshot": {"settings_edgemaster": True, "settings_mowing_height_mm": 30},
        "area_mowed_m2": 0,
        "map_area_m2": 0,
    }))

    await coord._restore_in_progress()

    assert coord.live_map.settings_snapshot == {
        "settings_edgemaster": True,
        "settings_mowing_height_mm": 30,
    }


async def test_restore_in_progress_missing_settings_snapshot_legacy(tmp_path):
    """Legacy in_progress.json without settings_snapshot → field stays None."""
    coord = _make_coord_with_archive(tmp_path)
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    import json
    (tmp_path / "sessions" / "in_progress.json").write_text(json.dumps({
        "session_start_ts": 1700000000,
        "legs": [[]],
    }))

    await coord._restore_in_progress()

    assert coord.live_map.settings_snapshot is None
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `pytest tests/integration/test_coordinator.py -v -k settings_snapshot`

Expected: 3 new failures (KeyError on `settings_snapshot` in persisted blob, or AttributeError if helper doesn't exist).

- [ ] **Step 3: Modify `_persist_in_progress` payload**

In `coordinator/_session.py`, find the `payload` dict in `_persist_in_progress` (~line 670). Add `settings_snapshot` next to `charge_at_start`:

```python
        payload: dict[str, Any] = {
            "session_start_ts": self.live_map.started_unix,
            "legs": [list(list(pt) for pt in leg) for leg in self.live_map.legs],
            "wifi_samples": [list(s) for s in self.live_map.wifi_samples],
            "battery_samples": [list(s) for s in self.live_map.battery_samples],
            "charging_status_samples": [
                list(s) for s in self.live_map.charging_status_samples
            ],
            "state_samples": [list(s) for s in self.live_map.state_samples],
            "error_samples": [list(s) for s in self.live_map.error_samples],
            "charge_at_start": self.live_map.charge_at_start,
            "settings_snapshot": self.live_map.settings_snapshot,
            "area_mowed_m2": self.data.area_mowed_m2 or 0.0,
            "map_area_m2": 0,
        }
```

- [ ] **Step 4: Modify `_restore_in_progress`**

In the same file, find the restore section that re-hydrates samples (~line 590). After the `charge_at_start` block, add:

```python
        raw_settings = data.get("settings_snapshot")
        settings_snapshot: dict[str, Any] | None = (
            dict(raw_settings) if isinstance(raw_settings, dict) else None
        )
```

Then in the "Populate LiveMapState" block immediately below, add:

```python
        self.live_map.settings_snapshot = settings_snapshot
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `pytest tests/integration/test_coordinator.py -v -k settings_snapshot`

Expected: 5 passes (2 from Task 2 + 3 here).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py tests/integration/test_coordinator.py
git commit -m "coordinator: persist + restore settings_snapshot in in_progress.json"
```

---

### Task 4: Inject settings_snapshot into archive payload

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` — `_do_oss_fetch` (after the `charge_at_start` injection added in v1.0.12a2)
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` — FINALIZE_INCOMPLETE path in `_run_finalize_incomplete` (after `charge_at_start` injection)
- Test: same test files as above.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_coordinator.py`:

```python
async def test_do_oss_fetch_includes_settings_snapshot_in_raw_dict(tmp_path):
    """_do_oss_fetch injects live_map.settings_snapshot into raw_dict
    before parse_session_summary + archive."""
    coord = _make_coord_with_archive(tmp_path)
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = {"settings_edgemaster": True}

    captured = {}

    async def fake_archive(summary, raw_dict, map_id):
        captured["raw_dict"] = raw_dict
        return None

    coord.session_archive.archive = lambda *a, **k: None  # sync fallback
    coord.hass.async_add_executor_job = lambda fn, *a: fake_archive(*a) if fn.__name__ == "archive" else fn(*a)
    # Stub the cloud-OSS fetch to return a minimal valid summary blob:
    coord._fetch_oss_session_summary = lambda obj_name: {
        "start": 1700000000, "end": 1700001000, "time": 16, "areas": 50.0,
        "md5": "abc", "map_area": 100, "map": [], "obstacle": [],
        "trajectory": [], "pref": [30, 1], "region_status": [],
        "faults": [], "spot": [], "ai_obstacle": [], "dock": [0, 0, 0],
        "mode": 102, "result": 1, "stop_reason": -1, "start_mode": 1,
        "pre_type": 0,
    }

    await coord._do_oss_fetch("test_object")

    assert captured["raw_dict"]["settings_snapshot"] == {"settings_edgemaster": True}
```

Note: the exact way to invoke `_do_oss_fetch` depends on the test harness. If the stub is too involved, use a simpler approach: extract the "inject samples into raw_dict" sub-block of `_do_oss_fetch` into a helper `_inject_live_map_into_raw_dict(raw_dict)` and unit-test that helper directly. The plan continues assuming the helper extraction.

- [ ] **Step 2: Extract helper in `_lidar_oss.py`**

Find the block in `_do_oss_fetch` (right after the cloud-OSS fetch result, where `raw_dict["_local_legs"]`, `raw_dict["wifi_samples"]`, `raw_dict["battery_samples"]`, etc. get assigned — currently lines ~360-395). Move that into a new method:

```python
    def _inject_live_map_into_raw_dict(self, raw_dict: dict[str, Any]) -> None:
        """Add LiveMapState-tracked fields to a cloud-OSS raw_dict before archive.

        Mutates raw_dict in place. Called from _do_oss_fetch and from the
        FINALIZE_INCOMPLETE path.
        """
        if self.live_map.legs and any(self.live_map.legs):
            raw_dict["_local_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg in self.live_map.legs
                if leg
            ]
        if self.live_map.wifi_samples:
            raw_dict["wifi_samples"] = [
                [float(x), float(y), int(r), int(t)]
                for (x, y, r, t) in self.live_map.wifi_samples
            ]
        if self.live_map.battery_samples:
            raw_dict["battery_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.battery_samples
            ]
        if self.live_map.charging_status_samples:
            raw_dict["charging_status_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.charging_status_samples
            ]
        if self.live_map.state_samples:
            raw_dict["state_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.state_samples
            ]
        if self.live_map.error_samples:
            raw_dict["error_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.error_samples
            ]
        if self.live_map.charge_at_start is not None:
            raw_dict["charge_at_start"] = int(self.live_map.charge_at_start)
        if self.live_map.settings_snapshot is not None:
            raw_dict["settings_snapshot"] = dict(self.live_map.settings_snapshot)
```

Replace the inline block in `_do_oss_fetch` with a single call:

```python
        self._inject_live_map_into_raw_dict(raw_dict)
```

- [ ] **Step 3: Update the FINALIZE_INCOMPLETE path in `_session.py`**

Find `_run_finalize_incomplete` and the existing block that copies wifi/battery/etc into `incomplete_payload`. Replace that block with:

```python
        self._inject_live_map_into_raw_dict(incomplete_payload)
```

(The helper now lives on `_LidarOssMixin`; coordinator inherits from it so `self.` resolves it via MRO.)

- [ ] **Step 4: Replace the failing test with a direct helper test**

Since the helper now exists, rewrite the test from Step 1:

```python
def test_inject_live_map_settings_snapshot():
    coord = _make_coord()  # synchronous helper
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = {"settings_edgemaster": True}
    coord.live_map.charge_at_start = 87
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert raw["settings_snapshot"] == {"settings_edgemaster": True}
    assert raw["charge_at_start"] == 87


def test_inject_live_map_settings_snapshot_none_skipped():
    coord = _make_coord()
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = None
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert "settings_snapshot" not in raw
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_coordinator.py -v -k inject_live_map`

Expected: 2 passes.

Run: `pytest -q` for the full sweep.

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py custom_components/dreame_a2_mower/coordinator/_session.py tests/integration/test_coordinator.py
git commit -m "coordinator: extract _inject_live_map_into_raw_dict + inject settings_snapshot"
```

---

### Task 5: Copy real backfilled JSONs into test fixtures

**Files:**
- Create: `tests/protocol/data/sessions/short.json`
- Create: `tests/protocol/data/sessions/long_with_recharges.json`
- Create: `tests/protocol/data/sessions/incomplete.json`

- [ ] **Step 1: Make the fixtures directory**

Run: `mkdir -p tests/protocol/data/sessions`

- [ ] **Step 2: Copy backfilled archives + rename**

```bash
cp /tmp/session_backfill/2026-04-26_1777233426_7bff1b02.json tests/protocol/data/sessions/short.json
cp /tmp/session_backfill/2026-05-13_1778697514_7bff1b02.json tests/protocol/data/sessions/long_with_recharges.json
cp '/tmp/session_backfill/2026-05-10_1778448356_(incompl.json' tests/protocol/data/sessions/incomplete.json
```

- [ ] **Step 3: Verify they're valid JSON and present the expected backfill fields**

Run:

```bash
python3 -c '
import json, glob
for p in sorted(glob.glob("tests/protocol/data/sessions/*.json")):
    d = json.load(open(p))
    print(p, "battery=", len(d.get("battery_samples", [])), "duration=", d.get("time"))
'
```

Expected: 3 lines, each with battery>0 and duration > 0 (short: ~7, long: 278, incomplete: ~88).

- [ ] **Step 4: Commit**

```bash
git add tests/protocol/data/sessions/
git commit -m "tests: add 3 backfilled session fixtures for session_card tests"
```

---

### Task 6: Create `session_card.py` skeleton + `format_session_label`

**Files:**
- Create: `custom_components/dreame_a2_mower/session_card.py`
- Create: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_session_card.py`:

```python
"""Unit tests for session_card.build_picked_session_summary + helpers."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
    format_session_label,
)
from custom_components.dreame_a2_mower.protocol import session_summary as _ss


FIXTURE_DIR = Path(__file__).parent / "data" / "sessions"


def _load_session(name: str) -> tuple[dict, _ss.SessionSummary, SimpleNamespace]:
    raw = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    summary = _ss.parse_session_summary(raw)
    entry = SimpleNamespace(
        md5=raw.get("md5"),
        filename=f"{name}.json",
        map_id=0,
        start_ts=raw["start"],
        end_ts=raw["end"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
    )
    return raw, summary, entry


def test_format_session_label_mowing():
    entry = SimpleNamespace(
        end_ts=1778697514,
        map_id=0,
        area_mowed_m2=285.3,
        duration_min=278,
        md5="abc",
        local_trail_complete=True,
        still_running=False,
    )
    label = format_session_label(entry)
    assert label.startswith("[Mowing] [Map 1] ")
    assert "285.3 m² / 278min" in label


def test_format_session_label_partial_trail():
    entry = SimpleNamespace(
        end_ts=1778697514,
        map_id=0,
        area_mowed_m2=10.0,
        duration_min=5,
        md5="abc",
        local_trail_complete=False,
        still_running=False,
    )
    label = format_session_label(entry)
    assert label.startswith("⚠ ")
    assert "(partial trail)" in label
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/protocol/test_session_card.py -v`

Expected: ImportError or NameError — module doesn't exist.

- [ ] **Step 3: Create `session_card.py` with the formatter**

Write `custom_components/dreame_a2_mower/session_card.py`:

```python
"""Picked-session summary builder.

Pure derivation: takes a raw archive dict + parsed SessionSummary +
ArchivedSession-like metadata, returns a flat dict of attributes the
dashboard cards consume. No HA / coordinator imports — fully unit-
testable in isolation.

Spec: docs/superpowers/specs/2026-05-15-session-summary-card-design.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def format_session_label(entry: Any) -> str:
    """Build a picker label matching DreameA2WorkLogSelect's format.

    Single source of truth — the select entity and the coordinator both
    call this so labels stay aligned. Expects entry to have:
    end_ts (int), map_id (int), area_mowed_m2 (float), duration_min (int),
    optionally md5, local_trail_complete, still_running.
    """
    try:
        ts_str = datetime.fromtimestamp(int(entry.end_ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        ts_str = "??"
    map_id = getattr(entry, "map_id", -1)
    map_prefix = "[Map ?]" if map_id == -1 else f"[Map {map_id + 1}]"
    base = (
        f"[Mowing] {map_prefix} {ts_str}"
        f" — {entry.area_mowed_m2:.1f} m² / {entry.duration_min}min"
    )
    if not getattr(entry, "local_trail_complete", True):
        return f"⚠ {base} (partial trail)"
    return base


def build_picked_session_summary(
    raw_dict: dict[str, Any],
    summary: Any,  # SessionSummary
    entry: Any,   # ArchivedSession
    picker_label: str,
) -> dict[str, Any]:
    """Compute the flat attribute dict for sensor.picked_session.

    The dict is what extra_state_attributes returns; every key is
    rendered to a card field. See spec § Attribute schema for the
    full list. Future fields go alongside; pure-additive growth is
    safe.
    """
    out: dict[str, Any] = {
        "label": picker_label,
        "md5": getattr(entry, "md5", None),
        "filename": getattr(entry, "filename", None),
        "map_id": getattr(entry, "map_id", None),
    }
    return out
```

- [ ] **Step 4: Refactor `DreameA2WorkLogSelect._build_options_from_sessions` to use it**

In `custom_components/dreame_a2_mower/select.py`, replace the inline label-building loop with a call to `format_session_label`:

```python
    def _build_options_from_sessions(self, sessions: list) -> tuple[list[str], dict[str, str]]:
        """Pure formatter — no I/O.

        Filters out still_running entries (in-progress lives on Main view).
        """
        from .session_card import format_session_label

        eligible = [s for s in sessions if not getattr(s, "still_running", False)]
        eligible = sorted(eligible, key=lambda s: s.end_ts, reverse=True)[: self._max_options]
        labels: list[str] = [self._placeholder]
        mapping: dict[str, str] = {}
        for s in eligible:
            label = format_session_label(s)
            if label in mapping:
                label = f"{label} [{(getattr(s, 'md5', '') or '')[:6]}]"
            labels.append(label)
            mapping[label] = s.filename or s.md5
        return labels, mapping
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `pytest tests/protocol/test_session_card.py tests/integration/test_per_map_entity_names.py -v`

Expected: both new test_format_* pass; existing select-related tests still pass (label format is unchanged).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py custom_components/dreame_a2_mower/select.py tests/protocol/test_session_card.py
git commit -m "session_card: new module + format_session_label, used by work_log select"
```

---

### Task 7: Identity & outcome attribute group

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
def test_build_identity_outcome_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "label-x")

    assert result["label"] == "label-x"
    assert result["md5"] == raw["md5"]
    assert result["filename"] == "long_with_recharges.json"
    assert result["started_at_unix"] == raw["start"]
    assert result["ended_at_unix"] == raw["end"]
    assert result["duration_min"] == raw["time"]
    assert result["mode_raw"] == raw["mode"]
    assert result["pre_type_raw"] == raw["pre_type"]
    assert result["start_mode_raw"] == raw["start_mode"]
    assert result["result_raw"] == raw["result"]
    assert result["stop_reason_raw"] == raw["stop_reason"]
    # Completed when result == 1 AND stop_reason in {-1, 0}
    assert result["completed"] == (raw["result"] == 1 and raw["stop_reason"] in (-1, 0))
    # Labels exist (whether resolved or "raw=N" depends on the table)
    assert isinstance(result["mode_label"], str)
    assert isinstance(result["stop_reason_label"], str)
    assert isinstance(result["result_label"], str)


def test_build_identity_outcome_incomplete():
    raw, summary, entry = _load_session("incomplete")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    # md5 is "(incomplete)" for these
    assert result["md5"] == "(incomplete)"
    assert result["completed"] is False
    assert "Incomplete" in result["result_label"]


def test_started_at_ends_with_tz_marker():
    """started_at is local-format ISO; assert minute precision and shape."""
    raw, summary, entry = _load_session("short")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    # Format: YYYY-MM-DD HH:MM (no seconds, no TZ — keep simple for cards)
    assert len(result["started_at"]) == 16
    assert result["started_at"][4] == "-" and result["started_at"][7] == "-"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/protocol/test_session_card.py -v -k identity_outcome -k started_at`

Expected: KeyError / AttributeError on missing keys.

- [ ] **Step 3: Implement the identity & outcome group in `session_card.py`**

Replace the body of `build_picked_session_summary` with:

```python
MODE_LABELS: dict[int, str] = {
    102: "All areas",
}
"""Best-effort mode-enum labels. Unmapped values render as raw=N."""

PRE_TYPE_LABELS: dict[int, str] = {
    0: "Default",
}

START_MODE_LABELS: dict[int, str] = {
    0: "Schedule",
    1: "Manual (app)",
}

STOP_REASON_LABELS: dict[int, str] = {
    -1: "Natural end",
    0: "Natural end",
}

EFFICIENCY_LABELS: dict[int, str] = {
    0: "Eco",
    1: "Standard",
    2: "High",
}


def _label(table: dict[int, str], value: Any) -> str:
    if value is None:
        return "—"
    try:
        v = int(value)
    except (TypeError, ValueError):
        return f"raw={value!r}"
    return table.get(v, f"raw={v}")


def build_picked_session_summary(
    raw_dict: dict[str, Any],
    summary: Any,
    entry: Any,
    picker_label: str,
) -> dict[str, Any]:
    md5 = getattr(entry, "md5", None) or raw_dict.get("md5")

    # Identity & outcome
    out: dict[str, Any] = {
        "label": picker_label,
        "md5": md5,
        "filename": getattr(entry, "filename", None),
        "map_id": getattr(entry, "map_id", None),
        "started_at_unix": summary.start_ts,
        "ended_at_unix": summary.end_ts,
        "started_at": datetime.fromtimestamp(summary.start_ts).strftime("%Y-%m-%d %H:%M"),
        "ended_at": datetime.fromtimestamp(summary.end_ts).strftime("%Y-%m-%d %H:%M"),
        "duration_min": summary.duration_min,
        "mode_raw": summary.mode,
        "mode_label": _label(MODE_LABELS, summary.mode),
        "pre_type_raw": summary.pre_type,
        "pre_type_label": _label(PRE_TYPE_LABELS, summary.pre_type),
        "start_mode_raw": summary.start_mode,
        "start_mode_label": _label(START_MODE_LABELS, summary.start_mode),
        "result_raw": summary.result,
        "stop_reason_raw": summary.stop_reason,
    }

    # Incomplete entries get a special result label.
    if md5 == "(incomplete)":
        out["result_label"] = "Incomplete"
        out["completed"] = False
    else:
        out["result_label"] = "Completed" if summary.result == 1 else _label({}, summary.result)
        out["completed"] = (summary.result == 1 and summary.stop_reason in (-1, 0))

    out["stop_reason_label"] = _label(STOP_REASON_LABELS, summary.stop_reason)

    return out
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `pytest tests/protocol/test_session_card.py -v`

Expected: all green so far.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: identity + outcome attribute group"
```

---

### Task 8: Coverage & efficiency attribute group

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
def test_coverage_efficiency_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    assert result["area_mowed_m2"] == pytest.approx(raw["areas"], rel=1e-3)
    assert result["map_area_m2"] == raw["map_area"]
    if raw["map_area"]:
        assert result["coverage_pct"] == pytest.approx(
            raw["areas"] / raw["map_area"] * 100, rel=1e-3
        )
    else:
        assert result["coverage_pct"] is None
    assert result["mowing_height_mm"] == raw["pref"][0]
    assert result["mowing_efficiency_raw"] == raw["pref"][1]
    assert result["mowing_efficiency_label"] in ("Eco", "Standard", "High")
    # m2_per_min: area / duration; m2_per_pct: area / charge_used
    if raw["time"]:
        assert result["m2_per_min"] == pytest.approx(raw["areas"] / raw["time"], rel=1e-3)
    # distance_m: from _local_legs (sum of pairwise euclidean)
    assert result["distance_m"] > 0


def test_coverage_zero_map_area():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["map_area"] = 0
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["coverage_pct"] is None


def test_coverage_zero_duration():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["time"] = 0
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["m2_per_min"] is None


def test_distance_falls_back_to_track_segments():
    """When _local_legs is absent, distance_m comes from summary.track_segments."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut.pop("_local_legs", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    # As long as either source has data, result is a number. May be 0 if
    # both empty — accept any non-negative number.
    assert result["distance_m"] >= 0
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/protocol/test_session_card.py -v -k coverage -k distance`

Expected: KeyError on missing keys.

- [ ] **Step 3: Implement**

Insert into `build_picked_session_summary` after the identity block:

```python
    # Coverage & efficiency
    area = summary.area_mowed_m2 or 0.0
    map_area = summary.map_area_m2 or 0
    duration = summary.duration_min or 0
    out["area_mowed_m2"] = area
    out["map_area_m2"] = map_area
    out["coverage_pct"] = (area / map_area * 100) if map_area else None

    pref = list(summary.pref) if summary.pref else []
    out["mowing_height_mm"] = pref[0] if len(pref) >= 1 else None
    eff = pref[1] if len(pref) >= 2 else None
    out["mowing_efficiency_raw"] = eff
    out["mowing_efficiency_label"] = _label(EFFICIENCY_LABELS, eff)

    out["distance_m"] = _compute_distance_m(raw_dict, summary)

    out["m2_per_min"] = (area / duration) if duration else None
    # m2_per_pct is computed in Task 9 once charge_used_pct is available.
    # Set None placeholder here; Task 9 overwrites.
    out["m2_per_pct"] = None
```

And add the helper at module level:

```python
def _compute_distance_m(raw_dict: dict[str, Any], summary: Any) -> float:
    """Sum of pairwise euclidean over _local_legs (fallback to summary track)."""
    from math import hypot

    legs = raw_dict.get("_local_legs") or []
    if not legs:
        legs = [list(seg) for seg in summary.track_segments]
    total = 0.0
    for leg in legs:
        for i in range(1, len(leg)):
            ax, ay = leg[i - 1][0], leg[i - 1][1]
            bx, by = leg[i][0], leg[i][1]
            total += hypot(bx - ax, by - ay)
    return total
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/protocol/test_session_card.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: coverage + efficiency attribute group"
```

---

### Task 9: Energy & time-breakdown attribute group

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_energy_long_session_with_recharges():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    bs = raw["battery_samples"]
    assert result["charge_at_start_pct"] == raw["charge_at_start"]
    assert result["charge_at_end_pct"] == bs[-1][1]
    assert result["charge_min_pct"] == min(v for _, v in bs)
    # Long session has mid-mow recharges in charging_status_samples
    assert result["recharge_count"] >= 1
    assert isinstance(result["time_charging_min"], int)
    assert isinstance(result["time_mowing_min"], int)
    assert isinstance(result["time_other_min"], int)
    # All three should be non-negative
    assert result["time_charging_min"] >= 0
    assert result["time_mowing_min"] >= 0
    assert result["time_other_min"] >= 0
    # battery_samples passthrough
    assert result["battery_samples"] == bs


def test_energy_no_battery_samples():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["battery_samples"] = []
    raw_mut.pop("charge_at_start", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["charge_at_start_pct"] is None
    assert result["charge_at_end_pct"] is None
    assert result["charge_min_pct"] is None
    assert result["charge_used_pct"] == 0
    assert result["m2_per_pct"] is None


def test_energy_recharge_count_counts_zero_to_one_transitions():
    """charging_status_samples=[0,1,0,1,0] → 2 recharges."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["charging_status_samples"] = [
        [1000, 0], [1100, 1], [1200, 0], [1300, 1], [1400, 0],
    ]
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["recharge_count"] == 2


def test_energy_classify_intervals_empty_state_samples():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["state_samples"] = []
    raw_mut["charging_status_samples"] = []
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["time_mowing_min"] is None
    assert result["time_charging_min"] is None
    assert result["time_other_min"] is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/protocol/test_session_card.py -v -k energy`

Expected: KeyError on missing keys.

- [ ] **Step 3: Implement the energy block in `session_card.py`**

Add module-level constants:

```python
MOWING_STATE_CODES: set[int] = {2, 5}
"""State codes that count as 'mowing' for the time-breakdown.

Best-effort — conservative classification. Verify by checking that
time_mowing + time_charging + time_other ≈ duration_min for a real
session. Update inventory.yaml when a value is wire-confirmed.
"""
```

Insert into `build_picked_session_summary` after the coverage block:

```python
    # Energy & time-breakdown
    bs = list(raw_dict.get("battery_samples") or [])
    cs = list(raw_dict.get("charging_status_samples") or [])
    ss = list(raw_dict.get("state_samples") or [])

    charge_at_start_pct = raw_dict.get("charge_at_start")
    if charge_at_start_pct is None and bs:
        charge_at_start_pct = bs[0][1]
    out["charge_at_start_pct"] = (
        int(charge_at_start_pct) if charge_at_start_pct is not None else None
    )
    out["charge_at_end_pct"] = bs[-1][1] if bs else None
    out["charge_min_pct"] = min(v for _, v in bs) if bs else None
    if out["charge_at_start_pct"] is not None and out["charge_at_end_pct"] is not None:
        out["charge_used_pct"] = max(0, out["charge_at_start_pct"] - out["charge_at_end_pct"])
    else:
        out["charge_used_pct"] = 0
    out["recharge_count"] = sum(
        1 for i in range(1, len(cs)) if cs[i - 1][1] == 0 and cs[i][1] == 1
    )

    mow_min, chg_min, other_min = _classify_intervals(
        ss, cs, summary.start_ts, summary.end_ts
    )
    out["time_mowing_min"] = mow_min
    out["time_charging_min"] = chg_min
    out["time_other_min"] = other_min

    if out["charge_used_pct"] > 0 and area:
        out["m2_per_pct"] = area / out["charge_used_pct"]
    else:
        out["m2_per_pct"] = None

    out["battery_samples"] = bs
```

And add the helper:

```python
def _classify_intervals(
    state_samples: list[list[int]],
    charging_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> tuple[int | None, int | None, int | None]:
    """Step-integrate state + charging_status into (mowing, charging, other) minutes.

    Returns (None, None, None) when state_samples is empty so the card
    distinguishes 'no data' from 'didn't mow'.

    Algorithm: walk the merged timeline of state + charging events,
    for each [t_i, t_{i+1}] interval pick the classification based on
    the most-recent value of each stream. Charging wins over mowing
    when both bits are set (mower can't physically be mowing while
    docked + charging).
    """
    if not state_samples and not charging_samples:
        return (None, None, None)

    # Build event list with type tag.
    events: list[tuple[int, str, int]] = []
    for t, v in state_samples:
        events.append((int(t), "state", int(v)))
    for t, v in charging_samples:
        events.append((int(t), "charging", int(v)))
    events.sort()

    cur_state: int | None = None
    cur_charging: int = 0
    last_t = int(start_ts)
    mow_s = chg_s = other_s = 0

    def _classify(s: int | None, c: int) -> str:
        if c == 1:
            return "charging"
        if s is not None and s in MOWING_STATE_CODES:
            return "mowing"
        return "other"

    for t, kind, v in events:
        dt = max(0, t - last_t)
        cls = _classify(cur_state, cur_charging)
        if cls == "mowing":
            mow_s += dt
        elif cls == "charging":
            chg_s += dt
        else:
            other_s += dt
        if kind == "state":
            cur_state = v
        else:
            cur_charging = v
        last_t = t

    # Tail to end_ts
    dt = max(0, int(end_ts) - last_t)
    cls = _classify(cur_state, cur_charging)
    if cls == "mowing":
        mow_s += dt
    elif cls == "charging":
        chg_s += dt
    else:
        other_s += dt

    return (mow_s // 60, chg_s // 60, other_s // 60)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/protocol/test_session_card.py -v -k energy`

Expected: green.

- [ ] **Step 5: Sanity-check the time decomposition on the long session**

Run:

```bash
python3 -c '
import json
from custom_components.dreame_a2_mower.session_card import build_picked_session_summary
from custom_components.dreame_a2_mower.protocol import session_summary as ss
from types import SimpleNamespace
raw = json.load(open("tests/protocol/data/sessions/long_with_recharges.json"))
summary = ss.parse_session_summary(raw)
entry = SimpleNamespace(md5=raw["md5"], filename="x", map_id=0, end_ts=raw["end"], area_mowed_m2=raw["areas"], duration_min=raw["time"])
r = build_picked_session_summary(raw, summary, entry, "lbl")
print(f"duration={r[\"duration_min\"]}, mow+chg+other={r[\"time_mowing_min\"]+r[\"time_charging_min\"]+r[\"time_other_min\"]}")
print(f"recharges={r[\"recharge_count\"]}, charge_used={r[\"charge_used_pct\"]}, m2/pct={r[\"m2_per_pct\"]:.2f}" if r["m2_per_pct"] else "no charge")
'
```

Expected: `mow + chg + other ≈ duration_min` within a minute or two of rounding. `recharges ≥ 1`. If the sum is wildly off (e.g., 50% short), MOWING_STATE_CODES needs adjustment — drop a note in the spec's "Open questions" section and continue (the tests pass; the labels can be tightened later).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: energy + time-breakdown attribute group"
```

---

### Task 10: Diagnostics + settings_snapshot passthrough

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_diagnostics_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    assert result["fault_count"] == len(raw["faults"])
    assert isinstance(result["faults_compact"], list)
    assert result["obstacle_count"] == len(raw["obstacle"])
    assert result["ai_obstacle_count"] == len(raw["ai_obstacle"])
    assert result["state_transition_count"] == len(raw["state_samples"])
    assert result["error_event_count"] == len(raw["error_samples"])
    expected_error_codes = sorted({v for _, v in raw["error_samples"]})
    assert result["error_codes_seen"] == expected_error_codes


def test_diagnostics_wifi_stats():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    ws = raw.get("wifi_samples") or []
    if ws:
        rssis = [int(s[2]) for s in ws]
        assert result["wifi_rssi_min_dbm"] == min(rssis)
        assert result["wifi_rssi_max_dbm"] == max(rssis)
        assert result["wifi_rssi_avg_dbm"] == round(sum(rssis) / len(rssis))
        assert result["wifi_sample_count"] == len(ws)
        assert result["wifi_samples"] == ws
    else:
        assert result["wifi_rssi_min_dbm"] is None
        assert result["wifi_sample_count"] == 0


def test_settings_snapshot_passthrough():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["settings_snapshot"] = {"settings_edgemaster": True, "settings_mowing_height_mm": 30}
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["settings_snapshot"] == {
        "settings_edgemaster": True, "settings_mowing_height_mm": 30,
    }


def test_settings_snapshot_absent_yields_none():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut.pop("settings_snapshot", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["settings_snapshot"] is None


def test_faults_compact_truncates_to_5():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["faults"] = [{"code": i} for i in range(10)]
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert len(result["faults_compact"]) == 6  # 5 + "+5 more"
    assert result["faults_compact"][-1] == "+5 more"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/protocol/test_session_card.py -v -k diagnostics -k wifi -k settings_snapshot -k faults`

Expected: KeyError on missing keys.

- [ ] **Step 3: Implement**

Append to `build_picked_session_summary` body, after the energy block:

```python
    # Diagnostics
    out["fault_count"] = len(summary.faults)
    faults_compact = [str(f) for f in summary.faults[:5]]
    if len(summary.faults) > 5:
        faults_compact.append(f"+{len(summary.faults) - 5} more")
    out["faults_compact"] = faults_compact
    out["obstacle_count"] = len(summary.obstacles)
    out["ai_obstacle_count"] = len(summary.ai_obstacle)
    out["state_transition_count"] = len(ss)
    err_samples = list(raw_dict.get("error_samples") or [])
    out["error_event_count"] = len(err_samples)
    out["error_codes_seen"] = sorted({int(v) for _, v in err_samples})

    ws = list(raw_dict.get("wifi_samples") or [])
    if ws:
        rssis = [int(s[2]) for s in ws]
        out["wifi_rssi_min_dbm"] = min(rssis)
        out["wifi_rssi_max_dbm"] = max(rssis)
        out["wifi_rssi_avg_dbm"] = round(sum(rssis) / len(rssis))
    else:
        out["wifi_rssi_min_dbm"] = None
        out["wifi_rssi_max_dbm"] = None
        out["wifi_rssi_avg_dbm"] = None
    out["wifi_sample_count"] = len(ws)
    out["wifi_samples"] = ws

    # Settings snapshot passthrough
    snapshot = raw_dict.get("settings_snapshot")
    out["settings_snapshot"] = (
        dict(snapshot) if isinstance(snapshot, dict) else None
    )

    return out
```

- [ ] **Step 4: Run all session_card tests**

Run: `pytest tests/protocol/test_session_card.py -v`

Expected: green.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`

Expected: all 1325+ pre-existing tests + new ones pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: diagnostics + settings_snapshot passthrough"
```

---

### Task 11: Add WORK_LOG_PLACEHOLDER constant

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`
- Modify: `custom_components/dreame_a2_mower/select.py`
- Test: existing `tests/integration/test_per_map_entity_names.py` or sibling — add a constant-consistency check.

- [ ] **Step 1: Write the failing test**

Append to a relevant test file (e.g. `tests/integration/test_devices_helpers.py`):

```python
def test_work_log_placeholder_constant_matches_select():
    from custom_components.dreame_a2_mower.const import WORK_LOG_PLACEHOLDER
    from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect

    assert DreameA2WorkLogSelect._placeholder == WORK_LOG_PLACEHOLDER
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/integration/test_devices_helpers.py -v -k work_log_placeholder`

Expected: `ImportError: cannot import name 'WORK_LOG_PLACEHOLDER'`.

- [ ] **Step 3: Add the constant**

In `custom_components/dreame_a2_mower/const.py`, add near the top with the other string constants:

```python
WORK_LOG_PLACEHOLDER: str = "(pick a session)"
```

Note the exact string matches the existing `_placeholder` in the select class.

- [ ] **Step 4: Use it in `select.py`**

Find the class:

```python
class DreameA2WorkLogSelect(...):
    _placeholder: str = "(pick a session)"
```

Change to:

```python
from .const import WORK_LOG_PLACEHOLDER

class DreameA2WorkLogSelect(...):
    _placeholder: str = WORK_LOG_PLACEHOLDER
```

(If `const` is already imported, just add `WORK_LOG_PLACEHOLDER` to the existing import line.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_devices_helpers.py -v -k work_log_placeholder`

Expected: pass.

Run: `pytest -q` for the full sweep.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/select.py tests/integration/test_devices_helpers.py
git commit -m "const: extract WORK_LOG_PLACEHOLDER, used by work_log select"
```

---

### Task 12: Add `_picked_session_summary` slot to coordinator

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py`

- [ ] **Step 1: Locate `_CoreMixin.__init__`**

Open `coordinator/_core.py`. Find `class _CoreMixin:` and inside `__init__` the cluster of `self._foo = ...` assignments near `_work_log_png`.

- [ ] **Step 2: Add the slot**

Add right after `self._work_log_png: bytes | None = None`:

```python
        self._picked_session_summary: dict[str, Any] | None = None
        """Flat attribute dict for sensor.dreame_a2_mower_picked_session.
        Set by render_work_log_session; cleared by the work_log select
        when the placeholder is picked."""
```

If `Any` isn't already imported, add it to the `typing` import at the top of the file.

- [ ] **Step 3: Run any coordinator-init tests to confirm nothing broke**

Run: `pytest tests/integration/test_coordinator.py -v -k init`

Expected: still green.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py
git commit -m "coordinator: add _picked_session_summary slot"
```

---

### Task 13: Wire builder into render_work_log_session

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py:render_work_log_session`
- Test: `tests/integration/test_picked_session.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_picked_session.py`:

```python
"""Integration tests for sensor.dreame_a2_mower_picked_session wiring."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the existing coordinator-test fixtures.
from tests.integration.test_coordinator import _make_coord  # type: ignore


FIXTURE_DIR = Path("tests/protocol/data/sessions")


@pytest.mark.asyncio
async def test_render_work_log_session_populates_picked_summary():
    coord = _make_coord()
    raw = json.loads((FIXTURE_DIR / "short.json").read_text())

    entry = SimpleNamespace(
        md5=raw["md5"],
        filename="short.json",
        map_id=0,
        end_ts=raw["end"],
        start_ts=raw["start"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
        local_trail_complete=True,
        still_running=False,
    )

    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[entry])
    coord.session_archive.load = MagicMock(return_value=raw)
    coord.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    coord._cached_maps_by_id = {0: SimpleNamespace()}
    # Stub render_work_log so we don't need PIL
    import custom_components.dreame_a2_mower.coordinator._session as sess_mod
    sess_mod.render_work_log = lambda *a, **k: b"png"

    await coord.render_work_log_session("short.json")

    assert coord._picked_session_summary is not None
    assert coord._picked_session_summary["filename"] == "short.json"
    assert coord._picked_session_summary["label"].startswith("[Mowing]")
    assert "duration_min" in coord._picked_session_summary
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/integration/test_picked_session.py -v`

Expected: AssertionError — `_picked_session_summary` is still None after the call.

- [ ] **Step 3: Wire the builder into `render_work_log_session`**

In `coordinator/_session.py`, find `render_work_log_session`. After the `parse_session_summary` block but BEFORE the PNG render call, add:

```python
        from ..session_card import build_picked_session_summary, format_session_label

        try:
            picker_label = format_session_label(entry)
        except Exception:
            picker_label = entry.filename or (entry.md5 or "(unknown)")
        try:
            self._picked_session_summary = build_picked_session_summary(
                raw_dict=raw_dict,
                summary=summary,
                entry=entry,
                picker_label=picker_label,
            )
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: build_picked_session_summary failed "
                "for filename=%s — clearing picked_session", getattr(entry, "filename", "?")
            )
            self._picked_session_summary = None
```

After the existing `self._work_log_png = png` assignment, ping listeners (the existing path already does this if `render_work_log` returns; verify there is an `async_update_listeners()` call — add one if not, so the sensor refreshes too).

- [ ] **Step 4: Run tests to confirm pass**

Run: `pytest tests/integration/test_picked_session.py -v`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py tests/integration/test_picked_session.py
git commit -m "coordinator: populate _picked_session_summary from render_work_log_session"
```

---

### Task 14: Clear picked summary when placeholder is picked

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py` — `DreameA2WorkLogSelect.async_select_option`
- Modify: `tests/integration/test_picked_session.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_picked_session.py`:

```python
@pytest.mark.asyncio
async def test_placeholder_pick_clears_picked_summary():
    from custom_components.dreame_a2_mower.const import WORK_LOG_PLACEHOLDER
    from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect

    coord = _make_coord()
    coord._picked_session_summary = {"label": "old", "md5": "abc"}
    coord._work_log_png = b"old"
    sel = DreameA2WorkLogSelect(coord)
    sel.hass = coord.hass
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option(WORK_LOG_PLACEHOLDER)

    assert coord._work_log_png is None
    assert coord._picked_session_summary is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/integration/test_picked_session.py -v -k placeholder`

Expected: AssertionError — summary still set after placeholder pick.

- [ ] **Step 3: Modify `async_select_option`**

In `select.py`, find the existing placeholder branch:

```python
        if option == self._placeholder:
            # Picking the placeholder clears the work-log camera.
            self.coordinator._work_log_png = None
            update_listeners = getattr(self.coordinator, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()
            self._attr_current_option = self._placeholder
            self.async_write_ha_state()
            return
```

Add the picked-summary clear:

```python
        if option == self._placeholder:
            # Picking the placeholder clears the work-log camera AND the
            # picked-session summary so all per-session cards hide.
            self.coordinator._work_log_png = None
            self.coordinator._picked_session_summary = None
            update_listeners = getattr(self.coordinator, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()
            self._attr_current_option = self._placeholder
            self.async_write_ha_state()
            return
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_picked_session.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py tests/integration/test_picked_session.py
git commit -m "select.work_log: clear _picked_session_summary on placeholder pick"
```

---

### Task 15: Add `DreameA2PickedSessionSensor` entity

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Modify: `tests/integration/test_picked_session.py` (add a sensor smoke-test)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_picked_session.py`:

```python
def test_picked_session_sensor_reflects_coordinator_summary():
    from custom_components.dreame_a2_mower.sensor import DreameA2PickedSessionSensor

    coord = _make_coord()
    coord._picked_session_summary = None
    sensor = DreameA2PickedSessionSensor(coord)

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}

    coord._picked_session_summary = {
        "label": "[Mowing] [Map 1] 2026-05-13 14:00 — 285.3 m² / 278min",
        "duration_min": 278,
    }
    assert sensor.native_value == coord._picked_session_summary["label"]
    assert sensor.extra_state_attributes["duration_min"] == 278
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/integration/test_picked_session.py -v -k sensor`

Expected: ImportError on `DreameA2PickedSessionSensor`.

- [ ] **Step 3: Add the entity class**

In `sensor.py`, near the other class definitions (after `DreameA2WorkLogSelect` peers — pick a sensible spot, e.g. near the existing custom sensor classes):

```python
class DreameA2PickedSessionSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Exposes the picker-selected session as state + attributes.

    State = the picker label (matches the dropdown). Attributes carry
    the full summary dict built by session_card.build_picked_session_summary.
    Used by the Sessions tab's per-session detail cards.
    """

    _attr_has_entity_name = True
    _attr_name = "Picked session"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "picked_session")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        summary = self.coordinator._picked_session_summary
        return summary.get("label") if summary else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator._picked_session_summary or {}
```

If `mower_unique_id` and `mower_device_info` aren't already imported in `sensor.py`, add them from `._devices`. Same for `DreameA2MowerCoordinator` import.

- [ ] **Step 4: Register in `async_setup_entry`**

Find the existing `async_setup_entry` in `sensor.py`. Append the new sensor to the list of entities being added:

```python
    entities.append(DreameA2PickedSessionSensor(coordinator))
```

Place this near the other mower-level sensors (not in the per-map loop).

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_picked_session.py -v -k sensor`

Expected: pass.

Run: `pytest -q`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_picked_session.py
git commit -m "sensor: add DreameA2PickedSessionSensor"
```

---

### Task 16: Update entity-inventory.yaml

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Add the verification record**

Open `custom_components/dreame_a2_mower/entity-inventory.yaml`. Find the section for mower-level sensors (near where `sensor.latest_session_*` entries live, if present — search for `latest_session_area`). If there's no existing entry, append a new one. Schema per CLAUDE.md § Fact discipline:

```yaml
  - id: "sensor_picked_session"
    entity_id: "sensor.dreame_a2_mower_picked_session"
    platform: "sensor"
    device: "mower"  # parent device, not per-map
    source:
      class: "DreameA2PickedSessionSensor"
      file: "custom_components/dreame_a2_mower/sensor.py"
      data_path: "coordinator._picked_session_summary"
    semantic: |
      State = the work_log picker's current label. Attributes carry
      the flat picked-session summary dict (built by
      session_card.build_picked_session_summary). All Sessions-tab
      per-session detail cards consume this entity's attributes.
    verifications:
      - date: "2026-05-15"
        status: verified
        claim: "Entity exists; state matches picker label; attributes match builder output"
        evidence: "tests/integration/test_picked_session.py + tests/protocol/test_session_card.py"
    status:
      last_seen: "2026-05-15"
```

Also update the existing `summary_*` rows in `inventory.yaml` to record that `MODE_LABELS` etc. are `presumed`-status — append a new verification entry to each:

```yaml
    verifications:
      - date: "2026-05-15"
        status: presumed
        claim: "session_card.MODE_LABELS / PRE_TYPE_LABELS / START_MODE_LABELS / STOP_REASON_LABELS hold best-effort enum mappings; unmapped values render as 'raw=N'"
```

(Apply to `summary_mode`, `summary_pre_type`, `summary_start_mode`, `summary_stop_reason` — only if those entries exist; otherwise skip.)

- [ ] **Step 2: Run the inventory linter**

If `tools/inventory_audit.py` exists, run:

```bash
python tools/inventory_audit.py
```

Expected: no errors. If it complains about schema, adjust the YAML to match the actual schema (see `docs/research/inventory/README.md` if available).

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory: record sensor.picked_session + presumed enum labels"
```

---

### Task 17: Restructure the Sessions tab in dashboard.yaml

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Locate the current Sessions tab block**

Open `dashboards/mower/dashboard.yaml`. Find `- title: Sessions` (around line 783). Note the existing cards listed under it.

- [ ] **Step 2: Replace the Sessions tab body**

Replace everything from `- title: Sessions` up to (but not including) the next `- title:` view with the following block. Mind the indentation — match the surrounding `views:` list.

```yaml
  - title: Sessions
    path: sessions
    icon: mdi:history
    cards:
      - type: markdown
        content: |
          # Mowing session history
          Cross-session widgets and the picker stay above the line.
          Pick a session below to see its detail cards.

      # ───── Top half: cross-session + picker (left) + replay map (right) ─────
      - type: horizontal-stack
        cards:
          - type: vertical-stack
            cards:
              - type: custom:atomic-calendar-revive
                name: Mowing sessions
                defaultMode: Calendar
                maxDaysToShow: 31
                showColors: true
                showLocation: false
                showRelativeTime: false
                entities:
                  - entity: calendar.dreame_a2_mower_sessions
                    icon: mdi:robot-mower
              - type: entities
                title: Replay picker
                entities:
                  - entity: select.dreame_a2_mower_work_log
                    name: Session
              - type: entities
                title: Latest archived
                entities:
                  - entity: sensor.dreame_a2_mower_latest_session_duration
                    name: Latest duration
                  - entity: sensor.dreame_a2_mower_latest_session_area
                    name: Latest area mowed (m²)
                  - entity: sensor.dreame_a2_mower_latest_session_time
                    name: Latest started at
                  - entity: sensor.dreame_a2_mower_archived_session_count
                    name: Archived count
              - type: conditional
                conditions:
                  - entity: binary_sensor.dreame_a2_mower_mowing_session_active
                    state: "on"
                card:
                  type: entities
                  title: Live session
                  entities:
                    - entity: sensor.dreame_a2_mower_session_distance
                      name: Distance (m)
                    - entity: sensor.dreame_a2_mower_session_track_point_count
                      name: Track points
              - type: entities
                title: Per-map session totals
                entities:
                  - entity: sensor.dreame_a2_mower_map_1_total_area_mowed
                    name: Map 1 — total area mowed
                  - entity: sensor.dreame_a2_mower_map_1_total_mowing_time
                    name: Map 1 — total time
                  - entity: sensor.dreame_a2_mower_map_1_mowing_sessions
                    name: Map 1 — sessions
                  - entity: sensor.dreame_a2_mower_map_2_total_area_mowed
                    name: Map 2 — total area mowed
                  - entity: sensor.dreame_a2_mower_map_2_total_mowing_time
                    name: Map 2 — total time
                  - entity: sensor.dreame_a2_mower_map_2_mowing_sessions
                    name: Map 2 — sessions
          - type: picture-entity
            entity: camera.dreame_a2_mower_work_log
            name: Session replay
            camera_view: auto
            show_state: false
            aspect_ratio: 1/1
            tap_action:
              action: none
            hold_action:
              action: none

      # ───── Divider + per-session cards (visible only when picked) ─────
      - type: markdown
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
        content: |
          ## Picked session
          {{ states('sensor.dreame_a2_mower_picked_session') }}

      - type: horizontal-stack
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
        cards:
          - type: markdown
            content: |
              ### Identity & outcome
              **When**: {{ state_attr('sensor.dreame_a2_mower_picked_session','started_at') }} → {{ state_attr('sensor.dreame_a2_mower_picked_session','ended_at') }} ({{ state_attr('sensor.dreame_a2_mower_picked_session','duration_min') }} min)
              **Mode**: {{ state_attr('sensor.dreame_a2_mower_picked_session','mode_label') }}
              **Trigger**: {{ state_attr('sensor.dreame_a2_mower_picked_session','start_mode_label') }}
              **Strategy**: {{ state_attr('sensor.dreame_a2_mower_picked_session','pre_type_label') }}
              **Outcome**: {{ state_attr('sensor.dreame_a2_mower_picked_session','result_label') }} — {{ state_attr('sensor.dreame_a2_mower_picked_session','stop_reason_label') }}
              **Completed**: {{ '✅' if state_attr('sensor.dreame_a2_mower_picked_session','completed') else '❌' }}
          - type: markdown
            content: |
              ### Coverage & efficiency
              **Area mowed**: {{ state_attr('sensor.dreame_a2_mower_picked_session','area_mowed_m2') }} m² of {{ state_attr('sensor.dreame_a2_mower_picked_session','map_area_m2') }} m²
              **Coverage**: {{ '%.1f'|format(state_attr('sensor.dreame_a2_mower_picked_session','coverage_pct')) if state_attr('sensor.dreame_a2_mower_picked_session','coverage_pct') else '—' }} %
              **Distance**: {{ '%.0f'|format(state_attr('sensor.dreame_a2_mower_picked_session','distance_m')) }} m
              **Height**: {{ state_attr('sensor.dreame_a2_mower_picked_session','mowing_height_mm') }} mm
              **Efficiency**: {{ state_attr('sensor.dreame_a2_mower_picked_session','mowing_efficiency_label') }}
              **m²/min**: {{ '%.2f'|format(state_attr('sensor.dreame_a2_mower_picked_session','m2_per_min')) if state_attr('sensor.dreame_a2_mower_picked_session','m2_per_min') else '—' }}
              **m²/% battery**: {{ '%.2f'|format(state_attr('sensor.dreame_a2_mower_picked_session','m2_per_pct')) if state_attr('sensor.dreame_a2_mower_picked_session','m2_per_pct') else '—' }}

      - type: horizontal-stack
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
        cards:
          - type: markdown
            content: |
              ### Energy & time breakdown
              **Battery**: {{ state_attr('sensor.dreame_a2_mower_picked_session','charge_at_start_pct') }} → {{ state_attr('sensor.dreame_a2_mower_picked_session','charge_at_end_pct') }} (min {{ state_attr('sensor.dreame_a2_mower_picked_session','charge_min_pct') }})
              **Charge used**: {{ state_attr('sensor.dreame_a2_mower_picked_session','charge_used_pct') }} % across {{ state_attr('sensor.dreame_a2_mower_picked_session','recharge_count') }} mid-mow recharge(s)
              **Time mowing**: {{ state_attr('sensor.dreame_a2_mower_picked_session','time_mowing_min') }} min
              **Time charging**: {{ state_attr('sensor.dreame_a2_mower_picked_session','time_charging_min') }} min
              **Time other**: {{ state_attr('sensor.dreame_a2_mower_picked_session','time_other_min') }} min
          - type: markdown
            content: |
              ### Diagnostics
              **Faults**: {{ state_attr('sensor.dreame_a2_mower_picked_session','fault_count') }}
              **Obstacles**: {{ state_attr('sensor.dreame_a2_mower_picked_session','obstacle_count') }} (AI {{ state_attr('sensor.dreame_a2_mower_picked_session','ai_obstacle_count') }})
              **State transitions**: {{ state_attr('sensor.dreame_a2_mower_picked_session','state_transition_count') }}
              **Error events**: {{ state_attr('sensor.dreame_a2_mower_picked_session','error_event_count') }} (codes {{ state_attr('sensor.dreame_a2_mower_picked_session','error_codes_seen') }})
              **WiFi RSSI**: min {{ state_attr('sensor.dreame_a2_mower_picked_session','wifi_rssi_min_dbm') }} / avg {{ state_attr('sensor.dreame_a2_mower_picked_session','wifi_rssi_avg_dbm') }} / max {{ state_attr('sensor.dreame_a2_mower_picked_session','wifi_rssi_max_dbm') }} dBm ({{ state_attr('sensor.dreame_a2_mower_picked_session','wifi_sample_count') }} samples)

      - type: markdown
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
          - condition: template
            value_template: "{{ state_attr('sensor.dreame_a2_mower_picked_session','settings_snapshot') is not none }}"
        content: |
          ### Settings in effect at session start
          {% set s = state_attr('sensor.dreame_a2_mower_picked_session','settings_snapshot') or {} %}
          **EdgeMaster**: {{ s.get('settings_edgemaster') }}
          **Edge walk mode**: {{ s.get('settings_edge_mowing_walk_mode') }}
          **Edge mowing mode**: {{ s.get('settings_edge_mowing_mode') }}
          **Obstacle avoidance**: {{ s.get('settings_obstacle_avoidance_mode') }} (AI: {{ s.get('settings_obstacle_avoidance_ai') }})
          **Mowing height**: {{ s.get('settings_mowing_height_mm') }} mm
          **Mowing efficiency**: {{ s.get('settings_mowing_efficiency') }}

      - type: custom:apexcharts-card
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
        header:
          show: true
          title: Battery % over session
        graph_span: 8h
        series:
          - entity: sensor.dreame_a2_mower_picked_session
            name: Battery %
            type: line
            data_generator: |
              return (entity.attributes.battery_samples || []).map(s => [s[0]*1000, s[1]]);

      - type: custom:apexcharts-card
        visibility:
          - condition: state
            entity: select.dreame_a2_mower_work_log
            state_not: "(pick a session)"
        header:
          show: true
          title: WiFi RSSI over session
        graph_span: 8h
        series:
          - entity: sensor.dreame_a2_mower_picked_session
            name: RSSI (dBm)
            type: line
            data_generator: |
              return (entity.attributes.wifi_samples || []).map(s => [s[3]*1000, s[2]]);
```

(Note: `apexcharts-card`'s `data_generator` returns `[unix_ms, value]` pairs — multiply timestamps by 1000.)

- [ ] **Step 3: Validate YAML**

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"
```

Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: restructure Sessions tab with picked-session detail cards"
```

---

### Task 18: SCP dashboard + smoke-test in browser

**Files:**
- Modify: `/config/dashboards/mower/dashboard.yaml` (on HA host) — push via scp

- [ ] **Step 1: Build a release**

Run:

```bash
tools/release.sh 1.0.13a1 --notes "Add sensor.picked_session + restructure Sessions tab with 5 detail cards and 2 apexcharts series. Capture per-map settings_snapshot at session_begin so future archives carry the in-effect config."
```

Expected: release.sh runs tests, bumps manifest, pushes, creates release, refreshes HACS.

- [ ] **Step 2: SCP the dashboard**

```bash
sshpass -p "$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)" \
  scp -o StrictHostKeyChecking=no \
  dashboards/mower/dashboard.yaml \
  root@10.0.0.30:/config/dashboards/mower/dashboard.yaml
```

- [ ] **Step 3: Reboot HA to pick up the new integration version**

(Don't reload — config_entries/reload won't re-import the integration's modules per memory feedback_ha_dev_gotchas.) Instead ask the user to reboot via the HA UI, OR run:

```bash
sshpass -p "$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)" \
  ssh -o StrictHostKeyChecking=no \
  root@10.0.0.30 \
  "curl -sS -X POST -H 'Authorization: Bearer $(sed -n 4p /data/claude/homeassistant/ha-credentials.txt)' http://10.0.0.30:8123/api/services/homeassistant/restart"
```

(This restarts HA — confirm with the user before running in case there's mowing in progress.)

- [ ] **Step 4: Visual smoke test (user-driven)**

Ask the user to:
1. Open the Mower dashboard → Sessions tab.
2. Confirm the upper half shows calendar + picker + latest/totals on the left and the replay map on the right.
3. Confirm the "## Picked session" divider is HIDDEN when the picker is on `(pick a session)`.
4. Pick a session — divider + 5 detail cards + 2 charts appear.
5. Pick a session from before v1.0.13a1 — Settings-in-effect card stays hidden (because settings_snapshot is None).
6. Re-pick `(pick a session)` — divider + detail cards vanish.

Verify in the HA log there are no template/visibility errors. If apexcharts series are empty, double-check the timestamp multiplication in `data_generator`.

- [ ] **Step 5: Update memory**

After visual confirmation, append a note to `/home/ok/.claude/projects/-data-claude-homeassistant/memory/MEMORY.md`:

```markdown
- [Session-summary card](project_session_card.md) — v1.0.13a1: sensor.picked_session + restructured Sessions tab; settings_snapshot captured at session_begin from v1.0.13a1 forward.
```

And create the memory file with status/scope notes per the user's memory schema.

- [ ] **Step 6: Final commit (if smoke-test required fixes)**

If anything needed tweaking from the smoke-test, commit + push + re-release as v1.0.13a2.

---

## Self-review

**Spec coverage** — every spec section now has at least one task:

- § New entity `sensor.dreame_a2_mower_picked_session` → Task 15.
- § Coordinator state `_picked_session_summary` → Task 12.
- § New pure module `session_card.py` → Tasks 6-10.
- § `LiveMapState.settings_snapshot` → Task 1.
- § Capture at session_begin → Task 2.
- § Persist + restore in `in_progress.json` → Task 3.
- § Inject into archive payload → Task 4.
- § Attribute schema (identity / coverage / energy / diagnostics / settings) → Tasks 7-10.
- § Tab layout → Task 17.
- § Conditional visibility → Task 17.
- § Live-session entities split → Task 17.
- § Data flow → end-to-end in Tasks 13-15.
- § Edge cases → Tasks 7-10 unit tests.
- § Testing → Tasks 6-10 (builder), 13-15 (integration), 11 (constant), 16 (inventory).
- § WORK_LOG_PLACEHOLDER → Task 11.
- § Entity-inventory.yaml update → Task 16.
- § Risk: state enum semantics → Task 9 includes sanity-check + conservative classification.
- § Risk: settings_snapshot growth → not addressed (deferred per spec, acceptable).

**Placeholder scan** — no "TBD", "TODO", "fill in details" placeholders. Each step has concrete code + commands.

**Type / name consistency**:
- `_picked_session_summary` (snake-case dict slot) — Tasks 12-15 all use this name.
- `build_picked_session_summary` (function) — Tasks 6-10 + 13.
- `format_session_label` — Tasks 6 + 13.
- `WORK_LOG_PLACEHOLDER` — Tasks 11 + 17 (used in `state_not:` strings — the constant is in const.py but the dashboard YAML embeds the literal string; both must match).
- `settings_snapshot` — Tasks 1-4, 10, 17.
- `DreameA2PickedSessionSensor` — Task 15 only.

All names consistent.

**Scope check** — 18 tasks. Each is bite-sized (2-5 min implementation + 1 test + 1 commit). Total estimated effort: 1-2 working days. Within plan scope.

---

## Implementation choice

Plan complete and saved to `docs/superpowers/plans/2026-05-15-session-summary-card.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
