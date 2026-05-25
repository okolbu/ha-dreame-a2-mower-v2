# Refresher Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant legacy cloud refresher timers by folding their still-needed port logic into the single 2-min `_refresh_cloud_state` path, fixing a latent CFG clobber bug along the way.

**Architecture:** The CloudState architecture already fetches the device's full state every 2 min and ports MIHIS + SETTINGS onto `MowerState`. This plan drops the duplicate `_refresh_mihis` and `_refresh_cfg` timers, moves the CFG→MowerState port into a pure, independently-tested helper (`cfg_to_state_updates`) consumed by the cloud_state path, applies MAPL active-map detection from `cs.mapl`, and stops the full-state fetch from double-fetching LOCN/DOCK (the 60 s timers own those) — then removes the now-dead `CloudState.locn`/`.dock` fields.

**Tech Stack:** Python 3.13 (HA custom integration), pytest. Tests run in the vanilla stubbed-HA venv: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-25-refresher-consolidation-design.md`

**Conventions:** Commits prefixed `audit-b1-refresher:`, authored as Olav Kolbu (already the git default), **no** co-author trailer, on `main`. Do **not** push. Move refactored bodies verbatim; prune imports only via per-name grep.

**Test command (use everywhere below):**
```bash
PY=/data/claude/homeassistant/.venv-vanilla/bin/python
cd /data/claude/homeassistant/ha-dreame-a2-mower
```
Baseline before this plan: **1591 passed, 4 skipped**. No pre-existing test may regress.

---

## File Structure

| File | Change |
|---|---|
| `custom_components/dreame_a2_mower/coordinator/_property_apply.py` | **Add** pure `cfg_to_state_updates(cfg) -> dict` helper |
| `custom_components/dreame_a2_mower/coordinator/_cloud_state.py` | Wire helper into `_apply_cloud_state_to_mower_state`; add `_apply_mapl(cs.mapl)` to `_refresh_cloud_state`; rewrite docstring |
| `custom_components/dreame_a2_mower/coordinator/_refreshers.py` | **Delete** `_refresh_mihis` and `_refresh_cfg` |
| `custom_components/dreame_a2_mower/coordinator/_core.py` | **Remove** `_periodic_cfg` + `_periodic_mihis` timer blocks; fix stale "10-min" comment |
| `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` | Fix stale "10-min" comments |
| `custom_components/dreame_a2_mower/cloud_state.py` | **Remove** `locn` + `dock` fields |
| `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` | Remove `fetch_locn`/`fetch_dock` probes + constructor kwargs |
| `custom_components/dreame_a2_mower/CLAUDE.md` | **Add** "Refresher cadence" subsection |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | Append `verifications:` for `pre_edgemaster` source correction |
| `tools/state_machine_audit_fake_coord.py` | Drop `locn=`/`dock=` from its `CloudState(...)` builder |
| `tests/…` (many) | Drop `locn=`/`dock=` kwargs; new helper + integration tests |

Execution order: **Task 1 (A) → Task 2 (C) → Task 3 + 4 (B) → Task 5 (D)**. Tasks 1 and 2 are mutually independent; 3 depends on neither; 4 depends on 3; 5 is cleanup over the finished code.

---

## Task 1: Drop `_refresh_mihis` (Block A)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:451-463`
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py:510-554`
- Characterization (already exists): `tests/integration/test_startup_availability.py::test_mihis_fields_populated_at_startup`

The MIHIS port already lives in `_apply_cloud_state_to_mower_state` (`_cloud_state.py:161-168`), which runs every 2 min. The standalone 10-min `_refresh_mihis` timer is pure duplication. **No new test is needed** — `test_mihis_fields_populated_at_startup` (`test_startup_availability.py:84-91`) already asserts the cloud_state path populates `total_mowed_area_m2` / `total_mowing_time_min` / `mowing_count` from `cs.mihis`. That is our safety net for the removal.

- [ ] **Step 1: Confirm the existing characterization test passes**

```bash
$PY -m pytest tests/integration/test_startup_availability.py::test_mihis_fields_populated_at_startup -v
```
Expected: PASS. (If it fails, STOP — the assumption that the cloud_state path already ports MIHIS is wrong; escalate before deleting anything.)

- [ ] **Step 2: Remove the `_periodic_mihis` timer block**

In `_core.py`, delete lines 451-463 (the comment block + `_periodic_mihis` def + `async_on_unload(async_track_time_interval(...))` + the immediate `await self._refresh_mihis()`):

```python
            # Schedule MIHIS refresh every 10 min; also fire one
            # immediately so the lifetime-totals sensors switch from
            # the local-archive seed to the cloud-authoritative numbers
            # right after HA reload.
            async def _periodic_mihis(_now: Any) -> None:
                await self._refresh_mihis()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_mihis, timedelta(minutes=10)
                )
            )
            await self._refresh_mihis()
