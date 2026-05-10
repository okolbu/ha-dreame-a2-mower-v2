"""async_migrate_entry rewrites entity registry unique_ids v1 -> v2."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.dreame_a2_mower._migration import async_migrate_entry
from custom_components.dreame_a2_mower.const import DOMAIN


def test_migration_bumps_version_from_1_to_2():
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
        return_value={},
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
