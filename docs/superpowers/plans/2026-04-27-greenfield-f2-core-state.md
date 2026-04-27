# Greenfield F2 — Core State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface every §2.1-confirmed mower property as a Home Assistant entity. After F2 the dashboard shows position (3 coordinate frames), area mowed, distance, mowing phase, error code, WiFi RSSI, total lawn area, blade/side-brush life, GPS device-tracker, plus binary sensors for rain protection / positioning failed / battery temp low / obstacle detected / mowing session active. Live map camera renders a static base map (no trail yet — that's F5).

**Architecture:** Extends F1's three-layer stack with no new architectural decisions. `MowerState` grows ~25 fields. The coordinator's `apply_property_to_state` gains a blob-handler dispatch path so that one (siid, piid) push can update multiple fields when the value is a structured blob (s1.4 telemetry, s1.1 heartbeat). Two periodic refresh tasks added (CFG every 10 min, LOCN every 60 s) — both via `hass.async_add_executor_job` per spec §3.

**Tech Stack:** Same as F1. Pillow for the base-map PNG renderer.

**Spec:** `docs/superpowers/specs/2026-04-27-greenfield-integration-design.md` § 7 phase F2.

**Working dir:** `/data/claude/homeassistant/ha-dreame-a2-mower-v2/`. Use `git -C <path>` and absolute paths; one-shot `cd` in a single Bash invocation is OK. **Do NOT push from implementer subagents** — controller pushes after each commit.

**Reference repo:** legacy at `/data/claude/homeassistant/ha-dreame-a2-mower/` is the lift-on-demand source. Read but don't modify.

---

## File map

```
custom_components/dreame_a2_mower/
├── __init__.py                    # F2.9.1: extend PLATFORMS list
├── coordinator.py                 # F2.3, F2.4: blob dispatch + CFG/LOCN periodics
├── mower/
│   ├── state.py                   # F2.1: new fields
│   ├── property_mapping.py        # F2.2: new entries
│   └── (no new files in F2)
├── binary_sensor.py               # F2.5: new file (5 entities)
├── sensor.py                      # F2.6: extend SENSORS tuple (~20 new)
├── device_tracker.py              # F2.7: new file
├── camera.py                      # F2.8: new file
└── (no other layer-3 files added)

protocol/                          # NO changes — F1 lift is complete
mower/                             # F2.1 state extension only

tests/
├── mower/
│   ├── test_state.py              # F2.1: new test cases
│   └── test_property_mapping.py   # F2.2: new test cases
├── integration/
│   └── test_coordinator.py        # F2.3: blob dispatch tests
└── (no new test directories)

docs/
├── data-policy.md                 # F2.1: persistent vs volatile split
└── lessons-from-legacy.md         # F2.x: as needed
```

---

## Phase F2.1 — Extend MowerState

### Task F2.1.1: Add F2 fields to MowerState

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `tests/mower/test_state.py`
- Modify: `docs/data-policy.md`

The new fields per §2.1:

| Field | Source | Persistence | Notes |
|---|---|---|---|
| `error_code` | s2.2 | volatile | int; describe via `error_codes.describe_error()` |
| `obstacle_flag` | s1.53 | volatile | bool |
| `area_mowed_m2` | s1.4 (decoded) | volatile | float, decimetres in raw |
| `total_distance_m` | s1.4 (decoded) | volatile | float |
| `total_lawn_area_m2` | s2.66 | persistent | float, [0] of the 2-elem list |
| `mowing_phase` | s1.4 (decoded byte[8]) | volatile | int 0..N (raw value, semantics unclear) |
| `position_x_m` | s1.4 (decoded) | persistent | mower-frame x in metres |
| `position_y_m` | s1.4 (decoded) | persistent | mower-frame y in metres |
| `position_north_m` | computed from x,y + station_bearing | persistent | derived |
| `position_east_m` | computed from x,y + station_bearing | persistent | derived |
| `position_lat` | LOCN | persistent | None when sentinel `[-1,-1]` |
| `position_lon` | LOCN | persistent | None when sentinel `[-1,-1]` |
| `wifi_rssi_dbm` | s6.3[1] | volatile | int |
| `cloud_connected` | s6.3[0] | volatile | bool |
| `battery_temp_low` | s1.1 (decoded byte[6] bit) | volatile | bool |
| `slam_task_label` | s2.65 | volatile | string e.g. 'TASK_SLAM_RELOCATE' |
| `task_state_code` | s2.56 | volatile | int 1..5 |
| `blades_life_pct` | CFG.CMS | persistent | float 0..100 |
| `side_brush_life_pct` | CFG.CMS | persistent | float 0..100 |
| `total_cleaning_time_min` | CFG | persistent | int |
| `total_cleaned_area_m2` | CFG | persistent | float |
| `cleaning_count` | CFG | persistent | int |
| `first_cleaning_date` | CFG | persistent | string YYYY-MM-DD |
| `station_bearing_deg` | config_flow option | persistent | float 0..360 |
| `manual_mode` | computed | volatile | bool — F5 wires the 15s-no-s1.4 detector; F2 leaves at False |

24 new fields. Plus updating data-policy.md to list each under persistent or volatile.

- [ ] **Step 1: Append failing tests to test_state.py**

Add these test functions to `tests/mower/test_state.py`:

```python
def test_mower_state_f2_fields_default_to_none():
    """All F2 fields default to None on a fresh MowerState."""
    s = MowerState()
    assert s.error_code is None
    assert s.obstacle_flag is None
    assert s.area_mowed_m2 is None
    assert s.total_distance_m is None
    assert s.total_lawn_area_m2 is None
    assert s.mowing_phase is None
    assert s.position_x_m is None
    assert s.position_y_m is None
    assert s.position_north_m is None
    assert s.position_east_m is None
    assert s.position_lat is None
    assert s.position_lon is None
    assert s.wifi_rssi_dbm is None
    assert s.cloud_connected is None
    assert s.battery_temp_low is None
    assert s.slam_task_label is None
    assert s.task_state_code is None
    assert s.blades_life_pct is None
    assert s.side_brush_life_pct is None
    assert s.total_cleaning_time_min is None
    assert s.total_cleaned_area_m2 is None
    assert s.cleaning_count is None
    assert s.first_cleaning_date is None
    assert s.station_bearing_deg is None
    assert s.manual_mode is None


def test_mower_state_f2_construction_with_all_fields():
    """All F2 fields accept positional/keyword construction."""
    s = MowerState(
        state=State.WORKING,
        battery_level=72,
        charging_status=ChargingStatus.NOT_CHARGING,
        error_code=0,
        obstacle_flag=False,
        area_mowed_m2=12.5,
        total_distance_m=345.0,
        total_lawn_area_m2=378.3,
        mowing_phase=2,
        position_x_m=1.23,
        position_y_m=-4.56,
        position_north_m=1.23,
        position_east_m=-4.56,
        position_lat=59.123,
        position_lon=10.456,
        wifi_rssi_dbm=-65,
        cloud_connected=True,
        battery_temp_low=False,
        slam_task_label="TASK_SLAM_RELOCATE",
        task_state_code=2,
        blades_life_pct=85.0,
        side_brush_life_pct=90.0,
        total_cleaning_time_min=1234,
        total_cleaned_area_m2=5678.0,
        cleaning_count=42,
        first_cleaning_date="2026-04-01",
        station_bearing_deg=45.0,
        manual_mode=False,
    )
    assert s.error_code == 0
    assert s.position_lat == 59.123
    assert s.station_bearing_deg == 45.0
```

- [ ] **Step 2: Run the tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: the two new tests fail with `TypeError` or `AttributeError` because the fields don't exist yet.

- [ ] **Step 3: Extend MowerState with the new fields**

