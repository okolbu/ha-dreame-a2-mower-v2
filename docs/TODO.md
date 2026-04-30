# Dreame A2 (g2408) v2 — Outstanding Work

Last updated: 2026-04-30 (v1.0.0a60).

## Open

### Controlled lift / lid / PIN / lid-down test

Goal: settle the semantics of `s1p1` byte[10] bit 1 (set 19:39:35,
cleared 19:39:46 in the 2026-04-30 maintenance trace — couldn't be
water-on-lidar since the dome stayed wet for 2 min, couldn't be
top-cover-open since `s2p2 = 73` stayed asserted until 19:41:45).
Working hypothesis is a "PIN-acceptance secondary latch" that clears
one tick after byte[3] bit 7 (lift lockout) clears.

Procedure (~5 min, tail mower_tail.py against a fresh probe log):

1. Lift the mower → wait 30 s.
2. Open the top cover → wait 30 s.
3. Type the PIN on-device → wait 30 s.
4. Close the cover → wait 30 s.
5. Set the mower back down.

Expected diff per byte:

- byte[2] bit 1 (lift) sets at step 1, clears when set down.
- byte[3] bit 7 (lift lockout) sets at step 1 lift, clears at step 3
  PIN entry.
- `s2p2 = 73` (TOP_COVER_OPEN) sets at step 2, clears at step 4 close.
- byte[10] bit 1 set/clear timing is the unknown — record it.

Outcome: tighten the protocol doc §3.4 byte[10] entry, possibly rename
the `binary_sensor.emergency_stop_activated` to `lift_lockout` for
semantic accuracy, and decide whether byte[10] bit 1 deserves a
separate decoder field or stays undecoded.

### Replay map: render session obstacles as blue blobs

Pre-greenfield used to overlay the obstacles the mower encountered
during a session onto its replay map (blue blobs at the encounter
points). v2 dropped the visual but kept the data — `protocol/session_summary.py`
already decodes `obstacles: tuple[Obstacle, ...]` and `ai_obstacle` from
the session-summary JSON's `obstacle` and `ai_obstacle` arrays. The
parsed model lives on each archived session record; just the renderer
in `map_render.py` doesn't draw them yet.

Wiring needed:
- Extend `render_with_trail` (or the dedicated session-replay path if
  it has one) to accept the `Obstacle` tuple and stamp filled circles
  / soft blue blobs at each obstacle's centroid.
- Pick a colour matching the pre-greenfield style (HA has the
  pre-greenfield repo at `/data/claude/homeassistant/ha-dreame-a2-mower/`
  for visual reference).
- Distinguish `obstacle` vs `ai_obstacle` if pre-greenfield did
  (different colour or shape).

### LiDAR popout: make the modal controllable like the inline card

The LiDAR card has interactive controls (rotate / pan / zoom, optional
auto-refresh, etc.) when rendered inline on the dashboard, but the
"popout" / fullscreen modal of the same camera entity exposes only a
static image. Wire the popout to the same WebGL card JS so the modal
view supports the same gestures and controls. Likely requires a custom
HA `more-info` dialog or registering the card itself as the
fullscreen presenter rather than letting HA fall back to the default
camera-entity preview.

### Dashboard: replicate the Dreame app's contextual button transitions

The Dreame mobile app shows different button rows depending on mower state:

| State                | App buttons                                       |
| -------------------- | ------------------------------------------------- |
| Docked / idle        | **Start**, **Recharge**                           |
| Charging / charged   | **Start**, **Recharge** (disabled)                |
| Mowing               | **Pause**, **Stop**                               |
| Paused               | **Continue**, **End**, **Recharge**               |
| Returning to dock    | **Start** (disabled), **End Return to Station**   |

The HA Device Info page is rigid — entities are listed in a grid and we
cannot show/hide them per state without custom card logic. Live
buttons today: Start, Pause (only when WORKING/MAPPING), Stop (when
WORKING/MAPPING/PAUSED), Recharge (always), Finalize (always).

What to build: a section on the mower dashboard
(`/config/dashboards/mower/dashboard.yaml`) that uses
`conditional` cards keyed off `lawn_mower.dreame_a2_mower` activity to
render the app-style button row per state. "Continue" reuses the
existing Start button (Start → already handles
WORKING/MAPPING/PAUSED transitions cloud-side). "End" reuses Stop.

Notes:
- Don't duplicate entities — wrap existing buttons in conditional
  cards.
- Recharge stays visible across multiple states per app convention.
- Dashboard sketches in the screenshots in `/data/claude/homeassistant/`
  (IMG_4413.PNG..IMG_4422.PNG capture the app's button layouts in each
  state) — use them as the visual reference.

## Recently shipped (a52 → a60)

