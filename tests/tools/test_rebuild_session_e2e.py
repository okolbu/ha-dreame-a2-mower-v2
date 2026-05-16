"""Smoke test: rebuild a session against synthetic probe + archive."""
from __future__ import annotations

import datetime as dt
import json
import zoneinfo
from pathlib import Path

from tools._rebuild_session_lib.probe_reader import ProbeReader
from tools.rebuild_session import _diff_and_merge_samples, rebuild_one_session


def _write_synthetic_probe(path: Path):
    """Tiny probe log: one battery sample + one state transition."""
    lines = [
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:00",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 3, "piid": 1, "value": 80}],
            }},
        }),
        json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-15 08:00:01",
            "payload": {"data": {
                "method": "properties_changed",
                "params": [{"siid": 2, "piid": 1, "value": 1}],
            }},
        }),
    ]
    path.write_text("\n".join(lines) + "\n")


def test_rebuild_one_session_adds_to_empty_archive(tmp_path: Path):
    probe_path = tmp_path / "probe.jsonl"
    _write_synthetic_probe(probe_path)
    reader = ProbeReader([str(probe_path)], tz=zoneinfo.ZoneInfo("UTC"))

    start = int(dt.datetime(2026, 5, 15, 7, 0, tzinfo=zoneinfo.ZoneInfo("UTC")).timestamp())
    end = int(dt.datetime(2026, 5, 15, 9, 0, tzinfo=zoneinfo.ZoneInfo("UTC")).timestamp())

    archive = {
        "start": start,
        "end": end,
        "battery_samples": [],
        "state_samples": [],
        "wifi_samples": [],
        "legs": [],
    }
    new_archive, diff = rebuild_one_session(reader, archive)
    assert len(new_archive["battery_samples"]) >= 1
    assert len(new_archive["state_samples"]) >= 1
    # diff structure
    assert diff["battery_samples"]["added"] >= 1


def test_diff_and_merge_samples_default_sort_by_index_0():
    """Sample arrays [ts, val]: s[0] is the timestamp."""
    archive = [[100, 80], [300, 78]]
    probe   = [[200, 79], [400, 77]]
    _, union = _diff_and_merge_samples(archive, probe)
    assert [s[0] for s in union] == [100, 200, 300, 400]


def test_diff_and_merge_samples_wifi_sorts_by_ts_index_3():
    """WiFi samples [x, y, rssi, ts]: s[3] is the timestamp.
    Regression: pre-fix tool sorted by s[0] (X coordinate)
    producing scrambled timelines in the dashboard chart.
    """
    # X coords DECREASING while timestamps INCREASING — this exposes
    # the wrong-index bug: sorting by s[0] would put ts=400 first.
    archive = [
        [8.0, 1.0, -70, 100],
        [5.0, 1.0, -71, 300],
    ]
    probe = [
        [6.0, 1.0, -68, 200],
        [1.0, 1.0, -72, 400],
    ]
    _, union = _diff_and_merge_samples(archive, probe, ts_index=3)
    assert [s[3] for s in union] == [100, 200, 300, 400]
