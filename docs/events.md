# Events

The integration surfaces mower lifecycle moments as Home Assistant
event entities so automations and push notifications can react to
"something happened" without polling sensor states.

## Entities

| entity_id | Purpose |
|---|---|
| `event.dreame_a2_mower_lifecycle` | Mowing start/pause/resume/end + dock arrive/depart + charging state + rain delay |
| `event.dreame_a2_mower_notification` | Cloud-sourced s2p2 notifications (emergency_stop, human_detected, rain_protection, low_battery_return, etc.) with localised text fetched from the cloud per fire |

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
- `reason` — `"recharge_required"` when `battery_level <= 20` at pause
  time, otherwise `"unknown"`. The integration cannot today distinguish
  a user-pressed pause from a safety pause; both surface as `"unknown"`.
  More fine-grained reasons may land in the alert-tier follow-up release.

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

### `charging_started`
Mower began charging (s3.2 rising edge into CHARGING=1). Fires once per
dock session when the energy state transitions from not-charging to charging.
Distinct from `dock_arrived` (which is cloud DOCK connect_status); this is
the energy-state edge.
- `at_unix`
- `battery_level` — battery % at the moment charging began

### `charging_complete`
Battery full / charging done (s3.2 rising edge into CHARGED=2).
- `at_unix`
- `battery_level` — battery % at the moment charging completed (typically 100)

### `rain_delay_started`
Rain detected; mower is waiting out the rain-protection timer before
retrying. Fires on the s2p2 rising edge into 56 (rain_protection).

**Note:** there is no `rain_delay_ended` event — the firmware sends only
a rain-start signal; no rain-end code is ever emitted on the wire. The
mower resuming surfaces via `dock_departed` followed by
`mowing_resumed` / `mowing_started`. The projected retry time is on
`sensor.dreame_a2_mower_rain_resume_at` and the current wait state on
`binary_sensor.dreame_a2_mower_rain_protection_active`.
- `at_unix`

## Notification events

`event.dreame_a2_mower_notification` fires whenever the mower's cloud
service delivers a notification text for an s2p2 code. The integration
fetches the localised text from the cloud `/dreame-messaging/device-messages/v2`
endpoint and exposes it on the event payload.

Known event_type slugs (from `S2P2_EVENT_TYPES`): `emergency_stop`,
`human_detected`, `rain_protection`, `low_battery_return`,
`maintenance_reminder`, `mowing_started`, `mowing_complete`,
`scheduled_task_cancelled`, `continue_task`, `blade_worn`, `task_failed`.
Codes not in the catalog surface as `unknown_s2p2`.

Each firing exposes:
- `event_type` — slug from the list above
- `text` — localised notification text from the cloud
- `s2p2_code` — raw integer code that triggered the notification

This entity was named `event.dreame_a2_mower_alert` prior to 2026-05-26.
If you have automations keyed on the old entity_id, remove the old entity
from the HA registry (Settings → Devices → Dreame A2 Mower → entity list)
after updating the integration.

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
