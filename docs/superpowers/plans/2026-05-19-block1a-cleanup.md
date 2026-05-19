# B1a — Cleanup Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the 8 low-risk cleanup items inventoried in the Block 1 discovery doc — dead code, logging additions, lifecycle-leak fixes, and dead-import removals — without changing any user-visible behaviour.

**Architecture:** Each task is a single concern, edits a bounded set of files, ends with `pytest tests/ -q` green, and produces one commit. Serial execution; commits are independently revertable.

**Tech Stack:** Python (Home Assistant custom integration). `pytest` for regression check. `_LOGGER` is the integration's standard logger (`logging.getLogger(__name__)` in each file).

**Reference docs (do NOT modify):**
- Discovery findings: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`
- B1a design spec: `docs/superpowers/specs/2026-05-19-block1a-cleanup-design.md`
- Parent Block 1 design: `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
- Repo conventions: `CLAUDE.md`

**Output:** ~9 commits prefixed `audit-b1a:`. Push to `origin/main` after T9.

**Hard rules:**
- No edits outside the files named in each task. If a task would need to touch a file not in its scope, STOP and report.
- No new tests added. The existing `tests/` suite is the regression check.
- No refactor beyond the literal action described.
- After each task: `pytest tests/ -q` must be green before committing.

---

## Task 1: Fix stale docstring in `_refresh_cloud_state`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:94`

- [ ] **Step 1: Read context around line 94**

Run: `sed -n '88,98p' custom_components/dreame_a2_mower/coordinator/_cloud_state.py`

You should see a docstring containing the literal text `Called every 10 min` (or similar wording referring to a 10-minute cadence). The actual cadence is 2 min (per `_core.py:386` which schedules `_periodic_cloud_state` at `timedelta(minutes=2)`).

- [ ] **Step 2: Edit the docstring**

Replace the "10 min" wording with the accurate cadence. Use the Edit tool:
- `old_string`: the exact prose mentioning 10 min (e.g. `Called every 10 min`).
- `new_string`: the corrected prose (e.g. `Called every 2 min`).

Keep all other docstring content unchanged.

- [ ] **Step 3: Verify**

Run: `grep -n "10 min" custom_components/dreame_a2_mower/coordinator/_cloud_state.py`
Expected: no output (or only legitimate non-cadence mentions).

Run: `python -m py_compile custom_components/dreame_a2_mower/coordinator/_cloud_state.py`
Expected: no output (clean compile).

- [ ] **Step 4: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_cloud_state.py
git commit -m "audit-b1a: fix stale _refresh_cloud_state docstring (10 min → 2 min)"
```

---

## Task 2: Add `_LOGGER.debug` to 22 silent swallows in `cloud_client.py`

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` (21 sites; the L340 site is `[better]`/deferred per discovery § 1.2)

This task adds exactly **one `_LOGGER.debug` line** per silent-`except` handler. The handler body, fallback assignments, and `continue`/`return` statements are NOT changed — only a logging line is inserted at the top of each handler body.

The proposed log message for each site is taken verbatim from the discovery doc's § 1.2 dispositions.

- [ ] **Step 1: Read each site to confirm shape**

For each line number below, read the file at that line to confirm an `except ...:` handler exists and to understand the local variable names:

```bash
for ln in 940 973 1114 1150 1711 1727 1737 1746 1812 1835 1843 1855 1866 1879 1892 1906 1918 1928 1943 1947 1951 1955; do
  echo "=== L$ln ==="
  sed -n "$((ln-2)),$((ln+5))p" custom_components/dreame_a2_mower/cloud_client.py
done
```

Confirm: each is a real `except` line, the body is silent (no `_LOGGER` call already present), and the local variable names match what the proposed log message references.

- [ ] **Step 2: Add log lines at the 22 sites**

For each site, use Edit to insert exactly one `_LOGGER.debug(...)` line as the FIRST statement of the handler body. Preserve indentation (typically 4 or 8 spaces matching the existing handler body).

The proposed `_LOGGER.debug` lines (verbatim from discovery § 1.2):

