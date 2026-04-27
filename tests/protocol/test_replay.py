"""Tests for the probe-log replay iterator."""

from __future__ import annotations

from pathlib import Path

import pytest

from protocol.config_s2p51 import decode_s2p51
from protocol.heartbeat import decode_s1p1
from protocol.properties_g2408 import (
    Property,
    property_for,
    state_label,
)
from protocol.replay import (
    ProbeLogEvent,
    iter_probe_log,
)
from protocol.telemetry import decode_s1p4


def test_iter_probe_log_yields_mqtt_messages_only(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    assert events, "expected at least one event from the trimmed fixture"
    assert all(isinstance(e, ProbeLogEvent) for e in events)
    assert all(e.method == "properties_changed" for e in events)


def test_iter_probe_log_parses_siid_piid_value(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    # First mqtt_message in the short fixture is s3p1 BATTERY_LEVEL = 59.
    first = events[0]
    assert (first.siid, first.piid) == (3, 1)
    assert first.value == 59
    assert first.timestamp == "2026-04-17 11:33:14"


def test_iter_probe_log_captures_list_value_for_telemetry_blob(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    blobs = [e for e in events if (e.siid, e.piid) == (1, 1)]
    assert blobs, "expected at least one s1p1 heartbeat blob"
    assert isinstance(blobs[0].value, list)
    assert len(blobs[0].value) == 20


def test_iter_probe_log_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(iter_probe_log(tmp_path / "does_not_exist.jsonl"))


def test_replay_full_session_routes_to_correct_decoder_without_errors(
    fixtures_dir: Path,
):
    """Drive every event in the short session through the decoder pipeline.

    Expectations:
      - Every known (siid, piid) routes to a decoder that accepts the payload.
      - Battery values are monotonically non-decreasing during a charging window.
      - Heartbeat counter is present and decodable (it's a 16-bit counter that wraps).
      - No unhandled exception from any decoder.
    """
    batteries: list[int] = []
    heartbeat_counters: list[int] = []

    for ev in iter_probe_log(fixtures_dir / "session_short.jsonl"):
        prop = property_for(ev.siid, ev.piid)

        if prop is Property.BATTERY_LEVEL:
            assert isinstance(ev.value, int)
            batteries.append(ev.value)
        elif prop is Property.STATE:
            assert isinstance(ev.value, int)
            label = state_label(ev.value)
            assert not label.startswith("unknown_"), (
                f"unrecognised STATE code {ev.value} at {ev.timestamp}: {label}"
            )
        elif prop is Property.HEARTBEAT:
            hb = decode_s1p1(bytes(ev.value))
            heartbeat_counters.append(hb.counter)
        elif prop is Property.MOWING_TELEMETRY:
            # Telemetry only appears while mowing; the short fixture may not
            # include it, but if present it must decode without error.
            decode_s1p4(bytes(ev.value))
        elif prop is Property.MULTIPLEXED_CONFIG:
            decode_s2p51(ev.value)
        # unknown (siid, piid) — acceptable for now; Plan C will map more.

    # The short fixture covers a charging window — battery should be non-decreasing.
    assert batteries == sorted(batteries), (
        f"battery not non-decreasing in short fixture window: {batteries}"
    )
    # Heartbeat counter is a 16-bit value that wraps; just ensure we decoded some.
    assert len(heartbeat_counters) > 1, (
        "expected multiple heartbeats in short fixture"
    )
    # Verify all heartbeat counters are valid 16-bit unsigned integers.
    assert all(0 <= c < 65536 for c in heartbeat_counters), (
        f"heartbeat counter out of range: {heartbeat_counters}"
    )
    assert len(batteries) > 1, "expected multiple battery readings in short fixture"
