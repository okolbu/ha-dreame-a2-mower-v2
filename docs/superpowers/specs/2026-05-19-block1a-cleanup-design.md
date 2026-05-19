# B1a — Cleanup Wins (Design)

**Date:** 2026-05-19
**Status:** spec
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Discovery findings:** `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`

## What this is

The first **source-modifying** phase of the integration audit. Everything before
this (meta pass, Block 1 design, Block 1 discovery) was read-only documentation.
B1a executes the low-risk cleanup items already inventoried in the discovery
doc — dead-code removal, logging additions, one-line lifecycle fixes, and
dead-import deletions.

## Goals

Execute the following items as listed in the discovery findings doc:

1. Fix the stale docstring at `coordinator/_cloud_state.py:94` — claims "10 min"
   cadence; actual is 2 min (discovery § 5.4 last entry).
2. Add `_LOGGER.debug` lines to **22 silent `except Exception` handlers** in
   `cloud_client.py` (discovery § 1.2 — 21 `[bug]` + 1 `[better]`).
3. Register `coordinator/_device_sync.py:291`'s `_cloud_refresh_debounce_handle`
   with `entry.async_on_unload` (discovery § 1.3 — confirmed leak).
4. Call `coordinator._mqtt.disconnect()` from `async_unload_entry` in
   `custom_components/dreame_a2_mower/__init__.py` (discovery § 5.3 — second
   confirmed leak; orphan paho thread + TCP socket on unload).
5. Remove **38 dead `from ..protocol import …` lines** across 9 coordinator
   mixins per the 9×5 table in discovery § 1.4.
6. Remove **7 dead `from ..observability import …` lines** across 9 coordinator
   mixins per the 9×2 table in discovery § 1.4.
7. Delete `custom_components/dreame_a2_mower/_lidar_migration.py` (75 LOC) and
   its single caller (discovery § 1.1).
8. Delete `custom_components/dreame_a2_mower/_migration.py` (468 LOC) and its
   single caller in `__init__.py` (discovery § 1.1). This also removes the
   `_migration.py:301` reader of `_cached_maps_by_id` (relevant to B1c).

## Non-goals

- No retry helper extraction (B1b).
- No `_cached_*` shadow removal beyond what falls out naturally from migration
  deletion (B1c does the rest).
- No `cloud_client.py` file split (B1d).
- No new tests beyond what the existing suite covers — the behaviours being
  cleaned up aren't currently tested and shouldn't grow tautological tests.
- No refactor of any function/file (B1a is mechanical cleanup only).
- No remediation of items in the discovery doc's § 1.4 "consolidation options"
  beyond removing dead lines — picking a consolidation pattern (shared base
  vs `_imports.py` re-export) is deferred to a later cycle if it's worth doing
  at all after the dead-line removal.

## Hard constraint — no regression

- Entity `unique_id`, `entity_id`, device identifiers, friendly names unchanged.
- Service signatures unchanged.
- Event payloads unchanged.
- Archive format unchanged.
- MowerState dataclass shape unchanged.
- CloudState dataclass shape unchanged.
- 10-min canonical cloud-state refresh (and every other refresher cadence)
  unchanged.
- MQTT subscription topics unchanged.

If any task above would break any of these the task is redesigned or carved
out as a follow-up. Migration deletion specifically: per memory
`feedback_no_migration_overengineering.md`, a single-user dev box can drop
v1→v2 migration code safely. The verification step below confirms the live
HA config_entry is already at version 2 (the gate that makes the migration
a no-op).

## Approach — 8 sequential tasks, low-risk first

```
T1 docstring → T2 logging → T3 debounce → T4 mqtt → T5 protocol imports
  → T6 observability imports → T7 _lidar_migration delete → T8 _migration delete
```

Each task:
1. Edits only the files the discovery doc named for that finding-group.
2. Ends with `pytest tests/` green and `python -m py_compile` on touched files.
3. Commits independently (prefix `audit-b1a:`).
4. Pushes to `origin/main` after the final task (per memory: HACS pulls from
   `origin/main`, push regularly).

Serial execution because some tasks touch the same files (e.g. T2 and T8 both
touch `cloud_client.py` and `__init__.py`). Parallel would risk merge conflicts.

## Sequencing rationale

