"""Tests for tools/backfill_wifi_samples.py — probe-log replay helpers."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def backfill_module():
    """Load tools/backfill_wifi_samples.py as a module without going
    through the protocol package's __init__ (which pulls in HA)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "backfill_wifi_samples.py"
    )
    spec = importlib.util.spec_from_file_location("_bf_test_module", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bf_test_module"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_property_pushes_modern_shape(backfill_module):
    entry = {
        "type": "mqtt_message",
        "method": "properties_changed",
        "params": [{"siid": 1, "piid": 1, "value": [1, 2, 3]}],
    }
    out = backfill_module._extract_property_pushes(entry)
    assert out == [{"siid": 1, "piid": 1, "value": [1, 2, 3]}]


def test_extract_property_pushes_nested_parsed_data(backfill_module):
    entry = {
        "type": "mqtt_message",
        "method": "properties_changed",
        "parsed_data": {
            "params": [{"siid": 1, "piid": 4, "value": [9, 8, 7]}],
        },
    }
    out = backfill_module._extract_property_pushes(entry)
    assert out == [{"siid": 1, "piid": 4, "value": [9, 8, 7]}]


def test_extract_property_pushes_filters_non_mqtt(backfill_module):
    entry = {"type": "pretty", "text": "hello"}
    assert backfill_module._extract_property_pushes(entry) == []


def test_parse_unix_ts_iso_local(backfill_module):
    # Naive ISO string — host-local; result must be a positive unix int.
    ts = backfill_module._parse_unix_ts({"timestamp": "2026-05-13 12:00:00"})
    assert isinstance(ts, int)
    assert ts > 1_700_000_000


def test_parse_unix_ts_garbage(backfill_module):
    assert backfill_module._parse_unix_ts({"timestamp": "not-a-date"}) is None
    assert backfill_module._parse_unix_ts({}) is None


def test_bytes_from_value_list(backfill_module):
    assert backfill_module._bytes_from_value([0xCE, 0x00]) == bytes([0xCE, 0x00])


def test_bytes_from_value_garbage(backfill_module):
    assert backfill_module._bytes_from_value(None) is None
    assert backfill_module._bytes_from_value({"weird": True}) is None


def test_bucket_samples_groups_by_session(backfill_module):
    Sample = backfill_module._Sample
    sessions = [
        {"filename": "a.json", "start_ts": 1000, "end_ts": 2000},
        {"filename": "b.json", "start_ts": 2500, "end_ts": 3500},
    ]
    samples = [
        Sample(1.0, 2.0, -55, 1500),  # falls into a
        Sample(3.0, 4.0, -60, 2200),  # outside both
        Sample(5.0, 6.0, -70, 2800),  # falls into b
        Sample(7.0, 8.0, -65, 3200),  # falls into b
    ]
    out = backfill_module._bucket_samples_by_session(samples, sessions)
    assert set(out.keys()) == {"a.json", "b.json"}
    assert len(out["a.json"]) == 1
    assert len(out["b.json"]) == 2


def test_merge_samples_overwrite_mode(backfill_module):
    Sample = backfill_module._Sample
    existing = [[0.0, 0.0, -50, 1000]]
    new = [Sample(1.0, 1.0, -55, 2000)]
    result, added = backfill_module._merge_samples(existing, new, merge_mode=False)
    assert added == 1
    assert result == [[1.0, 1.0, -55, 2000]]


def test_merge_samples_merge_mode_dedups_by_ts(backfill_module):
    Sample = backfill_module._Sample
    existing = [[0.0, 0.0, -50, 1000]]
    new = [
        Sample(0.0, 0.0, -50, 1000),  # same ts — skip
        Sample(2.0, 2.0, -60, 2000),  # new ts — add
    ]
    result, added = backfill_module._merge_samples(existing, new, merge_mode=True)
    assert added == 1
    assert len(result) == 2
    # Sorted by ts.
    assert result[0][3] == 1000
    assert result[1][3] == 2000


def test_end_to_end_smoke(tmp_path: Path, backfill_module):
    """Build a tiny probe log + sessions tree and verify the tool
    writes wifi_samples into the matching blob."""
    # ── synthesised probe events ─────────────────────────────────────
    # s1p4 33-byte frame: [0xCE, 20-bit packed pose (x=10 → x_mm=100 → 0.1m), …, 0xCE]
    # Use the canonical hex we know decodes: bytes(33) with 0xCE delimiters.
    # Easier: encode in-place by calling the live encoder API isn't available,
    # so write a minimal but valid s1p4 33-byte frame.
    from custom_components.dreame_a2_mower.protocol import telemetry as t
    from custom_components.dreame_a2_mower.protocol import heartbeat as hb

    # Build a 33-byte zero-filled frame with 0xCE delimiters; pose decode
    # returns (0, 0) — that's fine for the test.
    frame_s1p4 = bytearray(t.FRAME_LENGTH)
    frame_s1p4[0] = 0xCE
    frame_s1p4[-1] = 0xCE
    # Build an s1p1 20-byte heartbeat with RSSI = -70 at byte[17]
    # (which is the signed-byte 0xBA = -70 = 256 - 70 = 186).
    frame_s1p1 = bytearray(hb.FRAME_LENGTH)
    frame_s1p1[0] = 0xCE
    frame_s1p1[-1] = 0xCE
    frame_s1p1[17] = 186  # -70 dBm

    probe_path = tmp_path / "probe_log_x.jsonl"
    with probe_path.open("w") as f:
        # First an s1p4 frame to seed position
        f.write(json.dumps({
            "type": "mqtt_message",
            "method": "properties_changed",
            "timestamp": "2026-05-13 12:00:00",
            "params": [{"siid": 1, "piid": 4, "value": list(frame_s1p4)}],
        }) + "\n")
        # Then an s1p1 frame — should generate one sample
        f.write(json.dumps({
            "type": "mqtt_message",
            "method": "properties_changed",
            "timestamp": "2026-05-13 12:00:30",
            "params": [{"siid": 1, "piid": 1, "value": list(frame_s1p1)}],
        }) + "\n")

    # ── synthesised sessions tree ────────────────────────────────────
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    from datetime import datetime, timezone
    ts_noon = int(datetime(2026, 5, 13, 12, 0, 0).astimezone().timestamp())
    sessions_index = {
        "sessions": [
            {
                "filename": "session_x.json",
                "start_ts": ts_noon - 60,
                "end_ts": ts_noon + 3600,
                "duration_min": 60,
                "area_mowed_m2": 0,
                "map_area_m2": 0,
                "md5": "x",
            }
        ]
    }
    (sessions_dir / "index.json").write_text(json.dumps(sessions_index))
    (sessions_dir / "session_x.json").write_text(json.dumps({"md5": "x"}))

    # Run the tool in real mode (not dry-run).
    rc = backfill_module.main([
        "--probe-glob", str(tmp_path / "probe_log_*.jsonl"),
        "--sessions-dir", str(sessions_dir),
        "--log-level", "WARNING",
    ])
    assert rc == 0

    blob = json.loads((sessions_dir / "session_x.json").read_text())
    samples = blob.get("wifi_samples")
    assert isinstance(samples, list)
    assert len(samples) == 1
    x, y, rssi, ts = samples[0]
    assert rssi == -70
    # ts should fall inside the session window.
    assert sessions_index["sessions"][0]["start_ts"] <= ts <= sessions_index["sessions"][0]["end_ts"]


def test_idempotent_second_run(tmp_path: Path, backfill_module):
    """Running the tool twice doesn't duplicate samples."""
    from custom_components.dreame_a2_mower.protocol import telemetry as t
    from custom_components.dreame_a2_mower.protocol import heartbeat as hb
    frame_s1p4 = bytearray(t.FRAME_LENGTH)
    frame_s1p4[0] = 0xCE
    frame_s1p4[-1] = 0xCE
    frame_s1p1 = bytearray(hb.FRAME_LENGTH)
    frame_s1p1[0] = 0xCE
    frame_s1p1[-1] = 0xCE
    frame_s1p1[17] = 186

    probe_path = tmp_path / "probe_log_x.jsonl"
    with probe_path.open("w") as f:
        f.write(json.dumps({
            "type": "mqtt_message",
            "method": "properties_changed",
            "timestamp": "2026-05-13 12:00:00",
            "params": [{"siid": 1, "piid": 4, "value": list(frame_s1p4)}],
        }) + "\n")
        f.write(json.dumps({
            "type": "mqtt_message",
            "method": "properties_changed",
            "timestamp": "2026-05-13 12:00:30",
            "params": [{"siid": 1, "piid": 1, "value": list(frame_s1p1)}],
        }) + "\n")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    from datetime import datetime
    ts_noon = int(datetime(2026, 5, 13, 12, 0, 0).astimezone().timestamp())
    sessions_index = {
        "sessions": [
            {
                "filename": "session_x.json",
                "start_ts": ts_noon - 60,
                "end_ts": ts_noon + 3600,
                "duration_min": 60,
                "area_mowed_m2": 0,
                "map_area_m2": 0,
                "md5": "x",
            }
        ]
    }
    (sessions_dir / "index.json").write_text(json.dumps(sessions_index))
    (sessions_dir / "session_x.json").write_text(json.dumps({"md5": "x"}))

    backfill_module.main([
        "--probe-glob", str(tmp_path / "probe_log_*.jsonl"),
        "--sessions-dir", str(sessions_dir),
        "--log-level", "WARNING",
    ])
    blob_first = json.loads((sessions_dir / "session_x.json").read_text())
    # Second run — should be a no-op.
    backfill_module.main([
        "--probe-glob", str(tmp_path / "probe_log_*.jsonl"),
        "--sessions-dir", str(sessions_dir),
        "--log-level", "WARNING",
    ])
    blob_second = json.loads((sessions_dir / "session_x.json").read_text())
    assert blob_first["wifi_samples"] == blob_second["wifi_samples"]
