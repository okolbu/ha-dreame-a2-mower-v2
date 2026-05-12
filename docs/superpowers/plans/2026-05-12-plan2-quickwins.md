# Plan 2 quick-wins implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 4 of the 9 "Plan 2" dashboard placeholders with real entities — all using data the integration already decodes. Cover map metadata, maintenance points (read-only), per-map session totals, and a unified mowing-mode picker.

**Architecture:** Add per-map sensor entities that read from `coordinator._cached_maps_by_id[map_id]` (already populated by the map decoder). Aggregate session archive by `map_id` for totals. Add a unified `MowingMode` select that delegates to existing zone/spot/edge selects underneath. Update dashboard YAML to replace the placeholder markdown cards with the real entities.

**Tech stack:** Python 3.13, HA custom_component, pytest. No cloud-write paths needed for any of these 4 tasks; all are read-side or UX-layer.

**Out of scope (deferred):**
- Head to Maintenance Point button (#5) — blocked on capturing the cloud op code for cruise-to-point. Pick this up after a single app-tap is captured in `probe_log_*.jsonl`.
- Other 4 Plan-2 items (custom mode, per-map obstacle settings, ignore-zone services, per-map T7 schedule) — each needs protocol research.

---

## File Structure

**Files to modify:**
- `custom_components/dreame_a2_mower/sensor.py` — add 4 per-map sensor classes + per-map sub-device registration
- `custom_components/dreame_a2_mower/select.py` — add `DreameA2MowingModeSelect` per-map class
- `dashboards/mower/dashboard.yaml` — replace 4 Plan 2 placeholder markdown cards with entity cards

**Files to create:**
- `tests/integration/test_per_map_metadata_sensors.py` — sensors for name/area/segments
- `tests/integration/test_maintenance_points_sensor.py` — maintenance-points read-side
- `tests/integration/test_per_map_session_totals.py` — aggregate over session archive
- `tests/integration/test_mowing_mode_select.py` — unified picker delegation

---

## Task 1: Per-map metadata sensors (name, area, segment count)

**Goal:** Expose three per-map sensors using `MapData` fields already decoded. Each map gets its own sub-device (per `_devices.py:map_unique_id`/`map_device_info`).

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Test: `tests/integration/test_per_map_metadata_sensors.py`

### Step 1: Write the failing tests

Create `tests/integration/test_per_map_metadata_sensors.py`:

```python
"""Per-map name / area / segment-count sensors."""
from unittest.mock import MagicMock


def _make_coord_with_two_maps():
    """Two maps, both decoded into MapData-shaped objects."""
    coord = MagicMock()
    coord.entry.entry_id = "fake"

    map0 = MagicMock()
    map0.name = "Front lawn"
    map0.total_area = 240.5
    map0.mowing_areas = (MagicMock(), MagicMock(), MagicMock())  # 3 segments
    map1 = MagicMock()
    map1.name = "Back garden"
    map1.total_area = 410.0
    map1.mowing_areas = (MagicMock(),)  # 1 segment

    coord._cached_maps_by_id = {0: map0, 1: map1}
    coord.data = MagicMock()
    return coord


def test_map_name_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapNameSensor
    coord = _make_coord_with_two_maps()
    sensor0 = DreameA2MapNameSensor(coord, map_id=0)
    sensor1 = DreameA2MapNameSensor(coord, map_id=1)
    assert sensor0.native_value == "Front lawn"
    assert sensor1.native_value == "Back garden"


def test_map_area_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapAreaSensor
    coord = _make_coord_with_two_maps()
    sensor0 = DreameA2MapAreaSensor(coord, map_id=0)
    sensor1 = DreameA2MapAreaSensor(coord, map_id=1)
    assert sensor0.native_value == 240.5
    assert sensor1.native_value == 410.0
    assert sensor0.native_unit_of_measurement == "m²"


def test_map_segment_count_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapSegmentCountSensor
    coord = _make_coord_with_two_maps()
    sensor0 = DreameA2MapSegmentCountSensor(coord, map_id=0)
    sensor1 = DreameA2MapSegmentCountSensor(coord, map_id=1)
    assert sensor0.native_value == 3
    assert sensor1.native_value == 1


def test_sensors_returns_none_when_map_absent():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapNameSensor,
        DreameA2MapAreaSensor,
        DreameA2MapSegmentCountSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._cached_maps_by_id = {}  # no maps
    for cls in (DreameA2MapNameSensor, DreameA2MapAreaSensor, DreameA2MapSegmentCountSensor):
        s = cls(coord, map_id=0)
        assert s.native_value is None


def test_sensors_attached_to_map_subdevice():
    """Each per-map sensor lives under the map_id sub-device (via_device)."""
    from custom_components.dreame_a2_mower.sensor import DreameA2MapNameSensor
    coord = _make_coord_with_two_maps()
    sensor0 = DreameA2MapNameSensor(coord, map_id=0)
    info = sensor0._attr_device_info
    # Per _devices.map_device_info, identifiers are (DOMAIN, f"{sn}_map_{map_id}")
    ident = list(info["identifiers"])[0]
    assert ident[1].endswith("_map_0")
```

### Step 2: Run; confirm fail

```
python -m pytest tests/integration/test_per_map_metadata_sensors.py -v
```
Expected: `ImportError: cannot import name 'DreameA2MapNameSensor' ...`

### Step 3: Implement the three sensor classes

In `custom_components/dreame_a2_mower/sensor.py`, near the existing sensor classes (search for `DreameA2WifiRefreshStatusSensor` as an anchor for placement), add:

```python
class _DreameA2PerMapSensorBase(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Common scaffolding for per-map sensors.

    Each sensor lives under its own map sub-device (per
    `_devices.map_device_info`). Subclasses set `_KEY` and override
    `_compute_value(map_data)`.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _KEY: str = "override-me"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        from ._devices import map_unique_id, map_device_info
        self._attr_unique_id = map_unique_id(coordinator, map_id, self._KEY)
        self._attr_device_info = map_device_info(coordinator, map_id)

    def _map(self):
        return self.coordinator._cached_maps_by_id.get(self._map_id)

    def _compute_value(self, map_data):
        raise NotImplementedError

    @property
    def native_value(self):
        m = self._map()
        if m is None:
            return None
        return self._compute_value(m)


class DreameA2MapNameSensor(_DreameA2PerMapSensorBase):
    _attr_name = "Name"
    _attr_translation_key = "map_name"
    _attr_icon = "mdi:label-outline"
    _KEY = "name"

    def _compute_value(self, m):
        return getattr(m, "name", None)


class DreameA2MapAreaSensor(_DreameA2PerMapSensorBase):
    _attr_name = "Area"
    _attr_translation_key = "map_area"
    _attr_icon = "mdi:vector-square"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "area"

    def _compute_value(self, m):
        return getattr(m, "total_area", None)


class DreameA2MapSegmentCountSensor(_DreameA2PerMapSensorBase):
    _attr_name = "Segments"
    _attr_translation_key = "map_segments"
    _attr_icon = "mdi:vector-polyline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "segments"

    def _compute_value(self, m):
        areas = getattr(m, "mowing_areas", ())
        return len(areas) if areas is not None else 0
```

In `async_setup_entry` (search for where other per-map entities are added — look for `for map_id in sorted(coordinator._cached_maps_by_id.keys()):` analog if it exists; the sensor platform may not have one yet), add a loop:

```python
for map_id in sorted(coordinator._cached_maps_by_id.keys()):
    entities.extend([
        DreameA2MapNameSensor(coordinator, map_id=map_id),
        DreameA2MapAreaSensor(coordinator, map_id=map_id),
        DreameA2MapSegmentCountSensor(coordinator, map_id=map_id),
    ])
```

If no such loop exists yet in `sensor.py:async_setup_entry`, add the import for `SensorStateClass` if missing (`from homeassistant.components.sensor import SensorStateClass`).

### Step 4: Run tests; confirm pass

```
python -m pytest tests/integration/test_per_map_metadata_sensors.py -v
python -m pytest tests/ -q
```

### Step 5: Commit

```
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_per_map_metadata_sensors.py
git commit -m "feat: per-map metadata sensors (name, area, segments)"
```

---

## Task 2: Maintenance Points sensor (per-map, read-only)

**Goal:** A per-map sensor whose state is the count of maintenance points, with the full point list (id, x_mm, y_mm) as `extra_state_attributes`. Mirrors the inventoried-but-not-implemented `sensor.maintenance_points_count` from `inventory.yaml`.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Test: `tests/integration/test_maintenance_points_sensor.py`

### Step 1: Write the failing test

```python
"""Per-map maintenance-points sensor."""
from unittest.mock import MagicMock


def _make_coord_with_points():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    point1 = MagicMock()
    point1.point_id = 1
    point1.x_mm = 2820.0
    point1.y_mm = 12760.0
    point2 = MagicMock()
    point2.point_id = 5
    point2.x_mm = 1500.0
    point2.y_mm = 800.0
    map0.maintenance_points = (point1, point2)
    coord._cached_maps_by_id = {0: map0}
    coord.data = MagicMock()
    return coord


def test_maintenance_points_sensor_count_is_state():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = _make_coord_with_points()
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    assert sensor.native_value == 2


def test_maintenance_points_sensor_points_in_attributes():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = _make_coord_with_points()
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    attrs = sensor.extra_state_attributes
    assert "points" in attrs
    assert len(attrs["points"]) == 2
    assert attrs["points"][0] == {"id": 1, "x_mm": 2820.0, "y_mm": 12760.0}
    assert attrs["points"][1] == {"id": 5, "x_mm": 1500.0, "y_mm": 800.0}


def test_maintenance_points_sensor_empty_when_no_points():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.maintenance_points = ()
    coord._cached_maps_by_id = {0: map0}
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["points"] == []
```

### Step 2: Run; confirm fail

```
python -m pytest tests/integration/test_maintenance_points_sensor.py -v
```

### Step 3: Implement

In `sensor.py` (next to the metadata sensors from Task 1):

```python
class DreameA2MaintenancePointsSensor(_DreameA2PerMapSensorBase):
    """Per-map list of user-placed Maintenance Points.

    State is the count; `extra_state_attributes['points']` is the full
    list as ``[{id, x_mm, y_mm}, ...]``. Decoded from MAP key
    ``cleanPoints`` (see inventory.yaml `map_key_cleanPoints`).
    """

    _attr_name = "Maintenance points"
    _attr_translation_key = "maintenance_points"
    _attr_icon = "mdi:map-marker-radius"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "maintenance_points"

    def _compute_value(self, m):
        pts = getattr(m, "maintenance_points", None) or ()
        return len(pts)

    @property
    def extra_state_attributes(self):
        m = self._map()
        if m is None:
            return {"points": []}
        pts = getattr(m, "maintenance_points", None) or ()
        return {
            "points": [
                {
                    "id": getattr(p, "point_id", None),
                    "x_mm": getattr(p, "x_mm", None),
                    "y_mm": getattr(p, "y_mm", None),
                }
                for p in pts
            ]
        }
```

Add to the per-map loop in `async_setup_entry`:

```python
entities.append(DreameA2MaintenancePointsSensor(coordinator, map_id=map_id))
```

### Step 4: Run tests

```
python -m pytest tests/integration/test_maintenance_points_sensor.py tests/ -q
```

### Step 5: Commit

```
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_maintenance_points_sensor.py
git commit -m "feat: per-map maintenance-points sensor (read-only)"
```

---

## Task 3: Per-map session totals (area, time, sessions)

**Goal:** Three per-map sensors aggregating the session archive by `map_id`: total area mowed (m²), total mowing time (minutes), and session count.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Test: `tests/integration/test_per_map_session_totals.py`

### Step 1: Inspect existing session archive shape

Find how sessions are stored in the coordinator. Run:

```
grep -n "session_archive\|sessions\b\|by_map_id\|map_id" custom_components/dreame_a2_mower/coordinator.py | head -20
```

The session archive is likely a list-of-dicts or list-of-dataclasses under `coordinator._session_archive` or similar. Each session should have `map_id`, `area_m2`, `duration_min` (or `end_ts - start_ts`).

If the data structure isn't ready (e.g., sessions don't carry `map_id`), STOP and report the gap. The plan assumes existing data — don't add the storage.

