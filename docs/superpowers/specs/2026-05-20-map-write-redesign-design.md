# Map-write Architecture Redesign (Design)

**Date:** 2026-05-20
**Status:** spec
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Supersedes:** the paused `docs/superpowers/specs/2026-05-19-block1c-shadow-removal-design.md`
(see its "Pause note"). T1+T2 reader-routing (commits `9c58ccb`, `52e409f`)
stand; this redesign completes the shadow removal those started.
**Discovery findings:**
  - `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 3 (shadow inventory), § 5.1 (refreshers)
  - This cycle's exploration (2026-05-20) — recorded below under "What we found".

## What this is

The map-data path in the coordinator has three write sites for map data
that the v1.0.0a100 CloudState migration left half-converted. After the
B1c reader-routing (T1+T2) pointed all 60 readers at
`cloud_state.maps_by_id`, two of those writers (`_load_persisted_maps`,
`_refresh_map`) plus one in `_session.py` write only the now-unread
shadow `_cached_maps_by_id`. This redesign makes `cloud_state.maps_by_id`
the single source of truth, deletes the shadow and the redundant map
machinery, and fixes a latent device-pruning bug surfaced along the way.

Scope is **maps only**. The broader refresher redundancy (CFG / MIHIS /
DEV / NET / slow-poll all still scheduled despite `_refresh_cloud_state`
subsuming them) is a separate future cycle — see "Out of scope".

## What we found (current code, 2026-05-20)

1. **`_refresh_cloud_state` is the only `cloud_state.maps_by_id` writer**
   (`_cloud_state.py:108`). It also mirrors to the shadow at L112 (a
   genuinely redundant write).

2. **Three orphaned shadow writers** (write `_cached_maps_by_id`, never
   `cloud_state`, now that readers moved):
   - `_cloud_state.py:244` `_load_persisted_maps` — startup disk-cache restore.
   - `_cloud_state.py:316` `_refresh_map` — 6 h dedicated `fetch_map()` batch.
   - `_session.py:325` — work-log replay last-resort "hydrate" after a live fetch.

3. **`_refresh_map`'s fetch is redundant.** `fetch_full_cloud_state`
   (`cloud_client.py:1883-1925`) parses `MAP.*` from the unified batch with
   the *same* `parse_cloud_maps` decoder, so `cloud_state.maps_by_id` is
   identical to what `_refresh_map`'s separate `fetch_map()` produces.
   `_refresh_map`'s only *unique* effects are (a) writing the raw response
   to the disk cache via `_save_persisted_maps`, and (b) calling
   `_sync_map_subdevices`.

4. **`_refresh_cloud_state` never calls `_sync_map_subdevices`.** Sub-device
   sync runs only in `_load_persisted_maps`, `_refresh_map`, and the MQTT
   MAPL path (`_mqtt_handlers.py:136,141`). So map sub-devices currently
   depend on `_refresh_map` even online.

5. **Disk cache provides no protection against the scary case.**
   `_init_cloud` calls `client.login()` — a blocking network call — before
   maps are considered (`_core.py:757`). If the cloud is unreachable at
   restart, `async_config_entry_first_refresh()` raises
   `ConfigEntryNotReady`; HA shows "Retrying setup", keeps all devices in
   the registry, marks entities **unavailable** (not deleted), and
   auto-recovers. The disk cache is downstream of `login()`, so it never
   helps the offline-restart case. It only ever covers the narrow window
   where login succeeds but the map batch comes back empty.

6. **Latent prune bug.** `_sync_map_subdevices` (`_device_sync.py:249-266`)
   removes every per-map device whose id is not in `cloud_state.maps_by_id`,
   no-op'ing only when `cloud_state is None` (L232). If `cloud_state` is set
   but `maps_by_id` is empty (transient empty batch after a successful
   login), it deletes **all** per-map devices. Combined with the
   static-at-setup entity model (each platform calls `async_add_entities`
   exactly once, from `cloud_state.maps_by_id`), that is the genuine
   "configs disappeared" hazard — independent of this redesign and worth
   fixing here.

7. **`fetch_map` (cloud client) stays.** `dump_map_diagnostics`
   (`services.py:302`) calls it directly. Only the coordinator's
   `_refresh_map` wrapper is deleted.

## Decision

Direction chosen by the user (2026-05-20): **drop the disk cache + harden
the prune.** `cloud_state.maps_by_id` is the single map store;
`_refresh_cloud_state` is its single owner.

Rationale: the cache's only real value (case 5's narrow window) is
outweighed by the simplification, and the scary offline-restart case is
already safe (unavailable + retrying, governed by `login()`). The
prune-hardening makes the result strictly safer than today.

Accepted trade-off: in the narrow login-ok-but-maps-empty startup window,
per-map entities are unavailable until the next successful refresh
(≤2 min) or a reload, instead of being seeded from disk.

## Changes

### Delete
- `_cloud_state.py`: `_load_persisted_maps` (213-249), `_save_persisted_maps`
  (251-256), `_refresh_map` (258-359).
- `_cloud_state.py:112`: the shadow-mirror line in `_refresh_cloud_state`.
- `_core.py`: shadow init (186), `_maps_cache_store` init (278), and the
  MAP block (474-500: `_periodic_map` timer registration, `Store`
  construction, `_load_persisted_maps` call, `_refresh_map` call).
- `tests/integration/test_maps_cache_persist.py`.

### Convert
- `_session.py:325`: replace the in-place shadow write with
  ```python
  self.cloud_state = dataclasses.replace(
      self.cloud_state,
      maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
  )
  ```
  (Guarded by the existing non-None assumption on that path; `dataclasses`
  already imported at `_session.py:9`.)

### Add
- `_refresh_cloud_state` (`_cloud_state.py`): call `self._sync_map_subdevices()`
  after `_render_maps_from_cloud_state()` and before the listener notify,
  so startup + periodic sub-device sync survives `_refresh_map`'s deletion.

### Harden
- `_sync_map_subdevices` (`_device_sync.py`): skip the prune loop when
  `wanted_ids` is empty. Empty `maps_by_id` = "no authoritative info",
  not "remove all map devices". The add loop is naturally a no-op when
  empty. The `cloud_state is None` guard stays.

### Cleanup (comments / docs)
- Stale `_refresh_map` / "10 min" mentions: `_core.py:179,185`,
  `cloud_state.py` module docstring, `_cloud_state.py:88-90`
  (`_refresh_cloud_state` docstring's "replaces" list — note `_refresh_map`
  is now actually deleted), `_device_sync.py:224-225`.
- `services.yaml` `replay_session` description: it cites "the next
  `_refresh_map` tick (every 6 hours…)". Repoint to `_refresh_cloud_state`
  (every 2 min). (Behavioral note: replay now clears on the next 2-min
  render instead of 6 h — a strict improvement; the exit mechanism
  `_render_main_view` is unchanged.)

## Architecture after

```
_refresh_cloud_state()            # 2 min timer + awaited once at startup
  └─ fetch_full_cloud_state()     # unified batch (incl. MAP.* → maps_by_id)
  └─ self.cloud_state = new_state # SINGLE map store
  └─ _render_maps_from_cloud_state()   # base PNGs + main view + active base
  └─ _sync_map_subdevices()       # NEW: add/prune (prune guarded vs empty)
  └─ _apply_cloud_state_to_mower_state()
  └─ async_update_listeners()

