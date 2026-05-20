# Map-write Architecture Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `cloud_state.maps_by_id` the single source of truth for map data, deleting the `_cached_maps_by_id` shadow, the disk cache, and the redundant `_refresh_map` fetch, while fixing a device-pruning bug.

**Architecture:** `_refresh_cloud_state` (2-min timer, awaited at startup) becomes the sole owner of the map lifecycle: fetch → set `cloud_state` → render → sync sub-devices → notify. The `_session` work-log hydrate writes `cloud_state` via `dataclasses.replace`. `_sync_map_subdevices` no longer prunes devices on an empty batch.

**Tech Stack:** Python 3, Home Assistant custom integration, pytest (+ pytest-asyncio). Frozen dataclasses (`CloudState`) mutated via `dataclasses.replace`.

**Spec:** `docs/superpowers/specs/2026-05-20-map-write-redesign-design.md`

**Context:** This continues B1c. `origin/main` is at clean B1b (`3726b63`); local has the B1c reader-routing (`9c58ccb`, `52e409f`) + pause commit (`49d58f1`) + this spec (`6a95a19`), all unpushed. Do **not** push until Task 9 + the user's live smoke-check.

---

## File Structure

| File | Change |
|---|---|
| `custom_components/dreame_a2_mower/coordinator/_device_sync.py` | Harden `_sync_map_subdevices` prune (T1) |
| `custom_components/dreame_a2_mower/coordinator/_cloud_state.py` | Add `_sync_map_subdevices()` call to `_refresh_cloud_state` (T2); delete `_refresh_map` (T5), `_load_persisted_maps`/`_save_persisted_maps` (T6), shadow mirror line (T7) |
| `custom_components/dreame_a2_mower/coordinator/_session.py` | Convert hydrate write → `cloud_state` (T4) |
| `custom_components/dreame_a2_mower/coordinator/_core.py` | Delete MAP timer block + `_refresh_map` call (T5), Store + `_load_persisted_maps` call + `_maps_cache_store` init (T6), shadow init (T7); fix comments (T8) |
| `custom_components/dreame_a2_mower/services.yaml` | Update `replay_session` description (T8) |
| `tests/integration/test_subdevice_sync.py` | Prune-on-empty test (T1); shadow→cloud_state fixture cleanup (T7) |
| `tests/integration/test_coordinator.py` | `_refresh_cloud_state` sync test (T2); render characterization tests (T3); delete `_refresh_map` tests+stub (T5); shadow fixture cleanup (T7) |
| `tests/integration/conftest.py` | Add `make_empty_cloud_state` helper (T4); fixture cleanup (T7) |
| `tests/integration/test_picked_session.py` | Hydrate-branch test (T4); shadow cleanup (T7) |
| `tests/integration/test_work_log_isolation.py` | Shadow cleanup (T7) |
| `tests/integration/test_maps_cache_persist.py` | Delete (T6) |
| `tests/integration/test_no_map_shadow.py` | Create capstone guard (T8) |

---

### Task 1: Harden `_sync_map_subdevices` against pruning on an empty batch

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_device_sync.py:249-266`
- Test: `tests/integration/test_subdevice_sync.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_subdevice_sync.py`:

```python
def test_sync_does_not_prune_when_maps_empty(coordinator_with_two_maps):
    """An empty maps_by_id must NOT delete existing per-map devices.

    Empty means 'no authoritative map list right now' (e.g. a transient
    empty cloud batch), not 'remove every map'. Because per-map entities
    are static-at-setup, wiping the devices would require a reload to
    recover. Regression guard for the prune-on-empty bug.
    """
    coord = coordinator_with_two_maps
    coord.cloud_state.maps_by_id = {}  # empty batch, but cloud_state not None
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        existing = MagicMock()
        existing.identifiers = {(DOMAIN, "G2408053AEE0006232_map_0")}
        existing.id = "dev_map_0"
        registry.devices.values.return_value = [existing]
        mock_reg.return_value = registry
        coord._sync_map_subdevices()

    registry.async_remove_device.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_subdevice_sync.py::test_sync_does_not_prune_when_maps_empty -v`
Expected: FAIL — `async_remove_device` is called once (current code prunes map_0 because `wanted_ids` is empty).

- [ ] **Step 3: Add the guard**

In `_device_sync.py`, immediately before the `# Remove orphan map sub-devices` block (currently `prefix = f"{stable}_map_"` at L252), insert:

