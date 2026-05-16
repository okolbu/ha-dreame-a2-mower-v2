# Session Rebuild Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tools/rebuild_session.py` — an end-to-end session-rebuild tool that walks probe `*.jsonl` files, detects session windows, fetches matching HA archives, replays MQTT events through the integration's wire decoders to backfill every backfillable field (sample arrays, wifi_samples, legs, charge_at_start, settings_snapshot), and pushes back to HA. Bulk + single-session modes; surfaces uncovered HA archives.

**Architecture:** Single self-contained tool file with internal classes. Imports `protocol/heartbeat.py`, `protocol/_telemetry.py` (or owner of s1p4 decode), and `live_map/state.py` directly to reuse decoders + dedup helpers. SCP-mediated HA fetch + push behind `--dry-run`.

**Tech Stack:** Python 3.13, paramiko or sshpass + scp, pytest. No new runtime deps for the integration itself.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `tools/rebuild_session.py` | Main tool. Internal classes: `ProbeReader`, `HAArchiveFetcher`, `SessionRebuilder`, `VerboseDiffReporter`. CLI via argparse. | Create |
| `tools/_rebuild_session_lib/__init__.py` | Empty marker | Create |
| `tools/_rebuild_session_lib/session_windows.py` | Pure helper: walk s2p56 events → list of (start_ts, end_ts) windows. | Create |
| `tools/_rebuild_session_lib/wifi_replay.py` | Pure helper: replay heartbeat decode + position pairing → wifi_samples. | Create |
| `tools/_rebuild_session_lib/legs_replay.py` | Pure helper: replay s1p4 + s2p56 → legs. | Create |
| `tools/_rebuild_session_lib/settings_replay.py` | Pure helper: latest s5p107/s6p1/s2p51 at-or-before start_ts → settings_snapshot dict. | Create |
| `tests/tools/__init__.py` | Empty marker | Create |
| `tests/tools/test_session_windows.py` | Tests for window detection from synthetic s2p56 events. | Create |
| `tests/tools/test_wifi_replay.py` | Tests for wifi_samples reconstruction. | Create |
| `tests/tools/test_legs_replay.py` | Tests for legs reconstruction. | Create |
| `tests/tools/test_settings_replay.py` | Tests for settings_snapshot. | Create |
| `tests/tools/test_rebuild_session_e2e.py` | Smoke test wiring everything against a fixture probe + archive. | Create |
| `tools/backfill_session_samples.py` | Existing 4-stream tool — superseded by the new tool. | Delete (in last task) |

The internal-lib split keeps each concern testable in isolation; the main tool file just orchestrates.

---

## Phase 1 — Session window detection

### Task 1: `session_windows.detect_windows`

**Files:**
- Create: `tools/_rebuild_session_lib/__init__.py` (empty)
- Create: `tools/_rebuild_session_lib/session_windows.py`
- Create: `tests/tools/__init__.py` (empty)
- Create: `tests/tools/test_session_windows.py`

- [ ] **Step 1: Verify the s2p56 decode rule from inventory**

```bash
grep -A 12 'id: "s2p56"' custom_components/dreame_a2_mower/inventory.yaml | head -20
```

Confirm the rule:
- `prev ∈ {None, 2}` and `new == 0` → session start
- `prev ∈ {0, 4}` and `new ∈ {2, None}` → session end

- [ ] **Step 2: Write failing tests**

Create `tests/tools/test_session_windows.py`:

```python
"""Tests for tools._rebuild_session_lib.session_windows."""
from __future__ import annotations

import pytest

from tools._rebuild_session_lib.session_windows import (
    detect_windows,
    Window,
)


def _ev(ts: int, sub_state):
    """Build a synthetic s2p56 event."""
    return (ts, sub_state)  # (ts_unix, sub_state_int_or_None)


def test_detect_single_session_happy_path():
    events = [
        _ev(1000, None),  # idle
        _ev(2000, 0),     # session START
        _ev(3000, 4),     # paused (recharge)
        _ev(4000, 0),     # resumed
        _ev(5000, 2),     # session END (complete)
        _ev(6000, None),  # idle again
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_session_ending_in_none():
    events = [
        _ev(2000, 0),
        _ev(5000, None),  # END via "no task"
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_two_sessions():
    events = [
        _ev(1000, None),
        _ev(2000, 0), _ev(5000, 2),    # session 1
        _ev(6000, None),
        _ev(7000, 0), _ev(9000, None), # session 2
    ]
    windows = detect_windows(events)
    assert windows == [
        Window(start_ts=2000, end_ts=5000),
        Window(start_ts=7000, end_ts=9000),
    ]


def test_detect_mid_log_start_drops_open_session():
    """Probe started while mower was already running. We don't see
    the start event, so the implicit window is dropped (incomplete)."""
    events = [
        _ev(1000, 0),    # already running when probe began
        _ev(5000, 2),    # end seen
    ]
    windows = detect_windows(events)
    # No prev=None or prev=2 transition seen for the start, so this
    # session has no valid start_ts and gets dropped.
    assert windows == []


def test_detect_mid_log_end_drops_open_session():
    """Probe truncated mid-session. No end event, so window is dropped."""
    events = [
        _ev(2000, 0),
    ]
    windows = detect_windows(events)
    assert windows == []


def test_detect_ignores_non_transition_events():
    """Multiple consecutive 0 events (heartbeat re-emission) shouldn't
    create new sessions."""
    events = [
        _ev(2000, 0),    # start
        _ev(3000, 0),    # re-emit (no transition)
        _ev(4000, 0),    # re-emit
        _ev(5000, 2),    # end
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_empty_input():
    assert detect_windows([]) == []
```

- [ ] **Step 3: Verify tests fail**

```bash
pytest tests/tools/test_session_windows.py -v
```