Append the 24 fields to the `MowerState` dataclass in `custom_components/dreame_a2_mower/mower/state.py`. Keep the existing 3 F1 fields intact. Each new field must:
1. Default to `None`
2. Have a one-line comment citing the §2.1 source + persistence policy

The block to add (place after the 3 F1 fields, preserving slots=True):

```python
    # ------ F2 fields ------

    # Source: s2.2 (confirmed, apk fault index). Persistence: volatile.
    error_code: int | None = None

    # Source: s1.53 (confirmed). Persistence: volatile.
    obstacle_flag: bool | None = None

    # Source: s1.4 byte[29-30] decoded (confirmed). Persistence: volatile.
    area_mowed_m2: float | None = None

    # Source: s1.4 byte[24-25] decoded (confirmed). Persistence: volatile.
    total_distance_m: float | None = None

    # Source: s2.66[0] (confirmed). Persistence: persistent (slow-changing).
    total_lawn_area_m2: float | None = None

    # Source: s1.4 byte[8] decoded (confirmed). Persistence: volatile.
    mowing_phase: int | None = None

    # Source: s1.4 byte[1-2] decoded (confirmed). Persistence: persistent.
    position_x_m: float | None = None

    # Source: s1.4 byte[3-4] decoded (confirmed). Persistence: persistent.
    position_y_m: float | None = None

    # Source: computed (x, y rotated by station_bearing_deg). Persistence: persistent.
    position_north_m: float | None = None
    position_east_m: float | None = None

    # Source: LOCN routed action (confirmed). Persistence: persistent.
    # Sentinel [-1, -1] → both None.
    position_lat: float | None = None
    position_lon: float | None = None

    # Source: s6.3[1] (confirmed g2408 overlay). Persistence: volatile.
    wifi_rssi_dbm: int | None = None

    # Source: s6.3[0] (confirmed g2408 overlay). Persistence: volatile.
    cloud_connected: bool | None = None

    # Source: s1.1 byte[6] bit (confirmed heartbeat decode). Persistence: volatile.
    battery_temp_low: bool | None = None

    # Source: s2.65 (confirmed). Persistence: volatile.
    slam_task_label: str | None = None

    # Source: s2.56 (confirmed task-state codes 1..5). Persistence: volatile.
    task_state_code: int | None = None

    # Source: CFG.CMS (confirmed). Persistence: persistent.
    blades_life_pct: float | None = None
    side_brush_life_pct: float | None = None

    # Source: CFG (confirmed). Persistence: persistent.
    total_cleaning_time_min: int | None = None
    total_cleaned_area_m2: float | None = None
    cleaning_count: int | None = None
    first_cleaning_date: str | None = None

    # Source: config_flow option. Persistence: persistent.
    # 0..360 degrees compass — 0 means "station faces north, projection is
    # identity". Used to project position_x_m, position_y_m onto
    # position_north_m, position_east_m.
    station_bearing_deg: float | None = None

    # Source: computed (15s of no s1.4 telemetry while state==MOWING).
    # Persistence: volatile. F5 wires the detector; F2 leaves at None.
    manual_mode: bool | None = None
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_state.py -v 2>&1 | tail -10
```

Expected: 6 passed (4 F1 + 2 F2).

- [ ] **Step 5: Update data-policy.md**

Open `docs/data-policy.md`. Replace the placeholder text in each section with the actual fields:

```markdown
## Persistent fields (RestoreEntity, last-known across HA boot)

- `total_lawn_area_m2` — s2.66[0]
- `position_x_m`, `position_y_m` — s1.4 decoded
- `position_north_m`, `position_east_m` — computed from x,y + station bearing
- `position_lat`, `position_lon` — LOCN
- `blades_life_pct`, `side_brush_life_pct` — CFG.CMS
- `total_cleaning_time_min`, `total_cleaned_area_m2`, `cleaning_count`,
  `first_cleaning_date` — CFG
- `station_bearing_deg` — config_flow option

## Volatile fields (unavailable when source is None)

- `state` — s2.1 (apk-confirmed enum)
- `battery_level` — s3.1
- `charging_status` — s3.2 (g2408 enum offset)
- `error_code` — s2.2 (apk fault index)
- `obstacle_flag` — s1.53
- `area_mowed_m2`, `total_distance_m`, `mowing_phase` — s1.4 decoded
- `wifi_rssi_dbm`, `cloud_connected` — s6.3 (g2408 overlay)
- `battery_temp_low` — s1.1 byte[6] bit
- `slam_task_label` — s2.65
- `task_state_code` — s2.56
- `manual_mode` — computed (15s no-s1.4 detector, wired in F5)

## Computed fields (inherits source's policy)

- `position_north_m`, `position_east_m` — derived from `position_x_m`,
  `position_y_m`, `station_bearing_deg`. Inherits the persistent policy
  of its sources.
- `error_description` — derived from `error_code` via
  `mower/error_codes.describe_error()`. Inherits volatile policy of
  `error_code`.
```

- [ ] **Step 6: Smoke-test imports**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
from custom_components.dreame_a2_mower.mower.state import MowerState, State, ChargingStatus
s = MowerState(error_code=0, position_x_m=1.0, blades_life_pct=85.0)
assert s.error_code == 0
assert s.position_x_m == 1.0
assert s.blades_life_pct == 85.0
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 7: Commit (do NOT push)**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/state.py tests/mower/test_state.py docs/data-policy.md
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F2.1.1: extend MowerState with all F2 fields

Adds 24 fields to cover every §2.1-confirmed mower property:
  - position trio: x_m/y_m (s1.4) + north_m/east_m (computed) +
    lat/lon (LOCN)
  - telemetry-derived: area_mowed, total_distance, mowing_phase
  - errors + flags: error_code (s2.2), obstacle_flag (s1.53),
    battery_temp_low (s1.1 bit), task_state_code (s2.56)
  - environment: wifi_rssi_dbm, cloud_connected (s6.3 g2408 overlay),
    slam_task_label (s2.65), total_lawn_area_m2 (s2.66[0])
  - CFG-derived: blades_life_pct, side_brush_life_pct,
    total_cleaning_time_min, total_cleaned_area_m2, cleaning_count,
    first_cleaning_date
  - config: station_bearing_deg (options-flow input)
  - computed: manual_mode (F5 wires the detector)

Each field's docstring cites its §2.1 source + persistence policy
per spec §8. data-policy.md updated with the persistent/volatile/
computed split.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F2.2 — Property mapping for simple scalar pushes

### Task F2.2.1: Add s1.53, s2.2, s2.66, s6.3, s2.65, s2.56 entries

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/property_mapping.py`
- Modify: `tests/mower/test_property_mapping.py`

These are scalar (or list-of-scalars) pushes. The blob-decoder pushes (s1.4, s1.1) are handled separately in F2.3.

- [ ] **Step 1: Add failing tests to test_property_mapping.py**

```python
def test_obstacle_flag_maps_to_s1p53():
    assert PROPERTY_MAPPING[(1, 53)].field_name == "obstacle_flag"


def test_error_code_maps_to_s2p2():
    assert PROPERTY_MAPPING[(2, 2)].field_name == "error_code"


def test_total_lawn_area_maps_to_s2p66():
    """s2.66 is a 2-element list; the disambiguator extracts [0]."""
    entry = PROPERTY_MAPPING[(2, 66)]
    assert entry.field_name == "total_lawn_area_m2"
    # Disambiguator extracts [0] from the list
    assert entry.disambiguator is not None


def test_wifi_signal_maps_to_s6p3():
    """s6.3 is [cloud_connected: bool, rssi_dbm: int].
    Resolution depends on payload shape — the disambiguator picks
    one of two MowerState fields per call."""
    entry = PROPERTY_MAPPING[(6, 3)]
    assert entry.disambiguator is not None


