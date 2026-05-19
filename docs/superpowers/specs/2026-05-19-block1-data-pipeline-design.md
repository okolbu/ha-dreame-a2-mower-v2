# Block 1 — Data Pipeline Audit (Design)

**Date:** 2026-05-19
**Status:** spec
**Parent spec:** `docs/superpowers/specs/2026-05-19-integration-audit-overview.md`
**Ground truth:** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (the meta-pass output — cite by section number rather than re-deriving facts)

## Background

Block 1 is the first of four serial audit blocks. Its scope is the data
pipeline: how the integration *acquires* state from the cloud and the device,
*holds* it, and *applies* writes back. The meta pass surfaced 11 B1-specific
backlog items in § 5 plus multiple cross-cutting smells that implicate this
block. This spec turns those findings into an executable cycle.

## In-scope files (~10K LOC)

Authoritative list from `audit-overview` § "Block 1 — Data pipeline":

- `coordinator/` (15 modules, ~7K LOC) — see meta § 1 for per-file purposes
- `cloud_client.py` (2197)
- `cloud_state.py` (128)
- `mqtt_client.py` (406)
- `_settings_writes.py` (77)
- `_migration.py` (468), `_lidar_migration.py` (75)

## Goals

1. Eliminate known dead/dormant code in the pipeline (residual `_cached_*`,
   safe-to-delete migration scaffolding, dead branches in transport).
2. Consolidate duplicated retry/poll logic into one helper (meta § 4.1) and
   fix the stacked-loop amplification bug (3×3=9 effective attempts on action
   calls).
3. Fix the confirmed memory leak: `_cloud_refresh_debounce_handle` in
   `coordinator/_device_sync.py:291` is not registered with `async_on_unload`
   (meta § 4.2).
4. Remove the `_cached_maps_by_id` shadow state and route all reads through
   `CloudState.maps_by_id` (meta § 3 `map`/Stored, § 4.5 row 2).
5. Add minimal logging to the 14 silent `except Exception` swallows in
   `cloud_client.py:1835–1960` parse-batch block (meta § 4.3).
6. Consolidate the 5-line protocol import block + 1-line observability import
   line duplicated across all 9 coordinator mixins (meta § 4.5 → § 5 [B1]).
7. Split `cloud_client.py` (2197 LOC) into focused submodules:
   `_cloud_auth.py` + `_cloud_rpc.py` + `_cloud_oss.py` + `_cloud_discovery.py`
   (meta § 4.4 row 1, § 5 [B1] entry).
8. Confirm every interval/timer/task is cancelled on coordinator shutdown
   (meta § 4.2).

## Non-goals

- No protocol/cloud-API/MQTT changes (upstream wire is fixed).
- No new features.
- No changes to user-visible entity surface (unique_id, entity_id, friendly_name).
- No splits of the 4 coordinator files >800 LOC (`_core`, `_refreshers`,
  `_session`, `_mqtt_handlers`). These get named refactor plans in the
  discovery doc but execution waits — they're tangled internally and a wrong
  split is expensive. Revisit when B2/B3 demand it.
- No resolution of the B1/B2 boundary smells (`protocol/schedule.py` decode
  co-location with `cloud_client.fetch_full_cloud_state`, `_lidar_oss.py`
  Acquired+Transformed split). Deferred to Block 2 which owns the protocol
  side of those boundaries.
- No `cloud_state.py` schema changes. It's the canonical store; B1 routes
  reads to it, doesn't restructure it.
- No archive format changes (B2 owns archive shape).

## Hard constraint — no regression

Carried over from the audit overview spec. Concretely for Block 1:

- Every `unique_id`, `entity_id`, `device_identifier`, `friendly_name` is
  stable. No `async_migrate_entry` needed because nothing user-visible
  changes.
- Service signatures (`services.yaml`), event payloads, archive format
  unchanged.
- MowerState field shape unchanged. CloudState field shape unchanged.
- The 10-min canonical cloud-state refresh cadence unchanged.
- MQTT subscription topics and dispatch unchanged.
- Settings-write semantics unchanged unless documented as a bug fix in the
  per-phase plan (none planned in this cycle).

If a remediation would break any of the above it gets redesigned or pulled
out as a separate breaking-change proposal.

## Approach — discovery once, then 4 phased remediations

### Stage 1: Discovery

Deliverable: `docs/superpowers/specs/2026-05-NN-block1-data-pipeline-findings.md`

One read-through of the entire B1 surface. Every finding is categorised per
the meta-pass 5-bucket rule (dead code / duplication / refactor candidate /
bug / better-implementation available) and tagged with its target phase
(B1a/b/c/d) for remediation sequencing.

