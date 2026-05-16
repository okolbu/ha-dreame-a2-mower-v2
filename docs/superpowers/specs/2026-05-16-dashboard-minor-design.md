# Dashboard minor sweep — uniform tab delimiter + More-Settings wiring

Date: 2026-05-16
Status: design, awaiting implementation plan

## Goal

Two related changes to `dashboards/mower/dashboard.yaml`:

1. **Cosmetic — uniform tab header.** Give every tab a full-width
   single-line title delimiter at the very top, modelled on the
   `## 📊 Picked session — <name>` delimiter the Sessions tab already
   uses. The title should always be in the same place so the tab
   identity is obvious at a glance, regardless of what cards sit
   underneath.
2. **Wiring — replace stale "Plan 3" placeholders on More Settings.**
   The integration already exposes the entities the placeholders
   describe; only the dashboard is behind. Replace each 🚧 placeholder
   with a real `entities` card. Keep 🚧 markers only for surfaces
   that genuinely have no entity yet (maintenance reset buttons,
   ambient temperature). Drop the existing Time Zone / Switch Unit /
   Notifications placeholder entirely — those are app-only
   preferences with no cloud / MQTT / integration surface.

## Non-goals

- No new integration entities. Anything missing stays a TODO note in
  the relevant card; new entities are a separate change.
- No write-path verification per surface. A switch that exists in
  `switch.*` is rendered as interactive even if its write may silently
  no-op on g2408 firmware. Integration write-path gaps are filed
  against the integration, not worked around in the dashboard.
- No restructuring of which tab owns which card. Per-map cards stay on
  Settings & Zones; device-wide settings stay on More Settings.
- No restructuring of the Sessions tab's `type: panel` layout. The
  per-session "Picked session — X" delimiter that already exists stays
  where it is; a separate top-of-tab delimiter is added above the
  panel's outer vertical stack.

## Part A — Uniform tab delimiter

### Shape

One `type: markdown` card per tab, sitting at the very top of `cards:`
(for panel tabs, at the top of the outer vertical stack). The content
template is one heading line preceded by a horizontal rule:

```markdown
<hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>

## <emoji> <Title> — <live-value-or-omit> &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)"><small grey note></span>
```

- `<emoji>` is one glyph, consistent per tab.
- `<Title>` is the human-friendly tab name (matches `title:`).
- `<live-value-or-omit>` — only used for per-map tabs and Sessions
  (live archive count). Omitted entirely (including the em-dash) for
  stand-alone tabs.
- `<small grey note>` is a 1-line description of what the tab *is*,
  not how to operate its controls. Style via inline `<span>` so it
  shrinks to ~75% size and uses the theme's secondary text colour.
  **Assumed to render** in HA's markdown card via `marked` HTML
  pass-through; verify in the browser at first deploy. If `<span
  style>` is stripped, fall back to `<sub>` (always supported) and
  accept the looser sizing.

### Per-tab table

| Tab | Emoji | Live value | Small grey note |
|---|---|---|---|
| Mower | 🤖 | `Active map: {{ states('select.dreame_a2_mower_active_map') }}` | switch on Map Selector |
| Map Selector | 🗺️ | (omit) | drives the active map for every per-map tab |
| Settings & Zones | ⚙️ | `Active map: {{ … }}` | switch on Map Selector |
| Schedule | 📅 | `Active map: {{ … }}` | read-only on cloud; switch on Map Selector |
| LiDAR | 📡 | (omit) | archived 3-D point clouds |
| WiFi Coverage | 📶 | (omit) | signal strength as measured during mowing |
| Sessions | 📊 | `{{ states('sensor.dreame_a2_mower_archived_session_count') }} archived` | calendar plus per-session breakdown |
| More Settings | ⚙️ | (omit) | device-wide settings (per-map ones live on Settings & Zones) |
| Diagnostics | 🩺 | (omit) | health checks and raw state |
| Tools | 🔧 | (omit) | helpers, services, manual ops |
| Photo Privacy | 🔒 | (omit) | review and delete AI-obstacle photos |

