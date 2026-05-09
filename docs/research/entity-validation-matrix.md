# Entity validation matrix (g2408)

Authoritative live-verified inventory of every HA entity, every received MQTT
slot, and every cloud endpoint the integration uses. Replaces the retired
[`entity-sync-matrix.md`](entity-sync-matrix.md).

**Status:** **First-pass skeleton — every row is `⚠ hypothesis (first pass 2026-05-09)`. No row has been live-verified yet.** The second pass (Tasks 2-9 of the plan) will replace `⚠` with `✓ live <date>` cell-by-cell.

**Spec:** `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md` (commit `b17bc6a`)
**Plan:** `docs/superpowers/plans/2026-05-09-protocol-validation-audit.md` (commit `4c0646d`)

## Evidence tiers

- `✓ live <date> / fw <ver> / int <ver>` — verified by a live test within the audit window. The ONLY tier that counts as evidence.
- `⚠ hypothesis from <source>` — from code, docs, git, or APK reference. Drives test design; doesn't replace the test.
- `✗ live <date>` — actively disproved by a live test.
- `? unknown` — not yet investigated.

There is no tier for "code looks right" / "git history shows it once worked." Those remain `⚠` until tested live.

## Per-entity row format

Each entity is one block. Fields:

- **Read** — sources in priority order (live first, polled fallback). Each source is `MQTT s<N>p<M>[<idx>]`, `cloud SETTINGS.<path>`, `cloud CFG.<key>`, `routed-action g.<TARGET>.<path>`, or `derived`.
- **Latency** — observed worst case to surface a value change.
- **Cold-start** — which source to prefer at integration startup (typically the cloud snapshot).
- **Sanity-check** — what to cross-check against during live operation.
- **Write** — current code path (exact RPC + payload). If different from pre-rewrite (commit `3413170` and earlier), both shown.
- **Outcome** — `✓ end-to-end / ✗ cloud-accept-no-device-apply / ? untested / n/a`.
- **Caveats** — edge cases, dependencies, ambiguous wire shapes.
- **Recipe** — how to re-verify (test pattern from spec methodology: T0 git-archeology, T1 cloud-snap, T2 mqtt-probe, T3 app-save, T4 HA-write end-to-end, T5 two-device, T6 read-only liveness).
- **Verified** — `<date> / fw / int / spec-commit` stamp.

When sample wire captures exceed ~10 lines they spill into `docs/research/wire-captures/<feature>-<date>.md`.

---

## Section A — `lawn_mower` (1 entity)

### `lawn_mower.dreame_a2_mower` — Lawn mower
- **Read**: live MQTT `s2p1` (state enum) + derived from `MowerState`
- **Latency**: ⚠ instant via MQTT
- **Cold-start**: cloud `routed-action g.MISTA` (currently 80001 on g2408 — fallback to last-known MQTT state)
- **Sanity-check**: cloud poll @2min via `_refresh_cloud_state`
- **Write**: `coordinator.dispatch_action(MowerAction.START_MOWING / PAUSE / STOP / DOCK) → routed-action s2.50 m='a' o=<op>`
- **Outcome**: ⚠ untested in this audit (op codes are believed to drive device per existing live experience but not tested under this rigour)
- **Caveats**: action routing dispatches different opcodes for all-areas / edge / zone / spot mow based on `state.action_mode` and `active_selection_*`
- **Recipe**: T6 (run a real session, observe state transitions) + T0 git-archeology of `dispatch_action`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section B — `switch` (34 entities)