def test_slam_label_maps_to_s2p65():
    assert PROPERTY_MAPPING[(2, 65)].field_name == "slam_task_label"


def test_task_state_maps_to_s2p56():
    assert PROPERTY_MAPPING[(2, 56)].field_name == "task_state_code"
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_property_mapping.py -v 2>&1 | tail -10
```

Expected: 6 new tests fail (KeyError on missing dict entries).

- [ ] **Step 3: Extend PROPERTY_MAPPING**

Modify `custom_components/dreame_a2_mower/mower/property_mapping.py` to add the new entries. The s2.66 and s6.3 cases need disambiguators because the wire payload is a list, not a scalar. The disambiguator extracts the right element AND returns the field name; the coordinator's apply_property_to_state needs a small extension (in F2.3) to call the entry's `extract_value` callable when present.

**Subtle issue:** the current `resolve_field` returns just a field name. For list-shaped payloads we need to also extract the right list element. So extend `PropertyMappingEntry` with an optional `extract_value` callable.

Update the dataclass and the table:

```python
@dataclass(frozen=True, slots=True)
class PropertyMappingEntry:
    """One row of the property mapping table.

    field_name: the primary MowerState field this (siid, piid) feeds.

    disambiguator: optional callable that inspects the payload value
                   and returns an alternate field name when the primary
                   doesn't apply. Return None to drop the push.

    extract_value: optional callable that transforms the wire payload
                   into the value to assign to the field. Used when the
                   wire shape is a list/dict and only part of it should
                   land on the dataclass. Defaults to identity (the
                   raw value is assigned).

    multi_field: optional list of (field_name, extract_fn) tuples for
                 wire payloads that update multiple MowerState fields
                 from one push (e.g., s6.3 carries both cloud_connected
                 and wifi_rssi_dbm). When set, field_name and
                 disambiguator are ignored — the coordinator iterates
                 multi_field and applies each.
    """

    field_name: str | None = None
    disambiguator: Callable[[Any], str | None] | None = None
    extract_value: Callable[[Any], Any] | None = None
    multi_field: tuple[tuple[str, Callable[[Any], Any]], ...] | None = None