- **v1.0.0a60** — Consumable thresholds moved to `protocol/config_s2p51.py`
  (single source of truth shared with `mower_tail.py`). `s2p2` codes
  0/1/9/23 corrected against today's empirical data: 0 = "No error / OK"
  (was wrongly "Hanging" — apk label was off for g2408), 1 = "Robot tilted
  (drop sensor)", 9 = "Robot lifted", 23 = "Lift lockout — PIN required
  on device".
- **v1.0.0a59** — Dropped the dead `Property.STATE = (2, 2)` /
  `StateCode` enum / `state_label()` helper that runtime dispatch had
  long bypassed (`mower/property_mapping.py` routes (2, 1) → state, (2,
  2) → error_code). `s2p2 = 73` and `56` re-confirmed apk-correct
  (TOP_COVER_OPEN, BAD_WEATHER respectively). The byte[3] bit 7
  semantic is *lift-lockout / PIN-required* (clears on PIN entry, not
  cover close), per user clarification — even though the app calls it
  "Emergency stop is activated". Dropped the speculative
  `water_on_lidar` byte[10] bit 1 decoder; replaced the affected
  binary_sensor with `top_cover_open` from `error_code == 73`.
- **v1.0.0a58** — Five new decoders, all confirmed against live app
  notifications during a deliberate maintenance test:
  - `s1p1` byte mask: drop/tilt, bumper, lift, emergency_stop binary
    sensors. Bumper has no `s2p2` mirror — only this bit.
  - `s1p1` byte[17] = WiFi RSSI sensor (signed dBm) — confirmed across
    −64 to −97 dBm by toggling APs.
  - `s2p51` CONSUMABLES decoder + Blades / Cleaning Brush / Robot
    Maintenance percent sensors with confirmed thresholds (100h /
    500h / 60h).
  - `s1p5` hardware serial fetched on demand via cloud RPC, surfaced
    as the device-info "Serial Number" field + diagnostic sensor.
    Cloud `did` (a 32-bit signed int) split out as a separate
    `cloud_device_id` diagnostic — *not* a serial.
  - WiFi MAC pulled from cloud device record into
    `DeviceInfo.connections` and a diagnostic sensor.
- **v1.0.0a52..a57** — see git log for incremental fixes
  (`async_update_token` callback typing, camera-proxy access-token
  rotation, recovery tooling: `probe-log → session-JSON`,
  `install_recovered.py`, `retrofit_local_legs.py`).
- **v1.0.0a51** (2026-04-30) — End-to-end live-confirmed:
  - Session archive dedups on `(md5, start_ts)`. The cloud's `md5`
    on g2408 is per-map (a stable hash of the unchanged map), not
    per-session — every spot/zone mow after the first was being
    silently dropped on the already-archived branch.
  - "Target area" sensor sources from s1p4 telemetry's
    `total_uint24_m2` (bytes 26-28) when a session is active, so a
    spot/zone mow shows the firmware's actual target area instead of
    the full lawn. Cloud's `spotAreas[].area` is `0` on g2408 so the
    idle-state fallback to total_lawn_area is accepted.
- **v1.0.0a48** — Recognise `task_state_code = 2` as session-end
  alongside `None`.
- **v1.0.0a45/a47** — `Target area` rename + `Mowing count` unit
  restored to `'x'` so HA's recorder keeps historical statistics.
- **v1.0.0a43** — Hourly cloud-RPC poll of `(6, 3)` populates the
  cellular Link Module heartbeat without waiting for the mower's
  sparse spontaneous pushes. Live WiFi RSSI now sourced from
  `s1p1[17]` instead (a58 finding) — the earlier "RSSI from s6.3"
  reading was conflating cellular with WiFi.

## Live-confirmed

- Pause / Stop / Recharge buttons (a27).
- Spot mow end-to-end (a34/a35) — Spot1 selected, Action mode = Spot,
  Start pressed, mower mowed the spot. By extension Zone (op=102) and
  Edge (op=101) wire formats are very likely correct.
- `select.spot` selection persists across HA restart (a31 RestoreEntity).
- Maintenance reminders (16:20, 18:52 on 2026-04-30) → app notification
  "Robot maintenance time reached" matched `s2p2 = 30` precisely on
  CHARGING→MOWING edges.
- Maintenance acknowledgement (slot 2 reset) and Cleaning Brush
  fake-replace (slot 1 reset) → s2p51 CONSUMABLES counters updated as
  expected (a58 wiring picks both up live).
- WiFi AP toggle test → `s1p1[17]` tracked the app's 5-stage signal
  bar in lockstep across −64 to −97 dBm.
- Tilt / lift / bumper / emergency-stop test → all five binary_sensors
  fired in sync with the corresponding app notifications.
