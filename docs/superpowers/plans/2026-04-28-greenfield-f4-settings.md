# Greenfield F4 — Settings (Mowing + More) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface all the Dreame A2's user-configurable settings as Home Assistant entities. After F4 the user has, in HA, the same setting controls visible in the Dreame app's General Mode and More Settings pages: mowing height + efficiency + edgemaster, rain/frost protection, DND, light scenarios, charging schedule, child lock, etc. Entities are settable when the write path is confirmed working on g2408; otherwise read-only.

**Architecture:** Settings split into two transport classes:
1. **CFG-resident** (`CLS`, `DND`, `VOL`, `PRE` array, etc.) — read via `getCFG` (already wired in F2.4.1), write via `setCFG`. Confirmed working write paths on g2408 (legacy proves it).
2. **s2.51 multiplexed config** — the multi-field push that carries Rain Protection, Low Speed at Night, LED scenarios, Anti-Theft, etc. Decode via `protocol/config_s2p51.decode_s2p51` (lifted in F1.1.1). Write via `encode_s2p51` + `set_property` — if the mower acks the change with a fresh s2.51 push within a few seconds, the entity's optimistic update is confirmed; if no ack, the entity reverts (BT-only on g2408 is a real possibility for this path).

Per spec §3 cross-cutting commitments: every disk read/write goes through `hass.async_add_executor_job`; the typed domain layer (`mower/`) stays HA-import-free; the property mapping table is the single source of truth.

**Tech Stack:** Same as F1–F3.

**Spec:** `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md` § 5.3 + § 5.4 + § 7 phase F4.

**Working dir:** `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`. Use `git -C <path>` and absolute paths; one-shot `cd` in a single Bash invocation is OK. **Do NOT push from implementer subagents** — controller pushes after each commit.

**Reference repo:** legacy at `/data/claude/homeassistant/ha-dreame-a2-mower/`.

---

## File map

```
custom_components/dreame_a2_mower/
├── coordinator.py               # F4.3, F4.5, F4.6: s2.51 dispatch + write helpers
├── cloud_client.py              # F4.5: setCFG, setPRE write methods
├── const.py                     # F4.12: extend PLATFORMS with number, switch, time
├── mower/
│   └── state.py                 # F4.1: ~30 new fields for settings
├── number.py                    # F4.7: NEW — numeric settings (mowing_height, etc.)
├── switch.py                    # F4.8: NEW — boolean settings (child_lock, dnd, etc.)
├── select.py                    # F4.9: extend with enum settings (mowing_efficiency, etc.)
├── time.py                      # F4.10: NEW — schedule slot entries (display-only)
└── sensor.py                    # F4.9: append read-only sensors for settings
                                 #         we can decode but can't yet write

protocol/
├── (no changes)                 # F1.1 lifted everything we need
```

---

## Phase F4.1 — Extend MowerState with settings fields

### Task F4.1.1: Add ~30 settings fields

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `tests/mower/test_state.py`
- Modify: `docs/data-policy.md`

The settings fields all default to `None` (no observation yet). Persistence is **persistent** for all of them — settings change rarely, and "last known across HA boot" is the right policy.

Field list (CFG-derived first, then s2.51-derived):

**CFG-derived:**
- `child_lock_enabled: bool | None` (CFG.CLS)
- `volume_pct: int | None` (CFG.VOL — 0..100)
- `language_code: str | None` (CFG.LANG)
- `pre_mowing_height_mm: int | None` (CFG.PRE[2] — also pushed via s6.2[0])
- `pre_mowing_efficiency: int | None` (CFG.PRE[1] — also pushed via s6.2[1])
- `pre_edgemaster: bool | None` (CFG.PRE[8] / element-name TBD per legacy)
- `pre_zone_id: int | None` (CFG.PRE[0])
- (other PRE elements per spec §5.3 — read legacy `set_pre` / `get_cfg` for the array shape)

**s2.51-derived (decode-ready, write path may or may not work):**
- `rain_protection_enabled: bool | None` (Setting.RAIN_PROTECTION)
- `rain_protection_resume_hours: int | None` (sub-field of RAIN_PROTECTION)
- `low_speed_at_night_enabled: bool | None` (Setting.LOW_SPEED_NIGHT)
- `anti_theft_enabled: bool | None` (Setting.ANTI_THEFT)
- `dnd_enabled: bool | None` (Setting.DND or CFG.DND — pick one source)
- `dnd_start_time: str | None` (HH:MM string, from CFG.DND or s2.51)
- `dnd_end_time: str | None`
- `auto_recharge_battery_pct: int | None` (Setting.CHARGING — auto-recharge threshold)
- `resume_battery_pct: int | None` (Setting.CHARGING — resume threshold)
- `led_period_enabled: bool | None` (Setting.LED_PERIOD)
- `led_in_standby: bool | None`
- `led_in_working: bool | None`
- `led_in_charging: bool | None`
- `led_in_error: bool | None`
- `human_presence_alert_enabled: bool | None` (Setting.HUMAN_PRESENCE_ALERT)
- `language_setting: str | None` (Setting.LANGUAGE — alternate to CFG.LANG)
- `last_settings_change_unix: int | None` (Setting.TIMESTAMP — observability hook)