```
Delete the whole block. (The local-archive seed at boot — `_cloud_state`/`_core` archive sweep — still seeds totals before the first cloud refresh.)

- [ ] **Step 3: Delete the `_refresh_mihis` method**

In `_refreshers.py`, delete the entire `_refresh_mihis` method (lines 510-554, from `async def _refresh_mihis(self) -> None:` through its final `self.async_set_updated_data(new_state)`).

- [ ] **Step 4: Grep-check for any remaining references**

```bash
grep -rn "_refresh_mihis" custom_components tests
```
Expected: **no matches**. If any remain, resolve them before continuing.

- [ ] **Step 5: Run the full suite**

```bash
$PY -m pytest tests -q
```
Expected: 1591 passed, 4 skipped (no test added in this task — the removal is covered by the existing characterization test). No regressions.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "audit-b1-refresher: drop redundant _refresh_mihis timer (cloud_state path covers MIHIS)"
```

---

## Task 2: Dedup LOCN/DOCK fetch + remove dead CloudState fields (Block C)

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py:506-546`
- Modify: `custom_components/dreame_a2_mower/cloud_state.py:110-128`
- Modify (tests): `tests/integration/conftest.py:201-205`, `tests/test_cloud_state_dataclasses.py`, `tests/integration/test_coordinator_writes.py`, `tests/integration/test_startup_availability.py`, `tests/integration/test_cloud_state_entity_attrs.py`, `tests/integration/test_cloud_state_sensors.py`, `tests/integration/test_settings_switch_entities.py`, `tests/integration/test_settings_active_follower_rebind.py`, `tests/protocol/test_fetch_full_cloud_state.py`, `tests/audit/test_discover.py`, `tests/audit/test_fake_coord.py`

Nothing reads `CloudState.locn` / `CloudState.dock` (verified in the spec). LOCN→MowerState and DOCK→MowerState+state-machine are owned by the 60 s `_refresh_locn` / `_refresh_dock` timers, which stay untouched.

- [ ] **Step 1: Write the failing dedup test**

Add to `tests/protocol/test_fetch_full_cloud_state.py`:

```python
def test_fetch_full_cloud_state_does_not_probe_locn_or_dock():
    """LOCN/DOCK are owned by the 60s timers; the full-state fetch must
    not double-fetch them."""
    client = _make_client(REAL_BATCH, {"VER": 461})
    # Attach spies even though _make_client no longer wires these.
    client.fetch_locn = MagicMock(return_value={"pos": [1.0, 2.0]})
    client.fetch_dock = MagicMock(return_value={"dock": {"x": 1}})
    client.fetch_full_cloud_state()
    client.fetch_locn.assert_not_called()
    client.fetch_dock.assert_not_called()
```

- [ ] **Step 2: Run it — expect FAIL**

```bash
$PY -m pytest tests/protocol/test_fetch_full_cloud_state.py::test_fetch_full_cloud_state_does_not_probe_locn_or_dock -v
```
Expected: FAIL — `fetch_locn`/`fetch_dock` ARE currently called.

- [ ] **Step 3: Remove the LOCN/DOCK probes + constructor kwargs in `_fetchers.py`**

Delete the `locn` and `dock` probe blocks (`_fetchers.py:508-517`):

```python
        try:
            locn = self.fetch_locn()
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_locn raised: %s", e)
            locn = None
        try:
            dock = self.fetch_dock() or {}
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_dock raised: %s", e)
            dock = {}
```
Keep the `mapl` and `mihis` probe blocks. Then in the `return CloudState(...)` call, **delete** the `locn=locn,` and `dock=dock,` lines (currently `_fetchers.py:541-542`).

- [ ] **Step 4: Remove the `locn` + `dock` fields from `CloudState`**

In `cloud_state.py`, delete these two lines from the `CloudState` dataclass (currently L124-125):

```python
    locn: tuple[float, float] | None
    dock: dict[str, Any]
```

- [ ] **Step 5: Update `_make_client` in the fetch-full test**

In `tests/protocol/test_fetch_full_cloud_state.py`, change `_make_client` to stop wiring the removed probes:

```python
def _make_client(batch_response, cfg_response, mapl=None, mihis=None):
    client = object.__new__(DreameA2CloudClient)
    client.get_batch_device_datas = MagicMock(return_value=batch_response)
    client.fetch_cfg = MagicMock(return_value=cfg_response or {})
    client.fetch_mapl = MagicMock(return_value=mapl)
    client.fetch_mihis = MagicMock(return_value=mihis or {})
    return client
