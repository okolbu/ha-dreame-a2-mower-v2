# F11: WiFi Cross-Map Picker + Base-Map Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-map WiFi view picker with a cross-map archive picker that lists every WiFi heatmap object from the cloud (labeled `[Map N] YYYY-MM-DD HH:MM`), and update the dashboard WiFi Coverage view with opacity, flip, and base-map-visibility controls.

**Architecture:** `cloud_client.list_wifi_candidates()` probes the OBJ endpoint and returns all wifimap entries with geometry-matched `map_id`. `coordinator.list_wifi_archive_entries()` + `_wifi_render_entry` mirror the LiDAR archive pattern. `DreameA2WifiArchiveSelect` replaces `DreameA2WifiViewSelect`; `DreameA2WifiSelectedCamera` is updated to use `_wifi_render_entry` instead of `_wifi_view_map_id`. Dashboard is rewritten to use the new picker and add opacity/flip/base-map controls via card-mod.

**Tech Stack:** Python 3.12, Home Assistant custom integration, Lovelace YAML, card-mod, pytest.

---

## File Map

| File | Change |
|------|--------|
| `custom_components/dreame_a2_mower/cloud_client.py` | Add `list_wifi_candidates(map_extents)` method |
| `custom_components/dreame_a2_mower/coordinator.py` | Add `_wifi_render_entry`, `list_wifi_archive_entries()`, `set_wifi_render_entry()`; remove `_wifi_view_map_id` / `set_wifi_view_map_id` |
| `custom_components/dreame_a2_mower/select.py` | Replace `DreameA2WifiViewSelect` with `DreameA2WifiArchiveSelect`; update `async_setup_entry` |
| `custom_components/dreame_a2_mower/camera.py` | Update `DreameA2WifiSelectedCamera` to use `_wifi_render_entry`; update `async_setup_entry` entity name |
| `custom_components/dreame_a2_mower/translations/en.json` | Replace `wifi_view` key → `wifi_archive` under `entity.select`; update camera key if needed |
| `docs/superpowers/helpers/dreame-a2-helpers.yaml` | Add 3 new `input_boolean` helpers |
| `dashboards/mower/dashboard.yaml` | Rewrite WiFi Coverage view cards |
| `tests/integration/test_wifi_archive_select.py` | New: tests for `DreameA2WifiArchiveSelect` + archive coordinator methods |
| `tests/integration/test_wifi_selected_camera.py` | New: tests for updated `DreameA2WifiSelectedCamera` render path |
| `tests/integration/test_wifi_view_select.py` | Remove tests that rely on removed `DreameA2WifiViewSelect` / `_wifi_view_map_id` |

---

## Task 1: Add `cloud_client.list_wifi_candidates()`

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py`

This method probes the OBJ endpoint (same call as `fetch_wifi_map`) and returns metadata for every wifimap object, with `map_id` inferred by geometry matching.

- [ ] **Step 1: Locate insert point in cloud_client.py**

Read the file around line 948 (just after `fetch_wifi_map` ends). The new method goes immediately after `fetch_wifi_map`.

Run: `grep -n "def get_file\|def fetch_wifi_map\|def list_wifi" custom_components/dreame_a2_mower/cloud_client.py`

Expected output includes `750:    def fetch_wifi_map` and `949:    def get_file`.

- [ ] **Step 2: Write the failing test for `list_wifi_candidates`**

Create file `tests/integration/test_wifi_archive_select.py`:

```python
"""Tests for WiFi archive select + coordinator archive methods."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_map(name: str | None = None, bx1=0.0, by1=0.0, bx2=1000.0, by2=1000.0):
    m = MagicMock()
    m.name = name
    # bx1/by1/bx2/by2 represent cloud-frame extent in cm.
    m.bx1 = bx1; m.by1 = by1; m.bx2 = bx2; m.by2 = by2
    m.pixel_size_mm = 25.0
    return m


def _make_coordinator(maps: dict, wifi_candidates=None):
    coord = MagicMock()
    coord._cached_maps_by_id = maps
    coord._active_map_id = min(maps.keys()) if maps else None
    coord._wifi_render_entry = None
    coord.async_update_listeners = MagicMock()
    if wifi_candidates is not None:
        coord.list_wifi_archive_entries = MagicMock(return_value=wifi_candidates)

    def _set_wifi_render_entry(map_id, object_name):
        coord._wifi_render_entry = None if map_id is None else (map_id, object_name)
        coord.async_update_listeners()

    coord.set_wifi_render_entry = _set_wifi_render_entry
    return coord


# ---------------------------------------------------------------------------
# cloud_client.list_wifi_candidates
# ---------------------------------------------------------------------------

def test_list_wifi_candidates_returns_all_with_no_extents():
    """Without map_extents all candidates are returned with map_id=None."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}

    # OBJ probe returns two object names.
    obj_resp = {"out": [{"d": {"name": ["wifimap_1746000000.json", "wifimap_1745000000.json"]}}]}
    client.action = MagicMock(return_value=obj_resp)

    # _decode_or_none path: provide signed URL + downloadable JSON for each.
    def _fake_url(obj_name):
        return f"https://oss/{obj_name}"

    def _fake_get_file(url):
        import json
        ts = int(url.split("_")[-1].replace(".json", ""))
        return json.dumps({
            "data": [1] * 4,
            "width": 2, "height": 2, "resolution": 2,
            "startX": 100, "startY": 100,
        }).encode()

    client.get_interim_file_url = _fake_url
    client.get_file = _fake_get_file

    results = client.list_wifi_candidates(map_extents={})
    assert len(results) == 2
    # Newest first (1746000000 > 1745000000).
    assert results[0]["unix_ts"] == 1746000000
    assert results[1]["unix_ts"] == 1745000000
    # No geometry match possible — map_id is None.
    assert all(r["map_id"] is None for r in results)


