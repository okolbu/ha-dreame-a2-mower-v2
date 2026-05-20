# B3a Entity-Platform File Splits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `switch.py`, `select.py`, `sensor.py` into domain-grouped sibling modules + a shared `_<platform>_base.py` each, keeping the platform file as the thin `async_setup_entry` entry — behavior-preserving.

**Architecture:** For each platform file: a `_<platform>_base.py` holds shared abstract bases + `EntityDescription` dataclasses + cross-group helpers; `<platform>_<group>.py` modules hold the concrete entity classes plus the description tables and helper functions that serve only that group; the platform file keeps `async_setup_entry` (+ module docstring) and imports classes/tables from the group modules. Imports are acyclic: `_base` ← group modules ← platform file.

**Tech Stack:** Python 3, Home Assistant custom integration, pytest. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-20-b3a-entity-platform-splits-design.md`

**Context:** On branch `main` (HEAD `a2b1671`). Commit each task on `main` with `audit-b3a:` prefix, authored as the user, no co-author trailer. Do NOT push (user ships after). Full suite (`python -m pytest tests -q`) baseline: **1591 passed, 4 skipped**. Tasks ordered smallest-first (switch is the template).

---

## Split Procedure (Conventions — applied in T1-T3)

For a platform `P` (one of switch/select/sensor) with group modules `P_<group>`:

**1. Create `_P_base.py`** — move into it, VERBATIM:
- the `*EntityDescription` dataclass(es) for `P`;
- every abstract/shared entity base class that is subclassed by entities which will land in DIFFERENT group modules (determine by grep: `grep -n "class .*(<BaseName>" P.py`);
- any module-level constant/helper used by MORE THAN ONE group.
Start the file with `from __future__ import annotations` + exactly the imports the moved code references (copy from `P.py`'s import block; grep each name to confirm it's used). **`_P_base.py` must NOT import from any `P_<group>` module or from `P.py`** (keeps imports acyclic).

**2. Create each `P_<group>.py`** — move into it, VERBATIM: that group's concrete entity classes + the description TABLE(s) that instantiate them + the module-level helper functions/constants used ONLY by that group. Add `from __future__ import annotations`, `from ._P_base import <bases/descriptions it uses>`, and the other imports the moved code references (grep-verify).

**3. Edit `P.py`** — delete the moved classes/tables/helpers; KEEP `async_setup_entry` + the module docstring. Add imports of the entity classes + tables that `async_setup_entry` references, from the `P_<group>` modules (and any `*EntityDescription` it references directly, from `._P_base`). Confirm every name `async_setup_entry` uses resolves.

**4. Verify imports per new module:** for each module, grep every name it references against its imports; a missing import is a latent `NameError`. The platform's entity tests + the full suite are the gate, but DO the grep too (don't rely on tests alone — unexercised branches can hide a missing import). Do NOT prune `P.py`'s imports beyond what the move makes dead; if pruning, grep-verify each (the "tests pass" heuristic is not sufficient — verified the hard way in B1d/B2a).

**5. Placement rules (resolve by grep, not guessing):**
- A class subclassed by entities in >1 group → `_P_base.py`; subclassed in only one group → that group module.
- A description TABLE → the group module whose entities it creates.
- A helper/constant → the group that uses it; used by >1 group → `_P_base.py`.
- `async_setup_entry` + module docstring → stay in `P.py`.

**Behavior preservation:** move bodies VERBATIM — no change to `unique_id`, `_attr_name`, `device_info`, value/availability logic, descriptions, or the entity set/order `async_setup_entry` produces.

---

### Task 1: Split `switch.py` (template — smallest)

**Files:**
- Create: `custom_components/dreame_a2_mower/_switch_base.py`, `switch_global.py`, `switch_map.py`
- Modify: `custom_components/dreame_a2_mower/switch.py`

- [ ] **Step 1: `_switch_base.py`** — move (verbatim) `DreameA2SwitchEntityDescription`, and (after grep-confirming they're subclassed across groups OR used by the table) `DreameA2Switch` and `_AiRecognitionBitSwitch`. If a `_build_*`/`_field_updates` helper or constant is used by switches landing in both groups, move it here too (grep each). Add `from __future__ import annotations` + the imports the moved code uses.

- [ ] **Step 2: `switch_map.py`** — move `DreameA2MapEdgemasterSwitch` (the only per-map switch — uses `map_device_info`). Import its base(s) from `._switch_base`.

- [ ] **Step 3: `switch_global.py`** — move the device-level switches: `DreameA2EdgeMowingAutoSwitch`, `DreameA2EdgeMowingSafeSwitch`, `DreameA2EdgeMowingObstacleAvoidanceSwitch`, `DreameA2ObstacleAvoidanceEnabledSwitch`, `DreameA2AiHumanDetectionSwitch`, `DreameA2AiRecognitionHumansSwitch`, `DreameA2AiRecognitionAnimalsSwitch`, `DreameA2AiRecognitionObjectsSwitch` — plus the switch description TABLE (the `tuple[DreameA2SwitchEntityDescription, ...]` `async_setup_entry` iterates) and the `_build_*`/`_field_updates` helper functions those descriptions reference (grep to confirm each helper is global-only). Import shared bases from `._switch_base`.

- [ ] **Step 4: `switch.py`** — delete the moved classes/table/helpers; keep `async_setup_entry` + docstring; import the entity classes + the table from `switch_global`/`switch_map`/`_switch_base` as `async_setup_entry` needs.

- [ ] **Step 5: Verify**
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -c "import ast,glob; [ast.parse(open(f).read()) for f in ('custom_components/dreame_a2_mower/switch.py','custom_components/dreame_a2_mower/_switch_base.py','custom_components/dreame_a2_mower/switch_global.py','custom_components/dreame_a2_mower/switch_map.py')]; print('parse ok')"
python -m pytest tests/integration/test_settings_switch_entities.py tests/integration/test_per_map_setting_switches.py tests/integration/test_entity_builders.py tests/integration/test_per_map_entity_names.py -q
python -m pytest tests -q
```
Expected: parse ok; switch/entity tests pass; full suite **1591 passed, 4 skipped**.

