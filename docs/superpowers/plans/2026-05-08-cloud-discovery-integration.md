# Cloud Discovery — Full Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the cloud-fetch pipeline around `get_batch_device_datas([])`, decode and integrate the seven new key families (M_PATH, SETTINGS, SCHEDULE, AI_HUMAN, FBD_NTYPE, OTA_INFO, TASKID, prop.s_*) discovered on 2026-05-08, surface 15 new SETTINGS-driven per-map active-follower entities, render M_PATH cloud history as a gray overlay on per-map cameras, and consolidate the 8 scattered `_refresh_*` methods into a single `_refresh_cloud_state()`.

**Architecture:** New `CloudState` frozen dataclass replaces `_cached_*` coordinator attrs and is the single read source for all consumers. New `protocol/` decoders (m_path, settings, schedule) parse fresh-from-cloud bytes into typed sub-dataclasses. The empty-batch + CFG fetch becomes the canonical 10-min refresh path; LOCN/DOCK/MAPL keep separate fast-cadence timers. SETTINGS dual-level structure preserved via read-modify-write — no semantic assumptions baked in.

**Tech Stack:** Python 3.13+, Home Assistant Core, pytest, frozen `@dataclass(slots=True)` patterns, regex-based binary-format decode for M_PATH.

**Spec:** `docs/superpowers/specs/2026-05-08-cloud-discovery-integration-design.md`

**Raw discovery artifact:** `docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`

---

## File Structure

| Purpose | Path |
|---|---|
| `CloudState` + sub-dataclasses | `custom_components/dreame_a2_mower/cloud_state.py` (new) |
| M_PATH regex decoder | `custom_components/dreame_a2_mower/protocol/m_path.py` (new) |
| SETTINGS read + read-modify-write helper | `custom_components/dreame_a2_mower/protocol/settings.py` (new) |
| SCHEDULE header decoder | `custom_components/dreame_a2_mower/protocol/schedule.py` (new) |
| `fetch_full_cloud_state()` orchestration | `custom_components/dreame_a2_mower/cloud_client.py` (modify) |
| Coordinator: replace 8 `_refresh_*` with one | `custom_components/dreame_a2_mower/coordinator.py` (modify) |
| MowerState: SETTINGS-driven fields | `custom_components/dreame_a2_mower/mower/state.py` (modify) |
| 15 new SETTINGS-driven entities | `number.py`, `select.py`, `switch.py` (modify) |
| OTA + schedule sensors | `sensor.py` (modify) |
| Camera diagnostic attrs + M_PATH overlay | `camera.py`, `map_render.py` (modify) |
| Schedule view dynamic | `dashboards/mower/dashboard.yaml` (modify) |
| Decoder fixtures from real data | `tests/protocol/fixtures/2026-05-08-*.json` (new) |
| Decoder tests | `tests/protocol/test_m_path.py`, `test_settings.py`, `test_schedule.py` (new) |
| `CloudState` integration test | `tests/integration/test_cloud_state.py` (new) |
| Active-follower entity tests | `tests/integration/test_settings_entities.py` (new) |
| Renderer test | `tests/protocol/test_m_path_render.py` (new) |
| Docs | `docs/multi-map.md` update, `README.md`, `docs/TODO.md` |
| Version bump | `manifest.json` |

---

## Task 1: Create `cloud_state.py` with frozen dataclasses

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_state.py`
- Test: `tests/test_cloud_state_dataclasses.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cloud_state_dataclasses.py`:

```python
"""Smoke tests for CloudState + sub-dataclass instantiation."""
from __future__ import annotations

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState,
    MowPathData,
    ScheduleData,
    ScheduleSlot,
    SettingsRoot,
)


