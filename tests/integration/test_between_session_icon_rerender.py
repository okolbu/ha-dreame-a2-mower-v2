"""TDD tests for the between-session mower-icon re-render trigger.

Bug: when `live_map.is_active()` is False (no session running), the main
view was only re-rendered on the ~2-minute cloud-state refresh.  The mower
icon therefore freezes at the last known position and jumps to the dock
after docking — the return-to-dock drive is invisible.

Fix: `_on_state_update` checks whether the snapshot position has moved
enough (delta threshold) since the last render when live_map is inactive,
and if so calls `_render_main_view()` — throttled to at most once per N
seconds to avoid a re-render on every 5-Hz s1.4 push.

Tests (all behavioural, coordinator-level):
1. Between-session position change beyond threshold → _render_main_view called.
2. Between-session position change below threshold → _render_main_view NOT called.
3. Between-session position unchanged → _render_main_view NOT called.
4. Active session (live_map.is_active() True) → _render_main_view NOT called
   via this path (the existing trail path handles it).
5. Throttle: two between-session moves within the minimum interval → only
   one render call.
6. Throttle reset: a between-session move after the interval has elapsed
   triggers a new render.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal coordinator stub
# ---------------------------------------------------------------------------

def _make_coord(
    *,
    live_map_active: bool = False,
    snap_x: float | None = 3.0,
    snap_y: float | None = 4.0,
    last_render_unix: float = 0.0,
    last_render_x: float | None = None,
    last_render_y: float | None = None,
):
    """Build a minimal coordinator-like object for testing the between-session
    icon re-render path.

    `snap_x`/`snap_y` are the current snapshot position (what the mower's
    state machine reports).  `last_render_x`/`last_render_y` are where the
    icon was last rendered (None = never rendered, treated as very far away).
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)

    # --- live_map ---------------------------------------------------------
    lm = MagicMock()
    lm.is_active.return_value = live_map_active
    coord.live_map = lm

    # --- state_machine (snapshot) -----------------------------------------
    snap = MagicMock()
    snap.position_x_m = snap_x
    snap.position_y_m = snap_y
    sm = MagicMock()
    sm.snapshot.return_value = snap
    coord.state_machine = sm

    # --- throttle state (from _CoreMixin.__init__) -------------------------
    coord._last_live_render_unix = last_render_unix
    coord._last_between_session_render_x: float | None = last_render_x
    coord._last_between_session_render_y: float | None = last_render_y

    # --- render target (spy) ----------------------------------------------
    coord._render_main_view = AsyncMock(return_value=None)

    # --- hass (needed for async_create_task) ------------------------------
    hass = MagicMock()
    coord.hass = hass

    return coord


# ---------------------------------------------------------------------------
# Test 1: position moved beyond threshold → render called
# ---------------------------------------------------------------------------

async def test_between_session_position_moved_triggers_render():
    """A significant between-session position change triggers _render_main_view."""
    coord = _make_coord(
        live_map_active=False,
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=0.0,       # interval already elapsed
        last_render_x=0.0,          # was at origin — now moved to (3,4), delta=5m
        last_render_y=0.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: position moved below threshold → render NOT called
# ---------------------------------------------------------------------------

async def test_between_session_position_tiny_move_no_render():
    """A sub-threshold between-session position change does NOT trigger a render."""
    coord = _make_coord(
        live_map_active=False,
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=0.0,
        last_render_x=3.05,         # only 5 cm away — below threshold
        last_render_y=4.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3: position unchanged → render NOT called
# ---------------------------------------------------------------------------

async def test_between_session_position_unchanged_no_render():
    """An unchanged between-session position does NOT trigger a render."""
    coord = _make_coord(
        live_map_active=False,
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=0.0,
        last_render_x=3.0,          # identical position
        last_render_y=4.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4: active session → render NOT called via this path
# ---------------------------------------------------------------------------

async def test_active_session_does_not_use_between_session_path():
    """During an active session, this helper does NOT call _render_main_view
    (the existing trail path in _on_state_update handles rendering)."""
    coord = _make_coord(
        live_map_active=True,       # session IS active
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=0.0,
        last_render_x=0.0,          # large position delta
        last_render_y=0.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 5: throttle — second call within interval does NOT render
# ---------------------------------------------------------------------------

async def test_between_session_throttle_suppresses_second_render():
    """Two between-session calls within the min interval: only the first renders."""
    coord = _make_coord(
        live_map_active=False,
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=0.0,       # interval elapsed — first call renders
        last_render_x=0.0,
        last_render_y=0.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    # First call — should render (interval elapsed, position moved).
    now_unix = time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)
    coord._render_main_view.assert_awaited_once()

    # Simulate the render having run: _last_live_render_unix is now ~now_unix
    # (this happens inside the helper; the coord state should already be updated).
    # Confirm the attribute was updated by checking it's no longer 0.
    assert coord._last_live_render_unix > 0, (
        "After a render, _last_live_render_unix should be updated to now_unix"
    )

    # Now move the mower a large distance again.
    snap2 = MagicMock()
    snap2.position_x_m = 10.0
    snap2.position_y_m = 10.0
    coord.state_machine.snapshot.return_value = snap2

    # Second call within the same second — throttle should suppress it.
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    # Still only one call total.
    assert coord._render_main_view.await_count == 1, (
        "Throttle should suppress the second render within the min interval"
    )


# ---------------------------------------------------------------------------
# Test 6: throttle reset — render after interval has elapsed
# ---------------------------------------------------------------------------

async def test_between_session_throttle_allows_render_after_interval():
    """After the throttle interval elapses, a new large position change renders."""
    import time as _time

    # Start with last_render at now - 10s (well beyond the throttle interval).
    past_render = _time.time() - 10.0
    coord = _make_coord(
        live_map_active=False,
        snap_x=3.0,
        snap_y=4.0,
        last_render_unix=past_render,
        last_render_x=0.0,          # large delta
        last_render_y=0.0,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = _time.time()
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 7: no position in snapshot → no crash, no render
# ---------------------------------------------------------------------------

async def test_between_session_no_position_no_crash():
    """When snapshot has no position (None), the helper exits cleanly."""
    coord = _make_coord(
        live_map_active=False,
        snap_x=None,                # no position
        snap_y=None,
        last_render_unix=0.0,
        last_render_x=None,
        last_render_y=None,
    )

    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _maybe_rerender_between_session_icon,
    )

    now_unix = time.time()
    # Must not raise.
    await _maybe_rerender_between_session_icon(coord, now_unix=now_unix)

    coord._render_main_view.assert_not_awaited()
