# Entity validation matrix (g2408)

> **Status — AUTHORITATIVE.** This is the source of truth for every HA entity's read source, write path, and outcome on g2408. When older docs (`g2408-protocol.md`, `g2408-research-journal.md`, `entity-sync-matrix.md`-retired) and this doc disagree, **this doc wins.** Each row carries an explicit evidence tier (✓ live / ⚠ hypothesis / ✗ disproved / ? unknown) — never read a row's claim without checking its tier.

Authoritative live-verified inventory of every HA entity, every received MQTT
slot, and every cloud endpoint the integration uses. Replaces the retired
[`historical/entity-sync-matrix-RETIRED-2026-05-09.md`](historical/entity-sync-matrix-RETIRED-2026-05-09.md).

**Status of the audit:** Spec / plan complete; many rows live-verified end-to-end (e.g. CLS, WRP, lawn_mower); many rows still ⚠ hypothesis (first pass 2026-05-09 — second pass folds in cell-by-cell). The "Cross-entity verification summary" section below tracks the moving frontier.

**Spec:** `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md` (commit `b17bc6a`)
**Plan:** `docs/superpowers/plans/2026-05-09-protocol-validation-audit.md` (commit `4c0646d`)

## Evidence tiers

- `✓ live <date> / fw <ver> / int <ver>` — verified by a live test within the audit window. The ONLY tier that counts as evidence.
- `⚠ hypothesis from <source>` — from code, docs, git, or APK reference. Drives test design; doesn't replace the test.
- `✗ live <date>` — actively disproved by a live test.
- `? unknown` — not yet investigated.

There is no tier for "code looks right" / "git history shows it once worked." Those remain `⚠` until tested live.

## SETTINGS chunked-batch write surface — cloud-cache-only (2026-05-09)

Task 4 verification: HA toggle of `switch.ai_obstacle_recognition_humans` on the active map (map_id=1). Cloud `entry0/map_id=1.obstacleAvoidanceAi` updated 7 → 6 as expected. **The Dreame app continued showing all 3 AI bits on even after restart** — the device firmware never received the change. **All 13 SETTINGS-backed entity write paths flip to ✗ (cloud-cache-only).**

Affected: number.mowing_height, _cutter_position, _cutter_position_height, _edge_mowing_num, _obstacle_avoidance_height, _distance, _sensitivity; select.mowing_direction, _mowing_direction_mode, _edge_walk_mode; switch.edge_mowing_auto, _safe, _obstacle_avoidance, .obstacle_avoidance_enabled; switch.ai_obstacle_recognition_humans, _animals, _objects.

Same Phase 3 work item (HTTPS sniff) covers these + the 7 failing CFG keys + AI_HUMAN.0 + SCHEDULE — a single sniff session capturing 4-5 different settings will likely reveal the missing write surface.

Wire-format evidence: `wire-captures/settings-surface-cloud-only-2026-05-09.md`.

---

## Cross-entity verification summary (v1.0.2a9, 2026-05-09)

A summary of recent class-level verifications (full per-entity detail in the rows below):

### CFG-backed write surface — fixed in v1.0.2a9 for the working shapes

The integration's `set_cfg` was sending the wrong wire format. With v1.0.2a9:

**✓ End-to-end verified live (2026-05-09 / fw 4.3.6_0550 / int v1.0.2a9):**
The CLS round-trip via HA → cloud → device → app within seconds (no app restart) was directly observed. By extension (same `coordinator.write_setting → set_cfg` code path; same `r=0` response shape in the wire-format probe), the following 16 CFG-backed entities are inferred to also work end-to-end via the corrected wire format. **Each is flagged "verified by class-extension" and should still receive an individual T4 confirmation when convenient:**