Expected: ImportError (module doesn't exist).

- [ ] **Step 4: Implement**

Create `tools/_rebuild_session_lib/__init__.py` (empty file).

Create `tools/_rebuild_session_lib/session_windows.py`:

```python
"""Detect session windows from probe-captured s2p56 task_state events.

A session starts when the firmware transitions from "no task"
(None) or "complete" (2) into "running" (0). A session ends when
it leaves the running/paused set (0/4) for "complete" (2) or "no
task" (None).

Re-emissions of the same sub_state (heartbeat duplicates) are
ignored — only true transitions count.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    start_ts: int
    end_ts: int


_RUNNING = {0, 4}
_IDLE = {2, None}


def detect_windows(events: list[tuple[int, int | None]]) -> list[Window]:
    """events is a list of (ts_unix, sub_state) sorted by ts.

    Returns one Window per complete (start + end) session. Sessions
    that lack a clear start (already running when probe began) or
    a clear end (probe truncated mid-session) are dropped.
    """
    windows: list[Window] = []
    sorted_evs = sorted(events, key=lambda e: e[0])

    prev: int | None | object = object()  # sentinel: "no prior event"
    open_start: int | None = None
    for ts, sub in sorted_evs:
        if prev is object():
            # First event seen. Treat as "we don't know what came
            # before"; only start tracking transitions from here.
            prev = sub
            continue
        if sub == prev:
            continue  # heartbeat re-emit
        # Transition prev → sub
        if sub == 0 and prev in _IDLE:
            open_start = ts
        elif prev in _RUNNING and sub in _IDLE:
            if open_start is not None:
                windows.append(Window(start_ts=open_start, end_ts=ts))
                open_start = None
        prev = sub
    return windows
```

- [ ] **Step 5: Verify tests pass**

```bash
pytest tests/tools/test_session_windows.py -v
```

Expected: 7 PASS.

- [ ] **Step 6: ruff check**

```bash
ruff check tools/_rebuild_session_lib/ tests/tools/test_session_windows.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add tools/_rebuild_session_lib/__init__.py \
        tools/_rebuild_session_lib/session_windows.py \
        tests/tools/__init__.py \
        tests/tools/test_session_windows.py
git commit -m "rebuild_session: session_windows.detect_windows helper

Walk s2p56 task_state events to extract (start_ts, end_ts) pairs.
Drops incomplete sessions (no clear start or no clear end).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: ProbeReader — event store with s2p56 surface

**Files:**
- Create: `tools/_rebuild_session_lib/probe_reader.py`
- Create: `tests/tools/test_probe_reader.py`

The existing `backfill_session_samples.py` has the parsing logic for properties_changed events. Port it into a reusable class that exposes events for ALL slots (not just the four sample arrays), so wifi/legs/settings replay can use the same store.

- [ ] **Step 1: Read the existing backfill tool's parsing logic**

```bash
sed -n '60,110p' custom_components/dreame_a2_mower/tools/backfill_session_samples.py 2>/dev/null || \
sed -n '60,110p' tools/backfill_session_samples.py
```

(Tool path may be at repo root or under custom_components/dreame_a2_mower/. Check both.)

- [ ] **Step 2: Write failing tests**

Create `tests/tools/test_probe_reader.py`:

```python
"""Tests for tools._rebuild_session_lib.probe_reader."""
from __future__ import annotations

import json
import zoneinfo
from pathlib import Path

import pytest

from tools._rebuild_session_lib.probe_reader import ProbeReader


@pytest.fixture
def tmp_probe(tmp_path: Path) -> Path:
    """Write a tiny synthetic probe log."""
    p = tmp_path / "probe.jsonl"
    lines = [
        # mqtt_message with properties_changed: s3p1 = 80
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:00",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 3, "piid": 1, "value": 80}],
            }},
        }),
        # mqtt_message: s2p56 = {"status": [[1, 0]]}
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:01",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 2, "piid": 56,
                            "value": {"status": [[1, 0]]}}],
            }},
        }),
        # pretty: not parsed
        json.dumps({
            "type": "pretty",
            "timestamp": "2026-05-15 08:00:02",
            "text": "PRETTY ...",
        }),
    ]
    p.write_text("\n".join(lines) + "\n")
    return p


def test_probe_reader_parses_int_value(tmp_probe: Path):
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    events = r.events_for_slot(3, 1)
    assert len(events) == 1
    ts, val = events[0]
    assert val == 80


def test_probe_reader_parses_dict_value(tmp_probe: Path):
    """s2p56 value is a dict {"status": [[task_type, sub_state]]}.
    The reader should expose the raw value; downstream callers decode."""
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    events = r.events_for_slot(2, 56)
    assert len(events) == 1
    ts, val = events[0]
    assert val == {"status": [[1, 0]]}


def test_probe_reader_skips_non_properties_changed(tmp_probe: Path):
    """`pretty` and other types are ignored."""
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    # No event for slot (1, 1) since the only s1p1 mention is in pretty.
    assert r.events_for_slot(1, 1) == []


def test_probe_reader_filters_by_window(tmp_probe: Path):
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    # Window that excludes the only event for s3p1
    events = r.events_for_slot(3, 1, start_ts=0, end_ts=10)
    assert events == []
    # Window that includes it (timestamp 2026-05-15 08:00:00 UTC)
    ts_in = int(__import__("datetime").datetime(2026, 5, 15, 8, 0, tzinfo=zoneinfo.ZoneInfo("UTC")).timestamp())
    events = r.events_for_slot(3, 1, start_ts=ts_in - 60, end_ts=ts_in + 60)
    assert len(events) == 1
```

- [ ] **Step 3: Verify tests fail**

```bash
pytest tests/tools/test_probe_reader.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement**

Create `tools/_rebuild_session_lib/probe_reader.py`:

```python
"""Walk probe *.jsonl files; expose properties_changed events
indexed by (siid, piid).

Mirrors the logic in tools/backfill_session_samples.py but exposes
events for ALL slots, not just the four sample arrays. Downstream
helpers (wifi_replay, legs_replay, settings_replay) consume events
for the slots they need.
"""
from __future__ import annotations

import datetime as dt
import json
import zoneinfo
from collections import defaultdict
from typing import Any


def _parse_probe_ts(s: str, tz: zoneinfo.ZoneInfo) -> int:
    """Parse a probe-log timestamp string to unix seconds.

    Probe writes 'YYYY-MM-DD HH:MM:SS' in the configured timezone.
    """
    return int(
        dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=tz)
        .timestamp()
    )


class ProbeReader:
    """Parsed event store. One instance covers a list of probe files.

    Events are indexed by (siid, piid) and within that sorted by ts.
    Values are kept verbatim — callers decode dicts/lists/ints as
    appropriate for the slot.
    """

    def __init__(
        self,
        probe_paths: list[str],
        tz: zoneinfo.ZoneInfo = zoneinfo.ZoneInfo("UTC"),
    ) -> None:
        self._tz = tz
        # {(siid, piid): [(ts_unix, value), ...]}
        self._store: dict[tuple[int, int], list[tuple[int, Any]]] = defaultdict(list)
        for p in probe_paths:
            self._ingest(p)
        for events in self._store.values():
            events.sort(key=lambda t: t[0])

    def _ingest(self, path: str) -> None:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "mqtt_message":
                    continue
                payload = rec.get("payload") or {}
                data = payload.get("data") or {}
                if data.get("method") != "properties_changed":
                    continue
                try:
                    ts = _parse_probe_ts(rec["timestamp"], self._tz)
                except Exception:
                    continue
                for param in data.get("params") or []:
                    try:
                        slot = (int(param["siid"]), int(param["piid"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    self._store[slot].append((ts, param.get("value")))

    def events_for_slot(
        self,
        siid: int,
        piid: int,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[tuple[int, Any]]:
        """Return events for the given slot.

        If start_ts/end_ts provided, filters to events within
        [start_ts, end_ts] inclusive.
        """
        events = self._store.get((siid, piid), [])
        if start_ts is None and end_ts is None:
            return list(events)
        out: list[tuple[int, Any]] = []
        for ts, val in events:
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
            out.append((ts, val))
        return out

    def slots_seen(self) -> list[tuple[int, int]]:
        """Diagnostic: list of all slots with at least one event."""
        return sorted(self._store.keys())
```

- [ ] **Step 5: Verify tests pass**

```bash
pytest tests/tools/test_probe_reader.py -v
```

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/_rebuild_session_lib/probe_reader.py \
        tests/tools/test_probe_reader.py
git commit -m "rebuild_session: ProbeReader event store

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Sample-array backfill (4 streams)

### Task 3: `samples_replay.collect_window` (port from existing tool)

**Files:**
- Create: `tools/_rebuild_session_lib/samples_replay.py`
- Create: `tests/tools/test_samples_replay.py`

The existing tool's `collect_window` function does exactly this. Port it as a pure helper that takes a ProbeReader.

- [ ] **Step 1: Read the existing tool's collect_window**

```bash
sed -n '110,170p' tools/backfill_session_samples.py
```

- [ ] **Step 2: Write failing tests**

Create `tests/tools/test_samples_replay.py`:

