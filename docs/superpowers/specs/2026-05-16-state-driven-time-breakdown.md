# State-Driven Session Time Breakdown — Design

**Date:** 2026-05-16
**Status:** Draft (pending user review)
**Supersedes:** Part 2 of `2026-05-16-session-recorder-merge-and-rain-bucket-design.md` (the rain-bucket-from-battery-drops approach)

## Problem

The 2026-05-15 19h mowing session exposed a fundamental flaw in
`_compute_time_breakdown`: the four buckets (mowing / charging /
rain / other) don't sum to wall clock. Reported:

```
Wall clock: 1148 min
Mowing:      584 min
Charging:    303 min
Rain delay:  480 min
Sum:        1367 min   (+219 over wall)
```

Probe-log ground truth for the same session:

```
State=1  MOWING:           271.6 min   (vs reported 584 → 2.15× over)
State=6  CHARGING:         455.6 min   (vs reported 303 → missed early window)
State=13 CHG_COMPLETED:    413.0 min   (mostly waiting at dock during rain)
State=5  RETURNING:          5.7 min
State=3  PAUSED:             2.1 min
                          ───────
                          1148.0 min   ✓ matches wall

Rain windows (s2p2=56): 3 windows × 240 min = 720 min
  [12:18:49, 16:18:50]   ← MISSED entirely in integration (data loss)
  [16:34:16, 20:34:15]
  [20:35:20, 00:35:20]
```

Three distinct bugs are at play:

### Bug A — Battery-drop detection over-counts mowing 2× to 3×

`_compute_time_breakdown` defines "mowing" as any interval where
two consecutive `battery_samples` entries show v2 < v1. The
integer-rounded battery percentage flickers (`100 → 99 → 100`)
during at-dock periods. For the 19h session this counted **468 min
of at-dock flicker during rain as mowing**, plus **242 min of
flicker during active charging cycles as mowing**. The
algorithm structurally cannot tell "actually cutting grass" from
"sitting on the dock with a percentage display that bobbled".

### Bug B — Buckets overlap by design

Even with correct detection, the four buckets allow overlap. The
mower physically charges *while* in rain protection — both the
charging interval (chg_status=1) and the rain interval (s2p2=56)
claim the same minutes. Without an explicit priority rule, sums
exceed wall clock.

### Bug C — Pre-restart data loss (separate ticket)

`in_progress.json` lost the first 8.5 h of samples across HA
restarts during the long session, hiding the first 240-min rain
window entirely from `error_samples` and the morning's real
mowing+charging from the other arrays. Captured in
[[project-session-persist-audit-todo]]; out of scope for this
spec.

## Non-goals

- Backfilling existing archived sessions. The fix only applies to
  sessions finalized after the new code ships.
- Adding new sample sources or recorder integrations. The fix
  operates on what's already in `raw_dict`.
- Fixing pre-restart data loss (Bug C). The state-driven
  breakdown will still under-count if `state_samples` has gaps —
  but it under-counts cleanly into "Other" instead of inflating
  into "Mowing", which is the load-bearing improvement.
- Per-state granular reporting (state=13 separately from state=5,
  etc.). Users don't care about that level; the four buckets are
  the contract.
- Visual chart changes. The `battery_samples` chart still uses raw
  battery data; only the *summary breakdown* numbers change.

## Architecture

```
Inputs (from raw_dict):
  state_samples         : list[[ts, state_code]]   — load-bearing
  error_samples         : list[[ts, err_code]]     — for rain windows
  charging_status_samples: list[[ts, chg_status]]  — chart only, NOT time
  battery_samples       : list[[ts, pct]]          — chart only, NOT time
  start_ts, end_ts      : session window

Algorithm:
  1. Forward-fill state_samples into a step function s(t) over
     [first_state_ts, end_ts]. The gap [start_ts, first_state_ts]
     is treated as state=None (unknown → "Other").

  2. Build the rain interval set R from error_samples: each entry
     where err==56 opens an interval; the next entry where err!=56
     closes it. If no close before end_ts, interval extends to
     end_ts.

  3. Compute four mutually-exclusive buckets via priority order:
     a. Rain delay  = total seconds inside any R interval
                      (regardless of state)
     b. Mowing      = total seconds where s(t) == 1
                      AND t is NOT in any rain interval
     c. Charging    = total seconds where s(t) == 6
                      AND t is NOT in any rain interval
     d. Other       = end_ts - start_ts - rain - mowing - charging

  4. Return (mow_min // 60, chg_min // 60, rain_min // 60, other_min)
     where other_min is computed at the minute level to absorb
     floor-rounding remainder so the four buckets sum to elapsed
     minutes exactly. (Same trick as the current
     _compute_time_breakdown.)
```

Battery samples are entirely removed from the time-totaling logic.
They remain in `raw_dict` for the dashboard chart but their role
in the breakdown is over.

### Priority rationale

When the mower is at the dock charging *during* a rain protection
window, the user's mental model is "stuck because of rain, doing
its best to be ready when rain clears." That's rain delay, not
mid-mow recharging. Bucketing rain over charging matches the
"why is the mower not mowing" framing the breakdown exists to
answer.

