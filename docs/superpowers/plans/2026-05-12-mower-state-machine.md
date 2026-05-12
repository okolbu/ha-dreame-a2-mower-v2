# Mower State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ad-hoc per-slot state mutation in `coordinator.py` with a single `MowerStateMachine` class producing a coherent multi-dimensional `StateSnapshot`. Drive all state-consuming entities from that snapshot.

**Architecture:** Pure-Python `MowerStateMachine` lives in `mower/state_machine.py`. Inputs in (MQTT slots, cloud-poll results, heartbeat ticks), `StateSnapshot` out. Per-field freshness tracking enforces MQTT-primary precedence (cloud only overwrites when fresher than last MQTT update). Coordinator-level snapshot persisted via HA `Store` across restarts. Entities re-read snapshot fields; legacy `MowerState` dataclass deleted.

**Tech Stack:** Python 3.13 / Home Assistant custom_component, `dataclasses` (frozen), `enum.Enum`, `homeassistant.helpers.storage.Store`, pytest.

**Per `feedback_no_migration_overengineering`:** No backward-compat shims. Entities rewire in one cut; users reinstall the integration if entity_registry orphans accumulate.

---

## File Structure

**New files:**
- `custom_components/dreame_a2_mower/mower/state_snapshot.py` — `StateSnapshot` dataclass + dimension enums (separate file to avoid circular imports)
- `custom_components/dreame_a2_mower/mower/state_machine.py` — `MowerStateMachine` class

**Heavily modified:**
- `custom_components/dreame_a2_mower/coordinator.py` — delegate parsing to state machine; remove per-slot mutation
- `custom_components/dreame_a2_mower/lawn_mower.py` — projection from snapshot
- `custom_components/dreame_a2_mower/binary_sensor.py` — `mower_in_dock` + `mowing_session_active` re-source
- `custom_components/dreame_a2_mower/sensor.py` — new sensors (current_activity, location, positioning_health, mqtt_connectivity, cloud_rpc_health) + re-source existing

**Deleted:**
- `custom_components/dreame_a2_mower/mower/state.py` (legacy `MowerState`) — folded into `StateSnapshot`

**New tests:**
- `tests/state_machine/test_state_snapshot.py` — snapshot dataclass + enum behaviour
- `tests/state_machine/test_state_machine_mqtt.py` — handle_mqtt_property scenarios
- `tests/state_machine/test_state_machine_cloud.py` — handle_cloud_poll + freshness precedence
- `tests/state_machine/test_state_machine_tick.py` — tick: HB staleness, buffered s2p2=71
- `tests/state_machine/test_state_machine_persistence.py` — Store round-trip
- `tests/state_machine/test_lawn_mower_projection.py` — projection table

---

## Task 1: StateSnapshot dataclass + dimension enums

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/state_snapshot.py`
- Test: `tests/state_machine/test_state_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
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
        StateSnapshot, MowSession, CurrentActivity, Location,
        PositioningHealth, Connectivity, RpcHealth,
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
```

- [ ] **Step 2: Run; verify it fails**

```
python -m pytest tests/state_machine/test_state_snapshot.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `state_snapshot.py`**

```python
"""StateSnapshot dataclass + dimension enums.

Defined in a separate file from MowerStateMachine to keep the type
surface importable without pulling the state-machine logic (avoids
circular imports across the package).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MowSession(Enum):
    IN_SESSION = "in_session"
    BETWEEN_SESSIONS = "between_sessions"


class CurrentActivity(Enum):
    MOWING = "mowing"
    PAUSED = "paused"
    REPOSITIONING = "repositioning"
    RETURNING = "returning"
    CHARGE_RESUME = "charge_resume"
    CRUISING_TO_POINT = "cruising_to_point"
    AT_POINT = "at_point"
    FAST_MAPPING = "fast_mapping"
    DRIVING_BLADES_UP = "driving_blades_up"
    IDLE = "idle"


class Location(Enum):
    AT_DOCK = "at_dock"
    ON_LAWN = "on_lawn"
    AT_POINT = "at_point"
    OUTSIDE_KNOWN_AREA = "outside_known_area"


class PositioningHealth(Enum):
    LOCALIZED = "localized"
    RELOCATING = "relocating"
    STUCK = "stuck"


class Connectivity(Enum):
    ONLINE = "online"
    STALE = "stale"


class RpcHealth(Enum):
    OK = "ok"
    FAILING = "failing"


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable multi-dim mower state. Replace via `dataclasses.replace`."""

    # Multi-dim state
    mow_session: MowSession
    current_activity: CurrentActivity
    location: Location
    positioning_health: PositioningHealth
    charging: bool
    errors: frozenset[int]
    pin_required: bool
    mqtt_connectivity: Connectivity
    cloud_rpc_health: RpcHealth

    # Provenance + freshness
    last_heartbeat_unix: int | None
    field_freshness: dict[str, int]

    # Pre-disambiguation / debug
    paused_from: CurrentActivity | None
    last_task_op: int | None
    raw_s2p1: int | None
    raw_s2p2: int | None

    # Scalars
    battery_percent: int | None
    position_x_m: float | None
    position_y_m: float | None
    position_north_m: float | None
    position_east_m: float | None
    error_code: int | None
    wifi_rssi_dbm: int | None

    @classmethod
    def initial(cls) -> "StateSnapshot":
        return cls(
            mow_session=MowSession.BETWEEN_SESSIONS,
            current_activity=CurrentActivity.IDLE,
            location=Location.AT_DOCK,
            positioning_health=PositioningHealth.LOCALIZED,
            charging=False,
            errors=frozenset(),
            pin_required=False,
            mqtt_connectivity=Connectivity.STALE,
            cloud_rpc_health=RpcHealth.OK,
            last_heartbeat_unix=None,
            field_freshness={},
            paused_from=None,
            last_task_op=None,
            raw_s2p1=None,
            raw_s2p2=None,
            battery_percent=None,
            position_x_m=None,
            position_y_m=None,
            position_north_m=None,
            position_east_m=None,
            error_code=None,
            wifi_rssi_dbm=None,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-able serialisation. Enums → name strings, frozenset → list."""
        d = dataclasses.asdict(self)
        for k, v in d.items():
            if isinstance(v, Enum):
                d[k] = v.name
            elif isinstance(v, frozenset):
                d[k] = sorted(v)
        # `paused_from` is an Enum-or-None; asdict already converted
        # to its `.value` form via dataclasses internals when nested?
        # Safer: re-derive from the actual field.
        d["paused_from"] = (
            self.paused_from.name if self.paused_from is not None else None
        )
        d["mow_session"] = self.mow_session.name
        d["current_activity"] = self.current_activity.name
        d["location"] = self.location.name
        d["positioning_health"] = self.positioning_health.name
        d["mqtt_connectivity"] = self.mqtt_connectivity.name
        d["cloud_rpc_health"] = self.cloud_rpc_health.name
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StateSnapshot":
        return cls(
            mow_session=MowSession[raw["mow_session"]],
            current_activity=CurrentActivity[raw["current_activity"]],
            location=Location[raw["location"]],
            positioning_health=PositioningHealth[raw["positioning_health"]],
            charging=bool(raw["charging"]),
            errors=frozenset(int(c) for c in raw.get("errors") or []),
            pin_required=bool(raw["pin_required"]),
            mqtt_connectivity=Connectivity[raw["mqtt_connectivity"]],
            cloud_rpc_health=RpcHealth[raw["cloud_rpc_health"]],
            last_heartbeat_unix=raw.get("last_heartbeat_unix"),
            field_freshness=dict(raw.get("field_freshness") or {}),
            paused_from=(
                CurrentActivity[raw["paused_from"]]
                if raw.get("paused_from") else None
            ),
            last_task_op=raw.get("last_task_op"),
            raw_s2p1=raw.get("raw_s2p1"),
            raw_s2p2=raw.get("raw_s2p2"),
            battery_percent=raw.get("battery_percent"),
            position_x_m=raw.get("position_x_m"),
            position_y_m=raw.get("position_y_m"),
            position_north_m=raw.get("position_north_m"),
            position_east_m=raw.get("position_east_m"),
            error_code=raw.get("error_code"),
            wifi_rssi_dbm=raw.get("wifi_rssi_dbm"),
        )
```

