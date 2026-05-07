# Event Surface (Lifecycle Tier) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Home Assistant `event` entity platform exposing six lifecycle moments — mowing started/paused/resumed/ended + dock arrived/departed — fired from existing transition sites in the coordinator, with payloads suitable for automation triggers and push notifications.

**Architecture:** New `event.py` platform registers two `EventEntity` subclasses (`lifecycle` active, `alert` declared empty for future use). A thin `_fire_lifecycle(event_type, payload)` dispatcher on the coordinator calls the entity's `_trigger_event` from existing transition detection sites in `_on_state_update`, `_do_oss_fetch`, and `_run_finalize_incomplete`. Race-skip if entity not yet registered. No changes to existing entities or behavior.

**Tech Stack:** Python 3.13+, Home Assistant Core ≥ 2024 (event entity platform is stable since 2023.9), pytest with `MagicMock` for entity stubs.

**Spec:** `docs/superpowers/specs/2026-05-07-event-surface-design.md`

---

## File Structure

| Purpose | Path |
|---|---|
| Platform setup + entity classes | `custom_components/dreame_a2_mower/event.py` (new) |
| Wire `Platform.EVENT` into setup | `custom_components/dreame_a2_mower/const.py` (modify line 13) |
| Dispatcher + fire-point wiring + `_prev_in_dock` field | `custom_components/dreame_a2_mower/coordinator.py` (modify) |
| Event-type constants | `custom_components/dreame_a2_mower/const.py` (modify, append) |
| Unit tests | `tests/event/test_event_entity.py` (new) |
| Test package marker | `tests/event/__init__.py` (new, empty) |
| User-facing automation guide | `docs/events.md` (new) |
| README link to events guide | `README.md` (modify Features section) |
| TODO entry for follow-up alert tier | `docs/TODO.md` (modify) |
| Version bump | `custom_components/dreame_a2_mower/manifest.json` (modify) |

---

## Task 1: Add event-type constants to const.py

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py` (append after PLATFORMS list)

- [ ] **Step 1: Append constants**

Append to `custom_components/dreame_a2_mower/const.py` (after the existing `PLATFORMS` block at line 25, before `LOGGER`):

```python
# Lifecycle event_types fired on event.dreame_a2_mower_lifecycle.
# See docs/events.md for payload schema.
EVENT_TYPE_MOWING_STARTED: Final = "mowing_started"
EVENT_TYPE_MOWING_PAUSED: Final = "mowing_paused"
EVENT_TYPE_MOWING_RESUMED: Final = "mowing_resumed"
EVENT_TYPE_MOWING_ENDED: Final = "mowing_ended"
EVENT_TYPE_DOCK_ARRIVED: Final = "dock_arrived"
EVENT_TYPE_DOCK_DEPARTED: Final = "dock_departed"

LIFECYCLE_EVENT_TYPES: Final[tuple[str, ...]] = (
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
)

ALERT_EVENT_TYPES: Final[tuple[str, ...]] = ()
"""Populated in the alert-tier follow-up PR (emergency_stop, lifted, etc.).
Exists now so users can pre-register automations against the entity_id."""
```

- [ ] **Step 2: Add `Platform.EVENT` to PLATFORMS list**

Edit `PLATFORMS` list at line 13 — append `"event"` to the list. After:

```python
PLATFORMS: Final = [
    "lawn_mower",
    "sensor",
    "binary_sensor",
    "device_tracker",
    "camera",
    "select",
    "number",
    "switch",
    "time",
    "button",
    "event",
]
```

- [ ] **Step 3: Verify the file parses**

Run: `python -c "from custom_components.dreame_a2_mower import const; print(const.LIFECYCLE_EVENT_TYPES)"`
Expected: tuple of 6 event_type strings printed.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py
git commit -m "feat(events): event_type constants + Platform.EVENT registration"
```

---

## Task 2: Create event.py platform with two entities

**Files:**
- Create: `custom_components/dreame_a2_mower/event.py`

- [ ] **Step 1: Create the file**

Create `custom_components/dreame_a2_mower/event.py`:

