"""handle_mqtt_property — scalar slots (s3p1, s3p2) + freshness."""
from __future__ import annotations


def test_handle_s3p1_updates_battery():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1700000000)
    assert snap.battery_percent == 87
    assert snap.field_freshness["battery_percent"] == 1700000000


def test_handle_s3p2_updates_charging():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=3, piid=2, value=1, now_unix=1700000000)
    assert snap.charging is True
    snap = sm.handle_mqtt_property(siid=3, piid=2, value=0, now_unix=1700000001)
    assert snap.charging is False


def test_handle_unknown_slot_does_not_raise_and_logs_novel():
    """Unknown (siid, piid) returns snapshot unchanged, no exception."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    before = sm.snapshot()
    snap = sm.handle_mqtt_property(siid=99, piid=99, value="x", now_unix=0)
    assert snap == before


def test_freshness_only_updates_when_value_changes():
    """Re-applying the same value does NOT bump the freshness timestamp."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=2000)
    # Same value → no freshness bump, still 1000
    assert sm.snapshot().field_freshness["battery_percent"] == 1000


def test_freshness_bumps_on_value_change():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=80, now_unix=2000)
    assert sm.snapshot().field_freshness["battery_percent"] == 2000
