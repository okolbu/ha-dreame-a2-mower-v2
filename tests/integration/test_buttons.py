"""Tests for the WiFi refresh-all button."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_refresh_wifi_button_calls_archive_refresh():
    from custom_components.dreame_a2_mower.button import DreameA2RefreshAllWifiButton

    coord = MagicMock()
    coord.refresh_wifi_archive = AsyncMock(
        return_value={"fetched": 2, "new": 1, "archive_total": 3}
    )
    coord.entry.entry_id = "fake"
    btn = DreameA2RefreshAllWifiButton(coord)
    await btn.async_press()
    coord.refresh_wifi_archive.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_wifi_button_handles_archive_refresh_failure():
    """If refresh_wifi_archive raises, the button logs but does not re-raise."""
    from custom_components.dreame_a2_mower.button import DreameA2RefreshAllWifiButton

    coord = MagicMock()
    coord.refresh_wifi_archive = AsyncMock(side_effect=RuntimeError("network down"))
    coord.entry.entry_id = "fake"
    btn = DreameA2RefreshAllWifiButton(coord)
    # Should NOT raise.
    await btn.async_press()
    coord.refresh_wifi_archive.assert_awaited_once()