```python
        # An empty maps_by_id means "no authoritative map list right now"
        # (transient empty cloud batch), NOT "delete every map". Pruning on
        # empty would wipe all per-map sub-devices; skip it.
        if not wanted_ids:
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_subdevice_sync.py -v`
Expected: PASS — the new test passes and the existing add/remove/3-tuple tests still pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_device_sync.py tests/integration/test_subdevice_sync.py
git commit -m "audit-b1c: guard _sync_map_subdevices against pruning on empty maps_by_id"
```

---

### Task 2: `_refresh_cloud_state` syncs map sub-devices

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:114-116`
- Test: `tests/integration/test_coordinator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_coordinator.py`:

```python
def test_refresh_cloud_state_syncs_map_subdevices():
    """_refresh_cloud_state must call _sync_map_subdevices.

    After _refresh_map is deleted, _refresh_cloud_state is the only
    startup/periodic path that creates per-map devices (the MQTT MAPL
    path is push-only). Guard against silently dropping that sync.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cloud = MagicMock()
    coord.hass = MagicMock()

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass.async_add_executor_job.side_effect = _exec
    coord._cloud.fetch_full_cloud_state = MagicMock(return_value=MagicMock())
    coord.async_update_listeners = MagicMock()

    with patch.object(coord, "_render_maps_from_cloud_state", new=AsyncMock()), \
         patch.object(coord, "_apply_cloud_state_to_mower_state"), \
         patch.object(coord, "_sync_map_subdevices") as m_sync:
        asyncio.run(coord._refresh_cloud_state())

    m_sync.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_coordinator.py::test_refresh_cloud_state_syncs_map_subdevices -v`
Expected: FAIL — `_sync_map_subdevices` is never called (0 calls).

- [ ] **Step 3: Add the sync call**

In `_cloud_state.py`, inside `_refresh_cloud_state`, after `await self._render_maps_from_cloud_state()` (L114) and before `self._apply_cloud_state_to_mower_state()` (L116), insert:

```python
        # Sync HA per-map sub-devices to the freshly-set cloud_state. This
        # is the sole startup/periodic sync now that _refresh_map is gone
        # (the MQTT MAPL path is push-only).
        self._sync_map_subdevices()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_coordinator.py::test_refresh_cloud_state_syncs_map_subdevices -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_cloud_state.py tests/integration/test_coordinator.py
git commit -m "audit-b1c: _refresh_cloud_state syncs map sub-devices"
```

---

### Task 3: Characterize `_render_maps_from_cloud_state` (lock render coverage before deleting `_refresh_map`)

`_render_maps_from_cloud_state` owns base-PNG rendering + md5 dedup — the same logic the `_refresh_map` tests cover. It has zero tests today. Add characterization tests now so coverage survives `_refresh_map`'s deletion in Task 5.

**Files:**
- Test: `tests/integration/test_coordinator.py`

- [ ] **Step 1: Write the tests (they should pass against current code)**

Append to `tests/integration/test_coordinator.py`:

```python
def _make_coordinator_for_render_tests(last_map_md5: str | None = None):
    """Minimal coordinator stub exercising _render_maps_from_cloud_state."""
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.map_decoder import parse_cloud_map
    from tests.integration.test_map_decoder import _MINIMAL_MAP
    import copy

    coord = object.__new__(DreameA2MowerCoordinator)
    md = parse_cloud_map(copy.deepcopy(_MINIMAL_MAP))
    assert md is not None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {0: md}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    if last_map_md5 is not None:
        coord._last_map_md5_by_id[0] = last_map_md5

    hass = MagicMock()

    async def _exec(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _exec
    coord.hass = hass
    return coord, md


def test_render_maps_from_cloud_state_renders_base_png():
    """Each map with a changed md5 gets a base PNG rendered into the cache."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    coord, _md = _make_coordinator_for_render_tests()
    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base, \
         patch.object(coord, "_render_main_view", new=AsyncMock()), \
         patch.object(coord, "_render_active_map_base", new=AsyncMock()):
        asyncio.run(coord._render_maps_from_cloud_state())
        mock_base.assert_called_once()

    assert coord._static_map_pngs_by_id.get(0) is not None


def test_render_maps_from_cloud_state_skips_if_md5_unchanged():
    """A map whose md5 matches the last render is not re-rendered."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    coord, md = _make_coordinator_for_render_tests(last_map_md5=None)
    coord._last_map_md5_by_id[0] = md.md5
    coord._static_map_pngs_by_id[0] = b"already-rendered"
    with patch(
        "custom_components.dreame_a2_mower.map_render.render_base_map",
        return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
    ) as mock_base, \
         patch.object(coord, "_render_main_view", new=AsyncMock()), \
         patch.object(coord, "_render_active_map_base", new=AsyncMock()):
        asyncio.run(coord._render_maps_from_cloud_state())
        mock_base.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they pass against existing code**

Run: `python -m pytest tests/integration/test_coordinator.py::test_render_maps_from_cloud_state_renders_base_png tests/integration/test_coordinator.py::test_render_maps_from_cloud_state_skips_if_md5_unchanged -v`
Expected: PASS (characterization — the logic already exists). If either fails, STOP — the dedup behavior differs from the assumption; reconcile before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_coordinator.py
git commit -m "audit-b1c: characterization tests for _render_maps_from_cloud_state"
```

---

### Task 4: Convert the `_session` work-log hydrate to write `cloud_state`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py:323-326`
- Modify: `tests/integration/conftest.py` (add helper)
- Test: `tests/integration/test_picked_session.py`

- [ ] **Step 1: Add a CloudState test helper**

Append to `tests/integration/conftest.py` (module level, not inside a fixture):

```python
def make_empty_cloud_state(**overrides):
    """Build a minimal real CloudState for tests that need dataclasses.replace.

    All fields default to empty; pass overrides (e.g. maps_by_id=...) as needed.
    """
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState,
        ScheduleData,
        SettingsRoot,
    )

    base = dict(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        locn=None,
        dock={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    base.update(overrides)
    return CloudState(**base)
```

- [ ] **Step 2: Write the failing test**

Append to `tests/integration/test_picked_session.py`:

```python
@pytest.mark.asyncio
async def test_render_work_log_session_hydrate_writes_cloud_state():
    """When the map cache is empty, the last-resort live fetch must hydrate
    cloud_state.maps_by_id (not a private shadow) so later replays reuse it."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from tests.integration.conftest import make_empty_cloud_state
    import custom_components.dreame_a2_mower.map_render as map_render_mod
    import custom_components.dreame_a2_mower.map_decoder as map_decoder_mod

    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._picked_session_summary = None
    coord.cloud_state = make_empty_cloud_state()  # maps_by_id == {}
    coord._active_map_id = 0

    coord._cloud = MagicMock()
    coord._cloud.fetch_map.return_value = {0: {"mapIndex": 0}}  # non-None
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[entry])
    coord.session_archive.load = MagicMock(return_value=raw)

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = _exec

    fetched_map = SimpleNamespace()  # stand-in MapData; identity-checked below
    orig_render = map_render_mod.render_work_log
    orig_parse = map_decoder_mod.parse_cloud_map
    map_render_mod.render_work_log = lambda *a, **k: b"png"
    map_decoder_mod.parse_cloud_map = lambda *a, **k: fetched_map
    try:
        await coord.render_work_log_session("short.json")
    finally:
        map_render_mod.render_work_log = orig_render
        map_decoder_mod.parse_cloud_map = orig_parse

    assert coord.cloud_state.maps_by_id.get(0) is fetched_map
    assert not hasattr(coord, "_cached_maps_by_id")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_picked_session.py::test_render_work_log_session_hydrate_writes_cloud_state -v`
