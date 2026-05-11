# WiFi Heatmap Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live-cloud-snapshot WiFi heatmap model with a disk-backed archive (one file per unique cloud `object_name`), a canonical-orientation renderer (+X right, +Y up), and `[Map ?]` honest labels.

**Architecture:** A new `wifi_archive_store.py` module owns disk I/O. The coordinator's `refresh_wifi_archive()` method drives append-only archiving. The picker, camera, and renderer read from the archive index in memory (sourced from disk). Flip-X / Flip-Y toggles move from CSS to data-layer via input_boolean state reads in the camera's image handler. The Refresh-All button calls `refresh_wifi_archive()` directly instead of the per-map path.

**Tech Stack:** Python 3.13 / Home Assistant custom_component, paho-mqtt, requests, PIL/Pillow, pytest.

---

## File Structure

**Files to create:**
- `custom_components/dreame_a2_mower/wifi_archive_store.py` — disk store: read/write index + object files, dedup by `object_name`.
- `tests/protocol/test_wifi_archive_store.py` — store unit tests.
- `tests/integration/test_wifi_archive_refresh.py` — `refresh_wifi_archive` end-to-end test.
- `tests/integration/test_wifi_renderer_orientation.py` — canonical orientation + Flip-X/Y escape-hatch tests.

**Files to modify:**
- `custom_components/dreame_a2_mower/coordinator.py` — add `_wifi_archive_index`, `refresh_wifi_archive`, deprecate `_wifi_archive_cache`.
- `custom_components/dreame_a2_mower/select.py` — `DreameA2WifiArchiveSelect` reads from index, always labels `[Map ?]`.
- `custom_components/dreame_a2_mower/camera.py` — `DreameA2WifiSelectedCamera` reads flip toggles, subscribes to state changes.
- `custom_components/dreame_a2_mower/wifi_map_render.py` — canonical orientation; `flip_x` / `flip_y` parameters that invert the default.
- `custom_components/dreame_a2_mower/button.py` — `DreameA2RefreshAllWifiButton.async_press` calls `refresh_wifi_archive` directly.
- `dashboards/mower/dashboard.yaml` — relabel Flip-X / Flip-Y as "override" toggles.
- `custom_components/dreame_a2_mower/manifest.json` — version bump.

---

## Task 1: Disk archive store primitives

**Goal:** A small module that owns `wifi_archive/` directory and the `index.json` file. No coordinator coupling; pure file I/O + dataclasses.

**Files:**
- Create: `custom_components/dreame_a2_mower/wifi_archive_store.py`
- Test: `tests/protocol/test_wifi_archive_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/protocol/test_wifi_archive_store.py
"""Tests for wifi_archive_store: disk-backed wifimap archive."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.wifi_archive_store import (
    WifiArchiveStore,
    WifiArchiveEntry,
)


def test_load_empty_returns_empty_list(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert store.load_index() == []


def test_write_then_load_round_trip(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50] * 16, "width": 4, "height": 4, "resolution": 2,
            "startX": 100, "startY": 200}
    entry = store.archive(
        object_name="wifimap_1700000001.json",
        body=body,
        first_seen_unix=1747000000,
    )
    assert entry.object_name == "wifimap_1700000001.json"
    assert entry.unix_ts == 1700000001
    assert entry.width == 4 and entry.height == 4 and entry.resolution == 2
    assert entry.startX == 100 and entry.startY == 200
    assert entry.first_seen_unix == 1747000000

    loaded = store.load_index()
    assert len(loaded) == 1
    assert loaded[0].object_name == "wifimap_1700000001.json"

    body_loaded = store.load_body("wifimap_1700000001.json")
    assert body_loaded == body


def test_archive_is_idempotent(tmp_path: Path):
    """Calling archive() twice with the same object_name does NOT duplicate
    the index entry, and does NOT update first_seen_unix."""
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50], "width": 1, "height": 1, "resolution": 2,
            "startX": 0, "startY": 0}
    store.archive("wifimap_1700000001.json", body, first_seen_unix=100)
    store.archive("wifimap_1700000001.json", body, first_seen_unix=999)
    loaded = store.load_index()
    assert len(loaded) == 1
    assert loaded[0].first_seen_unix == 100  # original wins


def test_has_object(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert not store.has_object("wifimap_1.json")
    store.archive("wifimap_1.json",
                  {"data": [], "width": 0, "height": 0, "resolution": 2,
                   "startX": 0, "startY": 0},
                  first_seen_unix=0)
    assert store.has_object("wifimap_1.json")


def test_load_body_unknown_returns_none(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert store.load_body("never_archived.json") is None


def test_parse_unix_ts_from_filename(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    # Standard pattern.
    assert store._parse_unix_ts("wifimap_1700000001.json") == 1700000001
    # Trailing extra suffix.
    assert store._parse_unix_ts("wifimap_1700000001_v2.json") == 1700000001
    # Garbage name.
    assert store._parse_unix_ts("not_a_wifimap.json") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/protocol/test_wifi_archive_store.py -v`
Expected: `ModuleNotFoundError: No module named '...wifi_archive_store'`

