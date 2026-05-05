# g2408 Protocol Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a YAML-sourced, generator-rendered inventory covering every protocol artefact the integration touches on a Dreame A2 (g2408) — properties, events, actions, opcodes, CFG keys, heartbeat bytes, telemetry fields, OSS payloads, etc. — so future reviews don't keep missing apk-known slots.

**Architecture:** `inventory.yaml` is the source of truth. `tools/inventory_gen.py` renders a human-readable chapter-style markdown doc. `tools/inventory_audit.py` walks the probe-log corpus and cloud dumps and reports any slot not in the inventory. `tools/inventory_probe.py` does read-only cloud RPCs to verify endpoints, with explicit per-batch user confirmation. Alt-repo clones (`alternatives/`, `ioBroker.dreame/`, `dreame-mova-mower/`, `ha-dreame-a2-mower-legacy/`) are absorbed and moved to `OLD/` once their content is reflected in the inventory.

**Tech Stack:** Python 3.13, PyYAML (already present in HA's bundled deps), pytest, ruff, mypy. Tools are stand-alone scripts under `tools/` — no HA runtime dependencies in axis 1.

---

## Setup notes for the implementer

- Working directory: `/data/claude/homeassistant/ha-dreame-a2-mower/` (the integration repo).
- Source artefacts the inventory cross-walks against live one level up at `/data/claude/homeassistant/`:
  - `probe_log_*.jsonl` — five files, ~14.7 k MQTT frames in the largest.
  - `dreame_cloud_dumps/dump_*.json` — currently two; a third is being written by a running script (`dreame_cloud_dump.py`, PID 1330347 at plan-write time).
  - `ioBroker.dreame/apk.md` — the apk decompilation reference.
  - `alternatives/dreame-mower/`, `alternatives/dreame-vacuum/`, `dreame-mova-mower/`, `ha-dreame-a2-mower-legacy/` — alt-repo clones.
  - `ha-credentials.txt` — HA REST/WebSocket creds for in-situ queries (read in place; never copy out).
  - `server-credentials.txt` — Dreame cloud creds (same rule).
- The integration is currently running on the user's HA. The mower may be mowing during plan execution. Probes that change device state are out of scope for axis 1; reads are gated per §4.7 of the spec.
- Spec: `docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md` — read before starting if you're a fresh subagent.

---

## Task 1: Bootstrap directories, schema doc, and empty YAML

**Files:**
- Create: `docs/research/inventory/inventory.yaml`
- Create: `docs/research/inventory/README.md`
- Create: `docs/research/inventory/generated/.gitkeep`
- Create: `tools/__init__.py` (if missing)

- [ ] **Step 1: Create directories**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
mkdir -p docs/research/inventory/generated
touch docs/research/inventory/generated/.gitkeep
```

- [ ] **Step 2: Write the empty inventory.yaml skeleton**

`docs/research/inventory/inventory.yaml`:

```yaml
# g2408 Protocol Inventory — source of truth.
#
# Edit this file by hand. Never edit the rendered docs in
# docs/research/inventory/generated/ — they are produced by
# `python tools/inventory_gen.py`.
#
# Schema documentation: docs/research/inventory/README.md
# Spec: docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md

_sources:
  apk_md: "github.com/TA2k/ioBroker.dreame/blob/main/apk.md"
  alt_repos:
    iobroker_dreame: "github.com/TA2k/ioBroker.dreame"
    dreame_mower: "github.com/antondaubert/dreame-mower"
    dreame_vacuum: "github.com/Tasshack/dreame-vacuum"
    dreame_mova_mower: "github.com/nicolasglg/dreame-mova-mower"
    legacy: "github.com/okolbu/ha-dreame-a2-mower-legacy"
  probe_log_corpus_glob: "../probe_log_*.jsonl"
  cloud_dump_corpus_glob: "../dreame_cloud_dumps/dump_*.json"

# Sections — each is a list of rows. Empty at bootstrap; populated
# by Tasks 8 onward.
properties: []
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

- [ ] **Step 3: Write the inventory README**

`docs/research/inventory/README.md`:

````markdown
# g2408 Protocol Inventory

This directory holds the canonical, machine-readable description of every
protocol artefact the integration touches on a Dreame A2 (`g2408`) lawn
mower.

## Files

| File | Role |
|------|------|
| `inventory.yaml` | Source of truth. Edit by hand. |
| `generated/g2408-canonical.md` | Human-readable reference. Generated. |
| `generated/coverage-report.md` | Audit complement. Empty when complete. |
| `README.md` | This file. |

## Adding a row

Pick the right section (`properties`, `events`, `actions`, etc.) and
append a new entry. The generic schema:

```yaml
- id: "s2p52"                  # category-unique id; used in cross-refs
  siid: 2                       # only for properties/events/actions
  piid: 52                      # ditto
  name: "preference_update_trigger"
  category: "trigger"           # property | blob | trigger | event | multiplexed
  payload_shape: "empty_dict"

  unit:                          # only for numeric scalars; omit for bool/struct
    wire: "cm"
    display: "m"
    scale: 0.01
    format: "{:.2f}"
    notes: "optional clarifying note"

  value_catalog:                 # only for enums; omit otherwise
    0: "off"
    1: "on"

  semantic: |
    Multi-paragraph human-readable description. Lives here, not in
    g2408-protocol.md. Cite confirmation evidence.

  status:
    seen_on_wire: true
    first_seen: "2026-04-17"     # date of first probe-log appearance
    last_seen: "2026-04-30"
    decoded: confirmed           # confirmed | hypothesized | unknown
    bt_only: false
    not_on_g2408: false

  references:
    apk: "ioBroker.dreame/apk.md §parseRobotPose"
    alt_repos:
      - "alternatives/dreame-mower/dreame/types.py:725"
    integration_code: "custom_components/dreame_a2_mower/mower/property_mapping.py:80"
    protocol_doc: "docs/research/g2408-protocol.md §4.7"

  open_questions:
    - "Does this also fire on PIN-update, or only PRE?"
```

Fields that don't apply to a row's category are simply omitted.

## Status taxonomy

The generator computes a single label per row from the booleans in `status`:

| Label | Condition |
|-------|-----------|
| `WIRED` | `references.integration_code` is non-null |
| `DECODED-UNWIRED` | seen + decoded confirmed + no integration handler |
| `SEEN-UNDECODED` | seen on wire, decoded != confirmed |
| `APK-KNOWN` | not seen, documented in apk |
| `UPSTREAM-KNOWN` | not seen, only in alt repos |
| `BT-ONLY` | feature exists but cloud-invisible |
| `NOT-ON-G2408` | confirmed missing/error on g2408 firmware |

A row matching multiple conditions picks the first row in the table.

## Unit vocabulary

`unit.wire` values are validated against a closed list. To add a new wire
encoding, extend `_UNIT_VOCAB` in `tools/inventory_gen.py` in the same
commit as the row that introduces it. Current vocab:

```
cm, mm, m, decimetres, centiares, m2, m2_x100, signed_dbm,
unsigned_byte, signed_byte, minutes_from_midnight, unix_seconds,
percent, percent_x100, degrees, degrees_x256, bool, enum,
raw_bytes, string
```

## Tools

```bash
# Render canonical doc + coverage report:
python tools/inventory_gen.py

# Audit committed corpus against the inventory; non-zero exit if any
# observed slot is missing:
python tools/inventory_audit.py

# Read-only live probe (asks before each batch); produces a delta
# JSON for the reviewer to merge by hand:
python tools/inventory_probe.py --read-only
```
````

- [ ] **Step 4: Verify YAML loads**

```bash
python -c "import yaml, sys; d = yaml.safe_load(open('docs/research/inventory/inventory.yaml')); assert d['_sources']['apk_md'].startswith('github.com'); assert d['properties'] == []; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add docs/research/inventory/ tools/
git commit -m "feat(inventory): bootstrap inventory.yaml + README

Empty section lists, schema doc, generated/ placeholder. First
slot ingestion happens in Task 8 once tools land."
```

---

## Task 2: `inventory_gen.py` — schema validator (TDD)

**Files:**
- Create: `tools/inventory_gen.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_inventory_gen_validate.py`
- Create: `tests/tools/fixtures/__init__.py`
- Create: `tests/tools/fixtures/good_inventory.yaml`
- Create: `tests/tools/fixtures/bad_unit_vocab.yaml`
- Create: `tests/tools/fixtures/bad_status.yaml`

- [ ] **Step 1: Write the failing test**

`tests/tools/test_inventory_gen_validate.py`:

```python
"""Tests for inventory_gen.py's schema validator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_gen.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_accepts_good_fixture() -> None:
    result = _run(["--validate-only", str(FIXTURES / "good_inventory.yaml")])
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout.lower()


def test_validate_rejects_unknown_unit_wire() -> None:
    result = _run(["--validate-only", str(FIXTURES / "bad_unit_vocab.yaml")])
    assert result.returncode != 0
    assert "unit.wire" in result.stderr
    assert "unknown_unit_xyz" in result.stderr


def test_validate_rejects_invalid_status_decoded() -> None:
    result = _run(["--validate-only", str(FIXTURES / "bad_status.yaml")])
    assert result.returncode != 0
    assert "decoded" in result.stderr
    assert "maybe_sometimes" in result.stderr
```

- [ ] **Step 2: Write the fixture YAMLs**

`tests/tools/fixtures/good_inventory.yaml`:

```yaml
_sources:
  apk_md: "github.com/TA2k/ioBroker.dreame/blob/main/apk.md"
properties:
  - id: "s2p1"
    siid: 2
    piid: 1
    name: "status"
    category: "property"
    payload_shape: "small_int_enum"
    value_catalog:
      1: "Mowing"
      2: "Standby"
    semantic: "Mode enum."
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-04-30"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/mower/property_mapping.py:56"
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

`tests/tools/fixtures/bad_unit_vocab.yaml`: same as good, but the `s2p1` row's body replaced with:

```yaml
properties:
  - id: "s2p66_bad"
    siid: 2
    piid: 66
    name: "lawn_area"
    category: "property"
    payload_shape: "list_2int"
    unit:
      wire: "unknown_unit_xyz"
      display: "m2"
      scale: 1.0
    semantic: "Bad unit."
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-04-30"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references: {}
```

`tests/tools/fixtures/bad_status.yaml`: same as good but with `decoded: maybe_sometimes` instead of a valid enum value.

- [ ] **Step 3: Run tests — expect FAIL (tool doesn't exist yet)**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/tools/test_inventory_gen_validate.py -v
```

Expected: 3 tests fail with `FileNotFoundError` or non-zero exit / wrong output.

- [ ] **Step 4: Implement the validator**

`tools/inventory_gen.py` (initial version, validator only):

```python
#!/usr/bin/env python3
"""Inventory generator + validator.

Validates docs/research/inventory/inventory.yaml against the schema
described in docs/research/inventory/README.md, and (in a later step)
renders generated/g2408-canonical.md.

CLI:
    python tools/inventory_gen.py                   # full generate
    python tools/inventory_gen.py --validate-only   # schema check only
    python tools/inventory_gen.py PATH              # validate a different file
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "research" / "inventory" / "inventory.yaml"

_UNIT_VOCAB: frozenset[str] = frozenset(
    {
        "cm", "mm", "m", "decimetres", "centiares", "m2", "m2_x100",
        "signed_dbm", "unsigned_byte", "signed_byte",
        "minutes_from_midnight", "unix_seconds",
        "percent", "percent_x100",
        "degrees", "degrees_x256",
        "bool", "enum", "raw_bytes", "string",
    }
)

_DECODED_VALUES: frozenset[str] = frozenset({"confirmed", "hypothesized", "unknown"})

_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "_sources", "properties", "events", "actions", "opcodes",
    "cfg_keys", "cfg_individual",
    "heartbeat_bytes", "telemetry_fields", "telemetry_variants",
    "s2p51_shapes", "state_codes", "mode_enum",
    "oss_map_keys", "session_summary_fields",
    "m_path_encoding", "lidar_pcd",
)


class ValidationError(Exception):
    pass


def _validate_row(section: str, idx: int, row: dict[str, Any]) -> Iterable[str]:
    """Yield error strings for a single row."""
    if "id" not in row:
        yield f"{section}[{idx}]: missing 'id'"
        return
    rid = row["id"]
    unit = row.get("unit")
    if unit is not None:
        wire = unit.get("wire")
        if wire is None:
            yield f"{section}[{rid}].unit: missing 'wire'"
        elif wire not in _UNIT_VOCAB:
            yield (
                f"{section}[{rid}].unit.wire: '{wire}' not in vocabulary "
                f"(extend tools/inventory_gen.py:_UNIT_VOCAB if intentional)"
            )
    status = row.get("status")
    if status is not None:
        decoded = status.get("decoded")
        if decoded is not None and decoded not in _DECODED_VALUES:
            yield (
                f"{section}[{rid}].status.decoded: '{decoded}' invalid "
                f"(must be one of {sorted(_DECODED_VALUES)})"
            )


def validate(inventory: dict[str, Any]) -> list[str]:
    """Return a list of error strings; empty list = valid."""
    errors: list[str] = []
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in inventory:
            errors.append(f"top-level: missing required key '{key}'")
    for section in _REQUIRED_TOP_LEVEL_KEYS:
        if section == "_sources":
            continue
        rows = inventory.get(section)
        if rows is None:
            continue
        if not isinstance(rows, list):
            errors.append(f"{section}: expected list, got {type(rows).__name__}")
            continue
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{section}[{idx}]: expected dict, got {type(row).__name__}")
                continue
            errors.extend(_validate_row(section, idx, row))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inventory_path", nargs="?", type=Path, default=DEFAULT_INVENTORY,
        help="Path to inventory.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Run schema validation and exit; do not render docs.",
    )
    args = parser.parse_args(argv)

    try:
        inventory = yaml.safe_load(args.inventory_path.read_text())
    except FileNotFoundError:
        print(f"error: {args.inventory_path} not found", file=sys.stderr)
        return 2

    errors = validate(inventory)
    if errors:
        print("validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if args.validate_only:
        print("ok: inventory schema valid")
        return 0

    # Generation is added in Task 3.
    print("ok: schema valid (generator not yet implemented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_inventory_gen_validate.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run validator on the bootstrap inventory**

```bash
python tools/inventory_gen.py --validate-only docs/research/inventory/inventory.yaml
```

Expected: `ok: inventory schema valid`

- [ ] **Step 7: Commit**

```bash
git add tools/inventory_gen.py tests/tools/
git commit -m "feat(inventory): inventory_gen.py schema validator + tests

Validates _UNIT_VOCAB membership and the decoded-enum vocabulary.
Generator rendering is added in the next task."
```

---

## Task 3: `inventory_gen.py` — chapter renderer (TDD)

**Files:**
- Modify: `tools/inventory_gen.py` (extend with renderer)
- Create: `tests/tools/test_inventory_gen_render.py`
- Create: `tests/tools/fixtures/render_one_property.yaml`
- Create: `tests/tools/fixtures/render_one_property.expected.md`

- [ ] **Step 1: Write the failing test**

`tests/tools/test_inventory_gen_render.py`:

```python
"""Tests for inventory_gen.py's chapter renderer."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_gen.py"


def test_render_one_property() -> None:
    expected = (FIXTURES / "render_one_property.expected.md").read_text()
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                str(FIXTURES / "render_one_property.yaml"),
                "--output-dir", str(out_dir),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        canonical = (out_dir / "g2408-canonical.md").read_text()
        # Compare ignoring trailing whitespace; allow expected to be a
        # substring (other chapters render too).
        assert "## Properties" in canonical
        for line in expected.splitlines():
            if line.strip():
                assert line in canonical, f"missing line: {line!r}"


def test_render_skips_empty_chapters() -> None:
    """A section with no rows should not render an empty table."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        # Use the good fixture from Task 2; it has properties but no events.
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                str(FIXTURES / "good_inventory.yaml"),
                "--output-dir", str(out_dir),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        canonical = (out_dir / "g2408-canonical.md").read_text()
        assert "## Properties" in canonical
        # Empty Events section shows a "(none)" line, not an empty table.
        assert "## Events\n\n_(none)_" in canonical
```

- [ ] **Step 2: Write the render fixtures**

`tests/tools/fixtures/render_one_property.yaml`:

```yaml
_sources:
  apk_md: "github.com/TA2k/ioBroker.dreame/blob/main/apk.md"
properties:
  - id: "s2p66"
    siid: 2
    piid: 66
    name: "lawn_area"
    category: "property"
    payload_shape: "list_2int"
    unit:
      wire: "m2"
      display: "m2"
      scale: 1.0
      format: "{:.0f} m²"
    semantic: |
      First element is total mowable lawn area in m². Second element
      observed as 1394 / 1386 — driver unknown.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-04-30"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/mower/property_mapping.py:95"
      protocol_doc: "docs/research/g2408-protocol.md §2.1"
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

`tests/tools/fixtures/render_one_property.expected.md`:

```markdown
## Properties

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p66 | lawn_area | list_2int | WIRED | m² (×1.0) |

### s2p66 — `lawn_area`

First element is total mowable lawn area in m². Second element
observed as 1394 / 1386 — driver unknown.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:95`, `docs/research/g2408-protocol.md §2.1`
```

- [ ] **Step 3: Run test — expect FAIL**

```bash
python -m pytest tests/tools/test_inventory_gen_render.py -v
```

Expected: tests fail because `--output-dir` flag isn't recognised yet.

- [ ] **Step 4: Extend `inventory_gen.py` with the renderer**

Add at the top of `tools/inventory_gen.py` after `_DECODED_VALUES`:

```python
_BANNER = (
    "<!-- DO NOT EDIT BY HAND. Source: docs/research/inventory/inventory.yaml. "
    "Regenerate via `python tools/inventory_gen.py`. -->\n\n"
)

# Order in which sections render. Names mirror inventory.yaml top-level keys.
_RENDER_ORDER: tuple[tuple[str, str], ...] = (
    ("properties", "Properties"),
    ("events", "Events"),
    ("actions", "Actions"),
    ("opcodes", "Routed-action opcodes"),
    ("cfg_keys", "CFG keys"),
    ("cfg_individual", "cfg_individual endpoints"),
    ("heartbeat_bytes", "Heartbeat (s1p1) bytes"),
    ("telemetry_fields", "Telemetry (s1p4) fields"),
    ("telemetry_variants", "Telemetry frame variants"),
    ("s2p51_shapes", "s2p51 multiplexed-config shapes"),
    ("state_codes", "s2p2 state codes"),
    ("mode_enum", "s2p1 mode enum"),
    ("oss_map_keys", "OSS map blob keys"),
    ("session_summary_fields", "Session-summary JSON fields"),
    ("m_path_encoding", "M_PATH encoding"),
    ("lidar_pcd", "LiDAR PCD format"),
)


def _derive_status_label(row: dict[str, Any]) -> str:
    """Map status booleans to a single human label."""
    refs = row.get("references") or {}
    status = row.get("status") or {}
    if refs.get("integration_code"):
        return "WIRED"
    seen = status.get("seen_on_wire", False)
    decoded = status.get("decoded")
    if status.get("not_on_g2408"):
        return "NOT-ON-G2408"
    if status.get("bt_only"):
        return "BT-ONLY"
    if seen and decoded == "confirmed":
        return "DECODED-UNWIRED"
    if seen:
        return "SEEN-UNDECODED"
    if refs.get("apk"):
        return "APK-KNOWN"
    if refs.get("alt_repos"):
        return "UPSTREAM-KNOWN"
    return "UNCLASSIFIED"


def _render_unit(unit: dict[str, Any] | None) -> str:
    if not unit:
        return ""
    display = unit.get("display", "")
    scale = unit.get("scale")
    if scale is None:
        return display
    return f"{display} (×{scale})"


def _render_chapter(section: str, title: str, rows: list[dict[str, Any]]) -> str:
    out: list[str] = [f"## {title}\n"]
    if not rows:
        out.append("\n_(none)_\n")
        return "".join(out)
    out.append("\n| id | name | shape | status | unit |\n")
    out.append("|----|------|-------|--------|------|\n")
    for row in rows:
        rid = row.get("id", "?")
        name = row.get("name", "")
        shape = row.get("payload_shape", "")
        label = _derive_status_label(row)
        unit = _render_unit(row.get("unit"))
        out.append(f"| {rid} | {name} | {shape} | {label} | {unit} |\n")
    out.append("\n")
    for row in rows:
        rid = row.get("id", "?")
        name = row.get("name", "")
        out.append(f"### {rid} — `{name}`\n\n")
        semantic = (row.get("semantic") or "").rstrip()
        if semantic:
            out.append(semantic + "\n\n")
        oqs = row.get("open_questions") or []
        if oqs:
            out.append("**Open questions:**\n")
            for oq in oqs:
                out.append(f"- {oq}\n")
            out.append("\n")
        refs = row.get("references") or {}
        ref_pieces: list[str] = []
        if refs.get("integration_code"):
            ref_pieces.append(refs["integration_code"])
        if refs.get("protocol_doc"):
            ref_pieces.append(refs["protocol_doc"])
        if refs.get("apk"):
            ref_pieces.append(f"apk: {refs['apk']}")
        for alt in refs.get("alt_repos") or []:
            ref_pieces.append(alt)
        if ref_pieces:
            out.append("**See also:** " + ", ".join(f"`{p}`" for p in ref_pieces) + "\n\n")
    return "".join(out)


def render_canonical(inventory: dict[str, Any]) -> str:
    body: list[str] = [_BANNER, "# g2408 Protocol — Canonical Reference\n\n"]
    for section, title in _RENDER_ORDER:
        rows = inventory.get(section) or []
        body.append(_render_chapter(section, title, rows))
    return "".join(body)
```

Replace the `main` function's "generation is added in Task 3" comment block with:

```python
    # Generate canonical doc.
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = out_dir / "g2408-canonical.md"
    canonical_path.write_text(render_canonical(inventory))
    # Coverage report is written by inventory_audit.py; we leave a stub
    # so the generated/ dir always has both files even if audit hasn't run.
    coverage_path = out_dir / "coverage-report.md"
    if not coverage_path.exists():
        coverage_path.write_text(
            _BANNER + "# Coverage Report\n\n_Run `python tools/inventory_audit.py` to populate._\n"
        )
    print(f"ok: rendered {canonical_path}")
    return 0
```

And add `--output-dir` to the argparse setup, defaulting to `docs/research/inventory/generated/`:

```python
    parser.add_argument(
        "--output-dir", type=Path,
        default=REPO_ROOT / "docs" / "research" / "inventory" / "generated",
        help="Where to write generated files (default: %(default)s)",
    )
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_inventory_gen_render.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Generate against the bootstrap inventory**

```bash
python tools/inventory_gen.py
```

Expected output: `ok: rendered docs/research/inventory/generated/g2408-canonical.md`

The generated file should contain headers for every chapter, all empty (each shows `_(none)_`).

- [ ] **Step 7: Commit**

```bash
git add tools/inventory_gen.py tests/tools/
git commit -m "feat(inventory): inventory_gen.py renderer + tests

Renders chapter-style canonical doc from inventory.yaml. Empty
chapters show '_(none)_'. Status label is derived from the
status booleans + references presence."
```

---

## Task 4: `inventory_audit.py` — probe-log walker (TDD)

**Files:**
- Create: `tools/inventory_audit.py`
- Create: `tests/tools/test_inventory_audit_probe.py`
- Create: `tests/tools/fixtures/mini_probe.jsonl`

- [ ] **Step 1: Write the failing test**

`tests/tools/test_inventory_audit_probe.py`:

```python
"""Tests for inventory_audit.py's probe-log walker."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_audit.py"


def test_probe_walker_finds_unknown_slot() -> None:
    """If the inventory has no s2p99 row but the probe log carries one,
    the audit must report it."""
    result = subprocess.run(
        [
            sys.executable, str(TOOL),
            "--inventory", str(FIXTURES / "good_inventory.yaml"),
            "--probe-glob", str(FIXTURES / "mini_probe.jsonl"),
            "--cloud-dump-glob", "/dev/null",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "s2p99" in result.stdout
    assert "not in inventory" in result.stdout.lower()


def test_probe_walker_passes_when_all_slots_known() -> None:
    """If the inventory covers every slot in the corpus, exit 0."""
    result = subprocess.run(
        [
            sys.executable, str(TOOL),
            "--inventory", str(FIXTURES / "good_inventory.yaml"),
            "--probe-glob", str(FIXTURES / "mini_probe_known_only.jsonl"),
            "--cloud-dump-glob", "/dev/null",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Write the fixture probe logs**

`tests/tools/fixtures/mini_probe.jsonl`:

```jsonl
{"type":"mqtt_message","timestamp":"2026-05-05 12:00:00","parsed_data":{"method":"properties_changed","params":[{"siid":2,"piid":1,"value":1}]}}
{"type":"mqtt_message","timestamp":"2026-05-05 12:00:01","parsed_data":{"method":"properties_changed","params":[{"siid":2,"piid":99,"value":42}]}}
```

`tests/tools/fixtures/mini_probe_known_only.jsonl`:

```jsonl
{"type":"mqtt_message","timestamp":"2026-05-05 12:00:00","parsed_data":{"method":"properties_changed","params":[{"siid":2,"piid":1,"value":1}]}}
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
python -m pytest tests/tools/test_inventory_audit_probe.py -v
```

Expected: tests fail because `inventory_audit.py` does not exist.

- [ ] **Step 4: Implement the audit tool**

`tools/inventory_audit.py`:

```python
#!/usr/bin/env python3
"""Inventory audit.

Walks the probe-log corpus and the cloud-dump corpus and reports any
slot, event, CFG key, or cfg_individual endpoint that isn't represented
in inventory.yaml.

Exit code 0: every observation is accounted for.
Exit code 1: at least one observation is missing from the inventory.
Exit code 2: usage error.

Outputs:
- stdout: human-readable report
- writes docs/research/inventory/generated/coverage-report.md
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "research" / "inventory" / "inventory.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research" / "inventory" / "generated" / "coverage-report.md"

_BANNER = (
    "<!-- DO NOT EDIT BY HAND. Generated by tools/inventory_audit.py. -->\n\n"
)


def _index_inventory(inv: dict[str, Any]) -> dict[str, set[str]]:
    """Return a {section_name: set_of_ids} index for fast lookup."""
    out: dict[str, set[str]] = defaultdict(set)
    for section in (
        "properties", "events", "actions", "opcodes",
        "cfg_keys", "cfg_individual",
    ):
        for row in inv.get(section) or []:
            rid = row.get("id")
            if rid is not None:
                out[section].add(str(rid))
    return out


def _walk_probe_logs(probe_glob: str) -> dict[tuple[str, int, int], int]:
    """Return {(kind, siid, key): count}; kind = 'property' or 'event'."""
    seen: dict[tuple[str, int, int], int] = defaultdict(int)
    for path in glob.glob(probe_glob):
        if path == "/dev/null":
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parsed = rec.get("parsed_data") or {}
                method = parsed.get("method")
                params = parsed.get("params")
                if not isinstance(params, list):
                    continue
                for p in params:
                    if not isinstance(p, dict):
                        continue
                    siid = p.get("siid")
                    if method == "properties_changed" and "piid" in p:
                        seen[("property", int(siid), int(p["piid"]))] += 1
                    elif method == "event_occured" and "eiid" in p:
                        seen[("event", int(siid), int(p["eiid"]))] += 1
    return seen


def _walk_cloud_dumps(dump_glob: str) -> dict[str, set[str]]:
    """Return {'cfg_keys': {...}, 'cfg_individual': {...}, 'candidates': {...}}."""
    out: dict[str, set[str]] = {
        "cfg_keys": set(),
        "cfg_individual": set(),
        "candidates": set(),
    }
    for path in glob.glob(dump_glob):
        if path == "/dev/null":
            continue
        try:
            data = json.loads(Path(path).read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            continue
        cfg = data.get("cfg_full") or data.get("cfg") or {}
        if isinstance(cfg, dict):
            out["cfg_keys"].update(str(k) for k in cfg.keys())
        cfg_indiv = data.get("cfg_individual") or {}
        if isinstance(cfg_indiv, dict):
            out["cfg_individual"].update(str(k) for k in cfg_indiv.keys())
        cands = data.get("candidates") or {}
        if isinstance(cands, dict):
            out["candidates"].update(str(k) for k in cands.keys())
    return out


def _format_id(kind: str, siid: int, key: int) -> str:
    if kind == "property":
        return f"s{siid}p{key}"
    return f"event_s{siid}eiid{key}"


def audit(
    inventory: dict[str, Any],
    probe_glob: str,
    dump_glob: str,
) -> tuple[int, str]:
    """Run the audit and return (exit_code, markdown_report)."""
    indexed = _index_inventory(inventory)
    probe = _walk_probe_logs(probe_glob)
    dumps = _walk_cloud_dumps(dump_glob)

    missing_props: list[tuple[str, int]] = []
    missing_events: list[tuple[str, int]] = []
    for (kind, siid, key), count in sorted(probe.items()):
        rid = _format_id(kind, siid, key)
        target = "properties" if kind == "property" else "events"
        if rid not in indexed[target]:
            (missing_props if kind == "property" else missing_events).append((rid, count))

    missing_cfg_keys = sorted(dumps["cfg_keys"] - indexed["cfg_keys"])
    missing_cfg_indiv = sorted(dumps["cfg_individual"] - indexed["cfg_individual"])
    missing_cands = sorted(dumps["candidates"] - indexed["cfg_individual"])

    report: list[str] = [_BANNER, "# Coverage Report\n\n"]
    any_missing = False

    def section(title: str, items: list[Any]) -> None:
        nonlocal any_missing
        report.append(f"## {title}\n\n")
        if not items:
            report.append("_(empty — all accounted for)_\n\n")
            return
        any_missing = True
        for it in items:
            report.append(f"- {it}\n")
        report.append("\n")

    section(
        "Probe-log properties not in inventory",
        [f"`{rid}` (×{count})" for rid, count in missing_props],
    )
    section(
        "Probe-log events not in inventory",
        [f"`{rid}` (×{count})" for rid, count in missing_events],
    )
    section("Cloud-dump CFG keys not in inventory", [f"`{k}`" for k in missing_cfg_keys])
    section("Cloud-dump cfg_individual endpoints not in inventory", [f"`{k}`" for k in missing_cfg_indiv])
    section(
        "Cloud-dump 'candidates' probes not in cfg_individual inventory",
        [f"`{k}`" for k in missing_cands],
    )

    return (1 if any_missing else 0, "".join(report))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--probe-glob", type=str,
        default=str(REPO_ROOT.parent / "probe_log_*.jsonl"),
    )
    parser.add_argument(
        "--cloud-dump-glob", type=str,
        default=str(REPO_ROOT.parent / "dreame_cloud_dumps" / "dump_*.json"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        inventory = yaml.safe_load(args.inventory.read_text()) or {}
    except FileNotFoundError:
        print(f"error: {args.inventory} not found", file=sys.stderr)
        return 2

    exit_code, report = audit(inventory, args.probe_glob, args.cloud_dump_glob)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_inventory_audit_probe.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run audit against the live corpus**

```bash
python tools/inventory_audit.py
```

Expected: exit 1, report lists every observed slot in the probe corpus and every CFG key in the cloud dumps as "not in inventory" (because we haven't populated rows yet). This is the seed for Task 8.

- [ ] **Step 7: Commit**

```bash
git add tools/inventory_audit.py tests/tools/
git commit -m "feat(inventory): inventory_audit.py probe + cloud-dump walker

Walks probe_log_*.jsonl + dreame_cloud_dumps/dump_*.json and
reports every (siid,piid), (siid,eiid), CFG key, and
cfg_individual endpoint not present in the inventory. Exit 1
when any observation is missing; exit 0 when complete."
```

---

## Task 5: `inventory_probe.py` — read-only probe with safety gate (TDD)

**Files:**
- Create: `tools/inventory_probe.py`
- Create: `tests/tools/test_inventory_probe.py`

- [ ] **Step 1: Write the failing test**

`tests/tools/test_inventory_probe.py`:

```python
"""Tests for inventory_probe.py — primarily the safety-gate behavior."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).parents[2] / "tools" / "inventory_probe.py"


def test_probe_refuses_without_yes() -> None:
    """Refuses to run when stdin says 'n'."""
    result = subprocess.run(
        [sys.executable, str(TOOL), "--dry-run"],
        input="n\n",
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0  # Graceful no-op, not an error.
    assert "aborted" in result.stdout.lower()


def test_probe_dry_run_lists_planned_batches() -> None:
    """In dry-run with 'y', lists the planned read-only batches."""
    result = subprocess.run(
        [sys.executable, str(TOOL), "--dry-run"],
        input="y\n",
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Each planned batch is named in the spec; check for a few.
    for batch in ("getCFG", "cfg_individual sweep", "get_properties for apk-known"):
        assert batch in result.stdout
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/tools/test_inventory_probe.py -v
```

Expected: tests fail because the tool doesn't exist.

- [ ] **Step 3: Implement the probe skeleton**

`tools/inventory_probe.py`:

```python
#!/usr/bin/env python3
"""Read-only Dreame-cloud probe for inventory verification.

Per spec §4.7: refuses to write anything; asks before each batch;
emits a delta JSON the reviewer merges into inventory.yaml by hand.

CLI:
    python tools/inventory_probe.py --dry-run     # plan-only, no network
    python tools/inventory_probe.py               # actually probe (asks first)

Credentials: read in situ from ../server-credentials.txt and
../ha-credentials.txt. Never copied to disk.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DELTA_OUT = REPO_ROOT / "tools" / "inventory_probe_delta.json"


@dataclass
class Batch:
    name: str
    description: str
    estimated_calls: int
    risk: str = "read-only"


_BATCHES: tuple[Batch, ...] = (
    Batch(
        name="getCFG",
        description="Re-read all-keys CFG; diff vs latest cloud dump",
        estimated_calls=1,
    ),
    Batch(
        name="cfg_individual sweep",
        description=(
            "Probe each cfg_individual target (DEV, DOCK, MIHIS, NET, LOCN, MAPL, "
            "PIN, PREI, RPET, IOT) plus apk-named candidates not yet tried"
        ),
        estimated_calls=20,
    ),
    Batch(
        name="get_properties for apk-known unseen piids",
        description=(
            "One get_properties call per apk-documented (siid,piid) absent "
            "from the probe corpus. Most return 80001 on g2408."
        ),
        estimated_calls=30,
    ),
    Batch(
        name="candidates list re-test",
        description=(
            "Walk dreame_cloud_dumps/*.json 'candidates' list and re-probe "
            "any target that returned non-error in the previous dump."
        ),
        estimated_calls=15,
    ),
)


def _ask_yes_no(prompt: str) -> bool:
    """Ask a single y/n on stdin. Defaults to 'no' on empty input."""
    print(prompt, end=" ", flush=True)
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    return line.strip().lower().startswith("y")


def _print_plan() -> None:
    print("Planned probe batches:")
    for i, b in enumerate(_BATCHES, 1):
        print(f"  {i}. {b.name}")
        print(f"     {b.description}")
        print(f"     ~{b.estimated_calls} {b.risk} calls")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="List planned batches; no network calls.")
    parser.add_argument("--delta-out", type=Path, default=DEFAULT_DELTA_OUT,
                        help="Where to write the delta JSON.")
    args = parser.parse_args(argv)

    _print_plan()
    print()
    print(
        "WARNING: probes run against the live mower. "
        "If a mowing run is in progress some configs are locked and reads may "
        "yield misleading conclusions. Continue? (y/N):",
    )
    if not _ask_yes_no(""):
        print("aborted by user")
        return 0

    if args.dry_run:
        print("dry-run: planned batches above; no network calls.")
        return 0

    # Real probe execution wiring is added in Tasks 19-20 once we know
    # which batches actually need to run for inventory completeness.
    print(
        "error: live-probe execution not yet implemented; run with --dry-run "
        "or use the dedicated probe scripts in Tasks 19-20.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_inventory_probe.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Verify dry-run interactively against the real harness**

```bash
echo "y" | python tools/inventory_probe.py --dry-run
```

Expected: prints the four planned batches, exits 0.

- [ ] **Step 6: Commit**

```bash
git add tools/inventory_probe.py tests/tools/
git commit -m "feat(inventory): inventory_probe.py skeleton with safety gate

Lists the four planned read-only probe batches (getCFG,
cfg_individual sweep, get_properties for apk-known unseen
piids, candidates re-test). Refuses to proceed without explicit
y/N confirmation. Real-probe wiring lands in Tasks 19-20."
```

---

## Task 6: Populate `properties` and `events` sections from the probe corpus

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

This is a hand-data-entry task. Use `inventory_audit.py` to identify what's missing, then add rows. Iterate.

- [ ] **Step 1: Run audit to enumerate missing slots**

```bash
python tools/inventory_audit.py 2>&1 | tee /tmp/audit-task6.txt
```

The output's "Probe-log properties not in inventory" and "Probe-log events not in inventory" sections are your worklist. From the corpus there are 30 unique property slots and one event combo:

```
s1p1, s1p4, s1p50, s1p51, s1p52, s1p53,
s2p1, s2p2, s2p50, s2p51, s2p52, s2p53, s2p54, s2p55, s2p56,
s2p62, s2p65, s2p66,
s3p1, s3p2,
s5p104, s5p105, s5p106, s5p107, s5p108,
s6p1, s6p2, s6p3, s6p117,
s99p20

event_s4eiid1
```

- [ ] **Step 2: Add a row for every property slot**

Open `docs/research/inventory/inventory.yaml` and append rows under `properties:` using the schema from the README. Use this s1p4 row as the canonical example for all 30 — adjust `id`, `siid`, `piid`, `name`, `payload_shape`, `unit` (omit for non-numeric), `value_catalog` (omit for non-enum), and pull the `semantic` block verbatim from the corresponding section of `docs/research/g2408-protocol.md` (don't paraphrase; copy the canonical prose so the journal/canonical separation lands cleanly in axis 2):

```yaml
properties:
  - id: "s1p4"
    siid: 1
    piid: 4
    name: "mowing_telemetry"
    category: "blob"
    payload_shape: "33-byte / 8-byte / 10-byte variants"
    semantic: |
      Position, phase, area, distance during an active mowing session.
      Three frame variants (33/8/10 bytes) are documented in
      `g2408-protocol.md` §3.1–3.3. Per-byte field decode lives in
      `telemetry_fields:` and `telemetry_variants:` sections of this
      inventory.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §parseRobotPose, §parseRobotTrace, §parseRobotTask"
      alt_repos:
        - "alternatives/dreame-mower/dreame/types.py:720"
      integration_code: "custom_components/dreame_a2_mower/protocol/telemetry.py:1"
      protocol_doc: "docs/research/g2408-protocol.md §3.1"
    open_questions:
      - "Bytes [10-21] motion-vector decode — apk says trace deltas but Δ2 saturation pattern doesn't fit cleanly on g2408."
      - "Phase byte [8] semantics across different mowing modes."
```

For numeric-payload slots that *do* warrant `unit:`, include it. Examples (do NOT skip):

- `s2p66` (lawn area, list[m², ?]):
  ```yaml
  unit:
    wire: "m2"
    display: "m2"
    scale: 1.0
    format: "{:.0f} m²"
    notes: "First element only. Second element undecoded."
  ```
- `s3p1` (battery percent):
  ```yaml
  unit: { wire: "percent", display: "%", scale: 1.0, format: "{:d}%" }
  ```

For the `event_occured siid=4 eiid=1` end-of-session event, add a row under `events:`:

```yaml
events:
  - id: "event_s4eiid1"
    siid: 4
    eiid: 1
    name: "session_complete"
    category: "event"
    payload_shape: "list of {piid, value} args"
    semantic: |
      Fires once per completed (or user-aborted) mowing session.
      piid 9 carries the session-summary OSS object key. See
      g2408-protocol.md §7.4 for the full piid catalog.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/coordinator.py:_handle_event_occured"
      protocol_doc: "docs/research/g2408-protocol.md §7.4"
```

- [ ] **Step 3: Re-run validator**

```bash
python tools/inventory_gen.py --validate-only
```

Expected: `ok: inventory schema valid`

- [ ] **Step 4: Re-run audit**

```bash
python tools/inventory_audit.py
```

Expected: "Probe-log properties not in inventory" and "Probe-log events not in inventory" sections both empty.

- [ ] **Step 5: Re-render canonical doc and eyeball it**

```bash
python tools/inventory_gen.py
git diff docs/research/inventory/generated/g2408-canonical.md | head -60
```

Confirm the Properties chapter now lists 30 rows with appropriate status labels.

- [ ] **Step 6: Commit**

```bash
git add docs/research/inventory/
git commit -m "feat(inventory): seed properties + events from probe corpus

30 property rows + the session-summary event_occured row.
Semantic prose lifted verbatim from g2408-protocol.md so the
axis-2 doc restructure has a single source. Audit's probe-log
sections are now empty."
```

---

## Task 7: Populate `cfg_keys` and `cfg_individual` from cloud dumps

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

- [ ] **Step 1: Re-run audit**

```bash
python tools/inventory_audit.py 2>&1 | tee /tmp/audit-task7.txt
```

Worklist: every CFG key in the dumps (24 keys) and every cfg_individual endpoint (19 listed: AIOBS, CFG, CMS, DEV, DOCK, IOT, LOCN, MAPD, MAPI, MAPL, MIHIS, MISTA, MITRC, NET, OBS, PIN, PRE, PREI, RPET).

- [ ] **Step 2: Add a row for every CFG key**

In `inventory.yaml` append under `cfg_keys:` using this `WRP` row as the model. Pull the `semantic` and `value_catalog` from `g2408-protocol.md` §6.2:

```yaml
cfg_keys:
  - id: "WRP"
    name: "rain_protection"
    category: "cfg"
    payload_shape: "list[int(2)] [enabled, resume_hours]"
    semantic: |
      Rain Protection. Confirmed 2026-04-24 via live toggle. enabled
      ∈ {0,1}; resume_hours ∈ {0..24} where 0 = "Don't Mow After
      Rain" (no auto-resume). Mirror of the s2p51 RAIN_PROTECTION
      decoder.
    value_catalog:
      "[0, *]": "off"
      "[1, 0]": "enabled, no auto-resume"
      "[1, n]": "enabled, resume n hours after rain ends"
    status:
      seen_on_wire: true
      first_seen: "2026-04-24"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §setX WRP"
      integration_code: "custom_components/dreame_a2_mower/protocol/cfg_action.py"
      protocol_doc: "docs/research/g2408-protocol.md §6.2 WRP"
```

Repeat for the other 23 keys: AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG, LIT, LOW, MSG_ALERT, PATH, PRE, PROT, REC, STUN, TIME, VER, VOICE, VOL, WRF.

- [ ] **Step 3: Add a row for every `cfg_individual` endpoint**

Under `cfg_individual:`, one row per endpoint. Pull `semantic` from `g2408-protocol.md` §6.3. Use this `DOCK` row as the model:

```yaml
cfg_individual:
  - id: "DOCK"
    name: "dock_state_and_position"
    category: "cfg_individual"
    payload_shape: |
      {dock: {connect_status, in_region, x, y, yaw, near_x, near_y, near_yaw, path_connect}}
    semantic: |
      Dock state + map-frame position. Wired in v1.0.0a78.
      connect_status:1 → mower currently in dock (authoritative).
      in_region flips depending on whether the dock sits inside the
      mowable polygon. yaw matches compass bearing for the dock's
      X-axis. near_*/path_connect semantics still TBD.
    status:
      seen_on_wire: false
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §getX DOCK"
      integration_code: "custom_components/dreame_a2_mower/cloud_client.py"
      protocol_doc: "docs/research/g2408-protocol.md §6.3 DOCK"
    open_questions:
      - "near_x/near_y/near_yaw — approach point for path-to-dock?"
      - "yaw unit — degrees fits 'yaw:112' but near_yaw=1912 doesn't."
```

For endpoints documented as not-supported on g2408 (AIOBS, MAPD, MAPI, MISTA, MITRC, OBS, PRE), set `status.not_on_g2408: true` and the derived label becomes `NOT-ON-G2408` automatically.

For the unwired ones (MAPL, PIN, PREI, RPET, IOT), set `status.decoded: hypothesized` or `unknown` with the relevant prose from §6.3 and an `open_questions` block listing what we'd need to confirm.

- [ ] **Step 4: Re-run validator and audit**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py
```

Expected: validator ok; audit's CFG-keys + cfg_individual sections empty (the `candidates` list is still populated — that's Task 14 territory).

- [ ] **Step 5: Commit**

```bash
git add docs/research/inventory/inventory.yaml
git commit -m "feat(inventory): seed cfg_keys + cfg_individual

24 CFG keys + 19 cfg_individual endpoints. Mark MAP*/MISTA/
MITRC/OBS/PRE/AIOBS as not_on_g2408 per §6.3."
```

---

## Task 8: Populate `actions` and `opcodes` (MIoT actions + routed-action `o` codes)

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

The action surface lives in three places: the `(siid, aiid)` direct calls (mostly 80001 on g2408), the routed-action `m+t+o` envelope, and the `m='s'` / `m='g'` setters/getters. The first two get rows here; the setters/getters are already covered by `cfg_keys` and `cfg_individual`.

- [ ] **Step 1: Add `actions` rows from `mower/actions.py`**

For every entry in `ACTION_TABLE` in `custom_components/dreame_a2_mower/mower/actions.py`, add an `actions` row:

```yaml
actions:
  - id: "s5a1"
    siid: 5
    aiid: 1
    name: "start_mowing"
    category: "action"
    semantic: |
      Direct MIoT action that starts a mowing session. Returns 80001
      on g2408 in practice; the integration retries via routed-action
      o:100 (see opcodes section).
    status:
      seen_on_wire: false  # 80001 means we don't see a successful echo
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §siid:5"
      alt_repos:
        - "alternatives/dreame-mower/dreame/types.py:start_mowing"
      integration_code: "custom_components/dreame_a2_mower/mower/actions.py:152"
```

Apk-documented but not in our integration: `RESET_BLADES (s9a1)`, `RESET_SIDE_BRUSH (s10a1)`, `RESET_FILTER (s11a1)`, etc. — alt-repo subagent reports flagged these. Add them with `references.integration_code: null` and `decoded: hypothesized` (we know what they're called but haven't tested).

- [ ] **Step 2: Add `opcodes` rows for routed-action `o` codes**

For each opcode in the apk-cross-reference doc + `g2408-protocol.md` §4.6 catalog, one row. Use `o:101` as the model:

```yaml
opcodes:
  - id: "o101"
    op: 101
    name: "edge_mower"
    category: "opcode"
    payload_shape: "{m:'a', p:0, o:101, d:{edge:[[map_id, contour_id], ...]}}"
    semantic: |
      Edge-only mowing. Empty contour list is interpreted as "every
      contour including merged sub-zone seams" by firmware — confirmed
      to drain the firmware budget on lawns with tight maneuvering
      spots near such seams (2026-05-05). Always pass an explicit
      list of [map_id, contour_id] pairs from MAP.*.contours.value.
    status:
      seen_on_wire: true
      first_seen: "2026-04-26"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §m=a opcodes"
      alt_repos:
        - "alternatives/dreame-mower/dreame/device.py:1745"
      integration_code: "custom_components/dreame_a2_mower/mower/actions.py:_edge_mow_payload"
      protocol_doc: "docs/research/g2408-protocol.md §4.6"
    open_questions:
      - "Move/drag of a saved zone (different opcode pattern; not yet captured)"
```

Repeat for `0`, `2-7`, `8`, `9`, `10`, `11`, `12`, `100`, `101`, `102`, `103`, `104`, `105`, `107`, `108`, `109`, `110`, `200`, `201`, `204`, `205`, `206`, `218`, `234`, `400`, `401`, `503`. Mark untested ones `decoded: hypothesized`.

- [ ] **Step 3: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py
python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): seed actions + routed-action opcodes

Every (siid,aiid) the integration uses + every apk-documented
opcode. Untested opcodes flagged decoded: hypothesized."
```

---

## Task 9: Populate `heartbeat_bytes` (s1p1 byte-by-byte)

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

`g2408-protocol.md` §3.4 has the canonical byte-level decode. Every documented byte / bit becomes one row. Use this entry for byte[3] bit 7 as the model:

```yaml
heartbeat_bytes:
  - id: "s1p1_b3_bit7"
    byte: 3
    bit: 7
    name: "lift_lockout_pin_required"
    category: "heartbeat_bit"
    payload_shape: "single bit"
    unit:
      wire: "bool"
      display: "bool"
      scale: 1.0
    semantic: |
      Lift lockout / PIN required (the app calls this "Emergency stop
      is activated"). Set on lift OR top-cover-open; cleared ONLY by
      typing the PIN on the device. Re-confirmed 2026-05-04 across a
      5-test controlled series.
    status:
      seen_on_wire: true
      first_seen: "2026-04-30"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/protocol/heartbeat.py"
      protocol_doc: "docs/research/g2408-protocol.md §3.4"
```

- [ ] **Step 1: Walk §3.4 of `g2408-protocol.md` and extract every documented byte/bit**

Documented today: byte[1] bits 0-1, byte[2] bit 1, byte[3] bit 7, byte[4] (full byte), byte[6] bit 3, byte[7] (full byte), byte[9] (full byte), byte[10] bits 1+7, bytes [11-12] (counter), byte[14], byte[17] (RSSI). One row per byte or bit-mask.

For byte[17] use:

```yaml
  - id: "s1p1_b17"
    byte: 17
    name: "wifi_rssi_dbm"
    category: "heartbeat_byte"
    payload_shape: "signed_byte"
    unit:
      wire: "signed_dbm"
      display: "dBm"
      scale: 1.0
      format: "{:d} dBm"
      notes: "byte if <128 else byte-256"
    ...
```

- [ ] **Step 2: Add an "undocumented bytes" row per byte still without semantics**

For bytes 0, 5, 8, 13, 15, 16, 18, 19 (the heartbeat is 20 bytes; document gaps explicitly):

```yaml
  - id: "s1p1_b13"
    byte: 13
    name: "undocumented"
    category: "heartbeat_byte"
    payload_shape: "byte"
    semantic: "Observed but not characterised. Captured value range pending probe-log walk."
    status:
      seen_on_wire: true
      decoded: unknown
      bt_only: false
      not_on_g2408: false
    references:
      protocol_doc: "docs/research/g2408-protocol.md §3.4"
    open_questions:
      - "Determine value range and stationarity across mowing/idle/charging."
```

- [ ] **Step 3: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): heartbeat byte-by-byte rows for s1p1

20 rows covering documented bits + explicit undocumented bytes
so contributors have a place to file findings."
```

---

## Task 10: Populate `telemetry_fields` and `telemetry_variants`

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

`g2408-protocol.md` §3.1, §3.2, §3.3 have the per-byte decode for the 33-byte / 8-byte / 10-byte s1p4 frames. Each field is a row.

- [ ] **Step 1: Add 33-byte frame fields (§3.1)**

Use the `x_mm` field as the model. Per the apk-corrected decoder (alpha.98), bytes [1-5] use a 20-bit-signed packed decode:

```yaml
telemetry_fields:
  - id: "s1p4_33b_x_mm"
    variant: "33-byte"
    field_name: "x_mm"
    bytes: "[1-5] (packed)"
    payload_shape: "20-bit signed; x = (b[2]<<28 | b[1]<<20 | b[0]<<12) >> 12"
    unit:
      wire: "mm"
      display: "m"
      scale: 0.001
      format: "{:.2f} m"
      notes: |
        Wire reports cm × 10 = mm in the dock-relative frame.
        Display format aligns with user-visible lawn distances.
    semantic: |
      X position in the dock-relative coordinate frame (mower-local mm).
      Positive X points toward the house in the user's setup. See
      §3.1 for full coordinate-frame semantics.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §parseRobotPose"
      integration_code: "custom_components/dreame_a2_mower/protocol/telemetry.py"
      protocol_doc: "docs/research/g2408-protocol.md §3.1"
```

Repeat for: `y_mm`, `phase_raw` (byte 8), `start_index` (bytes 7-9 uint24, distinct from frame's outer position bytes — note the apk overlay nuance), `delta_1/2/3` (bytes 10-21 with Δ2 saturation caveat as `open_questions`), `flag_22`, `flag_23`, `distance_dm` (bytes 24-25 uint16), `total_area_centiares` (bytes 26-28 uint24 per apk; integration currently reads uint16 + static byte — see open question), `area_mowed_centiares` (bytes 29-31 uint24 with same caveat).

For `distance_dm`:

```yaml
  - id: "s1p4_33b_distance_dm"
    variant: "33-byte"
    field_name: "distance_decimetres"
    bytes: "[24-25]"
    payload_shape: "uint16_le"
    unit:
      wire: "decimetres"
      display: "m"
      scale: 0.1
      format: "{:.1f} m"
    ...
```

For `total_area_centiares`:

```yaml
  - id: "s1p4_33b_total_area_centiares"
    variant: "33-byte"
    field_name: "total_area_m2"
    bytes: "[26-27] (currently); apk says uint24 [26-28]"
    payload_shape: "uint16_le; counter / 100 → m²"
    unit:
      wire: "m2_x100"   # centiares = m² × 100
      display: "m²"
      scale: 0.01
      format: "{:.2f} m²"
      notes: |
        Wire stores 100× m² to keep two decimals in a uint16. Lawn
        sizes ≤ 655 m² fit; larger lawns need the apk's uint24 [26-28]
        decode — see open question.
    semantic: |
      Total mowable lawn area for the active session, including area
      under exclusion zones (user-confirmed 2026-04-25). Resets each
      session.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §parseRobotTask"
      integration_code: "custom_components/dreame_a2_mower/protocol/telemetry.py"
      protocol_doc: "docs/research/g2408-protocol.md §3.1"
    open_questions:
      - "Switch to apk's uint24 decode for lawns > 655 m². Currently uint16+static."
```

- [ ] **Step 2: Add 8-byte and 10-byte variant fields (§3.2, §3.3)**

Same shape: one row per documented field in each variant. Note that 8-byte byte[6] is the heading byte:

```yaml
  - id: "s1p4_8b_heading_byte"
    variant: "8-byte"
    field_name: "heading_deg"
    bytes: "[6]"
    payload_shape: "byte"
    unit:
      wire: "degrees_x256"   # byte / 255 * 360 → degrees
      display: "degrees"
      scale: 1.4117647        # 360 / 255
      format: "{:.0f}°"
    ...
```

- [ ] **Step 3: Add `telemetry_variants` rows for the frame-length catalog**

```yaml
telemetry_variants:
  - id: "s1p4_33b"
    length: 33
    name: "mowing_telemetry_full"
    seen_on_g2408: true
    semantic: |
      Active-mowing-session telemetry. Used throughout a TASK including
      auto-recharge return legs.
    references:
      protocol_doc: "docs/research/g2408-protocol.md §3.1"
  - id: "s1p4_8b"
    length: 8
    name: "beacon"
    seen_on_g2408: true
    semantic: "Idle/docked, leg-start preamble, BUILDING, post-FTRTS dock-nav."
    references:
      protocol_doc: "docs/research/g2408-protocol.md §3.2"
  - id: "s1p4_10b"
    length: 10
    name: "building_save_marker"
    seen_on_g2408: true
    references:
      protocol_doc: "docs/research/g2408-protocol.md §3.3"
  - id: "s1p4_7b"
    length: 7
    name: "unknown_g2568a_variant"
    seen_on_g2408: false
    semantic: "Documented in apk for g2568a. Not seen on g2408."
    references:
      apk: "ioBroker.dreame/apk.md §s1p4 lengths"
  - id: "s1p4_13b"
    length: 13
    seen_on_g2408: false
    references: { apk: "ioBroker.dreame/apk.md §s1p4 lengths" }
  - id: "s1p4_22b"
    length: 22
    seen_on_g2408: false
    references: { apk: "ioBroker.dreame/apk.md §s1p4 lengths" }
  - id: "s1p4_44b"
    length: 44
    seen_on_g2408: false
    references: { apk: "ioBroker.dreame/apk.md §s1p4 lengths" }
```

- [ ] **Step 4: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): telemetry field + frame-variant rows

s1p4 33/8/10-byte field decode with apk-cross-checked unit
blocks. Frame-variant catalog includes 7/13/22/44 lengths
documented in apk but not seen on g2408."
```

---

## Task 11: Populate `s2p51_shapes` (multiplexed-config payloads)

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

`g2408-protocol.md` §6 has the canonical shape table (~17 settings). One row per shape.

- [ ] **Step 1: Add a row for every documented payload shape**

Use this `do_not_disturb` row as the model:

```yaml
s2p51_shapes:
  - id: "s2p51_dnd"
    setting_name: "do_not_disturb"
    cfg_key: "DND"
    category: "multiplexed"
    payload_shape: "{end: int, start: int, value: 0|1}"
    unit:
      wire: "minutes_from_midnight"
      display: "HH:MM local"
      scale: 1.0
      notes: "start/end in minutes from midnight; tz from CFG.TIME"
    value_catalog:
      0: "DND off"
      1: "DND active in window"
    semantic: |
      Wired in s2p51 push when user toggles DND or edits the window.
      Shape is unambiguous on the wire (named keys, no list collision).
    status:
      seen_on_wire: true
      first_seen: "2026-04-24"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/protocol/config_s2p51.py"
      protocol_doc: "docs/research/g2408-protocol.md §6"
```

Cover: do_not_disturb, low_speed_nighttime, navigation_path, charging_config, auto_recharge_standby, led_period, anti_theft, child_lock, rain_protection, frost_protection, ai_obstacle_photos, human_presence_alert, consumables_runtime, notification_preferences (4-bool), voice_prompt_modes (4-bool), language, timestamp_event.

For the two ambiguous-on-wire shapes (`{value: 0|1}` and `{value: [b,b,b,b]}`), document the disambiguation logic (sensor.cfg_keys_raw._last_diff) in the row's `semantic` block:

```yaml
  - id: "s2p51_ambiguous_toggle"
    setting_name: "ambiguous_single_toggle"
    cfg_key: "(disambiguated via getCFG diff: CLS / FDP / STUN / AOP / PROT)"
    payload_shape: "{value: 0|1}"
    semantic: |
      Wire-level ambiguous shape — five distinct CFG keys ride this
      same payload. Disambiguation requires a getCFG diff via
      sensor.cfg_keys_raw._last_diff.
    ...
```

- [ ] **Step 2: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): s2p51 multiplexed-config shape rows"
```

---

## Task 12: Populate `state_codes` and `mode_enum` value catalogs

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

- [ ] **Step 1: Add `state_codes` rows from `g2408-protocol.md` §4.1 + §8.3**

One row per known s2p2 code. Use code 48 as the model:

```yaml
state_codes:
  - id: "s2p2_48"
    code: 48
    name: "MOWING_COMPLETE"
    category: "state_code"
    semantic: |
      Mowing run finished cleanly. Reused for user-cancel ("End"
      from app) — distinguish via s2p50 op-code 3 vs natural
      completion.
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      last_seen: "2026-05-05"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/mower/error_codes.py"
      protocol_doc: "docs/research/g2408-protocol.md §4.1"
```

Repeat for: 27, 31, 33, 37, 38, 39, 40, 41, 43, 44, 45, 46, 47, 48, 49, 50, 51, 53, 54, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 70, 71, 73, 75, 78, 117 (apk-known + observed).

- [ ] **Step 2: Add `mode_enum` rows for s2p1**

```yaml
mode_enum:
  - id: "s2p1_1"
    value: 1
    name: "MOWING"
    semantic: "Active mowing-related task (mowing, head-to-MP, manual mode all use this)."
    status: { seen_on_wire: true, first_seen: "2026-04-17", last_seen: "2026-05-05", decoded: confirmed, bt_only: false, not_on_g2408: false }
    references: { protocol_doc: "docs/research/g2408-protocol.md §4.2" }
```

Repeat for: 1, 2, 5, 6, 11, 13, 14, 16.

- [ ] **Step 3: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): state_codes + mode_enum value catalogs"
```

---

## Task 13: Populate `oss_map_keys`, `session_summary_fields`, `m_path_encoding`, `lidar_pcd`

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

These are the outer-ring (cloud-side) payloads. Lift schemas verbatim from `g2408-protocol.md` §7.6 (session summary) and §7.8 (MAP top-level keys), the cross-reference doc (M_PATH), and the existing LiDAR PCD format docs.

- [ ] **Step 1: Add `oss_map_keys` rows**

One row per top-level MAP.* key. Use `forbiddenAreas` as the model:

```yaml
oss_map_keys:
  - id: "map_forbiddenAreas"
    key: "forbiddenAreas"
    name: "exclusion_zones"
    category: "map_blob_key"
    payload_shape: "{dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}], angle}]]}"
    unit:
      wire: "mm"
      display: "m"
      scale: 0.001
      format: "{:.2f} m"
      notes: "Path coordinates in cloud frame mm; multiply by 0.001 for m."
    semantic: |
      Classic exclusion / no-go zones (red in the Dreame app).
      shapeType=2 = rotated rectangle (path is unrotated corners +
      angle in degrees).
    status:
      seen_on_wire: false
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      apk: "ioBroker.dreame/apk.md §MAP keys"
      integration_code: "custom_components/dreame_a2_mower/map_decoder.py"
      protocol_doc: "docs/research/g2408-protocol.md §7.8"
```

Repeat for: notObsAreas, spotAreas, contours, cleanPoints, cruisePoints, cut, obstacles, paths, mowingAreas, boundary, mapIndex, name, totalArea, hasBack, merged, md5sum.

- [ ] **Step 2: Add `session_summary_fields` rows**

One row per top-level key in the session-summary JSON (§7.6). Plus per-`map[]` element keys (track, obstacles, boundary, etime, id, name, time, type) and per-`trajectory[]` element keys.

For `map[].track`:

```yaml
session_summary_fields:
  - id: "summary_map_track"
    key_path: "map[].track"
    name: "mow_path"
    category: "session_summary"
    payload_shape: "[[x, y] | [2147483647, 2147483647], ...]"
    unit:
      wire: "cm"
      display: "m"
      scale: 0.01
      notes: "[2147483647, 2147483647] = segment break sentinel"
    semantic: "Mow path. Max-int sentinel marks segment breaks."
    status:
      seen_on_wire: true
      first_seen: "2026-04-17"
      decoded: confirmed
      bt_only: false
      not_on_g2408: false
    references:
      integration_code: "custom_components/dreame_a2_mower/protocol/session_summary.py"
      protocol_doc: "docs/research/g2408-protocol.md §7.6"
```

- [ ] **Step 3: Add `m_path_encoding` rows**

The cross-reference doc describes the `M_PATH.0..N + M_PATH.info` chunked blob with the `[32767, -32768]` segment-break sentinel and the ×10 coordinate scaling. Add three rows: chunked-reassembly rule, segment-break sentinel, coordinate-scale rule.

```yaml
m_path_encoding:
  - id: "m_path_chunked"
    name: "chunked_assembly"
    payload_shape: "MAP.0 + MAP.1 + ... + MAP.info"
    semantic: |
      The M_PATH live trail is chunked across multiple userdata keys
      with M_PATH.info supplying the split position. Reassemble by
      concatenating M_PATH.0..N in order before parsing the points
      array.
    status: { seen_on_wire: false, decoded: confirmed, bt_only: false, not_on_g2408: false }
    references:
      apk: "ioBroker.dreame/apk.md §M_PATH"
      alt_repos:
        - "alternatives/dreame-mower/dreame/map_data_parser.py:256-284"
      protocol_doc: "docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH"
```

- [ ] **Step 4: Add `lidar_pcd` rows**

The existing `protocol/pcd.py` defines header + payload shape. Lift those into one row per field.

- [ ] **Step 5: Validate, audit, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): outer-ring rows (OSS map, session-summary, M_PATH, LiDAR PCD)"
```

---

## Task 14: Cross-walk `apk.md` for missing rows

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

After Tasks 6-13 the inventory captures everything we've *observed*. Now read `ioBroker.dreame/apk.md` end-to-end and add rows for apk-documented slots we haven't covered.

- [ ] **Step 1: Read apk.md systematically**

```bash
wc -l /data/claude/homeassistant/ioBroker.dreame/apk.md
```

Walk the file. For every documented `(siid, piid)`, AIID, opcode, CFG key, or settings shape, check whether the inventory has a row. If not, add one with `status.seen_on_wire: false` and `references.apk` populated. Sample the apk shows we are likely missing:

- `s1p2 firmware_install_state` — already in `g2408-protocol.md` but verify the row exists with proper `value_catalog`.
- `s1p3 firmware_download_progress` — same.
- `s2p57 robot_shutdown_5s` — apk-known, never seen; add `APK-KNOWN` row.
- `s2p58 self_check_result` — same.
- AIIDs s9a1 / s10a1 / s11a1 (consumable resets) — apk says they exist; we never tested.
- Apk-listed CFG keys not in our 24-key g2408 dump → these are confirmed `NOT-ON-G2408`.

Add open_questions where uncertainty remains.

- [ ] **Step 2: Run audit; expect zero unaccounted apk-doc'd entries**

If the audit tool's "Apk-documented entries not in inventory" section is non-empty, iterate. (This audit-section is a future axis-3 enhancement; for axis 1 we manually walk the apk doc.)

- [ ] **Step 3: Validate, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): cross-walk apk.md; add APK-KNOWN-NEVER-SEEN rows"
```

---

## Task 15: Cross-walk alt repos for any remaining surface

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

Even after Tasks 6-14, the alt repos may carry decoders or named slots we missed. Walk each in turn.

- [ ] **Step 1: For each alt repo, walk its property dictionary**

```bash
# alternatives/dreame-mower (Tasshack-style mower fork)
grep -nE "^\s*(MOWER_PROPERTY|s[0-9]+p[0-9]+|MowerAction)" \
  /data/claude/homeassistant/alternatives/dreame-mower/custom_components/dreame_mower/dreame/types.py \
  | head -50
# Repeat for alternatives/dreame-vacuum, dreame-mova-mower, ha-dreame-a2-mower-legacy
```

For each entry, verify the inventory has a row. If a row exists, ensure `references.alt_repos` includes the file:line cite. If not, decide whether the slot applies to g2408 (vacuum-only? other-mower-only?) and either add an `UPSTREAM-KNOWN` row or skip with a note in `_sources` rationale.

- [ ] **Step 2: Walk `ha-dreame-a2-mower-legacy` for dropped decoders**

Use the legacy-vs-greenfield diff from earlier subagent reports as a worklist. Specifically check: `live_map.py`'s segment-deduplication logic, `protocol/trail_overlay.py`'s phase-byte filtering, `dreame/types.py:807-836` action mappings.

For each legacy decoder absent from the greenfield, add the relevant slot's `open_questions` entry "Legacy carried decoder X at <file:line>; greenfield dropped during rewrite — re-evaluate during axis 4."

- [ ] **Step 3: Validate, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): cross-walk alt repos; add UPSTREAM-KNOWN rows + legacy decoder open_questions"
```

---

## Task 16: Backfill `references.integration_code` across all rows

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

Every protocol slot the greenfield code currently handles must have its `integration_code` cite populated. This task is the final sweep.

- [ ] **Step 1: For each YAML row, `grep` greenfield for the slot**

```bash
# For s2p51 multiplexed shapes:
grep -n "Setting\." custom_components/dreame_a2_mower/protocol/config_s2p51.py | head
# For property mapping entries:
grep -n "PROPERTY_MAPPING\[" custom_components/dreame_a2_mower/mower/property_mapping.py
# Etc.
```

For each YAML row with `integration_code: null` but a confirmed handler in code, populate the cite. Conversely: any row that ends Task 16 still with `integration_code: null` AND `decoded: confirmed` AND not BT-only AND not not-on-g2408 is a candidate for axis 4 (decoder enrichment / new entity).

- [ ] **Step 2: Validate, render, commit**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_gen.py
git add docs/research/inventory/
git commit -m "feat(inventory): backfill integration_code references

Every greenfield-handled slot now has a file:line cite. Rows
that remain integration_code:null are the axis-4 candidate
list."
```

---

## Task 17: Run the read-only live probe; merge delta

**Files:**
- Modify: `tools/inventory_probe.py` (extend with real probe execution)
- Modify: `docs/research/inventory/inventory.yaml` (manual merge of probe results)

- [ ] **Step 1: Confirm with the user that the mower is at a safe state**

The user noted that some configs are locked while a mowing run is in progress. Print the current state and ask for explicit go-ahead:

```bash
# Read s2p1 mode + s2p2 from HA REST API (read-only).
HA_TOKEN=$(grep '^token:' /data/claude/homeassistant/ha-credentials.txt | cut -d: -f2- | tr -d ' ')
HA_URL=$(grep '^url:' /data/claude/homeassistant/ha-credentials.txt | cut -d: -f2- | tr -d ' ')
curl -s -H "Authorization: Bearer $HA_TOKEN" \
  "$HA_URL/api/states/sensor.dreame_a2_mower_state" | python -m json.tool
```

If the mower is mowing (`state ∈ {1, 5}`), pause this task until the user signals it's a safe time.

- [ ] **Step 2: Implement the four real-probe batches in `inventory_probe.py`**

Each batch is a function that:
1. Loads creds from `../server-credentials.txt` in situ (no copy).
2. Calls the Dreame cloud RPC via the integration's existing `cloud_client` (or a copy of the necessary subset).
3. Records every response or error in a structured form.
4. Returns a list of delta entries.

Hand-write minimal wire-level code (or reuse `cloud_client.py` if you can do so without booting HA). Keep delta entries to:

```python
{"slot_id": "s2p57", "verdict": "80001", "raw": null, "ts": "..."}
{"slot_id": "DOCK", "verdict": "ok", "raw": {...}, "ts": "..."}
```

- [ ] **Step 3: Run the probe**

```bash
python tools/inventory_probe.py
```

Confirm at each batch prompt. Probe writes `tools/inventory_probe_delta.json`.

- [ ] **Step 4: Merge the delta into `inventory.yaml` by hand**

For each delta entry:
- If `verdict: ok` and the slot has `seen_on_wire: false`, flip it to `true`, set `last_seen` to the probe timestamp, possibly upgrade `decoded` to `confirmed`.
- If `verdict: 80001`, no change to the row but add an `open_questions` note "Cloud RPC consistently 80001 on g2408 as of <date>".
- If `verdict: r=-1` or `r=-3`, set `not_on_g2408: true`.
- If a slot returned data we hadn't characterised, write a new row.

- [ ] **Step 5: Re-run audit, validator, render**

```bash
python tools/inventory_gen.py --validate-only && python tools/inventory_audit.py && python tools/inventory_gen.py
```

- [ ] **Step 6: Commit the probe tool extension and the YAML delta separately**

```bash
git add tools/inventory_probe.py
git commit -m "feat(inventory): live-probe execution for the four read-only batches"
git add docs/research/inventory/
git commit -m "data(inventory): merge live-probe delta from <YYYY-MM-DD>"
```

---

## Task 18: Drive `coverage-report.md` to empty

**Files:**
- Modify: `docs/research/inventory/inventory.yaml`

By this point the audit should be very close to clean. Iterate.

- [ ] **Step 1: Run audit**

```bash
python tools/inventory_audit.py 2>&1 | tee /tmp/audit-task18.txt
```

- [ ] **Step 2: For every line in the report, add the missing row**

Common residuals at this stage:
- Rare `s2p2` codes that fired only once in a long-tail probe log
- `candidates`-list endpoints that returned non-error and aren't yet in `cfg_individual`
- New CFG keys introduced by a firmware update mid-corpus

Add rows; rerun audit; iterate.

- [ ] **Step 3: When audit exits 0, commit**

```bash
python tools/inventory_audit.py
echo "exit code: $?"  # must be 0
git add docs/research/inventory/
git commit -m "feat(inventory): drive coverage-report to empty

Audit exits 0 against the committed corpus + cloud dumps.
Acceptance criterion #6 met."
```

---

## Task 19: Move alt-repo clones to `OLD/`

**Files:**
- Move: `/data/claude/homeassistant/alternatives/`, `ioBroker.dreame/`, `dreame-mova-mower/`, `ha-dreame-a2-mower-legacy/`
- Create: `/data/claude/homeassistant/OLD/alternatives_archive_2026-05-05/README.md`

These directories live one level above the integration repo, in the user's working directory. They aren't tracked by the integration's git, so the move is a filesystem operation, not a git mv.

- [ ] **Step 1: Confirm none of the four are tracked by the integration repo**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git ls-files | grep -E "alternatives|ioBroker.dreame|dreame-mova-mower|ha-dreame-a2-mower-legacy" || echo "ok: none tracked"
```

Expected: `ok: none tracked`.

- [ ] **Step 2: Create the archive directory**

```bash
cd /data/claude/homeassistant
mkdir -p OLD/alternatives_archive_2026-05-05
```

- [ ] **Step 3: Move the clones**

```bash
mv alternatives ioBroker.dreame dreame-mova-mower ha-dreame-a2-mower-legacy \
  OLD/alternatives_archive_2026-05-05/
```

- [ ] **Step 4: Write `OLD/alternatives_archive_2026-05-05/README.md`**

```markdown
# Alt-repo archive — 2026-05-05

Four upstream repositories used as protocol-RE references during the
greenfield buildout of `ha-dreame-a2-mower`. Their content has been
absorbed into the integration's inventory:

- `ha-dreame-a2-mower/docs/research/inventory/inventory.yaml`
  (machine-readable source of truth)
- `ha-dreame-a2-mower/docs/research/inventory/generated/g2408-canonical.md`
  (rendered reference)

The clones are kept here for two purposes:

1. **Protocol-info fallback** — past reviews repeatedly missed slots
   that turned out to be documented in these repos. Keeping them lets
   a future investigation re-read corners that may have been glossed.
2. **HA UX patterns** — the legacy and Tasshack-derived integrations
   chose specific ways to surface device state to users. Those choices
   inform axes 4 (decoder enrichment / new entities) and 5 (live-test
   gap closure) of the protocol-cleanup project.

To re-consult, e.g. for an apk-doc'd slot:

```bash
grep -rn "siid.*piid" OLD/alternatives_archive_2026-05-05/
```

Original sources:

- ioBroker.dreame: github.com/TA2k/ioBroker.dreame
- dreame-mower: github.com/antondaubert/dreame-mower
- dreame-vacuum: github.com/Tasshack/dreame-vacuum
- dreame-mova-mower: github.com/nicolasglg/dreame-mova-mower
- ha-dreame-a2-mower-legacy: github.com/okolbu/ha-dreame-a2-mower-legacy
```

- [ ] **Step 5: Verify probe-log paths still resolve**

The audit tool's `--probe-glob` defaults to `../probe_log_*.jsonl` relative to the integration repo, which is unaffected by the move (the probe logs sit alongside the moved directories, in `/data/claude/homeassistant/`).

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python tools/inventory_audit.py
```

Expected: exit 0 (already clean from Task 18).

- [ ] **Step 6: Commit the README — no integration-repo file changes from the move itself**

The integration repo doesn't track the moved directories, so there's nothing to commit there. The OLD/ README is outside the integration repo too. If the user maintains a separate VCS for `/data/claude/homeassistant/`, commit there; otherwise document the move in this plan's completion checklist.

---

## Task 20: Final acceptance checklist

**Files:**
- Modify: `docs/research/inventory/inventory.yaml` (any final fixes)
- Run: every tool

This task is a checkpoint, not new code. Walk every acceptance criterion from the spec.

- [ ] **Step 1: Acceptance criteria #1-3 — sections populated**

```bash
python -c "
import yaml
inv = yaml.safe_load(open('docs/research/inventory/inventory.yaml'))
for section in ('properties', 'events', 'actions', 'opcodes', 'cfg_keys',
                'cfg_individual', 'heartbeat_bytes', 'telemetry_fields',
                'telemetry_variants', 's2p51_shapes', 'state_codes',
                'mode_enum', 'oss_map_keys', 'session_summary_fields',
                'm_path_encoding', 'lidar_pcd'):
    n = len(inv.get(section) or [])
    print(f'{section}: {n}')
    assert n > 0, f'section {section} is empty'
print('ok')
"
```

Expected: every section has at least one row.

- [ ] **Step 2: Criterion #4 — every apk-known surface has a row**

This is enforced manually in Task 14. Re-skim apk.md once more; if any documented entity isn't in the inventory, add it now.

- [ ] **Step 3: Criterion #5 — every greenfield-handled slot has integration_code**

```bash
python -c "
import yaml
inv = yaml.safe_load(open('docs/research/inventory/inventory.yaml'))
unwired_decoded = []
for section in inv:
    if section.startswith('_'): continue
    for row in inv.get(section) or []:
        s = row.get('status') or {}
        r = row.get('references') or {}
        if s.get('decoded') == 'confirmed' and not s.get('bt_only') and not s.get('not_on_g2408') and not r.get('integration_code'):
            unwired_decoded.append(row['id'])
print(f'{len(unwired_decoded)} rows are confirmed-decoded but unwired (axis 4 candidates):')
for rid in unwired_decoded: print(f'  - {rid}')
"
```

This is informational; the count seeds axis 4.

- [ ] **Step 4: Criterion #6 — audit exits 0**

```bash
python tools/inventory_audit.py
echo "exit: $?"
```

Expected: `exit: 0`.

- [ ] **Step 5: Criterion #7 — generator runs cleanly; coverage-report empty**

```bash
python tools/inventory_gen.py
grep -c "_(empty" docs/research/inventory/generated/coverage-report.md
```

Expected: every section reports empty.

- [ ] **Step 6: Criterion #8 — alt-repo archive in place**

```bash
ls /data/claude/homeassistant/OLD/alternatives_archive_2026-05-05/
```

Expected: 4 directories (alternatives, ioBroker.dreame, dreame-mova-mower, ha-dreame-a2-mower-legacy) + README.md.

- [ ] **Step 7: Criterion #9 — inventory README documents the workflow**

Open `docs/research/inventory/README.md`, confirm it covers: how to add a row, how to run the generator, how to run the audit, how to run the live probe.

- [ ] **Step 8: Criteria #10 + #11 — units and value catalogs**

```bash
python -c "
import yaml
inv = yaml.safe_load(open('docs/research/inventory/inventory.yaml'))
no_unit = []
no_catalog = []
for section in inv:
    if section.startswith('_'): continue
    for row in inv.get(section) or []:
        shape = (row.get('payload_shape') or '').lower()
        # Heuristic: numeric payloads (cm, mm, dm, m2, percent, dbm in name or shape)
        # should have unit; small-int enums should have value_catalog.
        wants_unit = any(t in shape for t in ('cm', 'mm', 'centiares', 'percent', 'dbm', 'minute'))
        if wants_unit and not row.get('unit'):
            no_unit.append(row['id'])
        if 'enum' in shape and not row.get('value_catalog'):
            no_catalog.append(row['id'])
print(f'{len(no_unit)} numeric rows without unit:')
for r in no_unit: print(f'  - {r}')
print(f'{len(no_catalog)} enum rows without value_catalog:')
for r in no_catalog: print(f'  - {r}')
"
```

Add missing `unit` / `value_catalog` blocks to any flagged rows; re-run.

- [ ] **Step 9: Final commit**

```bash
git add docs/research/inventory/
git commit -m "feat(inventory): axis-1 complete

All 11 acceptance criteria green. Inventory covers properties,
events, actions, opcodes, CFG keys, cfg_individual, heartbeat
bytes, telemetry fields, frame variants, s2p51 shapes, state
codes, mode enum, OSS map keys, session-summary fields, M_PATH,
LiDAR PCD. Coverage report empty against the committed corpus.
Alt-repo clones archived under OLD/.

Hand-off: axis 2 consumes this inventory to restructure
g2408-protocol.md and TODO.md."
```

- [ ] **Step 10: Push**

```bash
git push origin main
```

Per user memory: HACS pulls from origin/main, so don't let integration-adjacent commits sit unpushed even if no version bump.

---

## Self-review summary

**Spec coverage check:**
- §4.1 file layout — Tasks 1, 19 (file creation + alt-repo move).
- §4.2 multi-section YAML — Task 1 (skeleton), Tasks 6-13 (population).
- §4.3 row schema with `unit` + `value_catalog` — Task 1 (README docs schema), every population task uses it; Task 20 verifies.
- §4.4 status taxonomy — Task 3 (generator computes labels); Task 20 verifies.
- §4.5 generator output — Tasks 2 + 3.
- §4.6 cross-walk — Tasks 6-15 mirror the 11-step procedure.
- §4.7 live-probe safety rules — Task 5 (skeleton) + Task 17 (real probe with explicit gate).
- §5 tooling — Tasks 2-5 build all three tools.
- §6 acceptance criteria — Task 20 verifies all 11.
- §7 risks — mitigations baked into the tool design (per-batch gates, validator vocab, "do not edit" banner).
- §8 hand-off — captured in Task 20's final commit message.

**Placeholder scan:** no "TBD", "TODO", "implement later". Every step shows the code. Data-entry tasks (6-15) reference the schema in Task 1 explicitly and provide a worked-example row per section so the engineer always has a template at hand.

**Type consistency:** `_UNIT_VOCAB`, `_DECODED_VALUES`, `_RENDER_ORDER` are defined once in `inventory_gen.py` (Task 2) and referenced consistently afterward. Section names (`properties`, `events`, etc.) match between YAML, validator, generator, and audit tool.
