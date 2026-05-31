# Head-to-Maintenance-Point (go-to-point / op=109) — design

**Date:** 2026-05-31
**Status:** approved (design), pre-implementation
**Scope unit:** "Feature A" of the larger ask (go-to-point feature + dashboard;
the write-targets doc and the missing-controls bug are separate units).

## Background

op=109 (cruise-to-point / "Head to Maintenance Point") is now fully decoded and
live-confirmed (`inventory.yaml` o109, verified 2026-05-31):

- **Send:** `routed_action(109, {"point": [point_id]})` —
  `{m:'a', p:0, o:109, d:{point:[point_id]}}` via the same routed-action /
  `/device/sendCommand` transport as the working mow ops. The `d`-key is the
  target *type* (`point`); reusing spot's `{area:[id]}` with o=109 is **rejected**
  (`s2p50 o:109 status:false`).
- **Point identity:** `point_id` is a per-map cleanPoint id (the active map had
  ids 1, 2). A bare id worked because the target was on the **active** map, so the
  trigger must ensure the right map is active first.
- **Read side already present:** `MapData.maintenance_points`
  (`MaintenancePoint(point_id, x_mm, y_mm)`, parsed from `cleanPoints` in
  `map_decoder._parse_maintenance_points`); the notification synthesizer already
  fires arrival off `s2p2=75` and "cannot reach" off `s2p2=76`.

The integration can read/track these runs but cannot **trigger** one, and the
dashboard still shows a "Head to Maintenance Point" placeholder.

## Goal

Let the user pick a maintenance point per map and send the mower there, as a
first-class action distinct from mowing (the app treats it as its own mode, so it
gets its **own trigger**, not the Start button).

## Approved design decisions

1. **Point labels:** `Point {id}` (cloud provides no name).
2. **Selection model:** per-map — the stored selection is `(map_id, point_id)`,
   so each map's button only heads to a point chosen on that map. (More robust
   than the existing global `active_selection_spots` pattern; avoids multi-map
   ambiguity.)
3. **Bug D (To-Point on live map):** verify-and-fix — trigger a real go-to-point
   from the integration, confirm it renders as a To-Point session on the live map,
   and fix the begin/render path only if there is a genuine gap.

## Components

### 1. Action layer — `mower/actions.py`
- Add `MowerAction.GO_TO_POINT`.
- `ACTION_TABLE[GO_TO_POINT] = {siid:5, aiid:1, routed_t:"TASK", routed_o:109,
  payload_fn:_go_to_point_payload}` (mirrors `START_SPOT_MOW`).
- `_go_to_point_payload(params)` → `{"point": [int(params["point_id"])]}`; raises
  `ValueError` if `point_id` missing (mirrors `_spot_mow_payload`).

### 2. Coordinator — `coordinator/_writes.py`
- `async def start_go_to_point(self, *, map_id: int, point_id: int) -> None`:
  `await self._ensure_active_map(map_id)` then
  `await self.dispatch_action(MowerAction.GO_TO_POINT, {"point_id": point_id})`.
  Mirrors `start_mowing_spot`.

### 3. State — `mower/state.py`
- Add `active_selection_point: tuple[int, int] | None = None` to `MowerState`
  (the `(map_id, point_id)` the user picked). Frozen-dataclass replace pattern,
  same as `active_selection_spots`.

### 4. Per-map select — `DreameA2MaintenancePointSelect` (`select_map_settings.py`)
- Per-map (`map_device_info` / `map_unique_id`), `_attr_name = "Maintenance point"`,
  icon `mdi:map-marker`.
- Options: `Point {p.point_id}` for `p in maps_by_id[map_id].maintenance_points`;
  empty placeholder `"(no points on this map)"`.
- `async_select_option`: resolve label → point_id, store
  `active_selection_point=(map_id, point_id)` via `async_set_updated_data`.
- `current_option`: reflect the stored selection iff its map_id == this map.
- Registered in the existing per-map loop in `select.py:async_setup_entry`.

### 5. Per-map button — `DreameA2HeadToPointButton` (`button.py`)
- Per-map variant of the action button (uses `map_device_info` / `map_unique_id`),
  `_attr_name = "Head to point"`, icon `mdi:map-marker-right`.
- `available`: True iff this map has points AND `active_selection_point` is set
  for this map.
- `async_press`: read `active_selection_point`; if it targets this map, call
  `coordinator.start_go_to_point(map_id=self._map_id, point_id=point_id)`; else
  log + no-op.
- Registered via a new per-map loop in `button.py:async_setup_entry`.

### 6. Entity inventory — `entity-inventory.yaml`
- Add entries for `DreameA2MaintenancePointSelect` and `DreameA2HeadToPointButton`
  (source = `maps_by_id[*].maintenance_points` → `start_go_to_point` →
  `routed_action(109,{point:[id]})`), status `presumed` until live-validated.

### 7. Dashboard (`/config/dashboards/mower/dashboard.yaml`, deployed via SCP)
- Replace the "Head to Maintenance Point" placeholder with the per-map
  `select.…_maintenance_point` dropdown + the `button.…_head_to_point` button,
  following the per-map naming/layout conventions. Deploy per the dashboard-deploy
  procedure (backup first, browser-reload).

### 8. Bug D — To-Point on the live map
- After the trigger works, start a real go-to-point and watch whether the mower
  renders on the live map as a To-Point session. The prior miss was observed when
  a **standalone probe** triggered it (no integration dispatch); an
  integration-triggered run exercises the coordinator's session-begin path. If the
  mower still doesn't render, trace the To-Point session begin/classify → live-map
  render path and fix. Treated as verification with a contingent fix, not an
  assumed code change.

## Data flow

`select.maintenance_point` (per map) → `MowerState.active_selection_point` →
`button.head_to_point` (same map) → `coordinator.start_go_to_point(map_id,
point_id)` → `_ensure_active_map(map_id)` (op=200 if needed) →
`dispatch_action(GO_TO_POINT)` → `routed_action(109,{point:[id]})` → firmware
`s2p50 o:109 status:true` → `s2p56=[[id,0]]→[[id,2]]` → `s2p2=75` arrival.

## Testing (TDD)

- `_go_to_point_payload`: returns `{"point":[id]}`; raises on missing `point_id`.
- `ACTION_TABLE[GO_TO_POINT]` shape (routed_o=109, payload_fn wired).
- `start_go_to_point`: calls `_ensure_active_map(map_id)` then dispatches
  GO_TO_POINT with the point_id (mock dispatch/active-map).
- `DreameA2MaintenancePointSelect`: options from `maintenance_points`, empty
  placeholder, select stores `(map_id, point_id)`, `current_option` map-scoped.
- `DreameA2HeadToPointButton`: `available` logic; press → `start_go_to_point`
  with the selected point; no-op when selection is for a different map / unset.
- Per-map naming tests (entity_id namespacing) extended to the two new classes.

## Out of scope (separate units)

- **Write-targets/endpoints doc** (unit B).
- **Missing Start/Recharge controls on the mower dashboard tab** (unit C — the
  entities exist and work; it's a dashboard-card gap).

## Conventions

- Per-map naming rule (CLAUDE.md "Per-map naming convention"): device name carries
  the `DEFAULT_NAME` prefix; entity `_attr_name` is the bare entity name only.
- Inventory discipline: live-validation results recorded under the new
  entity-inventory entries; protocol stays in `inventory.yaml` o109.