```python
"""Tests for tools._rebuild_session_lib.samples_replay."""
from __future__ import annotations

import pytest

from tools._rebuild_session_lib.samples_replay import (
    backfill_samples,
    SampleStreamCounts,
)


class _StubReader:
    """Tiny ProbeReader stand-in."""
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs if (start_ts is None or t >= start_ts) and (end_ts is None or t <= end_ts)]


def test_backfill_samples_extracts_four_streams():
    reader = _StubReader({
        (3, 1): [(1000, 80), (1100, 79), (1200, 78)],     # battery
        (3, 2): [(1050, 1), (1500, 0)],                    # charging
        (2, 1): [(1000, 1), (1500, 6)],                    # state
        (2, 2): [(1100, 70), (1500, 28)],                  # error
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1100, 79], [1200, 78]]
    assert out["charging_status_samples"] == [[1050, 1], [1500, 0]]
    assert out["state_samples"] == [[1000, 1], [1500, 6]]
    assert out["error_samples"] == [[1100, 70], [1500, 28]]


def test_backfill_samples_dedups_consecutive_identical_values():
    """Mirrors live LiveMapState.append_telemetry_sample debounce."""
    reader = _StubReader({
        (3, 1): [(1000, 80), (1050, 80), (1100, 80), (1200, 79)],
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    # 80 → 80 → 80 dedups to one entry; then 79
    assert out["battery_samples"] == [[1000, 80], [1200, 79]]


def test_backfill_samples_filters_window():
    reader = _StubReader({
        (3, 1): [(500, 90), (1000, 80), (1500, 70), (2500, 60)],
    })
    out = backfill_samples(reader, start_ts=1000, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1500, 70]]


def test_backfill_samples_empty_streams():
    reader = _StubReader({})
    out = backfill_samples(reader, start_ts=1000, end_ts=2000)
    assert out == {
        "battery_samples": [],
        "charging_status_samples": [],
        "state_samples": [],
        "error_samples": [],
    }


def test_backfill_samples_skips_non_int_values():
    """A dict value (e.g., wrong-slot leak) is silently skipped."""
    reader = _StubReader({
        (3, 1): [(1000, 80), (1100, {"status": []}), (1200, 79)],
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1200, 79]]
```

- [ ] **Step 3: Verify fail**