def test_list_wifi_candidates_assigns_map_id_by_geometry():
    """Geometry matching assigns the correct map_id to each candidate."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}

    # Two wifimap objects with different extents.
    obj_resp = {"out": [{"d": {"name": [
        "wifimap_1746000000.json",   # center ~ (250, 250) → inside map 0 (0-500)
        "wifimap_1745000000.json",   # center ~ (1250, 1250) → inside map 1 (1000-1500)
    ]}}]}
    client.action = MagicMock(return_value=obj_resp)

    import json

    def _fake_url(obj_name):
        return f"https://oss/{obj_name}"

    def _fake_get_file(url):
        if "1746000000" in url:
            # startX=100, startY=100, width=4, height=4, res=2 →
            # w_cm=4*2*10=80, cx=100+40=140; cy=100+40=140 → inside map0(0-500)
            return json.dumps({
                "data": [1] * 16, "width": 4, "height": 4,
                "resolution": 2, "startX": 100, "startY": 100,
            }).encode()
        else:
            # startX=1100, startY=1100, width=4, height=4, res=2 →
            # cx=1100+40=1140, cy=1100+40=1140 → inside map1(1000-1500)
            return json.dumps({
                "data": [1] * 16, "width": 4, "height": 4,
                "resolution": 2, "startX": 1100, "startY": 1100,
            }).encode()

    client.get_interim_file_url = _fake_url
    client.get_file = _fake_get_file

    map_extents = {
        0: (0.0, 0.0, 500.0, 500.0),
        1: (1000.0, 1000.0, 1500.0, 1500.0),
    }
    results = client.list_wifi_candidates(map_extents=map_extents)
    assert len(results) == 2
    by_ts = {r["unix_ts"]: r for r in results}
    assert by_ts[1746000000]["map_id"] == 0
    assert by_ts[1745000000]["map_id"] == 1


def test_list_wifi_candidates_empty_when_no_objects():
    """Returns [] when OBJ probe has no names."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}
    client.action = MagicMock(return_value={"out": [{"d": {"name": []}}]})
    client.get_interim_file_url = MagicMock()
    client.get_file = MagicMock()

    results = client.list_wifi_candidates(map_extents={})
    assert results == []


# ---------------------------------------------------------------------------
# coordinator.list_wifi_archive_entries + set_wifi_render_entry
# ---------------------------------------------------------------------------

def test_coordinator_list_wifi_archive_entries_sorted_newest_first():
    """list_wifi_archive_entries returns entries newest-first."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._cached_maps_by_id = {0: _make_map("Front"), 1: _make_map("Back")}
    coord._cloud = MagicMock()

    entries = [
        {"object_name": "a", "unix_ts": 1000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
        {"object_name": "b", "unix_ts": 2000, "map_id": 1,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
        {"object_name": "c", "unix_ts": 1500, "map_id": None,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord._cloud.list_wifi_candidates = MagicMock(return_value=entries)
    # Provide map extents.
    coord._build_map_extents = MagicMock(return_value={})

    result = coord.list_wifi_archive_entries()
    assert result[0]["unix_ts"] == 2000
    assert result[1]["unix_ts"] == 1500
    assert result[2]["unix_ts"] == 1000


def test_set_wifi_render_entry_updates_state_and_fires_listeners():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = None
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(0, "wifimap_1746000000.json")
    assert coord._wifi_render_entry == (0, "wifimap_1746000000.json")
    coord.async_update_listeners.assert_called_once()


def test_set_wifi_render_entry_none_resets():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = (0, "old.json")
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(None, None)
    assert coord._wifi_render_entry is None


# ---------------------------------------------------------------------------
# DreameA2WifiArchiveSelect
# ---------------------------------------------------------------------------

def test_wifi_archive_select_options_labeled():
    """Options are formatted as '[Map N] YYYY-MM-DD HH:MM'."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "a", "unix_ts": 1746000000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({0: _make_map("Front")}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"

    sel._rebuild_options()

    assert len(sel._attr_options) == 1
    opt = sel._attr_options[0]
    assert opt.startswith("[Map 1]")
    # Should contain a date string.
    assert "202" in opt


