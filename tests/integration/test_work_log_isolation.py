"""Cross-cache isolation: picking a Work Log doesn't touch _main_view_png."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


def _build_coord(active_map_id: int = 0):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._static_map_pngs_by_id = {}
    coord._cached_maps_by_id = {}  # Empty — replay must handle gracefully.
    coord._last_map_md5_by_id = {}
    coord._active_map_id = active_map_id
    coord._cloud = MagicMock()
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[])
    coord.session_archive.load = MagicMock(return_value=None)
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    coord.data = MagicMock()
    coord.data.position_x_m = None
    coord.data.position_y_m = None
    coord.live_map = MagicMock()
    coord.live_map.is_active = MagicMock(return_value=False)
    coord.hass = MagicMock()
    return coord


def test_render_work_log_session_method_exists():
    import inspect
    method = getattr(DreameA2MowerCoordinator, "render_work_log_session", None)
    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_render_work_log_session_does_not_touch_main_view_png():
    """A Work Log render writes _work_log_png and never _main_view_png."""
    coord = _build_coord()
    main_view_before = coord._main_view_png

    # render_work_log_session bails when the session isn't found; we only
    # need to verify it doesn't TOUCH _main_view_png even on failure.
    coord.session_archive.list_sessions = MagicMock(return_value=[])

    async def _executor(fn, *args):
        return fn(*args)

    coord.hass.async_add_executor_job.side_effect = _executor

    asyncio.run(coord.render_work_log_session("does-not-exist"))

    assert coord._main_view_png == main_view_before, (
        "_main_view_png must not change during a Work Log render"
    )