- `switch.child_lock` (CLS) — ✓ end-to-end 2026-05-09 (user)
- `switch.frost_protection` (FDP) — ✓ end-to-end 2026-05-09 (user)
- `switch.auto_recharge_standby` (STUN) — ✓ end-to-end 2026-05-09 (user)
- `switch.ai_obstacle_photos` (AOP) — ✓ end-to-end 2026-05-09 (user)
- `select.navigation_path` (PROT) — ✓ end-to-end 2026-05-09 (user). **Single-int AMBIGUOUS_TOGGLE family closed: 5 of 5.**
- `number.volume` (VOL) — by extension (int 0-100, same shape class)
- `switch.anti_theft_lift_alarm`, `_offmap_alarm`, `_realtime_location` (ATA × 3) — by extension (list[3] all-bool ANTI_THEFT shape)
- `switch.msg_alert_anomaly`, `_error`, `_task`, `_consumables` (MSG_ALERT × 4) — by extension (list[4] AMBIGUOUS_4LIST shape)
- `switch.voice_regular_notification`, `_work_status`, `_special_status`, `_error_status` (VOICE × 4) — by extension (same as MSG_ALERT shape)

**✓ Wire format unblocked 2026-05-09 — named-key dict payloads (FAMILY COMPLETE):**
Survey of ioBroker.dreame revealed the missing wire format for several "complex CFG" keys: send the `d` payload as a **named-key dict** instead of `{value: <list>}`. `cloud_client.set_cfg` was refactored to accept either shape (primitive → wrap as `{value:X}` for back-compat; dict → send as-is). All three writable named-key entities are now end-to-end live-confirmed on g2408 fw 4.3.6_0550 / int v1.0.3a1:

- `switch.rain_protection` + `select.rain_protection_resume_hours` (WRP) — `{value, time}`. End-to-end live-confirmed via 4h→6h→4h round-trip with Dreame app reflecting both flips in real time. Optional `sen` field omitted (not surfaced in app, not echoed in getCFG).
- `switch.dnd` (DND) — `{value, time:[start_min, end_min]}`. End-to-end live-confirmed via toggle in HA → app's DND screen mirrored the change.
- `switch.low_speed_at_night` (LOW) — `{value, time:[start_min, end_min]}`. End-to-end live-confirmed via toggle in HA → app's "Low Speed at Night" page mirrored the change.
- LIT-backed lights (currently read-only) — wire format `{value, time:[start, end], light:[l0,l1,l2,l3], fill}` verified accepted in cloud round-trip; entities still read-only pending a write-side design.

**✗ Write still rejected — Phase 3 sniff still needed:**
The device returns `r=-3` for these CFG keys with every wire format we've tried.

- `switch.custom_charging_period` + `number.auto_recharge_battery_pct` + `number.resume_battery_pct` (BAT list[6] mixed) — no ioBroker reference, named-key shape unknown
- REC (read-only) — same
- `select.language` (LANG list[2], read-only) — same

Wire-format evidence: `wire-captures/cfg-write-regression-2026-05-09.md` (initial r=-3 evidence) + `wire-captures/iobroker-write-catalog-2026-05-09.md` (named-key catalog + the WRP/DND/LOW/LIT round-trip results).

---

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
- **Latency**: ✓ instant via MQTT
- **Cold-start**: last-known MQTT state (routed-action `g.MISTA` returns r=-1 unsupported on g2408)
- **Sanity-check**: cloud poll @2min via `_refresh_cloud_state`
- **Write**: `coordinator.dispatch_action(MowerAction.<op>) → routed-action s2.50 m='a' o=<op>`
- **Outcome**: ✓ end-to-end verified live 2026-05-09 — Task 2 captured a real mowing session; dispatch_action's `s2.aiid=1` (alternate START path tried during Task 3 wire-format probe) also unintentionally triggered a real device-side mow start, confirming the action surface drives the device
- **Caveats**: action routing dispatches different opcodes for all-areas / edge / zone / spot mow based on `state.action_mode` and `active_selection_*`. Op codes documented in `protocol/cfg_action.py` `_OP_CATALOGUE`: 100=globalMower, 101=edgeMower, 102=zoneMower, 103=spotMower, 110=startLearningMap, 11=suppressFault, 9=findBot, 12=lockBot, 401=takePic, 503=cutterBias, 200=changeMap.
- **Recipe**: T6 (run a real session, observe state transitions in MQTT)
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int v1.0.2a9 — cross-validated against the Task-3 unintended-START incident (probe-safety incident note in `wire-captures/cfg-write-regression-2026-05-09.md`)

---

## Section B — `switch` (34 entities)

