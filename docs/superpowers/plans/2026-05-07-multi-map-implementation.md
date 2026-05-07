# Multi-Map Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the integration to fetch, parse, cache, and render multiple cloud-side maps. Active-map awareness drives selectors; replay rendering follows session.map_id; per-map static cameras provide observability into inactive maps. Wipe-and-rebuild for old archives.

**Architecture:** `fetch_map` splits MAP.0..27 via MAP.info into a `dict[map_id, raw_dict]`; `parse_cloud_maps` returns `dict[map_id, MapData]`. Coordinator caches both `_cached_maps_by_id` and `_cached_pngs_by_id`; `_active_map_id` (from MAPL polling) and `_render_map_id` (replay-aware) drive the camera surface. Existing entities (camera, zone/spot/edge selectors, replay picker) auto-pivot via property accessors. New entities: `select.active_map` (read-only Phase 1) and per-map static cameras.

**Tech Stack:** Python 3.13+, Home Assistant Core, pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-05-07-multi-map-design.md`

---

## File Structure

| Purpose | Path | Action |
|---|---|---|
| `MapData` dataclass + `NavPath` dataclass + `parse_cloud_maps` | `custom_components/dreame_a2_mower/map_decoder.py` | Modify |
| `fetch_map` reshape (split via MAP.info, return dict) | `custom_components/dreame_a2_mower/cloud_client.py` | Modify |
| Coordinator caches + active/render map IDs + MAPL polling | `custom_components/dreame_a2_mower/coordinator.py` | Modify |
| `select.active_map` entity | `custom_components/dreame_a2_mower/select.py` | Modify |
| Per-map static camera entities | `custom_components/dreame_a2_mower/camera.py` | Modify |
| `MapImageView` accepts `?map_id=N` query | `custom_components/dreame_a2_mower/camera.py` | Modify |
| Replay-picker labels with `[Map N]` prefix; render via session.map_id | `custom_components/dreame_a2_mower/select.py` and `coordinator.py` | Modify |
| `ArchivedSession.map_id` required field | `custom_components/dreame_a2_mower/archive/session.py` | Modify |
| Multi-map test fixture (today's MAPL=2-row response) | `tests/protocol/fixtures/multi_map_response.json` | Create |
| `parse_cloud_maps` tests | `tests/protocol/test_multi_map_decoder.py` | Create |
| `nav_paths` decoding tests | `tests/protocol/test_nav_paths.py` | Create |
| Active-map routing tests (MAPL → `_active_map_id`) | `tests/integration/test_active_map_routing.py` | Create |
| Cross-map replay test | `tests/integration/test_replay_cross_map.py` | Create |
| Dashboard updates: Mower view header, Maps view | `dashboards/mower/dashboard.yaml` | Modify |
| User-facing multi-map docs | `docs/multi-map.md` | Create |
| README link | `README.md` | Modify |
| TODO entries (writability, lidar-per-map, paths overlay) | `docs/TODO.md` | Modify |
| Version bump | `custom_components/dreame_a2_mower/manifest.json` | Modify |

---

## Task 1: Add `NavPath` dataclass + `nav_paths` field on `MapData`

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_decoder.py`
- Test: `tests/protocol/test_nav_paths.py`

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_nav_paths.py`:

```python
"""Tests for the cloud `paths` key (gray nav-paths between maps)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.map_decoder import (
    MapData,
    NavPath,
    parse_cloud_map,
)


def _make_minimal_cloud_response_with_paths():
    """Minimal cloud response with a single boundary + one nav path."""
    return {
        "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
        "mowingAreas": {},
        "paths": {
            "0": {
                "path": [
                    {"x": 1000, "y": 1000},
                    {"x": 2000, "y": 1500},
                    {"x": 3000, "y": 2000},
                ],
                "type": 0,
            },
        },
        "totalArea": 100,
    }


def test_parse_cloud_map_decodes_nav_paths():
    """A `paths` entry produces a NavPath with cloud-mm coords intact."""
    response = _make_minimal_cloud_response_with_paths()
    map_data = parse_cloud_map(response)

    assert map_data is not None
    assert len(map_data.nav_paths) == 1
    nav = map_data.nav_paths[0]
    assert isinstance(nav, NavPath)
    assert nav.path_id == 0
    assert nav.path_type == 0
    assert nav.path == ((1000.0, 1000.0), (2000.0, 1500.0), (3000.0, 2000.0))


def test_parse_cloud_map_with_no_paths_key_yields_empty_tuple():
    """No `paths` key → `nav_paths == ()`, not None."""
    response = {
        "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
        "mowingAreas": {},
        "totalArea": 100,
    }
    map_data = parse_cloud_map(response)
    assert map_data is not None
    assert map_data.nav_paths == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/protocol/test_nav_paths.py -v`
Expected: FAIL — `ImportError: cannot import name 'NavPath' from ...`

- [ ] **Step 3: Add `NavPath` dataclass and field**

In `custom_components/dreame_a2_mower/map_decoder.py`, after the `MaintenancePoint` dataclass (~line 122), add:

```python
@dataclass(frozen=True, slots=True)
class NavPath:
    """A connecting "navigation path" rendered as a gray polyline in the
    Dreame app. Connects two map regions (e.g. dock area to a remote
    mowing zone). Decoded from the cloud `paths` key.

    `path_type` semantics undecoded (observed `0` in 2026-05-07 capture).
    """

    path_id: int
    path: tuple[tuple[float, float], ...]  # cloud-frame mm
    path_type: int = 0
```

In the same file, locate the `MapData` dataclass (~line 126) and add a new field at the end (after `total_area_m2`):

```python
    nav_paths: tuple[NavPath, ...] = ()
```

(Adding with a default `()` so the field is optional — existing test fixtures that build MapData manually keep working.)

In the same file's `parse_cloud_map` function, after the `maintenance_points` decoding loop (around line 460-470, find `clean_raw = cloud_response.get("cleanPoints", {})` block), add a new decoding block:

```python
    # Decode the `paths` key — gray nav-paths between map regions.
    # Legacy upstream parses these as `MowerPath`; we use `NavPath`.
    nav_paths_raw = cloud_response.get("paths", {})
    nav_paths_out: list[NavPath] = []
    if isinstance(nav_paths_raw, dict):
        for path_id_str, pdata in nav_paths_raw.items():
            try:
                path_id_int = int(path_id_str)
            except (TypeError, ValueError):
                continue
            if not isinstance(pdata, dict):
                continue
            raw_pts = pdata.get("path", [])
            if not isinstance(raw_pts, list):
                continue
            pts = tuple(
                (float(p["x"]), float(p["y"]))
                for p in raw_pts
                if isinstance(p, dict) and "x" in p and "y" in p
            )
            if pts:
                nav_paths_out.append(
                    NavPath(
                        path_id=path_id_int,
                        path=pts,
                        path_type=int(pdata.get("type", 0) or 0),
                    )
                )
```

Then in the `MapData(...)` constructor call at the end of `parse_cloud_map`, add `nav_paths=tuple(nav_paths_out),` to the kwargs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/protocol/test_nav_paths.py -v`
Expected: BOTH PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py tests/protocol/test_nav_paths.py
git commit -m "feat(map-decoder): NavPath dataclass + nav_paths field on MapData"
```

---

## Task 2: Add `map_id` and `name` fields on `MapData`

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_decoder.py`

- [ ] **Step 1: Add fields with defaults**

In `MapData` (after `nav_paths` field added in Task 1), add:

```python
    map_id: int = 0
    name: str | None = None
```

Default `0` lets single-map fixtures continue to work.

- [ ] **Step 2: Stamp values in `parse_cloud_map`**

In the `parse_cloud_map` function, before the `MapData(...)` constructor call, add:

```python
    # Multi-map metadata: present in cloud responses with mapIndex; absent
    # in older single-map fixtures (default to 0 / None).
    map_index = cloud_response.get("mapIndex")
    if map_index is None:
        map_index = 0
    map_name = cloud_response.get("name")
    if map_name is not None:
        map_name = str(map_name)
```

In the `MapData(...)` constructor call, add `map_id=int(map_index),` and `name=map_name,`.

- [ ] **Step 3: Run the existing decoder tests**

Run: `python -m pytest tests/protocol/test_cloud_map_geom.py tests/protocol/test_nav_paths.py -v`
Expected: ALL PASS (existing tests use default `map_id=0`, `name=None`; nav_paths test still passes).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py
git commit -m "feat(map-decoder): MapData carries map_id + name from cloud mapIndex/name"
```

---

## Task 3: Add `parse_cloud_maps` (returns dict by map_id)

**Files:**
- Create: `tests/protocol/fixtures/multi_map_response.json`
- Create: `tests/protocol/test_multi_map_decoder.py`
- Modify: `custom_components/dreame_a2_mower/map_decoder.py`

- [ ] **Step 1: Create the fixture file**

Create `tests/protocol/fixtures/multi_map_response.json` with two minimal maps:

```json
{
  "by_id": {
    "0": {
      "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
      "mowingAreas": {},
      "totalArea": 100,
      "mapIndex": 0,
      "name": "Map 1",
      "paths": {}
    },
    "1": {
      "boundary": {"x1": 20000, "y1": 0, "x2": 30000, "y2": 10000},
      "mowingAreas": {},
      "totalArea": 80,
      "mapIndex": 1,
      "name": "Map 2",
      "paths": {
        "0": {
          "path": [{"x": 5000, "y": 5000}, {"x": 25000, "y": 5000}],
          "type": 0
        }
      }
    }
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/protocol/test_multi_map_decoder.py`:

```python
"""Tests for parse_cloud_maps (multi-map cloud response)."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.map_decoder import (
    MapData,
    parse_cloud_maps,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multi_map_response.json"