### Step 2: Write failing tests

```python
"""Per-map session totals aggregation."""
from unittest.mock import MagicMock


def _make_coord_with_sessions():
    """Build a coordinator with a session archive carrying map_id per entry."""
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map1 = MagicMock()
    coord._cached_maps_by_id = {0: map0, 1: map1}

    # Adapt the field names below to match the real session-archive shape
    # discovered in Step 1.
    sessions = [
        MagicMock(map_id=0, area_m2=100.0, duration_min=30),
        MagicMock(map_id=0, area_m2=120.0, duration_min=40),
        MagicMock(map_id=1, area_m2=200.0, duration_min=60),
        MagicMock(map_id=None, area_m2=50.0, duration_min=15),  # ignored
    ]
    coord._session_archive = sessions  # adapt attribute name
    return coord


def test_per_map_session_area_total():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionAreaTotalSensor,
    )
    coord = _make_coord_with_sessions()
    sensor0 = DreameA2MapSessionAreaTotalSensor(coord, map_id=0)
    sensor1 = DreameA2MapSessionAreaTotalSensor(coord, map_id=1)
    assert sensor0.native_value == 220.0  # 100 + 120
    assert sensor1.native_value == 200.0


def test_per_map_session_time_total():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionTimeTotalSensor,
    )
    coord = _make_coord_with_sessions()
    sensor0 = DreameA2MapSessionTimeTotalSensor(coord, map_id=0)
    assert sensor0.native_value == 70  # 30 + 40
    assert sensor0.native_unit_of_measurement == "min"


def test_per_map_session_count():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionCountSensor,
    )
    coord = _make_coord_with_sessions()
    sensor0 = DreameA2MapSessionCountSensor(coord, map_id=0)
    sensor1 = DreameA2MapSessionCountSensor(coord, map_id=1)
    assert sensor0.native_value == 2
    assert sensor1.native_value == 1


def test_per_map_totals_zero_when_no_sessions_for_map():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionAreaTotalSensor,
        DreameA2MapSessionCountSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._cached_maps_by_id = {0: MagicMock()}
    coord._session_archive = []
    assert DreameA2MapSessionAreaTotalSensor(coord, map_id=0).native_value == 0
    assert DreameA2MapSessionCountSensor(coord, map_id=0).native_value == 0
```

