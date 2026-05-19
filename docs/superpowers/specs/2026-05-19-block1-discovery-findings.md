# Block 1 — Discovery Findings

**Date:** 2026-05-19
**Status:** in progress — populated task-by-task per plan
**Plan:** `docs/superpowers/plans/2026-05-19-block1-discovery.md`
**Design:** `docs/superpowers/specs/2026-05-19-block1-discovery-design.md`
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Ground truth (meta):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

This document is read-only output of the Block 1 discovery pass. It captures
phase-ready inventories for the four remediation phases (B1a/b/c/d), a
broader sweep of B1 surface findings, and deferred-split sketches for the
four coordinator files >800 LOC.

Every finding uses the format:
`- **[bucket]** \`file.py:LL\` — short description. Evidence: <line>. Disposition: <phase | defer>.`

Buckets: `dead` (remove), `dup` (consolidate), `refactor` (split/simplify), `bug` (fix), `better` (cleaner option).

## 1. B1a — Cleanup inventory

### 1.1 Dead-code candidates

#### Migration files

- **[dead]** `_migration.py:1–468` — entity-registry migration v1→v2 (entry_id → SN-based unique_id rewrite) plus three post-v2 orphan-cleanup helpers (`remove_per_map_wifi_orphans`, `remove_double_prefix_mowing_mode_orphans`).
  Evidence: `__init__.py:38–40` defines HA's `async_migrate_entry` hook delegating to this file; gate at `_migration.py:30` (`if entry.version >= 2: return True`) means the v1→v2 rewrite path is dead for any install already at v2; `config_flow.py:39` sets `VERSION = 2` so every fresh install starts at v2. The two orphan-cleanup helpers (`remove_per_map_wifi_orphans` at line 343, `remove_double_prefix_mowing_mode_orphans` at line 384) run unconditionally on every `async_setup_entry` via imports at `__init__.py:110` and `__init__.py:117–120`; these guard internally against nothing-to-do so they're cheap but permanent noise.
  Disposition: B1a — per memory `feedback_no_migration_overengineering.md`: "single-user dev: skip async_migrate_entry / registry-rename code. Reinstall is fine." Safe to delete `async_migrate_entry` + `_collect_rewrites` + `_apply_rewrites` + `_notify_orphans` (lines 28–57, 235–340, 309–340, 446–468). Orphan-cleanup helpers can be deleted too after confirming no v1 installs remain (both check-and-skip safely if no matching entities exist). Discovery item: verify entry.version == 2 in the live install before removing.

- **[dead]** `_lidar_migration.py:1–75` — one-shot flat→per-map lidar archive layout migration (moves `lidar/*.pcd` + `lidar/index.json` into `lidar/0/`).
  Evidence: `__init__.py:73–93` calls `migrate_flat_lidar_archive` on every setup; the function itself is idempotent (returns 0 if `lidar/0/` already exists, line 37); once migrated it's a pure no-op on every subsequent restart. The T12 flat layout is from before version 1.0.3; any running install will have `lidar/0/` already.
  Disposition: B1a — deletable once we confirm live install has `lidar/0/` (one `ls` check). The `__init__.py` call site (lines 71–93) also deletes. Low-risk removal.

#### Dead branches

No `if False`, `# DEAD`, or true dead-branch patterns found. The `XXX` hits in `_resources.py:96` are an embedded base64 resource, not dead code.

### 1.2 Silent-swallow log additions

All silent swallows are in `cloud_client.py`. The bulk live in two batch parsers — `fetch_full_cloud_state` (14 sites: L1812–L1955, including the L1843 mapIndex cast) and `fetch_map` (L1711, L1727, L1737, L1746) — and the OSS decode helpers `_decode_or_none` (L940), `_decode_candidate` (L1114, L1150), and `fetch_wifi_map` (L973). One login fallback at L340 is bucketed `[better]` (covered by an outer log).

- **[bug]** `cloud_client.py:1711` — silent `except (TypeError, ValueError)` in `fetch_map` MAP.info `int()` parse (fallback to `split_pos=0`).
  Evidence: line 1710: `split_pos = int(info_raw) if info_raw else 0`; except block is single `assign` (split_pos = 0). Parse context is clear; losing the error is harmless but masks corrupt MAP.info values.
  Disposition: B1a — add `_LOGGER.debug("fetch_map: MAP.info parse failed %r: %s", info_raw, e)`.

