"""Tests for the per-field freshness tracker."""

from __future__ import annotations

from dataclasses import dataclass

from custom_components.dreame_a2_mower.observability.freshness import FreshnessTracker


@dataclass
class _Probe:
    a: int | None = None
    b: int | None = None


def test_record_marks_fields_that_changed():
    tracker = FreshnessTracker()
    old = _Probe(a=None, b=None)
    new = _Probe(a=5, b=None)
    tracker.record(old, new, now_unix=1700000000)
    assert tracker.last_updated("a") == 1700000000
    assert tracker.last_updated("b") is None


def test_record_does_not_overwrite_unchanged_fields():
    tracker = FreshnessTracker()
    tracker.record(_Probe(a=None), _Probe(a=5), now_unix=1700000000)
    tracker.record(_Probe(a=5), _Probe(a=5, b=9), now_unix=1700000005)
    assert tracker.last_updated("a") == 1700000000  # unchanged → stamp stays
    assert tracker.last_updated("b") == 1700000005  # changed None→9


def test_age_seconds_returns_none_for_never_updated():
    tracker = FreshnessTracker()
    assert tracker.age_seconds("a", now_unix=1700000000) is None


def test_age_seconds_computes_delta():
    tracker = FreshnessTracker()
    tracker.record(_Probe(a=None), _Probe(a=5), now_unix=1700000000)
    assert tracker.age_seconds("a", now_unix=1700000005) == 5


def test_record_handles_none_old_state_gracefully():
    """When the coordinator boots, ``self.data`` may be None before the
    first state propagation. Don't crash."""
    tracker = FreshnessTracker()
    tracker.record(None, _Probe(a=5), now_unix=1700000000)
    # Nothing recorded — we have no baseline to compare against.
    assert tracker.last_updated("a") is None


def test_snapshot_returns_independent_copy():
    """snapshot() returns a dict the caller can mutate without affecting
    the tracker."""
    tracker = FreshnessTracker()
    tracker.record(_Probe(a=None), _Probe(a=5), now_unix=1700000000)
    snap = tracker.snapshot()
    snap["a"] = 9999
    assert tracker.last_updated("a") == 1700000000
