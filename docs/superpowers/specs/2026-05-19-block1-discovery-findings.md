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

- **[dead]** `_settings_writes.py:1–77` — shared optimistic-write helper for SETTINGS-driven entities (consolidates the revert-on-failure pattern).
  Evidence: actively imported and used: `switch.py:1306–1307`, `select.py:49–50`, `number.py:683`. This file is NOT dead — it is a live, actively called utility.
  Disposition: defer — keep as-is. No finding needed.

#### Dead branches

- **[dead]** `cloud_client.py:545` — `"from": "XXXXXX"` placeholder string inside an HTTP request body.
  Evidence: `grep -n '"from": "XXXXXX"' cloud_client.py` → lines 545, 590. These are intentional placeholder values in cloud API payloads (the field name is `"from"` and the value is a redacted credential or device ID that was anonymized in source). Not a dead branch — a runtime value that happens to look like a placeholder.
  Disposition: defer — not dead code; these are intentional obfuscated fields in the cloud API body.

No `if False`, `# DEAD`, or true dead-branch patterns found. The `XXX` hits in `_resources.py:96` are an embedded base64 resource, not dead code.

### 1.2 Silent-swallow log additions

All sites are in `cloud_client.py` within `fetch_full_cloud_state` (lines 1757–1957) plus two OSS JSON helpers and one login fallback path.

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

- **[better]** `cloud_client.py:340` — silent `except Exception: pass` in login refresh-token fallback (JSON parse of error response).
  Evidence: `json.loads(response.text)` is wrapped; on failure falls through to `_LOGGER.error("Login failed: %s", response.text)`. The `pass` is intentionally safe here — the outer error log always fires.
  Disposition: defer — this one is intentional (outer log covers it); lower priority than the batch-parse cluster.

Summary: 16 `[bug]` findings for B1a, 1 `[better]` deferred. Total silent swallows in `cloud_client.py` discovered by AST scan: 18 (including the 2 int-cast ones at L1711/L1843 caught only by this scan, which meta § 4.3 summarised as "14 in 1835–1960"; actual count in that range is 13, plus L1711/L1843 outside it, plus L940/L1114).

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
| `_property_apply.py` | **13** | **1** | 0 | **5** | **1** | 1 |
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
(populated by Task 3)

### 2.2 Call sites
(populated by Task 3)

### 2.3 Stacked-loop elimination
(populated by Task 3)

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