- **[bug]** `cloud_client.py:1812` — silent `except (TypeError, ValueError)` in `fetch_full_cloud_state` MAP.info `int()` parse.
  Evidence: same pattern as L1711 but in the inline batch-parse branch of `fetch_full_cloud_state`. Single assign (split_pos=0).
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: MAP.info parse failed %r: %s", map_info_raw, e)`.

- **[bug]** `cloud_client.py:1835` — silent `except Exception: continue` in the double-JSON-decode inner loop (MAP segment string → dict).
  Evidence: the inner loop at line 1831–1835 re-parses JSON-string entries; `except Exception: continue` is a single `pass`-equivalent (continue = no log). Any malformed double-encoded map entry is silently skipped.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: MAP entry double-decode failed: %s", e)` before `continue`.

- **[bug]** `cloud_client.py:1843` — silent `except (TypeError, ValueError)` in MAP entry `mapIndex` int cast.
  Evidence: `idx_int = int(idx)` wrapped in try/except assign (idx_int=0). Non-integer mapIndex silently maps to index 0 (clobbers it).
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: mapIndex cast failed %r: %s", idx, e)`.

- **[bug]** `cloud_client.py:1855` — silent `except (TypeError, ValueError)` in M_PATH.info split-pos parse.
  Evidence: `m_split = int(m_path_info) if str(m_path_info).isdigit() else 0`; except assign (m_split=0).
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: M_PATH.info parse failed %r: %s", m_path_info, e)`.

- **[bug]** `cloud_client.py:1866` — silent `except Exception` in SETTINGS batch JSON parse (fallback to `settings_raw = []`).
  Evidence: `settings_raw = _json.loads(settings_joined)` wrapped in try/except assign. Malformed SETTINGS JSON silently produces an empty settings root — all SETTINGS-driven entities go Unknown.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: SETTINGS JSON parse failed: %s", e, exc_info=True)`.

- **[bug]** `cloud_client.py:1879` — silent `except Exception` in SCHEDULE batch JSON parse (fallback to `sched_raw = {}`).
  Evidence: same pattern as L1866. Malformed SCHEDULE JSON silently produces `ScheduleData(version=0, slots=())` — schedule entities go empty.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: SCHEDULE JSON parse failed: %s", e, exc_info=True)`.

- **[bug]** `cloud_client.py:1892` — silent `except Exception` in AI_HUMAN batch JSON parse (fallback to `ai_human_enabled = None`).
  Evidence: `bool(_json.loads(ai_joined))` wrapped in try/except assign. None is a valid sentinel but hides decode errors.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: AI_HUMAN JSON parse failed: %s", e)`.

- **[bug]** `cloud_client.py:1906` — silent `except Exception: pass` in FBD_NTYPE batch JSON parse.
  Evidence: outer try/except at line 1898–1907; body is `pass`. Any FBD_NTYPE decode error silently drops all forbidden-node-type data.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: FBD_NTYPE JSON parse failed: %s", e, exc_info=True)`.

- **[bug]** `cloud_client.py:1918` — silent `except Exception: pass` in OTA_INFO batch JSON parse.
  Evidence: outer try/except at line 1912–1919; body is `pass`. OTA status silently stays None on any decode error.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: OTA_INFO JSON parse failed: %s", e)`.

- **[bug]** `cloud_client.py:1928` — silent `except Exception: pass` in TASKID batch JSON parse.
  Evidence: outer try/except at line 1924–1929; body is `pass`. task_id stays 0 on any decode error.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: TASKID JSON parse failed: %s", e)`.

- **[bug]** `cloud_client.py:1943` — silent `except Exception` in fast-cadence `fetch_locn()` call (fallback to `locn = None`).
  Evidence: meta § 4.3 comment: "Errors here don't fail the whole fetch — fields just stay None/empty." Single assign swallow.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: fetch_locn raised: %s", e)`.

- **[bug]** `cloud_client.py:1947` — silent `except Exception` in fast-cadence `fetch_dock()` call (fallback to `dock = {}`).
  Evidence: same pattern as L1943.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: fetch_dock raised: %s", e)`.