- [ ] **Step 4: Run; verify pass**

```
python -m pytest tests/state_machine/test_state_snapshot.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_snapshot.py tests/state_machine/test_state_snapshot.py
git commit -m "feat(state): StateSnapshot dataclass + dimension enums"
```

---

## Task 2: MowerStateMachine skeleton

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_skeleton.py`

- [ ] **Step 1: Write the failing test**

```python
"""Skeleton tests — class instantiates, snapshot accessor, dirty flag."""
from __future__ import annotations


def test_state_machine_instantiates_with_initial_snapshot():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    sm = MowerStateMachine()
    assert isinstance(sm.snapshot(), StateSnapshot)


def test_snapshot_returns_same_instance_when_unchanged():
    """Cheap accessor — returns the cached snapshot, not a fresh copy."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    s1 = sm.snapshot()
    s2 = sm.snapshot()
    assert s1 is s2


def test_state_machine_dirty_flag():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    assert sm.is_dirty() is False
    sm._mark_dirty()
    assert sm.is_dirty() is True
    sm._clear_dirty()
    assert sm.is_dirty() is False
```

- [ ] **Step 2: Run; verify fails**

```
python -m pytest tests/state_machine/test_state_machine_skeleton.py -v
```

- [ ] **Step 3: Implement skeleton**

```python
"""MowerStateMachine — single owner of the multi-dim mower state.

Inputs (MQTT slots, cloud-poll results, heartbeat ticks) in;
StateSnapshot out. Pure-Python; the only HA dependency is the
optional Store used by load_persisted / save_persisted.
"""
from __future__ import annotations

import logging
from typing import Any

from .state_snapshot import StateSnapshot

_LOGGER = logging.getLogger(__name__)


class MowerStateMachine:
    """Multi-dim mower state machine."""

    def __init__(self) -> None:
        self._snapshot: StateSnapshot = StateSnapshot.initial()
        self._dirty: bool = False

    def snapshot(self) -> StateSnapshot:
        """Cheap accessor — returns the current immutable snapshot."""
        return self._snapshot

    def _replace(self, **kwargs: Any) -> StateSnapshot:
        """Replace snapshot fields, marking dirty if changed."""
        import dataclasses
        new = dataclasses.replace(self._snapshot, **kwargs)
        if new != self._snapshot:
            self._snapshot = new
            self._dirty = True
        return new

    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _clear_dirty(self) -> None:
        self._dirty = False
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_skeleton.py
git commit -m "feat(state): MowerStateMachine skeleton with snapshot accessor"
```

---

## Task 3: handle_mqtt_property — slot routing + freshness stamping

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_mqtt.py`

- [ ] **Step 1: Write the failing tests (scalar slots first)**

```python
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
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement handle_mqtt_property**

Append to `state_machine.py`:

```python
    # Slot → (field-name, value-transform). For value-change-only fields.
    _SCALAR_SLOTS: dict[tuple[int, int], tuple[str, Any]] = {}

    def handle_mqtt_property(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> StateSnapshot:
        """Apply one MQTT property change. Returns the (possibly new) snapshot."""
        key = (int(siid), int(piid))

        # Scalar slots — battery, charging, etc.
        if key == (3, 1):
            return self._apply_scalar("battery_percent", int(value), now_unix)
        if key == (3, 2):
            return self._apply_scalar("charging", bool(int(value)), now_unix)

        # Unknown slot — log once, return unchanged
        _LOGGER.debug(
            "MowerStateMachine: unrecognised slot s%dp%d value=%r",
            siid, piid, value,
        )
        return self._snapshot

    def _apply_scalar(
        self, field_name: str, new_value: Any, now_unix: int
    ) -> StateSnapshot:
        """Update a scalar field with freshness stamping. Idempotent on same value."""
        current = getattr(self._snapshot, field_name)
        if current == new_value:
            return self._snapshot
        new_freshness = dict(self._snapshot.field_freshness)
        new_freshness[field_name] = now_unix
        return self._replace(
            **{field_name: new_value},
            field_freshness=new_freshness,
        )
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_mqtt.py
git commit -m "feat(state): handle_mqtt_property routes scalar slots with freshness"
```

---

## Task 4: handle_mqtt_property — task_state + event codes (s2p1, s2p2)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_mqtt.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
def test_s2p1_task_state_done_transitions_to_idle():
    """s2p1 = 2 (task done) → current_activity = IDLE."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    # First enter a session via s2p1=1
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1000)
    snap = sm.snapshot()
    assert snap.raw_s2p1 == 1
    # Now finish
    sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=2000)
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.raw_s2p1 == 2


