"""Battery-delta charging inference.

s3p2 (charging) only fires on change, so a mid-charge integration
reload leaves snapshot.charging at whatever was persisted before —
often None / False because the mower wasn't charging when the state
machine was first initialised. The mower's battery monotonically
rising is a hard piece of evidence that it IS charging, so use it as
a fallback signal.

Rule: when battery_percent rises between two pushes, set
charging=True. Falling battery doesn't flip charging back to False
(could be brief discharge / load spike). Location going ON_LAWN does
clear charging (mower clearly off the dock).
"""
from __future__ import annotations


def test_rising_battery_infers_charging_true():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    assert sm.snapshot().charging is False  # initial
    sm.handle_mqtt_property(siid=3, piid=1, value=30, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=31, now_unix=1060)
    assert sm.snapshot().charging is True


def test_falling_battery_does_not_clear_charging():
    """Once charging, a brief battery drop (load spike) shouldn't flip
    charging back to False."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=30, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=35, now_unix=2000)
    assert sm.snapshot().charging is True
    sm.handle_mqtt_property(siid=3, piid=1, value=34, now_unix=2100)
    assert sm.snapshot().charging is True


def test_first_battery_observation_does_not_infer():
    """A single battery reading is not enough — we need TWO points to
    compute a delta. The first push just stamps the value."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=30, now_unix=1000)
    assert sm.snapshot().charging is False


def test_battery_rise_inference_forces_location_at_dock():
    """The only charging surface is the dock, so charging=True must
    imply location=AT_DOCK. Without this, the dashboard shows the
    impossible combination 'In dock=off' + 'Charging=charging'."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, MowSession,
    )
    import dataclasses
    sm = MowerStateMachine()
    # Simulate the stuck-state: IN_SESSION + ON_LAWN + battery rising
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        location=Location.ON_LAWN,
    )
    sm.handle_mqtt_property(siid=3, piid=1, value=30, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=31, now_unix=1060)
    snap = sm.snapshot()
    assert snap.charging is True
    # And location must have flipped to AT_DOCK
    assert snap.location == Location.AT_DOCK


def test_explicit_s3p2_true_forces_location_at_dock():
    """Same invariant via the s3p2 path."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, MowSession,
    )
    import dataclasses
    sm = MowerStateMachine()
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        location=Location.ON_LAWN,
    )
    sm.handle_mqtt_property(siid=3, piid=2, value=1, now_unix=1000)
    snap = sm.snapshot()
    assert snap.charging is True
    assert snap.location == Location.AT_DOCK


def test_explicit_s3p2_false_overrides_inference():
    """If firmware explicitly pushes s3p2=0 (not charging), that wins
    even if a subsequent battery rise looks like charging — the
    firmware signal is authoritative."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=30, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=31, now_unix=1060)
    assert sm.snapshot().charging is True
    sm.handle_mqtt_property(siid=3, piid=2, value=0, now_unix=1100)
    assert sm.snapshot().charging is False
