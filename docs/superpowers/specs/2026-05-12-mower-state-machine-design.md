# Mower State Machine — design

**Created:** 2026-05-12  
**Status:** Approved (brainstorm complete; ready for plan).

## Goal

Replace the integration's current ad-hoc per-slot state mutation in
`coordinator.py` with a single `MowerStateMachine` class that produces
a coherent, multi-dimensional snapshot of the mower's state. Drive all
state-consuming entities (`lawn_mower`, `binary_sensor.*`, sensor
projections) from that snapshot.

Replaces the current symptoms:
- `binary_sensor.mower_in_dock` stuck on `on` for an hour because
  `CFG.DOCK.connect_status` polling fails silently and the cached value
  persists.
- `lawn_mower.dreame_a2_mower = docked` when the mower is at a
  maintenance point because `STANDBY` blindly maps to `DOCKED` in HA's
  impoverished enum.
- `binary_sensor.mowing_session_active = on` during cruise-to-point
  because `LiveMapState.is_active()` can't tell mowing from cruising.
- s2p2=71 notification always reads "Positioning failed (SLAM relocation
  needed)" even when the actual semantic is "Returning home after
  extended standby" (STUN-driven auto-return).

## Non-goals

- Backwards-compatible migration of stored entity state. Per
  `feedback_no_migration_overengineering`, the integration is single-user
  dev — deleting and reinstalling is the supported transition.
- Preserving the legacy `MowerState` dataclass shape. Entities migrate
  to read the new snapshot; old fields disappear.
- Adding HA-side throttling / debouncing of state updates. Coordinator
  semantics stay as-is (push on change).
- Fixing the cruise-to-point cloud command. Tracked separately in
  `docs/research/cruise-to-point-todo.md`.

## State dimensions

Seven orthogonal dimensions plus the existing scalar fields:

```
mow_session         IN_SESSION | BETWEEN_SESSIONS
current_activity    MOWING | PAUSED | REPOSITIONING | RETURNING |
                    CHARGE_RESUME | CRUISING_TO_POINT | AT_POINT |
                    FAST_MAPPING | DRIVING_BLADES_UP | IDLE
location            AT_DOCK | ON_LAWN | AT_POINT | OUTSIDE_KNOWN_AREA
positioning_health  LOCALIZED | RELOCATING | STUCK
charging            true | false
errors              frozenset[ErrorCode]
pin_required        true | false        (sticky until user enters PIN)
mqtt_connectivity   ONLINE | STALE
cloud_rpc_health    OK | FAILING
```