```

Then the new entries:

```python
PROPERTY_MAPPING: dict[tuple[int, int], PropertyMappingEntry] = {
    (2, 1): PropertyMappingEntry(field_name="state"),
    (3, 1): PropertyMappingEntry(field_name="battery_level"),
    (3, 2): PropertyMappingEntry(field_name="charging_status"),

    # F2 additions:
    (1, 53): PropertyMappingEntry(field_name="obstacle_flag"),       # bool
    (2, 2): PropertyMappingEntry(field_name="error_code"),           # int
    (2, 56): PropertyMappingEntry(field_name="task_state_code"),     # int 1..5
    (2, 65): PropertyMappingEntry(field_name="slam_task_label"),     # string

    # s2.66 is [area_m², ?]; we only consume [0] in F2.
    (2, 66): PropertyMappingEntry(
        field_name="total_lawn_area_m2",
        disambiguator=lambda v: "total_lawn_area_m2" if isinstance(v, list) and v else None,
        extract_value=lambda v: float(v[0]) if isinstance(v, list) and v else None,
    ),

    # s6.3 g2408 = [cloud_connected: bool, rssi_dbm: int]
    (6, 3): PropertyMappingEntry(
        multi_field=(
            ("cloud_connected", lambda v: bool(v[0]) if isinstance(v, list) and len(v) >= 1 else None),
            ("wifi_rssi_dbm", lambda v: int(v[1]) if isinstance(v, list) and len(v) >= 2 else None),
        ),
    ),
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/mower/test_property_mapping.py -v 2>&1 | tail -10
```

Expected: all tests pass (the original 6 + 6 new).

- [ ] **Step 5: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/mower/property_mapping.py tests/mower/test_property_mapping.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F2.2.1: property mapping — scalar pushes (s1.53, s2.2, s2.56, s2.65, s2.66, s6.3)

Adds 6 new entries plus extensions to PropertyMappingEntry to
support list-payload pushes:

  - s1.53 obstacle_flag (bool)
  - s2.2 error_code (int)
  - s2.56 task_state_code (int 1..5)
  - s2.65 slam_task_label (string)
  - s2.66 total_lawn_area_m2 (extracts [0] from a 2-elem list)
  - s6.3 wifi/cloud (multi_field — updates both cloud_connected and
    wifi_rssi_dbm from one push)

Two new optional fields on PropertyMappingEntry:
  - extract_value: transforms wire value before assignment
  - multi_field: tuple of (field_name, extract_fn) for pushes that
    update multiple MowerState fields atomically (e.g., s6.3)

The disambiguator slot from F1.2.3 stays — it's still the right
shape for the multi-purpose-pair case (e.g., the documented
robot-voice / notification-type slot).

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F2.3 — Wire blob decoders into coordinator

### Task F2.3.1: s1.4 telemetry blob → multi-field state update

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `tests/integration/test_coordinator.py`

The s1.4 push delivers a 33-byte (or 10-byte BUILDING-mode, or 8-byte BEACON) blob. The `protocol/telemetry.py` module (lifted in F1.1.1) decodes it into a dataclass with fields like `position_x_m`, `position_y_m`, `area_mowed_m2`, etc. The coordinator needs to call the decoder when (siid, piid) == (1, 4) and update multiple `MowerState` fields from the result.

- [ ] **Step 1: Inspect protocol/telemetry.py to know its API**

Run:

```bash
grep -E "^def |^class " /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/telemetry.py
```

Note the public functions and their return types. The expected key entry points:
- `decode_s1p4(blob: bytes) -> MowingTelemetry` (or similar)
- `MowingTelemetry` dataclass with at least: `x_m`, `y_m`, `area_mowed_m2`, `distance_m`, `mowing_phase`

If the actual function names / dataclass shape differ, adapt the test below to match. **Read the actual file** before writing the test.

Note: the wire payload for s1.4 is delivered as a base64-encoded string in the MQTT JSON, NOT raw bytes. The decoder's input may be `bytes` after `base64.b64decode` is applied somewhere — check the decoder's signature. Some decoders accept either; look at the legacy coordinator's call site for a hint:

```bash
grep -n "decode_s1p4\|s1p4\|telemetry" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/device.py | head -10
```

Read 5-10 lines of context around the legacy call to understand how the bytes get to the decoder.

- [ ] **Step 2: Write failing tests in test_coordinator.py**

```python
# Add to tests/integration/test_coordinator.py

import base64

# Synthetic 33-byte s1.4 frame:
#   bytes[0]   = 0xCE (delimiter)
#   bytes[1-2] = int16_le x in cm (123 cm = 1.23m → 123 = 0x7B 0x00)
#   bytes[3-4] = int16_le y in mm (-4560 mm = -4.56m → 0xF0 0xEE in two's complement)
#   bytes[5]   = 0
#   bytes[6-7] = uint16 sequence
#   bytes[8]   = phase (e.g. 2)
#   bytes[9]   = 0
#   bytes[10-21] = motion vectors (8 bytes) + sentinel pair (4 bytes) — zeros for test
#   bytes[22]  = 0
#   bytes[23]  = 2
#   bytes[24-25] = uint16_le distance_deci (3450 = 345.0 m)
#   bytes[26-27] = uint16_le total_area_cent (37830 = 378.30 m²)
#   bytes[28]  = 0
#   bytes[29-30] = uint16_le area_mowed_cent (1250 = 12.50 m²)
#   bytes[31]  = 0
#   bytes[32]  = 0xCE (delimiter)
#
# Construction:

def _make_s1p4_frame_33b(
    x_cm: int = 123,
    y_mm: int = -4560,
    phase: int = 2,
    distance_dm: int = 3450,
    area_mowed_cm2: int = 1250,
) -> bytes:
    import struct
    parts = [
        b"\xce",                                  # 0 delimiter
        struct.pack("<h", x_cm),                  # 1-2 x_cm
        struct.pack("<h", y_mm),                  # 3-4 y_mm
        b"\x00",                                  # 5
        b"\x00\x00",                              # 6-7 sequence
        bytes([phase]),                           # 8 phase
        b"\x00",                                  # 9
        b"\x00" * 12,                             # 10-21 motion vectors + sentinel pair
        b"\x00\x02",                              # 22-23 flags
        struct.pack("<H", distance_dm),           # 24-25 distance
        struct.pack("<H", 50000),                 # 26-27 total_area (irrelevant)
        b"\x00",                                  # 28
        struct.pack("<H", area_mowed_cm2),        # 29-30 area_mowed
        b"\x00",                                  # 31
        b"\xce",                                  # 32 delimiter
    ]
    return b"".join(parts)


def test_s1p4_blob_updates_position_area_distance_phase():
    """A (1, 4) push (telemetry blob) decodes and updates multiple state fields."""
    state = MowerState()
    blob = _make_s1p4_frame_33b()
    # MQTT delivers the blob base64-encoded in the value field
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    assert new_state.mowing_phase == 2
    assert abs(new_state.area_mowed_m2 - 12.50) < 0.001
    assert abs(new_state.total_distance_m - 345.0) < 0.001


def test_s1p4_short_frame_partial_update():
    """8-byte and 10-byte short frames update only the position fields."""
    # 8-byte frame: just position (x_cm, y_mm) at known offsets
    # The exact short-frame structure depends on the decoder; check
    # protocol/telemetry.py for the SHORT_FRAME_LENGTH / BUILDING_LENGTH
    # constants. Use a synthetic 8-byte frame matching the decoder's
    # expectations.
    # If the decoder doesn't expose a public way to construct test frames,
    # use the protocol/replay.py path or just feed one of the
    # tests/fixtures/captured_s1p4_frames.json fixtures into the decoder
    # to verify the integration of decoder + apply_property_to_state.
    pass  # placeholder — fill in once the decoder API is read in step 1


def test_s1p4_invalid_blob_returns_unchanged_state():
    """A malformed s1.4 blob is dropped (logged) without crashing."""
    state = MowerState(position_x_m=1.0)
    new_state = apply_property_to_state(state, siid=1, piid=4, value="not-base64-padded!!")
    # State is unchanged
    assert new_state == state
```

- [ ] **Step 3: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/integration/test_coordinator.py -v 2>&1 | tail -10
```

Expected: the s1.4 tests fail because the coordinator currently treats all (siid, piid) → string field_name; the (1, 4) entry isn't in PROPERTY_MAPPING and there's no blob-handler dispatch.

- [ ] **Step 4: Extend the coordinator with blob-handler dispatch**

Modify `apply_property_to_state` to recognize blob properties and route them through the protocol decoder. The cleanest way: a separate small dispatch table at the top of coordinator.py:

```python
# In coordinator.py, add near the imports:
import base64
from protocol import telemetry as _telemetry  # protocol/telemetry.py decoder


# Add a function below apply_property_to_state:
def _apply_s1p4_telemetry(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.4 telemetry blob and apply its fields to MowerState."""
    if isinstance(value, str):
        try:
            blob = base64.b64decode(value)
        except (ValueError, TypeError):
            LOGGER.warning("%s s1.4: value not base64-decodable: %r", LOG_NOVEL_PROPERTY, value[:32])
            return state
    elif isinstance(value, (bytes, bytearray)):
        blob = bytes(value)
    else:
        LOGGER.warning("%s s1.4: unexpected value type %s", LOG_NOVEL_PROPERTY, type(value).__name__)
        return state

    try:
        # The actual decoder API may be decode_s1p4 or decode_s1p4_position
        # — read protocol/telemetry.py to confirm.
        decoded = _telemetry.decode_s1p4(blob)
    except Exception as ex:  # decoder defines its own exceptions; broad-catch is appropriate here
        LOGGER.warning("%s s1.4 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
        return state

    # Decoded object exposes fields per the decoder's dataclass shape.
    # Replace these field names with the actual names from telemetry.py.
    return dataclasses.replace(
        state,
        position_x_m=getattr(decoded, "x_m", None),
        position_y_m=getattr(decoded, "y_m", None),
        mowing_phase=getattr(decoded, "phase", None),
        area_mowed_m2=getattr(decoded, "area_mowed_m2", None),
        total_distance_m=getattr(decoded, "distance_m", None),
    )


# Modify apply_property_to_state — add an early dispatch for blob properties:
def apply_property_to_state(state, siid, piid, value):
    # Blob-shaped pushes have their own handler:
    if (siid, piid) == (1, 4):
        return _apply_s1p4_telemetry(state, value)

    # ... existing scalar-property logic ...
```

**Important**: read `protocol/telemetry.py` to confirm the decoder function name and dataclass field names. If the field names on the decoded dataclass differ from the MowerState field names (very likely — `x_m` vs `position_x_m`), use `getattr(decoded, "x_m", None)` to extract and assign to `position_x_m`. Don't rename the decoder's fields.

The `getattr(decoded, ..., None)` pattern is intentional: short frames (8-byte, 10-byte) may set only some fields. The default `None` is correct; the unchanged fields stay None.

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/integration/test_coordinator.py -v 2>&1 | tail -15
```

Expected: the F1 tests still pass + the new s1.4 tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "$(cat <<'EOF'
F2.3.1: wire s1.4 telemetry blob → multi-field MowerState update

Adds blob-handler dispatch to apply_property_to_state. (siid, piid)
== (1, 4) now routes through protocol/telemetry.decode_s1p4 to
populate position_x_m, position_y_m, mowing_phase, area_mowed_m2,
total_distance_m in one update.

The handler accepts both base64-string values (the MQTT-on-wire
shape) and raw bytes. Malformed blobs are dropped with a
[NOVEL/property] warning.

Short frames (8-byte BEACON, 10-byte BUILDING) populate only the
position fields; the getattr(..., None) pattern leaves unchanged
fields as None per spec §8 unknowns policy.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task F2.3.2: s1.1 heartbeat blob → battery_temp_low + (more)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `tests/integration/test_coordinator.py`

The s1.1 push delivers a 20-byte heartbeat blob. The `protocol/heartbeat.py` decoder produces a `Heartbeat` dataclass with various flags. F2 wires `battery_temp_low` from byte[6] bit 3.

- [ ] **Step 1: Inspect protocol/heartbeat.py**

Run:

```bash
grep -E "^def |^class |battery_temp" /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/heartbeat.py
```

Note the decoder function name and the field on the Heartbeat dataclass that holds the temp-low flag. Adapt the test below to match.

- [ ] **Step 2: Write failing test**

Add to `tests/integration/test_coordinator.py`:

```python
def _make_s1p1_frame_temp_low_set() -> bytes:
    """20-byte heartbeat with battery_temp_low bit asserted at byte[6] bit 3."""
    frame = bytearray(20)
    frame[0] = 0xCE  # delimiter
    frame[6] = 0x08  # bit 3 = battery_temp_low
    frame[19] = 0xCE  # delimiter
    return bytes(frame)


def test_s1p1_blob_sets_battery_temp_low():
    state = MowerState()
    blob = _make_s1p1_frame_temp_low_set()
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is True


def test_s1p1_blob_clears_battery_temp_low():
    """When the bit is unset, battery_temp_low → False (not None)."""
    state = MowerState(battery_temp_low=True)
    frame = bytearray(20)
    frame[0] = 0xCE
    frame[19] = 0xCE
    blob = bytes(frame)
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is False
```

- [ ] **Step 3: Run tests, expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/integration/test_coordinator.py -v -k s1p1 2>&1 | tail -10
```

Expected: 2 new tests fail.

- [ ] **Step 4: Add s1.1 handler to coordinator.py**

```python
# Near the top of coordinator.py:
from protocol import heartbeat as _heartbeat


# Below _apply_s1p4_telemetry, add:
def _apply_s1p1_heartbeat(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.1 heartbeat blob and apply its flags to MowerState."""
    if isinstance(value, str):
        try:
            blob = base64.b64decode(value)
        except (ValueError, TypeError):
            LOGGER.warning("%s s1.1: value not base64-decodable", LOG_NOVEL_PROPERTY)
            return state
    elif isinstance(value, (bytes, bytearray)):
        blob = bytes(value)
    else:
        return state

    try:
        decoded = _heartbeat.decode_s1p1(blob)
    except Exception as ex:
        LOGGER.warning("%s s1.1 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
        return state

    return dataclasses.replace(
        state,
        battery_temp_low=getattr(decoded, "battery_temp_low", None),
    )


# Update apply_property_to_state's blob-dispatch section:
def apply_property_to_state(state, siid, piid, value):
    # Blob-shaped pushes have their own handlers:
    if (siid, piid) == (1, 4):
        return _apply_s1p4_telemetry(state, value)
    if (siid, piid) == (1, 1):
        return _apply_s1p1_heartbeat(state, value)

    # ... existing scalar logic ...
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest tests/integration/test_coordinator.py -v 2>&1 | tail -15
```

Expected: all coordinator tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.3.2: wire s1.1 heartbeat blob → battery_temp_low

Adds (1, 1) dispatch to apply_property_to_state. Routes through
protocol/heartbeat.decode_s1p1 to populate battery_temp_low from
byte[6] bit 3 of the heartbeat frame.

F2 only consumes battery_temp_low; subsequent phases extend the
heartbeat handler with other flags as their consumers land.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.4 — CFG + LOCN periodic fetchers

### Task F2.4.1: CFG fetcher

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

The CFG-derived fields (blade life, side-brush life, total cleaning time, etc.) come from a routed-action call to the cloud, NOT from MQTT. The legacy coordinator has a `refresh_cfg` method (in `dreame/device.py`) that fetches CFG via cloud-RPC and decodes the result.

For F2: add a `_refresh_cfg` method to `DreameA2MowerCoordinator` that:
1. Calls `cloud_client.fetch_cfg()` (or the actual method name on the F1.4.1 cloud client)
2. Parses the result via `protocol/cfg_action.py` decoders
3. Updates `MowerState` with the relevant fields

Schedule it at:
- First refresh (after MQTT subscribe completes)
- Every 10 minutes thereafter via `async_track_time_interval`

- [ ] **Step 1: Inspect cloud_client + cfg_action**

```bash
grep -E "fetch_cfg|get_cfg|refresh_cfg|cfg|CFG" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/cloud_client.py | head -10
grep -E "^def |^class " /data/claude/homeassistant/ha-dreame-a2-mower-v2/protocol/cfg_action.py
```

Note the actual method names + decoder shape. If the cloud_client doesn't have a `fetch_cfg` or equivalent, look at how the legacy `dreame/device.py:refresh_cfg` constructs the request:

```bash
grep -n "refresh_cfg\|getCFG\|t.*CFG\|aiid.*50" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/device.py | head -20
```

Read 10-15 lines of context around the legacy `refresh_cfg` method to understand the request shape. The greenfield cloud_client may need a new method `fetch_cfg()` added.

- [ ] **Step 2: Add CFG-fetch helper to coordinator.py (and to cloud_client.py if missing)**

If `cloud_client.fetch_cfg()` doesn't exist:

In `cloud_client.py`, add a method modeled on the legacy:

```python
def fetch_cfg(self) -> dict[str, Any] | None:
    """Fetch CFG via routed-action s2 aiid=50. Returns the parsed
    'd' field (dict of CFG keys) or None on failure.

    Source: docs/research/g2408-protocol.md §1 cloud transport;
    this routes via the OSS/getDownloadUrl path that does work on
    g2408 (cloud-RPC `action` returns 80001, but routed-actions
    work).

    See legacy dreame/device.py:refresh_cfg for the request
    construction pattern.
    """
    # Implementation: build the routed-action request {m: 'g', t: 'CFG'}
    # and POST to /dreame-iot-com-10000/device/sendCommand. On success
    # the response includes a 'd' field with all the CFG keys.
    # Use _cookie_session.post(...) like the existing get_interim_file_url
    # path does.
    ...
```

(Concrete implementation lifted from legacy.)

In `coordinator.py`:

```python
# Near imports:
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval


# Add to DreameA2MowerCoordinator:
async def _refresh_cfg(self) -> None:
    """Fetch CFG via routed-action and update MowerState."""
    if self._cloud is None:
        return
    cfg = await self.hass.async_add_executor_job(self._cloud.fetch_cfg)
    if cfg is None:
        return
    # cfg is a dict like {"CMS": {...}, "VOL": 50, "BLD": ..., ...}
    # Use protocol/cfg_action decoders or direct dict access to pick out
    # blades_life_pct, side_brush_life_pct, total_cleaning_time_min,
    # total_cleaned_area_m2, cleaning_count, first_cleaning_date.

    # The exact decoder API depends on protocol/cfg_action.py.
    # Read it before writing this code. Pattern:
    # blades_life = protocol.cfg_action.parse_cms(cfg.get("CMS"))
    # ...

    new_state = dataclasses.replace(
        self.data,
        blades_life_pct=...,           # extract from cfg["CMS"] or whatever
        side_brush_life_pct=...,
        total_cleaning_time_min=...,
        total_cleaned_area_m2=...,
        cleaning_count=...,
        first_cleaning_date=...,
    )
    if new_state != self.data:
        self.async_set_updated_data(new_state)


# In _async_update_data, schedule periodic refresh after first one:
async def _async_update_data(self) -> MowerState:
    if not hasattr(self, "_cloud"):
        # ... existing setup ...
        # Schedule periodic CFG refresh every 10 minutes
        async def _periodic_cfg(_now):
            await self._refresh_cfg()
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, _periodic_cfg, timedelta(minutes=10)
            )
        )
        # Fire one immediately
        await self._refresh_cfg()
    return self.data
```

- [ ] **Step 3: Smoke-test compile**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
import py_compile
py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True)
py_compile.compile('custom_components/dreame_a2_mower/cloud_client.py', doraise=True)
print('ok')
"
```

Expected: `ok`.

The CFG fetcher can't be unit-tested without mocking the cloud HTTP layer, which is out of scope for F2. Live verification against the user's mower happens after the F2 install.

- [ ] **Step 4: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/cloud_client.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.4.1: periodic CFG fetcher in coordinator

Adds _refresh_cfg method to DreameA2MowerCoordinator. Fetches CFG via
the routed-action s2 aiid=50 'g'/'CFG' path (per protocol-doc §1.2 —
the only cloud-RPC surface that works on g2408 since regular
set_properties/action returns 80001).

Decodes blades_life_pct, side_brush_life_pct, total_cleaning_time_min,
total_cleaned_area_m2, cleaning_count, first_cleaning_date from the
returned dict via protocol/cfg_action decoders.

Scheduled via async_track_time_interval every 10 minutes; fires once
immediately during integration setup. All blocking I/O via
async_add_executor_job per spec §3.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F2.4.2: LOCN fetcher

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` (if needed)

