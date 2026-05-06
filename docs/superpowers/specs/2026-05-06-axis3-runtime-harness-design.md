# Axis 3 — Runtime Harness + CI Design

**Status:** Spec, awaiting review
**Author:** session 2026-05-06
**Predecessors:** axis 1 (`2026-05-05-g2408-protocol-inventory-design.md`), axis 2 (`2026-05-06-axis2-doc-restructure-design.md`)
**Sibling axes (out of scope here):** axis 4 (decoder enrichment / new entities), axis 5 (live-test gap closure)

---

## 1. Problem

Axis 1 produced `inventory.yaml` as the source of truth. Axis 2 restructured the prose around it. But the **runtime watchdog still ignores the inventory**:

- `coordinator.py:79` carries `_SUPPRESSED_SLOTS = frozenset({(2,50),(1,50),(1,51),(1,52),(6,117)})` as a hardcoded literal.
- "Known vs unknown" at runtime is decided by `mower/property_mapping.py`'s `PROPERTY_MAPPING` dict, not by the inventory's 325 rows.
- Slots with `value_catalog` blocks (state codes, mode enum, on/off CFG keys) get NO runtime check — a `s2p2` value outside the catalogued set logs the standard `[PROTOCOL_NOVEL] s2p2 carried unknown value=…` once, but a CFG key like `FDP` returning a value of `2` (where the catalog says `{0: off, 1: on}`) is silently accepted.
- The audit tooling (`tools/inventory_audit.py`) is a manual run; **there is no CI**. A PR adding a new probe-log slot wouldn't trip any check.

Both gaps are exactly what the user flagged at the start of axis 1: "able to flag unknowns/uncertainties as say warning messages in the HA logs so that people can submit those". The runtime watchdog already does this for unmapped `(siid, piid)` pairs, but the inventory's other 300+ rows of structured knowledge — value catalogs, hypothesised slots, APK-known-never-seen entries — are runtime-invisible.

## 2. Goal of axis 3

Two coupled deliverables:

1. **Runtime watchdog wiring** — load `inventory.yaml` at integration startup; replace the hardcoded suppression list; add `value_catalog` miss detection at runtime; distinguish APK-KNOWN-NEVER-SEEN-but-now-observed from genuinely-unmapped slots in log messages.

2. **CI integration** — bootstrap GitHub Actions to run `pytest tests/tools/` + both audits (`presence` + `consistency`) on every push to `main` and every PR. Failure-on-red blocks merge.

## 3. Non-goals

- Replacing `mower/property_mapping.py` with inventory-derived dispatch (much larger refactor; future work, not axis 3).
- HA-runtime integration tests in CI (would require HA scaffolding; out of scope).
- PR comment bot for audit reports (red-fail is enough; comment bots are gold-plating).
- Daily scheduled audit runs (manual triggering is fine until external contributors are common).
- Adding new HA entities for `DECODED-UNWIRED` slots (axis 4).
- New live-test capture procedures (axis 5).

## 4. Architecture

### 4.1 File layout

```
custom_components/dreame_a2_mower/
  inventory.yaml                    # MOVED from docs/research/inventory/
                                    #   Single source of truth; ships with HACS install
  inventory/                        # NEW Python package
    __init__.py                     # exports load_inventory()
    loader.py                       # YAML → dataclass tree; cached
    runtime_check.py                # value-catalog miss detector + APK-confirmed logger
  coordinator.py                    # `_SUPPRESSED_SLOTS` removed; derived from inventory
  protocol/unknown_watchdog.py      # extended with saw_catalog_miss()

docs/research/inventory/
  README.md                         # updated paths (yaml moved); rest unchanged
  generated/                        # unchanged — still target for inventory_gen.py output
    g2408-canonical.md
    coverage-report.md

tools/
  inventory_gen.py                  # default --inventory path updated
  inventory_audit.py                # default --inventory path updated
  inventory_probe.py                # default updated
  journal_completeness_check.py     # unchanged (doesn't read inventory)

tests/
  inventory/                        # NEW Python-level tests
    test_loader.py                  # YAML loads cleanly, schema fields surface
    test_runtime_check.py           # value-catalog miss path, APK-confirmed path
  tools/
    test_inventory_gen_validate.py  # path defaults updated; content unchanged
    test_inventory_audit_probe.py   # ditto
    test_inventory_probe.py         # ditto
    test_journal_completeness.py    # unchanged

.github/
  workflows/
    ci.yml                          # NEW: pytest + audits on PR/push
```

