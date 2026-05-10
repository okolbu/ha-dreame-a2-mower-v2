# Multi-Map Phase 2 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the SN-keyed sub-device foundation and migrate every *existing* per-map entity onto its corresponding map sub-device, with one-time `async_migrate_entry` rewriting unique_ids.

**Architecture:** New helper module `_devices.py` centralises identifier construction (mower SN + map sub-device). New `_migration.py` runs on integration setup, rewrites entity registry from `{entry_id}_*` to `{sn}_*` (or `{sn}_map_{N}_*` for per-map entities), bumps entry version 1→2, and fires a `persistent_notification` listing any unmapped orphans for manual cleanup. The coordinator gains a `_sync_map_subdevices()` hook that adds/removes HA devices when `_cached_maps_by_id` changes. Existing per-map entity classes (zone/spot/edge selects, schedule, settings switches, per-map snapshot camera, WiFi heatmap camera, LiDAR camera) are reshaped to register one instance per `map_id` against the right sub-device.

**Tech Stack:** Python 3.13, Home Assistant ConfigEntry/DeviceRegistry/EntityRegistry APIs, pytest (asyncio_mode=auto), ruff, mypy strict. No new third-party deps.

**Spec:** [`docs/superpowers/specs/2026-05-10-multi-map-phase-2-design.md`](../specs/2026-05-10-multi-map-phase-2-design.md)

**Scope boundary:** This plan does NOT add net-new entities. New entities (mowing-type select, live video, map metadata sensors, maintenance points, pathway/ignore zones, Custom Mode services, all mower-level second-settings-page items) ship in Plans 2 and 3.

---

## File Structure

**Files to create:**

- `custom_components/dreame_a2_mower/_devices.py` — identifier + DeviceInfo factories
- `custom_components/dreame_a2_mower/_migration.py` — `async_migrate_entry` and unique_id rewrite engine
- `tests/integration/test_sn_capture.py`
- `tests/integration/test_devices_helpers.py`
- `tests/integration/test_migration_v1_v2.py`
- `tests/integration/test_subdevice_sync.py`
- `tests/integration/test_per_map_zone_select.py`
- `tests/integration/test_per_map_schedule.py`
- `tests/integration/test_per_map_setting_switches.py`
- `tests/integration/test_per_map_cameras.py`
- `tests/integration/test_lidar_per_map.py`

**Files to modify:**

- `custom_components/dreame_a2_mower/cloud_client.py:355-376` — capture `info["sn"]`
- `custom_components/dreame_a2_mower/coordinator.py` — expose `sn` accessor; add `_sync_map_subdevices` hook
- `custom_components/dreame_a2_mower/__init__.py:33` — wire `async_migrate_entry`
- `custom_components/dreame_a2_mower/config_flow.py:39` — bump `VERSION = 2`
- `custom_components/dreame_a2_mower/select.py` — zone/spot/edge become per-map; active_map re-keyed; schedule per-map
- `custom_components/dreame_a2_mower/switch.py` — settings switches per-map
- `custom_components/dreame_a2_mower/camera.py` — per-map snapshot/WiFi/LiDAR cameras on sub-devices
- `custom_components/dreame_a2_mower/binary_sensor.py` — same DeviceInfo refactor
- `custom_components/dreame_a2_mower/sensor.py` — same DeviceInfo refactor
- `custom_components/dreame_a2_mower/archive/lidar.py` — accept `map_id` param, per-map subdir
- `custom_components/dreame_a2_mower/manifest.json` — version bump

---

## Conventions

- **Per-task workflow**: write failing test, run to confirm fail, implement, run to confirm pass, commit. Each task's commit message follows `<type>(<scope>): <summary>` format used in this repo (see `git log --oneline`).
- **Migration rewrite map**: each task that changes an entity's unique_id ALSO appends to the rewrite mapping in `_migration.py`. The migration ships atomically with the entity changes.
- **Run after every commit:** `python -m pytest tests/ -x` to catch regressions immediately.
- **Run before final commit of each task:** `ruff check .` and `mypy custom_components/dreame_a2_mower/`.
- **No version bump until plan complete.** The release.sh + GitHub-release happens in Task 15.

---

## Task 1: Capture SN in cloud_client

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py:357-376`
- Test: `tests/integration/test_sn_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_sn_capture.py
"""SN capture in DreameMowerDreameHomeCloudProtocol._handle_device_info."""
from custom_components.dreame_a2_mower.cloud_client import (
    DreameMowerDreameHomeCloudProtocol,
)


def test_sn_captured_from_device_info():
    proto = DreameMowerDreameHomeCloudProtocol.__new__(
        DreameMowerDreameHomeCloudProtocol
    )
    proto._strings = None
    info = {
        "did": "BM169439",
        "model": "dreame.mower.g2408",
        "uid": "-112293549",
        "host": "10000.mt.eu.iot.dreame.tech",
        "mac": "EF:CE:CC:AA:FE:FD",
        "sn": "G2408053AEE0006232",
        "property": "",
    }
    # Patch _ensure_strings so the index lookups resolve.
    proto._ensure_strings = lambda: {
        8: "uid", 9: "host", 10: "property", 11: "stream_key", 35: "model",
    }
    proto._handle_device_info(info)
    assert proto._sn == "G2408053AEE0006232"


def test_sn_missing_logs_warning_and_sets_none(caplog):
    proto = DreameMowerDreameHomeCloudProtocol.__new__(
        DreameMowerDreameHomeCloudProtocol
    )
    info = {
        "did": "BM169439", "model": "dreame.mower.g2408",
        "uid": "u", "host": "h", "mac": None, "property": "",
    }
    proto._ensure_strings = lambda: {
        8: "uid", 9: "host", 10: "property", 11: "stream_key", 35: "model",
    }
    proto._handle_device_info(info)
    assert proto._sn is None
    assert "sn missing" in caplog.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_sn_capture.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_sn'`.

- [ ] **Step 3: Implement SN capture**

In `cloud_client.py:_handle_device_info`, after the existing `self._mac = ...` line, add:

```python
self._sn = info.get("sn")
if not self._sn:
    _LOGGER.warning("cloud _handle_device_info: sn missing from device info; falling back to mac/entry_id for identifiers")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_sn_capture.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py tests/integration/test_sn_capture.py
git commit -m "feat(cloud): capture device SN for stable HA identifiers"
```

---

## Task 2: `_devices.py` helper module