LOCN (location, GPS coords) is similar to CFG but uses `t: 'LOCN'`. Returns `{pos: [lon, lat]}` per protocol-doc §2.1, with the sentinel `[-1, -1]` meaning "dock origin not configured".

- [ ] **Step 1: Add fetch_locn to cloud_client.py if missing**

Same pattern as fetch_cfg but with `t: 'LOCN'`.

- [ ] **Step 2: Add _refresh_locn to coordinator**

```python
async def _refresh_locn(self) -> None:
    """Fetch LOCN and update MowerState.position_lat/lon."""
    if self._cloud is None:
        return
    locn = await self.hass.async_add_executor_job(self._cloud.fetch_locn)
    if locn is None:
        return
    pos = locn.get("pos") if isinstance(locn, dict) else None
    if not isinstance(pos, list) or len(pos) != 2:
        return
    lon, lat = pos
    if lon == -1 and lat == -1:
        # Sentinel — dock origin not configured. Leave fields as None.
        new_state = dataclasses.replace(self.data, position_lat=None, position_lon=None)
    else:
        new_state = dataclasses.replace(
            self.data, position_lat=float(lat), position_lon=float(lon)
        )
    if new_state != self.data:
        self.async_set_updated_data(new_state)


# In _async_update_data, after the CFG schedule:
async def _periodic_locn(_now):
    await self._refresh_locn()
self.entry.async_on_unload(
    async_track_time_interval(
        self.hass, _periodic_locn, timedelta(seconds=60)
    )
)
await self._refresh_locn()
```

