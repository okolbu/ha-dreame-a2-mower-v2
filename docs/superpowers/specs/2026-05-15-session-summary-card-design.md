# Session-summary card — design

**Date**: 2026-05-15
**Target version**: v1.0.13a1 — sensor, builder, settings_snapshot capture, and dashboard rebuild ship in a single release. Patches (v1.0.13a2+) get cut only if smoke-test reveals issues.
**Status**: brainstormed; awaiting spec review.

## Problem

The Sessions tab on the bundled dashboard has a picker (`select.dreame_a2_mower_work_log`) and a map replay, but no card surfaces the **picked session's** stats. The `Session details` card shows `latest_session_*` sensors — those always reflect the most recent archived session, not whichever one the user selected. With v1.0.12a2 now persisting battery / charging / state / error / wifi sample streams plus `charge_at_start` (and all 49 historical sessions backfilled), there's enough data per session to drive a rich summary surface.

The dashboard is also a showcase for first-time installers, so the new cards should demonstrate the integration's breadth without making the tab cluttered.

## Goals

1. A picked-session summary surface that updates when the user selects a different entry in the work-log picker.
2. Four conceptual groupings, each rendered as its own card: identity/outcome, coverage/efficiency, energy/time-breakdown, diagnostics. Plus a fifth optional "settings-in-effect" card and two chart cards (battery, RSSI).
3. Tab layout that keeps cross-session stuff (calendar, totals, latest) and picker at the top, the replay map prominent, and the per-session detail cards below a visual divider — visible only when something is picked.
4. Capture per-map settings at session-begin so future archives carry an authoritative settings_snapshot (current archives can't be backfilled — settings change over time).
5. Cover the derivation logic with isolated unit tests against real backfilled fixtures.

## Non-goals

- Backfilling settings_snapshot into pre-v1.0.13a1 archives. The values aren't recoverable from probe logs alone (we'd need a contemporaneous cloud SETTINGS dump for each session). The settings-snapshot card gracefully hides on older entries.
- Replacing the existing `latest_session_*` sensors. They keep working as-is for users who reference them in automations.
- Replay of state/battery curves through HA's recorder. Charts read from the picked-session sensor's attribute lists via apexcharts-card's `data_generator`. The recorder only ever sees the picker's current state.
- Cross-session trend cards (e.g. "battery efficiency over the last 30 days"). Belongs in a future plan once we know what's interesting.
- Decoding the unknown enums (`pre_type`, `start_mode`, full `mode` / `stop_reason` tables). The card shows best-effort labels and falls back to `raw=N` for unmapped values, plus exposes `*_raw` attributes so users can spot inventory gaps and file them.

## Architecture

### New entity: `sensor.dreame_a2_mower_picked_session`

Class: `DreameA2PickedSessionSensor` in `custom_components/dreame_a2_mower/sensor.py`.

```python
class DreameA2PickedSessionSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Picked session"
    _attr_icon = "mdi:history"
    _attr_unique_id = mower_unique_id(coordinator, "picked_session")
    _attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        summary = self.coordinator._picked_session_summary
        return summary.get("label") if summary else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator._picked_session_summary or {}
```

- **State**: the picker label (e.g. `"[Mowing] [Map 1] 2026-05-13 14:00 — 285 m² / 278min"`); `None` when picker is on placeholder.
- **Attributes**: full picked-session summary dict (see § Attribute schema).

Does not appear in `SENSOR_DESCRIPTIONS` because the descriptor pattern is built around `MowerState.<field>` accessors; this sensor's value derives from a separate coordinator slot.

### Coordinator state

`_picked_session_summary: dict[str, Any] | None = None` — added to `_CoreMixin.__init__` in `coordinator/_core.py` alongside `_work_log_png`.

Populated/cleared in `coordinator/_session.py::render_work_log_session`. After loading the raw JSON and parsing the `SessionSummary`, but before rendering the PNG:

```python
from ..session_card import build_picked_session_summary

self._picked_session_summary = build_picked_session_summary(
    raw_dict=raw_dict,
    summary=summary,
    entry=entry,
    picker_label=picker_label,  # rebuilt from entry, matches dropdown
)
```

When the picker is set to the placeholder (`async_select_option` in `select.py`'s `DreameA2WorkLogSelect`), the existing branch that clears `_work_log_png` also sets `_picked_session_summary = None`.

After mutation, `self.async_update_listeners()` fires so the sensor's state updates immediately (the existing camera-ping path already does this; we piggyback).

### New pure module: `custom_components/dreame_a2_mower/session_card.py`

```python
def build_picked_session_summary(
    raw_dict: dict[str, Any],
    summary: SessionSummary,
    entry: ArchivedSession,
    picker_label: str,
) -> dict[str, Any]:
    """Compute the picked-session attribute dict.

    Pure function — no HA / coordinator imports. Returns a flat dict
    keyed by the names the dashboard cards reference.
    """
```

Lives outside `coordinator/` because:
1. It's pure derivation (input → dict), trivial to unit-test.
2. It's substantially big enough (~250 LOC) that adding it to the coordinator package would bloat one of the mixins.
3. The label-mapping tables (mode → label, stop_reason → label, etc.) belong with the function that uses them.

### Live-side settings snapshot (new field on LiveMapState)

```python
settings_snapshot: dict[str, Any] | None = None
```

Captured at session_begin in `coordinator/_mqtt_handlers.py::_on_state_update` at the same call site as `charge_at_start`:

```python
if is_active_now and not was_active_before and not self.live_map.is_active():
    self.live_map.begin_session(now_unix)
    if new_state.battery_level is not None:
        self.live_map.charge_at_start = int(new_state.battery_level)
    # NEW:
    if (
        getattr(self, "cloud_state", None) is not None
        and self._active_map_id is not None
    ):
        per_map = self.cloud_state.settings.by_map_id_canonical.get(
            int(self._active_map_id)
        )
        if isinstance(per_map, dict):
            self.live_map.settings_snapshot = dict(per_map)  # shallow copy
```

Persisted in `in_progress.json` (`coordinator/_session.py::_persist_in_progress`) under key `settings_snapshot`. Restored in `_restore_in_progress`. Injected into the archive payload in `coordinator/_lidar_oss.py::_do_oss_fetch` and the FINALIZE_INCOMPLETE path in `_session.py`.

### Dashboard restructure

The Sessions tab is reorganised from a 6-card vertical stack into a structured layout. See § Tab layout for the full picture.

## Attribute schema

All attributes are at the top level of `extra_state_attributes`. Grouped by which card consumes them.

### Identity & outcome

| Attribute | Type | Derivation |
|---|---|---|
| `label` | str | `picker_label` arg — matches what's in the dropdown |
| `md5` | str | `entry.md5` |
| `filename` | str | `entry.filename` |
| `map_id` | int \| None | `entry.map_id` |
| `started_at` | str (ISO local) | `summary.start_ts` formatted in HA's configured TZ |
| `ended_at` | str (ISO local) | `summary.end_ts` formatted |
| `started_at_unix` | int | `summary.start_ts` |
| `ended_at_unix` | int | `summary.end_ts` |
| `duration_min` | int | `summary.duration_min` |
| `mode_raw` | int | `summary.mode` |
| `mode_label` | str | from `MODE_LABELS` table |
| `pre_type_raw` | int | `summary.pre_type` |
| `pre_type_label` | str | from `PRE_TYPE_LABELS` (best-effort) |
| `start_mode_raw` | int | `summary.start_mode` |
| `start_mode_label` | str | from `START_MODE_LABELS` (best-effort) |
| `result_raw` | int | `summary.result` |
| `result_label` | str | `1` → "Completed"; other values → "raw=N" until classified |
| `stop_reason_raw` | int | `summary.stop_reason` |
| `stop_reason_label` | str | `-1` → "Natural end"; others → "raw=N" |
| `completed` | bool | `result == 1 and stop_reason in (-1, 0)` |

### Coverage & efficiency

| Attribute | Type | Derivation |
|---|---|---|
| `area_mowed_m2` | float | `summary.area_mowed_m2` |
| `map_area_m2` | int | `summary.map_area_m2` |
| `coverage_pct` | float \| None | `area / map_area * 100`, None when `map_area == 0` |
| `distance_m` | float | sum of pairwise euclidean over `_local_legs` (fallback to `summary.track_segments`) |
| `mowing_height_mm` | int \| None | `summary.pref[0]` if present |
| `mowing_efficiency_raw` | int \| None | `summary.pref[1]` if present |
| `mowing_efficiency_label` | str \| None | from `EFFICIENCY_LABELS` table |
| `m2_per_min` | float \| None | `area / duration_min`, None when `duration_min == 0` |
| `m2_per_pct` | float \| None | `area / charge_used_pct`, None when `charge_used_pct <= 0` |

### Energy & time-breakdown

| Attribute | Type | Derivation |
|---|---|---|
| `charge_at_start_pct` | int \| None | `raw_dict.get("charge_at_start")`; falls back to `battery_samples[0][1]` |
| `charge_at_end_pct` | int \| None | last `battery_samples` entry |
| `charge_min_pct` | int \| None | min over `battery_samples` |
| `charge_used_pct` | int | `max(0, start - end)`; underestimate when mid-mow recharges occurred — but `recharge_count` flags that |
| `recharge_count` | int | count of `0 → 1` transitions in `charging_status_samples` |
| `time_mowing_min` | int \| None | sum of intervals where state ∈ {mowing-state-codes}; None when `state_samples` empty |
| `time_charging_min` | int \| None | sum of intervals where `charging_status_samples[-1] == 1` |
| `time_other_min` | int \| None | `duration_min - mowing - charging`, clamped ≥ 0 |
| `battery_samples` | list[[int, int]] | passthrough — for chart card |

State-interval classification (helper `_classify_intervals`):
- Step-integrate `state_samples` over the session window. Mowing states: `{2, 5}` (best-effort — verify against probe samples; expose `time_*_min` as None if state_samples is empty rather than guessing).
- Step-integrate `charging_status_samples`; intervals with last seen value `1` are charging.
- "Other" is the remainder (idle, faults, transitions).

### Diagnostics

| Attribute | Type | Derivation |
|---|---|---|
| `fault_count` | int | `len(summary.faults)` |
| `faults_compact` | list[str] | first 5 entries of `summary.faults` coerced to `str(...)` (shape isn't decoded yet); truncates with "+N more" when > 5 |
| `obstacle_count` | int | `len(summary.obstacles)` |
| `ai_obstacle_count` | int | `len(summary.ai_obstacle)` |
| `state_transition_count` | int | `len(state_samples)` |
| `error_event_count` | int | `len(error_samples)` |
| `error_codes_seen` | list[int] | sorted unique values from `error_samples` |
| `wifi_rssi_min_dbm` | int \| None | min over `wifi_samples` 3rd column |
| `wifi_rssi_max_dbm` | int \| None | max |
| `wifi_rssi_avg_dbm` | int \| None | mean, rounded to int |
| `wifi_sample_count` | int | `len(wifi_samples)` |
| `wifi_samples` | list[[float, float, int, int]] | passthrough — for chart card |

### Settings-in-effect (conditional)

`settings_snapshot: dict[str, Any] | None` — passed through unchanged. When present, the dashboard card surfaces specific keys:

| Card row | Snapshot key |
|---|---|
| Mowing height | `settings_mowing_height_mm` |
| Mowing efficiency | `settings_mowing_efficiency` |
| EdgeMaster | `settings_edgemaster` |
| Edge mowing mode | `settings_edge_mowing_mode` |
| Edge walk mode | `settings_edge_mowing_walk_mode` |
| Obstacle avoidance | `settings_obstacle_avoidance_mode` |
| Obstacle avoidance AI | `settings_obstacle_avoidance_ai` |

Exact keys present depend on what `cloud_state.settings.by_map_id_canonical[active_map_id]` already populates today; the snapshot is a shallow copy. If a future CFG entry adds new per-map keys, they'll appear automatically.

## Tab layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Markdown header (trimmed — drop the "Map below renders the      │
│  session's recorded map_id" hint since the picker label already  │
│  shows [Map N])                                                  │
├──────────────────────────────────────────────────────────────────┤
│  TOP ROW (horizontal-stack)                                      │
│  ┌────────────────────────────────┬─────────────────────────────┐│
│  │ LEFT (vertical-stack)          │ RIGHT (single card)         ││
│  │  • atomic-calendar-revive      │  • picture-entity:          ││
│  │  • entities (Replay picker)    │      camera.work_log        ││
│  │  • entities (Latest archived)  │      aspect_ratio: 1/1      ││
│  │  • conditional entities        │      show_state: false      ││
│  │      (Live session — hidden    │                             ││
│  │       when mowing_session_     │                             ││
│  │       active == off)           │                             ││
│  │  • entities (Per-map totals)   │                             ││
│  └────────────────────────────────┴─────────────────────────────┘│
├──────────────────────────────────────────────────────────────────┤
│  ## Picked session                                               │
│  (markdown divider — also renders the picker label + completed   │
│  badge so the section heading itself reflects the selection)     │
├──────────────────────────────────────────────────────────────────┤
│  ROW 2 (horizontal-stack)                                        │
│  ┌────────────────────────────────┬─────────────────────────────┐│
│  │ Identity & Outcome (markdown)  │ Coverage & Efficiency       ││
│  │  templated from sensor's       │ (entities — display attrs   ││
│  │  attributes                    │  via type:attribute)        ││
│  └────────────────────────────────┴─────────────────────────────┘│
├──────────────────────────────────────────────────────────────────┤
│  ROW 3 (horizontal-stack)                                        │
│  ┌────────────────────────────────┬─────────────────────────────┐│
│  │ Energy & Time breakdown        │ Diagnostics                 ││
│  │ (entities + small step-chart)  │ (entities)                  ││
│  └────────────────────────────────┴─────────────────────────────┘│
├──────────────────────────────────────────────────────────────────┤
│  Settings in effect (entities)                                   │
│  conditional: hidden when settings_snapshot attribute is None    │
├──────────────────────────────────────────────────────────────────┤
│  Battery % over session (apexcharts-card, full width)            │
│  data_generator reads battery_samples attribute                  │
├──────────────────────────────────────────────────────────────────┤
│  WiFi RSSI over session (apexcharts-card, full width)            │
│  data_generator reads wifi_samples attribute                     │
└──────────────────────────────────────────────────────────────────┘
```

### Conditional visibility

All cards below the `## Picked session` divider use HA's per-card `visibility:` block:

```yaml
visibility:
  - condition: state
    entity: select.dreame_a2_mower_work_log
    state_not: "(no session selected)"
```

(Exact placeholder string lifted from `DreameA2WorkLogSelect._placeholder`.)

The Settings-in-effect card stacks a second condition:

```yaml
visibility:
  - condition: state
    entity: select.dreame_a2_mower_work_log
    state_not: "(no session selected)"
  - condition: state
    entity: sensor.dreame_a2_mower_picked_session
    attribute: settings_snapshot
    state_not: None
```

### Live-session entities split

The current `Session details` card mixes archived (`latest_*`) and live (`session_distance`, `session_track_point_count`) entities. Splitting them:

- *Latest archived* (always visible): `latest_session_duration`, `latest_session_area`, `latest_session_time`, `archived_session_count`.
- *Live session* (visible only when `binary_sensor.dreame_a2_mower_mowing_session_active == on`): `session_distance`, `session_track_point_count`. Hidden between mows so the column doesn't show flat zeros.

## Data flow

```
User picks option in select.work_log
    │
    ▼
DreameA2WorkLogSelect.async_select_option(option)
    │  (existing path)
    │  resolves option → filename via _label_to_filename
    ▼
coordinator.render_work_log_session(filename)
    │  load archive JSON
    │  parse_session_summary(raw_dict) → SessionSummary
    │
    ├──▶ build_picked_session_summary(raw_dict, summary, entry, label)
    │       │
    │       ▼
    │   _picked_session_summary dict  ───┐
    │                                     ▼
    │                            sensor.picked_session.state + attrs
    │                                     │
    │                                     ▼
    │                       cards consume via templates / data_generator
    │
    └──▶ render_work_log() → _work_log_png → camera.work_log
                                     │
                                     ▼
                            picture-entity card refreshes
```