- **[bug]** `cloud_client.py:1951` — silent `except Exception` in fast-cadence `fetch_mapl()` call (fallback to `mapl = None`).
  Evidence: same pattern as L1943.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: fetch_mapl raised: %s", e)`.

- **[bug]** `cloud_client.py:1955` — silent `except Exception` in fast-cadence `fetch_mihis()` call (fallback to `mihis = {}`).
  Evidence: same pattern as L1943.
  Disposition: B1a — add `_LOGGER.debug("parse_full_cloud_state: fetch_mihis raised: %s", e)`.

- **[bug]** `cloud_client.py:940` — silent `except Exception: return None` in `_decode_or_none` OSS JSON parse (`_json_pick.loads(body)`).
  Evidence: `dec = _json_pick.loads(body)` wrapped in try/except return None. Used in the PICK map OSS decode path; any LZ4/JSON error silently returns None, suppressing the candidate entirely.
  Disposition: B1a — add `_LOGGER.debug("_decode_or_none(%s): JSON/LZ4 decode failed: %s", obj_name, e)` before `return None`.

- **[bug]** `cloud_client.py:1114` — silent `except Exception: return None` in `_decode_candidate` WiFi map JSON parse (`_json_lc.loads(body)`).
  Evidence: same pattern as L940 but in the WiFi heatmap candidate decode path.
  Disposition: B1a — add `_LOGGER.debug("_decode_candidate(%s): JSON/LZ4 decode failed: %s", obj_name, e)` before `return None`.

- **[bug]** `cloud_client.py:973` — silent `except (TypeError, ValueError): continue` in `fetch_wifi_map` OSS cell-geometry parse loop. Silently skips any WiFi heatmap candidate whose `startX/startY/width/height/resolution` fields are malformed, dropping that candidate entirely.
  Evidence: `except (TypeError, ValueError): continue` inside the inner candidate-decode loop of `fetch_wifi_map` (function starts line 805); the five float/int casts on `dec.get(...)` fields are wrapped together.
  Disposition: B1a — add `_LOGGER.debug("fetch_wifi_map: skipping candidate %s: malformed cell geometry: %s", obj_name, e)` before `continue`.

- **[bug]** `cloud_client.py:1150` — silent `except (TypeError, ValueError)` in `_decode_candidate` WiFi heatmap cell-geometry; sets fallback `start_x_cm = start_y_cm = 0.0`, `cells_w = cells_h = 0`, `cell_size_m = 1` and continues. Parse failure is hidden behind plausible-looking zero defaults.
  Evidence: `except (TypeError, ValueError):` assigns fallback values instead of `continue`; inside the `_decode_candidate` inner function (defined at line 1100) within `fetch_wifi_map`. The fallback geometry places the candidate at the map origin with zero size, causing the subsequent bbox-centre match to silently mis-assign it.
  Disposition: B1a — add `_LOGGER.debug("_decode_candidate(%s): malformed cell geometry, using fallback zeros: %s", obj_name, e)` before the fallback assignments.

- **[bug]** `cloud_client.py:1727` — silent `except (ValueError, _json.JSONDecodeError): continue` in `fetch_map`'s segment first-pass JSON decode. Any segment string that is not valid JSON is silently skipped.
  Evidence: `except (ValueError, _json.JSONDecodeError): continue` in the outer `for seg in segments` loop of `fetch_map` (function starts line 1668).
  Disposition: B1a — add `_LOGGER.debug("fetch_map: skipping malformed segment: %s", e)` before `continue`.

- **[bug]** `cloud_client.py:1737` — silent `except (ValueError, _json.JSONDecodeError): continue` in `fetch_map`'s inner double-decode loop. A list entry that is a JSON string but fails to decode is silently skipped.
  Evidence: `except (ValueError, _json.JSONDecodeError): continue` inside the `for entry in entries` inner loop of `fetch_map`; handles the case where `entry` is a `str` that was supposed to be a nested JSON map dict.
  Disposition: B1a — add `_LOGGER.debug("fetch_map: skipping malformed double-encoded entry: %s", e)` before `continue`.

