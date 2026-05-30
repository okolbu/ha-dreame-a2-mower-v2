# `docs/research/` — what's authoritative, what's historical

This directory holds the integration's reverse-engineering record. Files split into two distinct kinds with different epistemic weight — knowing which is which keeps old guesses from contaminating new work.

## Authoritative — cite these, trust these

These docs are kept current. Each carries a **Status — AUTHORITATIVE** banner at the top with a last-verified date. When two docs disagree, these win.

| Doc | Scope |
|---|---|
| [`entity-validation-matrix.md`](entity-validation-matrix.md) | Per-HA-entity source of truth: every entity's read source, write path, outcome, evidence tier. |
| [`cloud-write-reference.md`](cloud-write-reference.md) | Cloud transport layer: auth, endpoints, payload framing, response codes for every cloud surface (routed-action / set_cfg / setDeviceData / chunked-batch). |
| [`inventory/generated/g2408-canonical.md`](inventory/generated/g2408-canonical.md) | Per-slot semantic for every property / event / action / CFG key (auto-generated from `inventory/inventory.yaml`). |
| `inventory/generated/coverage-report.md` | Inventory coverage status — auto-generated, **gitignored** (data-dependent; run `tools/inventory_audit.py` locally). |

## Stable overview — read for context

Cross-cutting prose that is mostly evergreen but doesn't drive day-to-day decisions:

| Doc | Scope |
|---|---|
| [`g2408-protocol.md`](g2408-protocol.md) | Architecture overview: transport layer, OSS fetch flow, coordinate-frame math, contributor PROTOCOL_NOVEL guide. |
| [`cloud-map-geometry.md`](cloud-map-geometry.md) | Map geometry transformations from cloud-frame to renderer-frame. |
| [`g2408-capture-procedures.md`](g2408-capture-procedures.md) | How to capture specific MQTT/cloud events for closing inventory gaps. |

## In-tree dated evidence / context — read for traceability, NOT as current

These stay in-tree because the authoritative docs above cite them as evidence,
but a claim being in them does **not** make it current — `inventory.yaml` wins.

| Doc | What it is |
|---|---|
| [`g2408-research-journal.md`](g2408-research-journal.md) | Timeline of how each protocol piece got figured out. Each topic's *Quick answer* line is current; everything below it is timeline (hypotheses later refined/disproved). Verify against `inventory.yaml` before citing. |
| [`wire-captures/*.md`](wire-captures/) | Dated, evidence-grade wire-format capture snapshots — frozen at the date in the filename. |

## Moved OUT of the git tree

Process and pre-restructure docs no longer live in-tree (the tree is the search
scope; keeping them here let disproved claims get retrieved as current). They are
at `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/research/`, mirroring
the old `docs/research/`-relative path:

- `historical/` — pre-restructure raw source + retired entity-sync-matrix + old TODO snapshots.

(The whole `docs/superpowers/` specs/plans layer moved too — see
**CLAUDE.md § "Documentation canonicity & lifecycle"** for the full rule.)

## Rules of thumb

- **New finding?** Land it in `inventory.yaml` / `entity-inventory.yaml` (the
  source of truth), and the matrix (per-entity) / cloud-write-reference
  (transport) / a wire-capture (evidence) as needed. Append a hypothesis cycle to
  the journal only if it's worth preserving.
- **Disagreement between docs?** `inventory.yaml` wins. Fix the lagging doc.
- **Date everything.** "Verified live <YYYY-MM-DD>" is the load-bearing claim.
- **A spec/plan goes historical the moment its work ships** — move it to `OLD/…`,
  don't leave it in-tree (CLAUDE.md lifecycle rule).