```
(The new test in Step 1 re-attaches `fetch_locn`/`fetch_dock` spies itself.)

- [ ] **Step 6: Drop `locn=`/`dock=` kwargs from every other `CloudState(...)` site**

Remove the `locn=...,` and `dock=...,` kwargs (and `locn`/`dock` keys in `make_empty_cloud_state`'s `base` dict) from each:
- `tests/integration/conftest.py` — the `base = dict(...)` in `make_empty_cloud_state` (lines `locn=None,` / `dock={},`).
- `tests/test_cloud_state_dataclasses.py` — both `CloudState(...)` calls (the `locn=None,`/`dock={},` lines around L25-26 and the inline `... locn=None, dock={}, ...` around L41).
- `tests/integration/test_coordinator_writes.py` — the two `... locn=None, dock={}, ...` lines (~L60, L126).
- `tests/integration/test_startup_availability.py` — `locn=None,`/`dock={},` (~L69-70).
- `tests/integration/test_cloud_state_entity_attrs.py` — `locn=None, dock={}, ...` (~L51).
- `tests/integration/test_cloud_state_sensors.py` — `locn=None, dock={}, ...` (~L43).
- `tests/integration/test_settings_switch_entities.py` — `locn=None, dock={}, ...` (~L60).
- `tests/integration/test_settings_active_follower_rebind.py` — `locn=None,`/`dock={},` (~L125-126).
- `tools/state_machine_audit_fake_coord.py:71-72` — the audit fake-coord builder's `CloudState(...)` call has `locn=None,`/`dock={},`. **This is a non-test site; removing the fields breaks the tool (and `tests/audit/test_fake_coord.py`, which imports it) if missed.** Delete both kwargs.

After editing, verify none remain:
```bash
grep -rn "locn=\|dock=" tests/ tools/ custom_components/dreame_a2_mower/cloud_client/_fetchers.py
```
Expected: no `CloudState`-related `locn=`/`dock=` matches. (Unrelated `dock=` in `tests/test_session_card_timeline.py` and `at_dock=` in `tests/event/` are session-summary / event params — leave them.)

- [ ] **Step 7: Fix the two audit tests**

- `tests/audit/test_discover.py:72`: the source string `"lambda coord: coord.cloud_state.dock.get('connect_status')"` is a classifier input, not a real access. Retarget it to a surviving field so it isn't misleading:
  ```python
      src = "lambda coord: coord.cloud_state.mihis.get('area')"
  ```
  (The assertion `classify_holder(src) == "cloud_state"` still holds.)
- `tests/audit/test_fake_coord.py:23-27` (`test_fake_coord_has_cloud_state`): it asserts `getattr(coord.cloud_state, "dock", None) in (None, {}, {})`. That still *passes* after field removal (getattr default), but the field and comment are now stale. Retarget to a surviving field and fix the comment:
  ```python
  def test_fake_coord_has_cloud_state():
      coord = build_fake_coord()
      assert coord.cloud_state is not None
      # CloudState.cfg starts as an empty dict
      assert coord.cloud_state.cfg == {}
  ```

- [ ] **Step 8: Run the new test (PASS) then the full suite**

```bash
$PY -m pytest tests/protocol/test_fetch_full_cloud_state.py -v
$PY -m pytest tests -q
```
Expected: the dedup test PASSes; full suite 1592 passed (1591 + this new test), 4 skipped.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "audit-b1-refresher: stop double-fetching LOCN/DOCK in full-state; remove dead CloudState.locn/.dock fields"
```

---

## Task 3: Add the pure `cfg_to_state_updates` helper (Block B, part 1)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_property_apply.py` (add helper at module level)
- Test: `tests/coordinator/test_cfg_to_state_updates.py` (create)

The helper holds the CFG→MowerState decode logic currently inside `_refresh_cfg` (`_refreshers.py:127-398`), converted from the "default-None local var + unconditional `dataclasses.replace` kwarg" pattern to **"only add a key to the `updates` dict when the CFG source is present and decodes."** It is pure: `dict → dict`, no `self`. `_property_apply.py` already imports `_s2p51`, `LOGGER`, and defines `_consumable_pct_remaining`, so no new imports are needed.

