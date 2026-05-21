# B4b — camera.py + map_render.py Splits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `camera.py` (962 LOC) into a thin platform entry + `_camera_*.py` siblings, and convert `map_render.py` (1283 LOC) into a `map_render/` package — both behavior-preserving (bodies move VERBATIM).

**Architecture:** `camera.py` keeps `async_setup_entry` (entity creation + 4 view registrations) and imports entity/view classes from domain-grouped siblings. `map_render.py` becomes a package whose modules follow the acyclic call graph geometry → base_map → {main_view, work_log, trail}, with `__init__.py` re-exporting the public surface so `from ..map_render import X` keeps working.

**Tech Stack:** Python 3, HA custom integration, Pillow, pytest. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-21-b4b-camera-maprender-splits-design.md`

**Context:** On branch `main`. Commit on `main` with `audit-b4b:` prefix, authored as the user, **no co-author trailer**. Do NOT push (user ships after, with explicit authorization). Full suite (`python -m pytest tests -q`) baseline ≈ **1591 passed, 4 skipped** (B3a) — Task 1 captures the exact current number. Refactor discipline (B1d/B2a/B3a lessons): **move bodies VERBATIM**; **prune imports only via per-name grep**, never by "tests pass"; **re-export only names a real caller imports**.

---

## File Structure

| File | Change |
|---|---|
| `custom_components/dreame_a2_mower/camera.py` | reduce to platform entry + re-export imports (T2) |
| `custom_components/dreame_a2_mower/_camera_map.py` | NEW — Map / PerMap / WorkLog cameras (T2) |
| `custom_components/dreame_a2_mower/_camera_lidar.py` | NEW — `_LidarCameraBase` + 3 LiDAR cameras (T2) |
| `custom_components/dreame_a2_mower/_camera_wifi.py` | NEW — 2 WiFi cameras (T2) |
| `custom_components/dreame_a2_mower/_camera_views.py` | NEW — 4 `HomeAssistantView` classes (T2) |
| `custom_components/dreame_a2_mower/map_render/__init__.py` | NEW — re-export public surface (T3) |
| `custom_components/dreame_a2_mower/map_render/_geometry.py` | NEW — geometry + shared consts (T3) |
| `custom_components/dreame_a2_mower/map_render/base_map.py` | NEW — base-map render (T3) |
| `custom_components/dreame_a2_mower/map_render/main_view.py` | NEW — main view + pre-start variants (T3) |
| `custom_components/dreame_a2_mower/map_render/work_log.py` | NEW — work-log render (T3) |
| `custom_components/dreame_a2_mower/map_render/trail.py` | NEW — trail render (T3) |
| `custom_components/dreame_a2_mower/map_render.py` | DELETE (replaced by package) (T3) |
| `CLAUDE.md` | add "Rendering structure" note (T4) |

---

### Task 1: Capture the baseline

- [ ] **Step 1: Run the full suite, record the numbers**

Run: `python -m pytest tests -q 2>&1 | tail -5`
Expected: a line like `1591 passed, 4 skipped`. Record the exact counts; T2/T3/T4 must keep them (no regressions). If the baseline is RED before any change, STOP and report — do not refactor onto a red suite.

---

### Task 2: Split `camera.py`

`camera.py` does not import `map_render`, so this task is independent of T3.

**Files:** create `_camera_map.py`, `_camera_lidar.py`, `_camera_wifi.py`, `_camera_views.py`; rewrite `camera.py`.

Source line ranges in the current `camera.py` (move VERBATIM — bodies unchanged):

| Class | Lines | → module |
|---|---|---|
| `DreameA2MapCamera` | 61–207 | `_camera_map.py` |
| `DreameA2PerMapCamera` | 208–252 | `_camera_map.py` |
| `DreameA2WorkLogCamera` | 253–324 | `_camera_map.py` |
| `_LidarCameraBase` | 325–376 | `_camera_lidar.py` |
| `DreameA2LidarTopDownCamera` | 377–395 | `_camera_lidar.py` |
| `DreameA2LidarTopDownFullCamera` | 396–414 | `_camera_lidar.py` |
| `DreameA2LidarSelectedCamera` | 415–503 | `_camera_lidar.py` |
| `DreameA2WifiSelectedCamera` | 504–630 | `_camera_wifi.py` |
| `DreameA2WifiPerMapCamera` | 631–752 | `_camera_wifi.py` |
| `MapImageView` | 753–824 | `_camera_views.py` |
| `WorkLogImageView` | 825–863 | `_camera_views.py` |
| `LidarSelectedPcdView` | 864–914 | `_camera_views.py` |
| `LidarPcdDownloadView` | 915–962 | `_camera_views.py` |

- [ ] **Step 1: Create the four sibling modules**

For each new module: add `from __future__ import annotations`, then the import lines from `camera.py`'s header that the moved classes actually use, then paste the class bodies VERBATIM. Available import sources (copy the subset each module needs; prune the rest with a per-name grep — see Step 4):

```python
import logging
from typing import Any
from aiohttp import web
from homeassistant.components.camera import Camera
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
```

Grouping is fixed by the table above:
- `_camera_map.py`: the 3 map-image cameras.
- `_camera_lidar.py`: `_LidarCameraBase` FIRST, then the 3 LiDAR cameras (two extend `_LidarCameraBase`; `DreameA2LidarSelectedCamera` extends `CoordinatorEntity[...]+Camera` directly but is grouped here).
- `_camera_wifi.py`: the 2 WiFi cameras.
- `_camera_views.py`: the 4 `HomeAssistantView` classes (these use `web`, `HomeAssistantView`, `DOMAIN`, and look up the coordinator from `hass`/`request`).

If any module-level helper/constant in `camera.py` (outside the classes) is referenced by a moved class, move it to the same module or, if shared across modules, leave it in `camera.py` and import it. Grep to confirm none is missed.

- [ ] **Step 2: Rewrite `camera.py` to the thin platform entry**

`camera.py` keeps only: `from __future__ import annotations`, the imports `async_setup_entry` needs (`logging` if used, `ConfigEntry`, `HomeAssistant`, `AddEntitiesCallback`, `Camera` for the `list[Camera]` hint, `DOMAIN`, `DreameA2MowerCoordinator`), the imports of the entity + view classes from the new siblings, and the `async_setup_entry` body VERBATIM (L22–57 of the current file — the view-registration guard + entity list + `async_add_entities`). Example head:

```python
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from ._camera_map import (
    DreameA2MapCamera,
    DreameA2PerMapCamera,
    DreameA2WorkLogCamera,
)
from ._camera_lidar import (
    DreameA2LidarSelectedCamera,
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
)
from ._camera_wifi import (
    DreameA2WifiPerMapCamera,
    DreameA2WifiSelectedCamera,
)
from ._camera_views import (
    LidarPcdDownloadView,
    LidarSelectedPcdView,
    MapImageView,
    WorkLogImageView,
)
```

These imports make every entity/view class an attribute of `camera.py`, preserving every `from …camera import X` in the test suite (see Step 3). `async_setup_entry` uses the entity classes + the 4 views exactly as before. No separate re-export block is needed; do NOT add `# noqa`-only re-exports for names already imported here.

