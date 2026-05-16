# Session Recorder-Merge + Rain-Protection Time Bucket — Design

**Date:** 2026-05-16
**Status:** Draft (pending user review)

## Problem

Two related session-finalize-time correctness issues:

### A. Sample arrays lose data across reboots

The 2026-05-15 08:00 mowing session lasted 19.13 h (rain-protection
caused multiple 4-hour backoffs). HA was restarted dozens of times
during that window. The persisted session JSON correctly captures
`start=08:00, end=03:08+1d` and the firmware-side mowing-minutes
total, but the per-tick sample arrays (`battery_samples`,
`wifi_samples`) only span the last 10.8 h starting at 16:19 — the
timestamp of the LAST HA restart before session-end.

The existing in_progress.json persistence (30s debounced via
`_persist_in_progress`) plus the boot-time `_restore_in_progress`
read-back is the load-bearing mechanism that's supposed to keep
samples alive across restarts. It IS implemented and DOES handle
all five sample lists. But something in the chain broke during
this multi-restart stretch (root cause unknown — possibly a
persist-skipped-because-not-dirty bypass during a long charge
interval, possibly an in_progress.json write failure, possibly a
restore that found stale legs and bailed).

### B. Rain-protection sit-time isn't broken out from "other"

The same session reports `time_mowing_min=267, time_charging_min=
<x>, time_other_min=<y>` — but the "other" bucket bundles two
distinct things: actual mid-session pauses (manual stop, brief
faults) AND the multi-hour at-dock sits triggered by rain protection.
For a 19 h session that's 12 h of rain delay sitting in "other",
making the breakdown misleading.

## Non-goals

- Replacing the in_progress.json persistence. The 30s-debounced
  layer stays as-is. The recorder merge is a finalize-time safety
  net, not a replacement.
- Recovering data lost to power outages. If HA goes down before
  the periodic persist can flush, AND HA recorder hasn't committed
  the corresponding entity state yet, those samples are gone. The
  design accepts this — out of scope.
- Fixing the underlying in_progress.json reliability bug. The
  recorder-merge papers over the symptom for battery/wifi
  specifically. Other persisted lists (charging_status_samples,
  state_samples, error_samples) keep their existing reliability
  profile. A separate `project_session_persist_audit_todo` memo
  captures the broader investigation.
- Adding HA recorder entities for the three lists without
  corresponding sensor entities. That's a meaningful API addition
  and belongs to the persist-audit follow-up.

## Architecture

```
session-finalize path  (existing)
        │
        ▼
load samples from in_progress.json into raw_dict
        │
        ▼
[NEW] merge_recorder_samples(raw_dict, start_ts, end_ts, hass)
        │   ├─ query sensor.dreame_a2_mower_battery history → merge into battery_samples
        │   └─ query sensor.dreame_a2_mower_wifi_rssi history → merge into wifi_samples
        ▼
[NEW] _compute_time_breakdown(...) returns 4-tuple including rain_pause_min
        │
        ▼
write session JSON to disk + build picked_session attributes
```

Two clearly bounded additions, each in its own small module.

## Components

### Part 1 — Recorder merge

**New module:** `coordinator/_recorder_merge.py`

```python
async def merge_recorder_samples(
    hass: HomeAssistant,
    raw_dict: dict[str, Any],
    start_ts: int,
    end_ts: int,
) -> dict[str, int]:
    """Merge HA recorder history for the session's battery+wifi entities
    into raw_dict's sample arrays.

    Idempotent. Dedup key is (timestamp_unix, value). Sorts merged
    lists by timestamp ascending. Returns counts of merged-net-new
    samples per category for logging.

    Wrapped in recorder.get_instance(hass).async_add_executor_job(...)
    so the event loop stays clean.
    """
```

**Internals:**