### `switch.dreame_a2_mower_child_lock` — Child lock
- **Read**: live `s2p51 ambiguous-toggle` (5-member set) → cloud `CFG.CLS` @10min
- **Latency**: ⚠ ~5s expected
- **Cold-start**: cloud `CFG.CLS` via `fetch_cfg`
- **Sanity-check**: cloud `CFG.CLS` poll
- **Write**: `coordinator.write_setting("CLS", value) → routed-action s2.50 s.CLS d=0|1`
- **Outcome**: ⚠ untested
- **Caveats**: s2p51 wire shape `{value: 0|1}` is ambiguous between CLS / FDP / STUN / AOP / PROT — disambiguates via getCFG diff
- **Recipe**: T3 (app toggle, expect s2p51 fire) + T4 (HA toggle, cold-start app)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_dnd` — Do not disturb
- **Read**: live `s2p51 LOW_SPEED_NIGHT_or_ANTI_THEFT_or_DND list[3]` (shape-discriminated by value range) → cloud `CFG.DND` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.DND`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("DND", [enabled, start_min, end_min]) → routed-action s2.50 s.DND`
- **Outcome**: ⚠ untested
- **Caveats**: list[3] shape collides with LOW (low-speed-night) and ATA (anti-theft) — discriminated by element values: minutes (0-1440) → LOW/DND, bools → ATA
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_rain_protection` — Rain protection
- **Read**: live `s2p51 RAIN_PROTECTION list[2]` → cloud `CFG.WRP` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.WRP`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("WRP", [enabled, resume_hours]) → routed-action s2.50 s.WRP`
- **Outcome**: ⚠ untested
- **Caveats**: shares wire with `select.rain_protection_resume_hours` (writes the same WRP list, different index — last writer wins)
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_low_speed_at_night` — Low speed at night
- **Read**: live `s2p51 LOW list[3]` → cloud `CFG.LOW` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.LOW`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("LOW", [enabled, start_min, end_min]) → routed-action s2.50 s.LOW`
- **Outcome**: ⚠ untested
- **Caveats**: list[3] shape ambiguity (see DND)
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_custom_charging_period` — Custom charging period
- **Read**: live `s2p51 CHARGING list[6]` → cloud `CFG.BAT` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.BAT`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("BAT", [recharge_pct, resume_pct, 1, custom_charging, start_min, end_min]) → routed-action s2.50 s.BAT`
- **Outcome**: ⚠ untested
- **Caveats**: BAT[2] hardcoded `1` (assumed-constant flag, see TODO entry); shares wire with number.auto_recharge_battery_pct + number.resume_battery_pct + time.charging_start/end
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_anti_theft_lift_alarm` / `_offmap_alarm` / `_realtime_location` — Anti-theft (3 switches sharing CFG.ATA)
- **Read**: live `s2p51 ANTI_THEFT list[3]` → cloud `CFG.ATA` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.ATA`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("ATA", [lift, offmap, realtime]) → routed-action s2.50 s.ATA` (each switch overrides its index)
- **Outcome**: ⚠ untested
- **Caveats**: 3 switches write to same ATA list — last-writer-wins if toggled simultaneously; shape ambiguity with DND/LOW disambiguated by all-elements-bool
- **Recipe**: T3 + T4 per switch
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_frost_protection` — Frost protection
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.FDP` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.FDP`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("FDP", value) → routed-action s2.50 s.FDP d=0|1`
- **Outcome**: ⚠ untested
- **Caveats**: s2p51 ambiguous-toggle (CLS/FDP/STUN/AOP/PROT)
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_auto_recharge_standby` — Auto recharge after extended standby
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.STUN` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.STUN`
- **Write**: `coordinator.write_setting("STUN", value) → routed-action s2.50 s.STUN d=0|1`
- **Outcome**: ⚠ untested
- **Caveats**: ambiguous-toggle wire; behaviour observed to fire `s2p2=71 + s2p1=5` after 57 min idle outside dock
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_ai_obstacle_photos` — AI obstacle photos
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.AOP` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.AOP`
- **Write**: `coordinator.write_setting("AOP", value) → routed-action s2.50 s.AOP d=0|1`
- **Outcome**: ⚠ untested
- **Caveats**: NOT to be confused with `switch.ai_human_detection` (which writes AI_HUMAN.0 chunked-batch); AOP controls photo capture for obstacles, AI_HUMAN.0 controls capture-photos-of-AI-detected-obstacles
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_msg_alert_anomaly` / `_error` / `_task` / `_consumables` — Notification preferences (4 switches sharing CFG.MSG_ALERT)
- **Read**: live `s2p51 AMBIGUOUS_4LIST list[4]` → cloud `CFG.MSG_ALERT` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.MSG_ALERT`
- **Write**: `coordinator.write_setting("MSG_ALERT", [anomaly, error, task, consumables]) → routed-action s2.50 s.MSG_ALERT` (each switch overrides its index)
- **Outcome**: ⚠ untested
- **Caveats**: AMBIGUOUS_4LIST wire collides with VOICE — disambiguated only via `getCFG` diff (the integration has no `cfg_keys_raw _last_diff` sensor today; ambiguity may currently be lost)
- **Recipe**: T3 + T4 per switch
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_voice_regular_notification` / `_work_status` / `_special_status` / `_error_status` — Voice prompt modes (4 switches sharing CFG.VOICE)
- **Read**: live `s2p51 AMBIGUOUS_4LIST` → cloud `CFG.VOICE` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.VOICE`
- **Write**: `coordinator.write_setting("VOICE", [regular, work, special, error]) → routed-action s2.50 s.VOICE`
- **Outcome**: ⚠ untested
- **Caveats**: same ambiguous-4-bool wire as MSG_ALERT
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_led_period` / `_in_standby` / `_in_working` / `_in_charging` / `_in_error` — LED states (5 switches sharing CFG.LIT, READ-ONLY)
- **Read**: live `s2p51 LED_PERIOD list[8]` → cloud `CFG.LIT` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.LIT`
- **Write**: ✗ no write path — LIT[1, 2, 7] not stored in MowerState; full-list reconstruction unsafe → marked read-only
- **Outcome**: n/a
- **Caveats**: LIT[7] = unknown trailing toggle; if all 8 indices are decoded later, the switches can become writable
- **Recipe**: T3 (app toggle, expect s2p51 fire); no T4 since no write
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_human_presence_alert` — Human presence alert (READ-ONLY)
- **Read**: live `s2p51 HUMAN_PRESENCE_ALERT list[9]` → cloud `CFG.REC` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.REC`
- **Write**: ✗ no write path — REC[2..8] not decoded into MowerState
- **Outcome**: n/a
- **Caveats**: REC[2..8] hold standby / mowing / recharge / patrol / alert / photo_consent / push_min — settable once decoded
- **Recipe**: T3 only
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_edge_mowing_auto` — Automatic edge mowing
- **Read**: cloud `SETTINGS.entry0.<active_map_id>.edgeMowingAuto` @2min poll
- **Latency**: ⚠ ≤2 min via cloud poll (no MQTT push observed for this field)
- **Cold-start**: cloud SETTINGS @ `_refresh_cloud_state`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_settings(map_id, "edgeMowingAuto", int) → setDeviceData (chunked SETTINGS.0..N + .info)` — writes BOTH dual-level entries
- **Pre-rewrite path**: per docs, used to be a routed-action `setX` target — exact target unknown; rewrite (commit `3413170`) replaced with chunked-batch
- **Outcome**: ✗ HA-write doesn't drive device (likely — based on user report; not yet rigorously verified)
- **Caveats**: per-active-map setting; user report indicates HA writes update cloud SETTINGS but app keeps showing old value, suggesting device firmware doesn't apply
- **Recipe**: T0 (git diff pre-`3413170` to find old write path) + T3 + T4 (cold-start fresh app to verify)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_edge_mowing_safe` — Safe edge mowing
- **Read**: cloud `SETTINGS.entry0.<map>.edgeMowingSafe` @2min poll
- **Write**: `coordinator.write_settings(map_id, "edgeMowingSafe", int) → setDeviceData (SETTINGS chunked)`
- **Pre-rewrite**: same as edge_mowing_auto
- **Outcome**: ✗ likely — same class
- **Caveats**: same as edge_mowing_auto
- **Recipe**: T0 + T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_edge_mowing_obstacle_avoidance` — Obstacle Avoidance on Edges
- **Read**: cloud `SETTINGS.entry0.<map>.edgeMowingObstacleAvoidance`
- **Write**: same as siblings
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_obstacle_avoidance_enabled` — LiDAR obstacle recognition
- **Read**: cloud `SETTINGS.entry0.<map>.obstacleAvoidanceEnabled`
- **Write**: `coordinator.write_settings(..., "obstacleAvoidanceEnabled", int) → setDeviceData`
- **Outcome**: ✗ likely
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_ai_human_detection` — Capture photos AI obstacles
- **Read**: cloud `AI_HUMAN.0` (chunked-batch single key, JSON bool string `"true"`/`"false"`) @2min poll
- **Latency**: ⚠ ≤2 min (no known MQTT push for this key)
- **Cold-start**: cloud `AI_HUMAN.0`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_ai_human_enabled(bool) → setDeviceData {"AI_HUMAN.0": '"true"'|'"false"'}`
- **Pre-rewrite**: was attempted via `set_property(s4, p22)` but returned 80001 — chunked-batch path was the unblock
- **Outcome**: ⚠ untested live in this audit
- **Caveats**: distinct from `switch.ai_obstacle_photos` (CFG.AOP) — different setting in app
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_ai_obstacle_recognition_humans` — AI Obstacle Recognition: Humans (bit 0)
- **Read**: cloud `SETTINGS.entry0.<map>.obstacleAvoidanceAi & 1` (bitmask) — also reflected in `pre_*` MowerState fields, but no live MQTT slot for the AI bit field
- **Latency**: ⚠ ≤2 min via cloud poll
- **Cold-start**: cloud SETTINGS
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_settings(map_id, "obstacleAvoidanceAi", new_int_with_bit_set) → setDeviceData`
- **Pre-rewrite**: per docs, used to be `set_property(s4, p22)` w/ `{"human_detect_switch": bool}` — returned 80001; rewrite uses chunked-batch
- **Outcome**: ✗ HA-write probably doesn't drive device (user report 2026-05-09 — needs cold-start app verify to confirm)
- **Caveats**: bit-switch over single int field; toggling mutates the whole int via `_AiRecognitionBitSwitch._toggle`
- **Recipe**: T3 + T4 + cold-start app
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_ai_obstacle_recognition_animals` — AI Obstacle Recognition: Animals (bit 1)
- (same as humans, bit 1)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `switch.dreame_a2_mower_ai_obstacle_recognition_objects` — AI Obstacle Recognition: Objects (bit 2)
- (same as humans, bit 2)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section C — `select` (13 entities)

### `select.dreame_a2_mower_action_mode` — Action mode picker (LOCAL ONLY)
- **Read**: `MowerState.action_mode` — RestoreEntity persisted across HA restarts
- **Mechanism**: HA local state, not from cloud or MQTT
- **Cold-start**: RestoreEntity loads last-saved value
- **Sanity-check**: n/a
- **Write**: HA-local — sets `MowerState.action_mode`; affects which opcode `start_mowing` uses (all_areas / edge / zone / spot)
- **Outcome**: ✓ self-evident — local state machine, no cloud round-trip
- **Caveats**: paired with select.zone, select.spot, select.edge for the actual targets
- **Recipe**: HA UI test only
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_mowing_efficiency` — Mowing efficiency
- **Read**: live MQTT `s6p2[1]` → cloud `CFG.PRE[1]` @10min
- **Latency**: ⚠ instant via s6p2 (single-element change fires the frame)
- **Cold-start**: cloud `CFG.PRE`
- **Sanity-check**: cloud poll cross-check
- **Write**: `coordinator.write_setting("PRE", [zone_id, mode, height_mm, *PAD_DEFAULTS]) → routed-action s2.50 s.PRE` — pads list(2) → list(10) with hardcoded defaults
- **Pre-rewrite**: same path
- **Outcome**: ⚠ untested — TODO flagged the inflation as a potential clobber
- **Caveats**: live PRE on g2408 is `[0, 0]` (length 2); the 10-element padding hardcodes height=60mm and indices 3..9 = 0 — could clobber if firmware later stores values there
- **Recipe**: T3 + T4 (Standard ↔ Efficient flip; watch s6p2[1] flip)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_navigation_path` — Navigation path
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.PROT` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.PROT`
- **Write**: `coordinator.write_setting("PROT", 0|1) → routed-action s2.50 s.PROT`
- **Outcome**: ⚠ untested
- **Caveats**: PROT mapping `{0: direct, 1: smart}`; ambiguous-toggle wire
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_rain_protection_resume_hours` — Rain protection resume hours
- **Read**: live `s2p51 RAIN_PROTECTION list[2]` → cloud `CFG.WRP[1]`
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.WRP`
- **Write**: `coordinator.write_setting("WRP", [enabled, resume_hours]) → routed-action s2.50 s.WRP` (overrides index [1])
- **Outcome**: ⚠ untested
- **Caveats**: shares wire with switch.rain_protection — last writer wins
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_language` — Language (READ-ONLY)
- **Read**: live `s2p51 LANGUAGE {text, voice}` → cloud `CFG.LANG[2]`
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.LANG`
- **Write**: ✗ no write path — language pack indices are device-specific; no confirmed write target for g2408
- **Caveats**: surfaces `text=N,voice=M` string
- **Recipe**: T3 only (app changes language, observe push)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_work_log` — Work log session picker
- **Read**: derived from `coordinator.session_archive.list_sessions()` — local archive
- **Mechanism**: HA local state
- **Cold-start**: archive loads from disk
- **Write**: HA-local — picking a session calls `coordinator.render_work_log_session(md5)` which renders the path on the work-log camera
- **Outcome**: ✓ self-evident
- **Caveats**: in-progress sessions filtered out; capped at 50 most recent
- **Recipe**: HA UI test
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_zone` — Zone target picker (LOCAL)
- **Read**: cloud `MAP.entry<active_map_id>.mowingAreas` (zones list) + `MowerState.active_selection_zones`
- **Mechanism**: HA local picker — no cloud write on selection
- **Cold-start**: from cached map
- **Write**: HA-local — sets `MowerState.active_selection_zones`; consumed by `start_mowing` button
- **Outcome**: ✓ self-evident
- **Caveats**: auto-commits first entry if none selected (so Start always mows something)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_spot` — Spot target picker (LOCAL)
- (same pattern as zone)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_edge` — Edge contour picker (LOCAL)
- **Read**: cloud MAP contours; default = all outer-perimeter `[N, 0]` contours
- **Write**: HA-local — sets `MowerState.active_selection_edge_contours`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_active_map` — Active map selector
- **Read**: cloud `MAPL` (multi-map list, row[1] == 1 marks active) via routed-action `g.MAPL`
- **Latency**: ⚠ refreshes via s1p50 ping (sub-second) + 60s `_refresh_mapl` timer
- **Cold-start**: cloud MAPL fetch
- **Sanity-check**: 60s MAPL repoll
- **Write**: `coordinator.dispatch_action(SET_ACTIVE_MAP, op:200) → routed-action s2.50 m='a' o=200 d={mapId}`
- **Outcome**: ⚠ untested in this audit (op:200 widely believed working — used for multi-map support PR)
- **Caveats**: optimistic UI during write-in-flight; MAPL repoll confirms within seconds via s1p50 trigger
- **Recipe**: T6 (switch maps in HA, observe MAPL row[1] flip in cloud snapshot)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_mowing_direction` — Mowing direction (0° / 90° / 180° / 270°)
- **Read**: cloud `SETTINGS.entry0.<map>.mowingDirection` @2min poll
- **Latency**: ⚠ ≤2 min via cloud poll
- **Cold-start**: cloud SETTINGS
- **Write**: `coordinator.write_settings(map_id, "mowingDirection", int) → setDeviceData (SETTINGS chunked)`
- **Pre-rewrite**: unknown direct path; rewrite uses chunked-batch
- **Outcome**: ✗ likely (same class as edge mowing toggles)
- **Caveats**: per-active-map; no MQTT push for this field
- **Recipe**: T0 + T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_mowing_direction_mode` — Mowing pattern (Striped / Crisscross / Chequerboard)
- **Read**: cloud `SETTINGS.entry0.<map>.mowingDirectionMode`
- **Write**: `coordinator.write_settings(..., "mowingDirectionMode", int) → setDeviceData`
- **Outcome**: ✗ likely
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `select.dreame_a2_mower_edge_walk_mode` — Edge walk mode (walk_0 / walk_1)
- **Read**: cloud `SETTINGS.entry0.<map>.edgeMowingWalkMode`
- **Write**: `coordinator.write_settings(..., "edgeMowingWalkMode", int) → setDeviceData`
- **Outcome**: ✗ likely
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section D — `number` (11 entities)

