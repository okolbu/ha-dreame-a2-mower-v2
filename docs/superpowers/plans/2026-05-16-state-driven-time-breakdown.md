# State-Driven Session Time Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace battery-drop-based mowing detection in `session_card._compute_time_breakdown` with a state-driven partition that produces mutually-exclusive buckets summing exactly to wall clock.

**Architecture:** Build interval sets — rain windows from `error_samples`, state intervals (forward-filled) from `state_samples` — and intersect them with priority `Rain > Mowing > Charging > Other`. Battery samples remain in `raw_dict` for the chart but no longer drive time totals.

**Tech Stack:** Python 3.13, pytest, pytest-asyncio. No new dependencies.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/session_card.py` | Replaces `_compute_rain_pause_seconds` with `_build_rain_intervals` + `_interval_total_seconds`. Adds `_build_state_intervals`, `_state_seconds_outside_intervals`. Rewrites `_compute_time_breakdown` to use them. Updates `build_picked_session_summary` caller. | Modify |
| `tests/protocol/test_session_card.py` | Removes the 5 `test_rain_pause_*` tests (they tested a now-deleted helper). Removes the 2 `test_time_breakdown_*` tests (battery-drop fixtures). Adds new tests for the four new helpers + the rewritten breakdown + a ground-truth regression test for the 19h session. | Modify |
| `tests/protocol/fixtures/19h_session_state_timeline.json` | New fixture: a sparse `raw_dict`-shaped JSON with only the fields the breakdown reads (`start`, `end`, `state_samples`, `error_samples`) reproducing the 19h session's transitions exactly as observed in the probe log. | Create |
| `tools/state_partition.py` | Standalone diagnostic that reads a session JSON + a probe log and prints the state-time partition for verification. Used in Phase 6 manual verification, not by the integration. | Create |

---

## Phase 1 — Pure interval helpers (TDD)

### Task 1: `_build_rain_intervals`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
from custom_components.dreame_a2_mower.session_card import (
    _build_rain_intervals,
)


def test_build_rain_intervals_empty_when_no_56():
    assert _build_rain_intervals([[100, 70], [200, 28]], 0, 1000) == []


def test_build_rain_intervals_single_window_with_close():
    """err=56 at t=100, err=70 at t=500 → one interval [100, 500]."""
    err = [[100, 56], [500, 70]]
    out = _build_rain_intervals(err, 0, 1000)
    assert out == [(100, 500)]


def test_build_rain_intervals_extends_to_end_when_unclosed():
    """err=56 fires and never resolves → interval extends to end_ts."""
    err = [[100, 56]]
    out = _build_rain_intervals(err, 0, 1000)
    assert out == [(100, 1000)]


def test_build_rain_intervals_three_windows():
    """The 19h-session pattern: three independent rain events."""
    err = [
        [1000, 56],  [2000, 70],
        [3000, 56],  [4000, 70],
        [5000, 56],  [6000, 70],
    ]
    out = _build_rain_intervals(err, 0, 10000)
    assert out == [(1000, 2000), (3000, 4000), (5000, 6000)]


def test_build_rain_intervals_merges_consecutive_56_events():
    """Two 56 events with no non-56 between them = ONE window
    that closes at the eventual non-56."""
    err = [[100, 56], [200, 56], [500, 70]]
    out = _build_rain_intervals(err, 0, 1000)
    assert out == [(100, 500)]


def test_build_rain_intervals_clamps_to_window():
    """An err=56 that started before start_ts should clamp to start_ts."""
    err = [[100, 56], [500, 70]]
    out = _build_rain_intervals(err, 200, 1000)
    # Conservative: events at t<start_ts are ignored entirely; only
    # rain events within [start_ts, end_ts] are recognized.
    assert out == []


def test_build_rain_intervals_orders_input_first():
    """Out-of-order err entries still produce correct intervals."""
    err = [[500, 70], [100, 56]]
    out = _build_rain_intervals(err, 0, 1000)
    assert out == [(100, 500)]
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tests/protocol/test_session_card.py -v -k 'build_rain_intervals'
```

Expected: ImportError on `_build_rain_intervals`.

- [ ] **Step 3: Implement the helper**

In `custom_components/dreame_a2_mower/session_card.py`, near the top of the file (alongside other private helpers), add:

```python
def _build_rain_intervals(
    error_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int]]:
    """Walk error_samples; each 'enter err=56' opens, next 'leave 56' closes.

    Robust to:
      - Consecutive err=56 events (treated as one window).
      - A 56 that's never closed before end_ts (extends to end_ts).
      - Out-of-order input (sorts first).
      - Events outside [start_ts, end_ts] (ignored).
    """
    if not error_samples:
        return []
    sorted_err = sorted(error_samples, key=lambda s: int(s[0]))
    intervals: list[tuple[int, int]] = []
    open_ts: int | None = None
    for s in sorted_err:
        if len(s) < 2:
            continue
        try:
            ts = int(s[0])
            code = int(s[1])
        except (TypeError, ValueError):
            continue
        if ts < start_ts or ts > end_ts:
            continue
        if code == 56 and open_ts is None:
            open_ts = ts
        elif code != 56 and open_ts is not None:
            intervals.append((open_ts, ts))
            open_ts = None
    if open_ts is not None:
        intervals.append((open_ts, end_ts))
    return intervals
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/protocol/test_session_card.py -v -k 'build_rain_intervals'
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: _build_rain_intervals helper

Walk error_samples to extract s2p2=56 windows. Replaces the
event-driven approach in _compute_rain_pause_seconds (which
required state_samples to close intervals — wrong because rain
windows are defined entirely by err=56 transitions).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_build_state_intervals`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
from custom_components.dreame_a2_mower.session_card import (
    _build_state_intervals,
)