```python
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period

@callback
def _read_battery_history_sync(hass, start_dt, end_dt):
    # state_changes_during_period returns {entity_id: [State, ...]}
    states = state_changes_during_period(
        hass,
        start_dt,
        end_dt,
        entity_id="sensor.dreame_a2_mower_battery",
        include_start_time_state=True,
    )
    out = []
    for s in states.get("sensor.dreame_a2_mower_battery", []):
        try:
            v = int(s.state)
        except (TypeError, ValueError):
            continue  # 'unknown', 'unavailable', etc.
        if not 0 <= v <= 100:
            continue
        out.append([int(s.last_changed.timestamp()), v])
    return out
```

WiFi parallel — entity `sensor.dreame_a2_mower_wifi_rssi`, state is the dBm integer. Recorder-sourced samples are formatted as `[None, None, rssi, ts]` (matching the existing 4-tuple shape, with positional fields nulled since the recorder doesn't have lat/lon for these readings).

**Dedup:**

```python
def _merge_samples(existing, recorder):
    """Combine two sample lists; dedup on (ts, value); sort by ts."""
    seen = {(s[0], s[1]) for s in existing}
    out = list(existing)
    for s in recorder:
        if (s[0], s[1]) in seen:
            continue
        out.append(s)
        seen.add((s[0], s[1]))
    out.sort(key=lambda s: s[0])
    return out
```

WiFi uses `(ts, rssi)` as the dedup key (index 3 + index 2).

**Call site:** In `_session.py`, find the session-finalize code paths that build raw_dict before the final write (search for `raw_dict["battery_samples"]` and `session_archive.write`). Insert:

```python
from ._recorder_merge import merge_recorder_samples

try:
    counts = await merge_recorder_samples(
        self.hass, raw_dict, summary.start_ts, summary.end_ts,
    )
    LOGGER.info(
        "[recorder-merge] added %d battery + %d wifi samples to session %s",
        counts.get("battery_added", 0),
        counts.get("wifi_added", 0),
        session_md5,
    )
except Exception:
    LOGGER.exception(
        "[recorder-merge] failed for session %s; using in_progress samples only",
        session_md5,
    )
```

Wrapped in try/except so a recorder query failure can never block the session-finalize.

**Error handling:**

- Recorder not loaded (rare): `get_instance` raises. Caught, logged, fallback to in_progress samples only.
- Entity unknown to recorder (entity disabled, renamed): `state_changes_during_period` returns `{}`. Merge adds 0 samples — no fallback needed.
- Recorder query exceeds available history (session older than retention): query returns what's available. The merged set is the union of (in_progress, recorder); gaps that exist in BOTH stay as gaps in the final session JSON.

### Part 2 — Rain-protection time bucket

**Modify:** `session_card.py:_compute_time_breakdown`

Currently returns `(mow_min, chg_min, other_min)`. Upgrade to return `(mow_min, chg_min, rain_pause_min, other_min)`, where:

- `rain_pause_min` = sum of intervals where the mower is at-dock-and-not-charging AFTER an `s2p2 = 56` (rain_protection) event and BEFORE the next mowing resume.
- `other_min` excludes `rain_pause_min` — totals still sum to `elapsed_min`.

**Detection:**

```python
def _compute_rain_pause_seconds(
    error_samples: list[list[int]],
    state_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> int:
    """Sum seconds spent in rain-protection backoff (s2p2=56 → next
    state_samples transition back to a mowing code).

    Each s2p2=56 in error_samples opens an interval. The interval
    closes at the first subsequent state_samples entry whose value
    is in {1, 2, 3} (the mowing-state codes from
    PROPERTY_MAPPING). If no closing transition is seen before
    end_ts, the interval extends to end_ts (rain backoff that
    outlasted the session).
    """
```

The mowing-state classifier already exists in
`dreame-mower-replay-card.js:_MOWING_STATES = new Set([1, 2, 3])`.
Use the same set for consistency.

**Output:** new attribute `out["time_rain_protection_min"] = rain_pause_min` on `sensor.dreame_a2_mower_picked_session`. Existing `out["time_other_min"]` decreases by the same amount. Total still equals elapsed.

**Dashboard:** add one row to the time-breakdown card in the Sessions tab:

```yaml
- entity: sensor.dreame_a2_mower_picked_session
  attribute: time_rain_protection_min
  name: Rain protection delay (min)
```

## Data flow

```
session-end MQTT event
    ↓
existing OSS-fetch and/or finalize_incomplete path runs
    ↓
load in_progress.json → raw_dict (existing)
    ↓
[NEW] merge_recorder_samples(raw_dict, start_ts, end_ts)
       ├─ recorder.get_instance().async_add_executor_job(_read_battery_history_sync, ...)
       └─ recorder.get_instance().async_add_executor_job(_read_wifi_history_sync, ...)
    ↓
session_summary.parse_session_summary(raw_dict)  (existing)
    ↓
session_card.build_picked_session_summary(raw_dict, summary, entry, ...)
       └─ [NEW] _compute_time_breakdown now returns 4-tuple
       └─ [NEW] out["time_rain_protection_min"] populated
    ↓
session_archive.write(...)  (existing)
```

## Testing

**Unit:**
- `tests/coordinator/test_recorder_merge.py`:
  - Empty in_progress + recorder has 100 battery samples → merged list has 100 entries
  - in_progress has 50 samples + recorder has 100 samples with 30 overlap → merged 120, sorted
  - Recorder entity unknown → merge returns unchanged
  - Recorder query raises → exception propagates (caller wraps in try/except)
- `tests/protocol/test_session_card.py`:
  - Session with one s2p2=56 + state_samples showing resume after 4 h → time_rain_protection_min = 240
  - Session with two s2p2=56 events → sum of both intervals
  - Session with s2p2=56 but no closing transition → interval extends to end_ts
  - Session with no s2p2=56 → time_rain_protection_min = 0, time_other_min unchanged

**Integration:**
- Manual test on the 19h session (2026-05-15): re-finalize via service call, verify battery_samples now spans the full 19h.

## Risks

1. **Recorder retention shorter than session.** Configurable per-install (default 10 days). A session that spans more than the configured retention won't be fully covered. Log a WARNING when this happens. Out of scope to enforce a minimum.

2. **Sample-rate mismatch.** The in_progress.json samples come from MQTT push events (e.g., battery 1%-step changes). The recorder samples come from HA's commit cadence (default 5s). Merged list may have denser stretches where both sources contributed. Acceptable — chart rendering handles arbitrary spacing.

3. **Sensor renamed.** If a user renames the battery entity, the hardcoded entity_id lookup fails silently (returns 0 merged samples). Mitigation: read entity_id from a constant in `const.py` that's also used by the sensor registration. Already the case for the sensor's `_attr_unique_id`; just need to surface the resolved entity_id at finalize time. Defer the indirection until someone reports it.

4. **Recorder queries on the event loop.** Wrapped in
`async_add_executor_job` so the loop stays clean. The existing
integration's `read_text` blocking-call WARNING is the precedent
for getting this wrong; the wrapper avoids it.

## Out of scope (deferred to other TODOs)

- Underlying in_progress.json reliability fix. Captured in
  `project_session_persist_audit_todo` memo. The recorder-merge
  here papers over the symptom for battery/wifi.
- Persisting `charging_status_samples`, `state_samples`,
  `error_samples` via recorder (no HA entities exist for them).
  Future option: add diagnostic sensors for each so the recorder
  captures them. Spec-level decision deferred.
- Backfilling previously-archived incomplete sessions (e.g.,
  re-finalize the 19h session to get its full samples). Doable as
  a one-shot tool but not required for the steady-state fix.

## Acceptance criteria

- A new session whose `in_progress.json` is missing battery samples
  for any sub-window of `[start_ts, end_ts]` ends up with a
  session JSON whose `battery_samples` spans the full window
  (subject to recorder retention).
- The same is true for `wifi_samples`.
- `sensor.dreame_a2_mower_picked_session.attributes.time_rain_protection_min`
  reports the cumulative rain-protection backoff time for any
  picked session.
- The dashboard's time-breakdown card shows a "Rain protection
  delay" row alongside Mowing / Charging / Other, with the four
  values summing to `elapsed_min`.
