# Session Recorder-Merge + Rain-Protection Time Bucket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At session-finalize, fill gaps in `battery_samples`/`wifi_samples` by querying HA recorder for the session window; also extract rain-protection sit-time as a separate `time_rain_protection_min` bucket on the picked-session sensor.

**Architecture:** New `coordinator/_recorder_merge.py` exposes `merge_recorder_samples(hass, raw_dict, start_ts, end_ts)`. Called from both `_do_oss_fetch` and `_run_finalize_incomplete` right after the existing `_inject_live_map_into_raw_dict` call, before `parse_session_summary`. Pure-function merge helpers stay testable without HA. Rain-protection bucket lives in `session_card.py:_compute_time_breakdown` which grows from a 3-tuple to a 4-tuple return.

**Tech Stack:** Python 3.13, Home Assistant `homeassistant.components.recorder` (async_add_executor_job + state_changes_during_period), pytest, pytest-asyncio.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py` | New module. `merge_recorder_samples` async entrypoint + pure `_merge_samples`/`_merge_wifi_samples` helpers + sync recorder readers (battery, wifi). No call-site logic; just the merge primitive. | Create |
| `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py:403` | After existing `_inject_live_map_into_raw_dict(raw_dict)` in `_do_oss_fetch`, call `merge_recorder_samples` and log counts. Wrapped in try/except so recorder failure can't block finalize. | Modify |
| `custom_components/dreame_a2_mower/coordinator/_session.py:504` | Same insertion in `_run_finalize_incomplete` after the `_inject_live_map_into_raw_dict(incomplete_payload)` call. | Modify |
| `custom_components/dreame_a2_mower/session_card.py:81-149` | `_compute_time_breakdown` upgrades from 3-tuple to 4-tuple (mow, chg, rain, other). Add `_compute_rain_pause_seconds` helper. `build_picked_session_summary` adds `time_rain_protection_min` attribute. | Modify |
| `tests/coordinator/test_recorder_merge.py` | Pure-function tests for `_merge_samples`/`_merge_wifi_samples`. Integration test for `merge_recorder_samples` with a stubbed `state_changes_during_period`. | Create |
| `tests/protocol/test_session_card.py` | Add tests for rain-pause detection and the 4-tuple breakdown. | Modify |
| `dashboards/mower/dashboard.yaml` | Add one row in the session time-breakdown card for `time_rain_protection_min`. | Modify |

---

## Phase 1 — Recorder-merge module (TDD on pure functions first)

### Task 1: Scaffold `_recorder_merge.py` with pure merge primitives

**Files:**
- Create: `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`
- Create: `tests/coordinator/test_recorder_merge.py`

- [ ] **Step 1: Write failing tests for the pure merge functions**

Create `tests/coordinator/__init__.py` if it doesn't exist (empty file).

Create `tests/coordinator/test_recorder_merge.py`:

```python
"""Tests for the session recorder-merge helpers."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _merge_samples,
    _merge_wifi_samples,
)


def test_merge_samples_empty_inputs() -> None:
    assert _merge_samples([], []) == []


def test_merge_samples_dedups_on_ts_value() -> None:
    existing = [[100, 80], [200, 79]]
    additions = [[100, 80], [150, 79], [200, 79], [250, 78]]
    out = _merge_samples(existing, additions)
    # (100,80), (150,79), (200,79), (250,78) — dups removed
    assert out == [[100, 80], [150, 79], [200, 79], [250, 78]]


def test_merge_samples_sorts_by_ts() -> None:
    existing = [[300, 70], [100, 80]]
    additions = [[200, 75]]
    out = _merge_samples(existing, additions)
    assert [s[0] for s in out] == [100, 200, 300]


def test_merge_samples_preserves_value_difference_at_same_ts() -> None:
    """Two different values at the same timestamp both survive
    (rare but possible — a battery sample and a recorder-side
    rounding artifact could land at the same second with
    different ints)."""
    existing = [[100, 80]]
    additions = [[100, 81]]
    out = _merge_samples(existing, additions)
    assert sorted(out) == [[100, 80], [100, 81]]


def test_merge_wifi_samples_empty_inputs() -> None:
    assert _merge_wifi_samples([], []) == []


def test_merge_wifi_samples_dedups_on_ts_rssi() -> None:
    # WiFi sample shape: [lat_offset, lon_offset, rssi, ts]
    existing = [[1.0, 2.0, -70, 100], [1.0, 2.0, -71, 200]]
    additions = [
        [None, None, -70, 100],  # dup on (ts=100, rssi=-70)
        [None, None, -69, 150],  # new
        [None, None, -71, 200],  # dup on (ts=200, rssi=-71)
    ]
    out = _merge_wifi_samples(existing, additions)
    rssi_ts = [(s[3], s[2]) for s in out]
    assert rssi_ts == [(100, -70), (150, -69), (200, -71)]


def test_merge_wifi_samples_sorts_by_ts() -> None:
    existing = [[1.0, 2.0, -70, 300]]
    additions = [[None, None, -65, 100], [None, None, -68, 200]]
    out = _merge_wifi_samples(existing, additions)
    assert [s[3] for s in out] == [100, 200, 300]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/coordinator/test_recorder_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '...coordinator._recorder_merge'`.

- [ ] **Step 3: Create the module with the pure helpers**

Create `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`:

```python
"""Recorder-merge safety net for session sample arrays.

At session-finalize time, the in_progress.json sample arrays
(populated by the 30s-debounced persist + restore chain) may be
missing windows where the persist/restore couldn't run (HA restart
during quiet periods, write-failure, etc.). HA's own recorder
keeps state history for any sensor entity with default-true
recording, so battery and wifi-RSSI samples are recoverable from
there.

