"""charging_started / charging_complete fire on s3.2 rising edges."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state import ChargingStatus


class _FakeLifecycle:
    def __init__(self):
        self.fired = []
    def trigger(self, event_type, data):
        self.fired.append((event_type, data))


def _coord():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c._prev_charging_status = None
    lc = _FakeLifecycle()
    c._lifecycle_event = lc
    c._notification_event = None
    return c, lc


def test_charging_started_fires_on_edge_into_charging():
    c, lc = _coord()
    c._maybe_fire_charging_events(ChargingStatus.NOT_CHARGING, now_unix=100, battery=50)
    assert lc.fired == []  # first observation only primes _prev
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=200, battery=55)
    assert lc.fired == [("charging_started", {"at_unix": 200, "battery_level": 55})]


def test_charging_complete_fires_on_edge_into_charged():
    c, lc = _coord()
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=100, battery=90)
    lc.fired.clear()
    c._maybe_fire_charging_events(ChargingStatus.CHARGED, now_unix=300, battery=100)
    assert lc.fired == [("charging_complete", {"at_unix": 300, "battery_level": 100})]


def test_no_refire_on_same_status():
    c, lc = _coord()
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=100, battery=90)
    lc.fired.clear()
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=110, battery=91)
    assert lc.fired == []


def test_none_status_is_noop():
    c, lc = _coord()
    c._maybe_fire_charging_events(None, now_unix=100, battery=50)
    assert lc.fired == []
    assert c._prev_charging_status is None