- [ ] **Step 6: Commit**
```bash
git add -A
git commit -m "audit-b3a: split switch.py into switch_global + switch_map (+ _switch_base)"
```

---

### Task 2: Split `select.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/_select_base.py`, `select_map_settings.py`, `select_global.py`
- Modify: `custom_components/dreame_a2_mower/select.py`

Resolved groupings (by `device_info`): `DreameA2SettingSelect` uses `mower_device_info` → global; `DreameA2MowingModeSelect` uses `map_device_info` → map_settings.

- [ ] **Step 1: `_select_base.py`** — move (verbatim) `DreameA2SettingsSelectDescription` and `_DreameA2DynamicTargetSelect` (the base for Zone/Spot selects — grep `class .*_DreameA2DynamicTargetSelect` to confirm both subclasses land in map_settings; it stays in base regardless as the shared abstract base). Add `from __future__ import annotations` + imports used.

- [ ] **Step 2: `select_map_settings.py`** (per-map): move `DreameA2ZoneSelect`, `DreameA2SpotSelect`, `DreameA2EdgeSelect`, `DreameA2MowingModeSelect`, `DreameA2PerMapMowingDirectionSelect`, `DreameA2PerMapMowingDirectionModeSelect`, `DreameA2MapMowingEfficiencySelect`, `DreameA2PerMapEdgeMowingWalkModeSelect` + any helper/constant used only by these. Import bases from `._select_base`.

- [ ] **Step 3: `select_global.py`** (device-level): move `DreameA2ActionModeSelect`, `DreameA2SettingSelect`, `DreameA2WorkLogSelect`, `DreameA2LidarArchiveSelect`, `DreameA2ActiveMapSelect`, `DreameA2WifiArchiveSelect` + the `SETTING_SELECTS` table (L467) and the settings-encoder helpers it references (`_build_pre_efficiency`, `_pre_efficiency_field_updates`, `_build_prot_path`, `_prot_path_field_updates`, `_build_text_language`, `_text_language_field_updates`, `_build_voice_language`, `_voice_language_field_updates`, `_build_wrp_resume_hours`, `_wrp_resume_hours_field_updates`) + the language/option constants (`VOICE_LANGUAGE_NAMES`, `TEXT_LANGUAGE_NAMES`, `TEXT_LANGUAGE_OPTIONS`, `APP_TEXT_LANGUAGE_NAMES`, `_PRE_PAD_DEFAULTS`, `_RESUME_HOURS_OPTIONS`). Grep each to confirm map_settings doesn't also use it — if shared, move to `_select_base.py` instead. Import shared bases from `._select_base`.