def test_wifi_archive_select_unknown_map_labeled():
    """Candidates with map_id=None are labeled '[Unknown map]'."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "a", "unix_ts": 1746000000, "map_id": None,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"

    sel._rebuild_options()
    assert sel._attr_options[0].startswith("[Unknown map]")


def test_wifi_archive_select_on_select_calls_set_wifi_render_entry():
    """Selecting an option updates coordinator._wifi_render_entry."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "wifimap_1746000000.json", "unix_ts": 1746000000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({0: _make_map("Front")}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"
    sel.async_write_ha_state = MagicMock()

    sel._rebuild_options()
    opt = sel._attr_options[0]
    asyncio.run(sel.async_select_option(opt))

    assert coord._wifi_render_entry == (0, "wifimap_1746000000.json")
    coord.async_update_listeners.assert_called()
```

- [ ] **Step 3: Run test to verify it fails cleanly**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_archive_select.py -v 2>&1 | tail -30
```

Expected: Import errors or AttributeErrors — `list_wifi_candidates`, `DreameA2WifiArchiveSelect`, `_wifi_render_entry` don't exist yet.

- [ ] **Step 4: Implement `cloud_client.list_wifi_candidates()`**

In `custom_components/dreame_a2_mower/cloud_client.py`, add this method immediately after `fetch_wifi_map` (before `def get_file` at line ~949):

```python
def list_wifi_candidates(
    self,
    map_extents: dict[int, tuple[float, float, float, float]] | None = None,
) -> list[dict]:
    """Return metadata for every wifimap object in the cloud, sorted newest-first.

    Calls the same OBJ probe as ``fetch_wifi_map`` but returns ALL objects
    (one per map, typically), not just the one that matches a given map_id.
    Each returned dict has:
        {
            "object_name": str,
            "unix_ts": int,       # parsed from filename; 0 if not parseable
            "map_id": int | None, # geometry-matched against map_extents
            "startX": float, "startY": float,
            "width": int, "height": int, "resolution": int,
        }

    map_extents: dict mapping map_id → (x1, y1, x2, y2) in cm (cloud frame).
    If empty or None, map_id is left as None for all candidates.
    """
    import re as _re
    try:
        obj_resp = self.action(
            siid=2, aiid=50,
            parameters=[{"m": "g", "t": "OBJ", "d": {"type": "wifimap"}}],
        )
    except Exception as ex:
        _LOGGER.warning("list_wifi_candidates: OBJ probe error: %s", ex)
        return []
    if not isinstance(obj_resp, dict):
        return []
    outs = obj_resp.get("out") or []
    if not outs or not isinstance(outs[0], dict):
        return []
    names = (outs[0].get("d") or {}).get("name")
    if not names:
        return []
    candidates: list[str] = []
    if isinstance(names, list):
        candidates = [n for n in names if isinstance(n, str)]
    elif isinstance(names, dict):
        candidates = [v for v in names.values() if isinstance(v, str)]
    if not candidates:
        return []

    import json as _json_lc

    def _decode_candidate(obj_name: str) -> dict[str, Any] | None:
        cache = getattr(self, "_wifi_map_cache", None)
        if cache is not None:
            for (mid, cached_name), cached_dec in cache.items():
                if cached_name == obj_name:
                    return cached_dec
        url = self.get_interim_file_url(obj_name)
        if not url:
            return None
        body = self.get_file(url)
        if not body:
            return None
        try:
            dec = _json_lc.loads(body)
        except Exception:
            return None
        if isinstance(dec, dict) and "data" in dec:
            dec["_object_name"] = obj_name
            return dec
        return None

    def _parse_unix_ts(obj_name: str) -> int:
        """Extract a unix timestamp from the object's filename component."""
        # Typical pattern: something/wifimap_<digits>.json or _<digits>_...
        m = _re.search(r"_(\d{9,11})(?:[._]|$)", obj_name)
        if m:
            return int(m.group(1))
        # Fallback: any 10-digit run.
        m = _re.search(r"\b(\d{10})\b", obj_name)
        if m:
            return int(m.group(1))
        return 0

    results: list[dict] = []
    extents = map_extents or {}
    for obj_name in candidates:
        dec = _decode_candidate(obj_name)
        if dec is None:
            continue
        try:
            sx = float(dec.get("startX", 0))
            sy = float(dec.get("startY", 0))
            w = int(dec.get("width", 0))
            h = int(dec.get("height", 0))
            res = int(dec.get("resolution", 1)) or 1
        except (TypeError, ValueError):
            sx = sy = 0.0; w = h = 0; res = 1

        # Geometry-match: find which map's extent contains this heatmap's centre.
        matched_map_id: int | None = None
        if extents:
            cand_w_cm = w * res * 10
            cand_h_cm = h * res * 10
            cx = sx + cand_w_cm / 2.0
            cy = sy + cand_h_cm / 2.0
            for mid, (ex_x1, ex_y1, ex_x2, ex_y2) in extents.items():
                x1, x2 = sorted((ex_x1, ex_x2))
                y1, y2 = sorted((ex_y1, ex_y2))
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    matched_map_id = mid
                    break

        results.append({
            "object_name": obj_name,
            "unix_ts": _parse_unix_ts(obj_name),
            "map_id": matched_map_id,
            "startX": sx, "startY": sy,
            "width": w, "height": h, "resolution": res,
        })

    results.sort(key=lambda r: r["unix_ts"], reverse=True)
    return results
```