```python
"""Event entity platform for the Dreame A2 Mower integration.

Exposes lifecycle moments (mowing started/paused/resumed/ended, dock
arrived/departed) and reserves an alert entity for the follow-up
alert-tier PR.

Per spec docs/superpowers/specs/2026-05-07-event-surface-design.md:
the coordinator's _fire_lifecycle dispatcher calls each entity's
_trigger_event(event_type, event_data) on the relevant transition.
Logbook integration is automatic — HA renders firings as entries.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ALERT_EVENT_TYPES,
    DOMAIN,
    LIFECYCLE_EVENT_TYPES,
    LOGGER,
)
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entities and register them with the coordinator."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    lifecycle = DreameA2LifecycleEventEntity(coordinator)
    alert = DreameA2AlertEventEntity(coordinator)
    coordinator.register_event_entities(lifecycle=lifecycle, alert=alert)
    async_add_entities([lifecycle, alert])


class _DreameA2EventEntityBase(EventEntity):
    """Common boilerplate for the integration's event entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        unique_suffix: str,
        translation_key: str,
        event_types: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_translation_key = translation_key
        self._attr_event_types = list(event_types)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @callback
    def trigger(self, event_type: str, event_data: dict[str, Any] | None) -> None:
        """Public API the coordinator calls to fire an event.

        Drops keys whose values are None so automation templates don't
        have to default-guard nullable payload fields.
        """
        if event_type not in self._attr_event_types:
            LOGGER.debug(
                "[event] dropping unknown event_type=%r on %s; declared=%r",
                event_type, self.entity_id, self._attr_event_types,
            )
            return
        cleaned = (
            {k: v for k, v in event_data.items() if v is not None}
            if event_data
            else {}
        )
        self._trigger_event(event_type, cleaned)
        self.async_write_ha_state()


class DreameA2LifecycleEventEntity(_DreameA2EventEntityBase):
    """Lifecycle moments — mowing started/paused/resumed/ended + dock."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_suffix="lifecycle",
            translation_key="lifecycle",
            event_types=LIFECYCLE_EVENT_TYPES,
        )
        self._attr_name = "Lifecycle"


class DreameA2AlertEventEntity(_DreameA2EventEntityBase):
    """Alert moments — populated in the follow-up alert-tier PR.

    Declared with empty event_types today so the entity exists from
    this PR onwards and users can pre-register automations against the
    stable entity_id.
    """

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator,
            unique_suffix="alert",
            translation_key="alert",
            event_types=ALERT_EVENT_TYPES,
        )
        self._attr_name = "Alert"
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from custom_components.dreame_a2_mower import event; print(event.DreameA2LifecycleEventEntity.__name__)"`
Expected: `DreameA2LifecycleEventEntity`

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/event.py
git commit -m "feat(events): event.py platform with lifecycle + alert entities"
```

---

## Task 3: Coordinator dispatcher + entity registration + `_prev_in_dock` field

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Initialize `_prev_in_dock` and event-entity refs in `__init__`**

In `coordinator.py` `__init__`, immediately after the existing line `self._prev_task_state: int | None = None` (around line 515), add:

```python
        # Event-entity refs populated by event.py's async_setup_entry.
        # Coordinator's _fire_lifecycle dispatcher calls these to surface
        # transitions to HA. None until the platform setup completes;
        # _fire_lifecycle race-skips with a DEBUG log when not yet wired.
        self._lifecycle_event: Any = None
        self._alert_event: Any = None
        # Tracks the previous mower_in_dock value for rising/falling edge
        # detection of dock_arrived / dock_departed events. None at
        # startup; explicit `is True` / `is False` comparisons in
        # _on_state_update mean the first push doesn't fire spuriously.
        self._prev_in_dock: bool | None = None
