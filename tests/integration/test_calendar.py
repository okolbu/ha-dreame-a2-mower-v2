"""DreameA2SessionCalendar exposes archived sessions as HA calendar events."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _archived_session(start_ts, end_ts, area=10.0, distance=42.0, map_id=0):
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    return ArchivedSession(
        filename="s.json", start_ts=start_ts, end_ts=end_ts,
        duration_min=(end_ts - start_ts) // 60,
        area_mowed_m2=area, map_area_m2=100, md5=f"md5_{start_ts}",
        map_id=map_id, session_distance_m=distance,
    )


def _archive_with(*entries):
    arc = MagicMock()
    arc.list_sessions.return_value = list(entries)
    return arc


def _make_cal(archive):
    from custom_components.dreame_a2_mower.calendar import (
        DreameA2SessionCalendar,
    )
    coord = MagicMock()
    coord.entry.entry_id = "e"
    coord.session_archive = archive
    cal = DreameA2SessionCalendar.__new__(DreameA2SessionCalendar)
    cal.coordinator = coord
    cal.hass = MagicMock()
    return cal


def test_calendar_exposes_session_as_event():
    cal = _make_cal(_archive_with(_archived_session(
        start_ts=1_700_000_000, end_ts=1_700_001_800,
    )))
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert len(events) == 1
    ev = events[0]
    assert ev.start.timestamp() == 1_700_000_000
    assert ev.end.timestamp() == 1_700_001_800
    # Summary matches the work_log select's option label format so a
    # Lovelace tap_action can pass {{ summary }} → select_option.
    assert ev.summary.startswith("[Mowing] [Map 1] ")
    assert "m² / 30min" in ev.summary


def test_calendar_summary_matches_work_log_label():
    """Summary string MUST be byte-identical to what
    DreameA2WorkLogSelect would generate for the same ArchivedSession,
    so the tap_action can pipe summary → select_option."""
    from custom_components.dreame_a2_mower.select import (
        DreameA2WorkLogSelect,
    )
    cal = _make_cal(_archive_with(_archived_session(
        start_ts=1_700_000_000, end_ts=1_700_001_800,
        area=42.5, distance=0.0, map_id=0,
    )))
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    ev = events[0]
    # Build the work_log label for the same session
    sel = DreameA2WorkLogSelect.__new__(DreameA2WorkLogSelect)
    sel._placeholder = "(pick a session)"
    sel._max_options = 50
    labels, _ = sel._build_options_from_sessions([
        _archived_session(
            start_ts=1_700_000_000, end_ts=1_700_001_800,
            area=42.5, distance=0.0, map_id=0,
        )
    ])
    # labels[0] is the placeholder; labels[1] is the session entry.
    assert ev.summary == labels[1]


def test_calendar_filters_by_date_window():
    cal = _make_cal(_archive_with(
        _archived_session(1_700_000_000, 1_700_001_800),   # in range
        _archived_session(1_600_000_000, 1_600_001_800),   # too old
    ))
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert len(events) == 1


def test_calendar_empty_archive_returns_no_events():
    cal = _make_cal(_archive_with())
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert events == []


def test_calendar_event_property_returns_latest():
    """The `event` property is the 'most recent' session — HA uses it for
    the entity state line. list_sessions() returns sorted most-recent-
    first, so the calendar entity reads entries[0]."""
    cal = _make_cal(_archive_with(
        _archived_session(1_700_100_000, 1_700_101_800),  # latest first
        _archived_session(1_700_000_000, 1_700_001_800),
    ))
    ev = cal.event
    assert ev is not None
    assert ev.start.timestamp() == 1_700_100_000


def test_calendar_event_description_includes_distance():
    cal = _make_cal(_archive_with(_archived_session(
        start_ts=1_700_000_000, end_ts=1_700_001_800,
        distance=523.5,
    )))
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert "524" in events[0].description or "523" in events[0].description
