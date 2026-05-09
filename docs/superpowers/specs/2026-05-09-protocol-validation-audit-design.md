# Protocol validation audit — design

**Date:** 2026-05-09
**Status:** Drafted, pending user review.
**Predecessor specs:** `2026-05-08-cloud-discovery-integration-design.md`,
`2026-05-08-cloud-write-integration-design.md` (the rewrite this audit
investigates).
**Successor:** Phase 2 — protocol coherence refactor (separate spec, not
written until this audit completes and surfaces a frontier).

## Problem

The integration has accumulated ~140 entities across switches, selects,
numbers, sensors, binary sensors, buttons, lawn_mower, services, plus
internal state populated from multiple cloud / MQTT sources. The
read-side mostly works ("most endpoints accessible on read"). The
write-side is uncertain for a number of entities — and the recent
chunked-batch rewrite (commit `3413170` and the cloud-write integration
spec from 2026-05-08) made an aggressive bet that `setDeviceData` could
be the unified write surface for everything previously addressed via
direct MIoT or routed-action setX. Live evidence over the last 24 hours
has refuted parts of that bet:

- v1.0.2a2 read entry -1 of SETTINGS as canonical based on a misdiagnosis
  in commit `db507c9`. Reverted to entry 0 in v1.0.2a3 after a
  controlled two-device test proved entry 0 is the user-saved entry.
- The "BT-only" classification covering AI Obstacle Recognition,
  Mowing Direction, Edge Mowing toggles, Obstacle Avoidance
  Distance/Height/Sensitivity, etc. was retracted on 2026-05-09 after
  a controlled two-device test showed every claimed BT-only setting
  in fact propagates through the cloud.
- Multiple "this can't work / must be BT-only / endpoint doesn't
  support this" historical conclusions turned out to be wrong endpoints,
  wrong URL paths, wrong JSON parsing assumptions, or stale captures.
- The user has identified that the rewrite *replaced* per-setting write
  paths that used to drive the device for at least some entities; the
  replacement (chunked-batch `setDeviceData`) updates the cloud cache
  but it's not yet established whether the device firmware applies it.

The integration also has multi-source entities by design: a single user-
visible setting (e.g. mowing height) may be addressable via MQTT
property push (`s6p2[0]`), via cloud SETTINGS (`mowingHeight`), and
sometimes via a routed-action getX. Today the integration picks one of
these per entity, but no document captures *why* that choice was made
or which source is right for which use case.

**The 140 entities have not been collectively tested in a long time.**
We don't know which currently-passing assumptions about reads or writes
are still true; some have likely silently rotted across firmware or
integration updates without anyone noticing.

## Goals

1. **A complete, validated feature inventory.** Every Dreame app feature,
   every HA entity, every received MQTT slot, every cloud endpoint we
   call — captured in a single matrix with one row per feature.

2. **Hypothesis-validation discipline.** Existing claims (in code,
   `docs/research/`, `docs/research/historical/`, `inventory.yaml`) are
   treated as starting hypotheses with default trust ~90%. Each row's
   final tier comes from a live test run *now*, on the current firmware
   and integration version, regardless of how plausible the existing
   claim looked. Code/docs/git are inputs to test design, not substitutes
   for tests.

3. **Multi-source-aware row schema.** When a feature surfaces on multiple
   wires, the matrix records all sources in priority order, plus the
   recommended-strategy-per-use-case (cold start / live operation / sanity
   check). The follow-on refactor (Phase 2) will use this to rationalise
   the integration's read paths.

