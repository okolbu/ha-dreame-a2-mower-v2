# Head-to-Maintenance-Point Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a maintenance/clean point per map and send the mower there (op=109) via a dedicated "Head to point" trigger separate from Start, wired into the dashboard.

**Architecture:** Mirror the existing spot-mow path. New typed action `GO_TO_POINT` → `routed_action(109, {"point":[id]})`; coordinator `start_go_to_point(map_id, point_id)` switches the active map first; a per-map "Maintenance point" select stores `(map_id, point_id)` on `MowerState`; a per-map "Head to point" button reads it and triggers. Read side (`MapData.maintenance_points`) already exists.

**Tech Stack:** Python, Home Assistant entity platforms (select/button), pytest (`asyncio_mode=auto`), the `/data/claude/homeassistant/.venv-vanilla` interpreter.

**Conventions (must follow):**
- Per-map naming (CLAUDE.md): per-map entities use `map_unique_id` / `map_device_info`; `_attr_name` is the bare entity name only.
- Inventory discipline (CLAUDE.md): adding entities requires `entity-inventory.yaml` entries (CI `inventory-touch-gate`).
- Run tests from the repo root with: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v`. Baseline: 1591 passed / 4 skipped.
- Commit per task, staging by **explicit path** (a concurrent process commits with `add -A`).

---

### Task 1: Action layer — `GO_TO_POINT` + payload

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/actions.py`
- Test: `tests/integration/test_go_to_point.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_go_to_point.py`:

```python
"""op=109 go-to-point: action payload + table wiring."""
import pytest


def test_go_to_point_payload_builds_point_list():
    from custom_components.dreame_a2_mower.mower.actions import _go_to_point_payload
    assert _go_to_point_payload({"point_id": 1}) == {"point": [1]}
    assert _go_to_point_payload({"point_id": "5"}) == {"point": [5]}


def test_go_to_point_payload_requires_point_id():
    from custom_components.dreame_a2_mower.mower.actions import _go_to_point_payload
    with pytest.raises(ValueError):
        _go_to_point_payload({})


def test_go_to_point_action_table_entry():
    from custom_components.dreame_a2_mower.mower.actions import (
        ACTION_TABLE,
        MowerAction,
        _go_to_point_payload,
    )
    entry = ACTION_TABLE[MowerAction.GO_TO_POINT]
    assert entry["routed_o"] == 109
    assert entry["routed_t"] == "TASK"
    assert entry["payload_fn"] is _go_to_point_payload
```

- [ ] **Step 2: Run it — expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py -v`
Expected: FAIL (`AttributeError` / `MowerAction has no GO_TO_POINT`).

- [ ] **Step 3: Add the enum member**

In `mower/actions.py`, in `class MowerAction`, add after `START_SPOT_MOW = auto()`:

```python
    GO_TO_POINT = auto()