def test_build_state_intervals_empty():
    """No state samples → one interval (start..end) with state=-1."""
    out = _build_state_intervals([], 100, 200)
    assert out == [(100, 200, -1)]


def test_build_state_intervals_forward_fill():
    """state=1 from 100 holds until next sample at 500."""
    states = [[100, 1], [500, 6]]
    out = _build_state_intervals(states, 0, 1000)
    # Gap [0, 100) is unknown=-1, [100, 500) is 1, [500, 1000) is 6.
    assert out == [(0, 100, -1), (100, 500, 1), (500, 1000, 6)]


def test_build_state_intervals_no_unknown_when_first_sample_at_start():
    """If the first state sample is exactly at start_ts, no unknown gap."""
    states = [[0, 1], [500, 6]]
    out = _build_state_intervals(states, 0, 1000)
    assert out == [(0, 500, 1), (500, 1000, 6)]


def test_build_state_intervals_clamps_pre_start_entries():
    """Sample with ts < start_ts is treated as the initial state."""
    states = [[-50, 13], [100, 1], [500, 6]]
    out = _build_state_intervals(states, 0, 1000)
    # The pre-start entry seeds initial state=13, no unknown gap.
    assert out == [(0, 100, 13), (100, 500, 1), (500, 1000, 6)]


def test_build_state_intervals_drops_post_end_entries():
    """Samples beyond end_ts are ignored."""
    states = [[100, 1], [500, 6], [1500, 13]]
    out = _build_state_intervals(states, 0, 1000)
    assert out == [(0, 100, -1), (100, 500, 1), (500, 1000, 6)]


def test_build_state_intervals_consecutive_same_state():
    """Two entries with the same state code emit a single merged interval."""
    states = [[100, 1], [200, 1], [500, 6]]
    out = _build_state_intervals(states, 0, 1000)
    # Merged: (100, 500, 1) — the duplicate 200 is collapsed.
    assert out == [(0, 100, -1), (100, 500, 1), (500, 1000, 6)]


def test_build_state_intervals_sorts_input_first():
    """Out-of-order entries still produce correct intervals."""
    states = [[500, 6], [100, 1]]
    out = _build_state_intervals(states, 0, 1000)
    assert out == [(0, 100, -1), (100, 500, 1), (500, 1000, 6)]
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tests/protocol/test_session_card.py -v -k 'build_state_intervals'
```

Expected: ImportError on `_build_state_intervals`.

- [ ] **Step 3: Implement the helper**

Add to `custom_components/dreame_a2_mower/session_card.py`:

```python
def _build_state_intervals(
    state_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int, int]]:
    """Forward-fill state_samples into [start_ts, end_ts] step intervals.

    Returns a list of (interval_start, interval_end, state_code).
    Adjacent intervals with the same state code are merged.

    Special handling:
      - The gap [start_ts, first_state_ts] gets state=-1 (sentinel
        for "unknown"; never matches the mowing/charging filters
        so it falls into Other).
      - A state entry with ts < start_ts seeds the initial state
        instead of producing a -1 prefix.
      - Entries with ts > end_ts are ignored.
      - Out-of-order input is sorted first.
    """
    if end_ts <= start_ts:
        return []
    if not state_samples:
        return [(start_ts, end_ts, -1)]

    sorted_samples = sorted(state_samples, key=lambda s: int(s[0]))
    intervals: list[tuple[int, int, int]] = []

    # Determine initial state at start_ts.
    initial_state = -1
    in_window: list[tuple[int, int]] = []
    for s in sorted_samples:
        if len(s) < 2:
            continue
        try:
            ts = int(s[0])
            code = int(s[1])
        except (TypeError, ValueError):
            continue
        if ts <= start_ts:
            initial_state = code
        elif ts <= end_ts:
            in_window.append((ts, code))

    cur_state = initial_state
    cur_start = start_ts
    for ts, code in in_window:
        if code == cur_state:
            continue  # merge adjacent same-state entries
        if ts > cur_start:
            intervals.append((cur_start, ts, cur_state))
        cur_start = ts
        cur_state = code
    if cur_start < end_ts:
        intervals.append((cur_start, end_ts, cur_state))
    return intervals
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/protocol/test_session_card.py -v -k 'build_state_intervals'
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: _build_state_intervals helper

Forward-fill state_samples into step intervals. Gap before the
first sample becomes state=-1 (Other). Adjacent same-state
entries merge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `_interval_total_seconds` and `_state_seconds_outside_intervals`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/protocol/test_session_card.py`:

```python
from custom_components.dreame_a2_mower.session_card import (
    _interval_total_seconds,
    _state_seconds_outside_intervals,
)


