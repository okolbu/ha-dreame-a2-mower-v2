"""Tests for the novel-observation registry."""

from __future__ import annotations

from custom_components.dreame_a2_mower.observability.registry import (
    NovelObservation,
    NovelObservationRegistry,
)


def test_registry_starts_empty():
    reg = NovelObservationRegistry()
    snap = reg.snapshot()
    assert snap.count == 0
    assert snap.observations == []


def test_record_property_adds_observation():
    reg = NovelObservationRegistry()
    fired = reg.record_property(siid=99, piid=42, now_unix=1700000000)
    assert fired is True
    snap = reg.snapshot()
    assert snap.count == 1
    obs = snap.observations[0]
    assert obs.category == "property"
    assert obs.detail == "siid=99 piid=42"
    assert obs.first_seen_unix == 1700000000


def test_record_property_dedupes():
    reg = NovelObservationRegistry()
    assert reg.record_property(siid=99, piid=42, now_unix=1700000000) is True
    assert reg.record_property(siid=99, piid=42, now_unix=1700000005) is False
    assert reg.snapshot().count == 1


def test_record_value_for_known_property():
    reg = NovelObservationRegistry()
    fired = reg.record_value(siid=2, piid=2, value=99, now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "value"
    assert "siid=2 piid=2" in obs.detail
    assert "value=99" in obs.detail


def test_record_key_uses_namespace():
    reg = NovelObservationRegistry()
    fired = reg.record_key(namespace="session_summary", key="weird_field", now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "key"
    assert obs.detail == "session_summary.weird_field"


def test_observations_sorted_oldest_first():
    reg = NovelObservationRegistry()
    reg.record_property(siid=1, piid=1, now_unix=1700000010)
    reg.record_property(siid=2, piid=2, now_unix=1700000005)
    reg.record_property(siid=3, piid=3, now_unix=1700000020)
    seen = [o.first_seen_unix for o in reg.snapshot().observations]
    # Insertion order, NOT sorted-by-time. Matches "first sighting" semantics.
    assert seen == [1700000010, 1700000005, 1700000020]
