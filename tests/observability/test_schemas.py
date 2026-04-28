"""Tests for schema-validator drift detection."""

from __future__ import annotations

from custom_components.dreame_a2_mower.observability.schemas import (
    SCHEMA_SESSION_SUMMARY,
    SchemaCheck,
)


def test_known_keys_yield_no_diff():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"start": "2026-01-01", "time": 600, "map": []}  # all in schema
    extra = check.diff_keys(payload)
    assert extra == []


def test_unknown_key_at_top_level():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"start": "ts", "weird_field": "x"}
    extra = check.diff_keys(payload)
    assert extra == ["weird_field"]


def test_unknown_keys_nested_in_list_of_dicts():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"map": [{"track": [], "rogue": True}]}
    extra = check.diff_keys(payload)
    assert "map[].rogue" in extra


def test_empty_payload_no_diff():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    assert check.diff_keys({}) == []


def test_payload_missing_keys_is_not_a_diff():
    """diff_keys reports unknown keys present in payload, not missing
    ones — a partial payload is normal (e.g. session with no obstacles)."""
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    extra = check.diff_keys({"start": "2026-01-01"})
    assert extra == []


def test_diff_keys_returns_sorted_list():
    """Sorted output keeps log lines deterministic."""
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"zzz_extra": 1, "aaa_extra": 2, "start": "ts"}
    extra = check.diff_keys(payload)
    assert extra == ["aaa_extra", "zzz_extra"]


def test_non_dict_payload_returns_empty():
    """A payload that's not a dict at the top level can't be diffed —
    return empty rather than raise."""
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    assert check.diff_keys([]) == []
    assert check.diff_keys("string") == []
