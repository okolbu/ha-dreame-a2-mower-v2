# Integration Audit — Overview & Block Decomposition

**Date:** 2026-05-19
**Status:** spec
**Scope:** the full `ha-dreame-a2-mower` integration repo (custom_component,
dashboard, user-facing docs)

## Background

The integration has shipped 16+ alpha releases since v1.0.0a, with many small
iterations layered on top of each other (CloudState rewrite, multi-map phase 2,
state-machine audit/remediation, session-data-completeness, path-rendering
overhaul). The recent **path-rendering audit** found significant dead code and
inconsistencies inside one bounded subsystem — confirming that a broader audit
of the rest of the integration is overdue.

This spec lays out *how* the audit is organised so each block is bounded,
deliverable, and independently reviewable. It does **not** enumerate the
specific findings — those come from each block's discovery doc.

## Goals

1. Identify and remove **dead code** (unused branches, leftover migration
   scaffolding, retired entities, orphan registry fields).
2. Identify **duplication / divergent implementations** of the same concept
   (e.g. two retry loops, two settings-write fan-outs).
3. Identify **overly complex or long functions/files** that should be split or
   simplified, and flag concrete refactor targets with rationale.
4. Identify **easier/better implementations** of existing behavior (when a
   newer Python/HA API, or a cleaner internal helper, makes current code more
   complex than it needs to be).
5. Identify and **propose fixes for actual bugs** discovered during the audit
   (not introduce new ones).
6. Confirm **documentation accuracy** — README + user docs reflect current
   state; protocol/research docs are either current or moved to `historical/`.
7. Confirm **dashboard completeness** — every user-relevant entity is shown
   somewhere, dead references are removed.

## Non-goals

- No new features.
- No protocol/cloud-API/MQTT changes (upstream wire is fixed).
- No test-coverage drive as a separate phase. Tests are added opportunistically
  when a remediation removes or restructures behavior.
- No `tools/` directory audit (dev-only utilities, separate scope).
- No `archive/` package archaeology beyond confirming it's still referenced.

## Hard constraint — no regression

**Every remediation must preserve existing user-visible behavior.** This is the
overriding rule. Concretely:

- Entity unique_ids, entity_ids, device identifiers, and state values stay
  stable. Renames need an `entity_registry` migration step or are deferred.
- Service signatures (`services.yaml`) and event payloads stay stable.
- Dashboard entity references resolve after every step.
- Session-archive on-disk format stays readable; new fields are additive.
- Settings-write semantics are unchanged unless the change is documented as a
  bug fix.

If a cleanup would break any of the above, it is either redesigned to be
non-breaking or flagged as a separate breaking-change proposal for the user to
accept before execution.

## Bug & refactor handling rules

During each block's discovery phase, findings fall into one of five buckets:

| Bucket | Disposition |
|---|---|
| **Dead code** | Remove in the block's remediation. |
| **Duplication / inconsistency** | Consolidate in the block's remediation. |
| **Refactor candidate** (long/complex/tangled) | Flag with concrete proposal (file split, function break-down, helper extraction). Execute in remediation only if low-risk; otherwise carve into its own follow-up spec. |
| **Bug** | Flag with reproduction + proposed fix. Fix in the block's remediation if the fix is localised; carve out if it crosses block boundaries. |
| **Better implementation available** | Flag with before/after sketch + rationale. Apply in remediation only if it's a clear win on both readability and behavior; otherwise leave a `# AUDIT: consider X` marker and a follow-up issue. |

Refactor candidates explicitly include:

- Files over ~800 LOC where the parts are not obviously one concept
  (`cloud_client.py` at 2197, `select.py` at 1990, `sensor.py` at 1499,
  `switch.py` at 1308, `map_render.py` at 1283, `camera.py` at 962,
  `state_machine.py` at 764).
- Functions over ~80 LOC, especially branching state-update functions in
  `coordinator/_property_apply.py`, `coordinator/_mqtt_handlers.py`,
  `mower/state_machine.py`.
- Files with mixed concerns (e.g. transport + decoding + business rules in one
  module).