### Step 3: Implement

In `sensor.py`, add (adapting attribute name `_session_archive` and session-entry field names per what Step 1 found):

```python
class _DreameA2PerMapSessionSensorBase(_DreameA2PerMapSensorBase):
    """Common scaffolding for per-map session aggregates."""

    def _sessions_for_map(self):
        archive = getattr(self.coordinator, "_session_archive", None) or []
        out = []
        for s in archive:
            mid = getattr(s, "map_id", None)
            if mid == self._map_id:
                out.append(s)
        return out


class DreameA2MapSessionAreaTotalSensor(_DreameA2PerMapSessionSensorBase):
    _attr_name = "Total area mowed"
    _attr_translation_key = "map_session_area_total"
    _attr_icon = "mdi:vector-square"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_area_total"

    def _compute_value(self, m):
        total = 0.0
        for s in self._sessions_for_map():
            total += float(getattr(s, "area_m2", 0) or 0)
        return round(total, 1)


class DreameA2MapSessionTimeTotalSensor(_DreameA2PerMapSessionSensorBase):
    _attr_name = "Total mowing time"
    _attr_translation_key = "map_session_time_total"
    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_time_total"

    def _compute_value(self, m):
        total = 0
        for s in self._sessions_for_map():
            total += int(getattr(s, "duration_min", 0) or 0)
        return total


class DreameA2MapSessionCountSensor(_DreameA2PerMapSessionSensorBase):
    _attr_name = "Mowing sessions"
    _attr_translation_key = "map_session_count"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_count"

    def _compute_value(self, m):
        return len(self._sessions_for_map())
```