| Site | Inserted line (at top of handler body) |
|---|---|
| L1711 | `_LOGGER.debug("fetch_map: MAP.info parse failed %r: %s", info_raw, e)` |
| L1812 | `_LOGGER.debug("parse_full_cloud_state: MAP.info parse failed %r: %s", map_info_raw, e)` |
| L1835 | `_LOGGER.debug("parse_full_cloud_state: MAP entry double-decode failed: %s", e)` |
| L1843 | `_LOGGER.debug("parse_full_cloud_state: mapIndex cast failed %r: %s", idx, e)` |
| L1855 | `_LOGGER.debug("parse_full_cloud_state: M_PATH.info parse failed %r: %s", m_path_info, e)` |
| L1866 | `_LOGGER.debug("parse_full_cloud_state: SETTINGS JSON parse failed: %s", e, exc_info=True)` |
| L1879 | `_LOGGER.debug("parse_full_cloud_state: SCHEDULE JSON parse failed: %s", e, exc_info=True)` |
| L1892 | `_LOGGER.debug("parse_full_cloud_state: AI_HUMAN JSON parse failed: %s", e)` |
| L1906 | `_LOGGER.debug("parse_full_cloud_state: FBD_NTYPE JSON parse failed: %s", e, exc_info=True)` |
| L1918 | `_LOGGER.debug("parse_full_cloud_state: OTA_INFO JSON parse failed: %s", e)` |
| L1928 | `_LOGGER.debug("parse_full_cloud_state: TASKID JSON parse failed: %s", e)` |
| L1943 | `_LOGGER.debug("parse_full_cloud_state: fetch_locn raised: %s", e)` |
| L1947 | `_LOGGER.debug("parse_full_cloud_state: fetch_dock raised: %s", e)` |
| L1951 | `_LOGGER.debug("parse_full_cloud_state: fetch_mapl raised: %s", e)` |
| L1955 | `_LOGGER.debug("parse_full_cloud_state: fetch_mihis raised: %s", e)` |
| L940 | `_LOGGER.debug("_decode_or_none(%s): JSON/LZ4 decode failed: %s", obj_name, e)` |
| L1114 | `_LOGGER.debug("_decode_candidate(%s): JSON/LZ4 decode failed: %s", obj_name, e)` |
| L973 | `_LOGGER.debug("fetch_wifi_map: skipping candidate %s: malformed cell geometry: %s", obj_name, e)` |
| L1150 | `_LOGGER.debug("_decode_candidate(%s): malformed cell geometry, using fallback zeros: %s", obj_name, e)` |
| L1727 | `_LOGGER.debug("fetch_map: skipping malformed segment: %s", e)` |
| L1737 | `_LOGGER.debug("fetch_map: skipping malformed double-encoded entry: %s", e)` |
| L1746 | `_LOGGER.debug("fetch_map: mapIndex cast failed %r: %s", idx, e)` |

**IMPORTANT — exception variable name:** Most handlers in `cloud_client.py` use `except (TypeError, ValueError):` (no `as e` clause). The proposed log lines reference `e`. For each site, check whether the handler is `except ... as e:`. If it is NOT, change it to `except ... as e:` so the log line resolves. Example:

```python
# BEFORE
except (TypeError, ValueError):
    split_pos = 0
```
```python
# AFTER
except (TypeError, ValueError) as e:
    _LOGGER.debug("fetch_map: MAP.info parse failed %r: %s", info_raw, e)
    split_pos = 0
```

If a site already has `as e:`, don't change the clause — just insert the log line.

**IMPORTANT — log message context variables:** The proposed messages reference local variables (`info_raw`, `map_info_raw`, `idx`, `obj_name`, `m_path_info`, `e`). For each site, confirm the variable exists in the immediate scope. If a name doesn't exist (e.g. the actual variable is named differently), substitute the actual name. Don't invent variables.

Apply the 22 inserts one at a time. After each Edit, run `python -m py_compile custom_components/dreame_a2_mower/cloud_client.py` to catch typos immediately.

- [ ] **Step 3: Verify handler-count unchanged**

