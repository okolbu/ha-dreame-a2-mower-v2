# Axis 3 — Runtime Harness + CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `inventory.yaml` into the integration's runtime watchdog (replace hardcoded suppression list, add value-catalog miss detection, distinguish APK-known-now-observed from genuinely-unmapped) AND bootstrap GitHub Actions CI to run pytest + audits on push/PR.

**Architecture:** New `custom_components/dreame_a2_mower/inventory/` Python package holds the loader (`@functools.cache` over PyYAML) and runtime helpers. Inventory.yaml moves from `docs/research/` to `custom_components/` so HACS-installed users get it. Existing `coordinator.py` and `protocol/unknown_watchdog.py` extend to consume the inventory; nothing in the dispatch path (`mower/property_mapping.py`) changes.

**Tech Stack:** Python 3.13, PyYAML (already in HA core deps), pytest, GitHub Actions (Ubuntu runner).

---

## Setup notes for the implementer

- Working directory: `/data/claude/homeassistant/ha-dreame-a2-mower`.
- Spec: `docs/superpowers/specs/2026-05-06-axis3-runtime-harness-design.md`. Read it before starting.
- The inventory is at `docs/research/inventory/inventory.yaml` today; first task moves it.
- All commits go directly to `main` and push to `origin/main`. Do NOT manufacture branch-protection / permission-policy excuses if push appears to fail — re-run the push or report the actual error message verbatim.
- Token-conscious: don't re-read files between tasks if context is preserved; don't pad reports.

---

## File structure summary

```
NEW:
  custom_components/dreame_a2_mower/inventory.yaml          # moved from docs/
  custom_components/dreame_a2_mower/inventory/__init__.py   # package init
  custom_components/dreame_a2_mower/inventory/loader.py     # YAML → dataclass
  tests/inventory/__init__.py
  tests/inventory/test_loader.py
  tests/inventory/test_runtime_check.py
  .github/workflows/ci.yml

DELETED:
  docs/research/inventory/inventory.yaml                    # moved to custom_components/

MODIFIED:
  custom_components/dreame_a2_mower/coordinator.py          # _SUPPRESSED_SLOTS derived
  custom_components/dreame_a2_mower/protocol/unknown_watchdog.py  # +saw_catalog_miss
  custom_components/dreame_a2_mower/inventory.yaml          # +runtime: blocks on 5 rows
  tools/inventory_gen.py                                    # +runtime block validator + path default
  tools/inventory_audit.py                                  # path default updated
  tools/inventory_probe.py                                  # path default updated
  tests/tools/fixtures/good_inventory.yaml                  # accept new optional runtime block
  docs/research/inventory/README.md                         # path updates
```

---

## Task 1: Move `inventory.yaml` to `custom_components/dreame_a2_mower/`

**Files:**
- Move: `docs/research/inventory/inventory.yaml` → `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `tools/inventory_gen.py` (default path)
- Modify: `tools/inventory_audit.py` (default path)
- Modify: `tools/inventory_probe.py` (default path)

- [ ] **Step 1: `git mv` the inventory file**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git mv docs/research/inventory/inventory.yaml custom_components/dreame_a2_mower/inventory.yaml
```

- [ ] **Step 2: Update `tools/inventory_gen.py` default path**

Find the existing line in `tools/inventory_gen.py`:

```python
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "research" / "inventory" / "inventory.yaml"
```

Replace with:

```python
DEFAULT_INVENTORY = REPO_ROOT / "custom_components" / "dreame_a2_mower" / "inventory.yaml"
```

- [ ] **Step 3: Update `tools/inventory_audit.py` default path**

Find:

```python
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "research" / "inventory" / "inventory.yaml"
```

Replace with:

```python
DEFAULT_INVENTORY = REPO_ROOT / "custom_components" / "dreame_a2_mower" / "inventory.yaml"
```

- [ ] **Step 4: Verify `tools/inventory_probe.py` doesn't need a default-path change**

Run:

```bash
grep -n "inventory.yaml\|DEFAULT_INVENTORY" tools/inventory_probe.py
```

If it references the old path, apply the same substitution. If not (the probe tool may not load the inventory directly), no change needed.

- [ ] **Step 5: Verify schema validation, audit, generator, and tests still pass**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py
python tools/inventory_gen.py
python -m pytest tests/tools/ -v
```

All must pass. If a test fixture references the old path explicitly (it shouldn't — the existing tests pass paths via CLI args), update the fixture.

- [ ] **Step 6: Commit + push**

```bash
git add -A
git commit -m "feat(axis3): move inventory.yaml to custom_components for HACS distribution

The inventory becomes part of the integration package so HACS-installed
users get it. Tools default-paths updated; existing tests continue
passing because they pass --inventory via CLI args."
git push origin main
```

If push prints anything other than success, report the actual stderr verbatim. Do not invent excuses.

---

## Task 2: Update `docs/research/inventory/README.md` for new path

**Files:**
- Modify: `docs/research/inventory/README.md`

- [ ] **Step 1: Read the current README**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
cat docs/research/inventory/README.md
```