def test_interval_total_seconds_empty():
    assert _interval_total_seconds([]) == 0


def test_interval_total_seconds_basic():
    intervals = [(0, 100), (200, 350), (400, 410)]
    assert _interval_total_seconds(intervals) == 100 + 150 + 10


def test_state_seconds_outside_intervals_no_overlap():
    """Mowing intervals don't overlap rain → full seconds count."""
    state_intervals = [(0, 100, 1), (200, 300, 1), (300, 400, 6)]
    rain = [(500, 600)]
    out = _state_seconds_outside_intervals(state_intervals, {1}, rain)
    assert out == 200  # 100 + 100


def test_state_seconds_outside_intervals_full_overlap():
    """Mowing entirely inside a rain window → zero seconds count."""
    state_intervals = [(100, 200, 1)]
    rain = [(50, 250)]
    out = _state_seconds_outside_intervals(state_intervals, {1}, rain)
    assert out == 0


def test_state_seconds_outside_intervals_partial_overlap():
    """Mowing [100,300) intersects rain [200,400) → 100 seconds count."""
    state_intervals = [(100, 300, 1)]
    rain = [(200, 400)]
    out = _state_seconds_outside_intervals(state_intervals, {1}, rain)
    assert out == 100


def test_state_seconds_outside_intervals_filters_by_target_state():
    """Only intervals whose state ∈ target_states contribute."""
    state_intervals = [(0, 100, 1), (100, 200, 6), (200, 300, 1)]
    rain: list = []
    out = _state_seconds_outside_intervals(state_intervals, {1}, rain)
    assert out == 200
    out = _state_seconds_outside_intervals(state_intervals, {6}, rain)
    assert out == 100
    out = _state_seconds_outside_intervals(state_intervals, {1, 6}, rain)
    assert out == 300


def test_state_seconds_outside_intervals_multiple_rain_windows():
    """Mowing [0, 1000) intersects two rain windows [100,200) + [400,500)."""
    state_intervals = [(0, 1000, 1)]
    rain = [(100, 200), (400, 500)]
    out = _state_seconds_outside_intervals(state_intervals, {1}, rain)
    # 1000 total - 100 (rain1) - 100 (rain2) = 800
    assert out == 800
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tests/protocol/test_session_card.py -v -k 'interval_total or state_seconds'
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Add to `custom_components/dreame_a2_mower/session_card.py`:

```python
def _interval_total_seconds(intervals: list[tuple[int, int]]) -> int:
    """Sum (end - start) over a list of (start, end) intervals.

    Assumes non-overlapping (caller's responsibility).
    _build_rain_intervals satisfies this naturally.
    """
    return sum(max(0, b - a) for a, b in intervals)


def _state_seconds_outside_intervals(
    state_intervals: list[tuple[int, int, int]],
    target_states: set[int],
    excluded_intervals: list[tuple[int, int]],
) -> int:
    """Sum seconds in any state_interval whose state ∈ target_states,
    EXCLUDING any overlap with excluded_intervals.

    Both interval lists are assumed sorted ascending and
    non-overlapping internally. Excluded intervals are subtracted
    via per-pair clipping (O(N×M); fine for our N,M < 1000).
    """
    total = 0
    for sa, sb, sv in state_intervals:
        if sv not in target_states:
            continue
        seg_total = sb - sa
        for ea, eb in excluded_intervals:
            if eb <= sa or ea >= sb:
                continue
            seg_total -= min(sb, eb) - max(sa, ea)
        total += max(0, seg_total)
    return total
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/protocol/test_session_card.py -v -k 'interval_total or state_seconds'
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: interval-arithmetic helpers"
```

---

## Phase 2 — Rewrite `_compute_time_breakdown`

### Task 4: Drop the old `_compute_rain_pause_seconds` helper + tests

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

The helper added in the prior 2026-05-16 spec is now subsumed by `_build_rain_intervals` + `_interval_total_seconds`. Delete it.

- [ ] **Step 1: Find the existing helper and tests**

```bash
grep -n '_compute_rain_pause_seconds' custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
```

Expected output: 1 def line in session_card.py, 1 import line in test file, 5 test function defs (`test_rain_pause_*`).

- [ ] **Step 2: Delete the helper from session_card.py**