Run: `grep -c "except Exception\|except (TypeError, ValueError)\|except (ValueError" custom_components/dreame_a2_mower/cloud_client.py`

Capture the count. It MUST equal the pre-edit count (you haven't deleted handlers, only added log lines). If it changes, something went wrong — revert and retry.

- [ ] **Step 4: Verify log-line count grew by 22**

Run: `grep -c "_LOGGER.debug" custom_components/dreame_a2_mower/cloud_client.py`

Capture the count. Compare to the pre-edit count (capture before Step 2). The delta MUST be exactly 22.

- [ ] **Step 5: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py
git commit -m "audit-b1a: log 22 silent exception handlers in cloud_client.py"
```

---

## Task 3: Register `_cloud_refresh_debounce_handle` with `async_on_unload`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` — add one `entry.async_on_unload(...)` registration alongside the existing block at lines ~384–741

The discovery doc § 1.3 specifies the fix: add a registration that cancels the debounce handle on unload, near the other `async_on_unload` calls in `_core.py`.

- [ ] **Step 1: Read the block where other `async_on_unload` registrations live**

Run: `grep -n "entry\.async_on_unload" custom_components/dreame_a2_mower/coordinator/_core.py`

You should see ~12 hits between roughly line 384 and line 741. Pick a spot for the new registration that's coherent — recommend placing it right at the start of the block (just before the first `async_on_unload` call) so it's the first cleanup hook to run on unload.

Confirm `self._cloud_refresh_debounce_handle` is initialised at `_core.py:237` (the discovery doc says so) — run:

```bash
grep -n "_cloud_refresh_debounce_handle" custom_components/dreame_a2_mower/coordinator/_core.py
```

- [ ] **Step 2: Add the registration**

Insert the following block at an appropriate location — right before the first existing `entry.async_on_unload(async_track_time_interval(...))` call (typically around line 384). Use Edit with sufficient surrounding context to make the `old_string` unique:

```python
            # Ensure the debounce handle from _device_sync (set by tripwire
            # callbacks via loop.call_later) doesn't fire into a torn-down
            # coordinator after entry unload.
            def _cancel_debounce_handle() -> None:
                handle = self._cloud_refresh_debounce_handle
                if handle is not None:
                    handle.cancel()
                    self._cloud_refresh_debounce_handle = None

            self.entry.async_on_unload(_cancel_debounce_handle)
```

(Adjust indentation to match the surrounding code — typically 12 spaces inside the `_async_update_data` method body or wherever the `async_on_unload` block lives.)

- [ ] **Step 3: Verify**

Run: `grep -n "_cancel_debounce_handle\|_cloud_refresh_debounce_handle" custom_components/dreame_a2_mower/coordinator/_core.py`

You should see:
- The original init at ~L237 (`self._cloud_refresh_debounce_handle: asyncio.TimerHandle | None = None`)
- The new `def _cancel_debounce_handle` and `entry.async_on_unload(_cancel_debounce_handle)` you just added.

Run: `python -m py_compile custom_components/dreame_a2_mower/coordinator/_core.py`
Expected: clean.

- [ ] **Step 4: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py
git commit -m "audit-b1a: cancel _cloud_refresh_debounce_handle on entry unload"
```

---

## Task 4: Disconnect MQTT client on entry unload

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py:266–280` (`async_unload_entry`)

Discovery § 5.3 confirmed `coordinator._mqtt.disconnect()` is never called on unload — paho background thread + TCP socket are orphaned. The fix is a one-line addition to `async_unload_entry`.

- [ ] **Step 1: Read `async_unload_entry`**

Run: `sed -n '266,285p' custom_components/dreame_a2_mower/__init__.py`

You should see the current shape:
```python
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    LOGGER.info("Unloading %s integration", DOMAIN)
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        handler = getattr(coordinator, "_novel_log_handler", None)
        if handler is not None:
            logging.getLogger("custom_components.dreame_a2_mower").removeHandler(handler)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            async_unregister_services(hass)
    return unload_ok
```

- [ ] **Step 2: Confirm `_mqtt` attribute exists on the coordinator**

Run: `grep -n "self\._mqtt = \|self\._mqtt: " custom_components/dreame_a2_mower/coordinator/_core.py`

You should see the attribute assigned (e.g. `self._mqtt = DreameA2MqttClient(...)` somewhere in `_init_mqtt`). The discovery doc cited `_core.py:769`. Confirm.

Also confirm `DreameA2MqttClient.disconnect()` exists:
```bash
grep -n "def disconnect" custom_components/dreame_a2_mower/mqtt_client.py
```

- [ ] **Step 3: Add the disconnect call**

The disconnect should happen BEFORE platform unload (so subscriptions stop firing into entities that may be torn down). Use Edit to change the inner `if coordinator is not None:` block:

```python
# BEFORE
    if coordinator is not None:
        handler = getattr(coordinator, "_novel_log_handler", None)
        if handler is not None:
            logging.getLogger("custom_components.dreame_a2_mower").removeHandler(handler)
```

```python
# AFTER
    if coordinator is not None:
        # Disconnect MQTT client first so paho thread + TCP socket are
        # released before platform unload tears down entities the
        # callback path writes into. disconnect() is sync — run in
        # executor to keep async_unload_entry non-blocking.
        mqtt = getattr(coordinator, "_mqtt", None)
        if mqtt is not None:
            await hass.async_add_executor_job(mqtt.disconnect)
        handler = getattr(coordinator, "_novel_log_handler", None)
        if handler is not None:
            logging.getLogger("custom_components.dreame_a2_mower").removeHandler(handler)
```

- [ ] **Step 4: Verify**

Run: `grep -n "mqtt.disconnect\|_mqtt.disconnect" custom_components/dreame_a2_mower/__init__.py`
Expected: one match in `async_unload_entry`.

Run: `python -m py_compile custom_components/dreame_a2_mower/__init__.py`
Expected: clean.

- [ ] **Step 5: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py
git commit -m "audit-b1a: disconnect MQTT client on entry unload"
```

---

## Task 5: Remove 38 dead protocol imports across 9 coordinator mixins

**Files (all modify):**
- `custom_components/dreame_a2_mower/coordinator/_core.py` — delete 5 lines (60–64)
- `custom_components/dreame_a2_mower/coordinator/_cloud_state.py` — delete 5 lines (60–64)
- `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` — delete 4 lines (61, 62, 64, 65); keep line 63
- `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` — delete 4 lines (61, 63, 64, 65); keep line 62
- `custom_components/dreame_a2_mower/coordinator/_property_apply.py` — delete 1 line (74)
- `custom_components/dreame_a2_mower/coordinator/_refreshers.py` — delete 4 lines (61, 62, 63, 64); keep line 60
- `custom_components/dreame_a2_mower/coordinator/_rendering.py` — delete 5 lines (60–64)
- `custom_components/dreame_a2_mower/coordinator/_session.py` — delete 5 lines (60–64)
- `custom_components/dreame_a2_mower/coordinator/_writes.py` — delete 5 lines (60–64)

Per discovery § 1.4, every line above is a `from ..protocol import <name> as <alias>` line where the alias is unused in the file body.

- [ ] **Step 1: Verify each line BEFORE deleting**

For each file/line, confirm the line matches the expected pattern. Example for `_core.py`:

```bash
sed -n '60,64p' custom_components/dreame_a2_mower/coordinator/_core.py
```

Expected output for `_core.py:60–64`:
```
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import session_summary as _session_summary
from ..protocol import telemetry as _telemetry
from ..protocol import wheel_bind as _wheel_bind
```

Do the same `sed -n 'A,Bp'` check for every file in the list above. If any file's line numbers don't match the expected import pattern, STOP — the file may have drifted; report and re-check the discovery doc.

- [ ] **Step 2: Delete the dead lines**

For each file, use Edit with `replace_all: false`. The `old_string` is the dead import line(s), the `new_string` is empty (delete) OR the surviving lines (if some imports in the block survive).

Example for `_lidar_oss.py` (delete 4, keep `_session_summary`):

`old_string`:
```
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import session_summary as _session_summary
from ..protocol import telemetry as _telemetry
from ..protocol import wheel_bind as _wheel_bind
```

`new_string`:
```
from ..protocol import session_summary as _session_summary
```

Do this file-by-file. After each Edit, `python -m py_compile <file>` to catch errors.

- [ ] **Step 3: Verify dead protocol imports are gone**

Run: 
```bash
for f in coordinator/_core.py coordinator/_cloud_state.py coordinator/_writes.py coordinator/_rendering.py coordinator/_session.py; do
  echo "=== $f ==="
  grep -n "from \.\.protocol import" custom_components/dreame_a2_mower/$f
done
```

Expected for these 5 files: no output (all 5 protocol imports were dead and got deleted).

For the others:
```bash
grep -n "from \.\.protocol import" custom_components/dreame_a2_mower/coordinator/_lidar_oss.py
# expect: ONE line — session_summary
grep -n "from \.\.protocol import" custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py
# expect: ONE line — heartbeat
grep -n "from \.\.protocol import" custom_components/dreame_a2_mower/coordinator/_property_apply.py
# expect: FOUR lines — _s2p51, _heartbeat, _telemetry, _wheel_bind
grep -n "from \.\.protocol import" custom_components/dreame_a2_mower/coordinator/_refreshers.py
# expect: ONE line — _s2p51
```

- [ ] **Step 4: Verify imports compile and resolve**

Run:
```bash
python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator; print('OK')"
```
Expected: prints `OK`. If it fails with `NameError` for any alias, you deleted an import that's actually used — revert that file and re-check the usage with `grep -n "_<alias>\." <file>`.

- [ ] **Step 5: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/
git commit -m "audit-b1a: remove 38 dead protocol imports across 9 coordinator mixins"
```

---

## Task 6: Remove 7 dead observability imports across 8 coordinator mixins

**Files (all modify):**
- `custom_components/dreame_a2_mower/coordinator/_cloud_state.py` — delete line 58
- `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` — delete line 59
- `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` — delete line 58
- `custom_components/dreame_a2_mower/coordinator/_property_apply.py` — delete line 70
- `custom_components/dreame_a2_mower/coordinator/_refreshers.py` — delete line 58
- `custom_components/dreame_a2_mower/coordinator/_rendering.py` — delete line 58
- `custom_components/dreame_a2_mower/coordinator/_session.py` — delete line 58
- `custom_components/dreame_a2_mower/coordinator/_writes.py` — delete line 58

`_core.py` keeps its observability import (it instantiates `FreshnessTracker` and `NovelObservationRegistry`).

The import being deleted in each file is:
```python
from ..observability import FreshnessTracker, NovelObservationRegistry
```

- [ ] **Step 1: Verify each line BEFORE deleting**

For each file/line, confirm the line matches. Example:

```bash
sed -n '58p' custom_components/dreame_a2_mower/coordinator/_cloud_state.py
```

Expected: `from ..observability import FreshnessTracker, NovelObservationRegistry`

Do this for every file in the list above. If any line content doesn't match, STOP and re-check.

- [ ] **Step 2: Delete each line**

For each file, use Edit with the import line as `old_string` and empty `new_string`. After each Edit, `python -m py_compile <file>`.

- [ ] **Step 3: Verify**

Run:
```bash
for f in coordinator/_cloud_state.py coordinator/_lidar_oss.py coordinator/_mqtt_handlers.py coordinator/_property_apply.py coordinator/_refreshers.py coordinator/_rendering.py coordinator/_session.py coordinator/_writes.py; do
  if grep -q "from \.\.observability import" custom_components/dreame_a2_mower/$f; then
    echo "LEFTOVER: $f"
  fi
done
```
Expected: no `LEFTOVER` output.

Confirm `_core.py` still has its import:
```bash
grep -n "from \.\.observability import" custom_components/dreame_a2_mower/coordinator/_core.py
```
Expected: one line (`FreshnessTracker, NovelObservationRegistry`).

Run the import sanity check:
```bash
python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator; print('OK')"
```

- [ ] **Step 4: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/
git commit -m "audit-b1a: remove 7 dead observability imports across 8 coordinator mixins"
```

---

## Task 7: Delete `_lidar_migration.py` and its caller

**Files:**
- Delete: `custom_components/dreame_a2_mower/_lidar_migration.py`
- Modify: `custom_components/dreame_a2_mower/__init__.py:71–93` (remove the lidar-migration call block)

Pre-flight check ensures the live install already has the post-migration layout (`lidar/0/`).

- [ ] **Step 1: Pre-flight — confirm the migration is already a no-op on the live install**

The function `migrate_flat_lidar_archive(root)` returns 0 if `root / "0"` exists. The lidar archive root on the live HA is `<config>/dreame_a2_mower/lidar/`. Confirm via SSH or shell on the HA host:

```bash
# Run from the HA host (or via the user's SSH credentials per memory)
ls /config/dreame_a2_mower/lidar/0/ 2>&1 | head -3
```

If the user can confirm the directory exists, the migration is already a no-op and deletion is safe. If unable to confirm, halt and ask the user.

- [ ] **Step 2: Read the caller block in `__init__.py`**

Run: `sed -n '70,95p' custom_components/dreame_a2_mower/__init__.py`

You should see:
```python
    # T12: one-shot migration of pre-T12 flat lidar archive → per-map subdirs.
    # Runs in an executor so it's non-blocking on the event loop.
    from ._lidar_migration import migrate_flat_lidar_archive as _migrate_lidar
    moved = await hass.async_add_executor_job(
        _migrate_lidar, coordinator._lidar_archive_root
    )
    if moved:
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"{DOMAIN}: lidar archive migrated to per-map layout",
                    "message": (
                        f"Moved {moved} file(s) into `lidar/0/`. "
                        f"Pre-T12 flat scans now live under map 0; "
                        f"future scans route correctly per active map."
                    ),
                    "notification_id": f"{DOMAIN}_lidar_v2_migration",
                },
                blocking=False,
            )
        )