```

- [ ] **Step 2: Add `register_event_entities` method on the coordinator**

Search `coordinator.py` for `def _restore_in_progress` (around line 2713). Just BEFORE that method, insert:

```python
    def register_event_entities(self, *, lifecycle: Any, alert: Any) -> None:
        """Called from event.py's async_setup_entry to wire the event
        entities the coordinator's dispatcher fires through.

        Stored as plain attributes (no weakref needed — entities live
        for the integration's lifetime). The lifecycle and alert
        parameters are the EventEntity instances created by
        event.py's setup call.
        """
        self._lifecycle_event = lifecycle
        self._alert_event = alert

    def _fire_lifecycle(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> None:
        """Race-safe dispatcher to the lifecycle event entity.

        Drops the call with a DEBUG log if the entity isn't yet wired
        (transient on startup before event.py's async_setup_entry has
        run). Delegates payload-cleaning to the entity's `trigger`
        wrapper.
        """
        ent = self._lifecycle_event
        if ent is None:
            LOGGER.debug(
                "[event] _fire_lifecycle(%r) dropped — entity not yet registered",
                event_type,
            )
            return
        ent.trigger(event_type, event_data)
```

- [ ] **Step 3: Verify the file still parses**

Run: `python -c "from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(events): coordinator dispatcher + event-entity refs + _prev_in_dock"
```

---

## Task 4: Wire `mowing_started` fire-point

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (in `_on_state_update`, the begin_session block)

- [ ] **Step 1: Write the failing test**

Create `tests/event/__init__.py` (empty file) and `tests/event/test_event_entity.py`:

```python
"""Tests for the lifecycle event-entity dispatcher."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import (
    DreameA2MowerCoordinator,
    apply_property_to_state,
)
from custom_components.dreame_a2_mower.const import (
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
)
from custom_components.dreame_a2_mower.mower.state import (
    ActionMode,
    MowerState,
)
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord() -> DreameA2MowerCoordinator:
    """Minimal coordinator stub usable for fire-point assertions."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._cached_map_data = None
    coord.cached_map_png = None
    coord._lifecycle_event = MagicMock()
    coord._alert_event = MagicMock()
    return coord


def _trigger_calls(coord: DreameA2MowerCoordinator) -> list:
    """Return the list of (event_type, payload) tuples the lifecycle
    entity's trigger method has been called with."""
    return [
        (call.args[0], call.args[1] if len(call.args) > 1 else {})
        for call in coord._lifecycle_event.trigger.call_args_list
    ]


def test_mowing_started_fires_on_first_active_state():
    """task_state None → 0 with no live_map active fires mowing_started."""
    coord = _make_coord()
    coord.data = MowerState(action_mode=ActionMode.ZONE)

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_600)

    calls = _trigger_calls(coord)
    started = [c for c in calls if c[0] == EVENT_TYPE_MOWING_STARTED]
    assert len(started) == 1, f"expected exactly 1 mowing_started, got {calls!r}"
    payload = started[0][1]
    assert payload["at_unix"] == 1_714_329_600
    assert payload["action_mode"] == "zone"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_started_fires_on_first_active_state -v`
Expected: FAIL — `AssertionError: expected exactly 1 mowing_started, got []` (the dispatcher exists but no fire-point is wired yet).

- [ ] **Step 3: Wire the fire-point**

In `coordinator.py`, find the `_on_state_update` block that calls `live_map.begin_session(now_unix)`. The current code looks like:

```python
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # means _restore_in_progress repopulated legs/started_unix
            # from disk (mid-mow HA restart). begin_session would clear
            # legs to [[]] and reset started_unix to now_unix, abandoning
            # the pre-restart trail. Just continue appending to the
            # restored leg.
            self.live_map.begin_session(now_unix)
        elif prev == 4 and new_task_state == 0:
            self.live_map.begin_leg()
```

Replace that block with:

```python
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # means _restore_in_progress repopulated legs/started_unix
            # from disk (mid-mow HA restart). begin_session would clear
            # legs to [[]] and reset started_unix to now_unix, abandoning
            # the pre-restart trail. Just continue appending to the
            # restored leg.
            self.live_map.begin_session(now_unix)
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_STARTED,
                {
                    "at_unix": int(now_unix),
                    "action_mode": (
                        new_state.action_mode.value
                        if new_state.action_mode is not None
                        else None
                    ),
                    "target_area_m2": new_state.target_area_m2,
                },
            )
        elif prev == 4 and new_task_state == 0:
            self.live_map.begin_leg()
```

Also add the import of the constant at the top of `coordinator.py`. Search for the existing `from .const import` block and add `EVENT_TYPE_MOWING_STARTED` to the imported names. (Other event-type constants will be added as we wire each fire-point.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_started_fires_on_first_active_state -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/event/__init__.py tests/event/test_event_entity.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(events): fire mowing_started on first active task_state"
```

---

## Task 5: Verify mowing_started does NOT fire after restore

**Files:**
- Modify: `tests/event/test_event_entity.py` (append test)

This is regression coverage for the trail-loss-on-restart guard added in a88: when restore set `live_map.is_active() = True`, the first MQTT push must not call begin_session AND must not fire mowing_started (the session was already in progress before the restart).

- [ ] **Step 1: Append the test**

Append to `tests/event/test_event_entity.py`:

```python
def test_mowing_started_does_not_fire_when_live_map_already_active():
    """If _restore_in_progress already populated live_map (mid-mow restart),
    the first MQTT push must NOT fire mowing_started — the session was
    already in progress before the restart, not a fresh start."""
    coord = _make_coord()
    # Simulate post-restore state: live_map active, started_unix set.
    coord.live_map.started_unix = 1_714_300_000
    coord.live_map.legs = [[(1.0, 2.0), (3.0, 4.0)]]

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_600)

    calls = _trigger_calls(coord)
    started = [c for c in calls if c[0] == EVENT_TYPE_MOWING_STARTED]
    assert started == [], f"expected no mowing_started, got {started!r}"
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_started_does_not_fire_when_live_map_already_active -v`
Expected: PASS (the existing `not self.live_map.is_active()` guard short-circuits before the fire site).

- [ ] **Step 3: Commit**

```bash
git add tests/event/test_event_entity.py
git commit -m "test(events): mowing_started does not fire after mid-mow restart restore"
```

---

## Task 6: Wire `mowing_paused` and `mowing_resumed`

**Files:**
- Modify: `tests/event/test_event_entity.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/event/test_event_entity.py`:

```python
def test_mowing_paused_fires_on_0_to_4():
    """task_state 0 → 4 fires mowing_paused with area_mowed_m2."""
    coord = _make_coord()
    coord.data = MowerState(area_mowed_m2=12.5)
    coord._prev_task_state = 0  # was running
    coord.live_map.started_unix = 1_714_329_600  # session is active

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 4]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_900)

    calls = _trigger_calls(coord)
    paused = [c for c in calls if c[0] == EVENT_TYPE_MOWING_PAUSED]
    assert len(paused) == 1, f"expected 1 mowing_paused, got {calls!r}"
    payload = paused[0][1]
    assert payload["at_unix"] == 1_714_329_900
    assert payload["area_mowed_m2"] == 12.5
    assert payload["reason"] in ("user", "recharge_required", "unknown")


def test_mowing_resumed_fires_on_4_to_0():
    """task_state 4 → 0 fires mowing_resumed with area_mowed_m2."""
    coord = _make_coord()
    coord.data = MowerState(area_mowed_m2=18.0)
    coord._prev_task_state = 4  # was paused
    coord.live_map.started_unix = 1_714_329_600  # session is active

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_330_500)

    calls = _trigger_calls(coord)
    resumed = [c for c in calls if c[0] == EVENT_TYPE_MOWING_RESUMED]
    assert len(resumed) == 1, f"expected 1 mowing_resumed, got {calls!r}"
    payload = resumed[0][1]
    assert payload["at_unix"] == 1_714_330_500
    assert payload["area_mowed_m2"] == 18.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_paused_fires_on_0_to_4 tests/event/test_event_entity.py::test_mowing_resumed_fires_on_4_to_0 -v`
Expected: BOTH FAIL — `expected 1 mowing_paused, got []` etc.

- [ ] **Step 3: Wire the fire-points**

In `coordinator.py`, find the `_on_state_update` block right after the begin_session/begin_leg dispatch you edited in Task 4. The current sequence is:

```python
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # ... (begin_session + mowing_started fire from Task 4) ...
        elif prev == 4 and new_task_state == 0:
            self.live_map.begin_leg()
```

Add a parallel pair of branches (paused on 0→4, resumed on 4→0). Replace the whole block with:

```python
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # means _restore_in_progress repopulated legs/started_unix
            # from disk (mid-mow HA restart). begin_session would clear
            # legs to [[]] and reset started_unix to now_unix, abandoning
            # the pre-restart trail. Just continue appending to the
            # restored leg.
            self.live_map.begin_session(now_unix)
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_STARTED,
                {
                    "at_unix": int(now_unix),
                    "action_mode": (
                        new_state.action_mode.value
                        if new_state.action_mode is not None
                        else None
                    ),
                    "target_area_m2": new_state.target_area_m2,
                },
            )
        elif prev == 0 and new_task_state == 4:
            # Mid-mow pause. Reason is best-effort: if the previous
            # tick's MowerState exposed an obvious cause use it,
            # otherwise "unknown". Don't gate fire on reason detection.
            reason = "unknown"
            if new_state.battery_level is not None and new_state.battery_level <= 20:
                reason = "recharge_required"
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_PAUSED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                    "reason": reason,
                },
            )
        elif prev == 4 and new_task_state == 0:
            self.live_map.begin_leg()
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_RESUMED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                },
            )
```

Add `EVENT_TYPE_MOWING_PAUSED` and `EVENT_TYPE_MOWING_RESUMED` to the existing `from .const import` block at the top of `coordinator.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_paused_fires_on_0_to_4 tests/event/test_event_entity.py::test_mowing_resumed_fires_on_4_to_0 -v`
Expected: BOTH PASS

- [ ] **Step 5: Commit**

```bash
git add tests/event/test_event_entity.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(events): fire mowing_paused on 0→4 and mowing_resumed on 4→0"
```

---

## Task 7: Wire `mowing_ended` from finalize paths

**Files:**
- Modify: `tests/event/test_event_entity.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/event/test_event_entity.py`:

```python
def test_mowing_ended_fires_complete_with_summary():
    """When _do_oss_fetch successfully archives a session,
    mowing_ended fires with completed=True and the summary's metrics."""
    coord = _make_coord()
    # Caller-supplied payload args mirror what _do_oss_fetch passes
    # through after the archive write — exercise the helper directly.
    coord._fire_mowing_ended(
        now_unix=1_714_330_000,
        area_mowed_m2=42.5,
        duration_min=63,
        completed=True,
    )

    calls = _trigger_calls(coord)
    ended = [c for c in calls if c[0] == EVENT_TYPE_MOWING_ENDED]
    assert len(ended) == 1, f"expected 1 mowing_ended, got {calls!r}"
    payload = ended[0][1]
    assert payload["at_unix"] == 1_714_330_000
    assert payload["area_mowed_m2"] == 42.5
    assert payload["duration_min"] == 63
    assert payload["completed"] is True


def test_mowing_ended_fires_incomplete():
    """FINALIZE_INCOMPLETE path fires mowing_ended with completed=False."""
    coord = _make_coord()
    coord._fire_mowing_ended(
        now_unix=1_714_330_500,
        area_mowed_m2=8.0,
        duration_min=12,
        completed=False,
    )

    calls = _trigger_calls(coord)
    ended = [c for c in calls if c[0] == EVENT_TYPE_MOWING_ENDED]
    assert len(ended) == 1
    assert ended[0][1]["completed"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_ended_fires_complete_with_summary tests/event/test_event_entity.py::test_mowing_ended_fires_incomplete -v`