Plus a few F3-deferred items that F4 picks up:
- `frost_protection_enabled: bool | None` — if it has a CFG key or s2.51 setting; if not, defer to a future research task
- `pathway_obstacle_avoidance_enabled: bool | None` — same caveat
- `start_from_stop_point_enabled: bool | None`
- `stop_point_term_days: int | None` (1..7)
- `auto_recharge_after_standby_enabled: bool | None`
- `capture_obstacle_photos_enabled: bool | None`

The exact set depends on what's actually decodable from s2.51 and CFG on g2408. **Read** `protocol/config_s2p51.py` and the legacy `dreame/device.py` for the actual settings the mower exposes. If a field is in spec §5.4 but has no decoder/source, mark it as F4-deferred or omit (don't add a field with no source).

- [ ] **Step 1: Inspect protocol/config_s2p51.py for the Setting enum**

```bash
sed -n '23,200p' /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/config_s2p51.py
```

Note every Setting value + the sub-field structure (some Settings carry a single bool, some a 4-element list, some a sub-int). Build the MowerState field list to match what the decoder actually produces.

- [ ] **Step 2: Append failing tests to test_state.py**

```python
def test_settings_fields_default_to_none():
    """All F4 settings fields default to None on a fresh MowerState."""
    s = MowerState()
    # CFG-derived settings
    assert s.child_lock_enabled is None
    assert s.volume_pct is None
    assert s.language_code is None
    # s2.51-derived settings
    assert s.rain_protection_enabled is None
    assert s.rain_protection_resume_hours is None
    assert s.low_speed_at_night_enabled is None
    assert s.anti_theft_enabled is None
    assert s.dnd_enabled is None
    assert s.dnd_start_time is None
    assert s.dnd_end_time is None
    assert s.auto_recharge_battery_pct is None
    assert s.resume_battery_pct is None
    assert s.led_period_enabled is None
    assert s.human_presence_alert_enabled is None


def test_settings_fields_assignable():
    """All F4 settings fields accept keyword construction."""
    s = MowerState(
        child_lock_enabled=True,
        volume_pct=75,
        rain_protection_enabled=True,
        rain_protection_resume_hours=3,
        dnd_enabled=False,
        auto_recharge_battery_pct=15,
        resume_battery_pct=95,
    )
    assert s.child_lock_enabled is True
    assert s.volume_pct == 75
    assert s.rain_protection_enabled is True
    assert s.auto_recharge_battery_pct == 15
```

- [ ] **Step 3: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: 2 new tests fail (AttributeError on `child_lock_enabled` etc.).

- [ ] **Step 4: Append fields to MowerState**

In `custom_components/dreame_a2_mower/mower/state.py`, after the F3 block, append the field list above. Each field:
- Defaults to `None`
- Has a one-line docstring citing the source (CFG.X / s2.51 Setting.Y)
- Persistence: persistent

Group them by source for readability:

```python
    # ------ F4 fields: CFG-derived settings ------

    # Source: CFG.CLS (confirmed). Persistence: persistent.
    child_lock_enabled: bool | None = None

    # Source: CFG.VOL (confirmed, 0..100%). Persistence: persistent.
    volume_pct: int | None = None

    # ... (and so on for all CFG-derived fields) ...

    # ------ F4 fields: s2.51-derived settings ------

    # Source: s2.51 Setting.RAIN_PROTECTION (confirmed). Persistence: persistent.
    rain_protection_enabled: bool | None = None
    rain_protection_resume_hours: int | None = None

    # ... (and so on) ...
```

The exact field list depends on what the decoder produces. If a spec-listed setting has no decoder support (e.g., "Frost Protection" if neither CFG nor s2.51 carries it), omit it from F4 and note in the commit message.

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6: Update data-policy.md**

Append the new fields under "Persistent fields" with their source citation.

- [ ] **Step 7: Commit (do NOT push)**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/state.py tests/mower/test_state.py docs/data-policy.md
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F4.1.1: extend MowerState with settings fields

Adds ~25 settings fields covering the Dreame app's General Mode +
More Settings surface (per spec §5.3, §5.4):

  - CFG-derived: child_lock_enabled, volume_pct, language_code,
    pre_* (PRE array elements)
  - s2.51-derived: rain_protection_enabled / resume_hours,
    low_speed_at_night_enabled, anti_theft_enabled, dnd_*,
    auto_recharge_battery_pct, resume_battery_pct, led_*,
    human_presence_alert_enabled, last_settings_change_unix

All persistent (settings change rarely; last-known across HA boot
is the right policy). Each field cites its CFG key or s2.51 Setting
enum value per spec §8.