**The two excluded fields:** `pre_mowing_height_mm` and `pre_edgemaster` are owned by the s6.2 push (`mower/property_mapping.py:114,117`) and MUST NOT appear in the returned dict.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/coordinator/test_cfg_to_state_updates.py`:

```python
"""Unit tests for the pure CFG -> MowerState updates helper."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator._property_apply import (
    cfg_to_state_updates,
)


def test_present_keys_are_ported():
    cfg = {
        "CLS": 1,
        "VOL": 60,
        "DND": [1, 1200, 480],
        "WRP": [1, 0],
        "BAT": [80, 60, 1, 1, 1200, 480],
        "PROT": 1,
    }
    out = cfg_to_state_updates(cfg)
    assert out["child_lock_enabled"] is True
    assert out["volume_pct"] == 60
    assert out["dnd_enabled"] is True
    assert out["dnd_start_min"] == 1200
    assert out["dnd_end_min"] == 480
    assert out["rain_protection_enabled"] is True
    assert out["rain_protection_resume_hours"] == 0
    assert out["auto_recharge_battery_pct"] == 80
    assert out["custom_charging_enabled"] is True
    assert out["navigation_path_smart"] is True


def test_absent_keys_are_omitted_not_nulled():
    """A CFG dict missing a key must not emit that key at all, so the
    caller leaves the prior MowerState value untouched."""
    out = cfg_to_state_updates({"CLS": 0})
    assert out == {"child_lock_enabled": False}
    assert "volume_pct" not in out
    assert "dnd_enabled" not in out
    assert "blades_life_pct" not in out


def test_push_owned_pre_fields_never_emitted():
    """pre_mowing_height_mm / pre_edgemaster belong to the s6.2 push,
    not CFG — even a full-length PRE list must not produce them."""
    out = cfg_to_state_updates({"PRE": [3, 1, 25, 0, 0, 0, 0, 0, 1]})
    assert out["pre_zone_id"] == 3
    assert out["pre_mowing_efficiency"] == 1
    assert "pre_mowing_height_mm" not in out
    assert "pre_edgemaster" not in out


def test_cms_wear_percentages():
    # CMS = [blades_min, cleaning_brush_min, robot_maintenance_min, link]
    out = cfg_to_state_updates({"CMS": [1000, 2000, 3000, 0]})
    assert "blades_life_pct" in out
    assert "cleaning_brush_life_pct" in out
    assert "robot_maintenance_life_pct" in out


def test_malformed_value_is_skipped_not_raised():
    """A malformed CFG value is logged and skipped, not fatal."""
    out = cfg_to_state_updates({"VOL": "not-an-int", "CLS": 1})
    assert "volume_pct" not in out
    assert out["child_lock_enabled"] is True


def test_empty_cfg_returns_empty_dict():
    assert cfg_to_state_updates({}) == {}
```

- [ ] **Step 2: Run them — expect FAIL (import error)**

```bash
$PY -m pytest tests/coordinator/test_cfg_to_state_updates.py -v
```
Expected: FAIL — `cannot import name 'cfg_to_state_updates'`.

- [ ] **Step 3: Implement `cfg_to_state_updates` in `_property_apply.py`**

Add this module-level function (place it near the other pure helpers, e.g. after `_consumable_pct_remaining`). Build it by moving each decode block from `_refresh_cfg` (`_refreshers.py:127-398`) **verbatim**, with the mechanical change that each field is written into `updates` inside its existing guard instead of into a default-None local var. The structure:

```python
def cfg_to_state_updates(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pure CFG dict -> MowerState field updates.

    Only includes a field when its CFG key is present and decodes cleanly;
    an absent or malformed key is omitted (the caller keeps the prior value).
    pre_mowing_height_mm / pre_edgemaster are intentionally NOT ported here —
    they are owned by the s6.2 push (mower/property_mapping.py:114,117).
    """
    updates: dict[str, Any] = {}

    # ---- CMS: per-consumable wear ----
    cms = cfg.get("CMS")
    if isinstance(cms, list) and len(cms) >= 3:
        try:
            updates["blades_life_pct"] = _consumable_pct_remaining(
                int(cms[0]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[0]
            )
            updates["cleaning_brush_life_pct"] = _consumable_pct_remaining(
                int(cms[1]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[1]
            )
            updates["robot_maintenance_life_pct"] = _consumable_pct_remaining(
                int(cms[2]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[2]
            )
        except (TypeError, ValueError, ZeroDivisionError) as ex:
            LOGGER.warning("[CFG] CMS decode error: %s — cms=%r", ex, cms)

    # ---- CLS: child lock ----
    cls_raw = cfg.get("CLS")
    if cls_raw is not None:
        try:
            updates["child_lock_enabled"] = bool(int(cls_raw))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] CLS decode error: %s — cls=%r", ex, cls_raw)

    # ---- VOL: voice volume ----
    vol_raw = cfg.get("VOL")
    if vol_raw is not None:
        try:
            updates["volume_pct"] = int(vol_raw)
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] VOL decode error: %s — vol=%r", ex, vol_raw)

    # ---- PRE: mowing preferences (g2408: only [0]=zone_id, [1]=efficiency).
    # pre_mowing_height_mm / pre_edgemaster owned by the s6.2 push — NOT ported.
    pre_raw = cfg.get("PRE")
    if isinstance(pre_raw, list):
        try:
            if len(pre_raw) >= 1:
                updates["pre_zone_id"] = int(pre_raw[0])
            if len(pre_raw) >= 2:
                updates["pre_mowing_efficiency"] = int(pre_raw[1])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] PRE decode error: %s — pre=%r", ex, pre_raw)

    # ... continue for LANG, DND, WRP, LOW, BAT, LIT, ATA, REC, MSG_ALERT,
    #     VOICE, and the _cfg_bool toggles (FDP/STUN/AOP/PROT), each following
    #     the same "guard -> updates[field] = decoded" pattern moved verbatim
    #     from _refresh_cfg lines 171-398.

    return updates