- [ ] **Step 3: Confirm the test import surface is intact**

Tests import these names from `…camera` — all must resolve as `camera.py` attributes:
`DreameA2MapCamera`, `DreameA2PerMapCamera`, `DreameA2WorkLogCamera`,
`DreameA2LidarTopDownCamera`, `DreameA2LidarTopDownFullCamera`,
`DreameA2LidarSelectedCamera`, `DreameA2WifiSelectedCamera`,
`DreameA2WifiPerMapCamera`, `LidarSelectedPcdView`, `LidarPcdDownloadView`.
Run:
```bash
grep -rnE "from .*\.camera import|from custom_components.dreame_a2_mower.camera import" tests tools | sort
python -c "import importlib; m=importlib.import_module('custom_components.dreame_a2_mower.camera'); [getattr(m,n) for n in ['DreameA2MapCamera','DreameA2PerMapCamera','DreameA2WorkLogCamera','DreameA2LidarTopDownCamera','DreameA2LidarTopDownFullCamera','DreameA2LidarSelectedCamera','DreameA2WifiSelectedCamera','DreameA2WifiPerMapCamera','LidarSelectedPcdView','LidarPcdDownloadView','MapImageView','WorkLogImageView']]; print('all camera names resolve')"
```
Expected: the import succeeds and prints `all camera names resolve`. If a name a test imports is missing, add it to the relevant sibling import in `camera.py`.