Settings without a confirmed decoder source on g2408 (e.g., Frost
Protection, Pathway Obstacle Avoidance) are omitted from F4 and
deferred to a future research task.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F4.2 — Wire s2.51 + s6.2 multi-field updates in coordinator

### Task F4.2.1: s2.51 blob dispatch + field application

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `tests/integration/test_coordinator.py`

The s2.51 push comes through `apply_property_to_state` already (F2.2 added the property mapping entry). What's missing: the actual decode-and-apply step. F4 wires this.

- [ ] **Step 1: Add `_apply_s2p51_settings` helper to coordinator.py**

The handler decodes the s2.51 payload via `protocol.config_s2p51.decode_s2p51`, gets back an `S2P51Event(setting, ...)`, and dispatches by `event.setting` to update the right MowerState fields:

```python
# Imports at the top
from protocol import config_s2p51 as _s2p51

# Below _apply_s1p1_heartbeat:

def _apply_s2p51_settings(state: MowerState, value: Any) -> MowerState:
    """Decode the s2.51 multiplexed-config payload and update MowerState."""
    if not isinstance(value, dict):
        # s2.51 occasionally arrives as something else (empty, list-shaped). Skip.
        return state
    try:
        event = _s2p51.decode_s2p51(value)
    except _s2p51.S2P51DecodeError as ex:
        LOGGER.warning("%s s2.51 decode failed: %s — payload=%r",
                       LOG_NOVEL_PROPERTY, ex, value)
        return state
    setting = event.setting
    # Dispatch by setting. The exact field-extraction depends on what
    # S2P51Event exposes — read protocol/config_s2p51.py to see the
    # event's attributes for each Setting variant. The pattern below
    # is illustrative; adapt to actual attribute names.
    if setting == _s2p51.Setting.RAIN_PROTECTION:
        return dataclasses.replace(
            state,
            rain_protection_enabled=getattr(event, "enabled", None),
            rain_protection_resume_hours=getattr(event, "resume_hours", None),
        )
    if setting == _s2p51.Setting.LOW_SPEED_NIGHT:
        return dataclasses.replace(
            state,
            low_speed_at_night_enabled=getattr(event, "enabled", None),
        )
    if setting == _s2p51.Setting.ANTI_THEFT:
        return dataclasses.replace(
            state,
            anti_theft_enabled=getattr(event, "enabled", None),
        )
    if setting == _s2p51.Setting.DND:
        return dataclasses.replace(
            state,
            dnd_enabled=getattr(event, "enabled", None),
            dnd_start_time=getattr(event, "start_time", None),
            dnd_end_time=getattr(event, "end_time", None),
        )
    if setting == _s2p51.Setting.CHARGING:
        return dataclasses.replace(
            state,
            auto_recharge_battery_pct=getattr(event, "auto_recharge_pct", None),
            resume_battery_pct=getattr(event, "resume_pct", None),
        )
    if setting == _s2p51.Setting.LED_PERIOD:
        return dataclasses.replace(
            state,
            led_period_enabled=getattr(event, "enabled", None),
            led_in_standby=getattr(event, "in_standby", None),
            led_in_working=getattr(event, "in_working", None),
            led_in_charging=getattr(event, "in_charging", None),
            led_in_error=getattr(event, "in_error", None),
        )
    if setting == _s2p51.Setting.HUMAN_PRESENCE_ALERT:
        return dataclasses.replace(
            state,
            human_presence_alert_enabled=getattr(event, "enabled", None),
        )
    # AMBIGUOUS_TOGGLE / AMBIGUOUS_4LIST / TIMESTAMP / LANGUAGE etc. —
    # observed-but-not-yet-mapped; just log at DEBUG and skip.
    LOGGER.debug("s2.51 unmapped setting=%s event=%r", setting, event)
    return state
```

- [ ] **Step 2: Wire in `apply_property_to_state`**

Add the dispatch above the existing scalar mapping:

```python
# In apply_property_to_state, blob-handler section:
if (siid, piid) == (1, 4):
    return _apply_s1p4_telemetry(state, value)
if (siid, piid) == (1, 1):
    return _apply_s1p1_heartbeat(state, value)
if (siid, piid) == (2, 51):  # NEW
    return _apply_s2p51_settings(state, value)
```

- [ ] **Step 3: Add tests**

In `tests/integration/test_coordinator.py`, add cases that feed synthetic s2.51 payloads through `apply_property_to_state` and assert the right MowerState fields update. Read `tests/protocol/test_config_s2p51.py` for known-good test payloads — the integration's tests can re-use those.