```bash
pytest tests/tools/test_samples_replay.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement**

Create `tools/_rebuild_session_lib/samples_replay.py`:

```python
"""Backfill the four core sample arrays from a ProbeReader.

Mirrors the logic in the live coordinator's
_capture_telemetry_sample (in coordinator/_mqtt_handlers.py) and
LiveMapState.append_telemetry_sample (in live_map/state.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# (siid, piid) -> field name on raw_dict
_SLOT_TO_FIELD: dict[tuple[int, int], str] = {
    (3, 1): "battery_samples",
    (3, 2): "charging_status_samples",
    (2, 1): "state_samples",
    (2, 2): "error_samples",
}


@dataclass(frozen=True)
class SampleStreamCounts:
    field: str
    in_archive: int
    in_probe: int
    final: int


def backfill_samples(
    reader, start_ts: int, end_ts: int,
) -> dict[str, list[list[int]]]:
    """For each (siid, piid) sample slot, collect probe events in
    window, dedup adjacent identical values, return as
    `[[ts_unix, value_int], ...]`.

    Returns a dict with all four field names, even if empty.
    """
    out: dict[str, list[list[int]]] = {f: [] for f in _SLOT_TO_FIELD.values()}
    for slot, field in _SLOT_TO_FIELD.items():
        events = reader.events_for_slot(*slot, start_ts=start_ts, end_ts=end_ts)
        last_val: int | None = None
        for ts, val in events:
            try:
                v_int = int(val)
            except (TypeError, ValueError):
                continue
            if last_val is not None and last_val == v_int:
                continue
            out[field].append([int(ts), v_int])
            last_val = v_int
    return out
```

- [ ] **Step 5: Verify tests pass**

```bash
pytest tests/tools/test_samples_replay.py -v
```

Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/_rebuild_session_lib/samples_replay.py \
        tests/tools/test_samples_replay.py
git commit -m "rebuild_session: samples_replay.backfill_samples

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — charge_at_start + settings_snapshot

### Task 4: `state_replay.charge_at_start`

**Files:**
- Create: `tools/_rebuild_session_lib/state_replay.py`
- Create: `tests/tools/test_state_replay.py`

The most-recent s3p1 BEFORE start_ts. Used by the integration to record what battery the mower had when the session began.

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_state_replay.py`:

```python
"""Tests for tools._rebuild_session_lib.state_replay."""
from __future__ import annotations

from tools._rebuild_session_lib.state_replay import charge_at_start


class _StubReader:
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs if (start_ts is None or t >= start_ts) and (end_ts is None or t <= end_ts)]


def test_charge_at_start_returns_latest_before_window():
    reader = _StubReader({
        (3, 1): [(900, 90), (950, 88), (1100, 80)],  # 1100 is in-window
    })
    assert charge_at_start(reader, start_ts=1000) == 88


def test_charge_at_start_returns_none_when_no_prior_event():
    reader = _StubReader({(3, 1): [(1100, 80)]})
    assert charge_at_start(reader, start_ts=1000) is None


def test_charge_at_start_returns_none_when_no_events():
    reader = _StubReader({})
    assert charge_at_start(reader, start_ts=1000) is None


def test_charge_at_start_returns_value_at_exact_start_ts():
    """A sample exactly at start_ts counts as 'just before' (boundary)."""
    reader = _StubReader({(3, 1): [(1000, 85)]})
    assert charge_at_start(reader, start_ts=1000) == 85
```

- [ ] **Step 2: Fail**

```bash
pytest tests/tools/test_state_replay.py -v
```

- [ ] **Step 3: Implement**

```python
"""Helpers for non-time-series state derived from probe events."""
from __future__ import annotations


def charge_at_start(reader, start_ts: int) -> int | None:
    """Return the most-recent s3p1 (battery) value at or before start_ts.

    Returns None if no s3p1 event exists at or before start_ts.
    """
    events = reader.events_for_slot(3, 1, start_ts=None, end_ts=start_ts)
    if not events:
        return None
    # Reader returns sorted ascending; the last entry is the latest.
    try:
        return int(events[-1][1])
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Pass**

```bash
pytest tests/tools/test_state_replay.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/_rebuild_session_lib/state_replay.py \
        tests/tools/test_state_replay.py
git commit -m "rebuild_session: state_replay.charge_at_start helper"
```

---

### Task 5: `settings_replay.snapshot_at_start`

**Files:**
- Modify: `tools/_rebuild_session_lib/state_replay.py` (add settings function alongside)
- Modify: `tests/tools/test_state_replay.py`

Settings snapshot in the live integration captures the latest values of s5p107, s6p1, s2p51 at session start.

- [ ] **Step 1: Inspect what the live integration writes for settings_snapshot**

```bash
grep -nB 2 -A 10 'settings_snapshot' custom_components/dreame_a2_mower/coordinator/_session.py | head -40
grep -nB 2 -A 10 'settings_snapshot' custom_components/dreame_a2_mower/coordinator/_property_apply.py | head -30
```

Identify which slots feed it.

- [ ] **Step 2: Write failing tests**

Append to `tests/tools/test_state_replay.py`:

```python
from tools._rebuild_session_lib.state_replay import settings_snapshot_at_start


def test_settings_snapshot_picks_latest_per_slot_before_start():
    reader = _StubReader({
        (5, 107): [(900, 100), (950, 105)],  # latest before start = 105
        (6, 1):   [(800, 1)],                  # latest before start = 1
        (2, 51):  [(1100, 5)],                 # AFTER start — ignored
    })
    snap = settings_snapshot_at_start(reader, start_ts=1000)
    assert snap.get("s5p107") == 105
    assert snap.get("s6p1") == 1
    assert "s2p51" not in snap


def test_settings_snapshot_empty_when_no_prior_events():
    reader = _StubReader({})
    assert settings_snapshot_at_start(reader, start_ts=1000) == {}


def test_settings_snapshot_handles_dict_values():
    """s6p1 carries a dict payload; preserve as-is (decode is downstream)."""
    reader = _StubReader({(6, 1): [(900, {"some": "dict"})]})
    snap = settings_snapshot_at_start(reader, start_ts=1000)
    assert snap.get("s6p1") == {"some": "dict"}
```

- [ ] **Step 3: Implement (append to state_replay.py)**

```python
# Slots whose latest at-or-before-start value defines the
# settings_snapshot. Mirrors the slots the live integration's
# coordinator/_property_apply.py treats as settings tripwires.
_SETTINGS_SLOTS: list[tuple[int, int]] = [
    (5, 105),
    (5, 106),
    (5, 107),
    (6, 1),
    (2, 51),
    (1, 53),
]


def settings_snapshot_at_start(reader, start_ts: int) -> dict[str, object]:
    """For each settings tripwire slot, return its most-recent value
    at or before start_ts.

    Returns dict keyed by 's<siid>p<piid>'. Slots with no prior event
    are omitted (rather than mapped to None) so the snapshot only
    contains real captured values.
    """
    snap: dict[str, object] = {}
    for siid, piid in _SETTINGS_SLOTS:
        events = reader.events_for_slot(siid, piid, start_ts=None, end_ts=start_ts)
        if not events:
            continue
        snap[f"s{siid}p{piid}"] = events[-1][1]
    return snap
```

(Adjust `_SETTINGS_SLOTS` based on what Step 1 grep found — the spec list above is the candidate set per the inventory; update if the integration uses a different set.)

- [ ] **Step 4: Run all state_replay tests**

```bash
pytest tests/tools/test_state_replay.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/_rebuild_session_lib/state_replay.py \
        tests/tools/test_state_replay.py
git commit -m "rebuild_session: settings_snapshot_at_start helper"
```

---

## Phase 4 — wifi_samples reconstruction

### Task 6: `wifi_replay.reconstruct_wifi_samples`

**Files:**
- Create: `tools/_rebuild_session_lib/wifi_replay.py`
- Create: `tests/tools/test_wifi_replay.py`

Replay logic: for each s1p1 (heartbeat) event, decode it via `protocol.heartbeat.decode_s1p1` to extract `wifi_rssi_dbm`. Pair with the most-recent position from s1p4 events. Apply the live `LiveMapState.append_wifi_sample` dedup (25cm-radius at same RSSI).

- [ ] **Step 1: Confirm decoder import paths**

```bash
ls custom_components/dreame_a2_mower/protocol/heartbeat.py
grep -n 'def decode_s1p1\|wifi_rssi_dbm' custom_components/dreame_a2_mower/protocol/heartbeat.py
```

The tool will need to add the repo root to sys.path so `from custom_components...` works. The s1p1 payload in probe events is the raw bytes (or a hex string?). Confirm format:

```bash
grep -nB 1 -A 3 's1p1' /data/claude/homeassistant/probe_log_20260514_211550.jsonl | head -20
# Or directly look at one mqtt_message for s1p1
python3 -c "
import json
for line in open('/data/claude/homeassistant/probe_log_20260514_211550.jsonl'):
    d = json.loads(line)
    if d.get('type') != 'mqtt_message': continue
    for p in (d.get('payload') or {}).get('data', {}).get('params') or []:
        if (p.get('siid'), p.get('piid')) == (1, 1):
            print(repr(p.get('value'))[:200]); break
    else: continue
    break
"
```

The s1p1 value is likely a base64-encoded blob string. The integration's `_coerce_blob` helper (in coordinator/_mqtt_handlers.py) handles this. Either:
- Import `_coerce_blob` directly, or
- Implement a thin tool-side equivalent: `base64.b64decode(value)` if value is a str, else assume raw bytes.

Check the coerce helper:

```bash
grep -nB 2 -A 15 'def _coerce_blob' custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py
```

- [ ] **Step 2: Write failing tests**

Create `tests/tools/test_wifi_replay.py`:

```python
"""Tests for tools._rebuild_session_lib.wifi_replay."""
from __future__ import annotations

import base64
import pytest

from tools._rebuild_session_lib.wifi_replay import reconstruct_wifi_samples


class _StubReader:
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs if (start_ts is None or t >= start_ts) and (end_ts is None or t <= end_ts)]


def _hb_blob_with_rssi(rssi: int) -> str:
    """Build a 20-byte heartbeat blob with the given RSSI byte
    (signed at index 17 per protocol/heartbeat.py)."""
    blob = bytearray(20)
    blob[17] = rssi & 0xFF  # signed byte; both signs OK for these values
    return base64.b64encode(bytes(blob)).decode()


def test_reconstruct_empty_when_no_heartbeats():
    reader = _StubReader({})
    out = reconstruct_wifi_samples(reader, start_ts=1000, end_ts=2000)
    assert out == []


def test_reconstruct_pairs_heartbeat_with_position():
    """Heartbeat at t=1100 should pair with the most recent s1p4
    position at t=1050."""
    # Stub s1p4 events with values that decode to (x_m, y_m). For the
    # test, we mock the s1p4 decoder to read .x_m and .y_m off the value
    # directly — see implementation note in Step 3.
    reader = _StubReader({
        (1, 1): [(1100, _hb_blob_with_rssi(-70))],
        (1, 4): [(1050, b"FAKE_POSITION_BLOB")],
    })
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: (1.5, 2.5),  # test injection
    )
    assert len(out) == 1
    x, y, rssi, ts = out[0]
    assert (x, y, rssi, ts) == (1.5, 2.5, -70, 1100)


def test_reconstruct_skips_heartbeat_with_no_prior_position():
    """A heartbeat that fires before any s1p4 position — no pair, skip."""
    reader = _StubReader({
        (1, 1): [(1100, _hb_blob_with_rssi(-70))],
        (1, 4): [(1200, b"FAKE")],   # position is AFTER heartbeat
    })
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: (1.0, 2.0),
    )
    assert out == []


def test_reconstruct_dedups_within_25cm_radius_at_same_rssi():
    """Two heartbeats both at RSSI -70 with positions within 25 cm
    should dedup to one sample."""
    reader = _StubReader({
        (1, 1): [
            (1100, _hb_blob_with_rssi(-70)),
            (1110, _hb_blob_with_rssi(-70)),
        ],
        (1, 4): [(1050, b"BLOB_A"), (1108, b"BLOB_B")],
    })
    # Both decode to nearly-identical positions
    pos_iter = iter([(1.0, 2.0), (1.001, 2.001), (1.002, 2.002)])
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: next(pos_iter),
    )
    # Second heartbeat dedups (same RSSI, position within 25cm)
    assert len(out) == 1
```

- [ ] **Step 3: Implement**

Create `tools/_rebuild_session_lib/wifi_replay.py`:

```python
"""Reconstruct wifi_samples from probe-captured s1p1 (heartbeat)
events paired with s1p4 (position) events.

Mirrors the live integration's logic in
coordinator/_mqtt_handlers.py around line 197 (the
append_wifi_sample call site).
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any, Callable


def _coerce_blob(value: Any) -> bytes | None:
    """Probe stores blobs as base64 strings; live wire is bytes."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            return None
    return None


def _ensure_decoders_importable() -> None:
    """Add repo root to sys.path so we can import the integration's
    decoders. Called lazily from reconstruct_wifi_samples."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _default_position_decoder(blob: bytes) -> tuple[float, float] | None:
    """Decode an s1p4 blob to (x_m, y_m). Lazy-import the integration's
    _telemetry decoder."""
    _ensure_decoders_importable()
    from custom_components.dreame_a2_mower.protocol import _telemetry
    try:
        if len(blob) in (
            _telemetry.FRAME_LENGTH_BEACON,
            _telemetry.FRAME_LENGTH_BUILDING,
        ):
            decoded = _telemetry.decode_s1p4_position(blob)
            return (decoded.x_m, decoded.y_m)
        # Full frame
        decoded = _telemetry.decode_s1p4(blob)
        return (decoded.x_m, decoded.y_m)
    except Exception:
        return None


