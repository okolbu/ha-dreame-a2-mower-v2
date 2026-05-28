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
| [`wire-captures/*.md`](wire-captures/) | Dated, evidence-grade wire-format captures and audit findings. Each file is a frozen snapshot from the date in its filename. |

## Stable overview — read for context

Cross-cutting prose that is mostly evergreen but doesn't drive day-to-day decisions:

| Doc | Scope |
|---|---|
| [`g2408-protocol.md`](g2408-protocol.md) | Architecture overview: transport layer, OSS fetch flow, coordinate-frame math, contributor PROTOCOL_NOVEL guide. |
| [`cloud-map-geometry.md`](cloud-map-geometry.md) | Map geometry transformations from cloud-frame to renderer-frame. |
| [`g2408-capture-procedures.md`](g2408-capture-procedures.md) | How to capture specific MQTT/cloud events for closing inventory gaps. |
| [`webgl-lidar-card-feasibility.md`](webgl-lidar-card-feasibility.md) | Feasibility analysis for an in-browser LIDAR viewer. |

## Historical — read for traceability, do NOT cite as current

These describe the *path* to current understanding — hypotheses that were later refined or disproved, deprecated readings, original raw layered-findings prose. **A claim being in these docs does not mean it is currently true.**

| Doc | What it is |
|---|---|
| [`g2408-research-journal.md`](g2408-research-journal.md) | Timeline of how each protocol piece got figured out. Each topic's *Quick answer* line at the top is current; everything below it is timeline. Verify against authoritative docs before citing. |
| [`historical/`](historical/) | Pre-restructure raw source for the slim+journal+canonical migration; retired entity-sync-matrix; old TODO snapshots. Archive only. |

## Rules of thumb

- **New finding?** Land it in the matrix (per-entity), the cloud-write-reference (transport), and/or a wire-capture doc (evidence). Mention it in the journal under the relevant topic if a hypothesis cycle is worth preserving.
- **Disagreement between docs?** Authoritative wins. If you find a contradiction, fix the lagging doc *or* mark the disagreement explicitly with a "supersedes" pointer so the next reader can resolve it without guessing.
- **Date everything.** "Verified live <YYYY-MM-DD>" is the load-bearing claim. Without a date, a row is back to ⚠ hypothesis.
- **Don't promote a journal entry to authoritative without re-verifying.** The journal preserves the path; the authoritative docs preserve current truth. They are different epistemic categories.
