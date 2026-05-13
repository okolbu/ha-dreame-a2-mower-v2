# State Machine Audit — Design

**Status:** Spec
**Date:** 2026-05-13
**Scope:** Audit-only. Produces documentation matrices + a remediation list. No production-code changes within this spec; the remediation list seeds a follow-up implementation plan.

## Problem

Five distinct state holders coexist in the integration. Entities split between them inconsistently, and several glitches cluster around HA restart:

- `MowerStateMachine` snapshot — persisted via HA `Store`, owns behavioural dimensions (session, activity, location, charging, positioning, connectivity, errors, battery%, position, RSSI, pin).
- `MowerState` dataclass (`mower/state.py`) — ~600 fields, **not persisted**, reset to `None` every restart. Several entities still read from here for fields that the snapshot also owns (battery%, charging status, position, error code).
- `LiveMapState` — persisted to `sessions/in_progress.json`; orthogonal.
- `CloudState` — ephemeral cloud cache (5–10 min lag on dock).
- Coordinator `_prev_*` edge-detection fields — in-RAM, transient.

Two concrete symptoms motivate the audit:

1. **`Battery=Unknown` while `Charging status=charging`.** Charging is read from `MowerState.charging_status` (synced back from the persisted snapshot on boot). Battery is read from `MowerState.battery_level`, which is **not** persisted and stays `None` until s3p1 next changes. Since s3p1 only pushes on change, a mid-charge restart leaves the entity Unknown indefinitely.
2. **Three dock-related surfaces** (`Location` sensor, `Mower in dock` binary, `In dock` orphan) where one is dead. The first two are intentional projections of the same snapshot field; the third is a stale entity_registry orphan from a prior rename.

Beyond these, several entities show `Unknown` after a restart (or while idle) where a meaningful idle value would be more useful: `Area mowed` should be `0` when no session is active, not Unknown; same for several session-scoped accumulators.

## Goals

- Produce three reference matrices that make the state model and its reboot behaviour fully legible.
- Ship a re-runnable verifier script (`tools/state_machine_audit.py`) that reports per-entity pass/fail across three checks: sourcing, idle expected value, reboot survival. Iterating fixes until the script shows all green is the success criterion.
- Surface every dual-source-of-truth entity and every cold-start glitch.
- Distinguish "Unknown is wrong" (rewire to persisted source) from "Unknown should be 0/N/A" (default to sensible idle) from "Unknown is honest" (mark unavailable).
- Output a ranked remediation list that seeds a follow-up implementation plan.

## Non-goals

- Implementation of the remediation fixes themselves. The audit defines the verifier and the targets it must hit; the follow-up plan executes the fixes against that verifier.
- Removing `MowerState` outright. SM-14 already removed several fields; further removal is a fix, not part of this audit.
- Touching `LiveMapState` or `CloudState` internals. They are catalogued but not the audit's primary focus.
- Touching the legacy `In dock` orphan; removal is a one-line WS API call documented in `feedback_entity_rename_orphan` and unrelated to the audit's design value.

## Deliverables

Three Markdown documents written to `docs/research/state-machines/`:

### Doc 1 — Per-dimension transition matrix (`transitions.md`)

One table per dimension owned by `MowerStateMachine`: `mow_session`, `current_activity`, `location`, `charging`, `positioning_health`, `mqtt_connectivity`, `errors`, `pin_required`. Columns:

| From | To | Trigger | Source (file:line) | Guards / invariants |
|------|----|---------|--------------------|---------------------|