- **[bug]** `cloud_client.py:1746` — silent `except (TypeError, ValueError)` in `fetch_map`'s `mapIndex` int cast (parallel pattern to L1843 in `fetch_full_cloud_state`). A non-integer `mapIndex` silently maps to index 0, potentially clobbering a previously decoded map.
  Evidence: `except (TypeError, ValueError): idx_int = 0` wrapping `int(idx)` in the final per-entry indexing step of `fetch_map`.
  Disposition: B1a — add `_LOGGER.debug("fetch_map: mapIndex cast failed %r: %s", idx, e)` before `idx_int = 0`.

- **[better]** `cloud_client.py:340` — silent `except Exception: pass` in login refresh-token fallback (JSON parse of error response).
  Evidence: `json.loads(response.text)` is wrapped; on failure falls through to `_LOGGER.error("Login failed: %s", response.text)`. The `pass` is intentionally safe here — the outer error log always fires.
  Disposition: defer — this one is intentional (outer log covers it); lower priority than the batch-parse cluster.

Summary: 21 `[bug]` findings for B1a, 1 `[better]` deferred. Total silent swallows in `cloud_client.py` discovered by AST scan: 23 (including the 2 int-cast ones at L1711/L1843 caught only by this scan, which meta § 4.3 summarised as "14 in 1835–1960"; actual count in that range is 13, plus L1711/L1843 outside it, plus L940/L1114, plus 5 additional at L973/L1150/L1727/L1737/L1746).

### 1.3 Uncancelled handles / timers

- **[bug]** `coordinator/_device_sync.py:291` — `loop.call_later` debounce handle (`_cloud_refresh_debounce_handle`) stored to `self._cloud_refresh_debounce_handle` but never registered with `entry.async_on_unload` or `self.async_on_remove`.
  Evidence: `_core.py:237` initialises `self._cloud_refresh_debounce_handle = None`; `_device_sync.py:280–291` cancels-then-re-arms on each tripwire call; no `entry.async_on_unload` call wraps the handle. `grep -n "async_on_unload\|_cloud_refresh_debounce" coordinator/_device_sync.py` shows only the cancel-in-arm pattern (line 281) and the arm (line 291). If HA unloads the entry between a tripwire fire and the 5-second timer expiry, `_fire` runs `self.hass.async_create_task(self._refresh_cloud_state())` after the entry is gone — which is a post-unload background task.
  Disposition: B1a — add `entry.async_on_unload(lambda: self._cloud_refresh_debounce_handle and self._cloud_refresh_debounce_handle.cancel())` in `_core.py` alongside the other `async_on_unload` registrations (lines 384–741 block).

All other `async_track_time_interval` calls in `coordinator/_core.py` (lines 384, 396, 408, 421, 435, 448, 462, 474, 512, 529, 675, 735) are correctly registered via `entry.async_on_unload(...)` wrapping the return value. The `call_soon_threadsafe` calls in `_mqtt_handlers.py` (lines 223, 630, 647, 658, 791) are fire-and-forget posts to the event loop — they do not return handles requiring cleanup. No additional leaks found.

### 1.4 Coordinator-mixin import consolidation

All 9 coordinator mixins were generated from the same monolith and carry identical 5-line protocol import blocks and 1-line observability import blocks at module top-level. Most of these imports are dead in the mixin they're in.

#### Protocol import usage table

The import block in each mixin (lines 60–64 or 61–65 or 72–76, depending on file) is:

```python
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import session_summary as _session_summary
from ..protocol import telemetry as _telemetry
from ..protocol import wheel_bind as _wheel_bind
```

Usage = number of `_alias.foo` dot-accesses in the file body (0 = import-only / dead):

| Mixin | `_s2p51` | `_heartbeat` | `_session_summary` | `_telemetry` | `_wheel_bind` | Dead lines |
|---|---|---|---|---|---|---|
| `_core.py` | 0 | 0 | 0 | 0 | 0 | 5 |
| `_cloud_state.py` | 0 | 0 | 0 | 0 | 0 | 5 |
| `_lidar_oss.py` | 0 | 0 | **2** | 0 | 0 | 4 |
| `_mqtt_handlers.py` | 0 | **1** | 0 | 0 | 0 | 4 |
| `_property_apply.py` | **13** | **1** | 0 | **4** | **1** | 1 |
| `_refreshers.py` | **3** | 0 | 0 | 0 | 0 | 4 |
| `_rendering.py` | 0 | 0 | 0* | 0 | 0 | 5* |
| `_session.py` | 0 | 0 | 0* | 0 | 0 | 5* |
| `_writes.py` | 0 | 0 | 0 | 0 | 0 | 5 |
| **Totals** | 3 live | 2 live | 2 live | 1 live | 1 live | **38 dead** |