def test_parse_cloud_maps_returns_dict_by_id():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert set(parsed.keys()) == {0, 1}
    assert all(isinstance(m, MapData) for m in parsed.values())


def test_parse_cloud_maps_stamps_map_id_and_name():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert parsed[0].map_id == 0
    assert parsed[0].name == "Map 1"
    assert parsed[1].map_id == 1
    assert parsed[1].name == "Map 2"


def test_parse_cloud_maps_decodes_nav_paths_per_map():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert parsed[0].nav_paths == ()  # Map 1 has no paths
    assert len(parsed[1].nav_paths) == 1  # Map 2 has one connecting path
    assert parsed[1].nav_paths[0].path_id == 0


def test_parse_cloud_maps_skips_invalid_entries():
    """Entries that fail parse_cloud_map are dropped, not raised."""
    by_id = {
        0: {"boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000}, "mowingAreas": {}, "totalArea": 100, "mapIndex": 0},
        1: {"this_is_not_a_valid_map_response": True},  # bad
    }

    parsed = parse_cloud_maps(by_id)

    assert 0 in parsed
    assert 1 not in parsed
```

- [ ] **Step 3: Run the tests, verify they fail**

Run: `python -m pytest tests/protocol/test_multi_map_decoder.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_cloud_maps' ...`

- [ ] **Step 4: Add `parse_cloud_maps`**

In `custom_components/dreame_a2_mower/map_decoder.py`, immediately after `parse_cloud_map` function, add:

```python
def parse_cloud_maps(by_id: dict[int, dict[str, Any]]) -> dict[int, MapData]:
    """Parse a multi-map cloud response into MapData entries by map_id.

    `by_id` is the splitter output from `cloud_client.fetch_map` —
    a dict keyed by map index, where each value is the raw cloud
    response dict for that map.

    Entries that fail `parse_cloud_map` are silently dropped; partial
    results beat raising on a single bad map.
    """
    result: dict[int, MapData] = {}
    for map_id, raw in by_id.items():
        if not isinstance(raw, dict):
            continue
        decoded = parse_cloud_map(raw)
        if decoded is None:
            continue
        result[int(map_id)] = decoded
    return result
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `python -m pytest tests/protocol/test_multi_map_decoder.py -v`
Expected: ALL 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py tests/protocol/fixtures/multi_map_response.json tests/protocol/test_multi_map_decoder.py
git commit -m "feat(map-decoder): parse_cloud_maps returns dict[map_id, MapData]"
```

---

## Task 4: Reshape `cloud_client.fetch_map` to split by MAP.info

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py`
- Test: `tests/protocol/test_cloud_client_fetch_map.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_cloud_client_fetch_map.py`:

```python
"""Tests for cloud_client.fetch_map multi-map split via MAP.info."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client(batch_response):
    client = object.__new__(DreameA2CloudClient)
    client.get_batch_device_datas = MagicMock(return_value=batch_response)
    return client


def _build_batch(map_jsons: list[dict]) -> dict:
    """Encode a list of map JSON dicts as if they were the cloud's
    MAP.0..MAP.27 batch reply, with MAP.info giving the split point.
    """
    parts = [json.dumps([m]) for m in map_jsons]  # cloud wraps each in []
    full = "".join(parts)
    info = str(len(parts[0])) if len(parts) > 1 else "0"
    out = {f"MAP.{i}": "" for i in range(28)}
    # Pack the full string into MAP.0; other slots empty (legal).
    out["MAP.0"] = full
    out["MAP.info"] = info
    return out


def test_fetch_map_returns_dict_by_id_for_two_maps():
    map0 = {"boundary": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "mowingAreas": {}, "mapIndex": 0, "name": "Map 1", "totalArea": 100}
    map1 = {"boundary": {"x1": 20, "y1": 0, "x2": 30, "y2": 10}, "mowingAreas": {}, "mapIndex": 1, "name": "Map 2", "totalArea": 80}
    client = _make_client(_build_batch([map0, map1]))

    result = client.fetch_map()

    assert isinstance(result, dict)
    assert set(result.keys()) == {0, 1}
    assert result[0]["name"] == "Map 1"
    assert result[1]["name"] == "Map 2"


def test_fetch_map_returns_dict_with_single_entry_for_one_map():
    map0 = {"boundary": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "mowingAreas": {}, "mapIndex": 0, "name": "Map 1", "totalArea": 100}
    client = _make_client(_build_batch([map0]))

    result = client.fetch_map()

    assert isinstance(result, dict)
    assert set(result.keys()) == {0}
    assert result[0]["name"] == "Map 1"


def test_fetch_map_returns_none_on_empty_batch():
    client = _make_client({})
    assert client.fetch_map() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/protocol/test_cloud_client_fetch_map.py -v`
Expected: FAIL — current `fetch_map` returns a single dict, not keyed by map_id.

- [ ] **Step 3: Reshape `fetch_map`**

In `custom_components/dreame_a2_mower/cloud_client.py`, replace the entire `fetch_map` method body with:

```python
    def fetch_map(self) -> "dict[int, dict[str, Any]] | None":
        """Fetch the cloud MAP.* batch and return per-map dicts keyed by map_id.

        Calls `get_batch_device_datas` with keys `MAP.0..MAP.27` plus
        `MAP.info`. Reassembles the 28 chunks; uses `MAP.info` as a byte
        offset to split the joined string when multiple maps are present.
        Each segment is a JSON list `[{...}]` whose inner dict has a
        `mapIndex` field. Returns `{mapIndex: dict, ...}`.

        Returns None on any irrecoverable failure (network error, empty
        batch, every segment malformed). Partial results beat None when
        at least one map decodes.
        """
        try:
            map_keys = [f"MAP.{i}" for i in range(28)] + ["MAP.info"]
            batch = self.get_batch_device_datas(map_keys)
        except Exception as ex:
            _LOGGER.warning("fetch_map: get_batch_device_datas error: %s", ex)
            return None

        if not batch:
            _LOGGER.debug("fetch_map: empty cloud response")
            return None

        parts = [batch.get(f"MAP.{i}", "") or "" for i in range(28)]
        full = "".join(parts)
        if not full:
            _LOGGER.debug("fetch_map: all MAP.* keys empty")
            return None

        info_raw = batch.get("MAP.info", "") or ""
        try:
            split_pos = int(info_raw) if info_raw else 0
        except (TypeError, ValueError):
            split_pos = 0

        if split_pos > 0 and split_pos < len(full):
            segments = [full[:split_pos], full[split_pos:]]
        else:
            segments = [full]

        result: dict[int, dict[str, Any]] = {}
        import json as _json
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            try:
                parsed = _json.loads(seg)
            except (ValueError, _json.JSONDecodeError):
                continue
            # Cloud wraps each map as a 1-element list.
            entries = parsed if isinstance(parsed, list) else [parsed]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if "boundary" not in entry and "mowingAreas" not in entry:
                    continue
                idx = entry.get("mapIndex", 0)
                try:
                    idx_int = int(idx)
                except (TypeError, ValueError):
                    idx_int = 0
                result[idx_int] = entry

        if not result:
            _LOGGER.debug("fetch_map: no usable map segments")
            return None

        _LOGGER.debug("fetch_map: decoded %d map(s) by id", len(result))
        return result
```

- [ ] **Step 4: Run all relevant tests**

Run: `python -m pytest tests/protocol/test_cloud_client_fetch_map.py -v`
Expected: ALL 3 PASS.

Run the broader suite (some integration tests mock `fetch_map`; they may need updating):
Run: `python -m pytest -q`
Expected: failures only in tests that mock the old single-dict return shape — note them; they get fixed in Task 5.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py tests/protocol/test_cloud_client_fetch_map.py
git commit -m "feat(cloud-client): fetch_map returns dict[map_id, dict] split via MAP.info"
```

---

## Task 5: Coordinator multi-map cache + properties

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

This task replaces single-map state with multi-map state and adds backwards-compat properties so existing entity code paths keep working.

- [ ] **Step 1: Replace cache attrs in `__init__`**

In `coordinator.py` `__init__`, find and replace the existing single-map state lines (around line 562-566):

```python
        # Base-map PNG cache — populated by _refresh_map every 6 hours.
        self.cached_map_png: bytes | None = None
        self._last_map_md5: str | None = None
        # v1.0.0a18: cache parsed MapData so live-trail re-renders don't
        # need to re-fetch the cloud map. Populated by _refresh_map.
        self._cached_map_data: Any = None
```

with:

```python
        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        self._cached_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
        # Active map (from MAPL polling). None until first MAPL response.
        self._active_map_id: int | None = None
        # Currently rendered map (defaults to active; transient override
        # during replay-session pick to the session's map_id).
        self._render_map_id: int | None = None
```

- [ ] **Step 2: Add property accessors at the end of `__init__` block (before the F5.7.1 section)**

In `coordinator.py`, locate the end of `__init__` method. Just BEFORE the `async def _async_update_data` at line 569, add new property methods on the class:

```python
    @property
    def cached_map_png(self) -> bytes | None:
        """Backwards-compat: PNG of the currently-rendered map.

        Reads `_cached_pngs_by_id[_render_map_id]` (or `_active_map_id`
        when render isn't overridden). Returns None when no map is
        cached or the active/render id isn't in the cache yet.
        """
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            # Fall back to lowest-numbered map_id when we have any cached
            # but haven't seen MAPL yet.
            if self._cached_pngs_by_id:
                target = min(self._cached_pngs_by_id.keys())
            else:
                return None
        return self._cached_pngs_by_id.get(target)

    @cached_map_png.setter
    def cached_map_png(self, png: bytes | None) -> None:
        """Backwards-compat setter: writes to the currently-rendered map's slot.

        Used by replay_session and _rerender_live_trail. The target id
        is `_render_map_id` (replay) or `_active_map_id` (live).
        """
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = min(self._cached_maps_by_id.keys()) if self._cached_maps_by_id else 0
        if png is None:
            self._cached_pngs_by_id.pop(target, None)
        else:
            self._cached_pngs_by_id[target] = png

    @property
    def _cached_map_data(self) -> Any:
        """Backwards-compat: MapData of the currently-rendered map."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            if self._cached_maps_by_id:
                target = min(self._cached_maps_by_id.keys())
            else:
                return None
        return self._cached_maps_by_id.get(target)

    @_cached_map_data.setter
    def _cached_map_data(self, value: Any) -> None:
        """Backwards-compat setter: writes to the currently-rendered map's slot."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = getattr(value, "map_id", 0) if value is not None else 0
        if value is None:
            self._cached_maps_by_id.pop(target, None)
        else:
            self._cached_maps_by_id[target] = value

    @property
    def _last_map_md5(self) -> str | None:
        """Backwards-compat: md5 of the currently-rendered map."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            return None
        return self._last_map_md5_by_id.get(target)

    @_last_map_md5.setter
    def _last_map_md5(self, value: str | None) -> None:
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = 0
        if value is None:
            self._last_map_md5_by_id.pop(target, None)
        else:
            self._last_map_md5_by_id[target] = value
```

- [ ] **Step 3: Verify the file compiles**

Run: `python -m py_compile custom_components/dreame_a2_mower/coordinator.py`
Expected: no output (success).

- [ ] **Step 4: Run the test suite**

Run: `python -m pytest -q`
Expected: tests using the old `_cached_map_data = MagicMock(...)` patterns may fail because writing through the property is now slot-aware. If any test fails: extend the failing fixture to set `_active_map_id = 0` AND populate `_cached_maps_by_id[0]` directly.

Specifically, `tests/integration/test_coordinator.py` `_make_coordinator_for_session_tests()` (around line 543) likely needs:

```python
    coord._cached_maps_by_id = {}
    coord._cached_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    coord._render_map_id = None
```

immediately after the existing field initializations.

If the suite is now green, proceed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git commit -m "feat(coordinator): multi-map cache + backwards-compat property accessors"
```

---

## Task 6: `_refresh_map` populates all maps

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Refactor `_refresh_map`**

In `coordinator.py`, locate `_refresh_map` (around line 1629). Replace its body — keep the same outer signature, but iterate the multi-map result. The new body:

```python
    async def _refresh_map(self) -> None:
        """Fetch the cloud MAP.* batch, parse all maps, and re-render
        per-map base-map PNGs. Updates `_cached_maps_by_id` and
        `_cached_pngs_by_id`.

        Per-map md5 dedup: if a map's md5 hasn't changed since the last
        fetch, skip re-rendering that map.

        Live-trail re-render path uses _cached_maps_by_id[_active_map_id]
        as the base map.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return

        from .map_decoder import parse_cloud_maps
        from .map_render import render_base_map, render_with_trail

        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return

        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _refresh_map: parse_cloud_maps returned empty")
            return

        # Update the MapData cache.
        self._cached_maps_by_id = parsed_by_id

        # Determine the live-trail map (active) and the maps that need PNG rerender.
        active_id = self._active_map_id
        for map_id, map_data in parsed_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            if prev_md5 == map_data.md5 and map_id in self._cached_pngs_by_id:
                continue  # dedup hit
            self._last_map_md5_by_id[map_id] = map_data.md5

            # Live trail belongs only on the active map; other maps render
            # the static base-map.
            if map_id == active_id and self.live_map.is_active():
                legs = list(self.live_map.legs)
                mower_pos = (
                    (float(self.data.position_x_m), float(self.data.position_y_m))
                    if self.data.position_x_m is not None and self.data.position_y_m is not None
                    else None
                )
                png = await self.hass.async_add_executor_job(
                    render_with_trail, map_data, legs, None, mower_pos, self._current_mower_heading()
                )
            else:
                png = await self.hass.async_add_executor_job(render_base_map, map_data)

            if png:
                self._cached_pngs_by_id[map_id] = png

        # Notify listeners (camera entity) the cached PNGs may have changed.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()
```

- [ ] **Step 2: Verify the file compiles + suite still green**

Run: `python -m py_compile custom_components/dreame_a2_mower/coordinator.py && python -m pytest -q 2>&1 | tail -5`
Expected: 0 failures (the property accessors keep external callers happy).

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): _refresh_map iterates all maps, per-map md5 dedup"
```

---

## Task 7: MAPL polling sets `_active_map_id`

**Files:**
- Test: `tests/integration/test_active_map_routing.py` (create)
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_active_map_routing.py`:

```python
"""Tests for _active_map_id derivation from cfg_individual.MAPL."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord():
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._cached_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    return coord


def test_apply_mapl_single_active_row():
    coord = _make_coord()
    # MAPL with map_id=0 active.
    coord._apply_mapl([[0, 1, 1, 1, 0]])
    assert coord._active_map_id == 0


def test_apply_mapl_two_rows_second_active():
    coord = _make_coord()
    coord._apply_mapl([[0, 0, 1, 1, 0], [1, 1, 1, 1, 0]])
    assert coord._active_map_id == 1


def test_apply_mapl_no_active_row_keeps_previous():
    coord = _make_coord()
    coord._active_map_id = 0
    # No row with col 1 == 1 (transient state).
    coord._apply_mapl([[0, 0, 1, 1, 0], [1, 0, 1, 1, 0]])
    assert coord._active_map_id == 0


def test_apply_mapl_invalid_payload_no_change():
    coord = _make_coord()
    coord._active_map_id = 0
    coord._apply_mapl("not-a-list")
    assert coord._active_map_id == 0
```

- [ ] **Step 2: Run, verify they fail**

Run: `python -m pytest tests/integration/test_active_map_routing.py -v`
Expected: FAIL — `AttributeError: ... '_apply_mapl'`.

- [ ] **Step 3: Add `_apply_mapl` and call it from `_refresh_cfg`**

In `coordinator.py`, locate `_refresh_cfg` (around line 838). Just BEFORE the existing `_refresh_cfg` method, add:

```python
    def _apply_mapl(self, mapl: Any) -> None:
        """Update _active_map_id from a MAPL response.

        MAPL is a list of rows, each row is `[map_id, is_active, ?, ?, ?]`.
        Sets `_active_map_id` to the row whose col 1 == 1. If no row
        matches (transient), keep the previous value. Bad payloads are
        ignored.
        """
        if not isinstance(mapl, list):
            return
        for row in mapl:
            if not isinstance(row, list) or len(row) < 2:
                continue
            try:
                if int(row[1]) == 1:
                    self._active_map_id = int(row[0])
                    return
            except (TypeError, ValueError):
                continue
        # No row matched; keep previous _active_map_id (do nothing).
```

In `_refresh_cfg`, after the existing CFG decode block, add a small block that polls MAPL via cfg_individual:

```python
        # Poll MAPL for active-map detection.
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_cfg_individual, "MAPL"
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_cfg: MAPL poll raised: %s", ex)
            mapl_resp = None
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
```

(This relies on `_cloud.fetch_cfg_individual` being available. If the method name is different, search `cloud_client.py` for the existing single-key fetch helper and use that name.)

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/integration/test_active_map_routing.py -v`
Expected: ALL 4 PASS.

Run the full suite:
Run: `python -m pytest -q`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_active_map_routing.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): _apply_mapl sets _active_map_id from MAPL polling"
```

---

## Task 8: Re-poll MAPL on `mowing_started`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Hook into the mowing_started fire site**

In `coordinator.py` `_on_state_update`, locate the block that fires `EVENT_TYPE_MOWING_STARTED` (added in a91 lifecycle PR). Right after `self._fire_lifecycle(EVENT_TYPE_MOWING_STARTED, {...})`, add:

```python
            # Re-poll MAPL so the live trail lands on the firmware's
            # current active map, even if the last 10-min CFG poll was
            # before the user switched maps.
            self.hass.async_create_task(self._refresh_mapl())
```

Also in `coordinator.py`, add a small helper method (place it near `_apply_mapl` from Task 7):

```python
    async def _refresh_mapl(self) -> None:
        """Re-poll MAPL only (no full CFG refresh)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_cfg_individual, "MAPL"
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_mapl raised: %s", ex)
            return
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
```

- [ ] **Step 2: Verify the suite still passes**

Run: `python -m pytest -q`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): re-poll MAPL on mowing_started for fresh active-map"
```

---

## Task 8b: Re-poll MAPL on `s1p50` empty-ping (per-swap trigger)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

Background: `s1p50={}` (the firmware's "something changed, consider
re-fetching" empty-ping) fires on every map-swap (confirmed
2026-05-07 across multiple swaps: 21:52:06 and 21:52:36, one ping per
swap). Subscribing to it gives sub-second active-map detection latency
instead of waiting up to 10 min for the next CFG poll.

`s2p50 op=200` (the apk-documented `changeMap` echo) is conditional
— fires on some swaps but not others — so it's NOT a reliable
per-swap signal. Use s1p50 instead.

- [ ] **Step 1: Hook MAPL re-poll into the s1p50 push handler**

In `coordinator.py`, locate `handle_property_push` (around line 2820)
or the equivalent dispatch for `properties_changed` MQTT messages.
Find where (siid=1, piid=50) is recognised. Today's code logs and
suppresses; we add a side-effect.

Just BEFORE the `apply_property_to_state` call (or in the suppress
branch where (1,50) is filtered), add:

```python
        # s1p50 is the firmware's "something changed" empty-ping. For
        # multi-map, every map-swap fires it (confirmed 2026-05-07).
        # Treat it as a MAPL-repoll trigger so active-map detection has
        # sub-second latency instead of waiting for the next 10-min
        # CFG poll. Other s1p50 cases (zone-edits, maintenance saves)
        # benefit from the cheap re-poll too — MAPL is a ~100 ms RPC.
        if (int(siid), int(piid)) == (1, 50):
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self._refresh_mapl())
            )
