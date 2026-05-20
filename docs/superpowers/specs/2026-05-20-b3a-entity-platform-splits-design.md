# B3a — Entity-Platform File Splits (Design)

**Date:** 2026-05-20
**Status:** spec
**Parent (Block 3):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` § 5 ([B3] items).

## What this is

First Block-3 sub-cycle. Splits the three largest entity-platform files —
`select.py` (1990 LOC, 16 classes), `sensor.py` (1499 LOC, 32 classes),
`switch.py` (1308 LOC, 12 classes) — into domain-grouped sibling modules,
each with a shared base module, keeping the platform file as a thin entry.
Behavior-preserving (entity classes moved verbatim; identical `unique_id` /
`_attr_name` / `device_info` / logic).

**Decisions (user, 2026-05-20):**
- **Bundle all three splits in one cycle** (one spec, one plan with a task per
  file) — the splits are mechanically identical.
- **A shared `_<platform>_base.py` per platform** holds cross-group bases +
  `EntityDescription` dataclasses (avoids the circular import that keeping them
  in the platform file would create).
- **Entity-orphan registry audit deferred** to a later live-HA cleanup pass
  (it's a runtime registry cleanup, not a code refactor) — NOT in B3a.

## Per-platform structure (same shape for all three)

```
_<platform>_base.py    # shared abstract bases + *EntityDescription dataclasses
                       #   + cross-group module-level constants/helpers.
                       #   Imports nothing from the group modules (acyclic).
<platform>_<group>.py  # concrete entity classes, moved VERBATIM, importing
                       #   bases from `._<platform>_base`. (2-3 per platform.)
<platform>.py          # UNCHANGED platform entry: async_setup_entry + the
                       #   EntityDescription tables it iterates; imports the
                       #   concrete entity classes from the group modules.