- [ ] **Step 4: Prune unused imports per-name**

For EACH file (`camera.py` + the 4 siblings), for every imported name, grep that file for a real use; remove imports with zero uses. Do NOT rely on "tests pass" (B1d/B2a lesson — `callback`, `web`, `Any`, `logging` are easy to leave dangling or to over-remove). Example: `for n in logging Any web callback CoordinatorEntity map_device_info map_unique_id mower_device_info mower_unique_id; do echo "== $n =="; grep -c "$n" custom_components/dreame_a2_mower/_camera_map.py; done`

- [ ] **Step 5: Run camera tests, then the full suite**

Run: `python -m pytest tests/integration/test_per_map_cameras.py tests/integration/test_lidar_camera.py tests/integration/test_lidar_per_map.py tests/integration/test_lidar_view.py tests/integration/test_lidar_selected_view.py tests/integration/test_wifi_selected_camera.py tests/integration/test_work_log_camera.py tests/integration/test_main_view_render.py tests/integration/test_per_map_entity_names.py -q`
Expected: all pass.
Run: `python -m pytest tests -q 2>&1 | tail -3`
Expected: the Task-1 baseline counts, no regressions.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/_camera_map.py custom_components/dreame_a2_mower/_camera_lidar.py custom_components/dreame_a2_mower/_camera_wifi.py custom_components/dreame_a2_mower/_camera_views.py
git commit -m "audit-b4b: split camera.py into platform entry + _camera_{map,lidar,wifi,views}"
```

---

### Task 3: Convert `map_render.py` into a `map_render/` package

**Files:** create `map_render/` with `__init__.py`, `_geometry.py`, `base_map.py`, `main_view.py`, `work_log.py`, `trail.py`; DELETE `map_render.py`.

Source elements in the current `map_render.py` (move VERBATIM):

| Element | Lines | → module |
|---|---|---|
| `_DEFAULT_PALETTE` | 56–124 | `_geometry.py` |
| `_DOCK_RADIUS_PX` | 125 | `_geometry.py` |
| `_cloud_to_px` | 128–150 | `_geometry.py` |
| `_renderer_to_px` | 151–178 | `_geometry.py` |
| `extract_projection` | 1249–end | `_geometry.py` |
| `render_base_map` (+ nested `_composite_polygon`) | 179–~581 | `base_map.py` |
| `_OBSTACLE_FILL` / `_OBSTACLE_OUTLINE` | 589–590 | `base_map.py` |
| `_MOWER_ICON_SIZE_PX` / `_MOWER_ICON_CACHE` | 598, 601 | `base_map.py` |
| `_mower_icon` | 604–~618 | `base_map.py` |
| `STRIPE_WIDTH_MM` | 619 | `main_view.py` |
| `render_main_view` | 622–715 | `main_view.py` |
| `_render_pre_start_with_stripes` | 716–791 | `main_view.py` |
| `_render_pre_start_edge` | 792–821 | `main_view.py` |
| `_render_pre_start_spot` | 822–857 | `main_view.py` |
| `render_work_log` | 858–921 | `work_log.py` |
| `_TRAIL_LINE_WIDTH` | 582 | `trail.py` |
| `render_with_trail` | 922–1248 | `trail.py` |

**Constant-placement rule (load-bearing):** before moving each module-level constant, grep ALL of `map_render.py` for its uses. The table above reflects the expected single-consumer placement; if a constant is referenced by functions landing in ≥2 different target modules, instead put it in `_geometry.py` and import it where used. Verify `STRIPE_WIDTH_MM`, `_TRAIL_LINE_WIDTH`, and the `_OBSTACLE_*`/`_MOWER_ICON_*` consts this way.

- [ ] **Step 1: Create `map_render/_geometry.py`**

Header: `from __future__ import annotations`, then `import logging` (+ `_LOGGER = logging.getLogger(__name__)` if any geometry fn logs), `from typing import TYPE_CHECKING`, the PIL imports the moved fns use, and the re-anchored MapData import:
```python
if TYPE_CHECKING:
    from ..map_decoder import MapData