```

- [ ] **Step 3: Remove the caller block**

Use Edit. `old_string` is the block above (lines ~71–93). `new_string` is empty (delete the block; leave surrounding code untouched).

After the edit, verify the surrounding lines flow naturally — `sed -n '65,80p' custom_components/dreame_a2_mower/__init__.py` should show the `coordinator = DreameA2MowerCoordinator(...)` line followed by the next meaningful step (`await coordinator.async_config_entry_first_refresh()` is line 95 in original; after deletion it should sit close to where the coordinator is created).

- [ ] **Step 4: Delete the migration file**

Run: `rm custom_components/dreame_a2_mower/_lidar_migration.py`

- [ ] **Step 5: Confirm no other references remain**

Run: `grep -rn "_lidar_migration\|migrate_flat_lidar_archive" custom_components/dreame_a2_mower --include='*.py'`
Expected: no output.

Run: `python -m py_compile custom_components/dreame_a2_mower/__init__.py`
Expected: clean.

Run: `python -c "from custom_components.dreame_a2_mower import async_setup_entry; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 6: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py custom_components/dreame_a2_mower/_lidar_migration.py
git commit -m "audit-b1a: delete _lidar_migration.py (no-op on all current installs)"
```

---

## Task 8: Delete `_migration.py` and its callers

**Files:**
- Delete: `custom_components/dreame_a2_mower/_migration.py`
- Modify: `custom_components/dreame_a2_mower/__init__.py` — remove 4 references to `_migration`:
  1. Top-level import (`from ._migration import async_migrate_entry as _async_migrate_entry` at line ~13)
  2. `async_migrate_entry` HA hook function (~lines 37–40)
  3. Conditional v1→v2 retry block (~lines 102–104)
  4. `remove_per_map_wifi_orphans` call block (~lines 107–112)
  5. `remove_double_prefix_mowing_mode_orphans` call block (~lines 114–123)

(Five references; the function block at lines 37–40 is one of them.)

Pre-flight confirms the live `config_entry.version == 2`.

- [ ] **Step 1: Pre-flight — confirm live config_entry.version == 2**

The discovery doc § 1.1 says: "Discovery item: verify entry.version == 2 in the live install before removing."

The user can read this via the HA REST API or via WebSocket:
```bash
# Replace TOKEN with the user's long-lived access token; replace HOST with the HA URL
curl -sH "Authorization: Bearer TOKEN" "http://HOST:8123/api/config/config_entries/entry" 2>/dev/null \
  | python -c "import sys, json; d=json.load(sys.stdin); [print(e['domain'], e.get('version')) for e in d if e['domain']=='dreame_a2_mower']"
