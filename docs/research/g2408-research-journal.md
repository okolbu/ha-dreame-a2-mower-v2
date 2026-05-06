# Dreame A2 (`g2408`) — Research Journal

Topic-clustered record of how each piece of the g2408 protocol got
figured out. Each topic carries a "Quick answer" of the current state,
a dated timeline of hypotheses and confirmations, deprecated readings
kept for traceability, and cross-references to inventory rows + canonical
chapters.

For **current state of any slot** see the canonical doc:
`docs/research/inventory/generated/g2408-canonical.md`.

For **the architectural overview** see `docs/research/g2408-protocol.md`.

For **open work** see `docs/TODO.md`.

---

## Topics

1. [s1p4 telemetry decoder evolution](#s1p4-telemetry-decoder-evolution)
2. [s1p1 byte[10] bit 1 saga (safety_alert_active)](#s1p1-byte10-bit-1-saga-safety_alert_active)
3. [s1p1 byte[3] bit 7 PIN-required clarification](#s1p1-byte3-bit-7-pin-required-clarification)
4. [Phase-byte semantics (s1p4 byte[8])](#phase-byte-semantics-s1p4-byte8)
5. [s2p1 mode + s2p2 state codes — what's enum vs error](#s2p1-mode--s2p2-state-codes--whats-enum-vs-error)
6. [s2p51 multiplexed config — disambiguation evolution](#s2p51-multiplexed-config--disambiguation-evolution)
7. [Edge-mow FTRTS + wheel-bind discovery (2026-05-05)](#edge-mow-ftrts--wheel-bind-discovery-2026-05-05)
8. [`s2p50` op-code catalog — incremental decode](#s2p50-op-code-catalog--incremental-decode)
9. [Map-fetch flow — `s6p1` / event_occured / OSS](#map-fetch-flow--s6p1--event_occured--oss)
10. [`cfg_individual` MISTA reversal (2026-05-06)](#cfg_individual-mista-reversal-2026-05-06)
11. [g2408 vs upstream divergence](#g2408-vs-upstream-divergence)
12. [apk cross-walk findings](#apk-cross-walk-findings)
13. [Recently shipped — version timeline](#recently-shipped--version-timeline)
14. [Live-confirmed status board](#live-confirmed-status-board)

---

## s1p4 telemetry decoder evolution

> **Quick answer (current state):** s1p4 carries 33-byte mowing telemetry,
> 8-byte beacon, or 10-byte BUILDING-save markers. Bytes 0-5 use a 20-bit
> packed encoder (apk-corrected in alpha.98); X is in mm post-decode (was
> mistakenly named `x_cm`); Y has a per-install 0.625 calibration factor.
> 33-byte field decode is in canonical; the per-byte history is here.

### Timeline

- **2026-04-17** — first probe corpus captured. 33-byte and 8-byte variants
  observed; 10-byte not yet seen. Initial decoder lifted from upstream Tasshack
  with int16_le for X (cm) and Y (mm). Worked for small coordinates.
- **2026-04-20** — full-day capture (07:58 → 12:33). Two auto-recharge interrupts.
  Confirmed `phase_raw` byte[8] advances monotonically through the firmware's
  pre-planned job sequence (per-zone area-fill, then edge passes, then
  return-home transport). Earlier "MOWING / TRANSIT / PHASE_2 / RETURNING" enum
  retired; `phase_raw` now exposed as a raw int diagnostic.
- **2026-04-22** — blades-down vs blades-up detection: `phase` byte[8] does NOT
  work (a 50 m blades-up dock-resume drive AND the subsequent mowing both had
  `phase = 2`). `area_mowed_cent` (bytes 29-30) WORKS PERFECTLY — frame-to-frame
  delta is a one-bit blades-on/off signal. Integration uses this in
  `live_map.DreameA2LiveMap` to tag captured path points with a `cutting` flag.
- **2026-04-24** — apk decompilation reveals bytes 1-5 are 20-bit signed packed,
  not int16_le. Validated against probe-log corpus (5586 consecutive-pair
  samples): median angular error 13°, 54% under 15° at the heading byte (8b
  variant byte[6]). Decoder bug found: Y was 1/16× the true value; downstream
  `* 0.625` compensation patches were masking the bug for small lawns.
- **2026-04-29** — alpha.98 ships the apk-corrected decoder. X and Y both in
  map-scale mm. All scattered `0.625` and `0.000625` magic factors removed.
  All probe-corpus regression frames re-validated.
- **2026-04-30** — confirmed `start_index` (bytes 7-9 uint24 LE) is a path-point
  sequence counter — 5,796 monotonic increments vs only 10 decrements across
  14,684 transitions. Decrements all look like new-session resets.
- **2026-05-05** — confirmed the post-FTRTS dock-nav phase uses 8-byte beacon
  frames (~25 consecutive frames over ~90 s during run 1's recovery). 8-byte
  beacons fire in four distinct contexts: idle/docked, leg-start preamble,
  BUILDING (manual map-learn), and post-FTRTS dock-nav.

### Deprecated readings

- ~~`Phase` enum: MOWING / TRANSIT / PHASE_2 / RETURNING~~ — wrong; phase byte
  is a per-task-plan zone index, not a transit/cutting discriminator. Retired
  2026-04-20.
- ~~Y-axis raw decode is `int16_le` at bytes [3-4]~~ — wrong; Y is the upper
  bits of a 20-bit packed value at bytes [1-5]. The old decode happened to give
  values 16× the truth, partially compensated by scattered `0.625` factors.
  Fixed in alpha.98.
- ~~Bytes [10-21] are motion vectors (vx, vy, ω, etc.)~~ — wrong; per apk they
  are three "delta" pairs (recent path history); per probe data Δ2 saturates
  more than Δ1/Δ3 in a way the apk doesn't explain. Decoder still pending; the
  integration ignores these bytes.
- ~~`area_mowed_cent` is a 16-bit value at bytes 29-30~~ — incomplete; per apk
  it's uint24 [29-31]. For lawns ≤ 655 m² the upper byte is always 0 so the
  16-bit decode happens to work. Lawns > 655 m² will overflow; open question.

### Cross-references

- Inventory: `s1p4_33b_x_mm`, `s1p4_33b_y_mm`, `s1p4_33b_phase_raw`, `s1p4_33b_distance_dm`, `s1p4_33b_total_area_centiares`, `s1p4_33b_area_mowed_centiares`, `s1p4_8b_heading_byte`, `s1p4_10b_unknown_6_7`
- Canonical: § Telemetry (s1p4) fields, § Telemetry frame variants

---

## s1p1 byte[10] bit 1 saga (safety_alert_active)

> **Quick answer (current state):** byte[10] bit 1 is a one-shot active-alert
> flag. Sets ~1 s after byte[3] bit 7 sets (i.e. shortly after a safety event);
> self-clears 30-90 s later regardless of state — including while the lid is
> still open and PIN has not been entered. Variable timer (4 / 18 / 33 / 53 / 77 s
> observed). Pairs with the Dreame app's "Emergency stop activated" push
> notification + the mower's red LED + voice prompt. Surfaced as
> `binary_sensor.safety_alert_active` in v1.0.0a69.

### Timeline

Pinned down 2026-05-04 via a 5-test controlled series on the live mower.

**Final model** after 5 controlled tests on 2026-05-04 (incl. one where the user
clarified PIN was at 20:43, lid-close at 20:44):

- **byte[3] bit 7** = "PIN required" / emergency-stop active. Sets on any safety
  event (lid open OR lift). Clears **only** on PIN entry — does NOT clear when
  the lid is closed or the mower is set down. Surfaced as
  `binary_sensor.emergency_stop_activated` (correctly named all along).
- **byte[10] bit 1** = one-shot active-alert flag. Sets ~1 s after byte[3] bit 7
  sets, self-clears 30–90 s later regardless of PIN/lid state. Pairs with the
  Dreame app's "Emergency stop activated" push notification + the mower's red
  LED + voice prompt. Surfaced as `binary_sensor.safety_alert_active` (renamed
  from `pin_required` in a69; original a68 name was based on the wrong
  hypothesis).
- **error_code (s2p2)** = sticky safety fault. Latches the first event (23 then
  73 within 1 s on g2408) and never naturally clears on the device's outbound
  `/status/` MQTT — even after PIN entry. The app's popup dismiss happens via a
  path the prober cannot observe.

**Smoking-gun test:** dock-only lid open → lid close, NO PIN. byte[3] stayed
asserted indefinitely after lid close, confirming the bit is PIN-tied (not
lid-tied). All 5 tests are consistent with this model.

**Structural gap:** PIN entry produces zero MQTT events on any topic the broker
ACL exposes. Both probable sources of the app's dismiss signal — cloud → app
push (APNs/account MQTT) and cloud → mower inbound `/cmd/` topic — are invisible
to a device-status-only subscriber. The integration cannot detect "PIN entered"
via MQTT.

**Test 1 (19:50–19:51):** manual mow → lift → set down → lid open → PIN typed
(lid open, mandatory — keypad is under the lid) → lid close → cancel → Recharge.

| Time | byte[3] bit 7 | byte[10] bit 1 | s2p2 error_code |
|---|---|---|---|
| 19:50:43 (lift) | **SET** | (still 0x80) | — |
| 19:50:44 (1 s later) | SET | **SET → 0x82** | 23, then 73 in same second |
| 19:51:02 (set down) | **CLEAR** | 0x82 (still set) | 73 (sticky) |
| 19:51:20 (some user step) | 0x00 | **CLEAR → 0x80** | 73 (sticky) |

byte[10] bit 1 SET 19:50:44, CLEAR 19:51:20 (**18 s after byte[3] cleared**,
well after PIN was typed).

**Test 2 (20:08–20:09, lid-only):** manual mow → lid open → PIN → lid close →
cancel → Recharge. (No lift this round.)

- byte[3] bit 7 SET 20:08:55, CLEAR 20:09:13 (lid close).
- byte[10] bit 1 SET 20:08:56, CLEAR 20:09:17 (**4 s after byte[3] cleared**,
  also after PIN was typed).

**Test 3 (lift-only, brief):** manual mow → quick lift → set down. No safety
lockout fired at all, no app notification. Suggests a **duration threshold** for
the safety chain to actually latch.

Key conclusions:

- byte[3] bit 7 is a **generic safety-chain flag** — both lift AND lid-open
  trigger it; clears as soon as the chain is restored. Brief lifts (< some
  threshold) don't fire it.
- byte[10] bit 1 sets ~1 s after byte[3] bit 7 sets and persists past byte[3]
  clearing.
- **byte[10] bit 1 is NOT cleared by PIN entry** — confirmed because PIN must
  be entered with lid open (keypad is under it), so the PIN is always typed
  BEFORE the lid-close that clears byte[3], and byte[10] still clears AFTER
  byte[3]. PIN was minutes earlier.
- The clear lag is variable (4 s / 18 s in our two data points), so it's not a
  fixed debounce timer either.
- **The Dreame app's "Emergency stop activated" push notification fires when
  byte[10] bit 1 sets**, not byte[3] bit 7.

### Deprecated readings

- ~~"byte[10] bit 1 = PIN-required latch (clears at PIN entry)"~~ — wrong;
  smoking-gun dock-only test had bit clear with lid still open and no PIN typed.
- ~~"byte[10] bit 1 = water_on_lidar (post-rain detection)"~~ — wrong; replaced
  by `error_code == 56` rain-protection signal in alpha.59.
- ~~"byte[10] bit 1 = post-fault-window timer (fixed N seconds)"~~ — wrong;
  observed clear lag varies 4-77 s, so it's not a fixed timer either.
- ~~"binary_sensor.dreame_a2_mower_pin_required" entity name~~ — renamed in
  alpha.69 to `binary_sensor.safety_alert_active` after semantics were pinned.

### Cross-references

- Inventory: `s1p1_b10_bit1`, `s1p1_b10_bit7`, `s1p1_b3_bit7`
- Canonical: § Heartbeat (s1p1) bytes

---

## s1p1 byte[3] bit 7 PIN-required clarification

> **Quick answer (current state):** byte[3] bit 7 = "PIN required" /
> emergency-stop active. Sets on any safety event (lid open OR lift). Clears
> ONLY on PIN entry — does NOT clear when lid is closed or mower is set down.
> Surfaced as `binary_sensor.emergency_stop_activated`. Sticky-until-acknowledged
> by design; the Dreame app's "Emergency stop is activated" modal is the user-
> facing UX, the integration's persistent_notification (a70) is the HA mirror.

### Timeline

- **2026-05-04 (first partial capture)** — initial observation during Test 1:
  byte[3] bit 7 appeared to behave as an immediate physical lift sensor: set the
  moment the mower was picked up, cleared the moment it was set down. NOT yet
  confirmed to be tied to PIN entry — that was the residual hypothesis.
- **2026-05-04 (Test 2, lid-only)** — byte[3] bit 7 SET 20:08:55, CLEAR
  20:09:13. The clear came at lid-close, not at PIN entry (typed earlier).
  This raised the question: is it lid-tied or PIN-tied?
- **2026-05-04 (smoking-gun test)** — dock-only lid open → lid close, NO PIN
  entered. byte[3] bit 7 stayed asserted indefinitely after lid close. Confirmed
  the bit is PIN-tied (not lid-tied). All 5 tests consistent with this model.
- **2026-05-04 (final model)** — byte[3] bit 7 = "safety chain broken, PIN
  required". Sets on any safety event (lift OR lid-open beyond duration
  threshold). Clears only on PIN entry. `s2p2` error_code 23/73 latches
  simultaneously and does not clear naturally.

### Deprecated readings

- ~~"byte[3] bit 7 = immediate physical lift sensor (sets on pickup, clears on
  setdown)"~~ — wrong; the bit is PIN-tied, not lift-tied. Smoking-gun was a
  dock-only lid-open-then-close test where the bit stayed asserted indefinitely
  after lid close, confirming PIN — not lid — is the trigger to clear.
- ~~"byte[3] bit 7 also signals top-cover-open"~~ — wrong; top-cover-open is
  signalled by `error_code == 73`, while byte[3] bit 7 is the broader "safety
  chain broken, PIN required" flag.

### Cross-references

- Inventory: `s1p1_b3_bit7`
- Canonical: § Heartbeat (s1p1) bytes

---

## Phase-byte semantics (s1p4 byte[8])

> **Quick answer (current state):** byte[8] is a task-phase index — the firmware
> decomposes each mowing task into ordered sub-tasks (per-zone area-fill, edge
> passes, return-home transport) and reports which one is currently active.
> Phase advances monotonically; once a value is done, the mower never returns
> to it in the same session. `phase_raw = 15` during post-complete return is
> distinctive. Different mowing modes expose different subsets of phase values;
> values are NOT cross-user portable.

### Timeline

- **2026-04-17** — first probe corpus captured. `Phase` enum labels
  (`MOWING / TRANSIT / PHASE_2 / RETURNING`) assigned based on rough positional
  clustering. Not yet validated as wrong.
- **2026-04-18** — live trajectory observation across a 3-hour session.
  `phase_raw` shown to advance monotonically through the firmware's pre-planned
  job sequence. Per-session observations table (Session 2):

  | phase_raw | Samples | X range | Y range (cal) | Likely role |
  |---|---|---|---|---|
  | 1 | 33 | -10.3..-9.0 m | -5.7..6.8 m | Dock transit corridor |
  | 2 | 329 | -10.4..2.9 m | -9.8..15.0 m | Zone area-fill (west) |
  | 3 | 293 | 0.2..14.4 m | -9.8..4.5 m | Zone area-fill (middle strip) |
  | 4 | 234+ | 12.1..20.5 m | -1.5..6.7 m | Zone area-fill (east / merged zone) |
  | 5 | 22+ | 7.3..20.7 m | -5.1..1.5 m | **Edge mow** — narrow Y spread, spans multiple zones |
  | 6 | 29+ | -6.6..8.6 m | -14.0..-6.2 m | Next edge/zone |
  | 7 | 3+ | -9.6..-8.7 m | -8.4..-6.3 m | Just starting — semantic TBD |

  Transitions (monotonic, non-repeating, each at a crisp coordinate):

  ```
  19:08:01  ph 1 → 2    at x = -10.21 m   (dock exit)
  19:35:56  ph 2 → 3    at x =   2.86 m   (zone boundary)
  20:56:01  ph 3 → 4    at x =  14.35 m   (into user's merged zone)
  21:15:41  ph 4 → 5    at x =  20.22 m   (far east — area-fill done, edge mow starts)
  21:17:31  ph 5 → 6    at x =   8.18 m   (next edge/zone)
  21:20:06  ph 6 → 7    at x =  -8.70 m
  ```

- **2026-04-20** — full-run capture confirms `phase_raw = 15` during the last
  23 s1p4 frames after `s2p56=[[1,2]]` and `s2p2=48` declare the task complete
  and before the mower reached the dock. Counters frozen at session's final
  values. Phase enum labels MOWING/TRANSIT/PHASE_2/RETURNING retired as
  actively misleading.
- **2026-04-22** — confirmed that phase does NOT discriminate blades-up from
  blades-down: a 50 m blades-up dock-resume drive AND the subsequent mowing
  both had `phase = 2`. Use `area_mowed_cent` delta instead.

### Deprecated readings

- ~~`Phase` enum: MOWING / TRANSIT / PHASE_2 / RETURNING~~ — retired 2026-04-20.
  No single phase value is "edge mode" or "transit" universally; the meaning of
  a phase value is bound to the current task plan.
- ~~"phase_raw distinguishes blades-up from blades-down"~~ — wrong; both
  blades-up dock-resume and blades-down mowing fired phase=2 in 2026-04-22
  capture. Use `area_mowed_cent` delta instead.

### Cross-references

- Inventory: `s1p4_33b_phase_raw`
- Canonical: § Telemetry (s1p4) fields, § Telemetry frame variants

---

## s2p1 mode + s2p2 state codes — what's enum vs error

> **Quick answer (current state):** g2408 SWAPS upstream's s2p1 / s2p2 meanings.
> Upstream's `(2, 1)` is STATE; on g2408 it's the small mode enum (1=Mowing,
> 2=Idle, 5=Returning, …). Upstream's `(2, 2)` is ERROR; on g2408 it's the
> wide state-code catalog (48=MOWING_COMPLETE, 50=manual-start, 53=scheduled-
> start, 70=mowing, …). The integration's overlay swaps these; per-code semantic
> is in the canonical doc's "s2p2 state codes" chapter.

### Timeline

- **2026-04-17** — `probe_log_20260417_095500.jsonl` analysed. 18 distinct
  (siid, piid) combinations observed across 2443 messages. Critical finding:
  upstream's `(2, 1)=STATE` and `(2, 2)=ERROR` are swapped on g2408. Overlay
  landed in alpha-overlay-c. s2p1 = small mode enum; s2p2 = wide state-code
  catalog.
- **2026-04-23** — apk decompilation cross-walk confirmed the swap: apk says
  s2p1 = "Status" enum and s2p2 = "Error code". The overlay is correct. Also
  confirmed specific state codes and the mode enum values via ioBroker-dreame
  cross-reference.

### Deprecated readings

- ~~"s2p1 is the STATE field; s2p2 is the ERROR field"~~ — that's upstream
  Tasshack's mapping (vacuum-derived); g2408 has them swapped. The overlay was
  added 2026-04-17 and re-validated by apk cross-walk 2026-04-23.
- ~~"s2p2 = 27 is IDLE"~~ — partially wrong; s2p2 = 27 fires twice in a single
  second during a human-presence event while the mower is demonstrably still
  moving. So `27` at runtime is NOT literal idle — it may be a query-response
  or alert-acknowledgement token. Documented as IDLE in the canonical for now;
  open question.
- ~~"s2p2 = 73 is TOP_COVER_OPEN per apk"~~ — apk-correct, but the empirical
  fire pattern includes lift events too (s2p2=73 fired during a mid-mow lift,
  before any lid touch). Either the apk label is wrong for g2408 or the lift
  gesture also disturbs the lid sensor.

### Cross-references

- Inventory: `s2p1_mode`, `s2p2_state`
- Canonical: § s2p1 mode enum, § s2p2 state codes

---

## s2p51 multiplexed config — disambiguation evolution

> **Quick answer (current state):** Every cloud-side settings change rides this
> slot. 17 distinct payload shapes documented; 15 unambiguous (named-key dicts
> or list shapes that fit only one CFG key) and 2 ambiguous on the wire
> (`{value: 0|1}` shared by 5 boolean settings, `{value: [b,b,b,b]}` shared by
> MSG_ALERT and VOICE). Disambiguation falls back to a `getCFG` snapshot diff
> on `sensor.cfg_keys_raw._last_diff`, run on each `s2p51` push.

### Timeline

- **2026-04-17** — first observation that all "More Settings" toggles ride a
  single property slot. Shapes not yet catalogued; payload is raw dict in logs.
- **2026-04-24** — live toggle testing. Named-key shapes confirmed unambiguous:
  Do Not Disturb `{end, start, value}`, Language `{text, voice}`, Timestamp
  `{time, tz}`. LED Period `{value: [8-element list]}` unambiguous by list
  length. Anti-Theft `{value: [3-element list]}` unambiguous.
- **2026-04-27** — Anti-Theft individually verified (all 3 indices toggled
  independently). Language voice index confirmed (7 = Norwegian).
- **2026-04-30** — MSG_ALERT and VOICE wire-collision discovered. Both ride
  `{value: [b,b,b,b]}`. All 4 slot semantics wire-confirmed for each. Decoder
  emits `Setting.AMBIGUOUS_4LIST`; `getCFG` diff needed to disambiguate. The
  5-key ambiguous-toggle set `{value: 0|1}` (CLS, FDP, STUN, AOP, PROT) also
  confirmed as a closed set — no additional booleans discovered.
- **2026-04-30** — Consumables runtime counter shape `{value: [int × 4]}` where
  any element > 1 discriminates from the 4-bool ambiguous set. Fake brush-reset
  test confirmed: only index 1 changed from `[3084, 3084, 0, -1]` to
  `[3084, 0, 0, -1]`.

### Deprecated readings

- ~~"`{value: 0|1}` is the Frost Protection toggle"~~ — partially right; FDP is
  one of the 5 keys that share this shape, but isolating which key flipped
  requires the getCFG diff.
- ~~"PRE has 10 elements per apk"~~ — true on g2568a; on g2408 PRE has only
  2 elements (zone_id, mode). The other 8 elements (cutting height, obstacle
  distance, coverage %, …) are BT-only on g2408 or live in a different slot.

### Cross-references

- Inventory: `s2p51_setting`
- Canonical: § s2p51 multiplexed config, § CFG keys

---

## Edge-mow FTRTS + wheel-bind discovery (2026-05-05)

> **Quick answer (current state):** Edge mow with `d.edge: []` (empty contour
> list) drains the firmware's edge-mode budget on irrelevant interior seam
> segments, causing wheel-bind + FTRTS on lawns with tight maneuvering spots
> near merged sub-zone seams. Always pass an explicit `[[map_id, contour_id]]`
> list (the Dreame app sends `[[1, 0]]` for outer perimeter only). Integration
> default is "all outer-perimeter contours from cached map" computed in
> `coordinator.dispatch_action`. Two new binary sensors surface the failure
> chain: `wheel_bind_active` (precursor) and `failed_to_return_to_station`
> (FTRTS condition itself).

### Timeline

Three live edge-mow runs on 2026-05-05 — two integration-launched, one app-
launched — produced a clean reproduction of an edge-mode-specific failure mode.

- **2026-05-05 run 1 (08:50 integration-launched, `edge: []`)** — mower entered
  a tight maneuvering spot (merged sub-zone seam in an eastern corridor ~13 m
  east of dock). Wheels physically stalled while the firmware's
  `area_mowed_cent` integrator advanced — visible on s1p4 33-byte frames as
  "position held within 50 mm AND `area_mowed_m2` advances by >0.05 m²".
  Firmware budget cap fired at `area_mowed_cent = 700` (= 7.00 m²) and
  `dist_dm = 10000` (= 1000.0 m) simultaneously. Auto-dock planner could not
  route home from the stuck pose: `s2p1: 5 → 2`, `s2p2: 48 → 31` (Failed to
  return to station). FTRTS at ~6 min; phases 0→3.
- **2026-05-05 run 2 (09:17 integration-launched, `edge: []`)** — identical
  failure at the same eastern seam. Concrete capture (09:21:30 → 09:21:50):

  ```
  pos held at (+12.44, -2.51) ±5 cm across 4 consecutive frames
  area_mowed:  4.30 → 6.38 → 6.72 → 6.98 → 7.05 m²
  distance:    517 → 815 → 851 → 877 → 887 m
  ```

  Δarea / Δposition ratios are physically impossible (~30 m/s of "mowing
  speed" while the mower is stationary). FTRTS again at ~6 min.

- **2026-05-05 run 3 (09:45 app-launched, `edge: [[1, 0]]`)** — same firmware,
  same lawn, same cap value. App's explicit outer-perimeter-only contour list
  skipped the seam contours; budget was spent on the actual outer perimeter.
  Cap fired *after* the mower had moved past the contentious area. Reached
  phase 0→7 over ~15 min and docked cleanly. Success vs FTRTS from a single
  input field change.

**Detection signature** (`protocol/wheel_bind.py`): position held <50 mm AND
`area_mowed_m2` advanced >0.05 m² across ≥2 consecutive 33-byte frames.
Surfaced as `binary_sensor.dreame_a2_mower_wheel_bind_active` (PROBLEM class,
diagnostic). 2-frame threshold avoids false positives on pivot turns.

**Integration mitigations applied**:

- `_edge_mow_payload` defaults to "every outer perimeter contour" (entries in
  cached `MapData.available_contour_ids` with second-int = 0) instead of empty
  list. Matches the app's behaviour and prevents seam tracing from using the
  budget.
- `binary_sensor.wheel_bind_active` surfaces the precursor signal so users /
  automations can react before the cap fires (e.g. pause and physically free
  the mower).
- `binary_sensor.failed_to_return_to_station` (PROBLEM, on `error_code == 31`)
  surfaces the FTRTS condition itself; an automation can issue Recharge.

### Deprecated readings

- ~~"Empty `edge:[]` means 'edge every contour in the current map'"~~ — wrong;
  empty list traces internal merged-sub-zone seams, draining budget on
  invisible-in-app interior segments.
- ~~"Edge-mode firmware budget is per-task and unreachable"~~ — wrong; observed
  to fire at exactly `area_mowed_cent = 700, dist_dm = 10000` (= 7.00 m² /
  1000.0 m). Both caps are tied to the same underlying integrator.

### Cross-references

- Inventory: `s2p50_task`, `s1p4_33b_area_mowed_centiares`, `s1p4_33b_distance_dm`
- Canonical: § Routed-action opcodes (o:101 edgeMower), § s2p2 state codes (31)

---

## `s2p50` op-code catalog — incremental decode

> **Quick answer (current state):** s2p50 echoes the mower's TASK responses.
> 14 op-codes documented (3=cancel, 6=recharge, 100=mow start, 101=edge,
> 102=zone, 103=spot, 109=task-start-failed, 204=map-edit-request,
> 215=map-edit-confirm-old, 218=delete-zone, 234=save-zone-geometry,
> 401=takePic, -1=error-abort-cleanup, 6 partial). The full catalog is in
> canonical's "Routed-action opcodes" chapter; the journal carries the
> incremental discovery history.

### Timeline

- **2026-04-20** — first systematic catalog. Ops 3 (cancel), 6 (recharge),
  100 (mow start), 109 (task-start-failed, status:False), -1 (abort cleanup)
  confirmed from the full-day capture. Op 204 (map-edit request) and 215
  (map-edit confirm) observed at 17:15:41 when the user resized an exclusion
  zone from the Dreame app.
- **2026-04-22** — op 101 (edgeMower) confirmed with group_id echo.
- **2026-04-26** — ops 218 (delete-zone) and 234 (save-zone-geometry)
  distinguished via deliberate add/edit/delete tests. Also confirmed op 102
  (zoneMower) and op 103 (spotMower). Echo format for 103: `{area_id: [N],
  exe:T, o:103, region_id:[], status:T, time:N}`.
- **2026-04-27** — op 401 (takePic) confirmed. Two distinct firmware echoes
  observed: (a) docked → `{o:401, exe:true, status:true, error:0}` — accepted
  but silently skipped; (b) BT-disconnected manual-mode-stopped on lawn →
  `{o:401, exe:true, status:false}` — rejected outright. Dreame app's Take
  Picture uses a separate cloud HTTP / OSS path, not op 401.
- **2026-05-05** — confirmed echo can drop entirely under cloud load: the
  wedged-edge recharge that fired no `o:6` echo. `s2p50` delivery is lossy
  under load. Detection of Recharge must lean on `s2p1: ?→5→6` + `s3p2 → 1`,
  not on the s2p50 echo.

### Deprecated readings

- ~~"s2p50 o:6 echo reliably signals a Recharge command"~~ — wrong; confirmed
  silent on 2026-05-05 09:24 for an app-tapped Recharge that successfully drove
  the mower home. Echo is delivery-best-effort.
- ~~"status:False in s2p50 means hard abort"~~ — incomplete; status:False also
  appears on o:401 takePic-rejected (which is not an abort, just a refusal). The
  combination `(status:False, o:109)` means task-start-failed; `(status:False,
  o:401)` means command-refused-state-mismatch.

### Cross-references

- Inventory: `s2p50_task`
- Canonical: § Routed-action opcodes

---

## Map-fetch flow — `s6p1` / event_occured / OSS

> **Quick answer (current state):** The mower pushes the map to OSS at
> recharge-leg-start (`s6p1 = 300`). Three distinct OSS-mediated payloads
> share this flow: MAP blob, session-summary JSON (per `event_occured`), and
> LiDAR PCD (per `s99p20`). Architecture diagram is in the slim protocol doc
> §4; per-event piid catalog and OSS object-key schema are in canonical
> § Session-summary fields and § OSS map blob keys.

### Timeline

- **2026-04-17** — first partial map captures. Upstream A1 Pro client DID fetch
  the A2's map successfully (file `map_live.png`), so the OSS side of the flow
  was confirmed to work. `s6p1` and `s6p3` observed but trigger conditions
  unclear.
- **2026-04-19** — **key discovery**: the session-summary OSS object key arrives
  not as an `s6p3` property-change but inside an `event_occured` MQTT message
  that the integration was never listening for. This unblocked session-summary
  fetching. Four `event_occured siid=4 eiid=1` messages captured across
  2026-04-17 / 2026-04-18 after this was understood.
- **2026-04-20** — full-run capture (07:58 → 12:33, two auto-recharge
  interrupts). Mechanism fully clarified:
  - `s6p1 = 300` fires at the exact ms `s2p2 → 54`, `s2p1 → 2 → 5` (at each
    recharge-leg-start). Confirmed twice at 09:14:09 and 11:13:04.
  - `event_occured siid=4 eiid=1` fires once at session end (12:33:12 — 3 s
    after `s2p2 = 48`). Carries the session-summary OSS key as piid=9.
  - `s6p1 = 300` is **not** a session-completion signal — it's a
    recharge-leg-start signal. Earlier doc claim corrected.
  - The 2026-04-20 run produced two `s6p1 = 300` pushes (per recharge
    interrupt) plus one `event_occured`.
- **v2.0.0-alpha.19** — integration adds proactive cloud-map poll at session
  starts, BUILDING completions, dock departures, and map-edit confirms, since
  these inflection points don't emit `s6p1 = 300`. All 5 poll paths funnel into
  `_build_map_from_cloud_data` which md5-dedupes no-change results.

### Deprecated readings

- ~~"`s6p1 = 300` is a session-completion signal"~~ — wrong; it's a
  recharge-leg-start signal. Session completion uses `event_occured siid=4
  eiid=1`.
- ~~"`getOss1dDownloadUrl` is the OSS fetch endpoint"~~ — wrong on g2408;
  returns 404. Use `getDownloadUrl` (the "interim" endpoint).

### Cross-references

- Inventory: `s6p1_map_ready`, `s6p3_oss_key`, `s99p20_lidar_key`
- Canonical: § Session-summary fields, § OSS map blob keys, § Map-fetch flow

---

## `cfg_individual` MISTA reversal (2026-05-06)

> **Quick answer (current state):** Mission-status endpoint MISTA returned r=-1 in
> cloud dumps 1 and 2, then a successful payload `{fin:0, prg:0, status:[[1,-1]], total:0}`
> in dump 3. Established empirically that r=-1 / r=-3 responses are stateful or
> transient, NOT proof of feature absence. Triggered an axis-1 hardening pass that
> downgraded all 7 `not_on_g2408:true` rows to `decoded:hypothesized` and added a
> consistency-check audit that catches this drift class.

### Timeline

- **2026-05-04** — first cloud dump captured. AIOBS, MAPD, MAPI, MITRC, OBS, PRE, MISTA
  all returned errors (r=-3 or r=-1). Inventory rows marked `not_on_g2408: true`,
  `decoded: confirmed`.
- **2026-05-05** — second dump captured; same error responses; conclusion held.
- **2026-05-06** — third dump captured; MISTA returned a valid payload. Reviewer
  spotted the contradiction during axis-2 brainstorming.
- **2026-05-06** — axis-1 hardening pass: all 7 rows downgraded to
  `decoded: hypothesized`, `not_on_g2408: false`. Consistency-check audit added
  (`tools/inventory_audit.py --consistency`) that flags any `not_on_g2408:true` row
  with an `ok` response in any dump. Three new tests in
  `tests/tools/test_inventory_audit_probe.py`. Acceptance criterion #12 added.

### Deprecated readings

- ~~"r=-3 means the endpoint is not supported on this firmware"~~ — wrong; r=-3 is
  stateful or transient. Sample-of-3 was insufficient.
- ~~"endpoints returning errors should be marked `not_on_g2408: true`"~~ — wrong;
  insufficient negative-evidence threshold. New rule: only mark `not_on_g2408: true`
  when there's a positive corroborating signal (apk explicitly says "vacuum-only",
  or the integration tested a known-write and the device rejected it).

### Cross-references

- Inventory rows: `MISTA`, `AIOBS`, `MAPD`, `MAPI`, `MITRC`, `OBS`, `PRE` (the
  `cfg_individual.PRE` row, distinct from `cfg_keys.PRE`)
- Canonical: § cfg_individual endpoints
- Audit code: `tools/inventory_audit.py` `_consistency_check` function
- Spec: `docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md` §6
  acceptance criterion #12

---

## g2408 vs upstream divergence

> **Quick answer (current state):** g2408's MQTT property surface diverges from
> upstream Tasshack's vacuum-derived mapping at two critical slots: s2p1 and
> s2p2 are SWAPPED. Plus 12 new-to-g2408 (siid, piid) combos that upstream
> doesn't define. The integration's overlay corrects the swap; new-g2408 slots
> get explicit decoder entries (heartbeat, telemetry, multiplexed config,
> obstacle flag).

### Timeline

- **2026-04-17** — `probe_log_20260417_095500.jsonl` analysed. 18 distinct
  (siid, piid) combinations observed across 2443 messages. 6 match upstream
  names; 12 are new-to-g2408. Critical finding: upstream's `(2, 1)=STATE` and
  `(2, 2)=ERROR` are swapped on g2408. Overlay landed in alpha-overlay-c.
- **2026-04-23** — apk decompilation cross-walk confirmed the swap (apk says
  s2p1 = "Status" enum and s2p2 = "Error code"). The overlay is correct.

### Divergence catalog (historical seed — 2026-04-17)

The table below is the original catalog from the first probe-log analysis.
Current authoritative list lives in `inventory.yaml`.

| siid.piid | events | example values | upstream name at same siid.piid | classification |
|-----------|--------|----------------|---------------------------------|----------------|
| 1.1 | 884 | list(len=20) | — | New (blob) |
| 1.4 | 1125 | list(len=33); list(len=8) | — | New (blob) |
| 1.50 | 2 | `{}` | — | New (session marker) |
| 1.51 | 2 | `{}` | — | New (session marker) |
| 1.52 | 2 | `{}` | — | New (session marker) |
| 1.53 | 87 | False; True | — | New (boolean) |
| 2.1 | 11 | 1; 2; 5 | STATE | Match-but-different-semantics |
| 2.2 | 9 | 48; 54; 70 | ERROR | Divergence (g2408 emits state codes here) |
| 2.50 | 3 | `{d, t}` keys | — | New (session event) |
| 2.51 | 49 | `{end, start, value}`, `{time, tz}` | — | New (multiplexed config) |
| 2.56 | 4 | `{status}` keys | — | New (status push) |
| 3.1 | 239 | 90; 91; 92 | BATTERY_LEVEL | Match |
| 3.2 | 7 | 0; 1; 2 | CHARGING_STATUS | Match |
| 5.105 | 3 | 1 | — | New (unknown telemetry) |
| 5.106 | 8 | 3; 5; 7 | — | New (unknown telemetry) |
| 5.107 | 6 | 133; 176; 250 | — | New (dynamic, unknown) |
| 6.1 | 1 | 300 | MAP_DATA | Match |
| 6.2 | 9 | list(len=4) | FRAME_INFO | Match |

**Totals:** 18 distinct g2408 siid/piid combinations. 6 already match upstream
names (but see 2.1/2.2 semantic swap). 12 are new to g2408.

### Deprecated readings

- ~~"s2p1 is STATE; s2p2 is ERROR"~~ — upstream Tasshack vacuum-derived mapping;
  g2408 has them swapped. Overlay added 2026-04-17, confirmed by apk 2026-04-23.
- ~~"1.50, 1.51, 1.52 are session boundary markers"~~ — apk says 1.51 is a
  dock-position-update trigger and 2.52 is a mowing-preference-changed trigger.
  The "brackets a session" hypothesis was wrong; see apk cross-walk findings
  topic for the correction.

### Cross-references

- Inventory: `s2p1_mode`, `s2p2_state`, `s1p1_heartbeat`, `s1p4_telemetry`,
  `s2p51_multiplexed_config`, `s1p53_obstacle_flag`
- Canonical: § Properties table, § s2p1 mode enum, § s2p2 state codes
- Journal topic: [s2p1 mode + s2p2 state codes — what's enum vs error](#s2p1-mode--s2p2-state-codes--whats-enum-vs-error)

---

## apk cross-walk findings

> **Quick answer (current state):** apk.md (TA2k/ioBroker.dreame) decompilation
> revealed the routed-action wrapper as g2408's primary write surface, the full
> opcode catalog (op 0-503), the PRE 10-element schema (g2408 only uses 2 of
> the 10 — the rest are BT-only or vacuum-only), and corrected several upstream
> property mappings. apk.md targets g2568a so binary-frame layouts need
> g2408-specific validation; semantic findings (action call routing, CFG keys,
> opcodes) port correctly because the React Native plugin is shared across
> mower models.

### Timeline

- **2026-04-23** — apk cross-reference doc captured 14 sections of findings:
  routed-action surface, full opcode catalog, settings (CFG / PRE / CMS),
  parseRobotState bitfield, MAP data structure, BLE characteristics, plus a
  prioritised action-items list.
- **2026-04-24** — apk-corrected pose decoder (20-bit packed, not int16_le)
  validated against probe corpus; alpha.98 fix removes scattered `0.625`
  magic factors.
- **2026-05-05** — apk's full opcode catalog populated `inventory.yaml` opcodes
  section (Task 14 of axis 1 plan).
- **2026-05-06** — residual content (g2568a-vs-g2408 caveats, action-items list
  remainders) folded into this journal topic. Source file deleted.

### Key apk findings and their resolution status

**s2p1 / s2p2 correction:** apk confirmed s2p1 = "Device Status" enum and
s2p2 = "Error Code" — matching the swap in the divergence catalog. The
integration's overlay is correct.

**s2p52 correction:** apk says s2p52 is a "Mowing Preference Update" trigger
(prompts app to re-fetch PRE settings via getCFG). Our earlier "session-end
marker" hypothesis was wrong — the "s1p50 + s2p52 brackets a session" model
is retired.

**s1p51 correction:** apk says s1p51 is a "Dock Position Update Trigger"
(signals loadDockPos()). Not a session-start marker. Protocol doc updated.

**Pose decoder (20-bit packed):** apk's `parseRobotPose` uses bytes 0-5 as
two 24-bit signed values sharing byte 2. The int16_le decode that was
originally used was "lucky" for small lawns (values fit in 16 bits). Fixed
in alpha.98. See [s1p4 telemetry decoder evolution](#s1p4-telemetry-decoder-evolution).

**PRE 10-element schema:** PRE is `[zone, mode, height_mm, obstacle_mm,
coverage%, direction_change, adaptive, ?, edge_detection, auto_edge]`.
On g2408 only elements 0 and 1 are writeable via cloud `{m:'s', t:'PRE'}`
(the rest are BT-only for g2408, or only apply to vacuum models). The
`getCFG → read-modify-write` pattern still applies for the two g2408 fields.

**Confirmed cloud endpoints (via action routing):** DOCK, MIHIS, LOCN, NET,
DEV — all confirmed via cloud dump analysis; several now wired as entities
(MIHIS in a75, LOCN already wired). DEV, DOCK, NET are open items in TODO.

**M_PATH userData key:** The mowing path is in a separate `M_PATH.0..N`
userData blob, not in `MAP.*`. Coordinates are ~10× smaller than MAP
coordinates (apply `×10` for map-frame projection). Not yet integrated;
relevant to the trail-loss-after-restart open item.

### Deprecated readings

- ~~"s2p52 is a session-end marker"~~ — wrong; it's a mowing-preference-changed
  trigger. Retired 2026-04-23.
- ~~"s1p50 + s2p52 bracket a session"~~ — same correction; not a session
  lifecycle pair.
- ~~"s1p51 is a session-start marker"~~ — wrong; it's a dock-position-update
  trigger.
- ~~"Y-axis is int16_le at bytes [3-4]"~~ — wrong; it's a 20-bit packed value;
  see s1p4 telemetry topic.

### g2568a vs g2408 caveats

- apk.md analyses **g2568a** firmware. Binary-frame layouts (especially
  s1p4 frame byte offsets beyond position) need g2408-specific validation.
- Semantic findings (action call routing, CFG keys, opcodes) port correctly —
  the React Native plugin is shared across mower models.
- `parseRobotTask` byte layout (bytes 22-31 = regionId, taskId, percent,
  total_uint24, finish_uint24) still needs empirical cross-check on g2408
  for the percent and regionId fields (area fields validated; percent not yet
  surfaced in integration).

### Cross-references

- Inventory rows: every row with `references.apk` populated (46 backfilled +
  9 added in axis 1's Task 14)
- Canonical: chapters that cite apk in their "See also" footer
- Slim protocol doc: §3 Routed-action surface
- Journal topic: [s1p4 telemetry decoder evolution](#s1p4-telemetry-decoder-evolution) (for pose decoder fix)

---

## Recently shipped — version timeline

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Recently shipped (a52 → a87)" section, with each version distributed under the topic it touched. This top-level section keeps the chronological view; per-topic context lives in each topic's Timeline.)_

---

## Live-confirmed status board

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Live-confirmed" bullet list)_