- [ ] **Step 4: `select.py`** — delete moved code; keep `async_setup_entry` + docstring; import the entity classes + `SETTING_SELECTS` from `select_global`/`select_map_settings` as `async_setup_entry` needs (it instantiates `DreameA2ActionModeSelect`, iterates `SETTING_SELECTS` for `DreameA2SettingSelect`, appends `DreameA2WorkLogSelect`/`DreameA2LidarArchiveSelect`/`DreameA2ActiveMapSelect`/`DreameA2WifiArchiveSelect`, and the per-map ones in its `extend` blocks).

- [ ] **Step 5: Verify**
```bash
python -c "import ast,glob; [ast.parse(open(f).read()) for f in ('custom_components/dreame_a2_mower/select.py','custom_components/dreame_a2_mower/_select_base.py','custom_components/dreame_a2_mower/select_map_settings.py','custom_components/dreame_a2_mower/select_global.py')]; print('parse ok')"
python -m pytest tests/integration/test_settings_select_entities.py tests/integration/test_action_mode_select.py tests/integration/test_work_log_picker.py tests/integration/test_wifi_archive_select.py tests/integration/test_per_map_entity_names.py tests/integration/test_entity_builders.py -q
python -m pytest tests -q
```
Expected: parse ok; select/entity tests pass; full suite 1591 passed, 4 skipped.

- [ ] **Step 6: Commit**
```bash
git add -A
git commit -m "audit-b3a: split select.py into select_map_settings + select_global (+ _select_base)"
```

---