- [ ] **Step 5: Run the `list_wifi_candidates` tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_archive_select.py::test_list_wifi_candidates_returns_all_with_no_extents tests/integration/test_wifi_archive_select.py::test_list_wifi_candidates_assigns_map_id_by_geometry tests/integration/test_wifi_archive_select.py::test_list_wifi_candidates_empty_when_no_objects -v 2>&1 | tail -20
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/cloud_client.py \
        tests/integration/test_wifi_archive_select.py
git commit -m "feat: add cloud_client.list_wifi_candidates() — cross-map OBJ probe with geometry matching"
```

---

## Task 2: Add coordinator archive methods and remove old wifi-view state

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Add `_wifi_render_entry` init and `_build_map_extents` helper**

In `coordinator.py`, find the line:

```python
        self._wifi_view_map_id: int | None = None
```

Replace it with:

```python
        # WiFi archive selection — drives DreameA2WifiSelectedCamera.
        # Tuple of (map_id, object_name) — None means "latest from active map".
        self._wifi_render_entry: tuple[int, str] | None = None
```

- [ ] **Step 2: Add `_build_map_extents()` helper method**

After `set_wifi_view_map_id` (around line 3185), add:

```python
    def _build_map_extents(self) -> dict[int, tuple[float, float, float, float]]:
        """Build map_id → (bx1, by1, bx2, by2) in cm for all cached maps.

        Used by list_wifi_archive_entries to pass geometry hints to
        cloud_client.list_wifi_candidates for cross-map heatmap matching.
        Falls back to empty dict when no maps are cached or extent fields
        are unavailable.
        """
        extents: dict[int, tuple[float, float, float, float]] = {}
        for map_id, map_data in self._cached_maps_by_id.items():
            try:
                bx1 = float(getattr(map_data, "bx1", 0.0))
                by1 = float(getattr(map_data, "by1", 0.0))
                bx2 = float(getattr(map_data, "bx2", 0.0))
                by2 = float(getattr(map_data, "by2", 0.0))
                extents[map_id] = (bx1, by1, bx2, by2)
            except (TypeError, ValueError, AttributeError):
                continue
        return extents
```

- [ ] **Step 3: Add `list_wifi_archive_entries()` method**

Immediately after `_build_map_extents`, add:

```python
    def list_wifi_archive_entries(self) -> list[dict]:
        """Return all wifimap objects from the cloud, sorted newest-first.

        Each entry is a dict:
            {
                "object_name": str,
                "unix_ts": int,
                "map_id": int | None,
                "startX": float, "startY": float,
                "width": int, "height": int, "resolution": int,
            }

        Geometry matching uses ``_cached_maps_by_id`` to assign map_ids.
        Returns candidates with map_id=None when maps are not yet loaded.
        Returns [] on cloud error (already logged in list_wifi_candidates).
        """
        extents = self._build_map_extents()
        return self._cloud.list_wifi_candidates(map_extents=extents)
```

- [ ] **Step 4: Add `set_wifi_render_entry()` method**

After `list_wifi_archive_entries`, add:

```python
    def set_wifi_render_entry(self, map_id: int | None, object_name: str | None) -> None:
        """Set which WiFi heatmap the archive camera renders. None resets to default."""
        if map_id is None or object_name is None:
            self._wifi_render_entry = None
        else:
            self._wifi_render_entry = (map_id, object_name)
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()
```

- [ ] **Step 5: Remove `set_wifi_view_map_id`**

Find and remove the old method:

```python
    def set_wifi_view_map_id(self, map_id: int | None) -> None:
        """Set which map the WiFi viewer renders. None = active map fallback."""
        self._wifi_view_map_id = map_id
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()
```

- [ ] **Step 6: Run coordinator tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_archive_select.py::test_coordinator_list_wifi_archive_entries_sorted_newest_first tests/integration/test_wifi_archive_select.py::test_set_wifi_render_entry_updates_state_and_fires_listeners tests/integration/test_wifi_archive_select.py::test_set_wifi_render_entry_none_resets -v 2>&1 | tail -20
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat: add coordinator wifi archive methods (_wifi_render_entry, list_wifi_archive_entries, set_wifi_render_entry)"
```

---

## Task 3: Replace `DreameA2WifiViewSelect` with `DreameA2WifiArchiveSelect` in `select.py`

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py`

- [ ] **Step 1: Write failing tests for `DreameA2WifiArchiveSelect`**

These tests are already written in `test_wifi_archive_select.py` (Task 1 Step 2). Verify they still fail:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_archive_select.py::test_wifi_archive_select_options_labeled tests/integration/test_wifi_archive_select.py::test_wifi_archive_select_unknown_map_labeled tests/integration/test_wifi_archive_select.py::test_wifi_archive_select_on_select_calls_set_wifi_render_entry -v 2>&1 | tail -20
```

Expected: `ImportError` — `DreameA2WifiArchiveSelect` not yet defined.

- [ ] **Step 2: Replace `DreameA2WifiViewSelect` class with `DreameA2WifiArchiveSelect`**

In `select.py`, find the entire `DreameA2WifiViewSelect` class block (lines ~1586–1637) and replace it with:

```python
# ---------------------------------------------------------------------------
# WiFi archive picker — cross-map; drives DreameA2WifiSelectedCamera
# ---------------------------------------------------------------------------


class DreameA2WifiArchiveSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Cross-map WiFi heatmap archive picker.

    Lists every wifimap object found in the cloud, sorted newest-first,
    labeled ``[Map N] YYYY-MM-DD HH:MM``. Drives
    ``camera.dreame_a2_mower_wifi_heatmap_selected`` via
    ``coordinator._wifi_render_entry``.

    Options are re-enumerated on every coordinator update (because a
    button-triggered refresh may have pulled a new object from cloud).
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi archive"
    _attr_icon = "mdi:wifi-marker"
    _attr_translation_key = "wifi_archive"
    _placeholder: str = "(no WiFi maps)"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_archive")
        self._attr_device_info = mower_device_info(coordinator)
        self._attr_current_option: str | None = self._placeholder
        self._attr_options: list[str] = [self._placeholder]
        # Cache of label → entry dict for reverse-lookup in async_select_option.
        self._label_to_entry: dict[str, dict] = {}

    @staticmethod
    def _format_option(entry: dict) -> str:
        from datetime import datetime, timezone
        map_id = entry.get("map_id")
        ts = entry.get("unix_ts", 0)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        prefix = f"[Map {map_id + 1}]" if map_id is not None else "[Unknown map]"
        return f"{prefix} {dt:%Y-%m-%d %H:%M}"

    def _rebuild_options(self) -> None:
        entries = self.coordinator.list_wifi_archive_entries()
        opts = [self._format_option(e) for e in entries]
        label_map: dict[str, dict] = {}
        for e, label in zip(entries, opts):
            label_map[label] = e
        if not opts:
            opts = [self._placeholder]
        # Reflect current selection.
        render = self.coordinator._wifi_render_entry
        cur: str
        if render is None:
            cur = opts[0]
        else:
            _, selected_obj = render
            cur = self._placeholder
            for label, entry in label_map.items():
                if entry.get("object_name") == selected_obj:
                    cur = label
                    break
        self._attr_options = opts
        self._label_to_entry = label_map
        self._attr_current_option = cur if cur in opts else opts[0]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._rebuild_options()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self._rebuild_options()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            self.coordinator.set_wifi_render_entry(None, None)
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        entry = self._label_to_entry.get(option)
        if entry is None:
            # Label map may be stale — rebuild and retry.
            self._rebuild_options()
            entry = self._label_to_entry.get(option)
        if entry is not None:
            map_id = entry.get("map_id")
            obj_name = entry.get("object_name")
            self.coordinator.set_wifi_render_entry(map_id, obj_name)
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        LOGGER.warning("WifiArchiveSelect: unknown option %r", option)
```

- [ ] **Step 3: Update `async_setup_entry` in `select.py`**

Find:

```python
    entities.append(DreameA2WifiViewSelect(coordinator))
```

Replace with:

```python
    entities.append(DreameA2WifiArchiveSelect(coordinator))
```

- [ ] **Step 4: Run all archive select tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_archive_select.py -v 2>&1 | tail -25
```

Expected: all tests pass.

- [ ] **Step 5: Verify old wifi_view tests are removed or updated**

The old `test_wifi_view_select.py` tests reference `DreameA2WifiViewSelect` and `_wifi_view_map_id` which no longer exist. Replace the contents of `tests/integration/test_wifi_view_select.py` with a notice redirecting to the new test file:

```python
"""Tests for the WiFi view picker have moved to test_wifi_archive_select.py.

DreameA2WifiViewSelect was replaced by DreameA2WifiArchiveSelect in F11.
This file is retained as a placeholder to avoid breaking test discovery.
"""
```

- [ ] **Step 6: Run the full integration test suite to check for regressions**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/ -q 2>&1 | tail -20
```

Expected: all previously-passing tests still pass; the old wifi_view tests are no-ops.

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/select.py \
        tests/integration/test_wifi_view_select.py
git commit -m "feat: replace DreameA2WifiViewSelect with DreameA2WifiArchiveSelect (cross-map archive picker)"
```

---

## Task 4: Update `DreameA2WifiSelectedCamera` to use `_wifi_render_entry`

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_wifi_selected_camera.py`:

```python
"""Tests for the updated DreameA2WifiSelectedCamera (F11: uses _wifi_render_entry)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _make_map(name=None):
    m = MagicMock()
    m.name = name
    return m


def _make_coordinator(maps=None, wifi_map_by_id=None, wifi_render_entry=None, active_map_id=0):
    coord = MagicMock()
    coord._cached_maps_by_id = maps or {}
    coord._active_map_id = active_map_id
    coord._wifi_render_entry = wifi_render_entry
    coord._wifi_map_by_id = wifi_map_by_id or {}
    return coord


def _make_camera(coord):
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera
    cam = DreameA2WifiSelectedCamera.__new__(DreameA2WifiSelectedCamera)
    cam.coordinator = coord
    cam._attr_unique_id = "wifi_selected"
    cam._attr_device_info = {}
    return cam


def test_camera_available_when_render_entry_has_data():
    """Camera is available when _wifi_render_entry points to loaded data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "wifimap_1746000000.json": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)
    assert cam.available


def test_camera_unavailable_when_render_entry_object_not_loaded():
    """Camera is unavailable when _wifi_render_entry's object is not in the cache."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_falls_back_to_active_map_when_no_render_entry():
    """When _wifi_render_entry is None, camera falls back to active map."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "active_latest": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=None,
        active_map_id=0,
    )
    # Put active map's data directly in _wifi_map_by_id[0] as the fallback path.
    coord._wifi_map_by_id = {
        0: {"data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
            "startX": 0, "startY": 0}
    }
    cam = _make_camera(coord)
    assert cam.available


def test_camera_unavailable_when_no_render_entry_and_no_active_data():
    """Camera is unavailable when no render entry and no active map data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=None,
        active_map_id=0,
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_entity_picture_includes_object_name_hash():
    """entity_picture URL includes a hash derived from the selected entry."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "wifimap_1746000000.json": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)

    pic = cam.entity_picture
    # Should be a non-None URL with a version query param.
    assert pic is not None
    assert "v=" in pic


def test_camera_entity_picture_none_when_unavailable():
    """entity_picture returns None when camera has no data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=(0, "missing.json"),
    )
    cam = _make_camera(coord)
    assert cam.entity_picture is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_selected_camera.py -v 2>&1 | tail -20
```

Expected: failures — `available` still uses `_wifi_view_map_id` logic, `entity_picture` doesn't match new keying.

- [ ] **Step 3: Update `DreameA2WifiSelectedCamera` in `camera.py`**

Find the class `DreameA2WifiSelectedCamera` (starts around line 622). Replace the entire class with:

```python
class DreameA2WifiSelectedCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Renders whichever WiFi heatmap the archive picker selects.

    Driven by ``select.dreame_a2_mower_wifi_archive`` (DreameA2WifiArchiveSelect)
    via ``coordinator._wifi_render_entry``. Falls back to active map's
    latest data (from ``_wifi_map_by_id[active_map_id]``) when no explicit
    selection has been made.

    The camera key ``wifi_heatmap_selected`` in translations corresponds to
    entity_id ``camera.dreame_a2_mower_wifi_heatmap_selected``.
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi heatmap (selected)"
    _attr_content_type = "image/png"
    _attr_translation_key = "wifi_heatmap_selected"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_selected")
        self._attr_device_info = mower_device_info(coordinator)

    def _resolve_decoded(self) -> dict | None:
        """Return decoded wifi map data for the selected entry.

        Priority:
        1. ``_wifi_render_entry`` is set → look up by object_name in
           ``_wifi_map_by_id`` (keyed by object_name).
        2. Fall back to active-map latest data keyed by map_id (as
           ``_refresh_wifi_map`` stores it).
        """
        render = self.coordinator._wifi_render_entry
        wifi_map_by_id = getattr(self.coordinator, "_wifi_map_by_id", {})
        if render is not None:
            _map_id, obj_name = render
            # Try object_name key first (new-style).
            dec = wifi_map_by_id.get(obj_name)
            if dec is None:
                # Fall back to map_id key (data loaded via _refresh_wifi_map).
                dec = wifi_map_by_id.get(_map_id)
            return dec
        # No explicit selection — fall back to active map.
        active = self.coordinator._active_map_id
        if active is None:
            return None
        return wifi_map_by_id.get(active)

    @property
    def available(self) -> bool:
        return self._resolve_decoded() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        from .wifi_map_render import render_wifi_map_png
        return await self.hass.async_add_executor_job(render_wifi_map_png, decoded)

    @property
    def entity_picture(self) -> str | None:
        """Cache-bust URL based on selected entry + data hash."""
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        import hashlib
        import json
        render = self.coordinator._wifi_render_entry
        if render is not None:
            key = f"{render[0]}:{render[1]}"
        else:
            active = self.coordinator._active_map_id
            key = f"active:{active}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = super().entity_picture
        if base is None:
            return None
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token whenever selection or data changes."""
        render = self.coordinator._wifi_render_entry
        decoded = self._resolve_decoded()
        cur = (render, id(decoded))
        if cur != getattr(self, "_last_seen_key", None):
            self._last_seen_key = cur
            self.async_update_token()
        super()._handle_coordinator_update()
```

- [ ] **Step 4: Update `async_setup_entry` in `camera.py`**

The entity class name stays `DreameA2WifiSelectedCamera`. Only the translation key changes (from `wifi_selected` to `wifi_heatmap_selected`) — that's handled by the class attribute update above. No `async_setup_entry` change needed.

Verify the existing line is still correct:

```bash
grep -n "DreameA2WifiSelectedCamera" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/camera.py
```

Expected: one definition class, one instantiation in `async_setup_entry`.

- [ ] **Step 5: Run camera tests**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/test_wifi_selected_camera.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Run full integration suite**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/integration/ -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/camera.py \
        tests/integration/test_wifi_selected_camera.py
