# F6 Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the integration self-report unknown protocol shapes, per-field staleness, supported endpoints, and dump a redacted diagnostics file users can attach to bug reports.

**Architecture:** New `observability/` HA-glue subpackage that wraps the existing `protocol/unknown_watchdog.py` with timestamped categorization, plus a thin schema-validator pass over JSON blobs (session_summary, CFG) so novel keys are flagged the same way novel `(siid, piid)` slots are. `diagnostics.py` snapshots `MowerState` + capabilities + the registry + a tail of recent NOVEL log lines, then redacts secrets. New diagnostic sensors surface registry data and per-field freshness.

**Tech Stack:** Python 3.11+, Home Assistant `DataUpdateCoordinator`, `pytest` + `pytest-homeassistant-custom-component`. No new third-party deps.

---

## Context for the implementer

### Where this fits in the project

F6 is the second-to-last phase. F1–F5 already shipped (tag `v0.5.0a1`). The integration today decodes MQTT, surfaces ~31 sensors / a lawn_mower platform / camera / device_tracker / select / number / switch / time / button, runs the session lifecycle end-to-end, and persists archives. F6 makes it **self-reporting**: the integration tells the user what it doesn't understand, what it lost contact with, and what it can do.

F7 (LiDAR popout + dashboard polish + cutover) follows. Don't pull F7 work forward.

### What's already in the repo

- `protocol/unknown_watchdog.py` — `UnknownFieldWatchdog` class with `saw_property`, `saw_method`, `saw_value`, `saw_event`. **Already exists**, **already unit-tested** at `tests/protocol/test_unknown_watchdog.py`. F6 wraps it; F6 does not rewrite it.
- `custom_components/dreame_a2_mower/const.py` — already declares `LOG_NOVEL_PROPERTY = "[NOVEL/property]"`, `LOG_NOVEL_VALUE = "[NOVEL/value]"`, `LOG_NOVEL_KEY = "[NOVEL_KEY]"`. Use these constants; do not re-declare.
- `custom_components/dreame_a2_mower/coordinator.py` — `apply_property_to_state` is the choke-point for every property push. Hooks for the registry go around it (the coordinator owns the registry instance and consults it before delegating).
- `protocol/session_summary.py` — `parse_session_summary(json_dict) -> SessionSummary`. F6 adds a schema-validation pass before/around this call.
- `protocol/api_log.py` — already exists for routed-action endpoint accept/reject tracking. F6 surfaces it as a sensor.
- `custom_components/dreame_a2_mower/sensor.py` — uses frozen `EntityDescription` dataclasses with `value_fn`. F6 adds three diagnostic descriptions to this file.

### Spec sections this plan satisfies

- §3 Layer 1 observability (schema validators with codecs).
- §3 Cross-cutting: `[NOVEL/{category}]` log prefixes.
- §5.6 Diagnostic / Observability layer (`sensor.novel_observations`, `sensor.api_endpoints_supported`, `sensor.dreame_a2_mower_data_freshness`).
- §6 Observability acceptance items 1–5 (the last block of the parity checklist).
- §8 Rule 3: per-field staleness sensor.

### Layering invariant (DO NOT VIOLATE)

| Path | Layer | HA imports allowed? |
|---|---|---|
| `protocol/` | 1 | NO |
| `custom_components/dreame_a2_mower/mower/` | 2 | NO |
| `custom_components/dreame_a2_mower/observability/` | 3 (HA-glue) | YES |
| `custom_components/dreame_a2_mower/archive/` | 2 | NO |
| `custom_components/dreame_a2_mower/live_map/` | 2 | NO |
| Everything else under `custom_components/dreame_a2_mower/` | 3 | YES |

`observability/registry.py` and `observability/schemas.py` would naturally be layer-2 (no HA dep). The spec puts them in the HA-glue tree at `custom_components/dreame_a2_mower/observability/` — keep them HA-import-free anyway. `observability/diagnostic_sensor.py` and the diagnostics handler at `custom_components/dreame_a2_mower/diagnostics.py` are HA-coupled.

### Where the parity-checklist items map to tasks

| Acceptance item | Task |
|---|---|
| Novel `(siid, piid)` arrival fires `[NOVEL/property]` WARNING once per process | F6.2 |
| Novel value for known property fires `[NOVEL/value]` WARNING once | F6.2 |
| Novel key in session_summary JSON fires `[NOVEL_KEY/session_summary]` WARNING | F6.4 |
| `sensor.novel_observations` count increments on each novel hit | F6.5 |
| `download_diagnostics` produces a file with state + capabilities + novel-token list + recent log lines, with creds redacted | F6.10 |
| `sensor.api_endpoints_supported` (§5.6) | F6.8 |
| `sensor.dreame_a2_mower_data_freshness` (§5.6, §8) | F6.7 |

### File structure delivered by F6

```
custom_components/dreame_a2_mower/
├── observability/
│   ├── __init__.py                  # re-exports public surface
│   ├── registry.py                  # NovelObservationRegistry + NovelObservation dataclass
│   ├── schemas.py                   # SchemaCheck.diff_keys() against expected schema fingerprints
│   ├── log_buffer.py                # bounded deque of NOVEL log lines for diagnostics tail
│   └── freshness.py                 # FreshnessTracker — last_updated[field_name] = unix_ts
├── diagnostics.py                   # async_get_config_entry_diagnostics with redaction
├── coordinator.py                   # F6 wires the four observability hooks
├── sensor.py                        # F6 adds 3 diagnostic descriptions
├── const.py                         # F6 adds NOVEL_KEY_SESSION_SUMMARY constant + freshness limits
└── ...

tests/
├── observability/
│   ├── test_registry.py
│   ├── test_schemas.py
│   ├── test_log_buffer.py
│   └── test_freshness.py
└── integration/
    └── test_diagnostics.py
```

---

## Phase F6.1 — Novel-observation registry

The registry is a thin wrapper over `protocol/unknown_watchdog.py` that adds **timestamps**, **categorization** (`property`, `value`, `event`, `key`), and a **snapshot view** suitable for HA sensors and the diagnostics dump. It owns one `UnknownFieldWatchdog` instance and one ordered list of `NovelObservation` records.

### Task F6.1.1: Create the registry skeleton + dataclass

**Files:**
- Create: `custom_components/dreame_a2_mower/observability/__init__.py`
- Create: `custom_components/dreame_a2_mower/observability/registry.py`
- Create: `tests/observability/__init__.py`
- Create: `tests/observability/test_registry.py`

- [ ] **Step 1: Write the failing test for empty-registry snapshot**