| Task | Risk | Why this position |
|---|---|---|
| T1 docstring | trivial | Validates the workflow end-to-end on a no-op edit. |
| T2 logging | low | 22 mechanical additions to one file; no behaviour change. |
| T3 debounce | low | One-line lifecycle fix, surgical scope. |
| T4 mqtt disconnect | low | One-line lifecycle fix in `__init__.py`. |
| T5 protocol imports | low | Dead-line deletion across 9 files; no symbol use that's being deleted. |
| T6 observability imports | low | Same shape as T5. |
| T7 `_lidar_migration` | medium | File deletion + caller removal; smaller / simpler than T8. |
| T8 `_migration` | medium | File deletion + caller removal in `__init__.py`. 468 LOC. Run after T7 so the workflow is proven. |

Higher-risk items (`_cached_*` shadow removal, retry consolidation, file
splits) are in B1b/c/d.

## Per-task input

Each task in the plan reads its corresponding section of the discovery doc as
input. For example, T5 reads the 9×5 protocol-imports table in § 1.4 to know
exactly which import lines to delete from which file.

## Verification per task

After each task, the worker runs:
```bash
pytest tests/ -q
python -m py_compile <files-touched>
```

After T2, additionally:
```bash
# Spot-check that every silent except now has a _LOGGER call
grep -c "except Exception" custom_components/dreame_a2_mower/cloud_client.py
# Count should be unchanged (we don't delete handlers, just add logging)
```

After T8, additionally:
```bash
# Confirm migration symbols are gone everywhere
grep -rn "_migration\|_lidar_migration\|async_migrate_entry" \
  custom_components/dreame_a2_mower --include='*.py'
# Should return nothing (or only legitimate references in comments)
```

## Final verification — after all 8 tasks

The worker reports the result of:

1. `pytest tests/` — green.
2. `python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py')`
   — clean.
3. `python -c "from custom_components.dreame_a2_mower import const; print(const.DOMAIN)"`
   — imports cleanly, prints `dreame_a2_mower`.
4. `tools/inventory_audit.py` (per CLAUDE.md CI gate) — passes.

User-led smoke check (not automated, but required before declaring B1a done):
- HA reloads the config entry without errors.
- Every entity that existed pre-B1a still exists post-B1a (same `entity_id`).
- The `Refresh from cloud` button still triggers a refresh.
- `Logbook` and `Events` for the mower still emit lifecycle entries.

If the user reports a regression, the offending commit gets reverted; the
remediation is then split into a smaller follow-up task.

## Rollback strategy

Each task is a single commit. Reverting any one is `git revert <SHA>`. The
commits are independent (each touches different files OR same files but
independent line ranges), so reverts don't cascade.

The riskiest revert would be T8 (migration deletion) if it turns out HA needs
the migration path for some reason we missed. Recovery: `git revert <T8-SHA>`,
push, force a config-entry reload.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Migration deletion breaks an upgrade path | Per memory: single-user dev, reinstall is fine. Pre-T8 the worker confirms the live HA `config_entry.version == 2` (the gate that makes the migration a no-op). |
| Silent-swallow logging is too noisy at runtime | `_LOGGER.debug` is gated by the integration's logger level. Per memory the user keeps it at DEBUG during audits, so a brief noise period is expected. |
| Dead-import deletion hides a runtime lookup | The discovery 9×5 table counted dot-accesses, not import-only references. A worker mistake here would be caught immediately by `pytest` (any code path that uses the deleted import would fail to import). |
| MQTT `disconnect()` call introduces a race | The fix is `entry.async_on_unload(...)` registration — calls happen in the standard HA unload sequence. No new race surface; just adds a missing cleanup. |
| One task's edits conflict with another's | Serial execution + per-task commits means a conflict only happens within one task's editing window, never across. |

## What stays for B1b / B1c / B1d

- **B1b:** retry helper extraction, stacked-loop bug elimination, `time.sleep(8)` removal (discovery § 2).
- **B1c:** `_cached_maps_by_id` shadow removal across 72 references in 13 files
  (discovery § 3) — plus the 3 refresher methods flagged as redundant in § 5.1
  (`_refresh_cfg`, `_refresh_mihis`, `_refresh_map` — these become deletable
  once CloudState fully owns the data flow).
- **B1d:** `cloud_client.py` file split per § 4 (59-row placement table).

## What's next

After user signs off on this spec, the writing-plans skill produces the B1a
implementation plan (8 tasks, one per goal above, executed via
subagent-driven development).