Add three lines to the per-map loop in `async_setup_entry`.

### Step 4: Verify tests pass

```
python -m pytest tests/integration/test_per_map_session_totals.py tests/ -q
```

### Step 5: Commit

```
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_per_map_session_totals.py
git commit -m "feat: per-map session totals (area, time, count)"
```

---

## Task 4: Unified mowing-mode picker (per-map)

**Goal:** A single `DreameA2MowingModeSelect` per map that surfaces options `All areas | Edge | Zone: <name> | Spot: <name>` and dispatches to the appropriate existing TASK envelope (op=100/101/102/103) on selection. Keeps the existing `DreameA2ZoneSelect` / `SpotSelect` / `EdgeSelect` for backwards compatibility but they become INTERNAL — hidden from the default dashboard.

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py`
- Test: `tests/integration/test_mowing_mode_select.py`

### Step 1: Inspect existing dispatch

```
grep -n "class DreameA2ZoneSelect\|class DreameA2SpotSelect\|class DreameA2EdgeSelect\|async def async_select_option\|op=10[0-3]" custom_components/dreame_a2_mower/select.py | head -20
```

Read each of the three classes' `async_select_option` to understand the dispatch they perform. The new unified select will call those same code paths internally (or replicate the dispatch).

### Step 2: Write the failing tests

```python
"""Unified per-map mowing-mode picker."""
from unittest.mock import AsyncMock, MagicMock