In `tests/observability/test_registry.py`:

```python
"""Tests for the novel-observation registry."""

from __future__ import annotations

from custom_components.dreame_a2_mower.observability.registry import (
    NovelObservation,
    NovelObservationRegistry,
)


def test_registry_starts_empty():
    reg = NovelObservationRegistry()
    snap = reg.snapshot()
    assert snap.count == 0
    assert snap.observations == []


def test_record_property_adds_observation():
    reg = NovelObservationRegistry()
    fired = reg.record_property(siid=99, piid=42, now_unix=1700000000)
    assert fired is True
    snap = reg.snapshot()
    assert snap.count == 1
    obs = snap.observations[0]
    assert obs.category == "property"
    assert obs.detail == "siid=99 piid=42"
    assert obs.first_seen_unix == 1700000000


def test_record_property_dedupes():
    reg = NovelObservationRegistry()
    assert reg.record_property(siid=99, piid=42, now_unix=1700000000) is True
    assert reg.record_property(siid=99, piid=42, now_unix=1700000005) is False
    assert reg.snapshot().count == 1


def test_record_value_for_known_property():
    reg = NovelObservationRegistry()
    fired = reg.record_value(siid=2, piid=2, value=99, now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "value"
    assert "siid=2 piid=2" in obs.detail
    assert "value=99" in obs.detail


def test_record_key_uses_namespace():
    reg = NovelObservationRegistry()
    fired = reg.record_key(namespace="session_summary", key="weird_field", now_unix=1700000000)
    assert fired is True
    obs = reg.snapshot().observations[0]
    assert obs.category == "key"
    assert obs.detail == "session_summary.weird_field"


def test_observations_sorted_oldest_first():
    reg = NovelObservationRegistry()
    reg.record_property(siid=1, piid=1, now_unix=1700000010)
    reg.record_property(siid=2, piid=2, now_unix=1700000005)
    reg.record_property(siid=3, piid=3, now_unix=1700000020)
    seen = [o.first_seen_unix for o in reg.snapshot().observations]
    assert seen == [1700000010, 1700000005, 1700000020]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_registry.py -v`
Expected: ImportError because `observability.registry` does not exist.

- [ ] **Step 3: Write the registry implementation**

In `custom_components/dreame_a2_mower/observability/__init__.py`:

```python
"""Layer-3 observability surface.

Wraps the layer-1 watchdog (`protocol/unknown_watchdog.py`) with
timestamps and categorization, exposes registry snapshots to HA sensors
and the diagnostics handler.

Modules in this package follow the layer-2 invariant of NO ``homeassistant.*``
imports — even though they live under ``custom_components/`` for packaging
reasons. The HA-coupled code lives in ``diagnostic_sensor.py`` (loaded by
``sensor.py``) and ``../diagnostics.py``.
"""

from __future__ import annotations

from .registry import NovelObservation, NovelObservationRegistry, RegistrySnapshot

__all__ = ["NovelObservation", "NovelObservationRegistry", "RegistrySnapshot"]
```

In `custom_components/dreame_a2_mower/observability/registry.py`:

```python
"""Novel-observation registry — timestamped wrapper over UnknownFieldWatchdog.

The watchdog at ``protocol/unknown_watchdog.py`` answers "have I seen this
key before?". The registry adds a wall-clock timestamp and a category
label (``property`` / ``value`` / ``event`` / ``key``) so HA sensors and
diagnostics can show *what* surprised the integration *when*.

Process-scoped: a HA restart drops everything. Matches the watchdog's
semantics.

NO ``homeassistant.*`` imports — this module lives under
``custom_components/`` for packaging convenience but obeys the layer-2
no-HA-import invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from protocol.unknown_watchdog import UnknownFieldWatchdog


@dataclass(frozen=True)
class NovelObservation:
    """One novel-token sighting.

    Insertion-ordered (the ``observations`` list preserves arrival order,
    which is the order users want when reading a diagnostics dump).
    """

    category: str           # "property" | "value" | "event" | "key"
    detail: str             # human-readable token, e.g. "siid=99 piid=42"
    first_seen_unix: int    # wall-clock time of the first sighting


@dataclass(frozen=True)
class RegistrySnapshot:
    """Read-only view of the registry suitable for sensor attributes."""

    count: int
    observations: list[NovelObservation]


class NovelObservationRegistry:
    """Records first-arrival of unknown protocol shapes.

    Methods return ``True`` the first time a token is seen, ``False``
    on every subsequent observation — matches the watchdog's "novelty
    bool" return convention so callers can gate their ``LOGGER.warning``
    calls cleanly.

    Caps total observations at ``MAX_OBSERVATIONS`` to bound the sensor
    attribute list and the diagnostics dump size on devices with a flood
    of unknown tokens. Once capped, further novel tokens are dropped at
    record-time (the watchdog still tracks them, but they don't reach
    the sensor).
    """

    MAX_OBSERVATIONS = 200

    def __init__(self) -> None:
        self._watchdog = UnknownFieldWatchdog()
        self._observations: list[NovelObservation] = []

    def record_property(self, siid: int, piid: int, now_unix: int) -> bool:
        if not self._watchdog.saw_property(siid, piid):
            return False
        self._append("property", f"siid={siid} piid={piid}", now_unix)
        return True

    def record_value(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> bool:
        if not self._watchdog.saw_value(siid, piid, value):
            return False
        self._append("value", f"siid={siid} piid={piid} value={value!r}", now_unix)
        return True

    def record_event(
        self, siid: int, eiid: int, piids: list[int], now_unix: int
    ) -> bool:
        if not self._watchdog.saw_event(siid, eiid, piids):
            return False
        self._append("event", f"siid={siid} eiid={eiid} piids={sorted(piids)!r}", now_unix)
        return True

    def record_key(self, namespace: str, key: str, now_unix: int) -> bool:
        """Track a JSON-blob key that's not in the expected schema.

        ``namespace`` is the schema name (``"session_summary"``,
        ``"cfg"``, ...). The watchdog's method-set is reused as the
        novelty store keyed on ``f"{namespace}.{key}"``.
        """
        token = f"{namespace}.{key}"
        if not self._watchdog.saw_method(token):
            return False
        self._append("key", token, now_unix)
        return True

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            count=len(self._observations),
            observations=list(self._observations),
        )

    # ----- internal -----

    def _append(self, category: str, detail: str, now_unix: int) -> None:
        if len(self._observations) >= self.MAX_OBSERVATIONS:
            return
        self._observations.append(
            NovelObservation(
                category=category,
                detail=detail,
                first_seen_unix=int(now_unix),
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/ -v`
Expected: 5 tests pass.

