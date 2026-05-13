# Dashboard Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the Mower dashboard so each tab has clear ownership: one active-map switcher (Maps tab only), state-aware action buttons on the Mower tab, base maps with read-only overlays on Settings & Zones, weekly schedule grid, calendar view of archived sessions, and a fuller Diagnostics tab. Surface state-machine entities added in v1.0.8. Fix the WiFi-heatmap initial-render bug.

**Architecture:** Two work surfaces:
1. **Integration code** (~5 small changes): new sensors, new `calendar.py` platform, renderer addition (maintenance-point glyphs), WiFi camera setup fix, persist `session_distance_m` on archive.
2. **Lovelace YAML**: bulk of the work in `dashboards/mower/dashboard.yaml` — rename, replace selectors, conditional button cards, base-map cards on Settings & Zones, weekly schedule grid, calendar card on Sessions.

**Tech Stack:** Python (HA custom_component), Home Assistant Lovelace YAML, pytest, paho-mqtt. Released via `tools/release.sh`.

**Spec:** `docs/superpowers/specs/2026-05-13-dashboard-cleanup-design.md`

---

## File map

**Integration code (`custom_components/dreame_a2_mower/`):**
- `archive/session.py` — add `session_distance_m: float = 0.0` field to `ArchivedSession`, plumb through `from_summary` / `to_dict` / `from_dict`.
- `sensor.py` — three new diagnostic sensors (cloud device-id, API endpoint, integration version).
- `camera.py` — fix WiFi-heatmap blank-on-load.
- `map_render.py` — add maintenance-point glyphs on `render_base_map`.
- `calendar.py` (NEW) — `DreameA2SessionCalendar` entity exposing archived sessions.
- `const.py` — add `"calendar"` to `PLATFORMS`.

**Dashboard YAML:**
- `dashboards/mower/dashboard.yaml` — all dashboard changes in this single file.

**Tests:**
- `tests/archive/test_session_distance.py` (NEW)
- `tests/integration/test_diagnostic_sensors_new.py` (NEW)
- `tests/integration/test_camera_initial_render.py` (NEW)
- `tests/protocol/test_maintenance_point_render.py` (NEW)
- `tests/integration/test_calendar.py` (NEW)

---

## Phase 1 — Integration code changes

### Task 1: Persist `session_distance_m` on archive

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py:46-133`
- Test: `tests/archive/test_session_distance.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/archive/test_session_distance.py
"""ArchivedSession persists session_distance_m across to_dict/from_dict."""
from __future__ import annotations


def test_archived_session_carries_distance():
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    entry = ArchivedSession(
        filename="s.json", start_ts=1, end_ts=2, duration_min=3,
        area_mowed_m2=4.0, map_area_m2=5, md5="a",
        session_distance_m=42.5,
    )
    d = entry.to_dict()
    assert d["session_distance_m"] == 42.5
    roundtrip = ArchivedSession.from_dict(d)
    assert roundtrip.session_distance_m == 42.5


def test_archived_session_legacy_entry_defaults_to_zero():
    """Legacy index.json entries without session_distance_m parse cleanly."""
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    legacy = {
        "filename": "s.json", "start_ts": 1, "end_ts": 2, "duration_min": 3,
        "area_mowed_m2": 4.0, "map_area_m2": 5, "md5": "a", "map_id": 0,
    }
    entry = ArchivedSession.from_dict(legacy)
    assert entry.session_distance_m == 0.0


def test_from_summary_pulls_distance():
    """ArchivedSession.from_summary reads session_distance_m off the summary."""
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    summary = SimpleNamespace(
        start_ts=1, end_ts=2, duration_min=3, area_mowed_m2=4.0,
        map_area_m2=5, md5="a", session_distance_m=99.9,
    )
    e = ArchivedSession.from_summary("s.json", summary, map_id=0)
    assert e.session_distance_m == 99.9
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/archive/test_session_distance.py -v
```
Expected: FAIL with `TypeError: ArchivedSession.__init__() got an unexpected keyword argument 'session_distance_m'`.

- [ ] **Step 3: Add the field**

In `custom_components/dreame_a2_mower/archive/session.py`, modify the `ArchivedSession` dataclass:

```python
# Add after the map_id field, around line 83
session_distance_m: float = 0.0
"""Total path length in metres for this session. Computed live from
the trail; persisted on archive write for the Sessions calendar /
detail card. Defaults to 0.0 on legacy entries without the field."""
```

Update `from_summary` (around line 84-103) to pass it through:

```python
@classmethod
def from_summary(
    cls,
    filename: str,
    summary,
    *,
    local_trail_complete: bool = True,
    map_id: int = -1,
) -> ArchivedSession:
    return cls(
        filename=filename,
        start_ts=int(summary.start_ts),
        end_ts=int(summary.end_ts),
        duration_min=int(summary.duration_min),
        area_mowed_m2=float(summary.area_mowed_m2),
        map_area_m2=int(summary.map_area_m2),
        md5=str(summary.md5),
        local_trail_complete=bool(local_trail_complete),
        map_id=int(map_id),
        session_distance_m=float(getattr(summary, "session_distance_m", 0.0) or 0.0),
    )
```

Update `to_dict` (around line 105-116):

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "filename": self.filename,
        "start_ts": self.start_ts,
        "end_ts": self.end_ts,
        "duration_min": self.duration_min,
        "area_mowed_m2": self.area_mowed_m2,
        "map_area_m2": self.map_area_m2,
        "md5": self.md5,
        "local_trail_complete": self.local_trail_complete,
        "map_id": self.map_id,
        "session_distance_m": self.session_distance_m,
    }
```

Update `from_dict` (around line 118-133):

```python
@classmethod
def from_dict(cls, d: dict[str, Any]) -> ArchivedSession:
    return cls(
        filename=str(d.get("filename", "")),
        start_ts=int(d.get("start_ts", 0)),
        end_ts=int(d.get("end_ts", 0)),
        duration_min=int(d.get("duration_min", 0)),
        area_mowed_m2=float(d.get("area_mowed_m2", 0.0)),
        map_area_m2=int(d.get("map_area_m2", 0)),
        md5=str(d.get("md5", "")),
        still_running=bool(d.get("still_running", False)),
        local_trail_complete=bool(d.get("local_trail_complete", True)),
        map_id=int(d["map_id"]) if "map_id" in d else -1,
        session_distance_m=float(d.get("session_distance_m", 0.0) or 0.0),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/archive/test_session_distance.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Run full suite to check for regression**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: PASS count increases by 3; no new failures.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/session.py tests/archive/test_session_distance.py
git commit -m "feat(archive): persist session_distance_m on ArchivedSession"
```

---

### Task 2: New diagnostic sensors (cloud device-id, API endpoint, integration version)

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py` (add 3 sensor classes + register in setup)
- Test: `tests/integration/test_diagnostic_sensors_new.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_diagnostic_sensors_new.py
"""New diagnostic sensors: cloud device-id, API endpoint, integration version."""
from __future__ import annotations
from unittest.mock import MagicMock


def _coord():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    cloud = MagicMock()
    cloud.device_id = "BM169439"
    cloud.host = "eu.iot.dreame.tech"
    coord._cloud = cloud
    return coord