Expected: FAIL — current code does `self._cached_maps_by_id[active_id] = map_data`, so `cloud_state.maps_by_id` stays empty and `coord._cached_maps_by_id` exists.

- [ ] **Step 4: Convert the hydrate write**

In `_session.py`, replace the hydrate block (currently L323-326):

```python
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self._cached_maps_by_id[active_id] = map_data
            target_map_id = active_id
```

with:

```python
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            # cloud_state is the single map store; replace it immutably.
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self.cloud_state = dataclasses.replace(
                self.cloud_state,
                maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
            )
            target_map_id = active_id
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_picked_session.py -v`
Expected: PASS — the new hydrate test passes and `test_render_work_log_session_populates_picked_summary` still passes.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py tests/integration/conftest.py tests/integration/test_picked_session.py
git commit -m "audit-b1c: work-log hydrate writes cloud_state via dataclasses.replace"
```

---

### Task 5: Delete `_refresh_map`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:258-359` (delete method)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:474-483, 500` (delete timer + startup call)
- Modify: `tests/integration/test_coordinator.py` (delete `_refresh_map` tests + stub, L1767-1977)

- [ ] **Step 1: Delete the `_refresh_map`-specific tests and stub**

In `tests/integration/test_coordinator.py`, delete the entire section under the banner `# F5.8.1 — _refresh_map routes to render_with_trail / render_base_map` (the `_make_coordinator_for_refresh_map_tests` helper and every `test_refresh_map_*` function — currently L1767 through the end of `test_refresh_map_base_map_skips_if_md5_unchanged_even_when_live`, ~L1977). The render behavior they covered is now held by the Task 3 characterization tests.

- [ ] **Step 2: Delete the `_refresh_map` method**