def test_s2p1_returning_sets_returning_activity():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1000)
    assert sm.snapshot().current_activity == CurrentActivity.RETURNING


def test_s2p2_event_50_starts_mow_session():
    """s2p2 = 50 (mowing_started) → mow_session = IN_SESSION."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.raw_s2p2 == 50


def test_s2p2_event_48_ends_mow_session():
    """s2p2 = 48 (mowing_complete) → mow_session = BETWEEN_SESSIONS."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=2, value=48, now_unix=2000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS
    assert snap.current_activity == CurrentActivity.IDLE


def test_s2p2_event_75_signals_arrived_at_point():
    """s2p2 = 75 → location = AT_POINT, current_activity = AT_POINT."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=1000)
    snap = sm.snapshot()
    assert snap.location == Location.AT_POINT
    assert snap.current_activity == CurrentActivity.AT_POINT
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Extend handle_mqtt_property with s2p1 + s2p2 routing**

In `state_machine.py`, extend `handle_mqtt_property`:

```python
        if key == (2, 1):
            return self._apply_s2p1_task_state(int(value), now_unix)
        if key == (2, 2):
            return self._apply_s2p2_event(int(value), now_unix)
```

Add the handler methods:

```python
    # s2p1 task_state code → current_activity
    _TASK_STATE_MAP: dict[int, "CurrentActivity"] = {}  # populated post-class

    def _apply_s2p1_task_state(
        self, task_state: int, now_unix: int
    ) -> StateSnapshot:
        from .state_snapshot import CurrentActivity, MowSession
        # Map raw task_state code to current_activity.
        activity_map: dict[int, CurrentActivity] = {
            1: CurrentActivity.MOWING,
            2: CurrentActivity.IDLE,
            5: CurrentActivity.RETURNING,
            6: CurrentActivity.CHARGE_RESUME,
        }
        new_activity = activity_map.get(task_state, self._snapshot.current_activity)
        # If task done while in session, also close the session.
        new_session = self._snapshot.mow_session
        if task_state == 2:
            new_session = MowSession.BETWEEN_SESSIONS
        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p1"] = now_unix
        if new_activity != self._snapshot.current_activity:
            freshness["current_activity"] = now_unix
        if new_session != self._snapshot.mow_session:
            freshness["mow_session"] = now_unix
        return self._replace(
            raw_s2p1=task_state,
            current_activity=new_activity,
            mow_session=new_session,
            field_freshness=freshness,
        )

    def _apply_s2p2_event(
        self, event_code: int, now_unix: int
    ) -> StateSnapshot:
        from .state_snapshot import CurrentActivity, MowSession, Location
        updates: dict[str, Any] = {"raw_s2p2": event_code}
        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p2"] = now_unix

        # Session start codes (mowing_started, scheduled_mowing_started)
        if event_code in (50, 53):
            updates["mow_session"] = MowSession.IN_SESSION
            updates["current_activity"] = CurrentActivity.MOWING
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix
        # Session end (mowing_complete)
        elif event_code == 48:
            updates["mow_session"] = MowSession.BETWEEN_SESSIONS
            updates["current_activity"] = CurrentActivity.IDLE
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix
        # Arrived at maintenance point
        elif event_code == 75:
            updates["location"] = Location.AT_POINT
            updates["current_activity"] = CurrentActivity.AT_POINT
            freshness["location"] = now_unix
            freshness["current_activity"] = now_unix

        updates["field_freshness"] = freshness
        return self._replace(**updates)
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_mqtt.py
git commit -m "feat(state): s2p1/s2p2 transitions (task state + event codes)"
```

---

## Task 5: TASK envelope handling — s2p50 and s2p56

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_mqtt.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
def test_s2p50_op_100_mow_dispatches_mowing():
    """TASK envelope with op=100 (global mow) → current_activity = MOWING."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 100, "exe": True, "status": True}},
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.last_task_op == 100
    assert snap.current_activity == CurrentActivity.MOWING


def test_s2p50_op_109_dispatches_cruise_no_session():
    """op=109 → CRUISING_TO_POINT and mow_session stays BETWEEN_SESSIONS."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 109, "exe": True, "status": True}},
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.last_task_op == 109
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT
    # Critical: cruise does NOT enter mow_session
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_s2p56_arrived_stage_transitions():
    """s2p56 [[N, 2]] (lifecycle stage 2) signals arrival."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    # Start cruise
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 109}}, now_unix=1000,
    )
    # Arrive
    sm.handle_mqtt_property(
        siid=2, piid=56,
        value={"status": [[1, 2]]}, now_unix=2000,
    )
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.AT_POINT