```

For the `_cfg_bool`-style toggles, define the closure inside the function (verbatim from `_refreshers.py:352-360`) but write into `updates` only when non-None:

```python
    def _cfg_bool(name: str) -> bool | None:
        raw = cfg.get(name)
        if raw is None:
            return None
        try:
            return bool(int(raw))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] %s decode error: %s — raw=%r", name, ex, raw)
            return None

    for cfg_key, field in (
        ("FDP", "frost_protection_enabled"),
        ("STUN", "auto_recharge_standby_enabled"),
        ("AOP", "ai_obstacle_photos_enabled"),
        ("PROT", "navigation_path_smart"),
    ):
        v = _cfg_bool(cfg_key)
        if v is not None:
            updates[field] = v
```

**Complete set of output keys** the helper must be able to emit (use this as the coverage checklist when porting the remaining blocks): `blades_life_pct`, `cleaning_brush_life_pct`, `robot_maintenance_life_pct`, `child_lock_enabled`, `volume_pct`, `language_code`, `language_text_idx`, `language_voice_idx`, `dnd_enabled`, `dnd_start_min`, `dnd_end_min`, `pre_zone_id`, `pre_mowing_efficiency`, `rain_protection_enabled`, `rain_protection_resume_hours`, `low_speed_at_night_enabled`, `low_speed_at_night_start_min`, `low_speed_at_night_end_min`, `auto_recharge_battery_pct`, `resume_battery_pct`, `custom_charging_enabled`, `charging_start_min`, `charging_end_min`, `led_period_enabled`, `led_in_standby`, `led_in_working`, `led_in_charging`, `led_in_error`, `anti_theft_lift_alarm`, `anti_theft_offmap_alarm`, `anti_theft_realtime_location`, `human_presence_alert_enabled`, `human_presence_alert_sensitivity`, `human_presence_scenario_standby`, `human_presence_scenario_mowing`, `human_presence_scenario_recharge`, `human_presence_scenario_patrol`, `human_presence_alert_voice`, `photo_consent`, `human_presence_alert_push_interval_min`, `frost_protection_enabled`, `auto_recharge_standby_enabled`, `ai_obstacle_photos_enabled`, `navigation_path_smart`, `msg_alert_anomaly`, `msg_alert_error`, `msg_alert_task`, `msg_alert_consumables`, `voice_regular_notification`, `voice_work_status`, `voice_special_status`, `voice_error_status`. **Excluded:** `pre_mowing_height_mm`, `pre_edgemaster`.

- [ ] **Step 4: Run the unit tests — expect PASS**

```bash
$PY -m pytest tests/coordinator/test_cfg_to_state_updates.py -v
```
Expected: all PASS. (If `tests/coordinator/` lacks `__init__.py` and the suite needs it, add an empty one to match the existing test-package layout.)

- [ ] **Step 5: Run the full suite (helper is not wired yet — nothing else changes)**

```bash
$PY -m pytest tests -q
```
Expected: 1598 passed (1592 + 6 new), 4 skipped.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "audit-b1-refresher: add pure cfg_to_state_updates helper (safe updates-dict, excludes push-owned PRE fields)"
```

---