Expected: BOTH FAIL — `AttributeError: ... '_fire_mowing_ended'` (helper not defined yet).

- [ ] **Step 3: Add helper + wire fire-points**

In `coordinator.py`, just below the `_fire_lifecycle` method you added in Task 3, add a small named helper:

```python
    def _fire_mowing_ended(
        self,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
    ) -> None:
        """Fire the mowing_ended lifecycle event.

        Called from both _do_oss_fetch (FINALIZE_COMPLETE, summary-driven)
        and _run_finalize_incomplete (FINALIZE_INCOMPLETE, best-effort).
        Delegates payload-shape consistency to one place.
        """
        self._fire_lifecycle(
            EVENT_TYPE_MOWING_ENDED,
            {
                "at_unix": int(now_unix),
                "area_mowed_m2": area_mowed_m2,
                "duration_min": duration_min,
                "completed": bool(completed),
            },
        )
```

Now wire the call sites. In `_do_oss_fetch`, find `self.live_map.end_session()` (around line 2510). Just BEFORE that call, add:

```python
            self._fire_mowing_ended(
                now_unix=now_unix,
                area_mowed_m2=summary.area_mowed_m2,
                duration_min=summary.duration_min,
                completed=True,
            )
```

In `_run_finalize_incomplete`, find the `self.live_map.end_session()` call (search for `end_session` in that method, around line 2654). Just BEFORE that call, add:

```python
            self._fire_mowing_ended(
                now_unix=now_unix,
                area_mowed_m2=self.data.area_mowed_m2,
                duration_min=(
                    int((now_unix - start_ts) / 60)
                    if start_ts > 0
                    else None
                ),
                completed=False,
            )
```

(The `start_ts` variable is already in scope inside `_run_finalize_incomplete` — it's read from disk earlier in that method.)

Add `EVENT_TYPE_MOWING_ENDED` to the const-import block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/event/test_event_entity.py::test_mowing_ended_fires_complete_with_summary tests/event/test_event_entity.py::test_mowing_ended_fires_incomplete -v`
Expected: BOTH PASS

- [ ] **Step 5: Commit**

```bash
git add tests/event/test_event_entity.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(events): fire mowing_ended from finalize paths (complete + incomplete)"
```

---

## Task 8: Wire `dock_arrived` and `dock_departed`

**Files:**
- Modify: `tests/event/test_event_entity.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/event/test_event_entity.py`:

```python
import dataclasses


def test_dock_arrived_fires_on_rising_edge():
    """_prev_in_dock False → mower_in_dock True fires dock_arrived once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=False)
    coord._prev_in_dock = False
    state = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state, now_unix=1_714_400_000)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert len(arrived) == 1
    assert arrived[0][1]["at_unix"] == 1_714_400_000
    assert coord._prev_in_dock is True


def test_dock_arrived_does_not_fire_on_first_observation():
    """When _prev_in_dock is None (boot) and mower is observed at dock,
    dock_arrived must NOT fire — there's no edge yet."""
    coord = _make_coord()
    coord.data = MowerState()
    # _prev_in_dock is None from _make_coord
    state = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state, now_unix=1_714_400_000)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert arrived == []