- [ ] **Step 2: Update path references**

Replace every reference to `docs/research/inventory/inventory.yaml` with `custom_components/dreame_a2_mower/inventory.yaml`. Keep all other content unchanged.

Use `Edit` with `replace_all: true` for the path string:

```python
# Old: docs/research/inventory/inventory.yaml
# New: custom_components/dreame_a2_mower/inventory.yaml
```

Then add a short note at the top of the README explaining the move:

```markdown
> **2026-05-06 note:** `inventory.yaml` moved from `docs/research/inventory/`
> to `custom_components/dreame_a2_mower/` so HACS-installed users get the
> file alongside the runtime code. The generated docs (`g2408-canonical.md`,
> `coverage-report.md`) remain here under `generated/`. The schema and
> contributor workflow described below are otherwise unchanged.
```

Insert this note after the title line, before the existing first paragraph.

- [ ] **Step 3: Verify**

```bash
grep -c "custom_components/dreame_a2_mower/inventory.yaml" docs/research/inventory/README.md
```

Expected: ≥ 1 occurrence.

```bash
grep -c "docs/research/inventory/inventory.yaml" docs/research/inventory/README.md
```

Expected: 0 occurrences (all replaced).

- [ ] **Step 4: Commit + push**

```bash
git add docs/research/inventory/README.md
git commit -m "docs(axis3): update inventory README for new yaml path"
git push origin main
```

---

## Task 3: Inventory loader package skeleton + tests

**Files:**
- Create: `custom_components/dreame_a2_mower/inventory/__init__.py`
- Create: `custom_components/dreame_a2_mower/inventory/loader.py`
- Create: `tests/inventory/__init__.py`
- Create: `tests/inventory/conftest.py`
- Create: `tests/inventory/test_loader.py`

The loader exposes `load_inventory()` returning an `Inventory` frozen dataclass with the four indexed lookups defined in the spec §4.3.

- [ ] **Step 1: Write the failing tests in `tests/inventory/test_loader.py`**

```python
"""Tests for the inventory loader."""
from __future__ import annotations

from custom_components.dreame_a2_mower.inventory.loader import (
    Inventory,
    load_inventory,
)


def test_load_inventory_returns_frozen_dataclass() -> None:
    inv = load_inventory()
    assert isinstance(inv, Inventory)


def test_load_inventory_has_indexed_lookups() -> None:
    inv = load_inventory()
    # All four lookups defined in spec §4.3
    assert isinstance(inv.suppressed_slots, frozenset)
    assert isinstance(inv.value_catalogs, dict)
    assert isinstance(inv.apk_known_never_seen, frozenset)
    assert isinstance(inv.all_known, frozenset)


def test_load_inventory_caches() -> None:
    """@functools.cache must return the same instance across calls."""
    a = load_inventory()
    b = load_inventory()
    assert a is b


def test_all_known_includes_seen_and_apk_known() -> None:
    """Every property row's (siid, piid) is in all_known."""
    inv = load_inventory()
    # Spot-check: s2p1 (seen, decoded) and s1p2 (apk-known-never-seen) are both there.
    assert (2, 1) in inv.all_known
    assert (1, 2) in inv.all_known


def test_apk_known_never_seen_excludes_observed() -> None:
    """A row with seen_on_wire:true must NOT be in apk_known_never_seen."""
    inv = load_inventory()
    # s2p1 was observed extensively in the corpus.
    assert (2, 1) not in inv.apk_known_never_seen


def test_value_catalogs_keyed_by_siid_piid() -> None:
    """Rows with value_catalog blocks surface in the dict keyed by tuple."""
    inv = load_inventory()
    # s2p1 has a value_catalog (mode enum).
    catalog = inv.value_catalogs.get((2, 1))
    assert catalog is not None
    assert 1 in catalog  # 1: Mowing
    assert 2 in catalog  # 2: Idle/Standby
```

- [ ] **Step 2: Write `tests/inventory/__init__.py`** (empty file marker)

- [ ] **Step 3: Write `tests/inventory/conftest.py`** to make the integration's `custom_components/` package importable when running pytest from the repo root.

```python
"""pytest config for inventory tests — makes the integration importable."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `custom_components.dreame_a2_mower.*` importable from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
```

