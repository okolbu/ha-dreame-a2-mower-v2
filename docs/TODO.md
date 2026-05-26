# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
For overall protocol architecture see `docs/research/g2408-protocol.md`.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

(Resolved 2026-05-26: the s6.3 slow-poll item was superseded — `_poll_slow_properties`
was removed entirely and `MowerState.cloud_connected` dropped. Heartbeat byte[17]
already supplies fresh wifi_rssi_dbm, MQTT-up implies cloud-connected, and DEV
owns the serial. The new `binary_sensor.cloud_connected` + `sensor.mqtt_age_s`
are backed by `coordinator.last_mqtt_unix`, stamped on every MQTT push.)

### Derive a real "blades worn" event from wear%

**Why:** `S2P2_NOTIFICATION_MAP[28]` used to fire `blades_worn` on every undock
(28 is the off-dock relocate marker, not blades) — corrected 2026-05-25, so
there is now NO blades-worn event at all. The real signal is `blades_life_pct`
(consumables wear%), which is what the Dreame app uses to compose its push.
**Done when:** a blades-worn event/binary_sensor fires off a `blades_life_pct`
threshold (matching the app's wear% behaviour), not off s2p2.
**Status:** open
**Cross-refs:** `coordinator/_property_apply.py` (S2P2_NOTIFICATION_MAP, blades_life_pct); `inventory.yaml` § s2p2.

### Reconcile mower/error_codes.py with verified s2p2 findings

**Why:** `ERROR_CODE_DESCRIPTIONS` still carries vacuum-derived guesses that
conflict with verified codes — e.g. 63="Blocked" (verified: "Scheduled task
cancelled — Robot working"), 54="Edge fault" (notification map:
"low_battery_return"). Both `mower_tail.py` and `probe_a2_mqtt.py` source labels
from this table, so the wrong ones surface in the narrative.
**Done when:** each s2p2 code in `error_codes.py` is reconciled against
`inventory.yaml` § s2p2 + `S2P2_NOTIFICATION_MAP`, correcting/annotating the
vacuum-derived entries.
**Status:** open
**Cross-refs:** `mower/error_codes.py`; `coordinator/_property_apply.py` (S2P2_NOTIFICATION_MAP); `inventory.yaml` § s2p2.

(Resolved 2026-05-25: the external probe enum-mislabel item — `probe_a2_analyze.py`
retired to `OLD/`; `probe_a2_mqtt.py` now integration-sources s2p1/s2p2 labels.)

### Phase 2: MAP write — programmatic boundary/zone editing

**Why:** With chunked-batch writes confirmed working (Phase 1 done in
v1.0.2a1), the MAP surface is the next big capability. Drawing
boundaries and editing mowing/exclusion zones from HA without walking
the mower would be a major UX win.
**Done when:** A safe MAP write surface exists with auto-backup of the
current MAP blob before any write, restore-from-backup mechanism, and
a Lovelace card for boundary editing.
**Status:** open
**Cross-refs:** spec
`docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
"Phase 2"; `docs/research/cloud-write-reference.md`.

### Re-verify EdgeMaster / Mowing Efficiency cloud-field correlations

**Why:** `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md`
catalogued EdgeMaster (`s6p2[2]`) and Mowing Efficiency (`s6p2[1]`)
as BT-only / not-in-cloud-CFG. Those claims predate the
2026-05-08 cloud-discovery findings and may be outdated; both could
now be writable via `setDeviceData` if the cloud surfaces them under a
chunked-batch key we haven't probed.
**Done when:** Toggle each in the app while monitoring the empty-batch
read; if any chunked-batch key changes, surface as a new entity. If
neither changes, document as confirmed BT-only post-cloud-discovery.
**Status:** open
**Cross-refs:** historical doc; `docs/research/cloud-write-reference.md`.

### SETTINGS dual-entry — closed 2026-05-09

**Why:** Originally open as "decode the dual-entry semantic". v1.0.2a2
read from the LAST entry; v1.0.2a3 corrected to entry 0 after a
controlled cloud diff against a two-device app save proved entry 0
is the user-saved entry (versioned, app-reflecting) and entry 1 is
a firmware-applied mirror (stays at `version: 0`, lags arbitrarily).
Writes propagate to both entries (defensive). See
`docs/research/cloud-write-reference.md` "Dual-entry semantic" and
the 2026-05-09 entry of `docs/research/g2408-research-journal.md`.
**Status:** done (no further work).
**Cross-refs:** commit `b25b5ac` (v1.0.2a2), commit pending (v1.0.2a3);
fixture `tests/protocol/fixtures/2026-05-08-settings-sample.json`.

### Capture zone / edge action codes for SCHEDULE blob

**Why:** The SCHEDULE blob format was decoded 2026-05-08 (see
`protocol/schedule.py` for the verified record layout). The action-
type nibble has only been observed as `0` (All-area mowing) — the
zone (1?) and edge (2?) codes are not yet pinned down. The user's
Dreame app supports All-area / Zone / Edge plans; capturing one of
each in the cloud blob would close out the catalogue.
**Done when:** the user adds a Zone-mowing and Edge-mowing schedule
in the app, the next cloud dump is captured, and the `_ACTION_LABELS`
dict in `sensor.py` is updated with the verified codes (plus
appropriate test fixtures in `tests/protocol/test_schedule.py`).
**Status:** blocked-by-user-data
**Cross-refs:** `custom_components/dreame_a2_mower/protocol/schedule.py`;
`/data/claude/homeassistant/schedule-doc.txt`

### OTA_INFO field semantics

**Why:** v1.0.0a100 surfaces `cloud_state.ota_status` as
`(int, int)` — the test fixture observed `(2, 100)`. We assume
the first field is a status code and the second is a percent (0-100),
but neither has been confirmed during a real OTA update. The
sensor uses `state = ota_status[0]` and `attr percent = ota_status[1]`;
mapping numeric statuses to human-readable strings (idle / downloading /
applying / failed / etc.) requires observation during an actual OTA.
**Done when:** the status-code → state-string mapping is documented
in `docs/research/g2408-research-journal.md` and the sensor either
returns the string directly or exposes both via attributes.
**Status:** blocked-by-OTA-observation (next firmware update).
**Cross-refs:** spec "Out of scope" item 5.

### Add integration icon via home-assistant/brands PR

**Why:** The HA Integrations page shows a blank square or nothing next to the
Dreame A2 Mower entry. Icons must come from `home-assistant/brands`, not the
integration's own folder.
**Done when:** A PR is merged to `home-assistant/brands` adding
`custom_integrations/dreame_a2_mower/icon.png` + `icon@2x.png`; the icon
appears on the Integrations page and in HACS.
**Status:** open
**Cross-refs:** upstream `home-assistant/brands` repo; source image at `/data/claude/homeassistant/dreame-a2-icon-large.jpg`

---

### Surface dock-departure repositioning UX

**Why:** The Dreame app shows a 3-stage popup ("Repositioning..." →
"Repositioning Successful" → "Mowing started") at every dock departure.
No MQTT property carrying this state has been identified yet — three
dock departures on 2026-05-05 produced no `s2p65` or `s5p104..107` events.
**Done when:** The MQTT property (or cloud-only push) carrying relocate-state
is identified, or confirmed cloud-only (in which case document and close).
**Status:** blocked-by-capture
**Procedure:** [docs/research/g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture](g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture)
**Cross-refs:** `docs/research/g2408-protocol.md §1` (80001 failure context); probe-log correlation needed

---

### Alert-tier event surface (follow-up to lifecycle PR)

**Why:** The lifecycle-tier event surface (a91) reserved
`event.dreame_a2_mower_alert` with empty `event_types`. Populate it
with `emergency_stop`, `lifted`, `tilted`, `stuck`, `bumper_error`,
`obstacle_with_photo`, `battery_low`, `battery_temperature_low`, `error`.
Add `CONF_NOTIFY` option toggle. Migrate the existing bespoke
`_handle_emergency_stop_transition` banner to a framework-managed
persistent_notification gated by CONF_NOTIFY.
**Done when:** All listed event_types fire from the appropriate
detection sites; `_handle_emergency_stop_transition` is replaced;
docs/events.md gains the alert section; emergency_stop banner
behavior is unchanged from the user's perspective.
**Status:** open
**Cross-refs:** `docs/superpowers/specs/2026-05-07-event-surface-design.md` § "Out of scope"

---

### Lifecycle event-surface PR — review-flagged cleanups

**Why:** The final whole-branch review of v1.0.0a91 (the lifecycle event
surface) flagged five non-blocking follow-ups that should not be lost:

1. **conftest.py placement** — `tests/event/conftest.py` stubs only
   `homeassistant.components.event` while the root `tests/conftest.py`
   already stubs every other HA component in one place. Fold into the
   root conftest for consistency.
2. **Unused `_attr_translation_key`** — both event entities set
   `_attr_translation_key="lifecycle"` / `"alert"` but `translations/en.json`
   has no `entity.event.*` block. Either add the translation entries
   or drop the unused keys.
3. **`_make_coordinator_for_persist_tests` fixture incomplete** —
   `tests/integration/test_coordinator.py` has three coordinator-stub
   fixtures; two set `_lifecycle_event` / `_alert_event` / `_prev_in_dock`,
   the persist one only sets `_prev_in_dock`. Latent foot-gun if a
   future test extends the persist case to call fire-paths.
4. **`mowing_ended` may double-fire on cloud md5 dedup hit** —
   `_do_oss_fetch` fires `_fire_mowing_ended` even when the cloud reused
   the md5 (dedup hit). The session was already finalized once; firing
   again is questionable. Add a guard or accept and document.
5. **`reason` heuristic in `mowing_paused`** — only emits
   `"recharge_required"` when `battery_level <= 20`; nullable
   `battery_level` always resolves to `"unknown"`. The threshold 20 is
   a magic number. Pull into a const, handle None explicitly, and
   consider expanding the reason vocabulary alongside the alert-tier PR.
**Done when:** Each of the five items is either fixed or explicitly
closed with a "won't fix because X" note.
**Status:** open
**Cross-refs:** final review on commit `e32c8f4..51f6883`;
`docs/superpowers/plans/2026-05-07-event-surface-lifecycle.md`

---

### Novel-observation sensor floods on continuous-integer slots

**Why:** `sensor.dreame_a2_mower_novel_observations` accumulated 51 entries
before a reboot 2026-05-07 and 5 since. All observed entries are
`category: value` for slots without a `value_catalog` — e.g. `s3p1`
battery_level (every new percentage triggers), `s5p107` energy_index
(int 1..250), `s1p53` obstacle_flag (True/False both fire on first
observation). The registry's first-time-seen-value path is correct as
a log signal but is noise on the user-visible sensor.
**Done when:** The sensor's `observations` attribute filters out
`category: value` entries for slots whose `_INVENTORY.value_catalogs`
entry is None. INFO-level logging of those novelty events stays so
contributor diagnostics aren't lost.
**Status:** open
**Cross-refs:** `coordinator.py` novelty dispatch around line 2843;
`observability/registry.py`

---


<!-- DONE — see commit history for the photo_consent + show_photo_privacy_policy
landing 2026-05-09. binary_sensor.photo_consent reads REC[7]; the verbatim
"AI Obstacle Recognition Privacy Policy" is bundled at
custom_components/dreame_a2_mower/data/privacy_policy_photo.md and surfaced
via the dreame_a2_mower.show_photo_privacy_policy service. -->

---

<!-- DONE 2026-05-09: text-language picker enumerated from user
screenshots (lang1.PNG / lang2.PNG / lang3.PNG). 33 entries, 1-indexed
on g2408 (vs voice's 0-indexed). TEXT_LANGUAGE_NAMES filled in;
position 0 reserved as None placeholder for a possible future "use
phone language" slot. T4 device-apply confirmation still pending —
pick "English" or any other option in select.text_language and verify
the Dreame app reflects the change. -->

---

### Trigger a fresh WiFi heatmap render

**Why:** v1.0.3a7 ships a working `camera.dreame_a2_mower_wifi_heatmap`
that renders the **latest cached** WiFi map from OSS, plus a
`button.request_wifi_map` that refreshes the cache. But there's no
way for the integration to *trigger a fresh scan* on the device:

- `s6.aiid=4` (the "request fresh" path per ioBroker.dreame v0.3.7 +
  Tasshack `dreame-mover` — they fire-and-forget then wait 30s for
  the OSS object to appear) returns 80001 on g2408 — the siid=6 RPC
  tunnel is closed on this firmware. Verified 2026-05-09.
- Same `g.OBJ d={type:'wifimap'}` route returns 2 already-cached
  objects (auto-generated by the mower at unknown trigger times).

So today the user sees whatever the mower last decided to render —
not a freshly-commissioned scan. This is a niche feature on a robot
mower (most users don't care about WiFi coverage) but worth pinning.

**Suspected real path** (in priority order for a future sniff):

1. **Routed-action opcode** — like `op=10 GENERATE_3D_MAP`, there
   may be a `op=N REQUEST_WIFI_MAP` we haven't enumerated. Try a few
   sequential opcodes near 9-12 once docked, watching for new OSS
   objects 30-60s later.
2. **MQTT direct publish** to `/cmd/<did>/` — Xiaomi-pattern command
   bypass. Same suspected path as SCHEDULE writes.
3. **Different cloud HTTP endpoint** — outside the routed-action /
   chunked-batch / MIoT-property surfaces.
4. **A scheduled-trigger entity-of-interest** — maybe writing a
   specific CFG key (e.g. setting some "wifi diagnostics" flag) makes
   the device run its own scan and upload.

**Done when:**
1. We can call a method that produces a NEW wifimap OSS object within
   ~60s (verifiable: `g.OBJ d={type:'wifimap'}` returns a previously-
   unseen filename).
2. `button.request_wifi_map` triggers that fresh scan + auto-fetches
   the new file once it appears (no manual second tap needed).
3. Matrix row flipped from "✓ refresh-from-cache only" to "✓ end-to-end".

**Status:** open (Phase 3 — needs HTTPS+MQTT sniff while watching the
Dreame app's wifi-map UI; same sniff session can cover the SCHEDULE,
SETTINGS, AI_HUMAN, and BAT/REC/LANG-int-list gaps).
**Cross-refs:** `cloud_client.fetch_wifi_map`, `coordinator._refresh_wifi_map`,
`button.request_wifi_map`, `camera.dreame_a2_mower_wifi_heatmap`, the
matrix `button.request_wifi_map` row.

---

### WiFi heatmap overlay on the live map

**Why:** v1.0.3a7 renders the WiFi heatmap as a standalone PNG
(`camera.dreame_a2_mower_wifi_heatmap`). The decoded JSON includes
`startX`, `startY`, `resolution`, `width`, `height` — all in the same
cloud-frame coordinate system as the lawn map. So the heatmap can be
reprojected onto the live-map renderer as a translucent layer, giving
users a "WiFi coverage by lawn area" view they can toggle on/off.

User suggestion 2026-05-09: "potentially a toggled heat map of
colored squares on top of the main map. Potentially oriented from the
dock?". Anchor is straightforward — same coordinate frame; the
existing renderer already handles cloud-frame → image-frame
transforms. Toggling can either be a switch entity ("WiFi overlay
on/off"; `MowerState.wifi_map_overlay_enabled`) or a Lovelace
picture-elements layer.

**Done when:**
1. `map_render` accepts a `wifi_map_data` kwarg that, when truthy,
   composites the RSSI cells over the lawn pixels at the right cloud-
   frame offsets and resolution.
2. A user-controllable switch (`switch.show_wifi_overlay` or similar)
   gates the overlay so it can be turned off.
3. The Mower-tab live map updates when the switch flips and when
   `MowerState.wifi_map_data` changes.
4. Cell rendering is alpha-blended (~50% so the lawn underneath is
   still visible) and uses the same red→yellow→green dBm gradient as
   the standalone camera.

**Status:** open (design+implement). Lower priority than the
GPS-coords gap and the SETTINGS Phase 3 sniff.
**Cross-refs:** `wifi_map_render.py`, `map_render` (live-map renderer),
`docs/research/cloud-map-geometry.md`.

---

### GPS world-coordinate read path — find the surface the Dreame app uses

**Why:** `device_tracker.dreame_a2_mower_location` is plumbed to the cloud `routed-action g.LOCN → {pos: [lon, lat]}` path, but on g2408 LOCN returns the `[-1, -1]` sentinel even with `switch.anti_theft_realtime_location` (CFG.ATA[2]) ON. The Dreame app's **Real-Time Location** sub-page nevertheless shows the mower at its correct world coordinates, so the app reads GPS from a different cloud / MQTT surface that the integration has not yet identified. The legacy fork hit the same wall (`coordinator.py:287-294`).

**Confirmed it's NOT**:
- `routed-action g.LOCN` (returns sentinel)
- LIDAR / odometry (those are mower-frame, not world-frame)
- a "dock GPS origin anchor" — user 2026-05-09 confirmed the mower has its own GNSS hardware
- the apk geofence subsystem (apk.md line 242 confirms it's for phone-GPS smart-lock auto-unlock, not the mower)

**Suspected candidates**:
- A different cloud routed-action key (`GPSPOS`, `GEOLOC`, etc.) we haven't probed
- An MQTT push: a `s2p51` message type beyond what we currently dispatch, or a broader robot-pose extension on `s1p4`
- A separate cloud HTTP endpoint outside the routed-action / chunked-batch surfaces
- ioBroker's apk catalog mentions `LOCN setLocation {pos}` for setting the GPS — the read counterpart on a healthy device may not be `getCFG` but rather a different envelope

**Done when:**
1. An HTTPS sniff of the Dreame app on the Real-Time Location page identifies the actual surface (request body + response shape).
2. `cloud_client` adds a fetch path (likely a new method, parallel to `fetch_locn`).
3. `_refresh_locn` is repointed (or a new `_refresh_gps_world` runs alongside).
4. `device_tracker.location` populates with valid lat/lon while ATA[2] is on; the dashboard's GPS map card renders.
5. Validation matrix row flips from ✗ live (KNOWN GAP) to ✓ end-to-end.

**Workaround for users right now**: open the Dreame app's Real-Time Location sub-page directly. The HA dashboard hides the map card while ATA[2] is off and falls back to a "toggle on to enable" notice — the same notice now mentions this gap so the user knows the integration's path isn't the same as the app's.

**Status:** open (Phase 3 — needs HTTPS capture). Recipe candidate to bundle with the broader Phase 3 sniff session (Phase 3 also covers SETTINGS / AI_HUMAN.0 / SCHEDULE writes).
**Cross-refs:** `docs/research/entity-validation-matrix.md` device_tracker row; `cloud_client.fetch_locn`; `coordinator._refresh_locn`; `OLD/alternatives_archive_2026-05-05/ha-dreame-a2-mower-legacy/custom_components/dreame_a2_mower/coordinator.py:287-294` (legacy reaching the same conclusion).

---

### LiDAR archive AND WiFi heatmap — per-map (CONFIRMED REQUIRED)

**Why:** The Dreame app's "pick the current map" screen exposes a
**dedicated LiDAR button per map** (user observation 2026-05-09) — so
the firmware does keep a distinct LIDAR blob for each map, not a
single global one. Today's `lidar_archive` is a flat folder; we need
to scope archives by `map_id` and surface per-map LIDAR cameras /
selectors so a user looking at Map 1 sees Map 1's LIDAR scans, not
Map 2's.

**Same gap applies to WiFi heatmaps** (v1.0.3a7+): the wifi map JSON
includes `startX`/`startY`/`resolution`/`width`/`height` in the
cloud-frame coordinate system, which is **per-map** (each map has its
own bbox). Currently `cloud_client.fetch_wifi_map` picks the newest
OSS object regardless of map; if the user has multiple maps, they'd
see whichever map was scanned most recently, not "the wifi map for
Map 1". Same coordination as LIDAR — needs `map_id` on cached entries
and per-map camera entities (or selector).

**Done when:**
1. lidar_archive entries carry a `map_id` field (or live in per-map
   subdirectories).
2. The LiDAR camera entities are per-map — `camera.lidar_top_down_<map_id>` /
   `camera.lidar_full_resolution_<map_id>` — or a single camera with a
   selector that picks which map's latest scan to render.
3. The fetch path knows which map a new LIDAR blob belongs to. Likely
   sourced from the same `s2p51` push or routed-action key that
   identifies the active map at scan time.
4. The LiDAR dashboard tab updates to show the relevant per-map view.
5. Backwards-compatibility: existing flat archives are migrated to
   "unknown map" or to the active map at migration time so we don't
   lose history.

**Status:** confirmed required (was investigation, now design+implement)
**Cross-refs:** `custom_components/dreame_a2_mower/lidar_archive.py`;
`docs/multi-map.md` "Limitations" section; dashboard `LiDAR` tab.

---

### Render `nav_paths` overlay on the camera

**Why:** `MapData.nav_paths` is decoded from the cloud `paths` key
(connecting paths between maps, rendered in the app as gray
polylines). The greenfield decodes them but the renderer doesn't draw
them yet.
**Done when:** `map_render` overlays `nav_paths` as a styled gray
polyline (similar to live-trail rendering); a multi-map test fixture
visually confirms the overlay aligns with the user's app screenshot.
**Status:** open (Phase 2 polish)
**Cross-refs:** `map_render.py`; `MapData.nav_paths`

---

### `edgeMowingWalkMode` — identify the app-side setting

**Why:** The cloud SETTINGS field `edgeMowingWalkMode` is exposed as
`select.<map>_edge_walk_mode` (values `walk_0` / `walk_1`), but no
toggle in the Dreame app appears to correspond to it. Curiously the
JSON key order in `SETTINGS.0` roughly matches the order of toggles in
the app's Mowing Settings screen, and `edgeMowingWalkMode` sits
between `mowingHeight` and `edgeMowingAuto` — which is where the app
shows "Mowing Direction" (the Standard / Crisscross / Chequerboard
selector). That direction selector is already wired to the
`mowingDirectionMode` field (our `Mowing Pattern` select), so
`edgeMowingWalkMode` is plausibly something different — perhaps a
hidden/A-B flag, an edge-walk strategy parameter, or a deprecated
field.
**Done when:** Physical test: run an Edge mow on the same map twice,
once with `edgeMowingWalkMode=0` and once with `=1`, and observe
whether the mower's edge-tracing behaviour differs (path shape,
direction, lap count, speed). Either confirm a behavioural delta and
characterise it, or confirm no observable delta and document the
field as cosmetic/no-op so we can decide whether to keep the entity.
**Status:** open
**Cross-refs:** `select.py` § `DreameA2PerMapEdgeMowingWalkModeSelect`;
`docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
(field values observed: entry0/map0=0, entry0/map1=0, entry1/map0=1,
entry1/map1=1 — both states known to be accepted by the cloud).

---

### Rain-stop / mid-session pause handling — session continuity across HA restarts

**Context — what's fixed already:**

1. **Boot-stale phantom** (v1.0.13a5) — `_restore_in_progress` used to
   seed `_prev_task_state=0` with `MowerState.task_state_code` still at
   default None. The first `_periodic_session_retry` 60 s after boot
   matched (prev=0, new=None) → `FINALIZE_INCOMPLETE` → 0 m² phantom.
   Fixed via the `_real_task_state_observed` latch: skip the dispatch
   until a non-None task_state arrives via MQTT. Probe-log evidence:
   2026-05-15 13:11–13:33 had 22 min of MQTT silence; a reboot in that
   window produced the 0 m²/337 min phantom for the still-paused mow.
2. **Phantom not cleaned when canonical lands** (v1.0.13a4) —
   `_prune_incomplete_for(start_ts)` now removes the placeholder when
   the cloud summary later archives.

**Still open:**

After today's boot-stale guard the post-rain resume produces a NEW
session in the archive (the prior session was already finalized as
(incomplete) before the guard was deployed, so on resume `live_map`
was clean → `begin_session()` fired). For a true continuity model:

- When the firmware shows a weather-hold sequence (`s2p2 == 70`
  followed by `task_state` returning to {[1,0]} after a delay), we
  should treat that as the SAME session, not a new one. Today the
  pre-rain segment lives at archive entry A (with its 0 m² incomplete)
  and the post-rain segment is a fresh in-progress with no link back.
- Even with the boot-stale guard, a longer outage that crosses the
  pending-OSS max-age (30 min) on a session that's truly paused
  (firmware in {[1,4]} the whole time) won't auto-finalize incorrectly
  — but won't auto-resume either.

**Done when:**
1. Identify the firmware's reliable "session continuing across pause"
   signal. Candidates: `s2p2 == 70` (weather_hold) in the recent
   notification stream; cloud_state's `mihis.count` NOT incrementing
   across the gap; `task_state` returning to {[1,0]} with the same
   `session_id` (does g2408 expose one?).
2. Coordinator boot path: when in_progress.json exists AND mower
   returns to a {[1,0]} state on first MQTT push, decide whether the
   live_map should keep its prior `started_unix` (continue) or start
   fresh (new session). Currently always starts fresh on the begin_
   session transition.
3. Update `live_map/finalize.py::decide` (or the equivalent gate in
   the state machine) to defer FINALIZE_INCOMPLETE on observed weather-
   hold notifications. Add a dwell-time / "session has been idle for N
   min with no weather indicator" guard.
4. Tests in `tests/live_map/test_finalize.py` for the rain-stop
   timeline using a captured fixture.
5. Live verification on the next rain-pause: archive shows one entry
   spanning the full session, not two separate fragments.

**Cross-refs:** `custom_components/dreame_a2_mower/live_map/finalize.py`
§ decide; `custom_components/dreame_a2_mower/mower/state_machine.py`
§ session-end transitions; `coordinator/_session.py::_run_finalize_incomplete`;
project memory `project_g2408_session_archive_quirks`;
v1.0.13a5 boot-stale guard at `coordinator/_session.py::_periodic_session_retry`.

---

### Area-mowed-based time breakdown for sensor.picked_session

**Why:** v1.0.13a2 ships a time_mowing/charging/other split for the
picked-session card derived from battery-drop intervals (mowing =
intervals where battery dropped between consecutive samples). Cleaner
signal would be the s1.4 telemetry's cumulative `area_mowed_m2`:
intervals where the area counter advanced = mower head was cutting;
intervals where it held static = transit / idle / parked. Aligns the
classification with how `protocol/wheel_bind.py` already reasons about
delta-area cross-frame (the only other place in the integration that
uses area-mowed-delta), and avoids the false-positives in the battery
heuristic (slow idle drift counts as mowing; battery-drop on a long
charge break can mis-classify).
**Done when:**
1. `LiveMapState.area_mowed_samples: list[tuple[int, float]]` field
   added with `begin_session`/`end_session` reset, mirroring
   `battery_samples`.
2. Capture in `coordinator/_mqtt_handlers.py::_on_state_update` when
   `new_state.area_mowed_m2 != self.data.area_mowed_m2` (dedup on
   no-change so transit periods produce zero rows). Throttle to one
   sample per second worst-case.
3. Persist/restore in `coordinator/_session.py`'s `_persist_in_progress`
   + `_restore_in_progress`, and inject into the archive payload via
   the existing `_inject_live_map_into_raw_dict` helper in
   `coordinator/_lidar_oss.py`.
4. `_compute_time_breakdown` in `session_card.py` extended: when
   `area_mowed_samples` is non-empty, prefer it for `time_mowing_min`
   (intervals where area advanced); battery-drop heuristic stays as
   fallback for archives without the new stream.
5. Tests: fixture with hand-rolled area_mowed_samples confirms the
   new classifier picks up advances correctly; fallback test confirms
   battery-drop path still works when the new stream is absent.
6. Optionally extend `tools/backfill_session_samples.py` to decode
   s1.4 blobs from probe logs and emit `area_mowed_samples` per
   session — the area counter is at byte[29-30] of the 33-byte s1.4
   frame, decodable via `protocol/telemetry.py::decode_s1p4`. Skip
   sessions whose probe log is gone.
7. Re-verify the long_with_recharges fixture: `mow + charge + other ≈
   wall_clock` and `time_mowing_min` is meaningfully different from
   the battery-drop result (validates the new signal is doing work).
**Status:** open — gated on the battery-drop heuristic in v1.0.13a2
landing on the dashboard and getting field-tested against more
sessions. If the user reports that the battery values look right on
most picks, this becomes "nice to have"; if the battery method shows
systematic skew, this is the fix.
**Cross-refs:** `custom_components/dreame_a2_mower/session_card.py
§ _compute_time_breakdown`; `custom_components/dreame_a2_mower/
live_map/state.py § battery_samples` (precedent shape);
`custom_components/dreame_a2_mower/protocol/wheel_bind.py § detect_wheel_bind`
(existing delta-area logic, per-frame); `tools/backfill_session_samples.py`.

---

## In-progress

_(none currently)_

---

## Blocked

### Mowing direction / Crisscross / Chequerboard pattern

**Why:** No observable property on the device's MQTT `/status/` topic carries
mowing direction or pattern. An 8-change test on 2026-05-04 produced eight
`s6p2` events all with the identical payload — the actual setting value is
absent from the outbound MQTT. Likely cloud-resident or BT-only.
**Done when:** A CFG key carrying the direction value is found via `getCFG`
brute-force (try `MOWP`, `MD`, `DIR`, `ANG`, `PAT`) OR the feature is
confirmed cloud/BT-only and documented as unsurfaceable.
**Status:** blocked-by-investigation (BT-only suspected)
**Cross-refs:** `docs/research/g2408-protocol.md §1.2` (80001 / BT channel)

---

### `ai_obstacle` blob format

**Why:** `SessionSummary.ai_obstacle` is typed `tuple[Any, ...]` because no
captured session has produced a non-empty value. Need an AI-obstacle trigger
event to capture the wire shape.
**Done when:** A session produces `ai_obstacle: [...]` in the OSS JSON;
fixture saved under `tests/protocol/fixtures/`; decoder and renderer updated.
**Status:** blocked-by-capture (need mower to detect an obstacle with AI camera)
**Procedure:** [docs/research/g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path](g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path)
**Cross-refs:** `protocol/session_summary.py`; journal topic `apk cross-walk findings`

---

### Patrol Logs — trigger and wire format

**Why:** The app's Work Logs has a "Patrol Logs" tab that is always empty on
the user's account. No way to initiate a Patrol from the current UI has been
found. Wire format and OSS schema are unknown.
**Done when:** A Patrol session is triggered, the s2p50/event_occured sequence
is captured, and the OSS JSON schema is documented.
**Status:** blocked-by-capture (no known Patrol trigger in current app)
**Procedure:** [docs/research/g2408-capture-procedures.md#4-patrol-log-trigger-investigation](g2408-capture-procedures.md#4-patrol-log-trigger-investigation)
**Cross-refs:** journal topic `s2p50 op-code catalog`; apk opcodes 107/108

---

### Firmware update flow — capture wire sequence

**Why:** Only one firmware update has occurred on the user's mower, before the
integration was running. The MQTT sequence during an update (STATE=14,
s2p53 progress, s2p57 shutdown trigger) is undocumented.
**Done when:** An update is captured; MQTT sequence documented; HA behaviour
during update (sensors, entities) verified.
**Status:** blocked-by-rare-event (wait for next firmware update notification)
**Procedure:** [docs/research/g2408-capture-procedures.md#1-firmware-update-flow](g2408-capture-procedures.md#1-firmware-update-flow)
**Cross-refs:** journal topic `s2p50 op-code catalog`; inventory `s2p2_state_14`

---

### Change PIN Code — confirm wire format

**Why:** The app has a "Change PIN Code" action. The wire format is unknown —
likely BT-only given PIN is a security-critical local secret. The integration
cannot currently read or write PIN.
**Done when:** PIN change is attempted while probe log is running; result is
either a cloud wire sequence documented in `protocol/config_s2p51.py`, or
BT-only confirmed and documented in `docs/research/g2408-protocol.md §1`.
**Status:** blocked-by-capture
**Procedure:** [docs/research/g2408-capture-procedures.md#8-change-pin-code-wire-format](g2408-capture-procedures.md#8-change-pin-code-wire-format)
**Cross-refs:** journal topic `s1p1 byte[3] bit 7 PIN-required clarification`; `docs/research/g2408-protocol.md §1`

---

### Pathway Obstacle Avoidance test — CFG.BP / CFG.PATH semantics

**Why:** Two CFG keys (`BP`, `PATH`) still have placeholder semantics.
Hypothesis: they relate to Pathway Obstacle Avoidance. No pathways are defined
on the user's map so neither field has been observed changing.
**Done when:** A test pathway is created and toggled in the app; CFG snapshot
diff identifies which key(s) change and what values mean; entities added.
**Status:** blocked-by-test (user has no pathway defined; needs deliberate setup)
**Procedure:** [docs/research/g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable](g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable)
**Cross-refs:** journal topic `s2p51 multiplexed config — disambiguation evolution`; canonical § CFG keys

---

### `MowerAction.SUPPRESS_FAULT` semantics

**Why:** The service exists in the integration but has never been live-tested.
It is unclear whether "suppress fault" means acknowledge a technical
malfunction, clear a physical-alert latch, or is a generic dismiss. Adding
a UI button without knowing semantics risks confusing users or triggering
unintended state changes.
**Done when:** A known-safe fault is triggered (e.g. lift lockout), the
SUPPRESS_FAULT action is called, and the resulting state change is observed.
Outcome: either a button entity is added with the right display conditions, or
the service is documented as power-user-only.
**Status:** blocked-by-safe-test-design (need a controlled fault scenario)
**Cross-refs:** `custom_components/dreame_a2_mower/actions.py`; journal topic `s1p1 byte[3] bit 7 PIN-required clarification`

---

## Phase 3: capture the Dreame app's write RPC — covers 28+ entities across multiple cloud surfaces

**Why:** Audit Tasks 3 and 4 (2026-05-09) + the SCHEDULE round-up probe (also 2026-05-09) revealed that **multiple cloud surfaces the integration uses for writes are cloud-cache-only or have missing setters on g2408**. The Dreame app uses a different write surface that we haven't reverse-engineered.

**SCHEDULE-specific update 2026-05-09:** ran `/tmp/probe_schedule_write.py` testing 5 candidate paths against the SCHEDULE blob. All returned `r=0` (cloud accepts) but the `v` version field never bumped — meaning the cloud is silently dropping the writes on every alternative path too. Direct MIoT `s8.{1..5}` returns 80001 (RPC tunnel closed for siid=8 on this firmware). Confirms SCHEDULE is genuinely Phase 3: the Dreame app must use either MQTT-direct publish to `/cmd/<did>/` (bypassing cloud RPC) or a different HTTP endpoint outside the routed-action / chunked-batch / MIoT-property surfaces we've enumerated.

Affected entities (all silently fail to drive the device after the v1.0.2a9 partial fix):

1. **CFG int-list keys (7 entities + sub-rows):** DND, LOW, WRP, BAT, LIT, REC, LANG. The cloud's routed-action `s2.50 m='s' t=KEY` returns `r=-3` (no setter). Direct MIoT `set_property(siid, piid, value)` returns `80001`. `r=-3` confirmed to mean "no setter at this address" — not a wire-format issue (cloud is lenient on the keys it does support, e.g. coerced `[1,4]` to `1` for CLS). See `wire-captures/cfg-write-regression-2026-05-09.md`. **NEW HYPOTHESIS (2026-05-09):** ioBroker.dreame uses **named-key payloads** for these complex CFG keys instead of wrapped lists — e.g. `WRP = {value:1, time:8, sen:0}`, `DND = {value:1, time:[1200,480]}`, `LIT = {value:1, time:[480,1200], light:[1,1,1,1], fill:0}`. We always sent `{value: <list>}` which is rejected with r=-3. Likely fix: refactor `set_cfg` to accept arbitrary `d` dict, then live-probe one key at a time. Catalog and test cases: `wire-captures/iobroker-write-catalog-2026-05-09.md`.

2. **SETTINGS-backed entities (13 entities):** All "Mowing settings page" entities — number.mowing_height / _cutter_position / _cutter_position_height / _edge_mowing_num / _obstacle_avoidance_height / _distance / _sensitivity; select.mowing_direction / _mowing_direction_mode / _edge_walk_mode; switch.edge_mowing_auto / _safe / _obstacle_avoidance / .obstacle_avoidance_enabled; switch.ai_obstacle_recognition_humans / _animals / _objects. The `setDeviceData` chunked-batch surface accepts the writes and persists them in the cloud chunked-batch dump, but the device firmware never sees the change and the Dreame app reads from a different surface (verified live 2026-05-09 — Map 2 app showed all 3 AI bits on even after cold-restart, while cloud had ai=6). See `wire-captures/settings-surface-cloud-only-2026-05-09.md`.

3. **AI_HUMAN.0 (1 entity), SCHEDULE (1 service):** Same chunked-batch surface as SETTINGS — almost certainly the same cloud-cache-only behavior. Confirm in audit Tasks 5 and 6.

The Dreame app obviously has a working device-write path: 3 weeks of s2p51 push fires show settings actually changing on the device when the user toggles in the app. **The path is not in our cloud_client repertoire and not in the legacy integration's repertoire either.**

**Probe-safety incident** during Task 3 wire-format brute-forcing: an `s2.aiid=1` call inadvertently triggered a global-mower-start action (the device ignored `m='s' t='WRP'` and treated it as a normal start command). Brute-force search of siid/aiid combinations is therefore not safe. Future probing must EITHER stay on `aiid=50` (varying only m/t/d) OR run only when the mower is docked AND the user is watching.

**Done when:** an HTTPS sniff of the Dreame app's "Save" tap on the affected pages identifies the wire format. Likely candidates:
- MQTT direct command publish to a `/cmd/<did>/` topic (the legacy Xiaomi pattern)
- A different cloud HTTP endpoint we haven't probed
- A different `method=` field (not `set_properties` or `action`)
- A new siid/aiid combination not in the integration's repertoire

A single sniff session capturing 4-5 different settings (one mowing-settings-page toggle, one DND change, one AI_HUMAN toggle, one schedule edit) will likely reveal the missing surface — they probably all use the same one.

Once captured, the integration routes the affected ~28 entities through the new path, retests end-to-end, and the audit's ✗ rows flip to ✓.

**Status:** open (deferred — needs traffic capture; substantial follow-up code work after that). NB the CFG int-list portion may be solvable without a sniff — see the named-key hypothesis above and `iobroker-write-catalog-2026-05-09.md`.
**Cross-refs:** `docs/research/wire-captures/cfg-write-regression-2026-05-09.md`; `docs/research/wire-captures/settings-surface-cloud-only-2026-05-09.md`; `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`; probe-safety incident note in the CFG file.

---

## Phase 3.5: ioBroker-derived write surfaces (independent of the app sniff)

**Why:** Investigation of `OLD/alternatives_archive_2026-05-05/ioBroker.dreame` (synced 2026-05-09, latest commit `fe0db96` v0.3.7) revealed two write surfaces our integration doesn't use, plus several action commands we don't expose. Full catalog: `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`.

**Tier 1 — CFG complex-payload formats ✓ DONE (v1.0.2a10):**
- `set_cfg` refactored to accept dict payloads; sent verbatim as `d`.
- `WRP {value, time}`, `DND {value, time:[start,end]}`, `LOW {value, time:[start,end]}` all live-verified on g2408 fw 4.3.6_0550. WRP end-to-end (HA → cloud → device → app) confirmed via 4h→6h→4h round-trip. **Important deviation from ioBroker's catalog:** the bare `{value:0}` form for "off" is rejected with r=-3 on g2408 — always send full form. Optional `sen` field omitted (not surfaced in app, not echoed in getCFG).
- Commit `c2ab186`. Switch entities & WRP-resume-hours select shipped.

**Tier 2 — PRE preferences ✗ NOT APPLICABLE TO g2408:**
- Live-probed 2026-05-09: g2408's `CFG.PRE = [0, 0]` (only 2 elements; ioBroker's PRE[2]=cutting-height, PRE[9]=edge-mowing etc. don't exist here). Round-trip write returns r=-3.
- The corresponding g2408 entities (cutting height, edge mowing) live behind the SETTINGS chunked-batch surface — same Phase 3 cloud-cache-only gap.

**Tier 3 — AutoSwitch (siid:4 piid:50) ✗ NOT APPLICABLE TO g2408:**
- Live-probed 2026-05-09: `get_properties [{siid:4, piid:50}]` returns `80001 设备可能不在线` — property doesn't exist on g2408 firmware. AutoSwitch is vacuum-side (and possibly newer mower firmware).

**Tier 4 — new actions ⚠ MOSTLY ALREADY COVERED:**
- find_robot op=9, stop, pause, dock, suppress_fault — already in our `MowerAction` enum.
- Still uncovered: lock_robot op=12 (separate from our CHILD_LOCK toggle; semantics on g2408 unverified), generate_3dmap op=10 with `d:{idx:0}` (needs new action shape), request_wifi_map siid:6 aiid:4 (different routing). All deferred — needs live probing in a docked window.

**WARNING from ioBroker commit `74467a3`:** `siid:2 aiid:3 in:[4]` was historically called "start zone mowing" but **actually triggers RETURN-TO-DOCK** on g2408. They had to remove it. Don't probe blindly.

**Status:** Tier 1 done; Tier 2/3 ruled out for g2408; Tier 4 has small remaining surface.
**Cross-ref:** `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md` (live-verification section at the end).

---

## Per-map device-info-page segmentation — research sub-devices

**Why:** Several entities are map-specific (mowing height, edge-mowing, mowing direction, AI obstacle bits, etc.) and currently appear flat under the single Dreame device on the device-info page. The HA device page has only three fixed sections — Controls / Configuration / Diagnostic — so there's no native way to label a section "Map 1" vs "Map 2" within a single device. A custom dashboard can group them, but the device-info page itself can't.

**Two paths to evaluate before committing:**

1. **Naming convention** — prefix entity `name=` with the map label, e.g. `"Map 1: Mowing height"`, `"Map 2: Mowing height"`. Lightweight, works today, no breaking changes. Drawback: the prefix shows up in voice / automation contexts where it reads awkwardly.

2. **Sub-devices** — HA 2024.10+ introduced device hierarchy via `via_device` and per-map child `DeviceInfo` (identifiers like `(DOMAIN, f"{entry_id}_map_{map_id}")`). Per-map entities live on the child device; each map becomes its own row in the devices list, with its own device-info page. Cleaner long-term but a sizable refactor and potentially affects entity unique_ids if not done carefully (could create entity orphans — see the `feedback_entity_rename_orphan.md` memory).

**Research before deciding:**

- Survey how other multi-map / multi-zone HA integrations handle this. Examples to look at: Roborock (multi-floor maps), Tasshack/Dreame (legacy fork — does the old integration use sub-devices?), Husqvarna Automower, Tesla (vehicle / charging), Mealie (recipes per shopping list)…
- Specifically check: do they actually create sub-devices, or do they prefix names? What are the migration pain points if they ever moved from one to the other?
- Check HA core docs / dev guidelines for whether sub-devices are recommended for "logical grouping inside one physical device" or only for "this physical device contains other physical devices."
- Confirm whether a sub-device's entities can be referenced from the parent's dashboard / lovelace card without extra plumbing.

**If sub-devices look viable**, plan the entity-id migration carefully — changing a unique_id pattern strands the old entity in the registry as "unavailable" (we hit this on the cloud_state architecture rename and had to remove orphans manually via WS `config/entity_registry/remove`).

**Status:** open (research-only; no code change yet).
**Cross-ref:** `feedback_entity_rename_orphan.md` (auto-memory), `docs/research/entity-validation-matrix.md` per-entity rows (label which entities are map-specific).

---

## Determine whether HA writes drive the device, or only update the cloud cache

**Why:** A whole class of g2408 settings — AI Obstacle Recognition
(humans/animals/objects), Mowing Direction, Edge Mowing Auto/Safe/
Obstacle Avoidance, LiDAR Obstacle Recognition, Obstacle Avoidance
Distance/Height/Sensitivity, Mowing Height, Cutter Position,
Mowing Pattern, Edge Walk Mode, Edge Passes, Start from Stop Point,
Pathway Obstacle Avoidance, EdgeMaster — are all readable from the
cloud and propagate end-to-end across app instances (verified
2026-05-09 via two-device test: toggle in app A, cold-start app B
on a different device → app B reflects the change without any BT
involvement). The full list and per-entity status lives in
`docs/research/entity-sync-matrix.md`.

The integration writes via `setDeviceData`. The cloud accepts the
write (CFG.VER bumps, SETTINGS reflects, refresh-button confirms).
What's NOT yet established is whether the device *firmware* applies
the HA-initiated write — i.e. whether the mower's actual behaviour
changes. Earlier we suspected "no" because the original Dreame app
session kept showing the pre-HA-write value, but that may simply be
the app's settings-screen UI cache (the same cache that hides
app-to-app changes until forced refresh).

**Right test (not yet performed):** HA writes X to a setting; then
cold-start a Dreame app instance that has never seen the device's
local cache. If it shows X, HA writes propagate fully and the
"doesn't apply" theory was a UI-cache illusion. If it shows the
pre-HA-write value, HA's `setDeviceData` only updated the cloud
cache and the device firmware uses a different write surface.

If HA writes are confirmed insufficient, the next step is HTTPS-
sniffing the Dreame app's "Save" tap to capture the actual RPC the
app uses (likely a routed-action `setX` target we haven't enumerated,
since direct MIoT `set_property` returns 80001 for most siids).

**Done when:** the test above is performed live and either:
1. HA writes confirmed end-to-end propagating → close as "no action,
   the apparent gap was UI cache"; OR
2. HA writes confirmed insufficient → app's actual write RPC is
   captured, wired into a `coordinator.write_*` method, and a
   follow-up live test confirms full propagation.
**Status:** open (deferred — needs user-side cold-start test, then
possibly a traffic capture).
**Cross-refs:** `docs/research/entity-sync-matrix.md` (full list of
affected entities); `docs/research/g2408-research-journal.md` 2026-05-09
entry "BT-only classification retracted".

---

## Deferred — write-path audit findings (2026-05-09)

Surfaced during the post-fix audit for additional structural
read/write mismatches like the SETTINGS dual-entry / SCHEDULE-mode
bugs (commits `b25b5ac` / `4868016` / `b89c574`). No other
dual-source storage shapes were found. Two encoder-side
findings still open; both are write paths whose hardcoded shape
doesn't match what the firmware actually stores.

### PRE encoder inflates `list(2)` to `list(10)` with hardcoded defaults

**Why:** Same class as the SCHEDULE `mode` bug. Live g2408 cloud has
`PRE = [0, 0]` (verified 2026-05-09 via `/tmp/probe_cfg_arrays.py`),
but `protocol/cfg_action.py:166` `set_pre()` rejects arrays with
`< 10` elements and `select.py:181` `_build_pre_efficiency` always
emits 10 elements, padding indices 2..9 with
`_PRE_PAD_DEFAULTS = [60, 0, 0, 0, 0, 0, 0, 0]`. First time the user
picks "Mowing Efficiency" in HA, the cloud's `[0, 0]` becomes
`[0, mode, 60, 0, 0, 0, 0, 0, 0, 0]` — the integration is
*inflating* a field that firmware kept short. Source comment claims
"may be trimmed server-side" but this is unverified, and even if
it is trimmed, the integration is sending data that doesn't reflect
firmware state.
**Done when:** `set_pre()` accepts the same length the firmware
stores (relax the 10-element minimum); `_build_pre_efficiency`
reads the current PRE list from `cs.cfg["PRE"]` and mutates only
the index it owns; live test on g2408 confirms PRE round-trips at
length 2 after a "Mowing Efficiency" toggle.
**Status:** open (deferred — schedule + AI work first)
**Cross-refs:** `custom_components/dreame_a2_mower/protocol/cfg_action.py:162`;
`custom_components/dreame_a2_mower/select.py:175-200`; live probe
`/tmp/probe_cfg_arrays.py`.

### BAT[2] hardcoded `1` in build helpers

**Why:** Three build helpers — `_build_bat_auto_recharge` (number.py),
`_build_bat_resume` (number.py), `_build_bat_custom_charging`
(switch.py:171) — all hardcode `BAT[2] = 1` instead of reading it
from MowerState. The decoder explicitly drops `BAT[2]` with
`# unknown_flag (consistently 1; semantic TBD)`. Live data confirms
`BAT[2] = 1` today (2026-05-09), so writes are correct now, but the
"consistently 1" assumption is brittle — if firmware ever stores
something else there, every BAT-related write clobbers it.
**Done when:** `bat_unknown_flag` is added to MowerState, populated
from `bat_raw[2]` in the CFG decoder, and the three build helpers
pass `int(state.bat_unknown_flag or 1)` instead of the literal `1`.
**Status:** open (deferred — defensive cleanup, low priority)
**Cross-refs:** `coordinator/_refreshers.py § _refresh_locn`;
`custom_components/dreame_a2_mower/switch.py:158-181`;
`custom_components/dreame_a2_mower/number.py:80-110`.

---

## Deferred from Task 17 (cloud-discovery integration)

### Legacy `_refresh_*` method consolidation

**Why:** `_refresh_cfg`, `_refresh_mihis`, `_refresh_dev`, `_refresh_net`,
`_poll_slow_properties` remain in place alongside `_refresh_cloud_state`.
They run on their own schedules and are still authoritative for some fields.
Task 17 dropped the three MIHIS-duplicate archive-seed paths
(`mowing_count`, `total_mowing_time_min`, `total_mowed_area_m2`) since
`_apply_cloud_state_to_mower_state` now covers them at startup, but a
full audit of the legacy refresh methods was deferred.
**Done when:** Each legacy method is walked:
1. Identify whether everything it sets is now sourced from `cloud_state`
   via `_apply_cloud_state_to_mower_state`.
2. For methods that are fully covered, drop them and their schedules.
3. For methods that set fields not yet in cloud_state, expand
   `_apply_cloud_state_to_mower_state` to cover them, then drop the legacy method.
4. Verify no entity contract is broken (run integration suite).
**Status:** open (deferred — audit needed before any removal)
**Cross-refs:** `coordinator.py` `_refresh_cfg` / `_refresh_mihis` /
`_refresh_dev` / `_refresh_net` / `_poll_slow_properties`;
`coordinator.py` `_apply_cloud_state_to_mower_state`