### `number.dreame_a2_mower_volume` — Voice volume
- **Read**: live `s2p51` shape (TBD which) → cloud `CFG.VOL` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.VOL`
- **Write**: `coordinator.write_setting("VOL", int 0..100) → routed-action s2.50 s.VOL`
- **Outcome**: ⚠ untested
- **Caveats**: percentage 0-100
- **Recipe**: T3 + T4
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_auto_recharge_battery_pct` — Auto-recharge battery %
- **Read**: live `s2p51 CHARGING` → cloud `CFG.BAT[0]`
- **Write**: `coordinator.write_setting("BAT", [pct, ...]) → routed-action s2.50 s.BAT` (BAT[0] override)
- **Caveats**: BAT[2] hardcoded `1` (TODO entry); shares list with custom_charging_period and resume_battery_pct
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_resume_battery_pct` — Resume battery %
- **Read**: live `s2p51 CHARGING` → cloud `CFG.BAT[1]`
- **Write**: `coordinator.write_setting("BAT", [..., pct, ...]) → routed-action s2.50 s.BAT` (BAT[1] override)
- **Caveats**: same as auto_recharge_battery_pct
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_human_presence_alert_sensitivity` — Human presence alert sensitivity (READ-ONLY)
- **Read**: live `s2p51 HUMAN_PRESENCE_ALERT[1]` → cloud `CFG.REC[1]`
- **Write**: ✗ no write path — REC[2..8] not decoded
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_mowing_height` — Mowing height (cm)
- **Read** (priority): live MQTT `s6p2[0]` (in mm, divided by 10 to cm via property_mapping multi_field) → cloud `SETTINGS.entry0.<map>.mowingHeight` @2min poll
- **Latency**: ✓ instant via s6p2 (mowing-height changes fire s6p2[0]; v1.0.2a7 wired both `pre_mowing_height_mm` and `settings_mowing_height` to same s6p2 push)
- **Cold-start**: cloud SETTINGS
- **Sanity-check**: cloud SETTINGS poll
- **Write**: `coordinator.write_settings(map_id, "mowingHeight", int_cm) → setDeviceData`
- **Pre-rewrite**: unknown — the s6p2[0] surface was always read-only in property_mapping; write uses chunked-batch
- **Outcome**: ⚠ untested live for write; read path is well-supported (s6p2 fires on app changes)
- **Caveats**: the same value lives in two MowerState fields (`pre_mowing_height_mm` mm, `settings_mowing_height` cm) — both updated by s6p2 multi_field; mm version exists for the PRE-write encoder
- **Recipe**: T3 (app slider, expect s6p2[0] flip) + T4 (HA slider)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09); s6p2 read confirmed today via probe log

### `number.dreame_a2_mower_cutter_position` — Cutter position
- **Read**: cloud `SETTINGS.entry0.<map>.cutterPosition`
- **Write**: `coordinator.write_settings(..., "cutterPosition", int) → setDeviceData`
- **Outcome**: ✗ likely (SETTINGS-class)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_cutter_position_height` — Cutter height
- **Read**: cloud `SETTINGS.entry0.<map>.cutterPositionHeight`
- **Write**: `coordinator.write_settings(..., "cutterPositionHeight", int) → setDeviceData`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_edge_mowing_num` — Edge passes
- **Read**: cloud `SETTINGS.entry0.<map>.edgeMowingNum`
- **Write**: `coordinator.write_settings(..., "edgeMowingNum", int) → setDeviceData`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_obstacle_avoidance_height` — Obstacle avoidance height
- **Read**: cloud `SETTINGS.entry0.<map>.obstacleAvoidanceHeight`
- **Write**: `coordinator.write_settings(..., "obstacleAvoidanceHeight", int) → setDeviceData`
- **Outcome**: ⚠ — user reported HA writes accepted but the original app instance keeps showing pre-write value (UI-cache or device-no-apply, unverified)
- **Caveats**: 5/10/15/20 cm (per app); recently observed propagating ~5 min after app save (cloud-side delay, not poll-cadence)
- **Recipe**: T3 + T4 + cold-start app verification
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_obstacle_avoidance_distance` — Obstacle avoidance distance
- **Read**: cloud `SETTINGS.entry0.<map>.obstacleAvoidanceDistance`
- **Write**: `coordinator.write_settings(..., "obstacleAvoidanceDistance", int) → setDeviceData`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `number.dreame_a2_mower_obstacle_avoidance_sensitivity` — Obstacle avoidance sensitivity
- **Read**: cloud `SETTINGS.entry0.<map>.obstacleAvoidanceSensitivity`
- **Write**: `coordinator.write_settings(..., "obstacleAvoidanceSensitivity", int) → setDeviceData`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section E — `sensor` (42 entities)

### `sensor.dreame_a2_mower_battery` — Battery
- **Read**: live MQTT `s3p1`
- **Latency**: instant via MQTT
- **Cold-start**: last-known MQTT value (or 0 if never received)
- **Write**: n/a (read-only)
- **Recipe**: T6 — observe during charging cycle
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_charging_status` — Charging status (enum)
- **Read**: live MQTT `s3p2` (NOT_CHARGING/CHARGING/CHARGED)
- **Recipe**: T6 — observe at session start/end and dock arrive
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_position_x_m` / `_y_m` / `_north_m` / `_east_m` — Position (4 entities)
- **Read**: live MQTT `s1p4` telemetry blob — `MowingTelemetry` decoder extracts x_mm, y_mm; north/east derived via station-bearing rotation
- **Latency**: instant (every ~5 s during mowing)
- **Cold-start**: None until first s1p4 received
- **Recipe**: T6 — capture during a session
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_area_mowed_m2` / `_session_distance_m` / `_mowing_phase` — Session telemetry (3 entities)
- **Read**: live MQTT `s1p4` blob — area, distance, phase fields
- **Latency**: ~5 s during mowing
- **Caveats**: resets at session start; phase advances monotonically
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_error_code` / `_error_description` — Error (2 entities)
- **Read**: live MQTT `s2p2` (int) for error_code; error_description = `_describe_error_or_none(error_code)` lookup
- **Latency**: instant
- **Caveats**: sticky — does not clear on device until app/PIN clears
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_task_state_code` — Task state code (raw)
- **Read**: live MQTT `s2p56.status[0][1]` (sub-state) — see `property_mapping.py:80-91` for shape decoding
- **Latency**: instant
- **Caveats**: 0 = running, 4 = paused-pending-resume; 0→4→0 = recharge round-trip; empty status = no active session
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_slam_task_label` — SLAM task label
- **Read**: live MQTT `s2p65` (string)
- **Latency**: instant on transition
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_total_lawn_area_m2` — Target area
- **Read**: live MQTT `s2p66[0]` (m²) — `[area_m², ?]` shape, only [0] consumed
- **Latency**: instant on map save
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_wifi_rssi_dbm` / `_wifi_ssid` / `_wifi_ip` — WiFi (3 entities)
- **Read**: cloud `routed-action g.NET` @10min poll for ssid/ip; live MQTT `s6p3[1]` for rssi
- **Latency**: rssi instant via MQTT; ssid/ip on poll
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_dock_x_mm` / `_dock_y_mm` / `_dock_yaw` — Dock pose (3 entities)
- **Read**: cloud `routed-action g.DOCK` @60s poll
- **Latency**: ≤60s
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_blades_life_pct` / `_cleaning_brush_life_pct` / `_robot_maintenance_life_pct` — Consumable life (3 entities)
- **Read**: live `s2p51 CONSUMABLES list[4]` push → cloud `CFG.CMS` @10min poll
- **Latency**: instant via s2p51 (when consumable is replaced)
- **Caveats**: -1 in any slot = "no timer applies" (Link Module on g2408)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_total_mowing_time_min` / `_total_mowed_area_m2` / `_mowing_count` / `_first_mowing_date` — MIHIS lifetime totals (4 entities)
- **Read**: cloud `routed-action g.MIHIS` @10min poll
- **Latency**: ≤10 min
- **Cold-start**: cloud MIHIS fetch
- **Caveats**: first_mowing_date is the firmware-hardcoded sentinel `1704038400` (2023-12-31 UTC) — not per-unit
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_active_selection` — Active selection (derived)
- **Read**: derived from `MowerState.action_mode` + `active_selection_*`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_last_settings_change_unix` — Last settings change
- **Read**: derived — set whenever any settings field updates in MowerState
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_language_text_idx` / `_voice_idx` — Language indices (2 entities)
- **Read**: cloud `CFG.LANG` @10min poll; also live via s2p51 LANGUAGE
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_s5p104_raw` / `s5p105_raw` / `s5p106_raw` / `s5p107_raw` / `s6p1_raw` — Diagnostic raw slots (5 entities)
- **Read**: live MQTT — semantics not yet decoded
- **Caveats**: surfaces for protocol-RE work; values logged at first observation
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_latest_session_area_m2` / `_latest_session_duration_min` — Latest session metrics (2 entities)
- **Read**: derived from session_archive
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_archived_session_count` — Archived session count
- **Read**: `coordinator.session_archive.list_sessions()` count
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_lidar_archive_count` — LiDAR archive count
- **Read**: `coordinator.lidar_archive` count
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_schedule_count` — Schedule count
- **Read**: cloud `SCHEDULE.0` (parsed) — counts plans across slots
- **Latency**: cloud poll @2min, plus s6p2 hook (when fires)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_hardware_serial` — Hardware serial
- **Read**: cloud `routed-action g.DEV` @6h poll
- **Caveats**: also tries `get_properties(s1, p5)` but mostly returns 80001
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_firmware_version` — Firmware version
- **Read**: cloud `routed-action g.DEV` @6h poll
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_mower_timezone` — Timezone
- **Read**: cloud `CFG.TIME` @10min poll
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_cfg_version` — CFG version
- **Read**: cloud `CFG.VER` @10min poll — monotonic increment on every CFG write
- **Caveats**: USEFUL TRIPWIRE — could drive a faster poll for change detection (Phase 2 candidate)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_cloud_connected` — Cloud connected (bool)
- **Read**: live MQTT `s6p3[0]`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_novel_observations` — Novel observations
- **Read**: derived — `coordinator.novel_registry`
- **Caveats**: surfaces unfamiliar protocol shapes — count + attributes list
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_data_freshness` — Per-field staleness
- **Read**: derived — `coordinator.freshness` tracker (default-disabled)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `sensor.dreame_a2_mower_api_endpoints_supported` — Cloud-RPC log
- **Read**: derived — `cloud_client.endpoint_log` (default-disabled)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

(Sensors not enumerated above: there are a few more diagnostic sensors that surface internal state — they will be fully cataloged in second-pass Task 9.)

---

## Section F — `binary_sensor` (18 entities)

### `binary_sensor.dreame_a2_mower_obstacle_detected` — Obstacle detected
- **Read**: live MQTT `s1p53` (bool)
- **Latency**: instant
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_rain_protection_active` — Rain protection active (derived)
- **Read**: derived from MQTT `s2p2 == 56` (error_code 56 = bad weather signal)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_positioning_failed` — Positioning failed (derived)
- **Read**: derived from MQTT `s2p2 == 71`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_failed_to_return_to_station` — FTRTS (derived)
- **Read**: derived from MQTT `s2p2 == 31`
- **Caveats**: two paths in: 33→31 or 48→31; user must manually Recharge to recover
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_battery_temp_low` — Battery temp low
- **Read**: live MQTT `s1p1` byte[6] bit 3 (heartbeat blob)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_mowing_session_active` — Session active
- **Read**: derived — `coordinator.live_map.is_active()` populated by `_on_state_update`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_drop_tilt` / `_bumper` / `_lift` — s1p1 byte bits (3 entities)
- **Read**: live MQTT `s1p1` heartbeat blob, byte[1] / byte[1] / byte[2] bits
- **Latency**: instant
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_emergency_stop` — Emergency stop activated
- **Read**: live MQTT `s1p1` byte[3] bit 7 — PIN-required latch
- **Caveats**: clears ONLY on PIN entry; lid close / set-down does NOT clear
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_safety_alert_active` — Safety alert (one-shot)
- **Read**: live MQTT `s1p1` byte[10] bit 1 — self-clearing 30-90s
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_top_cover_open` — Top cover open (derived)
- **Read**: derived from MQTT `s2p2 == 73`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_mower_in_dock` — Mower in dock
- **Read**: cloud `routed-action g.DOCK.connect_status` @60s poll
- **Caveats**: more reliable than `s2p1 == 6 (CHARGING)` which only fires while drawing power
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_dock_in_lawn_region` — Dock in lawn polygon
- **Read**: cloud `routed-action g.DOCK.in_region` @60s poll
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_wheel_bind_active` — Wheel bind detected (derived)
- **Read**: derived — cross-frame s1p4 diagnostic comparing position delta vs area-mowed delta
- **Caveats**: detects firmware integrator counting while wheels physically stalled
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `binary_sensor.dreame_a2_mower_edgemaster` — EdgeMaster
- **Read**: live MQTT `s6p2[2]` (bool)
- **Latency**: ✓ instant — verified live 2026-05-09 13:48 (probe log captured byte[2] flip)
- **Cold-start**: last-known s6p2 value
- **Write**: ✗ no write path (read-only entity)
- **Caveats**: only in s6p2 frame — no SETTINGS field; second app on cold-start picks it up via cloud (mechanism: app subscribes MQTT and gets latest s6p2 on connect)
- **Recipe**: T3 (toggle EdgeMaster in app, expect s6p2[2] flip in probe log)
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int 1.0.2a8 (probe log captured `s6p2 [1e 00 00 02]` — byte[2] = 0)

---

## Section G — `button` (7 entities)

### `button.dreame_a2_mower_start_mowing` — Start mowing
- **Write**: routes through `lawn_mower.async_start_mowing` → `coordinator.dispatch_action(START_MOWING / EDGE / ZONE / SPOT)` based on `state.action_mode`
- **Recipe**: T6 — press, observe state transition + opcode in routed-action probe
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_pause_mowing` — Pause
- **Write**: `coordinator.dispatch_action(PAUSE) → routed-action s2.50 m='a' o=PAUSE_OP`
- **Caveats**: only available WORKING/MAPPING
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_stop_mowing` — Stop
- **Write**: `coordinator.dispatch_action(STOP)`
- **Caveats**: WORKING/MAPPING/PAUSED/RETURNING; both Stop and End-Return-to-Station route through same op
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_recharge` — Recharge (return to dock)
- **Write**: `coordinator.dispatch_action(RECHARGE)`
- **Caveats**: greyed when CHARGING/CHARGED/RETURNING
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_find_bot` — Find my robot (locator beep)
- **Write**: `coordinator.dispatch_action(FIND_BOT, op:9) → fire-and-forget on /cmd/`
- **Caveats**: no state echo; always available
- **Recipe**: T6 — press, listen for beep
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_finalize_session` — Finalize stuck session
- **Write**: `coordinator.dispatch_action(FINALIZE_SESSION)` — local; flushes incomplete session to archive
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `button.dreame_a2_mower_refresh_from_cloud` — Refresh from cloud (v1.0.2a6+)
- **Write**: `coordinator._refresh_cloud_state()` — forces immediate cloud fetch
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section H — `time` (6 entities)