### `switch.dreame_a2_mower_child_lock` — Child lock
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.CLS` @10min
- **Latency**: ✓ live MQTT push (AMBIGUOUS_TOGGLE shape, 42 fires across 3 weeks)
- **Cold-start**: cloud `CFG.CLS` via `fetch_cfg`
- **Sanity-check**: cloud `CFG.CLS` poll
- **Write**: `coordinator.write_setting("CLS", value) → routed-action s2.50 m='s' t='CLS' d={value:N}` (wire format fixed in v1.0.2a9)
- **Outcome**: ✓ end-to-end verified live 2026-05-09 — HA toggle propagated to the Dreame app within seconds (user observation post-v1.0.2a9 deploy)
- **Caveats**: s2p51 wire shape ambiguous between CLS/FDP/STUN/AOP/PROT — disambiguation gap remains (Phase 2 candidate); pre-v1.0.2a9 set_cfg used the wrong wire format and silently failed every write
- **Recipe**: T3 (app toggle, observe AMBIGUOUS_TOGGLE in s2p51) + T4 (HA toggle, observe app reflects within seconds — no cold-start needed for this entity, the device pushes change live)
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int v1.0.2a9 — full HA→cloud→device→app round trip in seconds

### `switch.dreame_a2_mower_dnd` — Do not disturb
- **Read**: live `s2p51 LOW_SPEED_NIGHT_or_ANTI_THEFT_or_DND list[3]` (shape-discriminated by value range) → cloud `CFG.DND` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.DND`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("DND", {"value": <0|1>, "time": [start_min, end_min]}) → cloud_client.set_cfg → routed-action s2.50 m='s' t='DND' d=<dict>` (named-key wire format; build_value_fn `_build_dnd` constructs the dict from MowerState)
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA toggle propagated to the Dreame app (user observed app DND screen mirrored the change). Device firmware applies the named-key write, not just cloud cache.
- **Caveats**: full-form payload is required regardless of enabled bit — bare `{value:0}` returns r=-3 (verified live 2026-05-09). list[3] read-shape collides with LOW (low-speed-night) and ATA (anti-theft); discriminated by element values: minutes (0-1440) → LOW/DND, bools → ATA.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1 — full HA→cloud→device→app round trip confirmed (named-key wire format)

### `switch.dreame_a2_mower_rain_protection` — Rain protection
- **Read**: live `s2p51 RAIN_PROTECTION list[2]` → cloud `CFG.WRP` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.WRP`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("WRP", {"value": <0|1>, "time": <resume_hours>}) → cloud_client.set_cfg → routed-action s2.50 m='s' t='WRP' d=<dict>` (named-key wire format; build_value_fn `_build_wrp`)
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — cloud probe round-tripped 4h→6h→4h and the Dreame app reflected both flips in real time on the Rain Protection settings page (user observation post-named-key refactor). Device firmware applies the change, not just cloud cache.
- **Caveats**: shares wire with `select.rain_protection_resume_hours` (writes the same WRP record — last writer wins). The optional `sen` (rain-sensor sensitivity) field is silently accepted with `sen ∈ {0,1,2,3}` (all r=0) but `getCFG` returns only the 2-element shape and the Dreame app on this firmware doesn't surface a sensitivity UI — omitted from our writes.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.2a10 — full HA→cloud→device→app round trip confirmed (named-key wire format)

### `switch.dreame_a2_mower_low_speed_at_night` — Low speed at night
- **Read**: live `s2p51 LOW list[3]` → cloud `CFG.LOW` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.LOW`
- **Sanity-check**: cloud poll
- **Write**: `coordinator.write_setting("LOW", {"value": <0|1>, "time": [start_min, end_min]}) → cloud_client.set_cfg → routed-action s2.50 m='s' t='LOW' d=<dict>` (named-key wire format; build_value_fn `_build_low`)
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA toggle propagated to the Dreame app's "Low Speed at Night" page (user observation). Device firmware applies the named-key write, not just cloud cache. Completes the named-key family verification (WRP + DND + LOW all end-to-end on g2408 fw 4.3.6_0550).
- **Caveats**: list[3] shape ambiguity (see DND). Same "always send full form" rule as DND.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1 — full HA→cloud→device→app round trip confirmed (named-key wire format)

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
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA toggle propagated to the Dreame app's Frost Protection setting (user observation).
- **Caveats**: s2p51 ambiguous-toggle (CLS/FDP/STUN/AOP/PROT)
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1

