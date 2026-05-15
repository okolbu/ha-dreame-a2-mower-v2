# Coordinator Decomposition — Design

**Status:** Spec
**Date:** 2026-05-15
**Scope:** File-level refactor of `custom_components/dreame_a2_mower/coordinator.py` (4997 LOC). No behaviour change, no API change, no entity_id / unique_id change. Mechanical split into a `coordinator/` package of mixin classes.

## Problem

`coordinator.py` has grown to **4997 LOC** across ~60 methods spanning roughly 13 unrelated concerns: cloud refresh cycles, MQTT handlers, map rendering, settings writes, session finalize/restore, LiDAR + OSS fetch, WiFi archive, lifecycle events, device-registry sync, action dispatch, etc.

Concrete symptoms:

- **Any feature touch reads too much.** A 4997-line file blows past any reasonable context budget for an LLM agent and forces a human reviewer to page through unrelated code to find the change.
- **Bug fixes accumulate near unrelated code.** Today's `_render_main_view` race fix (v1.0.11a3) lives next to s2p51 decoding, which lives next to anti-theft, which lives next to LiDAR OSS fetches. The lexical proximity has nothing to do with what calls what.
- **No natural place to add a related new method.** Should the new method go next to the most similar existing method (clustering by domain) or at the bottom (clustering by timeline)? Both happen, and the file grows in both directions.
- **CI gate noise.** Any `coordinator.py` touch could plausibly require a `wire_inventory.yaml` or `entity_inventory.yaml` touch under the fact-discipline rules — gating it would mean every refactor PR has to declare an opt-out. The gate currently excludes `coordinator.py` for exactly this reason, but the exclusion is a workaround for the file being too big to gate sensibly.

The single coordinator class is the right *runtime abstraction* — `DreameA2MowerCoordinator` is what `__init__.py` constructs, what every entity platform consumes, and what `tests/` interacts with. The problem isn't the class; it's that the class definition is one giant file.

## Goals

- Split `coordinator.py` into ~10 focused submodules under a `coordinator/` package, each ~300–700 LOC, organised by concern. The largest expected file (`refreshers.py`) is ~900 LOC; the smallest (`wifi_archive.py`) is ~170.
- `DreameA2MowerCoordinator` remains a single class — assembled via mixin inheritance, so all `self.foo` references work unchanged via Python's MRO.
- All existing imports continue to work: `from .coordinator import DreameA2MowerCoordinator` resolves identically. Other modules and tests need no changes.
- Each extraction is a focused diff (move ~10–50 method definitions from `coordinator.py` to a new mixin file). Each commit passes the full test suite before merging. Reviewer / git-blame can trace which mixin a method moved to.
- Zero behavioural change. Method bodies are not modified, only their containing file. No method signatures, no decorators, no docstrings reordered.

## Non-goals

- **Splitting other large files.** `cloud_client.py` (2197 LOC), `select.py` (1970), `sensor.py` (1456), `switch.py` (1308) are not in scope. They have clearer entity-class boundaries and can be decomposed in separate spec passes if/when they start to hurt.
- **Renaming methods.** The pattern `_refresh_cfg` etc. stays as-is. Public method names — `write_setting`, `dispatch_action`, `replay_session` — also stay.
- **Adding type hints / strictening.** Preserve every annotation as-is. Adding hints invites scope creep and adds review friction.
- **Touching test files (other than possibly fixing imports if any test reaches into a private module). Test imports go through `from .coordinator import DreameA2MowerCoordinator`, which keeps working.
- **Adding behaviour.** No new methods, no new fields. Every method moved is moved verbatim.
- **Removing methods.** Anything that looks dead — leave it. Removal is a separate concern with its own audit trail.

## Deliverables

A new package `custom_components/dreame_a2_mower/coordinator/` containing:

```
coordinator/
  __init__.py               # re-exports DreameA2MowerCoordinator (~50 LOC)
  _core.py                  # __init__, _async_update_data, sn property, station_bearing_deg, _init_cloud, _init_mqtt
  _refreshers.py            # _refresh_{mapl,cfg,locn,mihis,dock,net,dev,cloud_state}, _poll_slow_properties
  _cloud_state.py           # _refresh_cloud_state, _render_maps_from_cloud_state, _apply_cloud_state_to_mower_state, _load_persisted_maps, _save_persisted_maps, _refresh_map
  _rendering.py             # _render_main_view, _rerender_live_trail, _load_last_session_obstacles, _render_active_map_base, _current_mower_position, _current_mower_heading
  _mqtt_handlers.py         # _on_mqtt_message, _on_state_update, _handle_event_occured, handle_property_push, _apply_mapl
  _writes.py                # write_settings, write_schedule, write_ai_human_enabled, write_setting, _dispatch_cfg_write, dispatch_action, start_mowing_*, _ensure_active_map, _fetch_fresh_settings_blob
  _session.py               # _restore_in_progress, _persist_in_progress, _run_finalize_incomplete, _dispatch_finalize_action, replay_session, render_work_log_session, _periodic_session_retry, _resolve_finalize_map_id
  _lidar_oss.py             # _handle_lidar_object_name, _do_oss_fetch, lidar_archive_for, list_lidar_archive_entries, set_lidar_render_entry, _build_map_extents, set_wifi_render_entry
  _wifi_archive.py          # refresh_wifi_archive, _download_and_archive_wifi, _read_session_wifi_samples, _tag_wifi_archive_map_ids
  _device_sync.py           # _sync_map_subdevices, _update_device_registry_serial, _get_device_registry, _handle_emergency_stop_transition, _schedule_cloud_refresh, _compute_target_area_m2, register_event_entities, _fire_lifecycle, _fire_mowing_ended, _fire_alert
```

Plus the existing `coordinator.py` either replaced with a one-line re-export OR deleted (package `coordinator/` is enough — depending on whether anything outside the integration `import`s from the file by path vs by symbol; project audit suggests symbol-only).

### Mixin assembly

Each submodule defines exactly one mixin class with a leading underscore in the filename and a leading underscore in the class name to mark them as package-private:

```python
# coordinator/_refreshers.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._core import _CoreMixin   # for typing self.<core_attr>

class _RefreshersMixin:
    async def _refresh_mapl(self) -> None:
        ...
    async def _refresh_cfg(self) -> None:
        ...
    # ... etc
```

`coordinator/__init__.py` assembles them:

```python
from __future__ import annotations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from ..mower.state import MowerState
from ._core import _CoreMixin
from ._refreshers import _RefreshersMixin
from ._cloud_state import _CloudStateMixin
from ._rendering import _RenderingMixin
from ._mqtt_handlers import _MqttHandlersMixin
from ._writes import _WritesMixin
from ._session import _SessionMixin
from ._lidar_oss import _LidarOssMixin
from ._wifi_archive import _WifiArchiveMixin
from ._device_sync import _DeviceSyncMixin


class DreameA2MowerCoordinator(
    _CoreMixin,
    _RefreshersMixin,
    _CloudStateMixin,
    _RenderingMixin,
    _MqttHandlersMixin,
    _WritesMixin,
    _SessionMixin,
    _LidarOssMixin,
    _WifiArchiveMixin,
    _DeviceSyncMixin,
    DataUpdateCoordinator[MowerState],
):
    """Assembled mower coordinator — see individual mixins for per-concern docs."""


__all__ = ["DreameA2MowerCoordinator"]
```