Captures every override path, including covert ones (e.g. `_apply_battery_percent` setting `location=AT_DOCK`, `_apply_charging` doing the same, `_apply_cloud_dock` suppressing AT_DOCK during IN_SESSION+ON_LAWN, telemetry reconcile's mirror/inverse cases).

### Doc 2 — Reboot-survival + idle-value matrix (`reboot-and-idle.md`)

One row per **observable field** across all five state holders. Columns:

| Field | Holder | Persisted? | Restored from | Cold-start value | Idle expected value | Current idle behaviour | First overwrite source | Known glitch |
|-------|--------|-----------|---------------|------------------|---------------------|------------------------|------------------------|--------------|

"Idle expected value" is the prescriptive column — what the user *should* see when the mower is sitting at the dock with nothing happening. "Current idle behaviour" is what they actually see. Discrepancy → remediation candidate.

Three remediation buckets emerge:

1. **Rewire to persisted snapshot** — Unknown is worse than slightly stale (battery%, charging status, position, RSSI, error_code).
2. **Default to sensible idle** — accumulators that are structurally zero when no session is active (area mowed, current-session duration, distance this session, blade-on time).
3. **Mark `unavailable` deliberately** — values that are genuinely only valid mid-session or while online; show greyed-out, not Unknown.

### Doc 3 — Entity → field dependency matrix (`entity-sources.md`)

One row per HA entity registered by the integration. Columns:

| Entity name | Key | Platform | Holder | Field path | `value_fn` excerpt | Idle expected | Notes |
|-------------|-----|----------|--------|------------|--------------------|----------------|-------|

Sorted **by field**, so all entities reading the same concept group together. Reveals dual-source-of-truth entities at a glance (e.g. battery sensor reads from `MowerState`, position sensor reads from `MowerState`, but activity/location read from snapshot).

A "Found issues" section at the bottom enumerates remediations, ranked by impact, with file:line pointers.

## Method

The audit is structured as a **verifier**, not a one-shot report. The script can be re-run after any change and produces a pass/fail status per entity across three checks. The remediation loop is: fix one issue → rerun → see the row flip from red to green. When everything is green, the integration's state model is clean.

### Audit script: `tools/state_machine_audit.py`

Walks the entity description tuples in `binary_sensor.py`, `sensor.py`, `switch.py`, `select.py`, `number.py`, `time.py`, `device_tracker.py`, `event.py`, `button.py`, `camera.py`, `calendar.py`, `lawn_mower.py`. For each `*EntityDescription`, extracts: `key`, `name`, `value_fn` source (AST + source-text fallback for multi-line lambdas), `entity_category`, `device_class`. Builds a minimal fake coordinator with `state_machine = MowerStateMachine()`, `data = MowerState()`, `cloud_state = CloudState()` — all in their initial/empty form — and invokes each `value_fn` to observe its cold-start behaviour.

### Three checks per entity

1. **Sourcing — single source of truth.**
   Snapshot-owned dimensions (battery%, charging, location, activity, session, position, errors, RSSI, pin) **must** be read from `coord.state_machine.snapshot()`, not from `coord.data`. Entities reading `coord.data.<snapshot_field>` are flagged red. (`MowerState` is still the legitimate source for non-snapshot fields: settings, consumables, dock CFG, etc.)

2. **Idle expected value.**
   A sidecar `tools/state_machine_audit_expectations.yaml` declares per-entity expectations:
   ```yaml
   battery_level: { idle: persisted_value, on_unknown: red }
   area_mowed_m2: { idle: 0, on_unknown: red }
   live_map_legs: { idle: unavailable, on_unknown: green }
   ```
   The script invokes each `value_fn` against the cold-start fake coordinator and compares the result to the declared expectation. Mismatch → red. The sidecar is human-editable; ground-truth lives there, not in the entity definitions themselves (keeps `*EntityDescription` clean).

3. **Reboot survival.**
   For each entity, determine which fields its `value_fn` touches. Cross-reference against the snapshot's `to_dict` / `from_dict` field set. An entity reading a `MowerState` field that should logically survive reboot (i.e. expectation is `persisted_value`, not `0` or `unavailable`) is flagged red. Effectively a stronger form of check 1 — catches the battery-Unknown case directly.

### Output

Running the script produces three artefacts:

- **Console summary**: one line per entity, e.g.
  ```
  [GREEN] sensor.battery_level         source=snapshot   idle=persisted   reboot=ok
  [RED  ] sensor.area_mowed_m2         source=MowerState idle=Unknown    expected=0
  [RED  ] sensor.battery_level         source=MowerState idle=Unknown    expected=persisted_value
  ```
  Plus a trailing tally: `12 green / 4 yellow / 7 red`.

- **Generated markdown** at `docs/research/state-machines/entity-sources.md` (Doc 3) — the same matrix, regenerable.

- **Exit code** non-zero when any red rows exist, so the script can run as a CI / pre-release check once it's been brought to green.

Docs 1 (transitions) and 2 (reboot+idle) are hand-curated markdown — they describe semantics that an AST can't infer (the *why* of each transition, the prescriptive idle value). Doc 3 is fully regenerated by the script.

### Iteration loop

1. Initial run: many reds expected (battery rewire, area-mowed idle-zero, etc.).
2. Fix one entity (rewire to snapshot, change `value_fn` to return 0 on idle, or set `available` property).
3. Rerun script → that row flips green.
4. Repeat until tally is `N green / 0 red`.
5. The script becomes a regression check: any future entity that reads from the wrong source or defaults to Unknown when it shouldn't trips the build.

## Out-of-scope clarifications

- **`Mower in dock` binary sensor**: confirmed used only by the bundled dashboard (3 references) plus its own tests. **Keep it.** Cost is one lambda; benefit is cleanly-rendering boolean in dashboard cards + clean target for future automations. Same pattern as `mowing_session_active` (boolean projection of an enum). Documented in Doc 3, not flagged for removal.
- **`In dock` orphan**: stale entity_registry entry from a prior rename. Removal via WS `config/entity_registry/remove`. Documented in Doc 3 as "orphan — not an integration entity", not flagged for code change.

## Risks & open questions

- **Lambda introspection brittleness**: `value_fn` lambdas in entity descriptions are sometimes complex (multi-line conditionals). AST extraction may need to fall back to source-text grep for those — acceptable for a one-shot audit tool.
- **`MowerState` field count is large**. Doc 3 will list hundreds of entities. Sorting by field and collapsing repeated sources keeps it readable; the alternative (per-platform sections) hides cross-platform duplication.
- **Field-freshness column**: `MowerStateMachine` tracks per-field freshness timestamps. Including a "last MQTT update" column in Doc 2 would make the cloud-vs-MQTT precedence rules visible. Defer unless the basic matrix proves insufficient.

## Acceptance

- All three matrices exist at `docs/research/state-machines/{transitions,reboot-and-idle,entity-sources}.md`. Docs 1 and 2 are hand-curated. Doc 3 is regenerated by the script.
- Audit script exists at `tools/state_machine_audit.py` and reports per-entity status across the three checks (sourcing / idle / reboot). Initial run produces a non-empty red list with battery and area-mowed among the reds — that is the expected starting state and proves the verifier works.
- Expectation sidecar exists at `tools/state_machine_audit_expectations.yaml`, covering every entity.
- Script exits non-zero when red rows exist, so it can later be wired into a pre-release check.
- No production code under `custom_components/dreame_a2_mower/` is modified by this spec.
- Spec is committed; the verifier + initial red list seed a follow-up implementation plan whose acceptance is "verifier shows all green."