- [ ] **Step 3: Implement the store module**

```python
# custom_components/dreame_a2_mower/wifi_archive_store.py
"""Disk-backed archive of cloud-side WiFi heatmap (wifimap) objects.

The cloud's OBJ probe returns OSS object names that embed a unix
timestamp (e.g., ``wifimap_1700000001.json``). The store keeps one
file per unique ``object_name`` plus an ``index.json`` that mirrors
the per-entry metadata for fast picker rebuilds.

Dedup: ``object_name`` is unique per cloud-side generation, so
"already on disk?" is a sufficient identity check. No content hash.

Path layout:

    /config/dreame_a2_mower/wifi_archive/
        index.json
        wifimap_1700000001.json
        wifimap_1700000002.json
        ...
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


_TS_RE = re.compile(r"_(\d{9,11})(?:[._]|$)")
_INDEX_NAME = "index.json"


@dataclass(frozen=True)
class WifiArchiveEntry:
    object_name: str
    unix_ts: int
    width: int
    height: int
    resolution: int
    startX: int
    startY: int
    first_seen_unix: int


class WifiArchiveStore:
    """Owns ``wifi_archive/`` and ``index.json`` for one device."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def index_path(self) -> Path:
        return self._root / _INDEX_NAME

    def has_object(self, object_name: str) -> bool:
        return (self._root / object_name).is_file()

    def load_index(self) -> list[WifiArchiveEntry]:
        if not self.index_path.is_file():
            return []
        try:
            raw = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[WifiArchiveEntry] = []
        for r in raw:
            try:
                out.append(WifiArchiveEntry(**r))
            except TypeError:
                continue
        return out

    def load_body(self, object_name: str) -> dict[str, Any] | None:
        body_path = self._root / object_name
        if not body_path.is_file():
            return None
        try:
            raw = json.loads(body_path.read_text())
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def archive(
        self,
        object_name: str,
        body: dict[str, Any],
        first_seen_unix: int,
    ) -> WifiArchiveEntry:
        """Write the body to disk and append to the index (idempotent)."""
        existing = {e.object_name: e for e in self.load_index()}
        if object_name in existing:
            return existing[object_name]
        body_path = self._root / object_name
        body_path.write_text(json.dumps(body))
        entry = WifiArchiveEntry(
            object_name=object_name,
            unix_ts=self._parse_unix_ts(object_name),
            width=int(body.get("width", 0)),
            height=int(body.get("height", 0)),
            resolution=int(body.get("resolution", 0)),
            startX=int(body.get("startX", 0)),
            startY=int(body.get("startY", 0)),
            first_seen_unix=first_seen_unix,
        )
        all_entries = list(existing.values()) + [entry]
        self.index_path.write_text(
            json.dumps([asdict(e) for e in all_entries], indent=2)
        )
        return entry

    @staticmethod
    def _parse_unix_ts(object_name: str) -> int:
        m = _TS_RE.search(object_name)
        return int(m.group(1)) if m else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/protocol/test_wifi_archive_store.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/wifi_archive_store.py tests/protocol/test_wifi_archive_store.py
git commit -m "feat(wifi): disk-backed wifimap archive store"
```

---

## Task 2: Coordinator integration — `_wifi_archive_index` + `refresh_wifi_archive`

**Goal:** The coordinator owns one `WifiArchiveStore`, loads the index on startup, and exposes `refresh_wifi_archive()` which fetches all cloud objects and archives new ones.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Test: `tests/integration/test_wifi_archive_refresh.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_wifi_archive_refresh.py
"""Tests for coordinator.refresh_wifi_archive end-to-end."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "wifi_archive"


async def _run_refresh(coord_klass, store_root: Path, cloud_objects: list[dict]):
    """Build a minimal coordinator-like object, run refresh_wifi_archive."""
    coord = object.__new__(coord_klass)
    coord._wifi_archive_store = WifiArchiveStore(store_root)
    coord._wifi_archive_index = []
    coord._cloud = MagicMock()
    coord._cloud.list_wifi_candidates = MagicMock(
        return_value=cloud_objects
    )
    coord._cloud.get_interim_file_url = MagicMock(
        side_effect=lambda name: f"https://oss/{name}"
    )
    coord._cloud.get_file = MagicMock(
        side_effect=lambda url: json.dumps(
            {"data": [-50] * 16, "width": 4, "height": 4, "resolution": 2,
             "startX": 0, "startY": 0}
        ).encode()
    )
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    coord.async_update_listeners = MagicMock()
    summary = await coord.refresh_wifi_archive()
    return coord, summary


@pytest.mark.asyncio
async def test_refresh_archives_new_objects(store_root: Path):
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_objects = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
        {"object_name": "wifimap_1700000002.json", "unix_ts": 1700000002,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, summary = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_objects
    )
    assert summary["fetched"] == 2
    assert summary["new"] == 2
    assert summary["archive_total"] == 2
    # Files written.
    assert (store_root / "wifimap_1700000001.json").is_file()
    assert (store_root / "wifimap_1700000002.json").is_file()
    # In-memory index mirrors disk.
    assert len(coord._wifi_archive_index) == 2


@pytest.mark.asyncio
async def test_refresh_is_idempotent(store_root: Path):
    """Two refreshes with the same cloud state → no duplicates."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    cloud_objects = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, _ = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_objects
    )
    # Re-run (manually, no re-instantiation — same coord + store).
    coord._cloud.list_wifi_candidates.return_value = cloud_objects
    summary2 = await coord.refresh_wifi_archive()
    assert summary2["fetched"] == 1
    assert summary2["new"] == 0
    assert summary2["archive_total"] == 1


@pytest.mark.asyncio
async def test_refresh_keeps_cloud_garbage_collected_entries(store_root: Path):
    """If cloud drops an object that's already archived, archive keeps it."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    # First refresh: 2 objects.
    cloud_first = [
        {"object_name": "wifimap_1700000001.json", "unix_ts": 1700000001,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
        {"object_name": "wifimap_1700000002.json", "unix_ts": 1700000002,
         "map_id": None, "startX": 0, "startY": 0,
         "width": 4, "height": 4, "resolution": 2},
    ]
    coord, _ = await _run_refresh(
        DreameA2MowerCoordinator, store_root, cloud_first
    )
    # Second refresh: cloud only returns one.
    coord._cloud.list_wifi_candidates.return_value = cloud_first[:1]
    await coord.refresh_wifi_archive()
    # Both still archived.
    assert len(coord._wifi_archive_index) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_wifi_archive_refresh.py -v`