## Task 4: Wire CFG + MAPL into cloud_state, delete `_refresh_cfg` (Block B, part 2)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:78-115` (add `_apply_mapl(cs.mapl)`) and `:150-206` (merge CFG updates)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:387-397` (remove `_periodic_cfg`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py:104-487` (delete `_refresh_cfg`)
- Test: `tests/integration/test_startup_availability.py` (CFG port + clobber), `tests/integration/test_coordinator.py` (MAPL wiring)

- [ ] **Step 1a: Write failing CFG-port + clobber tests in `test_startup_availability.py`**

This file already has `_make_coord_with_full_cloud_state()` (L23) which stubs `async_set_updated_data` and is the correct harness for `_apply_cloud_state_to_mower_state`. Add `import dataclasses` at the top if absent, then add:

```python
def test_cfg_settings_ported_via_cloud_state():
    """CFG settings reach MowerState through the cloud_state path now that
    cfg_to_state_updates is folded in."""
    coord = _make_coord_with_full_cloud_state()
    coord.cloud_state = dataclasses.replace(
        coord.cloud_state, cfg={"CLS": 1, "VOL": 42, "WRP": [1, 0]}
    )
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.child_lock_enabled is True
    assert coord.data.volume_pct == 42
    assert coord.data.rain_protection_enabled is True


def test_cfg_does_not_clobber_push_owned_pre_fields():
    """A cloud_state refresh whose CFG lacks PRE height/edgemaster must leave
    push-set values intact (the old _refresh_cfg nulled them every tick)."""
    coord = _make_coord_with_full_cloud_state()
    coord.data = dataclasses.replace(
        coord.data, pre_edgemaster=True, pre_mowing_height_mm=25
    )
    coord.cloud_state = dataclasses.replace(coord.cloud_state, cfg={"PRE": [3, 1]})
    coord._apply_cloud_state_to_mower_state()
    assert coord.data.pre_edgemaster is True
    assert coord.data.pre_mowing_height_mm == 25
    assert coord.data.pre_zone_id == 3
```

- [ ] **Step 1b: Write the failing MAPL-wiring test in `test_coordinator.py`**

Model it on the existing `test_refresh_cloud_state_syncs_map_subdevices` (`test_coordinator.py:2961`), adding a spy on `_apply_mapl`:

```python
def test_refresh_cloud_state_applies_mapl():
    """_refresh_cloud_state must drive active-map detection from cs.mapl
    (replaces the former _refresh_cfg trailing MAPL poll)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cloud = MagicMock()
    coord.hass = MagicMock()

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass.async_add_executor_job.side_effect = _exec
    fake_cs = MagicMock()
    coord._cloud.fetch_full_cloud_state = MagicMock(return_value=fake_cs)
    coord.async_update_listeners = MagicMock()

    with patch.object(coord, "_render_maps_from_cloud_state", new=AsyncMock()), \
         patch.object(coord, "_apply_cloud_state_to_mower_state"), \
         patch.object(coord, "_sync_map_subdevices"), \
         patch.object(coord, "_apply_mapl") as m_mapl:
        asyncio.run(coord._refresh_cloud_state())

    m_mapl.assert_called_once_with(fake_cs.mapl)
```

- [ ] **Step 2: Run them — expect FAIL**

```bash
$PY -m pytest tests/integration/test_startup_availability.py -k "cfg" tests/integration/test_coordinator.py::test_refresh_cloud_state_applies_mapl -v
```
Expected: FAIL — CFG fields not ported by the cloud_state path yet, and `_apply_mapl` not called by `_refresh_cloud_state` yet.

- [ ] **Step 3: Merge the CFG helper into `_apply_cloud_state_to_mower_state`**

In `_cloud_state.py`, add the import at the existing `from ._property_apply import (...)` block:
```python
    cfg_to_state_updates,
```
Then, inside `_apply_cloud_state_to_mower_state`, replace the stale comment at L199-201:
```python
        # CFG keys → MowerState (same fields as _refresh_cfg used to set;
        # the existing _refresh_cfg stays for now to do the heavy lifting,
        # see Task 7 step 6).
        if not updates:
            return
```
with:
```python
        # CFG keys → MowerState (folded from the former _refresh_cfg; uses the
        # safe updates-dict pattern so an absent CFG key never nulls a field).
        updates.update(cfg_to_state_updates(cs.cfg))
        if not updates:
            return
```

- [ ] **Step 4: Apply MAPL from `cs.mapl` in `_refresh_cloud_state`**