*`_rendering.py` and `_session.py` both have function-level `from ..protocol import session_summary as _session_summary` re-imports (at lines 292 and 168 respectively) that are used; the module-level import is redundant with those function-level re-imports, so it is still dead at module scope.

**38 dead protocol import lines** (out of 45 total = 9 files × 5 imports).

Individual dead-import findings (B1a):

- **[dead]** `coordinator/_core.py:60–64` — all 5 protocol aliases unused. Evidence: dot-access scan returns 0 for all. Disposition: B1a — delete all 5 lines.
- **[dead]** `coordinator/_cloud_state.py:60–64` — all 5 protocol aliases unused. Evidence: same. Disposition: B1a — delete all 5 lines.
- **[dead]** `coordinator/_lidar_oss.py:61,62,64,65` — `_s2p51`, `_heartbeat`, `_telemetry`, `_wheel_bind` unused (only `_session_summary` is used via dot-access). Evidence: 0 dot-accesses for the 4 dead aliases. Disposition: B1a — delete those 4 lines; keep `from ..protocol import session_summary as _session_summary` (line 63).
- **[dead]** `coordinator/_mqtt_handlers.py:61,63,64,65` — `_s2p51`, `_session_summary`, `_telemetry`, `_wheel_bind` unused (only `_heartbeat` is used). Evidence: 0 dot-accesses for the 4 dead aliases. Disposition: B1a — delete those 4 lines; keep `from ..protocol import heartbeat as _heartbeat` (line 62).
- **[dead]** `coordinator/_property_apply.py:74` — `_session_summary` unused (all other 4 aliases are used). Evidence: 0 dot-accesses for `_session_summary`. Disposition: B1a — delete line 74.
- **[dead]** `coordinator/_refreshers.py:61,62,63,64` — `_heartbeat`, `_session_summary`, `_telemetry`, `_wheel_bind` unused (only `_s2p51` is used). Evidence: 0 dot-accesses for the 4 dead aliases. Disposition: B1a — delete those 4 lines; keep `from ..protocol import config_s2p51 as _s2p51` (line 60).
- **[dead]** `coordinator/_rendering.py:60–64` — all 5 module-level protocol alias imports unused (function-level re-import of `_session_summary` at line 292 shadows the module-level one). Evidence: 0 dot-accesses at module scope. Disposition: B1a — delete all 5 module-level lines; the function-level `from ..protocol import session_summary as _session_summary` at line 292 stays.
- **[dead]** `coordinator/_session.py:60–64` — all 5 module-level protocol alias imports unused (function-level re-import of `_session_summary` at line 168 shadows). Evidence: 0 dot-accesses at module scope. Disposition: B1a — delete all 5 module-level lines; function-level re-import stays.
- **[dead]** `coordinator/_writes.py:60–64` — all 5 protocol aliases unused. Evidence: 0 dot-accesses. Disposition: B1a — delete all 5 lines.

#### Observability import usage table

The import block in each mixin (line 58 or 59 or 70):

```python
from ..observability import FreshnessTracker, NovelObservationRegistry
```

Usage = number of times the type name appears outside the import line (type instantiation in `_core.py.__init__`; `self.freshness` / `self.novel_registry` usage in others):

| Mixin | `FreshnessTracker` (type) | `NovelObservationRegistry` (type) | `self.freshness` | `self.novel_registry` | Dead? |
|---|---|---|---|---|---|
| `_core.py` | 1 (instantiation) | 1 (instantiation) | — | — | live |
| `_cloud_state.py` | 0 | 0 | 0 | 0 | **dead** |
| `_lidar_oss.py` | 0 | 0 | 0 | 1 | **partial** — type dead, instance used |
| `_mqtt_handlers.py` | 0 | 0 | 1 | 4 | **partial** — type dead, instance used |
| `_property_apply.py` | 0 | 0 | 0 | 0 | **dead** |
| `_refreshers.py` | 0 | 0 | 0 | 0 | **dead** |
| `_rendering.py` | 0 | 0 | 0 | 0 | **dead** |
| `_session.py` | 0 | 0 | 0 | 0 | **dead** |
| `_writes.py` | 0 | 0 | 0 | 0 | **dead** |