Expected: `AttributeError: 'DreameA2MowerCoordinator' object has no attribute 'refresh_wifi_archive'`

- [ ] **Step 3: Add `refresh_wifi_archive` + state init to the coordinator**

In `custom_components/dreame_a2_mower/coordinator.py`, add the import near the existing imports:

```python
from .wifi_archive_store import WifiArchiveStore, WifiArchiveEntry
```

In the coordinator's `__init__`, near the existing `_wifi_archive_cache = []` line (line 664), replace that line with:

```python
self._wifi_archive_store: WifiArchiveStore | None = None  # initialised in async_setup
self._wifi_archive_index: list[WifiArchiveEntry] = []
```

In whichever async-setup method initialises per-config-entry paths (search for `_lidar_archive_root` initialisation in the same file — wifi archive root follows the same pattern):

```python
import time as _time
from pathlib import Path
config_root = Path(self.hass.config.path("dreame_a2_mower"))
self._wifi_archive_store = WifiArchiveStore(config_root / "wifi_archive")
self._wifi_archive_index = self._wifi_archive_store.load_index()
```

Add the new method near `_refresh_wifi_map` (currently around line 1507):

```python
async def refresh_wifi_archive(self) -> dict:
    """Fetch all cloud wifimap objects and archive new ones to disk.

    Idempotent: objects already on disk are skipped. Returns:
        {"fetched": int, "new": int, "archive_total": int}
    """
    import time as _time

    if self._wifi_archive_store is None or not hasattr(self, "_cloud"):
        return {"fetched": 0, "new": 0, "archive_total": 0}

    extents = self._build_map_extents()
    candidates = await self.hass.async_add_executor_job(
        lambda: self._cloud.list_wifi_candidates(map_extents=extents)
    )
    if not isinstance(candidates, list):
        candidates = []

    new_count = 0
    now_ts = int(_time.time())
    for cand in candidates:
        obj_name = cand.get("object_name")
        if not isinstance(obj_name, str):
            continue
        if self._wifi_archive_store.has_object(obj_name):
            continue
        # Download + archive.
        body = await self.hass.async_add_executor_job(
            self._download_and_archive_wifi, obj_name, now_ts
        )
        if body is not None:
            new_count += 1

    # Refresh in-memory mirror + notify listeners.
    self._wifi_archive_index = self._wifi_archive_store.load_index()
    self.async_update_listeners()

    return {
        "fetched": len(candidates),
        "new": new_count,
        "archive_total": len(self._wifi_archive_index),
    }


def _download_and_archive_wifi(
    self, object_name: str, first_seen_unix: int
) -> dict | None:
    """Executor-side: download body from OSS and write to disk."""
    url = self._cloud.get_interim_file_url(object_name)
    if not url:
        return None
    raw = self._cloud.get_file(url)
    if not raw:
        return None
    try:
        import json as _json
        body = _json.loads(raw)
    except Exception:
        return None
    if not isinstance(body, dict) or "data" not in body:
        return None
    self._wifi_archive_store.archive(object_name, body, first_seen_unix)
    return body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_wifi_archive_refresh.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_wifi_archive_refresh.py
git commit -m "feat(wifi): coordinator.refresh_wifi_archive writes new heatmaps to disk"
```

---

## Task 3: Picker — read from archive index, `[Map ?]` labels