```

(Or the user reads it directly from `/config/.storage/core.config_entries` — `grep -A20 '"domain": "dreame_a2_mower"' /config/.storage/core.config_entries | grep '"version"'`.)

Expected: `version: 2`. If the user reports anything else, halt — migration code is still load-bearing and must NOT be deleted.

- [ ] **Step 2: Read all 5 reference blocks**

```bash
grep -n "_migration\|async_migrate_entry" custom_components/dreame_a2_mower/__init__.py
```

You should see references at lines 13 (import), 37–40 (function), 102–104 (conditional), 107–112 (wifi orphans), 114–123 (mowing-mode orphans). Sed each block to read context:

```bash
for range in '12,14' '37,41' '100,106' '105,114' '114,125'; do
  echo "=== $range ==="
  sed -n "${range}p" custom_components/dreame_a2_mower/__init__.py
done
```

- [ ] **Step 3: Remove the top-level import**

Use Edit:
- `old_string`: `from ._migration import async_migrate_entry as _async_migrate_entry`
- `new_string`: (empty — delete the line)

- [ ] **Step 4: Remove the `async_migrate_entry` HA hook function**

Use Edit:
- `old_string`:
```python
async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """HA hook: run on integration setup when entry.version < class.VERSION."""
    return await _async_migrate_entry(hass, entry)
