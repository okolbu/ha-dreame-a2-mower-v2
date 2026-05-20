# B1c — `_cached_*` Shadow Removal + Redundant Refresher Deletion (Design)

**Date:** 2026-05-19
**Status:** PAUSED after T2 (2026-05-20) — superseded by the map-write
architecture redesign. T1 + T2 (reader routing) are committed locally
(`9c58ccb`, `52e409f`) but NOT pushed; T3–T6 are not started. See the
"Pause note" below.
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Discovery findings:**
  - `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 3 (shadow inventory)
  - `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 5.1 (refreshers)

## Pause note (2026-05-20)

B1c was paused after T2 when reader-routing surfaced an architectural
fact the discovery doc (§ 3) missed: **`_cached_maps_by_id` is NOT a
pure shadow of `cloud_state.maps_by_id`.** Two methods write ONLY the
shadow and never populate `cloud_state`:

- `coordinator/_cloud_state.py:_load_persisted_maps` (startup cache
  restore) — writes shadow at L244, then calls `_sync_map_subdevices()`.
- `coordinator/_cloud_state.py:_refresh_map` (6 h dedicated MAP.* fetch
  via `fetch_map()`) — writes shadow at L316, persists raw to disk,
  renders per-map PNGs, then calls `_sync_map_subdevices()`.

Only the `_refresh_cloud_state` path (L108 + L112) writes both
`cloud_state` and the shadow; that L112 mirror is the genuinely-redundant
write. The L112 comment confirms the migration was left incomplete:
"These become inert once all consumers move to cloud_state directly, but
the migration is staged across Task 7+ steps."

**Effect of the committed T1+T2:** all 60 readers now read
`cloud_state.maps_by_id`, including `_sync_map_subdevices`. Because
`_refresh_cloud_state()` runs at startup (`_core.py:394`) BEFORE
`_load_persisted_maps()` (L495) and `_refresh_map()` (L500), the ONLINE
restart case still syncs sub-devices correctly (cloud_state is populated
before those two call `_sync_map_subdevices`). The narrow regression is
OFFLINE restart: if the first `_refresh_cloud_state()` fails (no network),
`cloud_state` stays None and the persisted-cache maps no longer create
map sub-devices (they did before B1c). Normal online operation is
unaffected, which is why T1+T2 are left in place rather than reverted.

**Why T4-as-written is wrong:** the plan's T4 ("delete the 3 writers")
would turn L244 and L316 into dead-ends — `_load_persisted_maps` and
`_refresh_map` would fetch/restore maps that land nowhere readable. The
correct fix is to make those two methods write `cloud_state.maps_by_id`
(via `dataclasses.replace`, constructing a fresh CloudState when
`cloud_state` is None), which is an architecture change beyond B1c's
"mechanical shadow removal" scope.

**Decision (user, 2026-05-20):** pause B1c and run a dedicated map-write
architecture redesign that consolidates the three map-write paths
(`_refresh_cloud_state`, `_refresh_map`, `_load_persisted_maps`) onto the
canonical `cloud_state.maps_by_id`, eliminates the offline-startup gap,
and only then completes the shadow deletion (the remaining T3-T6 work
folds into the redesign). The redesign gets its own spec → plan →
execute cycle. The redundant-refresher deletions (`_refresh_cfg`,
`_refresh_mihis` — original T5) are independent of the map-write tangle
and can be done in the redesign or a small standalone follow-up.

## What this is

Third source-modifying phase of the integration audit. B1c removes the
`_cached_maps_by_id` shadow attribute — the last surviving piece of the
pre-CloudState architecture — by routing 60+ readers to
`self.cloud_state.maps_by_id` and deleting the shadow's writers + init.
B1c also deletes two redundant refreshers (`_refresh_cfg`,
`_refresh_mihis`) whose work is fully covered by the 2-min
`_refresh_cloud_state` introduced in v1.0.0a100.

This is the largest-touch-surface task in Block 1: it edits files across
the entity-platform layer (`select.py`, `switch.py`, `camera.py`,
`sensor.py`, `number.py`) plus coordinator submodules.

## Goals

1. Replace **44 reader sites in entity platforms** that access
   `coordinator._cached_maps_by_id` with `coordinator.cloud_state.maps_by_id`.