def test_s2p50_failed_status_does_not_transition():
    """`status: False` in TASK echo → don't transition activity."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 100, "status": False}},
        now_unix=1000,
    )
    # Failed status → activity stays IDLE (initial)
    assert sm.snapshot().current_activity == CurrentActivity.IDLE
    # But we still record the op attempt for diagnostics
    assert sm.snapshot().last_task_op == 100
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Extend handle_mqtt_property + add s2p50/s2p56 handlers**

In `state_machine.py`:

```python
        if key == (2, 50):
            return self._apply_s2p50_task_envelope(value, now_unix)
        if key == (2, 56):
            return self._apply_s2p56_lifecycle(value, now_unix)
```

Add handlers:

```python
    # op → starting activity (when status=True)
    _OP_TO_ACTIVITY: dict[int, "CurrentActivity"] = {}

    def _apply_s2p50_task_envelope(
        self, envelope: Any, now_unix: int
    ) -> StateSnapshot:
        """TASK echo: {t:'TASK', d:{o:<op>, exe:bool, status:bool, ...}}."""
        from .state_snapshot import CurrentActivity, MowSession
        if not isinstance(envelope, dict):
            return self._snapshot
        d = envelope.get("d")
        if not isinstance(d, dict):
            return self._snapshot
        op = d.get("o")
        if not isinstance(op, int):
            return self._snapshot
        status = bool(d.get("status", False))
        updates: dict[str, Any] = {"last_task_op": op}
        freshness = dict(self._snapshot.field_freshness)
        freshness["last_task_op"] = now_unix
        if status:
            # Op-code → starting activity
            op_map: dict[int, CurrentActivity] = {
                100: CurrentActivity.MOWING,
                101: CurrentActivity.MOWING,  # edge variant
                102: CurrentActivity.MOWING,  # zone variant
                103: CurrentActivity.MOWING,  # spot variant
                109: CurrentActivity.CRUISING_TO_POINT,
                10: CurrentActivity.FAST_MAPPING,
            }
            new_activity = op_map.get(op)
            if new_activity is not None:
                updates["current_activity"] = new_activity
                freshness["current_activity"] = now_unix
            # Mow ops also enter mow_session (NOT cruise / fast-mapping)
            if op in (100, 101, 102, 103):
                updates["mow_session"] = MowSession.IN_SESSION
                freshness["mow_session"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def _apply_s2p56_lifecycle(
        self, envelope: Any, now_unix: int
    ) -> StateSnapshot:
        """s2p56 = {status: [[task_id, lifecycle_stage]]}.
        stage 0 = started, stage 2 = arrived (cruise) / completed."""
        from .state_snapshot import CurrentActivity
        if not isinstance(envelope, dict):
            return self._snapshot
        statuses = envelope.get("status")
        if not isinstance(statuses, list) or not statuses:
            return self._snapshot
        first = statuses[0]
        if not isinstance(first, list) or len(first) < 2:
            return self._snapshot
        stage = first[1]
        # Stage 2 in a cruise context → arrived AT_POINT
        if stage == 2 and self._snapshot.current_activity == CurrentActivity.CRUISING_TO_POINT:
            freshness = dict(self._snapshot.field_freshness)
            freshness["current_activity"] = now_unix
            return self._replace(
                current_activity=CurrentActivity.AT_POINT,
                field_freshness=freshness,
            )
        return self._snapshot
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_mqtt.py
git commit -m "feat(state): s2p50 TASK envelope + s2p56 lifecycle routing"
```

---

## Task 6: handle_heartbeat (s1p1 decode + connectivity)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_heartbeat.py`

- [ ] **Step 1: Write the failing tests**

```python
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


def test_handle_heartbeat_propagates_wifi_rssi():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_heartbeat(_make_hb(wifi_rssi=-72), now_unix=1000)
    assert sm.snapshot().wifi_rssi_dbm == -72
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement handle_heartbeat**

Append to `state_machine.py`:

```python
    def handle_heartbeat(self, hb: Any, now_unix: int) -> StateSnapshot:
        """Apply a decoded s1p1 heartbeat.

        Always updates last_heartbeat_unix + sets mqtt_connectivity = ONLINE.
        Also propagates pin_required (emergency_stop bit) and wifi_rssi_dbm.
        """
        from .state_snapshot import Connectivity
        freshness = dict(self._snapshot.field_freshness)
        freshness["last_heartbeat_unix"] = now_unix
        freshness["mqtt_connectivity"] = now_unix
        updates: dict[str, Any] = {
            "last_heartbeat_unix": now_unix,
            "mqtt_connectivity": Connectivity.ONLINE,
        }
        if hb.emergency_stop != self._snapshot.pin_required:
            updates["pin_required"] = hb.emergency_stop
            freshness["pin_required"] = now_unix
        if hb.wifi_rssi_dbm != self._snapshot.wifi_rssi_dbm:
            updates["wifi_rssi_dbm"] = hb.wifi_rssi_dbm
            freshness["wifi_rssi_dbm"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_heartbeat.py
git commit -m "feat(state): handle_heartbeat sets connectivity + pin/rssi"
```

---

## Task 7: handle_cloud_poll — DOCK source with freshness precedence

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_cloud.py`

- [ ] **Step 1: Write the failing tests**

```python
"""handle_cloud_poll — DOCK source + freshness precedence."""
from __future__ import annotations


def test_cloud_dock_connect_status_sets_location():
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
        Location,
    )
    sm = MowerStateMachine()
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"connect_status": 0}, now_unix=1000,
    )
    assert snap.location == Location.ON_LAWN


def test_cloud_poll_does_not_overwrite_fresher_mqtt():
    """Per-field precedence: if MQTT updated location at t=2000, a cloud
    poll at t=1000 must NOT overwrite — even with a different value."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, CurrentActivity,
    )
    sm = MowerStateMachine()
    # Simulate MQTT-derived location update at t=2000
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
    # Cloud poll later → should overwrite
    snap = sm.handle_cloud_poll(
        source="DOCK", payload={"connect_status": 1}, now_unix=3000,
    )
    assert snap.location == Location.AT_DOCK
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement handle_cloud_poll**