All on the event loop; one `async_update_listeners()` after both side effects.

## Edge cases

| Case | Behaviour |
|---|---|
| Picker on placeholder | `_picked_session_summary = None` → sensor state = `None`, all below-divider cards hidden |
| Archive JSON has no `battery_samples` (pre-v1.0.12a2 + un-backfilled) | charge_at_start_pct = None; charge_used_pct = 0; m2_per_pct = None; chart card renders empty series |
| `wifi_samples` empty | wifi_rssi_*_dbm = None; chart card empty series |
| `settings_snapshot` absent | Settings-in-effect card hidden |
| `map_area == 0` | coverage_pct = None |
| `duration_min == 0` (test fixtures, "incomplete" entries) | m2_per_min = None; time_*_min = None |
| Incomplete archive (`md5 == "(incomplete)"`) | normal handling; `completed = False`; identity card shows "Incomplete" as result_label |
| Multiple obstacles with degenerate polygons | already filtered in render_work_log_session; counts include only `len(polygon) >= 3` (consistent with renderer) |
| state_samples empty | time_mowing_min = None (not 0 — distinguishes "no data" from "didn't mow") |
| Picker option that doesn't resolve to any archived session | existing code returns early; we add `_picked_session_summary = None` before that early-return |

## Testing

### New: `tests/protocol/test_session_card.py`