```
- `new_string`: (empty — delete the function)

This is HA's `async_migrate_entry` hook. Removing it means HA will never call migration code on this integration. Since `VERSION = 2` and any live install is at v2, the hook is a no-op anyway. Per memory `feedback_no_migration_overengineering.md`, this is the right call.

- [ ] **Step 5: Remove the v1→v2 retry block**

Use Edit:
- `old_string`:
```python
    if entry.version < 2:
        from ._migration import async_migrate_entry as _migrate
        await _migrate(hass, entry)
```
- `new_string`: (empty — delete the 3-line block)

- [ ] **Step 6: Remove the `remove_per_map_wifi_orphans` call block**

Use Edit:
- `old_string`:
```python
    # Task 9: remove per-map WiFi entity orphans left behind when
    # DreameA2RequestWifiMapButton and DreameA2WifiMapCamera were deleted in
    # Task 8 of the wifi-heatmap-archive plan. Runs on every setup so it
    # catches installs that were already at v2 before Task 8 shipped.
    from ._migration import remove_per_map_wifi_orphans as _remove_wifi_orphans
    await _remove_wifi_orphans(hass, entry)
```
- `new_string`: (empty)

- [ ] **Step 7: Remove the `remove_double_prefix_mowing_mode_orphans` call block**

Use Edit:
- `old_string`:
```python
    # P2-4 follow-up: drop `select.map_<N>_map_<N>_mowing_mode` orphans
    # produced by the double-prefix bug in the initial MowingModeSelect
    # implementation. Fixed by switching to a static `_attr_name`; this
    # call frees the slug so HA can re-register as `select.map_<N>_mowing_mode`.
    from ._migration import (
        remove_double_prefix_mowing_mode_orphans as _remove_mm_orphans,
    )
    await _remove_mm_orphans(hass, entry)
