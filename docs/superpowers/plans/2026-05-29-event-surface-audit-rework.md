# Event-Surface Audit & Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add charging + rain-start lifecycle events, surface the rain-delay wait window as state, pin the notification lockstep with a test, finish the `alert`→`notification` rename, and refresh stale event docs.

**Architecture:** Two existing `EventEntity` instances (`event.dreame_a2_mower_lifecycle`, `event.dreame_a2_mower_notification`) dispatched from `coordinator._fire_lifecycle` / `_fire_notification`. One new coordinator field (`_rain_delay_started_at`) backs a new event + two state surfaces.

**Tech Stack:** Python 3.13, HA custom integration, pytest (stubbed-HA venv).

**Spec:** `docs/superpowers/specs/2026-05-29-event-surface-audit-rework-design.md`

**Test env:** `/data/claude/homeassistant/.venv-vanilla` — run pytest as
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`. Baseline: 1591 passed / 4 skipped.

**Fact-discipline:** This batch touches entity platform files and wire understanding. Task 8 records the required `inventory.yaml` / `entity-inventory.yaml` entries — do not skip it (CI `inventory-touch-gate` blocks otherwise).

---

### Task 1: Notification lockstep test

**Files:**
- Test: `tests/integration/test_notification_synthesizer.py` (append)

This invariant is today enforced only by a comment in `const.py`. Pin it so adding a slug to `S2P2_EVENT_TYPES` without updating `NOTIFICATION_EVENT_TYPES` fails CI instead of silently dropping the notification at the entity guard.

- [ ] **Step 1: Write the test**

Append to `tests/integration/test_notification_synthesizer.py`:

```python
def test_notification_event_types_cover_all_s2p2_slugs():
    """Every S2P2_EVENT_TYPES slug must be a declared NOTIFICATION_EVENT_TYPE.

    The notification EventEntity drops any event_type not in its declared
    _attr_event_types (= NOTIFICATION_EVENT_TYPES). If a slug is added to
    S2P2_EVENT_TYPES without updating const, that notification silently
    never fires. This pins the comment-only lockstep.
    """
    from custom_components.dreame_a2_mower.mower.error_codes import (
        S2P2_UNKNOWN_EVENT_TYPE,
    )

    declared = set(NOTIFICATION_EVENT_TYPES)
    for slug in set(S2P2_EVENT_TYPES.values()):
        assert slug in declared, f"{slug!r} fired but not declared on the entity"
    assert S2P2_UNKNOWN_EVENT_TYPE in declared


def test_logbook_message_tables_cover_all_event_types():
    """logbook.py holds the 3rd/4th hand-kept slug copies. Every declared
    event_type should have an explicit human message (the underscore-replace
    fallback works but is ugly)."""
    from custom_components.dreame_a2_mower import logbook as lb
    from custom_components.dreame_a2_mower.const import LIFECYCLE_EVENT_TYPES

    for slug in NOTIFICATION_EVENT_TYPES:
        assert slug in lb._NOTIFICATION_MESSAGES, f"logbook missing notif {slug!r}"
    for slug in LIFECYCLE_EVENT_TYPES:
        assert slug in lb._LIFECYCLE_MESSAGES, f"logbook missing lifecycle {slug!r}"
```

`S2P2_EVENT_TYPES` and `NOTIFICATION_EVENT_TYPES` are already imported at the top of this test file.

- [ ] **Step 2: Run — expect PASS**

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_notification_synthesizer.py -q`
Expected: PASS (the lockstep currently holds; this pins it). The lifecycle-coverage half also passes against the current 6-event table.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_notification_synthesizer.py
git commit -m "test: pin notification event-type lockstep + logbook message coverage"
```

---

### Task 2: `alert` → `notification` rename (coordinator plumbing)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_device_sync.py` (register_event_entities ~302, _fire_notification ~404)
- Modify: `custom_components/dreame_a2_mower/event.py` (~42)
- Test: grep + update any test passing `alert=` or reading `_alert_event`

Pure refactor — the entity is already `notification`; finish the field/param naming.

- [ ] **Step 1: Find callers**

```bash
grep -rn "_alert_event\|register_event_entities\|alert=" custom_components/dreame_a2_mower tests --include=*.py | grep -v __pycache__
```

- [ ] **Step 2: Rename in `_device_sync.py`**