Pure unit tests against `build_picked_session_summary`:

- **Real fixture replay**: 3 backfilled JSONs copied into `tests/protocol/data/sessions/` (a short rec, a long mow with recharge, an incomplete). For each, assert the full attribute dict against an expected JSON sibling.
- **Missing-data scenarios** (synthetic minimal dicts):
  - No `battery_samples` → charge_* = None, ratios = None, no exception
  - Empty `state_samples` + empty `charging_status_samples` → time_* = None
  - `map_area == 0` → coverage_pct = None
  - `duration_min == 0` → m2_per_min = None
- **Label-table coverage**: assert that every mode/result/stop_reason value present in any fixture either maps to a label or surfaces as `"raw=N"`.

### Modified: `tests/integration/test_coordinator_writes.py` (or new test_picked_session_integration.py)

- Test that `render_work_log_session` sets `_picked_session_summary` to a non-empty dict when called with a real archived session, and to `None` when the picker is reset.
- Test that selecting the placeholder option clears both `_work_log_png` and `_picked_session_summary`.

### Modified: `tests/integration/test_per_map_entity_names.py`

- Assert `sensor.dreame_a2_mower_picked_session` exists and is on the mower device (not a per-map sub-device).

### Modified: `tests/integration/test_session_archive.py` (or sibling)

- Test that `LiveMapState.settings_snapshot` is populated at session_begin when cloud_state.settings is set.
- Test that `_persist_in_progress` includes `settings_snapshot` in the JSON.
- Test that `_restore_in_progress` rehydrates `settings_snapshot`.
- Test that `_do_oss_fetch` injects `settings_snapshot` into `raw_dict` before archiving.

### No backfill of settings_snapshot

`tools/backfill_session_samples.py` is not extended. Pre-v1.0.13a1 archives keep `settings_snapshot` absent; the conditional card hides for them. Documented in the spec.

