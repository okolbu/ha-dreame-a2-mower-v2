# B2a — Domain/Protocol Refactors (Design)

**Date:** 2026-05-20
**Status:** spec
**Parent (Block 2):** the integration audit meta doc
`docs/superpowers/specs/2026-05-19-integration-audit-meta.md` § 5 (later-block
backlog, [B2] items).

## What this is

First of two Block-2 sub-cycles. B2a bundles six **behavior-preserving**
domain/protocol refactors (the meta's [B2] backlog minus the behaviorally
sensitive state-machine item). Each reshapes or relocates code without
changing behavior; the existing protocol / map / archive / schedule test
suites are the safety net, supplemented by characterization tests where a
split exposes an untested branch.

**Decisions (user, 2026-05-20):**
- **Two-cycle decomposition:** B2a = the 6 behavior-preserving items below;
  **B2b** = `mower/state_machine.py` `reconcile_from_telemetry` (121 LOC)
  `(phase,state)→transition_fn` dispatch — its own later cycle with
  characterization tests (behaviorally sensitive).
- **Naming item (#5) is IN scope.**
- **Schedule split (#6) is IN scope** (lightest version — re-export shim).

## The six items

### 1. `map_decoder.parse_cloud_map` split
`custom_components/dreame_a2_mower/map_decoder.py` — `parse_cloud_map`
(L278-718, ~440 LOC) is the largest target. It already nests `_accumulate`
(L325) and `_accumulate_spots` (L342); module-level helpers like
`_warn_shape_mismatch` (L45) already exist as a pattern.

**Approach:** promote the per-object-type parsing into named module-level
helpers (e.g. `_parse_boundary`, `_parse_mowing_areas`, `_parse_zones`,
`_parse_spots`, `_parse_obstacles` — names to match the actual branches found
during implementation), leaving `parse_cloud_map` a thin orchestrator that
calls them and assembles `MapData`. Behavior identical.
**Tests:** `tests/integration/test_map_decoder.py` is the safety net; add
characterization tests for any branch not already exercised before splitting it.

### 2. `config_s2p51._decode_list_payload` dispatch
`protocol/config_s2p51.py` — `_decode_list_payload` (L127, ~129 LOC).
**Reality note:** this is a *length-based* dispatch (`n==2`, `n==3`, …) with
real discrimination logic inside branches (e.g. the Low-Speed-vs-DnD
`any(v > 1 for v in value)` rule, with documented `[0,0,0]` ambiguity) — NOT a
pure field-index table as the backlog phrased it.
**Approach:** convert to a `{length: handler}` dispatch (dict mapping `n` → a
small per-length helper function), each helper keeping its branch's
discrimination logic verbatim. The orchestrator looks up by `len(value)` and
falls through to the existing default/unknown path.
**Tests:** existing `config_s2p51` decode tests; add characterization tests for
each length-case if not all are covered.

### 3. `archive/session.archive()` index-step extraction
`archive/session.py` — `archive()` (L463, ~101 LOC) does: `(md5,start_ts)`
dedup check (L18-24), file write, append to `self._index` (L85), and
`_prune_incomplete_for` (L97-98).
**Approach:** extract the index-mutation step (append + prune, and optionally
the dedup pre-check) into a helper `_commit_to_index(entry)`, leaving
`archive()` to build the summary, write the file, then delegate. Behavior
identical; idempotency `(md5,start_ts)` preserved.
**Tests:** existing session/archive tests; add a characterization test for the
dedup + prune behavior if not already pinned.

### 4. Delete dead `protocol/pose.py`
`protocol/pose.py` is imported only by `tests/protocol/test_pose.py`;
`protocol/telemetry.py` carries the live inline `_decode_pose`. No runtime
importer (confirmed via grep).
**Approach:** delete `protocol/pose.py` and `tests/protocol/test_pose.py`
(YAGNI dead-code removal). If `protocol/__init__.py` re-exports any pose symbol,
remove that re-export too.
**Tests:** suite stays green (nothing runtime references it).

### 5. Protocol naming convention (`decode_*` binary / `parse_*` JSON)
The binary outliers are **two**: `parse_pcd` (L110) and `parse_pcd_header`
(L58) in `protocol/pcd.py` (both decode binary PCD bytes), versus the
established `decode_s1p1` / `decode_s1p4` / `decode_s2p51` (binary) and
`parse_session_summary` / `parse_schedule_batch` / `parse_settings_batch`
(JSON/batch).
**Approach:** rename `parse_pcd → decode_pcd` and
`parse_pcd_header → decode_pcd_header`. Update call sites:
`camera.py` (imports + calls at L349, L366, L439, L469),
`tests/protocol/test_pcd_render.py` (L11, L104), and the prose mention in
`inventory.yaml` (L8138, a doc reference — not a protocol-fact change, so the
fact-discipline rule does not fire; update for accuracy). Add a short
"Protocol decoder naming" note to `custom_components/dreame_a2_mower/CLAUDE.md`
documenting `decode_*` = binary frames, `parse_*` = JSON/batch.
**Tests:** `test_pcd_render.py` + camera tests green after rename.

### 6. `protocol/schedule.py` encode/decode split (lightest version)
`protocol/schedule.py` mixes decode (`_decode_one_record` L73, `_decode_blob`
L109, `parse_schedule_batch` L250) and encode (`encode_schedule_blob` L165,
`build_schedule_set_value` L223).
**Approach:** create `protocol/schedule_decode.py` (the 3 decode symbols) and
`protocol/schedule_encode.py` (the 2 encode symbols), and reduce
`protocol/schedule.py` to a **thin re-export shim**
(`from .schedule_decode import *`-style explicit re-exports) so the 3 importers
need ZERO changes:
`coordinator/_writes.py:94` (`build_schedule_set_value`),
`cloud_client/_fetchers.py:333` (`parse_schedule_batch`),
`tests/protocol/test_schedule.py:8` (several).
Any shared types (e.g. `SchedulePlan`, `ScheduleData`) stay imported from their
canonical home (`cloud_state.py` / wherever they live) by both new modules.
**Tests:** `tests/protocol/test_schedule.py` green unchanged (resolves through
the shim).

## Architecture / boundaries

Each item is independent and self-contained. The unifying contract: **no
behavior change** — public function signatures, return shapes, logging, and
exception handling stay identical. Where a function is split, the orchestrator
keeps the exact same external contract; only internal structure changes.

## Testing

- Per item, the existing relevant suite must stay green; add characterization
  tests BEFORE splitting a function whose branches aren't already covered, so
  the split is provably faithful.
- Full suite (`python -m pytest tests -q`, baseline 1602 passed / 4 skipped at
  the start of B2a) green at every commit.
- Naming rename (#5) and pose deletion (#4) are verified by grep (no stale
  references) + suite.

## Out of scope (deferred)
- **#7 — `state_machine.reconcile_from_telemetry`** → B2b (next cycle).
- Cross-cutting PNG-serialisation helper and other [B4] items remain in their
  blocks.

## Push discipline
Behavior-preserving refactors with the full suite green. Per the cleanup
cadence, commit on `main` with `audit-b2a:` prefix; ship (push + `release.sh`)
at the user's discretion after the cycle completes — no separate live
smoke-gate required (no behavior change), though a quick reload check is cheap
insurance.