2. Replace **16 reader sites in coordinator submodules** with
   `self.cloud_state.maps_by_id` (or `coordinator.cloud_state.maps_by_id`
   where the coordinator is accessed externally).
3. Replace the **in-place dict mutation at `coordinator/_session.py:332`**
   with a `dataclasses.replace` of the frozen CloudState. This is the
   single writer that ISN'T a bulk reassignment.
4. Delete the **4 writer/init sites**: `_core.py:192` (init),
   `_cloud_state.py:119,251,323` (bulk reassigns). The shadow attribute
   ceases to exist.
5. Clean up **6 docstring/comment mentions** of `_cached_maps_by_id`
   across `_cloud_state.py`, `_rendering.py`, `_device_sync.py`.
6. Delete `_refresh_cfg` + its `async_track_time_interval` registration
   (10-min cadence; covered by 2-min `_refresh_cloud_state`).
7. Delete `_refresh_mihis` + its registration (same).

## Non-goals

- **`_refresh_map` deletion is deferred** to a follow-up cycle. Discovery
  § 5.1 claimed it's superseded, but the 6 h cadence + its location in
  `_cloud_state.py` (not `_refreshers.py`) suggests it may do map-decode
  work the 2-min path doesn't trigger. Confirming coverage requires
  reading the actual `_refresh_map` body carefully; that's its own
  brainstorm. (Per parent design: "redundant refresher" deletion is
  in-scope for B1c, but only the confirmed-redundant ones.)
- `_poll_slow_properties` (s6p3 returns 80001 on g2408 — flagged § 5.4)
  is a separate concern. Defer.
- No new tests. The existing pytest suite is the regression check. The
  shadow attribute isn't currently tested in isolation — it's tested
  indirectly via the entity platforms that read it.
- No `CloudState` schema changes. The frozen dataclass shape stays.
- No restructure of entity-platform logic. Reader updates touch ONLY the
  read accessor; everything else in the entity classes is unchanged.
- No removal of the `coordinator/_cloud_state.py:_apply_cloud_state` flow.
  The bulk reassigns at L119/L251/L323 currently write to BOTH
  `cloud_state` AND the shadow; after T4 they write to `cloud_state` only.
- No promotion of `_cached_maps_by_id` to a public attribute. The
  intermediate-state property-shim approach is rejected (over-engineered
  for a single-user codebase).

## Hard constraint — no regression

Carried from the parent design:
- Entity `unique_id`, `entity_id`, friendly names, service signatures,
  event payloads, archive format unchanged.
- MowerState / CloudState dataclass shape unchanged.
- After T5 (refresher deletion), the 2-min `_refresh_cloud_state` is the
  ONLY periodic cloud-state refresh. CFG/MIHIS fetches happen as part of
  the cloud-state batch every 2 min — settings still propagate within
  ~2 min worst case (was up to 10 min for CFG/MIHIS-only fields, so
  actually a slight improvement).
- Map data still flows: cloud → `cloud_state.maps_by_id` → readers.
  No reader sees a stale map.

The `_session.py:332` mutation change is the one semantic delta worth
documenting: the old code mutated a dict shared with anyone who held a
reference; the new code replaces `self.cloud_state` wholesale. Anything
else holding the OLD `cloud_state` reference would see the old map. Per
discovery analysis there is no such reference holder — `cloud_state` is
always read fresh via `self.cloud_state`. Documented as a hard rule in
the T3 plan.

## Approach — six sequential tasks, low-risk first

```
T1 entity-platform readers → T2 coordinator readers → T3 _session mutation
  → T4 writers/init/comments → T5 redundant refreshers → T6 verify + push
```

| Task | Files | Sites | Risk | Behaviour change |
|---|---|---|---|---|
| T1 entity-platform readers | select/camera/switch/sensor/number | 44 | low | none |
| T2 coordinator readers | 6 submodules | 16 | low | none |
| T3 `_session.py:332` mutation | `_session.py` | 1 | medium | wholesale CloudState replace |
| T4 writers + init + comments | `_core.py`, `_cloud_state.py`, others | 4 + 6 | low | none (consumers already routed) |
| T5 delete `_refresh_cfg` + `_refresh_mihis` | `_refreshers.py`, `_core.py` | 2 methods + 2 timer regs | medium | CFG/MIHIS propagation latency 10min → 2min |
| T6 verify + push | none | — | none | none |