In `_cloud_state.py`, in `_refresh_cloud_state`, after `self.cloud_state = new_state` (L104) and **before** `self._apply_cloud_state_to_mower_state()` (L111), add:
```python
        # Active-map detection from the unified fetch (replaces the former
        # _refresh_cfg trailing MAPL poll). Ordered before the MowerState
        # apply so SETTINGS/CFG fields key off the correct active map on
        # cold start.
        self._apply_mapl(new_state.mapl)
```
Note: `_apply_mapl` on an active-map *change* itself calls `_apply_cloud_state_to_mower_state` + a render + listeners; the subsequent explicit calls in `_refresh_cloud_state` are then idempotent. Verify no test in `test_active_map_routing` / `test_startup_availability` breaks on an extra broadcast.

- [ ] **Step 5: Remove the `_periodic_cfg` timer block**

In `_core.py`, delete lines 387-397:
```python
            # Schedule CFG refresh every 10 minutes; also fire one immediately
            # so blade-life / side-brush-life are populated at startup.
            async def _periodic_cfg(_now: Any) -> None:
                await self._refresh_cfg()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cfg, timedelta(minutes=10)
                )
            )
            await self._refresh_cfg()
```
The startup `_refresh_cloud_state()` immediately above (L385) already populates these fields on boot.

- [ ] **Step 6: Delete the `_refresh_cfg` method**

In `_refreshers.py`, delete the entire `_refresh_cfg` method (lines 104-487). Keep `_refresh_mapl` (104 is `_refresh_cfg`; do not touch `_refresh_mapl` at L86).

- [ ] **Step 7: Grep-check for stragglers**

```bash
grep -rn "_refresh_cfg" custom_components tests
```
Expected: **no matches**.

- [ ] **Step 8: Run the targeted tests then the full suite**

```bash
$PY -m pytest tests/integration/test_startup_availability.py tests/integration/test_active_map_routing.py tests/integration/test_coordinator.py::test_refresh_cloud_state_applies_mapl -v
$PY -m pytest tests -q
```
Expected: new tests PASS; full suite 1601 passed (1598 + 3 new), 4 skipped. No regressions. If `test_startup_availability` regresses on availability timing, confirm the startup `_refresh_cloud_state()` populates the formerly-`_refresh_cfg` fields (it now calls `cfg_to_state_updates` via the apply) — adjust the test only if it asserted the old two-pass cold-start ordering.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "audit-b1-refresher: fold CFG port + MAPL into cloud_state path; drop _refresh_cfg timer"
```

---

## Task 5: Comment sweep, docs, fact-discipline (Block D)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py:117,123,301,622,649`
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:514` (+ any "10-min" left near removed blocks)
- Modify: `custom_components/dreame_a2_mower/coordinator/_cloud_state.py:78-90` (docstring)
- Modify: `custom_components/dreame_a2_mower/CLAUDE.md`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

This task is docs/comments only — no behavior change.

- [ ] **Step 1: Sweep stale "10-min" cadence comments**

The live cloud-refresh cadence is 2 min. Find every stale reference:
```bash
grep -rn "10-min\|10 min\|next 10\|every 10 min" custom_components/dreame_a2_mower/coordinator/
```
For each in `_mqtt_handlers.py` (≈L117, L123, L301, L622, L649) and `_core.py:514`, reword "the next 10-min cloud refresh" → "the next 2-min cloud refresh" (or "the next cloud refresh"). Do not touch comments describing genuinely 10-min-or-slower things if any remain — but after Tasks 1 & 4 there should be none (cfg/mihis were the 10-min timers).

- [ ] **Step 2: Rewrite the `_refresh_cloud_state` docstring**

In `_cloud_state.py`, replace the body of the `_refresh_cloud_state` docstring (currently L79-91, the "The remaining legacy refreshers … remain scheduled as separate periodic cycles pending a future consolidation pass." paragraph) with an accurate description:

```python
        """Single-shot fetch of the full cloud state.

        Called every 2 min via the periodic timer. Map data, CFG, MIHIS and
        MAPL active-map detection are all handled here:
        `_apply_mapl(new_state.mapl)` sets the active map, then
        `_apply_cloud_state_to_mower_state` ports MIHIS, per-map SETTINGS and
        CFG (via `cfg_to_state_updates`) onto MowerState.

        Timers that intentionally remain separate: `_refresh_locn` /
        `_refresh_dock` (60 s fast cadence; dock also feeds the state machine),
        `_refresh_net` (1 h), `_refresh_dev` (6 h), `_poll_slow_properties`
        (1 h). LOCN/DOCK are NOT fetched here — those timers own them.

        On success: self.cloud_state is replaced atomically. Entities and
        consumers re-render via async_update_listeners. On failure:
        self.cloud_state is left unchanged.
        """