git commit -m "feat: update DreameA2WifiSelectedCamera to use _wifi_render_entry (archive-based)"
```

---

## Task 5: Update translations

**Files:**
- Modify: `custom_components/dreame_a2_mower/translations/en.json`

- [ ] **Step 1: Update translations**

Open `translations/en.json`. Under `entity.select`, the current state is:

```json
"wifi_view": {
  "name": "WiFi view"
}
```

Replace `wifi_view` with `wifi_archive`:

```json
"wifi_archive": {
  "name": "WiFi archive"
}
```

Under `entity.camera`, the current state is:

```json
"wifi_selected": {
  "name": "WiFi heatmap (selected)"
}
```

Replace `wifi_selected` with `wifi_heatmap_selected`:

```json
"wifi_heatmap_selected": {
  "name": "WiFi heatmap (selected)"
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -c "import json; json.load(open('custom_components/dreame_a2_mower/translations/en.json'))" && echo "OK"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/translations/en.json
git commit -m "feat: update translations — wifi_archive select + wifi_heatmap_selected camera"
```

---

## Task 6: Update helpers reference doc and dashboard

**Files:**
- Modify: `docs/superpowers/helpers/dreame-a2-helpers.yaml`
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Add new `input_boolean` helpers to the helpers doc**

In `docs/superpowers/helpers/dreame-a2-helpers.yaml`, append after the existing `input_number` block:

```yaml
input_boolean:
  dreame_a2_mower_wifi_show_base:
    name: WiFi overlay — show base map
    initial: true
    icon: mdi:image
  dreame_a2_mower_wifi_flip_x:
    name: WiFi overlay — flip X
    initial: false
    icon: mdi:flip-horizontal
  dreame_a2_mower_wifi_flip_y:
    name: WiFi overlay — flip Y
    initial: false
    icon: mdi:flip-vertical
```

- [ ] **Step 2: Rewrite the WiFi Coverage view in dashboard.yaml**

Find the WiFi Coverage view section (starts with `  - title: WiFi Coverage`, ends before `  - title: Sessions`). Replace the entire `cards:` block of that view with:

```yaml
    cards:
      - type: markdown
        content: |
          # WiFi heatmap
          Pick any heatmap from the archive. The viewer overlays it on
          the corresponding map's base snapshot. Adjust opacity, flip,
          or hide the base map with the controls below.

      - type: entities
        title: Viewer controls
        entities:
          - entity: select.dreame_a2_mower_wifi_archive
            name: Heatmap
          - entity: input_number.dreame_a2_mower_wifi_overlay_opacity
            name: Heatmap opacity
          - entity: input_boolean.dreame_a2_mower_wifi_show_base
            name: Show base map
          - entity: input_boolean.dreame_a2_mower_wifi_flip_x
            name: Flip X
          - entity: input_boolean.dreame_a2_mower_wifi_flip_y
            name: Flip Y
          - entity: sensor.dreame_a2_mower_wifi_map_last_refresh
            name: Last refresh

      # Base-map visible: overlay heatmap on top of base snapshot.
      - type: conditional
        conditions:
          - entity: input_boolean.dreame_a2_mower_wifi_show_base
            state: "on"
        card:
          type: picture-elements
          image_entity: camera.dreame_a2_mower_map
          elements:
            - type: image
              entity: camera.dreame_a2_mower_wifi_heatmap_selected
              image_entity: camera.dreame_a2_mower_wifi_heatmap_selected
              style:
                top: 50%
                left: 50%
                width: 100%
                height: 100%
              card_mod:
                style: |
                  :host {
                    opacity: {{ states('input_number.dreame_a2_mower_wifi_overlay_opacity') | float / 100 }};
                    transform:
                      scaleX({% if is_state('input_boolean.dreame_a2_mower_wifi_flip_x','on') %}-1{% else %}1{% endif %})
                      scaleY({% if is_state('input_boolean.dreame_a2_mower_wifi_flip_y','on') %}-1{% else %}1{% endif %});
                  }

      # Base-map hidden: show only the heatmap alone.
      - type: conditional
        conditions:
          - entity: input_boolean.dreame_a2_mower_wifi_show_base
            state: "off"
        card:
          type: picture-elements
          image_entity: camera.dreame_a2_mower_wifi_heatmap_selected
          elements: []
          card_mod:
            style: |
              ha-card {
                transform:
                  scaleX({% if is_state('input_boolean.dreame_a2_mower_wifi_flip_x','on') %}-1{% else %}1{% endif %})
                  scaleY({% if is_state('input_boolean.dreame_a2_mower_wifi_flip_y','on') %}-1{% else %}1{% endif %});
              }

      - type: horizontal-stack
        cards:
          - type: entities
            entities:
              - entity: button.dreame_a2_mower_request_wifi_map
                name: Refresh Map 1 from cloud
          - type: entities
            entities:
              - entity: button.map_2_refresh_wifi_map_view
                name: Refresh Map 2 from cloud
```

- [ ] **Step 3: Verify dashboard YAML is syntactically valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))" && echo "OK"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add docs/superpowers/helpers/dreame-a2-helpers.yaml \
        dashboards/mower/dashboard.yaml
git commit -m "feat: add wifi overlay helpers doc + rewrite WiFi Coverage dashboard view (F11)"
```

---

## Task 7: Run full test suite, bump version, push, release, SCP dashboard

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 1: Run the full test suite**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m pytest tests/ -q 2>&1 | tail -30
```

Expected: all tests pass (zero failures).

- [ ] **Step 2: Bump version**

Current version is `1.0.5a4`. F11 is a feature addition — bump to `1.0.5a5`.

In `custom_components/dreame_a2_mower/manifest.json`, change:

```json
  "version": "1.0.5a4"
```

to:

```json
  "version": "1.0.5a5"
```

- [ ] **Step 3: Commit version bump**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/manifest.json
git commit -m "chore: bump version to 1.0.5a5 (F11 wifi archive picker)"
```

- [ ] **Step 4: Push to origin/main**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git push origin main
```

- [ ] **Step 5: Create GitHub release**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git tag v1.0.5a5
git push origin v1.0.5a5
gh release create v1.0.5a5 --prerelease \
  --title "v1.0.5a5 — F11: WiFi cross-map archive picker + overlay controls" \
  --notes "## F11: WiFi archive picker + base-map overlay controls

### What's new
- Cross-map WiFi archive picker: \`select.dreame_a2_mower_wifi_archive\` lists all wifimap objects from cloud, labeled \`[Map N] YYYY-MM-DD HH:MM\`
- \`DreameA2WifiSelectedCamera\` renders the picked entry (any map, not just active)
- Dashboard WiFi Coverage view: opacity slider + X/Y flip + show/hide base map toggles
- Two new helpers required: \`input_boolean.dreame_a2_mower_wifi_show_base\`, \`input_boolean.dreame_a2_mower_wifi_flip_x\`, \`input_boolean.dreame_a2_mower_wifi_flip_y\` (see \`docs/superpowers/helpers/dreame-a2-helpers.yaml\`)

### Breaking changes
- \`select.dreame_a2_mower_wifi_view\` is removed; replaced by \`select.dreame_a2_mower_wifi_archive\`
- Old entity will remain as 'unavailable' in HA entity registry — remove it via Developer Tools → Entities or Settings → Devices
- New helpers must be added to \`configuration.yaml\` or via UI before the dashboard controls work
"
```

- [ ] **Step 6: SCP dashboard to HA**

```bash
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no \
    /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
    root@10.0.0.30:/config/dashboards/mower/dashboard.yaml
```

Expected: no error output, command exits 0.

- [ ] **Step 7: Reload HA config entry**

```bash
sshpass -p 'cex2vol' ssh -o StrictHostKeyChecking=no root@10.0.0.30 \
  "curl -s -X POST http://localhost:8123/api/config/config_entries/entry/$(
    curl -s -H 'Authorization: Bearer '"$(cat /data/claude/homeassistant/ha-dreame-a2-mower/.ha_token 2>/dev/null || echo MISSING)"' \
      http://localhost:8123/api/config/config_entries | python3 -c \
      'import json,sys; entries=json.load(sys.stdin); print(next(e[\"entry_id\"] for e in entries if \"dreame\" in e[\"domain\"]))'
  )/reload" 2>&1 | head -5 || echo "Manual reload: Developer Tools → Server Controls → Check Configuration + Reload"
```

If the token file doesn't exist, reload manually via HA UI: Developer Tools → YAML → Reload All.

---

## Self-Review Against Spec

### Spec coverage check

| Spec requirement | Covered by |
|-----------------|-----------|
| `cloud_client.list_wifi_candidates()` with geometry matching | Task 1 |
| `coordinator.list_wifi_archive_entries()` | Task 2 |
| `coordinator._wifi_render_entry` + `set_wifi_render_entry()` | Task 2 |
| `DreameA2WifiArchiveSelect` with `[Map N] timestamp` labels | Task 3 |
| `[Unknown map]` label for unmatched candidates | Task 3 + Tests |
| Drop `_wifi_view_map_id`, `set_wifi_view_map_id`, `DreameA2WifiViewSelect` | Tasks 2+3 |
| `DreameA2WifiSelectedCamera` uses `_wifi_render_entry` | Task 4 |
| `available` reflects picked entry's data | Task 4 |
| `entity_picture` cache-bust includes entry content hash | Task 4 |
| Translations: `wifi_archive` + `wifi_heatmap_selected` | Task 5 |
| 3 new `input_boolean` helpers in helpers doc | Task 6 |
| Dashboard: opacity, flip-x, flip-y, show-base controls | Task 6 |
| Dashboard: two-conditional-card pattern for show_base toggle | Task 6 |
| Refresh buttons preserved | Task 6 |
| Tests: geometry match, label format, setter, camera render | Tasks 1+3+4 |
| Commit + push + release + SCP | Task 7 |

### Placeholder scan

No TBD, TODO, or "fill in details" entries found.

### Type consistency

- `_wifi_render_entry: tuple[int, str] | None` — used consistently in Task 2 (coordinator), Task 3 (select), Task 4 (camera).
- `list_wifi_archive_entries() -> list[dict]` — defined in Task 2, consumed in Task 3 (`_rebuild_options`) and tests.
- `set_wifi_render_entry(map_id: int | None, object_name: str | None)` — defined in Task 2, called in Task 3.
- `list_wifi_candidates(map_extents: dict) -> list[dict]` — defined in Task 1, called in Task 2.
- `_wifi_map_by_id` keyed by both `int` (map_id, legacy) and `str` (object_name, new) — `_resolve_decoded()` in Task 4 tries both.