def _heartbeat_rssi(blob: bytes) -> int | None:
    """Decode an s1p1 heartbeat blob and extract wifi_rssi_dbm."""
    _ensure_decoders_importable()
    from custom_components.dreame_a2_mower.protocol import heartbeat as _hb
    try:
        return _hb.decode_s1p1(blob).wifi_rssi_dbm
    except Exception:
        return None


def reconstruct_wifi_samples(
    reader,
    start_ts: int,
    end_ts: int,
    *,
    _position_decoder: Callable[[bytes], tuple[float, float] | None] | None = None,
    _heartbeat_decoder: Callable[[bytes], int | None] | None = None,
) -> list[tuple[float, float, int, int]]:
    """Reconstruct wifi_samples for a session window.

    Returns a list of (x_m, y_m, rssi_dbm, ts_unix) tuples matching
    the shape `LiveMapState.wifi_samples` produces.

    The two `_*_decoder` kwargs exist for unit tests; production
    callers leave them None and the live integration's decoders are
    used.
    """
    pos_dec = _position_decoder or _default_position_decoder
    hb_dec = _heartbeat_decoder or _heartbeat_rssi

    # Build a sorted timeline of (ts, slot, blob) so we can walk
    # in order and maintain "most recent position".
    s1p1_events = reader.events_for_slot(1, 1, start_ts=start_ts, end_ts=end_ts)
    s1p4_events = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)

    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p1_events:
        timeline.append((ts, "hb", val))
    for ts, val in s1p4_events:
        timeline.append((ts, "pos", val))
    timeline.sort(key=lambda t: t[0])

    samples: list[tuple[float, float, int, int]] = []
    last_pos: tuple[float, float] | None = None
    for ts, kind, val in timeline:
        if kind == "pos":
            blob = _coerce_blob(val)
            if blob is None:
                continue
            decoded = pos_dec(blob)
            if decoded is not None:
                last_pos = decoded
        else:  # heartbeat
            if last_pos is None:
                continue
            blob = _coerce_blob(val)
            if blob is None:
                continue
            rssi = hb_dec(blob)
            if rssi is None:
                continue
            new_sample = (last_pos[0], last_pos[1], int(rssi), int(ts))
            # Dedup mirroring LiveMapState.append_wifi_sample:
            # within 25 cm radius at the same RSSI.
            if samples:
                lx, ly, lr, _lts = samples[-1]
                if lr == rssi:
                    dx = new_sample[0] - lx
                    dy = new_sample[1] - ly
                    if (dx * dx + dy * dy) < 0.0625:  # 25 cm squared
                        continue
            samples.append(new_sample)
    return samples
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/tools/test_wifi_replay.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/_rebuild_session_lib/wifi_replay.py \
        tests/tools/test_wifi_replay.py
git commit -m "rebuild_session: wifi_replay.reconstruct_wifi_samples

Replay s1p1 heartbeat + s1p4 position events; pair via 'most-recent
position' rule; apply 25cm-radius same-RSSI dedup matching
LiveMapState.append_wifi_sample.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — legs reconstruction

### Task 7: `legs_replay.reconstruct_legs`

**Files:**
- Create: `tools/_rebuild_session_lib/legs_replay.py`
- Create: `tests/tools/test_legs_replay.py`

Replay logic: walk s1p4 events for positions; walk s2p56 transitions for `4 → 0` (begin_leg). Apply the live `LiveMapState.append_point` rules (5m pen-up jump filter + dedup).

- [ ] **Step 1: Inspect live append_point**

```bash
sed -n '111,160p' custom_components/dreame_a2_mower/live_map/state.py
```

- [ ] **Step 2: Write failing tests**

Create `tests/tools/test_legs_replay.py`:

```python
"""Tests for tools._rebuild_session_lib.legs_replay."""
from __future__ import annotations

import pytest

from tools._rebuild_session_lib.legs_replay import reconstruct_legs


class _StubReader:
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs if (start_ts is None or t >= start_ts) and (end_ts is None or t <= end_ts)]


def test_reconstruct_legs_single_leg():
    """One leg with a few points, no s2p56 transitions."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    reader = _StubReader({
        (1, 4): [(100, b"A"), (110, b"B"), (120, b"C")],
        (2, 56): [],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: next(pos),
    )
    assert len(legs) == 1
    assert legs[0] == [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]


def test_reconstruct_legs_pen_up_jump_starts_new_leg():
    """A jump > 5 m should start a new leg (matches live algorithm)."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (10.0, 0.0)])  # last is 9m jump
    reader = _StubReader({
        (1, 4): [(100, b"A"), (110, b"B"), (120, b"C")],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: next(pos),
    )
    assert len(legs) == 2
    assert legs[0] == [[0.0, 0.0], [1.0, 0.0]]
    assert legs[1] == [[10.0, 0.0]]


def test_reconstruct_legs_recharge_round_trip_starts_new_leg():
    """s2p56 transition 4→0 (paused→running) should start a new leg
    even without a pen-up jump."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    reader = _StubReader({
        (1, 4): [(100, b"A"), (200, b"B"), (300, b"C")],
        # Paused at 150, resumed at 250 — leg 2 starts at the next position
        (2, 56): [
            (50,  {"status": [[1, 0]]}),  # initial running
            (150, {"status": [[1, 4]]}),  # pause
            (250, {"status": [[1, 0]]}),  # resume → triggers new leg
        ],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=400,
        _position_decoder=lambda b: next(pos),
    )
    # Leg 1: positions before resume = [(0,0)] (only the t=100 one)
    # Leg 2: positions after resume = [(1,0), (2,0)]
    assert len(legs) == 2
    assert legs[0] == [[0.0, 0.0]]
    assert legs[1] == [[1.0, 0.0], [2.0, 0.0]]


def test_reconstruct_legs_empty():
    reader = _StubReader({})
    assert reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: (0.0, 0.0),
    ) == []
```

- [ ] **Step 3: Implement**

Create `tools/_rebuild_session_lib/legs_replay.py`:

```python
"""Reconstruct legs from probe s1p4 (position) + s2p56 (task_state)
events.

Mirrors the live integration:
  - Each s2p56 transition `4 → 0` (paused → running) triggers
    begin_leg in LiveMapState.
  - Each s1p4 position is appended via append_point, with:
      * Pen-up filter: jump > 5m starts a new leg
      * Dedup: skip if very close to last (~10cm)
"""
from __future__ import annotations

from typing import Any, Callable

from .wifi_replay import _coerce_blob, _default_position_decoder


_PEN_UP_SQ = 25.0  # 5m squared
_DEDUP_SQ = 0.01   # 10cm squared


def _extract_sub_state(value: Any) -> int | None:
    """s2p56 value is {"status": [[task_type, sub_state]]} or {"status": []}."""
    if not isinstance(value, dict):
        return None
    status = value.get("status") or []
    if not status:
        return None
    first = status[0]
    if not isinstance(first, list) or len(first) < 2:
        return None
    try:
        return int(first[1])
    except (TypeError, ValueError):
        return None


def reconstruct_legs(
    reader,
    start_ts: int,
    end_ts: int,
    *,
    _position_decoder: Callable[[bytes], tuple[float, float] | None] | None = None,
) -> list[list[list[float]]]:
    """Reconstruct legs for a session window.

    Returns a list of legs, where each leg is a list of [x_m, y_m] points.
    """
    pos_dec = _position_decoder or _default_position_decoder

    s1p4 = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)
    s2p56 = reader.events_for_slot(2, 56, start_ts=start_ts, end_ts=end_ts)

    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p4:
        timeline.append((ts, "pos", val))
    for ts, val in s2p56:
        timeline.append((ts, "task", val))
    timeline.sort(key=lambda t: t[0])

    legs: list[list[list[float]]] = [[]]
    prev_sub: int | None = None
    for ts, kind, val in timeline:
        if kind == "task":
            sub = _extract_sub_state(val)
            if sub is None:
                continue
            # 4 → 0 means recharge round-trip just completed; start new leg
            if prev_sub == 4 and sub == 0 and legs[-1]:
                legs.append([])
            prev_sub = sub
            continue
        # position
        blob = _coerce_blob(val)
        if blob is None:
            continue
        decoded = pos_dec(blob)
        if decoded is None:
            continue
        x, y = float(decoded[0]), float(decoded[1])
        cur = legs[-1]
        if cur:
            lx, ly = cur[-1]
            dx = x - lx
            dy = y - ly
            sq = dx * dx + dy * dy
            if sq > _PEN_UP_SQ:
                # Pen-up jump → new leg
                legs.append([[x, y]])
                continue
            if sq < _DEDUP_SQ:
                continue  # dedup: too close to last point
        cur.append([x, y])

    # Drop trailing empty leg
    if legs and not legs[-1]:
        legs.pop()
    # Drop leading empty leg if no points were ever appended
    if legs and not legs[0]:
        legs.pop(0)
    return legs
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/tools/test_legs_replay.py -v
```