## Approach — hybrid 1 + 4

One short meta pass that produces a shared architectural ground-truth doc,
followed by four focused audit→remediation cycles. Each cycle is its own
spec → plan → subagent-driven execute, the same pattern as the path-rendering
overhaul.

```
Meta (architecture inventory)
  └─ Block 1: Data pipeline
      └─ Block 2: Domain model + protocol
          └─ Block 3: Entity surface + services + observability
              └─ Block 4: Rendering + dashboard + user-facing docs
```

Sequential, not parallel — each block consumes the cleaned interfaces of the
previous one. Cross-block findings spotted early are captured in the overview
doc's "later-block backlog" section, not acted on until that block runs.

## Meta pass — architecture inventory

**Goal:** produce `docs/superpowers/specs/2026-05-NN-integration-audit-meta.md`
that subsequent blocks reference instead of rediscovering.

**Deliverables:**

1. **Module map** — every `custom_components/dreame_a2_mower/**/*.py` with a
   one-line purpose and current LOC. Highlights files > 800 LOC.
2. **Dependency graph** — which modules import which; identify import cycles,
   suspiciously fat fan-in modules, and orphan modules.
3. **Domain-concept ownership table** — for each concept (cloud-state, mower
   state, session, map, settings, schedule, lidar, wifi, observability):
   where the data is *acquired*, *stored*, *transformed*, *rendered*.
   One row per concept. Surfaces split ownership.
