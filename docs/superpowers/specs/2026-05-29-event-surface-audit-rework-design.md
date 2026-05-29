# Event-Surface Audit & Rework — Design

**Date:** 2026-05-29
**Status:** Approved (interactive Q&A, 2026-05-29)

**Goal:** Close the gaps an audit of the lifecycle/notification event surface
found after the session-replay rewrite — add charging + rain-start lifecycle
events, surface the rain-delay wait window as state, pin the notification
lockstep with a test, finish the `alert`→`notification` rename, and refresh
the stale event docs.

**Architecture:** Two `EventEntity` entities already exist
(`event.dreame_a2_mower_lifecycle`, `event.dreame_a2_mower_notification`)
using the modern `_attr_event_types` + `_trigger_event` pattern, dispatched
from the coordinator's `_fire_lifecycle` / `_fire_notification`. This rework
extends the lifecycle tuple, adds one coordinator field
(`rain_delay_started_at`) that backs both a new event and two state surfaces,
and adds a regression test for an invariant that is currently only enforced
by a code comment.

---

## Audit summary (what we found)

The surfacing mechanism is **correct and modern**:
- `EventEntity` + `_attr_event_types` + `_trigger_event` + an undeclared-type
  guard (`event.py:_DreameA2EventEntityBase.trigger`).