Two clean layers:
  - Pure ``_merge_samples`` / ``_merge_wifi_samples`` helpers
    operate on lists. No HA dependency. Trivially unit-tested.
  - Async ``merge_recorder_samples`` orchestrates the recorder
    queries (wrapped in executor jobs) and stitches results into
    raw_dict via the pure helpers.

No ``homeassistant.*`` imports at module top so the pure helpers
can be tested without a running HA. The async function does its
imports lazily inside the function body.
"""
from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def _merge_samples(
    existing: list[list[int]], additions: list[list[int]]
) -> list[list[int]]:
    """Combine two `[ts_s, value]` lists; dedup on (ts, value); sort by ts.

    Both inputs are lists of 2-element ``[int_ts_seconds, int_value]``
    entries. Returns a new list — neither input is mutated.

    Dedup key is (ts, value), not ts alone, because the same
    timestamp can legitimately carry two distinct values in rare
    cases (e.g., MQTT push and recorder-rounded poll at the same
    second). Keeping both is correct behavior for charts.
    """
    out: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for src in (existing, additions):
        for s in src:
            if len(s) < 2:
                continue
            key = (int(s[0]), int(s[1]))
            if key in seen:
                continue
            seen.add(key)
            out.append([int(s[0]), int(s[1])])
    out.sort(key=lambda s: s[0])
    return out


def _merge_wifi_samples(
    existing: list[list[Any]], additions: list[list[Any]]
) -> list[list[Any]]:
    """Combine two WiFi sample lists; dedup on (ts, rssi); sort by ts.

    WiFi sample shape: ``[lat_offset, lon_offset, rssi, ts]``.
    Position fields (indices 0 and 1) can be None on
    recorder-sourced samples (no positional context for those
    readings). Dedup compares only the (ts, rssi) pair so
    recorder-sourced entries with None positions correctly merge
    against MQTT-sourced entries that have real positions.
    """
    out: list[list[Any]] = []
    seen: set[tuple[int, int]] = set()
    for src in (existing, additions):
        for s in src:
            if len(s) < 4:
                continue
            try:
                ts = int(s[3])
                rssi = int(s[2])
            except (TypeError, ValueError):
                continue
            key = (ts, rssi)
            if key in seen:
                continue
            seen.add(key)
            out.append([s[0], s[1], rssi, ts])
    out.sort(key=lambda s: s[3])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/coordinator/test_recorder_merge.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_recorder_merge.py \
        tests/coordinator/__init__.py \
        tests/coordinator/test_recorder_merge.py
git commit -m "recorder_merge: scaffold + pure merge helpers"
```

---

### Task 2: Sync recorder-reader functions for battery + wifi

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`
- Modify: `tests/coordinator/test_recorder_merge.py`

- [ ] **Step 1: Write failing tests for the sync recorder readers**

Append to `tests/coordinator/test_recorder_merge.py`:

```python
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _read_battery_history_sync,
    _read_wifi_history_sync,
    BATTERY_ENTITY_ID,
    WIFI_RSSI_ENTITY_ID,
)


def _state(ts_unix: int, value: str) -> SimpleNamespace:
    """Fake HA State with the two fields our reader touches."""
    return SimpleNamespace(
        state=value,
        last_changed=dt.datetime.fromtimestamp(ts_unix, dt.UTC),
    )


def test_read_battery_history_sync_parses_valid_states() -> None:
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "84"),
            _state(1200, "83"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == [[1000, 85], [1100, 84], [1200, 83]]


def test_read_battery_history_sync_skips_non_numeric_states() -> None:
    """unknown/unavailable/empty states get dropped silently."""
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "unavailable"),
            _state(1200, "unknown"),
            _state(1300, ""),
            _state(1400, "84"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1500, dt.UTC),
        )
    assert out == [[1000, 85], [1400, 84]]


def test_read_battery_history_sync_skips_out_of_range() -> None:
    """Battery values outside 0..100 are skipped (recorder rounding
    or a value-class change can leak in non-percentages)."""
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "-5"),
            _state(1200, "101"),
            _state(1300, "80"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1400, dt.UTC),
        )
    assert out == [[1000, 85], [1300, 80]]


def test_read_battery_history_sync_returns_empty_when_entity_missing() -> None:
    """state_changes_during_period returns {} when entity unknown."""
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value={},
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == []


def test_read_wifi_history_sync_parses_valid_states() -> None:
    fake_states = {
        WIFI_RSSI_ENTITY_ID: [
            _state(1000, "-70"),
            _state(1100, "-69"),
            _state(1200, "-71"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_wifi_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    # Output shape: [None, None, rssi, ts]
    assert out == [[None, None, -70, 1000], [None, None, -69, 1100], [None, None, -71, 1200]]


def test_read_wifi_history_sync_skips_non_numeric_states() -> None:
    fake_states = {
        WIFI_RSSI_ENTITY_ID: [
            _state(1000, "-70"),
            _state(1100, "unavailable"),
            _state(1200, "-71"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_wifi_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == [[None, None, -70, 1000], [None, None, -71, 1200]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/coordinator/test_recorder_merge.py -v -k 'read_battery_history or read_wifi_history'`
Expected: FAIL with `ImportError: cannot import name 'BATTERY_ENTITY_ID' ...` and friends.

- [ ] **Step 3: Add the sync readers + entity-id constants**

Append to `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`:

```python
# Entity IDs hardcoded here. Both are part of the integration's
# stable entity contract — sensor.py (battery + wifi_rssi) registers
# them with these unique-id suffixes which HA resolves to the
# entity_ids below. If a user renames the entities, the recorder
# merge silently returns 0 samples (no exception); not worth an
# indirection layer until someone reports it.
BATTERY_ENTITY_ID = "sensor.dreame_a2_mower_battery"
WIFI_RSSI_ENTITY_ID = "sensor.dreame_a2_mower_wifi_rssi"

# Lazy import: keeps the module loadable without HA so the pure
# helpers above stay unit-testable in isolation.
try:
    from homeassistant.components.recorder.history import (
        state_changes_during_period,
    )
except ImportError:
    # Tests stub state_changes_during_period at this module path
    # via `unittest.mock.patch`, so the symbol needs to exist
    # at import time even when HA isn't available.
    state_changes_during_period = None  # type: ignore[assignment]


def _read_battery_history_sync(hass, start_dt, end_dt) -> list[list[int]]:
    """Read battery-sensor state history from HA recorder.

    Synchronous — wrapped by ``merge_recorder_samples`` via
    recorder.async_add_executor_job. Returns ``[[ts_seconds, int_pct], ...]``
    sorted ascending by timestamp. Skips entries that aren't
    parseable as ints in the 0..100 range (unknown/unavailable,
    non-numeric, recorder rounding artifacts).
    """
    if state_changes_during_period is None:
        return []
    raw = state_changes_during_period(
        hass,
        start_dt,
        end_dt,
        entity_id=BATTERY_ENTITY_ID,
        include_start_time_state=True,
    )
    out: list[list[int]] = []
    for st in raw.get(BATTERY_ENTITY_ID, []):
        try:
            v = int(st.state)
        except (TypeError, ValueError):
            continue
        if not 0 <= v <= 100:
            continue
        try:
            ts = int(st.last_changed.timestamp())
        except (TypeError, AttributeError):
            continue
        out.append([ts, v])
    return out


def _read_wifi_history_sync(hass, start_dt, end_dt) -> list[list[Any]]:
    """Read WiFi-RSSI sensor state history from HA recorder.

    Output shape matches the existing wifi_samples format
    ``[lat_offset, lon_offset, rssi, ts]`` with positions nulled
    (recorder doesn't carry positional context). Skips non-numeric
    states. RSSI is kept as-is from the sensor — typically a
    negative dBm value.
    """
    if state_changes_during_period is None:
        return []
    raw = state_changes_during_period(
        hass,
        start_dt,
        end_dt,
        entity_id=WIFI_RSSI_ENTITY_ID,
        include_start_time_state=True,
    )
    out: list[list[Any]] = []
    for st in raw.get(WIFI_RSSI_ENTITY_ID, []):
        try:
            rssi = int(st.state)
        except (TypeError, ValueError):
            continue
        try:
            ts = int(st.last_changed.timestamp())
        except (TypeError, AttributeError):
            continue
        out.append([None, None, rssi, ts])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/coordinator/test_recorder_merge.py -v`
Expected: 12 PASS (6 pure-merge from Task 1 + 6 new sync-reader tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_recorder_merge.py \
        tests/coordinator/test_recorder_merge.py
git commit -m "recorder_merge: sync readers for battery + wifi history"
```

---

### Task 3: Async `merge_recorder_samples` orchestrator

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`
- Modify: `tests/coordinator/test_recorder_merge.py`

- [ ] **Step 1: Write failing test for the async entrypoint**

Append to `tests/coordinator/test_recorder_merge.py`:

```python
import asyncio

import pytest

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    merge_recorder_samples,
)


class _FakeRecorderInstance:
    """Minimal hass-like object for the merge orchestrator test."""

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class _FakeHass:
    def __init__(self) -> None:
        self._instance = _FakeRecorderInstance()


@pytest.mark.asyncio
async def test_merge_recorder_samples_fills_gaps(tmp_path) -> None:
    """When raw_dict has 2 battery samples and recorder has 5, the
    merged list should have 5 (deduped, sorted, source-agnostic)."""
    raw_dict: dict = {
        "battery_samples": [[1000, 85], [2000, 80]],
        "wifi_samples": [[1.0, 2.0, -70, 1000]],
    }
    hass = _FakeHass()

    fake_battery = [[1000, 85], [1500, 82], [2000, 80], [2500, 78], [3000, 75]]
    fake_wifi = [[None, None, -70, 1000], [None, None, -68, 1500], [None, None, -71, 2500]]

    with (
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_battery_from_recorder",
            return_value=fake_battery,
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_wifi_from_recorder",
            return_value=fake_wifi,
        ),
    ):
        counts = await merge_recorder_samples(hass, raw_dict, 1000, 3000)

    # Battery: 5 distinct ts (1000, 1500, 2000, 2500, 3000), all values present.
    assert [s[0] for s in raw_dict["battery_samples"]] == [1000, 1500, 2000, 2500, 3000]
    # WiFi: 3 distinct ts (1000, 1500, 2500).
    assert [s[3] for s in raw_dict["wifi_samples"]] == [1000, 1500, 2500]
    # Counts reflect what the recorder contributed (raw fetch count, not net-new).
    assert counts == {"battery_recorder_count": 5, "wifi_recorder_count": 3}


@pytest.mark.asyncio
async def test_merge_recorder_samples_handles_missing_raw_keys() -> None:
    """raw_dict without battery_samples / wifi_samples should not crash."""
    raw_dict: dict = {}
    hass = _FakeHass()

    with (
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_battery_from_recorder",
            return_value=[[100, 90]],
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_wifi_from_recorder",
            return_value=[[None, None, -65, 100]],
        ),
    ):
        await merge_recorder_samples(hass, raw_dict, 100, 200)

    assert raw_dict["battery_samples"] == [[100, 90]]
    assert raw_dict["wifi_samples"] == [[None, None, -65, 100]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/coordinator/test_recorder_merge.py -v -k 'merge_recorder_samples'`
Expected: FAIL — `merge_recorder_samples` and `_async_fetch_*` don't exist yet.

- [ ] **Step 3: Implement the async layer**

Append to `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`:

```python
import datetime as _dt


async def _async_fetch_battery_from_recorder(
    hass, start_ts: int, end_ts: int
) -> list[list[int]]:
    """Async wrapper around _read_battery_history_sync that runs the
    blocking recorder query in an executor.

    Returns an empty list if the recorder isn't loaded or the query
    raises — the caller treats this as "no augmenting samples
    available" and falls back to the in_progress.json samples
    alone.
    """
    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return []
    try:
        instance = get_instance(hass)
    except Exception:
        LOGGER.exception("[recorder_merge] get_instance failed")
        return []
    start_dt = _dt.datetime.fromtimestamp(start_ts, _dt.UTC)
    end_dt = _dt.datetime.fromtimestamp(end_ts, _dt.UTC)
    try:
        return await instance.async_add_executor_job(
            _read_battery_history_sync, hass, start_dt, end_dt
        )
    except Exception:
        LOGGER.exception(
            "[recorder_merge] battery history query failed for [%d, %d]",
            start_ts, end_ts,
        )
        return []


async def _async_fetch_wifi_from_recorder(
    hass, start_ts: int, end_ts: int
) -> list[list[Any]]:
    """Async wrapper around _read_wifi_history_sync. Same failure
    mode as the battery variant — returns [] on any error.
    """
    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return []
    try:
        instance = get_instance(hass)
    except Exception:
        LOGGER.exception("[recorder_merge] get_instance failed")
        return []
    start_dt = _dt.datetime.fromtimestamp(start_ts, _dt.UTC)
    end_dt = _dt.datetime.fromtimestamp(end_ts, _dt.UTC)
    try:
        return await instance.async_add_executor_job(
            _read_wifi_history_sync, hass, start_dt, end_dt
        )
    except Exception:
        LOGGER.exception(
            "[recorder_merge] wifi history query failed for [%d, %d]",
            start_ts, end_ts,
        )
        return []


async def merge_recorder_samples(
    hass, raw_dict: dict[str, Any], start_ts: int, end_ts: int
) -> dict[str, int]:
    """Merge HA recorder history for battery + wifi-RSSI into raw_dict.

    Mutates ``raw_dict`` in place: replaces ``battery_samples`` and
    ``wifi_samples`` with the merged-and-sorted union of whatever
    was there + whatever the recorder reports for the window.

    Returns a dict with raw-fetch counts so the caller can log
    how much the recorder contributed.

    Failure mode: recorder errors are caught and logged inside the
    _async_fetch_* helpers; this orchestrator never raises. If
    both fetches return [] the existing raw_dict samples are left
    untouched.
    """
    battery_recorder = await _async_fetch_battery_from_recorder(
        hass, start_ts, end_ts,
    )
    wifi_recorder = await _async_fetch_wifi_from_recorder(
        hass, start_ts, end_ts,
    )
    existing_battery = raw_dict.get("battery_samples") or []
    existing_wifi = raw_dict.get("wifi_samples") or []
    raw_dict["battery_samples"] = _merge_samples(
        existing_battery, battery_recorder,
    )
    raw_dict["wifi_samples"] = _merge_wifi_samples(
        existing_wifi, wifi_recorder,
    )
    return {
        "battery_recorder_count": len(battery_recorder),
        "wifi_recorder_count": len(wifi_recorder),
    }
```

- [ ] **Step 4: Run all recorder_merge tests**

Run: `pytest tests/coordinator/test_recorder_merge.py -v`
Expected: 14 PASS (12 from earlier + 2 new orchestrator tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_recorder_merge.py \
        tests/coordinator/test_recorder_merge.py
git commit -m "recorder_merge: async orchestrator with executor-job wrapping"
```

---

## Phase 2 — Wire into finalize paths

### Task 4: Call `merge_recorder_samples` from `_do_oss_fetch`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py:403`

The existing line in `_do_oss_fetch`:

```python
self._inject_live_map_into_raw_dict(raw_dict)
```

is followed by `parse_session_summary(raw_dict)`. Insert the recorder merge between them so the parser sees the merged samples.

- [ ] **Step 1: Read the current call site to know the exact surrounding text**

Run: `sed -n '398,415p' custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
Expected: the block ending in `self._inject_live_map_into_raw_dict(raw_dict)` followed by `try: summary = _session_summary.parse_session_summary(raw_dict)`.

- [ ] **Step 2: Insert the merge call**

In `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`, find:

```python
        # v1.0.0a54+: inject locally-tracked fields (legs, WiFi samples,
        # telemetry streams, settings_snapshot) into the raw JSON before
        # archiving. Extracted into _inject_live_map_into_raw_dict so the
        # FINALIZE_INCOMPLETE path can reuse the same logic.
        self._inject_live_map_into_raw_dict(raw_dict)

        try:
            summary = _session_summary.parse_session_summary(raw_dict)
```

Replace with:

```python
        # v1.0.0a54+: inject locally-tracked fields (legs, WiFi samples,
        # telemetry streams, settings_snapshot) into the raw JSON before
        # archiving. Extracted into _inject_live_map_into_raw_dict so the
        # FINALIZE_INCOMPLETE path can reuse the same logic.
        self._inject_live_map_into_raw_dict(raw_dict)

        # Recorder-merge safety net (2026-05-16 spec): fill gaps in the
        # battery/wifi sample arrays from HA's recorder history. Idempotent;
        # any failure leaves the in_progress samples untouched.
        try:
            from ._recorder_merge import merge_recorder_samples

            _start_ts = int(raw_dict.get("start") or 0)
            _end_ts = int(raw_dict.get("end") or 0)
            if _start_ts > 0 and _end_ts > _start_ts:
                _counts = await merge_recorder_samples(
                    self.hass, raw_dict, _start_ts, _end_ts,
                )
                LOGGER.info(
                    "[recorder_merge] OSS-fetch finalize: %d battery + %d wifi "
                    "samples merged from recorder for session [%d, %d]",
                    _counts["battery_recorder_count"],
                    _counts["wifi_recorder_count"],
                    _start_ts, _end_ts,
                )
        except Exception:
            LOGGER.exception(
                "[recorder_merge] OSS-fetch finalize: merge failed; "
                "using in_progress samples only"
            )

        try:
            summary = _session_summary.parse_session_summary(raw_dict)
```

- [ ] **Step 3: Run the existing session-tests to confirm nothing regressed**

Run: `pytest tests/protocol/test_session_card.py tests/integration/test_picked_session.py -v`
Expected: all PASS (the new code path isn't exercised by these tests but the import shouldn't break them).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py
git commit -m "lidar_oss: invoke recorder_merge in _do_oss_fetch finalize path"
```

---

### Task 5: Call `merge_recorder_samples` from `_run_finalize_incomplete`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py:504`

Same insertion in the FINALIZE_INCOMPLETE path so sessions that never got a cloud OSS summary also get the recorder safety net.

- [ ] **Step 1: Read the current call site**

Run: `sed -n '498,520p' custom_components/dreame_a2_mower/coordinator/_session.py`
Expected: shows `self._inject_live_map_into_raw_dict(incomplete_payload)` at line 504 followed by subsequent processing.

- [ ] **Step 2: Insert the merge call**

In `custom_components/dreame_a2_mower/coordinator/_session.py`, find the line:

```python
        self._inject_live_map_into_raw_dict(incomplete_payload)
```

Insert IMMEDIATELY AFTER it (preserving indentation; if the line is at column 8 — i.e., inside a method — the new block matches):

```python

        # Recorder-merge safety net (2026-05-16 spec) — same layer
        # _do_oss_fetch uses, applied to the FINALIZE_INCOMPLETE
        # payload before it gets archived.
        try:
            from ._recorder_merge import merge_recorder_samples

            _start_ts = int(incomplete_payload.get("start") or 0)
            _end_ts = int(incomplete_payload.get("end") or 0)
            if _start_ts > 0 and _end_ts > _start_ts:
                _counts = await merge_recorder_samples(
                    self.hass, incomplete_payload, _start_ts, _end_ts,
                )
                LOGGER.info(
                    "[recorder_merge] FINALIZE_INCOMPLETE: %d battery + "
                    "%d wifi samples merged from recorder for session "
                    "[%d, %d]",
                    _counts["battery_recorder_count"],
                    _counts["wifi_recorder_count"],
                    _start_ts, _end_ts,
                )
        except Exception:
            LOGGER.exception(
                "[recorder_merge] FINALIZE_INCOMPLETE: merge failed; "
                "using in_progress samples only"
            )
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/ -v -k 'finalize or picked_session' 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py
git commit -m "session: invoke recorder_merge in FINALIZE_INCOMPLETE path"
```

---

## Phase 3 — Rain-protection time bucket

### Task 6: Add `_compute_rain_pause_seconds` helper

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

The helper is added separately from the breakdown-tuple change so the unit test surface for the detection logic stays focused.

- [ ] **Step 1: Write failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
from custom_components.dreame_a2_mower.session_card import (
    _compute_rain_pause_seconds,
)


def test_rain_pause_zero_when_no_56_event():
    """No s2p2=56 in error_samples → 0 rain pause."""
    error_samples = [[1000, 70], [1500, 48]]  # 70=continue, 48=complete
    state_samples = [[900, 1], [1500, 2]]
    rain = _compute_rain_pause_seconds(error_samples, state_samples, 900, 1500)
    assert rain == 0


def test_rain_pause_closes_at_next_mowing_state():
    """s2p2=56 at t=1000, then state_samples returns to a mowing
    code (1/2/3) at t=14000. Rain pause should be 13000s."""
    error_samples = [[1000, 56]]
    state_samples = [[14000, 2]]
    rain = _compute_rain_pause_seconds(error_samples, state_samples, 500, 20000)
    assert rain == 13000


def test_rain_pause_extends_to_end_when_no_close():
    """s2p2=56 fires and the session ends without a mowing
    resume — pause extends to end_ts."""
    error_samples = [[1000, 56]]
    state_samples = []  # no closing transition
    rain = _compute_rain_pause_seconds(error_samples, state_samples, 500, 5000)
    assert rain == 4000  # 5000 - 1000


def test_rain_pause_sums_multiple_intervals():
    """Two distinct s2p2=56 events with their own closes."""
    error_samples = [[1000, 56], [20000, 56]]
    state_samples = [[5000, 1], [25000, 2]]
    rain = _compute_rain_pause_seconds(error_samples, state_samples, 500, 30000)
    # 1000→5000 = 4000s, 20000→25000 = 5000s
    assert rain == 9000


def test_rain_pause_ignores_pre_56_state_returns():
    """A mowing-state entry BEFORE the s2p2=56 doesn't close
    anything — we only look forward in time."""
    error_samples = [[1000, 56]]
    state_samples = [[500, 2], [10000, 1]]
    rain = _compute_rain_pause_seconds(error_samples, state_samples, 0, 20000)
    # The 500-entry is pre-56 and ignored; closes at 10000.
    assert rain == 9000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/protocol/test_session_card.py -v -k 'rain_pause'`
Expected: FAIL — `_compute_rain_pause_seconds` doesn't exist.

- [ ] **Step 3: Add the helper**

In `custom_components/dreame_a2_mower/session_card.py`, find the existing `_compute_time_breakdown` function (around line 81). Just BEFORE it, add:

```python
# Mowing-state codes per s2p1 task_state semantics. Mirrors the
# dreame-mower-replay-card.js _MOWING_STATES — keep the two
# definitions in sync if the firmware exposes new mowing states.
_MOWING_STATE_CODES: set[int] = {1, 2, 3}


def _compute_rain_pause_seconds(
    error_samples: list[list[int]],
    state_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> int:
    """Sum seconds spent in rain-protection backoff.

    Each ``s2p2 = 56`` entry in ``error_samples`` opens a rain-
    pause interval. The interval closes at the first subsequent
    entry in ``state_samples`` whose value is in
    ``_MOWING_STATE_CODES`` (mower resumed mowing). If no such
    close is seen before ``end_ts`` the interval extends to
    ``end_ts`` (rain backoff outlived the session).

    Returns the cumulative pause seconds (int, clamped at 0).

    Idempotent / order-tolerant: re-walks state_samples per
    interval; for the typical session size (<200 samples each)
    this is O(N×M) but N×M stays small enough that we don't
    need a sorted-window optimization.
    """
    if not error_samples:
        return 0
    total = 0
    sorted_state = sorted(state_samples, key=lambda s: s[0])
    for s in error_samples:
        if len(s) < 2 or int(s[1]) != 56:
            continue
        open_ts = int(s[0])
        close_ts = end_ts  # default: outlived the session
        for ss in sorted_state:
            if len(ss) < 2:
                continue
            ss_ts = int(ss[0])
            if ss_ts <= open_ts:
                continue
            try:
                ss_val = int(ss[1])
            except (TypeError, ValueError):
                continue
            if ss_val in _MOWING_STATE_CODES:
                close_ts = ss_ts
                break
        if close_ts > open_ts:
            total += close_ts - open_ts
    return max(total, 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/protocol/test_session_card.py -v -k 'rain_pause'`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: _compute_rain_pause_seconds helper"
```

---

### Task 7: Upgrade `_compute_time_breakdown` to a 4-tuple

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

Existing return: `(mow_min, chg_min, other_min)`. New: `(mow_min, chg_min, rain_min, other_min)`. The caller passes `error_samples` and `state_samples` so the helper can call `_compute_rain_pause_seconds` internally.

- [ ] **Step 1: Inspect the existing signature**

Run: `sed -n '81,100p' custom_components/dreame_a2_mower/session_card.py`
Expected: shows the current `_compute_time_breakdown(battery_samples, charging_samples, start_ts, end_ts)` signature and docstring.

- [ ] **Step 2: Write failing tests for the 4-tuple shape**

Append to `tests/protocol/test_session_card.py`:

```python
from custom_components.dreame_a2_mower.session_card import (
    _compute_time_breakdown,
)


def test_time_breakdown_returns_4_tuple_with_rain():
    """When error_samples carries an s2p2=56 event, the breakdown
    returns 4 values and rain time is extracted from other."""
    # 1 hour session: 30 min mow + 20 min rain pause + 10 min charging
    start_ts, end_ts = 0, 3600
    battery_samples = [
        [0, 100],
        [600, 95],   # mowing → drop
        [1200, 90],  # mowing → drop
        [1800, 90],  # paused → flat (rain protection begins)
        [3000, 90],  # still paused
        [3300, 95],  # charging → rise
        [3600, 100], # charging → rise
    ]
    charging_samples = [
        [3300, 1],  # charging began at 3300s
    ]
    error_samples = [[1800, 56]]   # rain protection at t=1800
    state_samples = [[3500, 2]]    # resumed mowing at t=3500 (close interval)

    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples, charging_samples,
        start_ts, end_ts,
        error_samples=error_samples,
        state_samples=state_samples,
    )
    assert rain == (3500 - 1800) // 60  # ~28 min in minutes
    assert mow + chg + rain + other == (end_ts - start_ts) // 60


def test_time_breakdown_no_error_samples_keeps_zero_rain():
    """No rain events → rain bucket is 0 and 'other' absorbs the leftover."""
    start_ts, end_ts = 0, 3600
    battery_samples = [[0, 100], [600, 95], [3600, 100]]
    charging_samples = []
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples, charging_samples, start_ts, end_ts,
        error_samples=[], state_samples=[],
    )
    assert rain == 0
    assert mow + chg + other == 60  # 60 min total
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/protocol/test_session_card.py -v -k 'time_breakdown'`
Expected: FAIL — `_compute_time_breakdown` returns a 3-tuple, doesn't accept `error_samples`/`state_samples`.

- [ ] **Step 4: Read the current `_compute_time_breakdown` body**

Run: `sed -n '81,150p' custom_components/dreame_a2_mower/session_card.py`
Expected: full function body showing the existing 3-tuple return.

- [ ] **Step 5: Modify the signature and return**

In `custom_components/dreame_a2_mower/session_card.py`, replace the existing `_compute_time_breakdown` function. The exact new function (keep the existing algorithm for mow/chg, then subtract the rain seconds out of "other"):

```python
def _compute_time_breakdown(
    battery_samples: list[list[int]],
    charging_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
    *,
    error_samples: list[list[int]] | None = None,
    state_samples: list[list[int]] | None = None,
) -> tuple[int | None, int | None, int, int | None]:
    """Split the session wall-clock into (mowing, charging, rain, other) minutes.

    See module docstring for the mowing/charging algorithm — that hasn't
    changed. New fourth value is the rain-protection backoff sum,
    extracted from what would previously have been "other".

    error_samples + state_samples are keyword-only kwargs to keep
    backward compatibility for any caller that still passes the 4
    positional args; passing the kwargs adds the rain bucket,
    omitting them keeps rain=0 and produces the same other_min as
    before.

    Algorithm — uses two reliable signals:

    - **time_charging**: sum of intervals where charging_status_samples
      shows the mower at the dock charging (value == 1). Step-integrated
      with initial state 0.
    - **time_mowing**: sum of intervals where battery dropped between
      consecutive samples. Mowing is the only thing that drains battery.
    - **time_other**: total wall-clock - charging - mowing - rain.
      Catches transitions, brief pauses, idle, faults, etc.
    """
    # Charging: step-integrate the charging_status flag.
    charging_s = 0
    if charging_samples:
        sorted_chg = sorted(charging_samples, key=lambda s: int(s[0]))
        state = 0
        last_ts = start_ts
        for s in sorted_chg:
            ts = int(s[0])
            if ts < start_ts:
                state = int(s[1])
                continue
            if ts > end_ts:
                break
            if state == 1:
                charging_s += ts - last_ts
            state = int(s[1])
            last_ts = ts
        if state == 1:
            charging_s += end_ts - last_ts

    # Mowing: any interval where battery dropped.
    mowing_s = 0
    if len(battery_samples) >= 2:
        sorted_b = sorted(battery_samples, key=lambda s: int(s[0]))
        for i in range(1, len(sorted_b)):
            t1, v1 = int(sorted_b[i - 1][0]), int(sorted_b[i - 1][1])
            t2, v2 = int(sorted_b[i][0]), int(sorted_b[i][1])
            if t2 <= start_ts or t1 >= end_ts:
                continue
            if v2 < v1:
                mowing_s += min(t2, end_ts) - max(t1, start_ts)

    # Rain: cumulative s2p2=56 backoff intervals (kwargs path).
    rain_s = 0
    if error_samples and state_samples is not None:
        rain_s = _compute_rain_pause_seconds(
            error_samples, state_samples, start_ts, end_ts,
        )
    elif error_samples and state_samples is None:
        rain_s = _compute_rain_pause_seconds(
            error_samples, [], start_ts, end_ts,
        )

    total_s = max(0, end_ts - start_ts)
    accounted_s = charging_s + mowing_s + rain_s
    other_s = max(0, total_s - accounted_s)

    return (
        mowing_s // 60,
        charging_s // 60,
        rain_s // 60,
        other_s // 60,
    )
```

- [ ] **Step 6: Update the caller in `build_picked_session_summary`**

In the same file, find the call to `_compute_time_breakdown`:

```python
    mow_min, chg_min, other_min = _compute_time_breakdown(
        bs, cs, summary.start_ts, summary.end_ts
    )
    out["time_mowing_min"] = mow_min
    out["time_charging_min"] = chg_min
    out["time_other_min"] = other_min
```

Replace with:

```python
    mow_min, chg_min, rain_min, other_min = _compute_time_breakdown(
        bs, cs, summary.start_ts, summary.end_ts,
        error_samples=err_samples,
        state_samples=ss,
    )
    out["time_mowing_min"] = mow_min
    out["time_charging_min"] = chg_min
    out["time_rain_protection_min"] = rain_min
    out["time_other_min"] = other_min
```

The variable `err_samples` is the existing `list(raw_dict.get("error_samples") or [])` from line ~321 in the same function (search for `err_samples =` to confirm the line). `ss` is the existing `list(raw_dict.get("state_samples") or [])` (search for `ss =`).

- [ ] **Step 7: Run all session-card tests**

Run: `pytest tests/protocol/test_session_card.py -v`
Expected: all PASS — the 2 new time_breakdown tests + all existing.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: 4-tuple time breakdown adds rain_protection bucket

time_rain_protection_min now lives on picked_session attributes;
the existing time_other_min decreases by the rain time so the
four buckets still sum to elapsed_min."
```

---

## Phase 4 — Dashboard + release

### Task 8: Add Rain protection delay row to the time-breakdown dashboard card

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Find the time-breakdown card**

Run: `grep -n 'time_mowing_min\|time_charging_min\|time_other_min' dashboards/mower/dashboard.yaml`
Expected: 3-6 lines showing where these attributes are rendered in the markdown / entities card on the Sessions tab.

- [ ] **Step 2: Add the new row in the same block**

Find the existing render block — likely a markdown template that does `{{ state_attr('sensor.dreame_a2_mower_picked_session', 'time_other_min') }} min`. After the `time_other_min` line, insert an analogous line for `time_rain_protection_min`:

```yaml
                        **Rain protection delay**: {{ state_attr('sensor.dreame_a2_mower_picked_session','time_rain_protection_min') }} min
```

Match the surrounding indentation exactly. If the existing rows use a different structure (e.g., `type: entities` with `entity:` + `attribute:`), match that pattern instead.

- [ ] **Step 3: Deploy and verify**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
STAMP=$(date +%Y%m%d_%H%M%S)
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "cp /config/dashboards/mower/dashboard.yaml /config/dashboards/mower/dashboard.yaml.bak-${STAMP}"
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
  "$USER@$HOST:/config/dashboards/mower/dashboard.yaml"
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "md5sum /config/dashboards/mower/dashboard.yaml"
md5sum /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
```

Md5 must match.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: surface time_rain_protection_min in session breakdown"
```

---

### Task 9: SCP integration changes, cut release

**Files:**
- None (release tooling)

- [ ] **Step 1: Push any unpushed commits**

```bash
git push origin HEAD
```

- [ ] **Step 2: SCP the changed Python files for immediate effect**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
for f in coordinator/_recorder_merge.py coordinator/_lidar_oss.py \
         coordinator/_session.py session_card.py; do
  sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
    "/data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/$f" \
    "$USER@$HOST:/config/custom_components/dreame_a2_mower/$f"
done
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -la /config/custom_components/dreame_a2_mower/coordinator/_recorder_merge.py"
```

The new file `_recorder_merge.py` should now exist on the live HA.

- [ ] **Step 3: Cut release via existing tooling**

```bash
tools/release.sh --notes "$(cat <<'EOF'
Session recorder-merge safety net + rain-protection time bucket.

Two complementary session-finalize-time fixes:

1. New coordinator/_recorder_merge.py queries HA recorder for
   sensor.dreame_a2_mower_battery and sensor.dreame_a2_mower_wifi_rssi
   history within [start_ts, end_ts] and merges the results into the
   raw_dict's battery_samples and wifi_samples arrays before archive
   write. Idempotent; failure-isolated; doesn't replace the existing
   30s-debounced in_progress.json persistence. Closes the most
   common gap (HA restart during a long session) for battery + wifi
   without touching the persist chain.

2. session_card._compute_time_breakdown grows from a 3-tuple to a
   4-tuple: (mow, chg, rain, other). New time_rain_protection_min
   attribute on sensor.dreame_a2_mower_picked_session captures
   cumulative s2p2=56 backoff intervals so multi-hour rain pauses
   stop being silently bundled into "other". Dashboard gets one
   extra row.

The underlying in_progress.json reliability bug that motivated this
spec (19h session losing 8h of samples) stays captured in the
project-session-persist-audit-todo memory note. The recorder merge
papers over the symptom for battery + wifi specifically. Other
sample lists (charging_status, state, error) without HA-recorder
backup stay as-is until the persist-audit lands.

See spec:
docs/superpowers/specs/2026-05-16-session-recorder-merge-and-rain-bucket-design.md
EOF
)"
```

- [ ] **Step 4: Confirm the release**

The script prints the release URL. Verify isLatest=true / isPrerelease=false / isDraft=false in the output.

---

## Phase 5 — Manual verification (no commit unless something breaks)

### Task 10: Verify the recorder merge fixes the 19h session if re-finalized

**Files:**
- None (verification)

- [ ] **Step 1: Compare the existing 19h session's sample span to the post-fix expected span**

The session file is at `/config/dreame_a2_mower/sessions/2026-05-16_1778893682_7bff1b02.json` on the live HA. Currently `battery_samples` and `wifi_samples` span ~10.8 h (16:19 → 03:08+1d).

This task does NOT backfill the existing session (out of scope per spec). Instead, verify behavior on a NEW session.

- [ ] **Step 2: After the next session finalizes (next mowing run), check the log + the session JSON**

Pull recent system_log:

```bash
HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
TOKEN=$(sed -n 4p /data/claude/homeassistant/ha-credentials.txt)
python3 /tmp/ws_syslog.py "$HOST" "$TOKEN" 2>&1 | grep -E 'recorder_merge' | head
```

Expected: one or more lines like `[recorder_merge] OSS-fetch finalize: N battery + M wifi samples merged from recorder for session [start, end]`.

- [ ] **Step 3: After the next session finalizes, fetch the session JSON and confirm sample-array completeness**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
NEWEST=$(sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -t /config/dreame_a2_mower/sessions/2026-*.json | head -1")
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no "$USER@$HOST:$NEWEST" /tmp/sess_latest.json
python3 -c "
import json
d = json.load(open('/tmp/sess_latest.json'))
duration_h = (d['end'] - d['start']) / 3600
bs = d.get('battery_samples') or []
ws = d.get('wifi_samples') or []
print(f'session duration: {duration_h:.2f} h')
if bs:
    span_h = (bs[-1][0] - bs[0][0]) / 3600
    print(f'battery_samples: {len(bs)} pts, span {span_h:.2f} h')
if ws:
    span_h = (ws[-1][3] - ws[0][3]) / 3600
    print(f'wifi_samples: {len(ws)} pts, span {span_h:.2f} h')
print(f'time_rain_protection_min (attribute on sensor): see entity dump')
"
```

Expected: sample spans approximately equal to the session duration (allowing for recorder commit cadence + small startup/end gaps). Rain protection minutes nonzero if the session hit rain protection.

- [ ] **Step 4: Pick the session via the dashboard, verify the new "Rain protection delay" row appears**

User action. The picker fires `render_work_log_session` which calls `build_picked_session_summary`; the new attribute populates and the dashboard row renders.

---

## Self-review

**Spec coverage:**
- ✅ Part 1: New `coordinator/_recorder_merge.py` — Tasks 1-3
- ✅ Part 1: Called from `_do_oss_fetch` — Task 4
- ✅ Part 1: Called from `_run_finalize_incomplete` — Task 5
- ✅ Part 1: Dedup on `(ts, value)` + sort — Task 1
- ✅ Part 1: Recorder query in executor — Task 3
- ✅ Part 1: Error handling (no raise) — Task 3 + Tasks 4-5
- ✅ Part 2: `_compute_rain_pause_seconds` — Task 6
- ✅ Part 2: 4-tuple `_compute_time_breakdown` — Task 7
- ✅ Part 2: `time_rain_protection_min` on picked_session — Task 7
- ✅ Part 2: Dashboard row — Task 8
- ✅ Acceptance: future session sample arrays span full duration — Task 10

**Placeholder scan:** No "TBD/TODO/implement later/handle edge cases" — every code block is complete code, every command has an expected output.

**Type consistency:**
- `_merge_samples(existing, additions)` — list[list[int]] in, list[list[int]] out. Used in Tasks 1, 3. Match.
- `_merge_wifi_samples(existing, additions)` — list[list[Any]] in, list[list[Any]] out. Tasks 1, 3. Match.
- `merge_recorder_samples(hass, raw_dict, start_ts, end_ts) -> dict[str, int]` — Tasks 3, 4, 5. Match. Returns `{"battery_recorder_count": int, "wifi_recorder_count": int}`.
- `_compute_rain_pause_seconds(error_samples, state_samples, start_ts, end_ts) -> int` — Tasks 6, 7. Match.
- `_compute_time_breakdown(battery_samples, charging_samples, start_ts, end_ts, *, error_samples=None, state_samples=None) -> tuple` — Task 7. The new fourth tuple element (rain_min) is consistent across callers updated in Task 7.

No drift detected.