### `switch.dreame_a2_mower_auto_recharge_standby` — Auto recharge after extended standby
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.STUN` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.STUN`
- **Write**: `coordinator.write_setting("STUN", value) → routed-action s2.50 s.STUN d=0|1`
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA toggle propagated to the Dreame app's Auto Recharge setting (user observation).
- **Caveats**: ambiguous-toggle wire; behaviour observed to fire `s2p2=71 + s2p1=5` after 57 min idle outside dock
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1

### `switch.dreame_a2_mower_ai_obstacle_photos` — AI obstacle photos
- **Read**: live `s2p51 ambiguous-toggle` → cloud `CFG.AOP` @10min
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.AOP`
- **Write**: `coordinator.write_setting("AOP", value) → routed-action s2.50 s.AOP d=0|1`
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA toggle propagated to the Dreame app's "Capture Photos of AI-Detected Obstacles" setting (user observation). App-side title disambiguates this from AI_HUMAN.0.
- **Caveats**: App-side display name is "Capture Photos of AI-Detected Obstacles" (mirrors what we previously labelled AI_HUMAN.0 in our integration — naming overlap; matrix row description should be reconsidered). Privacy-policy acceptance for photo capture is NOT surfaced as an entity in the integration — it lives in `CFG.REC[7]` (`photo_consent`) and is currently parsed for logging only. Toggling AOP on without accepted privacy policy may silently no-op on the device side.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1

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
- **Outcome**: ✗ inferred-cloud-cache-only (Task 5; same `setDeviceData` surface as the SETTINGS-backed class proven cloud-cache-only in Task 4) — pending direct T4 confirmation but very likely same as SETTINGS
- **Caveats**: distinct from `switch.ai_obstacle_photos` (CFG.AOP) — different setting in app; AOP works end-to-end (set_cfg path), AI_HUMAN.0 likely doesn't (setDeviceData path)
- **Recipe**: T3 + T4 (deferred to Phase 3 work which covers all setDeviceData entities)
- **Verified**: ✗ inferred 2026-05-09 — same cloud-cache-only surface as Task 4 SETTINGS class

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
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — HA option change propagated to the Dreame app's Navigation Path setting (user observation). Closes the single-int AMBIGUOUS_TOGGLE family (5 of 5: CLS, FDP, STUN, AOP, PROT all ✓).
- **Caveats**: PROT mapping `{0: direct, 1: smart}`; ambiguous-toggle wire. An older `switch.smart_navigation_path` (orphan from a pre-select version) was cleaned up 2026-05-09 — same `CFG.PROT` toggle, replaced by this select.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a2

### `select.dreame_a2_mower_rain_protection_resume_hours` — Rain protection resume hours
- **Read**: live `s2p51 RAIN_PROTECTION list[2]` → cloud `CFG.WRP[1]`
- **Latency**: ⚠ ~5s
- **Cold-start**: cloud `CFG.WRP`
- **Write**: `coordinator.write_setting("WRP", {"value": <enabled>, "time": <resume_hours>}) → cloud_client.set_cfg → routed-action s2.50 m='s' t='WRP' d=<dict>` (named-key wire format; build_value_fn `_build_wrp_resume_hours` reads the current `rain_protection_enabled` bit and overrides `time` with the picked option)
- **Outcome**: ✓ end-to-end live-confirmed 2026-05-09 — same WRP record as the switch; cloud round-tripped 4h→6h→4h with Dreame app reflecting the change in real time.
- **Caveats**: shares wire with switch.rain_protection — last writer wins.
- **Recipe**: T3 + T4 (T4 done 2026-05-09)
- **Verified**: ✓ end-to-end live 2026-05-09 / fw 4.3.6_0550 / int v1.0.2a10 (named-key wire format)

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
- **Latency**: ✓ sub-second via s1p50 ping + 60s `_refresh_mapl` timer
- **Cold-start**: cloud MAPL fetch
- **Sanity-check**: 60s MAPL repoll
- **Write**: `coordinator.dispatch_action(SET_ACTIVE_MAP, op:200) → routed-action s2.50 m='a' o=200 d={mapId}`
- **Outcome**: ✓ verified live during this audit — active map switched from Map 1 (map_id=0) to Map 2 (map_id=1) between Task 2 and Task 4 (MAPL row[1] flipped from `[0,1,1,1,0]` to `[1,1,1,1,0]`); HA's active_map select reflected immediately
- **Caveats**: optimistic UI during write-in-flight; MAPL repoll confirms within seconds via s1p50 trigger
- **Recipe**: T6 (switch maps in HA, observe MAPL row[1] flip in cloud snapshot)
- **Verified**: ✓ live 2026-05-09 (passive observation — map switched naturally during the audit window)

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
- **Latency**: ✓ instant via MQTT (20 fires in 23 min during the captured session, ~1-2 min cadence)
- **Cold-start**: last-known MQTT value (or 0 if never received)
- **Write**: n/a (read-only)
- **Recipe**: T6 — observe during charging cycle
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int 1.0.2a8 / spec b17bc6a — see `docs/research/wire-captures/telemetry-session-2026-05-09.md`

### `sensor.dreame_a2_mower_charging_status` — Charging status (enum)
- **Read**: live MQTT `s3p2` (NOT_CHARGING/CHARGING/CHARGED)
- **Latency**: ✓ instant (fires once on each state transition: dock-depart, charging-start, charged)
- **Recipe**: T6 — observe at session start/end and dock arrive
- **Verified**: ✓ live 2026-05-09 (`s3p2 = 0` captured at session start, transition from previous CHARGING/CHARGED)

### `sensor.dreame_a2_mower_position_x_m` / `_y_m` / `_north_m` / `_east_m` — Position (4 entities)
- **Read**: live MQTT `s1p4` telemetry blob — `MowingTelemetry` decoder extracts x_mm, y_mm; north/east derived via station-bearing rotation
- **Latency**: ✓ instant (every ~5 s during mowing — 274 s1p4 fires in 23 min)
- **Cold-start**: None until first s1p4 received
- **Recipe**: T6 — capture during a session
- **Verified**: ⚠ slot fires confirmed live 2026-05-09; per-field decode cross-check deferred to Task 9

### `sensor.dreame_a2_mower_area_mowed_m2` / `_session_distance_m` / `_mowing_phase` — Session telemetry (3 entities)
- **Read**: live MQTT `s1p4` blob — area, distance, phase fields
- **Latency**: ✓ ~5 s during mowing (s1p4 274 fires confirmed)
- **Caveats**: resets at session start; phase advances monotonically
- **Verified**: ⚠ slot fires confirmed live 2026-05-09; per-field decode cross-check deferred to Task 9

### `sensor.dreame_a2_mower_error_code` / `_error_description` — Error (2 entities)
- **Read**: live MQTT `s2p2` (int) for error_code; error_description = `_describe_error_or_none(error_code)` lookup
- **Latency**: ✓ instant on transition
- **Caveats**: sticky — does not clear on device until app/PIN clears; 20 distinct values seen across 149 historical transitions in the probe log (codes 0, 1, 9, 23, 27, 30, 31, 33, 36, 43, 48, 50, 53, 54, 56, 60, 70, 71, 73, 75)
- **Verified**: ✓ live 2026-05-09 (s2p2 = 50 captured at session start; 149 historical transitions cross-validate)

### `sensor.dreame_a2_mower_task_state_code` — Task state code (raw)
- **Read**: live MQTT `s2p56.status[0][1]` (sub-state) — see `property_mapping.py:80-91` for shape decoding
- **Latency**: ✓ instant
- **Caveats**: 0 = running, 4 = paused-pending-resume; 0→4→0 = recharge round-trip; empty status = no active session
- **Verified**: ✓ live 2026-05-09 (captured `{"status": []}` → `{"status": [[1, 0]]}` transition at session start)

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
- **Latency**: ✓ instant (5 fires during the 23-min captured session)
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int 1.0.2a8

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
- **Latency**: ✓ instant (s1p1 fires 88 times in 23 min during the captured session — slot is alive)
- **Verified**: ⚠ slot fires confirmed live 2026-05-09; per-bit flips need a fault-event session for full per-bit evidence (sample frame had all bits 0 = nominal mowing)

### `binary_sensor.dreame_a2_mower_emergency_stop` — Emergency stop activated
- **Read**: live MQTT `s1p1` byte[3] bit 7 — PIN-required latch
- **Caveats**: clears ONLY on PIN entry; lid close / set-down does NOT clear
- **Verified**: ⚠ slot fires confirmed (s1p1 alive); per-bit flip needs a controlled emergency-stop test (lift the mower mid-mow)

### `binary_sensor.dreame_a2_mower_safety_alert_active` — Safety alert (one-shot)
- **Read**: live MQTT `s1p1` byte[10] bit 1 — self-clearing 30-90s
- **Verified**: ⚠ slot fires confirmed (s1p1 alive); per-bit flip needs a controlled lift test

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

## Section G — `button` (10 entities)

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

### `button.dreame_a2_mower_lock_robot` — Lock robot (apk op=12) — accepted, no observable effect
- **Write**: `coordinator.dispatch_action(LOCK_BOT, op:12) → routed-action s2.50 m='a' o=12`
- **Caveats**: First press 2026-05-09 18:03 was followed by 30 min of fetch_* None warnings, but a controlled retry 18:36 (HA stable, 60s baseline, 90s post-press monitoring) showed **zero new warnings, zero entity changes** — the original incident was unrelated to op=12 (cloud was flaky during the post-restart setup window with a transient 80001 wave). **No visible effect on the device** in either press: LED stayed green, no app notification, CFG.CLS unchanged (distinct from CHILD_LOCK). On g2408 the action appears to be a no-op or has effects we can't detect from the cloud surface.
- **Outcome**: ✓ live 2026-05-09 — accepted by cloud, no observable device-side effect (n=2)
- **Recipe**: T6 — repeat as needed; capture any device-side state change (LED, sound, app notification, MQTT push)
- **Verified**: ✓ live 2026-05-09 / fw 4.3.6_0550 / int v1.0.3a1 — first-press incident was a coincidence; second press in controlled conditions was clean

### `button.dreame_a2_mower_generate_3dmap` — Generate 3D map (apk op=10) — UNTESTED
- **Write**: `coordinator.dispatch_action(GENERATE_3D_MAP, op:10, d:{idx:0}) → routed-action s2.50 m='a' o=10 d:{idx:0}`
- **Caveats**: Long-running on the mower side; progress should publish on s2p54 ("3dmap-progress"). Source: ioBroker.dreame v0.3.7 main.js:3474. Untested on g2408 — listed as `EntityCategory.DIAGNOSTIC` until verified.
- **Recipe**: T6 — press while docked, watch s2p54 for progress, wait for LIDAR archive URL
- **Verified**: ⚠ untested (added 2026-05-09 / int v1.0.2a10)

### `button.dreame_a2_mower_request_wifi_map` — Request WiFi map (s6.aiid=4) — UNTESTED
- **Write**: `coordinator.dispatch_action(REQUEST_WIFI_MAP) → direct MIoT s6.aiid=4` (NOT routed-action)
- **Caveats**: Different transport from the routed-action surface (siid=6 direct call). On g2408 the cloud-RPC tunnel for siid=6 actions has not been used before — may return 80001. Source: ioBroker.dreame v0.3.7 main.js:3478. Listed as `EntityCategory.DIAGNOSTIC` until verified.
- **Recipe**: T6 — press while docked, check for WiFi heatmap fetch / progress
- **Verified**: ⚠ untested (added 2026-05-09 / int v1.0.2a10)

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
- **Outcome**: ✗ inferred-cloud-cache-only (Task 6; same `setDeviceData` surface as the SETTINGS-backed class proven cloud-cache-only in Task 4) — pending direct T4 confirmation
- **Caveats**: SCHEDULE has known historical issue (mode flag dropped on encode) fixed in v1.0.2a2; that fix only addresses the cloud-side blob shape, not the device-apply gap
- **Recipe**: T3 (app slot edit, observe SCHEDULE.0 diff in cloud) + T4 (HA service call, cold-start app to verify schedule actually changed) — deferred to Phase 3
- **Verified**: ✗ inferred 2026-05-09 — same cloud-cache-only surface as Task 4 SETTINGS class

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

## Section N — Stale candidates + Task 1 entity-id corrections

Entities that may be old versions superseded by newer ones, or that shouldn't exist. To be assessed during the deep-verification passes.

- `event.dreame_a2_mower_alert` — declared with empty `event_types`; placeholder for an alert tier that hasn't shipped
- (Others to be flagged during Task 2-9)

### Task 1 first-pass entity_id corrections (post-Task 9 audit)

The first-pass skeleton inferred entity_ids from `key=` values plus unit suffixes, but HA's actual entity_ids don't include the suffixes. Live-verified actual entity_ids on the running instance (sensor platform):

| Matrix wrote | Actual entity_id |
|---|---|
| `sensor.dreame_a2_mower_battery_level` | `sensor.dreame_a2_mower_battery` |
| `sensor.dreame_a2_mower_position_x_m` etc. | `sensor.dreame_a2_mower_position_x` etc. |
| `sensor.dreame_a2_mower_area_mowed_m2` | `sensor.dreame_a2_mower_area_mowed` |
| `sensor.dreame_a2_mower_session_distance_m` | `sensor.dreame_a2_mower_session_distance` |
| `sensor.dreame_a2_mower_blades_life_pct` | `sensor.dreame_a2_mower_blades_life` |
| `sensor.dreame_a2_mower_cleaning_brush_life_pct` | `sensor.dreame_a2_mower_cleaning_brush_life` |
| `sensor.dreame_a2_mower_robot_maintenance_life_pct` | `sensor.dreame_a2_mower_robot_maintenance_life` |
| `sensor.dreame_a2_mower_total_mowing_time_min` | `sensor.dreame_a2_mower_total_mowing_time` |
| `sensor.dreame_a2_mower_total_mowed_area_m2` | `sensor.dreame_a2_mower_total_mowed_area` |
| `sensor.dreame_a2_mower_dock_x_mm` etc. | `sensor.dreame_a2_mower_dock_x` etc. |
| `sensor.dreame_a2_mower_task_state_code` | `sensor.dreame_a2_mower_task_state` |
| `sensor.dreame_a2_mower_slam_task_label` | `sensor.dreame_a2_mower_slam_task` |
| `sensor.dreame_a2_mower_total_lawn_area_m2` | `sensor.dreame_a2_mower_target_area` |
| `sensor.dreame_a2_mower_wifi_rssi_dbm` | `sensor.dreame_a2_mower_wifi_rssi` |
| `sensor.dreame_a2_mower_active_selection` | (matches) |

Sensors that DON'T currently exist in HA (despite being mentioned in matrix or expected):
- `sensor.dreame_a2_mower_hardware_serial` — not registered
- `sensor.dreame_a2_mower_mower_timezone` — not registered
- `sensor.dreame_a2_mower_cfg_version` — not registered
- `sensor.dreame_a2_mower_cloud_connected` — not registered
- `sensor.dreame_a2_mower_data_freshness` — not registered (default-disabled?)
- `sensor.dreame_a2_mower_api_endpoints_supported` — not registered (default-disabled?)
- `binary_sensor.dreame_a2_mower_dock_in_lawn_region` — not registered

Sensors that DO exist but were NOT in the first-pass matrix:
- `sensor.dreame_a2_mower_ota_flag_raw`, `_ota_status` — OTA state surfaces
- `sensor.dreame_a2_mower_session_track_point_count` — diagnostic
- `sensor.dreame_a2_mower_latest_session_area`, `_latest_session_duration`, `_latest_session_time` — session-summary surfaces
- `sensor.dreame_a2_mower_target_area` — lawn area surface
- `sensor.dreame_a2_mower_task_state` — task state surface

**Phase 2 work item**: regenerate the matrix from a live HA `get_states` call rather than from code reading. The first-pass approach guessed entity_ids from class declarations; reality is HA's name-flatting / unit-stripping is non-obvious.

---

## Audit completion stamp

- **Audit completion**: 2026-05-09
- **Integration version**: v1.0.2a9 (released mid-audit; included the major set_cfg fix)
- **Firmware version**: 4.3.6_0550
- **Spec commit**: `b17bc6a`
- **Plan commit**: `4c0646d`
- **Audit-complete tag**: `audit-complete-2026-05-09` (to be applied)

### Audit summary

| Class | Verification | Count |
|---|---|---|
| Read-only telemetry / state (Task 2) | ✓ live (s1p4 / s2p1 / s2p2 / s2p56 / s3p1 / s3p2 / s1p53 / s1p1) | 7 fully verified, ~10 slot-fires confirmed (per-bit deferred) |
| CFG-backed via `set_cfg` (Task 3) | ✓ end-to-end (CLS direct + 8 by class-extension via fixed v1.0.2a9 path) | 9 |
| CFG-backed via `set_cfg` — int-list shapes | ✗ no setter at this address (DND, LOW, WRP, BAT, LIT, REC, LANG) | 7 |
| SETTINGS-backed via `setDeviceData` (Task 4) | ✗ cloud-cache-only (writes don't drive device firmware) | 13 |
| AI_HUMAN.0 via `setDeviceData` (Task 5) | ✗ inferred-cloud-cache-only | 1 |
| SCHEDULE via `setDeviceData` (Task 6) | ✗ inferred-cloud-cache-only | 1 |
| Action surface (Task 7) | ✓ end-to-end (driven by `s2.50 m='a' o=<op>`) | lawn_mower + 6 buttons |
| Multi-map / map switching (Task 8) | ✓ end-to-end (`op:200 changeMap`) | active_map select |
| Diagnostics / read-only (Task 9) | ⚠ partial — most alive, ~7 expected sensors not registered (Phase 2 cleanup) | ~30 |

### Frontier — Phase 2 / Phase 3 work surfaced by the audit

**Phase 2 (read-side architecture refactor + matrix doc cleanup):**
- Regenerate matrix from live HA `get_states` rather than code-reading (first-pass had ~10 entity_id misnames).
- Surface missing diagnostic sensors that were expected but not registered (hardware_serial, mower_timezone, cfg_version, cloud_connected, data_freshness, api_endpoints_supported, dock_in_lawn_region).
- Decide on s2p51 ambiguous-shape disambiguation (`cfg_keys_raw _last_diff` from legacy alpha.123+ — was apparently in the legacy integration but missing from current).
- Coordinator decomposition (175 KB single file).

**Phase 3 (write-path repair via HTTPS sniff of Dreame app):**
- Single sniff session capturing 4-5 different settings across categories will likely identify the missing device-write surface for ~22 entities (7 CFG int-list keys + 13 SETTINGS-backed + AI_HUMAN.0 + SCHEDULE).
- All these entities currently silently fail to drive the device despite reporting success.
- Probe-safety incident note (Task 3): brute-force search of siid/aiid combos is unsafe — one such probe accidentally triggered a global-mower-start.

### Dispositional summary of write paths on g2408 cloud

After this audit:

| Cloud surface | Drives device? | Coverage |
|---|---|---|
| `routed-action s2.50 m='s' t=KEY d={value:<v>}` for 9 specific keys | ✓ yes | CFG simple-shape entities |
| `routed-action s2.50 m='s' t=KEY` for 7 other CFG keys | ✗ `r=-3` no setter | CFG int-list keys |
| `routed-action s2.50 m='a' o=<op>` | ✓ yes | mow start / stop / pause / dock / find_bot / change_map / etc. |
| `setDeviceData` chunked-batch | ✗ cloud-cache only | SETTINGS / AI_HUMAN.0 / SCHEDULE writes silently fail to drive device |
| direct MIoT `set_property(siid, piid, value)` | ✗ `80001` for most siids | Useless on g2408 except for op-codes that are equivalent to dispatch_action |
| **Some unknown surface used by the Dreame app** | ✓ presumably yes | Covers everything in the ✗ rows above; not yet captured |

This is the cleanest mental model the audit produces. **Future writes that need to drive the device firmware should be classified into the right cloud surface based on this table.** The current integration uses a mix of `set_cfg` and `setDeviceData`, but only `set_cfg` for the 9 specific CFG keys + the action opcodes actually drive the device. Everything else needs Phase 3 work.
