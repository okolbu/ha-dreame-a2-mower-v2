# B4b — camera.py + map_render.py File Splits (Design)

**Date:** 2026-05-21
**Status:** spec
**Parent (Block 4):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` § 5 ([B4] items).
**Sibling cycles:** B4c (session_card split + PNG helper), B4d (README catch-up).

## What this is

First Block-4 sub-cycle. Splits the two largest rendering files —
`camera.py` (962 LOC, 11 entity classes + 4 HTTP views) and `map_render.py`
(1283 LOC, pure render functions) — into domain/concern-grouped modules,
keeping the public import surface unchanged. **Behavior-preserving**: bodies
move VERBATIM (identical `unique_id` / `_attr_name` / `device_info` / value /
availability logic and identical pixel math). The existing camera/render tests
are the characterization gate.

**Decisions (user, 2026-05-21):**
- **Bundle camera.py + map_render.py in one cycle** (B4b) — both are rendering
  surfaces; mirrors B3a bundling related splits.
- **`map_render.py` becomes a `map_render/` package** with a re-export
  `__init__.py` (matches `coordinator/` and `cloud_client/` packages).
- **`camera.py` keeps the B3a flat-sibling pattern** (thin platform file +
  `_camera_*.py` siblings) — it's an HA platform file, so the platform entry
  must stay importable as `…camera`.

## Part 1 — camera.py → thin platform + `_camera_*.py` siblings

`camera.py` does not import `map_render` (cameras serve pre-rendered PNG bytes
from coordinator attributes), so this split is independent of Part 2.

```
camera.py            # platform entry: async_setup_entry (creates entities +
                     #   registers the 4 HTTP views), imports entity/view
                     #   classes from siblings, re-exports names tests import.
_camera_map.py       # DreameA2MapCamera, DreameA2PerMapCamera, DreameA2WorkLogCamera
_camera_lidar.py     # _LidarCameraBase, DreameA2LidarTopDownCamera,
                     #   DreameA2LidarTopDownFullCamera, DreameA2LidarSelectedCamera
_camera_wifi.py      # DreameA2WifiSelectedCamera, DreameA2WifiPerMapCamera
_camera_views.py     # MapImageView, WorkLogImageView, LidarSelectedPcdView,
                     #   LidarPcdDownloadView   (HomeAssistantView subclasses)
```

- **HA platform discovery preserved:** HA imports
  `custom_components.dreame_a2_mower.camera`; the `_camera_*` siblings are not
  named after a platform domain, so they're plain helper modules the platform
  file imports. (Same precedent as B3a's `_switch_*` / `_sensor_*`.)
- **Grouping rule:** map-image cameras → `_camera_map.py`; LiDAR cameras (incl.
  the shared `_LidarCameraBase`) → `_camera_lidar.py`; WiFi-heatmap cameras →
  `_camera_wifi.py`; the four `HomeAssistantView` HTTP endpoints → `_camera_views.py`.
- **Shared base:** only the LiDAR cameras share a base (`_LidarCameraBase`),
  which lives WITH them in `_camera_lidar.py`. The map/wifi cameras are
  standalone `CoordinatorEntity[…]+Camera` subclasses (no cross-group base). The
  plan confirms by grepping each class's declared bases; if a cross-group base
  surfaces, it goes to a new `_camera_base.py`.
- **`async_setup_entry` stays in `camera.py`** and registers the exact same
  entity set in the same order + the four views via `hass.http.register_view`.
  It imports the view classes from `_camera_views` and entity classes from the
  group modules.
- **Re-exports:** `camera.py` re-exports every entity/view/helper name that a
  test or tool imports from `…camera` directly (confirmed by grep in the plan;
  only names with a real importer are re-exported — the B3a lesson).

## Part 2 — map_render.py → `map_render/` package

Call graph is acyclic bottom-up: geometry → base_map → {main_view, work_log,
trail}. Module assignment follows it:

```
map_render/__init__.py   # re-exports the external API (see below). No logic.
map_render/_geometry.py  # _cloud_to_px, _renderer_to_px, extract_projection,
                         #   _DEFAULT_PALETTE, _DOCK_RADIUS_PX + other module consts
map_render/base_map.py   # render_base_map, _composite_polygon, _mower_icon
map_render/main_view.py  # render_main_view, _render_pre_start_with_stripes,
                         #   _render_pre_start_edge, _render_pre_start_spot
map_render/work_log.py   # render_work_log
map_render/trail.py      # render_with_trail
```

- **Acyclic imports:** `_geometry` imports nothing internal; `base_map` imports
  `_geometry`; `main_view`/`work_log`/`trail` import `base_map` + `_geometry`.
  `__init__` imports from the leaf modules only.
- **Public surface preserved:** external callers use exactly these via
  `from ..map_render import …` — `render_work_log`, `extract_projection`
  (`coordinator/_session.py`), `render_base_map` (`_session.py`,
  `_cloud_state.py`, `_rendering.py`), `render_with_trail`, `render_main_view`
  (`_rendering.py`). `map_render/__init__.py` re-exports all five (plus any
  private name a test imports — confirmed by grep in the plan).
- **Relative imports re-anchor** for moved bodies: a function that did
  `from .map_decoder import MapData` (a package sibling) becomes
  `from ..map_decoder import MapData` inside `map_render/*`. Local in-body
  imports stay local. (Same re-anchoring as the cloud_client package split.)
- **`map_render.py` is deleted**; the package replaces it. `MapData` stays a
  `TYPE_CHECKING`-only import where used.

## Behavior preservation

- Entity/view bodies and render functions move VERBATIM — no change to
  `unique_id`, `_attr_name`, `device_info`, availability/value logic, view
  routes/URLs, palette values, or pixel math.
- `async_setup_entry` produces the identical entity set + registers the same
  four views in the same order.
- No entity is added / renamed / removed and no protocol fact changes → the
  CLAUDE.md fact-discipline rule does NOT fire.

## Testing

The existing camera + render tests are the safety net (e.g.
`tests/integration/test_per_map_cameras.py`, the camera/view tests, and any
`map_render`/render tests). Run the relevant tests after each file's split, then
the full suite (`python -m pytest tests -q`, current baseline to be captured at
plan start) green at every commit. Confirm `async_setup_entry` still produces
the same entity set and registers the four views. Add a small import-surface
guard test only if a split exposes a gap.

## CLAUDE.md updates

Add a "Rendering structure" note documenting the `map_render/` package
(mirroring the existing "Coordinator structure" / "Cloud client structure"
notes): the
module→concern table + the acyclic import rule + "don't reintroduce a single
`map_render.py`". The camera split is a flat-sibling platform decomposition
(same shape as B3a) — note it briefly if useful, but the platform-file
convention is already covered.

## Out of scope (later B4 cycles)
- **PNG-serialisation helper** + `session_card.py` split → B4c.
- **README full catch-up** → B4d.
- **Live-image card "Configuration error"** → DEFERRED minor UI (see RESUME /
  memory `project_live_image_card_render_bug`); not in B4b.

## Push discipline

Behavior-preserving, suite green. Commit on `main` with `audit-b4b:` prefix,
authored as the user, no co-author trailer. Ship (push + `release.sh`) at the
user's discretion after the cycle, with explicit in-message push authorization.
