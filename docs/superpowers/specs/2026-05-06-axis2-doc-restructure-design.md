# Axis 2 — Doc Restructure Design

**Status:** Spec, awaiting review
**Author:** session 2026-05-06
**Predecessor:** axis 1 (`2026-05-05-g2408-protocol-inventory-design.md`)
**Sibling axes (out of scope here):** axis 3 (runtime harness), axis 4 (decoder enrichment), axis 5 (live-test gap closure)

---

## 1. Problem

After axis 1, `inventory.yaml` is the source of truth for slot-level protocol detail and `inventory/generated/g2408-canonical.md` is the rendered chapter-style reference. But the legacy "everything I learned" prose still lives in two oversized layered-findings documents:

- `docs/research/g2408-protocol.md` — 1821 lines, mixes (a) cross-cutting architectural prose, (b) per-slot semantic detail (now duplicated in canonical), and (c) dated investigation entries with deprecated hypotheses.
- `docs/TODO.md` — 1082 lines, mixes (a) actionable open items, (b) resolved historical entries kept "for traceability", and (c) version-shipped changelog (a52 → a87).

Two related side-files have similar issues:

- `docs/research/2026-04-17-g2408-property-divergences.md` — early divergence catalog, mostly absorbed into inventory.
- `docs/research/2026-04-23-iobroker-dreame-cross-reference.md` — apk cross-walk, mostly absorbed into inventory.

The user's framing: TODO should be an actual list of TODO items, and the historical material should move elsewhere — possibly merged with the prose extraction from `g2408-protocol.md` into a single journal.

## 2. Goal of axis 2

Restructure the four prose documents above into:

- `g2408-protocol.md` — slim hybrid overview (cross-cutting prose only).
- `g2408-research-journal.md` — topic-clustered historical record.
- `TODO.md` — actual list of open items.
- The two dated side-files are absorbed and deleted.

Inventory + canonical doc are unchanged. No new code beyond doc-link integrity.

## 3. Non-goals

- Modifying `inventory.yaml` content (axis 1 owns that surface).
- Adding any runtime behaviour (axis 3).
- Adding HA entities for `DECODED-UNWIRED` rows (axis 4).
- Capturing new evidence to close `hypothesized` rows (axis 5).
- Restructuring the `superpowers/specs/` and `superpowers/plans/` directories.
- Touching `docs/research/cloud-map-geometry.md` or `docs/research/webgl-lidar-card-feasibility.md`. They stay as-is.

## 4. Architecture

### 4.1 Target file layout

```
docs/research/
  g2408-protocol.md                       # SLIM (~300-400 lines)
  g2408-research-journal.md               # NEW (topic-clustered)
  cloud-map-geometry.md                   # unchanged
  webgl-lidar-card-feasibility.md         # unchanged
  inventory/                              # unchanged (axis 1)
    inventory.yaml
    README.md
    generated/
      g2408-canonical.md
      coverage-report.md

docs/
  TODO.md                                 # SLIM (open items only)
```

After axis 2 completes:

- `docs/research/g2408-protocol.md` is **replaced in place** with the slim version (same file path; new content). The old 1821-line content is split between the slim doc and the journal.
- `docs/research/2026-04-17-g2408-property-divergences.md` is **deleted**; content folded into the journal under "g2408 vs upstream divergence".
- `docs/research/2026-04-23-iobroker-dreame-cross-reference.md` is **deleted**; residual content folded into the journal under "apk cross-walk".

### 4.2 Slim `g2408-protocol.md` — what stays

Only **cross-cutting prose** that doesn't fit into per-slot rows. Specifically:

| Section | Source | Notes |
|---|---|---|
| Intro + scope | new | "What this doc is, what's in canonical, what's in the journal" |
| § Transport | current §1 | Cloud endpoints, MQTT topic format, 80001 failure mode (the architectural-level explanation, not the per-slot list) |
| § Coordinate frame | current §3.1 sub-section "Coordinate frame (charger-relative)" + Y-axis calibration | Plus a brief reference to `cloud-map-geometry.md` for the renderer-side math |
| § OSS fetch architecture | current §7 (the diagram + flow, not the per-slot details) | Mower → cloud → OSS → integration HTTP fetch |
| § Routed-action surface | current §6.2 (the m+t+o envelope explanation) | Without the per-key tables — those live in canonical |
| § PROTOCOL_NOVEL catalog | current §7.5 | The contributor-facing "what to report when" guide |
| § See also | new | Pointers to canonical, journal, inventory README |

