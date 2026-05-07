# Event Surface Design — Lifecycle Tier

**Status:** approved 2026-05-07
**Scope:** lifecycle event entity + initial six event types
**Follow-up:** alert-tier PR (emergency_stop migration, CONF_NOTIFY toggle)

## Why

The integration surfaces mower state via binary_sensors and sensors, but
has no first-class events for transient moments — "mowing started",
"arrived at dock", "got stuck". Users automating push notifications
(or any "fire-and-forget" reaction) today have to compose multiple
state-change triggers and read related sensors for context, which is
verbose and error-prone.

The Dreame app surfaces these moments as popups; users want HA to
mirror that and route them to mobile push, dashboards, logbooks, etc.

## Pattern

Modern HA (`event` entity platform, ~2023+) over the upstream Tasshack
pattern (persistent_notification only). Event entities are
Logbook-integrated, automation-friendly, and let one trigger handle
multiple branches via payload-based filtering.

The `persistent_notification` mechanism stays in the toolbox for
critical alerts in the follow-up PR; this lifecycle-tier PR doesn't add
new banners.

## Architecture

New `event.py` platform exposes two entities:

- `event.dreame_a2_mower_lifecycle` — declared `event_types`:
  `mowing_started`, `mowing_paused`, `mowing_resumed`, `mowing_ended`,
  `dock_arrived`, `dock_departed`.
- `event.dreame_a2_mower_alert` — declared `event_types: ()` initially
  (stub). Populated in the follow-up alert-tier PR. Entity exists from
  this PR so users can pre-register automations against the entity_id.

The coordinator gains a thin dispatcher `_fire_lifecycle(event_type,
payload)` called from existing transition sites. Event entities
register themselves with the coordinator at platform setup so the
dispatcher can find them. If an entity isn't yet registered (transient
during startup), `_fire_lifecycle` logs at DEBUG and drops the call
— no exceptions reach the state-machine code.

Logbook integration is automatic: HA renders event-entity firings with
the `event_type` as the headline and the payload as detail.

## Data flow — detection sites

| event_type | Trigger condition | Detection site |
|---|---|---|
| `mowing_started` | task_state None→{0,4} AND `not live_map.is_active()` | `_on_state_update` (begin_session site) |
| `mowing_paused` | `prev == 0 and new_task_state == 4` | `_on_state_update` |
| `mowing_resumed` | `prev == 4 and new_task_state == 0` | `_on_state_update` (begin_leg site) |
| `mowing_ended` | `FinalizeAction.FINALIZE_COMPLETE` or `FINALIZE_INCOMPLETE` dispatched | `_dispatch_finalize_action` |
| `dock_arrived` | `_prev_in_dock is False and new_state.mower_in_dock is True` | `_on_state_update` |
| `dock_departed` | `_prev_in_dock is True and new_state.mower_in_dock is False` | `_on_state_update` |

