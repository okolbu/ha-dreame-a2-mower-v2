"""Tests for tools._rebuild_session_lib.probe_reader."""
from __future__ import annotations

import json
import zoneinfo
from pathlib import Path

import pytest

from tools._rebuild_session_lib.probe_reader import ProbeReader


@pytest.fixture
def tmp_probe(tmp_path: Path) -> Path:
    """Write a tiny synthetic probe log."""
    p = tmp_path / "probe.jsonl"
    lines = [
        # mqtt_message with properties_changed: s3p1 = 80
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:00",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 3, "piid": 1, "value": 80}],
            }},
        }),
        # mqtt_message: s2p56 = {"status": [[1, 0]]}
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:01",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 2, "piid": 56,
                            "value": {"status": [[1, 0]]}}],
            }},
        }),
        # pretty: not parsed
        json.dumps({
            "type": "pretty",
            "timestamp": "2026-05-15 08:00:02",
            "text": "PRETTY ...",
        }),
    ]
    p.write_text("\n".join(lines) + "\n")
    return p


def test_probe_reader_parses_int_value(tmp_probe: Path):
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    events = r.events_for_slot(3, 1)
    assert len(events) == 1
    _ts, val = events[0]
    assert val == 80


def test_probe_reader_parses_dict_value(tmp_probe: Path):
    """s2p56 value is a dict {"status": [[task_type, sub_state]]}.
    The reader should expose the raw value; downstream callers decode."""
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    events = r.events_for_slot(2, 56)
    assert len(events) == 1
    _ts, val = events[0]
    assert val == {"status": [[1, 0]]}


def test_probe_reader_skips_non_properties_changed(tmp_probe: Path):
    """`pretty` and other types are ignored."""
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    # No event for slot (1, 1) since the only s1p1 mention is in pretty.
    assert r.events_for_slot(1, 1) == []


def test_probe_reader_filters_by_window(tmp_probe: Path):
    import datetime as dt
    r = ProbeReader([str(tmp_probe)], tz=zoneinfo.ZoneInfo("UTC"))
    # Window that excludes the only event for s3p1
    events = r.events_for_slot(3, 1, start_ts=0, end_ts=10)
    assert events == []
    # Window that includes it (timestamp 2026-05-15 08:00:00 UTC)
    ts_in = int(dt.datetime(2026, 5, 15, 8, 0, tzinfo=zoneinfo.ZoneInfo("UTC")).timestamp())
    events = r.events_for_slot(3, 1, start_ts=ts_in - 60, end_ts=ts_in + 60)
    assert len(events) == 1
