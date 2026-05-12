"""Tests for the StateSnapshot dataclass + dimension enums."""
from __future__ import annotations

import pytest


def test_dimension_enums_have_expected_values():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity, Location, PositioningHealth,
        Connectivity, RpcHealth,
    )
    assert {e.name for e in MowSession} == {"IN_SESSION", "BETWEEN_SESSIONS"}
    assert {e.name for e in CurrentActivity} == {
        "MOWING", "PAUSED", "REPOSITIONING", "RETURNING",
        "CHARGE_RESUME", "CRUISING_TO_POINT", "AT_POINT",
        "FAST_MAPPING", "DRIVING_BLADES_UP", "IDLE",
    }
    assert {e.name for e in Location} == {
        "AT_DOCK", "ON_LAWN", "AT_POINT", "OUTSIDE_KNOWN_AREA",
    }
    assert {e.name for e in PositioningHealth} == {
        "LOCALIZED", "RELOCATING", "STUCK",
    }
    assert {e.name for e in Connectivity} == {"ONLINE", "STALE"}
    assert {e.name for e in RpcHealth} == {"OK", "FAILING"}


def test_state_snapshot_is_frozen():
    from dataclasses import FrozenInstanceError
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    s = StateSnapshot.initial()
    with pytest.raises(FrozenInstanceError):
        s.charging = True  # type: ignore[misc]


def test_state_snapshot_initial_has_safe_defaults():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, MowSession, CurrentActivity, Location,
        Connectivity, RpcHealth, PositioningHealth,
    )
    s = StateSnapshot.initial()
    assert s.mow_session == MowSession.BETWEEN_SESSIONS
    assert s.current_activity == CurrentActivity.IDLE
    assert s.location == Location.AT_DOCK  # safest pre-data default
    assert s.positioning_health == PositioningHealth.LOCALIZED
    assert s.mqtt_connectivity == Connectivity.STALE  # no HB yet
    assert s.cloud_rpc_health == RpcHealth.OK
    assert s.charging is False
    assert s.errors == frozenset()
    assert s.pin_required is False
    assert s.field_freshness == {}
    assert s.last_heartbeat_unix is None
    assert s.battery_percent is None


def test_state_snapshot_serialise_roundtrip():
    """Snapshot serialises to JSON-able dict and restores cleanly."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, CurrentActivity, Location,
    )
    s = StateSnapshot.initial()
    import dataclasses
    s2 = dataclasses.replace(
        s,
        current_activity=CurrentActivity.MOWING,
        location=Location.ON_LAWN,
        battery_percent=87,
        field_freshness={"battery_percent": 1700000000},
    )
    raw = s2.to_dict()
    restored = StateSnapshot.from_dict(raw)
    assert restored == s2
