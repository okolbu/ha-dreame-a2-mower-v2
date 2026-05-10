"""async_migrate_entry rewrites entity registry unique_ids v1 -> v2."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.dreame_a2_mower._migration import async_migrate_entry
from custom_components.dreame_a2_mower.const import DOMAIN


def test_migration_bumps_version_from_1_to_2():
    """Migration bumps version when rewrites are non-empty (SN known)."""
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.entry_id = "abc123"

    with patch(
        "custom_components.dreame_a2_mower._migration._collect_rewrites",
        return_value={"abc123_battery_level": "G2408_battery_level"},
    ), patch(
        "custom_components.dreame_a2_mower._migration._apply_rewrites",
        new=AsyncMock(return_value=([], [])),
    ):
        ok = asyncio.run(async_migrate_entry(hass, entry))

    assert ok is True
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, version=2
    )


def test_migration_noop_for_already_v2():
    hass = MagicMock()
    entry = MagicMock()
    entry.version = 2
    ok = asyncio.run(async_migrate_entry(hass, entry))
    assert ok is True
    hass.config_entries.async_update_entry.assert_not_called()


def test_migration_emits_orphan_notification_when_unmapped():
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.entry_id = "abc123"

    apply_mock = AsyncMock(return_value=([], ["sensor.dreame_a2_mower_orphan"]))
    notify_mock = AsyncMock()
    with patch(
        "custom_components.dreame_a2_mower._migration._collect_rewrites",
        return_value={"abc123_battery_level": "G2408_battery_level"},
    ), patch(
        "custom_components.dreame_a2_mower._migration._apply_rewrites",
        new=apply_mock,
    ), patch(
        "custom_components.dreame_a2_mower._migration._notify_orphans",
        new=notify_mock,
    ):
        asyncio.run(async_migrate_entry(hass, entry))

    notify_mock.assert_awaited_once()
    args = notify_mock.await_args.args
    assert "sensor.dreame_a2_mower_orphan" in args[2]


def test_migration_rewrites_mower_level_unique_ids():
    """Mower-level sensors: {entry_id}_{key} -> {sn}_{key}."""
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower._migration import _collect_rewrites

    hass = MagicMock()
    # Stash the coordinator in hass.data so _collect_rewrites can find SN.
    coord = MagicMock()
    coord.sn = "G2408053AEE0006232"
    hass.data = {"dreame_a2_mower": {"abc123": coord}}

    entry = MagicMock()
    entry.entry_id = "abc123"

    rewrites = _collect_rewrites(hass, entry)

    # Battery level sensor (DreameA2Sensor)
    assert rewrites.get("abc123_battery_level") == "G2408053AEE0006232_battery_level"
    # WiFi RSSI sensor (DreameA2Sensor)
    assert rewrites.get("abc123_wifi_rssi_dbm") == "G2408053AEE0006232_wifi_rssi_dbm"
    # Lawn mower entity
    assert rewrites.get("abc123_lawn_mower") == "G2408053AEE0006232_lawn_mower"
    # Action button
    assert rewrites.get("abc123_start_mowing") == "G2408053AEE0006232_start_mowing"
    # Active map select
    assert rewrites.get("abc123_active_map") == "G2408053AEE0006232_active_map"


def test_migration_handles_unique_id_collision_gracefully():
    """If new_unique_id already exists, log + skip (don't crash setup)."""
    from unittest.mock import MagicMock, patch

    from custom_components.dreame_a2_mower._migration import (
        async_migrate_entry,
    )

    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock(version=1, entry_id="abc123")

    # Build a fake registry that raises ValueError on the rewrite.
    fake_entity = MagicMock()
    fake_entity.config_entry_id = "abc123"
    fake_entity.unique_id = "abc123_battery"
    fake_entity.entity_id = "sensor.dreame_a2_mower_battery"

    fake_registry = MagicMock()
    fake_registry.entities.values.return_value = [fake_entity]
    fake_registry.async_update_entity.side_effect = ValueError("already exists")

    with patch(
        "custom_components.dreame_a2_mower._migration._collect_rewrites",
        return_value={"abc123_battery": "G2408_battery"},
    ), patch(
        "custom_components.dreame_a2_mower._migration.er.async_get",
        return_value=fake_registry,
    ):
        ok = asyncio.run(async_migrate_entry(hass, entry))

    assert ok is True
    # Should NOT have raised; should still have bumped version.
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, version=2
    )


def test_migration_defers_when_sn_unknown_and_does_not_bump_version():
    """If SN isn't known at migrate time, version stays at 1 so retry can occur."""
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {}}  # no coordinator yet
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock(version=1, entry_id="abc123")
    entry.runtime_data = None

    ok = asyncio.run(async_migrate_entry(hass, entry))

    assert ok is True
    # Version should NOT be bumped on a deferred (empty-rewrites) run.
    hass.config_entries.async_update_entry.assert_not_called()


def test_migration_bumps_version_when_sn_known():
    """When SN is available, the migration runs and bumps the version."""
    hass = MagicMock()
    coord = MagicMock(sn="G2408053AEE0006232")
    coord._active_map_id = None
    coord._cached_maps_by_id = {}
    hass.data = {"dreame_a2_mower": {"abc123": coord}}
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock(version=1, entry_id="abc123")
    fake_registry = MagicMock()
    fake_registry.entities.values.return_value = []

    with patch(
        "custom_components.dreame_a2_mower._migration.er.async_get",
        return_value=fake_registry,
    ):
        ok = asyncio.run(async_migrate_entry(hass, entry))

    assert ok is True
    # SN known → version bumped to 2.
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, version=2
    )
