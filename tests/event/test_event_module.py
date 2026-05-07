"""Direct tests of event.py entity classes (payload cleaning + event_type guard)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.const import (
    ALERT_EVENT_TYPES,
    EVENT_TYPE_MOWING_STARTED,
    LIFECYCLE_EVENT_TYPES,
)
from custom_components.dreame_a2_mower.event import (
    DreameA2AlertEventEntity,
    DreameA2LifecycleEventEntity,
)


def _make_lifecycle_entity():
    coord = MagicMock()
    coord.entry.entry_id = "fake_entry"
    ent = DreameA2LifecycleEventEntity(coord)
    # Stub HA's lifecycle methods that EventEntity expects (_trigger_event
    # is a real method but writes to internal state we don't need to verify
    # here; the assertion is on what we feed it).
    ent._trigger_event = MagicMock()
    ent.async_write_ha_state = MagicMock()
    return ent


def test_lifecycle_entity_declares_six_event_types():
    ent = _make_lifecycle_entity()
    assert tuple(ent._attr_event_types) == LIFECYCLE_EVENT_TYPES
    assert len(ent._attr_event_types) == 6


def test_alert_entity_declares_empty_event_types():
    coord = MagicMock()
    coord.entry.entry_id = "fake_entry"
    ent = DreameA2AlertEventEntity(coord)
    assert tuple(ent._attr_event_types) == ALERT_EVENT_TYPES
    assert ent._attr_event_types == []


def test_trigger_drops_none_values_from_payload():
    """trigger() drops keys with None values so automation templates
    don't have to default-guard nullable payload fields."""
    ent = _make_lifecycle_entity()
    ent.trigger(
        EVENT_TYPE_MOWING_STARTED,
        {"at_unix": 100, "action_mode": "zone", "target_area_m2": None},
    )

    ent._trigger_event.assert_called_once()
    cleaned_event_type, cleaned_data = ent._trigger_event.call_args.args
    assert cleaned_event_type == EVENT_TYPE_MOWING_STARTED
    assert "target_area_m2" not in cleaned_data
    assert cleaned_data == {"at_unix": 100, "action_mode": "zone"}


def test_trigger_drops_unknown_event_type_silently():
    """Calling trigger() with an event_type not in the entity's declared
    list logs DEBUG and returns without firing."""
    ent = _make_lifecycle_entity()
    ent.trigger("not_a_real_event_type", {"at_unix": 100})

    ent._trigger_event.assert_not_called()


def test_trigger_with_none_event_data_passes_empty_dict():
    """trigger() called with event_data=None passes {} to _trigger_event."""
    ent = _make_lifecycle_entity()
    ent.trigger(EVENT_TYPE_MOWING_STARTED, None)

    ent._trigger_event.assert_called_once_with(EVENT_TYPE_MOWING_STARTED, {})
