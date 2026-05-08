# Work Logs cleanup + map-render z-order — design

**Status:** approved 2026-05-08, pending implementation plan
**Driver:** holistic fix for 6 issues observed after v1.0.1a2 (the cloud-discovery integration release):

1. M_PATH overlay color too close to live trail color.
2. M_PATH overlay z-order makes the trail look "dim" under the lawn's transparent zone fills.
3. The replay-map camera shows the latest session even when no session is picked.
4. Legacy archive entries lack `map_id` (separate backfill — out of scope here).
5. Picking a Map 1 session renders that session's trail on top of Map 2's base.
6. After 10–20 s, the replay reverts to the latest session despite the picker being held.

The user explicitly asked for a holistic redesign rather than a fifth quick-fix layer.

## Goal

Replace the single shared map-camera + replay-mode flag with three independent render pipelines that mirror the Dreame app's mental model:

- **Main view** — the active map with live state. No historical data.
- **Per-map static** — each map's base + cumulative cloud history. No live state.
- **Work Logs** — the picker-selected archived session. Independent of everything else.

This eliminates the shared-cache races behind issues #3 / #5 / #6, fixes the M_PATH layering / color (#1, #2), and aligns names + UX with the Dreame app ("Work Logs" parent → "Mowing Logs" tab; "Patrol Logs" tab is forward-prep only).

## Non-goals

- Patrol Logs data source / picker-list / render content. Architecture leaves room for a future `[Patrol]`-prefixed picker entry, no infrastructure built on speculation.
- Backfill of legacy `map_id=-1` archive entries from `probe*jsonl`. Tracked separately.
- Run-time obstacle polygons surfaced on the live main view. The renderer accepts the parameter and the call site passes empty until a data source is identified.
- M_PATH color customization / per-map palette overrides. Single black color.

## Architecture

### Three render pipelines

| Pipeline | Output | Cache slot | Triggered by |
|---|---|---|---|
| Main view | `lawn + nav_paths + mowing/exclusion/spot zones + dock + live trail + mower icon + run-time obstacles` | `_main_view_png` | s1.4 telemetry, lifecycle events, active-map switch, periodic `_refresh_cloud_state` |
| Per-map static | `lawn + nav_paths + mowing/exclusion/spot zones + dock + M_PATH (black, above zones)` | `_static_map_pngs_by_id[map_id]` | `_refresh_cloud_state` (10 min cadence) |
| Work Log | `lawn + nav_paths + zones + dock + replay trail + replay obstacles` | `_work_log_png` | User picks a session in `select.work_log`; never touched by periodic refreshes |

### Invariants

- The Main view never renders historical M_PATH and never renders an archived session.
- The Work Log camera's PNG is mutated **only** by picker select. Periodic refreshes do not touch it. Selecting a Map 1 log while Map 2 is the active main view is allowed: Work Log shows Map 1, Main view stays on Map 2.
- Per-map static cameras are the dashboard's "see all my maps" / "mini-window" equivalent and the only place M_PATH is rendered.
- `_render_map_id` is deleted. The `cached_map_png` getter/setter that resolved `_render_map_id ?? _active_map_id ?? cache_slot` is the source of issues #3, #5, #6 — replacing it with three independent slots eliminates the race entirely.

## Entity surface

### Renames

| Old | New | Reason |
|---|---|---|
| `select.dreame_a2_mower_replay_session` | `select.dreame_a2_mower_work_log` | App alignment ("Work Logs" parent → "Mowing Logs" tab) |
| Dashboard view title "Sessions" | "Work Logs" | Same |

### New

| Entity | Type | Purpose |
|---|---|---|
| `camera.dreame_a2_mower_work_log` | Camera | Independent PNG cache for the picker-selected log entry |

### Kept

| Entity | Role |
|---|---|
| `camera.dreame_a2_mower_map` | Main view (live trail on the active map) |
| `camera.dreame_a2_mower_map_<N>` | Per-map static (base + M_PATH) |

### Picker label format

`[Mowing] [Map N] YYYY-MM-DD HH:MM — A m² / Dmin`

Today's `[Map ?]` legacy prefix and `▶` (in-progress) / `⚠` (partial trail) markers are preserved. Adding a `[Mowing]` tag to every entry makes the upgrade path to Patrol Logs a one-line option-merge.

## Render-function split

`map_render.py` gains two semantic functions; `render_with_trail` is removed (callers move to one of the two new ones):

```python
def render_main_view(
    map_data: MapData,
    *,
    legs: list[Leg] | None,
    mower_position_m: tuple[float, float] | None,
    mower_heading_deg: float | None,
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
) -> bytes:
    """Live/active-map render: base (no m_path) + live trail + mower icon + obstacles."""

def render_work_log(
    map_data: MapData,
    *,
    legs: list[Leg],
    obstacle_polygons_m: list[list[tuple[float, float]]] | None = None,
) -> bytes:
    """Archived-session render: base (no m_path) + archived trail + archived obstacles.
    No mower icon — the session is over; no live position."""
```