**Files:**
- Create: `custom_components/dreame_a2_mower/_devices.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (add `sn` property)
- Test: `tests/integration/test_devices_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_devices_helpers.py
"""Helpers in _devices.py for SN-keyed identifiers and DeviceInfo."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower._devices import (
    map_device_info,
    map_identifiers,
    map_unique_id,
    mower_device_info,
    mower_identifiers,
    mower_unique_id,
)
from custom_components.dreame_a2_mower.const import DOMAIN


def _coord(sn="G2408053AEE0006232", mac="ef:ce:cc:aa:fe:fd",
           model="dreame.mower.g2408", entry_id="abc123"):
    coord = MagicMock()
    coord.sn = sn
    coord.entry.entry_id = entry_id
    client = MagicMock()
    client.sn = sn
    client.mac = mac
    client.model = model
    coord._cloud = client
    return coord


def test_mower_identifiers_uses_sn():
    assert mower_identifiers(_coord()) == {(DOMAIN, "G2408053AEE0006232")}


def test_mower_identifiers_falls_back_to_mac_when_sn_missing():
    c = _coord(sn=None)
    assert mower_identifiers(c) == {(DOMAIN, "mac:ef:ce:cc:aa:fe:fd")}


def test_mower_identifiers_falls_back_to_entry_id_when_both_missing():
    c = _coord(sn=None, mac=None)
    assert mower_identifiers(c) == {(DOMAIN, "entry:abc123")}


def test_map_identifiers():
    assert map_identifiers(_coord(), 0) == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_mower_unique_id():
    assert mower_unique_id(_coord(), "battery") == "G2408053AEE0006232_battery"


def test_map_unique_id():
    assert (
        map_unique_id(_coord(), 1, "lidar_top_down")
        == "G2408053AEE0006232_map_1_lidar_top_down"
    )


def test_mower_device_info_shape():
    info = mower_device_info(_coord())
    assert info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}
    assert info["manufacturer"] == "Dreame"
    assert info["model"] == "dreame.mower.g2408"
    assert info["serial_number"] == "G2408053AEE0006232"


def test_map_device_info_shape():
    info = map_device_info(_coord(), 0, name="Front Lawn")
    assert info["identifiers"] == {(DOMAIN, "G2408053AEE0006232_map_0")}
    assert info["via_device"] == (DOMAIN, "G2408053AEE0006232")
    assert info["name"] == "Front Lawn"


def test_map_device_info_default_name_when_none():
    info = map_device_info(_coord(), 1, name=None)
    assert info["name"] == "Map 2"  # 1-indexed display
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_devices_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.dreame_a2_mower._devices'`.

- [ ] **Step 3: Implement `_devices.py`**

```python
# custom_components/dreame_a2_mower/_devices.py
"""Identifier and DeviceInfo factories for the mower + map sub-devices.

Centralises the SN-based keying introduced in Phase 2. All entities
should construct their unique_id and device_info via these helpers so
the migration in `_migration.py` has a single source of truth.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import DreameA2MowerCoordinator


def _stable_id(coord: "DreameA2MowerCoordinator") -> str:
    """Return the most stable identifier available for this mower.

    Prefers the hardware SN. Falls back to mac (prefixed `mac:`) and
    finally to the config entry id (`entry:`). The fallback prefixes
    keep the namespace explicit so the migration can detect them.
    """
    sn = getattr(coord, "sn", None)
    if sn:
        return sn
    client = getattr(coord, "_cloud", None)
    mac = getattr(client, "mac", None) if client is not None else None
    if mac:
        return f"mac:{mac}"
    return f"entry:{coord.entry.entry_id}"


def mower_identifiers(coord: "DreameA2MowerCoordinator") -> set[tuple[str, str]]:
    return {(DOMAIN, _stable_id(coord))}


def map_identifiers(
    coord: "DreameA2MowerCoordinator", map_id: int
) -> set[tuple[str, str]]:
    return {(DOMAIN, f"{_stable_id(coord)}_map_{map_id}")}


def mower_unique_id(coord: "DreameA2MowerCoordinator", key: str) -> str:
    return f"{_stable_id(coord)}_{key}"


def map_unique_id(
    coord: "DreameA2MowerCoordinator", map_id: int, key: str
) -> str:
    return f"{_stable_id(coord)}_map_{map_id}_{key}"


def mower_device_info(coord: "DreameA2MowerCoordinator") -> DeviceInfo:
    client = getattr(coord, "_cloud", None)
    model = getattr(client, "model", None) if client is not None else None
    mac = getattr(client, "mac", None) if client is not None else None
    sn = getattr(coord, "sn", None)
    info: dict[str, Any] = {
        "identifiers": mower_identifiers(coord),
        "manufacturer": "Dreame",
        "model": model or "dreame.mower.g2408",
        "name": "Dreame A2 Mower",
    }
    if sn:
        info["serial_number"] = sn
    if mac:
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return DeviceInfo(**info)


def map_device_info(
    coord: "DreameA2MowerCoordinator",
    map_id: int,
    name: str | None,
) -> DeviceInfo:
    display_name = name or f"Map {map_id + 1}"
    return DeviceInfo(
        identifiers=map_identifiers(coord, map_id),
        via_device=(DOMAIN, _stable_id(coord)),
        manufacturer="Dreame",
        name=display_name,
    )
```

Then add to `coordinator.py` (search for the class body, add as a property):

```python
    @property
    def sn(self) -> str | None:
        """Hardware serial number from the cloud client, or None if not yet known."""
        client = self._cloud
        return getattr(client, "_sn", None) if client is not None else None
```

Also expose `mac` and `model` similarly if not already exposed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_devices_helpers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_devices.py custom_components/dreame_a2_mower/coordinator.py tests/integration/test_devices_helpers.py
git commit -m "feat(devices): add SN-keyed identifier + DeviceInfo helpers"
```

---

## Task 3: Migration engine `_migration.py` (skeleton + version bump)

**Files:**
- Create: `custom_components/dreame_a2_mower/_migration.py`
- Modify: `custom_components/dreame_a2_mower/config_flow.py:39` — `VERSION = 2`
- Modify: `custom_components/dreame_a2_mower/__init__.py` — add `async_migrate_entry`
- Test: `tests/integration/test_migration_v1_v2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_migration_v1_v2.py
"""async_migrate_entry rewrites entity registry unique_ids v1 -> v2."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.dreame_a2_mower._migration import async_migrate_entry
from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.asyncio
async def test_migration_bumps_version_from_1_to_2():
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.entry_id = "abc123"

    with patch(
        "custom_components.dreame_a2_mower._migration._collect_rewrites",
        return_value={},
    ), patch(
        "custom_components.dreame_a2_mower._migration._apply_rewrites",
        new=AsyncMock(return_value=([], [])),
    ):
        ok = await async_migrate_entry(hass, entry)

    assert ok is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, version=2
    )


@pytest.mark.asyncio
async def test_migration_noop_for_already_v2():
    hass = MagicMock()
    entry = MagicMock()
    entry.version = 2
    ok = await async_migrate_entry(hass, entry)
    assert ok is True
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_migration_emits_orphan_notification_when_unmapped():
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.entry_id = "abc123"

    apply_mock = AsyncMock(return_value=([], ["sensor.dreame_a2_mower_orphan"]))
    notify_mock = AsyncMock()
    with patch(
        "custom_components.dreame_a2_mower._migration._collect_rewrites",
        return_value={},
    ), patch(
        "custom_components.dreame_a2_mower._migration._apply_rewrites",
        new=apply_mock,
    ), patch(
        "custom_components.dreame_a2_mower._migration._notify_orphans",
        new=notify_mock,
    ):
        await async_migrate_entry(hass, entry)

    notify_mock.assert_awaited_once()
    args = notify_mock.await_args.args
    assert "sensor.dreame_a2_mower_orphan" in args[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_migration_v1_v2.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement migration engine**

```python
# custom_components/dreame_a2_mower/_migration.py
"""Entity-registry migration v1 -> v2: SN-based unique_ids.

Rewrites unique_ids from `{entry_id}_*` (and `{entry_id}_map_{N}_*`) to
`{stable_id}_*` (and `{stable_id}_map_{N}_*`). Stable id is the hardware
SN when available, falling back to mac then entry_id.

The rewrite map is built per task as entities are migrated to their new
shapes. Unmapped legacy entities are surfaced via persistent_notification
for manual cleanup via WS `config/entity_registry/remove`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Run unique_id rewrites and bump entry version."""
    if entry.version >= 2:
        return True

    _LOGGER.info(
        "%s: migrating config entry %s from v%d to v2 (SN-based unique_ids)",
        DOMAIN, entry.entry_id, entry.version,
    )

    rewrites = _collect_rewrites(hass, entry)
    rewritten, orphans = await _apply_rewrites(hass, entry, rewrites)

    if orphans:
        await _notify_orphans(hass, entry, orphans)

    hass.config_entries.async_update_entry(entry, version=2)
    _LOGGER.info(
        "%s: migration complete: %d entities rewritten, %d orphans",
        DOMAIN, len(rewritten), len(orphans),
    )
    return True


