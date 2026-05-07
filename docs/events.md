# Events

The integration surfaces mower lifecycle moments as Home Assistant
event entities so automations and push notifications can react to
"something happened" without polling sensor states.

## Entities

| entity_id | Purpose |
|---|---|
| `event.dreame_a2_mower_lifecycle` | Mowing start/pause/resume/end + dock arrive/depart |
| `event.dreame_a2_mower_alert` | Reserved for the alert-tier release (emergency_stop, lifted, stuck, etc.) |

When an event fires, the entity's `state` attribute is set to the
event_type (e.g. `mowing_started`) and the event payload is exposed as
additional attributes accessible via `trigger.to_state.attributes.<key>`.
HA's Logbook automatically records each firing.

## Lifecycle event reference

### `mowing_started`
Mower transitions from idle/complete to running.
- `at_unix` — wall-clock unix timestamp
- `action_mode` — `"all_areas"`, `"zone"`, `"edge"`, or `"spot"`
- `target_area_m2` — planned area for this run, when known

### `mowing_paused`
Mower transitions from running to paused (recharge, user pause, safety).
- `at_unix`
- `area_mowed_m2`
- `reason` — `"user"`, `"recharge_required"`, `"unknown"` (best-effort)

### `mowing_resumed`
Mower transitions from paused back to running (post-recharge or manual).
- `at_unix`
- `area_mowed_m2`

### `mowing_ended`
Session completed — either with a cloud summary (`completed: true`) or
because the integration gave up waiting for one and finalized with what
it had locally (`completed: false`).
- `at_unix`
- `area_mowed_m2`
- `duration_min`
- `completed` — bool

### `dock_arrived`
Mower returned to the charging dock. Fires on the `mower_in_dock`
sensor's rising edge.
- `at_unix`

### `dock_departed`
Mower left the dock. Fires on the falling edge.
- `at_unix`

## Recipes

### 1. Push notification on every mow start

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_started
action:
  - service: notify.mobile_app_<your_device>
    data:
      title: "Mower"
      message: >-
        Started {{ trigger.to_state.attributes.action_mode }} mow
        ({{ trigger.to_state.attributes.target_area_m2 | default("?") }} m²)
```

### 2. Mode-specific notification

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_started
condition:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.action_mode == 'edge' }}"
action:
  - service: notify.mobile_app_<your_device>
    data:
      title: "Mower"
      message: "Edge run started — clear the perimeter."
```

### 3. Log mowing_ended to a counter helper

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_ended
action:
  - service: counter.increment
    target:
      entity_id: counter.mowing_sessions
  - service: input_number.set_value
    target:
      entity_id: input_number.last_mow_area
    data:
      value: "{{ trigger.to_state.attributes.area_mowed_m2 }}"
```

## How event entities differ from state-change triggers

You could already react to most of these moments by watching state
changes on `lawn_mower.dreame_a2_mower` (e.g. `from: docked, to: mowing`)
and reading sibling sensors for context. The event-entity surface
adds three things:

1. **One trigger per moment, all data on the trigger** — no need to
   read `sensor.area_mowed` separately when `mowing_ended` fires; the
   value is already on `trigger.to_state.attributes.area_mowed_m2`.
2. **Logbook integration** — Settings → Logbook shows a chronological
   stream of event firings.
3. **Stable event_type strings** — automations key off
   `mowing_started` / `dock_arrived` / etc., not the integration's
   internal state machine, so future state-machine refactors won't
   break your automations.

## Pushing events outside HA

The integration stops at firing the event. To get push to your phone,
email, etc., write an automation that calls one of HA's notify
integrations on the event:

- **Mobile push** — Home Assistant Companion App: `notify.mobile_app_*`
- **Pushover / Pushbullet / Telegram / Slack** — install the matching
  integration, then `notify.<service>`
- **Webhook to anywhere** — `rest_command` or `shell_command` services
- **MQTT bridge** — `mqtt.publish` to a topic your other systems consume

The event payload is available in templates as
`trigger.to_state.attributes.<key>`, so any of these transports can
include the action_mode, area_mowed_m2, etc., in the message body.