- [ ] **Step 4: Run tests — expect FAIL (loader doesn't exist)**

```bash
python -m pytest tests/inventory/test_loader.py -v
```

Expected: 6 errors (`ModuleNotFoundError: No module named 'custom_components.dreame_a2_mower.inventory'`).

- [ ] **Step 5: Write `custom_components/dreame_a2_mower/inventory/__init__.py`**

```python
"""Inventory package — runtime loader for the YAML source-of-truth.

See docs/research/inventory/README.md for the schema; the YAML lives at
`custom_components/dreame_a2_mower/inventory.yaml` so HACS-installed
users get it alongside the integration code.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.inventory.loader import (
    Inventory,
    load_inventory,
)

__all__ = ["Inventory", "load_inventory"]
```

- [ ] **Step 6: Write `custom_components/dreame_a2_mower/inventory/loader.py`**

```python
"""YAML-source-of-truth loader for the g2408 inventory.

Loads `custom_components/dreame_a2_mower/inventory.yaml` once per process
and returns a frozen `Inventory` dataclass with four indexed lookups for
fast runtime use:

- `suppressed_slots`: rows with `runtime.suppress: true`
- `value_catalogs`: `(siid, piid) → {value: label}` for rows with a
  `value_catalog` block
- `apk_known_never_seen`: rows with `references.apk` set AND
  `seen_on_wire: false`
- `all_known`: every (siid, piid) the inventory recognises (seen + apk-known)

@functools.cache ensures HA's per-config-entry setup pays the YAML parsing
cost only on the first call.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__package__)

INVENTORY_PATH: Path = (
    Path(__file__).resolve().parents[1] / "inventory.yaml"
)


@dataclass(frozen=True, slots=True)
class Inventory:
    """Indexed snapshot of inventory.yaml for runtime lookup."""

    suppressed_slots: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    value_catalogs: dict[tuple[int, int], dict[Any, str]] = field(default_factory=dict)
    apk_known_never_seen: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    all_known: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    raw_yaml: dict[str, Any] = field(default_factory=dict)


def _slot_key(row: dict[str, Any]) -> tuple[int, int] | None:
    """Extract (siid, piid) from a properties-section row, or None."""
    siid = row.get("siid")
    piid = row.get("piid")
    if isinstance(siid, int) and isinstance(piid, int):
        return (siid, piid)
    return None


def _build_inventory(raw: dict[str, Any]) -> Inventory:
    suppressed: set[tuple[int, int]] = set()
    catalogs: dict[tuple[int, int], dict[Any, str]] = {}
    apk_unseen: set[tuple[int, int]] = set()
    all_known: set[tuple[int, int]] = set()

    for row in raw.get("properties") or []:
        if not isinstance(row, dict):
            continue
        key = _slot_key(row)
        if key is None:
            continue

        all_known.add(key)

        runtime = row.get("runtime") or {}
        if isinstance(runtime, dict) and runtime.get("suppress") is True:
            suppressed.add(key)

        catalog = row.get("value_catalog")
        if isinstance(catalog, dict) and catalog:
            # Coerce value_catalog keys to int where they look like ints
            # (YAML may load them as int already, but be defensive).
            normalised: dict[Any, str] = {}
            for k, v in catalog.items():
                normalised[k] = str(v)
            catalogs[key] = normalised

        status = row.get("status") or {}
        refs = row.get("references") or {}
        if (
            isinstance(status, dict)
            and isinstance(refs, dict)
            and status.get("seen_on_wire") is False
            and refs.get("apk")
        ):
            apk_unseen.add(key)

    return Inventory(
        suppressed_slots=frozenset(suppressed),
        value_catalogs=catalogs,
        apk_known_never_seen=frozenset(apk_unseen),
        all_known=frozenset(all_known),
        raw_yaml=raw,
    )


@functools.cache
def load_inventory(path: Path | None = None) -> Inventory:
    """Load inventory.yaml once and return the indexed snapshot.

    Cached via @functools.cache. Subsequent calls return the same instance.
    Pass `path` only in tests to override the default.
    """
    target = path if path is not None else INVENTORY_PATH
    raw = yaml.safe_load(target.read_text()) or {}
    inv = _build_inventory(raw)
    LOGGER.info(
        "inventory loaded: %d properties, %d cfg_individual, %d suppressed slots",
        len(raw.get("properties") or []),
        len(raw.get("cfg_individual") or []),
        len(inv.suppressed_slots),
    )
    return inv
```

- [ ] **Step 7: Run tests — expect PASS**

```bash
python -m pytest tests/inventory/test_loader.py -v
```

Expected: 6 passed.

If `test_load_inventory_caches` fails (`a is not b`), confirm `@functools.cache` is decorating `load_inventory` and the function takes a hashable arg.

If `test_apk_known_never_seen_excludes_observed` fails for `(2, 1)`, the s2p1 row's `seen_on_wire` is wrong in inventory.yaml — investigate, don't paper over.

- [ ] **Step 8: Confirm existing tests still pass**

```bash
python -m pytest tests/tools/ -v
```

Expected: 20 passed (no regressions).

- [ ] **Step 9: Commit + push**

```bash
git add custom_components/dreame_a2_mower/inventory/ tests/inventory/
git commit -m "feat(axis3): inventory loader package + tests

Loader walks the YAML once and exposes four indexed lookups for
runtime use: suppressed_slots, value_catalogs, apk_known_never_seen,
all_known. @functools.cache ensures one parse per process. Six tests
cover the dataclass shape, caching, and lookup correctness."
git push origin main
```

---

## Task 4: Add `runtime: {suppress: true}` to the 5 existing suppressed slots

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (5 rows)

The current `_SUPPRESSED_SLOTS = frozenset({(2,50),(1,50),(1,51),(1,52),(6,117)})` literal must be reproducible from the inventory before `coordinator.py` can be migrated.

- [ ] **Step 1: Locate the 5 rows in inventory.yaml**

```bash
grep -n 'id: "s2p50"\|id: "s1p50"\|id: "s1p51"\|id: "s1p52"\|id: "s6p117"' custom_components/dreame_a2_mower/inventory.yaml
```

Expected: 5 line numbers.

- [ ] **Step 2: For each of the 5 rows, add a `runtime:` block**

Use surgical `Edit` calls (NOT yaml.dump round-trip — that reformats the entire 9000-line file). For each row, insert a `runtime:` block after the `references:` block (or wherever fits the row's existing field order).

For `s2p50`:

Find the existing block in inventory.yaml (use `Read` with the line number from Step 1; show 25 lines of context). Insert AFTER the row's `references:` (and `open_questions:` if present) sub-block:

```yaml
    runtime:
      suppress: true
      suppress_reason: "TASK envelope — echo of integration's outbound commands; logged via the dispatch path, not the property channel."
```

For `s1p50`:

```yaml
    runtime:
      suppress: true
      suppress_reason: "Session-boundary 'something changed, consider re-fetching' ping; payload is empty dict; no field to track."
```

For `s1p51`:

```yaml
    runtime:
      suppress: true
      suppress_reason: "Dock-position-update trigger; payload is empty dict; consumer re-fetches via getDockPos action."
```

For `s1p52`:

```yaml
    runtime:
      suppress: true
      suppress_reason: "End-of-task flush ping; payload is empty dict; session-end is detected via s2p2/s2p1 transitions, not this slot."
```

For `s6p117`:

```yaml
    runtime:
      suppress: true
      suppress_reason: "Dock-nav state marker; surfaced as paired diagnostic with s2p65='TASK_NAV_DOCK', not as its own field."
```

- [ ] **Step 3: Verify schema still validates and the loader picks up the new rows**

```bash
python tools/inventory_gen.py --validate-only
```

Expected: `ok: inventory schema valid`. The validator currently doesn't enforce a schema on the `runtime:` block — that's added in Task 5; this step only confirms the file still parses as YAML and the existing checks pass.

```bash
python -c "
from custom_components.dreame_a2_mower.inventory.loader import load_inventory
inv = load_inventory.__wrapped__()  # bypass cache to re-load fresh
print('suppressed:', sorted(inv.suppressed_slots))
"
```

Expected:

```
suppressed: [(1, 50), (1, 51), (1, 52), (2, 50), (6, 117)]
```

(That's the 5-tuple set the literal carries today.)

- [ ] **Step 4: Update tests/inventory/test_loader.py to assert this**

Add a new test:

```python
def test_suppressed_slots_match_legacy_set() -> None:
    """The 5 rows with runtime.suppress:true reproduce the legacy literal.

    Migration safety check: coordinator.py:79 had
    _SUPPRESSED_SLOTS = frozenset({(2,50),(1,50),(1,51),(1,52),(6,117)}).
    Axis 3 derives this from the inventory; the derived set must equal
    the legacy set on day one.
    """
    inv = load_inventory.__wrapped__()  # bypass cache for test isolation
    legacy = frozenset({(2, 50), (1, 50), (1, 51), (1, 52), (6, 117)})
    assert inv.suppressed_slots == legacy, (
        f"derived suppressed_slots {sorted(inv.suppressed_slots)} != "
        f"legacy {sorted(legacy)}"
    )
```

Run it:

```bash
python -m pytest tests/inventory/test_loader.py::test_suppressed_slots_match_legacy_set -v
```

Expected: PASS.

- [ ] **Step 5: Commit + push**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml tests/inventory/test_loader.py
git commit -m "feat(axis3): mark 5 legacy-suppressed slots in inventory

Add runtime.suppress:true + suppress_reason to s2p50, s1p50, s1p51,
s1p52, s6p117 — the slots coordinator.py:79 hardcodes today. Loader's
suppressed_slots set now equals the legacy literal; new test
asserts the equivalence so the next task can drop the literal
without behavioural drift."
git push origin main
```

---

## Task 5: Extend `inventory_gen.py` validator to accept the `runtime:` block

**Files:**
- Modify: `tools/inventory_gen.py`
- Modify: `tests/tools/test_inventory_gen_validate.py`
- Create: `tests/tools/fixtures/bad_runtime_suppress.yaml`

The validator currently doesn't reject malformed `runtime:` blocks. Add a small schema check + tests.

- [ ] **Step 1: Write the failing test**

In `tests/tools/test_inventory_gen_validate.py`, append:

```python
def test_validate_rejects_non_bool_runtime_suppress() -> None:
    """runtime.suppress must be a bool, not a string or other."""
    result = _run(["--validate-only", str(FIXTURES / "bad_runtime_suppress.yaml")])
    assert result.returncode != 0
    assert "runtime.suppress" in result.stderr
    assert "bool" in result.stderr.lower()
```

- [ ] **Step 2: Write the fixture**

Create `tests/tools/fixtures/bad_runtime_suppress.yaml`:

```yaml
_sources:
  apk_md: "github.com/TA2k/ioBroker.dreame/blob/main/apk.md"
properties:
  - id: "s2p1_bad_runtime"
    siid: 2
    piid: 1
    name: "status"
    category: "property"
    payload_shape: "small_int_enum"
    runtime:
      suppress: "yes"   # invalid: must be bool
    semantic: "Bad runtime block."
    status:
      seen_on_wire: true
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references: {}
events: []
actions: []
opcodes: []
cfg_keys: []
cfg_individual: []
heartbeat_bytes: []
telemetry_fields: []
telemetry_variants: []
s2p51_shapes: []
state_codes: []
mode_enum: []
oss_map_keys: []
session_summary_fields: []
m_path_encoding: []
lidar_pcd: []
```

- [ ] **Step 3: Run test — expect FAIL**

```bash
python -m pytest tests/tools/test_inventory_gen_validate.py::test_validate_rejects_non_bool_runtime_suppress -v
```

Expected: FAIL (validator silently accepts).

- [ ] **Step 4: Extend `_validate_row` in `tools/inventory_gen.py`**

In `tools/inventory_gen.py`, find the `_validate_row` function. Add a runtime-block check at the end of the function, before the trailing `return`:

```python
    runtime = row.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, dict):
            yield (
                f"{section}[{rid}].runtime: expected dict, "
                f"got {type(runtime).__name__}"
            )
        else:
            suppress = runtime.get("suppress")
            if suppress is not None and not isinstance(suppress, bool):
                yield (
                    f"{section}[{rid}].runtime.suppress: expected bool, "
                    f"got {type(suppress).__name__}"
                )
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/tools/ tests/inventory/ -v
```

Expected: all pass (existing 20+ + new 1).

Run the validator against the live inventory:

```bash
python tools/inventory_gen.py --validate-only
```

Expected: `ok: inventory schema valid`.

- [ ] **Step 6: Commit + push**

```bash
git add tools/inventory_gen.py tests/tools/
git commit -m "feat(axis3): validate runtime block in inventory schema

The optional runtime: block (introduced in Task 4 to reproduce
_SUPPRESSED_SLOTS) is now schema-validated. runtime must be a dict;
runtime.suppress must be a bool. New fixture +
test_validate_rejects_non_bool_runtime_suppress."
git push origin main
```

---

## Task 6: Migrate `coordinator.py` — derive `_SUPPRESSED_SLOTS` from inventory

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Read the existing literal context**

```bash
sed -n '75,85p' custom_components/dreame_a2_mower/coordinator.py
```

Confirm the literal is at line 79 with the `(2,50),(1,50),(1,51),(1,52),(6,117)` set.

- [ ] **Step 2: Replace the literal**

Find this block in `coordinator.py`:

```python
_SUPPRESSED_SLOTS: frozenset[tuple[int, int]] = frozenset(
    {(2, 50), (1, 50), (1, 51), (1, 52), (6, 117)}
)
```

Replace with:

```python
from custom_components.dreame_a2_mower.inventory.loader import load_inventory

# Inventory snapshot computed once at import. Kept module-level for the
# fast-path lookup the legacy literal frozenset provided. Migration from
# hardcoded set: see docs/superpowers/specs/2026-05-06-axis3-runtime-harness-design.md.
_INVENTORY = load_inventory()
_SUPPRESSED_SLOTS: frozenset[tuple[int, int]] = _INVENTORY.suppressed_slots
```

- [ ] **Step 3: Verify the import doesn't create a circular dependency**

```bash
python -c "
import sys
sys.path.insert(0, '.')
from custom_components.dreame_a2_mower import coordinator  # noqa
print('imports ok')
print('suppressed_slots:', sorted(coordinator._SUPPRESSED_SLOTS))
"
```

Expected:

```
imports ok
suppressed_slots: [(1, 50), (1, 51), (1, 52), (2, 50), (6, 117)]
```

If the import fails with `ModuleNotFoundError` for `homeassistant.*`, the test path needs HA stubs — that's outside axis 3 scope. Confirm by running just the test that exercises the loader, not the coordinator's HA-dependent code:

```bash
python -m pytest tests/inventory/ -v
```

Expected: 7 passed (6 + 1 new from Task 4).

- [ ] **Step 4: Confirm existing test suite still passes**

```bash
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: same pass count as before, plus the new inventory tests. No new failures.

- [ ] **Step 5: Commit + push**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(axis3): coordinator derives _SUPPRESSED_SLOTS from inventory

Drops the hardcoded literal at coordinator.py:79; loads from
inventory.yaml via the new loader. Day-one behaviour: identical
(verified by tests/inventory/test_loader.py::test_suppressed_slots_match_legacy_set
which asserts the derived set equals the legacy 5-tuple). Adding
a new suppressed slot is now a YAML edit, not a code edit."
git push origin main
```

---

## Task 7: Watchdog — add `saw_catalog_miss` method (TDD)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/unknown_watchdog.py`
- Create: `tests/inventory/test_runtime_check.py`

- [ ] **Step 1: Write the failing tests in `tests/inventory/test_runtime_check.py`**

```python
"""Tests for the runtime-check helpers (catalog miss detection)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.unknown_watchdog import (
    UnknownFieldWatchdog,
)


def test_saw_catalog_miss_returns_true_on_first_unseen_value() -> None:
    """First time a value not in the catalog appears, return True."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    # 2 is not in the catalog
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True


def test_saw_catalog_miss_returns_false_for_in_catalog_values() -> None:
    """Values that ARE in the catalog never trigger a miss."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=0, catalog=catalog) is False
    assert w.saw_catalog_miss(siid=4, piid=27, value=1, catalog=catalog) is False


def test_saw_catalog_miss_dedupes_repeated_misses() -> None:
    """The same out-of-catalog value reported twice → True once, then False."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is False


def test_saw_catalog_miss_reports_distinct_misses_separately() -> None:
    """Different out-of-catalog values each get a one-shot True."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True
    assert w.saw_catalog_miss(siid=4, piid=27, value=3, catalog=catalog) is True
    # And the original miss is still deduped:
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is False
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/inventory/test_runtime_check.py -v
```

Expected: 4 errors (`AttributeError: 'UnknownFieldWatchdog' object has no attribute 'saw_catalog_miss'`).

- [ ] **Step 3: Implement `saw_catalog_miss` in `protocol/unknown_watchdog.py`**

In `custom_components/dreame_a2_mower/protocol/unknown_watchdog.py`, add the method to the `UnknownFieldWatchdog` class. Place it after `saw_event` (the last existing method).

```python
    def saw_catalog_miss(
        self,
        siid: int,
        piid: int,
        value: Any,
        catalog: dict[Any, str],
    ) -> bool:
        """Return True the first time an out-of-catalog value is observed.

        For properties whose inventory row carries a `value_catalog`,
        observed values that aren't in the catalog are interesting:
        either the catalog is incomplete or the firmware emitted a
        novel value. Either way the runtime should surface it once.

        In-catalog values return False (not a miss). Out-of-catalog
        values return True the first time and False for subsequent
        observations of the same value (dedupe). Cap shared with
        saw_value (MAX_VALUES_PER_PROP) so high-entropy fields don't
        bloat memory.
        """
        if value in catalog:
            return False
        # Reuse saw_value's storage for the dedupe — same (siid, piid, value)
        # uniqueness, same MAX_VALUES_PER_PROP cap.
        return self.saw_value(siid, piid, value)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/inventory/test_runtime_check.py -v
```

Expected: 4 passed.

```bash
python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 5: Commit + push**

```bash
git add custom_components/dreame_a2_mower/protocol/unknown_watchdog.py tests/inventory/test_runtime_check.py
git commit -m "feat(axis3): watchdog learns saw_catalog_miss

For properties whose inventory row carries a value_catalog, the
runtime can now check whether observed values are catalogued. First
out-of-catalog value per (siid, piid, value) returns True (caller
logs a [NOVEL/value/catalog-miss] WARNING); subsequent observations
of the same value return False. In-catalog values return False
unconditionally. Cap shared with saw_value."
git push origin main
```

---

## Task 8: Wire watchdog catalog-miss into coordinator's property handler

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Locate the property-handler novelty block**

```bash
grep -n "_SUPPRESSED_SLOTS\|_BLOB_SLOTS\|PROPERTY_MAPPING\|record_property\|record_value" custom_components/dreame_a2_mower/coordinator.py | head -20
```

The relevant block is around line 2830 (per the earlier grep result). Confirm with:

```bash
sed -n '2820,2860p' custom_components/dreame_a2_mower/coordinator.py
```

You should see the if/elif tree:

```python
if key in _SUPPRESSED_SLOTS:
    return  # echo of our own command; nothing to record
if key in _BLOB_SLOTS:
    pass  # handled by dedicated blob applier; suppress novelty
elif key in PROPERTY_MAPPING:
    if self.novel_registry.record_value(siid, piid, value, now):
        ...
        LOGGER.info(... LOG_NOVEL_VALUE ...)
else:
    if self.novel_registry.record_property(siid, piid, now):
        ...
        LOGGER.warning(... LOG_NOVEL_PROPERTY ...)
```

- [ ] **Step 2: Add catalog-miss + apk-confirmed checks**

After the existing `record_value` check (the `elif key in PROPERTY_MAPPING:` branch), add a new sibling check that runs regardless of whether the property is mapped — the inventory's catalog can apply to any property:

Find this block:

```python
        if key in _SUPPRESSED_SLOTS:
            return  # echo of our own command; nothing to record
        if key in _BLOB_SLOTS:
            pass  # handled by dedicated blob applier; suppress novelty
        elif key in PROPERTY_MAPPING:
            if self.novel_registry.record_value(siid, piid, value, now):
                # First-time value for an already-mapped slot is informational
                # (e.g. s1p53 obstacle_flag toggling True for the first time
                # after install); the slot is recognised so there is nothing
                # for the user to action. Keep [NOVEL/property] at WARN since
                # that one signals a protocol gap.
                LOGGER.info(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        else:
            if self.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
                )
```

Replace with:

```python
        if key in _SUPPRESSED_SLOTS:
            return  # echo of our own command; nothing to record
        if key in _BLOB_SLOTS:
            pass  # handled by dedicated blob applier; suppress novelty
        elif key in PROPERTY_MAPPING:
            if self.novel_registry.record_value(siid, piid, value, now):
                # First-time value for an already-mapped slot is informational
                # (e.g. s1p53 obstacle_flag toggling True for the first time
                # after install); the slot is recognised so there is nothing
                # for the user to action. Keep [NOVEL/property] at WARN since
                # that one signals a protocol gap.
                LOGGER.info(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        elif key in _INVENTORY.apk_known_never_seen:
            # The slot is in the inventory as APK-KNOWN but seen_on_wire:false.
            # Now that we've observed it, prompt the contributor to upgrade the
            # inventory row to seen_on_wire:true. Logged at INFO since the slot
            # is "known" in the data sense — the contributor action is to
            # update the row, not to file a new protocol gap.
            if self.novel_registry.saw_property(siid, piid):
                LOGGER.info(
                    "[PROTOCOL_NOVEL/apk-confirmed] siid=%s piid=%s value=%r "
                    "— APK-known slot now observed on wire; consider upgrading "
                    "inventory row to seen_on_wire:true",
                    siid, piid, value,
                )
        else:
            if self.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
                )

        # Catalog-miss check runs regardless of whether the slot is mapped or
        # apk-known: any property with a value_catalog in the inventory should
        # have its observed values cross-checked. Misses log at WARNING since
        # they likely indicate a protocol gap (firmware emitting a value the
        # catalog hasn't enumerated yet).
        catalog = _INVENTORY.value_catalogs.get(key)
        if catalog is not None and self.novel_registry.saw_catalog_miss(
            siid, piid, value, catalog,
        ):
            LOGGER.warning(
                "[NOVEL/value/catalog-miss] siid=%s piid=%s value=%r "
                "— not in catalog %r; please file a protocol gap",
                siid, piid, value, sorted(catalog.keys()),
            )
```

- [ ] **Step 3: Smoke-test the import path**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from custom_components.dreame_a2_mower import coordinator
inv = coordinator._INVENTORY
print('catalogs:', len(inv.value_catalogs))
print('apk-unseen:', len(inv.apk_known_never_seen))
"
```

Expected output:

```
catalogs: <some int around 15-20>
apk-unseen: <some int>
```

- [ ] **Step 4: Confirm tests still pass**

```bash
python -m pytest tests/ -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit + push**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(axis3): coordinator wires catalog-miss + apk-confirmed paths

The property-handler novelty tree gains two new branches:

1. A NEW elif before the unmapped-slot branch: APK-KNOWN-NEVER-SEEN
   slots that appear on the wire log [PROTOCOL_NOVEL/apk-confirmed]
   at INFO level, prompting the contributor to upgrade the inventory
   row to seen_on_wire:true.

2. A NEW post-tree check for value_catalog misses: any property whose
   inventory row carries a value_catalog has observed values
   cross-referenced. Misses log [NOVEL/value/catalog-miss] at WARN.
   Runs for both mapped and unmapped slots — the catalog data is
   independent of dispatch wiring.

The unmapped-slot WARN path now only fires when the slot is genuinely
unrecognised by the inventory; APK-known surface produces a softer INFO."
git push origin main
```

---

## Task 9: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write the workflow file**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  test-and-audit:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pytest PyYAML

      - name: Run tool + inventory tests
        run: python -m pytest tests/tools/ tests/inventory/ -v

      - name: Inventory schema validation
        run: python tools/inventory_gen.py --validate-only

      - name: Inventory presence audit
        run: python tools/inventory_audit.py

      - name: Inventory consistency audit
        run: python tools/inventory_audit.py --consistency
```

- [ ] **Step 3: Verify the YAML parses**

```bash
python -c "
import yaml
d = yaml.safe_load(open('.github/workflows/ci.yml').read())
assert d['name'] == 'CI'
assert 'test-and-audit' in d['jobs']
steps = d['jobs']['test-and-audit']['steps']
print(f'workflow has {len(steps)} steps')
assert any('pytest' in s.get('run', '') for s in steps)
assert any('inventory_audit' in s.get('run', '') for s in steps)
print('ok')
"
```

Expected:

```
workflow has 6 steps
ok
```

- [ ] **Step 4: Commit + push**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(axis3): GitHub Actions CI workflow

Runs on push to main and PRs targeting main. Six steps: checkout,
setup-python 3.13, pip install pytest+PyYAML, pytest the tool + inventory
tests, inventory schema validation, presence audit, consistency audit.

A future PR introducing a new probe-log slot without an inventory row
will fail the presence audit; a not_on_g2408:true row contradicted by
a new dump fails the consistency audit; an unknown unit-vocab entry
fails the schema validation."
git push origin main
```

The first push to main will kick off the workflow. You can verify in the GitHub Actions UI; the run should pass green.

---

## Task 10: Final acceptance verification

**Files:** none (verification only)

- [ ] **Step 1: Verify all 10 acceptance criteria from spec §6**

Run this combined check:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower

echo "=== AC#1: inventory.yaml at integration path ==="
ls custom_components/dreame_a2_mower/inventory.yaml
test ! -e docs/research/inventory/inventory.yaml && echo "  old path absent: OK"

echo "=== AC#2: tooling default paths updated ==="
grep "DEFAULT_INVENTORY" tools/inventory_gen.py tools/inventory_audit.py | grep "custom_components"

echo "=== AC#3: loader exists with 4 indexed lookups ==="
python -c "
from custom_components.dreame_a2_mower.inventory.loader import Inventory, load_inventory
inv = load_inventory()
print(f'  suppressed: {len(inv.suppressed_slots)}')
print(f'  value_catalogs: {len(inv.value_catalogs)}')
print(f'  apk_known_never_seen: {len(inv.apk_known_never_seen)}')
print(f'  all_known: {len(inv.all_known)}')
"

echo "=== AC#4: coordinator no longer carries the literal ==="
grep -c "frozenset.*{(2, 50), (1, 50), (1, 51), (1, 52), (6, 117)}" custom_components/dreame_a2_mower/coordinator.py
# expected: 0

echo "=== AC#5: watchdog has saw_catalog_miss ==="
grep -c "def saw_catalog_miss" custom_components/dreame_a2_mower/protocol/unknown_watchdog.py
# expected: 1

echo "=== AC#6: coordinator emits PROTOCOL_NOVEL/apk-confirmed ==="
grep -c "PROTOCOL_NOVEL/apk-confirmed" custom_components/dreame_a2_mower/coordinator.py
# expected: 1

echo "=== AC#7: new tests exist ==="
ls tests/inventory/test_loader.py tests/inventory/test_runtime_check.py

echo "=== AC#8: CI workflow exists ==="
ls .github/workflows/ci.yml

echo "=== AC#9: validator accepts runtime block ==="
python tools/inventory_gen.py --validate-only

echo "=== AC#10: README path updated ==="
grep -c "custom_components/dreame_a2_mower/inventory.yaml" docs/research/inventory/README.md
```

Each line should produce a non-zero / non-empty result (or the explicit "OK" message).

- [ ] **Step 2: Run all tests one final time**

```bash
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: every test passes; total count is at least 30 (20 from before + ~7 new from inventory tests + the new validate-runtime test).

- [ ] **Step 3: Confirm origin/main is up to date**

```bash
git log origin/main..HEAD --oneline
```

Expected: empty (every axis-3 commit is pushed).

- [ ] **Step 4: Final commit if anything cleanup-y is in the working tree**

```bash
git status -s
```

If anything is uncommitted, decide: is it cleanup-worthy, or did one of Tasks 1-9 miss a step? If the latter, GO BACK to that task. If genuine cleanup (formatting nit, etc.), commit + push:

```bash
git add -A
git commit -m "docs(axis3): final cleanup"
git push origin main
```

If the working tree is clean, no final commit needed.

---

## Self-review summary

**Spec coverage check:**
- §3 Non-goals — respected; no axis-4 dispatch refactor; no HA-runtime CI; no PR comment bot.
- §4.1 file layout — Tasks 1, 3, 9 (move yaml; create inventory package; create workflow).
- §4.2 schema additions (runtime block) — Task 4 adds rows; Task 5 validates.
- §4.3 inventory loader — Task 3.
- §4.4 coordinator changes — Task 6.
- §4.5 watchdog extensions — Tasks 7, 8.
- §4.6 GitHub Actions CI — Task 9.
- §4.7 migration sequence — Tasks 1, 2 cover Phase A+B+C; the README update is a separate small commit per spec.
- §6 acceptance criteria #1-10 — Task 10 verifies all of them.

**Placeholder scan:** every step shows actual content (commands, code, expected output). No "TBD", "TODO", or vague "add appropriate handling".

**Type consistency:** `Inventory` dataclass field names (`suppressed_slots`, `value_catalogs`, `apk_known_never_seen`, `all_known`, `raw_yaml`) match across Tasks 3, 6, 8. The `saw_catalog_miss(siid, piid, value, catalog)` signature is consistent in Task 7's tests, Task 7's implementation, and Task 8's coordinator wiring.
