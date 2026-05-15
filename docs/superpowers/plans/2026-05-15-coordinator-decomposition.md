# Coordinator Decomposition — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md`
**Status:** Plan ready to execute
**Date:** 2026-05-15

Executes the spec end-to-end: 12 sequential tasks. Each task is mechanical (move code from `coordinator.py` to a new mixin file), runs the full test suite before commit, and produces one focused diff.

## Pre-flight findings (from 2026-05-15 survey)

The survey turned up details the spec didn't anticipate. Plan incorporates them:

- **Module-level helpers (lines 70-580 of current coordinator.py) need their own submodule** — `_property_apply.py`. 8 functions + 7 constants live there. Extraction is task 1 (smallest, leaf-most).
- **External imports of private symbols must be re-exported** from `coordinator/__init__.py`:
  - `_project_north_east` — used in `number.py:539` (delayed import) and `tests/state_machine/test_position_projection.py:15`.
  - `apply_property_to_state`, `_BLOB_SLOTS`, `_SUPPRESSED_SLOTS` — used in `tests/integration/test_probe_type_check.py:8`.
- **MRO compatibility low-risk.** `conftest.py:217` already uses multi-base inheritance with `CoordinatorEntity` subclasses; no metaclass conflict expected.
- **Line-number refs in inventory.yaml** (~20 entries pointing at `coordinator.py:80` etc.) — deferred to a post-refactor sweep task.

## Final mixin layout

```
custom_components/dreame_a2_mower/coordinator/
  __init__.py               # exports DreameA2MowerCoordinator + re-exports legacy symbols (~80 LOC)
  _property_apply.py        # module-level helpers + constants (~510 LOC)
  _wifi_archive.py          # WiFi archive refresh (~170 LOC)
  _device_sync.py           # device registry + sub-device sync + lifecycle events (~250 LOC)
  _lidar_oss.py             # LiDAR archive + OSS fetch (~430 LOC)
  _rendering.py             # main view + live trail + obstacle overlay (~250 LOC)
  _session.py               # restore + persist + finalize + replay + work-log render (~700 LOC)
  _writes.py                # settings + action writes (~500 LOC)
  _mqtt_handlers.py         # MQTT message routing + state update + event_occured (~700 LOC)
  _cloud_state.py           # cloud_state apply + map fetch/persist (~400 LOC)
  _refreshers.py            # all _refresh_* methods (~900 LOC)
  _core.py                  # __init__, _async_update_data, properties (~500 LOC)
```

11 submodules. `coordinator.py` becomes a 1-line re-export at the end (task 12).

## Tasks

Each task: identify methods → cut from `coordinator.py` → paste into new mixin file → register in `__init__.py` → run `pytest tests/` → commit.

If pytest fails: do NOT commit. Fix or back out before moving on.

### Task 1 — Setup: create the package shell

**Subject:** `chore(coordinator): create coordinator/ package shell`

Create `coordinator/` directory with:

- `coordinator/__init__.py` containing only:
  ```python
  from __future__ import annotations
  # Transitional shim — re-export from the old coordinator.py while the
  # package is being assembled. Final form replaces this with the
  # full mixin-assembly class. See spec
  # docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
  from ..coordinator import (
      DreameA2MowerCoordinator,
      apply_property_to_state,
      _BLOB_SLOTS,
      _SUPPRESSED_SLOTS,
      _project_north_east,
  )

  __all__ = [
      "DreameA2MowerCoordinator",
      "apply_property_to_state",
      "_BLOB_SLOTS",
      "_SUPPRESSED_SLOTS",
      "_project_north_east",
  ]
  ```

Wait — this won't work because `coordinator/` would shadow `coordinator.py` (Python prefers packages). **Drop the transitional shim**. Instead: skip task 1's separate "shell" commit. Roll the package creation into task 2 (the first real extraction), where `coordinator/__init__.py` imports from the new `_property_apply.py` submodule that task 2 creates.