Serial because:
- T1 and T2 leave the shadow's writers running but readers gone — transient,
  fine, but two-phase rollout makes bisecting clean.
- T3 must run before T4: T3 is the last remaining writer of the shadow
  attribute; once T3 lands, T4 can safely delete the init + bulk writers.
- T5 is independent of T1-T4 but kept last because the wall-clock effect
  is the most visible on the live HA (settings propagate via 2-min path
  only).
- T6 verifies the cumulative end state.

## Detailed per-task scope

### T1 — Entity-platform readers (44 sites)

**Files:**
- `custom_components/dreame_a2_mower/select.py` — 21 sites
- `custom_components/dreame_a2_mower/camera.py` — 11 sites
- `custom_components/dreame_a2_mower/switch.py` — 7 sites
- `custom_components/dreame_a2_mower/sensor.py` — 3 sites
- `custom_components/dreame_a2_mower/number.py` — 2 sites

**Pattern:** `coordinator._cached_maps_by_id` → `coordinator.cloud_state.maps_by_id` (and similar with `.get()`, `.keys()`, etc.). The plan task uses `Edit` with surrounding context per site; some files have uniform-enough patterns that `replace_all=true` works.

Note: per discovery, `camera.py:388,407` have `getattr`-guarded reads
(startup-safety pattern from when `cloud_state` could be uninitialized).
After T1 these guards can be simplified — but DON'T simplify in T1.
Just route the read. Guard simplification is a follow-up if anyone cares.

### T2 — Coordinator-submodule readers (16 sites)

**Files:**
- `coordinator/_session.py` — 7 read sites (NOT the mutation at L332)
- `coordinator/_rendering.py` — 3 sites
- `coordinator/_device_sync.py` — 3 sites
- `coordinator/_cloud_state.py` — 1 site (`.get()` reader at L311 inside the writer method; this read becomes `self.cloud_state.maps_by_id.get()`)
- `coordinator/_lidar_oss.py` — 1 site
- `coordinator/_writes.py` — 1 site

**Pattern:** `self._cached_maps_by_id` → `self.cloud_state.maps_by_id`
(internal access). The `_cloud_state.py:311` read happens INSIDE the
writer method (`_refresh_map`); it reads the previous map before writing
the new one. After T2 this reads the canonical CloudState before T4's
writer-deletion changes anything.

### T3 — `_session.py:332` in-place mutation

**File:** `coordinator/_session.py`

Current:
```python
self._cached_maps_by_id[active_id] = map_data
```

New:
```python
self.cloud_state = dataclasses.replace(
    self.cloud_state,
    maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
)
```

`dataclasses` is already imported at `_session.py:9`. No new imports needed.