```

- **HA platform discovery is preserved:** HA imports
  `custom_components.dreame_a2_mower.<platform>` (the platform file). The
  group/base sibling modules are NOT named after a platform domain, so HA never
  mistakes them for platforms — they're plain helper modules the platform file
  imports.
- **Acyclic imports:** base module ← group modules ← platform file. The base
  module never imports a group module, so there's no cycle. (Same precedent as
  `coordinator/_property_apply.py` and `cloud_client/_helpers.py`.)
- **Relative imports** stay `from .const import ...` etc. (these are siblings in
  the same package, not a sub-package — no re-anchoring needed, unlike the
  cloud_client package split).

## Grouping rule

Each concrete entity class goes to the group module matching its scope. The
load-bearing, mechanical rule: **a class that builds its device via
`map_device_info(...)` (a per-map sub-device) → the per-map group module; a
class that uses `mower_device_info()` (the parent device) → the device/global
module.** Session-scoped per-map sensors are their own group (sensor only).
Shared abstract bases and `*EntityDescription` dataclasses → `_<platform>_base.py`.
The plan finalizes each class's assignment by grepping its `device_info` usage.

### select.py → `select_map_settings.py` + `select_global.py` (+ `_select_base.py`)
- **_select_base.py:** `DreameA2SettingsSelectDescription`, `_DreameA2DynamicTargetSelect`.
- **select_map_settings.py** (per-map): `DreameA2ZoneSelect`, `DreameA2SpotSelect`,
  `DreameA2EdgeSelect`, `DreameA2PerMapMowingDirectionSelect`,
  `DreameA2PerMapMowingDirectionModeSelect`, `DreameA2MapMowingEfficiencySelect`,
  `DreameA2PerMapEdgeMowingWalkModeSelect`.
- **select_global.py** (device-level): `DreameA2ActionModeSelect`,
  `DreameA2SettingSelect`, `DreameA2WorkLogSelect`, `DreameA2LidarArchiveSelect`,
  `DreameA2ActiveMapSelect`, `DreameA2WifiArchiveSelect`.
- **To finalize by device_info in the plan:** `DreameA2MowingModeSelect`,
  `DreameA2SettingSelect` (confirm map vs global).

### sensor.py → `sensor_device.py` + `sensor_map.py` + `sensor_session.py` (+ `_sensor_base.py`)
- **_sensor_base.py:** `DreameA2SensorEntityDescription`,
  `DreameA2DiagnosticSensorEntityDescription`, `_SnapshotEnumSensorBase`,
  `_DreameA2PerMapSensorBase`, `_DreameA2PerMapPreShadowBase`,
  `_DreameA2PerMapSessionSensorBase`.
- **sensor_device.py** (device-level): `DreameA2CurrentActivitySensor`,
  `DreameA2LocationSensor`, `DreameA2PositioningHealthSensor`,
  `DreameA2MqttConnectivitySensor`, `DreameA2PickedSessionSensor`,
  `DreameA2Sensor`, `DreameA2DiagnosticSensor`, `DreameA2OtaStatusSensor`,
  `DreameA2ScheduleCountSensor`, `DreameA2WifiRefreshStatusSensor`,
  `DreameA2WifiHeatmapAgeSensor`, `DreameA2LastNotificationSensor`,
  `DreameA2ApiEndpointSensor`, `DreameA2IntegrationVersionSensor`.
- **sensor_map.py** (per-map metadata): `DreameA2MapNameSensor`,
  `DreameA2MapAreaSensor`, `DreameA2MapSegmentCountSensor`,
  `DreameA2MaintenancePointsSensor`, `DreameA2ExclusionZonesSensor`,
  `DreameA2IgnoreObstacleZonesSensor`, `DreameA2SpotsCountSensor`,
  `DreameA2MapPreMowingHeightSensor`, `DreameA2MapPreEdgemasterSensor`.
- **sensor_session.py** (per-map session totals): `DreameA2MapSessionAreaTotalSensor`,
  `DreameA2MapSessionTimeTotalSensor`, `DreameA2MapSessionCountSensor`.

### switch.py → `switch_map.py` + `switch_global.py` (+ `_switch_base.py`)
- **_switch_base.py:** `DreameA2SwitchEntityDescription`, `DreameA2Switch`,
  `_AiRecognitionBitSwitch`.
- **switch_map.py** (per-map): `DreameA2MapEdgemasterSwitch`.
- **switch_global.py** (device-level): `DreameA2EdgeMowingAutoSwitch`,
  `DreameA2EdgeMowingSafeSwitch`, `DreameA2EdgeMowingObstacleAvoidanceSwitch`,
  `DreameA2ObstacleAvoidanceEnabledSwitch`, `DreameA2AiHumanDetectionSwitch`,
  `DreameA2AiRecognitionHumansSwitch`, `DreameA2AiRecognitionAnimalsSwitch`,
  `DreameA2AiRecognitionObjectsSwitch`.
- (`DreameA2Switch` is the shared concrete base used as the generic switch +
  superclass — placed in `_switch_base.py`; if `async_setup_entry` instantiates
  `DreameA2Switch` directly from a description table, it imports it from base.)

## Behavior preservation

- Entity class bodies move VERBATIM — no change to `unique_id`, `_attr_name`,
  `device_info`, value/availability logic, or descriptions.
- `async_setup_entry` stays in the platform file and instantiates the exact same
  entity set in the same order. Description tables stay with it (importing the
  description dataclass from `_<platform>_base`).
- No entity is added / renamed / removed → the CLAUDE.md fact-discipline rule
  does NOT fire. The CI `inventory-touch-gate` is a PR-only job; we commit to
  `main`, so it does not block (noted for awareness if a PR is ever opened).

## Testing

Per file: the existing platform/entity tests are the safety net —
`tests/integration/test_per_map_entity_names.py`,
`tests/integration/test_devices_helpers.py`, and the per-platform entity tests
(select/sensor/switch entity tests). Run the relevant tests after each file's
split, then the full suite (`python -m pytest tests -q`, baseline **1591 passed
/ 4 skipped**) green at every commit. Add a small import/availability guard test
only if a split exposes a gap. Confirm `async_setup_entry` still produces the
same entity set (the per-map-naming tests pin entity_ids).

## Out of scope (deferred)
- **Entity-orphan registry audit** ([B3]) → later live-HA cleanup pass.
- Block 4 (rendering/dashboard/docs, README catch-up) follows Block 3.

## Push discipline
Behavior-preserving, suite green. Commit on `main` with `audit-b3a:` prefix;
ship (push + `release.sh`) at the user's discretion after the cycle. NOTE: the
next release crosses the `a9→a10` digit boundary, so `release.sh` will
auto-bump the patch (`1.0.17a9` → `1.0.18a1`).