Remove the `_MOWING_STATE_CODES` const if it's still in the file (we'll redefine inside the new `_compute_time_breakdown` with `{1}` instead of `{1, 2, 3}`), and remove the entire `_compute_rain_pause_seconds` function. Also remove its in-`_compute_time_breakdown` callers (Phase 2's rewrite will handle the rain calc differently).

- [ ] **Step 3: Delete the 5 `test_rain_pause_*` tests**

Remove from `tests/protocol/test_session_card.py`:
- test_rain_pause_zero_when_no_56_event
- test_rain_pause_closes_at_next_mowing_state
- test_rain_pause_extends_to_end_when_no_close
- test_rain_pause_sums_multiple_intervals
- test_rain_pause_ignores_pre_56_state_returns

Also remove the `from custom_components.dreame_a2_mower.session_card import (_compute_rain_pause_seconds,)` line.

- [ ] **Step 4: Run tests to confirm nothing else breaks (apart from the 2 `test_time_breakdown_*` tests which depend on the old behavior — they'll be addressed in Task 5)**

```bash
pytest tests/protocol/test_session_card.py -v -k 'not time_breakdown'
```

Expected: All PASS (the 19 helper tests from Tasks 1-3 + remaining session-card tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: drop _compute_rain_pause_seconds (subsumed)

The new _build_rain_intervals + _interval_total_seconds combo
returns the same number AND exposes the underlying intervals for
the priority-based bucket exclusion in the upcoming
_compute_time_breakdown rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Rewrite `_compute_time_breakdown` (state-driven)

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py`
- Modify: `tests/protocol/test_session_card.py`

- [ ] **Step 1: Replace the existing failing test_time_breakdown_* tests**

In `tests/protocol/test_session_card.py`, find and DELETE both:
- `test_time_breakdown_returns_4_tuple_with_rain`
- `test_time_breakdown_no_error_samples_keeps_zero_rain`

Then APPEND these new tests:

```python
def test_compute_time_breakdown_empty_state_samples_returns_none():
    """Degenerate case: no state samples → can't classify state-time.
    Rain still computed if error_samples present."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=0, end_ts=3600,
        error_samples=[[100, 56], [200, 70]],
        state_samples=[],
    )
    assert mow is None
    assert chg is None
    assert rain == (200 - 100) // 60  # 1 minute
    assert other is None


def test_compute_time_breakdown_simple_pure_mowing_session():
    """100% mowing, no rain, no charging. Mow=elapsed, others=0."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=0, end_ts=3600,
        error_samples=[],
        state_samples=[[0, 1]],
    )
    assert mow == 60  # 60 minutes
    assert chg == 0
    assert rain == 0
    assert other == 0


def test_compute_time_breakdown_mowing_then_charging():
    """30 min mow → 30 min charge → 0 rain, 0 other."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=0, end_ts=3600,
        error_samples=[],
        state_samples=[[0, 1], [1800, 6]],
    )
    assert mow == 30
    assert chg == 30
    assert rain == 0
    assert other == 0


def test_compute_time_breakdown_rain_priority_over_charging():
    """Mower at dock charging during a rain window:
    that time is RAIN, not CHARGING."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=0, end_ts=3600,
        error_samples=[[600, 56], [3000, 70]],  # rain [600, 3000) = 40 min
        state_samples=[
            [0, 1],         # mowing [0, 600)
            [600, 6],       # charging [600, 3000) — but this is in rain
            [3000, 1],      # mowing [3000, 3600)
        ],
    )
    # Rain claims [600, 3000) = 40 min
    # Mowing claims [0, 600) + [3000, 3600) = 20 min
    # Charging: state=6 only happens during rain → 0 min
    # Other: 0
    assert rain == 40
    assert mow == 20
    assert chg == 0
    assert other == 0
    assert mow + chg + rain + other == 60


def test_compute_time_breakdown_state_unknown_falls_into_other():
    """First state sample at t=600; pre-600 is state=-1 → Other."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=0, end_ts=3600,
        error_samples=[],
        state_samples=[[600, 1]],
    )
    # [0, 600) = 10 min unknown → Other
    # [600, 3600) = 50 min mowing
    assert mow == 50
    assert chg == 0
    assert rain == 0
    assert other == 10
    assert mow + chg + rain + other == 60


def test_compute_time_breakdown_buckets_always_sum_to_elapsed():
    """Sanity: pick a complex case, assert sum invariant."""
    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=1000, end_ts=11800,  # 180 min
        error_samples=[[2000, 56], [5000, 70], [7000, 56], [9000, 70]],
        state_samples=[
            [1000, 1],    # mowing
            [1800, 6],    # charging
            [2000, 13],   # at dock
            [5000, 1],    # mowing
            [7000, 6],    # charging
            [9000, 1],    # mowing
        ],
    )
    elapsed_min = (11800 - 1000) // 60
    assert mow + chg + rain + other == elapsed_min
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tests/protocol/test_session_card.py -v -k 'compute_time_breakdown'
```

Expected: FAIL — old `_compute_time_breakdown` is still battery-drop based, returns wrong numbers for the new tests.

- [ ] **Step 3: Replace `_compute_time_breakdown`**

In `custom_components/dreame_a2_mower/session_card.py`, find the existing `def _compute_time_breakdown(...)`. Replace its entire body with the new implementation. The new function:

```python
_MOWING_STATE_CODES: set[int] = {1}
_CHARGING_STATE_CODE: int = 6


def _compute_time_breakdown(
    battery_samples: list[list[int]],
    charging_status_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
    *,
    error_samples: list[list[int]] | None = None,
    state_samples: list[list[int]] | None = None,
) -> tuple[int | None, int | None, int, int | None]:
    """Split the session wall-clock into (mowing, charging, rain, other) minutes.

    State-driven (not battery-drop-driven). Buckets are mutually
    exclusive and sum to elapsed minutes exactly.

    Priority order:
      1. Rain delay  — any second inside an s2p2=56 window
                       (regardless of mower state)
      2. Mowing      — state=1 outside rain
      3. Charging    — state=6 outside rain
      4. Other       — remainder (state=13/5/3/2 + unknown gaps)

    battery_samples and charging_status_samples are kept in the
    signature for API compatibility but no longer used for time
    totals. They're still consumed by the dashboard chart.

    error_samples and state_samples are keyword-only kwargs to
    keep older positional callers working — they'll receive
    (None, None, 0, None) which is the safest fallback when no
    state_samples are passed.
    """
    if state_samples is None or not state_samples:
        rain_intervals_only = _build_rain_intervals(
            error_samples or [], start_ts, end_ts,
        )
        rain_s = _interval_total_seconds(rain_intervals_only)
        return (None, None, rain_s // 60, None)

    rain_intervals = _build_rain_intervals(
        error_samples or [], start_ts, end_ts,
    )
    state_intervals = _build_state_intervals(
        state_samples, start_ts, end_ts,
    )

    rain_s = _interval_total_seconds(rain_intervals)
    mowing_s = _state_seconds_outside_intervals(
        state_intervals, _MOWING_STATE_CODES, rain_intervals,
    )
    charging_s = _state_seconds_outside_intervals(
        state_intervals, {_CHARGING_STATE_CODE}, rain_intervals,
    )

    total_min = max(0, end_ts - start_ts) // 60
    mow_min = mowing_s // 60
    chg_min = charging_s // 60
    rain_min = rain_s // 60
    other_min = max(0, total_min - mow_min - chg_min - rain_min)

    return (mow_min, chg_min, rain_min, other_min)
```

- [ ] **Step 4: Update the caller in `build_picked_session_summary`**

Find the existing caller (search for `_compute_time_breakdown(`). The signature it uses is currently:

```python
mow_min, chg_min, rain_min, other_min = _compute_time_breakdown(
    bs, cs, summary.start_ts, summary.end_ts,
    error_samples=err_samples,
    state_samples=ss,
)
```

This is already compatible with the new signature — no change needed. Verify via grep that the call site matches exactly.

- [ ] **Step 5: Run all session-card tests**

```bash
pytest tests/protocol/test_session_card.py -v
```

Expected: All PASS (the 6 new compute_time_breakdown tests + the 21 helper tests from Tasks 1-3 + everything else that was passing pre-task).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py \
        tests/protocol/test_session_card.py
git commit -m "session_card: state-driven time breakdown

Replace battery-drop-based mowing detection with a state-driven
partition. Buckets are now mutually exclusive and sum to wall
clock exactly. Priority: Rain > Mowing > Charging > Other.

Diagnosed via probe-log analysis of the 2026-05-15 19h session
where battery flicker at the dock was being counted as 468 min of
'mowing' during rain windows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Ground-truth regression test (the 19h session)

### Task 6: Add the 19h-session probe-log fixture + test

**Files:**
- Create: `tests/protocol/fixtures/19h_session_state_timeline.json`
- Modify: `tests/protocol/test_session_card.py`

This pins the bug to a real-world fixture. If a future change regresses the algorithm, this test catches it.

- [ ] **Step 1: Create the fixture**

Create `tests/protocol/fixtures/19h_session_state_timeline.json` with the exact content below (transitions extracted from `probe_log_20260514_211550.jsonl` for the 2026-05-15 08:00 → 2026-05-16 03:08 window):

```json
{
  "start": 1778824800,
  "end": 1778893682,
  "state_samples": [
    [1778824801, 1],
    [1778827269, 2],
    [1778827269, 5],
    [1778827323, 6],
    [1778830268, 1],
    [1778833655, 2],
    [1778833655, 5],
    [1778833695, 6],
    [1778836784, 1],
    [1778840329, 2],
    [1778840330, 5],
    [1778840384, 6],
    [1778843487, 13],
    [1778854732, 1],
    [1778855656, 2],
    [1778855656, 5],
    [1778855714, 6],
    [1778870056, 1],
    [1778870120, 2],
    [1778870121, 5],
    [1778870167, 6],
    [1778870438, 13],
    [1778877518, 6],
    [1778878069, 13],
    [1778884521, 1],
    [1778885577, 3],
    [1778885705, 1],
    [1778889148, 2],
    [1778889148, 5],
    [1778889239, 6],
    [1778892274, 1]
  ],
  "error_samples": [
    [1778824801, 53],
    [1778827268, 54],
    [1778830267, 70],
    [1778833654, 54],
    [1778836783, 70],
    [1778840329, 56],
    [1778854730, 70],
    [1778854731, 28],
    [1778855656, 56],
    [1778870055, 70],
    [1778870056, 28],
    [1778870120, 56],
    [1778884520, 70],
    [1778884521, 28],
    [1778889147, 54],
    [1778892272, 70],
    [1778892273, 28],
    [1778893683, 48]
  ]
}
```

- [ ] **Step 2: Add the regression test**

Append to `tests/protocol/test_session_card.py`:

```python
import json
from pathlib import Path


def test_compute_time_breakdown_19h_session_regression():
    """Pin the algorithm against the 2026-05-15 19h session.

    Probe-log ground truth (state-time integration):
      - State=1 (MOWING):           271.6 min
      - State=6 (CHARGING):         455.6 min  (304.4 in rain)
      - State=13 (CHG_COMPLETED):   413.0 min
      - State=5 (RETURNING):          5.7 min
      - State=3 (PAUSED):             2.1 min
      - Wall clock:                1148.0 min

    Rain windows (s2p2=56): 3 × 240 min = 720 min.

    Expected breakdown (rain-priority):
      - Mowing:    271 min  (state=1 outside rain)
      - Charging:  151 min  (state=6 outside rain — 455.6 - 304.4)
      - Rain:      720 min
      - Other:       6 min  (state=13 outside rain + state=5/3 + 1 min for the
                              [start_ts, first_state_sample_ts] gap)
      - Sum:      1148 min  ≡  end_ts - start_ts
    """
    fixture_path = (
        Path(__file__).parent / "fixtures" / "19h_session_state_timeline.json"
    )
    fx = json.loads(fixture_path.read_text())

    mow, chg, rain, other = _compute_time_breakdown(
        battery_samples=[],
        charging_status_samples=[],
        start_ts=fx["start"],
        end_ts=fx["end"],
        error_samples=fx["error_samples"],
        state_samples=fx["state_samples"],
    )
    elapsed_min = (fx["end"] - fx["start"]) // 60
    assert elapsed_min == 1148

    # Allow ±2 min for floor-rounding artifacts at second-vs-minute boundaries.
    assert abs(mow - 271) <= 2, f"mow={mow}, expected ~271"
    assert abs(chg - 151) <= 2, f"chg={chg}, expected ~151"
    assert abs(rain - 720) <= 2, f"rain={rain}, expected ~720"
    assert abs(other - 6) <= 2, f"other={other}, expected ~6"

    # Hard invariant: must sum to elapsed exactly.
    assert mow + chg + rain + other == elapsed_min, (
        f"buckets sum to {mow+chg+rain+other}, expected {elapsed_min}"
    )
```

- [ ] **Step 3: Run the regression test**

```bash
pytest tests/protocol/test_session_card.py::test_compute_time_breakdown_19h_session_regression -v
```

Expected: PASS. If it fails, the assertion message tells you which bucket is off — adjust the algorithm OR the expected values (carefully — the expected values are derived from probe-log ground truth and shouldn't shift unless the algorithm definition changes).

- [ ] **Step 4: Run the full session-card suite to confirm no regressions**

```bash
pytest tests/protocol/test_session_card.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/protocol/fixtures/19h_session_state_timeline.json \
        tests/protocol/test_session_card.py
git commit -m "session_card: 19h-session ground-truth regression test

Pins the algorithm against probe-log-derived state and error
transitions for the 2026-05-15 19h session. Catches any future
regression that lets the buckets diverge from wall clock.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Integration test fixtures (if any need updating)

### Task 7: Verify integration tests still pass + update fixtures if needed

**Files:**
- Read: `tests/integration/test_picked_session.py`
- Possibly modify: `tests/integration/test_picked_session.py` (only if existing tests use battery-drop-fixture-based expectations)

- [ ] **Step 1: Run integration tests**

```bash
pytest tests/integration/test_picked_session.py -v 2>&1 | tail -30
```

- [ ] **Step 2: If any fail with assertion errors on `time_mowing_min` / `time_charging_min` / `time_other_min` / `time_rain_protection_min`**

Read the failing test, identify the fixture it uses, and update the EXPECTED values to match the new state-driven semantics. Do NOT change the algorithm — the algorithm is correct now; older fixtures may have been pinning to wrong numbers.

If a test uses an old-style `state_samples=[]` fixture, the expected values for mowing/charging are now `None` (vs the old battery-drop-derived numbers).

- [ ] **Step 3: Run again to confirm green**

```bash
pytest tests/integration/test_picked_session.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Commit (only if test fixtures changed)**

```bash
git add tests/integration/test_picked_session.py
git commit -m "tests: update picked_session expectations for state-driven breakdown"
```

If no changes, skip this commit and move on.

- [ ] **Step 5: Run the FULL test suite**

```bash
pytest tests/ 2>&1 | tail -10
```

Expected: all green or only pre-existing failures unrelated to this work.

---

## Phase 5 — Diagnostic tool + release

### Task 8: Add `tools/state_partition.py` diagnostic

**Files:**
- Create: `tools/state_partition.py`

Standalone CLI for verifying any session against a probe log. Used in Phase 6 manual verification.

- [ ] **Step 1: Create the tool**

```bash
mkdir -p tools
```

Create `tools/state_partition.py`:

```python
#!/usr/bin/env python3
"""state_partition.py — verify a session JSON's time breakdown
against probe-log ground truth.

Usage:
    python3 tools/state_partition.py <session.json> <probe_log.jsonl>

Prints:
  - Per-state seconds (from probe log STATE transitions)
  - Per-error event timeline (from probe log s2p2 transitions)
  - The same algorithm as session_card._compute_time_breakdown
    applied to the probe-derived state_samples + error_samples
  - The integration's reported numbers (from session.json's
    in_progress.json-derived sample arrays)
  - Side-by-side comparison