def _make_coord_with_map():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    z1 = MagicMock(); z1.zone_id = 1; z1.name = "Lawn A"
    z2 = MagicMock(); z2.zone_id = 2; z2.name = "Lawn B"
    map0.mowing_areas = (z1, z2)
    sp1 = MagicMock(); sp1.spot_id = 5; sp1.name = "Spot near tree"
    map0.spot_areas = (sp1,)
    coord._cached_maps_by_id = {0: map0}
    return coord


def test_mowing_mode_options_include_all_areas_edge_zones_spots():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MowingModeSelect,
    )
    coord = _make_coord_with_map()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    opts = sel.options
    assert "All areas" in opts
    assert "Edge" in opts
    assert "Zone: Lawn A" in opts
    assert "Zone: Lawn B" in opts
    assert "Spot: Spot near tree" in opts


def test_select_all_areas_dispatches_op100(monkeypatch):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MowingModeSelect,
    )
    coord = _make_coord_with_map()
    coord.start_mowing_all_areas = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.get_event_loop().run_until_complete(sel.async_select_option("All areas"))
    coord.start_mowing_all_areas.assert_awaited_once_with(map_id=0)


def test_select_zone_dispatches_op102_with_id():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MowingModeSelect,
    )
    coord = _make_coord_with_map()
    coord.start_mowing_zone = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.get_event_loop().run_until_complete(sel.async_select_option("Zone: Lawn B"))
    coord.start_mowing_zone.assert_awaited_once_with(map_id=0, zone_id=2)


def test_select_spot_dispatches_op103_with_id():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MowingModeSelect,
    )
    coord = _make_coord_with_map()
    coord.start_mowing_spot = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.get_event_loop().run_until_complete(sel.async_select_option("Spot: Spot near tree"))
    coord.start_mowing_spot.assert_awaited_once_with(map_id=0, spot_id=5)


def test_select_edge_dispatches_op101():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MowingModeSelect,
    )
    coord = _make_coord_with_map()
    coord.start_mowing_edge = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    import asyncio
    asyncio.get_event_loop().run_until_complete(sel.async_select_option("Edge"))
    coord.start_mowing_edge.assert_awaited_once_with(map_id=0)