### Why drop battery-drop detection?

Three reasons:

1. Empirically wrong by 2-3× on real data (Bug A).
2. `state_samples` is a more direct signal — the firmware itself
   says "I am mowing" via `state=1` rather than us inferring from
   battery telemetry.
3. The current battery-drop algorithm couldn't be salvaged with a
   simple AND because the integer-rounded battery percentage
   makes the noise floor too high relative to the signal (real
   slow mowing draws ~1% per minute, same magnitude as flicker).

### Why drop charging_status_samples from totals?

Same reason: `state_samples=6` directly encodes "in charging
state." `chg_status=1` is a partially-redundant signal. For
sessions where state_samples is incomplete and chg_status_samples
is complete, we lose some accuracy — but that scenario is
unusual, and falling back to "Other" is honest. (Bug C affects
all sample lists symmetrically.)

## Components

### Refactored `_compute_time_breakdown`

```python
_MOWING_STATE_CODES: set[int] = {1}  # narrower than the previous {1,2,3}
                                      # set; 2 (IDLE) and 3 (PAUSED) are not
                                      # actively mowing. The replay-card's
                                      # _MOWING_STATES is for "highlight in
                                      # green on map" semantics — different
                                      # use case, kept separate.
_CHARGING_STATE_CODE: int = 6


def _compute_time_breakdown(
    battery_samples: list[list[int]],         # unused for totals — keep
    charging_status_samples: list[list[int]], # unused for totals — keep
    start_ts: int,
    end_ts: int,
    *,
    error_samples: list[list[int]] | None = None,
    state_samples: list[list[int]] | None = None,
) -> tuple[int | None, int | None, int, int | None]:
    """Split the session wall-clock into (mowing, charging, rain, other) minutes.

    Returns minutes (int). Buckets are mutually exclusive and sum
    to the session's elapsed minutes exactly.

    Priority order (highest first):
      1. Rain delay  — any second inside an s2p2=56 window
      2. Mowing      — state=1 outside rain
      3. Charging    — state=6 outside rain
      4. Other       — remainder
    """
    if state_samples is None or not state_samples:
        # Degenerate input: we can't classify state-time at all.
        # Preserve the existing 4-tuple shape with rain still
        # computed from error_samples if any.
        rain_s = _seconds_in_rain(error_samples or [], start_ts, end_ts)
        return (None, None, rain_s // 60, None)

    rain_intervals = _build_rain_intervals(
        error_samples or [], start_ts, end_ts,
    )
    rain_s = _interval_total_seconds(rain_intervals)

    state_intervals = _build_state_intervals(
        state_samples, start_ts, end_ts,
    )
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

### New helpers

```python
def _build_rain_intervals(
    error_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int]]:
    """Walk error_samples; each 'enter err=56' opens, next 'leave 56' closes.

    Robust to consecutive err=56 events (treated as one window) and
    to a 56 that's never closed before end_ts (extends to end_ts).
    Clamps interval endpoints to [start_ts, end_ts].
    """


def _build_state_intervals(
    state_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int, int]]:
    """Forward-fill state_samples into [start_ts, end_ts] step intervals.

    Returns a list of (interval_start, interval_end, state_code).
    The gap [start_ts, first_state_ts] gets state=-1 (sentinel for
    "unknown"; never matches mowing/charging filters → falls into
    Other).
    """


def _state_seconds_outside_intervals(
    state_intervals: list[tuple[int, int, int]],
    target_states: set[int],
    excluded_intervals: list[tuple[int, int]],
) -> int:
    """Sum seconds in any state_interval whose state ∈ target_states,
    EXCLUDING any overlap with excluded_intervals.
    """


def _interval_total_seconds(intervals: list[tuple[int, int]]) -> int:
    """Sum (end - start) over intervals. Assumes non-overlapping
    (which _build_rain_intervals guarantees)."""


def _seconds_in_rain(
    error_samples: list[list[int]], start_ts: int, end_ts: int,
) -> int:
    """Helper for the degenerate-state-samples path."""