Length budget: ~300-400 lines. Anything that wants to be more is either (a) per-slot detail (move to canonical) or (b) a hypothesis cycle (move to journal).

### 4.3 New `g2408-research-journal.md` — what goes there

Topic-clustered with dated subentries. Each topic is the "story of how we figured out X". Topics are mostly slot-bound; some are cross-cutting threads.

Initial topic list (extracted from existing prose):

| Topic | Source material |
|---|---|
| s1p4 telemetry decoder evolution | g2408-protocol §3.1-3.3 dated bits + alpha.98 fix story |
| s1p1 byte[10] bit 1 saga | TODO.md big section + g2408-protocol §3.4 |
| s1p1 byte[3] bit 7 PIN-required clarification | TODO.md sub-thread + g2408-protocol §3.4 |
| Phase-byte semantics (s1p4 byte[8]) | g2408-protocol §3.1 phase byte sub-section + dated samples |
| s2p1 mode + s2p2 state codes — what's enum vs error | g2408-protocol §4.1 / §4.2 + apk cross-reference |
| s2p51 multiplexed config — disambiguation evolution | g2408-protocol §6 + s2p51_shapes ambiguous-toggle history |
| Edge-mow FTRTS + wheel-bind discovery (2026-05-05) | g2408-protocol §4.6.1 |
| `s2p50` op-code catalog — incremental decode | g2408-protocol §4.6 dated entries |
| Map-fetch flow — `s6p1` / event_occured / OSS | g2408-protocol §7 dated entries |
| `cfg_individual` MISTA reversal (2026-05-06) | axis 1 hardening — important pattern, deserves its own topic |
| g2408 vs upstream divergence | `2026-04-17-g2408-property-divergences.md` (whole file folds in here) |
| apk cross-walk findings | `2026-04-23-iobroker-dreame-cross-reference.md` residuals after inventory absorption |
| Recently shipped (a52 → current) | TODO.md "Recently shipped" section, distributed under the topic each version touched |
| Live-confirmed status board | TODO.md "Live-confirmed" bullets at the bottom |

Each topic section follows this shape:

```markdown
## <Topic name>

> **Quick answer (current state):** one-paragraph summary of where we are now.

### Timeline

- **2026-04-17** — initial hypothesis: …
- **2026-04-22** — testing reveals X; hypothesis was Y, actually Z.
- **2026-04-30** — confirmed via …; integration ships at a58.
- **2026-05-04** — refinement: …

### Deprecated readings

- ~~Earlier reading: "byte[10] bit 1 = post-fault-window timer"~~ — wrong; pinned 2026-05-04.

### Cross-references

- Inventory rows: `s1p1_b10_bit1`, `s1p1_b3_bit7`
- Canonical: `g2408-canonical.md` § Heartbeat (s1p1) bytes
```

The "Quick answer" line is the load-bearing piece for someone who wants the current state without reading the saga; the timeline + deprecated readings preserve the hypothesis-correction history that gives the project its peculiar character.

Length budget: no hard cap. Likely 1500-2500 lines (the existing prose has substance; this is a real archive).

### 4.4 Slim `TODO.md` — what stays

**Only actionable open items** with ≤ 1-paragraph rationale. The current file's "Recently shipped", "Live-confirmed", and resolved/historical entries all move to the journal.

Each TODO item:

```markdown
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

Length budget: ~150-250 lines. Items with more than ~5 lines of "why" should be in the journal; the TODO is a worklist.

The four kinds of content currently in `TODO.md`:

| Kind | Destination |
|---|---|
| Open items with pending work | stay in `TODO.md` |
| Recently shipped (a52 → a87) | journal (under each topic the version touched) |
| Resolved historical entries | journal (under the topic) |
| Live-confirmed status board | journal as its own topic, optionally also a brief "Confirmed working" subsection in the slim `g2408-protocol.md` |

### 4.5 The two dated side-files

#### `2026-04-17-g2408-property-divergences.md`

Whole file moves to journal as "g2408 vs upstream divergence" topic. The divergence catalog table goes verbatim under that topic's "Timeline" entry for 2026-04-17. Then delete the file.

#### `2026-04-23-iobroker-dreame-cross-reference.md`

Most content was absorbed into inventory rows during axis 1 (`references.apk`). The residual:
- The full opcode catalog (op 0-503) — already in inventory `opcodes` section. **Drop**.
- The PRE schema discussion — already in inventory `cfg_keys.PRE`. **Drop**.
- Action items list (priority-ordered) — these were axis-1 todos; most are done. The remaining ones (M_PATH userData fetch; `s1p4` regionId/taskId/percent decode; cross-check pose decoder on lawn >32 m) become **TODO items**.
- Notes/caveats about g2568a vs g2408 — fold into journal "apk cross-walk" topic.

Then delete the file.

### 4.6 Cross-reference integrity

After the restructure:

- The slim `g2408-protocol.md` gets a "See also" footer linking inventory README + canonical + journal.
- `inventory.yaml._sources.protocol_doc_overview` adds the slim file path so the inventory README knows where to point readers.
- `references.protocol_doc` cites in `inventory.yaml` rows currently point at section anchors in the OLD `g2408-protocol.md` (e.g., `"docs/research/g2408-protocol.md §3.4"`). After the restructure, these anchors mostly disappear from the slim file (the per-slot detail moved). **Update those cites to point at the canonical doc instead** (`docs/research/inventory/generated/g2408-canonical.md § <chapter>`). Where a row's prose is genuinely cross-cutting (e.g., transport-layer prose), the cite stays on the slim file.

This is a mechanical sweep, not a research task. The existing cite pattern is `"docs/research/g2408-protocol.md §X.Y"`; the new pattern is `"docs/research/inventory/generated/g2408-canonical.md § <ChapterName>"` for slot-detail rows or `"docs/research/g2408-protocol.md § <Section>"` for cross-cutting cites.

### 4.7 Validation

The restructure adds two new audit-style checks:

1. **No content lost**: `tools/journal_completeness_check.py` (or a one-shot script — doesn't need to live in `tools/` permanently). Walks the OLD `g2408-protocol.md` and `TODO.md` paragraph by paragraph; for each, asserts that the paragraph's content appears in either the slim doc, the journal, the canonical doc, or a deleted-on-purpose list. Fails on orphans.

2. **No broken cross-references**: simple grep — every `docs/research/g2408-protocol.md §` cite in `inventory.yaml` resolves to a section that exists in the slim file. If not, the cite needs updating to canonical or journal.

Both run once during execution; they're not permanent CI. They're the "did the migration drop anything" gate before the OLD files are deleted.

## 5. Execution model

Per axis 1's pattern: brainstorm → spec → plan → subagent-driven implementation. Implementation phases:

1. **Phase A — Skeletons.** Create the new slim `g2408-protocol.md`, the empty `g2408-research-journal.md`, and the slim `TODO.md` template. Each has only its TOC + section headers + intro/banner. Commit.

2. **Phase B — Migrate cross-cutting prose to slim.** Walk OLD `g2408-protocol.md` §1 (Transport) and the cross-cutting bits of §3.1 (coordinate frame), §6.2 (routed-action envelope), §7 (OSS architecture), §7.5 (PROTOCOL_NOVEL catalog). Lift verbatim into the slim file. Commit.

3. **Phase C — Migrate dated/topic content to journal.** Walk OLD `g2408-protocol.md` end to end; for each paragraph that is dated, hypothetical, or per-slot detail (and isn't already absorbed into inventory), file it under the right journal topic. Use the topic list in §4.3. Each topic accumulates its timeline entries. Commit per-topic where natural.

4. **Phase D — Migrate TODO.md.** Walk `docs/TODO.md` section by section. Open items → slim TODO. Resolved/historical → journal. Recently-shipped versions → journal under each topic. Live-confirmed bullets → journal "Live-confirmed status board" topic. Commit.

5. **Phase E — Absorb the two dated side-files.** Move what's left into journal; delete the side-files. Commit.

6. **Phase F — Cross-reference sweep.** Update `inventory.yaml` `references.protocol_doc` cites to point at canonical (mostly) or slim protocol (cross-cutting). Re-render canonical. Commit.

7. **Phase G — Completeness check + acceptance.** Run the orphan-paragraph script + cross-reference grep. If both clean, declare axis 2 complete. (No final "delete g2408-protocol.md" step — it was replaced in place during Phase B; Phases B-F also deleted the two side-files.) Commit + push.

## 6. Acceptance criteria

1. `docs/research/g2408-protocol.md` exists and is between 250 and 500 lines (slim hybrid overview).
2. `docs/research/g2408-research-journal.md` exists with the topic structure from §4.3 populated.
3. `docs/TODO.md` exists with ≤ 250 lines, every entry follows the §4.4 shape, and contains only open or in-progress items (no resolved/historical, no shipped-version notes).
4. `docs/research/2026-04-17-g2408-property-divergences.md` and `docs/research/2026-04-23-iobroker-dreame-cross-reference.md` are deleted; their useful content lives in the journal.
5. The orphan-paragraph completeness script reports zero orphans.
6. Every `references.protocol_doc` cite in `inventory.yaml` resolves to a section that exists in either the slim protocol doc or the canonical doc; no dangling cites.
7. `python tools/inventory_gen.py --validate-only` passes.
8. `python tools/inventory_audit.py` (presence + consistency) exits 0.
9. `python -m pytest tests/tools/ -v` — all tests pass.
10. The slim `g2408-protocol.md`'s "See also" footer links inventory README + canonical + journal.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Migration drops content (the layered findings have value; losing entries is real harm) | Orphan-paragraph completeness script (acceptance #5) |
| Slim protocol doc grows back to layered-findings shape over time | Length budget (acceptance #1); contributors must explicitly file historical entries in journal, not in slim |
| Cross-reference cites break silently | Cite-resolution grep (acceptance #6); run as part of completeness check |
| Journal becomes its own unwieldy file | Topic-clustering keeps each section self-contained; readers navigate by topic, not by reading end-to-end |
| TODO.md grows back to 1000 lines | Length budget (acceptance #3); items with > 5 lines of rationale belong in journal, not TODO |
| Inventory rows' historical context (open_questions, dated semantic notes) duplicates journal entries | Acceptable — the row is the slot's current state; the journal carries the saga. Some duplication is the cost of having both views available. |

## 8. Hand-off to subsequent axes

- **Axis 3** (runtime harness): consumes `inventory.yaml` for runtime watchdog suppression + CI auditing. No dependency on axis 2's doc shape.
- **Axis 4** (decoder enrichment): writes new HA entities for `DECODED-UNWIRED` rows. Each new entity's commit message can cite the journal topic where the slot's history lives, giving reviewers the context.
- **Axis 5** (live-test gap closure): every `decoded: hypothesized | unknown` row is a candidate test. The journal topic is the test-design starting point.

## 9. Open assumptions to validate before coding

- The slim `g2408-protocol.md` length budget (250-500 lines) is approximate. If the cross-cutting prose genuinely needs more (e.g., the OSS architecture warrants its own diagram-heavy section), allow expansion with reviewer judgement.
- The journal's topic list (§4.3) is a starting point. New topics surface during Phase C; the implementer files them under best-fit and notes any reorganisation in commit messages.
- The orphan-paragraph script is one-shot, not permanent CI. If reviewers want it permanent, that's an axis-3 enhancement.
- The two dated side-files are deleted at the end of axis 2. If you want them kept under `docs/research/historical/` instead of deleted, call it out at review.

## 10. References

- Axis 1 spec: `docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md`
- Axis 1 plan: `docs/superpowers/plans/2026-05-05-g2408-protocol-inventory.md`
- Inventory README: `docs/research/inventory/README.md`
- Source docs to be migrated: `docs/research/g2408-protocol.md`, `docs/TODO.md`, `docs/research/2026-04-17-g2408-property-divergences.md`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md`