"Partial" = the imported type names are not used (no `FreshnessTracker(...)` or `NovelObservationRegistry(...)` call), but `self.freshness` / `self.novel_registry` attributes (created by `_core.py`) are accessed via MRO. The import of the type names is still dead in those files; using the instance doesn't require importing the type.

**Dead observability import lines:** 7 files × 1 line = **7 dead** (all except `_core.py`).

Individual dead-import findings:

- **[dead]** `coordinator/_cloud_state.py:58` — `FreshnessTracker, NovelObservationRegistry` imported but never instantiated or referenced. Evidence: 0 type usages, 0 `self.freshness/novel_registry` accesses. Disposition: B1a — delete line.
- **[dead]** `coordinator/_lidar_oss.py:59` — type names unused (only `self.novel_registry` used via MRO). Evidence: type-name scan = 0. Disposition: B1a — delete import; `self.novel_registry` works fine without importing the type.
- **[dead]** `coordinator/_mqtt_handlers.py:58` — type names unused (only `self.freshness` + `self.novel_registry` used via MRO). Evidence: same. Disposition: B1a — delete import.
- **[dead]** `coordinator/_property_apply.py:70` — fully dead. Evidence: 0 type usages, 0 instance accesses. Disposition: B1a — delete line.
- **[dead]** `coordinator/_refreshers.py:58` — fully dead. Evidence: same. Disposition: B1a — delete line.
- **[dead]** `coordinator/_rendering.py:58` — fully dead. Evidence: same. Disposition: B1a — delete line.
- **[dead]** `coordinator/_session.py:58` — fully dead. Evidence: same. Disposition: B1a — delete line.
- **[dead]** `coordinator/_writes.py:58` — fully dead. Evidence: same. Disposition: B1a — delete line.

#### Consolidation options

Total dead imports found: 38 protocol + 7 observability = **45 dead import lines** across the 9 coordinator mixins.

Three consolidation approaches for B1a:

**Option A — Inline-and-delete (recommended for B1a):** Simply delete the dead import lines in each mixin. Live imports stay in-place. No shared module needed. Minimal diff, zero structural change.
- Trade-off: leaves slightly different import sets per mixin (each only imports what it uses), which is the correct state. No coordination cost. Easiest to review.

**Option B — `coordinator/_imports.py` re-export module:** Create a single file that imports all 5 protocol aliases + both observability types, then each mixin imports from `._imports`. Reduces per-mixin boilerplate to 1 line.
- Trade-off: adds indirection; `_imports.py` becomes a hidden dependency; flake8/pylint may complain about re-exporting. Doesn't help once the dead imports are gone (only 3–5 live imports remain per file). Not recommended.

**Option C — Shared mixin base (`_BaseMixin`):** Introduce a `_BaseMixin` that imports and exposes the full set; all other mixins inherit from it.
- Trade-off: creates a class hierarchy where none exists today; the mixin pattern relies on flat MRO; adding a shared base risks ordering issues. Complex for a cosmetic win. Not recommended.

**Recommendation:** Option A. B1a plan should just delete the 45 dead lines file-by-file with a clear checklist.

## 2. B1b — Retry helper inventory

### 2.1 Helper contract

The three existing loops share a common shape but differ on four axes:

| Axis | `request()` L1387 | `get_file()` L1219 | `send()` L578 |
|---|---|---|---|
| Per-attempt action | `requests.post(url, ...)` | `requests.get(url, ...)` | `_api_call(url, ...)` → `request()` |
| Failure predicate | `except requests.exceptions.Timeout` + `except Exception` | `response is None or status_code != 200` | return value shape (`api_response["data"]["result"]` missing or error_code present) |
| Inter-attempt delay | none | none | `time.sleep(8)` on non-80001 failure |
| Attempt count | `retry_count + 1` (default 2 → 3 iters) | `retry_count + 1` (default 4 → 5 iters) | `3` when `method=="action"`, `1` otherwise |
| Deadline | none | none | none |
| Runs on | executor thread (called via `_api_call` from `send`) | executor thread | executor thread / direct call |

