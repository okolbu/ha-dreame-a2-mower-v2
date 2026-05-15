"""Tests for coordinator-level write helpers + mutex."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock


def test_coordinator_init_declares_chunked_write_lock():
    """Regex check that __init__ creates self._chunked_write_lock as Lock()."""
    # Refactor 2026-05-15: coordinator.py was split into coordinator/
    # package + _coordinator_legacy.py. The class body still lives in
    # the legacy file until task 12 of the decomposition completes.
    src = Path("custom_components/dreame_a2_mower/_coordinator_legacy.py").read_text()
    assert re.search(
        r"self\._chunked_write_lock\s*:\s*asyncio\.Lock\s*=\s*asyncio\.Lock\(\)",
        src,
    ), "coordinator.__init__ should declare self._chunked_write_lock"


def _make_coord_for_settings_write():
    """Build a coordinator stub with cloud_state.settings populated."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    # Make hass.async_add_executor_job actually call the function inline.
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    raw = [
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
    ]
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=raw,
            by_map_id_canonical={
                0: raw[0]["settings"]["0"],
                1: raw[0]["settings"]["1"],
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, locn=None, dock={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    async def _noop_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=lambda: _noop_refresh())
    return coord


def test_write_settings_modifies_both_entries_and_chunks():
    """write_settings RMWs target map on BOTH entries (firmware reads
    from entry 1 — confirmed live 2026-05-09)."""
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is True
    args, _ = coord._cloud.write_chunked_key.call_args
    key_prefix, value = args[0], args[1]
    assert key_prefix == "SETTINGS"
    import json
    parsed = json.loads(value)
    # Both entries' map 0 mutated.
    assert parsed[0]["settings"]["0"]["mowingHeight"] == 7
    assert parsed[1]["settings"]["0"]["mowingHeight"] == 7
    # Other map preserved on both entries.
    assert parsed[0]["settings"]["1"]["mowingHeight"] == 6
    assert parsed[1]["settings"]["1"]["mowingHeight"] == 6


def test_write_settings_returns_false_on_cloud_rejection():
    coord = _make_coord_for_settings_write()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(False, {"code": 10007, "msg": "rejected"})
    )
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is False


def test_write_settings_unknown_map_id_returns_false():
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=99, field="mowingHeight", value=7))
    assert ok is False
    coord._cloud.write_chunked_key.assert_not_called()


def test_write_schedule_uses_write_chunked_key():
    """write_schedule routes through cloud_client.write_chunked_key, not the
    raw set_batch_device_datas method, so it picks up chunking + lock."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, ScheduleSlot, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=10, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, locn=None, dock={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    # Stub _refresh_cloud_state with a coroutine factory (Py 3.14 compat).
    async def _stub_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=_stub_refresh)
    new_slots = (ScheduleSlot(slot_id=0, name="A", raw_blob_b64="", plans=()),)
    asyncio.run(coord.write_schedule(new_slots))
    args, _ = coord._cloud.write_chunked_key.call_args
    assert args[0] == "SCHEDULE"
    # value should contain v=11 (incremented from current 10)
    assert '"v":11' in args[1]


def test_write_ai_human_enabled_uses_write_chunked_key():
    """write_ai_human_enabled routes through write_chunked_key (not set_batch_device_datas)
    to pick up chunking + lock."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    async def _stub_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=_stub_refresh)
    asyncio.run(coord.write_ai_human_enabled(True))
    coord._cloud.write_chunked_key.assert_called_once_with("AI_HUMAN", '"true"')