Used to diagnose breakdown-vs-truth mismatches without modifying
the integration code path.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path


STATE_NAMES = {
    1: "MOWING", 2: "IDLE", 3: "PAUSED", 5: "RETURNING",
    6: "CHARGING", 13: "CHG_COMPLETED",
}


def parse_probe_log(probe_path: Path, start_ts: int, end_ts: int):
    """Walk a probe log; return (state_transitions, err_transitions)
    where each is a list of (unix_ts, code) within [start_ts, end_ts]."""
    state, err = [], []
    start_dt = dt.datetime.fromtimestamp(start_ts)
    end_dt = dt.datetime.fromtimestamp(end_ts)
    with probe_path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "pretty":
                continue
            try:
                ts_d = dt.datetime.fromisoformat(d["timestamp"])
            except Exception:
                continue
            if not (start_dt <= ts_d <= end_dt):
                continue
            text = d.get("text", "")
            ts_unix = int(ts_d.timestamp())
            try:
                if "s2p1 (STATE)" in text:
                    if "->" in text:
                        new = int(text.split("->", 1)[1].strip().split()[0])
                    else:
                        new = int(text.split("=", 1)[1].strip().split()[0])
                    state.append((ts_unix, new))
                elif "s2p2" in text:
                    if "->" in text:
                        new = int(text.split("->", 1)[1].strip().split()[0])
                    else:
                        new = int(text.split("=", 1)[1].strip().split()[0])
                    err.append((ts_unix, new))
            except Exception:
                pass
    return state, err