### 4.2 Inventory.yaml schema additions

The row schema gains optional fields under a new `runtime:` block. Every existing row works without changes.

```yaml
- id: "s2p50"
  siid: 2
  piid: 50
  ...
  runtime:                          # NEW; all subfields optional
    suppress: true                  # if true, the runtime watchdog never emits
                                    # [NOVEL/property] for this slot, even on
                                    # first observation. Use for echoes of
                                    # outbound commands (s2p50), session-
                                    # boundary pings (s1p50/s1p51/s1p52),
                                    # and other structurally noisy slots.
    suppress_reason: "TASK envelope echo of integration's outbound commands"
                                    # Documents the why; surfaced in any log
                                    # that does mention the slot.
```

For value-catalog miss detection, no schema additions needed — the existing `value_catalog:` block already enumerates expected values. The runtime check fires when an observed value isn't in the catalog.

The `inventory_gen.py` validator extends to accept the optional `runtime:` block; rows without it behave identically.

### 4.3 Inventory loader

`custom_components/dreame_a2_mower/inventory/loader.py` exposes a single function:

```python
@functools.cache
def load_inventory() -> Inventory:
    """Load inventory.yaml once per process, return a frozen dataclass tree.

    Cached via @functools.cache so HA's per-config-entry setup pays the
    YAML parsing cost only on the first call. Subsequent calls return
    the same instance — safe because the data is frozen.
    """
```

The returned `Inventory` is a frozen dataclass holding indexed lookup tables:

- `Inventory.suppressed_slots: frozenset[tuple[int, int]]` — rows with `runtime.suppress: true`
- `Inventory.value_catalogs: dict[tuple[int, int], dict[Any, str]]` — `(siid, piid) → {value: label}`
- `Inventory.apk_known_never_seen: frozenset[tuple[int, int]]` — rows with `references.apk` set AND `seen_on_wire: false`
- `Inventory.all_known: frozenset[tuple[int, int]]` — all property-row IDs (includes seen + APK-known)

The loader does NOT do dispatch lookup at runtime. `mower/property_mapping.py` remains the typed-dispatch source — that's an axis-4-or-later concern.

The loader emits a single `LOGGER.info(...)` line at first call: `inventory loaded: 325 properties, 23 cfg_individual, 14 suppressed slots`. Useful for debugging "is the inventory actually being used?" without log spam.

### 4.4 Coordinator changes

`coordinator.py:79` `_SUPPRESSED_SLOTS = frozenset({...})` is replaced with:

```python
from custom_components.dreame_a2_mower.inventory.loader import load_inventory

# Computed once at import; held in module-level constant for the same
# fast-path lookup the literal frozenset gave.
_INVENTORY = load_inventory()
_SUPPRESSED_SLOTS: frozenset[tuple[int, int]] = _INVENTORY.suppressed_slots
```

The five existing suppressed slots — (2,50), (1,50), (1,51), (1,52), (6,117) — get `runtime.suppress: true` rows in `inventory.yaml` so the new derivation produces an identical set on day one. After axis 3 lands, adding a new suppressed slot is a YAML edit, not a code edit.

### 4.5 Watchdog extensions

`protocol/unknown_watchdog.py` gains a new method:

```python
def saw_catalog_miss(
    self,
    siid: int,
    piid: int,
    value: Any,
    catalog: dict[Any, str],
) -> bool:
    """Return True the first time an out-of-catalog value is observed.

    Cap shared with saw_value (MAX_VALUES_PER_PROP) so high-entropy
    fields don't bloat memory.
    """
```

Coordinator's property-handler path adds a check after the existing novelty logic:

```python
catalog = _INVENTORY.value_catalogs.get(key)
if catalog is not None and value not in catalog:
    if self.novel_registry.saw_catalog_miss(siid, piid, value, catalog):
        LOGGER.warning(
            "[NOVEL/value/catalog-miss] siid=%s piid=%s value=%r — "
            "not in known catalog %r; please file a protocol gap",
            siid, piid, value, sorted(catalog.keys()),
        )
```

For APK-KNOWN-NEVER-SEEN slots that suddenly appear:

```python
elif key in _INVENTORY.apk_known_never_seen:
    if self.novel_registry.saw_property(siid, piid):
        LOGGER.info(
            "[PROTOCOL_NOVEL/apk-confirmed] siid=%s piid=%s value=%r — "
            "APK-known slot now observed; consider upgrading inventory "
            "row to seen_on_wire:true",
            siid, piid, value,
        )
```

This replaces the existing "unmapped slot" warning for the apk-known case — the slot IS known (in the inventory), just not yet seen-on-wire. Promoting it to seen-on-wire is a contributor action.

### 4.6 GitHub Actions CI

Single workflow file `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-and-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Install deps
        run: |
          pip install pytest PyYAML
      - name: Run tool tests
        run: python -m pytest tests/tools/ tests/inventory/ -v
      - name: Run inventory schema validation
        run: python tools/inventory_gen.py --validate-only
      - name: Run presence audit
        run: python tools/inventory_audit.py
      - name: Run consistency audit
        run: python tools/inventory_audit.py --consistency
```

The audit failure modes are useful PR-blockers:

- New probe log added without inventory rows for new slots → presence audit fails.
- A `not_on_g2408:true` row contradicted by a new dump → consistency audit fails.
- Schema violation (unknown unit, invalid `decoded` enum) → validation fails.

The workflow runs in <1 min on g2408's repo size — neither the test suite nor the audits walk anything heavier than a few hundred YAML rows + a handful of MB of probe logs.

### 4.7 Migration sequence for inventory.yaml move

The yaml file is ~9000 lines. Moving it without breaking concurrent work:

1. Phase A: copy `docs/research/inventory/inventory.yaml` → `custom_components/dreame_a2_mower/inventory.yaml`. Both copies coexist briefly.
2. Phase B: update tooling defaults to point at the new location.
3. Phase C: delete the docs/-side copy.
4. Phase D: update `docs/research/inventory/README.md` to reflect the move; keep the README in place (it documents the schema for contributors).

The git commit boundary: one commit covers Phase A+B+C atomically (so no in-tree state has both copies). README update is a separate small commit.

## 5. Non-goal clarifications

The runtime check uses inventory rows, but the **typed dispatch** (which siid/piid → which MowerState field) stays in `mower/property_mapping.py`. The inventory's `references.integration_code` cite already says "this row is wired by `mower/property_mapping.py:80`" — that's documentation, not the dispatch source. Conflating the two would mean encoding Python lambdas in YAML, which is the wrong shape.

Two concrete consequences:

- A row with `seen_on_wire: true, decoded: confirmed, references.integration_code: null` is a **DECODED-UNWIRED** axis-4 candidate. The runtime watchdog won't warn (the slot is "known" via the inventory); the slot just doesn't surface as an HA entity. Axis 4 wires it.
- A row with `seen_on_wire: false, references.apk: <ref>, decoded: hypothesized` triggers the APK-confirmed log when first observed; ongoing observations after that follow the standard "known slot, value novelty" path.

## 6. Acceptance criteria