- [ ] **Step 5: Verify no HA imports in observability/**

Run: `grep -rn "from homeassistant\|import homeassistant" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/observability/`
Expected: empty output.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/observability/__init__.py custom_components/dreame_a2_mower/observability/registry.py tests/observability/__init__.py tests/observability/test_registry.py && git commit -m "F6.1.1: novel-observation registry skeleton"
```

---

## Phase F6.2 — Wire registry into property push

### Task F6.2.1: Coordinator owns the registry; property-push consults it

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (constructor + the property-push helper)
- Modify: `custom_components/dreame_a2_mower/const.py` — add `LOG_NOVEL_VALUE` log usage (already declared in F1)
- Test: `tests/integration/test_coordinator.py` (extend an existing test file)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_coordinator.py`:

```python
def test_unknown_siid_piid_triggers_property_novelty(coordinator):
    """A property push with an unmapped (siid, piid) pair must add a
    'property' observation to the registry exactly once."""
    coordinator.handle_property_push(siid=99, piid=42, value=7)
    coordinator.handle_property_push(siid=99, piid=42, value=8)  # dupe
    obs = coordinator.novel_registry.snapshot().observations
    property_obs = [o for o in obs if o.category == "property"]
    assert len(property_obs) == 1
    assert property_obs[0].detail == "siid=99 piid=42"


def test_known_siid_piid_with_novel_value_triggers_value_novelty(coordinator):
    """A property push with a mapped (siid, piid) but never-before-seen
    value must add a 'value' observation."""
    # s2.2 (error_code) is mapped. Push a value that's outside the known
    # range to trigger the value novelty.
    coordinator.handle_property_push(siid=2, piid=2, value=999)
    coordinator.handle_property_push(siid=2, piid=2, value=999)  # dupe
    value_obs = [
        o for o in coordinator.novel_registry.snapshot().observations
        if o.category == "value"
    ]
    assert len(value_obs) == 1
    assert "value=999" in value_obs[0].detail
```

(Use the existing `coordinator` fixture from `tests/integration/conftest.py` if one exists; otherwise read the file to find the established way to construct a coordinator under test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_coordinator.py -k novel -v`
Expected: FAIL — `coordinator.novel_registry` does not exist.

- [ ] **Step 3: Wire the registry into the coordinator**

Read `custom_components/dreame_a2_mower/coordinator.py` to find the constructor and the `handle_property_push` method. Make these changes:

In the imports section, add:

```python
from .observability import NovelObservationRegistry
```

In `__init__`, add (next to the other instance attributes):

```python
self.novel_registry = NovelObservationRegistry()
```

In `handle_property_push`, before the `apply_property_to_state` call, consult the registry. The exact patch (read the current method first to merge correctly):

```python
def handle_property_push(self, siid: int, piid: int, value) -> None:
    now = int(time.time())
    # Novelty checks — gate the warning logs on the registry's
    # first-arrival bool so each new token logs exactly once per process.
    if siid_piid_is_known(siid, piid):
        if self.novel_registry.record_value(siid, piid, value, now):
            LOGGER.warning(
                "%s siid=%s piid=%s value=%r — first-time value for known slot",
                LOG_NOVEL_VALUE, siid, piid, value,
            )
    else:
        if self.novel_registry.record_property(siid, piid, now):
            LOGGER.warning(
                "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                LOG_NOVEL_PROPERTY, siid, piid, value,
            )

    new_state = apply_property_to_state(self.data, siid, piid, value)
    if new_state == self.data:
        return

    def _apply() -> None:
        hopped = self._on_state_update(new_state, now)
        self.async_set_updated_data(hopped)

    self.hass.loop.call_soon_threadsafe(_apply)
```

`siid_piid_is_known` is a tiny helper that consults the existing `mower/property_mapping.py`. Add it next to the imports:

```python
from .mower.property_mapping import PROPERTY_MAPPING


def siid_piid_is_known(siid: int, piid: int) -> bool:
    return (int(siid), int(piid)) in PROPERTY_MAPPING
```

(If the property mapping uses a different structure — e.g., a list of records — read the actual file and adapt. The intent is "is this slot in the table?".)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_coordinator.py -v`
Expected: all previously-passing tests still pass + the two new ones pass.

- [ ] **Step 5: Run the full suite**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: still green; no F1–F5 regressions. Specifically: still 520 passed minimum + the 2 new tests = 522 passing.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py && git commit -m "F6.2.1: wire novel-observation registry into property push"
```

---

## Phase F6.3 — Schema validators for JSON blobs

The protocol layer parses JSON for `session_summary` and CFG. F6 adds a "did this blob have any keys we don't recognize?" check so unknown keys go through the same novelty pipeline as unmapped MQTT slots.

### Task F6.3.1: Implement `SchemaCheck.diff_keys`

**Files:**
- Create: `custom_components/dreame_a2_mower/observability/schemas.py`
- Create: `tests/observability/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

In `tests/observability/test_schemas.py`:

```python
"""Tests for schema-validator drift detection."""

from __future__ import annotations

from custom_components.dreame_a2_mower.observability.schemas import (
    SCHEMA_SESSION_SUMMARY,
    SchemaCheck,
)


def test_known_keys_yield_no_diff():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"area": 12.3, "duration": 600, "map": []}
    extra = check.diff_keys(payload)
    assert extra == []


def test_unknown_key_at_top_level():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"area": 12.3, "weird_field": "x"}
    extra = check.diff_keys(payload)
    assert extra == ["weird_field"]


def test_unknown_keys_nested_one_level():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    payload = {"map": [{"track": [], "rogue": True}]}
    extra = check.diff_keys(payload)
    # nested path uses dotted notation
    assert "map[].rogue" in extra


def test_empty_payload_no_diff():
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    assert check.diff_keys({}) == []


def test_payload_missing_keys_is_not_a_diff():
    """diff_keys reports unknown keys present in payload, not missing ones —
    a partial payload is normal (e.g. session with no obstacles)."""
    check = SchemaCheck(SCHEMA_SESSION_SUMMARY)
    extra = check.diff_keys({"area": 1.0})
    assert extra == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_schemas.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement schemas.py**

In `custom_components/dreame_a2_mower/observability/schemas.py`:

```python
"""Schema fingerprints for known JSON blobs.

Each schema is a nested dict where leaf-True means "we know about this
key". Lists of dicts use a single ``"[]"`` sub-key to describe the
expected element shape. ``SchemaCheck.diff_keys`` returns the dotted
paths of keys present in the payload but absent from the schema —
exactly the surface the registry's ``record_key`` method consumes.

NO ``homeassistant.*`` imports — layer-2 invariant.

Adding a new fingerprint
------------------------
Schemas live as module-level constants. To extend, add another constant
plus its tests; the wire-in logic in the coordinator references the
constant by name. Don't pull schemas from disk — drift in a
configuration file would be a worse failure mode than drift in the
code.
"""

from __future__ import annotations

from typing import Any


SCHEMA_SESSION_SUMMARY: dict[str, Any] = {
    "area": True,
    "duration": True,
    "started_at": True,
    "ended_at": True,
    "map": {
        "[]": {
            "track": True,
            "obstacles": True,
            "boundary": True,
        },
    },
    "battery_used_pct": True,
    "blade_runtime_min": True,
    "session_id": True,
}
"""Known top-level keys in the OSS session-summary JSON. Update as the
parser learns new fields. Keys present in the payload but not here
trigger a [NOVEL_KEY/session_summary] WARNING."""


SCHEMA_CFG: dict[str, Any] = {
    "CFG": True,
    "CMS": True,
    "CLS": True,
    "CMG": True,
    "RPM": True,
    "schedule": True,
}
"""Top-level keys in the s2.51 CFG blob."""


class SchemaCheck:
    """Compute the set of unexpected keys in a JSON payload."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def diff_keys(self, payload: dict[str, Any]) -> list[str]:
        """Return dotted paths of keys present in payload but absent from schema."""
        return sorted(self._diff(payload, self._schema, prefix=""))

    def _diff(
        self,
        payload: Any,
        schema: dict[str, Any] | bool,
        prefix: str,
    ) -> list[str]:
        # Schema is a leaf marker (True). Anything below this level
        # is opaque to the validator; report nothing.
        if schema is True:
            return []
        if not isinstance(payload, dict):
            return []
        unknown: list[str] = []
        for key, value in payload.items():
            if key not in schema:
                unknown.append(f"{prefix}{key}" if prefix else key)
                continue
            sub = schema[key]
            if isinstance(value, list) and isinstance(sub, dict) and "[]" in sub:
                element_schema = sub["[]"]
                for item in value:
                    unknown.extend(self._diff(item, element_schema, f"{prefix}{key}[]."))
            elif isinstance(sub, dict):
                unknown.extend(self._diff(value, sub, f"{prefix}{key}."))
        return unknown
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_schemas.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/observability/schemas.py tests/observability/test_schemas.py && git commit -m "F6.3.1: schema fingerprints + key-diff for JSON blobs"
```

---

## Phase F6.4 — Wire schema validation into session_summary

### Task F6.4.1: Validate session_summary keys when parsing

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — wherever `parse_session_summary` is called, run the schema check first
- Modify: `custom_components/dreame_a2_mower/const.py` — add `LOG_NOVEL_KEY_SESSION_SUMMARY = "[NOVEL_KEY/session_summary]"`
- Test: `tests/integration/test_coordinator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_session_summary_with_novel_key_logs_and_records(coordinator, caplog):
    """An OSS session_summary fetch where the JSON contains a key not in
    SCHEMA_SESSION_SUMMARY must log [NOVEL_KEY/session_summary] WARNING
    once and add a 'key' observation to the registry."""
    payload = {
        "area": 5.0,
        "duration": 60,
        "map": [],
        "weird_field": 42,  # novel key
    }
    coordinator._handle_session_summary_payload(payload)
    coordinator._handle_session_summary_payload(payload)  # dupe
    novel = [
        o for o in coordinator.novel_registry.snapshot().observations
        if o.category == "key"
    ]
    assert len(novel) == 1
    assert novel[0].detail == "session_summary.weird_field"
    warns = [r for r in caplog.records if "[NOVEL_KEY/session_summary]" in r.message]
    assert len(warns) == 1
```

(Adjust the helper-method name `_handle_session_summary_payload` to match whatever the coordinator currently calls when an OSS fetch returns. If the existing path is `_do_oss_fetch` and it bakes in HTTP, factor out a pure helper that takes a parsed JSON dict and call that — both from `_do_oss_fetch` and from this test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_coordinator.py -k session_summary_with_novel_key -v`
Expected: FAIL — registry lacks the entry, or the helper doesn't exist.

- [ ] **Step 3: Add the const**

In `custom_components/dreame_a2_mower/const.py`, near the other `LOG_NOVEL_*` constants:

```python
LOG_NOVEL_KEY_SESSION_SUMMARY: Final = "[NOVEL_KEY/session_summary]"
```

- [ ] **Step 4: Wire schema validation into the session_summary path**

Read coordinator.py to locate where the parsed OSS JSON dict is consumed. Refactor to a helper if necessary. Add:

```python
from .observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck

# At the class level — module-shared, since SCHEMA is immutable:
_SESSION_SUMMARY_CHECK = SchemaCheck(SCHEMA_SESSION_SUMMARY)
```

In the helper that handles the parsed payload:

```python
def _handle_session_summary_payload(self, payload: dict) -> None:
    now = int(time.time())
    for key in _SESSION_SUMMARY_CHECK.diff_keys(payload):
        if self.novel_registry.record_key("session_summary", key, now):
            LOGGER.warning(
                "%s key=%s — JSON shape drift, parser may need an update",
                LOG_NOVEL_KEY_SESSION_SUMMARY, key,
            )
    summary = parse_session_summary(payload)
    # ... existing post-parse handling ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: all tests pass; the new test included.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/const.py tests/integration/test_coordinator.py && git commit -m "F6.4.1: validate session_summary keys, log NOVEL_KEY drift"
```

---

## Phase F6.5 — `sensor.novel_observations`

### Task F6.5.1: Add the novel-observations sensor

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py` — add a frozen `EntityDescription` + `value_fn` + `extra_state_attributes`
- Modify: `custom_components/dreame_a2_mower/const.py` if a category constant is helpful
- Test: `tests/integration/test_sensor.py` (or whatever test file exercises the existing sensor surface — read `tests/integration/` to find the right one)

- [ ] **Step 1: Write the failing test**

```python
def test_novel_observations_sensor_state_and_attrs(coordinator_with_novelties):
    """The sensor's state must equal the registry count; the
    'observations' attribute must list each obs as a dict with
    category/detail/first_seen_unix keys."""
    sensor = build_novel_observations_sensor(coordinator_with_novelties)
    assert sensor.native_value == 3
    attrs = sensor.extra_state_attributes
    assert len(attrs["observations"]) == 3
    sample = attrs["observations"][0]
    assert set(sample.keys()) == {"category", "detail", "first_seen_unix"}
    assert sensor.entity_description.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.entity_description.icon == "mdi:eye-question"
```

The fixture `coordinator_with_novelties` should pre-load three observations into a coordinator's registry. Implement next to the existing fixtures.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_sensor.py -k novel_observations -v`
Expected: FAIL — symbol does not exist.

- [ ] **Step 3: Add the sensor description**

Read `sensor.py` to find the existing description-list pattern (frozen dataclass with `value_fn`/`extra_state_attributes_fn`). Add this entry:

```python
DreameA2MowerSensorEntityDescription(
    key="novel_observations",
    translation_key="novel_observations",
    icon="mdi:eye-question",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=True,
    value_fn=lambda _state, *, ctx: ctx.novel_registry.snapshot().count,
    extra_state_attributes_fn=lambda _state, *, ctx: {
        "observations": [
            {
                "category": o.category,
                "detail": o.detail,
                "first_seen_unix": o.first_seen_unix,
            }
            for o in ctx.novel_registry.snapshot().observations
        ],
    },
),
```

If the existing description signature passes only `state`, extend it to also receive a context object (pattern: `value_fn=lambda state, *, ctx: ...`). The context is the coordinator. Match the established convention exactly — read three or four existing descriptions first.

If no `extra_state_attributes_fn` field exists yet, add it to the dataclass:

```python
extra_state_attributes_fn: Callable[..., dict[str, Any]] | None = None
```

…and in the entity class wire it through:

```python
@property
def extra_state_attributes(self) -> dict[str, Any] | None:
    if self.entity_description.extra_state_attributes_fn is None:
        return None
    return self.entity_description.extra_state_attributes_fn(
        self.coordinator.data, ctx=self.coordinator,
    )
```

- [ ] **Step 4: Add `translations/en.json` entry**

Open `custom_components/dreame_a2_mower/translations/en.json`. Find the `entity.sensor` block. Add:

```json
"novel_observations": {
    "name": "Novel observations"
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/translations/en.json tests/integration/test_sensor.py && git commit -m "F6.5.1: sensor.novel_observations diagnostic entity"
```

---

## Phase F6.6 — Per-field freshness tracker

The coordinator needs to know "when was each field last updated?" so the freshness sensor can report stale fields. The tracker is a thin dict keyed by field name.

### Task F6.6.1: FreshnessTracker + integration into `_on_state_update`

**Files:**
- Create: `custom_components/dreame_a2_mower/observability/freshness.py`
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (call tracker on every state mutation)
- Create: `tests/observability/test_freshness.py`

- [ ] **Step 1: Write the failing tests**

In `tests/observability/test_freshness.py`:

```python
"""Tests for the per-field freshness tracker."""

from __future__ import annotations

from dataclasses import dataclass

from custom_components.dreame_a2_mower.observability.freshness import FreshnessTracker


@dataclass
class _Probe:
    a: int | None = None
    b: int | None = None


def test_record_marks_fields_that_changed():
    tracker = FreshnessTracker()
    old = _Probe(a=None, b=None)
    new = _Probe(a=5, b=None)
    tracker.record(old, new, now_unix=1700000000)
    assert tracker.last_updated("a") == 1700000000
    assert tracker.last_updated("b") is None


def test_record_does_not_overwrite_unchanged_fields():
    tracker = FreshnessTracker()
    tracker.record(_Probe(a=None), _Probe(a=5), now_unix=1700000000)
    tracker.record(_Probe(a=5), _Probe(a=5, b=9), now_unix=1700000005)
    assert tracker.last_updated("a") == 1700000000  # unchanged
    assert tracker.last_updated("b") == 1700000005


def test_age_seconds_returns_none_for_never_updated():
    tracker = FreshnessTracker()
    assert tracker.age_seconds("a", now_unix=1700000000) is None


def test_age_seconds_computes_delta():
    tracker = FreshnessTracker()
    tracker.record(_Probe(a=None), _Probe(a=5), now_unix=1700000000)
    assert tracker.age_seconds("a", now_unix=1700000005) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_freshness.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the tracker**

In `custom_components/dreame_a2_mower/observability/freshness.py`:

```python
"""Per-field freshness tracker.

The coordinator calls ``record(old_state, new_state, now)`` on every
state mutation. The tracker compares the two dataclass instances field
by field and stamps any field whose value changed with ``now``. Used by
``sensor.dreame_a2_mower_data_freshness`` to surface staleness for the
user.

NO ``homeassistant.*`` imports — layer-2.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any


class FreshnessTracker:
    def __init__(self) -> None:
        self._last_updated: dict[str, int] = {}

    def record(self, old: Any, new: Any, now_unix: int) -> None:
        """Stamp every field whose value changed between ``old`` and ``new``."""
        if old is None or new is None:
            return
        for f in fields(new):
            old_val = getattr(old, f.name, None)
            new_val = getattr(new, f.name)
            if old_val != new_val:
                self._last_updated[f.name] = int(now_unix)

    def last_updated(self, field_name: str) -> int | None:
        return self._last_updated.get(field_name)

    def age_seconds(self, field_name: str, now_unix: int) -> int | None:
        ts = self._last_updated.get(field_name)
        if ts is None:
            return None
        return int(now_unix) - int(ts)

    def snapshot(self) -> dict[str, int]:
        return dict(self._last_updated)
```

- [ ] **Step 4: Wire into coordinator**

Read coordinator.py. Find `_on_state_update`. Add at the top of the constructor (next to `novel_registry`):

```python
from .observability.freshness import FreshnessTracker  # at module top

# in __init__:
self.freshness = FreshnessTracker()
```

In `_on_state_update`, after the new state is computed but before it's returned/published:

```python
self.freshness.record(self.data, new_state, now_unix=now)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_freshness.py tests/integration/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/observability/freshness.py custom_components/dreame_a2_mower/coordinator.py tests/observability/test_freshness.py && git commit -m "F6.6.1: per-field freshness tracker"
```

---

## Phase F6.7 — `sensor.dreame_a2_mower_data_freshness`

### Task F6.7.1: Diagnostic sensor exposes freshness map

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Modify: `custom_components/dreame_a2_mower/translations/en.json`
- Test: `tests/integration/test_sensor.py`

- [ ] **Step 1: Write the failing test**

```python
def test_freshness_sensor_state_is_oldest_age_seconds(coordinator):
    """The sensor's native_value is the AGE in seconds of the OLDEST
    tracked field — gives the user a single-number "how stale is the
    integration overall?" reading. The attribute dict has per-field
    ages."""
    coordinator.freshness._last_updated = {
        "battery_level": 1700000000,
        "state": 1700000005,
        "position_x_m": 1700000010,
    }
    sensor = build_data_freshness_sensor(coordinator)
    # now_unix mocked to 1700000020 via patch on time.time at the test entry
    with patch("custom_components.dreame_a2_mower.sensor.time.time", return_value=1700000020):
        value = sensor.native_value
    # oldest = battery_level at 1700000000, age = 20s
    assert value == 20
    with patch("custom_components.dreame_a2_mower.sensor.time.time", return_value=1700000020):
        attrs = sensor.extra_state_attributes
    assert attrs["battery_level_age_s"] == 20
    assert attrs["state_age_s"] == 15
    assert attrs["position_x_m_age_s"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_sensor.py -k freshness -v`
Expected: FAIL.

- [ ] **Step 3: Add the sensor description**

In `sensor.py` add (next to `novel_observations`):

```python
DreameA2MowerSensorEntityDescription(
    key="data_freshness",
    translation_key="data_freshness",
    native_unit_of_measurement="s",
    icon="mdi:clock-alert-outline",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,  # opt-in; chatty for debugging
    value_fn=_freshness_value,
    extra_state_attributes_fn=_freshness_attrs,
),
```

…with module-level helpers:

```python
import time

def _freshness_value(_state, *, ctx) -> int | None:
    snap = ctx.freshness.snapshot()
    if not snap:
        return None
    now = int(time.time())
    return now - min(snap.values())


def _freshness_attrs(_state, *, ctx) -> dict[str, int]:
    snap = ctx.freshness.snapshot()
    now = int(time.time())
    return {f"{name}_age_s": now - ts for name, ts in snap.items()}
```

- [ ] **Step 4: Add translations**

In `translations/en.json` `entity.sensor`:

```json
"data_freshness": {
    "name": "Data freshness"
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/translations/en.json tests/integration/test_sensor.py && git commit -m "F6.7.1: sensor.data_freshness diagnostic"
```

---

## Phase F6.8 — `sensor.api_endpoints_supported`

The cloud RPC layer (`cloud_client.action`) tracks which routed-action opcodes returned 80001 vs accepted. F6 surfaces this as a diagnostic so users can answer "does my mower understand op=X?" without grepping logs.

### Task F6.8.1: Cloud client exposes endpoint accept/reject log; sensor surfaces it

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` — track `_endpoint_log: dict[str, str]` keyed by opcode/method, value `"accepted"|"rejected_80001"|"error"`
- Modify: `custom_components/dreame_a2_mower/sensor.py` — new entity description
- Modify: `custom_components/dreame_a2_mower/translations/en.json`
- Test: `tests/integration/test_cloud_client.py` (or wherever cloud_client tests live — read the dir)
- Test: `tests/integration/test_sensor.py`

- [ ] **Step 1: Write the failing tests**

```python
# In test_cloud_client.py
async def test_action_records_accepted(mock_http_ok, cloud_client):
    await cloud_client.routed_action(siid=2, aiid=50, op=100, payload=[])
    assert cloud_client.endpoint_log["routed_action_op=100"] == "accepted"


async def test_action_records_80001(mock_http_80001, cloud_client):
    await cloud_client.routed_action(siid=2, aiid=50, op=999, payload=[])
    assert cloud_client.endpoint_log["routed_action_op=999"] == "rejected_80001"


# In test_sensor.py
def test_api_endpoints_supported_sensor(coordinator_with_endpoint_log):
    sensor = build_api_endpoints_sensor(coordinator_with_endpoint_log)
    assert sensor.native_value == 2  # count of "accepted"
    attrs = sensor.extra_state_attributes
    assert "routed_action_op=100" in attrs["accepted"]
    assert "routed_action_op=999" in attrs["rejected_80001"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/ -k api_endpoints -v`

- [ ] **Step 3: Implement endpoint_log in cloud_client.py**

Read the current `cloud_client.py` to find `routed_action` and `action`. Add `self.endpoint_log: dict[str, str] = {}` to `__init__`. After every routed-action HTTP response:

```python
key = f"routed_action_op={op}"
if response_code == 80001:
    self.endpoint_log[key] = "rejected_80001"
elif response_ok:
    self.endpoint_log[key] = "accepted"
else:
    self.endpoint_log[key] = "error"
```

(Adapt the conditional to match the actual response shape — read the file first.)

- [ ] **Step 4: Add the sensor description**

```python
DreameA2MowerSensorEntityDescription(
    key="api_endpoints_supported",
    translation_key="api_endpoints_supported",
    icon="mdi:api",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda _state, *, ctx: sum(
        1 for v in ctx.cloud.endpoint_log.values() if v == "accepted"
    ),
    extra_state_attributes_fn=lambda _state, *, ctx: {
        "accepted": sorted(k for k, v in ctx.cloud.endpoint_log.items() if v == "accepted"),
        "rejected_80001": sorted(k for k, v in ctx.cloud.endpoint_log.items() if v == "rejected_80001"),
        "error": sorted(k for k, v in ctx.cloud.endpoint_log.items() if v == "error"),
    },
),
```

(`ctx.cloud` is whatever attribute name the coordinator already uses for the cloud client — read coordinator.py to confirm. If it's `cloud_client`, use that.)

- [ ] **Step 5: Add translations**

```json
"api_endpoints_supported": {
    "name": "API endpoints supported"
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/cloud_client.py custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/translations/en.json tests/integration/ && git commit -m "F6.8.1: sensor.api_endpoints_supported + endpoint accept/reject log"
```

---

## Phase F6.9 — Recent NOVEL log-line buffer

`download_diagnostics` should include a tail of the most recent NOVEL log lines so a bug-report attachment is self-contained without the user having to manually grep.

### Task F6.9.1: Bounded ring buffer of NOVEL log lines

**Files:**
- Create: `custom_components/dreame_a2_mower/observability/log_buffer.py`
- Modify: `custom_components/dreame_a2_mower/__init__.py` — install a `logging.Handler` that pushes records matching any `LOG_NOVEL_*` prefix into the buffer; install during `async_setup_entry`, remove during `async_unload_entry`
- Test: `tests/observability/test_log_buffer.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the bounded NOVEL log-line ring buffer."""

from __future__ import annotations

import logging

from custom_components.dreame_a2_mower.observability.log_buffer import NovelLogBuffer


def test_buffer_records_matching_prefix():
    buf = NovelLogBuffer(maxlen=5, prefixes=("[NOVEL/property]",))
    handler = buf.as_handler()
    logger = logging.getLogger("test_logger_a")
    logger.addHandler(handler)
    logger.warning("[NOVEL/property] siid=99 piid=42")
    logger.warning("not novel: ignore me")
    lines = buf.lines()
    assert len(lines) == 1
    assert "siid=99" in lines[0]


def test_buffer_evicts_oldest_when_full():
    buf = NovelLogBuffer(maxlen=2, prefixes=("[NOVEL/value]",))
    handler = buf.as_handler()
    logger = logging.getLogger("test_logger_b")
    logger.addHandler(handler)
    logger.warning("[NOVEL/value] one")
    logger.warning("[NOVEL/value] two")
    logger.warning("[NOVEL/value] three")
    lines = buf.lines()
    assert len(lines) == 2
    assert "two" in lines[0]
    assert "three" in lines[1]


def test_buffer_matches_any_listed_prefix():
    buf = NovelLogBuffer(maxlen=10, prefixes=("[NOVEL/property]", "[NOVEL_KEY/session_summary]"))
    handler = buf.as_handler()
    logger = logging.getLogger("test_logger_c")
    logger.addHandler(handler)
    logger.warning("[NOVEL/property] x")
    logger.warning("[NOVEL_KEY/session_summary] y")
    logger.warning("[NOVEL/value] z")  # not in our list
    lines = buf.lines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/observability/test_log_buffer.py -v`

- [ ] **Step 3: Implement the buffer**

In `custom_components/dreame_a2_mower/observability/log_buffer.py`:

```python
"""Bounded ring buffer of NOVEL log lines for diagnostics dumps.

Wires into Python's ``logging`` framework via ``as_handler()``. The
returned handler filters records by message prefix and appends matching
lines to a ``collections.deque`` capped at ``maxlen``. A diagnostics
dump reads ``lines()`` to include the recent novelty trail without the
user having to grep their HA log file.

NO ``homeassistant.*`` imports — layer-2.
"""

from __future__ import annotations

import logging
from collections import deque


class NovelLogBuffer:
    def __init__(self, *, maxlen: int, prefixes: tuple[str, ...]) -> None:
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._prefixes = tuple(prefixes)

    def as_handler(self) -> logging.Handler:
        outer = self

        class _BufferHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                msg = record.getMessage()
                if any(msg.startswith(p) for p in outer._prefixes):
                    outer._buffer.append(msg)

        return _BufferHandler()

    def lines(self) -> list[str]:
        return list(self._buffer)
```

- [ ] **Step 4: Install the handler in `__init__.py`**

Read `custom_components/dreame_a2_mower/__init__.py`. In `async_setup_entry`, after the coordinator is built:

```python
from .observability.log_buffer import NovelLogBuffer
from .const import LOG_NOVEL_PROPERTY, LOG_NOVEL_VALUE, LOG_NOVEL_KEY, LOG_NOVEL_KEY_SESSION_SUMMARY

novel_log = NovelLogBuffer(
    maxlen=200,
    prefixes=(
        LOG_NOVEL_PROPERTY,
        LOG_NOVEL_VALUE,
        LOG_NOVEL_KEY,
        LOG_NOVEL_KEY_SESSION_SUMMARY,
    ),
)
handler = novel_log.as_handler()
LOGGER.parent.addHandler(handler) if LOGGER.parent else logging.getLogger().addHandler(handler)
coordinator.novel_log = novel_log
coordinator._novel_log_handler = handler
```

In `async_unload_entry`:

```python
handler = getattr(coordinator, "_novel_log_handler", None)
if handler is not None:
    logging.getLogger().removeHandler(handler)
```

(Adapt to whatever logger structure `__init__.py` already uses. The integration's package logger is `logging.getLogger("custom_components.dreame_a2_mower")` — install on that, not the root logger, to avoid catching unrelated logs.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/observability/log_buffer.py custom_components/dreame_a2_mower/__init__.py tests/observability/test_log_buffer.py && git commit -m "F6.9.1: NOVEL log-line ring buffer"
```

---

## Phase F6.10 — `download_diagnostics`

### Task F6.10.1: diagnostics handler with redaction

**Files:**
- Create: `custom_components/dreame_a2_mower/diagnostics.py`
- Modify: `custom_components/dreame_a2_mower/manifest.json` — add `"diagnostics": "diagnostics"` if HA's manifest format requires it (check the manifest first; modern versions discover by filename alone)
- Test: `tests/integration/test_diagnostics.py`

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_diagnostics.py`:

```python
"""Tests for the download_diagnostics handler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.diagnostics import (
    REDACTION_KEYS,
    async_get_config_entry_diagnostics,
    redact,
)


def test_redact_replaces_listed_keys():
    payload = {"username": "alice", "password": "p@ss", "did": "x123", "other": "ok"}
    out = redact(payload)
    assert out["username"] == "**REDACTED**"
    assert out["password"] == "**REDACTED**"
    assert out["did"] == "**REDACTED**"
    assert out["other"] == "ok"


def test_redact_handles_nested_dicts():
    payload = {"creds": {"password": "x", "country": "NO"}}
    out = redact(payload)
    assert out["creds"]["password"] == "**REDACTED**"
    assert out["creds"]["country"] == "NO"


def test_redaction_keys_match_spec_section_5_9():
    # Spec §5.9 lists: username, password, token, did, mac.
    # Country is not redacted (not a credential).
    expected = {"username", "password", "token", "did", "mac"}
    assert expected.issubset(set(REDACTION_KEYS))


@pytest.mark.asyncio
async def test_diagnostics_dump_includes_required_sections(coordinator_with_data):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"username": "alice", "password": "p", "host": "1.2.3.4"}
    hass.data = {
        "dreame_a2_mower": {entry.entry_id: coordinator_with_data},
    }
    out = await async_get_config_entry_diagnostics(hass, entry)
    assert "config_entry" in out
    assert out["config_entry"]["password"] == "**REDACTED**"
    assert "state" in out
    assert "capabilities" in out
    assert "novel_observations" in out
    assert "freshness" in out
    assert "endpoint_log" in out
    assert "recent_novel_log_lines" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_diagnostics.py -v`

- [ ] **Step 3: Implement diagnostics.py**

In `custom_components/dreame_a2_mower/diagnostics.py`:

```python
"""Diagnostics dump for HA's download_diagnostics button.

Returns a dict with redacted credentials so users can attach the file
to bug reports without leaking secrets. Spec §5.9 lists the redaction
keys: username, password, token, did, mac.

Sections in the dump:
- config_entry         (redacted)
- state                (MowerState as dict)
- capabilities         (Capabilities dataclass as dict)
- novel_observations   (registry snapshot)
- freshness            (per-field last_updated map)
- endpoint_log         (cloud RPC accept/reject map)
- recent_novel_log_lines (tail of NOVEL log warnings)
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACTION_KEYS: tuple[str, ...] = ("username", "password", "token", "did", "mac")


def redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            k: ("**REDACTED**" if k in REDACTION_KEYS else redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def _as_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    snap = coordinator.novel_registry.snapshot()
    return {
        "config_entry": redact(dict(entry.data)),
        "state": _as_dict(coordinator.data),
        "capabilities": _as_dict(getattr(coordinator, "capabilities", None)),
        "novel_observations": [
            {
                "category": o.category,
                "detail": o.detail,
                "first_seen_unix": o.first_seen_unix,
            }
            for o in snap.observations
        ],
        "freshness": coordinator.freshness.snapshot(),
        "endpoint_log": dict(getattr(coordinator.cloud, "endpoint_log", {})),
        "recent_novel_log_lines": coordinator.novel_log.lines(),
    }
```

(`coordinator.cloud` may be named differently — read coordinator.py to confirm.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/diagnostics.py tests/integration/test_diagnostics.py && git commit -m "F6.10.1: download_diagnostics handler with credential redaction"
```

---

## Phase F6.11 — Documentation

### Task F6.11.1: docs/observability.md — what fires what + how to read the surface

**Files:**
- Create: `docs/observability.md`

- [ ] **Step 1: Write the doc**

Content:

```markdown
# Observability surface — F6

This file documents what the integration self-reports about itself.
Use it to debug or to file a clean bug report.

## Diagnostic sensors

| Entity | What |
|---|---|
| `sensor.novel_observations` | Count of unfamiliar protocol shapes seen this process. Attribute `observations` lists each: category (`property` / `value` / `event` / `key`), detail string, first-seen unix timestamp. |
| `sensor.dreame_a2_mower_data_freshness` | Age in seconds of the OLDEST tracked field. Attributes: per-field age in seconds. |
| `sensor.api_endpoints_supported` | Count of routed-action opcodes the cloud accepted. Attributes: `accepted`, `rejected_80001`, `error` lists by op key. |
| `sensor.archived_sessions_count` | (from F4) total archived session entries on disk. |

## Log prefixes that mean something

| Prefix | Triggers when |
|---|---|
| `[NOVEL/property]` | A property push arrived for an `(siid, piid)` slot the integration doesn't recognize. Once per slot per process. |
| `[NOVEL/value]` | A property push arrived with a value the integration has never seen for a known slot. Once per `(siid, piid, value)` per process. |
| `[NOVEL_KEY/session_summary]` | The OSS session-summary JSON contained a key not in the parser's schema. Once per key per process. |

## Downloading a diagnostics dump

Settings → Devices & Services → Dreame A2 Mower → "Download Diagnostics".

The dump is JSON with these top-level keys:
- `config_entry` — config entry data with creds redacted (`username`, `password`, `token`, `did`, `mac`)
- `state` — a snapshot of `MowerState` at dump time
- `capabilities` — fixed g2408 capabilities
- `novel_observations` — list from the registry
- `freshness` — `{field_name: last_updated_unix}`
- `endpoint_log` — `{routed_action_op=N: "accepted"|"rejected_80001"|"error"}`
- `recent_novel_log_lines` — tail of NOVEL log lines (capped at 200)

Attach this file to bug reports; everything sensitive is redacted.
```

- [ ] **Step 2: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add docs/observability.md && git commit -m "F6.11.1: observability docs"
```

---

## Phase F6.12 — Final wire-in + sweep + tag

### Task F6.12.1: Sanity sweep + tag v0.6.0a0

**Files:**
- (none new)

- [ ] **Step 1: Verify layering invariant**

Run: `grep -rn "from homeassistant\|import homeassistant" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/observability/`
Expected: empty.

Run: `grep -rn "from homeassistant\|import homeassistant" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/{mower,live_map,archive}/`
Expected: empty.

- [ ] **Step 2: Smoke-compile every Python file**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m compileall -q custom_components/dreame_a2_mower/ protocol/`
Expected: empty output.

- [ ] **Step 3: Final pytest sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: ALL tests pass. Baseline before F6 was 520 / 4 skipped. F6 adds approximately 25–30 new tests; expect ~545+ passing.

- [ ] **Step 4: Commit any final cleanup, then tag v0.6.0a0**

If the sweep is clean, no commit needed; just tag:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git tag v0.6.0a0
```

(If sweeping found issues, fix them, commit, then tag.)

Do NOT push. The controller pushes commit + tag.

---

## Self-review checklist

- [ ] `protocol/unknown_watchdog.py` is reused, not rewritten.
- [ ] `observability/registry.py`, `schemas.py`, `freshness.py`, `log_buffer.py` have NO `homeassistant.*` imports.
- [ ] Every NOVEL log call uses one of the `LOG_NOVEL_*` constants from `const.py`.
- [ ] `[NOVEL/property]`, `[NOVEL/value]`, `[NOVEL_KEY/session_summary]` each fire ONCE per token per process (test-asserted via dupe calls).
- [ ] `sensor.novel_observations` count matches `coordinator.novel_registry.snapshot().count`.
- [ ] `sensor.dreame_a2_mower_data_freshness` reports the AGE of the oldest tracked field as native_value, with per-field ages in attributes.
- [ ] `sensor.api_endpoints_supported` distinguishes accepted / rejected_80001 / error.
- [ ] `download_diagnostics` redacts username, password, token, did, mac (spec §5.9 list).
- [ ] `download_diagnostics` includes state + capabilities + novel_observations + freshness + endpoint_log + recent_novel_log_lines.
- [ ] All disk reads/writes still go through `hass.async_add_executor_job` (F6 adds none).
- [ ] All previously-passing tests still pass.
- [ ] v0.6.0a0 tag created.

## What this plan does NOT do

Out-of-scope for F6:
- F7: LiDAR popout entity pair, WebGL Lovelace card, dashboard YAML redesign, cutover from legacy.
- Active probing of the cloud for which endpoints exist (the endpoint_log is *passive* — it learns from real attempts, doesn't poll).
- Auto-reporting (telemetry to a remote service). The user stays in control; downloading the diagnostics file is always opt-in.
- Fixing protocol gaps that the registry surfaces. F6 makes them visible; subsequent F7 + post-cutover work fixes them.