def main(session_path: Path, probe_path: Path) -> None:
    sess = json.loads(session_path.read_text())
    start_ts, end_ts = int(sess["start"]), int(sess["end"])
    elapsed_min = (end_ts - start_ts) // 60

    state_probe, err_probe = parse_probe_log(probe_path, start_ts, end_ts)

    # Add to sys.path so we can import the integration's helper directly.
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
    from custom_components.dreame_a2_mower.session_card import (
        _compute_time_breakdown,
    )

    # Probe-truth breakdown
    truth = _compute_time_breakdown(
        battery_samples=[], charging_status_samples=[],
        start_ts=start_ts, end_ts=end_ts,
        error_samples=[[t, c] for t, c in err_probe],
        state_samples=[[t, c] for t, c in state_probe],
    )

    # Integration-as-was breakdown (uses session.json's in_progress samples)
    integration = _compute_time_breakdown(
        battery_samples=sess.get("battery_samples") or [],
        charging_status_samples=sess.get("charging_status_samples") or [],
        start_ts=start_ts, end_ts=end_ts,
        error_samples=sess.get("error_samples") or [],
        state_samples=sess.get("state_samples") or [],
    )

    print(f"=== Session {session_path.name} ===")
    print(f"  start:  {dt.datetime.fromtimestamp(start_ts)}")
    print(f"  end:    {dt.datetime.fromtimestamp(end_ts)}")
    print(f"  wall:   {elapsed_min} min ({elapsed_min/60:.2f} h)")
    print()
    print(f"=== Probe-derived (ground truth) ===")
    print(f"  state transitions: {len(state_probe)}")
    print(f"  error transitions: {len(err_probe)}")
    _print_breakdown(truth, elapsed_min)
    print()
    print(f"=== Integration-archive samples ===")
    print(f"  state samples: {len(sess.get('state_samples') or [])}")
    print(f"  error samples: {len(sess.get('error_samples') or [])}")
    _print_breakdown(integration, elapsed_min)