_session.render_work_log_session()   # last-resort live fetch → cloud_state via replace
_mqtt_handlers (_apply_mapl)         # still calls _sync_map_subdevices on MAPL push
```

No shadow. No disk cache. No `_refresh_map`. One owner, one store.

## Testing

- **Delete** `test_maps_cache_persist.py`. **Update** `test_coordinator.py`
  to drop references to the deleted methods/cache.
- **Add** unit/integration tests:
  1. `_sync_map_subdevices` with empty `maps_by_id` leaves existing per-map
     devices intact (prune-on-empty guard).
  2. `_sync_map_subdevices` with a populated `maps_by_id` still prunes a
     genuinely dropped map (regression guard for the guard).
  3. `_refresh_cloud_state` calls `_sync_map_subdevices` (sub-devices appear
     after a periodic/startup refresh with no MAPL push).
  4. `_session` work-log hydrate writes `cloud_state.maps_by_id`, not a shadow.
- Full unit + integration suite green.
- Live smoke-check (user-led, on the HA box): reload the config entry;
  confirm maps + per-map devices present and populated; call the
  `_refresh_cloud_state` service and confirm a clean re-render; confirm no
  per-map device flapping.

## Out of scope (deferred to their own cycles)

- **Broad refresher consolidation** — `_refresh_cfg`, `_refresh_mihis`,
  `_refresh_dev`, `_refresh_net`, `_poll_slow_properties` are all still
  scheduled despite `_refresh_cloud_state` subsuming their data.
  `_refresh_cfg` carries a regression trap (cfg→MowerState not yet ported
  into `_apply_cloud_state_to_mower_state`), so this needs its own cycle.
- **Static-at-setup per-map entities** — a genuinely new map (added in the
  app) needs a config-entry reload to appear, because each platform calls
  `async_add_entities` once. Pre-existing limitation; not addressed here.

## Push discipline

This redesign is the continuation of B1c. Per the B1c pause note,
`origin/main` currently sits at clean B1b (`3726b63`); the local B1c
reader-routing commits (`9c58ccb`, `52e409f`, `49d58f1`) are unpushed.
Once this redesign lands, passes the suite, and the user's live
smoke-check confirms it, push the whole B1c+redesign sequence to
`origin/main` together so HACS picks up a coherent state.