**Task 1 is therefore a no-op**: confirm the spec, run `pytest tests/` to baseline. No commit.

**Acceptance:** `pytest tests/` exits 0 with no changes.

### Task 2 — Extract `_property_apply.py` (module-level helpers + constants)

**Subject:** `refactor(coordinator): extract module-level helpers to _property_apply submodule`

Move (verbatim, no body edits) from `coordinator.py` lines roughly 70–580:

**Constants:**
- `_SESSION_SUMMARY_CHECK`
- `_BLOB_SLOTS`
- `_INVENTORY`
- `_SUPPRESSED_SLOTS`
- `_SETTINGS_TRIPWIRE_SLOTS`
- `S2P2_NOTIFICATION_MAP`
- `S2P2_NOVEL_EVENT_TYPE`

**Functions:**
- `_coerce_blob`
- `_apply_s1p1_heartbeat`
- `_apply_s1p4_telemetry`
- `_project_north_east`
- `_apply_s2p51_settings`
- `_consumable_pct_remaining`
- `_apply_consumables`
- `apply_property_to_state`

Plus their supporting imports at the top of the new module.

Create `coordinator/__init__.py`:

```python
from __future__ import annotations
# Mixin-assembled coordinator. See spec
# docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
from ._property_apply import (
    apply_property_to_state,
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    _project_north_east,
)
# Re-import DreameA2MowerCoordinator from the legacy module until the
# mixin chain is assembled. Final state (after task 12) replaces this
# import with a from-package class definition.
from .._coordinator_legacy import DreameA2MowerCoordinator

__all__ = [
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "_project_north_east",
]
```

Rename existing `coordinator.py` → `_coordinator_legacy.py` for the duration of the refactor. Importers of `from .coordinator import X` continue to resolve through the new `coordinator/` package's `__init__.py`. Internal refactor housekeeping; no module outside `coordinator/` imports `_coordinator_legacy` directly.

In `_coordinator_legacy.py`, change the imports of the helpers — remove the original definitions and add `from .coordinator._property_apply import (...)`.

**Tests to run:**
- `pytest tests/integration/test_probe_type_check.py` — uses `apply_property_to_state`, `_BLOB_SLOTS`, `_SUPPRESSED_SLOTS`.
- `pytest tests/state_machine/test_position_projection.py` — uses `_project_north_east`.
- `pytest tests/` — full suite.

**Acceptance:** 596 tests pass. `git diff` shows: `coordinator.py` renamed to `_coordinator_legacy.py` with the helpers' bodies removed and replaced with `from .coordinator._property_apply import ...`; new `coordinator/__init__.py` + `coordinator/_property_apply.py` created.

### Task 3 — Extract `_wifi_archive` mixin (~170 LOC)

**Subject:** `refactor(coordinator): extract _wifi_archive mixin`

Methods to move from `_coordinator_legacy.py` (the renamed coordinator.py):

- `refresh_wifi_archive` (line ~1638 in current file)
- `_download_and_archive_wifi`
- `_read_session_wifi_samples`
- `_tag_wifi_archive_map_ids`

Create `coordinator/_wifi_archive.py`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # add cross-mixin imports here only if needed

class _WifiArchiveMixin:
    async def refresh_wifi_archive(self) -> dict:
        ...
    def _download_and_archive_wifi(self, ...) -> None:
        ...
    # etc.
```

Register in `coordinator/__init__.py`:

```python
from ._wifi_archive import _WifiArchiveMixin

# After task 12: assembled DreameA2MowerCoordinator inherits from
# every mixin + DataUpdateCoordinator. During tasks 2-11, the legacy
# class still owns __init__ and runtime state; mixins coexist on a
# transitional class.
```

**Transitional pattern:** during tasks 2-11, the legacy `DreameA2MowerCoordinator` class (in `_coordinator_legacy.py`) inherits the new mixin(s) AND keeps its own method implementations for everything not-yet-extracted. As methods are extracted, they're cut from the legacy class and become the mixin's. The mixin always sits before `DataUpdateCoordinator` in the MRO, so the moved method definitions take precedence.

Concretely, in `_coordinator_legacy.py`:

```python
from .coordinator._wifi_archive import _WifiArchiveMixin