- Race-safe dispatch (`_fire_lifecycle`/`_fire_notification` drop with a DEBUG
  log if the entity isn't wired yet).
- A `logbook.py` describer fed by a custom `dreame_a2_mower_event` bus event.
  **This is NOT a removable hack** — HA routes `EventEntity` firings as
  `PSEUDO_EVENT_STATE_CHANGED`, which bypasses describers and renders a
  generic "detected an event". The custom bus event is the only way to get
  rich logbook text (and to surface the cloud's localised notification
  `text`). Verdict: **keep it.**

Nothing is stale enough to remove. The gaps are additions + one bug + debt:

| Finding | Resolution in this rework |
|---|---|
| No charging lifecycle events | Add `charging_started` / `charging_complete` |
| No way to see *why* the mower is parked for hours after rain | Add `rain_delay_started` event + rain-delay state surface |
| `NOTIFICATION_EVENT_TYPES` ⊇ `S2P2_EVENT_TYPES.values()` is comment-only | Add a lockstep test (also covers `logbook.py` message tables) |
| `register_event_entities(alert=…)` param + `self._alert_event` field still named `alert` though the entity is `notification` | Rename |
| `binary_sensor.rain_protection_active` reads `error_code == 56` — true only for the *instant* of the rain push (already a retracted claim in `entity-inventory.yaml`) | Repoint to the whole wait window |
| `docs/events.md` still calls the second entity `event.dreame_a2_mower_alert` "reserved for the alert-tier release" | Refresh — it's `notification` and fully implemented |

**Decisions taken (Q&A):**
- `mowing_ended` **stays at finalize** (full summary payload). No split, no
  `session_archived` event.
- **No `rain_delay_ended` event.** The firmware sends only a rain-*start*
  signal (s2p2=56); rain may have stopped seconds later. We do not infer an
  end. The mower resuming surfaces through the existing `dock_departed` +
  `mowing_resumed`/`mowing_started` events (identical to resuming after a
  mid-mow charge), now enriched by the new charging events.

---

## Work items

### 1. Notification lockstep test

`NOTIFICATION_EVENT_TYPES` (const.py, declared on the notification entity) must
contain every slug in `S2P2_EVENT_TYPES.values()` (error_codes.py, the actual
fire source) plus `S2P2_UNKNOWN_EVENT_TYPE`. If a slug is added to
`S2P2_EVENT_TYPES` without updating const, the entity's undeclared-type guard
silently drops that notification. Today the invariant holds but is enforced
only by a comment ("Keep this in lockstep with `S2P2_EVENT_TYPES.values()`").

Pin it. While here, also assert every `NOTIFICATION_EVENT_TYPES` slug has a
`logbook._NOTIFICATION_MESSAGES` entry and every `LIFECYCLE_EVENT_TYPES` slug
has a `logbook._LIFECYCLE_MESSAGES` entry (these are the 3rd/4th hand-kept
copies; the underscore-replace fallback means a miss is non-fatal but ugly).

### 2. `alert` → `notification` rename

`event.py` calls `coordinator.register_event_entities(lifecycle=…, alert=…)`;
`_device_sync.register_event_entities` stores `self._alert_event` and
`_fire_notification` dispatches via it. The notification entity itself was
renamed 2026-05-26; finish the job in the coordinator plumbing. Pure refactor,
no wire/entity change.

### 3. New lifecycle event_types (declaration layer)

Add to `const.py`:
```python
EVENT_TYPE_CHARGING_STARTED: Final = "charging_started"
EVENT_TYPE_CHARGING_COMPLETE: Final = "charging_complete"
EVENT_TYPE_RAIN_DELAY_STARTED: Final = "rain_delay_started"
```
Append all three to `LIFECYCLE_EVENT_TYPES` (the entity declares the tuple, so
this is the only place they need registering). Add human messages to
`logbook._LIFECYCLE_MESSAGES` and entity-state translations to
`translations/en.json` § `entity.event.lifecycle.state`.

### 4. Charging lifecycle events

Wire signal: `charging_status` (s3.2, enum **confirmed**:
`NOT_CHARGING=0, CHARGING=1, CHARGED=2`).

- `charging_started` — rising edge into `CHARGING` (1). Payload
  `{at_unix, battery_level}`.
- `charging_complete` — rising edge into `CHARGED` (2). Payload
  `{at_unix, battery_level}`.

Fired in `_on_state_update` (`_mqtt_handlers.py`) beside the existing dock
edge, using a new `_prev_charging_status` tracker (added to
`_CoreMixin.__init__`). Edge logic mirrors the dock edge (skip the first
observation so a boot-time charging state doesn't fire spuriously). Distinct
from `dock_arrived` (which derives from the cloud DOCK `connect_status` poll, a
different source) — charging is the energy-state, dock is the position-state.

### 5. `rain_delay_started` event + rain-delay state surface

One coordinator field backs all three surfaces (DRY):
```python
self._rain_delay_started_at: int | None = None   # _CoreMixin.__init__
```

**Set:** on the `error_code` (s2p2) rising edge **into 56** (rain_protection,
cloud-verified 2026-05-26) — the same edge that fires the
`rain_delay_started` event.

**Clear (→ None):** at the `dock_departed` fire site (mower left the dock — the
rain-wait-at-dock is over, whether by timer expiry, the resume button, or a
manual start) and at session finalize. No click-bookkeeping.

**Computed coordinator properties** (in `_core.py`):
```python
@property
def rain_resume_at_unix(self) -> int | None:
    """Projected unix time the mower will retry after a rain delay."""
    started = self._rain_delay_started_at
    if started is None:
        return None
    hours = self.data.rain_protection_resume_hours
    if not hours:
        return None
    return int(started) + int(hours) * 3600

@property
def rain_delay_active(self) -> bool:
    """True while the mower is waiting out the rain-protection timer."""
    if self._rain_delay_started_at is None:
        return False
    resume_at = self.rain_resume_at_unix
    if resume_at is None:
        return True            # waiting; resume_hours unknown → no upper bound
    return time.time() < resume_at
```

Three surfaces:
- **`rain_delay_started` event** (lifecycle entity) — payload `{at_unix}`.
- **`sensor.dreame_a2_mower_rain_resume_at`** — `device_class: timestamp`,
  `native_value` = `datetime.fromtimestamp(rain_resume_at_unix, tz=UTC)` or
  `None`. HA renders the live "in N hours" countdown with no server-side
  ticking (state changes only on set + clear). New class-based sensor (the
  value spans coordinator field + state), following the
  `DreameA2WifiRefreshStatusSensor` TIMESTAMP pattern.
- **`binary_sensor.rain_protection_active`** — repointed from
  `error_code == 56` to `coord.rain_delay_active` (the whole window). Fixes the
  retracted momentary-flash bug.

### 6. Docs + fact-discipline

- `docs/events.md`: rename the `alert` entity to `notification`, drop
  "reserved", document the notification tier + the 3 new lifecycle events.
- `inventory.yaml`: s2p2=56 entry — record that the firmware emits a rain
  **start** signal only (no end signal observed; `verified` absence drives the
  no-`rain_delay_ended` decision); s3.2 — note the charging_started/complete
  edges consume the enum.
- `entity-inventory.yaml`: lifecycle event entity gains 3 event_types
  (verification record); `binary_sensor.rain_protection_active` fix
  (retraction → window-based); new `sensor.dreame_a2_mower_rain_resume_at` row.

---

## File-touch list

| File | Change |
|---|---|
| `const.py` | +3 `EVENT_TYPE_*`, +3 to `LIFECYCLE_EVENT_TYPES` |
| `coordinator/_core.py` | `_prev_charging_status`, `_rain_delay_started_at` init; `rain_resume_at_unix` + `rain_delay_active` properties |
| `coordinator/_mqtt_handlers.py` | charging edges; rain-56-edge set + fire; rain clear at `dock_departed` |
| `coordinator/_session.py` | clear `_rain_delay_started_at` at finalize |
| `coordinator/_device_sync.py` | `alert`→`notification` field/param |
| `event.py` | `register_event_entities(notification=…)` |
| `logbook.py` | +3 `_LIFECYCLE_MESSAGES` |
| `translations/en.json` | +3 lifecycle event states |
| `binary_sensor.py` | rain_protection_active → `rain_delay_active` |
| `sensor_device.py` | new `DreameA2RainResumeSensor` + register in setup |
| `tests/` | lockstep test; charging/rain edge fire tests; binary_sensor window test; timestamp sensor test; rename updates |
| `inventory.yaml`, `entity-inventory.yaml` | fact records |
| `docs/events.md` | refresh |

## Out of scope
- `mowing_ended` semantics (stays at finalize).
- `session_archived` event (no automations need it).
- `rain_delay_ended` (no wire signal).
- Replacing the logbook dual-fire (it's correct).

## Testing
Vanilla stubbed-HA venv (`/data/claude/homeassistant/.venv-vanilla`, 3.13;
baseline 1591 passed/4 skipped). Each task is TDD: failing test → implement →
green. Final full run + `tools/release.sh` → `1.0.19a9` (single-digit alpha,
safe per the HACS string-sort ladder).