```
- `new_string`: (empty)

- [ ] **Step 8: Delete the migration file**

Run: `rm custom_components/dreame_a2_mower/_migration.py`

- [ ] **Step 9: Confirm no leftover references**

Run: `grep -rn "_migration\|async_migrate_entry\|_remove_wifi_orphans\|_remove_mm_orphans\|remove_per_map_wifi_orphans\|remove_double_prefix_mowing_mode_orphans" custom_components/dreame_a2_mower --include='*.py'`
Expected: no output. (Comments mentioning "migration" elsewhere are fine — only Python symbol references should be checked, but the grep above will catch most.)

If the grep finds something in `coordinator/__init__.py` or similar, investigate — it may be a legitimate `import` chain we hadn't seen.

Run: `python -c "from custom_components.dreame_a2_mower import async_setup_entry; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 10: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass. Note: there may be tests in `tests/` that reference `_migration.py` directly — if `pytest` complains about an import error from a test file, the test was testing the migration code and should also be deleted. Surface the failing test name to the user before deleting.

- [ ] **Step 11: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py custom_components/dreame_a2_mower/_migration.py
git commit -m "audit-b1a: delete _migration.py (v1->v2 migration is a no-op on all current installs)"
```

---

## Task 9: Final verification + push

**Files:** none (read-only verification).

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -q
```
Expected: all tests pass.