def _collect_rewrites(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Build the {old_unique_id: new_unique_id} map.

    Populated incrementally as entities migrate in subsequent tasks.
    Today returns empty (no entity has migrated yet).
    """
    return {}


async def _apply_rewrites(
    hass: HomeAssistant,
    entry: ConfigEntry,
    rewrites: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Apply rewrites to the entity registry.

    Returns (rewritten_entity_ids, orphan_entity_ids).
    """
    registry = er.async_get(hass)
    rewritten: list[str] = []
    orphans: list[str] = []
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue
        if entity.unique_id in rewrites:
            new = rewrites[entity.unique_id]
            registry.async_update_entity(entity.entity_id, new_unique_id=new)
            rewritten.append(entity.entity_id)
            _LOGGER.debug(
                "%s migration: %s unique_id %r -> %r",
                DOMAIN, entity.entity_id, entity.unique_id, new,
            )
        elif entity.unique_id.startswith(f"{entry.entry_id}_"):
            # Old-style id we don't have a mapping for: orphan.
            orphans.append(entity.entity_id)
    return rewritten, orphans


async def _notify_orphans(
    hass: HomeAssistant,
    entry: ConfigEntry,
    orphans: list[str],
) -> None:
    """Surface unmapped legacy entities via persistent_notification."""
    title = f"{DOMAIN}: migration left orphan entities"
    message = (
        "The Dreame A2 Mower integration migrated to SN-based entity ids. "
        "The following entities have legacy ids with no mapping and should "
        "be removed manually (Settings → Devices → entity → '...' menu):\n\n"
        + "\n".join(f"- `{eid}`" for eid in orphans)
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": title,
            "message": message,
            "notification_id": f"{DOMAIN}_migration_v2_orphans",
        },
        blocking=False,
    )
```

Bump `config_flow.py:39`:

```python
    VERSION = 2
```

In `__init__.py`, after the imports add:

```python
from ._migration import async_migrate_entry as _async_migrate_entry


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """HA hook: run on integration setup when entry.version < class.VERSION."""
    return await _async_migrate_entry(hass, entry)
```

(Keep the existing `async_setup_entry` unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_migration_v1_v2.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_migration.py custom_components/dreame_a2_mower/__init__.py custom_components/dreame_a2_mower/config_flow.py tests/integration/test_migration_v1_v2.py
git commit -m "feat(migration): v1->v2 entity-registry rewrite engine"
```

---

## Task 4: Coordinator sub-device sync hook

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — add `_sync_map_subdevices` method, call from `_apply_mapl` and after `_refresh_map`
- Test: `tests/integration/test_subdevice_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_subdevice_sync.py
"""Coordinator syncs HA devices to match _cached_maps_by_id."""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.asyncio
async def test_sync_creates_subdevice_per_map_id(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        mock_reg.return_value = registry
        coord._sync_map_subdevices()

    calls = registry.async_get_or_create.call_args_list
    identifiers = [c.kwargs["identifiers"] for c in calls]
    assert {(DOMAIN, "G2408053AEE0006232_map_0")} in identifiers
    assert {(DOMAIN, "G2408053AEE0006232_map_1")} in identifiers


@pytest.mark.asyncio
async def test_sync_removes_subdevice_for_dropped_map(
    coordinator_with_two_maps,
):
    coord = coordinator_with_two_maps
    coord._cached_maps_by_id = {0: coord._cached_maps_by_id[0]}  # drop map 1
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        # Pretend map_1 is registered.
        existing = MagicMock()
        existing.identifiers = {(DOMAIN, "G2408053AEE0006232_map_1")}
        existing.id = "dev_map_1"
        registry.devices.values.return_value = [existing]
        mock_reg.return_value = registry
        coord._sync_map_subdevices()

    registry.async_remove_device.assert_called_with("dev_map_1")
```

Add a fixture in `tests/integration/conftest.py` (or local conftest):

```python
@pytest.fixture
def coordinator_with_two_maps():
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.map_decoder import MapData
    coord = MagicMock()
    coord.sn = "G2408053AEE0006232"
    coord.entry.entry_id = "abc123"
    coord._cloud = MagicMock(sn="G2408053AEE0006232", mac="ef:ce:cc:aa:fe:fd",
                              model="dreame.mower.g2408")
    m0 = MagicMock(spec=MapData); m0.map_id = 0; m0.name = "Front"
    m1 = MagicMock(spec=MapData); m1.map_id = 1; m1.name = "Back"
    coord._cached_maps_by_id = {0: m0, 1: m1}
    # Bind the real method.
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )
    coord._sync_map_subdevices = (
        DreameA2MowerCoordinator._sync_map_subdevices.__get__(coord)
    )
    return coord
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_subdevice_sync.py -v`
Expected: FAIL — `_sync_map_subdevices` not defined.

- [ ] **Step 3: Implement `_sync_map_subdevices`**

In `coordinator.py`, add:

```python
    def _get_device_registry(self):
        from homeassistant.helpers import device_registry as dr
        return dr.async_get(self.hass)

    def _sync_map_subdevices(self) -> None:
        """Add HA devices for new map_ids; remove devices for dropped ones.

        Called whenever `_cached_maps_by_id` may have changed (after
        `_apply_mapl` and after `_refresh_map`).
        """
        from ._devices import _stable_id, map_device_info
        registry = self._get_device_registry()
        stable = _stable_id(self)
        wanted_ids = set(self._cached_maps_by_id.keys())

        for map_id, map_data in self._cached_maps_by_id.items():
            info = map_device_info(self, map_id, getattr(map_data, "name", None))
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                **info,
            )

        # Remove orphan map sub-devices belonging to this entry.
        prefix = f"{stable}_map_"
        for dev in list(registry.devices.values()):
            for domain, ident in dev.identifiers:
                if domain != DOMAIN or not ident.startswith(prefix):
                    continue
                try:
                    map_id = int(ident.removeprefix(prefix))
                except ValueError:
                    continue
                if map_id not in wanted_ids:
                    registry.async_remove_device(dev.id)
                break
```