4. **Cross-cutting smells list** — findings that touch >2 blocks (e.g.
   "retry loop reimplemented in 4 places", "three different ways to schedule
   a delayed task"). Each smell tagged with which block(s) will resolve it.
5. **Later-block backlog** — items spotted incidentally that belong to a
   later block; deferred to keep blocks bounded.

**Effort:** half-day. Mostly read + tabulate, no code changes.

**No remediation step.** Meta pass output is read-only; remediations happen in
blocks 1-4.

## Block 1 — Data pipeline (coordinator + transport)

**Files in scope (~10K LOC):**
- `coordinator/` (15 modules, ~7K LOC)
- `cloud_client.py` (2197)
- `cloud_state.py` (128)
- `mqtt_client.py` (406)
- `_settings_writes.py`
- `_migration.py` (468), `_lidar_migration.py`

**Discovery focus:**
- Residual `_cached_*` and pre-CloudState code (memory: CloudState architecture
  shipped in v1.0.0a100; check what's still there).
- Duplicated retry / poll / backoff loops; consolidate to one helper.
- Refresher cadence — is every refresher still needed, do any overlap, is the
  10-min canonical refresh respected.
- `_property_apply.py` and `_mqtt_handlers.py` — branching state-update logic
  that's grown organically; identify split points.
- Settings-write fan-out — `_settings_writes.py` vs `_writes.py` vs entity
  `async_set_*` methods; one path or multiple.
- `cloud_client.py` at 2197 LOC — almost certainly multiple files (auth /
  device discovery / RPC / blob fetch / settings); produce a concrete split.
- Migration code: `_migration.py` and `_lidar_migration.py` — what's safe to
  delete given current installed versions (per memory: single-user dev,
  reinstall is fine, no over-engineering on migration).
- MQTT subscription lifecycle — confirm one path, no leaks.

**Deliverables:**
1. `docs/superpowers/specs/2026-05-NN-block1-data-pipeline-findings.md` —
   discovery doc with all findings categorised by bucket.
2. `docs/superpowers/plans/2026-05-NN-block1-data-pipeline.md` — remediation
   plan (subagent-driven, 15-20 tasks).
3. Execute the plan; ship commits with consistent prefix `audit-b1:`.

## Block 2 — Domain model + protocol

**Files in scope (~5.5K LOC):**
- `mower/` (8 files, ~2.2K LOC) — `state.py`, `state_machine.py`,
  `state_snapshot.py`, `actions.py`, `property_mapping.py`, `capabilities.py`,
  `error_codes.py`
- `protocol/` (21 modules, ~2.7K LOC) — telemetry, session_summary, schedule,
  pcd, cfg_action, settings, properties_g2408, etc.
- `map_decoder.py` (794)
- `wifi_archive_store.py` (321), `wifi_match.py` (190)

**Discovery focus:**
- Orphan `MowerState` fields (state-machine audit already flagged 48; resolve
  per the existing remediation plan or close them out).
- `property_mapping.py` ↔ `properties_g2408.py` ↔ `_property_apply.py`
  consistency — single source of truth for which property maps to what.
- Dead protocol decoders — anything in `protocol/` not imported, not exercised
  by tests, not validated against captured wire data.
- `state.py` (619) + `state_machine.py` (764) — two large overlapping modules;
  identify clear seam (e.g. snapshot vs transitions vs derivations).
- `map_decoder.py` (794) — likely splittable by frame type or by layer
  (lawn / zones / spots / edge / dock).
- Archive writer (`coordinator/_recorder_merge.py` + `coordinator/_session.py`)
  ↔ rebuild_session tool symmetry — confirm what archive carries vs what
  rebuild can synthesize.
- `cfg_action.py` and `config_s2p51.py` — known to have ioBroker reference; is
  the current implementation aligned with what TA2k actually does (per memory).

**Deliverables:** same pattern (findings doc + plan + execute). Commit prefix
`audit-b2:`.

## Block 3 — Entity surface + services + observability

**Files in scope (~8K LOC):**
- All entity platforms: `sensor.py`, `select.py`, `switch.py`, `number.py`,
  `binary_sensor.py`, `button.py`, `time.py`, `calendar.py`, `event.py`,
  `device_tracker.py`, `lawn_mower.py`, `logbook.py`
- `_devices.py` — device registry + per-map device naming
- `services.py` (711), `services.yaml`
- `observability/` (5 modules: registry, novel_store, log_buffer, schemas,
  freshness), `diagnostics.py`
- `strings.json`, `translations/`
- `_migration.py` re-check at the entity-registry boundary

**Discovery focus:**
- Orphan registry entries (recurring issue per memory: changing `unique_id`
  pattern creates a new entity + old one stays as "unavailable").
- Entity → property coverage: every property in `property_mapping.py` /
  `properties_g2408.py` is either surfaced as an entity, intentionally hidden,
  or flagged. Build coverage matrix.
- Per-map device naming consistency (CLAUDE.md rule: per-map devices must be
  `DEFAULT_NAME`-prefixed so entity_ids land in `dreame_a2_mower_map_N_*`).
- `select.py` at 1990, `switch.py` at 1308, `sensor.py` at 1499 — split by
  domain group (rain / DnD / cutter / anti-theft / etc.) or by data source
  (settings vs telemetry vs derived).
- Services in `services.yaml` ↔ `services.py` ↔ actual registered service —
  any orphan or undocumented one.
- `strings.json` keys ↔ actual entity translation keys — drift.
- Observability: `novel_store` + `log_buffer` + `registry` + `schemas` +
  `freshness` — five small files; confirm they form one coherent surface, not
  five parallel half-features.
- `logbook.py`, `event.py`, `calendar.py` — wired and emitting? Or scaffolds
  from earlier iterations?
- `diagnostics.py` — does the diagnostics dump still match current state
  shape; is anything redacted that shouldn't be (or vice-versa).

**Deliverables:** same pattern. Commit prefix `audit-b3:`.

## Block 4 — Rendering + dashboard + user-facing docs

**Files in scope (~9K LOC across code, YAML, docs):**
- Rendering: `map_render.py` (1283), `_render_direction.py`,
  `_render_dotted.py`, `_render_stripes.py`, `camera.py` (962),
  `live_map/` (3 modules), `wifi_map_render.py` (118), `session_card.py` (645)
- Custom Lovelace cards in `www/`
- Dashboard: `dashboards/mower/dashboard.yaml` (1714)
- User-facing docs: `README.md` (336), `CONTRIBUTING.md` (110),
  `docs/*.md` (TODO, cutover, data-policy, events, lidar, multi-map,
  observability, lessons-from-legacy)
- Research docs: `docs/research/*` (15+ files) — triage into `historical/`
  (already exists) vs current-truth.

**Discovery focus:**
- Post-path-rendering-overhaul dead code: `map_render.py`, `_render_*.py`,
  `camera.py`, `live_map/`, `session_card.py` likely still carry pre-overhaul
  branches. (Block 4's biggest single payoff.)
- Custom-card ↔ backend contract: every prop the cards read is still emitted
  by the entity; every backend field is consumed by a card or sensor.
- Dashboard completeness vs Block 3's entity inventory — every entity is
  either on the dashboard or explicitly excluded with a one-line reason.
- Dashboard dead references — entity_ids that no longer exist (orphan-rename
  history per memory).
- README catch-up: currently says "v1.0.0a release candidate"; integration
  is on v1.0.17a5 with multi-map phase 2, state-machine remediation, session
  rebuild tool, persistent novel log, replay animation, path-rendering
  overhaul, live-image card. Sections to add: multi-map walkthrough, replay
  card, session rebuild tool, observability surface. Sections to remove:
  obsolete phase table once integration is past 1.0.
- `docs/TODO.md` at 835 lines — triage: still relevant → keep, shipped →
  remove, deferred → keep with status.
- `docs/research/` triage — move stale/superseded research to `historical/`
  with a one-line header explaining what supersedes it.
- `CONTRIBUTING.md` accuracy.
- `data-policy.md` — confirm it reflects current data flow (CloudState,
  archives, observability).

**Deliverables:** same pattern. Commit prefix `audit-b4:`.

## Cross-block coordination

The meta-pass overview doc is the single source of truth that all four blocks
reference. Each block's findings doc cites overview entries by short label
(e.g. "see overview §domain-ownership.session") rather than re-stating them.

A block discovering something that obviously belongs to a later block does
**not** act on it. Instead it appends to the overview doc's
"later-block backlog" with a stable label, and the later block picks it up.

## Sequencing & dependencies

```
Meta → Block 1 → Block 2 → Block 3 → Block 4
```

Strict serial. Reasons:
- Block 1 changes coordinator interfaces; Block 2's domain model reads from
  the coordinator, so Block 2 starts from cleaned state.
- Block 3's entity surface reads from the domain model; cleaned model first.
- Block 4's dashboard reads from entities; cleaned entities first.
- README/docs catch-up sits in Block 4 so it documents the post-cleanup
  state, not a moving target.

Each block produces one or more **alpha releases** during execution (release
cadence per memory: push regularly, version bump as needed, but don't gate on
installability between intermediate steps). Final state at end of each block
must be installable and pass tests.

## Release / branch hygiene

- One git branch per block (`audit/block-1-data-pipeline` etc.), merged to
  main when block completes.
- Existing release.sh flow used as-is — every commit pushed to origin/main
  during execution per HACS pull rules in memory.
- Version bumps follow established ladder; remember a→a digit boundary
  triggers a patch bump (per memory: HACS string-sort quirk).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cleanup introduces regression | Hard-constraint rule above; every remediation step ends with `pytest` + a smoke run; user-visible surface compared before/after. |
| Block scope creeps | Findings doc is the contract; out-of-scope findings go to the overview backlog, not into the active block. |
| Audit findings exceed remediation capacity | Each block's remediation plan accepts that not every finding gets fixed; remaining ones become tracked TODO items with rationale. |
| Refactor candidate destabilises something | Each large refactor (file split, function break-down) is its own commit, reversible in isolation; if a refactor is risky it gets carved into a follow-up spec instead of bundled. |
| Multi-week elapsed time | Blocks are independent enough that pausing between blocks is safe; the overview doc carries state across pauses. |

## Open questions

(None for the overview itself. Per-block specs may surface their own.)

## What's next after the meta pass

After the meta pass produces the overview doc and the user signs off, Block 1
starts with its own brainstorm → spec → plan → execute cycle. The overview doc
is the durable artifact; per-block specs and plans live alongside it under
`docs/superpowers/`.