def _print_breakdown(b, elapsed_min: int) -> None:
    mow, chg, rain, other = b
    s = (mow or 0) + (chg or 0) + rain + (other or 0)
    print(f"  Mowing:    {mow} min")
    print(f"  Charging:  {chg} min")
    print(f"  Rain:      {rain} min")
    print(f"  Other:     {other} min")
    print(f"  SUM:       {s} min  ({'matches' if s == elapsed_min else 'OFF BY ' + str(s - elapsed_min)})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: state_partition.py <session.json> <probe_log.jsonl>",
              file=sys.stderr)
        sys.exit(2)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
```

- [ ] **Step 2: Smoke-test against the 19h session**

```bash
chmod +x tools/state_partition.py
python3 tools/state_partition.py /tmp/sess_19h.json \
  /data/claude/homeassistant/probe_log_20260514_211550.jsonl
```

Expected: probe-derived breakdown shows ~Mowing 271 / Charging 151 / Rain 720 / Other 6 with SUM=1148 (matches). Integration-archive breakdown shows the under-data version (which after the algorithm rewrite will also be self-consistent — sums to 1148 — but with values reflecting the partial sample set).

- [ ] **Step 3: Commit**

```bash
git add tools/state_partition.py
git commit -m "tools: state_partition.py diagnostic

Compares a session.json's breakdown against probe-log ground
truth. Used during manual verification to confirm the algorithm
produces correct numbers from probe-derived samples vs
integration-archive samples.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: SCP integration changes + cut release