Then in `_apply_mapl` and at the end of `_refresh_map` (search for existing call sites), add:

```python
        self._sync_map_subdevices()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_subdevice_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_subdevice_sync.py tests/integration/conftest.py
git commit -m "feat(coordinator): sync HA sub-devices to _cached_maps_by_id"
```

---

## Task 5: Mower-level entities → SN identifiers + unique_ids

**Files:**
- Modify: `custom_components/dreame_a2_mower/{switch,binary_sensor,sensor,camera,select,button,event,device_tracker,lawn_mower,number,time}.py` — every place that constructs `DeviceInfo(identifiers={(DOMAIN, coordinator.entry.entry_id)})` and unique_ids `f"{coordinator.entry.entry_id}_{...}"`
- Modify: `custom_components/dreame_a2_mower/_migration.py:_collect_rewrites` — register the rewrite map for the (still-mower-level) entities
- Test: `tests/integration/test_migration_v1_v2.py` — extend with a real-rewrite case

- [ ] **Step 1: Identify the mower-level entities to rekey (NOT the per-map ones, which Tasks 6-12 handle).**

Run: `grep -rn "coordinator.entry.entry_id" custom_components/dreame_a2_mower/*.py | grep -v "_map_" | sort`

Document the list inline in `_migration.py:_collect_rewrites` as comments.

- [ ] **Step 2: Write the failing test**

Add to `tests/integration/test_migration_v1_v2.py`:

```python
@pytest.mark.asyncio
async def test_migration_rewrites_battery_unique_id():
    """Battery sensor: {entry_id}_battery -> {sn}_battery."""
    from custom_components.dreame_a2_mower._migration import _collect_rewrites
    from unittest.mock import MagicMock

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "abc123"
    entry.runtime_data = MagicMock()
    entry.runtime_data.sn = "G2408053AEE0006232"
    rewrites = _collect_rewrites(hass, entry)

    assert rewrites.get("abc123_battery") == "G2408053AEE0006232_battery"
    assert rewrites.get("abc123_signal") == "G2408053AEE0006232_signal"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/integration/test_migration_v1_v2.py::test_migration_rewrites_battery_unique_id -v`
Expected: FAIL — empty rewrite map.

- [ ] **Step 4: Update `_collect_rewrites`**

```python
# Mower-level entity keys (stay on the mower device, just re-keyed).
_MOWER_LEVEL_KEYS: tuple[str, ...] = (
    "battery", "signal", "error", "online", "mqtt_connected",
    "voice_language", "lcd_language", "volume",
    "blade_hours", "active_map", "work_log", "wifi_map",  # wifi_map gets per-map'd in Task 11; keep here for now
    "ai_obstacle_photos",
    "settings_automatic_edge_mowing",
    "settings_safe_edge_mowing",
    "settings_edge_mowing_obstacle_avoidance",
    "settings_obstacle_avoidance_enabled",
    "settings_obstacle_avoidance_ai",
    "settings_obstacle_avoidance_ai_humans",
    "settings_obstacle_avoidance_ai_animals",
    "settings_obstacle_avoidance_ai_objects",
    "settings_edgemaster",
    # ... extend per the grep output
)

def _collect_rewrites(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coord is None:
        # Migration runs before async_setup_entry, so coord may not exist yet.
        # In that case we look up SN from a stash on the entry, or skip.
        sn = getattr(entry.runtime_data, "sn", None) if hasattr(entry, "runtime_data") else None
    else:
        sn = getattr(coord, "sn", None)
    if not sn:
        # Without SN we can't build new ids; defer (the migration becomes a no-op
        # this run). On next setup attempt with sn populated we'll retry.
        _LOGGER.warning(
            "%s migration: SN not yet known; deferring unique_id rewrites",
            DOMAIN,
        )
        return {}

    old_prefix = f"{entry.entry_id}_"
    return {
        f"{old_prefix}{key}": f"{sn}_{key}"
        for key in _MOWER_LEVEL_KEYS
    }
```

**Important**: migration runs BEFORE setup. To get SN at migration time, the simplest approach is: try once; if SN is unavailable (no client yet) skip and let the migration re-run at the *next* `entry.version < 2` call. Since we bump version only on success, a deferred migration is fine. To be safer, do a best-effort cloud client construction in `_migration.py` to fetch device info early. **Initial implementation: defer if no SN.**

- [ ] **Step 5: Update mower-level entity classes**

For each occurrence of:

```python
self._attr_unique_id = f"{coordinator.entry.entry_id}_battery"
self._attr_device_info = DeviceInfo(
    identifiers={(DOMAIN, coordinator.entry.entry_id)},
    ...,
)
```

Replace with:

```python
from ._devices import mower_device_info, mower_unique_id

self._attr_unique_id = mower_unique_id(coordinator, "battery")
self._attr_device_info = mower_device_info(coordinator)
```

Touch every mower-level entity. Skip per-map entities (Tasks 6-12).

- [ ] **Step 6: Run tests, verify pass**

```bash
python -m pytest tests/integration/test_migration_v1_v2.py -v
python -m pytest tests/integration/ -v
```

Expected: existing tests still pass; new migration test passes.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(entities): mower-level identifiers + unique_ids via _devices helpers"
```

---

## Task 6: Per-map zone/spot/edge selects → map sub-device

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py:983-1096` — `DreameA2ZoneSelect`, `DreameA2SpotSelect`, `DreameA2EdgeSelect` become per-map (one entity per `map_id`)
- Modify: `custom_components/dreame_a2_mower/_migration.py:_collect_rewrites` — add `{entry_id}_zone_select` → `{sn}_map_{N}_zone_select` for each map in `_cached_maps_by_id` at migration time. **Caveat**: at v1, only the active map's selector existed; the migration cleanly maps it to `_map_{active_map_id}_*`.
- Test: `tests/integration/test_per_map_zone_select.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_per_map_zone_select.py
"""Zone/spot/edge selects: one entity per map, on map sub-device."""
import pytest
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.select import (
    DreameA2ZoneSelect, DreameA2SpotSelect, DreameA2EdgeSelect,
)


@pytest.mark.asyncio
async def test_zone_select_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    e0 = DreameA2ZoneSelect(coord, map_id=0)
    e1 = DreameA2ZoneSelect(coord, map_id=1)

    assert e0.unique_id == "G2408053AEE0006232_map_0_zone_select"
    assert e1.unique_id == "G2408053AEE0006232_map_1_zone_select"
    assert e0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
    assert e1.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_1")
    }


@pytest.mark.asyncio
async def test_zone_select_options_come_from_its_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    coord._cached_maps_by_id[0].zones = [MagicMock(zone_id=1, name="A")]
    coord._cached_maps_by_id[1].zones = [
        MagicMock(zone_id=1, name="X"), MagicMock(zone_id=2, name="Y"),
    ]
    e0 = DreameA2ZoneSelect(coord, map_id=0)
    e1 = DreameA2ZoneSelect(coord, map_id=1)
    assert e0.options == ["A"]
    assert e1.options == ["X", "Y"]
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — `DreameA2ZoneSelect.__init__` currently doesn't take `map_id`.

- [ ] **Step 3: Refactor `DreameA2ZoneSelect/SpotSelect/EdgeSelect`**

Read existing implementation (search `class DreameA2ZoneSelect`). Refactor signature to `__init__(self, coordinator, map_id: int)`. Replace every reference to `coordinator._active_map_id` (within these three classes) with `self._map_id`. Update unique_id and device_info via `_devices` helpers.

Update the `async_setup_entry` logic in `select.py` that registers these selects: instead of one instance keyed off active map, iterate `coordinator._cached_maps_by_id.keys()` and instantiate one per map. Wire to `coordinator.async_add_listener` so newly-detected maps add their selects via `async_add_entities`.

- [ ] **Step 4: Update migration**

In `_migration.py:_collect_rewrites`, add:

```python
# Per-map selects: at v1 only the active map's selector existed.
coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
active = getattr(coord, "_active_map_id", None) if coord else None
if active is not None:
    for key in ("zone_select", "spot_select", "edge_select"):
        old = f"{entry.entry_id}_{key}"
        new = f"{sn}_map_{active}_{key}"
        rewrites[old] = new