```python
def test_s2p51_rain_protection_updates_state():
    state = MowerState()
    # Use a known-good rain-protection payload from protocol/test_config_s2p51.py
    payload = {...}  # READ tests/protocol/test_config_s2p51.py for the exact shape
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.rain_protection_enabled is True
    # ... etc.

def test_s2p51_charging_updates_battery_thresholds():
    # ... similar for Setting.CHARGING ...

def test_s2p51_invalid_payload_drops_silently():
    state = MowerState(rain_protection_enabled=True)
    new_state = apply_property_to_state(state, siid=2, piid=51, value="not-a-dict")
    assert new_state == state  # unchanged
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/integration/test_coordinator.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F4.2.1: wire s2.51 multiplexed-config decoder into coordinator

apply_property_to_state now dispatches (2, 51) through
protocol.config_s2p51.decode_s2p51, then maps the resulting
S2P51Event.setting to the right MowerState fields.

Each Setting variant updates the relevant fields (RAIN_PROTECTION
→ rain_protection_*; CHARGING → auto_recharge_battery_pct +
resume_battery_pct; LED_PERIOD → led_*; etc.). Unmapped settings
(AMBIGUOUS_TOGGLE, TIMESTAMP) log at DEBUG and skip.

Decoder errors and non-dict payloads are dropped with a
[NOVEL/property] warning, leaving state unchanged.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F4.2.2: s6.2 element extraction (mowing height/efficiency/edgemaster)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/property_mapping.py`
- Modify: `tests/mower/test_property_mapping.py`

The s6.2 push is `[mowing_height_mm, mow_mode, edgemaster, ?]`. Currently the property mapping has no entry for s6.2. Add an entry that uses the `multi_field` mechanism (added in F2.2.1) to extract elements.

- [ ] **Step 1: Add tests**

```python
def test_s6p2_extracts_mowing_height_efficiency_edgemaster():
    """s6.2 = [height_mm, mow_mode, edgemaster, ?] updates 3 fields."""
    entry = PROPERTY_MAPPING[(6, 2)]
    assert entry.multi_field is not None
    # Test the extractors directly
    extractors = dict(entry.multi_field)
    assert extractors["pre_mowing_height_mm"]([60, 0, True, 2]) == 60
    assert extractors["pre_mowing_efficiency"]([60, 1, True, 2]) == 1
    assert extractors["pre_edgemaster"]([60, 0, True, 2]) is True
    # Default behavior on too-short list
    assert extractors["pre_mowing_height_mm"]([60]) == 60
    assert extractors["pre_mowing_efficiency"]([60]) is None
```

- [ ] **Step 2: Add s6.2 entry**

```python
# In PROPERTY_MAPPING:
(6, 2): PropertyMappingEntry(
    multi_field=(
        ("pre_mowing_height_mm",
         lambda v: int(v[0]) if isinstance(v, list) and len(v) >= 1 else None),
        ("pre_mowing_efficiency",
         lambda v: int(v[1]) if isinstance(v, list) and len(v) >= 2 else None),
        ("pre_edgemaster",
         lambda v: bool(v[2]) if isinstance(v, list) and len(v) >= 3 else None),
    ),
),
```

- [ ] **Step 3: Verify multi_field path is wired**

The coordinator's `apply_property_to_state` already supports multi_field (F2.2.1 set this up). Confirm the s6.2 push will route correctly:

Read the relevant section of coordinator.py to confirm — if multi_field is checked AFTER the blob-handler shortcut for (1, 4) etc., that's fine; s6.2 isn't a blob.

If multi_field handling is missing, add it. The pattern:

```python
# In apply_property_to_state, after the blob-handler dispatch:
entry = PROPERTY_MAPPING.get((siid, piid))
if entry is not None and entry.multi_field is not None:
    updates = {}
    for field_name, extract_fn in entry.multi_field:
        try:
            updates[field_name] = extract_fn(value)
        except (TypeError, ValueError) as ex:
            LOGGER.debug("multi_field extract %s failed: %s", field_name, ex)
    return dataclasses.replace(state, **updates)
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_property_mapping.py tests/integration/test_coordinator.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/property_mapping.py tests/mower/test_property_mapping.py custom_components/dreame_a2_mower/coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F4.2.2: s6.2 multi-field extraction (mowing height + efficiency + edgemaster)

Adds (6, 2) to PROPERTY_MAPPING with three extractors:
  - pre_mowing_height_mm = element[0] (mm; range 30..70 in 5mm steps)
  - pre_mowing_efficiency = element[1] (0=Standard, 1=Efficient)
  - pre_edgemaster = element[2] (bool)

Element[3] is observed-constant=2 in 25 captures and not yet
characterised — left undecoded.

Confirms the multi_field dispatch path in apply_property_to_state
(set up in F2.2.1).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F4.3 — CFG fetcher extension

### Task F4.3.1: Extend coordinator._refresh_cfg to extract more settings

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

F2.4.1 wired the CFG fetcher to populate `blades_life_pct` + `side_brush_life_pct`. F4 extends the same code path to extract the rest of the CFG keys: `CLS` (child lock), `VOL` (volume), `LANG` (language), `DND` (do-not-disturb config), `PRE` (10-element preferences array).

- [ ] **Step 1: Read the existing _refresh_cfg**

```bash
grep -nA 50 "async def _refresh_cfg" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/coordinator.py
```

- [ ] **Step 2: Extend the field-extraction**

Update `_refresh_cfg` to extract more CFG fields. The `cfg` dict returned by `get_cfg(send_action)` has top-level keys per protocol-doc §6.2. Read protocol/cfg_action.py to confirm the exact shape:

```bash
sed -n '60,80p' /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/cfg_action.py
```

Then add field extraction:

```python
# In _refresh_cfg, after the existing blade/side-brush extraction:
child_lock = cfg.get("CLS")
volume = cfg.get("VOL")
language = cfg.get("LANG")
dnd_cfg = cfg.get("DND") or {}  # nested {enabled, start, end}
pre_array = cfg.get("PRE") or []