```

- [ ] **Step 3: Add the "Refresher cadence" subsection to the integration CLAUDE.md**

Append to `custom_components/dreame_a2_mower/CLAUDE.md` (after the "Coordinator structure" section):

```markdown
## Refresher cadence (load-bearing)

Cloud polling is consolidated onto one full-state timer plus a few
fast/slow specialists. Do **not** re-add per-slot CFG/MIHIS timers — they
were removed in the 2026-05-25 refresher consolidation
(`docs/superpowers/specs/2026-05-25-refresher-consolidation-design.md`).

| Timer | Interval | Why separate |
|---|---|---|
| `_refresh_cloud_state` | 2 min | Full state: cfg, mihis, mapl, settings, maps, props. Ports CFG via `cfg_to_state_updates`, MIHIS + SETTINGS, and active-map via `_apply_mapl(cs.mapl)`. |
| `_refresh_locn` | 60 s | GPS position wants low latency. |
| `_refresh_dock` | 60 s | Dock arrival/departure latency **and** feeds `state_machine.handle_cloud_poll` (cloud_state path does not). |
| `_refresh_net` | 1 h | NET is not part of the full-state fetch. |
| `_refresh_dev` | 6 h | DEV is not part of the full-state fetch. |
| `_poll_slow_properties` | 1 h | s6.3 + s1.5 serial-while-unknown; feeds the state machine. |

`CloudState` does **not** carry `locn`/`dock` — those flow straight to
`MowerState` via their 60 s timers. The CFG→MowerState port lives in the pure
`coordinator/_property_apply.py:cfg_to_state_updates` helper, which never nulls
a field for an absent CFG key and never emits `pre_mowing_height_mm` /
`pre_edgemaster` (those are owned by the s6.2 push, `property_mapping.py`).
```

- [ ] **Step 4: Record the entity source correction in entity-inventory.yaml**

The source of `pre_edgemaster` (and `pre_mowing_height_mm`) changed: it is no
longer clobbered by the CFG poll, only set by the s6.2 push. Append a
`verifications:` entry to the `sensor.dreame_a2_mower_map_N_pre_edgemaster`
record (`entity-inventory.yaml:156`). Read that record first to match the
indentation/field style, then add:

```yaml
    verifications:
      - date: "2026-05-25"
        status: verified
        claim: "pre_edgemaster is sourced solely from the s6.2 push; the CFG
          refresh no longer writes it (refresher consolidation removed the
          _refresh_cfg clobber)."
        evidence: "mower/property_mapping.py:114,117"
```
Also bump that record's `status.last_seen` (or the file-level `last_seen` if that's the convention there) to `2026-05-25`. If the file has an `inventory_audit.py` gate, run it:
```bash
$PY tools/inventory_audit.py
```
Expected: passes.

- [ ] **Step 5: Run the full suite (sanity — docs/comments shouldn't affect it)**

```bash
$PY -m pytest tests -q
```
Expected: 1601 passed, 4 skipped (unchanged from Task 4).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "audit-b1-refresher: sweep stale 10-min comments, document refresher cadence, record pre_edgemaster source correction"
```

---

## Final verification

- [ ] **All five tasks committed; working tree clean**
```bash
git status -sb && git log --oneline -6
```
- [ ] **Full suite green**
```bash
$PY -m pytest tests -q
```
Expected: **1601 passed, 4 skipped** (1591 baseline + 10 new tests).
- [ ] **No dangling references to removed symbols**
```bash
grep -rn "_refresh_cfg\|_refresh_mihis\|_periodic_cfg\|_periodic_mihis\|cloud_state.locn\|cloud_state.dock" custom_components tests tools
```
Expected: no matches (the only `.locn`/`.dock` hits, if any, must be MowerState/session-summary, not CloudState).
- [ ] **Report the diffstat and the final test count to the user. Do NOT push** (push is gated on explicit user authorization per the working rules).
```

## Notes for the executing worker

- This is an **audit refactor**: behavior is preserved except the one deliberate fix (CFG no longer clobbers push-owned PRE fields, and folds run at 2-min instead of 10-min cadence). The existing per-area suite is the characterization gate; move decode bodies verbatim.
- After each task, the two-stage review (spec adherence, then code quality) applies per `subagent-driven-development`.
- If the cold-start availability test (`test_startup_availability`) asserts the **old** two-pass ordering (cloud_state then `_refresh_cfg`), that assertion is now obsolete — the single-pass `_refresh_cloud_state` (with `_apply_mapl` + folded CFG) populates everything in one go. Update the test's expectation, do not reintroduce a second pass.