4. **Write-path collective insight.** Each write-capable feature is tested
   end-to-end (HA writes → cloud → device → app). Patterns that emerge
   across rows are captured (e.g. "setDeviceData accepts but doesn't
   apply for X-class settings" — if that turns out to be true). The
   cumulative result tells us whether the chunked-batch write surface is
   genuinely insufficient for some classes, and what the right write path
   is per class.

5. **Regression-resistant documentation.** Each row carries a
   verification stamp (date / firmware version / integration version /
   commit hash) and enough wire-format detail (sample MQTT payload,
   sample cloud JSON, sample RPC request) that any future change to the
   relevant code without re-citing this row is a visible regression
   risk. The intent: stop the "rewrite assumed X, broke Y, no one noticed
   for weeks" pattern.

6. **Clear next-steps frontier.** The matrix exits as the source of
   truth for what's verified vs uncertain vs broken. Each `⚠`/`✗`/`?`
   row becomes a candidate for Phase 2 (refactor) or Phase 3 (write-path
   repair / app-RPC capture).

## Scope

### In scope

- All 140+ HA entities in the integration (switch, select, number, sensor,
  binary_sensor, button, lawn_mower, device_tracker, camera, event,
  plus the public services).
- All MQTT slots received by the integration that are wired into
  `PROPERTY_MAPPING` (`property_mapping.py`) or handled in the s2p51
  multiplexed-config decoder (`config_s2p51.py`).
- All cloud endpoints called by `cloud_client.py`:
  chunked-batch `getDeviceData` / `setDeviceData`, routed-action `s2.50`
  with each `t=` target the integration uses, MIoT direct
  `set_property` / `get_properties` (where used at all), the auth /
  session / device-discovery flow.
- Read paths AND write paths.
- Multi-source mapping: when a feature has more than one valid source,
  document all of them with their relative priority for cold-start,
  live, and sanity-check use cases.
- Git archaeology of each write path's evolution across the chunked-batch
  rewrite — used as a hypothesis-generation input only, not as evidence.
- App-side testing where required (controlled toggle, cold-start
  verification, two-device propagation check). User drives these
  interactively.

### Out of scope

- Code changes beyond minor wiring fixes if a test trivially exposes a
  bug. This is an audit, not a refactor.
- The architectural refactor of `coordinator.py` (175 KB) — Phase 2.
- New entities for currently-unsurfaced data unless trivially small
  (e.g. one-line additions to existing entity tables). Larger additions
  go in Phase 2.
- Exhaustive APK reverse-engineering. We probe APK references only when
  a test surfaces a missing endpoint that blocks evidence for an
  in-scope row.
- Performance tuning (poll cadence experiments are in scope only when
  evidence shows the current cadence is wrong).
- LiDAR camera / dashboard / Lovelace card visuals.

### Hard constraints

- "BT-only" terminology is banned. The 2026-05-09 retraction stands.
- No cell in the matrix is marked `✓` without a *current* live test, no
  matter how plausible the existing claim looked.
- Pre-production status: breaking changes are encouraged when they are
  clearly correct. The audit should not preserve incorrect entity
  shapes for backward compatibility.
- Single-instance deployment: tests can be run live without coordinating
  with other operators.

## Methodology

### Evidence tiers

| Tier | Meaning |
|---|---|
| `✓ live <date> / fw <ver> / int <ver>` | Verified by a live test run within the audit window. The ONLY tier that counts as evidence. |
| `⚠ hypothesis from <source>` | From code, docs, git, APK reference, or pre-rewrite history. Useful for designing tests; never the final answer. |
| `✗ live <date>` | Actively disproved by a live test. |
| `? unknown` | Not yet investigated. |

There is no tier for "code looks right" / "this row's logic is the same
as another verified row" / "git history says it once worked." Those
remain `⚠` until tested live.

### Test patterns (named)

- **T0 — Git archaeology.** For each write target, run `git log -p` on
  the relevant function. Identify the pre-rewrite path. Records as
  hypothesis input only.
- **T1 — Cloud snapshot.** `python3 /tmp/snapshot_cloud.py <label>` —
  read SETTINGS / CFG / batch keys at a moment in time.
- **T2 — MQTT probe scan.** `grep` the latest probe log around a time
  window for slots of interest.
- **T3 — App-save observation.** User toggles ONE thing in the Dreame
  app and Saves. Snapshot before + after, scan MQTT for fires, diff
  cloud surfaces. Records: which slot fired, what changed in cloud,
  propagation latency.
- **T4 — HA-write end-to-end.** HA toggles a setting; immediately
  snapshot cloud; then user cold-starts a fresh app instance (second
  phone or force-quit-and-relaunch). Check whether the cold-started app
  shows HA's value. Records: cloud accept yes/no, device-apply yes/no
  (inferred from the cold-started app), app-cache yes/no.
- **T5 — Two-device cloud propagation.** Used when no MQTT signal exists
  and we need to verify a write reached cloud authoritatively.
- **T6 — Read-only liveness.** Trigger the underlying physical / state
  event and observe the MQTT push slot or polled cloud field.

### Per-feature workflow

```
For each row:
  1. Read code + docs/research/* + docs/research/historical/* + inventory.yaml.
     Record the existing claim as a starting hypothesis.
  2. Apply T0 — git archaeology — only if the row is write-capable
     and the rewrite touched the relevant code.
  3. Apply T1 + T2 — passive cloud snapshot + MQTT probe scan,
     to establish current state and recent activity.
  4. Design the SHARPEST test for the unanswered question:
     read-only?    → T6 (trigger the physical event)
     write-capable → T3 (app-side reference behavior) + T4 (HA-side propagation)
     multi-source  → T3 — observe which sources update simultaneously
  5. Run the test. Record result with evidence stamp.
  6. Inline-document the row sufficiently for regression detection:
       wire format (bytes / JSON shape, with one captured sample)
       all known sources, in priority order
       per-use-case strategy (cold-start / live / sanity check)
       test recipe (so anyone can re-run it)
       verification stamp (date / fw / int / commit)
  7. If a contradiction surfaces (doc said X, test showed Y):
       update the row to reflect reality
       open a "next steps" line item for whatever caused the divergence
       update docs/research/g2408-research-journal.md with the finding
```

### Documentation contract per row

Each entity carries enough detail in its matrix row that any future
change to its read or write path without citing the row is a visible
regression risk:

- **Wire format**: exact JSON / bytes / decoded fields, with at least
  one captured live sample (timestamp, fw version).
- **All sources** known to carry the value, with priority for
  cold-start / live / sanity-check use cases.
- **Test recipe**: explicit steps to re-verify (a future-me / a
  contributor / a CI job can re-run it).
- **Verification stamp**: integration version, firmware version, date,
  commit hash of the spec at verification time.

The intent: a code change touching `coordinator.write_settings` should
visibly require updating the relevant matrix rows or explicitly
invalidating their stamps. Without this, the next "groundbreaking find
+ rewrite" cycle silently breaks things again.

## Matrix schema

One row per *user-visible app feature*, organised by app screen.
Columns:

| Column | Purpose / format |
|---|---|
| Feature | App-side name, e.g. "AI Obstacle Recognition: Animals" |
| App screen | Path: "Mowing settings → AI Obstacle Recognition" |
| HA entity | `entity_id` or "MISSING" |
| Read sources (priority) | Ordered list. Each entry: `MQTT s<N>p<M>[<idx>]` / `cloud SETTINGS.<path>` / `cloud CFG.<key>` / `routed-action g.<TARGET>.<path>` / `derived` |
| Live mechanism | `live MQTT push` / `cloud poll @<cadence>` / `mixed` (priority: live first, poll fallback) / `n/a` |
| Live latency | Verified worst case: `≤5s via MQTT`, `≤2 min via poll`, etc. |
| Cold-start strategy | Which source to prefer at integration startup (typically the cloud snapshot, since MQTT push hasn't arrived yet) |
| Sanity-check strategy | Which source to cross-check against the live one (e.g. "every 10 min, re-fetch cloud SETTINGS, alert on divergence") |
| Write — current path | `coordinator.<method> → <RPC>` with exact endpoint + payload shape |
| Write — pre-rewrite path | If different, the path the code used pre-`3413170`. `(unchanged)` if same. |
| Write — verified outcome | `✓ end-to-end / ✗ cloud-accept-no-device-apply / ? untested / n/a` |
| Caveats | Edge cases, dependencies (e.g. "requires `_active_map_id` set"), known firmware version range |
| Last verified | Date / fw version / int version / spec commit |
| Test recipe | Terse steps: "Toggle in app → snapshot cloud → verify s6p2[2] within 10s, cloud SETTINGS.obstacleAvoidanceAi within 2 min" |

Wide rows (large RPC payloads, multi-byte MQTT decodings) point to a
sidecar evidence file in `docs/research/wire-captures/<feature>.md`.

## Working order

### First pass — full skeleton, low rigor

For every HA entity and every MQTT slot wired into PROPERTY_MAPPING,
populate the matrix from code reading alone. ALL rows start at
`⚠ hypothesis (first pass <date>)`. This gets us a complete table where
every cell is either evidenced (in the second pass) or visibly
unverified.

### Second pass — per-category deep verification

In priority order, lowest-risk and lowest-effort first:

1. **Read-only telemetry.** Battery, charging status, position, area
   mowed, error code, obstacle flag, mowing phase, dock state,
   schedule_count, plus the s1p1 byte-bit sensors (drop_tilt, lift,
   bumper, emergency_stop, safety_alert, top_cover_open, battery_temp_low).
   ~20 rows. Single mowing session under probe gives evidence for most.

2. **Read-only state machine.** Mower state enum, charging status,
   active selection, session active, dock-in-region, mower-in-dock.
   Observed during state transitions in normal use.

3. **CFG-backed settings via s2p51 push.** DND, BAT, ATA, LIT, REC,
   MSG_ALERT, VOICE, FDP, STUN, AOP, PROT, WRP, LOW, LANG, VOL, PRE, CLS.
   ~17 rows. Per row: T3 (toggle in app, observe MQTT + cloud) + T4 (HA
   write, cold-start app verify). 17 × 2 = 34 controlled tests.

4. **SETTINGS-backed (Mowing settings page).** mowing_height,
   cutter_position, cutter_position_height, edge_mowing_num,
   obstacle_avoidance_height/distance/sensitivity, ai_obstacle_recognition
   {humans,animals,objects}, mowing_direction, mowing_pattern,
   edge_walk_mode, obstacle_avoidance_enabled, edge_mowing_{auto,safe,
   obstacle_avoidance}. ~13 rows. Same pattern as #3.

5. **AI_HUMAN.0** — single bool. 1 round trip.

6. **SCHEDULE.** One slot edit, one slot add, one slot remove, both via
   app and via HA `set_schedule_plans`.

7. **Action surface.** start/pause/stop/recharge/find_bot, mow_zone,
   mow_edge, mow_spot, suppress_fault, finalize_session, refresh_cloud_state,
   set_active_selection. Observed during real session use.

8. **Maps / multi-map / LiDAR.** Map switching, zone editing, lidar
   blob fetch. Separate, complex, last.

9. **Diagnostics + housekeeping.** novel_observations, freshness, endpoint
   log, hardware_serial, firmware_version, etc. Lowest priority.

### Estimated user effort

- 30-60 controlled toggles
- 4-8 cold-start app verifications
- 1 full mowing session under probe (covers many telemetry rows)
- Spread over 3-5 sessions

### Pivot trigger

If we are ~10 rows into the second pass and the per-row time is averaging
> 30 minutes, we pivot to writing the test plan as a deferred deliverable
(Plan B per the user's earlier preference). The matrix gets a `?` for
all remaining rows; the test plan describes the exact steps for any
future operator to fill them in.

## Risks + open questions

### Risks

- **Firmware update mid-audit** invalidates verifications. Mitigation:
  record fw per row; spot-check on next session; full retest of category
  if fw bumped.
- **Probe log gaps** (paho-mqtt reconnect drops). Mitigation: cloud
  snapshot as cross-check; if MQTT and cloud disagree, retest.
- **Test fatigue** — 60+ toggles is a lot. Mitigation: pivot trigger above.
- **HA-write end-to-end test** requires fresh app instance. Mitigation:
  user has a second device; force-quit-and-relaunch counts as fresh.
- **Audit may discover broken entities right now**. The audit doesn't
  fix them; produces a Phase 2/3 priority list.

### Settled (per pre-spec discussion)

- Audit-only first; code changes deferred to Phase 2. ✓
- Interactive driving with possible pivot to written test plan. ✓
- Order of work: telemetry → CFG → SETTINGS → schedule → action → maps/lidar → diagnostics. ✓
- "BT-only" terminology banned. ✓
- Evidence tier discipline (no inferred = ✓). ✓
- Multi-source rows record all sources with use-case strategies. ✓

### Open questions resolved during spec drafting

- **Replace `entity-sync-matrix.md` or create new file?** — Replace.
  The current file is partially fiction; explicitly retiring it is more
  honest than keeping a misleading sibling document.
- **Where do evidence stamps live?** — Inline in the matrix row for the
  small stuff (date / fw / int / commit). Wire captures (full sample
  MQTT frames, full RPC payloads) go in
  `docs/research/wire-captures/<feature>.md` to keep the matrix
  scannable.
- **Sample wire captures location** — `docs/research/wire-captures/`,
  one file per feature where a row's full evidence trace exceeds ~10
  lines.

## Definition of done

The audit is complete when:

1. Every HA entity has a row in the matrix.
2. Every MQTT slot wired into PROPERTY_MAPPING has at least one row
   referencing it.
3. Every cloud endpoint called by `cloud_client.py` has at least one
   row referencing it.
4. Every row has either:
   - `✓ live <date>` evidence (preferred), OR
   - `⚠ hypothesis` with a specific test recipe and a clear reason for
     not having tested yet (`physical event needed`, `paid feature`,
     `dependent on uncommon state`, etc.).
5. Every multi-source row lists all sources with priorities for
   cold-start / live / sanity-check.
6. Every write-capable row has a verified-outcome value
   (`✓ end-to-end`, `✗ ...`, `? untested`).
7. The journal (`docs/research/g2408-research-journal.md`) has at least
   one new entry per dated test session, capturing surprises and
   contradictions.
8. The next-steps frontier — list of `⚠`/`✗`/`?` rows — is captured in
   `docs/TODO.md` with each row scoped for Phase 2 (refactor) or
   Phase 3 (write-path repair / app-RPC capture).

The integration version at completion gets tagged in the spec ("audit
verified against `<int_version>` / `<fw_version>` as of `<date>`") so
later regressions reference a clear baseline.

## Outputs

- `docs/research/entity-validation-matrix.md` — the new authoritative
  matrix (replaces `entity-sync-matrix.md` which is retired with a
  stub-and-redirect).
- `docs/research/wire-captures/*.md` — sample wire captures, one file
  per feature where the trace is too large for inline.
- `docs/research/g2408-research-journal.md` — per-session findings.
- `docs/TODO.md` — next-steps frontier for Phase 2 / Phase 3.
- (No code changes beyond minor wiring fixes if a test trivially exposes
  a bug.)

## Non-goals (explicit, to prevent scope creep)

- We are NOT redesigning the coordinator architecture. Phase 2.
- We are NOT capturing the Dreame app's HTTPS traffic. Out of scope
  unless a row's evidence requires it.
- We are NOT building unit tests for every entity. The test recipes
  are user-driven live tests; turning them into automated tests is
  Phase 2 work.
- We are NOT shipping any version bump driven by the audit alone.
  Audit completion is a documentation milestone.