new_state_fields = dict(blades_life_pct=..., ...)  # existing fields
new_state_fields.update(
    child_lock_enabled=bool(child_lock) if child_lock is not None else None,
    volume_pct=int(volume) if volume is not None else None,
    language_code=str(language) if language else None,
    dnd_enabled=bool(dnd_cfg.get("enabled")) if dnd_cfg else None,
    dnd_start_time=dnd_cfg.get("start"),
    dnd_end_time=dnd_cfg.get("end"),
    pre_zone_id=int(pre_array[0]) if len(pre_array) >= 1 else None,
    pre_mowing_efficiency=int(pre_array[1]) if len(pre_array) >= 2 else None,
    pre_mowing_height_mm=int(pre_array[2]) if len(pre_array) >= 3 else None,
    # ... other PRE elements ...
    pre_edgemaster=bool(pre_array[8]) if len(pre_array) >= 9 else None,
)
```

The exact PRE element-to-field mapping per protocol-doc §6.2:
- PRE[0] = zone_id
- PRE[1] = mode (0=Standard, 1=Efficient)
- PRE[2] = height_mm
- PRE[3] = obstacle_mm
- PRE[4] = coverage%
- PRE[5] = direction_change
- PRE[6] = adaptive
- PRE[7] = ?
- PRE[8] = edge_detection (edgemaster)
- PRE[9] = auto_edge

Map only the elements we have MowerState fields for. The others can be ignored or added later.

- [ ] **Step 3: Smoke-test compile**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True); print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F4.3.1: extend _refresh_cfg to populate child_lock/volume/lang/DND/PRE

CFG fetch now extracts:
  - CLS → child_lock_enabled
  - VOL → volume_pct
  - LANG → language_code
  - DND → dnd_enabled / dnd_start_time / dnd_end_time
  - PRE[0..9] → pre_zone_id / pre_mowing_efficiency /
    pre_mowing_height_mm / ... / pre_edgemaster

PRE elements 3..7 + 9 mapped only when MowerState fields exist
(spec §5.3 — F4 covers the user-actionable subset; remaining
PRE elements deferred).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F4.4 — Cloud client write helpers

### Task F4.4.1: setCFG, setPRE, set_property write methods

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py`

Add three write methods:

1. `set_cfg(t: str, value: Any) -> bool` — single-key CFG setter (e.g., `set_cfg("CLS", True)` toggles child lock)
2. `set_pre(pre_array: list) -> bool` — write the 10-element PRE array. May delegate to `protocol.cfg_action.set_pre` (already exists per the legacy lift).
3. `set_property(siid: int, piid: int, value: Any) -> bool` — for s2.51 writes via the property-set RPC (return True on success, False on 80001 / failure)

- [ ] **Step 1: Read existing helpers**

```bash
grep -nE "^    def |action\b|sendCommand|set_pre|setCFG|set_property" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/cloud_client.py | head -30
sed -n '160,220p' /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/cfg_action.py
```

The cloud_client already has a generic `action()` method (used for routed_action in F3.5.2). It probably also has a `set_property()` (lifted from legacy `dreame/protocol.py`); check.

- [ ] **Step 2: Add `set_cfg` method**

The setCFG path uses routed-action `s2 aiid=50` with `{m:'s', t:t, d:value}` (the 's' = set variant of the 'g' = get variant used by get_cfg).

```python
def set_cfg(self, key: str, value: Any) -> bool:
    """Write a CFG key via routed-action s2 aiid=50.

    Returns True on success, False on cloud failure.
    Source: protocol-doc §6.2 + legacy device.py:set_cfg pattern.
    """
    payload = {"m": "s", "t": key, "d": value}
    try:
        result = self.action(siid=2, aiid=50, parameters=payload)
        return bool(result and result.get("code") == 0)
    except Exception as ex:
        LOGGER.warning("set_cfg %s=%r failed: %s", key, value, ex)
        return False
```

- [ ] **Step 3: Add `set_pre` method**

```python
def set_pre(self, pre_array: list) -> bool:
    """Write the 10-element PRE preferences array.

    Delegates to protocol.cfg_action.set_pre which constructs the
    routed-action envelope. Per protocol-doc §6.2, PRE writes
    succeed on g2408.
    """
    from protocol import cfg_action
    try:
        result = cfg_action.set_pre(self.action, pre_array)
        return bool(result is not None)
    except Exception as ex:
        LOGGER.warning("set_pre failed: %s", ex)
        return False
```

