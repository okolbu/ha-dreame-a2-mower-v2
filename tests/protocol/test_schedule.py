"""Tests for SCHEDULE header decoder (blob decode deferred)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.schedule import (
    parse_schedule_batch,
)


def test_parse_real_shape():
    """Verified shape (2026-05-08, g2408 fw 4.3.6_0550):
        {"d": [[id, ?, name, blob_b64], ...], "v": version}
    """
    raw = {
        "d": [
            [0, 0, "Spr & Sum Schedule", "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="],
            [1, 0, "", "qgcQHAIA7aoHQBwCAO0="],
        ],
        "v": 657,
    }
    result = parse_schedule_batch(raw)
    assert result.version == 657
    assert len(result.slots) == 2
    assert result.slots[0].slot_id == 0
    assert result.slots[0].name == "Spr & Sum Schedule"
    assert result.slots[0].raw_blob_b64 == "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqgdQ4AEA7Q=="
    assert result.slots[1].slot_id == 1
    assert result.slots[1].name == ""


def test_parse_empty_returns_empty_slots():
    result = parse_schedule_batch({"d": [], "v": 0})
    assert result.version == 0
    assert result.slots == ()


def test_parse_html_escape_in_name_decoded():
    """Cloud emits `&amp;`; decoder unescapes to `&`."""
    raw = {"d": [[0, 0, "A &amp; B", ""]], "v": 1}
    result = parse_schedule_batch(raw)
    assert result.slots[0].name == "A & B"


def test_parse_invalid_input_returns_empty():
    """Defensive: non-dict input → empty result, not crash."""
    assert parse_schedule_batch(None).slots == ()
    assert parse_schedule_batch([]).slots == ()
    assert parse_schedule_batch({}).slots == ()


def test_parse_skips_malformed_slot_entries():
    raw = {"d": [[0, 0, "Good", "blob"], "not-a-list", [1]], "v": 1}
    result = parse_schedule_batch(raw)
    assert len(result.slots) == 1  # only the well-formed entry
    assert result.slots[0].slot_id == 0