Append to `state_machine.py`:

```python
    def handle_cloud_poll(
        self, source: str, payload: dict[str, Any], now_unix: int
    ) -> StateSnapshot:
        """Apply a cloud-poll result.

        Per-field precedence: only overwrite a field when the cloud
        poll's `now_unix` is GREATER than the field's last MQTT
        update stamp in field_freshness.
        """
        from .state_snapshot import Location, RpcHealth
        if source == "DOCK":
            return self._apply_cloud_dock(payload, now_unix)
        return self._snapshot

    def _apply_cloud_dock(
        self, payload: dict[str, Any], now_unix: int
    ) -> StateSnapshot:
        from .state_snapshot import Location
        connect = payload.get("connect_status")
        if connect is None:
            return self._snapshot
        new_location = Location.AT_DOCK if int(connect) == 1 else Location.ON_LAWN
        last_mqtt = self._snapshot.field_freshness.get("location", 0)
        if now_unix <= last_mqtt:
            # Cloud is stale relative to MQTT — skip
            return self._snapshot
        if new_location == self._snapshot.location:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        freshness["location"] = now_unix
        return self._replace(location=new_location, field_freshness=freshness)
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_cloud.py
git commit -m "feat(state): handle_cloud_poll DOCK source + freshness precedence"
```

---

## Task 8: tick — HB staleness + buffered s2p2=71 disambiguation

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_tick.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    # Unresolved → leave positioning_health at LOCALIZED (don't claim stuck)
    assert snap.positioning_health == PositioningHealth.LOCALIZED
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement buffering + tick**

Add to `state_machine.py`. In `__init__`:

```python
        # s2p2=71 disambiguation buffer
        self._s2p2_71_pending_since: int | None = None
        # Codes seen since the s2p2=71 event (within 30s window)
        self._s2p2_71_followups_codes: set[int] = set()
        self._s2p2_71_saw_returning: bool = False
```

Modify `_apply_s2p2_event` to start the buffer on event_code=71 AND to record follow-up codes when an existing buffer is active:

```python
        # Track follow-ups for s2p2=71 disambiguation
        if event_code == 71:
            self._s2p2_71_pending_since = now_unix
            self._s2p2_71_followups_codes = set()
            self._s2p2_71_saw_returning = False
        elif self._s2p2_71_pending_since is not None:
            self._s2p2_71_followups_codes.add(event_code)
```

In `_apply_s2p1_task_state` add (right at the top):

```python
        # If a s2p2=71 disambiguation is pending, record RETURNING follow-up
        if self._s2p2_71_pending_since is not None and task_state == 5:
            self._s2p2_71_saw_returning = True
```

Then the `tick` method:

```python
    HB_STALENESS_S: int = 90
    S2P2_71_WINDOW_S: int = 30

    def tick(self, now_unix: int) -> StateSnapshot:
        """Periodic resolver. Call ~every 10 seconds."""
        from .state_snapshot import Connectivity, PositioningHealth, Location
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)

        # 1) HB staleness check
        last_hb = self._snapshot.last_heartbeat_unix
        if last_hb is not None and (now_unix - last_hb) > self.HB_STALENESS_S:
            if self._snapshot.mqtt_connectivity != Connectivity.STALE:
                updates["mqtt_connectivity"] = Connectivity.STALE
                freshness["mqtt_connectivity"] = now_unix

        # 2) Resolve buffered s2p2=71
        pending = self._s2p2_71_pending_since
        if pending is not None and (now_unix - pending) >= self.S2P2_71_WINDOW_S:
            if 31 in self._s2p2_71_followups_codes or 33 in self._s2p2_71_followups_codes:
                # STUCK — hard positioning failure
                updates["positioning_health"] = PositioningHealth.STUCK
                updates["location"] = Location.OUTSIDE_KNOWN_AREA
                freshness["positioning_health"] = now_unix
                freshness["location"] = now_unix
            elif self._s2p2_71_saw_returning:
                # AUTO-RETURN — leave positioning_health LOCALIZED
                # (auto-recovery succeeded). Current activity is already
                # RETURNING via the s2p1=5 handler.
                pass
            else:
                # Unresolved — leave health alone, log for diagnostics
                _LOGGER.info(
                    "MowerStateMachine: s2p2=71 buffer expired with no "
                    "disambiguating follow-up; leaving positioning_health unchanged"
                )
            # Clear buffer either way
            self._s2p2_71_pending_since = None
            self._s2p2_71_followups_codes = set()
            self._s2p2_71_saw_returning = False

        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_tick.py
git commit -m "feat(state): tick — HB staleness + s2p2=71 disambiguation"
```

---

## Task 9: Persistence via HA Store

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py`
- Test: `tests/state_machine/test_state_machine_persistence.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Persistence — load_persisted / save_persisted via a mock Store."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def test_save_persisted_writes_serialised_snapshot():
    import asyncio
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    store = MagicMock()
    store.async_save = AsyncMock()

    asyncio.run(sm.save_persisted(store))

    store.async_save.assert_awaited_once()
    saved = store.async_save.await_args.args[0]
    assert isinstance(saved, dict)
    assert saved["battery_percent"] == 87