**Goal:** `DreameA2WifiArchiveSelect` reads from `coordinator._wifi_archive_index` (not `_wifi_archive_cache`), and labels every entry `[Map ?]` regardless of any inferred `map_id`.

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py:1585-1690`
- Test: `tests/integration/test_wifi_archive_select.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_wifi_archive_select.py`:

```python
def test_wifi_archive_select_labels_always_map_unknown():
    """Every label is [Map ?] regardless of any inferred map_id from the entry."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry
    from unittest.mock import MagicMock

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="wifimap_1700000001.json",
            unix_ts=1700000001,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=1747000000,
        ),
        WifiArchiveEntry(
            object_name="wifimap_1700000002.json",
            unix_ts=1700000002,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=1747000000,
        ),
    ]
    coord._wifi_render_entry = None
    ent = DreameA2WifiArchiveSelect(coord)
    ent._rebuild_options()
    for opt in ent._attr_options:
        assert opt.startswith("[Map ?] "), f"label {opt!r} missing [Map ?] prefix"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_wifi_archive_select.py::test_wifi_archive_select_labels_always_map_unknown -v`
Expected: failure — either `AttributeError: _wifi_archive_index` (coordinator path) or label-format mismatch.

- [ ] **Step 3: Update `DreameA2WifiArchiveSelect`**

In `custom_components/dreame_a2_mower/select.py`, replace `_format_option` and `_rebuild_options`:

```python
@staticmethod
def _format_option(entry) -> str:
    """Always label '[Map ?] YYYY-MM-DD HH:MM' — correlation unsolved."""
    from datetime import datetime, timezone
    ts = entry.unix_ts if hasattr(entry, "unix_ts") else entry.get("unix_ts", 0)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return f"[Map ?] {dt:%Y-%m-%d %H:%M}"

def _rebuild_options(self) -> None:
    entries = list(self.coordinator._wifi_archive_index)
    # Sort newest-first by unix_ts.
    entries.sort(
        key=lambda e: getattr(e, "unix_ts", 0),
        reverse=True,
    )
    opts = [self._format_option(e) for e in entries]
    label_map: dict[str, object] = {}
    for e, label in zip(entries, opts):
        label_map[label] = e
    if not opts:
        opts = [self._placeholder]
    render = self.coordinator._wifi_render_entry
    cur: str
    if render is None:
        cur = opts[0]
    else:
        _, selected_obj = render
        cur = self._placeholder
        for label, entry in label_map.items():
            name = getattr(entry, "object_name", None)
            if name == selected_obj:
                cur = label
                break
    self._attr_options = opts
    self._label_to_entry = label_map
    self._attr_current_option = cur if cur in opts else opts[0]
```

Also update `async_select_option` to use attribute access:

```python
async def async_select_option(self, option: str) -> None:
    if option == self._placeholder:
        self.coordinator.set_wifi_render_entry(None, None)
        self._attr_current_option = option
        self.async_write_ha_state()
        return
    entry = self._label_to_entry.get(option)
    if entry is None:
        self._rebuild_options()
        entry = self._label_to_entry.get(option)
    if entry is not None:
        obj_name = getattr(entry, "object_name", None)
        # map_id intentionally None — correlation unsolved.
        self.coordinator.set_wifi_render_entry(None, obj_name)
        self._attr_current_option = option
        self.async_write_ha_state()
        return
    LOGGER.warning("WifiArchiveSelect: unknown option %r", option)
```

- [ ] **Step 4: Run all wifi-archive tests to verify they pass**

Run: `python -m pytest tests/integration/test_wifi_archive_select.py -v`
Expected: all tests pass (existing ones still work; new one passes).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py tests/integration/test_wifi_archive_select.py
git commit -m "feat(wifi): picker reads from archive index, labels [Map ?]"
```

---

## Task 4: Renderer — canonical orientation + flip parameters

**Goal:** `render_wifi_map_png` draws cell `(col, row)` at image pixel `(col, h-1-row)` so row 0 = image-bottom (= min Y); inverted from the current double-flip. Add `flip_x` / `flip_y` params that invert each default axis.

**Files:**
- Modify: `custom_components/dreame_a2_mower/wifi_map_render.py:67-114`
- Test: `tests/integration/test_wifi_renderer_orientation.py` (new)

Note the spec's coordinate convention: cell `(col, row)` → image `(col, h-1-row)`. But empirically the user reports needing Flip-Y today, and the current renderer reverses BOTH axes. Reconciling: cloud convention is array index 0 = MAX coordinate on both axes. To get canonical (+X right, +Y up, image-top = max Y):
- **Y default:** read `src_row = row` (image row 0 = array row 0 = max Y = image-top). ✓
- **X default:** read `src_col = (w - 1) - col` (image col 0 = array col w-1 = min X = image-left). ✓
- **Flip Y ON (escape hatch):** invert → `src_row = (h - 1) - row`.
- **Flip X ON (escape hatch):** invert → `src_col = col`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_wifi_renderer_orientation.py
"""Tests for wifi_map_render canonical orientation + flip toggles."""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from custom_components.dreame_a2_mower.wifi_map_render import (
    CELL_PX,
    render_wifi_map_png,
)


def _decode_png(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGBA")


def _make_decoded(w: int, h: int, marker_row: int, marker_col: int) -> dict:
    """Build a wifi-map dict where one cell at (marker_col, marker_row) is
    a distinct RSSI value; all other cells are 'no data' (sentinel 1)."""
    data = [1] * (w * h)
    data[marker_row * w + marker_col] = -50  # strongest = full green
    return {"data": data, "width": w, "height": h, "resolution": 2,
            "startX": 0, "startY": 0}


def _green_cell_position(img: Image.Image) -> tuple[int, int]:
    """Return (col, row) of the centre-of-cell that is mostly green."""
    w, h = img.size
    cells_w = w // CELL_PX
    cells_h = h // CELL_PX
    for cr in range(cells_h):
        for cc in range(cells_w):
            px = img.getpixel((cc * CELL_PX + CELL_PX // 2,
                               cr * CELL_PX + CELL_PX // 2))
            r, g, b, _a = px
            if g > 200 and r < 100:
                return cc, cr
    raise AssertionError("no green cell found in image")


def test_canonical_orientation_row0_at_image_top():
    """Cell at array (col=3, row=0) appears at image (col=0, row=0) (top-left).

    Because X is reversed: array col 0 = image right; array col w-1 = image left.
    So array col 3 in a w=4 grid maps to image col 0.
    """
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (0, 0), (
        f"expected (0, 0), got ({cc}, {cr})"
    )


def test_canonical_orientation_col0_at_image_right():
    """Cell at array (col=0, row=0) appears at image (col=3, row=0)
    (top-right) in a w=4 grid because X is reversed by default."""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=0)
    png = render_wifi_map_png(decoded)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 0)


def test_flip_y_inverts_row_mapping():
    """With flip_y=True, array (col=3, row=0) appears at image bottom-left,
    not top-left. (h=3 → image row index 2.)"""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_y=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (0, 2)


def test_flip_x_inverts_column_mapping():
    """With flip_x=True, array (col=3, row=0) appears at image top-right
    (col=3) because X is no longer reversed."""
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_x=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 0)


def test_flip_both_inverts_both_axes():
    decoded = _make_decoded(w=4, h=3, marker_row=0, marker_col=3)
    png = render_wifi_map_png(decoded, flip_x=True, flip_y=True)
    img = _decode_png(png)
    cc, cr = _green_cell_position(img)
    assert (cc, cr) == (3, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_wifi_renderer_orientation.py -v`
Expected: failures — `render_wifi_map_png` doesn't accept `flip_x` / `flip_y` kwargs, and at least one orientation assertion fails (current double-flip).

- [ ] **Step 3: Update the renderer**

Replace `render_wifi_map_png` in `custom_components/dreame_a2_mower/wifi_map_render.py`:

```python
def render_wifi_map_png(
    decoded: dict[str, Any],
    flip_x: bool = False,
    flip_y: bool = False,
) -> bytes | None:
    """Return PNG bytes for the wifi map, or None on bad input.

    Canonical orientation: image-top = array row 0 (= max Y in cloud
    frame); image-right = array col 0 (= max X). Cloud convention is
    array index 0 = max coordinate on both axes, so default rendering
    reverses X (col → w-1-col) but NOT Y (row → row).

    `flip_x` / `flip_y` invert each axis from its canonical default,
    as escape hatches for firmware variants whose convention differs.
    """
    width = decoded.get("width")
    height = decoded.get("height")
    data = decoded.get("data")
    if not (isinstance(width, int) and isinstance(height, int) and isinstance(data, list)):
        return None
    if len(data) != width * height:
        return None
    if width <= 0 or height <= 0:
        return None

    img = Image.new("RGBA", (width * CELL_PX, height * CELL_PX), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
    except Exception:
        font = None

    for row in range(height):
        for col in range(width):
            # Y default: image row = array row (no reversal).
            src_row = (height - 1) - row if flip_y else row
            # X default: image col 0 = array col w-1 (reversed).
            src_col = col if flip_x else (width - 1) - col
            rssi = data[src_row * width + src_col]
            colour = _rssi_to_rgb(rssi)
            if colour[3] == 0:
                continue
            x0 = col * CELL_PX
            y0 = row * CELL_PX
            draw.rectangle((x0, y0, x0 + CELL_PX - 1, y0 + CELL_PX - 1), fill=colour)
            if font is not None:
                draw.text((x0 + 4, y0 + 4), str(rssi), fill=(0, 0, 0, 255), font=font)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
```

- [ ] **Step 4: Run renderer tests to verify they pass**

Run: `python -m pytest tests/integration/test_wifi_renderer_orientation.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/wifi_map_render.py tests/integration/test_wifi_renderer_orientation.py
git commit -m "feat(wifi): canonical orientation renderer; flip toggles as escape hatch"
```

---

## Task 5: Camera — read flip toggles, subscribe to state changes

**Goal:** `DreameA2WifiSelectedCamera` reads from the archive store via `coordinator._wifi_archive_store.load_body(object_name)`, reads flip toggle states from `input_boolean.dreame_a2_mower_wifi_flip_x` / `_flip_y`, and re-renders + busts the entity-picture cache when those input_booleans change.

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py:622-715`
- Test: `tests/integration/test_wifi_selected_camera.py` (existing — add cases)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_wifi_selected_camera.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_camera_with_flips(flip_x: bool, flip_y: bool):
    """Build a DreameA2WifiSelectedCamera with a mocked hass.states."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_render_entry = (None, "wifimap_1700000001.json")
    coord._wifi_archive_store = MagicMock()
    coord._wifi_archive_store.load_body = MagicMock(
        return_value={"data": [-50] * 16, "width": 4, "height": 4,
                      "resolution": 2, "startX": 0, "startY": 0}
    )
    cam = DreameA2WifiSelectedCamera(coord)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args, **kw: fn(*args, **kw)
    )
    def _is_state(eid: str, val: str) -> bool:
        if eid == "input_boolean.dreame_a2_mower_wifi_flip_x":
            return val == ("on" if flip_x else "off")
        if eid == "input_boolean.dreame_a2_mower_wifi_flip_y":
            return val == ("on" if flip_y else "off")
        return False
    cam.hass.states.is_state = _is_state
    return cam, coord