A new `_prev_in_dock` field on the coordinator tracks the previous
mower_in_dock value (initialized in `__init__` to `None`). The
explicit `is True` / `is False` comparisons in the trigger conditions
ensure the very first push — where `_prev_in_dock` is `None` — does
not fire a spurious arrived/departed event regardless of whether the
mower happens to be at the dock at boot. After each `_on_state_update`
tick, `_prev_in_dock` is updated to `new_state.mower_in_dock` (which
may itself be `None` if the dock state is unknown — also fine, the
next tick's transition will still be correct).

## Payload shapes

All events carry `at_unix`. Per-event additions:

| event_type | Additional payload keys |
|---|---|
| `mowing_started` | `action_mode` (`"all_areas"`/`"zone"`/`"edge"`/`"spot"`), `target_area_m2` (nullable) |
| `mowing_paused` | `area_mowed_m2`, `reason` (`"user"`/`"recharge_required"`/`"unknown"`) |
| `mowing_resumed` | `area_mowed_m2` |
| `mowing_ended` | `area_mowed_m2`, `duration_min`, `completed` (bool — false if FINALIZE_INCOMPLETE) |
| `dock_arrived` | (none beyond at_unix) |
| `dock_departed` | (none beyond at_unix) |

Payload keys with `None` values are dropped from the event_data dict
rather than serialized — keeps automation templates cleaner
(`{{ trigger.to_state.attributes.target_area_m2 | default("?") }}`
isn't needed when the key is just absent).

`reason` for `mowing_paused` is best-effort: if the previous tick's
MowerState exposed an obvious cause (battery low → recharge required,
explicit pause action, etc.), use that. Otherwise `"unknown"`. Don't
gate the fire on perfect detection.

## Components — files

**New:**
- `custom_components/dreame_a2_mower/event.py` — platform setup,
  `DreameA2LifecycleEventEntity`, `DreameA2AlertEventEntity` (stub).
- `tests/event/test_event_entity.py` — unit tests for every fire-path
  + race-skip + payload shape.
- `docs/events.md` — user-facing automation guide.

**Modified:**
- `custom_components/dreame_a2_mower/__init__.py` — add `Platform.EVENT`
  to `PLATFORMS`.
- `custom_components/dreame_a2_mower/const.py` — `EVENT_TYPE_*`
  constants.
- `custom_components/dreame_a2_mower/coordinator.py`:
  - `_lifecycle_event` and `_alert_event` entity refs (set by platform
    setup).
  - `_fire_lifecycle(event_type, payload)` helper (race-skip).
  - `_prev_in_dock` field initialized in `__init__`.
  - Wire 4 fire-points in `_on_state_update`, 1 in
    `_dispatch_finalize_action`.
- `custom_components/dreame_a2_mower/manifest.json` — version bump
  (a90 → a91).
- `README.md` — new "Events and notifications" subsection under
  Features, ~4 lines linking to `docs/events.md`.
- `docs/TODO.md` — add the alerts-tier follow-up entry.

## User docs (`docs/events.md`)

Sections:

1. **Why event entities** — short rationale (Logbook, single
   automation trigger w/ payload, no polling).
2. **Entities** — `event.dreame_a2_mower_lifecycle` (active),
   `event.dreame_a2_mower_alert` (placeholder).
3. **Lifecycle event reference** — same table as "Payload shapes"
   above with example trigger payloads.
4. **Recipes** — three concrete automations:
   - Push notification on any mow start (notify.mobile_app_<name>)
   - Mode-specific notification (template condition on `action_mode`)
   - Log `mowing_ended` to InfluxDB / a counter helper
5. **How event entities differ from state-change triggers** — short
   explanation of why `event_type` + payload beats "watch binary_sensor.X
   then read sensor.Y" patterns.
6. **Pushing events outside HA** — high-level pointers to `notify.*`
   services, webhooks, MQTT bridge. Not opinionated; the integration
   provides the events, the user picks the transport.

## Out of scope — this PR

- Alert-tier event_types (`emergency_stop`, `lifted`, `tilted`,
  `stuck`, `bumper_error`, `obstacle_with_photo`, `battery_low`,
  `battery_temperature_low`, `error`).
- `CONF_NOTIFY` option toggle.
- Reimplementation of `_handle_emergency_stop_transition` on the
  framework. Existing bespoke banner stays unchanged for now.
- `device_trigger.py` (HA automation builder dropdown integration).
- Integration code that calls `notify.*` services. Users wire
  push/email/SMS themselves via automations.

## Testing

`tests/event/test_event_entity.py` covers:

- Mowing start fires on first active task_state and not after restore
  (matches the trail-loss guard added in a88).
- Pause/resume transitions fire with correct `reason` / payload.
- Mowing end fires on both FINALIZE_COMPLETE and FINALIZE_INCOMPLETE
  with `completed` flag.
- Dock arrived/departed fire on rising/falling edge respectively;
  stable state doesn't refire.
- First push at boot does NOT fire dock_arrived even when the mower is
  observed at the dock (the `_prev_in_dock is None` initial state
  prevents the spurious edge).
- `_fire_lifecycle` called before entity registration logs DEBUG and
  returns without raising.
- Payload `None` values are dropped from event_data, not serialized.

Reuses `_make_coordinator_for_session_tests()` from
`tests/integration/test_coordinator.py`; extends the fixture with a
`_lifecycle_event = MagicMock()` so tests assert against
`coord._lifecycle_event._trigger_event.call_args_list`.

No HA-frontend tests — Logbook integration is HA-managed.

## Migration / compatibility

This PR doesn't break any existing user-facing behavior:

- All current entities (binary_sensors, sensors, switches, lawn_mower,
  camera) keep their entity_ids and semantics.
- Existing automations watching state changes continue to work.
- The emergency_stop banner is unchanged. The alerts-tier PR will
  migrate it to the framework — that's a separate, deliberate change
  with its own release notes.

Users who want to adopt the new event entities can do so incrementally
— the framework is additive.