def test_cloud_device_id_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CloudDeviceIdSensor,
    )
    s = DreameA2CloudDeviceIdSensor(_coord())
    assert s.native_value == "BM169439"
    assert s._attr_entity_category.name == "DIAGNOSTIC"


def test_cloud_device_id_sensor_unknown_when_missing():
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CloudDeviceIdSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._cloud = None
    s = DreameA2CloudDeviceIdSensor(coord)
    assert s.native_value is None


def test_api_endpoint_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2ApiEndpointSensor,
    )
    s = DreameA2ApiEndpointSensor(_coord())
    assert s.native_value == "eu.iot.dreame.tech:19973"


def test_integration_version_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2IntegrationVersionSensor,
    )
    s = DreameA2IntegrationVersionSensor(_coord())
    # Should be the manifest.json version string, e.g. "1.0.8a8"
    val = s.native_value
    assert isinstance(val, str)
    assert val
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_diagnostic_sensors_new.py -v
```
Expected: 4 FAIL with `ImportError: cannot import name 'DreameA2CloudDeviceIdSensor'`.

- [ ] **Step 3: Add the three sensor classes**

In `custom_components/dreame_a2_mower/sensor.py`, add near the bottom of the file (after `DreameA2WifiRefreshStatusSensor`, before `async_setup_entry`):

```python
class DreameA2CloudDeviceIdSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Surfaces the cloud-assigned device id (e.g. BM169439)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Cloud device id"
    _attr_translation_key = "cloud_device_id"
    _attr_icon = "mdi:cloud-tag"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = sn_unique_id(coordinator, "cloud_device_id")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        cloud = getattr(self.coordinator, "_cloud", None)
        if cloud is None:
            return None
        return getattr(cloud, "device_id", None)


class DreameA2ApiEndpointSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Cloud API endpoint host:port the integration is talking to."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "API endpoint"
    _attr_translation_key = "api_endpoint"
    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = sn_unique_id(coordinator, "api_endpoint")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        cloud = getattr(self.coordinator, "_cloud", None)
        if cloud is None:
            return None
        host = getattr(cloud, "host", None) or "eu.iot.dreame.tech"
        return f"{host}:19973"


class DreameA2IntegrationVersionSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Currently-running integration version, sourced from manifest.json."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Integration version"
    _attr_translation_key = "integration_version"
    _attr_icon = "mdi:package-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _cached_version: str | None = None

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = sn_unique_id(coordinator, "integration_version")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        if self._cached_version is not None:
            return self._cached_version
        import json
        from pathlib import Path
        manifest = Path(__file__).parent / "manifest.json"
        try:
            data = json.loads(manifest.read_text())
            self._cached_version = str(data.get("version", "unknown"))
        except Exception:
            self._cached_version = "unknown"
        return self._cached_version
```

Then register them in `async_setup_entry` — find the existing `entities = [...]` list around line 660 and add three lines:

```python
# In async_setup_entry, alongside the other top-level sensor entities
entities.extend([
    DreameA2CloudDeviceIdSensor(coordinator),
    DreameA2ApiEndpointSensor(coordinator),
    DreameA2IntegrationVersionSensor(coordinator),
])
```

(The exact location: just after the `entities.extend([...])` block that adds `DreameA2CurrentActivitySensor` and the other state-machine enum sensors.)

- [ ] **Step 4: Verify helpers `sn_unique_id` and `mower_device_info` exist**

```bash
grep -n "^def sn_unique_id\|^def mower_device_info\|from \._devices import" custom_components/dreame_a2_mower/sensor.py | head -5
```
Expected: at least one import / def line. If not present, find the correct import (it's in `custom_components/dreame_a2_mower/_devices.py`) and add it.

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/integration/test_diagnostic_sensors_new.py -v
```
Expected: 4 PASS.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: increase by 4; no new failures.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_diagnostic_sensors_new.py
git commit -m "feat(sensor): add cloud device-id, API endpoint, integration version diagnostics"
```

---

### Task 3: WiFi camera initial-render fix

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py` — `DreameA2WifiHeatmapCamera.async_added_to_hass`
- Test: `tests/integration/test_camera_initial_render.py` (NEW)

- [ ] **Step 1: Inspect current behaviour**

```bash
grep -n "class DreameA2WifiHeatmapCamera\|async_added_to_hass\|input_select" custom_components/dreame_a2_mower/camera.py | head -20
```