def test_load_persisted_restores_snapshot():
    import asyncio
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, CurrentActivity, Location,
    )
    sm = MowerStateMachine()
    initial = sm.snapshot()
    # Build a persisted dict from a non-initial snapshot
    import dataclasses
    persisted_snap = dataclasses.replace(
        initial,
        current_activity=CurrentActivity.MOWING,
        location=Location.ON_LAWN,
        battery_percent=42,
    )
    store = MagicMock()
    store.async_load = AsyncMock(return_value=persisted_snap.to_dict())

    asyncio.run(sm.load_persisted(store))

    assert sm.snapshot() == persisted_snap


def test_load_persisted_handles_missing_store_data():
    """No saved data → snapshot stays at initial."""
    import asyncio
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    sm = MowerStateMachine()
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)

    asyncio.run(sm.load_persisted(store))

    assert sm.snapshot() == StateSnapshot.initial()
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement persistence methods**

Append to `state_machine.py`:

```python
    async def save_persisted(self, store: Any) -> None:
        """Write the current snapshot to a HA Store-compatible object.

        `store` must implement async_save(data: dict)."""
        await store.async_save(self._snapshot.to_dict())
        self._clear_dirty()

    async def load_persisted(self, store: Any) -> None:
        """Restore snapshot from a HA Store-compatible object.

        `store` must implement async_load() -> dict | None. If None,
        the snapshot stays at its initial value."""
        raw = await store.async_load()
        if raw is None:
            return
        try:
            self._snapshot = StateSnapshot.from_dict(raw)
            self._dirty = False
        except (KeyError, ValueError) as ex:
            _LOGGER.warning(
                "MowerStateMachine: load_persisted failed (%s) — using initial", ex
            )
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_state_machine_persistence.py
git commit -m "feat(state): save/load via HA Store-shaped object"
```

---

## Task 10: Coordinator integration — plumb to state machine

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

This task wires the state machine into the coordinator AS A PARALLEL CONSUMER — both old `MowerState` mutation AND new state machine receive every MQTT message. Entities still read from `MowerState`. This is the safe intermediate step before flipping entities over.

- [ ] **Step 1: Add state machine to coordinator `__init__`**

In `coordinator.py` `__init__`:

```python
from .mower.state_machine import MowerStateMachine
from homeassistant.helpers.storage import Store

# At the appropriate point in __init__:
self.state_machine = MowerStateMachine()
self._state_store = Store(
    self.hass, version=1,
    key=f"dreame_a2_mower_state_{self.entry.entry_id}",
)
```

- [ ] **Step 2: Hook MQTT in `_on_mqtt_message`**

Find the MQTT message handler. Where each `properties_changed` param is processed, ALSO call:

```python
self.state_machine.handle_mqtt_property(
    siid=int(param.get("siid")),
    piid=int(param.get("piid")),
    value=param.get("value"),
    now_unix=int(time.time()),
)
```

Use a try/except so a state-machine error never breaks the existing path.

- [ ] **Step 3: Hook heartbeat decode**

In `_apply_s1p1_heartbeat`, after the existing decode, call:

```python
try:
    self.state_machine.handle_heartbeat(decoded, now_unix=int(time.time()))
except Exception:
    LOGGER.exception("state_machine.handle_heartbeat failed")
```

- [ ] **Step 4: Hook cloud DOCK refresh**

In `_refresh_dock` after the existing update, call:

```python
if isinstance(dock, dict):
    try:
        self.state_machine.handle_cloud_poll(
            source="DOCK", payload=dock, now_unix=int(time.time())
        )
    except Exception:
        LOGGER.exception("state_machine.handle_cloud_poll(DOCK) failed")
```

- [ ] **Step 5: Schedule the tick timer**

In `async_setup_entry` (where other periodic timers are registered):

```python
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval

@callback
def _state_machine_tick(_now):
    self.state_machine.tick(now_unix=int(time.time()))

self.entry.async_on_unload(
    async_track_time_interval(self.hass, _state_machine_tick, timedelta(seconds=10))
)
```

- [ ] **Step 6: Wire load_persisted on setup, save_persisted debounced**

In `async_config_entry_first_refresh` or equivalent:

```python
await self.state_machine.load_persisted(self._state_store)
```

Add a debounced save: in `_state_machine_tick`, if `self.state_machine.is_dirty()`:

```python
@callback
def _state_machine_tick(_now):
    self.state_machine.tick(now_unix=int(time.time()))
    if self.state_machine.is_dirty():
        self.hass.async_create_task(
            self.state_machine.save_persisted(self._state_store)
        )
```

- [ ] **Step 7: Run full suite + commit**

```
python -m pytest tests/ -q
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(state): wire state machine into coordinator as parallel consumer"
```

---

## Task 11: lawn_mower projection from snapshot

**Files:**
- Modify: `custom_components/dreame_a2_mower/lawn_mower.py`
- Test: `tests/state_machine/test_lawn_mower_projection.py`

- [ ] **Step 1: Write the failing tests**