`register_event_entities` signature + body:
```python
    def register_event_entities(self, *, lifecycle: Any, notification: Any) -> None:
        """Called from event.py's async_setup_entry to wire the event
        entities the coordinator's dispatcher fires through.

        Stored as plain attributes (no weakref needed — entities live
        for the integration's lifetime).
        """
        self._lifecycle_event = lifecycle
        self._notification_event = notification
```

In `_fire_notification`, change `ent = self._alert_event` to:
```python
        ent = self._notification_event
```
(Drop the now-obsolete "attribute name preserved for test/setup compat" comment.)

- [ ] **Step 3: Update the `event.py` setup call**

```python
    coordinator.register_event_entities(lifecycle=lifecycle, notification=notification)
```

- [ ] **Step 4: Update `_CoreMixin.__init__`** if it pre-initialises `self._alert_event = None`

```bash
grep -n "_alert_event\|_lifecycle_event\|_notification_event" custom_components/dreame_a2_mower/coordinator/_core.py
```
Rename any `self._alert_event = None` to `self._notification_event = None`.

- [ ] **Step 5: Update tests** found in Step 1 — any `register_event_entities(..., alert=x)` → `notification=x`; any `coord._alert_event` → `coord._notification_event`.

- [ ] **Step 6: Run — expect PASS**

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/event tests/integration/test_notification_synthesizer.py -q`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename coordinator alert→notification event field/param"
```

---

### Task 3: New lifecycle event_types — declaration layer

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py` (~31-46)
- Modify: `custom_components/dreame_a2_mower/logbook.py` (`_LIFECYCLE_MESSAGES`)
- Modify: `custom_components/dreame_a2_mower/translations/en.json` (`entity.event.lifecycle.state`)
- Test: `tests/event/test_event_module.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/event/test_event_module.py`:
```python
def test_lifecycle_declares_new_event_types():
    from custom_components.dreame_a2_mower.const import LIFECYCLE_EVENT_TYPES
    for slug in ("charging_started", "charging_complete", "rain_delay_started"):
        assert slug in LIFECYCLE_EVENT_TYPES
```

- [ ] **Step 2: Run — expect FAIL** (`charging_started` not in tuple)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/event/test_event_module.py::test_lifecycle_declares_new_event_types -q`

- [ ] **Step 3: Add constants + tuple entries in `const.py`**

After `EVENT_TYPE_DOCK_DEPARTED`:
```python
EVENT_TYPE_CHARGING_STARTED: Final = "charging_started"
EVENT_TYPE_CHARGING_COMPLETE: Final = "charging_complete"
EVENT_TYPE_RAIN_DELAY_STARTED: Final = "rain_delay_started"
```
Append to `LIFECYCLE_EVENT_TYPES`:
```python
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_CHARGING_STARTED,
    EVENT_TYPE_CHARGING_COMPLETE,
    EVENT_TYPE_RAIN_DELAY_STARTED,
)
```

- [ ] **Step 4: Add logbook messages** to `_LIFECYCLE_MESSAGES` in `logbook.py`:
```python
    "dock_departed": "left the dock",
    "charging_started": "started charging",
    "charging_complete": "finished charging",
    "rain_delay_started": "paused for rain — waiting out the delay",
```

- [ ] **Step 5: Add translations.** In `translations/en.json`, under `entity.event.lifecycle.state` (inspect the file for exact path first — `grep -n "lifecycle" custom_components/dreame_a2_mower/translations/en.json`), add the three keys mirroring the existing lifecycle state labels:
```json
"charging_started": "Started charging",
"charging_complete": "Finished charging",
"rain_delay_started": "Rain delay started"
```

