"""tick: HB staleness + buffered s2p2=71 disambiguation."""
from __future__ import annotations


def _make_hb():
    from custom_components.dreame_a2_mower.protocol.heartbeat import Heartbeat
    return Heartbeat(
        counter=1, state_raw=0, battery_temp_low=False, drop_tilt=False,
        bumper=False, lift=False, emergency_stop=False, safety_alert_active=False,
        wifi_rssi_dbm=-60, raw=b"\x00"*20,
    )


def test_tick_flips_connectivity_stale_after_90s_gap():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Connectivity,
    )
    sm = MowerStateMachine()
    sm.handle_heartbeat(_make_hb(), now_unix=1000)
    assert sm.snapshot().mqtt_connectivity == Connectivity.ONLINE
    sm.tick(now_unix=1085)  # 85s after HB — still online
    assert sm.snapshot().mqtt_connectivity == Connectivity.ONLINE
    sm.tick(now_unix=1095)  # 95s after HB — stale
    assert sm.snapshot().mqtt_connectivity == Connectivity.STALE


def test_s2p2_33_sets_positioning_stuck():
    """s2p2=33 (positioning / off-dock-relocate failure) sets STUCK directly.
    33 is the real positioning-failure signal (e.g. the 2026-05-25 12:32
    relocate-fail burst → s2p1=4 Paused), NOT a 71+31 combination."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth, Location,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=33, now_unix=1000)
    snap = sm.snapshot()
    assert snap.positioning_health == PositioningHealth.STUCK
    assert snap.location == Location.OUTSIDE_KNOWN_AREA


def test_positioning_stuck_clears_on_mowing_resume():
    """STUCK clears back to LOCALIZED when the mower resumes mowing (s2p1=1) —
    e.g. the 12:32 incident auto-resumed an hour later."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=33, now_unix=1000)
    assert sm.snapshot().positioning_health == PositioningHealth.STUCK
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=4600)  # resume mowing
    assert sm.snapshot().positioning_health == PositioningHealth.LOCALIZED


def test_s2p2_71_then_31_is_not_stuck():
    """71 (standby→returning) and 31 (failed-to-return) are orthogonal signals;
    neither is a positioning failure, so together they do NOT set STUCK. The old
    71+31→STUCK coupling (which never co-occurred in any probe log) is removed."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=71, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=2, value=31, now_unix=1010)
    sm.tick(now_unix=1032)
    assert sm.snapshot().positioning_health == PositioningHealth.LOCALIZED


def test_s2p2_71_is_returning_not_stuck():
    """s2p2=71 followed by s2p1=5 → RETURNING activity, positioning LOCALIZED."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=71, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1005)
    snap = sm.snapshot()
    assert snap.positioning_health == PositioningHealth.LOCALIZED
    assert snap.current_activity == CurrentActivity.RETURNING


def test_tick_no_op_when_nothing_to_resolve():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    before = sm.snapshot()
    snap = sm.tick(now_unix=1000)
    # No HB ever → no staleness transition (already STALE)
    # No buffered event → no resolution
    assert snap == before