```

- [ ] **Step 4: Add the payload builder**

In `mower/actions.py`, after `_spot_mow_payload`:

```python
def _go_to_point_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope d-field for go-to-point / Head to Maintenance Point (op=109).

    Live-confirmed 2026-05-31: ``routed_action(109, {"point":[point_id]})`` drives
    the mower to a per-map cleanPoint on the ACTIVE map. The d-key is the target
    TYPE (``point``); reusing spot's ``{area:[id]}`` with o=109 is rejected
    (``s2p50 o:109 status:false``). See inventory.yaml o109.
    """
    if "point_id" not in params:
        raise ValueError("GO_TO_POINT requires 'point_id' param")
    return {"point": [int(params["point_id"])]}
```

- [ ] **Step 5: Wire the table entry**

In `mower/actions.py`, in `ACTION_TABLE`, add after the `START_SPOT_MOW` entry:

```python
    MowerAction.GO_TO_POINT: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 109,
        "payload_fn": _go_to_point_payload,
    },
```

- [ ] **Step 6: Run — expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/actions.py tests/integration/test_go_to_point.py
git commit -m "feat(go-to-point): MowerAction.GO_TO_POINT + {point:[id]} payload (op=109)"
```

---

### Task 2: State field — `active_selection_point`

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py:288` (after `active_selection_spots`)
- Test: `tests/integration/test_go_to_point.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/integration/test_go_to_point.py`:

```python
def test_mower_state_active_selection_point_defaults_none():
    import dataclasses
    from custom_components.dreame_a2_mower.mower.state import MowerState
    s = MowerState()
    assert s.active_selection_point is None
    s2 = dataclasses.replace(s, active_selection_point=(0, 1))
    assert s2.active_selection_point == (0, 1)
```

- [ ] **Step 2: Run — expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py::test_mower_state_active_selection_point_defaults_none -v`
Expected: FAIL (`TypeError: ... unexpected keyword 'active_selection_point'`).

- [ ] **Step 3: Add the field**

In `mower/state.py`, immediately after the line `active_selection_spots: tuple[int, ...] = ()`:

```python
    # Source: the per-map Maintenance-point select. Stored as
    # (map_id, point_id) so each map's Head-to-point button only acts on a
    # point chosen on THAT map. None = nothing selected.
    active_selection_point: tuple[int, int] | None = None
```

- [ ] **Step 4: Run — expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py tests/integration/test_go_to_point.py
git commit -m "feat(go-to-point): MowerState.active_selection_point (map_id, point_id)"
```

---

### Task 3: Coordinator — `start_go_to_point`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` (after `start_mowing_spot`, ~line 535)
- Test: `tests/integration/test_go_to_point.py` (append)

- [ ] **Step 1: Write the failing test** — append:

```python
async def test_start_go_to_point_switches_map_then_dispatches():
    from unittest.mock import AsyncMock
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    class _Stub(_WritesMixin):
        def __init__(self):
            self._ensure_active_map = AsyncMock()
            self.dispatch_action = AsyncMock()

    c = _Stub()
    await c.start_go_to_point(map_id=2, point_id=7)
    c._ensure_active_map.assert_awaited_once_with(2)
    c.dispatch_action.assert_awaited_once_with(
        MowerAction.GO_TO_POINT, {"point_id": 7}
    )
```

(No `@pytest.mark.asyncio` needed — `asyncio_mode = "auto"`.)

- [ ] **Step 2: Run — expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py::test_start_go_to_point_switches_map_then_dispatches -v`
Expected: FAIL (`AttributeError: ... has no attribute 'start_go_to_point'`).

- [ ] **Step 3: Implement** — in `coordinator/_writes.py`, after `start_mowing_spot`:

```python
    async def start_go_to_point(self, *, map_id: int, point_id: int) -> None:
        """Send the mower to a maintenance/clean point on the given map (op=109).

        Confirmed 2026-05-31: ``routed_action(109, {"point":[id]})``. ``point_id``
        is a per-map cleanPoint id, so the map must be active first.
        """
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.GO_TO_POINT, {"point_id": point_id}
        )
```

(`MowerAction` is already imported in `_writes.py`.)

- [ ] **Step 4: Run — expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_go_to_point.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_go_to_point.py
git commit -m "feat(go-to-point): coordinator.start_go_to_point (active-map switch + dispatch)"
```

---

### Task 4: Per-map select — `DreameA2MaintenancePointSelect`

**Files:**
- Modify: `custom_components/dreame_a2_mower/select_map_settings.py` (new class at end)
- Modify: `custom_components/dreame_a2_mower/select.py` (import + register in the per-map loop)
- Test: `tests/integration/test_maintenance_point_select.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_maintenance_point_select.py`:

```python
"""Per-map maintenance-point select: options, per-map (map_id, point_id) store."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.mower.state import MowerState


def _points(*ids):
    out = []
    for i in ids:
        p = MagicMock(); p.point_id = i; p.x_mm = 0.0; p.y_mm = 0.0
        out.append(p)
    return tuple(out)


def _setup(coord):
    coord.cloud_state.maps_by_id[0].maintenance_points = _points(1, 5)
    coord.cloud_state.maps_by_id[1].maintenance_points = ()
    coord.data = MowerState()