```python
"""lawn_mower projection from StateSnapshot."""
from __future__ import annotations
import dataclasses


def _build_snapshot(**overrides):
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    return dataclasses.replace(StateSnapshot.initial(), **overrides)


def test_projection_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.MOWING,
        mow_session=MowSession.IN_SESSION,
    )
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_paused_in_session():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.PAUSED,
        mow_session=MowSession.IN_SESSION,
    )
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_idle_at_dock_is_docked():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, Location,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.IDLE,
        location=Location.AT_DOCK,
    )
    assert project_activity(s) == LawnMowerActivity.DOCKED


def test_projection_idle_on_lawn_is_paused():
    """KEY FIX: IDLE away from dock → PAUSED, not DOCKED."""
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, Location,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.IDLE,
        location=Location.AT_POINT,
    )
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_cruising_to_point_is_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.CRUISING_TO_POINT)
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_at_point_is_paused():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.AT_POINT)
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_returning():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.RETURNING)
    assert project_activity(s) == LawnMowerActivity.RETURNING


def test_projection_with_error_is_error():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.MOWING,
        errors=frozenset({27}),  # human_detected (BLOCKING enough to surface)
    )
    # ERROR wins over MOWING when any error is set
    assert project_activity(s) == LawnMowerActivity.ERROR
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Implement projection + reroute lawn_mower entity**

In `lawn_mower.py`, add the projection function near the top:

```python
def project_activity(snapshot) -> LawnMowerActivity:
    """Project the multi-dim snapshot down to HA's LawnMowerActivity enum."""
    from .mower.state_snapshot import (
        CurrentActivity as CA, Location as L, MowSession as MS,
    )
    if snapshot.errors:
        return LawnMowerActivity.ERROR
    ca = snapshot.current_activity
    if ca == CA.MOWING:
        return LawnMowerActivity.MOWING
    if ca == CA.PAUSED:
        return LawnMowerActivity.PAUSED
    if ca == CA.RETURNING:
        return LawnMowerActivity.RETURNING
    if ca == CA.CHARGE_RESUME:
        return LawnMowerActivity.DOCKED
    if ca == CA.IDLE:
        return (
            LawnMowerActivity.DOCKED
            if snapshot.location == L.AT_DOCK
            else LawnMowerActivity.PAUSED
        )
    if ca in (CA.CRUISING_TO_POINT, CA.FAST_MAPPING,
              CA.DRIVING_BLADES_UP, CA.REPOSITIONING):
        return LawnMowerActivity.MOWING
    if ca == CA.AT_POINT:
        return LawnMowerActivity.PAUSED
    return LawnMowerActivity.ERROR
```

Then update the `DreameA2LawnMower.activity` property:

```python
    @property
    def activity(self) -> LawnMowerActivity | None:
        snap = self.coordinator.state_machine.snapshot()
        return project_activity(snap)
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/lawn_mower.py tests/state_machine/test_lawn_mower_projection.py
git commit -m "feat(state): lawn_mower projects activity from snapshot"
```

---

## Task 12: binary_sensor migration (mower_in_dock + mowing_session_active)

**Files:**
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py`
- Test: `tests/state_machine/test_binary_sensor_resourcing.py`

- [ ] **Step 1: Write the failing tests**

```python
"""binary_sensor migration to snapshot fields."""
from __future__ import annotations
from unittest.mock import MagicMock


def _coord_with_snapshot(**overrides):
    import dataclasses
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    snap = dataclasses.replace(StateSnapshot.initial(), **overrides)
    coord.state_machine.snapshot.return_value = snap
    return coord


def test_mower_in_dock_true_when_location_at_dock():
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    from custom_components.dreame_a2_mower.binary_sensor import (
        DreameA2MowerInDockBinarySensor,
    )
    coord = _coord_with_snapshot(location=Location.AT_DOCK)
    s = DreameA2MowerInDockBinarySensor(coord)
    assert s.is_on is True


def test_mower_in_dock_false_when_location_elsewhere():
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    from custom_components.dreame_a2_mower.binary_sensor import (
        DreameA2MowerInDockBinarySensor,
    )
    for loc in (Location.ON_LAWN, Location.AT_POINT, Location.OUTSIDE_KNOWN_AREA):
        coord = _coord_with_snapshot(location=loc)
        s = DreameA2MowerInDockBinarySensor(coord)
        assert s.is_on is False, f"expected False for {loc}"


def test_mowing_session_active_true_only_in_mow_session():
    """Cruise must NOT trigger mowing_session_active."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    from custom_components.dreame_a2_mower.binary_sensor import (
        DreameA2MowingSessionActiveBinarySensor,
    )
    # In-mow → True
    coord_mow = _coord_with_snapshot(
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.MOWING,
    )
    assert DreameA2MowingSessionActiveBinarySensor(coord_mow).is_on is True
    # Cruise → False
    coord_cruise = _coord_with_snapshot(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.CRUISING_TO_POINT,
    )
    assert DreameA2MowingSessionActiveBinarySensor(coord_cruise).is_on is False
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Migrate the binary_sensor entities**

In `binary_sensor.py`, find `DreameA2MowerInDockBinarySensor` (or whatever the existing class is called) and update its `is_on`:

```python
    @property
    def is_on(self) -> bool | None:
        from .mower.state_snapshot import Location
        return self.coordinator.state_machine.snapshot().location == Location.AT_DOCK
```

For `DreameA2MowingSessionActiveBinarySensor`:

```python
    @property
    def is_on(self) -> bool | None:
        from .mower.state_snapshot import MowSession
        return (
            self.coordinator.state_machine.snapshot().mow_session
            == MowSession.IN_SESSION
        )
```

If the existing binary-sensor descriptors use `value_fn`, instead modify the value_fn:

```python
BinarySensorEntityDescription(
    key="mower_in_dock",
    name="In dock",
    value_fn=lambda coord: (
        coord.state_machine.snapshot().location.name == "AT_DOCK"
    ),
    ...
),
```

(Match the existing pattern in the file — whichever shape the descriptors use.)

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/binary_sensor.py tests/state_machine/test_binary_sensor_resourcing.py
git commit -m "feat(state): binary_sensor reads location + mow_session from snapshot"
```

---

## Task 13: New sensors for dimensional state

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Test: `tests/state_machine/test_new_dimension_sensors.py`

- [ ] **Step 1: Write the failing tests**