```

### Step 3: Implement `DreameA2MowingModeSelect`

In `custom_components/dreame_a2_mower/select.py`, find the existing zone/spot/edge classes. Add a new class that composes their actions:

```python
class DreameA2MowingModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Unified per-map mowing-mode picker.

    Options:
      - "All areas"                      → op=100
      - "Edge"                           → op=101
      - "Zone: <name>" for each zone     → op=102, zone_id=Z
      - "Spot: <name>" for each spot     → op=103, spot_id=S

    Dispatches to coordinator methods that wrap the existing TASK
    envelopes (see mower/actions.py op-codes). The legacy
    DreameA2ZoneSelect / SpotSelect / EdgeSelect entities remain
    registered for backwards-compat but are EntityCategory.DIAGNOSTIC
    so they don't clutter the default dashboard.
    """

    _attr_has_entity_name = True
    _attr_name = "Mowing mode"
    _attr_translation_key = "mowing_mode"
    _attr_icon = "mdi:robot-mower"
    _ALL_AREAS = "All areas"
    _EDGE = "Edge"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        from ._devices import map_unique_id, map_device_info
        self._attr_unique_id = map_unique_id(coordinator, map_id, "mowing_mode")
        self._attr_device_info = map_device_info(coordinator, map_id)
        self._attr_current_option: str | None = None

    def _map(self):
        return self.coordinator._cached_maps_by_id.get(self._map_id)

    @property
    def options(self) -> list[str]:
        m = self._map()
        opts = [self._ALL_AREAS, self._EDGE]
        if m is None:
            return opts
        for z in getattr(m, "mowing_areas", ()) or ():
            opts.append(f"Zone: {getattr(z, 'name', '?')}")
        for sp in getattr(m, "spot_areas", ()) or ():
            opts.append(f"Spot: {getattr(sp, 'name', '?')}")
        return opts

    async def async_select_option(self, option: str) -> None:
        m = self._map()
        if option == self._ALL_AREAS:
            await self.coordinator.start_mowing_all_areas(map_id=self._map_id)
        elif option == self._EDGE:
            await self.coordinator.start_mowing_edge(map_id=self._map_id)
        elif option.startswith("Zone: ") and m is not None:
            name = option[len("Zone: "):]
            zone = next(
                (z for z in getattr(m, "mowing_areas", ()) if getattr(z, "name", None) == name),
                None,
            )
            if zone is not None:
                await self.coordinator.start_mowing_zone(
                    map_id=self._map_id, zone_id=zone.zone_id
                )
        elif option.startswith("Spot: ") and m is not None:
            name = option[len("Spot: "):]
            spot = next(
                (s for s in getattr(m, "spot_areas", ()) if getattr(s, "name", None) == name),
                None,
            )
            if spot is not None:
                await self.coordinator.start_mowing_spot(
                    map_id=self._map_id, spot_id=spot.spot_id
                )
        self._attr_current_option = option
        self.async_write_ha_state()
```

The coordinator wrappers (`start_mowing_all_areas`, `start_mowing_edge`, `start_mowing_zone`, `start_mowing_spot`) may already exist or may need a thin layer over the TASK-envelope dispatch in `mower/actions.py`. Check `coordinator.py` first:

```
grep -n "start_mowing\|task_all_areas\|TaskEnvelope" custom_components/dreame_a2_mower/coordinator.py | head
```

If the methods don't exist yet, add minimal wrappers that call the existing TASK envelope code paths the legacy `DreameA2ZoneSelect.async_select_option` already invokes — reuse the implementation rather than duplicate.

### Step 4: Register in `async_setup_entry`

In the per-map loop (around line 72), add:

```python
entities.append(DreameA2MowingModeSelect(coordinator, map_id=map_id))
```

Make the legacy zone/spot/edge selects diagnostic-category so they don't clutter the dashboard:

```python
# Inside each of DreameA2ZoneSelect / SpotSelect / EdgeSelect __init__:
self._attr_entity_category = EntityCategory.DIAGNOSTIC
```

### Step 5: Run tests + commit

```
python -m pytest tests/integration/test_mowing_mode_select.py tests/ -q
git add custom_components/dreame_a2_mower/select.py tests/integration/test_mowing_mode_select.py
git commit -m "feat: unified per-map mowing-mode picker"
```

---

## Task 5: Dashboard — replace 4 Plan 2 placeholders

**Goal:** Update `dashboards/mower/dashboard.yaml` to use the real entities from Tasks 1-4 instead of the markdown placeholders.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

### Step 1: Identify the 4 placeholder blocks to replace

From the audit:
- Line ~148: "Mowing mode (Plan 2)" placeholder → replaced by `select.dreame_a2_mower_map_N_mowing_mode` (Task 4)
- Line ~225: "Map metadata (Plan 2)" placeholder → replaced by metadata sensors (Task 1)
- Line ~339: "Maintenance Points (Plan 2)" placeholder → replaced by maintenance points sensor (Task 2)
- Line ~519: "Per-map session totals (Plan 2)" placeholder → replaced by session-totals sensors (Task 3)

Leave the others (Custom Mode, Pathway Obstacle Avoidance, Ignore Obstacle Zones, Head to Maintenance, Per-map schedule) — those are still blocked.

### Step 2: Replace block 1 — Mowing mode

Find the markdown block starting "### 🚧 Mowing mode (Plan 2)" and replace with:

```yaml
- type: entities
  title: Start mowing
  entities:
    - entity: select.dreame_a2_mower_map_0_mowing_mode
      name: Map 1 — pick mode/target
    - entity: select.dreame_a2_mower_map_1_mowing_mode
      name: Map 2 — pick mode/target
```

(Adjust the entity_ids to match what HA assigns; the unique_id pattern is `<sn>_map_<map_id>_mowing_mode` so the entity_id is `select.dreame_a2_mower_map_<map_id>_mowing_mode` for the standard sn-derived prefix.)

### Step 3: Replace block 2 — Map metadata

Find "### 🚧 Map metadata (Plan 2)" and replace with:

```yaml
- type: entities
  title: Map metadata
  entities:
    - entity: sensor.dreame_a2_mower_map_0_name
      name: Map 1 name
    - entity: sensor.dreame_a2_mower_map_0_area
      name: Map 1 area
    - entity: sensor.dreame_a2_mower_map_0_segments
      name: Map 1 segments
    - entity: sensor.dreame_a2_mower_map_1_name
      name: Map 2 name
    - entity: sensor.dreame_a2_mower_map_1_area
      name: Map 2 area
    - entity: sensor.dreame_a2_mower_map_1_segments
      name: Map 2 segments
```

### Step 4: Replace block 3 — Maintenance Points

Find "### 🚧 Maintenance Points (Plan 2)" and replace with:

```yaml
- type: entities
  title: Maintenance points
  entities:
    - entity: sensor.dreame_a2_mower_map_0_maintenance_points
      name: Map 1 — points (count)
    - entity: sensor.dreame_a2_mower_map_1_maintenance_points
      name: Map 2 — points (count)
- type: markdown
  content: >
    Maintenance points are read-only here. Use the Dreame app to add or
    remove them, and the "Go to" button (Plan 2, blocked on cloud-action
    discovery) to dispatch the mower to a point.
```

### Step 5: Replace block 4 — Per-map session totals

Find "### 🚧 Per-map session totals (Plan 2)" and replace with:

```yaml
- type: entities
  title: Per-map session totals
  entities:
    - entity: sensor.dreame_a2_mower_map_0_session_area_total
      name: Map 1 — total area mowed
    - entity: sensor.dreame_a2_mower_map_0_session_time_total
      name: Map 1 — total time
    - entity: sensor.dreame_a2_mower_map_0_session_count
      name: Map 1 — session count
    - entity: sensor.dreame_a2_mower_map_1_session_area_total
      name: Map 2 — total area mowed
    - entity: sensor.dreame_a2_mower_map_1_session_time_total
      name: Map 2 — total time
    - entity: sensor.dreame_a2_mower_map_1_session_count
      name: Map 2 — session count
```

### Step 6: YAML validate + SCP

```
python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"
sshpass -p $(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt) \
  scp -o StrictHostKeyChecking=no \
  dashboards/mower/dashboard.yaml \
  root@$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt):/homeassistant/dashboards/mower/dashboard.yaml
```

### Step 7: Commit

```
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): replace 4 Plan 2 placeholders with real entities"
```

---

## Task 6: Release v1.0.7a1

After Tasks 1-5 are merged and the full suite is green:

```
tools/release.sh 1.0.7a1
```

Verify HACS picks it up and reload the config entry. The dashboard auto-SCPs as part of Task 5.

---

## Self-Review

**Spec coverage:**
- Plan 2 placeholders #1, #3, #7, #9 → Tasks 4, 1, 2, 3 ✓
- Placeholder #2 (Head to Maintenance Point button) explicitly deferred and reason documented.
- Other 4 placeholders explicitly listed as out-of-scope.

**Type consistency:**
- `_DreameA2PerMapSensorBase` shared across Tasks 1, 2, 3 → consistent class hierarchy.
- `map_unique_id(coord, map_id, key)` / `map_device_info(coord, map_id)` are existing helpers (see `_devices.py`).
- Coordinator wrapper methods `start_mowing_*` are assumed to exist or will be thin wrappers — implementer verifies in Task 4 Step 1.

**Placeholder scan:** no TBD / TODO / "fill in details" placeholders. Every step has the actual code or an exact grep command to discover its inputs.

**Outstanding risk:** Task 3 depends on the session archive carrying `map_id` per entry. Step 1 verifies this before writing tests. If the archive doesn't carry `map_id`, Task 3 surfaces as BLOCKED and skips ahead — implementer reports and we re-plan.
