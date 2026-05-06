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

> **Quick answer (current state):** _(filled in Phase C)_

### Timeline

_(filled in Phase C from OLD TODO.md "byte[10] bit 1 semantics" section + g2408-protocol §3.4)_

### Deprecated readings

_(filled in Phase C — wrong hypotheses crossed out)_

### Cross-references

- Inventory: `s1p1_b10_bit1`, `s1p1_b10_bit7`, `s1p1_b3_bit7`
- Canonical: § Heartbeat (s1p1) bytes

---

## s1p1 byte[3] bit 7 PIN-required clarification

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

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