- [ ] **Step 6: Run — expect PASS** (both the new test and Task 1's logbook-coverage test)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/event -q`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: declare charging + rain_delay_started lifecycle event_types"
```

---

### Task 4: Charging lifecycle events (fire sites)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (`__init__`, near line 127)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (import + `_on_state_update`, after the dock edge ~443)
- Test: `tests/integration/` (new or existing event-fire test module)

Wire: `charging_status` (s3.2) enum `NOT_CHARGING=0, CHARGING=1, CHARGED=2`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_charging_events.py`:
```python
"""charging_started / charging_complete fire on s3.2 rising edges."""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.state import ChargingStatus, MowerState


class _FakeLifecycle:
    def __init__(self):
        self.fired = []
    def trigger(self, event_type, data):
        self.fired.append((event_type, data))


def _coord(monkeypatch):
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    # minimal state the charging-edge block touches:
    c._prev_charging_status = None
    c._prev_task_state = None
    c._prev_in_dock = None
    c._prev_error_code = None
    c._rain_delay_started_at = None
    lc = _FakeLifecycle()
    c._lifecycle_event = lc
    c._notification_event = None
    return c, lc


def test_charging_started_fires_on_edge_into_charging(monkeypatch):
    c, lc = _coord(monkeypatch)
    # prime (first observation does not fire)
    c._maybe_fire_charging_events(ChargingStatus.NOT_CHARGING, now_unix=100, battery=50)
    assert lc.fired == []
    # rising edge → CHARGING
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=200, battery=55)
    assert lc.fired == [("charging_started", {"at_unix": 200, "battery_level": 55})]


def test_charging_complete_fires_on_edge_into_charged(monkeypatch):
    c, lc = _coord(monkeypatch)
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=100, battery=90)
    lc.fired.clear()
    c._maybe_fire_charging_events(ChargingStatus.CHARGED, now_unix=300, battery=100)
    assert lc.fired == [("charging_complete", {"at_unix": 300, "battery_level": 100})]


def test_no_refire_on_same_status(monkeypatch):
    c, lc = _coord(monkeypatch)
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=100, battery=90)
    lc.fired.clear()
    c._maybe_fire_charging_events(ChargingStatus.CHARGING, now_unix=110, battery=91)
    assert lc.fired == []
```

This pins the edge logic in an extracted helper `_maybe_fire_charging_events` (keeps `_on_state_update` readable and unit-testable without a full state pipeline).

- [ ] **Step 2: Run — expect FAIL** (no `_maybe_fire_charging_events`)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_charging_events.py -q`

- [ ] **Step 3: Add `_prev_charging_status` to `_CoreMixin.__init__`**

In `_core.py` near the other prev-trackers (after line 127 `self._prev_in_dock`):
```python
        self._prev_charging_status: int | None = None
```

- [ ] **Step 4: Add the helper + call it.** In `_mqtt_handlers.py`, add the `EVENT_TYPE_CHARGING_STARTED` / `EVENT_TYPE_CHARGING_COMPLETE` imports to the existing `from ..const import (...)` block, then add this method to `_MqttHandlersMixin`:

```python
    def _maybe_fire_charging_events(
        self, charging_status, now_unix: int, battery: int | None
    ) -> None:
        """Fire charging_started / charging_complete on s3.2 rising edges.

        Distinct from dock_arrived (cloud DOCK connect_status): this is the
        energy-state. First observation only primes _prev (no spurious fire
        for whatever charging state was active at HA boot).
        """
        if charging_status is None:
            return
        new_val = charging_status.value if hasattr(charging_status, "value") else int(charging_status)
        prev = self._prev_charging_status
        if prev is not None and new_val != prev:
            if new_val == 1:  # ChargingStatus.CHARGING
                self._fire_lifecycle(
                    EVENT_TYPE_CHARGING_STARTED,
                    {"at_unix": int(now_unix), "battery_level": battery},
                )
            elif new_val == 2:  # ChargingStatus.CHARGED
                self._fire_lifecycle(
                    EVENT_TYPE_CHARGING_COMPLETE,
                    {"at_unix": int(now_unix), "battery_level": battery},
                )
        self._prev_charging_status = new_val
```

Call it in `_on_state_update` right after the dock arrival/departure block (after line 443 `self._prev_in_dock = _sm_at_dock`):
```python
        self._maybe_fire_charging_events(
            new_state.charging_status, now_unix, new_state.battery_level
        )
```

- [ ] **Step 5: Run — expect PASS**

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_charging_events.py -q`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: charging_started/charging_complete lifecycle events (s3.2 edges)"
```

---

### Task 5: `rain_delay_started` event + rain-delay state field

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (`__init__` + two properties)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (set on 56-edge + fire; clear at dock_departed)
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` (clear at finalize)
- Test: `tests/integration/test_rain_delay.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_rain_delay.py`:
```python
"""rain_delay_started_at lifecycle: set on s2p2→56, derived properties, clear."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord():
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c._rain_delay_started_at = None
    c.data = MowerState()
    return c


def test_rain_resume_at_none_when_not_raining():
    c = _coord()
    assert c.rain_resume_at_unix is None
    assert c.rain_delay_active is False


def test_rain_resume_at_projects_from_resume_hours():
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = 2
    assert c.rain_resume_at_unix == 1000 + 2 * 3600


def test_rain_delay_active_within_window(monkeypatch):
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = 2  # resume_at = 8200
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.coordinator._core.time.time",
        lambda: 5000,
    )
    assert c.rain_delay_active is True
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.coordinator._core.time.time",
        lambda: 9000,  # past resume_at
    )
    assert c.rain_delay_active is False


def test_rain_delay_active_unbounded_when_resume_hours_unknown():
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = None
    assert c.rain_resume_at_unix is None
    assert c.rain_delay_active is True
```

- [ ] **Step 2: Run — expect FAIL** (no `rain_resume_at_unix` property)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_rain_delay.py -q`

- [ ] **Step 3: Add field + properties to `_CoreMixin`.** Confirm `_core.py` imports `time` at module top (`import time`); if not, add it. In `__init__` near the prev-trackers:
```python
        self._rain_delay_started_at: int | None = None
```
Add the two properties to `_CoreMixin` (alongside the other `@property` defs):
```python
    @property
    def rain_resume_at_unix(self) -> int | None:
        """Projected unix time the mower retries after a rain delay."""
        started = self._rain_delay_started_at
        if started is None:
            return None
        hours = self.data.rain_protection_resume_hours
        if not hours:
            return None
        return int(started) + int(hours) * 3600

    @property
    def rain_delay_active(self) -> bool:
        """True while the mower is waiting out the rain-protection timer."""
        if self._rain_delay_started_at is None:
            return False
        resume_at = self.rain_resume_at_unix
        if resume_at is None:
            return True
        return time.time() < resume_at
```

- [ ] **Step 4: Set + fire on the s2p2→56 rising edge.** In `_mqtt_handlers.py`, add `EVENT_TYPE_RAIN_DELAY_STARTED` to the const import block. In `_on_state_update`, inside the existing error-code transition block (the `if new_error_code is not None and new_error_code != old_error_code and old_error_code is not None:` body, where `_resolve_s2p2_notification` is scheduled), add — guarded so it only fires on the rising edge into 56:
```python
            if new_error_code == 56 and old_error_code != 56:
                self._rain_delay_started_at = int(now_unix)
                self._fire_lifecycle(
                    EVENT_TYPE_RAIN_DELAY_STARTED, {"at_unix": int(now_unix)}
                )
```

- [ ] **Step 5: Clear at `dock_departed`.** In the dock falling-edge branch (`elif self._prev_in_dock is True and not _sm_at_dock:`), after firing `EVENT_TYPE_DOCK_DEPARTED`:
```python
            self._rain_delay_started_at = None  # left dock → rain wait over
```

- [ ] **Step 6: Clear at finalize.** In `_session.py`, find the finalize/end path (e.g. `_run_finalize_incomplete` ~520 and the FINALIZE_COMPLETE path) and set `self._rain_delay_started_at = None` where the session is being closed out. Grep for where `settings_snapshot` is reset at session end and clear alongside it.

- [ ] **Step 7: Add a fire-edge test** to `test_rain_delay.py`:
```python
def test_fires_and_sets_started_at_on_edge_into_56():
    class _LC:
        def __init__(self): self.fired = []
        def trigger(self, t, d): self.fired.append((t, d))
    c = _coord()
    lc = _LC(); c._lifecycle_event = lc
    c._fire_rain_delay_started_if_edge(old=0, new=56, now_unix=500)
    assert c._rain_delay_started_at == 500
    assert lc.fired == [("rain_delay_started", {"at_unix": 500})]
    # no refire while already 56
    lc.fired.clear()
    c._fire_rain_delay_started_if_edge(old=56, new=56, now_unix=600)
    assert lc.fired == []
```
To make this unit-testable, extract the Step-4 logic into a small helper `_fire_rain_delay_started_if_edge(self, *, old, new, now_unix)` on `_MqttHandlersMixin` and call it from `_on_state_update` (passing `old_error_code` / `new_error_code`). The helper body is the Step-4 `if`.

- [ ] **Step 8: Run — expect PASS**

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_rain_delay.py -q`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: rain_delay_started event + rain_delay_started_at state field"
```

---

### Task 6: Fix `binary_sensor.rain_protection_active`

**Files:**
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py` (~61)
- Test: `tests/integration/test_binary_sensors.py` (or wherever rain_protection_active is tested — grep first)

- [ ] **Step 1: Write/adjust the failing test.** Grep for the existing rain_protection test:
```bash
grep -rn "rain_protection_active" tests --include=*.py | grep -v __pycache__
```
Add to the appropriate test module:
```python
def test_rain_protection_active_reads_whole_window(monkeypatch):
    """rain_protection_active is on for the whole wait window, not just the
    instant error_code==56 (the retracted momentary-flash bug)."""
    from custom_components.dreame_a2_mower.binary_sensor import BINARY_SENSORS
    desc = next(d for d in BINARY_SENSORS if d.key == "rain_protection_active")

    class _Coord:
        rain_delay_active = True
    assert desc.value_fn(_Coord()) is True
    class _Coord2:
        rain_delay_active = False
    assert desc.value_fn(_Coord2()) is False
```

- [ ] **Step 2: Run — expect FAIL** (value_fn still reads `coord.data.error_code == 56`)

- [ ] **Step 3: Repoint the value_fn** in `binary_sensor.py`:
```python
    DreameA2BinarySensorEntityDescription(
        key="rain_protection_active",
        translation_key="rain_protection_active",
        name="Rain protection active",
        device_class=BinarySensorDeviceClass.MOISTURE,
        # On for the whole rain-delay wait window (backed by
        # coordinator.rain_delay_active = _rain_delay_started_at within
        # resume_hours). The previous `error_code == 56` was true only for
        # the instant of the rain push — see entity-inventory retraction.
        value_fn=lambda coord: coord.rain_delay_active,
    ),
```

- [ ] **Step 4: Run — expect PASS** (+ confirm no other rain_protection test regressed)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_binary_sensors.py -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix: rain_protection_active reads the whole wait window, not the 56 flash"
```

---

### Task 7: `sensor.dreame_a2_mower_rain_resume_at` (timestamp countdown)

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_device.py` (new class near `DreameA2WifiRefreshStatusSensor`)
- Modify: `custom_components/dreame_a2_mower/sensor.py` (re-export + register in `async_setup_entry`)
- Test: `tests/integration/test_rain_delay.py` (append)

- [ ] **Step 1: Write the failing test** (append to `test_rain_delay.py`):
```python
def test_rain_resume_sensor_native_value():
    from datetime import UTC, datetime
    from custom_components.dreame_a2_mower.sensor_device import DreameA2RainResumeSensor

    c = _coord()
    s = DreameA2RainResumeSensor.__new__(DreameA2RainResumeSensor)
    s.coordinator = c
    assert s.native_value is None
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = 1
    assert s.native_value == datetime.fromtimestamp(1000 + 3600, tz=UTC)
```

- [ ] **Step 2: Run — expect FAIL** (no `DreameA2RainResumeSensor`)

- [ ] **Step 3: Add the class** in `sensor_device.py` (after `DreameA2WifiRefreshStatusSensor`). Confirm `from datetime import UTC, datetime` is already imported at the top of the file (it's used by the existing TIMESTAMP sensors):
```python
class DreameA2RainResumeSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """When the mower will retry mowing after a rain-protection delay.

    State is the projected resume time (rain_delay_started_at +
    resume_hours), rendered by HA as a live "in N hours" countdown via
    SensorDeviceClass.TIMESTAMP — no server-side ticking. Unknown when
    the mower is not in a rain delay. See
    docs/superpowers/specs/2026-05-29-event-surface-audit-rework-design.md.
    """

    _attr_has_entity_name = True
    _attr_name = "Rain resume at"
    _attr_icon = "mdi:weather-rainy"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "rain_resume_at")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> datetime | None:
        ts = self.coordinator.rain_resume_at_unix
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=UTC)
```
(`mower_unique_id` / `mower_device_info` are already imported in `sensor_device.py` — confirm with a grep; they back the other mower-level sensors.)

- [ ] **Step 4: Register + re-export** in `sensor.py`. Add `DreameA2RainResumeSensor` to the `from .sensor_device import (...)` block and to the mower-level entity list in `async_setup_entry`:
```python
            DreameA2RainResumeSensor(coordinator),
```

- [ ] **Step 5: Run — expect PASS**

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_rain_delay.py -q`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: sensor.rain_resume_at timestamp countdown for the rain-delay wait"
```

---

### Task 8: Docs + fact-discipline records

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (s2p2=56, s3.2)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (lifecycle event entity, rain_protection_active, new rain_resume_at sensor)
- Modify: `docs/events.md`

- [ ] **Step 1: `inventory.yaml`.** On the s2p2 entry (the error_code surface), append a verification:
```yaml
      - date: "2026-05-29"
        status: verified
        claim: "Firmware emits a rain-protection START signal only (s2p2→56); no rain-END code is ever sent. The integration fires rain_delay_started on the 56 rising edge and does NOT infer an end."
        evidence: "app-notification-history-2026-05-16.md § Empirical s2p2 mapping; live capture 2026-05-26"
```
On the s3.2 (charging_status) entry, append:
```yaml
      - date: "2026-05-29"
        status: verified
        claim: "charging_started / charging_complete lifecycle events fire on s3.2 rising edges into CHARGING(1) / CHARGED(2)."
        evidence: "mower/state.py:ChargingStatus enum; coordinator/_mqtt_handlers.py:_maybe_fire_charging_events"
```
Update both rows' `status.last_seen` to `"2026-05-29"`.

- [ ] **Step 2: `entity-inventory.yaml`.** Update `binary_sensor.dreame_a2_mower_rain_protection_active` with a verification recording the fix:
```yaml
      - date: "2026-05-29"
        status: verified
        claim: "rain_protection_active now reads coordinator.rain_delay_active (the whole rain-delay wait window), implementing the documented remediation."
        evidence: "binary_sensor.py value_fn=lambda coord: coord.rain_delay_active"
        retracts: "binary_sensor.rain_protection_active reads true while the mower is in the rain-protection wait window"
        reason: "Prior impl was error_code==56 which is only true for the instant of the rain push; the field-backed window is the fix the prior retraction asked for."
```
Add a new entity row for `sensor.dreame_a2_mower_rain_resume_at` (TIMESTAMP, source `coordinator.rain_resume_at_unix`), and a verification on the lifecycle event entity row noting the 3 new event_types. Follow the existing row schema in the file.

- [ ] **Step 3: Refresh `docs/events.md`.** Rename the `event.dreame_a2_mower_alert` row to `event.dreame_a2_mower_notification`, drop "Reserved for the alert-tier release" (the tier is live — cloud-sourced s2p2 text), and add reference entries for `charging_started`, `charging_complete`, `rain_delay_started` (payloads per the spec). Note rain has no `_ended` event by design.

- [ ] **Step 4: Run the inventory audit**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_audit.py --consistency
```
Expected: no new contradictions.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: record charging/rain events + rain_protection fix; refresh events.md"
```

---

### Task 9: Full suite + release

- [ ] **Step 1: Full test run — expect green** (baseline 1591 passed / 4 skipped, plus the new tests)

`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`

- [ ] **Step 2: Release** (handles bump → tag → push → GitHub Release → HACS refresh):

```bash
tools/release.sh
```
Target `1.0.19a9` (single-digit alpha — safe per the HACS string-sort ladder; the *next* bump after a9 must jump to `1.0.20a1`).

- [ ] **Step 3: Report** the released version + a one-line summary of the new event/sensor surface for the user to validate on the live mower.

---

## Self-review notes
- Type consistency: `_maybe_fire_charging_events` + `_fire_rain_delay_started_if_edge` are the extracted helpers referenced by both `_on_state_update` and the unit tests. `rain_resume_at_unix` / `rain_delay_active` are the property names used by the sensor, the binary_sensor, and the tests. `_rain_delay_started_at` / `_prev_charging_status` are the only new `__init__` fields (both in `_CoreMixin`, per the coordinator rule).
- The lockstep test (Task 1) passes immediately — it's a regression guard for an existing invariant, not a red-first TDD step; Step 2 says expect PASS deliberately.
- Tasks 4/5 construct the coordinator via `__new__` to avoid the full HA pipeline; this matches the existing test style (`getattr`-guarded `state_machine`/`hass` in `_on_state_update`).