Dimensions are independent; constraint validation (e.g., "you can't be
CHARGING and CRUISING_TO_POINT simultaneously") lives in a separate
sanity check rather than at the schema level.

`paused_from` records what `current_activity` was before transitioning
into PAUSED, so resuming a paused mow versus a paused cruise dispatches
to the right "resume" call.

## Snapshot dataclass

```python
@dataclass(frozen=True)
class StateSnapshot:
    # Multi-dim state
    mow_session: MowSession
    current_activity: CurrentActivity
    location: Location
    positioning_health: PositioningHealth
    charging: bool
    errors: frozenset[ErrorCode]
    pin_required: bool
    mqtt_connectivity: Connectivity
    cloud_rpc_health: RpcHealth

    # Provenance + freshness
    last_heartbeat_unix: int | None
    field_freshness: dict[str, int]   # last MQTT-update timestamp per field

    # Pre-disambiguation / debug
    paused_from: CurrentActivity | None
    last_task_op: int | None          # 100/101/102/103/109/10/...
    raw_s2p1: int | None
    raw_s2p2: int | None

    # Existing scalars surfaced through the same snapshot
    battery_percent: int | None
    position_x_m: float | None
    position_y_m: float | None
    position_north_m: float | None
    position_east_m: float | None
    error_code: int | None
    wifi_rssi_dbm: int | None
    # ... and the rest of the current MowerState scalars
```

## Architecture

Single class `MowerStateMachine` in
`custom_components/dreame_a2_mower/mower/state_machine.py`. Inputs in,
snapshot out. Internal state is the live snapshot plus a small buffer
for events awaiting disambiguation.

```python
class MowerStateMachine:
    def __init__(self, store: Store, freshness: FreshnessTracker) -> None: ...

    async def load_persisted(self) -> None:
        """Restore last-known snapshot on integration setup."""

    async def save_persisted(self) -> None:
        """Debounced write of current snapshot to HA Store."""

    def handle_mqtt_property(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> StateSnapshot:
        """Apply one MQTT property change. May transition state."""

    def handle_cloud_poll(
        self, source: CloudSource, payload: dict, now_unix: int
    ) -> StateSnapshot:
        """Apply a cloud-poll result. Per-field precedence:
        overwrites only when cloud_as_of > field_freshness[field]."""

    def handle_heartbeat(self, hb: Heartbeat, now_unix: int) -> StateSnapshot:
        """Update mqtt_connectivity + last_heartbeat_unix; decode state_raw."""

    def tick(self, now_unix: int) -> StateSnapshot:
        """Periodic (~10s). Resolves buffered events, flips connectivity
        on HB gap, saves snapshot if dirty."""

    def snapshot(self) -> StateSnapshot:
        """Cheap accessor for the current immutable snapshot."""
```

The coordinator's role shrinks to plumbing:
- On MQTT property change → `state_machine.handle_mqtt_property(...)`
- On cloud-poll result → `state_machine.handle_cloud_poll(...)`
- On HA timer (10s) → `state_machine.tick(...)`
- Entity subscribers receive `StateSnapshot` updates via the
  coordinator's existing `async_update_listeners` mechanism

## Input → state mapping

### MQTT slots

| Slot | Drives |
|---|---|
| `s1p1` heartbeat (~45s) | `mqtt_connectivity`, `pin_required`, safety flags, `last_heartbeat_unix`, byte[7] sub-state hints |
| `s1p4` telemetry | trail-only; routed to `LiveMapState`, not the FSM |
| `s2p1` task_state | `current_activity` core transitions (1=working, 2=done→IDLE, 5=returning, 6=charging) |
| `s2p2` event code | `errors`, plus disambiguation-buffered transitions (see below) |
| `s2p50` TASK echo | `last_task_op`, dispatches `current_activity` start: ops 100/101/102/103 → MOWING (variant in `paused_from`); op 109 → CRUISING_TO_POINT; op 10 → FAST_MAPPING |
| `s2p56` lifecycle | activity arrival / completion: `[[N,0]]` start, `[[N,2]]` arrived |
| `s2p65` SLAM relocate | `positioning_health = RELOCATING` (transient ~10s) |
| `s3p1` battery | `battery_percent` |
| `s3p2` charging | `charging` |
| `s5p106` session UUID | enters `mow_session = IN_SESSION` (only when last_task_op ∈ {100,101,102,103}, NOT for op 109) |

### Cloud-poll sources

| Source | Drives | Stale-cache risk |
|---|---|---|
| `CFG.DOCK.connect_status` | `location = AT_DOCK \| ON_LAWN` | Low. Stale-cache rule still applies |
| `CFG.LOCN.pos` | dock-origin coords (not live mower) | High — known sentinel cache |
| `CFG.MIHIS` | lifetime totals (out of FSM) | n/a |
| Properties batch (10-min poll) | scalar fields with per-field freshness check | High for settings |

### Tick (periodic, ~10s)

1. `last_heartbeat_unix < now - 90s` → `mqtt_connectivity = STALE`
2. Buffered s2p2=71 older than 30s → disambiguate:
   - Saw s2p2 ∈ {33, 31} within window → `errors += STUCK_POSITIONING`, fire
     "Positioning failed — waiting for help" notification
   - Saw s2p1 = 5 within window → fire "Returning home after extended
     standby" notification
   - Neither → fire generic "Positioning event" notification
3. `location == OUTSIDE_KNOWN_AREA` and recent s2p65 → flip to
   `positioning_health = RELOCATING`
4. `save_persisted` (debounced 30s)

## Precedence and freshness

Per-field rule:

1. MQTT is the live channel. Every parsed MQTT slot stamps
   `field_freshness[field] = now_unix` for each field it touched.
2. Cloud poll overwrites a field only when `cloud_as_of > field_freshness[field]`.
   A stale-cached cloud value older than our last MQTT-derived update
   does NOT clobber the truth.
3. MQTT-confirmed writes win: when we write a setting via cloud RPC AND
   MQTT echoes the new value, `field_freshness` updates → subsequent
   cloud-poll cache misses can't clobber it.
4. Fields the mower never broadcasts (lifetime totals, dock origin GPS,
   schedule slots) come only from cloud — no freshness check, cloud wins
   trivially.
5. Cloud RPC failure (80001, 400, timeout) → no overwrites. Field values
   persist. The `cloud_rpc_health` dimension flips to FAILING for
   observability.

## Persistence

Coordinator-level snapshot via HA `Store` helper.

- On every `handle_*` call that mutates the snapshot, mark dirty.
- `tick` flushes the latest snapshot to Store (debounced 30s, so we
  don't write every 1-second telemetry tick).
- On integration setup, `load_persisted` restores the most recent
  snapshot. `field_freshness` timestamps survive, so cloud-poll
  precedence still works correctly on restart.
- The next MQTT heartbeat (~45s worst case) refreshes connectivity and
  any fields that have changed.
- Dashboard usable instantly post-restart; stale fields are observable
  via existing `sensor.dreame_a2_mower_data_freshness`.

## Entities consuming the snapshot

| Entity | Source |
|---|---|
| `lawn_mower.dreame_a2_mower` | Projection: (`current_activity`, `mow_session`, `errors`) → HA's MOWING/PAUSED/DOCKED/RETURNING/ERROR enum |
| `binary_sensor.mower_in_dock` | `location == AT_DOCK` |
| `binary_sensor.mowing_session_active` | `mow_session == IN_SESSION` (mow only — cruise excluded) |
| `sensor.dreame_a2_mower_current_activity` | `current_activity.value` |
| `sensor.dreame_a2_mower_location` | `location.value` |
| `sensor.dreame_a2_mower_positioning_health` | `positioning_health.value` |
| `sensor.dreame_a2_mower_charging_status` | `charging` (enum: charging / not_charging) |
| `sensor.dreame_a2_mower_mqtt_connectivity` | `mqtt_connectivity.value` (new) |
| `sensor.dreame_a2_mower_cloud_rpc_health` | `cloud_rpc_health.value` (new) |
| `sensor.dreame_a2_mower_data_freshness` | derived from `field_freshness` (existing logic, new source) |
| Existing battery / position / error / etc. | unchanged — values come from the snapshot |

### lawn_mower projection rules

```
errors contains BLOCKING                        → ERROR
current_activity == MOWING                      → MOWING
current_activity == PAUSED, mow_session=IN      → PAUSED
current_activity == RETURNING                   → RETURNING
current_activity == CHARGE_RESUME               → DOCKED (mid-mow at dock)
current_activity == IDLE, location == AT_DOCK   → DOCKED
current_activity == IDLE, location != AT_DOCK   → PAUSED (idle on lawn / at point)
current_activity == CRUISING_TO_POINT           → MOWING (HA has no cruise enum)
current_activity == AT_POINT                    → PAUSED
current_activity == FAST_MAPPING                → MOWING
current_activity == DRIVING_BLADES_UP           → MOWING
current_activity == REPOSITIONING               → MOWING
default                                         → ERROR
```

Notes: `CRUISING_TO_POINT → MOWING` is a deliberate compromise — HA has
no "the mower is moving but not mowing" enum, and MOWING is closer than
DOCKED. The granular `current_activity` sensor surfaces the real value
for users who want it.

## Disambiguation patterns

| Pattern | Buffer | Resolution |
|---|---|---|
| `s2p2=71` | 30s | Followed by s2p2=33/31 → STUCK_POSITIONING; followed by s2p1=5 → "auto-return after extended standby"; neither → generic |
| Future: `s2p2` codes with dual meaning | 30s | Pattern is extensible to other ambiguous codes as we discover them |

The disambiguation buffer is owned by the state machine; emits
notifications through the existing notification synthesizer once
resolved.

## Open follow-ups (not blocking this design)

These are real but separable work items:

- **DRIVING_BLADES_UP signal binding.** Not yet observed in user's
  setup — fires when traversing between zones / maps. Discover the
  triggering signal pattern in a future capture and wire it. Until
  then, this state value exists but is never set.
- **"Patrolling" session type.** User noted as a separate session type
  the mower may support. Out of scope here; if it surfaces, add a
  `patrol_session` dimension parallel to `mow_session`.
- **REPOSITIONING signal binding.** ~10-20s state during dock-departure
  / cruise-departure. Visible in the app but the precise MQTT signal
  isn't pinned. Discover and wire later.
- **DRIVING_BLADES_UP vs REPOSITIONING.** Both involve the mower moving
  without mowing. Distinguish once both signals are pinned.

## Out-of-scope-but-related fixes shipped alongside

- Delete the legacy `MowerState` dataclass; entities migrate to read
  the new snapshot directly. Per
  `feedback_no_migration_overengineering`, no compatibility shim.
- Delete `binary_sensor.mower_in_dock`'s reliance on
  `CFG.DOCK.connect_status` as primary source. New source: `location`
  via the FSM (which still consumes the same field but as a
  freshness-checked input rather than a blind write).
- The notification synthesizer's `S2P2_NOTIFICATION_MAP` stays as the
  notification text dictionary, but the FSM owns event emission —
  including the buffered s2p2=71 case.

## Testing strategy

- Unit tests for `MowerStateMachine`: feed sequences of MQTT slots /
  cloud polls / HBs, assert the resulting snapshot. One scenario per
  observable lifecycle (dock → mow → pause → resume → done; cruise from
  dock; cruise from point to point; auto-return after extended standby;
  hard-stuck positioning).
- Reuse existing notification-synth tests; verify the disambiguation
  buffer fires the right text per scenario.
- One smoke test that loads a captured MQTT log (from `probe_log_*.jsonl`)
  and replays it through the FSM, asserting end-state matches reality.
- No HA-side integration test required for the state machine itself —
  it's pure-Python with no HA imports beyond `Store` and `dataclass`.

## Files

- New: `custom_components/dreame_a2_mower/mower/state_machine.py`
- New: `custom_components/dreame_a2_mower/mower/state_snapshot.py`
  (dataclass + enums; separate file to avoid circular imports)
- Modify heavily: `custom_components/dreame_a2_mower/coordinator.py`
  (strip per-slot logic; delegate to state machine)
- Delete: per-slot mutation helpers like `_apply_s1p1_heartbeat` (folded
  into `handle_heartbeat`)
- Modify: each entity file (`lawn_mower.py`, `binary_sensor.py`,
  `sensor.py`) to read snapshot fields. No backwards-compat layer.
- Modify: `custom_components/dreame_a2_mower/mower/state.py` (existing
  `MowerState`) — replaced by `StateSnapshot`; old dataclass deleted.

## When to revisit

When DRIVING_BLADES_UP / REPOSITIONING signal bindings are pinned via
live capture, fold the bindings into `handle_mqtt_property`. No design
change needed — the dimensions already exist.