```python
"""New sensors for dimension state."""
from __future__ import annotations
import dataclasses
from unittest.mock import MagicMock


def _coord(**overrides):
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.state_machine.snapshot.return_value = dataclasses.replace(
        StateSnapshot.initial(), **overrides,
    )
    return coord


def test_current_activity_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CurrentActivitySensor,
    )
    coord = _coord(current_activity=CurrentActivity.CRUISING_TO_POINT)
    s = DreameA2CurrentActivitySensor(coord)
    assert s.native_value == "cruising_to_point"


def test_location_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2LocationSensor,
    )
    coord = _coord(location=Location.AT_POINT)
    s = DreameA2LocationSensor(coord)
    assert s.native_value == "at_point"


def test_positioning_health_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2PositioningHealthSensor,
    )
    coord = _coord(positioning_health=PositioningHealth.STUCK)
    s = DreameA2PositioningHealthSensor(coord)
    assert s.native_value == "stuck"


def test_mqtt_connectivity_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Connectivity,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MqttConnectivitySensor,
    )
    coord = _coord(mqtt_connectivity=Connectivity.STALE)
    s = DreameA2MqttConnectivitySensor(coord)
    assert s.native_value == "stale"
```

- [ ] **Step 2: Run; verify fails**

- [ ] **Step 3: Add four new sensor classes**

In `sensor.py`, append:

```python
class _SnapshotSensorBase(CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity):
    """Common base: reads from coordinator.state_machine.snapshot()."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _SNAPSHOT_FIELD: str = "override-me"
    _KEY: str = "override-me"
    _NAME: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, self._KEY)
        self._attr_device_info = mower_device_info(coordinator)
        self._attr_name = self._NAME

    @property
    def native_value(self):
        snap = self.coordinator.state_machine.snapshot()
        val = getattr(snap, self._SNAPSHOT_FIELD)
        return val.value if val is not None else None


class DreameA2CurrentActivitySensor(_SnapshotSensorBase):
    _SNAPSHOT_FIELD = "current_activity"
    _KEY = "current_activity"
    _NAME = "Current activity"
    _attr_icon = "mdi:robot-mower"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "mowing", "paused", "repositioning", "returning", "charge_resume",
        "cruising_to_point", "at_point", "fast_mapping",
        "driving_blades_up", "idle",
    ]


class DreameA2LocationSensor(_SnapshotSensorBase):
    _SNAPSHOT_FIELD = "location"
    _KEY = "mower_location"
    _NAME = "Location"
    _attr_icon = "mdi:map-marker"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["at_dock", "on_lawn", "at_point", "outside_known_area"]


class DreameA2PositioningHealthSensor(_SnapshotSensorBase):
    _SNAPSHOT_FIELD = "positioning_health"
    _KEY = "positioning_health"
    _NAME = "Positioning health"
    _attr_icon = "mdi:radar"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["localized", "relocating", "stuck"]


class DreameA2MqttConnectivitySensor(_SnapshotSensorBase):
    _SNAPSHOT_FIELD = "mqtt_connectivity"
    _KEY = "mqtt_connectivity"
    _NAME = "MQTT connectivity"
    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "stale"]
```

Add the four to `async_setup_entry`'s entity list.

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/sensor.py tests/state_machine/test_new_dimension_sensors.py
git commit -m "feat(state): new sensors for current_activity, location, etc."
```

---

## Task 14: Delete legacy MowerState + cleanup

After all consumers migrated, delete `mower/state.py` and any remaining references.

- [ ] **Step 1: Find remaining references**

```
grep -rn "from .mower.state import\|MowerState\b" custom_components/dreame_a2_mower/ tests/
```

For each match, replace `MowerState` reads with reads from `coordinator.state_machine.snapshot()`.

- [ ] **Step 2: Delete file**

```
git rm custom_components/dreame_a2_mower/mower/state.py
```

- [ ] **Step 3: Drop coordinator's per-slot mutation**

In `coordinator.py`, remove the legacy per-slot mutators (`_apply_s1p1_heartbeat`, `_apply_s2p1_*`, etc.) that wrote to the old `MowerState`. The state machine handles these now.

Remove any unused helpers (`FreshnessTracker` may stay if other code uses it; check).

- [ ] **Step 4: Run full suite**

```
python -m pytest tests/ -q
```

Fix any references the migration missed.

- [ ] **Step 5: Commit + release**

```
git add -A
git commit -m "refactor(state): delete legacy MowerState; entities read snapshot"
tools/release.sh 1.0.8a1
```

After release, reload the integration config entry on the live HA box. If entity orphans accumulate (`feedback_entity_rename_orphan`), delete-and-reinstall the integration in HA Settings.

---

## Self-Review

**Spec coverage:**

- Multi-dim state dimensions → Tasks 1, 4, 5, 7, 8 ✓
- `MowerStateMachine` class API → Tasks 2–9 ✓
- MQTT-primary, cloud reconciles → Task 7 ✓
- s2p2=71 disambiguation → Task 8 ✓
- Persistence via Store → Task 9 ✓
- Coordinator delegation → Task 10 ✓
- `lawn_mower` projection → Task 11 ✓
- `binary_sensor.mower_in_dock` + `mowing_session_active` re-source → Task 12 ✓
- New sensors for dimensional state → Task 13 ✓
- Delete legacy MowerState → Task 14 ✓
- No migration code per `feedback_no_migration_overengineering` ✓

**Placeholder scan:** no "TBD" / "fill in" / "similar to" markers. Each task has runnable code + exact commands.

**Type consistency:**

- `StateSnapshot` field names match across Tasks 1, 3–9 ✓
- Enum names (`CurrentActivity`, `Location`, etc.) consistent ✓
- `MowerStateMachine` method names (`handle_mqtt_property`, `handle_cloud_poll`, `handle_heartbeat`, `tick`, `snapshot`, `is_dirty`, `save_persisted`, `load_persisted`) consistent across tasks ✓
- Coordinator attribute `state_machine` used consistently from Task 10 onwards ✓

**Outstanding risk:** Tasks 12 / 13 assume specific existing class names in `binary_sensor.py` and `sensor.py`. The implementer must grep the actual class names first and adapt. The shapes are correct (CoordinatorEntity + per-snapshot reads); only the class identifiers may need adjustment.