Surrounding context: this mutation happens in the replay-fetch path
(per discovery: "Hydrate the active-map slot so subsequent replays don't
re-fetch"). The new map data goes into the canonical CloudState, where
T1/T2 readers will see it on next access.

### T4 — Delete writers + init + stale comments

**Files:**
- `coordinator/_core.py:192` — delete the init line `self._cached_maps_by_id: dict[int, Any] = {}` and its surrounding comment `# Multi-map cache — populated by _refresh_map.` (above it).
- `coordinator/_cloud_state.py` — delete the 3 bulk-reassign writers at L119, L251, L323.
  - L119: `self._cached_maps_by_id = new_state.maps_by_id` (inside the cloud-state apply method — the cloud-state is already set wholesale before this line, so the shadow update is redundant once readers stop using it).
  - L251 and L323: similar shape inside `_refresh_map`.
- 6 docstring/comment cleanup lines:
  - `coordinator/_cloud_state.py:221` (comment in `_restore_persisted_maps` docstring)
  - `coordinator/_cloud_state.py:267` (comment about per-map base-map PNG update)
  - `coordinator/_cloud_state.py:278` (comment about live-trail re-render path)
  - `coordinator/_cloud_state.py:364` (comment about sub-device sync trigger)
  - `coordinator/_rendering.py:174` (comment in the render path)
  - `coordinator/_device_sync.py:223` (comment about map-id iteration)

For the docstring/comment edits: replace `_cached_maps_by_id` with
`cloud_state.maps_by_id` in-place. Don't restructure the prose, just
update the symbol reference.

After T4, `grep -rn "_cached_maps_by_id" custom_components/dreame_a2_mower/`
returns nothing. Confirm in the task's verification step.

### T5 — Delete redundant refreshers

**Files:**
- `coordinator/_refreshers.py` — delete `_refresh_cfg` method (currently at L109) and `_refresh_mihis` method (L515).
- `coordinator/_core.py` — delete the 4 `async_track_time_interval` registrations + the surrounding `entry.async_on_unload(...)` wrappers + the inner `_periodic_cfg` / `_periodic_mihis` definitions:
  - CFG block (registration + manual fire) around L390–406.
  - MIHIS block around L454–472.

The exact line ranges will have drifted slightly from the discovery doc
because of T1–T4 edits. The plan task uses `grep -n` to find the current
locations.

**Verification before deletion** (per task plan):
- Confirm `_refresh_cloud_state` calls `fetch_full_cloud_state` which
  includes the CFG and MIHIS batches in its response. Discovery verified
  this; T5 re-verifies by reading the actual code (one `grep -n
  "fetch_full_cloud_state\|CFG\|MIHIS"` in `cloud_client.py`).

**Behaviour change documented:** CFG-driven settings (rain protection,
DnD, child lock, anti-theft, etc.) and MIHIS counters (lifetime totals)
now refresh at most every 2 minutes instead of every 10 minutes. This is
a tightening of staleness, not a regression — discovery explicitly
flagged the 10-min cadence as redundant given the 2-min path. User-led
smoke check at T6 confirms.

### T6 — Final verification + push

- `pytest tests/ -q` green.
- `python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py')` clean.
- `grep -rn "_cached_maps_by_id\|_refresh_cfg\|_refresh_mihis" custom_components/dreame_a2_mower --include='*.py'` returns nothing.
- `tools/inventory_audit.py` clean.
- Push to `origin/main`.
- **User-led smoke check:** reload integration, toggle a CFG-driven setting
  (e.g. rain protection) from the HA UI, confirm it propagates within 2 min.
  Confirm map camera entity still renders. Confirm map-N sub-devices still
  exist with the same `entity_id`.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| A reader is missed → silent stale-data bug | Discovery doc lists all 60 reads with file:line. T1/T2 task plans walk the file list one by one. T6's final grep catches anything missed (`_cached_maps_by_id` must return zero hits). |
| `dataclasses.replace` performance regression at T3 | `_session.py:332` runs once per replay-fetch, not per state update. Shallow-copying a dict of ~5 maps is microsecond-level. Negligible. |
| A coordinator submodule's `self.cloud_state` is None during startup | The init order is: `__init__` sets `self.cloud_state = CloudState()` (empty) BEFORE any reader runs. Readers always see a (possibly-empty) CloudState. The 1 `_cloud_state.py:311` read inside a writer method is sequenced after `self.cloud_state` is populated by `_refresh_cloud_state` — same as today. |
| `_refresh_cfg` or `_refresh_mihis` does work beyond what `_refresh_cloud_state` covers | T5 task plan verifies by reading the function bodies + tracing the cloud-state batch parser. If verification fails, halt T5 and report. |
| Entity-registry orphans created by the shadow removal | None possible — readers change but `unique_id` patterns don't, so entity registry isn't touched. |
| `getattr`-guarded reads in `camera.py:388,407` now read a non-existent attribute (because we don't touch them in T1?) | T1 DOES route those reads to `cloud_state.maps_by_id`. The `getattr` guard is harmless (returns the empty dict default), so it stays even after T1. Guard simplification is a separate follow-up. |
| User-led smoke check fails (CFG settings don't propagate within 2 min) | Revert T5 (`git revert <T5-SHA>`). The shadow removal (T1-T4) stays. CFG/MIHIS refreshers come back. |

## What stays for later

- **`_refresh_map` deletion** — separate brainstorm + verification cycle.
- **`_poll_slow_properties` deletion** — s6p3 returns 80001; method is
  effectively dead but lower priority. Defer.
- **`getattr`-guarded read simplification** in `camera.py:388,407` — minor
  polish, defer until needed.
- **B1d**: `cloud_client.py` 2197-LOC file split. Independent of B1c.

## What's next

After user signs off, the writing-plans skill produces the B1c
implementation plan (6 tasks, executed via subagent-driven development).