Note the class location and confirm whether `async_added_to_hass` is already overridden. The fix lands in this method.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_camera_initial_render.py
"""WiFi heatmap camera must render the dropdown's default value at
setup time. Previously the camera stayed blank until the user manually
changed the input_select — then went back to the original choice."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_wifi_camera_renders_on_initial_setup():
    """async_added_to_hass should trigger an initial image refresh
    against whatever input_select.dreame_a2_mower_wifi_archive_pick
    is currently set to."""
    from custom_components.dreame_a2_mower.camera import (
        DreameA2WifiHeatmapCamera,
    )
    coord = MagicMock()
    coord.entry.entry_id = "e"
    coord.hass = MagicMock()
    coord.hass.states.get = MagicMock(return_value=MagicMock(state="archive_key_1"))
    coord.refresh_wifi_archive_image_for_key = AsyncMock()

    cam = DreameA2WifiHeatmapCamera.__new__(DreameA2WifiHeatmapCamera)
    cam.coordinator = coord
    cam.hass = coord.hass
    cam.async_write_ha_state = MagicMock()

    asyncio.run(cam.async_added_to_hass())

    # Must have asked the coordinator to render the current pick
    coord.refresh_wifi_archive_image_for_key.assert_awaited()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_camera_initial_render.py -v
```
Expected: FAIL — either the method doesn't exist or doesn't call refresh.

- [ ] **Step 4: Locate the right method on coordinator**

```bash
grep -n "def refresh_wifi_archive\|wifi_pick\|wifi_archive_pick" custom_components/dreame_a2_mower/coordinator.py | head -10
```

If the helper method has a different name, **adjust the test AND the implementation** to use the existing name (e.g. `refresh_wifi_archive_for_pick`). Do NOT add a new coordinator method just for this; reuse what's there.

- [ ] **Step 5: Implement the fix in camera.py**

Find the `DreameA2WifiHeatmapCamera` class. If `async_added_to_hass` already exists, extend it; if not, add it:

```python
async def async_added_to_hass(self) -> None:
    """Trigger an initial render against the current input_select pick.

    Without this, the camera stays blank until the user manually
    changes the dropdown — the input_select's default state never
    fires the refresh path because there's no state-CHANGE event on
    boot.
    """
    await super().async_added_to_hass()
    # Resolve the current pick from the input_select entity.
    entity_id = f"input_select.dreame_a2_mower_wifi_archive_pick"
    state_obj = self.hass.states.get(entity_id)
    if state_obj is None or state_obj.state in (None, "", "unknown", "unavailable"):
        return
    refresh = getattr(self.coordinator, "refresh_wifi_archive_image_for_key", None)
    if refresh is None:
        return
    try:
        await refresh(state_obj.state)
    except Exception:
        # Best-effort; missing keys / decode failures shouldn't block setup.
        pass
```

(Adjust the method name + entity_id if the actual one in the codebase differs — see Step 4.)

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/integration/test_camera_initial_render.py -v
```
Expected: PASS.

- [ ] **Step 7: Run full suite**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: increase by 1; no new failures.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py tests/integration/test_camera_initial_render.py
git commit -m "fix(camera): WiFi heatmap renders default pick on initial setup"
```

---

### Task 4: Maintenance-point glyphs on base-map renderer

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` — `render_base_map`
- Test: `tests/protocol/test_maintenance_point_render.py` (NEW)

- [ ] **Step 1: Inspect renderer signature + existing dock-circle code**

```bash
grep -n "def render_base_map\|docking_station\|maintenance\|circle" custom_components/dreame_a2_mower/map_render.py | head -15
```

Locate where the docking-station circle is drawn (the blue dock glyph) — the maintenance-point M-circle goes alongside, with 2× radius and a different colour.

- [ ] **Step 2: Write the failing test**

```python
# tests/protocol/test_maintenance_point_render.py
"""render_base_map paints a maintenance-point glyph for each point."""
from __future__ import annotations
import dataclasses
import json
from pathlib import Path


def test_maintenance_point_glyph_drawn():
    from custom_components.dreame_a2_mower.map_render import render_base_map
    from custom_components.dreame_a2_mower.map_decoder import (
        parse_cloud_maps, MaintenancePoint,
    )
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "multi_map_response.json")
        .read_text()
    )
    by_id = {int(k): v for k, v in fixture["by_id"].items()}
    parsed = parse_cloud_maps(by_id)
    m0 = parsed[0]
    # Inject a known maintenance point at a guaranteed in-bounds position
    m0 = dataclasses.replace(
        m0,
        maintenance_points=(
            MaintenancePoint(point_id=99, x_mm=0.0, y_mm=0.0),
        ),
    )
    png_no_mp = render_base_map(dataclasses.replace(m0, maintenance_points=()))
    png_with_mp = render_base_map(m0)
    # Pixel-different because we added a glyph
    assert png_no_mp != png_with_mp
    # Both PNGs are non-empty
    assert png_with_mp and len(png_with_mp) > 100
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/protocol/test_maintenance_point_render.py -v
```
Expected: FAIL (the two PNGs are byte-identical because the renderer ignores maintenance_points today).

- [ ] **Step 4: Implement maintenance-point drawing**

In `custom_components/dreame_a2_mower/map_render.py`, inside `render_base_map` after the docking-station glyph is drawn, add:

```python
# Maintenance points — light-brown circle 2x the dock radius with an
# "M" glyph. Drawn AFTER overlays so they sit on top, but BEFORE the
# mower position icon (the mower is the most-recent visual layer).
mp_color_fill = (180, 130, 80, 220)    # warm tan, semi-opaque
mp_color_outline = (110, 70, 30, 255)  # darker brown outline
mp_radius_px = (2 * DOCK_RADIUS_PX)    # use the same const as the dock
for mp in getattr(map_data, "maintenance_points", ()) or ():
    # Convert cloud-frame mm to renderer pixels (same helper used for the dock)
    px, py = _cloud_mm_to_render_px(map_data, mp.x_mm, mp.y_mm)
    if px is None or py is None:
        continue
    draw.ellipse(
        [
            (px - mp_radius_px, py - mp_radius_px),
            (px + mp_radius_px, py + mp_radius_px),
        ],
        fill=mp_color_fill,
        outline=mp_color_outline,
        width=2,
    )
    # Draw an "M" inside the circle, centred.
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=int(mp_radius_px * 1.2))
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((px, py), "M", font=font, anchor="mm")
    draw.text((px, py), "M", fill=(255, 255, 255, 255), font=font, anchor="mm")
```

**Adapt names to the existing renderer:**
- `DOCK_RADIUS_PX` may be a different constant — match what `render_base_map` already uses for the dock.
- `_cloud_mm_to_render_px` may be a different helper — use whatever maps cloud-frame mm to pixel coordinates inside the same function.
- `draw`, `ImageFont` are PIL-standard; if the file uses `aggdraw` or `cairo`, adapt syntax.

Read 30 lines around the existing docking-circle code first to match the established pattern.

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/protocol/test_maintenance_point_render.py -v
```
Expected: PASS.

- [ ] **Step 6: Visual smoke check (optional but recommended)**

```bash
python3 -c "
import sys, json, dataclasses
from pathlib import Path
sys.path.insert(0, 'custom_components/dreame_a2_mower')
from map_decoder import parse_cloud_maps, MaintenancePoint
from map_render import render_base_map
fixture = json.loads(Path('tests/protocol/fixtures/multi_map_response.json').read_text())
by_id = {int(k): v for k, v in fixture['by_id'].items()}
m = parse_cloud_maps(by_id)[0]
m = dataclasses.replace(m, maintenance_points=(MaintenancePoint(point_id=99, x_mm=0.0, y_mm=0.0),))
Path('/tmp/m_with_mp.png').write_bytes(render_base_map(m))
print('Wrote /tmp/m_with_mp.png')
"
```
Open `/tmp/m_with_mp.png` in an image viewer; confirm there's a tan circle with a white "M" at the dock origin.

- [ ] **Step 7: Run full suite**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: increase by 1; no new failures.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_maintenance_point_render.py
git commit -m "feat(map_render): draw maintenance-point M-glyphs on base map"
```

---

### Task 5: Calendar entity for archived sessions

**Files:**
- Create: `custom_components/dreame_a2_mower/calendar.py`
- Modify: `custom_components/dreame_a2_mower/const.py:13-25` (add `"calendar"` to PLATFORMS)
- Test: `tests/integration/test_calendar.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_calendar.py
"""DreameA2SessionCalendar exposes archived sessions as HA calendar events."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _archive_with(*entries):
    from unittest.mock import MagicMock
    arc = MagicMock()
    arc.entries.return_value = list(entries)
    return arc


def _archived_session(start_ts, end_ts, area=10.0, distance=42.0, map_id=0):
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    return ArchivedSession(
        filename="s.json", start_ts=start_ts, end_ts=end_ts,
        duration_min=(end_ts - start_ts) // 60,
        area_mowed_m2=area, map_area_m2=100, md5="a",
        map_id=map_id, session_distance_m=distance,
    )


def test_calendar_exposes_session_as_event():
    from custom_components.dreame_a2_mower.calendar import (
        DreameA2SessionCalendar,
    )
    coord = MagicMock()
    coord.entry.entry_id = "e"
    coord.session_archive = _archive_with(_archived_session(
        start_ts=1_700_000_000, end_ts=1_700_001_800,  # 30-min session
    ))
    cal = DreameA2SessionCalendar.__new__(DreameA2SessionCalendar)
    cal.coordinator = coord
    cal.hass = MagicMock()

    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert len(events) == 1
    ev = events[0]
    assert ev.start.timestamp() == 1_700_000_000
    assert ev.end.timestamp() == 1_700_001_800
    # Summary includes area
    assert "m²" in ev.summary or "m2" in ev.summary