Sessions deliberately surfaces the archive count, not the picked
session — the picked-session delimiter that already exists inside the
per-session block stays where it is.

### Anchor hoisting

Keep the existing pattern: each tab's delimiter is defined as a YAML
anchor at the top of the file (`_tab_header_mower: &tab_header_mower
...`) and aliased from the tab's `cards:` list. Existing anchors
(`_tab_header_mower`, `_tab_header_settings_zones`,
`_tab_header_schedule`, `_tab_header_lidar`) are rewritten in place
to drop the italic subtitle and adopt the inline small-text note;
new anchors are added for the other tabs.

### Intro cards to remove

These existing cards are replaced by the delimiter and deleted:

- Map Selector — `# Pick the active map` markdown block (lines 420–427).
- WiFi Coverage — `# WiFi heatmap` markdown block (lines 753–758).
- More Settings — `# More Settings` markdown block (lines 1162–1167)
  and the bare `## Functions` markdown disclaimer (lines 1182–1187).
- LiDAR — `### Re-tag a mis-categorized scan` stays (it's tab-specific
  reference, not a tab intro) but moves to the bottom of the tab.

The existing `## 📊 Picked session — …` delimiter that fires when a
session is picked stays as-is; its shape is the model the new
delimiters copy.

## Part B — More Settings wiring sweep

Replace the bare `🚧 Plan 3` markdown cards on the More Settings tab
with `entities` cards bound to the live entities. Ordering roughly
mirrors the Dreame app's More page so a user comparing the two can
find things in the same place.

Each card carries a footer markdown line only when there is a
genuinely missing piece (reset action, temperature, etc.) — silent
otherwise.

### Cards (top → bottom)

1. **Consumables & Maintenance** (`entities`)
   - `sensor.dreame_a2_mower_blades_life` — Blades
   - `sensor.dreame_a2_mower_cleaning_brush_life` — Cleaning brush
   - `sensor.dreame_a2_mower_robot_maintenance_life` — Robot maintenance
   - Footer: *Reset buttons not yet exposed — see [[project_g2408_iobroker_negatives]] for write-path candidates.*

2. **Work Management** (`entities`, existing card kept)
   - `switch.dreame_a2_mower_ai_obstacle_photos` — Capture photos of AI obstacles

3. **Rain Protection** (`entities`)
   - `switch.dreame_a2_mower_rain_protection` — Enabled
   - `select.dreame_a2_mower_rain_protection_resume_hours` — Resume after
   - `binary_sensor.dreame_a2_mower_rain_protection_active` — Currently delayed
   - Footer: *Ambient temperature not exposed; rain trigger source TBD.*

4. **Frost Protection** (`entities`)
   - `switch.dreame_a2_mower_frost_protection` — Enabled
   - Footer: *Stops below 6 °C. Ambient temperature not exposed (possible candidate in unknown mqtt corpus).*

5. **Do Not Disturb / Nighttime** (`entities`)
   - `switch.dreame_a2_mower_do_not_disturb` — Do not disturb
   - `switch.dreame_a2_mower_low_speed_at_night` — Low speed at night
   - Footer: *Time windows on the Schedule tab.*

6. **Navigation Path** (`entities`)
   - `select.dreame_a2_mower_navigation_path` — Path mode

7. **Charging** (`entities`)
   - `switch.dreame_a2_mower_auto_recharge_after_extended_standby` — Auto-recharge after standby
   - `number.dreame_a2_mower_auto_recharge_battery_threshold` — Auto-recharge threshold (%)
   - `number.dreame_a2_mower_resume_after_charge_battery_threshold` — Resume-after-charge threshold (%)
   - `switch.dreame_a2_mower_custom_charging_period` — Custom charging period