`render_base_map` keeps the optional `m_path` kwarg added in v1.0.0a100 (Task 14 of the cloud-discovery integration), with two adjustments:

1. **M_PATH color → `(0, 0, 0, 255)` (black).** Visually distinct from the live trail's dark gray `(70, 70, 70, 220)`. New palette default `_DEFAULT_PALETTE["m_path"] = (0, 0, 0, 255)`.
2. **M_PATH z-order → above mowing zones.** Currently drawn at "Section 1.5" (between lawn fill and mowing zones), which is why the alpha-200 green dimmed it inside the lawn. Move to "Section 2.5" (after mowing zones, before exclusion/spot/nav). M_PATH then sits clearly on top of the green; the dimming-under-transparent-zone behavior goes away.

Per-map static cameras stay on `render_base_map(map_data, m_path=mp)` — no behavior change beyond the palette/z-order tweaks.

## Coordinator state changes

**Delete:**
- `self._render_map_id`
- `self.cached_map_png` getter and setter
- The multi-map-aware variants `_cached_map_data` getter/setter and `_last_map_md5` getter/setter that route through `_render_map_id`
- `self._replay_counter` (no longer needed once the work-log camera has its own cache)

**Add:**
- `self._main_view_png: bytes | None` — populated by `_render_main_view()`
- `self._work_log_png: bytes | None` — populated by the picker only

**Rename for clarity:**
- `self._cached_pngs_by_id` → `self._static_map_pngs_by_id`
- `self._cached_maps_by_id` (the decoded `MapData` cache) keeps its name; only the PNG dict is renamed

**Render triggers:**

| Event | Calls |
|---|---|
| s1.4 telemetry tick (live position) | `_render_main_view()` |
| Lifecycle event (mowing started/finished, dock/undock) | `_render_main_view()` |
| `_active_map_id` change | `_render_main_view()` + invalidates `_main_view_png` |
| `_refresh_cloud_state()` (every 10 min) | re-renders all `_static_map_pngs_by_id` and `_render_main_view()` |
| User picks a session in `select.work_log` | `_render_work_log(session)` writes `_work_log_png` |
| User picks the placeholder | clears `_work_log_png = None`; camera surfaces "Image not available" |

## `map_id=-1` fix scope

`archive/session.py:382` `in_progress_entry()` synthesizes an `ArchivedSession` without passing `map_id`, so the in-progress row in the picker always gets `[Map ?]`. Fix: thread `coordinator._active_map_id` through `list_sessions()` → `in_progress_entry(active_map_id=...)` so the synthesized row carries the correct map.

For PERSISTED legacy entries that lack `map_id` in their on-disk JSON, the `[Map ?]` prefix stays. Backfilling those from the existing `probe*jsonl` archive is tracked as a separate follow-up TODO and is **out of scope** for this PR.

## Tests

| Test | Verifies |
|---|---|
| `tests/integration/test_main_view_render.py` | `render_main_view` output contains zero pixels of the M_PATH color, regardless of the `cloud_state.mow_paths_by_map_id` content |
| `tests/integration/test_work_log_isolation.py` | After picking a log entry, `_main_view_png` byte-equality survives a full simulated `_refresh_cloud_state()` tick; `_work_log_png` is unchanged by the tick; selecting a Map 1 log while `_active_map_id == 0` does not touch `_main_view_png` |
| `tests/integration/test_in_progress_map_id.py` | The synthesized in-progress entry carries `_active_map_id`, not `-1`; falls back to `-1` only when `_active_map_id is None` |
| `tests/protocol/test_m_path_render.py` (update) | Default M_PATH color is `(0, 0, 0, 255)`; rendered M_PATH pixels appear ABOVE mowing-zone fills (sample a pixel inside a zone where the M_PATH crosses, assert it's black not zone-tinted) |
| `tests/integration/test_work_log_picker.py` | Picker labels start with `[Mowing] [Map N]`; placeholder selection clears `_work_log_png` |

## Migration / rollout

- Entity-id renames are HA-visible; users who have automations or dashboard cards referencing `select.dreame_a2_mower_replay_session` need to update them once after the upgrade.
- The dashboard YAML in `dashboards/mower/dashboard.yaml` is updated as part of this PR — view title "Sessions" → "Work Logs", select reference updated, picture-entity reference updated to point at `camera.dreame_a2_mower_work_log`.
- The user is the only operator on this branch (per memory: only one HA install, breaking changes pre-approved). No HACS migration shim required.

## Spec / plan / version footprint

- This spec lives at `docs/superpowers/specs/2026-05-08-replay-session-cleanup-design.md`.
- The implementation plan to follow lives at `docs/superpowers/plans/2026-05-08-replay-session-cleanup.md`.
- Targeted release: `v1.0.1aN+1` (or `1.0.2a1` if HACS again misorders the alpha counter).