```
Paste `_DEFAULT_PALETTE`, `_DOCK_RADIUS_PX`, `_cloud_to_px`, `_renderer_to_px`, `extract_projection` VERBATIM. (Note: a `from .map_decoder import` becomes `from ..map_decoder import` — one level deeper.)

- [ ] **Step 2: Create `map_render/base_map.py`**

Header + `from ._geometry import _cloud_to_px, _renderer_to_px, _DEFAULT_PALETTE, _DOCK_RADIUS_PX` (whichever it uses), PIL imports, re-anchored `MapData` TYPE_CHECKING import. Paste `render_base_map` (with its nested `_composite_polygon`), `_OBSTACLE_FILL`, `_OBSTACLE_OUTLINE`, `_MOWER_ICON_SIZE_PX`, `_MOWER_ICON_CACHE`, `_mower_icon` VERBATIM. `_MOWER_ICON_CACHE` is module-global mutable state — keep it module-level here (its `global` statement inside `_mower_icon` still works).

- [ ] **Step 3: Create `map_render/main_view.py`**

Header + `from .base_map import render_base_map` (+ any base/geometry helper the pre-start variants call) + `from ._geometry import ...` as needed, PIL imports, re-anchored `MapData`. Paste `STRIPE_WIDTH_MM`, `render_main_view`, `_render_pre_start_with_stripes`, `_render_pre_start_edge`, `_render_pre_start_spot` VERBATIM.

- [ ] **Step 4: Create `map_render/work_log.py`**

Header + imports from `.base_map` / `._geometry` as used, PIL, re-anchored `MapData`. Paste `render_work_log` VERBATIM.

- [ ] **Step 5: Create `map_render/trail.py`**

Header + `_TRAIL_LINE_WIDTH`, imports from `.base_map` / `._geometry` as used, PIL, re-anchored `MapData`. Paste `render_with_trail` VERBATIM.

- [ ] **Step 6: Create `map_render/__init__.py` (re-export shim)**

```python
"""Map rendering package. Public surface re-exported for
`from ..map_render import X` callers (coordinator + tests)."""
from __future__ import annotations

from ._geometry import _DEFAULT_PALETTE, extract_projection
from .base_map import render_base_map
from .main_view import render_main_view
from .work_log import render_work_log
from .trail import render_with_trail