All three loops are **synchronous** — they live in blocking code running on an executor thread (the async boundary is above `send()`/`set_property()`). There is no `asyncio.sleep`, no deadline, and no `asyncio.CancelledError` propagation. The finalize-gate in `live_map/finalize.py:32–34` is the only pattern in the codebase that is deadline-bounded and async-cancellable; it is structurally different (deadline gate, not per-call retry) and is noted for contrast only.

**Proposed signature:**

```python
def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int = 3,
    delay_s: float = 0.0,
    should_retry: Callable[[Exception | None], bool] = _is_retryable,
) -> T | None:
    """Synchronous retry helper for blocking HTTP calls on the executor thread.

    Calls action() up to max_attempts times. On exception: calls should_retry(exc) —
    if True, sleeps delay_s and tries again; if False, breaks immediately.
    On non-exception failure (action returns a sentinel): caller wraps the
    check in should_retry(None) convention OR the action raises on failure.
    Returns the first successful result, or None after exhausting attempts.
    """
```

**Rationale for sync sibling only (not async):** all three call sites run in executor threads; introducing `asyncio.sleep` would require `run_coroutine_threadsafe` scaffolding with no benefit. An async sibling (`_http_retry_async`) can be introduced in B1c/later if any call site migrates to a native coroutine, but is out of scope for B1b. The finalize-gate model (async + deadline) is a different pattern and is not unified here.

**Failure predicate unification:** the three sites use heterogeneous checks — `request()` retries on any exception (Timeout or other), `get_file()` retries on bad status code (not exception), `send()` retries on missing result field or non-80001 error_code. The helper's `should_retry` parameter absorbs this per-site variation rather than forcing a single predicate. Default `_is_retryable(exc)` → `exc is not None` covers the `request()`/`get_file()` exception path; `send()` needs a custom predicate or the loop is removed (see § 2.3).

**Deadline:** currently absent in all three sites. No deadline parameter is added in B1b — adding one without an async context would require a threading.Event or monotonic check that adds complexity. Mark as a future improvement (see meta § 4.1).

**Call-site mapping:**

- `request()` at L1387: `action = lambda: self._session.post(url, ...)`, `max_attempts = retry_count + 1`, `delay_s = 0.0`. The `while retries < retry_count + 1` + exception counting is replaced by the helper's loop.
- `get_file()` at L1219: `action = lambda: self._session.get(url, ...)`, `max_attempts = retry_count + 1` (default 4 → 5), `delay_s = 0.0`. Failure predicate checks return value not exception, so either action raises on bad status, or should_retry receives None with status check.
- `send()` at L578 (action path): outer `for attempt in range(3)` loop is **removed** entirely (see § 2.3). The inner `_api_call → request()` loop already handles retries.

### 2.2 Call sites

- **[dup]** `cloud_client.py:1387` — `request()` 3-iter `while retries < retry_count + 1` loop.
  Evidence: `while retries < retry_count + 1` (default `retry_count=2` → 3 iterations); catches `requests.exceptions.Timeout` and bare `Exception`; no inter-attempt sleep; increments `retries` in the `except` blocks only (a successful POST breaks out). See meta § 4.1 row 1.
  Disposition: B1b — replace the `while` loop body with `_http_retry(lambda: self._session.post(...), max_attempts=retry_count + 1, delay_s=0.0)`. Note: `request()` is called via `_api_call()` which is called from executor threads — the sync helper fits without any async boundary changes. The `login()` call on `_key_expire` (L1389) is pre-attempt setup, not per-retry; keep it above the helper call or move into the action lambda with the check inline.

- **[dup]** `cloud_client.py:1219` — `get_file()` 5-iter `while retries < retry_count + 1` loop.
  Evidence: `while retries < retry_count + 1` (default `retry_count=4` → 5 iterations); retries on response-is-None or `status_code != 200` (not on exception — exception is caught and logs warning, sets response=None, then the status check handles it); no inter-attempt sleep. See meta § 4.1 row 2.
  Disposition: B1b — replace the `while` loop with `_http_retry(lambda: self._session.get(url, ...), max_attempts=retry_count + 1, delay_s=0.0)`. The failure predicate is mixed (exception path + bad-status path); cleanest approach is to have the action lambda raise `RuntimeError` on non-200 so the helper's exception-based should_retry handles both paths uniformly.