def test_calendar_filters_by_date_window():
    from custom_components.dreame_a2_mower.calendar import (
        DreameA2SessionCalendar,
    )
    coord = MagicMock()
    coord.entry.entry_id = "e"
    coord.session_archive = _archive_with(
        _archived_session(1_700_000_000, 1_700_001_800),   # in range
        _archived_session(1_600_000_000, 1_600_001_800),   # too old
    )
    cal = DreameA2SessionCalendar.__new__(DreameA2SessionCalendar)
    cal.coordinator = coord
    cal.hass = MagicMock()

    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 16, tzinfo=timezone.utc)
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert len(events) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_calendar.py -v
```
Expected: FAIL with `ImportError: No module named 'custom_components.dreame_a2_mower.calendar'`.

- [ ] **Step 3: Inspect coordinator to find the session archive accessor**

```bash
grep -n "session_archive\s*=\|self.session_archive\|def session_archive" custom_components/dreame_a2_mower/coordinator.py | head -5
```

Confirm the attribute name and its `entries()` (or equivalent) method that returns `ArchivedSession` instances.

- [ ] **Step 4: Create `calendar.py`**

```python
# custom_components/dreame_a2_mower/calendar.py
"""Calendar entity exposing archived sessions as events.

Each ArchivedSession becomes a CalendarEvent. Read-only — there is no
add/edit/delete; HA's calendar UI surfaces them in agenda/day/week/month
views via the built-in calendar card.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, sn_unique_id
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2SessionCalendar(coordinator)])


class DreameA2SessionCalendar(
    CoordinatorEntity["DreameA2MowerCoordinator"], CalendarEntity
):
    """Read-only calendar of archived mow sessions."""

    _attr_has_entity_name = True
    _attr_name = "Sessions"
    _attr_translation_key = "session_calendar"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: "DreameA2MowerCoordinator") -> None:
        super().__init__(coordinator)
        self._attr_unique_id = sn_unique_id(coordinator, "session_calendar")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def event(self) -> CalendarEvent | None:
        """The 'current or next' event. HA shows this in the entity state."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return None
        entries = list(archive.entries())
        if not entries:
            return None
        # Most-recent entry
        latest = max(entries, key=lambda e: e.start_ts)
        return _event_from_entry(latest)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within [start_date, end_date]."""
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return []
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()
        events: list[CalendarEvent] = []
        for entry in archive.entries():
            if entry.start_ts < start_ts or entry.start_ts > end_ts:
                continue
            events.append(_event_from_entry(entry))
        return events


def _event_from_entry(entry) -> CalendarEvent:
    """Render an ArchivedSession as a CalendarEvent."""
    start = datetime.fromtimestamp(entry.start_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(entry.end_ts, tz=timezone.utc)
    map_label = f"Map {entry.map_id + 1}" if entry.map_id >= 0 else "Map ?"
    summary = f"Mow {map_label} — {entry.area_mowed_m2:.1f} m²"
    description_parts = [
        f"Duration: {entry.duration_min} min",
        f"Area mowed: {entry.area_mowed_m2:.1f} m²",
    ]
    if entry.session_distance_m:
        description_parts.append(f"Distance: {entry.session_distance_m:.0f} m")
    description_parts.append(f"Map area: {entry.map_area_m2} m²")
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description="\n".join(description_parts),
        uid=f"dreame_a2_session_{entry.md5}_{entry.start_ts}",
    )
```

- [ ] **Step 5: Register calendar platform in const.py**

In `custom_components/dreame_a2_mower/const.py`, modify the `PLATFORMS` list:

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
    "calendar",
]
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/integration/test_calendar.py -v
```
Expected: 2 PASS.

- [ ] **Step 7: Run full suite**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: increase by 2; no new failures.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/calendar.py custom_components/dreame_a2_mower/const.py tests/integration/test_calendar.py
git commit -m "feat(calendar): expose archived sessions as HA calendar entity"
```

---

## Phase 2 — Dashboard YAML changes

> **Convention for YAML tasks:** "Verify" means open the dashboard in HA UI and confirm the card renders without errors. If the dev environment has no live HA, `yamllint dashboards/mower/dashboard.yaml` is the substitute.

### Task 6: Backup current dashboard

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` (no edits yet; copy first)

- [ ] **Step 1: Make a timestamped backup**

```bash
cp dashboards/mower/dashboard.yaml dashboards/mower/dashboard.pre-cleanup-$(date +%Y%m%d).yaml.bak
ls dashboards/mower/*.bak
```
Expected: two backup files visible (`.pre-phase2.yaml.bak` and the new one).

- [ ] **Step 2: Commit the backup**

```bash
git add dashboards/mower/dashboard.pre-cleanup-*.yaml.bak
git commit -m "chore(dashboard): snapshot pre-cleanup dashboard.yaml"
```

---

### Task 7: Map Selector tab — "Select" buttons + visual highlight

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Map Selector` view (around line 177)

- [ ] **Step 1: Inspect current Map Selector tab**

```bash
sed -n '177,240p' dashboards/mower/dashboard.yaml
```
Note the existing layout (likely picture-card per map + dropdown). The Select-button addition goes UNDER each map tile.

- [ ] **Step 2: Locate the `select.active_map_select` entity name**

```bash
grep -rn "active_map_select\|active_map\b" custom_components/dreame_a2_mower/select.py | head -5
```
Note the full entity_id format (e.g. `select.dreame_a2_mower_active_map`).

- [ ] **Step 3: Replace the Map Selector view body**

Find the `Map Selector` view (line 177ish) and replace its cards with this structure. Each map gets:
1. A picture-elements card that taps-to-zoom (existing behaviour)
2. A row of buttons below: "Select Map N" + visual indicator of which is active

```yaml
- title: Map Selector
  path: maps
  cards:
    - type: markdown
      content: |
        ## Map Selector
        Tap a map to zoom in. Press **Select** to make that map the
        active map for the rest of the dashboard (mowing target,
        schedule, settings). Switching is blocked during an active
        mow.
    - type: vertical-stack
      cards:
        - type: picture-entity
          entity: camera.dreame_a2_mower_map_1
          show_state: false
          show_name: false
          tap_action:
            action: more-info
        - type: horizontal-stack
          cards:
            - type: markdown
              content: |
                **Map 1**
                {% if state_attr('select.dreame_a2_mower_active_map', 'current_map_id') | int(0) == 0 %}
                🟢 Currently active
                {% else %}
                ⚪ Inactive
                {% endif %}
            - type: button
              name: Select Map 1
              icon: mdi:map-check
              tap_action:
                action: call-service
                service: select.select_option
                target:
                  entity_id: select.dreame_a2_mower_active_map
                data:
                  option: Map 1
    - type: vertical-stack
      cards:
        - type: picture-entity
          entity: camera.dreame_a2_mower_map_2
          show_state: false
          show_name: false
          tap_action:
            action: more-info
        - type: horizontal-stack
          cards:
            - type: markdown
              content: |
                **Map 2**
                {% if state_attr('select.dreame_a2_mower_active_map', 'current_map_id') | int(-1) == 1 %}
                🟢 Currently active
                {% else %}
                ⚪ Inactive
                {% endif %}
            - type: button
              name: Select Map 2
              icon: mdi:map-check
              tap_action:
                action: call-service
                service: select.select_option
                target:
                  entity_id: select.dreame_a2_mower_active_map
                data:
                  option: Map 2
```

**Notes:**
- The `current_map_id` attribute exists on `active_map_select` (see `tests/integration/test_active_map_select.py:test_active_map_select_exposes_current_map_id_attribute`).
- The option strings ("Map 1", "Map 2") must match the friendly names the select entity uses — verify by checking `select.py` or the entity state in HA dev tools.
- The mid-mow guard fires automatically from `select.active_map_select.async_select_option` — no extra dashboard logic needed.

- [ ] **Step 4: yamllint**

```bash
yamllint -d "{rules: {line-length: disable, comments-indentation: disable}}" dashboards/mower/dashboard.yaml
```
Expected: no errors.

- [ ] **Step 5: SCP the dashboard to HA, reload, smoke test**

```bash
sshpass -p "$(sed -n '3p' /data/claude/homeassistant/ha-credentials.txt)" scp \
    dashboards/mower/dashboard.yaml \
    root@10.0.0.30:/config/dashboards/mower/dashboard.yaml
```
Then reload via HA UI (Settings → Dashboards → reload), open the Map Selector tab. Confirm two map images, each with a "Select Map N" button below and the active indicator.

- [ ] **Step 6: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Map Selector tab — Select buttons + active indicator"
```

---

### Task 8: Mower tab — rename "Start mowing" → "Mowing target", single dropdown

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Mower` view (around line 73)

- [ ] **Step 1: Inspect current "Start mowing" card**

```bash
sed -n '73,180p' dashboards/mower/dashboard.yaml | grep -n "Start mowing\|mowing target\|select.*zone\|select.*spot\|select.*edge"
```
Note: there are currently per-map dropdowns. We replace them with the unified picker for the active map.

- [ ] **Step 2: Locate the unified mowing-mode picker entity**

```bash
grep -n "class.*MowingMode\|unified_mowing\|mowing_target\|mowing_mode_select" custom_components/dreame_a2_mower/select.py | head -10
```
Note the entity_id of the unified picker (P2-4).

- [ ] **Step 3: Replace the "Start mowing" card**

Find the card titled "Start mowing" in the `Mower` view and replace with:

```yaml
- type: entities
  title: Mowing target
  show_header_toggle: false
  state_color: false
  entities:
    - entity: select.dreame_a2_mower_mowing_target
      name: Target (active map)
      icon: mdi:target
  footer:
    type: graph
    entity: sensor.dreame_a2_mower_area_mowed
    hours_to_show: 6
```

Adapt `select.dreame_a2_mower_mowing_target` to whatever entity_id the P2-4 picker actually uses (see Step 2). If the unified picker doesn't exist for the active map (only per-map versions are wired), this becomes a 2-step task — first wire the unified picker, then surface it. Check first.

- [ ] **Step 4: yamllint + SCP + smoke test**

Same commands as Task 7 Step 4-5. Confirm the card title says "Mowing target" and only one dropdown shows zone/spot/edge options.

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Mower tab — 'Mowing target' card with single active-map picker"
```

---

### Task 9: Mower tab — state-aware action buttons (conditional cards)

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Mower` view (around line 73)

- [ ] **Step 1: Inspect current action buttons**

```bash
sed -n '73,180p' dashboards/mower/dashboard.yaml | grep -n "Start\|Pause\|Stop\|Recharge\|button\|tap_action"
```

- [ ] **Step 2: Find the existing button entity_ids**

```bash
grep -n "BUTTON_DESCRIPTIONS\|key=\"start\\|key=\"pause\\|key=\"end\\|key=\"recharge\\|key=\"find\\|key=\"continue" custom_components/dreame_a2_mower/button.py | head -10
```
Note the entity_ids (likely `button.dreame_a2_mower_start`, `button.dreame_a2_mower_pause`, etc.).

- [ ] **Step 3: Define the state predicates**

The six conditional rows use these predicates against state-machine sensors:

| Row | Predicate (Lovelace `conditional`) |
|---|---|
| Charging in mow | `binary_sensor.dreame_a2_mower_mowing_session_active == on` AND `sensor.dreame_a2_mower_charging_status == charging` |
| Charging not in mow | `mowing_session_active == off` AND `charging_status == charging` |
| In dock, not charging | `in_dock == on` AND `charging_status != charging` AND `mowing_session_active == off` |
| Doing-something | `current_activity in (mowing, cruising_to_point, fast_mapping, returning, repositioning)` AND `charging_status != charging` |
| Paused in session | `current_activity == paused` |
| Stopped on lawn idle | `mowing_session_active == off` AND `in_dock == off` AND `charging_status != charging` |

Predicates overlap — order matters. Lovelace doesn't support "first-match-wins" natively; we'll use `conditional` cards where each row's predicate is mutually exclusive with the others.

Mutually-exclusive form:

- Row 1 (charging-in-mow): `mowing_session_active == on AND charging_status == charging`
- Row 2 (charging-not-in-mow): `mowing_session_active == off AND charging_status == charging`
- Row 3 (in-dock-not-charging): `in_dock == on AND charging_status == not_charging AND mowing_session_active == off`
- Row 4 (doing-something): `current_activity in {mowing, cruising_to_point, fast_mapping, returning, repositioning}` (charging_status implicitly != charging because row 1 catches that)
- Row 5 (paused): `current_activity == paused`
- Row 6 (idle-on-lawn): `current_activity == idle AND in_dock == off AND mowing_session_active == off`

- [ ] **Step 4: Replace the existing button grid**

In the Mower view, find the buttons card (typically `glance` or `horizontal-stack` of buttons) and replace with this conditional stack. Add it AFTER the State card and BEFORE the GPS-map placeholder.

```yaml
- type: vertical-stack
  cards:
    # Find button — always available
    - type: horizontal-stack
      cards:
        - type: button
          name: Find mower
          icon: mdi:bell-ring
          tap_action:
            action: call-service
            service: button.press
            target:
              entity_id: button.dreame_a2_mower_find

    # Row 1: Charging in mow → Continue · End
    - type: conditional
      conditions:
        - entity: binary_sensor.dreame_a2_mower_mowing_session_active
          state: "on"
        - entity: sensor.dreame_a2_mower_charging_status
          state: charging
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Continue
            icon: mdi:play
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_start
          - type: button
            name: End
            icon: mdi:stop
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_end

    # Row 2: Charging not in mow → Start
    - type: conditional
      conditions:
        - entity: binary_sensor.dreame_a2_mower_mowing_session_active
          state: "off"
        - entity: sensor.dreame_a2_mower_charging_status
          state: charging
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Start
            icon: mdi:play
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_start

    # Row 3: In dock, not charging → Start · Recharge
    - type: conditional
      conditions:
        - entity: binary_sensor.dreame_a2_mower_in_dock
          state: "on"
        - entity: sensor.dreame_a2_mower_charging_status
          state_not: charging
        - entity: binary_sensor.dreame_a2_mower_mowing_session_active
          state: "off"
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Start
            icon: mdi:play
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_start
          - type: button
            name: Recharge
            icon: mdi:battery-charging
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_recharge

    # Row 4: Doing-something (mowing/cruising/mapping/returning) → Pause · End · Recharge
    - type: conditional
      conditions:
        - entity: sensor.dreame_a2_mower_current_activity
          state:
            - mowing
            - cruising_to_point
            - fast_mapping
            - returning
            - repositioning
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Pause
            icon: mdi:pause
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_pause
          - type: button
            name: End
            icon: mdi:stop
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_end
          - type: button
            name: Recharge
            icon: mdi:battery-charging
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_recharge

    # Row 5: Paused → Continue · End · Recharge
    - type: conditional
      conditions:
        - entity: sensor.dreame_a2_mower_current_activity
          state: paused
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Continue
            icon: mdi:play
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_start
          - type: button
            name: End
            icon: mdi:stop
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_end
          - type: button
            name: Recharge
            icon: mdi:battery-charging
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_recharge

    # Row 6: Stopped on lawn idle (error / arrived) → Recharge
    - type: conditional
      conditions:
        - entity: sensor.dreame_a2_mower_current_activity
          state: idle
        - entity: binary_sensor.dreame_a2_mower_in_dock
          state: "off"
        - entity: binary_sensor.dreame_a2_mower_mowing_session_active
          state: "off"
      card:
        type: horizontal-stack
        cards:
          - type: button
            name: Recharge
            icon: mdi:battery-charging
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_recharge
```

**Note on `state_not`:** Lovelace `conditional` cards don't natively support `state_not` — instead they require the inverse list. If `state_not: charging` is rejected, replace with `state: [not_charging, unknown]` or use a template-based card. Verify in HA UI; if rejected, use `state: not_charging`.

- [ ] **Step 5: yamllint + SCP + smoke test**

Verify behaviour by checking the dashboard against the current mower state. The current `current_activity` value tells you which row should be visible.

- [ ] **Step 6: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Mower tab — state-aware conditional action buttons"
```

---

### Task 10: Mower tab — GPS map + Head-to-Maintenance-Point placeholders

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Mower` view

- [ ] **Step 1: Locate GPS map + Head-to-Maintenance-Point cards**

```bash
grep -n "OpenStreetMap\|map_panel\|gps\|maintenance.*point\|head_to" dashboards/mower/dashboard.yaml | head -10
```

- [ ] **Step 2: Comment out the GPS card and replace with placeholder**

Find the existing GPS map card. Wrap the existing YAML in comments by prefixing each line with `#`, then add this placeholder below it:

```yaml
# --- GPS tracking card disabled until we have a working location source ---
# (original YAML preserved as comment block below for future restoration)
#  - type: ...
#    ...
- type: markdown
  content: |
    ### GPS Tracking
    Work in progress — Dreame does not expose live GPS coordinates
    over the cloud API. The map will reappear here once we identify
    the correct source.
```

- [ ] **Step 3: Same treatment for Head-to-Maintenance-Point**

```yaml
# --- Head-to-Maintenance-Point disabled until cruise/maintenance op is reachable ---
#  - type: ...
#    ...
- type: markdown
  content: |
    ### Head to Maintenance Point
    Work in progress — the cruise-to-point command (op=109) is not
    routable from the integration via the cloud-RPC surface. See
    `docs/research/cruise-to-point-todo.md`.
```

- [ ] **Step 4: yamllint + SCP + smoke test**

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "chore(dashboard): GPS + Head-to-MP cards → WIP placeholders"
```

---

### Task 11: Maps tab — base-maps only + Map 2 clipping fix

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Map Selector` view (already touched by Task 7)
- Modify: `custom_components/dreame_a2_mower/camera.py` — find the per-map camera class; ensure a "base map" variant exists or that the camera entity returns base-only when the live trail isn't active.

- [ ] **Step 1: Inspect map camera entities**

```bash
grep -n "class DreameA2MapCamera\|_static_map_pngs_by_id\|_render_live\|render_with_trail\|render_base_map" custom_components/dreame_a2_mower/camera.py | head -10
```
Note: there's likely already a path that uses `render_base_map` when live trail is inactive. The Map Selector tab should always show the BASE map regardless of live-trail state.

- [ ] **Step 2: Verify the per-map camera entity uses the right path**

Look at where the `DreameA2MapCamera.async_camera_image` (or equivalent) decides between trail and base. If it returns the base PNG when `_active_map_id != map_id`, no code change is needed — the trail only renders on the ACTIVE map. The Map Selector tab can keep its current entities.

If the inactive-map cameras also include trail overlays, add a guard that returns `_static_map_pngs_by_id[map_id]` for inactive maps.

- [ ] **Step 3: Diagnose Map 2 clipping**

```bash
grep -n "aspect_ratio\|camera.dreame_a2_mower_map_2\|map_2" dashboards/mower/dashboard.yaml | head -10
```

Likely cause: a single `aspect_ratio` value is applied to both map cards but Map 2's underlying PNG has a different W:H ratio. Fix by either:
- Removing `aspect_ratio` from the `picture-entity` cards (let them size to image)
- OR computing the per-map aspect from the PNG header and setting per-card values

For the easy fix, remove `aspect_ratio:` lines on the Map Selector tab's `picture-entity` cards.

- [ ] **Step 4: yamllint + SCP + smoke test**

Open Map Selector tab; both maps render without horizontal clip on Map 2.

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "fix(dashboard): Map Selector — base-only maps + Map 2 clipping fix"
```

---

### Task 12: Settings & Zones tab — base-map card + zone lists

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Settings & Zones` view (around line 239)

- [ ] **Step 1: Inspect current Settings & Zones tab**

```bash
sed -n '239,360p' dashboards/mower/dashboard.yaml
```

- [ ] **Step 2: Add base-map card at the top, then per-zone-type lists**

Replace the view's `cards:` body with:

```yaml
- title: Settings & Zones
  path: settings-zones
  cards:
    - type: markdown
      content: |
        ## Active Map: {{ states('select.dreame_a2_mower_active_map') }}
        Switch maps on the **Map Selector** tab.
    # Base map for the active map (no live trails on this tab)
    - type: picture-entity
      entity: camera.dreame_a2_mower_active_map_base
      show_state: false
      show_name: false
      tap_action:
        action: more-info
    # Exclusion zones (red)
    - type: entities
      title: Exclusion zones
      show_header_toggle: false
      entities:
        - entity: sensor.dreame_a2_mower_exclusion_zones
          name: Count
        - type: attribute
          entity: sensor.dreame_a2_mower_exclusion_zones
          attribute: zones
          name: Zone list
    # Ignore-obstacle zones (green)
    - type: entities
      title: Ignore-obstacle zones
      show_header_toggle: false
      entities:
        - entity: sensor.dreame_a2_mower_designated_ignore_zones
          name: Count
        - type: attribute
          entity: sensor.dreame_a2_mower_designated_ignore_zones
          attribute: zones
          name: Zone list
    # Spots
    - type: entities
      title: Spots
      show_header_toggle: false
      entities:
        - entity: sensor.dreame_a2_mower_spots
          name: Count
        - type: attribute
          entity: sensor.dreame_a2_mower_spots
          attribute: spots
          name: Spot list
    # Maintenance points
    - type: entities
      title: Maintenance points
      show_header_toggle: false
      entities:
        - entity: sensor.map_1_maintenance_points
          name: Map 1 count
        - entity: sensor.map_2_maintenance_points
          name: Map 2 count
    - type: markdown
      content: |
        > Read-only — all map edits happen in the Dreame app. See
        > `docs/research/map-edit-write-todo.md` for the write-surface
        > research status.
```

**Notes:**
- `camera.dreame_a2_mower_active_map_base` — this entity must exist. If the integration only exposes per-map cameras (e.g. `camera.dreame_a2_mower_map_1` / `..._map_2`), use a `picture-elements` card driven by `state_attr('select.dreame_a2_mower_active_map', 'current_map_id')` to pick the right camera. Alternatively add a new "active base map" camera in `camera.py` that mirrors whichever per-map base PNG matches the active map_id. The plan covers the rendering change in Task 4; here the dashboard expectation is just that the right entity is wired.
- `sensor.dreame_a2_mower_exclusion_zones` / `..._designated_ignore_zones` — verify these exist:

```bash
grep -n "exclusion_zones\|designated_ignore_zones\|spots\b" custom_components/dreame_a2_mower/sensor.py | head -10
```

- [ ] **Step 3: yamllint + SCP + smoke test**

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Settings & Zones — base map + per-zone-type lists"
```

---

### Task 13: Schedule tab — weekly grid + per-slot list

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Schedule` view (around line 358)

- [ ] **Step 1: Dig up the earlier weekly grid**

```bash
git log --oneline --all -- dashboards/mower/dashboard.yaml | head -20
git log -S "Monday\|weekly\|schedule_grid\|week_day" --oneline -- dashboards/mower/dashboard.yaml | head -10
```

Look for commits that introduce or remove a weekly grid. View the most likely candidate's diff:

```bash
git show <commit_sha> -- dashboards/mower/dashboard.yaml | head -200
```

Alternatively, check `dashboards/mower/dashboard.pre-phase2.yaml.bak`:

```bash
grep -n "Schedule\|weekly\|Monday" dashboards/mower/dashboard.pre-phase2.yaml.bak | head -20
sed -n '<line_range>' dashboards/mower/dashboard.pre-phase2.yaml.bak
```

- [ ] **Step 2: Port the weekly grid to current entity names**

The schedule sensors typically expose:
- `sensor.dreame_a2_mower_schedule_count`
- `sensor.dreame_a2_mower_schedule_slot_N_start_time` (or attributes on a single schedule sensor)
- `sensor.dreame_a2_mower_schedule_slot_N_days` (bitmask of 0-6 = Mon-Sun)

Confirm the entity layout:

```bash
grep -n "schedule_slot\|class.*Schedule\|key=\"schedule" custom_components/dreame_a2_mower/sensor.py | head -15
```

The weekly grid is a 7-column markdown table (one column per day of the week) with rows showing each slot's start time inside the appropriate column.

Replace the Schedule view's cards with the dug-up grid, adjusted to current entity names. The card structure is `markdown` with a templated table:

```yaml
- title: Schedule
  path: schedule
  cards:
    - type: markdown
      content: |
        ## Active Map: {{ states('select.dreame_a2_mower_active_map') }}
    - type: markdown
      content: >-
        ### Weekly view


        | Mon | Tue | Wed | Thu | Fri | Sat | Sun |

        |---|---|---|---|---|---|---|

        {% set ns = namespace(cells=['','','','','','','']) %}

        {% for slot in range(state_attr('sensor.dreame_a2_mower_schedule_count', 'slots') | length) %}

          {% set s = state_attr('sensor.dreame_a2_mower_schedule_count', 'slots')[slot] %}

          {% set start = s.start_time %}

          {% set days_bm = s.days_bitmask | int(0) %}

          {% for d in range(7) %}

            {% if (days_bm | bitwise_and(1 | bitwise_shift_left(d))) %}

              {% set ns.cells = ns.cells[:d] + [(ns.cells[d] ~ start ~ '<br>')] + ns.cells[d+1:] %}

            {% endif %}

          {% endfor %}

        {% endfor %}

        | {{ ns.cells[0] }} | {{ ns.cells[1] }} | {{ ns.cells[2] }} | {{ ns.cells[3] }} | {{ ns.cells[4] }} | {{ ns.cells[5] }} | {{ ns.cells[6] }} |
    - type: entities
      title: Schedule slots (active map)
      show_header_toggle: false
      entities:
        - entity: sensor.dreame_a2_mower_schedule_count
          name: Total slots
        - type: attribute
          entity: sensor.dreame_a2_mower_schedule_count
          attribute: slots
          name: Slot detail
```

**Important:** If the schedule sensor doesn't expose `slots` as a list attribute, this template won't work. Look at the actual sensor attributes:

```bash
python3 <<'EOF'
import json, websocket
with open('/data/claude/homeassistant/ha-credentials.txt') as f:
    TOKEN = f.read().splitlines()[3]
ws = websocket.create_connection("ws://10.0.0.30:8123/api/websocket", timeout=10)
ws.recv(); ws.send(json.dumps({"type":"auth","access_token":TOKEN})); ws.recv()
ws.send(json.dumps({"id":1,"type":"get_states"}))
for s in json.loads(ws.recv())["result"]:
    if "schedule" in s["entity_id"].lower() and "dreame" in s["entity_id"].lower():
        print(s["entity_id"], "=", s["state"])
        for k, v in (s.get("attributes") or {}).items():
            print(f"   {k}: {repr(v)[:100]}")
EOF
```

If `slots` is not an attribute, adapt the template to whatever IS present (e.g. iterate per-slot sensors).

- [ ] **Step 3: yamllint + SCP + smoke test**

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Schedule tab — weekly grid + per-slot list"
```

---

### Task 14: Sessions tab — calendar card + entity audit

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Sessions` view (around line 486)

- [ ] **Step 1: Inspect current Sessions tab**

```bash
sed -n '486,547p' dashboards/mower/dashboard.yaml
```

- [ ] **Step 2: Add the calendar card**

Insert a `calendar` card at the top of the Sessions view (uses the new `calendar.dreame_a2_mower_sessions` entity from Task 5):

```yaml
- type: calendar
  entities:
    - calendar.dreame_a2_mower_sessions
  initial_view: dayGridMonth
```

- [ ] **Step 3: Audit session entities for missing surface**

```bash
grep -n "session_\|class.*Session" custom_components/dreame_a2_mower/sensor.py | head -20
```

Compare against the existing Sessions tab YAML. Add any session-related sensors that aren't yet on the tab to a new `entities` card titled "Session details":

```yaml
- type: entities
  title: Session details
  show_header_toggle: false
  entities:
    - sensor.dreame_a2_mower_latest_session_area
    - sensor.dreame_a2_mower_latest_session_duration
    - sensor.dreame_a2_mower_latest_session_time
    - sensor.dreame_a2_mower_archived_session_count
    - sensor.dreame_a2_mower_session_distance
    - sensor.dreame_a2_mower_session_track_point_count
    # add any session sensors missing from the audit
```

- [ ] **Step 4: yamllint + SCP + smoke test**

Confirm the calendar shows archived sessions on the right dates.

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Sessions tab — calendar card + entity audit"
```

---

### Task 15: Diagnostics tab — add new sensors + cellular note

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Diagnostics` view (around line 619)

- [ ] **Step 1: Inspect current Diagnostics tab**

```bash
sed -n '619,684p' dashboards/mower/dashboard.yaml
```

- [ ] **Step 2: Add new entries**

Find the Diagnostics view's `entities` card(s) and add:

```yaml
# Inside the existing Diagnostics entities card:
- sensor.dreame_a2_mower_cloud_device_id
- sensor.dreame_a2_mower_api_endpoint
- sensor.dreame_a2_mower_integration_version
```

Then add a markdown card at the bottom of the view:

```yaml
- type: markdown
  content: |
    ### Connectivity

    - **WiFi:** see `sensor.dreame_a2_mower_wifi_rssi_dbm`
    - **Bluetooth:** not observable from this integration
    - **Cellular:** g2408 is WiFi-only (no cellular radio)

    ### Not exposed by Dreame cloud

    - IP address
    - MQTT / API protocol version
```

- [ ] **Step 3: yamllint + SCP + smoke test**

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Diagnostics tab — cloud device-id, API endpoint, integration version"
```

---

### Task 16: Tools tab — enumerate tool entities

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Tools` view (around line 684)

- [ ] **Step 1: Find all button entities**

```bash
grep -n "key=\"\\|BUTTON_DESCRIPTIONS" custom_components/dreame_a2_mower/button.py | head -20
```

- [ ] **Step 2: Inspect current Tools tab**

```bash
sed -n '684,721p' dashboards/mower/dashboard.yaml
```

- [ ] **Step 3: Add missing tool buttons**

The Tools tab should expose buttons that perform diagnostic/refresh/dump actions — typically:

```yaml
- title: Tools
  path: tools
  cards:
    - type: entities
      title: Diagnostic actions
      show_header_toggle: false
      entities:
        - button.dreame_a2_mower_find
        - button.dreame_a2_mower_refresh_wifi_archive
        - button.dreame_a2_mower_dump_cloud_state
        - button.dreame_a2_mower_force_cfg_refresh
        # Add others found in Step 1 that aren't already on the Mower tab
```

Match the button entity_ids found in Step 1.

- [ ] **Step 4: yamllint + SCP + smoke test**

- [ ] **Step 5: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Tools tab — enumerate diagnostic/refresh buttons"
```

---

### Task 17: Photo Privacy tab — policy text + AI toggle caveat

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — `Photo Privacy` view (around line 721)

- [ ] **Step 1: Locate the privacy policy text**

```bash
grep -rn "privacy_policy\|PRIVACY_POLICY\|privacy policy" custom_components/dreame_a2_mower/ docs/ 2>&1 | grep -v __pycache__ | head -10
```

If the full text isn't checked in, write a short paraphrase + link out. **Do not copy proprietary text** the project doesn't already include.

- [ ] **Step 2: Replace the Photo Privacy view body**

```yaml
- title: Photo Privacy
  path: privacy
  cards:
    - type: markdown
      content: |
        ## Photo Privacy

        The Dreame A2 mower has a camera that can capture obstacle
        recognition photos. By default these are sent to Dreame's
        cloud for AI processing.

        ### Privacy policy
        See the official Dreame privacy policy at:
        https://www.dreame.tech/policy/privacy

        You must accept the policy in the Dreame app before any
        AI-related features will work.
    - type: entities
      title: AI Photo capture
      show_header_toggle: false
      entities:
        - entity: switch.dreame_a2_mower_ai_human
          name: Capture obstacle photos
    - type: markdown
      content: |
        > ⚠️ Toggling this switch on only takes effect if you've
        > accepted the AI privacy policy in the Dreame app. There is
        > no way to accept the policy from Home Assistant.
```

- [ ] **Step 3: yamllint + SCP + smoke test**

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): Photo Privacy tab — policy link + AI toggle caveat"
```

---

## Phase 3 — Release

### Task 18: Release v1.0.9a1

**Files:**
- Tagged via `tools/release.sh`

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest 2>&1 | tail -3
```
Expected: PASS count = (previous baseline) + 10 (3 sensor + 3 archive + 1 camera + 1 render + 2 calendar). No failures.

- [ ] **Step 2: Push commits**

```bash
git push origin main
```

- [ ] **Step 3: Run release script**

```bash
tools/release.sh 1.0.9a1
```
Expected: ✅ release v1.0.9a1 published cleanly.

- [ ] **Step 4: Verify HACS pickup**

The release.sh script triggers a HACS refresh. After ~30s, check the integration tile in HA UI shows v1.0.9a1 available.

- [ ] **Step 5: Smoke test the live integration**

After updating in HACS and reloading the integration:
- Mower tab: action buttons match current state (only relevant row visible)
- Map Selector: tap-to-zoom + Select buttons functional
- Settings & Zones: base map present with all overlays
- Sessions: calendar card shows recent mows
- Diagnostics: new sensors populated (`BM169439`, `eu.iot.dreame.tech:19973`, `1.0.9a1`)

---

## Self-review

**Spec coverage check:**

| Spec section | Task |
|---|---|
| Mower tab — "Mowing target" card | Task 8 |
| Mower tab — state card with state-machine entities | Task 8 (entities footer) + Task 15 sensor audit cover this; state-machine entities already exist |
| Mower tab — state-aware buttons (6 rows) | Task 9 |
| Mower tab — base map with maintenance points | Task 4 (renderer) |
| Mower tab — GPS placeholder | Task 10 |
| Mower tab — Head-to-MP placeholder | Task 10 |
| Map Selector — Select buttons + highlight | Task 7 |
| Map Selector — base-maps only | Task 11 |
| Map Selector — Map 2 clipping fix | Task 11 |
| Settings & Zones — base map | Task 12 |
| Settings & Zones — zone list cards | Task 12 |
| Schedule — weekly grid | Task 13 |
| Schedule — per-slot list | Task 13 |
| WiFi heatmap — initial render fix | Task 3 |
| Sessions — calendar entity | Task 5 |
| Sessions — calendar card | Task 14 |
| Sessions — entity audit | Task 14 |
| Sessions — persist session_distance_m | Task 1 |
| Diagnostics — cloud device-id | Tasks 2 + 15 |
| Diagnostics — API endpoint | Tasks 2 + 15 |
| Diagnostics — integration version | Tasks 2 + 15 |
| Diagnostics — cellular note | Task 15 |
| Tools — enumerate entities | Task 16 |
| Privacy — policy text | Task 17 |
| Privacy — AI toggle + caveat | Task 17 |
| Release | Task 18 |

All spec requirements covered.

**Placeholder scan:** No "TBD" / "TODO" / vague language. Each step has executable commands or full code blocks.

**Type consistency:** `ArchivedSession.session_distance_m` referenced consistently across Tasks 1, 5, 14. `select.dreame_a2_mower_active_map` referenced consistently across Tasks 7, 8, 12, 13. State-machine entity ids (`sensor.dreame_a2_mower_current_activity`, `binary_sensor.dreame_a2_mower_in_dock`, `binary_sensor.dreame_a2_mower_mowing_session_active`, `sensor.dreame_a2_mower_charging_status`) referenced consistently in Task 9.

**Scope check:** This is a single cohesive plan — dashboard cleanup. The 5 code changes are small additions, all in service of dashboard surfaces. Could split into "code first / YAML second" sub-plans but the bite-sized task structure already captures that order (Phase 1 → Phase 2 → Phase 3).