Specific things the discovery doc must surface (in addition to whatever it
discovers fresh):

- Every retry/poll loop in the B1 surface (cross-check meta § 4.1).
- Every scheduled task in the B1 surface and its cancellation status
  (cross-check meta § 4.2).
- Every `except Exception` site in B1 files with disposition: log-and-swallow
  (appropriate for background loops, leave) vs silent (needs logging) vs
  reraise candidate.
- Every `_cached_*` attribute on coordinator submodules.
- Every refresher in `_refreshers.py` and its purpose / cadence / overlap.
- Every entry point into the settings-write fan-out (`_settings_writes.py`,
  `coordinator/_writes.py`, individual entity `async_set_*` methods).
- Migration code in `_migration.py` and `_lidar_migration.py`: what's
  safe to delete given current installed versions (single-user dev,
  per memory `feedback_no_migration_overengineering.md`).
- MQTT subscription lifecycle: subscribe sites, unsubscribe sites,
  any leaks.
- `cloud_client.py` file split plan: a concrete file-by-file table showing
  which functions move where. Pre-validates the B1d phase.

No remediation in this stage. Read-only output.

### Stage 2: Four phased remediations

**B1a — Low-risk cleanup wins**

Goal: remove obvious dead/dormant code + fix the cheap real bugs.

Scope:
- Delete migration code that's safe to drop (per discovery doc's list).
  Per memory: single-user dev box, reinstall is fine, no over-engineering.
- Register `_cloud_refresh_debounce_handle` with `async_on_unload` in
  `coordinator/_device_sync.py` (fix the confirmed leak from meta § 4.2).
- Add `_LOGGER.debug` to the 14 silent `except Exception` swallows in
  `cloud_client.py:1835–1960`. Also the 2 missed silent swallows at
  `cloud_client.py:940` and `cloud_client.py:1114` (per Task 7 follow-up
  finding). The 4 silent swallows in `services.py` are out of B1 scope —
  defer to B3 unless discovery determines they're trivial one-liners worth
  bundling.
- Consolidate the 5-line protocol import block + 1-line observability import
  line into one place. Options surfaced by discovery: shared mixin base
  class, `coordinator/_imports.py` re-export module, or removal of unused
  imports first (per Task 9 review: `wheel_bind` is used in only 1 of 9
  mixins; `config_s2p51` in only 2 of 9 — most mixins carry dead imports).
- Confirm-or-fix sweep: every other interval/timer in B1 files registers
  with `async_on_unload`. Anything missed gets registered.

Each commit ends with `pytest`. No behavioural change visible from outside
the coordinator.

**B1b — Retry helper consolidation**

Goal: one shared retry helper; eliminate the stacked-loop bug.

Scope:
- Extract `_cloud_request_with_retry(coro, *, max_attempts, delay_s,
  deadline_s=None)` as a small helper in `cloud_client.py` (or its own
  module — discovery picks).
- Flip `request()`, `get_file()`, `send()` to use the helper.
- Remove `send()`'s outer `for attempt in range(attempts)` loop — the inner
  `request()` loop is the only retry. Action ceiling becomes 3, not 9.
- Replace `time.sleep(8)` with `asyncio.sleep(8)` if the call sites are
  async-context, otherwise keep in the executor wrapper and add a
  one-line docstring explaining why.
- Add unit tests against the helper (mock the underlying call, exercise
  success/failure/timeout/deadline paths).

Behavioural change visible from outside: action calls now have a 3-attempt
ceiling instead of an opaque 9-attempt ceiling. This is a documented fix,
not a regression — the 9-attempt behaviour was unintended.

**B1c — `_cached_*` shadow removal**

Goal: eliminate `_cached_maps_by_id` and any sibling `_cached_*` residue.

Scope:
- Inventory every `_cached_*` attribute on the coordinator (discovery
  doc step). The known one is `_cached_maps_by_id` in `_core.py:192`.
- For each, identify the canonical replacement in `cloud_state.py` (almost
  always `CloudState.maps_by_id` / `CloudState.settings` / etc).
- Replace every reader with a `CloudState.<field>` reference. The downstream
  reads are mostly in entity platforms (per meta § 4.5: 22 in `select.py`,
  7 in `switch.py`, more scattered across `camera.py`, `sensor.py`) plus a
  smaller number of accessors inside `coordinator/` submodules —
  straightforward search-and-replace per discovery doc's inventory.
- Delete the `_cached_*` attribute and any writer.
- Confirm no test or runtime path relies on the shadow.

Hard rule: this phase touches some files under `select.py`, `sensor.py`,
`switch.py`, `camera.py` to update their reads. That's a B1 finishing touch,
not a B3 audit incursion — only the read accessor changes. No `unique_id`,
`async_added_to_hass`, or entity structure modifications.

