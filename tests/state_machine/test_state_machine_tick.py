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


def test_tick_resolves_buffered_s2p2_71_as_stuck():
    """s2p2=71 followed within 30s by s2p2=31 → STUCK_POSITIONING."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth, Location,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=71, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=2, value=31, now_unix=1010)
    sm.tick(now_unix=1032)  # 32s after buffer start — resolve
    snap = sm.snapshot()
    assert snap.positioning_health == PositioningHealth.STUCK
    assert snap.location == Location.OUTSIDE_KNOWN_AREA


def test_tick_resolves_buffered_s2p2_71_as_auto_return():
    """s2p2=71 followed by s2p1=5 (RETURNING) → auto-return, not stuck."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=71, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1005)
    sm.tick(now_unix=1032)
    snap = sm.snapshot()
    # NOT stuck — it's an auto-recovery
    assert snap.positioning_health == PositioningHealth.LOCALIZED
    assert snap.current_activity == CurrentActivity.RETURNING


def test_tick_unresolved_buffer_does_not_set_stuck():
    """If buffer expires without disambiguating signal, don't claim stuck."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=71, now_unix=1000)
    sm.tick(now_unix=1035)  # 35s, no follow-up
    snap = sm.snapshot()
    assert snap.positioning_health == PositioningHealth.LOCALIZED


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
