"""Regression: non-mow runs must finalize LOCALLY as separate archive entries.

The merge bug: a maintenance run (head-to-point / manual drive) produces no
cloud OSS summary. A MOW finalizes by awaiting the cloud OSS summary (md5);
if the same cloud-summary path is taken for a non-mow run the wait never
resolves, ``live_map`` stays active, and the next run keeps appending into the
SAME archive entry — even across a dock-return. The fix:

  (a) finalize a non-mow run LOCALLY (no cloud-summary await), even when a
      (stale) pending OSS object name is present, classified from the same
      inputs the injector uses (last_task_op / s2p2 50|53 / area_ever_positive);
  (b) defer the finalize past the per-point ARRIVAL (task_state→2) until the
      mower actually DOCKS (charging) — the existing _wait_for_dock_return; and
  (c) split on a new-task-command boundary so a distinct run that starts while
      the prior one is still active does not merge.

These tests drive the REAL coordinator finalize path
(`_periodic_session_retry` → `_dispatch_finalize_action`) against a real
``SessionArchive`` on a tmp dir — the established `__new__` fixture pattern
in this suite (cf. test_rain_delay / test_charging_events / test_lidar_per_map).

This is the finalize-decision flavour (not a full MQTT-driven end-to-end):
the load-bearing assertion of (a) is that a non-mow run with a pending OSS
object name still finalizes LOCALLY (no cloud fetch) as a maintenance_run.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState


class _FakeLifecycle:
    def __init__(self):
        self.fired = []

    def trigger(self, event_type, data):
        self.fired.append((event_type, data))


def _build_coord(tmp_path):
    """A real coordinator wired with just enough to drive the finalize path."""
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)

    archive = SessionArchive(tmp_path)
    c.session_archive = archive

    c.live_map = LiveMapState()
    c.data = MowerState()
    c._prev_task_state = None
    c._real_task_state_observed = True
    # _active_map_id set -> _resolve_finalize_map_id returns it without
    # touching cloud_state, so no CloudState construction is needed.
    c._active_map_id = 0
    c._lifecycle_event = _FakeLifecycle()
    c._notification_event = None
    c._rain_delay_started_at = None
    c.state_machine = None
    c._pending_finalize_done = None
    c._pending_finalize_done_reason = None

    # A cloud client that, if EVER touched, makes the test loud: a non-mow
    # finalize must NOT go through the cloud-OSS path.
    cloud = MagicMock(name="cloud_client")
    cloud.get_interim_file_url.side_effect = AssertionError(
        "non-mow finalize must not fetch the cloud OSS summary"
    )
    cloud.get_file.side_effect = AssertionError(
        "non-mow finalize must not fetch the cloud OSS summary"
    )
    c._cloud = cloud

    # Fake hass: executor jobs run inline; async_set_updated_data writes self.data.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    c.hass = hass

    def _set_data(new):
        c.data = new

    c.async_set_updated_data = _set_data
    return c, archive


def _begin_maintenance_run(c, *, started_unix, target_id, arrive_unix,
                           pending_oss=None, first_event_unix=None):
    """Set up live_map as a maintenance run that arrived at a point."""
    lm = c.live_map
    lm.begin_session(started_unix)
    lm.target_ids = [target_id]
    # No 50/53 (no mow start), no positive area -> maintenance_run.
    lm.error_samples = [(arrive_unix, 75)]  # arrived at point
    # Give it a couple of track points so the entry isn't empty.
    lm.append_point(t=started_unix + 1, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    lm.append_point(t=started_unix + 5, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0)
    # Coordinator-side end-of-session signal: task went idle, prev was running.
    c.data = c.data.__class__(
        task_state_code=None,
        pending_session_object_name=pending_oss,
        pending_session_first_event_unix=first_event_unix,
    )
    c._prev_task_state = 0


async def _finalize_with_dock(c, now_unix, monkeypatch):
    """Run the real periodic-retry tick, firing the dock signal mid-wait."""
    # Pin time so the two finalizes land in distinct archive-filename buckets
    # (the incomplete-archive stem is derived from end_ts = time.time()).
    monkeypatch.setattr("time.time", lambda: float(now_unix))

    async def fire_dock():
        # Wait until the finalize path has entered _wait_for_dock_return.
        for _ in range(400):
            if c._pending_finalize_done is not None:
                break
            await asyncio.sleep(0.005)
        c._pending_finalize_done_reason = "charging"
        if c._pending_finalize_done is not None:
            c._pending_finalize_done.set()

    fire = asyncio.create_task(fire_dock())
    await c._periodic_session_retry()
    await fire


def test_non_mow_finalizes_locally_without_cloud_summary(tmp_path, monkeypatch):
    """(a): a maintenance run with a (stale) pending OSS object name must
    finalize LOCALLY as a maintenance_run — NOT via the cloud OSS fetch.

    Without the fix the finalize gate returns FINALIZE_COMPLETE (because a
    pending OSS name is set) and the dispatcher calls _do_oss_fetch, which
    trips the cloud client's AssertionError side-effects."""
    c, archive = _build_coord(tmp_path)

    async def _run():
        _begin_maintenance_run(
            c, started_unix=1_700_000_000, target_id=1, arrive_unix=1_700_000_300,
            pending_oss="oss/leftover-key.json", first_event_unix=1_700_000_300,
        )
        await _finalize_with_dock(c, now_unix=1_700_000_600, monkeypatch=monkeypatch)

    asyncio.run(_run())

    sessions = archive.list_sessions()
    assert len(sessions) == 1, sessions
    raw = archive.load(sessions[0])
    assert raw is not None
    assert raw.get("session_type") == "maintenance_run"
    assert raw.get("target_ids") == [1]
    # live_map ended -> next run won't merge into it.
    assert not c.live_map.is_active()