**Files:**
- None (release tooling)

- [ ] **Step 1: Push commits**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git push origin HEAD
```

- [ ] **Step 2: SCP `session_card.py` to live HA**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/session_card.py \
  "$USER@$HOST:/config/custom_components/dreame_a2_mower/session_card.py"
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -la /config/custom_components/dreame_a2_mower/session_card.py"
```

- [ ] **Step 3: Cut release**

The previous release was `1.0.14a7`. Next safe alpha is `1.0.14a8`.

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
tools/release.sh 1.0.14a8 --notes "State-driven session time breakdown — fixes overlapping buckets.

Replaces the battery-drop-based mowing detection with a
state-driven partition that produces mutually-exclusive buckets
summing exactly to wall clock.

The 19h session of 2026-05-15 exposed a 219-min over-count in
the breakdown (Mowing 584 + Charging 303 + Rain 480 = 1367 vs
wall clock 1148). Probe-log analysis showed:

- Battery flicker (e.g. 100→99→100) at the dock was being
  counted as 'mowing'. Of the 584 reported, 468 min was in-rain
  flicker and 242 min was in-charging flicker.
- Charging-during-rain was double-counted in both buckets.

New algorithm:
1. Build rain windows from error_samples (s2p2=56).
2. Forward-fill state_samples into step intervals.
3. Bucket via priority: Rain > Mowing(state=1) > Charging(state=6) > Other.

For the 19h session this now produces:
  Mowing 271 / Charging 151 / Rain 720 / Other 6 = 1148 ✓

(The 720 rain reflects the THREE rain windows the probe captured.
The integration's still-incomplete sample set due to the
in_progress.json reliability bug means the integration's reported
rain may be smaller than 720 until [[project_session_persist_audit_todo]]
lands. Bug-budget-wise: under-counted rain falls into 'Other' now
instead of inflating 'Mowing'.)

See spec:
docs/superpowers/specs/2026-05-16-state-driven-time-breakdown.md"
```

- [ ] **Step 4: Confirm release**

The script prints the URL. Verify isLatest=true / isPrerelease=false / isDraft=false.

---

## Phase 6 — Manual verification

### Task 10: Verify on next live session

**Files:**
- None (verification)

- [ ] **Step 1: Wait for next session finalize**

When the next mowing session finalizes (whenever it happens — could be hours or days), proceed.

- [ ] **Step 2: Pull the new session JSON + run the diagnostic**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
NEWEST=$(sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -t /config/dreame_a2_mower/sessions/2026-*.json | head -1")
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no "$USER@$HOST:$NEWEST" /tmp/sess_latest.json

# If a probe was running, run the diagnostic:
PROBE=$(ls -t /data/claude/homeassistant/probe_log_*.jsonl | head -1)
python3 /data/claude/homeassistant/ha-dreame-a2-mower/tools/state_partition.py \
  /tmp/sess_latest.json "$PROBE"
```

- [ ] **Step 3: Confirm sum invariant**

The "SUM:" line should always print "matches" — the four buckets must sum to elapsed minutes exactly. If "OFF BY N" appears, file a bug with the session JSON attached.

- [ ] **Step 4: Pick the session in dashboard, eyeball the breakdown card**

User action. The four-row breakdown should look reasonable:
- Mowing time matches roughly what the user expected based on what they observed.
- Rain delay is 0 if no rain hit, non-zero if rain hit.
- Charging is the time-at-dock-charging outside rain.
- Other catches transitions and any sample-gap windows.

---

## Self-review

**Spec coverage:**
- ✅ `_build_rain_intervals` — Task 1
- ✅ `_build_state_intervals` — Task 2
- ✅ `_interval_total_seconds` + `_state_seconds_outside_intervals` — Task 3
- ✅ Drop `_compute_rain_pause_seconds` + its tests — Task 4
- ✅ Rewrite `_compute_time_breakdown` (state-driven) — Task 5
- ✅ 19h-session ground-truth regression test — Task 6
- ✅ Integration fixtures sanity check — Task 7
- ✅ Diagnostic tool — Task 8
- ✅ Release pipeline — Task 9
- ✅ Manual verification — Task 10
- ✅ Risks documented in spec (state-samples gaps, mowing-set narrowness, state=13 at session-end, dup-state robustness, performance)
- ✅ Acceptance criteria — every bullet maps to a task that verifies it

**Placeholder scan:** None. Every code block is complete; every command has expected output; every file path is concrete.

**Type consistency:**
- `_build_rain_intervals` returns `list[tuple[int, int]]` — used by `_state_seconds_outside_intervals` (excluded_intervals param) and `_interval_total_seconds`. Match.
- `_build_state_intervals` returns `list[tuple[int, int, int]]` — used by `_state_seconds_outside_intervals` (state_intervals param). Match.
- `_state_seconds_outside_intervals` returns `int` (seconds) — caller divides by 60 for minutes. Match.
- `_interval_total_seconds` returns `int` (seconds) — same.
- `_compute_time_breakdown` returns `tuple[int|None, int|None, int, int|None]` — caller in `build_picked_session_summary` unpacks 4 values. Match.

No drift detected.