```

The `_refresh_mapl` helper was added in Task 8. The
`call_soon_threadsafe` hop is necessary because `handle_property_push`
runs on paho's background thread; `async_create_task` requires the
event loop.

- [ ] **Step 2: Verify the suite still passes**

Run: `python -m pytest -q`
Expected: 0 failures (the new code path doesn't fire in any unit test
since they don't push s1p50 through `handle_property_push`).

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): s1p50 ping triggers MAPL re-poll (sub-second active-map)"
```

---

## Task 9: `select.dreame_a2_mower_active_map` (read-only)

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py`

- [ ] **Step 1: Add the entity**

In `custom_components/dreame_a2_mower/select.py`, near the other select entity classes, add:

```python
class DreameA2ActiveMapSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Active-map selector. Read-only Phase 1 — option-select is observed
    only; the firmware's MAPL is the source of truth.

    Future: writable once the cloud "set active map" action wire format
    is captured (probe procedure in docs/research/g2408-capture-procedures.md).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "active_map"
    _attr_name = "Active map"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_active_map"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def options(self) -> list[str]:
        return [
            self._label_for(map_id, m)
            for map_id, m in sorted(self.coordinator._cached_maps_by_id.items())
        ]

    @property
    def current_option(self) -> str | None:
        active = self.coordinator._active_map_id
        if active is None:
            return None
        m = self.coordinator._cached_maps_by_id.get(active)
        if m is None:
            return None
        return self._label_for(active, m)

    @staticmethod
    def _label_for(map_id: int, map_data: Any) -> str:
        name = getattr(map_data, "name", None)
        if name:
            return str(name)
        return f"Map {map_id + 1}"

    async def async_select_option(self, option: str) -> None:
        LOGGER.info(
            "select.active_map: option=%r is observed-only; cloud write "
            "action TBD. Resolving from MAPL re-poll.",
            option,
        )
        await self.coordinator._refresh_mapl()
        self.async_write_ha_state()