__all__ = [
    "render_base_map",
    "render_main_view",
    "render_work_log",
    "render_with_trail",
    "extract_projection",
    "_DEFAULT_PALETTE",
]
```
Then enumerate EVERY name the test suite imports from `map_render` and ensure each is in `__init__` (3 tests import `_DEFAULT_PALETTE`; several import name-tuples):
```bash
grep -rhoE "from custom_components.dreame_a2_mower.map_render import[^\n]*" tests | sort -u
grep -rnA6 "from custom_components.dreame_a2_mower.map_render import \(" tests
```
Add any additional imported name (e.g. another palette/const) to the `__init__` re-export + `__all__`. (Do NOT touch `wifi_map_render` — separate module.)

- [ ] **Step 7: Delete the old module**

```bash
git rm custom_components/dreame_a2_mower/map_render.py
```

- [ ] **Step 8: Prune imports per-name + verify acyclic**

For each new module, per-name grep every import and drop unused ones. Confirm import direction is `_geometry` ← `base_map` ← {`main_view`,`work_log`,`trail`} ← `__init__` with no back-edges:
```bash
grep -rnE "^from \.|^from \.\." custom_components/dreame_a2_mower/map_render/
python -c "import custom_components.dreame_a2_mower.map_render as m; print('package imports OK:', [n for n in ['render_base_map','render_main_view','render_work_log','render_with_trail','extract_projection','_DEFAULT_PALETTE'] if hasattr(m,n)])"
```
Expected: the package imports cleanly and lists all 6 names.

- [ ] **Step 9: Run render tests, then the full suite**

Run: `python -m pytest tests/protocol/test_m_path_render.py tests/protocol/test_nav_paths_render.py tests/protocol/test_render_base_with_obstacles.py tests/protocol/test_render_main_view_idle.py tests/protocol/test_render_work_log_uses_split.py tests/protocol/test_render_traversal_visible.py tests/protocol/test_render_stripes.py tests/protocol/test_render_dark_green_base.py tests/protocol/test_maintenance_point_render.py tests/protocol/test_map_render_palette.py tests/integration/test_map_render.py tests/integration/test_work_log_render.py tests/integration/test_main_view_render.py tests/test_render_timeline_order.py tests/test_extract_projection.py tests/test_render_pre_start_edge_spot.py tests/unit/test_map_projection.py tests/coordinator/test_legs_timeline_build.py -q`
Expected: all pass.
Run: `python -m pytest tests -q 2>&1 | tail -3`
Expected: the Task-1 baseline counts, no regressions.

- [ ] **Step 10: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render/
git rm --cached custom_components/dreame_a2_mower/map_render.py 2>/dev/null; true
git commit -m "audit-b4b: convert map_render.py into a map_render/ package (geometry/base_map/main_view/work_log/trail)"
```

---

### Task 4: CLAUDE.md "Rendering structure" note + final confirm

- [ ] **Step 1: Add the note**

Append a "## Rendering structure (load-bearing)" section to `CLAUDE.md` (after "Cloud client structure"), mirroring the existing package notes: the `map_render/` module→concern table, the acyclic import rule (`_geometry` ← `base_map` ← {`main_view`,`work_log`,`trail`} ← `__init__`), "the public surface lives in `__init__.py`; keep `from ..map_render import …` working", and "do NOT reintroduce a single `map_render.py`". One sentence noting `camera.py` is a thin platform entry with `_camera_*` siblings (B3a flat-sibling pattern).

- [ ] **Step 2: Full suite + structure sanity**

Run: `python -m pytest tests -q 2>&1 | tail -3` (baseline counts, green).
Run: `wc -l custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/_camera_*.py custom_components/dreame_a2_mower/map_render/*.py`
Expected: `camera.py` is now small (~60–90 LOC); no single map_render module dominates.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "audit-b4b: document map_render/ package + camera siblings in CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- camera.py → thin platform + `_camera_map`/`_camera_lidar`/`_camera_wifi`/`_camera_views` → T2. ✓
- map_render.py → `map_render/` package (geometry/base_map/main_view/work_log/trail + `__init__` re-export) → T3. ✓
- Behavior-preserving (verbatim moves; views/routes/pixel-math unchanged) → T2/T3. ✓
- Public import surface preserved (camera names as attrs; `from ..map_render import …` incl. `_DEFAULT_PALETTE`) → T2 Step 3, T3 Step 6. ✓
- CLAUDE.md "Rendering structure" note → T4. ✓
- Out of scope (PNG helper, session_card, README, live-image card) → not in any task. ✓

**Placeholder scan:** Move instructions cite exact line ranges and the VERBATIM rule; constant placement has an explicit grep-first rule; all commands have expected output. No TBD/TODO.

**Type/name consistency:** Module names (`_camera_*`, `map_render/_geometry|base_map|main_view|work_log|trail`), class groupings, and the `__init__` re-export list (incl. `_DEFAULT_PALETTE`) are consistent across tasks. `wifi_map_render` is explicitly excluded.

**Risk note:** The one non-mechanical step is constant placement in T3 (interspersed `_TRAIL_LINE_WIDTH`/`_OBSTACLE_*`/`_MOWER_ICON_*`/`STRIPE_WIDTH_MM`) and `_MOWER_ICON_CACHE` module-global state — the grep-first rule + the per-module test run guard it.