Expected: 4 PASS. If `test_reconstruct_legs_recharge_round_trip_starts_new_leg` fails because the boundary semantics differ, adjust — read the live `LiveMapState.begin_leg` and the call site in `_session.py` carefully and align.

- [ ] **Step 5: Commit**

```bash
git add tools/_rebuild_session_lib/legs_replay.py \
        tests/tools/test_legs_replay.py
git commit -m "rebuild_session: legs_replay.reconstruct_legs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — HA fetch + push

### Task 8: `ha_archive.HAArchiveFetcher`

**Files:**
- Create: `tools/_rebuild_session_lib/ha_archive.py`
- Create: `tests/tools/test_ha_archive.py` (mocked SCP)

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_ha_archive.py`:

```python
"""Tests for tools._rebuild_session_lib.ha_archive."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tools._rebuild_session_lib.ha_archive import (
    HAArchiveFetcher,
    parse_archive_filename,
)


def test_parse_archive_filename_with_md5():
    name = "2026-05-16_1778893682_7bff1b02.json"
    parsed = parse_archive_filename(name)
    assert parsed.date == "2026-05-16"
    assert parsed.end_ts == 1778893682
    assert parsed.md5 == "7bff1b02"
    assert parsed.is_recovered is False


def test_parse_archive_filename_recovered():
    name = "2026-04-20_1776681188_rec_6fe0.json"
    parsed = parse_archive_filename(name)
    assert parsed.date == "2026-04-20"
    assert parsed.end_ts == 1776681188
    assert parsed.md5 == "rec_6fe0"
    assert parsed.is_recovered is True


def test_parse_archive_filename_returns_none_on_garbage():
    assert parse_archive_filename("not_a_session.txt") is None


def test_fetcher_list_archives_parses_remote_ls(tmp_path):
    # Mock subprocess to simulate sshpass+ssh ls output
    fake_ls = (
        "2026-05-15_1778893682_7bff1b02.json\n"
        "2026-04-20_1776681188_rec_6fe0.json\n"
        "garbage.txt\n"
    )
    with patch(
        "tools._rebuild_session_lib.ha_archive._run_ssh",
        return_value=fake_ls,
    ):
        f = HAArchiveFetcher(host="x", user="x", password="x", remote_dir="/r")
        archives = f.list_archives()
    assert len(archives) == 2
    assert archives[0].end_ts == 1778893682


def test_fetcher_dry_run_does_not_scp(tmp_path):
    """In dry-run mode, push() returns the would-be path but doesn't
    actually invoke scp."""
    f = HAArchiveFetcher(host="x", user="x", password="x", remote_dir="/r", dry_run=True)
    with patch("tools._rebuild_session_lib.ha_archive._run_scp") as mock_scp:
        f.push_archive(local_path=tmp_path / "x.json", remote_filename="x.json")
        mock_scp.assert_not_called()
```

- [ ] **Step 2: Implement**

Create `tools/_rebuild_session_lib/ha_archive.py`:

```python
"""SCP-based HA session archive fetcher and pusher.

Uses sshpass + ssh + scp behind the scenes. Designed for the
dev-box workflow where credentials live in a local file.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchiveFilename:
    date: str           # "YYYY-MM-DD"
    end_ts: int
    md5: str            # 8-char hex OR "rec_<4-8 char>"
    raw: str            # original filename
    is_recovered: bool  # True if md5 starts with "rec_"


_FILENAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_(\d+)_(rec_[0-9a-f]+|[0-9a-f]{8})\.json$"
)


def parse_archive_filename(name: str) -> ArchiveFilename | None:
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    date, end_ts_s, md5 = m.groups()
    return ArchiveFilename(
        date=date,
        end_ts=int(end_ts_s),
        md5=md5,
        raw=name,
        is_recovered=md5.startswith("rec_"),
    )


def _run_ssh(cmd: list[str]) -> str:
    """Run ssh subprocess, return stdout. Raises on non-zero exit."""
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return res.stdout


def _run_scp(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


class HAArchiveFetcher:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        remote_dir: str,
        dry_run: bool = False,
    ) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.remote_dir = remote_dir
        self.dry_run = dry_run

    def list_archives(self) -> list[ArchiveFilename]:
        cmd = [
            "sshpass", "-p", self.password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.user}@{self.host}",
            f"ls {self.remote_dir}",
        ]
        out = _run_ssh(cmd)
        archives: list[ArchiveFilename] = []
        for line in out.splitlines():
            parsed = parse_archive_filename(line.strip())
            if parsed is not None:
                archives.append(parsed)
        return sorted(archives, key=lambda a: a.end_ts)

    def fetch_archive(self, remote_filename: str, local_path: Path) -> None:
        cmd = [
            "sshpass", "-p", self.password,
            "scp", "-o", "StrictHostKeyChecking=no",
            f"{self.user}@{self.host}:{self.remote_dir}/{remote_filename}",
            str(local_path),
        ]
        _run_scp(cmd)

    def push_archive(self, local_path: Path, remote_filename: str) -> None:
        if self.dry_run:
            return
        cmd = [
            "sshpass", "-p", self.password,
            "scp", "-o", "StrictHostKeyChecking=no",
            str(local_path),
            f"{self.user}@{self.host}:{self.remote_dir}/{remote_filename}",
        ]
        _run_scp(cmd)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/tools/test_ha_archive.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tools/_rebuild_session_lib/ha_archive.py \
        tests/tools/test_ha_archive.py
git commit -m "rebuild_session: HAArchiveFetcher (SCP read/write)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7 — Main tool: orchestrator + CLI

### Task 9: `rebuild_session.py` orchestrator + CLI

**Files:**
- Create: `tools/rebuild_session.py`
- Create: `tests/tools/test_rebuild_session_e2e.py` (smoke test)

- [ ] **Step 1: Write the smoke test**

Create `tests/tools/test_rebuild_session_e2e.py`:

```python
"""Smoke test: rebuild a session against synthetic probe + archive."""
from __future__ import annotations

import json
import zoneinfo
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.rebuild_session import rebuild_one_session
from tools._rebuild_session_lib.probe_reader import ProbeReader


def _write_synthetic_probe(path: Path):
    """Tiny probe log: one battery sample + one state transition."""
    lines = [
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:00",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 3, "piid": 1, "value": 80}],
            }},
        }),
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:01",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 2, "piid": 1, "value": 1}],
            }},
        }),
    ]
    path.write_text("\n".join(lines) + "\n")


