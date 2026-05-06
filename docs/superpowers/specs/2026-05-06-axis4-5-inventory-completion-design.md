# Axis 4/5 (combined) — Inventory Completion Design

**Status:** Spec, awaiting review
**Author:** session 2026-05-06
**Predecessors:** axis 1 (`2026-05-05-g2408-protocol-inventory-design.md`), axis 2 (`2026-05-06-axis2-doc-restructure-design.md`), axis 3 (`2026-05-06-axis3-runtime-harness-design.md`)
**Original axis split:** axis 4 (decoder enrichment) + axis 5 (live-test gap closure) — collapsed into one cycle because axis 4's worklist shrank to 1 row after axis 1's hardening.

---

## 1. Problem

Axes 1-3 produced a complete inventory, restructured docs, and a runtime harness that loads the inventory + value-catalogs. Two gaps remain:

- **Loader doesn't merge cross-section catalogs.** `state_codes:` is the value-catalog for `s2p2`; `mode_enum:` is the value-catalog for `s2p1`. The loader currently only indexes property-row `value_catalog:` blocks, so the runtime catalog-miss check exercises 3 properties (s1p2, s2p1 — only the inline 9 entries, s3p2) instead of ~50 (s1p2 + s2p1 full + s2p2 + s3p2).
- **137 inventory rows have `decoded: hypothesized | unknown` with no documented capture procedure.** The user's framing throughout has been "production ready, with documented unknowns" — those unknowns need capture procedures so contributors (or future-self) know what to do when the triggering event occurs.

Original axis-4 brief (wire DECODED-UNWIRED rows) has only 1 candidate after axis-1 hardening (`mode_enum/s2p1_3 PAUSED`); the lone candidate is auto-handled by deliverable 1 below.

## 2. Goals

Three deliverables in one cycle:

1. **Loader catalog merge** — `value_catalogs[(2,1)]` derived from `mode_enum:` ∪ inline; `value_catalogs[(2,2)]` derived from `state_codes:`. Auto-resolves the lone axis-4 candidate.
2. **`docs/research/g2408-capture-procedures.md`** — new topic-clustered document with a template + 6-8 fully-written procedures covering the trigger archetypes that cluster the 137 axis-5 candidates.
3. **TODO.md cross-references** — every blocked item in `docs/TODO.md` that has a matching capture procedure gains a `**Procedure:** <link>` line.

## 3. Non-goals

- Writing 137 per-row procedures (the ~6-8 clustered procedures cover the trigger archetypes; 1:1 mapping is overkill).
- Live-capture execution itself (procedures are documents; running them happens when triggers occur).
- New HA entities for inventory data not currently surfaced (e.g., MISTA mission status as a sensor) — those are real axis-4 enrichment work but should land per-feature, not as a bulk axis.
- Re-running the orphan-paragraph audit from axis 2 — those concerns were settled.
- CI extensions (axis 3 covers this).

## 4. Architecture

### 4.1 Loader catalog merge

In `custom_components/dreame_a2_mower/inventory/loader.py`, extend `_build_inventory()` to walk the `state_codes:` and `mode_enum:` sections in addition to `properties:` when populating `value_catalogs`.

```python
# After the existing properties walk, augment for state_codes and mode_enum.
# state_codes -> (2, 2) catalog; mode_enum -> (2, 1) catalog (merged with
# any inline value_catalog already populated for s2p1).

state_codes_catalog: dict[Any, str] = {}
for row in raw.get("state_codes") or []:
    if not isinstance(row, dict):
        continue
    code = row.get("code")
    name = row.get("name") or row.get("id") or str(code)
    if isinstance(code, int):
        state_codes_catalog[code] = str(name)
if state_codes_catalog:
    # Merge: existing inline (if any) wins, augmented by section entries.
    existing = catalogs.get((2, 2)) or {}
    catalogs[(2, 2)] = {**state_codes_catalog, **existing}

mode_enum_catalog: dict[Any, str] = {}
for row in raw.get("mode_enum") or []:
    if not isinstance(row, dict):
        continue
    value = row.get("value")
    name = row.get("name") or row.get("id") or str(value)
    if isinstance(value, int):
        mode_enum_catalog[value] = str(name)
if mode_enum_catalog:
    existing = catalogs.get((2, 1)) or {}
    catalogs[(2, 1)] = {**mode_enum_catalog, **existing}
```