def test_dock_departed_fires_on_falling_edge():
    """_prev_in_dock True → mower_in_dock False fires dock_departed once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=True)
    coord._prev_in_dock = True
    state = dataclasses.replace(coord.data, mower_in_dock=False)

    coord._on_state_update(state, now_unix=1_714_400_500)

    calls = _trigger_calls(coord)
    departed = [c for c in calls if c[0] == EVENT_TYPE_DOCK_DEPARTED]
    assert len(departed) == 1
    assert coord._prev_in_dock is False


def test_dock_arrived_does_not_refire_on_stable_state():
    """Two ticks both showing mower_in_dock=True only fires arrived once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=False)
    coord._prev_in_dock = False
    state_arrived = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state_arrived, now_unix=1_714_400_000)
    coord.data = state_arrived  # simulate the coordinator promoting the state
    coord._on_state_update(state_arrived, now_unix=1_714_400_010)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert len(arrived) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/event/test_event_entity.py -k dock -v`
Expected: ALL FAIL — no dock_arrived/departed fires yet.

- [ ] **Step 3: Wire the fire-points**

In `coordinator.py` `_on_state_update`, after the existing `self._prev_task_state = new_task_state` line and BEFORE the `self.freshness.record(...)` call, insert the dock-edge detection:

```python
        # Dock arrival/departure rising/falling edges. Explicit `is True` /
        # `is False` so the boot-time None state doesn't fire a spurious
        # arrived/departed event.
        if (
            self._prev_in_dock is False
            and new_state.mower_in_dock is True
        ):
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_ARRIVED, {"at_unix": int(now_unix)}
            )
        elif (
            self._prev_in_dock is True
            and new_state.mower_in_dock is False
        ):
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_DEPARTED, {"at_unix": int(now_unix)}
            )
        self._prev_in_dock = new_state.mower_in_dock
```

Add `EVENT_TYPE_DOCK_ARRIVED` and `EVENT_TYPE_DOCK_DEPARTED` to the const-import block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/event/test_event_entity.py -k dock -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/event/test_event_entity.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(events): fire dock_arrived/departed on mower_in_dock edges"
```

---

## Task 9: Race-skip + payload-clean tests

**Files:**
- Modify: `tests/event/test_event_entity.py`

- [ ] **Step 1: Append the tests**

Append to `tests/event/test_event_entity.py`:

```python
def test_fire_with_unregistered_entity_does_not_raise():
    """Calling _fire_lifecycle before event.py setup logs DEBUG and returns."""
    coord = _make_coord()
    coord._lifecycle_event = None  # not yet registered

    # Should NOT raise.
    coord._fire_lifecycle(EVENT_TYPE_MOWING_STARTED, {"at_unix": 1, "action_mode": "edge"})

    # Nothing observable should have happened.
    # (No assertion needed; the test passes if no exception was raised.)


def test_payload_omits_none_values():
    """Nullable payload keys with value None are dropped from event_data
    so automation templates don't have to default-guard."""
    coord = _make_coord()
    coord.data = MowerState(action_mode=ActionMode.EDGE, target_area_m2=None)

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_500_000)

    # Read what the entity received via its `trigger` method.
    last_call = coord._lifecycle_event.trigger.call_args
    event_type, event_data = last_call.args
    assert event_type == EVENT_TYPE_MOWING_STARTED
    # `target_area_m2` was None; the entity's trigger() drops None
    # values, but the dispatcher passes the raw dict — assertion
    # belongs in the entity-level test below in test_event_module.py.
    # Here we just check the dispatcher passed it through.
    assert event_data["action_mode"] == "edge"
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/event/test_event_entity.py -v`
Expected: ALL PASS (these tests exercise existing behavior — the dispatcher already race-skips, and payload-cleaning happens in the entity, exercised in Task 10).

- [ ] **Step 3: Commit**

```bash
git add tests/event/test_event_entity.py
git commit -m "test(events): race-skip + payload-pass-through coverage"
```

---

## Task 10: Entity-level payload cleaning + event_type validation tests

**Files:**
- Create: `tests/event/test_event_module.py`

- [ ] **Step 1: Write the failing test**

Create `tests/event/test_event_module.py`:

```python
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
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/event/test_event_module.py -v`
Expected: ALL PASS (the entity logic was complete in Task 2).

- [ ] **Step 3: Commit**

```bash
git add tests/event/test_event_module.py
git commit -m "test(events): entity-level payload cleaning + event_type validation"
```

---

## Task 11: Run full test suite, fix regressions if any

**Files:** none directly (verification step).

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: 712+ passed, 4 skipped (704 baseline + ~8 new tests in tests/event/)

- [ ] **Step 2: If any pre-existing test fails**

The fire-points should not affect existing behavior. If a test in `tests/integration/test_coordinator.py` fails because it doesn't set `coord._lifecycle_event` and `coord._prev_in_dock`, extend `_make_coordinator_for_session_tests` (in `tests/integration/test_coordinator.py`) to set both:

```python
    coord._lifecycle_event = MagicMock()
    coord._alert_event = MagicMock()
    coord._prev_in_dock = None
```

Then re-run.

- [ ] **Step 3: Commit (only if you had to fix tests)**

```bash
git add tests/integration/test_coordinator.py
git commit -m "test(events): extend coordinator test fixture with event-entity stubs"
```

---

## Task 12: User-facing events documentation

**Files:**
- Create: `docs/events.md`
- Modify: `README.md`

- [ ] **Step 1: Create docs/events.md**

Create `docs/events.md`:

```markdown
# Events

The integration surfaces mower lifecycle moments as Home Assistant
event entities so automations and push notifications can react to
"something happened" without polling sensor states.

## Entities

| entity_id | Purpose |
|---|---|
| `event.dreame_a2_mower_lifecycle` | Mowing start/pause/resume/end + dock arrive/depart |
| `event.dreame_a2_mower_alert` | Reserved for the alert-tier release (emergency_stop, lifted, stuck, etc.) |

When an event fires, the entity's `state` attribute is set to the
event_type (e.g. `mowing_started`) and the event payload is exposed as
additional attributes accessible via `trigger.to_state.attributes.<key>`.
HA's Logbook automatically records each firing.

## Lifecycle event reference

### `mowing_started`
Mower transitions from idle/complete to running.
- `at_unix` — wall-clock unix timestamp
- `action_mode` — `"all_areas"`, `"zone"`, `"edge"`, or `"spot"`
- `target_area_m2` — planned area for this run, when known

### `mowing_paused`
Mower transitions from running to paused (recharge, user pause, safety).
- `at_unix`
- `area_mowed_m2`
- `reason` — `"user"`, `"recharge_required"`, `"unknown"` (best-effort)

### `mowing_resumed`
Mower transitions from paused back to running (post-recharge or manual).
- `at_unix`
- `area_mowed_m2`

### `mowing_ended`
Session completed — either with a cloud summary (`completed: true`) or
because the integration gave up waiting for one and finalized with what
it had locally (`completed: false`).
- `at_unix`
- `area_mowed_m2`
- `duration_min`
- `completed` — bool

### `dock_arrived`
Mower returned to the charging dock. Fires on the `mower_in_dock`
sensor's rising edge.
- `at_unix`

### `dock_departed`
Mower left the dock. Fires on the falling edge.
- `at_unix`

## Recipes

### 1. Push notification on every mow start

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_started
action:
  - service: notify.mobile_app_<your_device>
    data:
      title: "Mower"
      message: >-
        Started {{ trigger.to_state.attributes.action_mode }} mow
        ({{ trigger.to_state.attributes.target_area_m2 | default("?") }} m²)
```

### 2. Mode-specific notification

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_started
condition:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.action_mode == 'edge' }}"
action:
  - service: notify.mobile_app_<your_device>
    data:
      title: "Mower"
      message: "Edge run started — clear the perimeter."
```

### 3. Log mowing_ended to a counter helper

```yaml
trigger:
  - platform: state
    entity_id: event.dreame_a2_mower_lifecycle
    to: mowing_ended
action:
  - service: counter.increment
    target:
      entity_id: counter.mowing_sessions
  - service: input_number.set_value
    target:
      entity_id: input_number.last_mow_area
    data:
      value: "{{ trigger.to_state.attributes.area_mowed_m2 }}"
```

## How event entities differ from state-change triggers

You could already react to most of these moments by watching state
changes on `lawn_mower.dreame_a2_mower` (e.g. `from: docked, to: mowing`)
and reading sibling sensors for context. The event-entity surface
adds three things:

1. **One trigger per moment, all data on the trigger** — no need to
   read `sensor.area_mowed` separately when `mowing_ended` fires; the
   value is already on `trigger.to_state.attributes.area_mowed_m2`.
2. **Logbook integration** — Settings → Logbook shows a chronological
   stream of event firings.
3. **Stable event_type strings** — automations key off
   `mowing_started` / `dock_arrived` / etc., not the integration's
   internal state machine, so future state-machine refactors won't
   break your automations.

## Pushing events outside HA

The integration stops at firing the event. To get push to your phone,
email, etc., write an automation that calls one of HA's notify
integrations on the event:

- **Mobile push** — Home Assistant Companion App: `notify.mobile_app_*`
- **Pushover / Pushbullet / Telegram / Slack** — install the matching
  integration, then `notify.<service>`
- **Webhook to anywhere** — `rest_command` or `shell_command` services
- **MQTT bridge** — `mqtt.publish` to a topic your other systems consume

The event payload is available in templates as
`trigger.to_state.attributes.<key>`, so any of these transports can
include the action_mode, area_mowed_m2, etc., in the message body.
```

- [ ] **Step 2: Add link to README**

In `README.md`, find the `## Features` section. Add a new subsection right before `### Showcase dashboard` (line 89). The new content:

```markdown
### Events and notifications

Mowing start/pause/resume/end and dock arrive/depart fire as HA event
entities (`event.dreame_a2_mower_lifecycle`). Each event carries a
payload with the action mode, area mowed, etc. — wire them to push
notifications, Logbook, automations, or your own dashboards. See
`docs/events.md` for the full event reference and recipes. The
follow-up alert tier (emergency_stop, lifted, stuck, ...) lands in
a later release.

```

Also append to the `## Documentation` section (after the existing list at line 162):