def test_camera_reads_archive_body_via_store():
    cam, coord = _make_camera_with_flips(flip_x=False, flip_y=False)
    decoded = cam._resolve_decoded()
    assert decoded is not None
    coord._wifi_archive_store.load_body.assert_called_with(
        "wifimap_1700000001.json"
    )


def test_camera_passes_flip_kwargs_to_renderer():
    cam, _ = _make_camera_with_flips(flip_x=True, flip_y=False)
    with patch("custom_components.dreame_a2_mower.camera.render_wifi_map_png") as mock_r:
        mock_r.return_value = b"\x89PNG..."
        asyncio.get_event_loop().run_until_complete(cam.async_camera_image())
        call = mock_r.call_args
        # render_wifi_map_png(decoded, flip_x=True, flip_y=False)
        assert call.kwargs.get("flip_x") is True
        assert call.kwargs.get("flip_y") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_wifi_selected_camera.py -v`
Expected: failures — camera doesn't call store, doesn't pass flip kwargs.

- [ ] **Step 3: Update the camera**

In `custom_components/dreame_a2_mower/camera.py`, replace `_resolve_decoded` and `async_camera_image`:

```python
_FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
_FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"

def _resolve_decoded(self) -> dict | None:
    """Return decoded wifi map body for the selected entry."""
    render = self.coordinator._wifi_render_entry
    if render is None:
        return None
    _map_id, obj_name = render
    if not obj_name:
        return None
    store = getattr(self.coordinator, "_wifi_archive_store", None)
    if store is None:
        return None
    return store.load_body(obj_name)