class DreameA2MowerCoordinator(
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    ...  # all not-yet-extracted methods
```

Each subsequent task adds another mixin to the inheritance list.

**Acceptance:** `pytest tests/` passes. Diff: 4 method definitions cut from `_coordinator_legacy.py`, new `_wifi_archive.py` created, inheritance list updated.

### Task 4 — Extract `_device_sync` mixin (~250 LOC)

**Subject:** `refactor(coordinator): extract _device_sync mixin`

Methods:

- `_sync_map_subdevices`
- `_update_device_registry_serial`
- `_get_device_registry`
- `_handle_emergency_stop_transition`
- `_schedule_cloud_refresh`
- `_compute_target_area_m2`
- `register_event_entities`
- `_fire_lifecycle`
- `_fire_mowing_ended`
- `_fire_alert`

**Acceptance:** pytest passes. Diff: 10 methods cut + mixin file + inheritance list updated.

### Task 5 — Extract `_lidar_oss` mixin (~430 LOC)

**Subject:** `refactor(coordinator): extract _lidar_oss mixin`

Methods:

- `_handle_lidar_object_name`
- `_do_oss_fetch`
- `lidar_archive_for`
- `list_lidar_archive_entries`
- `set_lidar_render_entry`
- `_build_map_extents`
- `set_wifi_render_entry`

**Acceptance:** pytest passes. Cross-check: `select.py` calls `set_lidar_render_entry` / `set_wifi_render_entry` — these remain callable via `self.coordinator.set_lidar_render_entry(...)` because the mixin's method dispatches through MRO.

### Task 6 — Extract `_rendering` mixin (~250 LOC)

**Subject:** `refactor(coordinator): extract _rendering mixin`

Methods:

- `_render_main_view`
- `_rerender_live_trail`
- `_load_last_session_obstacles`
- `_render_active_map_base`
- `_current_mower_position`
- `_current_mower_heading`

**Acceptance:** pytest passes. The v1.0.11a3 obstacle-cache race fix lives in `_load_last_session_obstacles` — verify the `_index_loaded` guard moves verbatim.

### Task 7 — Extract `_session` mixin (~700 LOC)

**Subject:** `refactor(coordinator): extract _session mixin`

Methods:

- `_restore_in_progress`
- `_persist_in_progress`
- `_run_finalize_incomplete`
- `_dispatch_finalize_action`
- `replay_session`
- `render_work_log_session`
- `_periodic_session_retry`
- `_resolve_finalize_map_id`

**Acceptance:** pytest passes. Session-finalize edge cases live here; the snapshot test suite (`tests/state_machine/*`) covers the recovery paths.

### Task 8 — Extract `_writes` mixin (~500 LOC)

**Subject:** `refactor(coordinator): extract _writes mixin`

Methods:

- `write_settings`
- `write_schedule`
- `write_ai_human_enabled`
- `write_setting`
- `_dispatch_cfg_write`
- `dispatch_action`
- `_ensure_active_map`
- `_fetch_fresh_settings_blob`
- `start_mowing_all_areas`
- `start_mowing_edge`
- `start_mowing_zone`
- `start_mowing_spot`

**Acceptance:** pytest passes. The settings-cloud-cache-only finding from 2026-05-09 lives in `write_settings`; verify the diff is purely a move.

### Task 9 — Extract `_mqtt_handlers` mixin (~700 LOC)

**Subject:** `refactor(coordinator): extract _mqtt_handlers mixin`

Methods:

- `_on_mqtt_message`
- `_on_state_update`
- `_handle_event_occured`
- `handle_property_push`
- `_apply_mapl`

The largest extraction by call-count — `_on_state_update` is ~200 lines and routes into rendering + session + lifecycle. Verify the diff carefully; this is the most likely to trip an MRO ordering bug.

**Acceptance:** pytest passes. Specifically run:

- `tests/integration/test_active_map_routing.py` (covers `_apply_mapl`)
- `tests/state_machine/*` (covers `_on_state_update` transitions)
- The fact that `hass.async_create_task(self._render_main_view())` from `_apply_mapl` still resolves — `_render_main_view` lives in `_RenderingMixin` now.

### Task 10 — Extract `_cloud_state` mixin (~400 LOC)

**Subject:** `refactor(coordinator): extract _cloud_state mixin`

Methods:

- `_refresh_cloud_state`
- `_render_maps_from_cloud_state`
- `_apply_cloud_state_to_mower_state`
- `_load_persisted_maps`
- `_save_persisted_maps`
- `_refresh_map`

**Acceptance:** pytest passes. `_apply_cloud_state_to_mower_state` is the big CFG decoder (~60 lines per surface); diff should be a clean move.

### Task 11 — Extract `_refreshers` mixin (~900 LOC)

**Subject:** `refactor(coordinator): extract _refreshers mixin`

Methods:

- `_refresh_mapl`
- `_refresh_cfg` (the giant ~365-line block)
- `_refresh_locn`
- `_refresh_mihis`
- `_refresh_dock`
- `_refresh_net`
- `_refresh_dev`
- `_poll_slow_properties`

**Acceptance:** pytest passes.

### Task 12 — Extract `_core` mixin + final cleanup

**Subject:** `refactor(coordinator): extract _core mixin, finalise package`

After task 11, `_coordinator_legacy.py` should contain only:

- The `DreameA2MowerCoordinator` class declaration with its inheritance list
- `__init__`
- `_async_update_data`
- `sn` property
- `station_bearing_deg` property
- `_init_cloud`
- `_init_mqtt`

Move these to `coordinator/_core.py` as `_CoreMixin`. Then `_coordinator_legacy.py` ONLY contains:

```python
class DreameA2MowerCoordinator(
    _CoreMixin,
    _RefreshersMixin,
    _CloudStateMixin,
    _MqttHandlersMixin,
    _WritesMixin,
    _SessionMixin,
    _RenderingMixin,
    _LidarOssMixin,
    _DeviceSyncMixin,
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    """Assembled mower coordinator — see individual mixins for per-concern docs."""
```

…with all the mixin imports at the top.

Move this final class declaration to `coordinator/__init__.py`. Delete `_coordinator_legacy.py` entirely.

`coordinator/__init__.py` final form:

```python
from __future__ import annotations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..mower.state import MowerState
from ._core import _CoreMixin
from ._refreshers import _RefreshersMixin
from ._cloud_state import _CloudStateMixin
from ._mqtt_handlers import _MqttHandlersMixin
from ._writes import _WritesMixin
from ._session import _SessionMixin
from ._rendering import _RenderingMixin
from ._lidar_oss import _LidarOssMixin
from ._device_sync import _DeviceSyncMixin
from ._wifi_archive import _WifiArchiveMixin
from ._property_apply import (
    apply_property_to_state,
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    _project_north_east,
)


class DreameA2MowerCoordinator(
    _CoreMixin,
    _RefreshersMixin,
    _CloudStateMixin,
    _MqttHandlersMixin,
    _WritesMixin,
    _SessionMixin,
    _RenderingMixin,
    _LidarOssMixin,
    _DeviceSyncMixin,
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    """Assembled mower coordinator — see individual mixins for per-concern docs."""


__all__ = [
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "_project_north_east",
]
```

**Acceptance:**

- `_coordinator_legacy.py` deleted.
- `coordinator/__init__.py` contains the final class assembly.
- `python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator"` returns without error.
- `pytest tests/` exits 0 (~596+ tests passing).
- HA test boot via `pytest tests/integration/test_init.py` (or equivalent integration smoke) succeeds.

### Task 13 — Line-number sweep (optional, post-refactor)

**Subject:** `docs(coordinator): update line-number references after decomposition`

Sweep `inventory.yaml`, `entity-inventory.yaml`, `docs/research/`, `docs/TODO.md`, `archive/session.py` comments, etc. for `coordinator\.py:[0-9]+` references and update to the new file/line:

- Most cited lines (`coordinator.py:80`) refer to general handling — replace with the symbol name (e.g., `coordinator._SUPPRESSED_SLOTS`) instead of a line number. Line numbers rot; symbol references don't.
- For specific method references (e.g., `coordinator.py:1228`), replace with `<new-file>:<symbol>` (e.g., `coordinator/_mqtt_handlers.py:_apply_mapl`).

**Acceptance:** `grep -rnE "coordinator\.py:[0-9]+" custom_components/ docs/` returns nothing or only fence-quoted historical references.

### Task 14 — CLAUDE.md update

**Subject:** `docs(claude): coordinator structure section`

Add a section to `CLAUDE.md`:

```
## Coordinator structure

The mower coordinator lives in `custom_components/dreame_a2_mower/coordinator/`
as a package, NOT a single file. Each submodule owns one concern:

- `_core.py`           — __init__, _async_update_data, properties
- `_property_apply.py` — module-level helpers + (siid, piid)-to-state
- `_refreshers.py`     — all cloud refresh cycles
- `_cloud_state.py`    — cloud_state apply + map fetch/persist
- `_mqtt_handlers.py`  — MQTT message routing + state transitions
- `_writes.py`         — settings + action writes
- `_session.py`        — finalize + persist + replay
- `_rendering.py`      — live-map render + obstacle overlay
- `_lidar_oss.py`      — LiDAR archive + OSS fetch
- `_device_sync.py`    — registry sync + lifecycle events
- `_wifi_archive.py`   — WiFi heatmap archive

When adding a new method, place it in the submodule whose concern
it matches. If a method mixes concerns, prefer the most natural
single owner and call into other mixins via self.

Mixin pattern: each submodule defines exactly one mixin class. The
class DreameA2MowerCoordinator (in __init__.py) inherits from all
mixins plus DataUpdateCoordinator. All self.foo references work via
Python's MRO. Only _CoreMixin owns __init__; other mixins are
method-only.

Imports keep working through `.coordinator` — re-exports in
__init__.py preserve apply_property_to_state, _BLOB_SLOTS,
_SUPPRESSED_SLOTS, _project_north_east for external callers.
```

**Acceptance:** section added; subsequent agent sessions reading `CLAUDE.md` get oriented immediately.

## Plan acceptance

- 12 commits landed (tasks 2–12 + sweep + claude doc).
- `coordinator.py` no longer exists; `coordinator/` package contains 11 submodules + `__init__.py`.
- `pytest tests/` exits 0 after every commit.
- All external imports (entity platforms, tests, services) keep working without modification.
- `inventory.yaml` / `entity-inventory.yaml` line-number references updated (task 13).
- `CLAUDE.md` § Coordinator structure section exists (task 14).

## Execution mode

Sequential, single-session. Each task ~5–20 minutes if no surprises. Total realistic time: 2–3 hours.

Subagent parallelism: tasks 2–11 *could* in principle parallelise (each cuts a disjoint set of methods from a shared file), but the file-level conflicts between branches would require a merge per task. Sequential is simpler and the speedup isn't worth the merge overhead at this scale.

## Verification across tasks

After each commit:

```bash
pytest tests/ -q
python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator; print(DreameA2MowerCoordinator.__mro__)"
grep -n "^class DreameA2MowerCoordinator" custom_components/dreame_a2_mower/_coordinator_legacy.py 2>/dev/null || echo "legacy file deleted"
```

The MRO check catches metaclass conflicts; the legacy-file check confirms progress.