```

- [ ] **Step 2: Register the entity in `async_setup_entry`**

In the same file, find `async_setup_entry`. Append to the `entities` list:

```python
    entities.append(DreameA2ActiveMapSelect(coordinator))
```

- [ ] **Step 3: Run the suite**

Run: `python -m pytest -q`
Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py
git commit -m "feat(select): active_map read-only selector"
```

---

## Task 10: Per-map static cameras

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`

- [ ] **Step 1: Add the per-map camera class**

In `custom_components/dreame_a2_mower/camera.py`, near the existing camera entity classes (after `DreameA2MowerCamera`), add:

```python
class DreameA2PerMapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Static base-map snapshot for a single map_id.

    Read-only — no live trail overlay (those follow the active map via
    DreameA2MowerCamera). Used by the bundled "Maps" dashboard view to
    show all maps side-by-side.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "map_static"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._map_id = map_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_map_{map_id}"
        self._attr_name = f"Map {map_id + 1}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator._cached_pngs_by_id.get(self._map_id)

    @property
    def entity_picture(self) -> str | None:
        png = self.coordinator._cached_pngs_by_id.get(self._map_id)
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?map_id={self._map_id}&v={v}"
```

- [ ] **Step 2: Update MapImageView to honour `?map_id=N`**

In the same file, locate `MapImageView.get` (around line 285). Replace the body with:

```python
    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")

        map_id_raw = request.query.get("map_id")
        if map_id_raw is not None:
            try:
                map_id = int(map_id_raw)
            except (TypeError, ValueError):
                return web.Response(status=400, text="Bad map_id")
            png = coordinator._cached_pngs_by_id.get(map_id)
        else:
            # Active map (with replay-render override applied).
            png = coordinator.cached_map_png

        if not png:
            return web.Response(status=404, text="No map rendered yet")

        return web.Response(
            body=png,
            content_type="image/png",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
```

- [ ] **Step 3: Register per-map cameras in `async_setup_entry`**

In the same file, find `async_setup_entry`. Where the camera entities are added, replace the single-camera registration with:

```python
async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register the public views once per integration setup.
    if not hass.data.setdefault(f"{DOMAIN}_views_registered", False):
        hass.http.register_view(LidarPcdDownloadView())
        hass.http.register_view(MapImageView())
        hass.data[f"{DOMAIN}_views_registered"] = True

    # The "active map" follower camera (existing behaviour).
    entities: list[Camera] = [DreameA2MowerCamera(coordinator)]
    # One per-map static camera per known map.
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.append(DreameA2PerMapCamera(coordinator, map_id))
    # Plus the LiDAR cameras (existing classes — keep them as-is).
    entities.extend(_lidar_camera_entities(coordinator))

    async_add_entities(entities)
```

(NOTE: the per-map camera registration only enumerates maps known at setup time. New maps detected during the integration's runtime won't auto-register — this is acceptable for Phase 1; users restart HA to pick up new maps. Document this in `docs/multi-map.md` in Task 14.)

- [ ] **Step 4: Run the suite**

Run: `python -m pytest -q`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py
git commit -m "feat(camera): per-map static cameras + MapImageView ?map_id query"
```

---

## Task 11: Replay picker `[Map N]` prefix + cross-map render

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `custom_components/dreame_a2_mower/archive/session.py`
- Test: `tests/integration/test_replay_cross_map.py` (create)

- [ ] **Step 1: Add `map_id` to `ArchivedSession`**

In `custom_components/dreame_a2_mower/archive/session.py`, locate the `ArchivedSession` dataclass (around line 47). Add a new required field:

```python
    map_id: int  # 0-indexed map_id this session was mowed against. -1 if unknown at finalize time.
```

In the `from_summary` classmethod, accept a new `map_id` kwarg and pass it through. Update `to_dict` and `from_dict` (around line 100-115):

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            ...                       # other fields
            "map_id": self.map_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedSession":
        return cls(
            filename=str(d.get("filename", "")),
            ...
            map_id=int(d["map_id"]) if "map_id" in d else -1,
        )
```

(Use `-1` as a sentinel when reading legacy entries that lack `map_id`. The loader treats `-1` entries as "Map ?".)

In the loader (`load_index` around line 175), entries with `map_id == -1` are kept but logged once:

```python
            if loaded_session.map_id == -1:
                LOGGER.warning(
                    "[archive] %s lacks map_id (legacy schema); rendering as [Map ?]. "
                    "Run tools/recover_sessions.py to retro-fit, or wipe and rebuild.",
                    loaded_session.filename,
                )
```

- [ ] **Step 2: Update archive write sites to pass map_id**

In `coordinator.py`, find the `_do_oss_fetch` archive call (around line 2480) and the `_run_finalize_incomplete` archive call (around line 2620). Both call `session_archive.archive(...)` with a session-summary kwarg. Update each:

```python
        # _do_oss_fetch:
        await self.hass.async_add_executor_job(
            self.session_archive.archive, summary, json_text, self._resolve_finalize_map_id(),
        )
```

Add a new helper method on the coordinator:

```python
    def _resolve_finalize_map_id(self) -> int:
        """Map id to stamp on a session being finalized.

        Active-map at finalize time is the canonical answer; if no
        active map yet (rare), fall back to the lowest-id cached map;
        if no maps cached at all, sentinel -1.
        """
        if self._active_map_id is not None:
            return int(self._active_map_id)
        if self._cached_maps_by_id:
            return min(self._cached_maps_by_id.keys())
        return -1
```

In `archive/session.py` `archive()` method, accept the new positional/kwarg `map_id` and forward to `from_summary`.

- [ ] **Step 3: Update replay picker labels**

In `custom_components/dreame_a2_mower/select.py`, find `DreameA2ReplaySessionSelect`. Update the `options` property to prefix labels with `[Map N]`:

```python
    @property
    def options(self) -> list[str]:
        sessions = self.coordinator.session_archive.list_sessions()
        return [
            self._label_for(s) for s in sorted(sessions, key=lambda x: x.end_ts, reverse=True)
        ]

    @staticmethod
    def _label_for(session: Any) -> str:
        map_id = getattr(session, "map_id", -1)
        if map_id == -1:
            map_prefix = "[Map ?]"
        else:
            map_prefix = f"[Map {map_id + 1}]"
        # Existing label format (date/duration/area):
        from datetime import datetime
        date_str = datetime.fromtimestamp(session.end_ts).strftime("%Y-%m-%d %H:%M")
        return f"{map_prefix} {date_str} — {int(session.area_mowed_m2)}m² ({session.duration_min}m)"
```

(Keep the picker `current_option` mapping consistent: it'll need the same `_label_for` call to round-trip selection.)

- [ ] **Step 4: Update coordinator.replay_session to set `_render_map_id`**

In `coordinator.py`, locate `replay_session(session_md5)` (around line 1735). Change the body so that:

```python
    async def replay_session(self, session_md5: str) -> None:
        """... (existing docstring) ..."""
        ...
        # Locate the entry (existing logic).
        ...
        if entry is None:
            LOGGER.warning(...)
            return

        # NEW: set _render_map_id so the camera serves the session's map.
        target_map_id = entry.map_id if entry.map_id != -1 else self._active_map_id
        if target_map_id is None or target_map_id not in self._cached_maps_by_id:
            LOGGER.warning(
                "[F5.9.1] replay_session: cannot render — map_id=%r not in cache",
                target_map_id,
            )
            return
        self._render_map_id = target_map_id

        # Existing render logic continues — uses _cached_map_data property
        # which now reads _cached_maps_by_id[_render_map_id] via the property.
        ...
```

After the render call, ensure the render writes to `_cached_pngs_by_id[_render_map_id]` (the property setter handles this).

After the next `_refresh_map` tick, `_render_map_id` is reset to None so the camera reverts to active. Add this at the end of `_refresh_map`:

```python
        # Replay-render override is one-shot: clear it after a fresh refresh.
        self._render_map_id = None
```

- [ ] **Step 5: Write the cross-map replay test**

Create `tests/integration/test_replay_cross_map.py`:

```python
"""Replay test: picking a session from inactive map renders against session.map_id."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord_with_two_maps():
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    map0, map1 = MagicMock(map_id=0, md5="aaa"), MagicMock(map_id=1, md5="bbb")
    coord._cached_maps_by_id = {0: map0, 1: map1}
    coord._cached_pngs_by_id = {0: b"png-map-0", 1: b"png-map-1"}
    coord._last_map_md5_by_id = {0: "aaa", 1: "bbb"}
    coord._active_map_id = 0
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    return coord


def test_render_map_id_defaults_to_active():
    coord = _make_coord_with_two_maps()
    assert coord.cached_map_png == b"png-map-0"


def test_render_map_id_override_serves_other_map_png():
    coord = _make_coord_with_two_maps()
    coord._render_map_id = 1
    assert coord.cached_map_png == b"png-map-1"
```

Run: `python -m pytest tests/integration/test_replay_cross_map.py -v`
Expected: BOTH PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/archive/session.py tests/integration/test_replay_cross_map.py
git commit -m "feat(replay): cross-map replay via session.map_id + [Map N] prefix"
```

---

## Task 12: Camera entity surfaces map metadata

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`

- [ ] **Step 1: Extend extra_state_attributes on the active-map camera**

In `DreameA2MowerCamera.extra_state_attributes` (around line 102), update to include map metadata:

```python
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Existing fields + multi-map awareness."""
        attrs: dict[str, Any] = {}
        png = self.coordinator.cached_map_png
        if png:
            import hashlib
            attrs["image_version"] = hashlib.sha1(png).hexdigest()[:12]
        # Existing calibration_points logic stays unchanged — it uses
        # self.coordinator._cached_map_data, which now reads the
        # currently-rendered map via the property accessor.
        md = self.coordinator._cached_map_data
        if md is not None:
            try:
                bx2 = float(md.bx2)
                by2 = float(md.by2)
                grid = float(md.pixel_size_mm)
                h = int(md.height_px)
            except (TypeError, ValueError, AttributeError):
                pass
            else:
                samples = ((0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0))
                attrs["calibration_points"] = [
                    {
                        "mower": {"x": x_mm, "y": y_mm},
                        "map": {
                            "x": (bx2 - x_mm) / grid,
                            "y": (h - 1) - (by2 - y_mm) / grid,
                        },
                    }
                    for x_mm, y_mm in samples
                ]
        # NEW: multi-map awareness.
        active = self.coordinator._active_map_id
        render = self.coordinator._render_map_id if self.coordinator._render_map_id is not None else active
        if render is not None:
            current_md = self.coordinator._cached_maps_by_id.get(render)
            attrs["map_id"] = render
            attrs["map_name"] = getattr(current_md, "name", None)
        attrs["available_map_ids"] = sorted(self.coordinator._cached_maps_by_id.keys())
        return attrs
```

- [ ] **Step 2: Verify suite still passes**

Run: `python -m pytest -q`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py
git commit -m "feat(camera): surface map_id, map_name, available_map_ids on active camera"
```

---

## Task 13: Dashboard updates

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Add active_map select to Mower view**

In `dashboards/mower/dashboard.yaml`, locate the "Mower" view's first `entities` card (currently labelled "State", around line 31). Add a new entities card BEFORE it:

```yaml
      # Active map selector — read-only Phase 1; mirrors the mower's
      # firmware-selected active map (cloud MAPL is the source of truth).
      - type: entities
        title: Map
        entities:
          - entity: select.dreame_a2_mower_active_map
            name: Active map
```

- [ ] **Step 2: Add a new Maps view**

Append a new view after "Diagnostics" (the file's last view, around line 307):

```yaml
  - title: Maps
    path: maps
    icon: mdi:map-multiple
    cards:
      - type: markdown
        content: |
          ## All known maps
          One static snapshot per map known to the integration. The
          live trail follows the active map (selectable on the Mower
          tab); these snapshots are read-only inventory.
      # Map 1 (always present after a successful refresh).
      - type: picture-entity
        entity: camera.dreame_a2_mower_map_0
        name: Map 1
        camera_view: live
        show_state: false
        aspect_ratio: 637x717
      # Map 2 — wrapped in a conditional so it only renders when the
      # entity actually exists. (Per-map cameras only register at HA
      # boot; restart HA after creating a new map.)
      - type: conditional
        conditions:
          - entity: camera.dreame_a2_mower_map_1
            state_not: unavailable
        card:
          type: picture-entity
          entity: camera.dreame_a2_mower_map_1
          name: Map 2
          camera_view: live
          show_state: false
          aspect_ratio: 637x717
```

- [ ] **Step 3: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print('YAML valid')"`
Expected: `YAML valid`.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): active_map select in Mower view + Maps overview view"
```

---

## Task 14: User docs (`docs/multi-map.md` + README)

**Files:**
- Create: `docs/multi-map.md`
- Modify: `README.md`

- [ ] **Step 1: Create docs/multi-map.md**

```markdown
# Multi-map support

The integration supports multiple cloud-side maps. Each map has its
own zones, contours, and replay sessions; the live trail follows
whichever map the mower is currently using.

## Entities

| entity_id | Purpose |
|---|---|
| `select.dreame_a2_mower_active_map` | Reflects the mower's firmware-selected active map. **Read-only** for now — switching maps requires the app. |
| `camera.dreame_a2_mower_map` | Active-map follower. Renders the active map's base + live trail (or replay during session-pick). |
| `camera.dreame_a2_mower_map_<id>` | Static per-map snapshot for the "Maps" dashboard view. |
| `select.dreame_a2_mower_replay_session` | Replay picker — entries from all maps, prefixed with `[Map N]`. |

## How active-map detection works

The integration polls `cfg_individual.MAPL` every 10 minutes (and on
each `mowing_started` event) to determine which map the mower is
actively using. MAPL is a 2D array with one row per map; the row
whose second column is `1` is the active map.

If you switch maps in the Dreame app, HA picks up the change within
~10 minutes (or on the next mow start). Manually triggering an
update is not exposed today.

## Adding a new map

The Dreame app's "Add map" / "Edit map" flow creates a new map slot.
After creating one:

1. Wait for the next CFG poll (or restart HA) so the integration
   sees `MAPL` with the new entry.
2. The per-map camera entity for the new map (`camera.map_<id>`) is
   created on the next HA restart. (Phase 1 doesn't auto-register
   entities at runtime — restart is required.)
3. The Maps dashboard view shows a hard-coded slot for the first 2
   maps; edit `dashboards/mower/dashboard.yaml` to add more.

## Replays across maps

The replay picker shows all archived sessions across all maps,
prefixed with `[Map 1]` / `[Map 2]` / etc. Picking a session from
the inactive map temporarily flips `camera.dreame_a2_mower_map` to
that map for the duration of the replay; the next live update reverts
it to the active map.

## Limitations

- Active-map switching is observed-only in HA — use the app to switch.
- Per-map LiDAR archives are not yet investigated; today's LiDAR
  archive is shared across maps.
- Inter-map "navigation paths" (the gray polyline the app draws between
  maps) are decoded into `MapData.nav_paths` but not yet rendered.
```

- [ ] **Step 2: Add README link**

In `README.md`, find the `## Documentation` section. Append:

```markdown
- **`docs/multi-map.md`** — multi-map support: active-map detection,
  per-map cameras, replay picker, current limitations.
```

Also add a brief "Multi-map" subsection in the Features section, before "Showcase dashboard":

```markdown
### Multi-map

The integration tracks multiple cloud-side maps. The active map drives
the camera + zone/spot/edge selectors; per-map static cameras let you
view inactive maps. Replay picker spans all maps. See `docs/multi-map.md`.

```

- [ ] **Step 3: Commit**

```bash
git add docs/multi-map.md README.md
git commit -m "docs(multi-map): user-facing reference + README link"
```

---

## Task 15: TODO updates

**Files:**
- Modify: `docs/TODO.md`

- [ ] **Step 1: Replace the multi-map placeholder + close stale entries**

Open `docs/TODO.md`. Remove the existing "Multi-map support (major undertaking)" entry (it's now implemented). Replace with three follow-up entries:

```markdown
### Writable `select.active_map` (capture wire format)

**Why:** The bundled `select.dreame_a2_mower_active_map` is read-only
because the cloud "set active map" action wire format isn't decoded.
The Dreame app shows other-map thumbnails as small windows on the
main view; tapping one swaps active. This is a frequent user action,
so capturing the wire format is high-value.
**Done when:** `select.active_map.async_select_option` writes to the
firmware via the captured action; option-select in HA results in
`MAPL[i][1]` flipping after the next CFG poll.
**Status:** blocked-by-capture (probe procedure: tap an other-map
thumbnail in app while probe log records; diff s2.50 / setCFG /
properties_changed traffic between the tap and the resulting MAPL
update).
**Cross-refs:** `docs/superpowers/specs/2026-05-07-multi-map-design.md`
§ "Out of scope"

---

### LiDAR archive — per-map?

**Why:** Today's `lidar_archive` is a flat folder; if the mower keeps
distinct LiDAR scans for each map (likely on physically-distinct
maps; ambiguous on overlapping ones like the user's current setup),
the archive layout needs a `map_id` field too.
**Done when:** Either (a) confirmed shared across maps and documented;
or (b) a `map_id` field is added to lidar_archive entries and the
LiDAR card filters/displays per-map scans.
**Status:** open (investigation)
**Cross-refs:** `custom_components/dreame_a2_mower/lidar_archive.py`;
`docs/multi-map.md` "Limitations" section

---

### Render `nav_paths` overlay on the camera

**Why:** `MapData.nav_paths` is decoded from the cloud `paths` key
(connecting paths between maps, rendered in the app as gray
polylines). The greenfield decodes them but the renderer doesn't draw
them yet.
**Done when:** `map_render` overlays `nav_paths` as a styled gray
polyline (similar to live-trail rendering); a multi-map test fixture
visually confirms the overlay aligns with the user's app screenshot.
**Status:** open (Phase 2 polish)
**Cross-refs:** `map_render.py`; `MapData.nav_paths`

---
```

- [ ] **Step 2: Commit**

```bash
git add docs/TODO.md
git commit -m "docs(todo): multi-map follow-ups (writable select, lidar-per-map, nav_paths render)"
```

---

## Task 15b: Update research docs with multi-map findings

**Files:**
- Modify: `docs/research/g2408-research-journal.md`
- Modify: `docs/research/g2408-protocol.md`

The journal records the RE journey; the protocol doc records the
finished decoded surface. Both need multi-map entries.

- [ ] **Step 1: Append a new journal topic for the multi-map research**

Open `docs/research/g2408-research-journal.md`. Find the index near the
top (the `## Topics` list around line 18) and append a new entry:

```
- [Multi-map support — wire confirmation 2026-05-07](#multi-map-support--wire-confirmation-2026-05-07)
```

Append a new section at the end of the file:

```markdown
## Multi-map support — wire confirmation 2026-05-07

**Quick answer (current state):** g2408 supports multiple cloud-side
maps. The `MAPL` cfg_individual response is the active-map source of
truth (one row per map_id, col 1 = is_active flag). The cloud `MAP.*`
batch concatenates all maps and uses `MAP.info` as the byte-offset to
split. `s1p50={}` empty-pings fire on every map-swap (reliable
trigger); `s2p50 op=200` is conditional. Outbound "set active map"
command shape still unknown.

### Timeline

- **2026-05-04..06**: cloud dumps show `MAPL = [[0, 1, 1, 1, 0]]`
  (single row). Inventory entry marks the field "hypothesized" with
  open question about row/col semantics.
- **2026-05-07 19:57**: user creates Map 2 in the Dreame app via the
  "Edit map" → "Add map" flow. App fails to merge the new map with
  the existing one; result is two separate maps in the cloud, with a
  connecting "navigation path" rendered as a gray polyline by the app.
- **2026-05-07 20:00**: Map 2 starts mowing. MAPL polled later shows
  `[[0, 0, 1, 1, 0], [1, 1, 1, 1, 0]]` — Map 0's col-1 went 1→0,
  Map 1 added with col-1=1. Confirms col 1 is the is_active flag.
- **2026-05-07 20:00:42 / 20:01:04 / 20:03:06**: `s2p65=TASK_NAV_CHECK`
  fires three times during the dock → Map 2 path traversal. Adds a
  third value to the s2p65 catalog (was: TASK_SLAM_RELOCATE,
  TASK_NAV_DOCK).
- **2026-05-07 21:43:32**: First confirmed wire observation of
  `s2p50 op=200` (apk-documented as `changeMap`) during a swap
  session. Inbound echo only: `{exe:true, o:200, status:true}`.
- **2026-05-07 21:52:05–07 (flip A→B)** and **21:52:36–38 (flip B→A)**:
  paired captures show `s1p50={}` fires on EVERY swap (reliable);
  `s2p50 op=200` fires on flip 1 only (conditional).
- **Greenfield gap discovered**: `parse_cloud_map` reads only the
  first map in the cloud batch; legacy upstream `parse_batch_map_data`
  splits via MAP.info. The greenfield silently discards Map 1+ data
  in multi-map setups. Fixed in v1.0.0a92.

### Findings

1. **MAPL row layout**: `[map_id, is_active, ?, ?, ?]`. Col 0 is
   0-indexed map_id. Col 1 flips between maps when the active map
   changes. Cols 2–4 stayed `[1, 1, 0]` across both samples; their
   semantic is undecoded — needs map-edit captures to discriminate.
2. **`MAP.info` split**: cloud batch returns all maps concatenated
   in `MAP.0..MAP.27` strings; `MAP.info` is the byte offset where
   the second map starts. JSON-decode each segment separately;
   each segment's `mapIndex` field keys it.
3. **`paths` key**: cloud map response carries the gray inter-map
   navigation paths under the `paths` key. Each entry is
   `{path_id_str: {path: [{x, y}, ...], type: int}}`. Legacy upstream
   parses this; greenfield greenfield decodes from a92 onwards as
   `MapData.nav_paths`.
4. **s1p50 per-swap signal**: empty-payload `s1p50={}` ping fires
   on every map-swap (confirmed across 2 paired flips). Used by the
   integration as a MAPL-repoll trigger for sub-second active-map
   detection latency. (Other s1p50 cases — zone-edits, maintenance
   saves — also benefit from the cheap re-poll.)
5. **s2p50 op=200 conditional**: fires on some swaps but not others.
   Hypothesis: direction-specific or first-in-quiet-window
   suppression. NOT a reliable per-swap signal.

### Deprecated readings

- "MAPL is hypothesized — needs operation-correlated capture" —
  superseded by today's confirmation. Cols 0+1 decoded; cols 2–4
  still open.
- "o:200 not observed on g2408 wire" — superseded by 2026-05-07
  capture. Op-code confirmed; outbound command form still unknown.

### Cross-references

- `docs/superpowers/specs/2026-05-07-multi-map-design.md` — full design
- `docs/superpowers/plans/2026-05-07-multi-map-implementation.md` — plan
- Inventory: `MAPL`, `s1p50`, `s2p65`, `o200` entries
- Code: `coordinator._apply_mapl`, `coordinator._refresh_mapl`,
  `cloud_client.fetch_map`, `map_decoder.parse_cloud_maps`
```

- [ ] **Step 2: Add multi-map note to the protocol doc**

Open `docs/research/g2408-protocol.md`. Search for "MAP.*" or "boundary"
to find the section that describes the cloud map fetch. Append a new
subsection (or augment the existing one) with:

```markdown
### Multi-map (MAP.* split via MAP.info)

When the device has multiple cloud-side maps, the `MAP.0..MAP.27`
batch response carries all of them concatenated in the joined string.
The auxiliary key `MAP.info` is the byte offset where the second
map's JSON starts; parse each segment as its own JSON list.

Each segment is wrapped as a one-element list whose inner dict has
the standard map keys (`boundary`, `mowingAreas`, `contours`, etc.)
plus `mapIndex` (0-indexed) and `name`.

Active-map detection uses `cfg_individual.MAPL` — a list of rows,
one per map. Row layout `[map_id, is_active, ?, ?, ?]`; the row with
col 1 == 1 is the active map. Cols 2–4 are undecoded as of 2026-05-07.

The integration's `cloud_client.fetch_map` returns
`dict[map_id, dict] | None`; `map_decoder.parse_cloud_maps` returns
`dict[map_id, MapData]` with each `MapData.map_id`, `MapData.name`,
and `MapData.nav_paths` populated.

See journal topic [Multi-map support — wire confirmation 2026-05-07].
```

- [ ] **Step 3: Verify markdown renders cleanly**

Run: `head -3 docs/research/g2408-research-journal.md`
Expected: file readable, no parse errors.

- [ ] **Step 4: Commit**

```bash
git add docs/research/g2408-research-journal.md docs/research/g2408-protocol.md
git commit -m "docs(research): multi-map findings — MAPL, MAP.info split, paths, s1p50/o200"
```

---

## Task 16: Run full suite, audit regressions

**Files:** none

- [ ] **Step 1: Full pytest run**

Run: `python -m pytest -q`
Expected: high pass count, 0 failures. The plan should preserve all 721 prior tests; new tests add ~12 (3 nav_paths, 4 multi_map_decoder, 3 fetch_map, 4 active_map_routing, 2 replay_cross_map = ~16 new).

- [ ] **Step 2: Triage any failure**

If a test fails:
- AttributeError on missing `_cached_maps_by_id` / `_active_map_id` / etc. → extend the failing test's coordinator stub fixture (see Task 5 Step 4 example).
- Mock returning the old single-dict shape from `fetch_map` → update mock to return `{0: dict}`.
- Anything else → STOP and escalate.

- [ ] **Step 3: Commit any test-only fixes**

```bash
git add tests/
git commit -m "test(multi-map): extend fixtures to seed multi-map cache attrs"
```

(Skip if no fixes needed.)

---

## Task 17: Cut release a92

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json` (via `tools/release.sh`)

- [ ] **Step 1: Verify clean tree on main**

Run: `git status --porcelain && git rev-parse --abbrev-ref HEAD`
Expected: empty output, then `main`.

- [ ] **Step 2: Write release notes**

Write to `/tmp/release_a92_notes.md`:

```markdown
## v1.0.0a92

Multi-map support — full reshape. The integration now fetches, parses,
and caches all cloud-side maps, tracks which one is active via MAPL
polling, and surfaces them through:

- `select.dreame_a2_mower_active_map` — read-only active-map selector
  (writable in a follow-up release once the cloud action is captured).
- `camera.dreame_a2_mower_map_<id>` — static per-map snapshots; the
  existing `camera.dreame_a2_mower_map` continues to follow the active
  map (with replay-render override during session picks).
- Replay picker now spans all maps with `[Map N]` prefixes; selecting a
  session renders against that session's map_id.

**Breaking change**: `ArchivedSession.map_id` is now a required field.
Sessions archived under prior versions are kept on disk but skipped
from the picker (the integration logs each skipped file). Wipe + rebuild
via `tools/recover_sessions.py` if you want them back.

`MapData` gains `map_id`, `name`, and `nav_paths` (the gray inter-map
paths from the cloud `paths` key). Rendering `nav_paths` as a styled
overlay on the camera image is deferred to Phase 2.

See `docs/multi-map.md` for the user-facing reference.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

- [ ] **Step 3: Run release.sh**

Run: `tools/release.sh --notes-file /tmp/release_a92_notes.md`
Expected: `✅ release v1.0.0a92 published cleanly.`

- [ ] **Step 4: SCP the new dashboard yaml to running HA**

Run:
```bash
HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PASS=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
BACKUP=dashboard.yaml.bak-$(date +%s)
sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=accept-new "${USER}@${HOST}" "cp /config/dashboards/mower/dashboard.yaml /config/dashboards/mower/${BACKUP}"
sshpass -p "${PASS}" scp -o StrictHostKeyChecking=accept-new dashboards/mower/dashboard.yaml "${USER}@${HOST}:/config/dashboards/mower/dashboard.yaml"
```

- [ ] **Step 5: Done**

Pull a92 via HACS on the running HA instance, restart, verify:
1. `select.dreame_a2_mower_active_map` appears in Settings → Devices & Services → Dreame A2 Mower
2. `camera.dreame_a2_mower_map_0` and `camera.dreame_a2_mower_map_1` are present
3. The Maps dashboard view renders both maps
4. Replay picker shows entries with `[Map 1]` / `[Map 2]` prefixes
5. Picking a Map 2 replay flips the live camera to render Map 2's base
