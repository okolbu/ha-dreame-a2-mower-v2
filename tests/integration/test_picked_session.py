"""Integration tests for sensor.dreame_a2_mower_picked_session wiring."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
    format_session_label,
)

FIXTURE_DIR = Path("tests/protocol/data/sessions")


def _make_entry_from_raw(raw: dict) -> SimpleNamespace:
    """Build an ArchivedSession-like namespace from fixture JSON."""
    return SimpleNamespace(
        md5=raw["md5"],
        filename="short.json",
        map_id=0,
        end_ts=raw["end"],
        start_ts=raw["start"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
        local_trail_complete=True,
        still_running=False,
    )


# ---------------------------------------------------------------------------
# Unit-level wiring test: call build_picked_session_summary directly so we
# verify the builder + format_session_label contract without HA/PIL deps.
# ---------------------------------------------------------------------------

def test_build_picked_session_summary_populates_all_required_keys():
    """build_picked_session_summary returns a dict with the expected keys."""
    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    from custom_components.dreame_a2_mower.protocol.session_summary import (
        parse_session_summary,
    )

    summary = parse_session_summary(raw)
    picker_label = format_session_label(entry)

    result = build_picked_session_summary(
        raw_dict=raw,
        summary=summary,
        entry=entry,
        picker_label=picker_label,
    )

    assert result["filename"] == "short.json"
    assert result["label"].startswith("[Mowing]")
    assert "duration_min" in result
    assert "area_mowed_m2" in result
    assert result["md5"] == raw["md5"]


# ---------------------------------------------------------------------------
# Coordinator-wiring test: call render_work_log_session and verify that
# _picked_session_summary is set on the coordinator.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_work_log_session_populates_picked_summary():
    """render_work_log_session populates coord._picked_session_summary."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker,
        NovelObservationRegistry,
    )

    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    # Build a minimal coordinator via object.__new__ (same pattern as
    # _make_coordinator_for_session_tests in test_coordinator.py).
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._picked_session_summary = None
    coord._cached_maps_by_id = {0: SimpleNamespace()}
    coord._active_map_id = 0

    # Stub the session_archive so list_sessions + load return our fixture.
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[entry])
    coord.session_archive.load = MagicMock(return_value=raw)

    # Stub hass.async_add_executor_job so sync callables run inline.
    async def _exec_job(fn, *args):
        return fn(*args)

    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = _exec_job

    # Stub render_work_log so we don't need PIL in this test.
    import custom_components.dreame_a2_mower.coordinator._session as sess_mod

    _original_render_work_log = None
    import custom_components.dreame_a2_mower.map_render as map_render_mod

    _original = map_render_mod.render_work_log
    map_render_mod.render_work_log = lambda *a, **k: b"png"

    try:
        await coord.render_work_log_session("short.json")
    finally:
        map_render_mod.render_work_log = _original

    assert coord._picked_session_summary is not None, (
        "_picked_session_summary should be set after render_work_log_session"
    )
    assert coord._picked_session_summary["filename"] == "short.json"
    assert coord._picked_session_summary["label"].startswith("[Mowing]")
    assert "duration_min" in coord._picked_session_summary


@pytest.mark.asyncio
async def test_placeholder_pick_clears_picked_summary():
    """Picking the placeholder clears both _work_log_png and _picked_session_summary."""
    from custom_components.dreame_a2_mower.const import WORK_LOG_PLACEHOLDER

    # Build a minimal coordinator with the required state.
    coord = MagicMock()
    coord._work_log_png = b"old png"
    coord._picked_session_summary = {"label": "old", "md5": "abc"}
    coord.async_update_listeners = MagicMock()

    # Manually create and configure the select entity to avoid __init__ complexity.
    from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect
    sel = object.__new__(DreameA2WorkLogSelect)
    sel.coordinator = coord
    sel._placeholder = WORK_LOG_PLACEHOLDER
    sel._attr_current_option = "some_session"
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option(WORK_LOG_PLACEHOLDER)

    assert coord._work_log_png is None
    assert coord._picked_session_summary is None
