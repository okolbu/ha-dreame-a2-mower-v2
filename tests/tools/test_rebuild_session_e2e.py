"""Smoke test: rebuild a session against synthetic probe + archive."""
from __future__ import annotations

import datetime as dt
import json
import zoneinfo
from pathlib import Path

from tools._rebuild_session_lib.probe_reader import ProbeReader
from tools.rebuild_session import rebuild_one_session


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