```

- [ ] **Step 5: Run tests pass**

```bash
python -m pytest tests/integration/test_per_map_zone_select.py -v
python -m pytest tests/integration/ -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(select): zone/spot/edge selects per-map on map sub-device"
```

---

## Task 7: Per-map schedule entity → map sub-device

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py` (or wherever `DreameA2ScheduleSelect` lives — grep)
- Modify: `_migration.py:_collect_rewrites` — add schedule rewrites
- Test: `tests/integration/test_per_map_schedule.py`

- [ ] **Step 1: Locate the schedule entity**

Run: `grep -n "Schedule" custom_components/dreame_a2_mower/select.py`

- [ ] **Step 2: Write failing test (mirror pattern of Task 6)**

```python
# tests/integration/test_per_map_schedule.py
import pytest
from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.asyncio
async def test_schedule_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ScheduleSelect

    e0 = DreameA2ScheduleSelect(coord, map_id=0)
    e1 = DreameA2ScheduleSelect(coord, map_id=1)

    assert "_map_0_schedule" in e0.unique_id
    assert "_map_1_schedule" in e1.unique_id
    assert e0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
```

- [ ] **Step 3: Run, fail, implement, pass — same recipe as Task 6**

Refactor schedule entity to take `map_id`. Update setup to instantiate per map. Update migration map.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(select): schedule entity per-map on map sub-device"
```

---

## Task 8: Per-map setting switches → map sub-device

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch.py:838-1216` — Auto Edge, Safe Edge, Obstacle Avoidance on Edges, LiDAR Obstacle Recognition, AI Obstacle Recognition (umbrella + 3 bits) become per-map
- Modify: `_migration.py:_collect_rewrites`
- Test: `tests/integration/test_per_map_setting_switches.py`

- [ ] **Step 1: Identify the active-map-follower switches**

Existing classes (grep `class.*Switch` in `switch.py`):
- `DreameA2AutomaticEdgeMowingSwitch`
- `DreameA2SafeEdgeMowingSwitch`
- `DreameA2EdgeObstacleAvoidanceSwitch`
- `DreameA2LidarObstacleRecognitionSwitch`
- `DreameA2AIObstacleRecognitionSwitch` (umbrella)
- `DreameA2AIObstacleRecognitionHumansSwitch`
- `DreameA2AIObstacleRecognitionAnimalsSwitch`
- `DreameA2AIObstacleRecognitionObjectsSwitch`

All currently read `coordinator.data.settings_*` (which is the active-map mirror). Refactor each to take `map_id` and read from `SettingsRoot.by_map_id_canonical[self._map_id][...]`.

- [ ] **Step 2: Write failing test**

```python
# tests/integration/test_per_map_setting_switches.py
import pytest
from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.switch import (
    DreameA2AutomaticEdgeMowingSwitch,
    DreameA2SafeEdgeMowingSwitch,
    DreameA2EdgeObstacleAvoidanceSwitch,
    DreameA2LidarObstacleRecognitionSwitch,
    DreameA2AIObstacleRecognitionSwitch,
    DreameA2AIObstacleRecognitionHumansSwitch,
    DreameA2AIObstacleRecognitionAnimalsSwitch,
    DreameA2AIObstacleRecognitionObjectsSwitch,
)


@pytest.mark.parametrize("cls,key", [
    (DreameA2AutomaticEdgeMowingSwitch, "settings_automatic_edge_mowing"),
    (DreameA2SafeEdgeMowingSwitch, "settings_safe_edge_mowing"),
    (DreameA2EdgeObstacleAvoidanceSwitch, "settings_edge_mowing_obstacle_avoidance"),
    (DreameA2LidarObstacleRecognitionSwitch, "settings_obstacle_avoidance_enabled"),
    (DreameA2AIObstacleRecognitionSwitch, "settings_obstacle_avoidance_ai"),
    (DreameA2AIObstacleRecognitionHumansSwitch, "settings_obstacle_avoidance_ai_humans"),
    (DreameA2AIObstacleRecognitionAnimalsSwitch, "settings_obstacle_avoidance_ai_animals"),
    (DreameA2AIObstacleRecognitionObjectsSwitch, "settings_obstacle_avoidance_ai_objects"),
])
def test_setting_switches_per_map(coordinator_with_two_maps, cls, key):
    coord = coordinator_with_two_maps
    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)

    assert e0.unique_id == f"G2408053AEE0006232_map_0_{key}"
    assert e1.unique_id == f"G2408053AEE0006232_map_1_{key}"
    assert e0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_setting_switch_reads_from_its_maps_settings(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    coord.data = type("S", (), {})()
    coord.data.cloud_state = type("CS", (), {})()
    coord.data.cloud_state.settings = type("SR", (), {
        "by_map_id_canonical": {
            0: {"safeEdgeMowing": True},
            1: {"safeEdgeMowing": False},
        },
    })()
    e0 = DreameA2SafeEdgeMowingSwitch(coord, map_id=0)
    e1 = DreameA2SafeEdgeMowingSwitch(coord, map_id=1)
    assert e0.is_on is True
    assert e1.is_on is False
```

- [ ] **Step 3: Run, fail, refactor each switch class**

Each class: add `map_id` param, switch read source to per-map settings dict, switch write target to `_settings_writes.settings_optimistic_write(coord, map_id=self._map_id, ...)`. Update unique_id + device_info.

Update setup function in `switch.py:async_setup_entry` to iterate `coord._cached_maps_by_id.keys()` for these classes.

- [ ] **Step 4: Update migration map**