### `time.dreame_a2_mower_dnd_start` / `_dnd_end` — DND time window
- **Read**: live `s2p51 DND list[3]` → cloud `CFG.DND[1]/[2]`
- **Write**: writes DND list — shares with switch.dnd
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `time.dreame_a2_mower_low_speed_at_night_start` / `_end` — Low-speed window
- (same pattern as DND, with CFG.LOW)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `time.dreame_a2_mower_charging_start` / `_end` — Custom charging window
- (same pattern, with CFG.BAT[4]/[5])
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section I — `camera` (6 entities)

### `camera.dreame_a2_mower_main_view` — Live map / active session
- **Source**: `coordinator._main_view_png` — re-rendered on s1p4 telemetry tick + map md5 change
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `camera.dreame_a2_mower_work_log` — Archived session replay
- **Source**: `coordinator._work_log_png` — populated by `render_work_log_session()`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `camera.dreame_a2_mower_lidar_top_down` / `_full` — LiDAR PCD render (2 entities)
- **Source**: `coordinator.lidar_archive` PCD blobs
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `camera.dreame_a2_mower_static_map_<id>` — Per-map static base + M_PATH (multi-map)
- **Source**: `coordinator._static_map_pngs_by_id`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section J — `device_tracker` / `event` / `update` (6 entities)