```markdown
- **`docs/events.md`** — event reference + automation recipes for the
  lifecycle event entity.
```

- [ ] **Step 3: Verify the markdown renders**

Run: `python -c "import pathlib; print(pathlib.Path('docs/events.md').read_text()[:200])"`
Expected: first 200 characters of the new doc.

- [ ] **Step 4: Commit**

```bash
git add docs/events.md README.md
git commit -m "docs(events): user-facing event reference + automation recipes"
```

---

## Task 13: Add alerts-tier follow-up TODO entry

**Files:**
- Modify: `docs/TODO.md`

- [ ] **Step 1: Add the entry**

In `docs/TODO.md`, find the `## Open` section. Add this entry right after the template block (or at the end of the Open section):

```markdown
### Alert-tier event surface (follow-up to lifecycle PR)

**Why:** The lifecycle-tier event surface (a91) reserved
`event.dreame_a2_mower_alert` with empty `event_types`. Populate it
with `emergency_stop`, `lifted`, `tilted`, `stuck`, `bumper_error`,
`obstacle_with_photo`, `battery_low`, `battery_temperature_low`, `error`.
Add `CONF_NOTIFY` option toggle. Migrate the existing bespoke
`_handle_emergency_stop_transition` banner to a framework-managed
persistent_notification gated by CONF_NOTIFY.
**Done when:** All listed event_types fire from the appropriate
detection sites; `_handle_emergency_stop_transition` is replaced;
docs/events.md gains the alert section; emergency_stop banner
behavior is unchanged from the user's perspective.
**Status:** open
**Cross-refs:** `docs/superpowers/specs/2026-05-07-event-surface-design.md` § "Out of scope"

---

```

- [ ] **Step 2: Commit**

```bash
git add docs/TODO.md
git commit -m "docs(todo): alert-tier event surface follow-up"
```

---

## Task 14: Version bump + release

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 1: Verify clean tree + on main**

Run: `git status --porcelain && git rev-parse --abbrev-ref HEAD`
Expected: empty output, then `main`

- [ ] **Step 2: Run the release script**

Write release notes to `/tmp/release_a91_notes.md`:

```markdown
## v1.0.0a91

Lifecycle event-entity surface (`event.dreame_a2_mower_lifecycle`).
Six event_types fire from existing transition sites — no behavior
change to existing entities, just a new automation surface.

Events:
- `mowing_started` (with `action_mode`, `target_area_m2`)
- `mowing_paused` (with `area_mowed_m2`, `reason`)
- `mowing_resumed` (with `area_mowed_m2`)
- `mowing_ended` (with `area_mowed_m2`, `duration_min`, `completed`)
- `dock_arrived`, `dock_departed`

A second `event.dreame_a2_mower_alert` entity is reserved with empty
`event_types` for the follow-up alert-tier release (emergency_stop,
lifted, stuck, etc.). Existing emergency_stop persistent_notification
unchanged in this release.

See `docs/events.md` for the event reference + automation recipes
(push notifications, Logbook, mode-specific reactions).
```

Run: `tools/release.sh --notes-file /tmp/release_a91_notes.md`
Expected: `✅ release v1.0.0a91 published cleanly.`

The release.sh script handles manifest bump, commit, tag, push, gh release create, HACS refresh.

- [ ] **Step 3: Verify HACS sees the release**

Run: `gh release view v1.0.0a91 --json tagName,isLatest,isPrerelease --jq '.'`
Expected:
```json
{"tagName": "v1.0.0a91", "isLatest": true, "isPrerelease": false}
```

---

## Task 15: Self-review + spec coverage check

**Files:** none (verification only)

- [ ] **Step 1: Re-read the spec**

Re-read `docs/superpowers/specs/2026-05-07-event-surface-design.md` and verify each section is covered:

- ✅ "Architecture" — Tasks 2 + 3 create the entities and dispatcher
- ✅ "Data flow — detection sites" — Tasks 4-8 wire each fire-point
- ✅ "Payload shapes" — payloads match in each fire-point
- ✅ "Components — files" — every file in the spec is created/modified
- ✅ "User docs (`docs/events.md`)" — Task 12
- ✅ "Out of scope — this PR" — alerts-tier deferred via Task 13
- ✅ "Testing" — Tasks 4-10 cover every assertion in the spec's testing section
- ✅ "Migration / compatibility" — no existing entity changes; emergency_stop banner unchanged

- [ ] **Step 2: Run pytest one last time**

Run: `python -m pytest -q`
Expected: 712+ passed.

- [ ] **Step 3: Done**

The lifecycle event surface is shipped in v1.0.0a91. Pull via HACS, restart HA, then `event.dreame_a2_mower_lifecycle` should appear under Settings → Devices & Services → Dreame A2 Mower → Entities. Test by starting/stopping a mow and watching Settings → Logbook.
