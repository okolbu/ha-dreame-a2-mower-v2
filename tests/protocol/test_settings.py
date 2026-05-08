"""Tests for SETTINGS decoder + read-modify-write helper."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.protocol.settings import (
    parse_settings_batch,
    write_setting,
)

FIXTURE = Path(__file__).parent / "fixtures" / "2026-05-08-settings-sample.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_parse_extracts_canonical_per_map():
    """Entry 0 of SETTINGS is canonical: by_map_id_canonical[i] = entry0.settings[str(i)]."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert set(result.by_map_id_canonical.keys()) == {0, 1}
    assert result.by_map_id_canonical[0]["mowingDirection"] == 0
    assert result.by_map_id_canonical[1]["mowingDirection"] == 180


def test_parse_preserves_full_raw():
    """The full list (both top-level entries) is preserved verbatim."""
    raw = _load()
    result = parse_settings_batch(raw)
    assert result.raw == raw
    assert len(result.raw) == 2


def test_write_setting_modifies_both_entries_for_target_map():
    """Writes propagate to BOTH entries' map_id sub-dicts.

    Initially we only wrote entry 0, but live testing 2026-05-09 showed
    the firmware/app reads from entry 1 — toggles never appeared in the
    app even though entry 0 was correctly mutated. Mutating both entries
    is required for the write to take effect.
    """
    raw = _load()
    new_raw = write_setting(raw, map_id=0, field="mowingHeight", value=7)
    # Both entries' map 0 mutated.
    assert new_raw[0]["settings"]["0"]["mowingHeight"] == 7
    assert new_raw[1]["settings"]["0"]["mowingHeight"] == 7
    # Other map's value preserved on both entries.
    assert new_raw[0]["settings"]["1"]["mowingHeight"] == raw[0]["settings"]["1"]["mowingHeight"]
    assert new_raw[1]["settings"]["1"]["mowingHeight"] == raw[1]["settings"]["1"]["mowingHeight"]


def test_write_setting_unknown_map_id_raises():
    raw = _load()
    try:
        write_setting(raw, map_id=99, field="mowingHeight", value=7)
    except KeyError as ex:
        assert "99" in str(ex)
    else:
        raise AssertionError("write_setting should raise KeyError on unknown map_id")


def test_write_setting_returns_new_object():
    """write_setting is non-mutating: returns a new list, leaves input alone."""
    raw = _load()
    original_height = raw[0]["settings"]["0"]["mowingHeight"]
    new_raw = write_setting(raw, map_id=0, field="mowingHeight", value=7)
    assert raw[0]["settings"]["0"]["mowingHeight"] == original_height
    assert new_raw is not raw


def test_parse_handles_missing_settings_key():
    """If entry 0 has no `settings` dict, by_map_id_canonical is empty (defensive)."""
    result = parse_settings_batch([{"mode": 0}])
    assert result.by_map_id_canonical == {}


def test_parse_handles_empty_list():
    result = parse_settings_batch([])
    assert result.raw == []
    assert result.by_map_id_canonical == {}