- [ ] **Step 3: Smoke-test compile**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True); print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/cloud_client.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.4.2: periodic LOCN fetcher

Adds _refresh_locn for GPS coordinates via getCFG t='LOCN'.
Sentinel [-1, -1] (dock origin not configured) → position_lat/lon
remain None, so device_tracker stays unavailable.

Schedule: 60s interval (faster than CFG since users may need
fresh location after re-establishing dock). Per protocol-doc
§2.1 LOCN entry, the value should be stable while the dock is
where it is, but a 60s poll catches the rare reposition without
burning much cloud bandwidth.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.5 — Binary sensors

### Task F2.5.1: binary_sensor.py with 5 entities

**Files:**
- Create: `custom_components/dreame_a2_mower/binary_sensor.py`

Five binary sensors per the spec §5.1 + the audit:

1. `obstacle_detected` ← `state.obstacle_flag`
2. `rain_protection_active` ← `state.error_code == 56`
3. `positioning_failed` ← `state.error_code == 71`
4. `battery_temp_low` ← `state.battery_temp_low`
5. `mowing_session_active` ← derived state — F5 wires the in-progress detector; F2 derives from `state.task_state_code in {1, 2}` as a starter

- [ ] **Step 1: Write binary_sensor.py**

```python
"""Binary sensor platform for the Dreame A2 Mower."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


@dataclass(frozen=True, kw_only=True)
class DreameA2BinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], bool | None]


BINARY_SENSORS: tuple[DreameA2BinarySensorEntityDescription, ...] = (
    DreameA2BinarySensorEntityDescription(
        key="obstacle_detected",
        name="Obstacle detected",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda s: s.obstacle_flag,
    ),
    DreameA2BinarySensorEntityDescription(
        key="rain_protection_active",
        name="Rain protection active",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda s: (s.error_code == 56) if s.error_code is not None else None,
    ),
    DreameA2BinarySensorEntityDescription(
        key="positioning_failed",
        name="Positioning failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: (s.error_code == 71) if s.error_code is not None else None,
    ),
    DreameA2BinarySensorEntityDescription(
        key="battery_temp_low",
        name="Battery temperature low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery_temp_low,
    ),
    DreameA2BinarySensorEntityDescription(
        key="mowing_session_active",
        name="Mowing session active",
        device_class=BinarySensorDeviceClass.RUNNING,
        # F2 starter: task_state_code 1=start_pending, 2=running.
        # F5 replaces this with the in-progress detector (live_map state machine).
        value_fn=lambda s: (s.task_state_code in (1, 2)) if s.task_state_code is not None else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DreameA2BinarySensor(coordinator, desc) for desc in BINARY_SENSORS]
    )


class DreameA2BinarySensor(
    CoordinatorEntity[DreameA2MowerCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    entity_description: DreameA2BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        # Same DeviceInfo as the lawn_mower / sensor entities — clusters under one device.
        client = coordinator._cloud
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
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
```

- [ ] **Step 2: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/binary_sensor.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/binary_sensor.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.5.1: binary_sensor.py with 5 F2 binary sensors

Five frozen-dataclass entity descriptors with value_fn pattern:
  - obstacle_detected (SAFETY) ← obstacle_flag
  - rain_protection_active (MOISTURE) ← error_code == 56
  - positioning_failed (PROBLEM) ← error_code == 71
  - battery_temp_low (PROBLEM, DIAGNOSTIC) ← battery_temp_low
  - mowing_session_active (RUNNING) ← task_state_code in (1, 2)

The mowing_session_active value_fn is an F2 starter that uses the
s2.56 task-state push directly; F5 replaces it with the in-progress
detector when the live_map state machine lands.

Same DeviceInfo as F1 entities to cluster all entities under one
HA device entry.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.6 — Sensor extension

### Task F2.6.1: Extend SENSORS tuple with all F2 sensors

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

Add ~20 new descriptors to the existing `SENSORS` tuple. Group by source:

```python
# Inside sensor.py, EXTEND the existing SENSORS tuple. Add to the end:

# Position trio:
DreameA2SensorEntityDescription(
    key="position_x_m",
    name="Position X",
    native_unit_of_measurement="m",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda s: s.position_x_m,
),
DreameA2SensorEntityDescription(
    key="position_y_m",
    name="Position Y",
    native_unit_of_measurement="m",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda s: s.position_y_m,
),
DreameA2SensorEntityDescription(
    key="position_north_m",
    name="Position North",
    native_unit_of_measurement="m",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda s: s.position_north_m,
),
DreameA2SensorEntityDescription(
    key="position_east_m",
    name="Position East",
    native_unit_of_measurement="m",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda s: s.position_east_m,
),

# Telemetry-derived:
DreameA2SensorEntityDescription(
    key="area_mowed_m2",
    name="Area mowed",
    native_unit_of_measurement="m²",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
    value_fn=lambda s: s.area_mowed_m2,
),
DreameA2SensorEntityDescription(
    key="total_distance_m",
    name="Session distance",
    native_unit_of_measurement="m",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
    value_fn=lambda s: s.total_distance_m,
),
DreameA2SensorEntityDescription(
    key="mowing_phase",
    name="Mowing phase",
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.mowing_phase,
),

# State-related:
DreameA2SensorEntityDescription(
    key="error_code",
    name="Error code",
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.error_code,
),
DreameA2SensorEntityDescription(
    key="error_description",
    name="Error",
    value_fn=lambda s: _describe_error_or_none(s.error_code),
),
DreameA2SensorEntityDescription(
    key="task_state_code",
    name="Task state",
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.task_state_code,
),
DreameA2SensorEntityDescription(
    key="slam_task_label",
    name="SLAM task",
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.slam_task_label,
),

# Lawn / environment:
DreameA2SensorEntityDescription(
    key="total_lawn_area_m2",
    name="Total lawn area",
    native_unit_of_measurement="m²",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
    value_fn=lambda s: s.total_lawn_area_m2,
),
DreameA2SensorEntityDescription(
    key="wifi_rssi_dbm",
    name="WiFi RSSI",
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement="dBm",
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.wifi_rssi_dbm,
),

# CFG-derived consumables:
DreameA2SensorEntityDescription(
    key="blades_life_pct",
    name="Blades life",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    suggested_display_precision=0,
    value_fn=lambda s: s.blades_life_pct,
),
DreameA2SensorEntityDescription(
    key="side_brush_life_pct",
    name="Side brush life",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    suggested_display_precision=0,
    value_fn=lambda s: s.side_brush_life_pct,
),
DreameA2SensorEntityDescription(
    key="total_cleaning_time_min",
    name="Total cleaning time",
    native_unit_of_measurement="min",
    state_class=SensorStateClass.TOTAL_INCREASING,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.total_cleaning_time_min,
),
DreameA2SensorEntityDescription(
    key="total_cleaned_area_m2",
    name="Total cleaned area",
    native_unit_of_measurement="m²",
    state_class=SensorStateClass.TOTAL_INCREASING,
    entity_category=EntityCategory.DIAGNOSTIC,
    suggested_display_precision=1,
    value_fn=lambda s: s.total_cleaned_area_m2,
),
DreameA2SensorEntityDescription(
    key="cleaning_count",
    name="Cleaning count",
    state_class=SensorStateClass.TOTAL_INCREASING,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.cleaning_count,
),
DreameA2SensorEntityDescription(
    key="first_cleaning_date",
    name="First cleaning date",
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.first_cleaning_date,
),
```

