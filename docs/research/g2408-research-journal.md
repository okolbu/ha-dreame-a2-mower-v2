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

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## s2p1 mode + s2p2 state codes — what's enum vs error

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## s2p51 multiplexed config — disambiguation evolution

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## Edge-mow FTRTS + wheel-bind discovery (2026-05-05)

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## `s2p50` op-code catalog — incremental decode

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## Map-fetch flow — `s6p1` / event_occured / OSS

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

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

> **Quick answer (current state):** _(filled in Phase E from `2026-04-17-g2408-property-divergences.md`)_

_(template; filled in Phase E)_

---

## apk cross-walk findings

> **Quick answer (current state):** _(filled in Phase E from residuals of `2026-04-23-iobroker-dreame-cross-reference.md`)_

_(template; filled in Phase E)_

---

## Recently shipped — version timeline

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Recently shipped (a52 → a87)" section, with each version distributed under the topic it touched. This top-level section keeps the chronological view; per-topic context lives in each topic's Timeline.)_

---

## Live-confirmed status board

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Live-confirmed" bullet list)_