def test_rebuild_one_session_adds_to_empty_archive(tmp_path: Path):
    probe_path = tmp_path / "probe.jsonl"
    _write_synthetic_probe(probe_path)
    reader = ProbeReader([str(probe_path)], tz=zoneinfo.ZoneInfo("UTC"))

    archive = {
        "start": int(__import__("datetime").datetime(
            2026, 5, 15, 7, 0, tzinfo=zoneinfo.ZoneInfo("UTC")
        ).timestamp()),
        "end": int(__import__("datetime").datetime(
            2026, 5, 15, 9, 0, tzinfo=zoneinfo.ZoneInfo("UTC")
        ).timestamp()),
        "battery_samples": [],
        "state_samples": [],
        "wifi_samples": [],
        "legs": [],
    }
    new_archive, diff = rebuild_one_session(reader, archive)
    assert len(new_archive["battery_samples"]) >= 1
    assert len(new_archive["state_samples"]) >= 1
    # cloud-only fields preserved/initialized
    assert "md5" not in archive or new_archive["md5"] == archive["md5"]
    assert diff["battery_samples"]["added"] >= 1
```

- [ ] **Step 2: Implement the orchestrator + CLI**

Create `tools/rebuild_session.py`:

```python
#!/usr/bin/env python3
"""rebuild_session.py — end-to-end session rebuild from probe logs.

See docs/superpowers/specs/2026-05-16-session-rebuild-tool-design.md
for the full design.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import sys
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools._rebuild_session_lib.ha_archive import (
    ArchiveFilename,
    HAArchiveFetcher,
    parse_archive_filename,
)
from tools._rebuild_session_lib.legs_replay import reconstruct_legs
from tools._rebuild_session_lib.probe_reader import ProbeReader
from tools._rebuild_session_lib.samples_replay import backfill_samples
from tools._rebuild_session_lib.session_windows import (
    Window,
    detect_windows,
)
from tools._rebuild_session_lib.state_replay import (
    charge_at_start,
    settings_snapshot_at_start,
)
from tools._rebuild_session_lib.wifi_replay import reconstruct_wifi_samples


@dataclass
class StreamDiff:
    in_archive: int
    in_probe: int
    added: int
    final: int


def _diff_count(archive_list, probe_list) -> StreamDiff:
    a = len(archive_list or [])
    p = len(probe_list or [])
    # Final = union (probe is the complete source; archive entries
    # not in probe stay because they may be real). Use (ts, *) dedup.
    seen = {(s[0], tuple(s[1:]) if len(s) > 1 else ()) for s in (archive_list or [])}
    union = list(archive_list or [])
    for s in probe_list or []:
        key = (s[0], tuple(s[1:]) if len(s) > 1 else ())
        if key in seen:
            continue
        union.append(s)
        seen.add(key)
    union.sort(key=lambda s: s[0])
    return StreamDiff(in_archive=a, in_probe=p, added=len(union) - a, final=len(union)), union


def rebuild_one_session(
    reader: ProbeReader,
    archive: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild a single session.

    Returns (new_archive, diff_report) where diff_report is a dict
    of stream_name -> {in_archive, in_probe, added, final}.
    """
    start_ts = int(archive["start"])
    end_ts = int(archive["end"])

    new = dict(archive)
    diff: dict[str, Any] = {}

    # 4 sample arrays
    samples = backfill_samples(reader, start_ts, end_ts)
    for field, probe_list in samples.items():
        d, union = _diff_count(archive.get(field) or [], probe_list)
        new[field] = union
        diff[field] = d.__dict__

    # wifi
    wifi_probe = reconstruct_wifi_samples(reader, start_ts, end_ts)
    wifi_probe_list = [list(t) for t in wifi_probe]
    d, union = _diff_count(archive.get("wifi_samples") or [], wifi_probe_list)
    new["wifi_samples"] = union
    diff["wifi_samples"] = d.__dict__

    # legs (different shape — list of lists of [x,y]; can't dedup the
    # same way; replace if probe has more total points)
    legs_probe = reconstruct_legs(reader, start_ts, end_ts)
    archive_legs = archive.get("legs") or []
    archive_pts = sum(len(leg) for leg in archive_legs)
    probe_pts = sum(len(leg) for leg in legs_probe)
    if probe_pts > archive_pts:
        new["legs"] = legs_probe
        diff["legs"] = {
            "in_archive": archive_pts, "in_probe": probe_pts,
            "added": probe_pts - archive_pts, "final": probe_pts,
        }
    else:
        diff["legs"] = {
            "in_archive": archive_pts, "in_probe": probe_pts,
            "added": 0, "final": archive_pts,
        }

    # charge_at_start
    cas_probe = charge_at_start(reader, start_ts)
    cas_archive = archive.get("charge_at_start")
    if cas_archive is None and cas_probe is not None:
        new["charge_at_start"] = cas_probe
        diff["charge_at_start"] = {
            "in_archive": "None", "in_probe": cas_probe,
            "added": 1, "final": cas_probe,
        }
    else:
        diff["charge_at_start"] = {
            "in_archive": cas_archive, "in_probe": cas_probe,
            "added": 0, "final": cas_archive,
        }

    # settings_snapshot
    snap_probe = settings_snapshot_at_start(reader, start_ts)
    snap_archive = archive.get("settings_snapshot") or {}
    if snap_archive in (None, {}) and snap_probe:
        new["settings_snapshot"] = snap_probe
        diff["settings_snapshot"] = {
            "in_archive": 0, "in_probe": len(snap_probe),
            "added": len(snap_probe), "final": len(snap_probe),
        }
    else:
        diff["settings_snapshot"] = {
            "in_archive": len(snap_archive) if snap_archive else 0,
            "in_probe": len(snap_probe),
            "added": 0,
            "final": len(snap_archive) if snap_archive else 0,
        }

    return new, diff


def _print_diff(window: Window, archive_filename: str | None, diff: dict[str, Any], improved: bool) -> None:
    start_str = dt.datetime.fromtimestamp(window.start_ts).isoformat()
    print(f"=== Session {start_str} ({window.start_ts} → {window.end_ts}) ===")
    print(f"  archive: {archive_filename or '(synthesizing new)'}")
    print(f"  {'archive':>5}  {'probe':>5}  {'added':>5}  {'final':>5}")
    for k, v in diff.items():
        ia = v.get("in_archive", "")
        ip = v.get("in_probe", "")
        ad = v.get("added", "")
        fn = v.get("final", "")
        print(f"  {ia!s:>5}  {ip!s:>5}  {ad!s:>5}  {fn!s:>5}  {k}")
    if improved:
        total_added = sum(int(v.get("added", 0) or 0) for v in diff.values() if isinstance(v.get("added"), int))
        print(f"  decision: copy back to HA ({total_added} new datapoints)")
    else:
        print(f"  decision: skip (no improvements)")


