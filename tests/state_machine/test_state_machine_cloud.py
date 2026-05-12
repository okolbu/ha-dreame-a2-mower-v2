"""handle_cloud_poll — DOCK source + per-field freshness precedence."""
from __future__ import annotations


def test_cloud_dock_connect_status_sets_location_at_dock():
    """CFG.DOCK with connect_status=1 → location=AT_DOCK (no MQTT yet)."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    snap = sm.handle_cloud_poll(
        source="DOCK",
        payload={"connect_status": 1},
        now_unix=1000,
    )
    assert snap.location == Location.AT_DOCK
    assert snap.field_freshness["location"] == 1000


def test_cloud_dock_connect_status_zero_sets_on_lawn():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, StateSnapshot,
    )
    # Need to flip location off of AT_DOCK default first — otherwise the
    # cloud poll setting connect_status=0 would just leave it as default
    # initial (AT_DOCK). Use _replace via internal API or seed via MQTT.
    sm = MowerStateMachine()
    # The default is AT_DOCK; with connect_status=0 we want it ON_LAWN
    # Just confirm cloud poll DOES set it to ON_LAWN even from AT_DOCK.
    # (The location dimension transitions both ways.)
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"connect_status": 0}, now_unix=1000,
    )
    assert snap.location == Location.ON_LAWN


def test_cloud_poll_does_not_overwrite_fresher_mqtt():
    """Per-field precedence: MQTT-derived location at t=2000 must NOT be
    overwritten by a cloud poll at t=1000 — even with a different value."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    # MQTT-derived location update at t=2000 (s2p2=75 → AT_POINT)
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=2000)
    assert sm.snapshot().location == Location.AT_POINT
    # Cloud poll claims AT_DOCK with as_of t=1000 — must be ignored
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"connect_status": 1}, now_unix=1000,
    )
    assert snap.location == Location.AT_POINT  # MQTT wins


def test_cloud_poll_overwrites_when_fresher():
    """Cloud overwrites when as_of > field's last MQTT stamp."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=1000)
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"connect_status": 1}, now_unix=3000,
    )
    assert snap.location == Location.AT_DOCK


def test_cloud_poll_unknown_source_is_noop():
    """Unknown source name → snapshot unchanged."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    before = sm.snapshot()
    snap = sm.handle_cloud_poll(
        source="GARBAGE", payload={"x": 1}, now_unix=1000,
    )
    assert snap is before


def test_cloud_poll_missing_connect_status_is_noop():
    """DOCK without connect_status field → snapshot unchanged."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    before = sm.snapshot()
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"in_region": 1}, now_unix=1000,
    )
    assert snap is before
