# Block 1 — Discovery (Design)

**Date:** 2026-05-19
**Status:** spec
**Parent:** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Ground truth:** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

## What this is

Stage 1 of Block 1: a read-only audit pass over the data-pipeline surface
(~10K LOC) that produces phase-ready inventories for the four remediation
phases B1a / B1b / B1c / B1d.

This is **not** the design of the data-pipeline cycle as a whole — that's the
parent spec. This is the design of just the discovery pass.

## Goals

1. Produce inventories concrete enough that each remediation phase plan
   reads them as task input — no re-derivation needed.
2. Catch B1-scope items that the meta pass missed at its broader resolution
   (the meta pass tabulated counts and top-N; discovery does the long tail).
3. Pre-validate the planned phase actions: confirm the `_cached_*` shadow
   has exactly the readers we expect, confirm `cloud_client.py` splits
   cleanly along the proposed lines, confirm the retry helper signature
   covers every call site.

## Non-goals

- No source code changes. This is read-only.
- No remediation. Findings are dispositioned (target phase + bucket) but
  not acted on.
- No revisiting of meta-pass findings that are already actionable — cite
  by meta § number rather than re-tabulating.
- No B2/B3/B4 scope. Findings that incidentally touch entity platforms get
  noted for B1c's read-path updates only.

## Hard rules

Carried over from the parent design spec:
- No edits to any file under `custom_components/dreame_a2_mower/`,
  `dashboards/`, `tools/`, or `tests/`.
- Output goes only to one doc: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`.

## Structure of the findings doc

Hybrid layout — phase-ready inventories at the top, broader sweep below,
deferred sketches at the bottom.

```
1. B1a — cleanup inventory
   1.1 Dead-code candidates (migration code, dead branches, unused imports)
   1.2 Silent-swallow log additions (every site + proposed log message)
   1.3 Uncancelled handles / timers (confirm/fix sweep)
   1.4 Coordinator-mixin import consolidation (per-mixin usage analysis)

2. B1b — retry helper inventory
   2.1 Helper contract (signature, semantics, async vs sync, deadline)
   2.2 Call sites (every cloud_client loop with proposed flip to helper)
   2.3 Stacked-loop elimination (send() outer loop → removed)

3. B1c — _cached_* shadow inventory
   3.1 Every _cached_* attribute on the coordinator (full list)
   3.2 Every reader (file:line per attribute) + canonical CloudState replacement
   3.3 Removal sequence (which to do first; any ordering constraints)

4. B1d — cloud_client.py split plan
   4.1 Function-by-function table (current function → target submodule)
   4.2 Module-level state (constants, helpers) target placement
   4.3 Tests that need import updates (if any)

5. Broader sweep
   5.1 Refreshers inventory (cadence / purpose / overlap audit of _refreshers.py)
   5.2 Settings-write fan-out trace (entity → _settings_writes → coordinator → cloud)
   5.3 MQTT subscription lifecycle (subscribe / unsubscribe / dispatch)
   5.4 Anything meta-pass missed at the B1 resolution

6. Deferred-split sketches (NOT for execution in this cycle)
   6.1 coordinator/_core.py — proposed split shape (notes)
   6.2 coordinator/_refreshers.py — proposed split shape
   6.3 coordinator/_session.py — proposed split shape
   6.4 coordinator/_mqtt_handlers.py — proposed split shape
```

## Finding format

Every finding gets a bucket label, file:line, evidence pointer, and
disposition. Format:

```markdown
- **[bucket]** `file.py:LL` — short description.
  Evidence: <one-line>. Disposition: <phase | defer>.
```

Buckets (from audit-overview spec § "Bug & refactor handling rules"):
- `dead` — dead code to remove
- `dup` — duplication / inconsistency to consolidate
- `refactor` — overly long/complex function/file (flagged for split or simplification)
- `bug` — actual bug with proposed fix
- `better` — easier/cleaner implementation available

## Sequencing

```
T1 scaffold → T2-T5 phase inventories → T6 broader sweep → T7 deferred sketches → T8 final pass
```

Phase inventories (T2-T5) are independent and could run in parallel, but the
plan executes them serially because they all write to the same output file
(merge conflicts otherwise).

## Effort estimate

~8 tasks, each one section of the findings doc, each ending with a commit.
Roughly similar shape to the meta pass.

## Deliverables

1. The findings doc itself at
   `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`.
2. ~8 commits prefixed `audit-b1-disco:`.
3. A final push to `origin/main`.

## What's next after discovery

After the findings doc is signed off, the four phase cycles run in order:
B1a → B1b → B1c → B1d. Each phase reads its corresponding top-of-doc
inventory section as a task list, plans against it, then executes via
subagent-driven development.