**B1d — `cloud_client.py` file split**

Goal: split the 2197-LOC `cloud_client.py` into focused submodules.

Scope:
- Discovery doc proposes the file-by-file split. Target shape:
  - `cloud_client/__init__.py` — re-export `CloudClient` class
  - `cloud_client/_auth.py` — login, token refresh, region routing
  - `cloud_client/_rpc.py` — `get_properties`, `set_properties`, `action`,
    `request`, `_api_call`
  - `cloud_client/_oss.py` — signed-URL OSS fetch (`get_file`, lidar/wifi
    blob retrieval)
  - `cloud_client/_discovery.py` — device list, capabilities query
  - `cloud_client/_batch.py` — `fetch_full_cloud_state`, batch parser
    glue (note: the `protocol/schedule.py` decoder co-location stays as-is
    in this cycle; B2 resolves it)
- Public API of `cloud_client.CloudClient` is unchanged. Importers don't
  notice the split.
- The retry helper from B1b lives in `cloud_client/_rpc.py` (or its own
  `_retry.py` if that's cleaner).
- Tests still pass without modification.

Why last: doing the split before B1b would just relocate three retry loops
to new files where they'd still need consolidation. Doing it before B1c
would do nothing because `_cached_*` lives in `coordinator/`, not in
`cloud_client.py`.

## Sequencing & dependencies

```
Discovery → B1a → B1b → B1c → B1d
```

Discovery is required input to all four phases.

B1a is independent of B1b/c/d. B1b is independent of B1c. B1d benefits from
B1b having landed (so the retry helper exists when we split files). B1c is
independent of B1d.

In practice they go serial because each phase is small enough that doing
them in parallel risks merge conflicts in the same files. Serial is faster
than parallel-with-rebases for a single dev.

## Deliverables per phase

Each remediation phase produces:

1. A plan at `docs/superpowers/plans/2026-05-NN-block1-{a|b|c|d}-*.md` with
   bite-sized tasks (the writing-plans skill format).
2. A series of commits with prefix `audit-b1a:` / `audit-b1b:` / etc.
3. `pytest` green at the end.
4. A short note appended to the discovery findings doc marking which
   findings were resolved.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| `_cached_*` removal breaks a hidden caller | Discovery doc inventories every read; phase plan touches each call site explicitly. |
| Retry helper changes timing in a way that confuses the cloud | The action ceiling change (9→3) is the only timing change. Cloud isn't latency-sensitive in this surface. |
| `cloud_client.py` file split changes import side effects | Public API of `CloudClient` is preserved. Re-export from `cloud_client/__init__.py`. Existing importers don't touch new submodules directly. |
| Coordinator-mixin import consolidation hides a real dependency | Discovery doc verifies which symbols each mixin actually uses; unused imports are deleted, kept ones move to one shared location. |
| Migration-code deletion breaks an upgrade path for some user | Single-user dev box per memory. If migration code is touched, the discovery doc explains what state would be skipped on upgrade. |
| Tests don't cover the changed paths | Add tests for the retry helper (mandatory), spot-add tests for any non-trivial path the audit changes. |

## What stays deferred

Named here so they don't get rediscovered later:

- Splitting `coordinator/_core.py` (828), `_refreshers.py` (802),
  `_session.py` (925), `_mqtt_handlers.py` (810) — each is its own follow-up
  spec. Discovery doc sketches split shapes as notes only (no committed plan
  files); a future cycle picks them up.
- `protocol/schedule.py` ↔ `cloud_client.fetch_full_cloud_state` decode
  co-location — B2.
- `coordinator/_lidar_oss.py` Acquired+Transformed dual-role split — B2.
- Naming convention pass on `decode_*` vs `parse_*` in `protocol/` — B2.
- PNG-serialisation idiom consolidation (`BytesIO; img.save; getvalue`
  duplicated 6+ times) — B4 (touches `map_render.py`, `wifi_map_render.py`,
  `protocol/pcd_render.py` — mostly B4 territory).
- The 4 silent swallows in `services.py` — B3 unless rolled into B1a as a
  trivial micro-step.

## Open questions

(none in the design itself — per-phase plans may surface their own when they
start writing tasks)

## What's next

After user signs off on this spec, the next step is the Discovery audit:
brainstorm → spec → plan → execute the read-only discovery pass that
produces `docs/superpowers/specs/2026-05-NN-block1-data-pipeline-findings.md`.
Each remediation phase then gets its own brainstorm → plan → execute cycle
referencing the discovery doc by finding ID.
