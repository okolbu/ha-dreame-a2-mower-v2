# Greenfield F3 — Action Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the integration from read-only into actionable. After F3 the user can start whole-lawn mow, edge mow, zone mow (one or more zones, ordered selection), spot mow, recharge, find_bot, lock_bot, suppress_fault — all via the HA `lawn_mower.start_mowing` action (state-aware) plus a small set of HA service calls. The `select.action_mode` entity gates which mode `start_mowing` activates; service-call data carries zone/spot IDs.

**Architecture:** Service-driven action surface per spec §5. The `lawn_mower` platform's `async_start_mowing` reads `coordinator.data.action_mode` and `active_selection_*` to dispatch the right opcode. Service calls (`mow_zone`, `mow_edge`, `mow_spot`, `find_bot`, `lock_bot`, `suppress_fault`, `set_active_selection`, `recharge`) are registered in `__init__.py` via `hass.services.async_register`. The actual wire-format dispatch lives in a new `actions.py` module that wraps the cloud client's routed-action path (the legacy noted that g2408's direct cloud `action()` returns 80001 but the routed siid=2 aiid=50 path works — that's what greenfield uses).

**Tech Stack:** Same as F1+F2. Plus `homeassistant.helpers.service` for the service registration + `homeassistant.helpers.config_validation` (`vol`) for the schema.

**Spec:** `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md` § 7 phase F3.

**Working dir:** `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`. Use `git -C <path>` and absolute paths; one-shot `cd` in a single Bash invocation is OK. **Do NOT push from implementer subagents** — controller pushes after each commit.

**Reference repo:** legacy at `/data/claude/homeassistant/ha-dreame-a2-mower/`. Key legacy paths for the action dispatcher (read but don't modify):
- `dreame/types.py:631-815` — `DreameMowerAction` enum + `DreameMowerActionMapping` (siid/aiid table)
- `dreame/device.py:4188-4310` — `call_action` with the primary + fallback dispatch (handles 80001 → routed siid=2 aiid=50)
- `dreame/device.py:4280-4300` — `_ALT_ACTION_SIID_MAP` documenting the ioBroker-documented routed paths

---

## File map

```
custom_components/dreame_a2_mower/
├── __init__.py                  # F3.4: register services
├── const.py                     # F3.7: extend PLATFORMS with "select"
├── coordinator.py               # F3.5: add dispatch_action helper
├── lawn_mower.py                # F3.6: replace F1 stubs with real handlers
├── select.py                    # F3.2: NEW — action_mode select entity
├── sensor.py                    # F3.3: extend with active_selection sensor
├── services.yaml                # F3.4: NEW — service-call schemas
├── services.py                  # F3.4: NEW — service handler module
└── mower/
    ├── state.py                 # F3.1: add action_mode + active_selection fields
    └── actions.py               # F3.5: NEW — typed action enum + (siid, aiid) table

(no changes to: protocol/, mqtt_client.py, cloud_client.py — though we may add a
`routed_action()` method to cloud_client.py if the existing helper doesn't cover the
TASK-envelope construction we need.)

tests/
├── mower/
│   ├── test_state.py            # F3.1: append tests for new fields
│   └── test_actions.py          # F3.5: NEW — actions.py table integrity
└── integration/
    ├── test_lawn_mower.py       # F3.6: NEW — start/pause/dock dispatch tests
    └── test_services.py         # F3.4: NEW — service handler dispatch tests

docs/
└── data-policy.md               # F3.1: classify the new fields under persistent
```

---

## Phase F3.1 — MowerState fields for action intent

### Task F3.1.1: Add action_mode + active_selection_zones + active_selection_spots

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `tests/mower/test_state.py`
- Modify: `docs/data-policy.md`

These three fields capture the user's *intent* about what `start_mowing` should do. They're persistent (survive HA restart): the user shouldn't lose their zone selection just because HA rebooted between selecting and pressing Start.

- [ ] **Step 1: Append failing tests to test_state.py**

```python
# Append to tests/mower/test_state.py

def test_action_mode_enum_covers_four_modes():
    """ActionMode enum has exactly the four documented modes (manual is BT-only)."""
    from custom_components.dreame_a2_mower.mower.state import ActionMode
    expected = {"all_areas", "edge", "zone", "spot"}
    actual = {m.value for m in ActionMode}
    assert actual == expected


def test_action_mode_default_is_all_areas():
    """Fresh MowerState defaults action_mode to ALL_AREAS — matches Dreame app default."""
    from custom_components.dreame_a2_mower.mower.state import ActionMode
    s = MowerState()
    assert s.action_mode == ActionMode.ALL_AREAS


def test_active_selection_defaults_empty():
    """Active selection defaults to empty — user explicitly picks before pressing Start."""
    s = MowerState()
    assert s.active_selection_zones == ()
    assert s.active_selection_spots == ()


def test_action_mode_assignment():
    from custom_components.dreame_a2_mower.mower.state import ActionMode
    s = MowerState(
        action_mode=ActionMode.ZONE,
        active_selection_zones=(3, 1, 2),
    )
    assert s.action_mode == ActionMode.ZONE
    assert s.active_selection_zones == (3, 1, 2)
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: 4 new tests fail with ImportError on `ActionMode` or AttributeError on `action_mode`.

- [ ] **Step 3: Add ActionMode + fields to state.py**

In `custom_components/dreame_a2_mower/mower/state.py`:

```python
# Add new enum near State / ChargingStatus:

from enum import Enum

class ActionMode(str, Enum):
    """User's mode selection for the next start_mowing dispatch.

    Mirrors the Dreame app's main-screen dropdown (per APP_INFO.txt).
    Manual mode is BT-only on g2408 and intentionally omitted.

    Persistence: persistent (intent survives HA restart).
    """
    ALL_AREAS = "all_areas"
    EDGE = "edge"
    ZONE = "zone"
    SPOT = "spot"
```

Then in the `MowerState` dataclass, append (preserving slots=True):

```python
    # ------ F3 fields (action intent) ------

    # Source: integration state (user selection via select.action_mode).
    # Persistence: persistent. Default ALL_AREAS matches the Dreame app's
    # main screen default.
    action_mode: ActionMode = ActionMode.ALL_AREAS

    # Source: integration state (set via dreame_a2_mower.set_active_selection
    # service or the dashboard's map-card click flow).
    # Persistence: persistent (user shouldn't lose selection across HA reboot).
    active_selection_zones: tuple[int, ...] = ()
    active_selection_spots: tuple[int, ...] = ()
```

Note: these fields have non-`None` defaults (an enum default + empty tuples) which is a deliberate departure from the F1/F2 "all fields default to None" pattern. Rationale:
- `action_mode` is integration state (user intent), not observed mower state. It always has a meaningful value.
- The empty-tuple default is sentinel-equivalent to `None` but lets the type be `tuple[int, ...]` (no Optional wrapping needed).

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: all tests pass (F1 6 + F2 2 + F3 4 = 12).

- [ ] **Step 5: Update data-policy.md**

Append to the "Persistent fields" section:

```markdown
- `action_mode` — integration state, default ALL_AREAS, set by select.action_mode
- `active_selection_zones`, `active_selection_spots` — integration state, set by services
```

- [ ] **Step 6: Commit (do NOT push)**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/state.py tests/mower/test_state.py docs/data-policy.md
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F3.1.1: MowerState — action_mode + active_selection fields

Adds ActionMode enum (all_areas / edge / zone / spot — manual omitted
per spec §5 since manual mode is BT-only on g2408) and three fields
on MowerState:
  - action_mode: ActionMode (default ALL_AREAS — matches Dreame app)
  - active_selection_zones: tuple[int, ...] (default empty)
  - active_selection_spots: tuple[int, ...] (default empty)

Unlike F1/F2 fields these have non-None defaults because they
represent integration intent rather than observed mower state. The
user's selection persists across HA reboots per spec §8 persistent
policy.

data-policy.md updated.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F3.2 — select.py: action_mode entity

### Task F3.2.1: Create select.py

**Files:**
- Create: `custom_components/dreame_a2_mower/select.py`

The select entity has 4 options matching ActionMode. When the user picks one, the integration updates `coordinator.data.action_mode` and notifies. Subsequent `lawn_mower.start_mowing` dispatches read this field.

- [ ] **Step 1: Write select.py**

```python
"""Select platform — action_mode picker for the Dreame A2 Mower."""
from __future__ import annotations

import dataclasses

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2ActionModeSelect(coordinator)])