- [ ] **Step 4: Confirm `set_property` exists or add it**

If the cloud_client already has a `set_property(siid, piid, value)` method (likely from the legacy lift), good. If not, add it — patterned on `action()`. The s2.51 write path uses this:

```python
def set_property(self, siid: int, piid: int, value: Any) -> bool:
    """Write a property via the cloud's set_properties RPC.

    Returns False on 80001 (g2408's typical failure for set_properties
    — but s2.51 writes may go via a different path that works).
    """
    # Implementation: post to /sendCommand with method=set_properties
    # and the right params shape. Look at legacy dreame/protocol.py for
    # the exact wire format.
    ...
```

If the legacy code's set_property pattern is hard to extract, mark this method as **deferred to F4 followup** — F4 ships with set_cfg + set_pre as the only writable paths, and s2.51 writes are an open question.

- [ ] **Step 5: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/cloud_client.py', doraise=True); print('ok')"
```

- [ ] **Step 6: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/cloud_client.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F4.4.1: cloud_client write helpers — set_cfg, set_pre, set_property

Adds three settings-write entry points:

  - set_cfg(key, value): single-key CFG writes via routed-action
    s2 aiid=50 with {m:'s', t:key, d:value}. Returns True on
    cloud success.
  - set_pre(pre_array): writes the 10-element PRE preferences via
    protocol.cfg_action.set_pre (already lifted from legacy).
  - set_property(siid, piid, value): generic property-set for the
    s2.51 write path. Returns False on 80001 (the typical g2408
    failure mode for direct set_properties).

These are the wire-level surfaces. Coordinator.write_setting
(F4.5.1) provides the typed, MowerState-aware façade.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F4.5 — Coordinator settings write helper

### Task F4.5.1: coordinator.write_setting

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

A typed entry point for entity write handlers. Takes a setting name and a new value, dispatches to the right cloud_client method, optimistically updates MowerState, then waits for the mower's confirming push before committing (or reverts).

- [ ] **Step 1: Add write_setting method**

```python
async def write_setting(self, setting_name: str, new_value: Any) -> bool:
    """Write a setting to the mower.

    Dispatch by setting_name to the right cloud_client write helper:
      - CFG-resident keys (CLS, VOL, ...) → cloud_client.set_cfg
      - PRE array elements → cloud_client.set_pre (full array write)
      - s2.51 settings → cloud_client.set_property(2, 51, encoded)

    Optimistically updates MowerState immediately so the entity
    reflects the change. If the cloud write returns False, reverts
    the optimistic update and logs WARNING.

    Returns True on success, False on failure.
    """
    if self._cloud is None:
        return False

    # Snapshot current state for revert
    prior_state = self.data

    # Optimistic update — replace the matching field on a new MowerState
    field_name = self._setting_name_to_field(setting_name)
    if field_name is None:
        LOGGER.warning("write_setting: unknown setting %r", setting_name)
        return False
    new_state = dataclasses.replace(self.data, **{field_name: new_value})
    self.async_set_updated_data(new_state)

    # Dispatch the cloud write
    success = await self._dispatch_setting_write(setting_name, new_value)
    if not success:
        LOGGER.warning(
            "write_setting %s=%r: cloud write failed; reverting optimistic update",
            setting_name, new_value,
        )
        self.async_set_updated_data(prior_state)
    return success


def _setting_name_to_field(self, setting_name: str) -> str | None:
    """Map a setting key to the MowerState field name."""
    # Single source of truth for setting → field mapping
    return {
        "CLS": "child_lock_enabled",
        "VOL": "volume_pct",
        "LANG": "language_code",
        "rain_protection": "rain_protection_enabled",
        # ... etc.
    }.get(setting_name)


async def _dispatch_setting_write(self, setting_name: str, new_value: Any) -> bool:
    """Invoke the right cloud_client write method for the setting."""
    if setting_name in ("CLS", "VOL", "LANG"):
        return await self.hass.async_add_executor_job(
            self._cloud.set_cfg, setting_name, new_value
        )
    # PRE array writes are full-array; call sites need to pass the entire array
    # (not a single element). For F4 we keep PRE writes coarse-grained.
    if setting_name == "PRE":
        return await self.hass.async_add_executor_job(
            self._cloud.set_pre, new_value
        )
    # s2.51 writes — use protocol.config_s2p51.encode_s2p51 if applicable
    # (F4 does not yet wire s2.51 writes; entities for s2.51 settings are
    # read-only until this path is validated).
    LOGGER.warning("_dispatch_setting_write: unsupported setting %r", setting_name)
    return False