def _hash_filename(start_ts: int, end_ts: int) -> str:
    h = hashlib.sha1(f"{start_ts}-{end_ts}".encode()).hexdigest()[:4]
    return f"rec_{h}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--session-start", type=str, help="ISO8601 or epoch seconds")
    grp.add_argument("--bulk", action="store_true")
    parser.add_argument(
        "--probe-glob",
        default="/data/claude/homeassistant/probe_log_*.jsonl",
    )
    parser.add_argument("--tz", default="Europe/Oslo")
    parser.add_argument(
        "--ha-cred-file",
        default="/data/claude/homeassistant/ha-credentials.txt",
    )
    parser.add_argument(
        "--ha-sessions-dir", default="/config/dreame_a2_mower/sessions",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    tz = zoneinfo.ZoneInfo(args.tz)
    probes = sorted(glob.glob(args.probe_glob))
    if not probes:
        print(f"No probe logs match {args.probe_glob}", file=sys.stderr)
        return 2

    print(f"Loading {len(probes)} probe file(s)...", file=sys.stderr)
    reader = ProbeReader(probes, tz=tz)

    # HA credentials
    cred_lines = Path(args.ha_cred_file).read_text().strip().split("\n")
    host, user, password = cred_lines[0], cred_lines[1], cred_lines[2]
    fetcher = HAArchiveFetcher(
        host=host, user=user, password=password,
        remote_dir=args.ha_sessions_dir, dry_run=args.dry_run,
    )

    # Collect probe-derived session windows
    s2p56 = reader.events_for_slot(2, 56)
    sub_state_events = []
    for ts, val in s2p56:
        sub = None
        if isinstance(val, dict):
            status = val.get("status") or []
            if status and isinstance(status[0], list) and len(status[0]) >= 2:
                try:
                    sub = int(status[0][1])
                except (TypeError, ValueError):
                    sub = None
        sub_state_events.append((ts, sub))
    windows = detect_windows(sub_state_events)
    print(f"Found {len(windows)} session windows in probe data.", file=sys.stderr)

    # If single mode: filter to one
    if args.session_start:
        try:
            target = int(args.session_start)
        except ValueError:
            target = int(dt.datetime.fromisoformat(args.session_start).timestamp())
        windows = [w for w in windows if abs(w.start_ts - target) <= 300]
        if not windows:
            print(f"No probe-detected window matches {target} ±300s", file=sys.stderr)
            return 1

    archives = fetcher.list_archives()
    archive_by_end = {a.end_ts: a for a in archives}

    # Track which archives we visited (so we can list "no probe coverage" at the end)
    visited_end_ts: set[int] = set()
    rebuilt_count = skipped_count = failed_count = 0

    for w in windows:
        archive_meta = archive_by_end.get(w.end_ts)
        local_archive: dict[str, Any]
        local_filename: str
        if archive_meta is not None:
            visited_end_ts.add(archive_meta.end_ts)
            tmp = Path(f"/tmp/rebuild_{archive_meta.end_ts}.json")
            try:
                fetcher.fetch_archive(archive_meta.raw, tmp)
                local_archive = json.loads(tmp.read_text())
                local_filename = archive_meta.raw
            except Exception as ex:
                print(f"  failed to fetch {archive_meta.raw}: {ex}", file=sys.stderr)
                failed_count += 1
                continue
        else:
            local_archive = {"start": w.start_ts, "end": w.end_ts}
            local_filename = f"{dt.datetime.fromtimestamp(w.start_ts).strftime('%Y-%m-%d')}_{w.end_ts}_{_hash_filename(w.start_ts, w.end_ts)}.json"

        try:
            new_archive, diff = rebuild_one_session(reader, local_archive)
        except Exception as ex:
            print(f"  rebuild failed for {local_filename}: {ex}", file=sys.stderr)
            failed_count += 1
            continue

        improved = any(int(v.get("added", 0) or 0) > 0 for v in diff.values() if isinstance(v.get("added"), int))
        _print_diff(w, local_filename, diff, improved)
        if improved:
            tmp_out = Path(f"/tmp/rebuild_{w.end_ts}_new.json")
            tmp_out.write_text(json.dumps(new_archive, indent=2))
            try:
                fetcher.push_archive(tmp_out, local_filename)
                rebuilt_count += 1
            except Exception as ex:
                print(f"  push failed: {ex}", file=sys.stderr)
                failed_count += 1
        else:
            skipped_count += 1

    # End-of-bulk summary
    print()
    print(f"=== Summary ===")
    print(f"Sessions in probe windows: {len(windows)}")
    print(f"  Backfilled: {rebuilt_count}")
    print(f"  Skipped:    {skipped_count}")
    print(f"  Failed:     {failed_count}")
    uncovered = [a for a in archives if a.end_ts not in visited_end_ts]
    if uncovered:
        print()
        print(f"Sessions in HA archive with NO probe coverage: {len(uncovered)}")
        for a in uncovered:
            print(f"  {args.ha_sessions_dir}/{a.raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run smoke test**

```bash
pytest tests/tools/test_rebuild_session_e2e.py -v
```

- [ ] **Step 4: Real smoke test against the 19h session (dry-run)**

```bash
chmod +x tools/rebuild_session.py
python3 tools/rebuild_session.py --session-start 1778824800 --dry-run
```

Expected: per-session diff showing significant additions to battery/state/error/wifi streams. SCP push is skipped.

- [ ] **Step 5: Commit**

```bash
git add tools/rebuild_session.py tests/tools/test_rebuild_session_e2e.py
git commit -m "rebuild_session: orchestrator + CLI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 8 — Cleanup + verification

### Task 10: Delete superseded backfill_session_samples.py + verify state_partition

**Files:**
- Delete: `tools/backfill_session_samples.py`
- Verify: `tools/state_partition.py` against rebuilt 19h session

- [ ] **Step 1: Confirm the new tool covers everything the old one did**

```bash
diff <(grep -oE 'WATCH_SLOTS|SLOT_TO_FIELD|backfill|charge_at_start' tools/backfill_session_samples.py | sort -u) \
     <(grep -oE 'backfill_samples|charge_at_start|SLOT_TO_FIELD' tools/_rebuild_session_lib/*.py | sort -u)
```

Sanity check — both tools handle the same 4 streams + charge_at_start.

- [ ] **Step 2: Delete the old tool**

```bash
git rm tools/backfill_session_samples.py
```

- [ ] **Step 3: Run a real rebuild + state_partition cross-check**

```bash
# Wet-mode rebuild of the 19h session
python3 tools/rebuild_session.py --session-start 1778824800
# Pull the now-updated session JSON
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
  "$USER@$HOST:/config/dreame_a2_mower/sessions/2026-05-16_1778893682_7bff1b02.json" \
  /tmp/sess_19h_rebuilt.json
# Compare time-breakdown
python3 tools/state_partition.py /tmp/sess_19h_rebuilt.json \
  /data/claude/homeassistant/probe_log_20260514_211550.jsonl
```

Expected: the integration-archive section now shows numbers close to the probe-truth section (Mowing 271, Charging 151, Rain 720, Other ~6) — instead of the pre-rebuild Mowing 99, Other 519.

- [ ] **Step 4: Commit the deletion**

```bash
git commit -m "tools: drop superseded backfill_session_samples.py

Replaced by tools/rebuild_session.py which covers the same 4
streams plus wifi/legs/charge_at_start/settings_snapshot, and
adds bulk + single modes with HA-direct fetch+push.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push**

```bash
git push origin HEAD
```

(No release needed — this is a tool, not a runtime change. Doesn't ship via HACS.)

---

## Self-review

**Spec coverage:**
- ✅ Session window detection from probe — Task 1
- ✅ ProbeReader — Task 2
- ✅ Sample arrays (4 streams) — Task 3
- ✅ charge_at_start — Task 4
- ✅ settings_snapshot — Task 5
- ✅ wifi_samples — Task 6
- ✅ legs — Task 7
- ✅ HAArchiveFetcher (SCP read/write/dry-run) — Task 8
- ✅ Orchestrator + CLI (single + bulk modes) — Task 9
- ✅ Cloud-only field preservation — handled in `rebuild_one_session`
- ✅ "No info on these" listing — handled in main() summary
- ✅ Verbose per-stream diff output — `_print_diff`
- ✅ Smoke test against 19h session — Task 9 Step 4 + Task 10 Step 3
- ✅ Delete old tool — Task 10

**Placeholder scan:** No "TBD/TODO/handle later" — every code block is complete.

**Type consistency:**
- `Window(start_ts: int, end_ts: int)` — used in Task 1 + Task 9. Match.
- `ProbeReader.events_for_slot` returns `list[tuple[int, Any]]` — consumed by Tasks 3-7 via `_StubReader` matching the same shape.
- `ArchiveFilename(date, end_ts, md5, raw, is_recovered)` — Task 8 + Task 9. Match.
- `rebuild_one_session(reader, archive) -> (new_archive, diff)` — Task 9.
- `_position_decoder: Callable[[bytes], tuple[float, float] | None]` — Tasks 6, 7. Match.

No drift.