### `device_tracker.dreame_a2_mower_mower_location` — Mower GPS-style location
- **Read**: derived from `MowerState.position_x_m / position_y_m` + dock pose
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `event.dreame_a2_mower_lifecycle` — Lifecycle events
- **Source**: coordinator state machine fires: mowing_started/paused/resumed/ended, dock_arrived/departed
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `event.dreame_a2_mower_alert` — Alert events (reserved)
- **Source**: declared with empty event_types; alert tier landing in a future PR
- **Caveats**: STALE / placeholder
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `update.*` — 3 update entities (TBD precise identity)
- **Source**: TBD — investigate in Task 9 / second pass
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section K — Public services

(Each service is a write-or-action surface; verification covers cloud-side acceptance + observable effect.)

### `dreame_a2_mower.set_active_selection` — Update local picker
- **Write**: HA-local — sets `MowerState.active_selection_zones / spots / edge_contours`
- **Outcome**: ✓ self-evident (HA-local state)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.mow_zone / .mow_edge / .mow_spot` — One-shot mow with selection
- **Write**: sets selection then `dispatch_action(START_*_MOW)`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.recharge / .find_bot / .lock_bot / .suppress_fault / .finalize_session` — Action wrappers
- **Write**: `dispatch_action(<MowerAction>)`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.replay_session` — Render archived session
- **Write**: HA-local — `render_work_log_session(md5)`
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.show_lidar_fullscreen` — Fire UI event
- **Write**: HA event bus
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.dump_map_diagnostics` / `.discover_cloud_api` — Diagnostic services
- **Write**: cloud probes; results to log / disk
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.set_schedule_plans` — Replace one slot's plan list
- **Write**: `coordinator.write_schedule(new_slots) → setDeviceData (SCHEDULE.0 chunked)` — bumps version, preserves slot mode flag
- **Outcome**: ⚠ untested live in this audit
- **Recipe**: T3 (app slot edit, observe SCHEDULE diff) + T4 (HA service call, cold-start app)
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