async def async_camera_image(
    self, width: int | None = None, height: int | None = None
) -> bytes | None:
    decoded = self._resolve_decoded()
    if not decoded:
        return None
    flip_x = (
        self.hass is not None
        and self.hass.states.is_state(self._FLIP_X_ENTITY, "on")
    )
    flip_y = (
        self.hass is not None
        and self.hass.states.is_state(self._FLIP_Y_ENTITY, "on")
    )
    from .wifi_map_render import render_wifi_map_png
    return await self.hass.async_add_executor_job(
        lambda: render_wifi_map_png(decoded, flip_x=flip_x, flip_y=flip_y)
    )
```

Also subscribe to flip state changes in `async_added_to_hass`:

```python
async def async_added_to_hass(self) -> None:
    await super().async_added_to_hass()
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def _flip_changed(_event) -> None:
        self.async_update_token()
        self.async_write_ha_state()

    self.async_on_remove(
        async_track_state_change_event(
            self.hass, [self._FLIP_X_ENTITY, self._FLIP_Y_ENTITY], _flip_changed
        )
    )
```

Class-level constants need to be class attributes so the test references work:

```python
class DreameA2WifiSelectedCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    _FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
    _FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"
    # ... existing _attr_* lines ...
```

Move the file-scope `_FLIP_X_ENTITY` / `_FLIP_Y_ENTITY` declarations inside the class.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_wifi_selected_camera.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py tests/integration/test_wifi_selected_camera.py
git commit -m "feat(wifi): camera reads archive body + flip toggles at data layer"
```

---

## Task 6: Refresh button — call `refresh_wifi_archive` directly

**Goal:** `DreameA2RefreshAllWifiButton.async_press` calls `coordinator.refresh_wifi_archive()` (one call, archives all cloud objects). Drop the per-map loop.

**Files:**
- Modify: `custom_components/dreame_a2_mower/button.py:328-380`
- Test: `tests/integration/test_buttons.py` (search for existing button tests; if absent, create at this path)

- [ ] **Step 1: Write the failing test**

Append to or create `tests/integration/test_buttons.py`:

```python
"""Tests for the WiFi refresh-all button."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_refresh_wifi_button_calls_archive_refresh():
    from custom_components.dreame_a2_mower.button import DreameA2RefreshAllWifiButton

    coord = MagicMock()
    coord.refresh_wifi_archive = AsyncMock(
        return_value={"fetched": 2, "new": 1, "archive_total": 3}
    )
    btn = DreameA2RefreshAllWifiButton(coord)
    await btn.async_press()
    coord.refresh_wifi_archive.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_buttons.py::test_refresh_wifi_button_calls_archive_refresh -v`
Expected: failure — button still calls `_refresh_wifi_map` per-map, not `refresh_wifi_archive`.