Three new tests in `tests/inventory/test_loader.py`:

- `test_state_codes_section_merged_into_s2p2_catalog` — asserts `catalogs[(2, 2)]` contains a code from `state_codes:` (e.g., `48` "MOWING_COMPLETE").
- `test_mode_enum_section_merged_into_s2p1_catalog` — asserts `catalogs[(2, 1)]` contains values from both inline + section sources, including `3` "PAUSED" (the lone axis-4 candidate).
- `test_inline_value_catalog_takes_precedence_over_section` — asserts the inline catalog wins when both sources have an entry for the same value (defends against future contradictions).

### 4.2 Capture procedures document

New file `docs/research/g2408-capture-procedures.md`. Structure:

```markdown
# g2408 — Capture Procedures

Topic-clustered procedures for closing inventory gaps where the slot's
semantic depends on observing a specific triggering event. Each procedure
names the inventory rows it closes, the trigger type, the prerequisite
state, the exact steps to take, what to look for in the resulting probe
log / cloud dump, and which inventory edits to make after capture.

For the slot-level current state see
`docs/research/inventory/generated/g2408-canonical.md`.
For the saga of how each slot got figured out see
`docs/research/g2408-research-journal.md`.
For open work see `docs/TODO.md`.

## Trigger types

| Type | Meaning |
|------|---------|
| `user-fakeable` | The user can synthesize the trigger (e.g., create a fake pathway, switch maps) without waiting for natural occurrence. |
| `event-driven` | Wait for a specific event the firmware fires (e.g., AI human detection during mowing). The user can sometimes increase the probability (drive past pets, etc.) but can't directly cause it. |
| `automatic-over-time` | The trigger occurs naturally on a cadence (e.g., cloud dumps re-running and producing different responses for stateful endpoints). No user action needed. |
| `blocked-on-firmware-cooperation` | The trigger requires the firmware to do something it currently doesn't (e.g., an OTA update). Document for later. |

## Procedure template

(see procedures below for the canonical shape)

---

## Procedures

[procedures listed here]
```

Followed by 6-8 procedures, each filling the template. Specific procedures to include:

1. **Firmware update flow** — `event-driven` (next OTA). Closes `s1p2 OTA state`, `s1p3 OTA progress`, `s2p1_14 UPDATING`, `s2p57 robot_shutdown` open questions.