### Task 3: Split `sensor.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/_sensor_base.py`, `sensor_device.py`, `sensor_map.py`, `sensor_session.py`
- Modify: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 1: `_sensor_base.py`** — move (verbatim) `DreameA2SensorEntityDescription`, `DreameA2DiagnosticSensorEntityDescription`, `_SnapshotEnumSensorBase`, `_DreameA2PerMapSensorBase`, `_DreameA2PerMapPreShadowBase`, `_DreameA2PerMapSessionSensorBase` (the shared abstract bases — `_DreameA2PerMapSessionSensorBase` subclasses `_DreameA2PerMapSensorBase`, and its subclasses land in sensor_session while the base's other subclasses land in sensor_map, so both bases belong in `_base`). Add `from __future__ import annotations` + imports used.

- [ ] **Step 2: `sensor_map.py`** (per-map metadata): move `DreameA2MapNameSensor`, `DreameA2MapAreaSensor`, `DreameA2MapSegmentCountSensor`, `DreameA2MaintenancePointsSensor`, `DreameA2ExclusionZonesSensor`, `DreameA2IgnoreObstacleZonesSensor`, `DreameA2SpotsCountSensor`, `DreameA2MapPreMowingHeightSensor`, `DreameA2MapPreEdgemasterSensor`. Import bases from `._sensor_base`.

- [ ] **Step 3: `sensor_session.py`** (per-map session totals): move `DreameA2MapSessionAreaTotalSensor`, `DreameA2MapSessionTimeTotalSensor`, `DreameA2MapSessionCountSensor`. Import bases from `._sensor_base`.

- [ ] **Step 4: `sensor_device.py`** (device-level): move `DreameA2CurrentActivitySensor`, `DreameA2LocationSensor`, `DreameA2PositioningHealthSensor`, `DreameA2MqttConnectivitySensor`, `DreameA2PickedSessionSensor`, `DreameA2Sensor`, `DreameA2DiagnosticSensor`, `DreameA2OtaStatusSensor`, `DreameA2ScheduleCountSensor`, `DreameA2WifiRefreshStatusSensor`, `DreameA2WifiHeatmapAgeSensor`, `DreameA2LastNotificationSensor`, `DreameA2ApiEndpointSensor`, `DreameA2IntegrationVersionSensor` + the `SENSORS` and `DIAGNOSTIC_SENSORS` tables + the device-sensor helpers/constants (`_manifest_version`, `_MANIFEST_VERSION`, `_describe_error_or_none`, `_format_active_selection`, `_api_endpoints_value`, `_api_endpoints_attrs`, `_freshness_value`, `_freshness_attrs`, `_WEEKDAY_LABELS`, `_ACTION_LABELS`, `_fmt_hhmm`, `_fmt_weekdays`, `_fmt_action`). Grep each helper to confirm it's device-only; if any is used by map/session sensors, move it to `_sensor_base.py`. Import bases from `._sensor_base`.

- [ ] **Step 5: `sensor.py`** — delete moved code; keep `async_setup_entry` + docstring; import the entity classes + the `SENSORS`/`DIAGNOSTIC_SENSORS` tables from the group modules as `async_setup_entry` needs.

- [ ] **Step 6: Verify**
```bash
python -c "import ast,glob; [ast.parse(open(f).read()) for f in ('custom_components/dreame_a2_mower/sensor.py','custom_components/dreame_a2_mower/_sensor_base.py','custom_components/dreame_a2_mower/sensor_device.py','custom_components/dreame_a2_mower/sensor_map.py','custom_components/dreame_a2_mower/sensor_session.py')]; print('parse ok')"
python -m pytest tests/integration/test_per_map_sensors.py tests/integration/test_per_map_session_totals.py tests/integration/test_pre_shadow_sensors.py tests/integration/test_diagnostic_sensors_new.py tests/integration/test_cloud_state_sensors.py tests/state_machine/test_new_dimension_sensors.py tests/integration/test_per_map_entity_names.py -q
python -m pytest tests -q
```
Expected: parse ok; sensor/entity tests pass; full suite 1591 passed, 4 skipped.

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "audit-b3a: split sensor.py into sensor_device + sensor_map + sensor_session (+ _sensor_base)"
```

---

### Task 4: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite + parse check**
```bash
python -m pytest tests -q
python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('custom_components/dreame_a2_mower/*.py')]; print('all parse OK')"
```
Expected: 1591 passed, 4 skipped; all parse OK.

- [ ] **Step 2: Confirm the entity set is unchanged.** The per-map naming tests pin entity_ids; confirm they pass and that each platform file shrank:
```bash
python -m pytest tests/integration/test_per_map_entity_names.py tests/integration/test_devices_helpers.py -q
wc -l custom_components/dreame_a2_mower/switch.py custom_components/dreame_a2_mower/select.py custom_components/dreame_a2_mower/sensor.py
ls custom_components/dreame_a2_mower/_switch_base.py custom_components/dreame_a2_mower/switch_global.py custom_components/dreame_a2_mower/switch_map.py custom_components/dreame_a2_mower/_select_base.py custom_components/dreame_a2_mower/select_global.py custom_components/dreame_a2_mower/select_map_settings.py custom_components/dreame_a2_mower/_sensor_base.py custom_components/dreame_a2_mower/sensor_device.py custom_components/dreame_a2_mower/sensor_map.py custom_components/dreame_a2_mower/sensor_session.py
```
Expected: naming tests pass; the three platform files are now thin (`async_setup_entry` + imports); all 10 new modules exist.

- [ ] **Step 3: Report for user ship decision** (no push — user runs push + release.sh; next release crosses a9→a10 so release.sh auto-bumps to 1.0.18a1).

---

## Self-Review

**Spec coverage:** select split → T2; sensor split → T3; switch split → T1; `_<platform>_base.py` per platform → each task Step 1; orphan audit explicitly deferred (not a task). ✓

**Placeholder scan:** No TBD/TODO. The per-file class→module assignments are explicit (from the spec, with the two ambiguous select classes resolved by device_info). The "move verbatim + grep-verify imports/placement" is a concrete refactor procedure (the source is the current platform file); the Split Procedure conventions define the mechanical rules. Test commands have expected output.

**Type/name consistency:** Module names (`_switch_base`/`switch_global`/`switch_map`; `_select_base`/`select_global`/`select_map_settings`; `_sensor_base`/`sensor_device`/`sensor_map`/`sensor_session`) and the class assignments are consistent across tasks. `async_setup_entry` stays in each platform file. Acyclic import direction (`_base` ← groups ← platform) stated in conventions and each task.