```

### Removed helper

`_compute_rain_pause_seconds` (added by 2026-05-16 spec, Part 2) is
removed. Its role — "find rain pause time" — is now covered by
`_build_rain_intervals` + `_interval_total_seconds` which return
the same number but expose the underlying intervals for the
exclusion logic.

The function's call sites (build_picked_session_summary +
_compute_time_breakdown) and its 5 unit tests are migrated to the
new helpers.

## Data flow

Unchanged from before — session-finalize still calls
`build_picked_session_summary` which calls
`_compute_time_breakdown` with `state_samples=ss, error_samples=
err_samples`. The internal algorithm changes; the contract
(return shape, attribute names on the picked-session sensor)
stays the same.

## Testing

**Unit (new, `tests/protocol/test_session_card.py`):**

- `test_build_rain_intervals_single_window` — one 56 event, one
  non-56 close.
- `test_build_rain_intervals_extends_to_end_when_unclosed` — 56
  without close.
- `test_build_rain_intervals_merges_consecutive_56_events` — two
  56 events with no non-56 between them = one window.
- `test_build_rain_intervals_three_windows` — three distinct
  windows like the 19h session.
- `test_build_state_intervals_forward_fill` — gap before first
  sample becomes state=-1.
- `test_build_state_intervals_clamps_to_window` — entries outside
  [start_ts, end_ts] are clipped.
- `test_state_seconds_outside_intervals_basic` — pure-function
  intersection arithmetic.
- `test_compute_time_breakdown_19h_session_fixture` — pin the
  exact ground-truth numbers (Mowing=271, Charging=151, Rain=720,
  Other=5, sum=1148) using a fixture derived from the probe-log
  timeline. **This is the load-bearing regression test.**
- `test_compute_time_breakdown_empty_state_samples_returns_none` —
  degenerate guard still works.
- `test_compute_time_breakdown_simple_no_rain_session` — sanity:
  100% mowing session returns (X, 0, 0, 0) with X = elapsed_min.

**Existing tests that need to be updated:**

The 7 existing `test_time_breakdown_*` / `test_rain_pause_*` tests
in `tests/protocol/test_session_card.py` use battery-drop-based
fixtures. Most need rewriting to feed `state_samples` instead.

**Integration:**
- The existing `tests/integration/test_picked_session.py` tests
  consume the function output via `out["time_*_min"]`. They should
  continue to pass (return shape unchanged) but the test fixtures
  may need updated expected values.

## Manual verification

After ship, on the next finalize:

1. Pull the new session JSON.
2. Compute ground truth from probe log (if probe was running):
   `python3 /tmp/state_partition.py <session.json> <probe.log>`
   (script to be added under `tools/`).
3. Compare against `time_mowing_min` / `time_charging_min` /
   `time_rain_protection_min` / `time_other_min`.
4. The four should now sum to elapsed minutes.

## Risks

1. **State-samples gaps look like Other.** Bug C (in_progress.json
   data loss) plus the new algorithm means lost-data periods
   show as Other instead of being silently re-classified as
   battery-flicker mowing. That's a CORRECTNESS improvement, but
   users may see a large Other and ask why. Dashboard caption can
   help: "Other includes idle, transitions, and periods with
   incomplete telemetry."

2. **`{1}` vs `{1, 2, 3}` for mowing.** The replay-card uses
   `{1, 2, 3}` to color the map. For the time totals, state=2
   (IDLE, ~1 sec transitional) and state=3 (PAUSED, manual stop)
   are not actively cutting grass. Going with `{1}` only — if a
   user pauses for 5 minutes mid-mow that's "Other", which is
   honest.

3. **State=13 (CHG_COMPLETED) at end of session.** If the mower
   finishes mowing, returns to dock, charges to full, and sits at
   100% until the session-end event fires, that final 5-10 min
   of state=13 is "Other." Users expecting it to count as
   "Charging" may complain. We can revisit by either (a)
   broadening CHARGING to {6, 13} or (b) adding a fifth bucket
   "At dock (idle)". Spec-level decision deferred until we have
   user data on this.

4. **What if state_samples has multiple identical-state entries?**
   Forward-fill is idempotent on dup state codes; `_build_state_intervals`
   just emits zero-length intervals for the dupes and the totaling
   sums to the right total. Tested.

5. **Performance.** For an extreme session (~500 state entries, ~10
   rain windows), the interval arithmetic is O(N×M) but N,M < 1000
   so total under 10ms. No optimization needed.

## Out of scope

- The "at dock idle (state=13)" fifth bucket. See Risk 3.
- Fixing Bug C (in_progress.json data loss). See
  `project-session-persist-audit-todo`.
- Reprocessing the existing 19h session archive to update its
  numbers retroactively. Can be done as a one-shot tool but isn't
  required for the steady-state fix.
- Removing battery_samples / charging_status_samples from the
  archive. They're still needed for the chart.

## Acceptance criteria

- A new session's `sensor.dreame_a2_mower_picked_session`
  attributes `time_mowing_min + time_charging_min +
  time_rain_protection_min + time_other_min` equals
  `(end_ts - start_ts) // 60` exactly.
- For the 19h session probe-log fixture, the breakdown matches:
  Mowing ≈ 272, Charging ≈ 151, Rain ≈ 720, Other ≈ 5 (within
  ±2 min for floor-rounding).
- An empty `state_samples` returns `(None, None, rain_min, None)`
  preserving the prior degenerate-guard behavior.
- The dashboard's existing "Rain protection delay" row continues
  to render.
- All existing `tests/protocol/test_session_card.py` and
  `tests/integration/test_picked_session.py` tests pass with
  updated fixtures.

## Related

- `2026-05-16-session-recorder-merge-and-rain-bucket-design.md` —
  superseded Part 2 (battery-flicker-based mowing). Part 1
  (recorder-merge safety net for battery + wifi samples) stays.
- `project-session-persist-audit-todo` — Bug C, the broader
  reliability issue.
