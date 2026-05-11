"""Tests for the F13 s2p2 notification synthesizer.

Verifies that s2p2 (error_code) transitions fire dreame_a2_mower_alert
events via the coordinator's _fire_alert / _on_state_update path and
that sensor.last_notification reflects the most-recently emitted event.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import (
    S2P2_NOTIFICATION_MAP,
    apply_property_to_state,
    DreameA2MowerCoordinator,
)
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord() -> DreameA2MowerCoordinator:
    """Minimal coordinator stub wired for notification-synthesis assertions."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord._prev_error_code = None
    coord._last_notification = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._cached_maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    coord._lifecycle_event = MagicMock()
    coord._alert_event = MagicMock()
    return coord


# ---------------------------------------------------------------------------
# Core transition tests
# ---------------------------------------------------------------------------


def test_s2p2_transition_to_48_fires_mowing_complete():
    """s2p2 going 50 → 48 should fire the alert entity with mowing_complete."""
    coord = _make_coord()
    # Seed previous code (non-None so boot-suppression doesn't apply)
    coord._prev_error_code = 50
    coord.data = MowerState(error_code=50)

    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state, now_unix=1_748_000_000)

    coord._alert_event.trigger.assert_called_once()
    call_args = coord._alert_event.trigger.call_args
    event_type = call_args.args[0]
    event_data = call_args.args[1]
    assert event_type == "mowing_complete"
    assert event_data["code"] == 48
    assert event_data["source"] == "s2p2"
    assert "text" in event_data


def test_s2p2_same_value_does_not_re_fire():
    """Multiple pushes of the same s2p2 value emit only once."""
    coord = _make_coord()
    coord._prev_error_code = 50
    coord.data = MowerState(error_code=50)

    # First transition: 50 → 48 (should fire)
    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state, now_unix=1_748_000_001)
    coord.data = state
    # Second push: still 48 (should NOT fire again)
    state2 = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state2, now_unix=1_748_000_002)

    # trigger() should have been called exactly once
    assert coord._alert_event.trigger.call_count == 1


def test_s2p2_unknown_value_does_not_fire():
    """s2p2 value outside the map silently passes through; no event fires."""
    coord = _make_coord()
    coord._prev_error_code = 50  # non-None: boot-suppression off
    coord.data = MowerState(error_code=50)

    # 99 is not in S2P2_NOTIFICATION_MAP
    state = apply_property_to_state(coord.data, siid=2, piid=2, value=99)
    coord._on_state_update(state, now_unix=1_748_000_003)

    coord._alert_event.trigger.assert_not_called()


def test_s2p2_first_push_after_boot_does_not_fire():
    """When _prev_error_code is None (HA boot), the first s2p2 push must
    NOT fire a notification — there is no meaningful 'transition' yet."""
    coord = _make_coord()
    # _prev_error_code starts as None
    assert coord._prev_error_code is None

    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state, now_unix=1_748_000_004)

    coord._alert_event.trigger.assert_not_called()


def test_s2p2_prev_error_code_is_updated_after_any_push():
    """_prev_error_code tracks the latest observed error_code regardless
    of whether it was in the notification map."""
    coord = _make_coord()
    coord._prev_error_code = 50
    coord.data = MowerState(error_code=50)

    state = apply_property_to_state(coord.data, siid=2, piid=2, value=99)
    coord._on_state_update(state, now_unix=1_748_000_005)

    assert coord._prev_error_code == 99


def test_last_notification_sensor_reflects_emitted_event():
    """_last_notification is populated after a successful transition."""
    coord = _make_coord()
    coord._prev_error_code = 50
    coord.data = MowerState(error_code=50)

    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state, now_unix=1_748_100_000)

    assert coord._last_notification is not None
    assert coord._last_notification["event_type"] == "mowing_complete"
    assert coord._last_notification["code"] == 48
    assert coord._last_notification["fired_at"] == 1_748_100_000
    assert "text" in coord._last_notification


def test_last_notification_is_none_when_no_alert_fired():
    """_last_notification stays None when no alert has fired."""
    coord = _make_coord()
    # Boot state: _prev_error_code is None; push a known code.
    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    coord._on_state_update(state, now_unix=1_748_200_000)

    # Boot suppression: no alert should have fired.
    assert coord._last_notification is None


def test_unregistered_alert_entity_does_not_raise():
    """_fire_alert with no registered alert entity logs DEBUG and returns."""
    coord = _make_coord()
    coord._alert_event = None
    coord._prev_error_code = 50
    coord.data = MowerState(error_code=50)

    state = apply_property_to_state(coord.data, siid=2, piid=2, value=48)
    # Should NOT raise.
    coord._on_state_update(state, now_unix=1_748_300_000)

    # _last_notification is populated even when entity is absent.
    assert coord._last_notification is not None
    assert coord._last_notification["event_type"] == "mowing_complete"


# ---------------------------------------------------------------------------
# Map completeness check
# ---------------------------------------------------------------------------


def test_all_documented_codes_in_map():
    """Every s2p2 code from docs/research/g2408-protocol.md must be in the map.

    Covers all codes with confirmed (apk-sourced or live-observed)
    semantics — HYPOTHESIS-only codes from the protocol doc stay out
    until corroborated.
    """
    expected = {
        0, 27, 30, 31, 33, 43, 48, 50, 53, 54, 56, 63, 70, 71, 73, 75, 78, 117,
    }
    assert set(S2P2_NOTIFICATION_MAP.keys()) == expected


def test_all_event_types_unique_in_map():
    """All event_type strings in S2P2_NOTIFICATION_MAP are unique."""
    event_types = [v[0] for v in S2P2_NOTIFICATION_MAP.values()]
    assert len(event_types) == len(set(event_types)), (
        "Duplicate event_type in S2P2_NOTIFICATION_MAP"
    )


def test_all_map_codes_covered_by_alert_event_types():
    """Every event_type in S2P2_NOTIFICATION_MAP must appear in ALERT_EVENT_TYPES."""
    from custom_components.dreame_a2_mower.const import ALERT_EVENT_TYPES
    for code, (event_type, _) in S2P2_NOTIFICATION_MAP.items():
        assert event_type in ALERT_EVENT_TYPES, (
            f"s2p2={code} event_type={event_type!r} not in ALERT_EVENT_TYPES"
        )


def test_all_9_codes_fire_on_transition():
    """Each of the 9 documented s2p2 codes fires an alert when transitioning from
    a different known value."""
    for code, (event_type, text) in S2P2_NOTIFICATION_MAP.items():
        coord = _make_coord()
        # Use a different previous code so we get a genuine transition
        other_code = next(c for c in S2P2_NOTIFICATION_MAP if c != code)
        coord._prev_error_code = other_code
        coord.data = MowerState(error_code=other_code)

        state = apply_property_to_state(coord.data, siid=2, piid=2, value=code)
        coord._on_state_update(state, now_unix=1_748_400_000)

        coord._alert_event.trigger.assert_called_once(), (
            f"s2p2={code} ({event_type}) did not fire"
        )
        fired_type = coord._alert_event.trigger.call_args.args[0]
        assert fired_type == event_type, (
            f"s2p2={code}: expected {event_type!r}, got {fired_type!r}"
        )