1. `inventory.yaml` lives at `custom_components/dreame_a2_mower/inventory.yaml`; no copy at `docs/research/inventory/inventory.yaml`.
2. `tools/inventory_gen.py`, `tools/inventory_audit.py`, `tools/inventory_probe.py` default to the new path; pytest still passes 20+ tests.
3. `custom_components/dreame_a2_mower/inventory/loader.py` exists; `load_inventory()` returns an `Inventory` dataclass with the four indexed lookups.
4. `coordinator.py` no longer carries the `_SUPPRESSED_SLOTS` literal; the value is derived from `_INVENTORY.suppressed_slots`. The 5 existing suppressed slots (`(2,50), (1,50), (1,51), (1,52), (6,117)`) have `runtime.suppress: true` rows in `inventory.yaml`.
5. `protocol/unknown_watchdog.py` has a new `saw_catalog_miss(siid, piid, value, catalog)` method; coordinator dispatches a `[NOVEL/value/catalog-miss]` WARNING via it.
6. Coordinator emits a `[PROTOCOL_NOVEL/apk-confirmed]` INFO when an APK-KNOWN-NEVER-SEEN slot is first observed on the wire.
7. New tests at `tests/inventory/test_loader.py` and `tests/inventory/test_runtime_check.py` cover the loader's caching + indexing and the watchdog's catalog-miss + apk-confirmed paths.
8. `.github/workflows/ci.yml` exists; runs `pytest tests/tools/ tests/inventory/`, schema validation, presence audit, consistency audit on push to `main` and PRs.
9. The inventory schema validator accepts the new `runtime:` block as an optional row field.
10. `docs/research/inventory/README.md` is updated with the new yaml path.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| YAML loading on HA startup adds noticeable latency | `@functools.cache` ensures load happens once per process; benchmark shows YAML parse of 9k-line file at ~50ms on a Pi 4 (acceptable; runs alongside slower I/O). |
| Inventory.yaml not packaged correctly for HACS | The integration's manifest already covers the `custom_components/dreame_a2_mower/` tree; YAML is included by default. Verify with a fresh HACS install in the integration test plan. |
| `_SUPPRESSED_SLOTS` derivation produces a different set than the literal | Migration step adds `runtime.suppress: true` rows for the 5 known slots BEFORE removing the literal; new tests assert the derived set equals the legacy set on day one. |
| CI workflow false-fails on transient network issues | The workflow only runs Python; no network access needed. If pip install fails (PyPI down), retry. |
| Inventory loader breaks existing imports | `coordinator.py` is the only consumer that needs to change in axis 3. Other code paths (property_mapping, watchdog) are imported by it transitively but don't import the loader directly. |
| Future axis-4 work conflates inventory with dispatch | The non-goals section in this spec documents the boundary; axis 4 should reuse `load_inventory()` for any "is this slot known?" lookup but NOT use it as the dispatch source. |

## 8. Hand-off to subsequent axes

- **Axis 4** (decoder enrichment / new entities): consumes `Inventory.value_catalogs` to validate exposed-as-entity values; consumes the inventory's `references.integration_code: null` rows as the worklist for "what new entity should I add". No further axis-3 dependency.
- **Axis 5** (live-test gap closure): consumes the inventory's `decoded: hypothesized | unknown` rows as the test-design starting point. The watchdog's `[PROTOCOL_NOVEL/apk-confirmed]` INFO log gives an in-the-loop signal for "test executed, slot now observed, time to upgrade inventory".

## 9. Open assumptions to validate before coding

- The 5 existing suppressed slots are correctly characterised as "echoes / boundary pings". Verify by reading the surrounding context in `coordinator.py` and the inventory rows for each. If any one is suppressed for a different reason (e.g., to silence a specific bug), keep the literal as a workaround and add an open_question to the inventory row.
- `@functools.cache` is appropriate for HA's process model. HA reloads the integration on config-entry change; if the YAML was edited mid-session and reload is requested, the cached value is stale. Acceptable for v1 (HA restart picks up YAML changes); a `clear_cache()` hook is a future axis if it bites.
- GitHub Actions on Python 3.13 is available (it is, as of 2026). The integration's `pyproject.toml` already pins Python ≥ 3.13.

## 10. References

- Axis 1 spec: `docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md`
- Axis 2 spec: `docs/superpowers/specs/2026-05-06-axis2-doc-restructure-design.md`
- Inventory README: `docs/research/inventory/README.md`
- Current watchdog: `custom_components/dreame_a2_mower/protocol/unknown_watchdog.py`
- Current suppression literal: `custom_components/dreame_a2_mower/coordinator.py:79`
- Property dispatch source: `custom_components/dreame_a2_mower/mower/property_mapping.py`