```python
# In _collect_rewrites, after the active-map block:
if active is not None:
    for key in (
        "settings_automatic_edge_mowing",
        "settings_safe_edge_mowing",
        "settings_edge_mowing_obstacle_avoidance",
        "settings_obstacle_avoidance_enabled",
        "settings_obstacle_avoidance_ai",
        "settings_obstacle_avoidance_ai_humans",
        "settings_obstacle_avoidance_ai_animals",
        "settings_obstacle_avoidance_ai_objects",
    ):
        rewrites[f"{entry.entry_id}_{key}"] = f"{sn}_map_{active}_{key}"
        # ALSO remove the mower-level rewrite added in Task 5 for these keys.
```

In Task 5's `_MOWER_LEVEL_KEYS`, REMOVE these eight entries (since they're now per-map). Re-test.

- [ ] **Step 5: Run, pass, commit**

```bash
python -m pytest tests/integration/ -v
git add -A
git commit -m "refactor(switch): setting switches per-map on map sub-device"
```

---

## Task 9: Per-map snapshot camera → map sub-device

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py:207-244` — `DreameA2PerMapCamera` is already keyed by `map_id`; just attach to map sub-device + use SN unique_id
- Modify: `_migration.py:_collect_rewrites`
- Test: `tests/integration/test_per_map_cameras.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_per_map_cameras.py
import pytest
from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.asyncio
async def test_per_map_snapshot_on_subdevice(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2PerMapCamera

    cam0 = DreameA2PerMapCamera(coord, map_id=0)
    assert cam0.unique_id == "G2408053AEE0006232_map_0_map"
    assert cam0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
```

- [ ] **Step 2: Run, fail, refactor**

In `DreameA2PerMapCamera.__init__`:
- Replace `self._attr_unique_id = f"{coordinator.entry.entry_id}_map_{map_id}"` with `mower_unique_id(coordinator, ...)` — actually use `map_unique_id(coordinator, map_id, "map")`.
- Set `self._attr_device_info = map_device_info(coordinator, map_id, getattr(coord._cached_maps_by_id.get(map_id), "name", None))`.

- [ ] **Step 3: Update migration**

```python
# In _collect_rewrites:
for map_id in (coord._cached_maps_by_id if coord else {}):
    rewrites[f"{entry.entry_id}_map_{map_id}"] = f"{sn}_map_{map_id}_map"
```

- [ ] **Step 4: Run pass, commit**

```bash
python -m pytest tests/integration/test_per_map_cameras.py -v
git add -A
git commit -m "refactor(camera): per-map snapshot camera on map sub-device"
```

---

## Task 10: Active map select → SN unique_id (stays mower-level)

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py:1218-1344`
- Test: extend `tests/integration/test_per_map_zone_select.py` or add new

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_active_map_select_unique_id_uses_sn(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect

    e = DreameA2ActiveMapSelect(coord)
    assert e.unique_id == "G2408053AEE0006232_active_map"
    from custom_components.dreame_a2_mower.const import DOMAIN
    assert e.device_info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}
```

- [ ] **Step 2: Run, fail, update**

Replace unique_id construction in `DreameA2ActiveMapSelect.__init__` with `mower_unique_id(coordinator, "active_map")` and `self._attr_device_info = mower_device_info(coordinator)`.

- [ ] **Step 3: Migration mapping**

`active_map` is already in `_MOWER_LEVEL_KEYS` from Task 5 — confirm it's there. No additional rewrite needed.

- [ ] **Step 4: Run pass, commit**

```bash
git add -A
git commit -m "refactor(select): active_map select uses SN unique_id"
```

---

## Task 11: WiFi heatmap camera → per-map sub-device

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py:412-449` — `DreameA2WifiMapCamera` becomes per-map
- Modify: `custom_components/dreame_a2_mower/cloud_client.py:745-820` — `fetch_wifi_map(map_id: int)` cache by `(map_id, sha)`
- Modify: `custom_components/dreame_a2_mower/wifi_map_render.py` — accept `map_id`
- Modify: `_migration.py:_collect_rewrites`
- Test: `tests/integration/test_per_map_cameras.py` (add cases)

- [ ] **Step 1: Write failing test**

```python
def test_wifi_map_camera_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera
    from custom_components.dreame_a2_mower.const import DOMAIN

    cam0 = DreameA2WifiMapCamera(coord, map_id=0)
    cam1 = DreameA2WifiMapCamera(coord, map_id=1)

    assert cam0.unique_id == "G2408053AEE0006232_map_0_wifi_map"
    assert cam1.unique_id == "G2408053AEE0006232_map_1_wifi_map"
    assert cam0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Refactor**

- `DreameA2WifiMapCamera.__init__(self, coord, map_id)`
- Camera reads its own map's heatmap (cloud response carries one heatmap per map; fetch by map_id)
- `cloud_client.fetch_wifi_map(map_id: int)` — extend signature; cache by `(map_id, sha)`; pass map_id through to OSS URL selection (cloud response already keys heatmaps per map_id, see `dreame_cloud_dumps/`)
- `async_setup_entry` (camera platform) iterates `coord._cached_maps_by_id` for WiFi camera too
- The "refresh wifi map" button entity (search for `wifi_map_refresh`) becomes per-map similarly

- [ ] **Step 4: Update migration**

```python
# Remove "wifi_map" from _MOWER_LEVEL_KEYS (Task 5).
# Add per-map mapping (legacy single -> active map's per-map):
if active is not None:
    rewrites[f"{entry.entry_id}_wifi_map"] = f"{sn}_map_{active}_wifi_map"
    rewrites[f"{entry.entry_id}_wifi_map_refresh"] = f"{sn}_map_{active}_wifi_map_refresh"
```

- [ ] **Step 5: Run pass, commit**

```bash
git add -A
git commit -m "refactor(camera): wifi heatmap per-map on map sub-device"
```

---

## Task 12: LiDAR archive per-map subdirs

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/lidar.py` — `LidarArchive.__init__(self, root: Path, map_id: int)`; `root_for_map = root / str(map_id)`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — replace `self.lidar_archive` with `self.lidar_archives: dict[int, LidarArchive]`; getter `lidar_archive_for(map_id)`; route incoming push through `lidar_archives[self._active_map_id]`
- Modify: `custom_components/dreame_a2_mower/__init__.py` — one-time migration of flat `lidar/*` into `lidar/0/` if `lidar/0/` doesn't exist and flat files exist; `persistent_notification` reports the move
- Test: `tests/integration/test_lidar_per_map.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_lidar_per_map.py
import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive


def test_lidar_archive_uses_map_id_subdir(tmp_path: Path):
    archive = LidarArchive(tmp_path, map_id=0)
    archive.add(b"fake_pcd_bytes_0", meta={"ts": 100})
    assert (tmp_path / "0").is_dir()
    assert (tmp_path / "0" / "index.json").is_file()
    idx = json.loads((tmp_path / "0" / "index.json").read_text())
    assert len(idx["entries"]) == 1


def test_lidar_archives_isolated_per_map(tmp_path: Path):
    a0 = LidarArchive(tmp_path, map_id=0)
    a1 = LidarArchive(tmp_path, map_id=1)
    a0.add(b"X", meta={"ts": 1})
    a1.add(b"Y", meta={"ts": 2})
    assert a0.latest()[0] == b"X"
    assert a1.latest()[0] == b"Y"


@pytest.mark.asyncio
async def test_coordinator_routes_push_to_active_map(
    coordinator_with_two_maps, tmp_path,
):
    coord = coordinator_with_two_maps
    coord.lidar_archives = {
        0: LidarArchive(tmp_path, map_id=0),
        1: LidarArchive(tmp_path, map_id=1),
    }
    coord._active_map_id = 1
    coord.handle_lidar_push(b"PCD_DATA", meta={"ts": 100})
    assert coord.lidar_archives[1].latest()[0] == b"PCD_DATA"
    assert coord.lidar_archives[0].latest() is None  # nothing in map 0
```

(`handle_lidar_push` should already exist or be the rename of an existing private method — grep first.)

- [ ] **Step 2: Run, fail, refactor**

Update `LidarArchive` to accept `map_id`. All file ops use `root / str(map_id)`. Backward-compat shim: if `map_id is None` (legacy callers), treat as 0 with a `DeprecationWarning`.

In coordinator: replace `self.lidar_archive` with the dict; everywhere it's read, route through `lidar_archive_for(map_id)`. Default to `_active_map_id`.

- [ ] **Step 3: Implement startup migration of flat archive**

In `__init__.py`, after coordinator init but before adding entities:

```python
async def _migrate_flat_lidar_archive(coordinator) -> None:
    """One-shot move of <root>/*.pcd -> <root>/0/*.pcd; preserves index."""
    from pathlib import Path
    root = Path(coordinator._lidar_archive_root)
    if (root / "0").is_dir():
        return  # already migrated
    flat_pcds = list(root.glob("*.pcd"))
    flat_index = root / "index.json"
    if not flat_pcds and not flat_index.is_file():
        return  # nothing to migrate
    (root / "0").mkdir(parents=True, exist_ok=True)
    moved = []
    for f in flat_pcds:
        f.rename(root / "0" / f.name)
        moved.append(f.name)
    if flat_index.is_file():
        flat_index.rename(root / "0" / "index.json")
        moved.append("index.json")
    # persistent_notification
    await coordinator.hass.services.async_call(
        "persistent_notification", "create", {
            "title": f"{DOMAIN}: lidar archive migrated to per-map layout",
            "message": (
                f"Moved {len(moved)} files into `lidar/0/`. If your previous "
                f"flat archive contained scans from multiple maps, they all "
                f"now live under map 0; future scans route correctly per map."
            ),
            "notification_id": f"{DOMAIN}_lidar_v2_migration",
        }, blocking=False,
    )

# call from async_setup_entry, before async_config_entry_first_refresh
await _migrate_flat_lidar_archive(coordinator)
```

- [ ] **Step 4: Run tests pass, commit**

```bash
python -m pytest tests/integration/test_lidar_per_map.py -v
python -m pytest tests/integration/ -v
git add -A
git commit -m "feat(lidar): per-map archive subdirs with one-shot flat migration"
```

---

## Task 13: LiDAR camera + HTTP view per-map

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py:355-395` — `DreameA2LidarTopDownCamera(coord, map_id)`
- Modify: `custom_components/dreame_a2_mower/camera.py:591-633` — `LidarPcdDownloadView` URL becomes `/api/dreame_a2_mower/lidar/{map_id}/latest.pcd`
- Modify: `_migration.py:_collect_rewrites` — `{entry_id}_lidar_top_down` → `{sn}_map_{active}_lidar_top_down`
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js` (if it hardcodes the URL) — use a configurable map_id
- Modify: `dashboards/mower/dashboard.yaml` (if a lidar card is bundled) — point at `camera.dreame_a2_mower_map_0_lidar_top_down`
- Test: `tests/integration/test_lidar_per_map.py` (add)

- [ ] **Step 1: Write failing test**

```python
def test_lidar_top_down_per_map(coordinator_with_two_maps, tmp_path):
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera
    from custom_components.dreame_a2_mower.const import DOMAIN

    coord = coordinator_with_two_maps
    coord.lidar_archives = {
        0: LidarArchive(tmp_path, map_id=0),
        1: LidarArchive(tmp_path, map_id=1),
    }
    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert cam0.unique_id == "G2408053AEE0006232_map_0_lidar_top_down"
    assert cam1.unique_id == "G2408053AEE0006232_map_1_lidar_top_down"
    assert cam0.device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
```

- [ ] **Step 2: Run, fail, refactor**

`DreameA2LidarTopDownCamera.__init__(self, coord, map_id)`. Reads from `coord.lidar_archive_for(map_id).latest()`.

`LidarPcdDownloadView`: change `url = "/api/dreame_a2_mower/lidar/latest.pcd"` to `url = "/api/dreame_a2_mower/lidar/{map_id}/latest.pcd"` and `name = "api:dreame_a2_mower:lidar"`. The `get` method takes `map_id: str` from the URL, parses it, and serves from the right archive.

`async_setup_entry` for camera platform iterates `coord._cached_maps_by_id` for the LiDAR camera too.

- [ ] **Step 3: Update migration**

```python
if active is not None:
    rewrites[f"{entry.entry_id}_lidar_top_down"] = (
        f"{sn}_map_{active}_lidar_top_down"
    )
```

Remove `lidar_top_down` from `_MOWER_LEVEL_KEYS` if present.

- [ ] **Step 4: Update LiDAR card JS to accept map_id**

Open `www/dreame-a2-lidar-card.js`. If it hardcodes `/api/dreame_a2_mower/lidar/latest.pcd`, change to read a `map_id` config field (default 0) and substitute. The bundled `dashboards/mower/dashboard.yaml` (if it includes the card) gains `map_id: 0` per card instance.

- [ ] **Step 5: Run pass, commit**

```bash
python -m pytest tests/integration/test_lidar_per_map.py -v
git add -A
git commit -m "feat(lidar): per-map top-down camera + HTTP view; card map_id config"
```

---

## Task 14: Migration deferral when SN unknown + SN-on-setup retry

**Files:**
- Modify: `custom_components/dreame_a2_mower/_migration.py` — handle deferred-migration case
- Modify: `custom_components/dreame_a2_mower/__init__.py:async_setup_entry` — after coordinator's first refresh succeeds (so SN is known), if `entry.version < 2` re-run the migration in-place
- Test: `tests/integration/test_migration_v1_v2.py` — add deferral test

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_migration_defers_when_sn_unknown_and_re_runs_after_setup():
    """If SN isn't known at migrate time, version stays at 1; re-runs after setup."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from custom_components.dreame_a2_mower._migration import (
        async_migrate_entry, _collect_rewrites,
    )
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {}}  # no coord yet
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock(version=1, entry_id="abc123", runtime_data=None)

    # First run: no SN, defer.
    rewrites = _collect_rewrites(hass, entry)
    assert rewrites == {}

    with patch(
        "custom_components.dreame_a2_mower._migration._apply_rewrites",
        new=AsyncMock(return_value=([], [])),
    ):
        ok = await async_migrate_entry(hass, entry)
    assert ok is True
    # Version should NOT be bumped on a deferred (empty-rewrites) run.
    hass.config_entries.async_update_entry.assert_not_called()
```

- [ ] **Step 2: Update `async_migrate_entry`**

```python
async def async_migrate_entry(hass, entry):
    if entry.version >= 2:
        return True
    rewrites = _collect_rewrites(hass, entry)
    if not rewrites:
        # No SN yet; defer to next setup attempt.
        _LOGGER.info(
            "%s: migration deferred until SN is known", DOMAIN,
        )
        return True  # OK to proceed with setup; we'll retry.

    rewritten, orphans = await _apply_rewrites(hass, entry, rewrites)
    if orphans:
        await _notify_orphans(hass, entry, orphans)
    hass.config_entries.async_update_entry(entry, version=2)
    return True
```

- [ ] **Step 3: Wire post-first-refresh retry in `__init__.py:async_setup_entry`**

After `await coordinator.async_config_entry_first_refresh()`:

```python
    if entry.version < 2:
        from ._migration import async_migrate_entry as _migrate
        await _migrate(hass, entry)
```

- [ ] **Step 4: Run pass, commit**

```bash
python -m pytest tests/integration/test_migration_v1_v2.py -v
git add -A
git commit -m "feat(migration): defer if SN unknown; retry post-first-refresh"
```

---

## Task 15: Polish, docs, release

**Files:**
- Run lint/typecheck across the whole module
- Update `docs/research/g2408-research-journal.md` with one entry summarising Phase 2 Foundation
- Bump `manifest.json` version (release.sh handles this — see below)
- Update `README.md` "Tested with one mower; multi-mower partially supported, untested." note
- Run `tools/release.sh` to bump+tag+push+release

- [ ] **Step 1: Run full lint + type pass**

```bash
ruff check custom_components/dreame_a2_mower/
mypy custom_components/dreame_a2_mower/
```

Fix any errors. Do NOT add `# type: ignore` to silence — fix the underlying type. Commit fixes with `chore(types): fix mypy errors after multi-map phase 2 foundation`.

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -x --tb=short
```

All pass. If any fail, fix in-place (likely fixture updates for the new SN-keyed identifiers).

```bash
git add -A
git commit -m "test: update fixtures for SN-keyed identifiers"
```

- [ ] **Step 3: Add a research-journal entry**

Open `docs/research/g2408-research-journal.md`. Append a dated section:

```markdown
## 2026-05-10 — Multi-map Phase 2 Foundation shipped

Reshape: every existing per-map entity now lives on its corresponding
map sub-device (zone/spot/edge selects, schedule, the eight settings
switches, per-map snapshot camera, WiFi heatmap camera, LiDAR top-down
camera). All entity unique_ids are keyed off the hardware SN
(`G2408053AEE0006232` here) instead of `entry_id`, so they survive
config-entry re-add. `async_migrate_entry` v1→v2 rewrites legacy ids
in one pass; orphans surface via `persistent_notification`. LiDAR
archive moved from a flat layout to `lidar/{map_id}/` subdirs with a
one-shot startup migration.

What's next: Plan 2 adds new per-map entities (mowing-type select,
maintenance points, pathway / ignore zones, live video, map metadata
sensors) plus the Custom Mode service-call API. Plan 3 adds the
mower-level entities from the second app settings page.
```

- [ ] **Step 4: README note**

In `README.md` (search for an existing "Limitations" or "Status" section, or add one):

```markdown
### Multi-mower support

This integration is tested with a single mower per Dreame account. The
internal architecture (SN-keyed identifiers, sub-devices via `via_device`)
allows multiple mowers under separate config entries, but it has not
been tested. If you have two A2/g2408 mowers, expect rough edges; please
file an issue.
```

- [ ] **Step 5: Commit docs**

```bash
git add docs/research/g2408-research-journal.md README.md
git commit -m "docs: phase 2 foundation summary + multi-mower limitation note"
```

- [ ] **Step 6: Cut release**

```bash
./tools/release.sh
```

Confirm the resulting GitHub Release is visible with HACS-compatible naming. The script bumps version, tags, pushes, and creates the GH Release per the standing convention.

- [ ] **Step 7: Verify on live HA**

Wait for HACS to pick up the new release (or trigger HACS refresh). Have the user install via HACS and restart HA. Verify:

1. Existing entities retain their history (rewrite worked) — check `sensor.dreame_a2_mower_battery` history graph in the HA UI.
2. New sub-devices appear: `Map 1`, `Map 2` under the mower in **Settings → Devices**.
3. Per-map zone/spot/edge selects exist, one per map.
4. LiDAR archive on the HA box reorganised: `ls /config/dreame_a2_mower/lidar/` should show `0/` (and `1/` once a Map 2 LiDAR push lands).
5. No orphan entities (or, if any, the persistent_notification listed them and the user can remove via WS).

Document any deviations in `docs/research/g2408-research-journal.md` under the same date.

---

## Self-review checklist

Run AFTER all tasks land but BEFORE final release:

- [ ] **Spec coverage**: every line item in the spec's "Map sub-device" and "Mower device" tables marked `(move)` is implemented in this plan. ✅ (zone/spot/edge selects → Task 6; schedule → Task 7; settings switches → Task 8; per-map snapshot → Task 9; WiFi heatmap → Task 11; LiDAR → Tasks 12-13; AI/Human zones — **GAP**: not migrated in Phase 1 but the entity may not exist yet — verify and add a Task 8b if it does. The mower-level `(move)` items are entirely covered by Task 5.)
- [ ] **No new entities**: confirm no new entity types were added in this plan. If something accidentally got added, remove it; it belongs in Plan 2.
- [ ] **Migration completeness**: every entity whose unique_id changed has a rewrite entry in `_collect_rewrites`. Run `grep -rn "_attr_unique_id = " custom_components/dreame_a2_mower/*.py` and cross-check.
- [ ] **Tests pass**: `pytest tests/ -x` clean.
- [ ] **Lint + type**: `ruff check` and `mypy --strict` clean.
- [ ] **No `entry_id` left in identifier construction**: `grep -rn "DOMAIN, .*entry.entry_id" custom_components/dreame_a2_mower/*.py` should match nothing.

---

## Out of scope (file as TODOs in journal, ship in Plans 2 / 3)

- New per-map entities: mowing-type select, live video camera, map metadata sensors, per-map session sensors, maintenance points (sensor + select), Pathway Obstacle Avoidance (switch + numbers), Ignore Obstacle Zones (sensor + services), AI/Human zones sensor — **Plan 2**.
- Custom Mode services + diagnostic sensor — **Plan 2**.
- Mower-level second-page entities (Rain/Frost/DnD/Anti-theft/Light/etc.) and the new buttons (Find My Robot, Head to Maintenance Point) — **Plan 3**.
- New General Mode setting entities not present today (Mowing Efficiency, Mowing Height, Mowing Direction + sub, Obstacle Avoidance Height, Obstacle Avoidance Distance, EdgeMaster as switch) — **Plan 2** (they're per-map; landed alongside the mowing-type select).
- Mower dashboard yaml reshape to mimic the app's two-page layout — after Plans 2 & 3 land, since dashboard depends on the entities existing.