- **[dup]** `cloud_client.py:578` — `send()` 3-iter `for attempt in range(attempts)` loop (action method only).
  Evidence: `attempts = 3 if method == "action" else 1`; `for attempt in range(attempts)` with an inner `_api_call(url, ..., retry_count)` call (which calls `request()`, which has its own retry loop). Non-action path (`attempts=1`) is effectively no loop. The outer loop adds inter-attempt `time.sleep(8)` on non-80001 error codes. See meta § 4.1 row 3.
  Disposition: B1b — remove the outer `for attempt in range(attempts)` loop entirely (see § 2.3). The inner `request()` retry loop (via `_api_call`) is sufficient; the `delay_s=8.0` can be passed through to `_http_retry` in `request()` if action-method calls warrant a delay, or set via a new `retry_count`+`delay_s` parameter threading from `send()` → `_api_call()` → `request()`. The 80001 fast-break logic (L617) moves into the `should_retry` predicate passed to the helper.

### 2.3 Stacked-loop elimination

- **[bug]** `cloud_client.py:578` — action method effective retry ceiling is 3×3=9, not 3.
  Evidence: `send(method="action")` sets `attempts = 3` and enters `for attempt in range(3)`. Inside the loop body, `_api_call(url, ..., retry_count)` calls `request(url, ..., retry_count)` which runs `while retries < retry_count + 1` with the caller-supplied default `retry_count=2` → 3 inner iterations. Per outer iteration, 3 inner HTTP POST attempts fire before the outer loop sees any result. On non-80001 failure with attempt < 2: `time.sleep(8)` executes on the calling executor thread before the outer loop advances. Worst-case cost: 3 outer × 3 inner = 9 HTTP POST attempts; 2 inter-outer sleeps × 8 s = 16 s of `time.sleep` on the thread (the inner `request()` loop itself has no sleep, so the 8 s fires only between outer iterations, not between inner ones — making the total blocking time 16–24 s depending on timeout accumulation).
  Disposition: B1b — remove the outer `for attempt in range(attempts)` loop entirely. Let the inner `request()` retry loop (controlled by `retry_count` parameter) be the sole retry mechanism. Replace the `time.sleep(8)` inter-outer-iteration delay by threading a `delay_s=8.0` parameter down through `send()` → `_api_call()` → `request()` (or into `_http_retry`'s `delay_s` argument). The 80001 fast-break guard (L617: `if method == "action" and error_code != 80001 and attempt < attempts - 1`) is migrated to a `should_retry` predicate at the `request()` level so a 80001 response still breaks immediately without sleeping. After this change the effective ceiling for action-method calls is `retry_count + 1` (default 3), matching user-visible documentation.

## 3. B1c — `_cached_*` shadow inventory

### 3.1 Every `_cached_*` attribute on the coordinator
(populated by Task 4)

### 3.2 Readers per attribute
(populated by Task 4)

### 3.3 Removal sequence
(populated by Task 4)

## 4. B1d — `cloud_client.py` split plan

### 4.1 Function-by-function placement table
(populated by Task 5)

### 4.2 Module-level state placement
(populated by Task 5)

### 4.3 Test import impact
(populated by Task 5)

## 5. Broader sweep

### 5.1 Refreshers inventory (`_refreshers.py`)
(populated by Task 6)

### 5.2 Settings-write fan-out
(populated by Task 6)

### 5.3 MQTT subscription lifecycle
(populated by Task 6)

### 5.4 Out-of-scope notes (catch-all)
(populated by Task 6)

## 6. Deferred coordinator-split sketches

### 6.1 `coordinator/_core.py`
(populated by Task 7)

### 6.2 `coordinator/_refreshers.py`
(populated by Task 7)

### 6.3 `coordinator/_session.py`
(populated by Task 7)

### 6.4 `coordinator/_mqtt_handlers.py`
(populated by Task 7)