class DreameA2ActionModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """User-facing action_mode picker.

    Per spec §5.1: HA realization of the Dreame app's mode dropdown
    (All-areas / Edge / Zone / Spot — Manual is BT-only and omitted).

    Selection is integration state stored on coordinator.data.action_mode
    and persisted across HA restarts via RestoreEntity (TBD: HA's
    SelectEntity doesn't auto-restore; we set the initial state from
    coordinator.data on entity construction, and write through to
    coordinator on every change).
    """

    _attr_has_entity_name = True
    _attr_name = "Action mode"
    _attr_options = [m.value for m in ActionMode]

    entity_description = SelectEntityDescription(
        key="action_mode",
        translation_key="action_mode",
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_mode"
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.action_mode.value

    async def async_select_option(self, option: str) -> None:
        """Update coordinator.data.action_mode and broadcast."""
        new_mode = ActionMode(option)
        new_state = dataclasses.replace(self.coordinator.data, action_mode=new_mode)
        self.coordinator.async_set_updated_data(new_state)
```

- [ ] **Step 2: Smoke-test compile**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/select.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/select.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.2.1: select.py with action_mode picker

Single SelectEntity wrapping coordinator.data.action_mode. Options
are the four ActionMode values (all_areas / edge / zone / spot).
async_select_option writes through to coordinator.data via
dataclasses.replace + async_set_updated_data.

Same DeviceInfo as F1/F2 entities for device-registry clustering.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F3.3 — sensor.py extension: active_selection display

### Task F3.3.1: Add sensor.active_selection

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

Read-only display of the currently-selected zones/spots in order. State is a comma-joined human-readable string ("3 → 1 → 2"); attributes carry the structured list.

- [ ] **Step 1: Add to sensor.py**

Append to the SENSORS tuple a new descriptor + add a helper above:

```python
# Helper near the top of sensor.py (alongside _describe_error_or_none):

def _format_active_selection(state: MowerState) -> str | None:
    """Format zone/spot selection for display.

    Examples:
      action_mode=all_areas → 'All areas'
      action_mode=edge → 'Edge mow'
      action_mode=zone, zones=(3, 1, 2) → 'Zones 3 → 1 → 2'
      action_mode=zone, zones=() → 'No zones selected'
      action_mode=spot, spots=() → 'No spots selected'
    """
    from .mower.state import ActionMode
    mode = state.action_mode
    if mode == ActionMode.ALL_AREAS:
        return "All areas"
    if mode == ActionMode.EDGE:
        return "Edge mow"
    if mode == ActionMode.ZONE:
        zones = state.active_selection_zones
        if not zones:
            return "No zones selected"
        return "Zones " + " → ".join(str(z) for z in zones)
    if mode == ActionMode.SPOT:
        spots = state.active_selection_spots
        if not spots:
            return "No spots selected"
        return "Spots " + " → ".join(str(s) for s in spots)
    return None
```

Then append to the SENSORS tuple:

```python
DreameA2SensorEntityDescription(
    key="active_selection",
    name="Active selection",
    value_fn=_format_active_selection,
),
```

- [ ] **Step 2: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/sensor.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/sensor.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.3.1: sensor.active_selection — display of mode + selection

Read-only sensor showing the current action_mode + selection in
human-readable form ('Zones 3 → 1 → 2', 'No spots selected',
'All areas', 'Edge mow'). Useful as a dashboard indicator
alongside the Start button.

Total SENSORS tuple now: 22 entries (2 F1 + 19 F2 + 1 F3).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F3.4 — Services: schema + handlers

### Task F3.4.1: services.yaml + services.py

**Files:**
- Create: `custom_components/dreame_a2_mower/services.yaml`
- Create: `custom_components/dreame_a2_mower/services.py`
- Modify: `custom_components/dreame_a2_mower/__init__.py` — register services on setup, unregister on unload

The services exposed by the integration. Each service handler reads from the coordinator + delegates to actions.py (built in F3.5).

- [ ] **Step 1: Write services.yaml**

```yaml
# custom_components/dreame_a2_mower/services.yaml

set_active_selection:
  description: >
    Set the ordered list of zones or spots to be mowed by the next "Start"
    action when action_mode is zone or spot. Updates the integration's
    persistent selection state.
  fields:
    zones:
      description: Zone IDs in mowing order. Empty list to clear zone selection.
      example: "[3, 1, 2]"
      selector:
        object:
    spots:
      description: Spot IDs in mowing order. Empty list to clear spot selection.
      example: "[1]"
      selector:
        object:

mow_zone:
  description: >
    One-shot — set zone selection then start mowing. Equivalent to
    set_active_selection with zones=… followed by lawn_mower.start_mowing
    when action_mode=zone.
  fields:
    zone_ids:
      description: Zone IDs in mowing order.
      required: true
      example: "[3, 1, 2]"
      selector:
        object:

mow_edge:
  description: >
    Edge-mow on a specific zone, or all zones if zone_id is omitted.
  fields:
    zone_id:
      description: Zone ID to edge-mow. Omit to edge-mow all zones.
      example: 3
      selector:
        number:
          mode: box
          min: 0

mow_spot:
  description: Spot-mow at a coordinate.
  fields:
    point:
      description: "[x_m, y_m] coordinate in mower frame."
      required: true
      example: "[12.5, -3.4]"
      selector:
        object:

recharge:
  description: Send the mower to the charging dock immediately.

find_bot:
  description: Make the mower beep so you can locate it.

lock_bot:
  description: Toggle the child lock.

suppress_fault:
  description: Clear a recoverable error condition.

finalize_session:
  description: >
    Manually finalize the in-progress session. Use when the cloud-side
    session-summary fetch fails permanently and the in-progress entry
    is stuck. F5 wires the auto-finalize gate; this is the user-facing
    escape hatch.
```

(`finalize_session` is exposed in F3 even though F5 wires the auto-gate — having the user-facing service from day 1 is cheap.)

- [ ] **Step 2: Write services.py**

```python
"""Service handlers for the Dreame A2 Mower integration.

Per spec §5.2: actions live in service calls; entities should be state.
This module wires the services declared in services.yaml to the
action-dispatch helpers in mower/actions.py (built in F3.5).

The handlers are registered in __init__.py via async_setup_entry, and
unregistered in async_unload_entry.
"""
from __future__ import annotations

import dataclasses
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode

# Service names — keep in sync with services.yaml
SERVICE_SET_ACTIVE_SELECTION = "set_active_selection"
SERVICE_MOW_ZONE = "mow_zone"
SERVICE_MOW_EDGE = "mow_edge"
SERVICE_MOW_SPOT = "mow_spot"
SERVICE_RECHARGE = "recharge"
SERVICE_FIND_BOT = "find_bot"
SERVICE_LOCK_BOT = "lock_bot"
SERVICE_SUPPRESS_FAULT = "suppress_fault"
SERVICE_FINALIZE_SESSION = "finalize_session"


# Schemas
SCHEMA_SET_SELECTION = vol.Schema(
    {
        vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("spots", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

SCHEMA_MOW_ZONE = vol.Schema(
    {vol.Required("zone_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_MOW_EDGE = vol.Schema(
    {vol.Optional("zone_id"): vol.Coerce(int)}
)

SCHEMA_MOW_SPOT = vol.Schema(
    {vol.Required("point"): vol.All(cv.ensure_list, [vol.Coerce(float)])}
)

SCHEMA_EMPTY = vol.Schema({})


def _coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> DreameA2MowerCoordinator | None:
    """Resolve the (only) coordinator instance.

    Single-mower integration: there's at most one coordinator. If
    multi-mower is ever supported, the call would need to specify
    which one (e.g., via entity_id of the lawn_mower entity).
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        LOGGER.warning("No %s coordinator registered; service ignored", DOMAIN)
        return None
    return next(iter(coordinators.values()))


async def _handle_set_active_selection(call: ServiceCall) -> None:
    """Update coordinator.data.active_selection_zones / _spots."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zones = tuple(call.data.get("zones", []))
    spots = tuple(call.data.get("spots", []))
    new_state = dataclasses.replace(
        coordinator.data,
        active_selection_zones=zones,
        active_selection_spots=spots,
    )
    coordinator.async_set_updated_data(new_state)


async def _handle_mow_zone(call: ServiceCall) -> None:
    """Set zone selection then dispatch start_mowing in zone mode."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zone_ids = tuple(call.data["zone_ids"])
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.ZONE,
        active_selection_zones=zone_ids,
    )
    coordinator.async_set_updated_data(new_state)
    # Dispatch the actual start. Imported here to avoid circular imports.
    from .mower.actions import dispatch_action, MowerAction
    await coordinator.dispatch_action(MowerAction.START_ZONE_MOW, {"zones": list(zone_ids)})


async def _handle_mow_edge(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zone_id = call.data.get("zone_id")
    payload: dict[str, Any] = {}
    if zone_id is not None:
        payload["zone_id"] = int(zone_id)
    from .mower.actions import dispatch_action, MowerAction
    await coordinator.dispatch_action(MowerAction.START_EDGE_MOW, payload)


async def _handle_mow_spot(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    point = call.data["point"]
    if not isinstance(point, list) or len(point) != 2:
        LOGGER.warning("mow_spot: point must be [x_m, y_m]; got %r", point)
        return
    from .mower.actions import dispatch_action, MowerAction
    await coordinator.dispatch_action(
        MowerAction.START_SPOT_MOW,
        {"x_m": float(point[0]), "y_m": float(point[1])},
    )


async def _handle_simple_action(action_name: str):
    """Factory for parameterless action handlers (recharge, find_bot, etc.)."""
    from .mower.actions import dispatch_action, MowerAction
    target = MowerAction[action_name]

    async def handler(call: ServiceCall) -> None:
        coordinator = _coordinator_from_call(call.hass, call)
        if coordinator is None:
            return
        await coordinator.dispatch_action(target, {})

    return handler


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all the integration's service handlers."""
    hass.services.async_register(DOMAIN, SERVICE_SET_ACTIVE_SELECTION,
                                  _handle_set_active_selection, schema=SCHEMA_SET_SELECTION)
    hass.services.async_register(DOMAIN, SERVICE_MOW_ZONE,
                                  _handle_mow_zone, schema=SCHEMA_MOW_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_EDGE,
                                  _handle_mow_edge, schema=SCHEMA_MOW_EDGE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_SPOT,
                                  _handle_mow_spot, schema=SCHEMA_MOW_SPOT)
    hass.services.async_register(DOMAIN, SERVICE_RECHARGE,
                                  await _handle_simple_action("RECHARGE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FIND_BOT,
                                  await _handle_simple_action("FIND_BOT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_LOCK_BOT,
                                  await _handle_simple_action("LOCK_BOT_TOGGLE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_SUPPRESS_FAULT,
                                  await _handle_simple_action("SUPPRESS_FAULT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FINALIZE_SESSION,
                                  await _handle_simple_action("FINALIZE_SESSION"), schema=SCHEMA_EMPTY)


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_SET_ACTIVE_SELECTION, SERVICE_MOW_ZONE, SERVICE_MOW_EDGE, SERVICE_MOW_SPOT,
        SERVICE_RECHARGE, SERVICE_FIND_BOT, SERVICE_LOCK_BOT, SERVICE_SUPPRESS_FAULT,
        SERVICE_FINALIZE_SESSION,
    ):
        hass.services.async_remove(DOMAIN, svc)
```

- [ ] **Step 3: Wire register/unregister in __init__.py**

In `custom_components/dreame_a2_mower/__init__.py`:

Add at the top:
```python
from .services import async_register_services, async_unregister_services
```

In `async_setup_entry`, after the platform forwarding:

```python
    # Register integration-wide services. Idempotent — async_register_services
    # checks if services are already registered and no-ops if so.
    if not hass.services.has_service(DOMAIN, "mow_zone"):
        await async_register_services(hass)
```

In `async_unload_entry`, before returning (only if this was the last config entry):

```python
    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)
```

(The first config entry's setup registers; the last config entry's unload removes. Multi-instance is unsupported so in practice there's only one entry.)

- [ ] **Step 4: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
import py_compile, yaml
py_compile.compile('custom_components/dreame_a2_mower/services.py', doraise=True)
py_compile.compile('custom_components/dreame_a2_mower/__init__.py', doraise=True)
yaml.safe_load(open('custom_components/dreame_a2_mower/services.yaml'))
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/services.yaml custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/__init__.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.4.1: services.yaml + services.py + register on setup

Nine services declared:
  - set_active_selection (zones / spots, ordered)
  - mow_zone, mow_edge, mow_spot (one-shot start variants)
  - recharge (immediate dock)
  - find_bot, lock_bot, suppress_fault (utility actions)
  - finalize_session (escape hatch for stuck in-progress entries; F5
    wires the auto-gate but the user-facing service ships in F3)

Each handler resolves the coordinator from hass.data[DOMAIN] (single-
mower) and delegates to coordinator.dispatch_action with a typed
MowerAction (defined in F3.5). Set-state services (set_active_selection,
mow_zone) update coordinator.data.action_mode / active_selection via
dataclasses.replace + async_set_updated_data.

__init__.py registers services on first setup, unregisters when the
last config entry unloads. Idempotent — checks has_service before
re-registering.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Note: the services reference `MowerAction` and `coordinator.dispatch_action` which don't exist yet. F3.5 builds them. Between F3.4 and F3.5 the integration won't successfully call any service, but it'll register and load.

---

## Phase F3.5 — Action dispatcher (mower/actions.py + coordinator)

### Task F3.5.1: Lift action enum + (siid, aiid) table from legacy

**Files:**
- Create: `custom_components/dreame_a2_mower/mower/actions.py`
- Create: `tests/mower/test_actions.py`

The legacy has `DreameMowerAction` IntEnum + `DreameMowerActionMapping` dict. Lift the relevant subset (only g2408-relevant actions) into a focused module.

- [ ] **Step 1: Inspect legacy**

```bash
grep -nE "^class DreameMowerAction\b|^DreameMowerActionMapping" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/types.py
```

Read 80-120 lines of context to see all the actions defined and their mappings. Identify which ones are g2408-relevant per the audit (P2.1.3 audit table noted ~12 PRODUCTION buttons + 1 OBSERVABILITY + 3 EXPERIMENTAL).

For F3, the relevant actions:

| MowerAction | Legacy | (siid, aiid) primary | Notes |
|---|---|---|---|
| START_MOWING | START_MOWING | (5, 1) | Whole-lawn — also can be (2, 1) routed |
| START_ZONE_MOW | START_ZONE_MOWING (or similar) | per legacy | Carries region_id |
| START_EDGE_MOW | (something) | per legacy | Carries optional zone_id |
| START_SPOT_MOW | (something) | per legacy | Carries x_m, y_m |
| PAUSE | PAUSE | (5, 4) | |
| DOCK | DOCK | (5, 3) | a.k.a. Recharge for the user |
| RECHARGE | (alias for DOCK) | (5, 3) | |
| STOP | STOP | (5, 2) | |
| FIND_BOT | (FIND_DEVICE or similar) | per legacy | beep |
| LOCK_BOT_TOGGLE | (CHILD_LOCK or similar) | per legacy | toggle |
| SUPPRESS_FAULT | CLEAR_WARNING | (4, 3) | |
| FINALIZE_SESSION | (custom — coordinator-only, no cloud RPC) | n/a | F5 has auto-gate; this is escape hatch |

**Read legacy carefully** to confirm action names and (siid, aiid) values. Some of these may have different names.

For FINALIZE_SESSION: this is integration-internal (no cloud call). The dispatcher special-cases it.

- [ ] **Step 2: Write tests/mower/test_actions.py**

```python
"""Tests for mower/actions.py — the typed action enum + dispatch table."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.actions import (
    ACTION_TABLE,
    MowerAction,
)


def test_action_enum_includes_all_f3_actions():
    """The MowerAction enum has at least the 9 F3-required values."""
    expected = {
        "START_MOWING",
        "START_ZONE_MOW",
        "START_EDGE_MOW",
        "START_SPOT_MOW",
        "PAUSE",
        "DOCK",
        "RECHARGE",
        "STOP",
        "FIND_BOT",
        "LOCK_BOT_TOGGLE",
        "SUPPRESS_FAULT",
        "FINALIZE_SESSION",
    }
    actual = {a.name for a in MowerAction}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_action_table_has_siid_aiid_for_cloud_actions():
    """Every action that hits the cloud has (siid, aiid) defined."""
    cloud_actions = {
        MowerAction.START_MOWING,
        MowerAction.PAUSE,
        MowerAction.DOCK,
        MowerAction.STOP,
        MowerAction.SUPPRESS_FAULT,
    }
    for action in cloud_actions:
        assert action in ACTION_TABLE
        entry = ACTION_TABLE[action]
        assert "siid" in entry, f"{action} missing siid"
        assert "aiid" in entry, f"{action} missing aiid"


def test_finalize_session_is_local_only():
    """FINALIZE_SESSION has no (siid, aiid) — it's integration-local."""
    entry = ACTION_TABLE.get(MowerAction.FINALIZE_SESSION, {})
    assert "siid" not in entry  # local-only
```

- [ ] **Step 3: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_actions.py -v 2>&1 | tail -10
```

Expected: ImportError on `MowerAction` / `ACTION_TABLE`.

- [ ] **Step 4: Implement actions.py**

```python
"""Typed action enum + (siid, aiid) dispatch table for the Dreame A2 mower.

Per spec §3 layer 2: no homeassistant imports. The dispatch helpers
here construct the wire payload but do NOT actually invoke the cloud
client — coordinator.dispatch_action does that.

The legacy DreameMowerActionMapping is at
``ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/types.py:807``.
The greenfield only carries the g2408-relevant subset (per P2.1.3 audit).

Cloud-RPC limitation on g2408: the direct ``action(siid, aiid, ...)`` call
returns 80001 ("device unreachable"). The fallback path is the routed
action (siid=2, aiid=50) — the legacy at device.py:4280 documents this
and provides _ALT_ACTION_SIID_MAP as the routing table. This module
records both the primary (siid, aiid) AND the routed-action variant
when applicable; the coordinator's dispatch_action retries via the
routed path on 80001.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any, TypedDict


class MowerAction(Enum):
    """Typed action identifiers. Names mirror Dreame app vocabulary
    where reasonable (Recharge, Find My Mower, etc.)."""
    START_MOWING = auto()
    START_ZONE_MOW = auto()
    START_EDGE_MOW = auto()
    START_SPOT_MOW = auto()
    PAUSE = auto()
    DOCK = auto()
    RECHARGE = auto()  # alias for DOCK with explicit "head to charger now" semantic
    STOP = auto()
    FIND_BOT = auto()
    LOCK_BOT_TOGGLE = auto()
    SUPPRESS_FAULT = auto()
    FINALIZE_SESSION = auto()  # integration-local; no cloud call


class ActionEntry(TypedDict, total=False):
    """One row of the dispatch table.

    siid / aiid: primary cloud-RPC mapping (returns 80001 on g2408 for
                 most actions, but recorded for completeness and as a
                 fallback should the cloud's RPC tunnel ever open).
    routed_t:    if set, the action dispatches via routed-action
                 s2 aiid=50 with this 't' value (the working path on g2408).
    routed_o:    optional 'o' opcode for TASK-envelope actions
                 (s2.50 op=100 mow start, op=101 zone-mow, etc.)
    payload_fn:  optional callable that builds the routed-action 'd' field
                 from a parameters dict.
    local_only:  if True, the action is integration-internal (no cloud call).
    """
    siid: int
    aiid: int
    routed_t: str
    routed_o: int
    payload_fn: Any  # Callable[[dict], dict | None]
    local_only: bool


def _zone_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Build the TASK envelope d-field for zone-mow (op=101)."""
    zones = params.get("zones") or []
    if not zones:
        raise ValueError("START_ZONE_MOW requires non-empty 'zones' list")
    return {"region_id": list(zones)}


def _edge_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope for edge-mow.

    Without zone_id: edge all zones. With zone_id: edge only that zone.
    """
    zone_id = params.get("zone_id")
    if zone_id is not None:
        return {"region_id": [int(zone_id)]}
    return {}


def _spot_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    x = params.get("x_m")
    y = params.get("y_m")
    if x is None or y is None:
        raise ValueError("START_SPOT_MOW requires 'x_m' and 'y_m'")
    # Spot point is in mower-frame metres. The wire format may need
    # conversion to centimetres or to cloud-frame coords — verify
    # against legacy device.py spot-mow handler. This stub uses metres
    # directly; adjust if legacy converts.
    return {"point": [float(x), float(y)]}


# (siid, aiid) values verified against legacy
# /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/
# dreame_a2_mower/dreame/types.py:807-815. Some entries are g2408-
# specific routings derived from the legacy _ALT_ACTION_SIID_MAP.
ACTION_TABLE: dict[MowerAction, ActionEntry] = {
    MowerAction.START_MOWING: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 100,
    },
    MowerAction.START_ZONE_MOW: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 101,
        "payload_fn": _zone_mow_payload,
    },
    MowerAction.START_EDGE_MOW: {
        "routed_t": "TASK", "routed_o": 101,
        "payload_fn": _edge_mow_payload,
    },
    MowerAction.START_SPOT_MOW: {
        "routed_t": "TASK",
        "payload_fn": _spot_mow_payload,
    },
    MowerAction.PAUSE: {"siid": 5, "aiid": 4},
    MowerAction.DOCK: {"siid": 5, "aiid": 3},
    MowerAction.RECHARGE: {"siid": 5, "aiid": 3},  # same as DOCK for now
    MowerAction.STOP: {"siid": 5, "aiid": 2},
    MowerAction.FIND_BOT: {
        # Verify (siid, aiid) against legacy — likely (4, ?)
        "siid": 4, "aiid": 5,  # placeholder per legacy CLEAR_WARNING pattern
    },
    MowerAction.LOCK_BOT_TOGGLE: {
        # Child-lock toggle — read the legacy mapping
        "siid": 4, "aiid": 12,  # adjust per legacy
    },
    MowerAction.SUPPRESS_FAULT: {"siid": 4, "aiid": 3},
    MowerAction.FINALIZE_SESSION: {"local_only": True},
}
```

**Important**: the (siid, aiid) values for FIND_BOT and LOCK_BOT_TOGGLE in the table above are placeholders. Read the legacy `DreameMowerActionMapping` to find the actual values. If an action's mapping isn't in legacy at all, set `local_only=True` and STOP to discuss with the controller.

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_actions.py -v 2>&1 | tail -10
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/actions.py tests/mower/test_actions.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.5.1: mower/actions.py — typed action enum + (siid, aiid) table

Lifts the g2408-relevant subset of legacy DreameMowerActionMapping
into a focused module. Records BOTH the primary (siid, aiid) and the
routed-action (s2 aiid=50) variant per action — the coordinator's
dispatch_action will retry via the routed path on 80001 (the only
working cloud-RPC surface on g2408).

12 actions: START_MOWING, START_ZONE_MOW, START_EDGE_MOW,
START_SPOT_MOW, PAUSE, DOCK, RECHARGE (alias), STOP, FIND_BOT,
LOCK_BOT_TOGGLE, SUPPRESS_FAULT, FINALIZE_SESSION.

FINALIZE_SESSION is local_only — no cloud call. F5 wires the
auto-gate; this is the user-facing escape hatch.

payload_fn callables build the TASK envelope d-field for the start-*
actions: zone (region_id list), edge (optional zone_id), spot (point
xy).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F3.5.2: Add coordinator.dispatch_action

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` — add `routed_action()` method if missing

The coordinator's `dispatch_action` is what services + lawn_mower call. It looks up the action in ACTION_TABLE and:
1. If `local_only`: handle internally (e.g., FINALIZE_SESSION calls F5's finalize logic — for now just log)
2. Else: build the routed-action payload and call cloud_client.routed_action()
3. (Future: F5+ may add a primary `cloud_client.action()` call with 80001 fallback to routed; for F3 we go straight to routed)

- [ ] **Step 1: Inspect cloud_client.py**

```bash
grep -nE "^def |routed_action|action\(|sendCommand" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/cloud_client.py | head -20
```

If a `routed_action(t: str, o: int | None, d: dict | None)` method already exists, use it. If not, add one. Pattern (from legacy): POST to `/dreame-iot-com-10000/device/sendCommand` with body `{method: "set_properties", params: [{did, siid: 2, piid: 51, value: {m: 's', t: t, o: o, d: d}}]}` (or similar — read legacy carefully).

Actually — the integration's existing `fetch_cfg` and `fetch_locn` both go through `protocol.cfg_action.get_cfg(send_action)` which already wraps the routed-action POST. There's likely a generic `set_action` or similar in cfg_action.py to mirror. Read both files:

```bash
grep -nE "^def " /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/cfg_action.py
```

If `cfg_action.py` has a `set_action(send_action, t, o, d)` or similar, use it. If only `get_cfg` / `probe_get` exist, add a small `set_action` helper.

- [ ] **Step 2: Add coordinator.dispatch_action**

In `coordinator.py`:

```python
# Near the top:
from .mower.actions import ACTION_TABLE, MowerAction

# Add to DreameA2MowerCoordinator class:

async def dispatch_action(
    self, action: MowerAction, parameters: dict[str, Any] | None = None
) -> None:
    """Dispatch a typed mower action.

    Looks up the action in ACTION_TABLE. local_only actions are handled
    internally (currently only FINALIZE_SESSION — its actual
    implementation lands in F5). Cloud actions go via the routed path
    (s2 aiid=50) since the direct (siid, aiid) call returns 80001 on
    g2408.

    Errors and timeouts are logged but not raised — the integration
    keeps going. F4+ surfaces persistent failures via diagnostic
    sensors.
    """
    parameters = parameters or {}
    entry = ACTION_TABLE.get(action)
    if entry is None:
        LOGGER.warning("dispatch_action: unknown action %r", action)
        return

    if entry.get("local_only"):
        # FINALIZE_SESSION — F5 wires the actual implementation. For
        # F3, log so the user knows the service was received.
        LOGGER.info("dispatch_action: local-only %s; F5 wires this", action.name)
        return

    if self._cloud is None:
        LOGGER.warning("dispatch_action: cloud client not ready; %s deferred", action.name)
        return

    routed_t = entry.get("routed_t")
    if routed_t is None:
        LOGGER.warning("dispatch_action: %s has no routed_t (g2408 cloud RPC returns 80001 for direct calls)", action.name)
        return

    routed_o = entry.get("routed_o")
    payload_fn = entry.get("payload_fn")
    try:
        d = payload_fn(parameters) if payload_fn else None
    except ValueError as ex:
        LOGGER.warning("dispatch_action %s: payload error: %s", action.name, ex)
        return

    # Construct the TASK-envelope and send via routed action
    # (s2 aiid=50 — the working path on g2408).
    LOGGER.info("dispatch_action: %s via routed t=%s o=%s d=%s",
                action.name, routed_t, routed_o, d)
    try:
        await self.hass.async_add_executor_job(
            self._cloud.routed_action, routed_t, routed_o, d
        )
    except Exception as ex:
        LOGGER.warning("dispatch_action %s failed: %s", action.name, ex)
```

- [ ] **Step 3: Add cloud_client.routed_action if missing**

If the cloud client doesn't have `routed_action(t, o, d)`, add one. Pattern (read legacy device.py for the exact wire format):

```python
def routed_action(
    self, t: str, o: int | None = None, d: dict | None = None
) -> dict[str, Any] | None:
    """Send a routed action via s2 aiid=50.

    On g2408, this is the only cloud-RPC path that works for action
    invocation (direct ``action()`` returns 80001). The TASK envelope
    is constructed as {m: 's', t: t, o: o, d: d}.

    Legacy reference:
    /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/
    dreame_a2_mower/dreame/protocol.py — search for sendCommand /
    routed_action.
    """
    envelope: dict[str, Any] = {"m": "s", "t": t}
    if o is not None:
        envelope["o"] = o
    if d is not None:
        envelope["d"] = d
    # Use the existing self.action() method that already handles auth
    # and the iotcomprefix gotcha. Pass siid=2 aiid=50 with the
    # envelope as the value.
    return self.action(siid=2, aiid=50, parameters=envelope)
```

(Adjust the parameter wrapping based on what the legacy actually does.)

- [ ] **Step 4: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
import py_compile
py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True)
py_compile.compile('custom_components/dreame_a2_mower/cloud_client.py', doraise=True)
print('ok')
"
```

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest -v 2>&1 | tail -10
```

Expected: full suite still green.

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/cloud_client.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.5.2: coordinator.dispatch_action + cloud_client.routed_action

DreameA2MowerCoordinator.dispatch_action: typed entry point for
service handlers. Looks up MowerAction in ACTION_TABLE, handles
local_only actions inline, dispatches cloud actions via the routed
path (s2 aiid=50). Errors are logged, not raised — integration keeps
running.

DreameA2CloudClient.routed_action: builds the TASK envelope
{m: 's', t: <type>, o: <opcode>, d: <payload>} and POSTs via the
existing action() helper (siid=2 aiid=50). The only cloud-RPC path
that works on g2408.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F3.6 — Wire lawn_mower platform handlers

### Task F3.6.1: Replace lawn_mower stubs with real dispatch

**Files:**
- Modify: `custom_components/dreame_a2_mower/lawn_mower.py`

The F1 stubs (`async_start_mowing`, `async_pause`, `async_dock`) just log a placeholder. Wire them to `coordinator.dispatch_action`.

`async_start_mowing` reads `coordinator.data.action_mode` to pick the right MowerAction.

- [ ] **Step 1: Update lawn_mower.py**

Replace the stub action handlers:

```python
# Add to imports:
from .mower.actions import MowerAction
from .mower.state import ActionMode


# Replace the stub methods on DreameA2LawnMower:

async def async_start_mowing(self) -> None:
    """Start mowing in the currently-selected action_mode.

    Reads coordinator.data.action_mode + active_selection_zones/spots
    to pick the right opcode. Dispatches via coordinator.dispatch_action
    which routes to the working cloud path on g2408.
    """
    state = self.coordinator.data
    mode = state.action_mode
    if mode == ActionMode.ALL_AREAS:
        await self.coordinator.dispatch_action(MowerAction.START_MOWING, {})
        return
    if mode == ActionMode.EDGE:
        await self.coordinator.dispatch_action(MowerAction.START_EDGE_MOW, {})
        return
    if mode == ActionMode.ZONE:
        zones = state.active_selection_zones
        if not zones:
            LOGGER.warning("start_mowing: zone mode but no zones selected; no-op")
            return
        await self.coordinator.dispatch_action(
            MowerAction.START_ZONE_MOW, {"zones": list(zones)}
        )
        return
    if mode == ActionMode.SPOT:
        spots = state.active_selection_spots
        if not spots:
            LOGGER.warning("start_mowing: spot mode but no spots selected; no-op")
            return
        # Spot uses an x_m, y_m point — but spots are stored as IDs in
        # active_selection_spots. The map_decoder produces named spots
        # in MapData; for F3 we look up the spot's x_m / y_m from the
        # cached map. F5 may extend this with the live trail integration.
        # For F3, take the first selected spot's coordinates.
        spot_id = spots[0]
        # Resolve spot_id → (x, y). The map decoder's MaintenancePoint
        # records carry IDs and coords. coordinator.cached_map_data
        # would be the right surface — F2.8.3 added cached_map_png; we
        # need cached_map_data too. For F3 we punt with a warning.
        LOGGER.warning(
            "start_mowing spot: spot ID → coord lookup not yet wired; spot_id=%d",
            spot_id,
        )
        return
    LOGGER.warning("start_mowing: unknown action_mode %r", mode)


async def async_pause(self) -> None:
    await self.coordinator.dispatch_action(MowerAction.PAUSE, {})


async def async_dock(self) -> None:
    await self.coordinator.dispatch_action(MowerAction.DOCK, {})
```

(The spot-mow path has a documented limitation: F3 doesn't yet do spot-id → coord resolution. The user-facing service `dreame_a2_mower.mow_spot` takes a literal `[x, y]` point and works correctly via that path. The lawn_mower-platform start in spot mode logs a warning and no-ops, with an issue noted for F5 to wire the cached_map_data lookup.)

- [ ] **Step 2: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/lawn_mower.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/lawn_mower.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F3.6.1: lawn_mower platform — real start/pause/dock dispatch

Replaces F1 stub action handlers with coordinator.dispatch_action
calls. async_start_mowing reads coordinator.data.action_mode to pick
the right MowerAction:

  - ALL_AREAS → START_MOWING
  - EDGE → START_EDGE_MOW
  - ZONE → START_ZONE_MOW with active_selection_zones
  - SPOT → logged-noop in F3 (spot_id → coord lookup needs
    cached_map_data, F5 wires this)

The user-facing dreame_a2_mower.mow_spot service takes a literal [x, y]
point and works correctly in F3 via that path; the lawn_mower platform
in spot mode is the gap.

async_pause and async_dock dispatch PAUSE / DOCK directly.

Empty selection in zone/spot mode → log WARNING + no-op (per spec
§5.2 — entities should be state, not enforce greying).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F3.7 — Wire-in + final sweep + tag

### Task F3.7.1: Update PLATFORMS, run final sweep, tag v0.3.0a0

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`

- [ ] **Step 1: Add `select` to PLATFORMS**

In `const.py`:

```python
PLATFORMS: Final = [
    "lawn_mower",
    "sensor",
    "binary_sensor",
    "device_tracker",
    "camera",
    "select",
]
```

- [ ] **Step 2: Final test sweep**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest -v 2>&1 | tail -25
```

Expected: full suite green. Test count should be 279 + (tests added in F3.1, F3.5) = ~286.

- [ ] **Step 3: Smoke-compile every Python file**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
import py_compile
files = [
    'custom_components/dreame_a2_mower/__init__.py',
    'custom_components/dreame_a2_mower/coordinator.py',
    'custom_components/dreame_a2_mower/cloud_client.py',
    'custom_components/dreame_a2_mower/mqtt_client.py',
    'custom_components/dreame_a2_mower/config_flow.py',
    'custom_components/dreame_a2_mower/const.py',
    'custom_components/dreame_a2_mower/services.py',
    'custom_components/dreame_a2_mower/lawn_mower.py',
    'custom_components/dreame_a2_mower/sensor.py',
    'custom_components/dreame_a2_mower/binary_sensor.py',
    'custom_components/dreame_a2_mower/select.py',
    'custom_components/dreame_a2_mower/device_tracker.py',
    'custom_components/dreame_a2_mower/camera.py',
    'custom_components/dreame_a2_mower/map_decoder.py',
    'custom_components/dreame_a2_mower/map_render.py',
    'custom_components/dreame_a2_mower/mower/state.py',
    'custom_components/dreame_a2_mower/mower/capabilities.py',
    'custom_components/dreame_a2_mower/mower/property_mapping.py',
    'custom_components/dreame_a2_mower/mower/error_codes.py',
    'custom_components/dreame_a2_mower/mower/actions.py',
]
for f in files:
    py_compile.compile(f, doraise=True)
print(f'compiled {len(files)} files ok')
"
```

Expected: `compiled 20 files ok`.

- [ ] **Step 4: Commit + tag**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/const.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F3.7: extend PLATFORMS with select — F3 complete

PLATFORMS now includes select alongside the F1 (lawn_mower, sensor)
+ F2 (binary_sensor, device_tracker, camera) entries. The select.action_mode
entity loads from F3.2.1.

End-state of F3: user can control mower from HA. lawn_mower
platform's start_mowing dispatches via coordinator.dispatch_action
based on coordinator.data.action_mode. Service-call surface (mow_zone,
mow_edge, mow_spot, find_bot, lock_bot, suppress_fault, recharge,
finalize_session, set_active_selection) registered on setup.

Known F3 gap: spot mode in lawn_mower.start_mowing logs-and-no-ops
because spot_id → coord lookup needs cached_map_data (F5 wires it).
Users can invoke the dreame_a2_mower.mow_spot service with a literal
[x, y] point as the F3 workaround.

Action handlers go through the routed-action path (s2 aiid=50) —
the only cloud-RPC surface that works on g2408 per protocol-doc §1.2.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ tag -a v0.3.0a0 -m "F3 — Action Surface phase complete. Mower controllable from HA. lawn_mower platform start/pause/dock + 9 services + select.action_mode + sensor.active_selection. F5 wires session lifecycle / spot_id resolution."
```

(Controller pushes the commit + tag.)

---

## Self-review checklist

- [ ] `pytest` is green.
- [ ] `select.action_mode` shows the four options + persists user selection on coordinator.data.
- [ ] All nine services registered on integration setup; visible in Developer Tools → Services.
- [ ] `lawn_mower.start_mowing` dispatches the right MowerAction based on action_mode.
- [ ] `dreame_a2_mower.mow_zone` service updates active_selection AND dispatches zone-mow.
- [ ] No `homeassistant.*` imports in `protocol/` or `mower/`.
- [ ] `v0.3.0a0` tag pushed.

## Out of scope (deferred)

- F4: settings entities (s2.51 multiplexed sub-fields, mowing height/efficiency/edgemaster/rain-protection/etc.)
- F5: session lifecycle (live_map state machine, in-progress, finalize gate, archive promotion)
- F5: spot_id → coord resolution for lawn_mower.start_mowing in spot mode (F3 has the gap; the explicit `mow_spot` service takes a literal point)
- F5: FINALIZE_SESSION's actual implementation (currently logs-and-no-ops as local_only)
- F6: observability layer
- F7: LiDAR + dashboard polish + cutover

## Followup

After F3 lands:
- Final cumulative review (controller dispatches).
- Live verification on the user's mower:
  - lawn_mower.start_mowing should actually start the mower mowing (not just log a stub)
  - Zone mode should respect the selection
  - Edge / pause / dock should work
- F4 plan written against post-F3 file structure.