Add the `_describe_error_or_none` helper near the top of sensor.py:

```python
from .mower.error_codes import describe_error

def _describe_error_or_none(code: int | None) -> str | None:
    return describe_error(code) if code is not None else None
```

Add the imports if missing:

```python
from homeassistant.const import PERCENTAGE  # already imported in F1; verify
from homeassistant.helpers.entity import EntityCategory  # may need adding
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass  # already imported
```

- [ ] **Step 2: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/sensor.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/sensor.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.6.1: extend SENSORS tuple with all F2 sensors (~20)

Adds 19 new sensor descriptors for the F2 surface:
  - position trio (x_m, y_m, north_m, east_m)
  - telemetry-derived (area_mowed_m2, total_distance_m, mowing_phase)
  - state-related (error_code, error_description, task_state_code, slam_task_label)
  - environment (total_lawn_area_m2, wifi_rssi_dbm)
  - CFG-derived (blades_life_pct, side_brush_life_pct,
    total_cleaning_time_min, total_cleaned_area_m2,
    cleaning_count, first_cleaning_date)

All descriptors use the frozen-dataclass + value_fn pattern from F1.5.2.
Diagnostic-tier entities marked with entity_category=DIAGNOSTIC so
the dashboard's 'controls' tab stays focused on user-actionable
state.

error_description is a computed sensor: value_fn calls
mower.error_codes.describe_error() — inherits the volatile policy
of error_code per data-policy.md.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.7 — GPS device_tracker

### Task F2.7.1: device_tracker.py

**Files:**
- Create: `custom_components/dreame_a2_mower/device_tracker.py`

```python
"""Device tracker (GPS) for the Dreame A2 Mower."""
from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2MowerGpsTracker(coordinator)])


class DreameA2MowerGpsTracker(
    CoordinatorEntity[DreameA2MowerCoordinator], TrackerEntity
):
    """Maps MowerState.position_lat/lon to HA's device_tracker.

    Source: LOCN routed action (`{pos: [lon, lat]}`). Sentinel
    `[-1, -1]` means the dock origin isn't configured — the entity
    is unavailable until the user runs the app's "Set dock GPS"
    flow. Per spec §8 unknowns policy, this is a persistent field;
    last-known coords survive HA restarts via RestoreEntity (F5
    when RestoreEntity is wired more broadly; F2 leaves it without).
    """

    _attr_has_entity_name = True
    _attr_name = "Location"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_gps"
        client = coordinator._cloud
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
    def latitude(self) -> float | None:
        return self.coordinator.data.position_lat

    @property
    def longitude(self) -> float | None:
        return self.coordinator.data.position_lon

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.position_lat is not None
            and self.coordinator.data.position_lon is not None
        )
```

- [ ] **Step 1: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "import py_compile; py_compile.compile('custom_components/dreame_a2_mower/device_tracker.py', doraise=True); print('ok')"
```

Expected: `ok`.

- [ ] **Step 2: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/device_tracker.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.7.1: device_tracker.py for LOCN-derived GPS

Single TrackerEntity wrapping coordinator.data.position_lat/lon.
Goes unavailable when LOCN sentinel [-1, -1] is observed (dock
GPS not configured) — clean handling of the documented sentinel
per protocol-doc §2.1.

Same DeviceInfo as F1 entities for device-registry clustering.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.8 — Base map camera

This phase has more uncertainty than the others — the legacy `dreame/map.py` is 8K LOC and a substantial chunk is upstream encrypted-blob decoding that g2408 doesn't use. The greenfield extracts only the cloud-JSON path.

### Task F2.8.1: Identify and lift the cloud-JSON map decoder

**Files:**
- Create: `custom_components/dreame_a2_mower/map_decoder.py`

The legacy code that's actually used on g2408:
- `dreame/map.py` — `_build_map_from_cloud_data` and the JSON-shape decoder around it
- `dreame/map.py` — `MapData` / `MapDataPartial` / `Segment` / `Area` dataclasses (already in `dreame/types.py`)
- `protocol/cloud_map_geom.py` — geometry transforms (already lifted in F1.1.1)

**This task may run long.** If the legacy code's cloud-JSON path is too tangled to extract cleanly within F2.8 scope, STOP and report DONE_WITH_CONCERNS. Discuss with the controller whether to:
- (a) Extract a minimal viable subset (just enough for base map render)
- (b) Defer to F5 with the trail/state-machine work
- (c) Write a smaller F2.8.1b cleanup task

- [ ] **Step 1: Inspect legacy map.py for the cloud-JSON path**

```bash
grep -n "cloud_data\|build_map_from_cloud\|MAP_REQUEST_PARAMETER_OUT\|getMapData\|fromJSON\|cloud.*map" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/map.py | head -30
```

Read 30-50 lines of context around the `_build_map_from_cloud_data` method or whichever method handles the cloud-JSON shape.

- [ ] **Step 2: Identify dependencies**

The cloud-JSON decoder typically depends on:
- `Segment`, `Area`, `Point` dataclasses from legacy `dreame/types.py`
- Geometry helpers from `protocol/cloud_map_geom.py` (already in new repo)
- Image rendering bits — those go in F2.8.2

For F2.8.1, build a `map_decoder.py` that takes a JSON dict (the MAP.* response) and returns a typed `MapData` dataclass. Define the dataclass locally (don't import from legacy `dreame/types.py` — that's the package we're not bringing forward).

The minimum-viable typed dataclass:

```python
@dataclass(frozen=True, slots=True)
class MapData:
    md5: str
    rotation_deg: float
    pixel_size_mm: float
    boundary_polygon: tuple[tuple[float, float], ...]   # lawn boundary
    exclusion_zones: tuple[tuple[tuple[float, float], ...], ...]  # list of polygons
    dock_xy: tuple[float, float] | None
    width_px: int
    height_px: int
```

(Field set extracted from what the cloud-JSON actually carries; refine after reading legacy.)

- [ ] **Step 3: Write map_decoder.py with a parse_cloud_map function**

The signature:

```python
def parse_cloud_map(cloud_response: dict[str, Any]) -> MapData | None:
    """Parse the cloud's getMapData response into a MapData dataclass.

    Returns None when the response is empty or malformed (caller logs).
    """