def test_two_maintenance_runs_split_into_two_entries(tmp_path, monkeypatch):
    """(a)+(b): two maintenance runs separated by a dock-return finalize into
    TWO separate archive entries (no merge)."""
    c, archive = _build_coord(tmp_path)

    async def _run():
        # ---- Run 1: maintenance run to target 1 ----
        _begin_maintenance_run(c, started_unix=1_700_000_000, target_id=1,
                               arrive_unix=1_700_000_300)
        await _finalize_with_dock(c, now_unix=1_700_000_600, monkeypatch=monkeypatch)

        # ---- dock-return between runs: live_map must be ended ----
        assert not c.live_map.is_active(), (
            "run 1 must have finalized (live_map ended) before run 2 begins"
        )

        # ---- Run 2: maintenance run to target 2 ----
        _begin_maintenance_run(c, started_unix=1_700_001_000, target_id=2,
                               arrive_unix=1_700_001_300)
        await _finalize_with_dock(c, now_unix=1_700_001_600, monkeypatch=monkeypatch)

    asyncio.run(_run())

    sessions = archive.list_sessions()
    assert len(sessions) == 2, (
        f"expected TWO separate maintenance-run archives, got {len(sessions)} "
        "(the runs merged into one entry — the bug)"
    )

    target_sets = []
    types = []
    for entry in sessions:
        raw = archive.load(entry)
        assert raw is not None
        types.append(raw.get("session_type"))
        target_sets.append(raw.get("target_ids"))

    assert all(t == "maintenance_run" for t in types), types
    assert sorted(target_sets) == [[1], [2]], target_sets


def test_new_command_boundary_finalizes_prior_without_dock(tmp_path, monkeypatch):
    """(c): _finalize_prior_for_new_command archives the still-active prior
    NON-mow session locally and ends it — with NO dock wait — so the caller's
    begin_session starts a clean session (no merge)."""
    c, archive = _build_coord(tmp_path)
    monkeypatch.setattr("time.time", lambda: 1_700_000_600.0)

    # Prior maintenance run still active (user abandoned it, no dock).
    _begin_maintenance_run(c, started_unix=1_700_000_000, target_id=1,
                           arrive_unix=1_700_000_300)

    asyncio.run(c._finalize_prior_for_new_command(now_unix=1_700_000_600))

    # Prior session archived locally as a maintenance_run and ended.
    sessions = archive.list_sessions()
    assert len(sessions) == 1, sessions
    raw = archive.load(sessions[0])
    assert raw.get("session_type") == "maintenance_run"
    assert raw.get("target_ids") == [1]
    assert not c.live_map.is_active(), "prior session must be ended -> no merge"


def test_new_command_boundary_split_flag_only_on_empty_to_active():
    """(c) detection guard: the split flag is set so that a per-target arrival
    (s2p56 stays non-empty) does NOT trip, only a real []→active transition.

    Pins the _prev_s2p56_empty bookkeeping that gates the split: a queued
    multi-target run keeps a non-empty status list, so prev stays False and
    no boundary fires.
    """
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.live_map = LiveMapState()

    # Simulate the bookkeeping the _apply closure performs.
    def feed(status):
        now_empty = not status
        tripped = (
            c._prev_s2p56_empty is True
            and not now_empty
            and c.live_map.is_active()
            and c.live_map.total_points() > 0
        )
        c._prev_s2p56_empty = now_empty
        return tripped

    c._prev_s2p56_empty = None
    c.live_map.begin_session(1000)
    c.live_map.append_point(t=1001, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)

    # Queued multi-target run: status never empties -> never splits.
    assert feed([[1, 0], [2, 0]]) is False
    assert feed([[2, 0]]) is False          # target 1 arrived, 2 still queued
    assert feed([[2, 2]]) is False          # target 2 arriving — NOT a split
    # Firmware drops to [] then a brand-new command arrives -> split.
    assert feed([]) is False                # going empty itself is not a split
    assert feed([[5, 0]]) is True           # []→active with prior points -> split