## Risks / open questions

1. **State enum semantics**: we don't have a confirmed list of which `state` enum values count as "mowing" vs "charging" vs "idle". The current best guess is mowing ∈ {2, 5}, charging ∈ {1, 6}, but `_classify_intervals` should be conservative — when in doubt, classify as "other" rather than mowing/charging. Verification can come from cross-checking a session where `time_mowing_min + time_charging_min + time_other_min ≈ duration_min` and `time_charging_min` rises in proportion to `recharge_count`.
2. **Picker race after HA restart**: on cold boot, the picker is on the placeholder. `_picked_session_summary` is None. First card render shows blanks under the visibility gate. No action needed — user has to re-pick. Acceptable.
3. **Settings_snapshot growth**: the dict is shallow-copied from cloud_state. Future CFG keys land automatically but `_persist_in_progress` writes it to disk every 30s; if `by_map_id_canonical` grows past ~50 keys we may want to revisit. Current size is ~20 keys per map.
4. **Picker label string drift**: the visibility condition uses the placeholder string literally. If `DreameA2WorkLogSelect._placeholder` changes, the dashboard breaks silently. Mitigation: pull the placeholder into a single constant in `const.py` (`WORK_LOG_PLACEHOLDER`) and reference it from both sites + a test that asserts the constant matches what the entity exposes. Alternative considered (binary_sensor "is a session picked"): more plumbing for less gain since one literal in the dashboard YAML is acceptable.
5. **Apexcharts data_generator JS string in YAML**: the `data_generator` lives as inline JS inside dashboard.yaml. Already used elsewhere in the integration's dashboard. Pin the syntax to the apexcharts-card README current as of 2026-05.

## Implementation steps (high level — full plan generated next via writing-plans)

1. Add `LiveMapState.settings_snapshot` + begin_session reset.
2. Capture settings_snapshot in `_on_state_update` at session_begin.
3. Persist + restore settings_snapshot (in_progress.json + archive payload).
4. Add `build_picked_session_summary` in new `session_card.py`. Comprehensive unit tests against real fixtures.
5. Add `_picked_session_summary` slot on `_CoreMixin`; populate / clear in `render_work_log_session` + the placeholder branch of `DreameA2WorkLogSelect.async_select_option`.
6. Add `DreameA2PickedSessionSensor` to `sensor.py`; wire into platform setup.
7. Add `WORK_LOG_PLACEHOLDER` constant; refactor `DreameA2WorkLogSelect` to use it; expose via const.
8. Update entity-inventory.yaml per fact-discipline rule.
9. Restructure `dashboards/mower/dashboard.yaml` per § Tab layout.
10. SCP dashboard, smoke-test in browser, verify all visibility conditions, verify apexcharts series populate.
11. Cut release v1.0.13a1.

## Memory / fact-discipline impact

Per `CLAUDE.md` § "Fact discipline (load-bearing)":
- Adding `sensor.dreame_a2_mower_picked_session` → entity-inventory.yaml update (verifications: status=verified, claim names the source `coordinator._picked_session_summary`).
- Adding `LiveMapState.settings_snapshot` capture from cloud_state — integration-side data flow, not a wire fact; no inventory.yaml change required.
- New label tables (MODE_LABELS, START_MODE_LABELS, etc.) are best-effort guesses; entries documented as `presumed` in inventory.yaml under existing `summary_*` rows. As live captures confirm specific values, they get upgraded to `verified` per the standard workflow.

## Future work (out of scope)

- Cross-session trend cards (e.g. `latest 14 sessions` battery efficiency graph).
- Service to re-render the picked-session map at a different zoom / with an obstacle overlay toggle.
- Statistics-platform integration so picked-session battery_samples drive long-term graphs in HA's Statistics page (would need a separate sensor since the picker can change beneath the recorder).
- Decoding the `mode` / `start_mode` / `pre_type` / `stop_reason` enums via app-trigger experiments (each mode → known archive → derive the value).