```

The dispatch table is intentionally minimal in F4 — only CFG single-key writes + PRE array writes. s2.51 writes are deferred.

- [ ] **Step 2: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True); print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F4.5.1: coordinator.write_setting — typed write entry point

Maps setting keys (CLS, VOL, LANG, PRE) to MowerState field names
and dispatches to cloud_client write helpers. Optimistically updates
state; reverts on cloud failure.

F4 supports CFG single-key writes (CLS, VOL, LANG) and PRE-array
writes only. s2.51 writes are deferred — entities for s2.51 settings
are read-only in F4 until the write path is validated against a
live mower.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F4.6 — Entity files

This is where the user actually sees results. Four entity-file tasks. For each, the implementer reads the spec §5.3/§5.4 list, picks the entries that have MowerState fields available, and adds entity descriptors.

### Task F4.6.1: number.py — settable numeric settings

**Files:**
- Create: `custom_components/dreame_a2_mower/number.py`

Settable numbers (write_fn calls coordinator.write_setting):

| Entity | Field | Range | Setting key |
|---|---|---|---|
| `number.mowing_height_cm` | `pre_mowing_height_mm / 10` | 3.0–7.0 step 0.5 | PRE[2] write — coarse, requires full-array setPRE |
| `number.volume` | `volume_pct` | 0..100 | CFG.VOL |
| `number.auto_recharge_battery_pct` | `auto_recharge_battery_pct` | 10..25 step 5 | s2.51 (read-only F4) |
| `number.resume_battery_pct` | `resume_battery_pct` | 80..100 step 5 | s2.51 (read-only F4) |
| `number.stop_point_term_days` | `stop_point_term_days` | 1..7 | (TBD where this lives) |

Read-only number entities (no write path yet):
- The above four where the write path is s2.51 (auto_recharge_battery_pct, resume_battery_pct) → keep as `entity_category=DIAGNOSTIC` and don't expose a write — or use HA's `mode="box"` and have the write_fn log "not yet wired" + revert. Choose explicit "read-only" by NOT defining `async_set_native_value`.

Pattern:

```python
"""Number platform — settable numeric settings."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
# ... usual imports per the F1/F2 entity pattern ...

@dataclass(frozen=True, kw_only=True)
class DreameA2NumberEntityDescription(NumberEntityDescription):
    value_fn: Callable[[MowerState], float | int | None]
    write_setting: str | None = None  # if set, the setting key for coordinator.write_setting
    write_value_fn: Callable[[float], Any] | None = None  # transform UI float → wire value


NUMBERS: tuple[DreameA2NumberEntityDescription, ...] = (
    DreameA2NumberEntityDescription(
        key="volume",
        name="Voice volume",
        native_min_value=0,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.volume_pct,
        write_setting="VOL",
        write_value_fn=lambda v: int(v),
    ),
    # ... more ...
)


class DreameA2Number(CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity):
    entity_description: DreameA2NumberEntityDescription

    def __init__(self, coordinator, description):
        # standard pattern — see lawn_mower.py / sensor.py for the boilerplate
        ...

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.write_setting is None:
            LOGGER.warning("set_native_value: no write_setting on %s",
                           self.entity_description.key)
            return
        wire_value = (
            self.entity_description.write_value_fn(value)
            if self.entity_description.write_value_fn
            else value
        )
        await self.coordinator.write_setting(
            self.entity_description.write_setting, wire_value
        )
```

Read-only number entities omit `write_setting` — `async_set_native_value` becomes the no-op above.

- [ ] **Step 1**: Write number.py with the entity descriptors. Aim for 4-5 entities (VOL, PRE-derived height, possibly more).
- [ ] **Step 2**: Smoke-test compile.
- [ ] **Step 3**: Commit.

(Detailed code matches the F1.5.2 sensor.py pattern; see that file for the full structure.)

### Task F4.6.2: switch.py — settable boolean settings

**Files:**
- Create: `custom_components/dreame_a2_mower/switch.py`

Same pattern. Settable switches:
- `switch.child_lock` → CFG.CLS (write works)
- `switch.dnd` → CFG.DND.enabled (write works)
- (others where the write path is confirmed)

Read-only switches (s2.51-derived, F4 reads-only):
- `switch.rain_protection` (s2.51 RAIN_PROTECTION)
- `switch.low_speed_at_night`
- `switch.anti_theft`
- `switch.led_period`, `led_in_standby`, `led_in_working`, `led_in_charging`, `led_in_error`
- `switch.human_presence_alert`

For read-only switches, omit `write_setting`; `async_turn_on` / `async_turn_off` log a "not yet wired" warning and no-op.

- [ ] **Step 1**: Write switch.py.
- [ ] **Step 2**: Smoke-test.
- [ ] **Step 3**: Commit.

### Task F4.6.3: select.py extension — enum settings

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py`

The existing `DreameA2ActionModeSelect` from F3.2.1 stays. Add a generic `DreameA2SettingSelect` and descriptors for:
- `select.mowing_efficiency` (Standard/Efficient — PRE[1])
- `select.language` (CFG.LANG — read-only F4 unless legacy confirms LANG write)
- `select.rain_protection_resume_hours` (read-only F4)

Pattern matches the action_mode select but reads/writes a different field.

- [ ] **Step 1**: Extend select.py with a generic settings-select class + descriptors.
- [ ] **Step 2**: Smoke-test.
- [ ] **Step 3**: Commit.

### Task F4.6.4: time.py — schedule slot entries (display-only)

**Files:**
- Create: `custom_components/dreame_a2_mower/time.py`

Schedule editing on g2408 is BT-only per protocol-doc §1.1. F4 ships display-only `time.dnd_start_time` + `time.dnd_end_time` so the dashboard can show the user's schedule without claiming to edit it.

- [ ] **Step 1**: Write time.py with two read-only TimeEntity instances backed by `state.dnd_start_time` / `state.dnd_end_time` (parsed as `time` objects).
- [ ] **Step 2**: Smoke-test.
- [ ] **Step 3**: Commit.

### Task F4.6.5: sensor.py — read-only sensors for s2.51 settings

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

For each s2.51-derived setting that DOESN'T have a write path in F4, add a read-only sensor. Examples:
- `sensor.rain_protection_status` → "On (resume in 3h)" / "Off"
- `sensor.low_speed_at_night` → "Active" / "Inactive"
- `sensor.led_status` → "Standby on, working on, charging on, error off"

Diagnostic-tier (`entity_category=DIAGNOSTIC`).

- [ ] **Step 1**: Extend SENSORS with the read-only setting sensors.
- [ ] **Step 2**: Smoke-test.
- [ ] **Step 3**: Commit.

---

## Phase F4.7 — LOCK_BOT_TOGGLE wiring

### Task F4.7.1: Wire LOCK_BOT_TOGGLE via property-set

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/actions.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (dispatch_action)

F3.5.1 noted LOCK_BOT_TOGGLE was `local_only=True` because legacy has no action mapping for child-lock — it's a property. F4 wires it via `set_cfg("CLS", new_value)`:

- [ ] **Step 1**: In actions.py, change LOCK_BOT_TOGGLE from `local_only=True` to a marker indicating "use coordinator.write_setting('CLS', ...)". Add a `cfg_key` slot to ActionEntry.
- [ ] **Step 2**: In coordinator.dispatch_action, handle the cfg_key case before the routed_o case.
- [ ] **Step 3**: The service handler in services.py for `lock_bot` works as-is (calls dispatch_action with empty params; the dispatcher reads coordinator.data.child_lock_enabled to decide which value to set).

Concrete: `lock_bot` toggles by reading current `child_lock_enabled` and writing `not (child_lock_enabled or False)`.

- [ ] **Step 4**: Commit.

---

## Phase F4.8 — Wire-in + final sweep + tag

### Task F4.8.1: Update PLATFORMS + final sweep + tag v0.4.0a0

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`

Add `number`, `switch`, `time` to PLATFORMS (now 9 entries: lawn_mower, sensor, binary_sensor, device_tracker, camera, select, number, switch, time).

- [ ] **Step 1**: Edit const.py.
- [ ] **Step 2**: Run final pytest sweep.
- [ ] **Step 3**: Smoke-compile every Python file in custom_components/.
- [ ] **Step 4**: Commit + tag v0.4.0a0.

(Use the same pattern as F1.6, F2.9, F3.7.)

---

## Self-review checklist

- [ ] All MowerState settings fields default to None.
- [ ] data-policy.md is up to date.
- [ ] s2.51 dispatch in coordinator handles every Setting variant or logs DEBUG for unmapped.
- [ ] s6.2 multi_field extracts mowing_height/efficiency/edgemaster.
- [ ] CFG fetch populates child_lock/volume/lang/DND/PRE.
- [ ] cloud_client.set_cfg + set_pre exist and return bool.
- [ ] coordinator.write_setting dispatches CFG keys + PRE; rejects unsupported settings.
- [ ] number, switch, select extensions, time, sensor extensions all compile.
- [ ] Settable entities have functional write handlers; read-only entities log a warning and no-op.
- [ ] No `homeassistant.*` imports in `protocol/` or `mower/`.
- [ ] LOCK_BOT_TOGGLE is no longer local_only — wired via set_cfg("CLS", ...).
- [ ] PLATFORMS has 9 entries.
- [ ] pytest sweep is green.
- [ ] v0.4.0a0 tag created.

## What this plan does NOT do

Out-of-scope for F4:
- s2.51 write path validation (entities for s2.51 settings stay read-only until the write is proven)
- Schedule edit (BT-only on g2408 per protocol-doc — F4 ships display-only)
- Settings the spec lists but the protocol research doesn't yet support (Frost Protection, Pathway Obstacle Avoidance, etc.) — added when/if a CFG/s2.51 source is found
- F5: session lifecycle (live trail, finalize, archive)
- F6: observability layer
- F7: LiDAR + dashboard polish + cutover