def test_options_are_point_labels_plus_placeholder(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    assert e0.options == ["(no point selected)", "Point 1", "Point 5"]


def test_empty_map_shows_no_points_placeholder(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e1 = DreameA2MaintenancePointSelect(coord, map_id=1)
    assert e1.options == ["(no points on this map)"]


def test_unique_id_and_device_are_per_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    assert e0._attr_unique_id == "G2408053AEE0006232_map_0_maintenance_point"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


async def test_select_stores_map_scoped_pick(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    await e0.async_select_option("Point 5")
    new_state = coord.async_set_updated_data.call_args.args[0]
    assert new_state.active_selection_point == (0, 5)


def test_current_option_is_map_scoped(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    coord.data = MowerState(active_selection_point=(0, 1))
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    e1 = DreameA2MaintenancePointSelect(coord, map_id=1)
    assert e0.current_option == "Point 1"
    # map 1 has no points and the pick belongs to map 0 → its placeholder
    assert e1.current_option == "(no points on this map)"
```

- [ ] **Step 2: Run — expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_maintenance_point_select.py -v`
Expected: FAIL (`ImportError: cannot import name 'DreameA2MaintenancePointSelect'`).

- [ ] **Step 3: Implement the select** — append to `select_map_settings.py`:

```python
class DreameA2MaintenancePointSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Per-map picker for the maintenance/clean point the Head-to-point button
    targets. Options are ``Point {id}`` from the map's ``maintenance_points``.

    The selection is stored per-map as
    ``MowerState.active_selection_point = (map_id, point_id)`` so each map's
    button only acts on a point chosen on that map.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker"
    _PLACEHOLDER = "(no point selected)"
    _NO_POINTS = "(no points on this map)"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "maintenance_point")
        self._attr_name = "Maintenance point"
        md = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(md, "name", None) if md is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)

    def _points(self) -> tuple:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        if md is None:
            return ()
        return tuple(getattr(md, "maintenance_points", ()) or ())

    @staticmethod
    def _label(point_id: int) -> str:
        return f"Point {point_id}"

    @property
    def options(self) -> list[str]:
        pts = self._points()
        if not pts:
            return [self._NO_POINTS]
        return [self._PLACEHOLDER] + [self._label(int(p.point_id)) for p in pts]

    @property
    def current_option(self) -> str | None:
        sel = self.coordinator.data.active_selection_point
        if sel is not None and sel[0] == self._map_id:
            label = self._label(int(sel[1]))
            if label in self.options:
                return label
        return self._NO_POINTS if not self._points() else self._PLACEHOLDER

    async def async_select_option(self, option: str) -> None:
        if option in (self._PLACEHOLDER, self._NO_POINTS):
            new = dataclasses.replace(
                self.coordinator.data, active_selection_point=None
            )
            self.coordinator.async_set_updated_data(new)
            return
        for p in self._points():
            if self._label(int(p.point_id)) == option:
                new = dataclasses.replace(
                    self.coordinator.data,
                    active_selection_point=(self._map_id, int(p.point_id)),
                )
                self.coordinator.async_set_updated_data(new)
                return
        LOGGER.warning(
            "select.%s: unknown option %r — ignoring", self._attr_unique_id, option
        )
```

(`dataclasses`, `CoordinatorEntity`, `SelectEntity`, `map_unique_id`, `map_device_info`, `LOGGER`, `DreameA2MowerCoordinator` are all already imported at the top of `select_map_settings.py`.)

- [ ] **Step 4: Register in `select.py`**

In `select.py`, add `DreameA2MaintenancePointSelect` to the import from `select_map_settings` (the same import line that brings in `DreameA2ZoneSelect`/`DreameA2SpotSelect`), then inside the existing
`for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):` block that adds `DreameA2ZoneSelect`/`DreameA2SpotSelect`/`DreameA2EdgeSelect`, add:

```python
            DreameA2MaintenancePointSelect(coordinator, map_id=map_id),
```

- [ ] **Step 5: Run — expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_maintenance_point_select.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/select_map_settings.py custom_components/dreame_a2_mower/select.py tests/integration/test_maintenance_point_select.py
git commit -m "feat(go-to-point): per-map Maintenance point select (stores (map_id, point_id))"
```

---

### Task 5: Per-map button — `DreameA2HeadToPointButton`

**Files:**
- Modify: `custom_components/dreame_a2_mower/button.py` (import + new class + per-map registration)
- Test: `tests/integration/test_head_to_point_button.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_head_to_point_button.py`:

```python
"""Per-map Head-to-point button: availability + dispatch to start_go_to_point."""
from unittest.mock import AsyncMock

from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_unique_id_and_device_are_per_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    assert b0._attr_unique_id == "G2408053AEE0006232_map_0_head_to_point"
    assert b0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_available_only_when_point_selected_for_this_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    b1 = DreameA2HeadToPointButton(coord, map_id=1)
    coord.data = MowerState(active_selection_point=(0, 1))
    assert b0.available is True
    assert b1.available is False
    coord.data = MowerState(active_selection_point=None)
    assert b0.available is False


async def test_press_dispatches_start_go_to_point(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.start_go_to_point = AsyncMock()
    coord.data = MowerState(active_selection_point=(0, 5))
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    await b0.async_press()
    coord.start_go_to_point.assert_awaited_once_with(map_id=0, point_id=5)


async def test_press_noop_when_selection_for_other_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.start_go_to_point = AsyncMock()
    coord.data = MowerState(active_selection_point=(0, 5))
    b1 = DreameA2HeadToPointButton(coord, map_id=1)
    await b1.async_press()
    coord.start_go_to_point.assert_not_awaited()
```

- [ ] **Step 2: Run — expect failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_head_to_point_button.py -v`
Expected: FAIL (`ImportError: cannot import name 'DreameA2HeadToPointButton'`).

- [ ] **Step 3: Add imports to `button.py`**

Change the `_devices` import line in `button.py` from:

```python
from ._devices import mower_device_info, mower_unique_id
```

to:

```python
from ._devices import (
    map_device_info,
    map_unique_id,
    mower_device_info,
    mower_unique_id,
)
```

- [ ] **Step 4: Add the button class** — at the end of `button.py`:

```python
class DreameA2HeadToPointButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Per-map 'Head to point' trigger — sends the mower to the point picked in
    this map's Maintenance-point select (op=109). Distinct from Start: the app
    treats go-to-point as its own mode, so it gets its own trigger.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-right"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "head_to_point")
        self._attr_name = "Head to point"
        md = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(md, "name", None) if md is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)

    @property
    def available(self) -> bool:
        sel = self.coordinator.data.active_selection_point
        return bool(sel is not None and sel[0] == self._map_id)

    async def async_press(self) -> None:
        sel = self.coordinator.data.active_selection_point
        if sel is None or sel[0] != self._map_id:
            LOGGER.warning(
                "button.%s: no point selected for this map; no-op",
                self._attr_unique_id,
            )
            return
        await self.coordinator.start_go_to_point(
            map_id=self._map_id, point_id=int(sel[1])
        )
```

- [ ] **Step 5: Register per-map** — in `button.py:async_setup_entry`, after `async_add_entities(entities)` is currently the last line; replace the tail so the per-map buttons are added before the call. Change:

```python
    async_add_entities(entities)
```

to:

```python
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.append(DreameA2HeadToPointButton(coordinator, map_id=map_id))
    async_add_entities(entities)
```

- [ ] **Step 6: Run — expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_head_to_point_button.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/button.py tests/integration/test_head_to_point_button.py
git commit -m "feat(go-to-point): per-map Head-to-point button → start_go_to_point"
```

---

### Task 6: Entity inventory entries

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Read the file's schema** — open `entity-inventory.yaml`, find the `DreameA2SpotSelect` and a per-map button entry; copy their field shape (id/platform/class/unique_id_suffix/source/status/verifications).

- [ ] **Step 2: Add two entries** modelled on the spot select + an action button, e.g.:

```yaml
  - id: "maintenance_point_select"
    platform: select
    class: DreameA2MaintenancePointSelect
    per_map: true
    unique_id_suffix: "map_{map_id}_maintenance_point"
    name: "Maintenance point"
    source: "cloud_state.maps_by_id[map].maintenance_points (cleanPoints); selection stored as MowerState.active_selection_point (map_id, point_id)"
    semantic: "Per-map picker for the Head-to-point target. Options 'Point {id}'."
    status:
      decoded: presumed
    verifications:
      - date: "2026-05-31"
        status: presumed
        claim: "Per-map select stores (map_id, point_id); options from maintenance_points. Code-read, live validation pending."

  - id: "head_to_point_button"
    platform: button
    class: DreameA2HeadToPointButton
    per_map: true
    unique_id_suffix: "map_{map_id}_head_to_point"
    name: "Head to point"
    source: "MowerState.active_selection_point → coordinator.start_go_to_point → routed_action(109, {point:[id]})"
    semantic: "Per-map trigger for op=109 Head to Maintenance Point. Available only when a point is selected for this map."
    status:
      decoded: presumed
    verifications:
      - date: "2026-05-31"
        status: presumed
        claim: "Press dispatches start_go_to_point(map_id, point_id). Protocol confirmed (inventory.yaml o109); entity wiring live-validation pending."
```

(Match the exact field names/indentation used by neighbouring entries — adjust if the file's schema differs.)

- [ ] **Step 3: Validate YAML + run the inventory audit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/entity-inventory.yaml')); print('OK')"`
Run (if present): `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_audit.py`
Expected: YAML OK; audit passes (or reports only pre-existing items).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "docs(go-to-point): entity-inventory entries for point select + Head-to button"
```

---

### Task 7: Full-suite regression

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: baseline + 14 new tests pass (≈1605 passed / 4 skipped), **0 failures**. If anything unrelated broke, fix or report before continuing.

- [ ] **Step 2: Per-map naming sanity** — confirm the new entity_ids land in the namespace:

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_per_map_entity_names.py -q`
Expected: pass (the new classes follow `map_unique_id`/`map_device_info`, so entity_ids are `select.dreame_a2_mower_map_N_maintenance_point` / `button.dreame_a2_mower_map_N_head_to_point`).

- [ ] **Step 3: Commit** (only if Step 2 needed a names-test addition; otherwise skip).

---

### Task 8: Dashboard wiring + deploy

**Files:**
- Modify: `/config/dashboards/mower/dashboard.yaml` (live HA box, via SCP) — replace the "Head to Maintenance Point" placeholder.
- Reference: `reference_ha_dashboard_deploy` (sshpass SCP to `/config/dashboards/mower/`, backup first, browser-reload — NO HA restart).

- [ ] **Step 1: Pull the current dashboard + back it up** (per the dashboard-deploy procedure). Locate the "Head to Maintenance Point" placeholder card.

- [ ] **Step 2: Replace the placeholder** with the two new entities (entity_ids assume map 1 = map_id 0; add per-map rows for additional maps):

```yaml
      - type: entities
        title: Head to Maintenance Point
        entities:
          - entity: select.dreame_a2_mower_map_1_maintenance_point
            name: Point
          - entity: button.dreame_a2_mower_map_1_head_to_point
            name: Head to point
```

(Confirm the exact entity_ids in HA Developer Tools → States after the integration reload; per-map device naming may slug differently if the map was renamed.)

- [ ] **Step 3: Deploy** via the documented SCP procedure; browser-reload the dashboard (no HA restart).

- [ ] **Step 4: Verify** the card renders, the dropdown lists `Point 1` / `Point 5` (etc.), and the button is disabled until a point is picked.

- [ ] **Step 5: Commit** the bundled dashboard copy in-repo (if the repo keeps one under `dashboards/`), explicit path.

---

### Task 9: Live validation + Bug D (To-Point on live map)

**Files:** `custom_components/dreame_a2_mower/entity-inventory.yaml` (record results); possibly the session-begin / live-map render path if a gap is found.

- [ ] **Step 1: Reload the config entry** so the new entities register (per `feedback_ha_dev_gotchas`: `config_entries/reload`).

- [ ] **Step 2: Trigger from HA** — pick a point in the dropdown, press **Head to point**. Confirm via HA logs (`button.…head_to_point: ...` → `dispatch_action GO_TO_POINT`) and physically that the mower leaves the dock and drives to the point.

- [ ] **Step 3: Bug D check** — watch the live-map camera: does the mower render, and is the run typed as a To-Point session? Note: this is now an **integration-triggered** run (the coordinator's session-begin path runs), unlike the earlier standalone-probe run.

- [ ] **Step 4: If the mower does NOT render**, trace: To-Point session begin/classify (`coordinator/_session.py`, the non-mow-session typing) → live-map render (`coordinator/_rendering.py`). Identify whether `begin_session` fires for op=109 and whether the live-trail render draws the mower for a non-mow session. Fix the specific gap (with a regression test), commit. If it DOES render, no code change — record that.

- [ ] **Step 5: Record results** — update the Task-6 `entity-inventory.yaml` entries from `presumed` → `verified` (or `partial`) with the live evidence (button press → mower moved; live-map render outcome). Commit, explicit path.

---

### Task 10: Version bump + release

**Files:** `custom_components/dreame_a2_mower/manifest.json` (version), via the repo release flow.

- [ ] **Step 1: Bump the alpha version** following `feedback_hacs_version_ladder` (bump the patch if the alpha counter crosses a digit boundary, e.g. `…a9 → …a10` needs a patch bump).

- [ ] **Step 2: Run the release pipeline** — `release.sh` handles bump+tag+push+GitHub Release (`--prerelease`)+HACS refresh in one shot (`feedback_subagent_release_pipeline`, `feedback_tag_after_push`: a GitHub **Release** is required, not just a tag).

- [ ] **Step 3: In HA** — HACS update to the new pre-release, reload, and re-run the Task-9 live check end-to-end on the shipped build.

---

## Self-review notes

- **Spec coverage:** action (T1), state (T2), coordinator (T3), per-map select (T4), per-map button (T5), entity-inventory (T6), regression+naming (T7), dashboard (T8), bug-D verify/fix (T9), ship (T10). All spec sections covered.
- **Out of scope (per spec):** write-targets doc (unit B) and missing Start/Recharge controls (unit C) are intentionally not here.
- **Type consistency:** `active_selection_point: tuple[int, int] | None`, `_go_to_point_payload` → `{"point":[id]}`, `start_go_to_point(*, map_id, point_id)`, unique-id suffixes `maintenance_point` / `head_to_point` — used identically across tasks and tests.
- **Assumptions to confirm during execution:** exact `entity-inventory.yaml` field schema (T6 Step 1); the `coordinator_with_two_maps` fixture's map mocks accept attribute assignment for `maintenance_points` (the maintenance-points sensor test sets it the same way); live entity_ids for the dashboard (T8 Step 2).
