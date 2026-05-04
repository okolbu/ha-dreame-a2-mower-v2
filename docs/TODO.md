# Dreame A2 (g2408) v2 — Outstanding Work

Last updated: 2026-05-04 (v1.0.0a74).

## Open

### Mowing direction / pattern (Crisscross / Chequerboard) — invisible on `/status/`

The Dreame app exposes three related controls under Mowing Settings:
- **Mowing direction angle** — 0–180° (continuous slider; "0" = north?
  empirical "Y-axis"-ish per renderer test)
- **Crisscross** — bool, mowing pattern overlay
- **Chequerboard** — bool, mowing pattern overlay
  (Crisscross + Chequerboard appear mutually exclusive at the app
  level — only zero or one selectable; unconfirmed whether the app
  flips the other off automatically.)

**Capture test 2026-05-04 21:38–21:41 across 8 changes** (4 angles
77° → 0° → 136° → 180°, then Crisscross OFF, Chequerboard ON, then
both OFF) produced exactly 8 `s6p2` MQTT events, **all with the
identical payload** `[50, 0, True, 2]` (height_mm, efficiency,
edgemaster, unknown[3]). Zero variation — the tripwire fires on
every change but the **actual setting value is not in the payload**.

Combined with the existing protocol-doc note (line 120: "Confirmed
NOT to be ... Mowing Direction" for s6p2[3]), this confirms there
is **no observable property on the device's outbound `/status/`
MQTT topic** carrying mowing direction or pattern. The app's preview
stripes on the map are rendered from a value the cloud knows but the
mower never echoes back via MQTT.

Where it could live:
- An undecoded CFG key the integration doesn't currently fetch
  (`getCFG` with the right key name). The integration knows
  `ATA, BAT, CLS, CMS, DND, LANG, LIT, LOW, PROT, REC, VOL, WRP`
  + a longer list in `cfg_action.py` of categories not yet read.
  Worth trying `getCFG` for `MOWP`, `MD`, `DIR`, `STR` (stripe),
  `ANG` (angle), `PAT` (pattern), and similar guesses.
- Cloud-account-resident state (like Auto-Update Firmware), in which
  case there's no way to get it without hitting the cloud HTTP API
  (and even then, only if there's an account-state endpoint).
- Inbound `/cmd/...` topic the broker ACL hides from device-status
  subscribers — same situation as the PIN-clear signal.

Suggested follow-up: brute-force getCFG with plausible 3–4-letter
keys and watch which return non-empty payloads. The mower's response
to an unknown CFG key on g2408 is presumably 80001 or empty; a
hit on a real key would return a list/int that matches the visible
app state.

For now: integration cannot surface mowing direction or pattern.
Documented and parked.

### `byte[10] bit 1` semantics — pinned down 2026-05-04 (5-test series)

**Final model** after 5 controlled tests on 2026-05-04 (incl. one
where the user clarified PIN was at 20:43, lid-close at 20:44):

- **byte[3] bit 7** = "PIN required" / emergency-stop active. Sets on
  any safety event (lid open OR lift). Clears **only** on PIN entry —
  does NOT clear when the lid is closed or the mower is set down.
  Surfaced as `binary_sensor.emergency_stop_activated` (correctly
  named all along).
- **byte[10] bit 1** = one-shot active-alert flag. Sets ~1s after
  byte[3] bit 7 sets, self-clears 30–90s later regardless of PIN/lid
  state. Pairs with the Dreame app's "Emergency stop activated" push
  notification + the mower's red LED + voice prompt. Surfaced as
  `binary_sensor.safety_alert_active` (renamed from `pin_required` in
  a69; original a68 name was based on the wrong hypothesis).
- **error_code (s2p2)** = sticky safety fault. Latches the first event
  (23 then 73 within 1s on g2408) and never naturally clears on the
  device's outbound `/status/` MQTT — even after PIN entry. The app's
  popup dismiss happens via a path the prober (subscribed to wildcard
  `#`, but only `/status/` is allowed by the broker ACL) cannot
  observe.

**Smoking-gun test:** dock-only lid open → lid close, NO PIN. byte[3]
stayed asserted indefinitely after lid close, confirming the bit is
PIN-tied (not lid-tied). All 5 tests are consistent with this model.

**Structural gap:** PIN entry produces zero MQTT events on any topic
the broker ACL exposes. Both probable sources of the app's dismiss
signal — cloud → app push (APNs/account MQTT) and cloud → mower
inbound `/cmd/` topic — are invisible to a device-status-only
subscriber. The integration cannot detect "PIN entered" via MQTT;
would need a cloud HTTP poll (`getDeviceState` or similar) to detect
the lockout-cleared state.

mower_tail.py's "lift-lockout / PIN-required cleared" label for the
byte[3] bit 7 → 0 transition is **correct**.

### Previous incremental findings (kept for traceability)

Two controlled tests on 2026-05-04 + a brief lift-only test:

**Test 1 (19:50–19:51):** manual mow → lift → set down → lid open
→ PIN typed (lid open, mandatory — keypad is under the lid) → lid
close → cancel → Recharge.
- byte[3] bit 7 SET 19:50:43, CLEAR 19:51:02 (likely lid close;
  set-down was probably immediately followed by lid-open keeping bit
  asserted).
- byte[10] bit 1 SET 19:50:44, CLEAR 19:51:20 (**18 s after byte[3]
  cleared**, well after PIN was typed).

**Test 2 (20:08–20:09, lid-only):** manual mow → lid open → PIN
→ lid close → cancel → Recharge. (No lift this round.)
- byte[3] bit 7 SET 20:08:55, CLEAR 20:09:13 (lid close).
- byte[10] bit 1 SET 20:08:56, CLEAR 20:09:17 (**4 s after byte[3]
  cleared**, also after PIN was typed).

**Test 3 (lift-only, brief):** manual mow → quick lift → set down.
No safety lockout fired at all, no app notification. Suggests a
**duration threshold** for the safety chain to actually latch.

What we know:

- byte[3] bit 7 is a **generic safety-chain flag** — both lift AND
  lid-open trigger it; clears as soon as the chain is restored.
  Brief lifts (< some threshold) don't fire it.
- byte[10] bit 1 sets ~1 s after byte[3] bit 7 sets and persists
  past byte[3] clearing.
- **byte[10] bit 1 is NOT cleared by PIN entry** — confirmed because
  PIN must be entered with lid open (keypad is under it), so the
  PIN is always typed BEFORE the lid-close that clears byte[3], and
  byte[10] still clears AFTER byte[3]. PIN was minutes earlier.
- The clear lag is variable (4 s / 18 s in our two data points), so
  it's not a fixed debounce timer either.
- **The Dreame app's "Emergency stop activated" push notification fires
  when byte[10] bit 1 sets**, not byte[3] bit 7.

What we still don't know:

- What actually clears byte[10] bit 1. Candidates: post-recovery
  cool-down, an internal "I've acknowledged the safety event" state
  machine on the mower, or some user action we haven't identified.
- The byte[3] bit 7 duration threshold for triggering the latched
  byte[10] state.
- Why the app notification only fires on lid-open and lift events
  but not on every byte[3] bit 7 set.

Implication: `binary_sensor.dreame_a2_mower_pin_required` (shipped in
a68) is likely **misnamed** — it tracks something more like
"safety-recovery window active" or "post-fault hold". Leaving the
entity in place; rename once semantics are nailed down. The user has
no automations on it yet so the rename is non-breaking.

Next test ideas:

- After a safety lockout, watch for ANY user / mower action between
  byte[3] clear and byte[10] clear (try not pressing anything, just
  wait — does byte[10] eventually clear on its own?).
- Try lifting for 30 s, 60 s, 120 s sustained — find the duration
  threshold that latches the safety state.

### Controlled lift / lid / PIN / lid-down test — partial findings 2026-05-04

A first pass was run during a manual mow (see probe log around
19:50:43–19:51:32, 2026-05-04). Sequence executed: manual mow start →
lift → set down → lid open → PIN typed → lid close → manual abort →
Recharge.

Caveat that limits this run's value: **only the lid-open step
generated an app notification** ("emergency stop voiced"). Lift, tilt,
PIN entry, and lid close did not produce any user-facing event in
the app — those interactions may be local-only on the robot, so we
can't ground-truth which physical action produced which byte change.

Observed byte transitions:

| Time | byte[3] bit 7 | byte[10] bit 1 | s2p2 error_code |
|---|---|---|---|
| 19:50:43 (lift) | **SET** | (still 0x80) | — |
| 19:50:44 (1s later) | SET | **SET → 0x82** | 23, then 73 in same second |
| 19:51:02 (set down) | **CLEAR** | 0x82 (still set) | 73 (sticky) |
| 19:51:20 (some user step) | 0x00 | **CLEAR → 0x80** | 73 (sticky) |

Empirical findings:

- **byte[3] bit 7** behaves as an immediate physical lift sensor:
  sets the moment the mower is picked up, clears the moment it's set
  down. NOT tied to PIN entry as the previous hypothesis claimed.
- **byte[10] bit 1** sets ~1 s after the lift (so it lags the lift
  bit) and persists past set-down, clearing 18 s later somewhere in
  the lid-open / PIN / lid-close window. Best-fit interpretation is
  still "PIN-required latch" but the original "clears one tick after
  byte[3] clears" wording was wrong — it persists much longer.
- **s2p2 = 73 fired during the lift, before any lid touch.** Either
  the apk label "Top cover open" is wrong for g2408, the lift gesture
  also disturbs the lid sensor, or 23 and 73 latch as a pair when
  the safety chain is broken.
- **error_code 73 stayed asserted through the entire window** — never
  cleared even after the lid closed and the mower returned to dock.
  Suggests error_code is sticky-until-suppressed (cf. open SUPPRESS_FAULT
  TODO entry — these may be the same thread).

Open questions:

- Which user step actually clears byte[10] bit 1 — PIN entry, lid
  close, or something else? Need a slower test with ≥30 s gaps
  between each individual physical step so the byte transitions can
  be unambiguously mapped to actions.
- Why did the cloud emit error 73 *during the lift* rather than at
  lid open? (App label says top-cover-open; observed behaviour is
  different.)
- Does pressing `dreame_a2_mower.suppress_fault` clear sticky error_code?

Re-run procedure (now that we know the mower stays on the lawn after
a lift if the user doesn't press anything):

1. Manual mow start → wait until on lawn.
2. Lift → wait 60 s, set down → wait 30 s.
3. Open lid → wait 30 s.
4. Type PIN → wait 30 s.
5. Close lid → wait 30 s.
6. Press Recharge.

The 60 s post-lift wait will let us see if byte[10] bit 1 clears on
its own (timer) vs. at PIN entry (manual). The 30 s gaps between
lid-open / PIN / lid-close should isolate which step clears the bit.

Once the bit's true semantics are pinned, decide whether to expose
it as `binary_sensor.dreame_a2_mower_pin_required` or similar.

### `ai_obstacle` blob format — capture wire shape

`SessionSummary.ai_obstacle` is currently typed as `tuple[Any, ...]`
because no g2408 session in the corpus has produced one (every captured
session has `ai_obstacle: []`). Likely an AI-detected obstacle (pet,
person, etc.) tied to the AI camera; the legacy integration treated
ai_obstacles separately from regular obstacles. When the first
non-empty payload appears, decode it in `protocol/session_summary.py`
and decide whether to render in a different colour (e.g. orange) on
the replay map.

Capture procedure:

1. Bookmark the probe log + snapshot the session_summary fetch.
2. Drive the mower past a pet / person / known AI-trigger object
   during a session.
3. End the session, retrieve the OSS JSON from the cloud, save the
   `ai_obstacle` array as a fixture under
   `tests/protocol/fixtures/`.
4. Update `Obstacle`-style decoder + tests + renderer to distinguish.

### Patrol Logs — investigate triggering and capture wire format

The app's "Work Logs" page has two tabs: **Mowing Logs** (which the
integration archives + replays) and **Patrol Logs** (currently empty
on the user's account; no obvious way to initiate a Patrol from the
app's main UI). Goals:

1. Find what gesture / menu item starts a Patrol session. Likely
   candidates: a long-press on a map waypoint, a hidden "Patrol" mode
   in the start-menu, or a feature gated on a Link Module / cellular
   subscription tier.
2. If a Patrol can be triggered, capture the s2p51 / s2p50 / event_occured
   sequence and the resulting JSON in OSS — the schema is likely
   different from `MowingTelemetry` since the mower's task isn't
   "cover the lawn" but "follow a route".
3. Decide whether to expose Patrol sessions in the integration:
   either as a sibling archive (`patrol_archive.json`) or as a
   second tab in the existing replay UI.

### Authoritative lifetime totals — find cloud aggregate endpoint

The app's "Work Logs" header shows lifetime aggregates that exceed
what the integration calculates locally. User's app on 2026-04-30:

```
Total Mowed = 4745 m²
Total Time  = 3134 min
Sessions    = 34
```

The integration's `sensor.mowing_count` / `total_mowing_time_min` /
`total_mowed_area_m2` are computed by `coordinator.py` summing
the local `session_archive` (via `session_archive.list_sessions`)
because legacy's cloud read at `s12.1..s12.4` returns 80001 on g2408.
Result: HA shows only sessions captured since integration install.

Investigation paths:
- Decompile / packet-sniff the app's Work Logs page open — note
  which endpoint the app hits.
- Try `getCFG t:'STATS'` or similar `t:` targets on the routed-action
  endpoint (siid:2 aiid:50). The 24-key CFG dump didn't show stats
  but a different `t:` value might.
- Check whether the cloud OSS bucket has a per-account stats
  document (similar to how MAP and session-summary JSONs are listed
  under `ali_dreame/<date>/<acct>/...`).

If the endpoint is found, prefer it over local aggregation so HA
totals match the app exactly. Keep the local aggregation as a
fallback for offline use.

### Firmware update flow — capture wire sequence (currently un-instrumented)

Only one firmware update has happened on the user's mower, and it was
before the HA integration was running, so the wire sequence isn't in
the probe corpus.

**Confirmed not on MQTT (2026-04-30):** the app's *"Auto-update
Firmware"* toggle is purely cloud-side — toggling it produced **zero**
events on the device's MQTT status topic. So the auto-update preference
lives in the user's cloud account, not on the mower. The integration
can't read it via the wire we listen on, and likely can't read it
via the routed-action paths we use either (CFG schema doesn't
include an "auto-update" key).

Open questions for actual update events (not the preference toggle):

- What MQTT events fire while an update is *running* (download
  progress, reboot, version-string change)? Candidates already
  observed in the corpus:
  - `s2.1 STATE = 14 (UPDATING)` — already in our `State` enum, so
    the device clearly transitions through it; just no surrounding
    capture.
  - `s2p53` "VOICE_DOWNLOAD_PROGRESS_PCT" in OBSERVED_LABELS — could
    be the firmware-download progress, not just voice packs. Confirm.
  - `s2p57` "SHUTDOWN_TRIGGER" — likely fires for the post-update
    reboot.
- Is the version string in `device.info.version` updated atomically
  at end-of-update? `sensor.firmware_version` reads it; behaviour
  during update unknown.

Capture plan: when the next firmware update notification appears in
the app, **don't tap update yet** — bookmark the probe log first,
then proceed with the update from the app, then dump the captured
events. Likely-rare event, so worth setting a calendar reminder
periodically to check the app for an "Update Available" banner.

Outcome: document the update-flow MQTT sequence in
`docs/research/g2408-protocol.md` under a new §X "Firmware update
lifecycle" section. Determine whether HA can:
1. Surface "update available" as a binary_sensor (read-only).
2. Trigger an update via routed action (probably not — likely cloud-push only).
Also add a §6.1 note that "Auto-update Firmware" is account-level
cloud state with no MQTT echo, so the integration can't surface it
as an entity.

### Change PIN Code — capture wire format (likely BT-only)

The app has a "Change PIN Code" action under Security / Anti-Theft.
The on-device PIN is what the user types after a lift-lockout to unlock
the mower (see `s2p2 = 23` lockout flow in §3.4 byte[3] bit 7).
Capture procedure:

1. Bookmark the probe log + snapshot `sensor.cfg_keys_raw` attributes.
2. Open the app → Settings → Change PIN Code → enter current → set new.
3. If nothing fires on s2p51 / s2p50 / event_occured during the
   action, this is likely a BT-only operation (consistent with the
   PIN being a security-critical local secret that shouldn't transit
   through cloud relay). The integration would then have no way to
   read or write it.
4. If something does fire — capture the envelope, slot semantics, and
   add to `protocol/config_s2p51.py` or wherever fits.

Outcome: confirm whether PIN-change is cloud-visible or BT-only.
If BT-only, document under §6.1 "Cloud-visible vs Bluetooth-only
settings" so future readers don't waste time looking for a cloud
endpoint that doesn't exist.

### Pathway Obstacle Avoidance test — likely candidate for `CFG.BP` / `CFG.PATH`

Two CFG keys still have placeholder semantics:
- `CFG.BP` — `list(2) [1, 3]` (same shape as `WRP` Rain Protection but
  different meaning).
- `CFG.PATH` — `int {0, 1}` stable at `1`. Confirmed *not* Navigation
  Path (that's `PROT`).

Hypothesis: both relate to the **Pathway Obstacle Avoidance** app feature,
which lets the user mark areas / pathways where the mower may bypass
obstacles. Currently no pathways are defined on the user's map, so
neither field has been observed changing.

Procedure:

1. Bookmark the probe log; snapshot `sensor.cfg_keys_raw` attributes.
2. Open the app → Map → define a fake pathway (any small line will do).
3. Mark the pathway for "Pathway Obstacle Avoidance".
4. Note the s2p51 events fired during the action.
5. Re-fetch CFG (or wait for the 10-min refresh); diff the snapshot.
6. Toggle the pathway's avoidance flag and capture again.
7. Delete the fake pathway when done.

Expected outcomes:
- If `CFG.BP` is the per-pathway list (e.g. `[count, max_pathways]` or
  `[active_id, count]`), values should change as pathways are added/edited.
- If `CFG.PATH` is the master "Pathway Obstacle Avoidance enabled" toggle,
  `PATH` should flip 1→0 when the screen-level toggle is off.
- Either could also be related to a different cluster of map features.

Outcome: pin down the semantics for both keys; add proper labels to the
CFG schema table in `docs/research/g2408-protocol.md` §6.2; expose as
HA entities (sensors or switches) per the existing pattern.

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

### `MowerAction.SUPPRESS_FAULT` — confirm semantics before adding a button

The integration carries `MowerAction.SUPPRESS_FAULT` ({siid:4, aiid:3,
routed_o:11}) and registers `dreame_a2_mower.suppress_fault` as a
service, but the action has never been live-tested and the *semantics*
are unclear:

- Does "fault" mean a **technical malfunction** (sensor error, motor
  fault, firmware-detected hardware issue — i.e. things in
  `error_codes.py`) that the user wants to acknowledge/dismiss?
- Or does it cover **physical/situational alerts** (mower flipped, lift
  lockout, top cover open, stuck on grass) that resolve themselves
  once the user fixes the situation and would not need an explicit
  "suppress" action?
- Or both — i.e. a generic "clear pending alert / dismiss notification"
  call that the app uses for any of the above?

Investigation paths:

1. Trigger a known fault we can reproduce safely (e.g. lift the mower
   and watch `s2p2 = 23` set; then drop and see what state the app
   shows the "dismiss"/"acknowledge" UI in).
2. Note which app screen has a "Suppress" / "Dismiss" / "I've fixed it"
   style button.
3. Trigger that button → snapshot the inbound `/cmd/` MQTT (separate
   subscription needed; the `/status/`-only prober is structurally
   blind to cloud→device commands; cf. Find My Robot finding) AND any
   resulting `/status/` property change to identify what the call
   actually does.
4. Verify against the legacy DreameMowerAction.CLEAR_WARNING semantic
   in alternatives/dreame-mower (Tasshack) — the legacy may have a
   docstring or service description that pins the meaning.

Outcome: once semantics are pinned, decide whether to (a) wrap as
`button.suppress_fault` (available only when the relevant fault
condition is active), (b) leave it service-only (power-user), or
(c) drop it from the integration if it turns out to be vestigial.

## Recently shipped (a52 → a74)

- **v1.0.0a74** — Replaced `switch.smart_navigation_path` (opaque
  on/off toggle) with `select.navigation_path` having explicit
  options "Direct Path" / "Smart Path". CFG.PROT mapping unchanged
  (0=direct, 1=smart); just the surface vocabulary now matches the
  Dreame app's own labels. Dashboard's Mowing Settings → Mowing mode
  card updated to use the new select. Breaking for users with
  automations on the old switch entity_id (single HA install with
  no automations on it).

- **v1.0.0a73** — Cleaned up the legacy MQTT-bringup persistent
  notifications (`dreame_a2_mqtt_bootstrap`, `..._connected`,
  `..._first_msg`) — useful during the a8/a9 early bring-up when HA
  log access was uncertain, but pure noise now that the integration
  is stable. Demoted to `LOGGER.debug(...)` calls. The notification
  panel is reserved for genuinely user-actionable events (emergency
  stop, etc.). Re-enable as `_pn.create(...)` calls if a fresh-install
  MQTT regression needs diagnosing.

- **v1.0.0a72** — Cleanup of a71 debug logging now that the
  emergency-stop notification path is end-to-end live-confirmed:
  lid-open posts the persistent_notification ("Enter PIN code on the
  robot to unlock it") + dashboard banner; PIN entry on the device
  dismisses both. Verbose WARNING-level transition diagnostics
  downgraded to INFO; only actual create/dismiss failures still log
  at WARNING.

- **v1.0.0a71** — Bugfix to a70: the persistent_notification hook for
  `emergency_stop` was wired to the cloud-RPC-response path, not the
  inbound MQTT push path. Result: dashboard banner worked (it's a
  state-machine read), but no notification appeared on lid open.
  Moved the hook into `_apply()` inside `handle_property_push()`,
  which is the actual path s1p1 heartbeats take from the MQTT
  message callback. Also made the trigger robust against `None →
  True` transitions (handles first-heartbeat-after-restart with
  mower already in lockout state).

- **v1.0.0a70** — Emergency-stop UX surfaced to match the Dreame app.
  When `binary_sensor.emergency_stop_activated` flips on (PIN-required
  lockout), the coordinator posts a `persistent_notification` titled
  "Dreame A2 Mower — Emergency stop activated" with the same call-to-
  action as the app's modal popup ("Enter the PIN code on the robot to
  unlock it"). Notification dismisses automatically when byte[3] bit 7
  clears (PIN entered). Also adds a conditional markdown banner at the
  top of the Mower dashboard view, visible only when locked out.

- **v1.0.0a69** — `binary_sensor.pin_required` (shipped a68) **renamed
  to `binary_sensor.safety_alert_active`** after a 5-test controlled-
  lift series on 2026-05-04 pinned down the actual semantics. byte[10]
  bit 1 is a one-shot alert flag (self-clears 30–90s later regardless
  of PIN entry), not a persistent PIN-required latch. The actual
  PIN-required latch is byte[3] bit 7 — the existing
  `binary_sensor.emergency_stop_activated` — which has been correctly
  named all along (it doesn't clear until PIN is entered, contrary to
  the earlier "immediate lift sensor" hypothesis).

  **Breaking for users with automations on the a68
  `binary_sensor.pin_required` entity** — the entity_id changes via
  unique_id change. Old entity will go to "unavailable" and can be
  manually removed. The user (single HA install) had no automations
  on it.

- **v1.0.0a68** — `binary_sensor.dreame_a2_mower_pin_required` decoded
  from `s1p1` byte[10] bit 1. (Renamed in a69 — see above.)

- **v1.0.0a67** — Find My Robot **button entity** added: presses
  `dreame_a2_mower.find_bot` (already a service since F3, with the
  wire format pre-mapped at `actions.py:153` as `{siid:7, aiid:1,
  routed_o:9}`). End-to-end live-confirmed against a g2408 — mower
  voices "The Robot is here". The action travels cloud → mower on the
  inbound `/cmd/` topic with no `/status/` echo, which is why the
  external prober (subscribed only to `/status/`) saw nothing during
  the verification: not a bug, just structural blindness on that path.

- **v1.0.0a66** — Showcase dashboard refresh: `aspect_ratio: 637x717`
  on Live Map and Replay map so the whole lawn fits vertically without
  cropping; dropped the now-redundant static "LiDAR (top-down)" picture
  card from the LiDAR view (the WebGL card replaces it). Fixed a dead
  entity ref `sensor.dreame_a2_mower_total_lawn_area` →
  `sensor.dreame_a2_mower_target_area`. Added previously-unsurfaced
  entities to the showcase: firmware update entity, location tracker,
  five new alerts (lifted/tilted/cover/bumper/emergency-stop),
  maintenance-life sensor, smart-navigation/frost-protection/AI-photos
  switches, human-presence detection, voice-prompts and push-notifications
  sections, language select, LED period switch, auto-recharge-after-standby.

- **v1.0.0a65** — LiDAR card overhaul:
  - In-card **⛶** expand button opens an interactive fullscreen
    overlay (drag-orbit / wheel-zoom / splat slider / map underlay all
    work). Dismisses on ESC, **×**, or backdrop click. The
    `dreame_a2_mower.show_lidar_fullscreen` service also triggers it.
  - Map underlay finally renders: `camera.dreame_a2_mower_map` now
    exposes `calibration_points` derived from `MapData.bx2/by2/pixel_size_mm`,
    so the card can affine-fit the mower-mm → PNG-pixel transform.
    Was silently failing for the entire history of the card because
    the attribute didn't exist.
  - Camera viewpoint (yaw / pitch / distance) and the Map underlay
    toggle now persist via `localStorage` across dashboard navigation.
    `pick()` precedence inverted to localStorage > YAML > default so
    YAML's `show_map: true` only seeds the first-time default instead
    of overriding user choice every load.
  - **↺** reset-view button — escape hatch when you've orbited into
    a confusing pose.
  - Base map's `lawn_fill` switched 255→221 grey to match legacy
    `MapRendererColorScheme.floor`; the desaturated underlay now reads
    as a calm grey background under the 3D points instead of a glaring
    white sheet.
- **v1.0.0a64** — Replay map redraws session obstacles as semi-transparent
  blue polygons (lifted colour from legacy `protocol/trail_overlay.py`).
  `render_with_trail` gains an optional `obstacle_polygons_m` parameter;
  `coordinator.replay_session` extracts `summary.obstacles` and passes
  them through. Live mowing renderer is unchanged. `ai_obstacle` is
  still un-rendered — see open item.
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
  Start pressed, mower mowed the spot.
- Zone mow end-to-end — multiple 5/8-minute zone sessions captured in
  the probe log; op=102 + region payload confirmed working on g2408.
- Edge mow (op=101) — wire format extrapolated from Tasshack but never
  explicitly tested on g2408; live-confirm next time the mower is at
  the dock.
- Find My Robot (a67) — button + service both confirmed; mower voices
  "The Robot is here".
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