- [ ] **Step 3: Update the button**

In `custom_components/dreame_a2_mower/button.py`, replace `DreameA2RefreshAllWifiButton.async_press`:

```python
async def async_press(self) -> None:
    LOGGER.info(
        "button.refresh_wifi_heatmaps: refreshing WiFi heatmap archive"
    )
    try:
        summary = await self.coordinator.refresh_wifi_archive()
        LOGGER.info(
            "button.refresh_wifi_heatmaps: fetched=%d new=%d archive_total=%d",
            summary["fetched"], summary["new"], summary["archive_total"],
        )
    except Exception as ex:
        LOGGER.warning("button.refresh_wifi_heatmaps: refresh failed: %s", ex)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_buttons.py -v`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/button.py tests/integration/test_buttons.py
git commit -m "feat(wifi): refresh-all button drives refresh_wifi_archive"
```

---

## Task 7: Dashboard — relabel toggles + verify card structure

**Goal:** Dashboard reflects the new model: flip toggles are escape hatches (relabeled), labels are honest, base-map overlay scaffold uses Map 1.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` (the WiFi tab section near lines 440-500)

- [ ] **Step 1: Read current WiFi tab structure**

Run: `grep -n "wifi_show_base\|wifi_flip\|wifi_opacity\|wifi_heatmap_selected" dashboards/mower/dashboard.yaml`
Note the entity_ids of the toggles and slider.

- [ ] **Step 2: Update toggle labels**

In `dashboards/mower/dashboard.yaml`, find the entities row in the WiFi tab that exposes Flip X / Flip Y / Show base / Opacity. Replace the toggle entries with:

```yaml
- entity: input_boolean.dreame_a2_mower_wifi_flip_x
  name: Flip X (override)
  icon: mdi:flip-horizontal
- entity: input_boolean.dreame_a2_mower_wifi_flip_y
  name: Flip Y (override)
  icon: mdi:flip-vertical
- entity: input_boolean.dreame_a2_mower_wifi_show_base
  name: Show base map (Map 1)
  icon: mdi:layers
```

(Leave `wifi_opacity` slider untouched.)

- [ ] **Step 3: Validate YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: no exception.

- [ ] **Step 4: SCP to HA box**

```bash
sshpass -p $(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt) \
  scp -o StrictHostKeyChecking=no \
  dashboards/mower/dashboard.yaml \
  root@$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt):/homeassistant/dashboards/mower/dashboard.yaml
```
Expected: silent success.

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(wifi): dashboard relabel flip toggles as override"
```

---

## Task 8: Remove dead path — `_refresh_wifi_map`, `_wifi_archive_cache`, `_wifi_map_by_id`

**Goal:** Now that the archive store owns persistence and the new refresh path is in place, drop the now-unused per-map refresh + in-memory caches.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (delete `_refresh_wifi_map`, `_wifi_archive_cache`, `_wifi_map_by_id`, and `list_wifi_archive_entries` if no remaining callers)
- Modify: `custom_components/dreame_a2_mower/button.py` (remove `DreameA2RequestWifiMapButton` if no longer registered; otherwise convert to no-op + entity_category=DIAGNOSTIC)

- [ ] **Step 1: Find remaining callers**

Run: `grep -rn "_refresh_wifi_map\|_wifi_archive_cache\|_wifi_map_by_id\|list_wifi_archive_entries" custom_components/ tests/`

Document the call sites. Any production caller that isn't the new path needs migrating before removal.

- [ ] **Step 2: Migrate or remove each caller**

For each caller printed in Step 1:
- If it's a test for the deprecated path, delete the test.
- If it's a production caller (e.g., another button entity), redirect it to `refresh_wifi_archive` or remove.

- [ ] **Step 3: Remove the dead methods + attributes**

In `coordinator.py`:
- Delete `_refresh_wifi_map` (around lines 1507-1600).
- Delete `_wifi_archive_cache` initialisation.
- Delete `_wifi_map_by_id` initialisation + all references.
- Delete `list_wifi_archive_entries` if Step 2 confirmed no callers.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass (no references to removed code).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/button.py
git commit -m "refactor(wifi): drop dead per-map refresh + in-memory caches"
```

---

## Task 9: Migration — async_migrate_entry for orphaned entities

**Goal:** Any per-map wifi-related entities removed in Task 8 leave orphans in the HA entity registry (see `feedback_entity_rename_orphan` — changing/removing a unique_id leaves "unavailable" entities). Add `async_migrate_entry` to remove them on next config-entry reload.

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py`

- [ ] **Step 1: Identify orphan unique_ids**

Run: `grep -n "wifi_map\|wifi_heatmap" custom_components/dreame_a2_mower/_devices.py custom_components/dreame_a2_mower/button.py custom_components/dreame_a2_mower/camera.py`

List the per-map unique_id patterns that are no longer registered.

- [ ] **Step 2: Add migration logic**

In `custom_components/dreame_a2_mower/__init__.py`, locate the existing `async_migrate_entry` (or add one if absent). Append:

```python
async def async_migrate_entry(hass, entry) -> bool:
    """Migrate config entries across versions.

    v1.0.5a9 → v1.0.6a1: remove orphan per-map WiFi entities that were
    folded into the single archive picker + single refresh button.
    """
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    orphan_prefixes = (
        # Per-map "request wifi map" buttons.
        ":wifi_map_request:",
        # Per-map heatmap cameras (replaced by camera.wifi_heatmap_selected).
        ":wifi_heatmap:",
    )
    for entity_id, entry_obj in list(reg.entities.items()):
        if entry_obj.config_entry_id != entry.entry_id:
            continue
        uid = entry_obj.unique_id or ""
        if any(p in uid for p in orphan_prefixes):
            reg.async_remove(entity_id)
    return True