`_CoreMixin.__init__` retains the **only** `__init__` — all other mixins are pure method containers, no `__init__` overrides, no class-level `_attr_*` (they're not entities), no `__init_subclass__`. This keeps MRO trivial: `__init__` resolves to `_CoreMixin.__init__` → `super().__init__()` reaches `DataUpdateCoordinator.__init__`.

### Shared private state

`_CoreMixin.__init__` is the sole site that assigns `self._foo = ...`. Every other mixin only *reads* those attributes (or calls back into a `_CoreMixin` method that writes them). This invariant is checkable via a grep:

```bash
grep -nE "self\._[a-z_]+\s*=" coordinator/_refreshers.py coordinator/_writes.py ...
```

…should return nothing except writes to attributes already initialized in `_CoreMixin`. Adding a new shared field requires editing `_CoreMixin` first.

### Cross-mixin type hints

Mixins call methods on `self` that belong to other mixins (e.g., `_async_update_data` in `_CoreMixin` awaits `self._refresh_cfg()` from `_RefreshersMixin`). At runtime this works via MRO. For static analysis (Pylance / mypy), use `TYPE_CHECKING` blocks:

```python
# coordinator/_core.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Imports here cost nothing at runtime; satisfy mypy when _CoreMixin
    # method bodies call self._refresh_cfg(), self.write_setting(), etc.
    from ._refreshers import _RefreshersMixin
    from ._writes import _WritesMixin
```

This is a known cost of the mixin pattern. Acceptable here because the integration is single-app and cross-references are explicit at the spec level.

## Method

Incremental extraction, one mixin per commit. Order chosen to minimize cross-mixin reference churn — extract leaves first, save the most-cross-referenced (`_core.py`, `_refreshers.py`) for last.

### Step 0 — setup

Create the `coordinator/` directory, add a stub `__init__.py` that re-exports the existing `DreameA2MowerCoordinator` from `coordinator.py`:

```python
from ..coordinator import DreameA2MowerCoordinator  # type: ignore
__all__ = ["DreameA2MowerCoordinator"]
```

(Avoids breaking anything that already imports from `coordinator.coordinator` if such an import exists. Probably nothing does.)

Run `pytest`. CI green. Commit: `chore(coordinator): create coordinator/ package shell`.

### Steps 1–10 — extract mixins, leaf-first

Order chosen by "few inbound dependencies, simple to lift":

1. `_wifi_archive.py` (~170 LOC, leaf) — `refresh_wifi_archive` and helpers. Called from a service handler and from `_dispatch_action`; not called by other refreshers.
2. `_device_sync.py` (~250 LOC) — `_sync_map_subdevices`, `_update_device_registry_serial`, `_handle_emergency_stop_transition`, `_fire_*` lifecycle helpers, `_schedule_cloud_refresh`. Pure helpers.
3. `_lidar_oss.py` (~430 LOC) — LiDAR archive query + OSS fetch. Self-contained.
4. `_rendering.py` (~250 LOC) — `_render_main_view`, `_rerender_live_trail`, `_load_last_session_obstacles`, `_render_active_map_base`. Called by `_cloud_state` and `_mqtt_handlers`; doesn't call them.
5. `_session.py` (~700 LOC) — restore, persist, finalize, replay. Called by `_core`, `_mqtt_handlers`, services; calls into `_rendering` and `_session_archive`.
6. `_writes.py` (~500 LOC) — settings + action writes. Called by services and entities; calls into `_cloud` client.
7. `_mqtt_handlers.py` (~700 LOC) — MQTT routing + state-update glue. Calls into many other mixins; the most cross-referenced.
8. `_cloud_state.py` (~400 LOC) — cloud_state apply + map fetch/persist. Called from `_refreshers`; calls into `_rendering`.
9. `_refreshers.py` (~900 LOC) — all `_refresh_*`. Called from `_core._async_update_data`; calls into `_cloud_state`, `_writes`, etc.
10. `_core.py` (~500 LOC) — what's left: `__init__`, `_async_update_data`, properties, `_init_cloud`, `_init_mqtt`. By construction this is the only mixin that owns `__init__` and writes to private state.

After step 10, `coordinator.py` is empty except for the original module docstring. Final commit either: (a) replace `coordinator.py` with a one-line re-export `from .coordinator import DreameA2MowerCoordinator`, or (b) delete `coordinator.py` (the package supersedes it).

### Per-step procedure

Each of steps 1–10 has the same shape:

1. Identify the methods in scope by grepping `coordinator.py` for their `async def` / `def` signatures.
2. Create the new `coordinator/_<name>.py` with a single `_<Name>Mixin` class and `if TYPE_CHECKING:` imports for any cross-mixin references in the method bodies.
3. Cut the method definitions from `coordinator.py` and paste into the new mixin. Preserve every comment, docstring, and decorator verbatim.
4. Append the new mixin to the inheritance list in `coordinator/__init__.py`.
5. Run `pytest tests/`. Must pass before committing.
6. Run `python -m custom_components.dreame_a2_mower` (or whatever smoke-imports work) to verify there's no top-level import error.
7. Commit: `refactor(coordinator): extract <name> mixin`.

If a step's test pass fails, do **not** commit. The bisect is between mixin commits, so a clean per-mixin checkpoint matters.

## Acceptance

- `coordinator/` package exists with 10 mixin files plus `__init__.py`.
- `coordinator.py` is reduced to either a 1-line re-export or deleted entirely.
- Every method that was in the original `coordinator.py` lives in exactly one mixin. No duplication.
- `_CoreMixin.__init__` is the only `__init__` across all mixins.
- `pytest tests/` exits 0.
- `python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator"` returns without error.
- `inventory-touch-gate` CI job is **not** triggered by any extraction commit (the only files touched are `coordinator.py` + `coordinator/*.py`, which are not in either glob).
- The cumulative diff is move-only: every line removed from `coordinator.py` appears identically (modulo class indentation) in some `coordinator/*.py`.

## Risks & open questions

### `__init_subclass__` or metaclass conflicts

`DataUpdateCoordinator` may have a metaclass or `__init_subclass__` hook. Mixin chains with multiple parents can hit MRO conflicts if any non-mixin has its own metaclass. **Verification step**: before step 1, write a small test that constructs the assembled class against the current `DataUpdateCoordinator` from HA's current pinned version. If the metaclass resolution fails, switch strategy from "mixins" to "thin coordinator + helper module functions taking `coordinator` as the first arg" (cost: slightly more boilerplate per method, no MRO).

### Test imports reaching private internals

`grep -rnE "from custom_components\.dreame_a2_mower\.coordinator import [_A-Z]" tests/` should be near-empty. If any test imports a private helper (`_apply_mapl`, `_render_main_view`), that test's import path needs updating — but only the import line, not the test body. Survey before step 1.

### Line-number drift in docs / comments

Other files contain `coordinator.py:1228`-style references. Grep first:

```bash
grep -rnE "coordinator\.py:[0-9]+" custom_components/ docs/ tools/
```

For each hit: either delete the line number (most cited methods are uniquely-named, so the symbol is enough) or update it post-refactor. The CLAUDE.md / entity-inventory.yaml entries written during 2026-05-14 are the main offenders.

### Backwards-compat for HACS-installed users

Existing installs have `coordinator.py` on disk. HACS overwrites the integration directory wholesale, so:

- Old `coordinator.py` is deleted by HACS update.
- New `coordinator/` directory is created.
- Python imports `from .coordinator import DreameA2MowerCoordinator` resolve to the new package.

Verified-by-design (HACS install model). No migration needed.

### Subagent-driven execution

Steps 1–10 are largely independent — each cuts a disjoint set of methods from the same file and writes a new file. A subagent-driven plan could run several extractions in parallel against branches and merge. The cross-mixin import lines (`TYPE_CHECKING` blocks) are the only true serialisation point.

Decision deferred to the implementation plan: single-session sequential extraction is simpler and the whole refactor fits in ~2 hours that way. Parallel subagents are an option if review bandwidth is the constraint.

### Style — `Mixin` suffix vs no suffix

Convention in this project for entity classes is no suffix (`DreameA2EdgeMowingAutoSwitch`, not `DreameA2EdgeMowingAutoSwitchEntity`). For mixin classes inside the coordinator package, the `Mixin` suffix is a strong signal that the class is **not** intended to be instantiated directly. Worth the explicit naming.

## Out-of-scope clarifications

- **Documentation files (e.g. `g2408-protocol.md`) referring to coordinator methods** — these stay. Method names don't change.
- **`docs/research/state-machines/*` mentions of coordinator line numbers** — fixed post-refactor in a single follow-up commit, not per-step.
- **Other large source files** — `cloud_client.py` (2197), `select.py` (1970), `sensor.py` (1456), `switch.py` (1308). All candidates for their own decomposition spec, but each has a different shape (entity classes vs orchestration), so the playbook here doesn't transfer one-to-one. Defer until painful.
- **Test reorganisation** — `tests/integration/test_*.py` files can also be split for clarity, but that's a separate refactor with its own value calculation.

## Follow-up plan

A separate implementation plan, executed via `superpowers:executing-plans`, follows this spec. The plan's tasks are:

1. **Setup** — create `coordinator/` directory + `__init__.py` shim. Tests green.
2. **Survey** — produce the actual method-to-mixin mapping table (this spec's groupings are a starting point but may need adjustment after grepping cross-references).
3. **Extract `_wifi_archive`** through **Extract `_core`** — 10 commits.
4. **Cleanup** — delete `coordinator.py` or replace with a re-export.
5. **Sweep line-number references** in docs / inventory yaml / comments.
6. **Update `CLAUDE.md` § coordinator structure** — one paragraph naming the mixin layout, so future agents know where to add new methods.

Plan acceptance: same as spec acceptance, plus the line-number sweep + CLAUDE.md update.