def test_cloud_state_constructs_with_minimal_args():
    cs = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        locn=None,
        dock={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    assert cs.fetched_at_unix == 0
    assert cs.task_id == 0


def test_cloud_state_is_frozen():
    cs = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, locn=None, dock={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    import dataclasses
    try:
        cs.task_id = 42  # should raise
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("CloudState should be frozen")


def test_mow_path_data_segments_is_tuple_of_tuples():
    mp = MowPathData(map_id=1, segments=(((100, 200), (300, 400)),))
    assert mp.map_id == 1
    assert mp.segments == (((100, 200), (300, 400)),)


def test_schedule_slot_fields():
    s = ScheduleSlot(slot_id=0, name="Spring", raw_blob_b64="qgcQ3gEA")
    assert s.slot_id == 0
    assert s.name == "Spring"
    assert s.raw_blob_b64 == "qgcQ3gEA"
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/test_cloud_state_dataclasses.py -v`
Expected: FAIL — `ModuleNotFoundError: cloud_state`

- [ ] **Step 3: Create the dataclasses**

Create `custom_components/dreame_a2_mower/cloud_state.py`:

```python
"""CloudState — unified container for all cloud-fetched data.

Replaces the scattered `_cached_*` attributes on the coordinator.
Populated by `_refresh_cloud_state()` (every 10 min) plus
fast-cadence probe updates (LOCN, DOCK, MAPL — separate timers).

All sub-dataclasses are frozen + slots for O(1) attribute access
and immutability semantics. Mutation goes through coordinator
helpers that build a new CloudState and replace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .map_decoder import MapData


@dataclass(frozen=True, slots=True)
class MowPathData:
    """Per-map persisted mow-trajectory history from M_PATH.* batch.

    Each segment is a tuple of (x_mm, y_mm) pairs; segment boundaries
    correspond to the firmware's `[32767, -32768]` pen-up sentinel
    in the raw stream.
    """

    map_id: int
    segments: tuple[tuple[tuple[int, int], ...], ...]


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    """One slot from the SCHEDULE batch."""

    slot_id: int
    name: str
    raw_blob_b64: str  # decoded later when format known


@dataclass(frozen=True, slots=True)
class ScheduleData:
    """Cloud-side schedule data (header-only decode in this PR)."""

    version: int
    slots: tuple[ScheduleSlot, ...]


@dataclass(frozen=True, slots=True)
class SettingsRoot:
    """Per-map mowing-behaviour settings.

    Preserves the dual-level structure observed on g2408 fw 4.3.6_0550
    (two top-level entries, both `mode: 0` with the same map_id keys
    inside). The semantic of the two entries is unknown; we read
    entry 0 as canonical and read-modify-write the FULL `raw` list
    on writes so entry 1's content is preserved unchanged.
    """

    raw: list[dict[str, Any]]
    by_map_id_canonical: dict[int, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CloudState:
    """Unified container for all cloud-fetched device state."""

    cfg: dict[str, Any]
    maps_by_id: dict[int, MapData]
    mow_paths_by_map_id: dict[int, MowPathData]
    settings: SettingsRoot
    schedule: ScheduleData
    ai_human_enabled: bool | None
    forbidden_node_types_by_map: dict[int, dict[str, Any]]
    ota_status: tuple[int, int] | None
    task_id: int
    props: dict[str, str]
    locn: tuple[float, float] | None
    dock: dict[str, Any]
    mapl: list[list[Any]] | None
    mihis: dict[str, Any]
    fetched_at_unix: int
```

- [ ] **Step 4: Run, verify it passes**

Run: `python -m pytest tests/test_cloud_state_dataclasses.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_state.py tests/test_cloud_state_dataclasses.py
git commit -m "feat(cloud-state): CloudState + sub-dataclass scaffold"
```

---

## Task 2: M_PATH regex decoder

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/m_path.py`
- Create: `tests/protocol/fixtures/2026-05-08-m-path-sample.txt`
- Create: `tests/protocol/test_m_path.py`

- [ ] **Step 1: Create the test fixture**

Extract the M_PATH segment from the user's real raw batch dump and save it. The fixture is a plain string (the joined M_PATH chunks).

Create `tests/protocol/fixtures/2026-05-08-m-path-sample.txt` with content (extracted from `docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`'s `M_PATH.*` keys joined). For this plan, use a synthetic minimal fixture matching the real shape:

```
[][32767,-32768],[-100,-200],[100,200],[200,300],[32767,-32768],[400,500],[500,600]
```

The leading `[]` is Map 0's empty M_PATH; the rest is Map 1's two segments.

- [ ] **Step 2: Write the failing test**

Create `tests/protocol/test_m_path.py`:

```python
"""Tests for M_PATH regex decoder."""
from __future__ import annotations

from pathlib import Path

from custom_components.dreame_a2_mower.protocol.m_path import (
    parse_m_path_batch,
)

FIXTURE = Path(__file__).parent / "fixtures" / "2026-05-08-m-path-sample.txt"


def test_parse_empty_string_returns_empty_dict():
    assert parse_m_path_batch("", split_pos=0) == {}


def test_parse_single_map_no_split():
    """No split (info=0): all coordinates belong to map_id=0."""
    raw = "[100,200],[200,300],[32767,-32768],[400,500]"
    result = parse_m_path_batch(raw, split_pos=0)
    assert set(result.keys()) == {0}
    # Coords are 1/10th-scale (decimeters); decoder multiplies by 10 for mm.
    assert result[0].segments == (
        ((1000, 2000), (2000, 3000)),
        ((4000, 5000),),
    )


def test_parse_two_maps_split_skips_first_segment():
    """split_pos > 0 means skip the first split_pos chars (legacy upstream pattern).
    Bytes [0:split_pos] are Map 0's data; remainder is Map 1's."""
    raw = FIXTURE.read_text()  # leading "[]" then Map 1 data
    # split_pos=2 means the leading "[]" is Map 0 (empty); skip it.
    result = parse_m_path_batch(raw, split_pos=2)
    assert 0 in result
    assert 1 in result
    assert result[0].segments == ()  # empty Map 0
    # Map 1 has two segments separated by a sentinel.
    assert len(result[1].segments) == 2
    assert result[1].segments[0] == ((-1000, -2000), (1000, 2000), (2000, 3000))
    assert result[1].segments[1] == ((4000, 5000), (5000, 6000))


def test_parse_no_pairs_returns_empty_segments():
    """Whitespace / empty content yields empty segments (not crash)."""
    result = parse_m_path_batch("[]", split_pos=0)
    assert 0 in result
    assert result[0].segments == ()


def test_parse_handles_split_pos_larger_than_raw():
    """Defensive: split_pos > len(raw) treated as 0."""
    raw = "[100,200]"
    result = parse_m_path_batch(raw, split_pos=999)
    assert 0 in result
```

- [ ] **Step 3: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_m_path.py -v`
Expected: FAIL — `ModuleNotFoundError: protocol.m_path`

- [ ] **Step 4: Implement the decoder**

Create `custom_components/dreame_a2_mower/protocol/m_path.py`:

```python
"""M_PATH.* regex decoder.

Format (verified 2026-05-08 against g2408 fw 4.3.6_0550):
  - Joined string is a sequence of `[x,y]` pairs separated by commas
  - The pair `[32767,-32768]` is the firmware's pen-up / segment-break sentinel
  - Coordinates are 1/10th-scale (decimeters); multiply by 10 for cloud-frame mm
  - The `M_PATH.info` byte offset (when > 0) marks the start of map 1's data;
    bytes [0:info] belong to map 0 (legacy upstream's pattern, see
    `alternatives/dreame-mower/.../map_data_parser.py:256-313`)

Use `parse_m_path_batch(raw, split_pos)` from the joined chunks +
`int(M_PATH.info)`.
"""
from __future__ import annotations

import re

from ..cloud_state import MowPathData

_PAIR_RE = re.compile(r"\[(-?\d+),(-?\d+)\]")
_SENTINEL = (32767, -32768)


def _decode_one(raw: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Decode one map's M_PATH region into a tuple of segments.

    Each segment is a tuple of (x_mm, y_mm) pairs in cloud-frame mm.
    """
    if not raw or not raw.strip() or raw.strip() == "[]":
        return ()
    raw_pairs = [
        (int(m.group(1)), int(m.group(2)))
        for m in _PAIR_RE.finditer(raw)
    ]
    if not raw_pairs:
        return ()
    segments: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []
    for p in raw_pairs:
        if p == _SENTINEL:
            if current:
                segments.append(tuple(current))
                current = []
        else:
            # cm → mm scaling
            current.append((p[0] * 10, p[1] * 10))
    if current:
        segments.append(tuple(current))
    return tuple(segments)


def parse_m_path_batch(raw: str, split_pos: int) -> dict[int, MowPathData]:
    """Parse the joined M_PATH.* string into per-map mow trajectories.

    `raw` is the result of joining `M_PATH.0..N` in order.
    `split_pos` is `int(M_PATH.info)` (0 for single-map devices).

    Returns a dict keyed by map_id (0 and 1 when split_pos > 0).
    """
    if not raw:
        return {}
    if split_pos < 0 or split_pos >= len(raw):
        # Defensive: treat as single-map.
        return {0: MowPathData(map_id=0, segments=_decode_one(raw))}
    if split_pos == 0:
        # Single map.
        return {0: MowPathData(map_id=0, segments=_decode_one(raw))}
    # Two maps: bytes [0:split_pos] are map 0, remainder is map 1.
    return {
        0: MowPathData(map_id=0, segments=_decode_one(raw[:split_pos])),
        1: MowPathData(map_id=1, segments=_decode_one(raw[split_pos:])),
    }
```

- [ ] **Step 5: Run, verify it passes**

Run: `python -m pytest tests/protocol/test_m_path.py -v`
Expected: PASS (5/5)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/m_path.py tests/protocol/test_m_path.py tests/protocol/fixtures/2026-05-08-m-path-sample.txt
git commit -m "feat(m-path): regex decoder for cloud-persisted mow trajectories"
```

---

## Task 3: SETTINGS read + read-modify-write helper

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/settings.py`
- Create: `tests/protocol/fixtures/2026-05-08-settings-sample.json`
- Create: `tests/protocol/test_settings.py`

- [ ] **Step 1: Create the fixture**

Create `tests/protocol/fixtures/2026-05-08-settings-sample.json` with the shape observed (two top-level entries, two map_ids per entry, 19 fields each):

```json
[
  {
    "mode": 0,
    "settings": {
      "0": {
        "id": 0,
        "version": 78,
        "mowingHeight": 5,
        "mowingDirection": 0,
        "mowingDirectionMode": 0,
        "cutterPosition": 1,
        "cutterPositionHeight": 3,
        "edgeMowingAuto": 1,
        "edgeMowingNum": 2,
        "edgeMowingObstacleAvoidance": 1,
        "edgeMowingSafe": 1,
        "edgeMowingWalkMode": 0,
        "obstacleAvoidanceAi": 7,
        "obstacleAvoidanceDistance": 15,
        "obstacleAvoidanceEnabled": 1,
        "obstacleAvoidanceHeight": 20,
        "obstacleAvoidanceSensitivity": 2
      },
      "1": {
        "id": 1,
        "version": 3,
        "mowingHeight": 6,
        "mowingDirection": 180,
        "mowingDirectionMode": 0,
        "cutterPosition": 1,
        "cutterPositionHeight": 3,
        "edgeMowingAuto": 1,
        "edgeMowingNum": 1,
        "edgeMowingObstacleAvoidance": 1,
        "edgeMowingSafe": 1,
        "edgeMowingWalkMode": 0,
        "obstacleAvoidanceAi": 7,
        "obstacleAvoidanceDistance": 20,
        "obstacleAvoidanceEnabled": 1,
        "obstacleAvoidanceHeight": 20,
        "obstacleAvoidanceSensitivity": 2
      }
    }
  },
  {
    "mode": 0,
    "settings": {
      "0": {"id": 0, "version": 0, "mowingHeight": 6, "mowingDirection": 180, "mowingDirectionMode": 0, "cutterPosition": 1, "cutterPositionHeight": 3, "edgeMowingAuto": 1, "edgeMowingNum": 1, "edgeMowingObstacleAvoidance": 1, "edgeMowingSafe": 1, "edgeMowingWalkMode": 1, "obstacleAvoidanceAi": 7, "obstacleAvoidanceDistance": 20, "obstacleAvoidanceEnabled": 1, "obstacleAvoidanceHeight": 20, "obstacleAvoidanceSensitivity": 2},
      "1": {"id": 1, "version": 0, "mowingHeight": 6, "mowingDirection": 180, "mowingDirectionMode": 0, "cutterPosition": 1, "cutterPositionHeight": 3, "edgeMowingAuto": 1, "edgeMowingNum": 1, "edgeMowingObstacleAvoidance": 1, "edgeMowingSafe": 1, "edgeMowingWalkMode": 1, "obstacleAvoidanceAi": 7, "obstacleAvoidanceDistance": 20, "obstacleAvoidanceEnabled": 1, "obstacleAvoidanceHeight": 20, "obstacleAvoidanceSensitivity": 2}
    }
  }
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/protocol/test_settings.py`:

```python
"""Tests for SETTINGS decoder + read-modify-write helper."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.protocol.settings import (
    parse_settings_batch,
    write_setting,
)

FIXTURE = Path(__file__).parent / "fixtures" / "2026-05-08-settings-sample.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_parse_extracts_canonical_per_map():
    """Entry 0 of SETTINGS is canonical: by_map_id_canonical[i] = entry0.settings[str(i)]."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert set(result.by_map_id_canonical.keys()) == {0, 1}
    assert result.by_map_id_canonical[0]["mowingDirection"] == 0
    assert result.by_map_id_canonical[1]["mowingDirection"] == 180


def test_parse_preserves_full_raw():
    """The full list (both top-level entries) is preserved verbatim."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert result.raw == raw
    assert len(result.raw) == 2


def test_write_setting_modifies_entry_0_only():
    """Writes go to entry 0; entry 1 is preserved unchanged."""
    raw = _load()
    new_raw = write_setting(raw, map_id=0, field="mowingHeight", value=7)
    assert new_raw[0]["settings"]["0"]["mowingHeight"] == 7
    # Other map untouched
    assert new_raw[0]["settings"]["1"]["mowingHeight"] == 6
    # Entry 1 untouched
    assert new_raw[1] == raw[1]


def test_write_setting_unknown_map_id_raises():
    raw = _load()
    try:
        write_setting(raw, map_id=99, field="mowingHeight", value=7)
    except KeyError as ex:
        assert "99" in str(ex)
    else:
        raise AssertionError("write_setting should raise KeyError on unknown map_id")


def test_write_setting_returns_new_object():
    """write_setting is non-mutating: returns a new list, leaves input alone."""
    raw = _load()
    original_height = raw[0]["settings"]["0"]["mowingHeight"]
    new_raw = write_setting(raw, map_id=0, field="mowingHeight", value=7)
    assert raw[0]["settings"]["0"]["mowingHeight"] == original_height
    assert new_raw is not raw


def test_parse_handles_missing_settings_key():
    """If entry 0 has no `settings` dict, by_map_id_canonical is empty (defensive)."""
    result = parse_settings_batch([{"mode": 0}])
    assert result.by_map_id_canonical == {}


def test_parse_handles_empty_list():
    result = parse_settings_batch([])
    assert result.raw == []
    assert result.by_map_id_canonical == {}
```

- [ ] **Step 3: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: protocol.settings`

- [ ] **Step 4: Implement parser + writer**

Create `custom_components/dreame_a2_mower/protocol/settings.py`:

```python
"""SETTINGS.* batch decoder + read-modify-write helper.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    [
      {"mode": 0, "settings": {"0": {<19 fields>}, "1": {<19 fields>}}},
      {"mode": 0, "settings": {"0": {...}, "1": {...}}}
    ]

Two top-level entries, both `mode: 0`, with the same map_id keys
inside. The semantic of the dual-level structure is UNKNOWN —
might be (a) per-mode profiles, (b) "current" + "default", or
(c) something else. We treat entry 0 as canonical for reads and
preserve entry 1 unchanged on writes.
"""
from __future__ import annotations

import copy
from typing import Any

from ..cloud_state import SettingsRoot


def parse_settings_batch(raw: list[dict[str, Any]]) -> SettingsRoot:
    """Parse a SETTINGS.* JSON-decoded payload into a SettingsRoot.

    Reads entry 0's `settings` dict (string-keyed by map_id) into
    `by_map_id_canonical` for fast active-follower entity reads.
    """
    by_map_id_canonical: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list) and raw:
        entry0 = raw[0]
        if isinstance(entry0, dict):
            settings_dict = entry0.get("settings")
            if isinstance(settings_dict, dict):
                for k, v in settings_dict.items():
                    try:
                        map_id = int(k)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(v, dict):
                        by_map_id_canonical[map_id] = v
    return SettingsRoot(
        raw=raw if isinstance(raw, list) else [],
        by_map_id_canonical=by_map_id_canonical,
    )


def write_setting(
    raw: list[dict[str, Any]],
    *,
    map_id: int,
    field: str,
    value: Any,
) -> list[dict[str, Any]]:
    """Read-modify-write: produce a new SETTINGS list with `field` set
    on entry 0's map_id sub-dict. Entry 1 (and any beyond) is preserved
    unchanged. Input is NOT mutated.

    Raises KeyError if map_id is not present in entry 0's settings dict.
    """
    new_raw = copy.deepcopy(raw)
    if not new_raw or not isinstance(new_raw[0], dict):
        raise KeyError(f"SETTINGS entry 0 missing or malformed; cannot set {field}")
    settings_dict = new_raw[0].setdefault("settings", {})
    map_key = str(map_id)
    if map_key not in settings_dict:
        raise KeyError(map_key)
    settings_dict[map_key][field] = value
    return new_raw
```

- [ ] **Step 5: Run, verify it passes**

Run: `python -m pytest tests/protocol/test_settings.py -v`
Expected: PASS (7/7)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/settings.py tests/protocol/test_settings.py tests/protocol/fixtures/2026-05-08-settings-sample.json
git commit -m "feat(settings): SETTINGS decoder + read-modify-write helper"
```

---

## Task 4: SCHEDULE header decoder

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/schedule.py`
- Create: `tests/protocol/test_schedule.py`

> **Note on the deferred blob decode:** The base64 `raw_blob_b64`
> field is intentionally NOT decoded in this task — only the headers
> (id, name, version) are surfaced. When tackling the deferred blob
> decode TODO, read `/data/claude/homeassistant/schedule-doc.txt`
> first — the user has documented the app-side schedule UI plus
> concrete data points (specific times, days-of-week) that correlate
> directly to the encoded bytes. Reference batch dumps are at
> `docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
> and `docs/research/cloud-discovery/2026-05-08-post-schedule-toggle-batch.json`.

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_schedule.py`:

```python
"""Tests for SCHEDULE header decoder (blob decode deferred)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.schedule import (
    parse_schedule_batch,
)


def test_parse_real_shape():
    """Verified shape (2026-05-08, g2408 fw 4.3.6_0550):
        {"d": [[id, ?, name, blob_b64], ...], "v": version}
    """
    raw = {
        "d": [
            [0, 0, "Spr & Sum Schedule", "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="],
            [1, 0, "", "qgcQHAIA7aoHQBwCAO0="],
        ],
        "v": 657,
    }
    result = parse_schedule_batch(raw)
    assert result.version == 657
    assert len(result.slots) == 2
    assert result.slots[0].slot_id == 0
    assert result.slots[0].name == "Spr & Sum Schedule"
    assert result.slots[0].raw_blob_b64 == "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="
    assert result.slots[1].slot_id == 1
    assert result.slots[1].name == ""


def test_parse_empty_returns_empty_slots():
    result = parse_schedule_batch({"d": [], "v": 0})
    assert result.version == 0
    assert result.slots == ()


def test_parse_html_escape_in_name_decoded():
    """Cloud emits `&amp;`; decoder unescapes to `&`."""
    raw = {"d": [[0, 0, "A &amp; B", ""]], "v": 1}
    result = parse_schedule_batch(raw)
    assert result.slots[0].name == "A & B"


def test_parse_invalid_input_returns_empty():
    """Defensive: non-dict input → empty result, not crash."""
    assert parse_schedule_batch(None).slots == ()
    assert parse_schedule_batch([]).slots == ()
    assert parse_schedule_batch({}).slots == ()


def test_parse_skips_malformed_slot_entries():
    raw = {"d": [[0, 0, "Good", "blob"], "not-a-list", [1]], "v": 1}
    result = parse_schedule_batch(raw)
    assert len(result.slots) == 1  # only the well-formed entry
    assert result.slots[0].slot_id == 0
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: protocol.schedule`

- [ ] **Step 3: Implement decoder**

Create `custom_components/dreame_a2_mower/protocol/schedule.py`:

```python
"""SCHEDULE.* batch decoder (header-only).

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    {"d": [[id, mode, name, base64_blob], ...], "v": version}

Each slot has an opaque base64 blob whose format is unknown.
This decoder extracts the metadata (id, name, version) so the
Schedule dashboard view can list slots; blob decode is deferred
to a follow-up TODO.
"""
from __future__ import annotations

import html
from typing import Any

from ..cloud_state import ScheduleData, ScheduleSlot


def parse_schedule_batch(raw: Any) -> ScheduleData:
    """Parse a SCHEDULE.* JSON-decoded payload into ScheduleData.

    Returns ScheduleData(version=0, slots=()) on any malformed input.
    """
    if not isinstance(raw, dict):
        return ScheduleData(version=0, slots=())
    version = raw.get("v")
    try:
        version_int = int(version) if version is not None else 0
    except (TypeError, ValueError):
        version_int = 0
    d_list = raw.get("d")
    if not isinstance(d_list, list):
        return ScheduleData(version=version_int, slots=())
    slots: list[ScheduleSlot] = []
    for entry in d_list:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        try:
            slot_id = int(entry[0])
        except (TypeError, ValueError):
            continue
        name = html.unescape(str(entry[2]) if entry[2] is not None else "")
        blob = str(entry[3]) if entry[3] is not None else ""
        slots.append(ScheduleSlot(slot_id=slot_id, name=name, raw_blob_b64=blob))
    return ScheduleData(version=version_int, slots=tuple(slots))
```

- [ ] **Step 4: Run, verify it passes**

Run: `python -m pytest tests/protocol/test_schedule.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule.py tests/protocol/test_schedule.py
git commit -m "feat(schedule): header decoder (blob decode deferred)"
```

---

## Task 5: Generic batch family-grouper

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/batch_grouper.py`
- Create: `tests/protocol/test_batch_grouper.py`

This pulls out a small reusable helper for splitting a batch dict by prefix family — needed by `cloud_client.fetch_full_cloud_state` (Task 6) to find all the chunked families.

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_batch_grouper.py`:

```python
"""Tests for batch family grouping + chunk reassembly."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.batch_grouper import (
    group_keys_by_prefix,
    join_family_chunks,
)


def test_group_by_prefix_basic():
    batch = {
        "MAP.0": "a", "MAP.1": "b", "MAP.info": "5",
        "M_PATH.0": "c", "M_PATH.info": "0",
        "prop.s_auth": "x",
        "standalone": "y",
    }
    fams = group_keys_by_prefix(batch)
    assert fams["MAP"] == ["MAP.0", "MAP.1", "MAP.info"]
    assert fams["M_PATH"] == ["M_PATH.0", "M_PATH.info"]
    assert fams["prop"] == ["prop.s_auth"]
    assert fams["standalone"] == ["standalone"]


def test_join_chunks_in_numeric_order():
    """MAP.10 must NOT come between MAP.1 and MAP.2 — sort numerically."""
    batch = {
        "MAP.0": "first",
        "MAP.1": "second",
        "MAP.10": "eleventh",  # alphabetical sort would put this between 1 and 2
        "MAP.2": "third",
        "MAP.info": "skip",
    }
    raw = join_family_chunks("MAP", batch)
    assert raw == "firstsecondthirdeleventh"


def test_join_chunks_skips_info_key():
    batch = {"MAP.0": "data", "MAP.info": "999"}
    assert join_family_chunks("MAP", batch) == "data"


def test_join_chunks_handles_missing_chunks():
    """If MAP.0 and MAP.2 exist but MAP.1 doesn't, treat the gap as empty."""
    batch = {"MAP.0": "a", "MAP.2": "c"}
    raw = join_family_chunks("MAP", batch)
    assert raw == "ac"


def test_join_chunks_empty_family():
    assert join_family_chunks("NOPE", {"MAP.0": "x"}) == ""
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_batch_grouper.py -v`
Expected: FAIL — `ModuleNotFoundError: protocol.batch_grouper`

- [ ] **Step 3: Implement helpers**

Create `custom_components/dreame_a2_mower/protocol/batch_grouper.py`:

```python
"""Helpers for grouping a batch response by prefix family.

Used by cloud_client.fetch_full_cloud_state to find chunked families
(MAP.*, M_PATH.*, SETTINGS.*, etc.) and reassemble them.
"""
from __future__ import annotations

from typing import Any


def group_keys_by_prefix(batch: dict[str, Any]) -> dict[str, list[str]]:
    """Group keys by their dot-prefix.

    'MAP.0', 'MAP.1', 'MAP.info' -> {'MAP': ['MAP.0', 'MAP.1', 'MAP.info']}
    'standalone_key' -> {'standalone_key': ['standalone_key']}
    Within each family, keys are returned sorted; numeric chunk keys
    sort BEFORE non-numeric keys like '.info'.
    """
    by_prefix: dict[str, list[str]] = {}
    for k in batch.keys():
        prefix = k.split(".", 1)[0] if "." in k else k
        by_prefix.setdefault(prefix, []).append(k)
    # Sort each family's keys: numeric-suffix keys first (numerically),
    # then non-numeric.
    for prefix, keys in by_prefix.items():
        keys.sort(key=_chunk_sort_key)
    return by_prefix


def _chunk_sort_key(key: str) -> tuple[int, int | str]:
    """Sort key: numeric suffix first (in numeric order), then alpha."""
    if "." not in key:
        return (1, key)
    suffix = key.split(".", 1)[1]
    if suffix.isdigit():
        return (0, int(suffix))
    return (1, suffix)


def join_family_chunks(prefix: str, batch: dict[str, Any]) -> str:
    """Join the numerically-suffixed chunks of one family in order.

    Skips '<prefix>.info' and any non-numeric keys. Empty/missing
    chunks are treated as empty strings.
    """
    chunked = sorted(
        (k for k in batch.keys()
         if "." in k
         and k.split(".", 1)[0] == prefix
         and k.split(".", 1)[1].isdigit()),
        key=lambda k: int(k.split(".", 1)[1]),
    )
    return "".join(batch.get(k, "") or "" for k in chunked)
```

- [ ] **Step 4: Run, verify it passes**

Run: `python -m pytest tests/protocol/test_batch_grouper.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/batch_grouper.py tests/protocol/test_batch_grouper.py
git commit -m "feat(batch-grouper): family-prefix grouping + numeric-order chunk join"
```

---

## Task 6: `fetch_full_cloud_state` orchestrator

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py`
- Create: `tests/protocol/test_fetch_full_cloud_state.py`

This adds a new method on the cloud client that does ONE empty-batch fetch + ONE CFG fetch + small probes (LOCN/DOCK/MAPL/MIHIS) and returns a `CloudState`. Existing `fetch_*` methods stay; the new one is additive.

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_fetch_full_cloud_state.py`:

```python
"""Tests for the new fetch_full_cloud_state orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
from custom_components.dreame_a2_mower.cloud_state import CloudState

# Real raw batch from the user's account (preserved in research artifact).
REAL_BATCH = json.loads(
    Path(__file__).parent.parent.parent.joinpath(
        "docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json"
    ).read_text()
)


def _make_client(batch_response, cfg_response, locn=None, dock=None, mapl=None, mihis=None):
    client = object.__new__(DreameA2CloudClient)
    client.get_batch_device_datas = MagicMock(return_value=batch_response)
    client.fetch_cfg = MagicMock(return_value=cfg_response or {})
    client.fetch_locn = MagicMock(return_value=locn)
    client.fetch_dock = MagicMock(return_value=dock or {})
    client.fetch_mapl = MagicMock(return_value=mapl)
    client.fetch_mihis = MagicMock(return_value=mihis or {})
    return client


def test_fetch_full_cloud_state_returns_cloud_state():
    client = _make_client(REAL_BATCH, {"VER": 461, "TIME": "Europe/Oslo"})
    cs = client.fetch_full_cloud_state()
    assert isinstance(cs, CloudState)
    # Real batch has 2 maps
    assert set(cs.maps_by_id.keys()) == {0, 1}
    # SETTINGS preserved both top-level entries
    assert len(cs.settings.raw) == 2
    # SETTINGS canonical dict has both map_ids
    assert set(cs.settings.by_map_id_canonical.keys()) == {0, 1}
    # mowingDirection differs between maps (0 vs 180)
    assert cs.settings.by_map_id_canonical[0]["mowingDirection"] == 0
    assert cs.settings.by_map_id_canonical[1]["mowingDirection"] == 180
    # Schedule has 2 slots
    assert len(cs.schedule.slots) == 2
    assert cs.schedule.slots[0].name.startswith("Spr")
    # M_PATH split — Map 0 empty, Map 1 has segments
    assert cs.mow_paths_by_map_id[0].segments == ()
    assert len(cs.mow_paths_by_map_id[1].segments) > 0
    # AI_HUMAN
    assert cs.ai_human_enabled is True
    # OTA_INFO
    assert cs.ota_status == (2, 100)
    # TASK_ID
    assert cs.task_id == 0
    # FBD_NTYPE per-map
    assert cs.forbidden_node_types_by_map[0] == {"101": 9}
    # CFG passed through
    assert cs.cfg["VER"] == 461


def test_fetch_full_cloud_state_handles_empty_batch():
    """If the cloud returns an empty batch, CloudState still constructs."""
    client = _make_client({}, {})
    cs = client.fetch_full_cloud_state()
    assert isinstance(cs, CloudState)
    assert cs.maps_by_id == {}
    assert cs.settings.raw == []
    assert cs.task_id == 0


def test_fetch_full_cloud_state_returns_none_on_total_failure():
    """If get_batch_device_datas raises, fetch_full_cloud_state returns None."""
    client = _make_client(None, None)
    client.get_batch_device_datas = MagicMock(side_effect=Exception("network"))
    cs = client.fetch_full_cloud_state()
    assert cs is None
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_fetch_full_cloud_state.py -v`
Expected: FAIL — `AttributeError: ... 'fetch_full_cloud_state'`

- [ ] **Step 3: Implement orchestrator**

Add to `custom_components/dreame_a2_mower/cloud_client.py` (place AFTER the existing `fetch_map` method):

```python
    def fetch_full_cloud_state(self) -> "CloudState | None":
        """Fetch the device's full cloud state in one orchestrated call.

        - Empty-list `get_batch_device_datas([])` returns all chunked
          data families (MAP, M_PATH, SETTINGS, SCHEDULE, AI_HUMAN,
          FBD_NTYPE, OTA_INFO, TASKID, prop.s_*).
        - `fetch_cfg()` returns the 24 CFG keys (not in the empty-batch).
        - Probes for LOCN, DOCK, MAPL, MIHIS (each a separate cfg_individual
          call that's already wired).

        Returns None if the empty-batch call fails entirely (network
        error). Partial data — a missing family within a successful
        batch — produces the appropriate empty/None field on
        CloudState rather than failing the whole fetch.
        """
        from .cloud_state import CloudState, ScheduleData, SettingsRoot
        from .map_decoder import parse_cloud_maps
        from .protocol.batch_grouper import group_keys_by_prefix, join_family_chunks
        from .protocol.m_path import parse_m_path_batch
        from .protocol.schedule import parse_schedule_batch
        from .protocol.settings import parse_settings_batch

        try:
            batch = self.get_batch_device_datas([])
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: empty-batch raised: %s", ex)
            return None
        if batch is None:
            return None
        if not isinstance(batch, dict):
            _LOGGER.warning(
                "fetch_full_cloud_state: empty-batch returned %s, not dict",
                type(batch).__name__,
            )
            batch = {}

        # CFG (separate call — not in the empty-batch).
        try:
            cfg = self.fetch_cfg() or {}
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: fetch_cfg raised: %s", ex)
            cfg = {}

        # Group batch keys by family prefix.
        families = group_keys_by_prefix(batch)

        # MAP.* — reuse existing fetch_map logic via an inline parse.
        # The existing fetch_map() makes its own get_batch_device_datas
        # call; we already have the batch, so parse directly.
        maps_by_id: dict[int, Any] = {}
        if "MAP" in families:
            map_joined = join_family_chunks("MAP", batch)
            map_info_raw = batch.get("MAP.info") or ""
            try:
                split_pos = int(map_info_raw) if map_info_raw else 0
            except (TypeError, ValueError):
                split_pos = 0
            segments = (
                [map_joined[:split_pos], map_joined[split_pos:]]
                if 0 < split_pos < len(map_joined)
                else [map_joined]
            )
            import json as _json
            raw_by_id: dict[int, dict] = {}
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                try:
                    parsed = _json.loads(seg)
                except (ValueError, _json.JSONDecodeError):
                    continue
                entries = parsed if isinstance(parsed, list) else [parsed]
                for entry in entries:
                    if isinstance(entry, str):
                        try:
                            entry = _json.loads(entry)
                        except Exception:
                            continue
                    if not isinstance(entry, dict):
                        continue
                    if "boundary" not in entry and "mowingAreas" not in entry:
                        continue
                    idx = entry.get("mapIndex", 0)
                    try:
                        idx_int = int(idx)
                    except (TypeError, ValueError):
                        idx_int = 0
                    raw_by_id[idx_int] = entry
            maps_by_id = parse_cloud_maps(raw_by_id) if raw_by_id else {}

        # M_PATH.*
        mow_paths_by_map_id: dict[int, Any] = {}
        if "M_PATH" in families:
            m_path_joined = join_family_chunks("M_PATH", batch)
            m_path_info = batch.get("M_PATH.info") or ""
            try:
                m_split = int(m_path_info) if str(m_path_info).isdigit() else 0
            except (TypeError, ValueError):
                m_split = 0
            mow_paths_by_map_id = parse_m_path_batch(m_path_joined, m_split)

        # SETTINGS.*
        settings_root: SettingsRoot
        if "SETTINGS" in families:
            settings_joined = join_family_chunks("SETTINGS", batch)
            try:
                import json as _json
                settings_raw = _json.loads(settings_joined)
            except Exception:
                settings_raw = []
            settings_root = parse_settings_batch(settings_raw)
        else:
            settings_root = SettingsRoot(raw=[], by_map_id_canonical={})

        # SCHEDULE.*
        schedule: ScheduleData
        if "SCHEDULE" in families:
            sched_joined = join_family_chunks("SCHEDULE", batch)
            try:
                import json as _json
                sched_raw = _json.loads(sched_joined)
            except Exception:
                sched_raw = {}
            schedule = parse_schedule_batch(sched_raw)
        else:
            schedule = ScheduleData(version=0, slots=())

        # AI_HUMAN — single chunk, JSON-encoded boolean.
        ai_human_enabled: bool | None = None
        if "AI_HUMAN" in families:
            ai_joined = join_family_chunks("AI_HUMAN", batch)
            try:
                import json as _json
                ai_human_enabled = bool(_json.loads(ai_joined))
            except Exception:
                ai_human_enabled = None

        # FBD_NTYPE — list of per-map dicts: [{<map0_dict>}, {<map1_dict>}].
        forbidden_node_types_by_map: dict[int, dict[str, Any]] = {}
        if "FBD_NTYPE" in families:
            fbd_joined = join_family_chunks("FBD_NTYPE", batch)
            try:
                import json as _json
                fbd_list = _json.loads(fbd_joined)
                if isinstance(fbd_list, list):
                    for i, entry in enumerate(fbd_list):
                        if isinstance(entry, dict):
                            forbidden_node_types_by_map[i] = entry
            except Exception:
                pass

        # OTA_INFO — `[status, percent]`.
        ota_status: tuple[int, int] | None = None
        if "OTA_INFO" in families:
            ota_joined = join_family_chunks("OTA_INFO", batch)
            try:
                import json as _json
                ota_list = _json.loads(ota_joined)
                if isinstance(ota_list, list) and len(ota_list) >= 2:
                    ota_status = (int(ota_list[0]), int(ota_list[1]))
            except Exception:
                pass

        # TASKID — int.
        task_id = 0
        if "TASKID" in families:
            tid_joined = join_family_chunks("TASKID", batch)
            try:
                import json as _json
                task_id = int(_json.loads(tid_joined))
            except Exception:
                pass

        # prop.s_* — standalone keys.
        props: dict[str, str] = {}
        if "prop" in families:
            for k in families["prop"]:
                v = batch.get(k)
                if isinstance(v, str):
                    props[k] = v

        # Fast-cadence probes (each a separate cloud call).
        # Errors here don't fail the whole fetch — fields just stay None/empty.
        try:
            locn = self.fetch_locn()
        except Exception:
            locn = None
        try:
            dock = self.fetch_dock() or {}
        except Exception:
            dock = {}
        try:
            mapl = self.fetch_mapl()
        except Exception:
            mapl = None
        try:
            mihis = self.fetch_mihis() or {}
        except Exception:
            mihis = {}

        import time as _time
        return CloudState(
            cfg=cfg,
            maps_by_id=maps_by_id,
            mow_paths_by_map_id=mow_paths_by_map_id,
            settings=settings_root,
            schedule=schedule,
            ai_human_enabled=ai_human_enabled,
            forbidden_node_types_by_map=forbidden_node_types_by_map,
            ota_status=ota_status,
            task_id=task_id,
            props=props,
            locn=locn,
            dock=dock,
            mapl=mapl,
            mihis=mihis,
            fetched_at_unix=int(_time.time()),
        )
```

- [ ] **Step 4: Run, verify the new tests pass**

Run: `python -m pytest tests/protocol/test_fetch_full_cloud_state.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: no regressions; all decoder + dataclass tests still pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py tests/protocol/test_fetch_full_cloud_state.py
git commit -m "feat(cloud-client): fetch_full_cloud_state — single-call orchestrator"
```

---

## Task 7: Coordinator — replace `_refresh_*` with `_refresh_cloud_state`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

This is the structural pivot. Replace 8 separate `_refresh_*` methods with a single `_refresh_cloud_state()` driven by `fetch_full_cloud_state`. Add `coordinator.cloud_state: CloudState | None`. Existing properties (`cached_map_png`, `_cached_map_data`, etc.) become wrappers that read from `cloud_state`.

This task is bigger; split into sub-steps within Task 7.

- [ ] **Step 1: Add `cloud_state` attribute + initial value in `__init__`**

In `coordinator.py` `__init__`, find the existing multi-map cache attrs (added in MM Task 5):

```python
        self._cached_maps_by_id: dict[int, Any] = {}
        self._cached_pngs_by_id: dict[int, bytes] = {}
        ...
```

Just BEFORE that block, add:

```python
        # Unified cloud state — populated by _refresh_cloud_state every 10 min.
        # All cloud-fetched data (maps, settings, schedule, mow paths, etc.)
        # lives here. Properties below maintain backwards-compat for entities
        # that were written against the previous _cached_* attributes.
        self.cloud_state: Any = None  # CloudState | None — actual import deferred
```

Keep the `_cached_*` attrs in place for now (Task 7 step 4 wires them as wrappers).

- [ ] **Step 2: Add `_refresh_cloud_state` method**

Add a new method on the coordinator (place near the existing `_refresh_map` around line 1700). The method runs `fetch_full_cloud_state` in the executor and updates `self.cloud_state`:

```python
    async def _refresh_cloud_state(self) -> None:
        """Single-shot fetch of the full cloud state.

        Called every 10 min via the periodic timer. Replaces the
        previous _refresh_cfg + _refresh_map + _refresh_mihis +
        _refresh_locn + _refresh_dock + _refresh_net + _refresh_dev
        + _poll_slow_properties series.

        On success: self.cloud_state is replaced atomically. Entities
        and consumers re-render via async_update_listeners.
        On failure: self.cloud_state is left unchanged.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            new_state = await self.hass.async_add_executor_job(
                self._cloud.fetch_full_cloud_state
            )
        except Exception as ex:
            LOGGER.warning("[cloud] _refresh_cloud_state raised: %s", ex)
            return
        if new_state is None:
            LOGGER.debug("[cloud] _refresh_cloud_state: fetch returned None")
            return
        self.cloud_state = new_state
        # Mirror legacy attributes that downstream code reads. These
        # become inert once all consumers move to cloud_state directly,
        # but the migration is staged across Task 7+ steps.
        self._cached_maps_by_id = new_state.maps_by_id
        # Re-render PNGs for any map whose md5 changed.
        await self._render_maps_from_cloud_state()
        # Update derived MowerState fields from CFG / SETTINGS / MIHIS.
        self._apply_cloud_state_to_mower_state()
        # Notify entity listeners of the new data.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()
```

Plus the two helpers it calls:

```python
    async def _render_maps_from_cloud_state(self) -> None:
        """Render PNGs for each map in cloud_state.maps_by_id, with md5 dedup.

        For the active map, draws live trail (if a session is in progress).
        For non-active maps, draws base + cloud-history M_PATH overlay.
        """
        if self.cloud_state is None:
            return
        from .map_render import render_base_map, render_with_trail
        active_id = self._active_map_id
        for map_id, map_data in self.cloud_state.maps_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            if prev_md5 == map_data.md5 and map_id in self._cached_pngs_by_id:
                continue
            if map_id == active_id and self.live_map.is_active():
                legs = list(self.live_map.legs)
                mower_pos = (
                    (float(self.data.position_x_m), float(self.data.position_y_m))
                    if self.data.position_x_m is not None
                    and self.data.position_y_m is not None
                    else None
                )
                png = await self.hass.async_add_executor_job(
                    render_with_trail, map_data, legs, None, mower_pos,
                    self._current_mower_heading(),
                )
            else:
                # Non-active map: base map only for now; the cloud-history
                # M_PATH overlay is added in Task 14 (render_base_map gains
                # the m_path kwarg there, and this call site is updated to
                # pass it in the same task).
                png = await self.hass.async_add_executor_job(
                    render_base_map, map_data,
                )
            if png:
                self._cached_pngs_by_id[map_id] = png
                self._last_map_md5_by_id[map_id] = map_data.md5

    def _apply_cloud_state_to_mower_state(self) -> None:
        """Push CFG / MIHIS / SETTINGS-derived fields onto MowerState.

        Mirrors what _refresh_cfg / _refresh_mihis used to do, now
        sourcing from cloud_state. SETTINGS-driven MowerState fields
        added in Task 8.
        """
        if self.cloud_state is None:
            return
        cs = self.cloud_state
        updates: dict[str, Any] = {}
        # MIHIS lifetime totals
        mihis = cs.mihis or {}
        if "area" in mihis:
            updates["total_mowed_area_m2"] = float(mihis["area"])
        if "time" in mihis:
            updates["total_mowing_time_min"] = int(mihis["time"])
        if "count" in mihis:
            updates["mowing_count"] = int(mihis["count"])
        # CFG keys → MowerState (same fields as _refresh_cfg used to set;
        # the existing _refresh_cfg stays for now to do the heavy lifting,
        # see Task 7 step 6).
        if not updates:
            return
        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)
```

- [ ] **Step 3: Schedule `_refresh_cloud_state` in `_async_update_data`**

In `coordinator.py` `_async_update_data` (around line 569), find the section that schedules periodic refresh tasks. Add a new schedule for `_refresh_cloud_state` running every 10 min, AND fire it once immediately after MQTT is up:

```python
            # New unified 10-min cloud-state refresh.
            async def _periodic_cloud_state(_now: Any) -> None:
                await self._refresh_cloud_state()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cloud_state, timedelta(minutes=10)
                )
            )
            await self._refresh_cloud_state()
```

Place this AFTER the `_init_mqtt` call but BEFORE the existing `_refresh_cfg` schedule. The existing `_refresh_*` calls keep running in this task; they're consolidated in step 6.

- [ ] **Step 4: Verify suite**

Run: `python -m pytest -q`
Expected: no regressions. Existing tests use `_cached_maps_by_id` and friends directly; those still work.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): _refresh_cloud_state runs every 10 min, populates CloudState"
```

- [ ] **Step 6: Drop legacy `_refresh_*` methods (separate commit)**

Once `_refresh_cloud_state` is wired, remove these methods (and their schedule timers in `_async_update_data`):
- `_refresh_cfg` — superseded by cloud_state.cfg
- `_refresh_mihis` — superseded by cloud_state.mihis
- `_refresh_dev` — DEV is in CFG response (or skip if not used)
- `_refresh_net` — NET is in cfg.NET (still polled; keep timer)
- `_refresh_map` — superseded by `_render_maps_from_cloud_state`
- `_poll_slow_properties` — kept for now if it does anything beyond cloud_state-derivable fields

Audit: read each `_refresh_*` method body. If everything it sets is now sourced from `cloud_state` via `_apply_cloud_state_to_mower_state`, remove it. If it sets fields not yet in cloud_state, expand `_apply_cloud_state_to_mower_state` to cover them.

KEEP (separate fast-cadence): `_refresh_locn` (60s), `_refresh_dock` (60s), `_refresh_mapl` (on-demand).

Run: `python -m pytest -q`
Expected: pass after each method removal. If a test fails, the removal exposed a real consumer not yet migrated; widen `_apply_cloud_state_to_mower_state` to cover it.

Commit:

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "refactor(coordinator): drop legacy _refresh_* methods, consolidated into cloud_state"
```

---

## Task 8: Add SETTINGS-driven MowerState fields

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (_apply_cloud_state_to_mower_state)

- [ ] **Step 1: Add fields**

In `mower/state.py`, append to the `MowerState` dataclass (preserving slots):

```python
    # ---------------------------------------------------------------
    # SETTINGS-driven (per-active-map mowing behaviour).
    # Populated by _apply_cloud_state_to_mower_state from
    # cloud_state.settings.by_map_id_canonical[active_map_id].
    # All None until the first cloud_state refresh + active_map_id known.
    # ---------------------------------------------------------------
    settings_mowing_height: int | None = None
    settings_mowing_direction: int | None = None
    settings_mowing_direction_mode: int | None = None
    settings_cutter_position: int | None = None
    settings_cutter_position_height: int | None = None
    settings_edge_mowing_num: int | None = None
    settings_edge_mowing_auto: bool | None = None
    settings_edge_mowing_safe: bool | None = None
    settings_edge_mowing_obstacle_avoidance: bool | None = None
    settings_edge_mowing_walk_mode: int | None = None
    settings_obstacle_avoidance_enabled: bool | None = None
    settings_obstacle_avoidance_height: int | None = None
    settings_obstacle_avoidance_distance: int | None = None
    settings_obstacle_avoidance_sensitivity: int | None = None
    settings_obstacle_avoidance_ai: int | None = None
```

- [ ] **Step 2: Wire population in `_apply_cloud_state_to_mower_state`**

In `coordinator.py`, expand `_apply_cloud_state_to_mower_state` (added in Task 7 step 2) to populate the new fields from active-map settings:

```python
        # SETTINGS-driven per-active-map fields.
        active_id = self._active_map_id
        if active_id is not None:
            sm = cs.settings.by_map_id_canonical.get(active_id) or {}
            for src, dst in (
                ("mowingHeight", "settings_mowing_height"),
                ("mowingDirection", "settings_mowing_direction"),
                ("mowingDirectionMode", "settings_mowing_direction_mode"),
                ("cutterPosition", "settings_cutter_position"),
                ("cutterPositionHeight", "settings_cutter_position_height"),
                ("edgeMowingNum", "settings_edge_mowing_num"),
                ("edgeMowingWalkMode", "settings_edge_mowing_walk_mode"),
                ("obstacleAvoidanceHeight", "settings_obstacle_avoidance_height"),
                ("obstacleAvoidanceDistance", "settings_obstacle_avoidance_distance"),
                ("obstacleAvoidanceSensitivity", "settings_obstacle_avoidance_sensitivity"),
                ("obstacleAvoidanceAi", "settings_obstacle_avoidance_ai"),
            ):
                if src in sm:
                    try:
                        updates[dst] = int(sm[src])
                    except (TypeError, ValueError):
                        pass
            for src, dst in (
                ("edgeMowingAuto", "settings_edge_mowing_auto"),
                ("edgeMowingSafe", "settings_edge_mowing_safe"),
                ("edgeMowingObstacleAvoidance", "settings_edge_mowing_obstacle_avoidance"),
                ("obstacleAvoidanceEnabled", "settings_obstacle_avoidance_enabled"),
            ):
                if src in sm:
                    updates[dst] = bool(sm[src])
```

- [ ] **Step 3: Run suite**

Run: `python -m pytest -q`
Expected: pass. Existing tests that build `MowerState()` with kwargs unaffected (all new fields default None).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(state): SETTINGS-driven per-active-map MowerState fields"
```

---

## Task 9: SETTINGS placeholder write helper + first number entity (template)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (add `_write_setting_placeholder`)
- Modify: `custom_components/dreame_a2_mower/number.py`
- Create: `tests/integration/test_settings_number_entities.py`

This task wires the FIRST SETTINGS-driven entity (`number.mowing_height`) end-to-end and adds the placeholder write helper that all 15 entities will share. Tasks 10-12 follow the same pattern with different fields.

- [ ] **Step 1: Add the placeholder write helper to coordinator**

In `coordinator.py`, add near `_apply_cloud_state_to_mower_state`:

```python
    async def _write_setting_placeholder(
        self, *, field: str, value: Any
    ) -> None:
        """Phase-1 placeholder: log a warning, refresh MAPL.

        The cloud's setSettings action wire format isn't yet captured.
        Until it is, write attempts log so the user knows the action
        is observed-only and the entity value reverts to the current
        cloud value on the next refresh.
        """
        LOGGER.info(
            "[settings] write %s=%r ignored (action wire format TBD); "
            "refreshing cloud_state to revert UI to authoritative value",
            field, value,
        )
        await self._refresh_cloud_state()
```

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_settings_number_entities.py`:

```python
"""Tests for SETTINGS-driven number entities (active-follower pattern)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import (
    DreameA2MowingHeightNumber,
)
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)


def _make_coord_with_cloud_state(*, active_map_id: int = 0):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=5)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._cached_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = active_map_id
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[{"mode": 0, "settings": {"0": {"mowingHeight": 5}, "1": {"mowingHeight": 7}}}],
            by_map_id_canonical={
                0: {"mowingHeight": 5},
                1: {"mowingHeight": 7},
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        locn=None, dock={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_mowing_height_reads_from_active_map_state():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    ent = DreameA2MowingHeightNumber(coord)
    assert ent.native_value == 5


def test_mowing_height_changes_when_active_map_changes():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    ent = DreameA2MowingHeightNumber(coord)
    coord._active_map_id = 1
    coord.data = MowerState(settings_mowing_height=7)
    assert ent.native_value == 7


def test_mowing_height_returns_none_when_no_cloud_state():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    coord.data = MowerState()  # field unset
    ent = DreameA2MowingHeightNumber(coord)
    assert ent.native_value is None
```

- [ ] **Step 3: Run, verify it fails**

Run: `python -m pytest tests/integration/test_settings_number_entities.py -v`
Expected: FAIL — `ImportError: cannot import name 'DreameA2MowingHeightNumber'`

- [ ] **Step 4: Implement the entity**

Add to `custom_components/dreame_a2_mower/number.py`:

```python
class DreameA2MowingHeightNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Mowing height (cm) — reads from SETTINGS, active-map follower."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_mowing_height"
    _attr_name = "Mowing height"
    _attr_native_min_value = 2
    _attr_native_max_value = 7
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_settings_mowing_height"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.data.settings_mowing_height
        return float(v) if v is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._write_setting_placeholder(
            field="mowingHeight", value=int(value),
        )
        self.async_write_ha_state()
```

Register it in `async_setup_entry`:

```python
    entities.append(DreameA2MowingHeightNumber(coordinator))
```

(Find the existing entities-list build pattern in number.py and follow it.)

- [ ] **Step 5: Run, verify the new test passes**

Run: `python -m pytest tests/integration/test_settings_number_entities.py -v`
Expected: PASS (3/3)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/number.py tests/integration/test_settings_number_entities.py
git commit -m "feat(settings): mowing_height number entity + write placeholder helper"
```

---

## Task 10: 6 more number entities (same template as Task 9)

**Files:** `number.py`, extend `tests/integration/test_settings_number_entities.py`

Add 6 entities, EACH following the Task 9 code exactly with field/min/max/unit changes:

| Class name | translation_key / name | field | min | max | step | unit |
|---|---|---|---|---|---|---|
| `DreameA2CutterPositionNumber` | settings_cutter_position / Cutter position | settings_cutter_position | 0 | 3 | 1 | (none) |
| `DreameA2CutterPositionHeightNumber` | settings_cutter_position_height / Cutter height | settings_cutter_position_height | 0 | 5 | 1 | cm |
| `DreameA2EdgeMowingNumNumber` | settings_edge_mowing_num / Edge passes | settings_edge_mowing_num | 1 | 3 | 1 | (none) |
| `DreameA2ObstacleAvoidanceHeightNumber` | settings_obstacle_avoidance_height / Obstacle avoidance height | settings_obstacle_avoidance_height | 0 | 30 | 1 | cm |
| `DreameA2ObstacleAvoidanceDistanceNumber` | settings_obstacle_avoidance_distance / Obstacle avoidance distance | settings_obstacle_avoidance_distance | 0 | 30 | 1 | cm |
| `DreameA2ObstacleAvoidanceSensitivityNumber` | settings_obstacle_avoidance_sensitivity / Obstacle avoidance sensitivity | settings_obstacle_avoidance_sensitivity | 1 | 3 | 1 | (none) |

Plus `DreameA2ObstacleAvoidanceAiNumber` for the bitfield (min=0, max=255, step=1, no unit) — bitfield catalog deferred per spec out-of-scope item.

For each: a unit test in the same test file asserting `native_value` reads the right MowerState field.

Field-name → MowerState field mapping uses the same transform as `_apply_cloud_state_to_mower_state` (Task 8).

Commit: `feat(settings): 7 number entities for cutter / edge / obstacle-avoidance fields`

## Task 11: 4 switch entities

**Files:** `switch.py`, `tests/integration/test_settings_switch_entities.py`

Identical template to Task 9 but for switches. Each reads a bool MowerState field and writes via `_write_setting_placeholder`.

| Class name | translation_key / name | field | SETTINGS field |
|---|---|---|---|
| `DreameA2EdgeMowingAutoSwitch` | settings_edge_mowing_auto / Edge mowing auto | settings_edge_mowing_auto | edgeMowingAuto |
| `DreameA2EdgeMowingSafeSwitch` | settings_edge_mowing_safe / Edge mowing safe | settings_edge_mowing_safe | edgeMowingSafe |
| `DreameA2EdgeMowingObstacleAvoidanceSwitch` | settings_edge_mowing_obstacle_avoidance / Edge mowing obstacle avoidance | settings_edge_mowing_obstacle_avoidance | edgeMowingObstacleAvoidance |
| `DreameA2ObstacleAvoidanceEnabledSwitch` | settings_obstacle_avoidance_enabled / Obstacle avoidance enabled | settings_obstacle_avoidance_enabled | obstacleAvoidanceEnabled |

Plus `DreameA2AiHumanDetectionSwitch` reading from `coordinator.cloud_state.ai_human_enabled` (NOT a per-map field; reads from cloud_state directly). Write goes through the same placeholder helper with `field="aiHumanEnabled"` (the actual cloud field name TBD per spec out-of-scope).

Tests (one per switch): `is_on` returns the expected bool; `async_turn_on` / `async_turn_off` call `_write_setting_placeholder`.

Commit: `feat(settings): 4 edge/obstacle switch entities + AI human detection switch`

## Task 12: 3 select entities + sensor entities

**Files:** `select.py`, `sensor.py`, `tests/integration/test_settings_select_entities.py`, `tests/integration/test_cloud_state_sensors.py`

**Selects:**
- `DreameA2MowingDirectionSelect` — options `["0°", "90°", "180°", "270°"]`, reads `settings_mowing_direction`
- `DreameA2MowingDirectionModeSelect` — options `["mode_0", "mode_1", "mode_2"]` (display names TBD per spec — use raw integers for Phase 1)
- `DreameA2EdgeMowingWalkModeSelect` — options `["walk_0", "walk_1"]` (same caveat)

**Sensors:**
- `sensor.dreame_a2_mower_ota_status` — state from `cloud_state.ota_status[0]` (or `unknown` if None); attribute `percent` = `cloud_state.ota_status[1]`
- `sensor.dreame_a2_mower_schedule_count` — state = `len(cloud_state.schedule.slots)`; attribute `slots` = `[{"slot_id": s.slot_id, "name": s.name} for s in slots]`

Tests: each entity's value reads from cloud_state correctly.

Commit: `feat(settings): mowing direction selects + OTA + schedule_count sensors`

## Task 13: Integration test — active-map switching rebinds all SETTINGS entities

**Files:**
- Create: `tests/integration/test_settings_active_follower_rebind.py`

Verify the active-follower contract end-to-end:
1. Build a coordinator with `cloud_state` populated for two maps with different SETTINGS values
2. Set `_active_map_id = 0` and call `_apply_cloud_state_to_mower_state`
3. Assert all 15 `coord.data.settings_*` fields match map 0's values
4. Switch `_active_map_id = 1` and call again
5. Assert all 15 fields now reflect map 1's values

This validates the full chain: SettingsRoot.by_map_id_canonical → _apply_cloud_state_to_mower_state → MowerState fields → entity.native_value.

Commit: `test(settings): active-map rebind integration test`

---

## Task 14: M_PATH overlay rendering

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (update `_render_maps_from_cloud_state` to pass `m_path` kwarg)
- Create: `tests/protocol/test_m_path_render.py`

`render_base_map` gains an optional `m_path: MowPathData | None = None` kwarg. When present, draws each segment as a gray polyline below the boundary/zone/contour layers but above the lawn fill. Use `_cloud_to_px` for the cloud-mm → pixel transform (same helper boundary uses).

ALSO update `_render_maps_from_cloud_state` (added in Task 7) — change the non-active-map render call from:

```python
png = await self.hass.async_add_executor_job(render_base_map, map_data)
```

to:

```python
mp = self.cloud_state.mow_paths_by_map_id.get(map_id)
from functools import partial
png = await self.hass.async_add_executor_job(
    partial(render_base_map, map_data, m_path=mp),
)
```

Test: render a base map with M_PATH overlay using a palette override (gray color = `(160, 160, 160, 255)` per Task 14 default; pass an overridable color so the test can use a distinct value to distinguish nav-path pixels from boundary/zones); verify the rendered PNG has the expected color at sampled segment endpoints.

---

## Task 15: Camera diagnostic attrs + per-map overlay routing

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`

Per-map static cameras now invoke `render_base_map(..., m_path=cloud_state.mow_paths_by_map_id[map_id])` so each shows the cloud-history track. The active follower keeps the live red trail.

Add diagnostic attributes:
- `lawn_mower.dreame_a2_mower`: `task_id` from `cloud_state.task_id`.
- `camera.dreame_a2_mower_map`: `forbidden_node_types` from `cloud_state.forbidden_node_types_by_map[active_map_id]`, `settings_dual_level_diagnostic` (the full `cloud_state.settings.raw` for inspection).

Test by extending the existing camera test scaffolding; assert attributes appear when `cloud_state` is populated.

---

## Task 16: Schedule view dynamic content

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

Replace the markdown placeholder in the Schedule view with a dynamic card driven by `sensor.dreame_a2_mower_schedule_count` attributes (jinja-templated list of slot names + versions). The "BT-only for editing" disclaimer stays as a separate markdown card.

YAML validation: `python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"` should succeed.

---

## Task 17: Startup-availability audit + redundant-code cleanup

**Files:**
- Read: every entity file (sensor.py, binary_sensor.py, switch.py, etc.)
- Modify: `coordinator.py` for any redundant code paths found

Walk each entity. For each that reads a MowerState field, identify which cloud source can populate it. After this PR, fields populated by `_refresh_cloud_state` (which fires once at startup before MQTT pushes arrive) include CFG-derived, MIHIS-derived, and SETTINGS-derived fields.

Specifically check the duplicate-code instances called out in the spec:
- `total_lawn_area_m2` — currently seeded from session_archive AND overwritten by MIHIS. Drop the archive-seed path; rely on cloud_state.mihis.
- `mowing_count` — same pattern.
- `total_mowed_area_m2` — same.

Test: HA restart → entities show real values without waiting for MQTT pushes (verifiable via integration test that constructs a coordinator with cloud_state populated and zero MQTT history; assert sensor.values are non-None).

Document any field that genuinely has no cloud source (e.g. live position from s1p4) so future contributors don't try to seed it.

---

## Task 18: Wipe-and-rebuild migration note

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py` (one-line warning at setup)

Add an `LOGGER.warning(...)` at integration setup announcing that this version (1.0.0bN — see Task 19) wiped existing local archive state on first launch (per spec). Document that probe-log replay rebuilds.

(No actual data deletion code — the archive is wiped because the SCHEMA changed and old entries are skipped, per the existing legacy-skip path. The warning is just informational.)

---

## Task 19: Version bump + release

**Files:**
- Modify: `manifest.json` via `tools/release.sh`

Run: `tools/release.sh --notes-file /tmp/release_b1_notes.md` (or 1.0.0aXX continuing the existing scheme — match the project convention).

Release notes file:
```
## v1.0.0bN — Cloud Discovery Integration

Major architectural refactor + new SETTINGS-driven feature set.

ARCHITECTURE
- New `CloudState` frozen dataclass replaces scattered `_cached_*` attrs
- Single `_refresh_cloud_state()` consolidates 8 previous _refresh_*
- `get_batch_device_datas([])` is now the canonical 10-min fetch path

NEW FEATURES
- 15 SETTINGS-driven per-map active-follower entities (mowing direction
  is now writable in HA — previously thought BT-only)
- M_PATH cloud-history rendered as gray overlay on per-map cameras
- SCHEDULE view shows actual cloud-side schedule slots
- New diagnostic attributes for forbidden-area types, task_id,
  SETTINGS dual-level structure

BREAKING
- Existing local session archive wiped on first install (probe-log
  replay rebuilds)
- 8 internal `_refresh_*` methods consolidated; entity contracts
  preserved

DEFERRED (filed as TODOs)
- SETTINGS dual-level semantic investigation
- SETTINGS write wire format capture
- SCHEDULE blob decode
- AI_HUMAN write capability
- nav_paths overlay rendering
```

---

## Task 20: Self-review + final test run

**Files:** none (verification only)

- [ ] **Step 1: Re-read the spec**

Verify each section in `docs/superpowers/specs/2026-05-08-cloud-discovery-integration-design.md` is covered by a task.

- [ ] **Step 2: Run `pytest -q`**

Expected: 750+ passes (added ~30 from this plan), 0 failures.

- [ ] **Step 3: Run `tools/release.sh`** if not done in Task 19.

- [ ] **Step 4: Done. Pull via HACS, restart HA, verify on the running instance:**

1. New entities visible: 15 SETTINGS-driven entries, OTA + schedule sensors
2. Schedule view shows the 2 actual slots
3. Per-map cameras show gray cloud-history overlay
4. `select.dreame_a2_mower_active_map` switches as before
5. Dashboard layout intact
