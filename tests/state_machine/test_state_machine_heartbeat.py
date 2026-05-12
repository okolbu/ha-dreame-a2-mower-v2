"""handle_heartbeat tests."""
from __future__ import annotations


def _make_hb(pin_required: bool = False, wifi_rssi: int = -60):
    """Build a Heartbeat from protocol/heartbeat.py."""
    from custom_components.dreame_a2_mower.protocol.heartbeat import Heartbeat
    return Heartbeat(
        counter=1, state_raw=0,
        battery_temp_low=False, drop_tilt=False, bumper=False, lift=False,
        emergency_stop=pin_required, safety_alert_active=False,
        wifi_rssi_dbm=wifi_rssi, raw=b"\x00" * 20,
    )


def test_handle_heartbeat_sets_connectivity_online():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Connectivity,
    )
    sm = MowerStateMachine()
    assert sm.snapshot().mqtt_connectivity == Connectivity.STALE  # pre-HB
    sm.handle_heartbeat(_make_hb(), now_unix=1000)
    snap = sm.snapshot()
    assert snap.mqtt_connectivity == Connectivity.ONLINE
    assert snap.last_heartbeat_unix == 1000


def test_handle_heartbeat_propagates_pin_required():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_heartbeat(_make_hb(pin_required=True), now_unix=1000)
    assert sm.snapshot().pin_required is True
    snap = sm.snapshot()
    assert snap.field_freshness["pin_required"] == 1000


def test_handle_heartbeat_propagates_wifi_rssi():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_heartbeat(_make_hb(wifi_rssi=-72), now_unix=1000)
    assert sm.snapshot().wifi_rssi_dbm == -72


def test_repeated_heartbeat_with_same_pin_does_not_bump_pin_freshness():
    """Idempotent: same pin_required value, freshness for pin_required not bumped."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_heartbeat(_make_hb(pin_required=True), now_unix=1000)
    sm.handle_heartbeat(_make_hb(pin_required=True), now_unix=2000)
    # last_heartbeat_unix bumps (always), but pin_required freshness stays at 1000
    snap = sm.snapshot()
    assert snap.last_heartbeat_unix == 2000
    assert snap.field_freshness["pin_required"] == 1000