- [ ] **Step 2: Compile every integration file**

```bash
python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py' -not -path '*/__pycache__/*')
```
Expected: clean (no output).

- [ ] **Step 3: Confirm integration imports cleanly**

```bash
python -c "from custom_components.dreame_a2_mower import const; print(const.DOMAIN)"
python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator; print(DreameA2MowerCoordinator.__name__)"
```
Expected: prints `dreame_a2_mower` then `DreameA2MowerCoordinator`.

- [ ] **Step 4: Run `inventory_audit.py`**

```bash
python tools/inventory_audit.py
```
Expected: passes (no `[error]` output). If it fails, fix the inventory before declaring B1a done.

- [ ] **Step 5: Confirm no references to deleted files**

```bash
grep -rn "_migration\b\|_lidar_migration\b\|migrate_flat_lidar_archive\|async_migrate_entry\|remove_per_map_wifi_orphans\|remove_double_prefix_mowing_mode_orphans" \
  custom_components/dreame_a2_mower --include='*.py'
```
Expected: no output.

- [ ] **Step 6: Confirm dead imports are gone**

```bash
# Protocol imports — only live ones should remain
grep -rn "from \.\.protocol import" custom_components/dreame_a2_mower/coordinator/ --include='*.py'
# Expected: 9 lines total (1 in _lidar_oss, 1 in _mqtt_handlers, 4 in _property_apply, 1 in _refreshers,
# plus 1 function-level reimport in _rendering.py:292 and 1 in _session.py:168)

# Observability imports — only _core.py should remain
grep -ln "from \.\.observability import" custom_components/dreame_a2_mower/coordinator/*.py
# Expected: only _core.py
```

- [ ] **Step 7: Confirm 22 new log lines exist in cloud_client.py**

```bash
grep -c "_LOGGER.debug" custom_components/dreame_a2_mower/cloud_client.py
```
Note the count. Compare to the pre-B1a count. Delta should be exactly 22 (one per swallow site touched in Task 2).

- [ ] **Step 8: Push to origin/main**

```bash
git push origin main
```

Per memory `feedback_push_upstream_regularly.md`: HACS pulls from origin/main; push to keep history visible.

- [ ] **Step 9: User-led smoke check**

After push, the user does this on their live HA:
1. Reload the integration config entry from the HA UI (or restart HA).
2. Confirm every entity that existed pre-B1a still exists post-B1a with the same `entity_id` (`developer-tools → states`).
3. Confirm the `Refresh from cloud` button still triggers a refresh.
4. Confirm `Logbook` and `Events` for the mower still emit lifecycle entries when state changes.

If the user reports a regression, identify the offending commit by bisecting (`git bisect` across the B1a commits) and revert it. Each B1a task is one commit — single-revert recovery.

---

## Done

After Task 9 passes, B1a is complete. The remaining Block 1 phases are:

- **B1b:** retry helper consolidation (discovery § 2)
- **B1c:** `_cached_*` shadow removal + redundant refresher deletion (discovery § 3 + § 5.1)
- **B1d:** `cloud_client.py` file split (discovery § 4)

Each gets its own brainstorm → spec → plan → execute cycle.