In `_cloud_state.py`, delete the whole `async def _refresh_map(self) -> None:` method (currently L258-359, ends just before the file's final blank line).

- [ ] **Step 3: Delete the MAP timer + startup call in `_core.py`**

In `_core.py`, delete the `_periodic_map` definition + its `async_track_time_interval` registration (currently L474-483) and the standalone `await self._refresh_map()` at L500. **Leave** the Store construction and `_load_persisted_maps` call for Task 6. After this edit the region should read (the load block stays for now):

```python
            # Restore the parsed map cache from disk before the first cloud
            # fetch so map-metadata sensors populate immediately on reload.
            if self._maps_cache_store is None:
                self._maps_cache_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_maps_{self.entry.entry_id}",
                )
            try:
                await self._load_persisted_maps()
            except Exception:
                LOGGER.exception(
                    "_load_persisted_maps failed; continuing with empty cache"
                )
```

- [ ] **Step 4: Run the suite to verify green**

Run: `python -m pytest tests/integration/test_coordinator.py tests/integration/test_subdevice_sync.py -q`
Expected: PASS — no references to `_refresh_map` remain; the render characterization tests cover the rendering path. If a collection error mentions `_make_coordinator_for_refresh_map_tests`, a stray reference remains — remove it.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_cloud_state.py custom_components/dreame_a2_mower/coordinator/_core.py tests/integration/test_coordinator.py
git commit -m "audit-b1c: delete redundant _refresh_map (fetch subsumed by _refresh_cloud_state)"
```

---

### Task 6: Delete the disk-cache subsystem

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py` (delete `_load_persisted_maps`, `_save_persisted_maps`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:278, 488-499` (delete `_maps_cache_store` init + Store/load block)
- Delete: `tests/integration/test_maps_cache_persist.py`

- [ ] **Step 1: Delete the cache test file**

```bash
git rm tests/integration/test_maps_cache_persist.py
```

- [ ] **Step 2: Delete the persistence methods**

In `_cloud_state.py`, delete both `async def _load_persisted_maps(self) -> None:` (currently L213-249) and `async def _save_persisted_maps(self, cloud_response: dict[int, Any]) -> None:` (currently L251-256).

- [ ] **Step 3: Delete the Store init + load block in `_core.py`**

In `_core.py`, delete the `self._maps_cache_store: Store | None = None` init line (currently L278) and the entire Store-construction + `_load_persisted_maps` try/except block left after Task 5 (the comment + `if self._maps_cache_store is None:` Store construction + `try: await self._load_persisted_maps() ...`). If the `Store` import in `_cloud_state.py`/`_core.py` becomes unused, remove it (check with `grep -n "Store" <file>` first — `_core.py` also uses `Store` for `_state_store`, so keep it there).

- [ ] **Step 4: Run the suite to verify green**

Run: `python -m pytest tests/integration -q`
Expected: PASS. A failure naming `_load_persisted_maps`/`_save_persisted_maps`/`_maps_cache_store` means a missed reference — `grep -rn` for it and remove.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b1c: delete the map disk cache (_load/_save_persisted_maps + Store)"
```

---

### Task 7: Delete the `_cached_maps_by_id` shadow

All writers are now converted (Task 4) or deleted (Tasks 5-6). Remove the shadow init and mirror, plus the now-dead shadow assignments in test fixtures.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:112` (delete mirror)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:186` (delete init)
- Modify: `tests/integration/conftest.py:173-174`, `tests/integration/test_subdevice_sync.py:23-24`, `tests/integration/test_coordinator.py`, `tests/integration/test_picked_session.py:90-92`, `tests/integration/test_work_log_isolation.py:16`

- [ ] **Step 1: Delete the mirror and init lines in source**

In `_cloud_state.py`, delete the mirror line in `_refresh_cloud_state` (currently L109-112: the comment `# Mirror legacy attributes...` through `self._cached_maps_by_id = new_state.maps_by_id`).

In `_core.py`, delete the shadow init (currently L185-186: the comment `# Multi-map cache — populated by _refresh_map.` and `self._cached_maps_by_id: dict[int, Any] = {}`).

- [ ] **Step 2: Clean shadow assignments in test fixtures**

Replace every two-line shadow+alias pair of the form
```python
coord._cached_maps_by_id = <X>
coord.cloud_state.maps_by_id = coord._cached_maps_by_id
```
with the single line `coord.cloud_state.maps_by_id = <X>`. Find all sites:

Run: `grep -rn "_cached_maps_by_id" tests/`

Known sites: `conftest.py:173-174`, `test_subdevice_sync.py:23-24`, `test_coordinator.py` (multiple fixtures), `test_picked_session.py:90-92`. For standalone shadow-only lines (e.g. `test_work_log_isolation.py:16` `coord._cached_maps_by_id = {}`), replace with `coord.cloud_state.maps_by_id = {}` and ensure `coord.cloud_state` is set (if it's a bare attr, set `coord.cloud_state = MagicMock()` first or use `make_empty_cloud_state()`). Update any docstring/comment mentioning `_cached_maps_by_id` (e.g. `test_coordinator.py:3090`) to say `cloud_state.maps_by_id`.

- [ ] **Step 3: Run the full suite to verify green**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1c: delete the _cached_maps_by_id shadow (cloud_state.maps_by_id is sole store)"
```

---

### Task 8: Cleanup comments/docs + capstone guard

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py`, `_cloud_state.py`, `_device_sync.py`, `cloud_state.py`, `services.yaml`
- Create: `tests/integration/test_no_map_shadow.py`

- [ ] **Step 1: Fix stale comments/docstrings**

- `_core.py`: the comment `# Unified cloud state — populated by _refresh_cloud_state every 10 min.` → change "10 min" to "2 min". Remove any remaining `_refresh_map` mention.
- `_cloud_state.py`: in `_refresh_cloud_state`'s docstring, the line listing `_refresh_cfg + _refresh_map + _refresh_mihis + ...` — note that `_refresh_map` is now removed (the others remain pending a future refresher-consolidation cycle).
- `_device_sync.py`: the `_sync_map_subdevices` docstring referencing `_cached_maps_by_id` / `_refresh_map` → "Called whenever `cloud_state.maps_by_id` may have changed (after `_apply_mapl` and after `_refresh_cloud_state`)."
- `cloud_state.py` module docstring: "(every 10 min)" → "(every 2 min)".
- `services.yaml`: in `replay_session` description, replace "the next `_refresh_map` tick (every 6 hours or on map data change)" / "trigger any other action that calls `_refresh_map`" with the 2-min `_refresh_cloud_state` render (e.g. "the next `_refresh_cloud_state` tick (every 2 minutes) re-renders the live map and clears replay").

- [ ] **Step 2: Create the capstone guard test**

Create `tests/integration/test_no_map_shadow.py`:

```python
"""Guard: the _cached_maps_by_id shadow stays removed.

cloud_state.maps_by_id is the single source of truth for map data. If this
test fails, the shadow was reintroduced — route the reader/writer to
cloud_state.maps_by_id instead.
"""
import pathlib


def test_no_cached_maps_shadow_in_source():
    src = pathlib.Path("custom_components/dreame_a2_mower")
    hits = []
    for path in src.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if "_cached_maps_by_id" in line:
                hits.append(f"{path}:{lineno}: {line.strip()}")
    assert not hits, "shadow reintroduced:\n" + "\n".join(hits)
```

- [ ] **Step 3: Run the guard + a doc-touch sanity check**

Run: `python -m pytest tests/integration/test_no_map_shadow.py -v`
Expected: PASS (no `_cached_maps_by_id` remains in source).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1c: refresh stale map comments/docs + add no-shadow guard test"
```

---

### Task 9: Full verification + handoff

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest tests -q`
Expected: PASS, no errors, no skips beyond the suite's pre-existing ones.

- [ ] **Step 2: Lint/syntax check the touched modules**

Run: `python -m pyflakes custom_components/dreame_a2_mower/coordinator/_cloud_state.py custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_device_sync.py custom_components/dreame_a2_mower/coordinator/_session.py`
Expected: no output (no unused imports/undefined names). If `pyflakes` isn't installed, use `python -c "import ast,sys;[ast.parse(open(f).read()) for f in sys.argv[1:]]" <files>` for a syntax check.

- [ ] **Step 3: Confirm the deletions landed**

Run:
```bash
grep -rn "_cached_maps_by_id\|_load_persisted_maps\|_save_persisted_maps\|_maps_cache_store\|def _refresh_map\b" custom_components/dreame_a2_mower/
```
Expected: no output.

- [ ] **Step 4: Hand off to the user for the live smoke-check**

Do NOT push. Report to the user: reload the config entry on the HA box and confirm (a) maps + per-map devices present and populated; (b) the `_refresh_cloud_state` service triggers a clean re-render; (c) no per-map device flapping. Only after the user confirms, push the full B1c sequence to `origin/main` (per the spec's "Push discipline").

---

## Self-Review

**Spec coverage:**
- Delete shadow → T7 + guard T8. ✓
- Delete `_load_persisted_maps`/`_save_persisted_maps`/`_refresh_map`/Store → T5, T6. ✓
- Convert `_session` hydrate → T4. ✓
- `_refresh_cloud_state` adds `_sync_map_subdevices` → T2. ✓
- Harden prune-on-empty → T1. ✓
- Render coverage preserved → T3. ✓
- Delete `test_maps_cache_persist.py`, update `test_coordinator.py` → T6, T5/T7. ✓
- Comment/doc/services.yaml cleanup → T8. ✓
- `fetch_map` (cloud client) kept → not deleted in any task. ✓
- Out-of-scope (refresher consolidation, static-at-setup) → untouched. ✓

**Placeholder scan:** No TBD/TODO; every code step shows real code; every run step shows the command + expected result.

**Type consistency:** `make_empty_cloud_state` matches the 19 `CloudState` fields from `cloud_state.py`. `dataclasses.replace` is valid (already imported in `_session.py:9`). `_sync_map_subdevices`, `_render_maps_from_cloud_state`, `_apply_cloud_state_to_mower_state`, `fetch_full_cloud_state` names match source. Prune guard uses `wanted_ids` (defined at the method's L240).
