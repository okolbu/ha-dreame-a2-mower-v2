# Doc 1 — Per-Dimension Transition Matrix

Every input event that can flip a `StateSnapshot` dimension, one table per
dimension. The authoritative reference is the source file
[`custom_components/dreame_a2_mower/mower/state_machine.py`][src]. This document
is **hand-curated** and can drift; when in doubt, re-read the source.

[src]: ../../../custom_components/dreame_a2_mower/mower/state_machine.py

## Matrix format

Each row records a single state mutation observed inside a method of
`MowerStateMachine`:

| Column | Meaning |
|--------|---------|
| **From** | Pre-condition on the dimension (`*` = any value). |
| **To** | Post-condition on the dimension. |
| **Trigger** | The input event / call site that caused the mutation. |
| **Source** | `state_machine.py:<line>` plus the owning method. |
| **Guards** | Additional pre-conditions that must hold (other dimensions, freshness, etc.). `—` = none. |

The dimensions covered match the public fields of `StateSnapshot` (see
[`mower/state_snapshot.py`][snapshot]).

[snapshot]: ../../../custom_components/dreame_a2_mower/mower/state_snapshot.py

Cross references:

- s2p2 event-code semantics — [`docs/research/g2408-protocol.md`](../g2408-protocol.md)
- CFG.DOCK staleness — [`docs/research/cloud-write-reference.md` § "Cloud-side propagation lag"](../cloud-write-reference.md#cloud-side-propagation-lag)

---

## `mow_session`

Values: `IN_SESSION`, `BETWEEN_SESSIONS`. Initial: `BETWEEN_SESSIONS`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| * | BETWEEN_SESSIONS | s2p1 = 2 (task done) | `state_machine.py:110` (`_apply_s2p1_task_state`) | — |
| * | IN_SESSION | s2p2 = 50 or 53 (mowing_started / scheduled_mowing_started) | `state_machine.py:149` (`_apply_s2p2_event`) | — |
| * | BETWEEN_SESSIONS | s2p2 = 48 (mowing_complete) | `state_machine.py:154` (`_apply_s2p2_event`) | — |
| ≠ IN_SESSION | IN_SESSION | s2p50 TASK echo, op ∈ {100, 101, 102, 103} (start mow variants) | `state_machine.py:209` (`_apply_s2p50_task_envelope`) | `status` ≠ False |
| ≠ BETWEEN_SESSIONS | BETWEEN_SESSIONS | `end_session()` (coordinator finalize hook) | `state_machine.py:308` (`end_session`) | — |
| BETWEEN_SESSIONS | IN_SESSION | `seed_in_session()` (coordinator post-reload restore) | `state_machine.py:337` (`seed_in_session`) | only when `mow_session == BETWEEN_SESSIONS` (no-op otherwise) |
| BETWEEN_SESSIONS | IN_SESSION | telemetry reconcile: `live_map_active` and `area_mowed_m2 > 0` | `state_machine.py:390` (`reconcile_from_telemetry`) | gated on `BETWEEN_SESSIONS`; `area_mowed_m2 is not None and > 0` |
| IN_SESSION | BETWEEN_SESSIONS | telemetry reconcile: `live_map_active` is False | `state_machine.py:405` (`reconcile_from_telemetry`) | gated on `IN_SESSION` |

---

## `current_activity`

Values: `MOWING`, `PAUSED`, `REPOSITIONING`, `RETURNING`, `CHARGE_RESUME`,
`CRUISING_TO_POINT`, `AT_POINT`, `FAST_MAPPING`, `DRIVING_BLADES_UP`, `IDLE`.
Initial: `IDLE`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| ≠ MOWING | MOWING | s2p1 = 1 (working) | `state_machine.py:116` (`_apply_s2p1_task_state`) | only when value differs |
| ≠ IDLE | IDLE | s2p1 = 2 (task done) | `state_machine.py:116` (`_apply_s2p1_task_state`) | only when value differs |
| ≠ RETURNING | RETURNING | s2p1 = 5 (returning to dock) | `state_machine.py:116` (`_apply_s2p1_task_state`) | only when value differs |
| ≠ CHARGE_RESUME | CHARGE_RESUME | s2p1 = 6 (mid-mow charge-resume) | `state_machine.py:116` (`_apply_s2p1_task_state`) | only when value differs |
| * | MOWING | s2p2 = 50 or 53 (mowing_started / scheduled_mowing_started) | `state_machine.py:150` (`_apply_s2p2_event`) | — |
| * | IDLE | s2p2 = 48 (mowing_complete) | `state_machine.py:155` (`_apply_s2p2_event`) | — |
| * | AT_POINT | s2p2 = 75 (arrived_at_maintenance_point) | `state_machine.py:160` (`_apply_s2p2_event`) | — |
| ≠ MOWING | MOWING | s2p50 TASK echo, op ∈ {100, 101, 102, 103} | `state_machine.py:205` (`_apply_s2p50_task_envelope`) | `status` ≠ False |
| ≠ CRUISING_TO_POINT | CRUISING_TO_POINT | s2p50 TASK echo, op = 109 (cruise) | `state_machine.py:205` (`_apply_s2p50_task_envelope`) | `status` ≠ False |
| ≠ FAST_MAPPING | FAST_MAPPING | s2p50 TASK echo, op = 10 | `state_machine.py:205` (`_apply_s2p50_task_envelope`) | `status` ≠ False |
| CRUISING_TO_POINT | AT_POINT | s2p56 lifecycle stage = 2 | `state_machine.py:236` (`_apply_s2p56_lifecycle`) | gated on `current_activity == CRUISING_TO_POINT` |
| ≠ IDLE | IDLE | `end_session()` (coordinator finalize hook) | `state_machine.py:311` (`end_session`) | — |
| IDLE | MOWING | `seed_in_session()` (coordinator post-reload restore) | `state_machine.py:341` (`seed_in_session`) | only when `current_activity == IDLE`; preserves PAUSED / RETURNING / CHARGE_RESUME |
| * | MOWING | telemetry reconcile: `BETWEEN_SESSIONS` + `live_map_active` + `area_mowed_m2 > 0` | `state_machine.py:391` (`reconcile_from_telemetry`) | session inference branch |
| * | IDLE | telemetry reconcile: `IN_SESSION` + not `live_map_active` | `state_machine.py:406` (`reconcile_from_telemetry`) | inverse session inference |
| CHARGE_RESUME | MOWING | telemetry reconcile: stuck-activity recovery | `state_machine.py:423` (`reconcile_from_telemetry`) | `IN_SESSION` + `location != AT_DOCK` + `area_mowed_m2 > 0` |
| MOWING | CHARGE_RESUME | telemetry reconcile: mirror at-dock recovery | `state_machine.py:436` (`reconcile_from_telemetry`) | `IN_SESSION` + `location == AT_DOCK` |

Notes:
- The s2p1 handler also writes `current_activity` whenever the mapped value
  differs from the current — single source line (`updates["current_activity"] = new_activity`),
  one row per task_state value listed above.
- s2p2 codes that don't appear above (e.g. 71, 31, 33) only stamp `raw_s2p2`;
  the `mqtt_connectivity` / `positioning_health` follow-up happens later in
  `tick()`.
- `s2p1 == 5` while an s2p2=71 buffer is open sets a side flag
  (`_s2p2_71_saw_returning`) used by `tick()`; it does not itself mutate
  `current_activity` beyond the regular RETURNING row above (line 96).
- `PAUSED`, `REPOSITIONING`, and `DRIVING_BLADES_UP` are valid values for the
  dimension but are not currently produced by any mutation in
  `state_machine.py` — they would arrive via future wiring.

---

## `location`

Values: `AT_DOCK`, `ON_LAWN`, `AT_POINT`, `OUTSIDE_KNOWN_AREA`. Initial: `AT_DOCK`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| * | AT_POINT | s2p2 = 75 (arrived_at_maintenance_point) | `state_machine.py:159` (`_apply_s2p2_event`) | — |
| * | AT_DOCK | cloud poll CFG.DOCK `connect_status = 1` | `state_machine.py:289` (`_apply_cloud_dock`) | `now_unix > field_freshness["location"]`; suppressed when `mow_session == IN_SESSION` AND `location == ON_LAWN` (cloud lag guard) |
| * | ON_LAWN | cloud poll CFG.DOCK `connect_status = 0` | `state_machine.py:289` (`_apply_cloud_dock`) | `now_unix > field_freshness["location"]` |
| ≠ AT_DOCK | AT_DOCK | charging False → True (s3p2) | `state_machine.py:581` (`_apply_charging`) | only on rising edge; overrides the IN_SESSION+ON_LAWN suppression because charging is the strongest at-dock signal |
| ≠ AT_DOCK | AT_DOCK | battery rise inferring charging=True | `state_machine.py:614` (`_apply_battery_percent`) | requires `prev is not None`, `new > prev`, `not snapshot.charging`; tied to the inferred-charging side effect |
| AT_DOCK | ON_LAWN | telemetry reconcile: position > `OFF_DOCK_THRESHOLD_M` (1.0 m) from dock origin | `state_machine.py:452` (`reconcile_from_telemetry`) | gated on `location == AT_DOCK`; `position_x_m` and `position_y_m` not None; never overwrites AT_POINT / OUTSIDE_KNOWN_AREA |
| * | OUTSIDE_KNOWN_AREA | s2p2 = 71 buffer expired with follow-up code 31 or 33 | `state_machine.py:510` (`tick`) | `S2P2_71_WINDOW_S` (30 s) elapsed since s2p2=71; paired with `positioning_health = STUCK` |

---

## `charging`

Values: `bool`. Initial: `False`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| ≠ value | value | s3p2 (explicit charging flag) | `state_machine.py:577` (`_apply_charging`) | no-op when current value matches; freshness stamp on change only |
| False | True | battery_percent rising and not currently charging | `state_machine.py:610` (`_apply_battery_percent`) | requires `prev is not None`, `new > prev`, `not snapshot.charging` (only inferred on a rise; falling battery is left alone — firmware s3p2=0 is authoritative for clearing) |

---

## `positioning_health`

Values: `LOCALIZED`, `RELOCATING`, `STUCK`. Initial: `LOCALIZED`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| * | STUCK | s2p2 = 71 buffer expired with follow-up code 31 or 33 | `state_machine.py:509` (`tick`) | `S2P2_71_WINDOW_S` (30 s) elapsed since s2p2=71; paired with `location = OUTSIDE_KNOWN_AREA` |

Notes:
- The other two `tick()` outcomes (saw s2p1=5 RETURNING, or no follow-up) leave
  `positioning_health` untouched — they only clear the buffer.
- `RELOCATING` is a valid value but no current mutation produces it.

---

## `mqtt_connectivity`

Values: `ONLINE`, `STALE`. Initial: `STALE`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| * | ONLINE | s1p1 heartbeat arrived | `state_machine.py:473` (`handle_heartbeat`) | unconditional (every heartbeat flips to ONLINE) |
| ≠ STALE | STALE | `tick()` observed `now_unix − last_heartbeat_unix > HB_STALENESS_S` (90 s) | `state_machine.py:502` (`tick`) | only when `last_heartbeat_unix is not None` |

---

## `errors`

Values: `frozenset[int]`. Initial: `frozenset()`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| — | — | (no mutation present in `state_machine.py`) | — | — |

The dimension exists on `StateSnapshot` but no mutation path currently writes
it; it stays at the initial empty frozenset for the lifetime of the state
machine. Error surfacing happens elsewhere in the integration today.

---

## `pin_required`

Values: `bool`. Initial: `False`.

| From | To | Trigger | Source (file:line) | Guards |
|------|----|---------|--------------------|--------|
| ≠ `hb.emergency_stop` | `hb.emergency_stop` | s1p1 heartbeat with differing `emergency_stop` flag | `state_machine.py:476` (`handle_heartbeat`) | only when value changes (freshness bumps on change only) |

---

## Adjacent scalars + provenance fields

These are not state-machine *dimensions* but are mutated alongside transitions
above. Documented here for completeness so the audit's idle/reboot checks have
a place to find them.

| Field | Mutating method(s) | Notes |
|-------|--------------------|-------|
| `raw_s2p1` | `_apply_s2p1_task_state` (line 114) | always stamped on every s2p1 |
| `raw_s2p2` | `_apply_s2p2_event` (line 144) | always stamped on every s2p2 |
| `last_task_op` | `_apply_s2p50_task_envelope` (line 190) | stamped regardless of `status` (so rejections are diagnosable) |
| `battery_percent` | `_apply_battery_percent` (line 603) | no-op on same value |
| `last_heartbeat_unix` | `handle_heartbeat` (line 472) | always updated to `now_unix` |
| `pin_required` | `handle_heartbeat` (line 476) | see table above |
| `wifi_rssi_dbm` | `handle_heartbeat` (line 479) | only when value changes |
| `field_freshness` | every mutator | per-field unix stamp, used by `_apply_cloud_dock` to honour MQTT-primary precedence |

`_apply_scalar` (line 618) is a generic helper but has no current call sites
from within the state machine — listed for completeness only.

Static fields with no current mutation path: `cloud_rpc_health`, `error_code`,
`position_x_m`, `position_y_m`, `position_north_m`, `position_east_m`,
`paused_from`. They stay at the values produced by `StateSnapshot.initial()` or
the persisted snapshot restored by `load_persisted`.