8. **LED Light** (`entities`)
   - `switch.dreame_a2_mower_led_in_standby` — In standby
   - `switch.dreame_a2_mower_led_on_error` — On error
   - `switch.dreame_a2_mower_led_while_charging` — While charging
   - `switch.dreame_a2_mower_led_while_working` — While working
   - `switch.dreame_a2_mower_led_period` — Period (timed)

9. **Anti-theft** (`entities`, replaces existing single-entity Security card)
   - `switch.dreame_a2_mower_anti_theft_lift_alarm` — Lift alarm
   - `switch.dreame_a2_mower_anti_theft_off_map_alarm` — Off-map alarm
   - `switch.dreame_a2_mower_anti_theft_realtime_location` — Realtime location

10. **Human Presence** (`entities`)
    - `switch.dreame_a2_mower_human_presence_alert` — Alert enabled
    - `number.dreame_a2_mower_human_presence_alert_sensitivity` — Sensitivity (1–10)
    - Footer: *1 = nearest detection, 10 = farthest (or vice versa — verify against app).*

11. **Child Lock** (`entities`)
    - `switch.dreame_a2_mower_child_lock` — Enabled

12. **General — Language & Voice** (`entities`, existing card kept)
    - `select.dreame_a2_mower_voice_language` — Voice
    - `select.dreame_a2_mower_mower_lcd_language` — LCD language
    - `number.dreame_a2_mower_voice_volume` — Volume

No Time Zone / Switch Unit / Notifications card — those settings live
in the Dreame app only and have no cloud / MQTT / integration surface
to surface from. The existing 🚧 placeholder is deleted, not
converted.

### Acknowledged write-path uncertainty

Per the user's instruction, writable entities are rendered as
interactive even when the write-path on g2408 firmware is unverified.
For surfaces where the write is known to silently no-op (see
[[project_g2408_iobroker_negatives]] and [[feedback_no_bt_transport]]),
the integration is the right place to mark the entity as
`entity_category: diagnostic` or to remove the setter; the dashboard
follows whatever the integration exposes.

## Part C — Process

- Single file edit: `dashboards/mower/dashboard.yaml`.
- Iterate Jinja inside the new delimiter cards via
  `mcp__home-assistant__ha_eval_template` before deploy; this catches
  template typos without round-tripping the dashboard.
- Deploy with the existing SCP flow per
  [[reference_ha_dashboard_path]] — target is the directory at
  `/config/dashboards/mower/dashboard.yaml`, not the sibling
  `mower.yaml` file.
- Reload Lovelace in the browser, click through every tab once,
  visually verify:
  - delimiter renders as one line with the small grey note styled
  - per-map tabs show the live active-map value
  - the More Settings card grouping reads cleanly top-to-bottom
- One commit, one push. No version bump, no release — this is
  dashboard-only and HACS-irrelevant per
  [[feedback_cleanup_push_cadence]].

## Risks & open questions

- **`<span style>` rendering.** Not all HA markdown-card stylings
  survive `marked` sanitization across HA versions. Fallback path is
  `<sub>`. Test at first deploy, swap if needed; not worth gating
  the spec on.
- **Em-dash on tabs without value.** The current 4-anchor mock has
  the dash always present, which would look broken when the value is
  omitted. The anchor templates for stand-alone tabs omit the
  ` — ` entirely.
- **Anti-theft card collision.** The existing Security card on More
  Settings holds only `anti_theft_realtime_location`. It's replaced
  by the 3-entity Anti-theft card; remove the orphan Security card.
- **Human-presence sensitivity polarity** is an unverified label;
  the footer flags this. Worth a 1-line verification against the app
  during implementation, but not a blocker.

## References

- [[reference_ha_dashboard_path]] — live dashboard directory layout
- [[reference_iobroker_write_paths]] — write-path tier reference
- [[project_g2408_iobroker_negatives]] — known-bad write surfaces on g2408
- [[feedback_no_bt_transport]] — frames the cloud-cache-only failure mode
- [[feedback_cleanup_push_cadence]] — push cadence for dashboard-only changes
- [[feedback_per_map_naming]] — entity-id rules per-map entities follow