```

Note: substitute the actual unique_id substrings observed in Step 1.

- [ ] **Step 3: Run integration tests**

Run: `python -m pytest tests/integration/ -q`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py
git commit -m "feat(wifi): migrate-entry removes per-map WiFi entity orphans"
```

---

## Task 10: Version bump + release

**Goal:** Cut v1.0.6a1 via the release script. (The patch-number bump escapes the `a9 → a10` HACS sort gotcha, per `feedback_hacs_version_ladder.md`.)

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 1: Bump the version**

Run: `tools/release.sh 1.0.6a1`
Expected output ends with:
```
✅ release v1.0.6a1 published cleanly.
   isLatest=true, isPrerelease=false, isDraft=false
```

- [ ] **Step 2: Verify HACS sees it**

Run: `gh api repos/{owner}/{repo}/releases/latest --jq .tag_name`
Expected: `v1.0.6a1`

- [ ] **Step 3: Reload config entry on HA**

```bash
TOKEN=$(sed -n '4p' /data/claude/homeassistant/ha-credentials.txt)
HOST=$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt)
ENTRY_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://${HOST}:8123/api/config/config_entries/entry" \
  | python3 -c "import json,sys;[print(e['entry_id']) for e in json.load(sys.stdin) if e['domain']=='dreame_a2_mower']")
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "http://${HOST}:8123/api/config/config_entries/entry/${ENTRY_ID}/reload"
```
Expected: `{"require_restart":false}` or `{}`.

- [ ] **Step 4: Verify on the live dashboard**

Open the WiFi tab in the HA UI. Verify:
- Refresh button is present.
- Picker shows `[Map ?] YYYY-MM-DD HH:MM` entries after pressing Refresh.
- Heatmap appears in canonical orientation (top of image = top of garden) with both flip toggles OFF.
- Flip-Y toggle inverts vertically.
- Flip-X toggle inverts horizontally.
- "Show base map (Map 1)" overlay still works with the opacity slider.

If any fail, document the gap and re-enter the relevant task. Once
verified, the plan is complete.

---

## Self-Review (against spec `2026-05-11-wifi-heatmap-archive-design.md`)

**Spec coverage:**
- Goal 1 (local archive on refresh) → Task 1 + Task 2 ✓
- Goal 2 (`[Map ?]` labels) → Task 3 ✓
- Goal 3 (canonical-orientation renderer) → Task 4 ✓
- Goal 4 (Map-1 base scaffold) → Task 7 (relabel only — overlay already in dashboard) ✓
- Out-of-scope items (resolution unit, trigger investigation, correlation, LiDAR work, retention cap) — confirmed not addressed; documented in spec.

**Components:**
- `wifi_archive/` on disk → Task 1 ✓
- `index.json` schema → Task 1 (matches `WifiArchiveEntry` dataclass exactly) ✓
- `coordinator.refresh_wifi_archive` → Task 2 ✓
- `select.wifi_archive` (always `[Map ?]`) → Task 3 ✓
- `camera.wifi_heatmap_selected` (canonical orientation + flip subscribe) → Task 5 ✓
- `button.refresh_wifi_heatmaps` → Task 6 ✓
- Dashboard relabels → Task 7 ✓
- Orphan migration → Task 9 ✓
- Version bump + release → Task 10 ✓

**Test coverage:**
- Archive dedup → Task 1 step 1, Task 2 step 1 ✓
- Archive append → Task 2 step 1 (`test_refresh_archives_new_objects`) ✓
- Archive persistence (read after write) → Task 1 step 1 ✓
- Renderer canonical Y orientation → Task 4 step 1 ✓
- Flip-Y escape hatch → Task 4 step 1 ✓
- Flip-X escape hatch → Task 4 step 1 ✓
- Picker label format → Task 3 step 1 ✓
- Picker rebuild on refresh → covered transitively via `test_refresh_archives_new_objects` + Task 3 tests ✓

**Type consistency:**
- `WifiArchiveEntry` dataclass field names match across Tasks 1, 2, 3 ✓
- Coordinator attribute names (`_wifi_archive_store`, `_wifi_archive_index`) used consistently ✓
- Renderer signature `render_wifi_map_png(decoded, flip_x=False, flip_y=False)` matches Task 4 implementation and Task 5 test expectations ✓
- Input_boolean entity_ids match between Task 5 (`_FLIP_X_ENTITY` / `_FLIP_Y_ENTITY`) and Task 7 dashboard YAML ✓