### `dreame_a2_mower.refresh_cloud_state` — Force on-demand cloud fetch
- **Write**: `coordinator._refresh_cloud_state()`
- **Outcome**: ✓ self-evident
- **Verified**: ⚠ hypothesis (first pass 2026-05-09)

---

## Section L — MQTT slots without a current entity (gap analysis)

(MowerState fields populated by MQTT but no HA entity exposes them.)

### `(1, 50)` `(1, 51)` `(1, 52)` — Empty-dict pings (suppressed)
- **Status**: handled internally — `(1, 50)` triggers MAPL repoll; others suppressed for novelty noise
- **Action**: no entity needed; INTERNAL

### `(2, 50)` — Action-surface TASK envelope (echo)
- **Status**: suppressed — echo of own command
- **Action**: no entity; INTERNAL

### `(6, 117)` — Dock-nav state marker
- **Status**: int (1, 3) observed; fires on TASK_NAV_DOCK transitions following FTRTS bounce
- **Action**: surfaced indirectly — could become a diagnostic sensor
- **Phase**: 2 (read-side refactor) candidate

### `pre_mowing_height_mm` — mm version of mowing height
- **Status**: internal helper for PRE-write encoding
- **Action**: no user-facing entity needed; keep internal

### `pre_mowing_efficiency` — mowing efficiency live value
- **Status**: surfaced via `select.mowing_efficiency`
- **Action**: ✓ surfaced