```

Implementation: read the legacy `_build_map_from_cloud_data` and translate. Most of it is straightforward — extract polygons, rotation, dock pos, pixel size from the response dict.

- [ ] **Step 4: Commit**

(Skipping detailed test code here because the test surface depends on what the legacy actually does. The implementer should add a smoke test that feeds a captured MAP.* response from `tests/fixtures/` into parse_cloud_map and asserts a non-None MapData out.)

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/map_decoder.py tests/integration/test_map_decoder.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.8.1: cloud-JSON map decoder

Lifts the cloud-JSON path of legacy dreame/map.py into a focused
map_decoder.py module. Parses the getMapData response dict into a
typed MapData dataclass: md5, rotation, pixel_size, lawn boundary,
exclusion zones, dock position.

Dependencies on protocol/cloud_map_geom (already lifted in F1.1.1)
for coordinate transforms. No upstream encrypted-blob decoder
machinery — that path is dead on g2408 per spec §10 deferred items.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F2.8.2: Lift the PNG renderer for the base map

**Files:**
- Create: `custom_components/dreame_a2_mower/map_render.py`

The legacy `dreame/map.py` has a PNG renderer that takes a `MapData` and produces an RGBA Pillow image with the lawn polygon, exclusion zones, and dock icon. F2 needs the **base render only** — no trail overlay (that's F5).

- [ ] **Step 1: Identify the renderer in legacy**

```bash
grep -n "Image\|pillow\|render\|Draw" /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/map.py | head -20
```

- [ ] **Step 2: Write map_render.py**

Function signature:

```python
def render_base_map(map_data: MapData, palette: dict | None = None) -> bytes:
    """Render the base map (no trail) as a PNG byte stream.

    Returns the PNG bytes ready to set as a camera entity's image content.
    """
```

Implement using Pillow. Lift the legacy palette / drawing code, ditch the trail-overlay portions.

- [ ] **Step 3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/map_render.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.8.2: base-map PNG renderer

Lifts the PNG-rendering path of legacy dreame/map.py into
map_render.py. Takes a MapData (from F2.8.1 decoder) and produces
PNG bytes with: lawn boundary polygon, exclusion zones (rotated
correctly), dock icon at the lawn-frame dock_xy.

No trail overlay — the trail layer is F5 territory along with the
session-finalize state machine.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F2.8.3: camera.py with map entity

**Files:**
- Create: `custom_components/dreame_a2_mower/camera.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — add periodic map refresh (every 6 hours per legacy precedent)

```python
"""Camera platform — base live map for Dreame A2 Mower."""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2MapCamera(coordinator)])


class DreameA2MapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Live map camera for the Dreame A2 Mower."""

    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_map"
        client = coordinator._cloud
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current rendered base-map PNG."""
        rendered = self.coordinator.cached_map_png
        return rendered  # may be None on first boot before map is fetched
```

The coordinator gains a `cached_map_png` attribute and a periodic refresh:

```python
# In coordinator.py:
async def _refresh_map(self) -> None:
    """Fetch MAP.* JSON via cloud, decode, render, cache."""
    if self._cloud is None:
        return
    cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
    if cloud_response is None:
        return
    from .map_decoder import parse_cloud_map
    from .map_render import render_base_map
    map_data = parse_cloud_map(cloud_response)
    if map_data is None:
        return
    if map_data.md5 == self._last_map_md5:
        return  # md5-deduped — no re-render needed
    png = await self.hass.async_add_executor_job(render_base_map, map_data)
    self.cached_map_png = png
    self._last_map_md5 = map_data.md5

# Initialize in __init__:
self.cached_map_png: bytes | None = None
self._last_map_md5: str | None = None

# Schedule in _async_update_data (alongside CFG and LOCN refreshes):
async def _periodic_map(_now):
    await self._refresh_map()
self.entry.async_on_unload(
    async_track_time_interval(self.hass, _periodic_map, timedelta(hours=6))
)
await self._refresh_map()
```

- [ ] **Step 1: Smoke-test**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && python3 -c "
import py_compile
py_compile.compile('custom_components/dreame_a2_mower/camera.py', doraise=True)
py_compile.compile('custom_components/dreame_a2_mower/coordinator.py', doraise=True)
print('ok')
"
```

- [ ] **Step 2: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.8.3: camera.py with base-map entity + 6h refresh

DreameA2MapCamera serves a PNG from coordinator.cached_map_png.
Coordinator's _refresh_map fetches MAP.* via cloud_client.fetch_map,
decodes via map_decoder.parse_cloud_map, renders via
map_render.render_base_map. md5-deduped — same MAP payload doesn't
re-render.

Schedule: 6-hour interval per legacy precedent (the mower doesn't
push 'map changed' events; 6h covers app-side zone edits without
burning bandwidth). Plus one immediate refresh on integration setup.

No trail overlay — F5 wires the live session trail layer when the
state machine lands.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F2.9 — Wire everything in

### Task F2.9.1: Update PLATFORMS list

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`

Update PLATFORMS to include all F2 platforms:

```python
PLATFORMS: Final = [
    "lawn_mower",
    "sensor",
    "binary_sensor",
    "device_tracker",
    "camera",
]
```

- [ ] **Step 1: Edit const.py**

Replace the F1 PLATFORMS with the 5-platform list above.

- [ ] **Step 2: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ add custom_components/dreame_a2_mower/const.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ commit -m "F2.9.1: extend PLATFORMS list to include F2 platforms

Adds binary_sensor, device_tracker, camera to PLATFORMS. Sensor
descriptors now extends to ~21 entities (battery + charging +
F2 additions). lawn_mower platform unchanged.

Spec: docs/superpowers/specs/2026-04-27-greenfield-integration-design.md F2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task F2.9.2: Final test sweep + tag v0.2.0a0

- [ ] **Step 1: Run full pytest sweep**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2/ && pytest -v 2>&1 | tail -30
```

Expected: full suite still green. New tests (F2.1, F2.2, F2.3) all pass; F1 tests unchanged.

- [ ] **Step 2: Tag**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower-v2/ tag -a v0.2.0a0 -m "F2 — Core state phase complete. All §2.1-confirmed properties surfaced as entities. Position trio + GPS tracker + base map camera + 5 binary sensors + ~20 sensors. Action handlers still F1 stubs (F3 wires them)."
```

(Controller pushes the commit + tag.)

---

## Self-review checklist

Run before declaring F2 complete:

- [ ] All `pytest` tests pass.
- [ ] No `homeassistant.*` imports in `protocol/` or `mower/`.
- [ ] All F2 fields on `MowerState` cite §2.1 source + persistence.
- [ ] data-policy.md has all F2 fields under correct sections.
- [ ] Each entity's `_attr_device_info` clusters with the F1 entities.
- [ ] HA reloads against a live g2408 successfully.
- [ ] Sensors show fresh values after the first MQTT update tick.
- [ ] Live map camera shows the lawn polygon + exclusion zones.
- [ ] GPS tracker pin lands at the correct dock position (or unavailable if LOCN sentinel).
- [ ] `v0.2.0a0` tag pushed.

## What this plan does NOT do

Out-of-scope for F2:

- F3: action surface (services + action_mode select + real cloud RPC)
- F4: settings (s2.51 multiplexed config sub-fields, mowing height/efficiency, rain protection, etc.)
- F5: live map trail overlay + session lifecycle (in-progress, finalize, archive)
- F6: observability layer (novel-token registry, schema validators, diagnostic sensor, download_diagnostics)
- F7: LiDAR popout + dashboard polish + cutover

## Followup tasks

After F2 lands:
- Final cumulative review (dispatched by controller).
- User installs v0.2.0a0 against the live mower; verifies sensors + binary_sensors + tracker + map camera work.
- F3 plan is written against the actual file structure F2 produced.