2. **Take-a-photo flow (apk's takePic)** — `user-fakeable`. Closes the `o:401 takePic` semantic question (apk vs HA-integration paths) + the `s2p55 ai_obstacle` payload-on-success unknown.

3. **Active mowing s5p10x sequence capture** — `event-driven`. Closes `s5p104`, `s5p105`, `s5p106`, `s5p108` semantic questions. Procedure: continuous mow (no recharge interrupts), capture probe log start-to-end, look for s5p10x value patterns correlated with phase transitions.

4. **Patrol log trigger investigation** — `event-driven` if findable, `blocked-on-firmware-cooperation` otherwise. Closes the `Patrol Logs` open item + ai_obstacle if patrol triggers it.

5. **Pathway Obstacle Avoidance (user-fakeable)** — Closes `CFG.BP`, `CFG.PATH` semantic questions. User creates a fake pathway in app, toggles avoidance flag, observes CFG diff + s2p51 push.

6. **Multi-lawn / second-map slot (user-fakeable)** — Closes `MAPL` 2x5 list semantics + service-4 map-related rows (s4p42 MAP_INDEX, s4p43 MAP_NAME, s4p44 CRUISE_TYPE, s4p47 SCHEDULED_CLEAN, s4p49 INTELLIGENT_RECOGNITION). User creates a second map slot, switches between them, captures.

7. **Cloud-dump cadence re-test** — `automatic-over-time`. Closes the 6 axis-1-hardening downgrades (AIOBS, MAPD, MAPI, MITRC, OBS, PRE cfg_individual) plus MISTA's open questions. Procedure: schedule `dreame_cloud_dump.py` to run hourly for a week; collect ~150 dumps; observe which endpoints flip from r=-1/-3 to `ok`. Update inventory rows accordingly.

8. **Change PIN code wire format** — `blocked-on-firmware-cooperation` (BT-only). Document the gap; note that the integration cannot close this without a BT sniffer or apk-side instrumentation.

### 4.3 TODO.md cross-references

For each entry in `docs/TODO.md`'s "Blocked" section, add a `**Procedure:** [link]` line pointing at the relevant procedure in `g2408-capture-procedures.md`. Items without a matching procedure (e.g., the dashboard contextual buttons UX work) get no link — those are HA-side polish, not protocol gaps.

Token cost: ~20 lines of TODO edits.

## 5. Acceptance criteria

1. `inventory/loader.py` extends `_build_inventory` to merge `state_codes:` into `value_catalogs[(2, 2)]` and `mode_enum:` into `value_catalogs[(2, 1)]`. Inline catalog wins on conflict.
2. Three new tests in `tests/inventory/test_loader.py` cover the merge logic; all pass.
3. After the loader extension, `len(inv.value_catalogs)` ≥ 4 (was 3); `(2, 2)` is in the dict; `(2, 1)` includes value 3 PAUSED.
4. `docs/research/g2408-capture-procedures.md` exists with 6-8 procedures conforming to the template.
5. Each procedure names: closes-list, trigger type, prerequisites, steps, what-to-look-for, after-capture inventory edits.
6. `docs/TODO.md`'s Blocked section gains a `**Procedure:** [link]` line on every entry that maps to a procedure in capture-procedures.md.
7. `python tools/inventory_gen.py --validate-only` passes (no schema changes).
8. `python tools/inventory_audit.py` (presence + consistency) exits 0.
9. `python -m pytest tests/ -q` shows the same pass count as axis 3 + 3 new (700+).
10. The `mode_enum/s2p1_3` row's runtime visibility is verified: a stub probe log carrying `s2p1 = 3` would no longer fire `[NOVEL/value/catalog-miss]` because the catalog now contains 3.

## 6. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Capture procedures rot if firmware changes | Each procedure includes a "last verified" date; future updates are journal entries, not procedure rewrites. |
| 6-8 procedures don't cover all 137 candidates → users hit a gap with no procedure | Procedures are clustered by trigger archetype; the trigger types section explains what to do for gaps without a procedure (write a new one following the template). |
| Loader merge inverts precedence accidentally | New test `test_inline_value_catalog_takes_precedence_over_section` is the regression gate. |
| Runtime catalog-miss WARNs flood the log if catalogs are now richer | Watchdog dedupe (`saw_catalog_miss` shared cap with `saw_value`) is unchanged — first-time-per-(siid,piid,value) only. Even with 50-entry catalogs, log volume is bounded. |

## 7. Hand-off after axis 4/5

After this axis, the original 5-axis arc is complete:

- **Axis 1**: inventory built, source-of-truth established
- **Axis 2**: docs restructured around inventory + journal
- **Axis 3**: runtime harness + CI
- **Axis 4/5**: catalog merge + capture procedures + TODO cross-refs

Subsequent work falls into normal feature development: each new HA entity, each newly-confirmed inventory row, each captured wire shape becomes a small commit on `main` that runs the existing CI pipeline. The protocol-cleanup project as a discrete arc closes here.

## 8. Open assumptions

- The mode_enum and state_codes section row schemas use `value`/`code` + `name` fields respectively (confirmed by spot-checks during axis 1; inventory_gen.py validator already accepts these shapes). If a section row uses a different field name, the loader will skip it silently — acceptable safety net, but worth a quick grep before implementation to confirm field names.
- The 6-8 procedures cover all 137 candidates by archetype, but a few candidates may need their own procedure. If during writing a candidate doesn't fit any archetype, add a 9th procedure rather than stretching an archetype.
- The "blocked-on-firmware-cooperation" type captures things we genuinely cannot fix from the integration side. Documenting them as such is the right deliverable; setting an unrealistic "we'll get to this" expectation is not.

## 9. References

- Axis 1 spec + plan
- Axis 2 spec + plan (especially the journal at `docs/research/g2408-research-journal.md`)
- Axis 3 spec + plan (especially `inventory/loader.py` and the watchdog wiring in coordinator.py)
- Existing user memory note: "Document confirmed protocol quirks" — once visually confirmed, add coordinate flips / rotation fields / byte layouts to docs/research so contributors don't re-derive