(Other gaps will be enumerated as the second pass exposes them.)

---

## Section M — Cloud endpoints reference

(Endpoints called by `cloud_client.py` — used to verify reads + as the surface for write-path tests.)

### Auth + discovery
- `dreame-auth/oauth/token` — login (primary password OR refresh-token paths)
- `dreame-user-iot/iotuserbind/device/listV2` — list devices
- `dreame-user-iot/iotuserbind/device/info` — device info
- `dreame-user-iot/iotuserbind/devOTCInfo` — OTC info (for MQTT credentials)

### Property RPCs (mostly fail with 80001 on g2408)
- `dreame-iot-com/sendCommand` — get_properties / set_property / set_properties / action — various siid/piid combos
- Confirmed 80001-rejected on g2408: most siid/piid combinations except `s2.50` routed-action

### Chunked-batch (the rewrite-introduced surface)
- `dreame-user-iot/iotuserdata/getDeviceData` — `get_batch_device_datas([])` returns ALL chunked keys
- `dreame-user-iot/iotuserdata/setDeviceData` — `set_batch_device_datas({key: value, ...})` writes chunked keys
- `cloud_client.write_chunked_key(key_prefix, value, info=None)` — chunking helper (1024-char cap)

### Routed-action `s2.50 aiid=50`
- `g.CFG` — full CFG dict (24 keys on g2408)
- `g.MAPL` — multi-map active list
- `g.MIHIS` — lifetime totals
- `g.LOCN` — dock GPS origin
- `g.DOCK` — dock pose (connect_status, in_region, x, y, yaw, near_x, near_y, near_yaw, path_connect)
- `g.DEV` — device info (sn, mac, fw, ota)
- `g.NET` — wifi info (current ssid, ip, rssi)
- `g.PREI` — preference info (type, ver list)
- `g.CMS` — consumable wear meters
- `g.PIN` — PIN status
- `g.RPET` — rain protection end time
- `g.AIOBS` — AI obstacle config (returns r=-3 unsupported on g2408)
- `g.OBS` — obstacle config (r=-3)
- `g.PRE` — preference (r=-3)
- `g.MISTA` — mission status (r=-1)
- `g.MAPI` `g.MAPD` — map info / data (r=-3 unsupported)
- `s.<KEY>` — write CFG key (set_cfg) — supports CLS, VOL, LANG, DND, WRP, LOW, BAT, LIT, ATA, REC, FDP, STUN, AOP, PROT, MSG_ALERT, VOICE
- `s.PRE` — write PRE preferences (set_pre) — requires list ≥10 elements
- `a` (m='a') — action opcodes: 100=globalMower, 101=edgeMower, 102=zoneMower, 103=spotMower, 110=startLearningMap, 11=suppressFault, 9=findBot, 12=lockBot, 401=takePic, 503=cutterBias, 200=changeMap

### File ops
- `iotfile/filename` — get_interim_file_url, get_file_url
- direct download: `get_file(url)`

---

## Section N — Stale candidates (review during second pass)

Entities that may be old versions superseded by newer ones, or that shouldn't exist. To be assessed during the deep-verification passes.

- `event.dreame_a2_mower_alert` — declared with empty `event_types`; placeholder for an alert tier that hasn't shipped
- (Others to be flagged during Task 2-9)

---

## Audit completion stamp

(Filled in at end of Task 10.)

- **Audit completion**: TBD
- **Integration version**: TBD
- **Firmware version**: TBD
- **Spec commit**: `b17bc6a`
- **Plan commit**: `4c0646d`
- **Audit-complete tag**: TBD
