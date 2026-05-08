# Cloud-Write Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert all 15 SETTINGS-driven entities + the AI_HUMAN switch from read-only-with-placeholder to real read/write via the Dreame Cloud `setDeviceData` endpoint, add a SCHEDULE custom-card edit surface, and revise the SCHEDULE decoder to support variable-length records (Zone + Edge plans currently break the read path).

**Architecture:** Three-layer write infrastructure: (1) `cloud_client.write_chunked_key` handles chunking + the `setDeviceData` HTTP call; (2) coordinator-side per-domain helpers (`write_settings`, `write_schedule`, `write_ai_human_enabled`) wrap RMW + the chunker behind a single `_chunked_write_lock`; (3) entity layer adopts an optimistic-update + revert-on-failure pattern with `persistent_notification` on rejection.

**Tech Stack:** Python 3.13+, Home Assistant Core, `dataclasses` for immutable state, `asyncio.Lock` for write serialization, vanilla JS (no build step) for the custom Lovelace card.

**Spec:** `docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`

---

## File Structure

| Path | Responsibility | Touched in |
|---|---|---|
| `custom_components/dreame_a2_mower/cloud_state.py` | `SchedulePlan` + `ScheduleSlot` dataclasses (add `zone_id`, `extra_bytes`) | Task 1 |
| `custom_components/dreame_a2_mower/protocol/schedule.py` | Variable-length decoder + encoder; new helper `build_schedule_set_value` already exists | Tasks 1, 2 |
| `custom_components/dreame_a2_mower/cloud_client.py` | `write_chunked_key` (new) + `set_batch_device_datas` (already fixed) | Task 3 |
| `custom_components/dreame_a2_mower/coordinator.py` | `_chunked_write_lock`, `write_settings`, rewire `write_schedule` + `write_ai_human_enabled` to use chunker; later: delete `_write_setting_placeholder` | Tasks 4-7, 19 |
| `custom_components/dreame_a2_mower/number.py` | Optimistic-update + revert; rename per app; delete `DreameA2ObstacleAvoidanceAiNumber` | Tasks 8, 12, 13 |
| `custom_components/dreame_a2_mower/switch.py` | Same pattern + AI_HUMAN rewire/rename + 3 new AI Recognition switches | Tasks 9, 11, 13 |
| `custom_components/dreame_a2_mower/select.py` | Same pattern + Mowing Pattern label revision | Tasks 10, 12 |
| `custom_components/dreame_a2_mower/sensor.py` | `DreameA2ScheduleCountSensor` exposes `zone_id` + action labels | Task 14 |
| `custom_components/dreame_a2_mower/services.py` + `services.yaml` | New `set_schedule_plans` service | Task 15 |
| `dashboards/cards/dreame-a2-schedule-card.js` (NEW) | Custom Lovelace card | Tasks 16, 17 |
| `dashboards/mower/dashboard.yaml` | Reference new card via `lovelace_resources` | Task 18 |
| `docs/research/g2408-research-journal.md` | Update SCHEDULE blob section, mark systemic finding RESOLVED | Task 20 |
| `docs/research/cloud-write-reference.md` (NEW) | General "how to read/write cloud state" reference | Task 20 |
| `docs/TODO.md` | Close 3 entries; mark MAP write as Phase 2 | Task 20 |
| `manifest.json` (via `tools/release.sh`) | Version bump | Task 21 |

---

## Task 1: Variable-length SCHEDULE decoder + dataclass extension

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_state.py` (add fields to `SchedulePlan`)
- Modify: `custom_components/dreame_a2_mower/protocol/schedule.py` (rewrite `_decode_blob`)
- Modify: `tests/protocol/test_schedule.py` (live-data fixtures for Zone + Edge)

**Reference real cloud bytes (verified live 2026-05-08, slot 0 'Spr & Sum Schedule', v=33438):**

```
hex: aa 07 10 de 01 00 ed
     aa 07 10 1a 04 00 ed
     aa 07 30 de 01 00 ed
     aa 08 31 c0 13 00 01 ed   ← Wed 16:00 Zone, zone_id=1
     aa 07 50 e0 01 00 ed
     aa 09 62 74 24 00 01 00 ed   ← Sat 19:00 Edge, zone_id=1, reserved2=0
base64 (full slot 0): qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqggxwBMAAe2qB1DgAQDtqglidCQAAQDt
```

Record layout summary:
- byte 0: 0xAA
- byte 1: total length (7 / 8 / 9)
- byte 2: high nibble = weekday (1-7), low nibble = action (0/1/2)
- byte 3: time_lo
- byte 4: high nibble = action again (redundant — likely format discriminator), low nibble = time_hi
- byte 5: reserved (0x00 in observed)
- byte 6: 0xED (All-area) OR zone_id (Zone/Edge)
- byte 7: 0xED (Zone) OR reserved2 0x00 (Edge)
- byte 8: 0xED (Edge only)

- [ ] **Step 1: Extend the `SchedulePlan` dataclass**

In `custom_components/dreame_a2_mower/cloud_state.py`, find the existing `SchedulePlan` definition and replace it with:

```python
@dataclass(frozen=True, slots=True)
class SchedulePlan:
    """One scheduled mow within a ScheduleSlot.

    A plan triggers a mow at `time_min` (minute-of-day, 0..1439) on every
    weekday whose bit is set in `weekday_mask` (bit 0 = Mon, bit 6 = Sun).
    `action_type`: 0 = All-area, 1 = Zone, 2 = Edge.

    `zone_id` is set for Zone (action=1) and Edge (action=2) plans (the
    target zone in the active map's mowing-zone list); None for All-area.

    `extra_bytes` preserves any trailing bytes the wire format includes
    that we don't yet fully decode (Edge has 1 trailing reserved byte).
    Lets the encoder round-trip byte-identical even when semantics are
    not fully known.
    """

    time_min: int
    weekday_mask: int
    action_type: int
    zone_id: int | None = None
    extra_bytes: bytes = b""
```

- [ ] **Step 2: Write the failing decoder tests**

Replace the existing `test_parse_real_blob_*` tests in `tests/protocol/test_schedule.py` with new ones that include the live Zone + Edge data:

```python
def test_decode_real_slot0_with_zone_and_edge():
    """Live slot 0 from 2026-05-08 — 6 records, 5 plans (Mon+Wed coalesce)."""
    raw = {
        "d": [[0, 0, "Spr & Sum Schedule",
               "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqggxwBMAAe2qB1DgAQDtqglidCQAAQDt"]],
        "v": 1,
    }
    plans = parse_schedule_batch(raw).slots[0].plans
    assert plans == (
        SchedulePlan(time_min=7*60+58, weekday_mask=MON|WED, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=17*60+30, weekday_mask=MON, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=16*60, weekday_mask=WED, action_type=1,
                     zone_id=1, extra_bytes=b""),
        SchedulePlan(time_min=8*60, weekday_mask=FRI, action_type=0,
                     zone_id=None, extra_bytes=b""),
        SchedulePlan(time_min=19*60, weekday_mask=SAT, action_type=2,
                     zone_id=1, extra_bytes=b"\x00"),
    )


def test_decode_skips_record_with_bad_length_byte():
    """A record with len < 7 or len > 16 is rejected (whole slot drops)."""
    import base64
    bad = base64.b64encode(b"\xaa\x05\x10\xde\x01\xed").decode()  # len=5 too short
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()


def test_decode_skips_zone_with_bad_terminator():
    """Zone record (len=8) with non-ED at byte 7 is rejected."""
    import base64
    bad = base64.b64encode(b"\xaa\x08\x31\xc0\x13\x00\x01\xff").decode()
    raw = {"d": [[0, 0, "Bad", bad]], "v": 1}
    assert parse_schedule_batch(raw).slots[0].plans == ()
```

- [ ] **Step 3: Run, verify the new test fails**

Run: `python -m pytest tests/protocol/test_schedule.py::test_decode_real_slot0_with_zone_and_edge -v`
Expected: FAIL with mismatched plans (current decoder breaks on Zone/Edge).

- [ ] **Step 4: Rewrite `_decode_blob`**

In `custom_components/dreame_a2_mower/protocol/schedule.py`, replace the existing `_decode_blob` function with:

```python
_VALID_LEN = (7, 8, 9)
_ACTION_LEN = {0: 7, 1: 8, 2: 9}


def _decode_one_record(rec: bytes) -> tuple[int, int, int, int | None, bytes] | None:
    """Decode one variable-length record into (time_min, weekday, action, zone_id, extra_bytes).

    Returns None if the record is malformed (caller drops the whole slot).
    """
    if len(rec) not in _VALID_LEN:
        return None
    rec_len = rec[1]
    if rec_len != len(rec):
        return None
    if rec[0] != _RECORD_START or rec[-1] != _RECORD_END:
        return None
    weekday = rec[2] >> 4
    action = rec[2] & 0x0F
    if not (1 <= weekday <= 7):
        return None
    if action not in _ACTION_LEN or _ACTION_LEN[action] != rec_len:
        return None
    time_min = rec[3] | ((rec[4] & 0x0F) << 8)
    if not (0 <= time_min <= 1439):
        return None
    zone_id: int | None = None
    extra_bytes = b""
    if action == 0:
        # All-area: 7 bytes total. Byte 5 is reserved; no zone_id.
        pass
    elif action == 1:
        # Zone: 8 bytes. Byte 5 reserved, byte 6 is zone_id.
        zone_id = rec[6]
    elif action == 2:
        # Edge: 9 bytes. Byte 5 reserved, byte 6 is zone_id, byte 7 reserved2.
        zone_id = rec[6]
        extra_bytes = bytes([rec[7]])
    return (time_min, weekday, action, zone_id, extra_bytes)


def _decode_blob(blob_b64: str) -> tuple[SchedulePlan, ...]:
    """Decode one slot's base64 blob into a tuple of SchedulePlans.

    Variable-length records (7/8/9 bytes by action_type). All-area=0,
    Zone=1, Edge=2. Returns () on any malformed input (logs once).
    """
    if not blob_b64:
        return ()
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except (ValueError, binascii.Error) as ex:
        _LOGGER.warning("schedule: bad base64 in slot blob: %s", ex)
        return ()
    parsed: list[tuple[int, int, int, int | None, bytes]] = []
    i = 0
    while i < len(raw):
        if raw[i] != _RECORD_START:
            _LOGGER.warning("schedule: byte %d is 0x%02x, expected 0xAA",
                            i, raw[i])
            return ()
        rec_len = raw[i + 1] if i + 1 < len(raw) else 0
        if rec_len not in _VALID_LEN or i + rec_len > len(raw):
            _LOGGER.warning("schedule: bad record len 0x%02x at offset %d",
                            rec_len, i)
            return ()
        rec = raw[i:i + rec_len]
        decoded = _decode_one_record(rec)
        if decoded is None:
            _LOGGER.warning("schedule: malformed record at offset %d: %s",
                            i, rec.hex())
            return ()
        parsed.append(decoded)
        i += rec_len
    # Group records by (action, time, zone_id, extra_bytes); union weekday bits.
    plans_by_key: dict[tuple, int] = {}
    plan_order: list[tuple] = []
    for time_min, weekday, action, zone_id, extra_bytes in parsed:
        key = (action, time_min, zone_id, extra_bytes)
        if key not in plans_by_key:
            plans_by_key[key] = 0
            plan_order.append(key)
        plans_by_key[key] |= 1 << (weekday - 1)
    return tuple(
        SchedulePlan(
            time_min=key[1],
            weekday_mask=plans_by_key[key],
            action_type=key[0],
            zone_id=key[2],
            extra_bytes=key[3],
        )
        for key in plan_order
    )
```

- [ ] **Step 5: Run all schedule tests**

Run: `python -m pytest tests/protocol/test_schedule.py -v`
Expected: All pass — new live-data tests + existing defensive tests.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_state.py \
        custom_components/dreame_a2_mower/protocol/schedule.py \
        tests/protocol/test_schedule.py
git commit -m "fix(schedule): variable-length record decoder; SchedulePlan zone_id + extra_bytes"
```

---

## Task 2: Variable-length encoder

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/schedule.py` (rewrite `encode_schedule_blob`)
- Modify: `tests/protocol/test_schedule.py` (round-trip test against the live blob)

- [ ] **Step 1: Write the failing round-trip test**

Append to `tests/protocol/test_schedule.py`:

```python
def test_encode_real_slot0_byte_identical():
    """Encoder must produce the exact same base64 the cloud emits, for the
    full slot 0 with All-area + Zone + Edge plans (live 2026-05-08)."""
    plans = (
        SchedulePlan(time_min=7*60+58, weekday_mask=MON|WED, action_type=0),
        SchedulePlan(time_min=17*60+30, weekday_mask=MON, action_type=0),
        SchedulePlan(time_min=16*60, weekday_mask=WED, action_type=1, zone_id=1),
        SchedulePlan(time_min=8*60, weekday_mask=FRI, action_type=0),
        SchedulePlan(time_min=19*60, weekday_mask=SAT, action_type=2,
                     zone_id=1, extra_bytes=b"\x00"),
    )
    expected = "qgcQ3gEA7aoHEBoEAO2qBzDeAQDtqggxwBMAAe2qB1DgAQDtqglidCQAAQDt"
    assert encode_schedule_blob(plans) == expected


def test_encode_zone_requires_zone_id():
    """Encoding a Zone (action=1) plan without zone_id raises."""
    plans = (SchedulePlan(time_min=600, weekday_mask=MON, action_type=1, zone_id=None),)
    try:
        encode_schedule_blob(plans)
    except ValueError:
        return
    raise AssertionError("expected ValueError for Zone plan without zone_id")
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_schedule.py::test_encode_real_slot0_byte_identical -v`
Expected: FAIL — encoder hardcodes 7-byte records, can't emit Zone/Edge.

- [ ] **Step 3: Rewrite `encode_schedule_blob`**

Replace the existing function:

```python
def encode_schedule_blob(plans: tuple[SchedulePlan, ...]) -> str:
    """Encode a tuple of SchedulePlans back into the base64 wire blob.

    Each plan emits one variable-length record per weekday in its mask
    (7 bytes for All-area, 8 for Zone, 9 for Edge). Records are sorted
    by (weekday_asc, time_asc) to match the cloud's emit order.
    """
    if not plans:
        return ""
    # Validate all plans before emitting any bytes.
    for plan in plans:
        if not (0 <= plan.time_min <= 1439):
            raise ValueError(f"time_min {plan.time_min} out of range 0..1439")
        if plan.action_type not in _ACTION_LEN:
            raise ValueError(f"action_type {plan.action_type} not in {{0,1,2}}")
        if plan.action_type in (1, 2) and plan.zone_id is None:
            raise ValueError(
                f"action_type {plan.action_type} requires zone_id (got None)"
            )
        if not (0 < plan.weekday_mask <= 0x7F):
            raise ValueError(
                f"weekday_mask 0x{plan.weekday_mask:x} must have bits 0..6"
            )
        if plan.action_type == 2 and len(plan.extra_bytes) != 1:
            raise ValueError(
                f"Edge plan needs exactly 1 extra byte (got {len(plan.extra_bytes)})"
            )
    # Expand → (weekday_idx, time_min, action_type, zone_id, extra_bytes).
    triples: list[tuple[int, int, int, int | None, bytes]] = []
    for plan in plans:
        for weekday_idx in range(7):
            if plan.weekday_mask & (1 << weekday_idx):
                triples.append((
                    weekday_idx, plan.time_min, plan.action_type,
                    plan.zone_id, plan.extra_bytes,
                ))
    triples.sort(key=lambda t: (t[0], t[1]))
    out = bytearray()
    for weekday_idx, time_min, action, zone_id, extra in triples:
        rec_len = _ACTION_LEN[action]
        day_byte = ((weekday_idx + 1) << 4) | (action & 0x0F)
        time_lo = time_min & 0xFF
        time_hi = (time_min >> 8) & 0x0F
        # Byte 4 high nibble carries action again (redundant, format
        # discriminator — matches cloud's emit byte-exact).
        byte4 = (action << 4) | time_hi
        rec = [_RECORD_START, rec_len, day_byte, time_lo, byte4, 0x00]
        if action == 1:
            rec.append(zone_id & 0xFF)  # type: ignore[operator]
        elif action == 2:
            rec.append(zone_id & 0xFF)  # type: ignore[operator]
            rec.append(extra[0])
        rec.append(_RECORD_END)
        assert len(rec) == rec_len, f"emit len {len(rec)} != expected {rec_len}"
        out.extend(rec)
    return base64.b64encode(bytes(out)).decode("ascii")
```

- [ ] **Step 4: Run all schedule tests**

Run: `python -m pytest tests/protocol/test_schedule.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule.py tests/protocol/test_schedule.py
git commit -m "feat(schedule): variable-length encoder for Zone + Edge plans"
```

---

## Task 3: `cloud_client.write_chunked_key`

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` (add new method)
- Create: `tests/protocol/test_cloud_chunker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/protocol/test_cloud_chunker.py`:

```python
"""Tests for cloud_client.write_chunked_key — chunking + endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client() -> DreameA2CloudClient:
    client = object.__new__(DreameA2CloudClient)
    client._did = "test_did"
    client.set_batch_device_datas = MagicMock(
        return_value={"code": 0, "success": True, "msg": "ok"}
    )
    return client


def test_write_chunked_key_short_value_single_chunk_no_info():
    """Values ≤ 1024 chars emit a single .0 chunk with no .info field."""
    client = _make_client()
    ok, resp = client.write_chunked_key("AI_HUMAN", '"true"')
    assert ok is True
    client.set_batch_device_datas.assert_called_once_with(
        {"AI_HUMAN.0": '"true"'}
    )


def test_write_chunked_key_long_value_chunks_with_info():
    """Values > 1024 chars split into ≤1024 chunks + .info field."""
    client = _make_client()
    value = "x" * 1500  # → chunk 0 of 1024 + chunk 1 of 476 + info=1500
    ok, resp = client.write_chunked_key("SETTINGS", value)
    assert ok is True
    expected = {
        "SETTINGS.0": "x" * 1024,
        "SETTINGS.1": "x" * 476,
        "SETTINGS.info": "1500",
    }
    client.set_batch_device_datas.assert_called_once_with(expected)


def test_write_chunked_key_exactly_1024_chars_single_chunk():
    """Boundary: value of exactly 1024 chars fits in one chunk."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "x" * 1024)
    client.set_batch_device_datas.assert_called_once_with({"KEY.0": "x" * 1024})


def test_write_chunked_key_1025_chars_two_chunks():
    """Boundary: 1025 chars → chunk 0 of 1024 + chunk 1 of 1."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "x" * 1025)
    client.set_batch_device_datas.assert_called_once_with({
        "KEY.0": "x" * 1024,
        "KEY.1": "x",
        "KEY.info": "1025",
    })


def test_write_chunked_key_explicit_info_override():
    """Caller can pass info= for keys where .info isn't total length."""
    client = _make_client()
    ok, _ = client.write_chunked_key("M_PATH", "abc", info="0")
    client.set_batch_device_datas.assert_called_once_with({
        "M_PATH.0": "abc",
        "M_PATH.info": "0",
    })


def test_write_chunked_key_returns_false_on_cloud_rejection():
    """code != 0 from cloud → ok=False, response preserved for caller."""
    client = _make_client()
    client.set_batch_device_datas = MagicMock(
        return_value={"code": 10007, "success": False, "msg": "bad value"}
    )
    ok, resp = client.write_chunked_key("KEY", "v")
    assert ok is False
    assert resp == {"code": 10007, "success": False, "msg": "bad value"}


def test_write_chunked_key_returns_false_on_none_response():
    client = _make_client()
    client.set_batch_device_datas = MagicMock(return_value=None)
    ok, resp = client.write_chunked_key("KEY", "v")
    assert ok is False
    assert resp is None


def test_write_chunked_key_empty_value_writes_single_empty_chunk():
    """Writing empty string → KEY.0 = '' (used to clear a slot)."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "")
    client.set_batch_device_datas.assert_called_once_with({"KEY.0": ""})
```

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/protocol/test_cloud_chunker.py -v`
Expected: FAIL — `AttributeError: 'DreameA2CloudClient' object has no attribute 'write_chunked_key'`.

- [ ] **Step 3: Add `write_chunked_key`**

In `custom_components/dreame_a2_mower/cloud_client.py`, add this method immediately after `set_batch_device_datas`:

```python
    def write_chunked_key(
        self,
        key_prefix: str,
        value: str,
        info: str | None = None,
    ) -> "tuple[bool, dict | None]":
        """Write a chunked-batch value to the cloud via setDeviceData.

        Splits `value` into ≤1024-char chunks (server-enforced cap),
        builds {key_prefix.0..N + key_prefix.info?}, calls
        set_batch_device_datas. Returns (ok, raw_response).

        `info` defaults to str(len(value)) when chunking is needed; for
        single-chunk writes (value ≤ 1024 chars) `.info` is omitted to
        match the AI_HUMAN.0 / SCHEDULE.0 single-chunk pattern observed
        live. Callers writing keys where `.info` carries something else
        (M_PATH offset, MAP split point) can pass `info=` explicitly.
        """
        CHUNK = 1024
        if len(value) <= CHUNK and info is None:
            payload = {f"{key_prefix}.0": value}
        else:
            chunks = [value[i:i + CHUNK] for i in range(0, len(value), CHUNK)] or [""]
            payload = {f"{key_prefix}.{i}": chunk for i, chunk in enumerate(chunks)}
            payload[f"{key_prefix}.info"] = info if info is not None else str(len(value))
        result = self.set_batch_device_datas(payload)
        ok = (
            isinstance(result, dict)
            and (result.get("success") is True or result.get("code") == 0)
        )
        return ok, result if isinstance(result, dict) else None
```

- [ ] **Step 4: Run the new tests + full suite**

```
python -m pytest tests/protocol/test_cloud_chunker.py -v
python -m pytest -q
```

Expected: 8 new tests pass, no regressions.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py tests/protocol/test_cloud_chunker.py
git commit -m "feat(cloud-client): write_chunked_key — chunked-batch write helper"
```

---

## Task 4: Coordinator `_chunked_write_lock` mutex

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (add lock to `__init__`)

- [ ] **Step 1: Write the failing test**

Append to a new file `tests/integration/test_coordinator_writes.py`:

```python
"""Tests for coordinator-level write helpers + mutex."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock


def test_coordinator_init_declares_chunked_write_lock():
    """Regex check that __init__ creates self._chunked_write_lock as Lock()."""
    src = Path("custom_components/dreame_a2_mower/coordinator.py").read_text()
    assert re.search(
        r"self\._chunked_write_lock\s*:\s*asyncio\.Lock\s*=\s*asyncio\.Lock\(\)",
        src,
    ), "coordinator.__init__ should declare self._chunked_write_lock"
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_coordinator_writes.py::test_coordinator_init_declares_chunked_write_lock -v
```

Expected: FAIL — lock not declared.

- [ ] **Step 3: Add the lock to `__init__`**

In `custom_components/dreame_a2_mower/coordinator.py`, find the existing block adding the four PNG cache slots (search for `self._main_view_png: bytes | None = None`). Immediately AFTER the `self._active_map_base_md5: str | None = None` line, add:

```python
        # Single coordinator-wide mutex serializing all chunked-batch
        # cloud writes (SETTINGS / SCHEDULE / AI_HUMAN). Each per-domain
        # helper acquires this around the read-modify-write sequence so
        # two near-simultaneous entity writes can't race on the same blob.
        # Hold time per write is sub-second; cross-blob writes are rare
        # so a single mutex (vs per-blob) keeps reasoning simple.
        self._chunked_write_lock: asyncio.Lock = asyncio.Lock()
```

If `import asyncio` is not already at the top of `coordinator.py`, add it. Verify with: `grep -n "^import asyncio" custom_components/dreame_a2_mower/coordinator.py` — if zero matches, add `import asyncio` near the other stdlib imports (around line 10).

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_coordinator_writes.py::test_coordinator_init_declares_chunked_write_lock -v
python -m pytest -q
```

Expected: New test passes; no regressions.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator_writes.py
git commit -m "feat(coordinator): add _chunked_write_lock mutex for cloud writes"
```

---

## Task 5: `coordinator.write_settings(map_id, field, value)`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (add new helper)
- Modify: `tests/integration/test_coordinator_writes.py` (RMW + lock + rollback tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_coordinator_writes.py`:

```python
def _make_coord_for_settings_write():
    """Build a coordinator stub with cloud_state.settings populated."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    # Make hass.async_add_executor_job actually call the function inline.
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    raw = [
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
    ]
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=raw,
            by_map_id_canonical={
                0: raw[0]["settings"]["0"],
                1: raw[0]["settings"]["1"],
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, locn=None, dock={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    coord._refresh_cloud_state = MagicMock(
        return_value=asyncio.Future()
    )
    coord._refresh_cloud_state.return_value.set_result(None)
    return coord


def test_write_settings_modifies_entry0_and_chunks():
    """write_settings does RMW + writes via cloud_client.write_chunked_key."""
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is True
    # Verify write_chunked_key called with serialized SETTINGS having the
    # new mowingHeight on entry 0, map "0".
    args, _ = coord._cloud.write_chunked_key.call_args
    key_prefix, value = args[0], args[1]
    assert key_prefix == "SETTINGS"
    import json
    parsed = json.loads(value)
    assert parsed[0]["settings"]["0"]["mowingHeight"] == 7
    # Other map untouched on entry 0
    assert parsed[0]["settings"]["1"]["mowingHeight"] == 6
    # Entry 1 untouched
    assert parsed[1]["settings"]["0"]["mowingHeight"] == 5


def test_write_settings_returns_false_on_cloud_rejection():
    coord = _make_coord_for_settings_write()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(False, {"code": 10007, "msg": "rejected"})
    )
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is False


def test_write_settings_unknown_map_id_returns_false():
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=99, field="mowingHeight", value=7))
    assert ok is False
    coord._cloud.write_chunked_key.assert_not_called()
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_coordinator_writes.py -v
```

Expected: FAIL — `write_settings` not defined.

- [ ] **Step 3: Add the helper**

In `custom_components/dreame_a2_mower/coordinator.py`, immediately after `write_ai_human_enabled` (search for `async def write_ai_human_enabled`), add:

```python
    async def write_settings(self, *, map_id: int, field: str, value: Any) -> bool:
        """Push one SETTINGS field change to the cloud.

        Read-modify-write on cloud_state.settings.raw entry 0's [map_id]
        sub-dict. Entry 1 (and any beyond) is preserved unchanged.
        Serializes against _chunked_write_lock so two concurrent writes
        on the same blob can't race.

        Returns True iff cloud accepted (code=0). Triggers a cloud_state
        refresh on success so the local view reflects what landed.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_settings: cloud client not ready")
            return False
        cs = self.cloud_state
        if cs is None:
            LOGGER.warning("write_settings: cloud_state not yet populated")
            return False
        from .protocol.settings import write_setting

        async with self._chunked_write_lock:
            try:
                new_raw = write_setting(
                    cs.settings.raw, map_id=map_id, field=field, value=value,
                )
            except KeyError as ex:
                LOGGER.warning("write_settings: KeyError %s", ex)
                return False
            import json as _json
            json_value = _json.dumps(new_raw, separators=(",", ":"))
            LOGGER.info(
                "[settings-write] field=%s map=%d value=%r json_len=%d",
                field, map_id, value, len(json_value),
            )
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SETTINGS", json_value,
            )
            if not ok:
                LOGGER.warning("[settings-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_coordinator_writes.py -v
python -m pytest -q
```

Expected: 4 tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator_writes.py
git commit -m "feat(coordinator): write_settings helper (RMW + chunked write + lock)"
```

---

## Task 6: Rewire `coordinator.write_schedule` to use `write_chunked_key`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py:write_schedule`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_coordinator_writes.py`:

```python
def test_write_schedule_uses_write_chunked_key():
    """write_schedule routes through cloud_client.write_chunked_key, not the
    raw set_batch_device_datas method, so it picks up chunking + lock."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, ScheduleSlot, SchedulePlan, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = lambda fn, *a: (lambda: fn(*a))()
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=10, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, locn=None, dock={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    coord._refresh_cloud_state = MagicMock(
        return_value=asyncio.Future()
    )
    coord._refresh_cloud_state.return_value.set_result(None)
    new_slots = (ScheduleSlot(slot_id=0, name="A", raw_blob_b64="", plans=()),)
    asyncio.run(coord.write_schedule(new_slots))
    args, _ = coord._cloud.write_chunked_key.call_args
    assert args[0] == "SCHEDULE"
    # value should contain v=11 (incremented from current 10)
    assert '"v":11' in args[1]
```

- [ ] **Step 2: Run, verify it fails**

Currently `write_schedule` calls `cloud_client.set_batch_device_datas` directly — the new test asserts it calls `write_chunked_key` instead.

```
python -m pytest tests/integration/test_coordinator_writes.py::test_write_schedule_uses_write_chunked_key -v
```

Expected: FAIL.

- [ ] **Step 3: Rewrite `write_schedule`**

Find `async def write_schedule(self, new_slots: ...)` in `coordinator.py` and replace its body with:

```python
    async def write_schedule(
        self,
        new_slots: "tuple[Any, ...] | list[Any]",
    ) -> bool:
        """Push a new SCHEDULE blob to the cloud via write_chunked_key.

        new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
        source of truth; .raw_blob_b64 is ignored — re-encoded). Bumps
        the schedule version by 1 and refreshes cloud_state on success.
        """
        from .protocol.schedule import build_schedule_set_value

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule: cloud client not ready")
            return False
        cs = self.cloud_state
        current_v = cs.schedule.version if cs is not None else 0
        new_v = current_v + 1
        json_value = build_schedule_set_value(tuple(new_slots), version=new_v)
        LOGGER.info(
            "[schedule-write] v %d → %d, len(d)=%d, json_len=%d",
            current_v, new_v, len(new_slots), len(json_value),
        )
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SCHEDULE", json_value,
            )
            if not ok:
                LOGGER.warning("[schedule-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_coordinator_writes.py -v
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator_writes.py
git commit -m "refactor(coordinator): write_schedule uses write_chunked_key + lock"
```

---

## Task 7: Rewire `coordinator.write_ai_human_enabled` to use `write_chunked_key`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py:write_ai_human_enabled`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_coordinator_writes.py`:

```python
def test_write_ai_human_enabled_uses_write_chunked_key():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = lambda fn, *a: (lambda: fn(*a))()
    coord._refresh_cloud_state = MagicMock(
        return_value=asyncio.Future()
    )
    coord._refresh_cloud_state.return_value.set_result(None)
    asyncio.run(coord.write_ai_human_enabled(True))
    coord._cloud.write_chunked_key.assert_called_once_with("AI_HUMAN", '"true"')
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_coordinator_writes.py::test_write_ai_human_enabled_uses_write_chunked_key -v
```

Expected: FAIL — current implementation calls `set_batch_device_datas` directly.

- [ ] **Step 3: Rewrite `write_ai_human_enabled`**

Find `async def write_ai_human_enabled(self, enabled: bool)` and replace with:

```python
    async def write_ai_human_enabled(self, enabled: bool) -> bool:
        """Toggle AI_HUMAN.0 (Capture Photos AI Obstacles) via write_chunked_key.

        Cloud value is a JSON-encoded boolean string (`"true"` / `"false"`).
        Privacy auth is gated app-side; here we trust that AI_HUMAN.0
        being writable means the user has accepted the policy in the app.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_ai_human_enabled: cloud client not ready")
            return False
        value = '"true"' if enabled else '"false"'
        LOGGER.info("[ai-human-write] AI_HUMAN.0 → %s", value)
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "AI_HUMAN", value,
            )
            if not ok:
                LOGGER.warning("[ai-human-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok
```

- [ ] **Step 4: Run tests + full suite**

```
python -m pytest tests/integration/test_coordinator_writes.py -v
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator_writes.py
git commit -m "refactor(coordinator): write_ai_human_enabled uses write_chunked_key + lock"
```

---

## Task 8: Optimistic-update + revert pattern — number entities

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py` (rewire 7 number entities)
- Create: `tests/integration/test_optimistic_writes.py`

This task wires ONE entity (`DreameA2MowingHeightNumber`) end-to-end as the template; subsequent tasks (9 / 10 / 11) replicate the pattern for switches, selects, and AI_HUMAN.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_optimistic_writes.py`:

```python
"""Tests for the entity-layer optimistic-update + revert pattern."""
from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import DreameA2MowingHeightNumber


def _make_coord(initial_value: int | None = 5):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=initial_value)
    coord._active_map_id = 0
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    coord.write_settings = MagicMock(
        return_value=asyncio.Future()
    )
    coord.write_settings.return_value.set_result(True)
    coord.hass = MagicMock()
    return coord


def test_number_entity_calls_write_settings_with_active_map_id():
    coord = _make_coord(5)
    ent = DreameA2MowingHeightNumber(coord)
    ent.async_write_ha_state = MagicMock()
    ent.hass = MagicMock()
    asyncio.run(ent.async_set_native_value(7.0))
    coord.write_settings.assert_called_once_with(
        map_id=0, field="mowingHeight", value=7
    )


def test_number_entity_optimistic_update_then_revert_on_failure():
    coord = _make_coord(5)
    coord.write_settings = MagicMock(return_value=asyncio.Future())
    coord.write_settings.return_value.set_result(False)  # cloud rejected
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = MagicMock(return_value=asyncio.Future())
    coord.hass.services.async_call.return_value.set_result(None)
    ent = DreameA2MowingHeightNumber(coord)
    ent.async_write_ha_state = MagicMock()
    ent.hass = coord.hass
    ent.entity_id = "number.test"
    asyncio.run(ent.async_set_native_value(7.0))
    # After revert, state.settings_mowing_height should be back to 5
    assert coord.data.settings_mowing_height == 5
    # Notification should have been fired
    args, kwargs = coord.hass.services.async_call.call_args
    assert args[0] == "persistent_notification"
    assert args[1] == "create"
    assert "dreame_a2_write_fail_number.test" in kwargs["service_data"]["notification_id"]
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_optimistic_writes.py -v
```

Expected: FAIL — current `async_set_native_value` calls `_write_setting_placeholder`.

- [ ] **Step 3: Rewire `DreameA2MowingHeightNumber.async_set_native_value`**

In `custom_components/dreame_a2_mower/number.py`, find `class DreameA2MowingHeightNumber` and replace its `async_set_native_value` method:

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="mowingHeight",
            new_value=int(value),
            state_field="settings_mowing_height",
        )
```

Then add this MODULE-LEVEL helper at the bottom of `number.py` (after the last entity class):

```python
async def _settings_optimistic_write(
    entity: "CoordinatorEntity",
    *,
    field: str,
    new_value: Any,
    state_field: str,
) -> None:
    """Optimistic-update + revert-on-failure for SETTINGS-driven entities.

    1. Save old value
    2. Update coordinator.data immediately + push state (instant UI)
    3. Call coordinator.write_settings(map_id, field, value)
    4. On success: cloud refresh confirms (no visible change)
    5. On failure: revert state + fire persistent_notification

    Reused by all numbers/switches/selects writing to SETTINGS — keeps
    every entity's setter to a single line.
    """
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    if coord._active_map_id is None:
        LOGGER.warning(
            "%s: no active map — write of %s deferred", entity.entity_id, field
        )
        return
    map_id = coord._active_map_id
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_settings(map_id=map_id, field=field, value=new_value)
    if ok:
        return
    # Revert + notify
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The cloud rejected the write of {field}={new_value!r}. "
                f"Reverted to previous value ({old_value!r})."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
```

Add `import dataclasses` near the top of `number.py` if not present.

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_optimistic_writes.py -v
python -m pytest -q
```

Expected: New tests pass; existing number-entity tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/number.py tests/integration/test_optimistic_writes.py
git commit -m "feat(number): optimistic write + revert pattern (mowing_height as template)"
```

---

## Task 9: Rewire remaining 6 number entities to the optimistic pattern

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py`

The 6 remaining number entities follow the SAME pattern as `DreameA2MowingHeightNumber`. For each, replace its `async_set_native_value` method body with a single call to `_settings_optimistic_write` (added in Task 8).

- [ ] **Step 1: Replace `DreameA2CutterPositionNumber.async_set_native_value`**

Find the class and replace the method:

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="cutterPosition",
            new_value=int(value),
            state_field="settings_cutter_position",
        )
```

- [ ] **Step 2: Replace `DreameA2CutterPositionHeightNumber.async_set_native_value`**

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="cutterPositionHeight",
            new_value=int(value),
            state_field="settings_cutter_position_height",
        )
```

- [ ] **Step 3: Replace `DreameA2EdgeMowingNumNumber.async_set_native_value`**

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="edgeMowingNum",
            new_value=int(value),
            state_field="settings_edge_mowing_num",
        )
```

- [ ] **Step 4: Replace `DreameA2ObstacleAvoidanceHeightNumber.async_set_native_value`**

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="obstacleAvoidanceHeight",
            new_value=int(value),
            state_field="settings_obstacle_avoidance_height",
        )
```

- [ ] **Step 5: Replace `DreameA2ObstacleAvoidanceDistanceNumber.async_set_native_value`**

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="obstacleAvoidanceDistance",
            new_value=int(value),
            state_field="settings_obstacle_avoidance_distance",
        )
```

- [ ] **Step 6: Replace `DreameA2ObstacleAvoidanceSensitivityNumber.async_set_native_value`**

```python
    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field="obstacleAvoidanceSensitivity",
            new_value=int(value),
            state_field="settings_obstacle_avoidance_sensitivity",
        )
```

(Note: `DreameA2ObstacleAvoidanceAiNumber` is intentionally NOT migrated here — it's removed entirely in Task 14 and replaced with 3 switches.)

- [ ] **Step 7: Run tests**

```
python -m pytest -q
```

Expected: All pass; no entity broken.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/number.py
git commit -m "feat(number): rewire 6 SETTINGS numbers to optimistic write pattern"
```

---

## Task 10: Rewire 4 SETTINGS switch entities

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch.py` (4 SETTINGS switches)

Each SETTINGS switch has TWO methods to rewire (`async_turn_on` and `async_turn_off`). Use the same `_settings_optimistic_write` helper. Add a switch-side wrapper at module level so we don't import from `number.py`.

- [ ] **Step 1: Add the switch-side helper to `switch.py`**

Append at the bottom of `switch.py` (after the last class):

```python
async def _settings_switch_optimistic_write(
    entity: "CoordinatorEntity",
    *,
    field: str,
    new_value: bool,
    state_field: str,
) -> None:
    """Bool-typed optimistic write for SETTINGS switches.

    Same pattern as the number version but with bool semantics —
    the integer write helper would also work but this signature
    expresses intent.
    """
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    if coord._active_map_id is None:
        LOGGER.warning(
            "%s: no active map — write of %s deferred", entity.entity_id, field
        )
        return
    map_id = coord._active_map_id
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_settings(
        map_id=map_id, field=field, value=int(new_value),
    )
    if ok:
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The cloud rejected the write of {field}={new_value!r}. "
                f"Reverted to previous value ({old_value!r})."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
```

Add `import dataclasses` near the top of `switch.py` if not present.

- [ ] **Step 2: Rewire `DreameA2EdgeMowingAutoSwitch`**

Replace BOTH `async_turn_on` and `async_turn_off`:

```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingAuto", new_value=True,
            state_field="settings_edge_mowing_auto",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingAuto", new_value=False,
            state_field="settings_edge_mowing_auto",
        )
```

- [ ] **Step 3: Rewire `DreameA2EdgeMowingSafeSwitch`**

```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingSafe", new_value=True,
            state_field="settings_edge_mowing_safe",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingSafe", new_value=False,
            state_field="settings_edge_mowing_safe",
        )
```

- [ ] **Step 4: Rewire `DreameA2EdgeMowingObstacleAvoidanceSwitch`**

```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingObstacleAvoidance", new_value=True,
            state_field="settings_edge_mowing_obstacle_avoidance",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingObstacleAvoidance", new_value=False,
            state_field="settings_edge_mowing_obstacle_avoidance",
        )
```

- [ ] **Step 5: Rewire `DreameA2ObstacleAvoidanceEnabledSwitch`**

```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="obstacleAvoidanceEnabled", new_value=True,
            state_field="settings_obstacle_avoidance_enabled",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="obstacleAvoidanceEnabled", new_value=False,
            state_field="settings_obstacle_avoidance_enabled",
        )
```

- [ ] **Step 6: Run tests**

```
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/switch.py
git commit -m "feat(switch): rewire 4 SETTINGS switches to optimistic write pattern"
```

---

## Task 11: Rewire AI_HUMAN switch + rename to "Capture Photos AI Obstacles"

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch.py:DreameA2AiHumanDetectionSwitch`

- [ ] **Step 1: Rewire `DreameA2AiHumanDetectionSwitch`**

Find `class DreameA2AiHumanDetectionSwitch` and:

a) Update `_attr_name`:

```python
    _attr_name = "Capture Photos AI Obstacles"
```

b) Replace `async_turn_on`:

```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        # Optimistic: we can't write to a frozen CloudState slot directly,
        # so reflect immediately via async_write_ha_state — the is_on
        # property reads from cloud_state which we don't mutate locally.
        # On success the next refresh updates it; on failure we just
        # revert visually by re-rendering current cloud_state value.
        ok = await coord.write_ai_human_enabled(True)
        if ok:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()
```

c) Replace `async_turn_off`:

```python
    async def async_turn_off(self, **kwargs: Any) -> None:
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        ok = await coord.write_ai_human_enabled(False)
        if ok:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()
```

- [ ] **Step 2: Run tests**

```
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/switch.py
git commit -m "feat(switch): AI Human switch real write + rename to app label"
```

---

## Task 12: Rewire 3 SETTINGS select entities

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py` (3 SETTINGS selects)

The select entities have an `async_select_option(option: str)` method that maps a string label back to an integer cloud value.

- [ ] **Step 1: Add the select-side helper**

At the bottom of `select.py` (after the last class), append:

```python
async def _settings_select_optimistic_write(
    entity: "CoordinatorEntity",
    *,
    field: str,
    new_value: int,
    state_field: str,
) -> None:
    """Int-typed optimistic write for SETTINGS selects."""
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    if coord._active_map_id is None:
        LOGGER.warning(
            "%s: no active map — write of %s deferred", entity.entity_id, field
        )
        return
    map_id = coord._active_map_id
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_settings(map_id=map_id, field=field, value=new_value)
    if ok:
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The cloud rejected the write of {field}={new_value!r}. "
                f"Reverted to previous value ({old_value!r})."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
```

Add `import dataclasses` to `select.py` if not present.

- [ ] **Step 2: Rewire `DreameA2MowingDirectionSelect.async_select_option`**

```python
    async def async_select_option(self, option: str) -> None:
        try:
            idx = self._OPTIONS.index(option)
        except ValueError:
            return
        await _settings_select_optimistic_write(
            self, field="mowingDirection", new_value=idx * 90,
            state_field="settings_mowing_direction",
        )
```

- [ ] **Step 3: Rewire `DreameA2MowingDirectionModeSelect.async_select_option`**

Also rename `_OPTIONS` to use Striped/Crisscross/Chequerboard labels and update `_attr_name` to "Mowing Pattern":

```python
class DreameA2MowingDirectionModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Mowing Pattern — Striped / Crisscross / Chequerboard."""

    _OPTIONS = ("Striped", "Crisscross", "Chequerboard")

    _attr_has_entity_name = True
    _attr_translation_key = "mowing_pattern"
    _attr_name = "Mowing Pattern"
    _attr_options = list(_OPTIONS)
    _attr_should_poll = False

    # __init__ unchanged from current implementation

    @property
    def current_option(self) -> str | None:
        v = self.coordinator.data.settings_mowing_direction_mode
        if v is None:
            return None
        return self._OPTIONS[v] if 0 <= v < len(self._OPTIONS) else None

    async def async_select_option(self, option: str) -> None:
        if option not in self._OPTIONS:
            return
        idx = self._OPTIONS.index(option)
        await _settings_select_optimistic_write(
            self, field="mowingDirectionMode", new_value=idx,
            state_field="settings_mowing_direction_mode",
        )
```

- [ ] **Step 4: Rewire `DreameA2EdgeMowingWalkModeSelect.async_select_option`**

```python
    async def async_select_option(self, option: str) -> None:
        if option not in self._OPTIONS:
            return
        try:
            n = int(option.split("_")[1])
        except (IndexError, ValueError):
            return
        await _settings_select_optimistic_write(
            self, field="edgeMowingWalkMode", new_value=n,
            state_field="settings_edge_mowing_walk_mode",
        )
```

- [ ] **Step 5: Run tests**

```
python -m pytest -q
```

Expected: All pass. Note: a select-rename test for the "Mowing Pattern" label may need to be added/updated under `tests/integration/test_settings_select_entities.py` — adapt as needed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py tests/integration/
git commit -m "feat(select): rewire 3 SETTINGS selects + Mowing Pattern label revision"
```

---

## Task 13: App-mirror naming pass — number/switch/select labels

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py`
- Modify: `custom_components/dreame_a2_mower/switch.py`
- Modify: `custom_components/dreame_a2_mower/select.py`

Spec table (entities whose `_attr_name` changes):

| Entity class | Old `_attr_name` | New `_attr_name` |
|---|---|---|
| `DreameA2MowingHeightNumber` | "Mowing height" | "Mowing Height" |
| `DreameA2MowingDirectionSelect` | "Mowing direction" | "Mowing Direction" |
| `DreameA2EdgeMowingAutoSwitch` | "Edge mowing auto" | "Automatic Edge Mowing" |
| `DreameA2EdgeMowingSafeSwitch` | "Edge mowing safe" | "Safe Edge Mowing" |
| `DreameA2EdgeMowingObstacleAvoidanceSwitch` | "Edge mowing obstacle avoidance" | "Obstacle Avoidance on Edges" |
| `DreameA2ObstacleAvoidanceEnabledSwitch` | "Obstacle avoidance enabled" | "LiDAR Obstacle Recognition" |
| `DreameA2ObstacleAvoidanceHeightNumber` | "Obstacle avoidance height" | "Obstacle Avoidance Height" |
| `DreameA2ObstacleAvoidanceDistanceNumber` | "Obstacle avoidance distance" | "Obstacle Avoidance Distance" |

Generic-name entities (KEEP current names — TBD per spec): `DreameA2CutterPositionNumber`, `DreameA2CutterPositionHeightNumber`, `DreameA2EdgeMowingNumNumber`, `DreameA2EdgeMowingWalkModeSelect`, `DreameA2ObstacleAvoidanceSensitivityNumber`. The `DreameA2MowingDirectionModeSelect` was renamed to "Mowing Pattern" in Task 12.

- [ ] **Step 1: Update each `_attr_name`**

Search-and-replace each entity class's `_attr_name = "..."` line per the table.

```bash
sed -i 's/_attr_name = "Mowing height"/_attr_name = "Mowing Height"/' custom_components/dreame_a2_mower/number.py
sed -i 's/_attr_name = "Mowing direction"/_attr_name = "Mowing Direction"/' custom_components/dreame_a2_mower/select.py
sed -i 's/_attr_name = "Edge mowing auto"/_attr_name = "Automatic Edge Mowing"/' custom_components/dreame_a2_mower/switch.py
sed -i 's/_attr_name = "Edge mowing safe"/_attr_name = "Safe Edge Mowing"/' custom_components/dreame_a2_mower/switch.py
sed -i 's/_attr_name = "Edge mowing obstacle avoidance"/_attr_name = "Obstacle Avoidance on Edges"/' custom_components/dreame_a2_mower/switch.py
sed -i 's/_attr_name = "Obstacle avoidance enabled"/_attr_name = "LiDAR Obstacle Recognition"/' custom_components/dreame_a2_mower/switch.py
sed -i 's/_attr_name = "Obstacle avoidance height"/_attr_name = "Obstacle Avoidance Height"/' custom_components/dreame_a2_mower/number.py
sed -i 's/_attr_name = "Obstacle avoidance distance"/_attr_name = "Obstacle Avoidance Distance"/' custom_components/dreame_a2_mower/number.py
```

Verify with: `grep -nE "_attr_name = " custom_components/dreame_a2_mower/{number,switch,select}.py`

- [ ] **Step 2: Run tests**

```
python -m pytest -q
```

Expected: All pass. The unique_ids haven't changed, so no entity-id orphan issue here.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/{number,switch,select}.py
git commit -m "feat: app-mirror naming for SETTINGS entities (per spec table)"
```

---

## Task 14: Drop `obstacleAvoidanceAi` number, add 3 AI Recognition switches

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py` (remove `DreameA2ObstacleAvoidanceAiNumber` + its `async_setup_entry` registration)
- Modify: `custom_components/dreame_a2_mower/switch.py` (add 3 new switches + register)
- Update: relevant tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_settings_switch_entities.py`:

```python
def test_ai_recognition_humans_switch_reads_bit0():
    """obstacleAvoidanceAi & 0x01 → switch.ai_recognition_humans is_on."""
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionHumansSwitch,
    )
    coord = _make_coord(settings_obstacle_avoidance_ai=0b001)
    ent = DreameA2AiRecognitionHumansSwitch(coord)
    assert ent.is_on is True


def test_ai_recognition_animals_switch_reads_bit1():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionAnimalsSwitch,
    )
    coord = _make_coord(settings_obstacle_avoidance_ai=0b010)
    ent = DreameA2AiRecognitionAnimalsSwitch(coord)
    assert ent.is_on is True


def test_ai_recognition_objects_switch_reads_bit2():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionObjectsSwitch,
    )
    coord = _make_coord(settings_obstacle_avoidance_ai=0b100)
    ent = DreameA2AiRecognitionObjectsSwitch(coord)
    assert ent.is_on is True


def test_ai_recognition_humans_off_when_bit_clear():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionHumansSwitch,
    )
    coord = _make_coord(settings_obstacle_avoidance_ai=0b110)
    ent = DreameA2AiRecognitionHumansSwitch(coord)
    assert ent.is_on is False
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_settings_switch_entities.py -v
```

Expected: FAIL — new switch classes not defined.

- [ ] **Step 3: Add 3 new switch classes to `switch.py`**

Append at the bottom of `switch.py` (after the existing switches, before the helper):

```python
_AI_HUMANS_BIT = 1 << 0
_AI_ANIMALS_BIT = 1 << 1
_AI_OBJECTS_BIT = 1 << 2


class _AiRecognitionBitSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Common base for the 3 AI obstacle recognition bit switches.

    Each subclass sets _BIT (one of _AI_HUMANS_BIT / _ANIMALS_BIT /
    _OBJECTS_BIT) and the entity-name / unique-id attrs.
    """

    _BIT: int = 0
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.data.settings_obstacle_avoidance_ai
        if v is None:
            return None
        return bool(v & self._BIT)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def _toggle(self, on: bool) -> None:
        coord = self.coordinator
        if coord._active_map_id is None:
            LOGGER.warning(
                "%s: no active map — toggle deferred", self.entity_id
            )
            return
        old = coord.data.settings_obstacle_avoidance_ai or 0
        new = (old | self._BIT) if on else (old & ~self._BIT)
        if new == old:
            return
        coord.data = dataclasses.replace(
            coord.data, settings_obstacle_avoidance_ai=new
        )
        self.async_write_ha_state()
        ok = await coord.write_settings(
            map_id=coord._active_map_id,
            field="obstacleAvoidanceAi",
            value=new,
        )
        if ok:
            return
        coord.data = dataclasses.replace(
            coord.data, settings_obstacle_avoidance_ai=old
        )
        self.async_write_ha_state()
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    f"The cloud rejected the AI recognition toggle. "
                    f"Previous bitfield value: 0b{old:03b}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle(False)


class DreameA2AiRecognitionHumansSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Humans (bit 0)."""
    _BIT = _AI_HUMANS_BIT
    _attr_translation_key = "ai_recognition_humans"
    _attr_name = "AI Obstacle Recognition: Humans"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_ai_recognition_humans"
        )


class DreameA2AiRecognitionAnimalsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Animals (bit 1)."""
    _BIT = _AI_ANIMALS_BIT
    _attr_translation_key = "ai_recognition_animals"
    _attr_name = "AI Obstacle Recognition: Animals"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_ai_recognition_animals"
        )


class DreameA2AiRecognitionObjectsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Objects (bit 2)."""
    _BIT = _AI_OBJECTS_BIT
    _attr_translation_key = "ai_recognition_objects"
    _attr_name = "AI Obstacle Recognition: Objects"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_ai_recognition_objects"
        )
```

- [ ] **Step 4: Register the 3 new switches in `switch.py:async_setup_entry`**

Find the `async_setup_entry` function in `switch.py`. After the existing `entities.extend([...])` block adding the SETTINGS switches, append:

```python
    entities.extend([
        DreameA2AiRecognitionHumansSwitch(coordinator),
        DreameA2AiRecognitionAnimalsSwitch(coordinator),
        DreameA2AiRecognitionObjectsSwitch(coordinator),
    ])
```

- [ ] **Step 5: Remove `DreameA2ObstacleAvoidanceAiNumber` from `number.py`**

Find `class DreameA2ObstacleAvoidanceAiNumber` and delete the entire class. Then in `number.py:async_setup_entry`, find:

```python
        DreameA2ObstacleAvoidanceAiNumber(coordinator),
```

and delete that line from the `entities.extend([...])` call.

- [ ] **Step 6: Run tests**

```
python -m pytest -q
```

Expected: New tests pass; tests that referenced `DreameA2ObstacleAvoidanceAiNumber` fail. Find and delete those tests:

```
grep -rn "DreameA2ObstacleAvoidanceAiNumber\|obstacle_avoidance_ai" tests/integration/ | grep -v __pycache__
```

For each match, decide: delete the assertion if it specifically tests the removed class, OR rewrite to test one of the 3 new switches. Re-run pytest after each fix.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/{number,switch}.py tests/integration/
git commit -m "feat(switch): split obstacleAvoidanceAi into 3 app-mirrored switches; remove old number"
```

---

## Task 15: `sensor.schedule_count` exposes zone_id + action labels

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py:DreameA2ScheduleCountSensor`
- Modify: `tests/integration/test_cloud_state_sensors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_cloud_state_sensors.py`:

```python
def test_schedule_count_surfaces_zone_id_and_action_label():
    """sensor.schedule_count attrs include zone_id + action label per plan."""
    from custom_components.dreame_a2_mower.cloud_state import (
        ScheduleSlot, SchedulePlan,
    )
    sched = ScheduleData(
        version=1,
        slots=(
            ScheduleSlot(
                slot_id=0, name="A", raw_blob_b64="z",
                plans=(
                    # Zone Wed 16:00 in Zone1
                    SchedulePlan(time_min=16*60, weekday_mask=1<<2,
                                 action_type=1, zone_id=1),
                ),
            ),
        ),
    )
    coord = _make_coord(schedule=sched)
    ent = DreameA2ScheduleCountSensor(coord)
    plans = ent.extra_state_attributes["slots"][0]["plans"]
    assert plans[0]["action"] == "zone"
    assert plans[0]["zone_id"] == 1
    assert plans[0]["time"] == "16:00"
    assert plans[0]["days"] == ["Wed"]
```

- [ ] **Step 2: Run, verify it fails**

```
python -m pytest tests/integration/test_cloud_state_sensors.py::test_schedule_count_surfaces_zone_id_and_action_label -v
```

Expected: FAIL — current sensor doesn't include `zone_id` and uses different action labels.

- [ ] **Step 3: Update the sensor**

In `custom_components/dreame_a2_mower/sensor.py`, find the `_ACTION_LABELS` module-level dict and replace:

```python
_ACTION_LABELS = {
    0: "all_area",
    1: "zone",
    2: "edge",
}
```

Find `DreameA2ScheduleCountSensor.extra_state_attributes` and replace the per-plan dict comprehension to include `zone_id`:

```python
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return {}
        return {
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "name": s.name,
                    "plans": [
                        {
                            "time": _fmt_hhmm(p.time_min),
                            "days": _fmt_weekdays(p.weekday_mask),
                            "action": _fmt_action(p.action_type),
                            "zone_id": p.zone_id,
                        }
                        for p in s.plans
                    ],
                }
                for s in cs.schedule.slots
            ],
            "version": cs.schedule.version,
        }
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_cloud_state_sensors.py -v
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py tests/integration/test_cloud_state_sensors.py
git commit -m "feat(sensor): schedule_count exposes zone_id + revised action labels"
```

---

## Task 16: `dreame_a2_mower.set_schedule_plans` service

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.py` (add handler + register)
- Modify: `custom_components/dreame_a2_mower/services.yaml` (declare service)

- [ ] **Step 1: Add the service constant + schema**

In `custom_components/dreame_a2_mower/services.py`, add to the constants block near the top:

```python
SERVICE_SET_SCHEDULE_PLANS = "set_schedule_plans"
```

Add a schema near the other `SCHEMA_*` definitions:

```python
SCHEMA_SET_SCHEDULE_PLANS = vol.Schema({
    vol.Required("slot_id"): vol.Coerce(int),
    vol.Required("plans"): vol.All(cv.ensure_list, [vol.Schema({
        vol.Required("time_min"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1439)),
        vol.Required("weekday_mask"): vol.All(vol.Coerce(int), vol.Range(min=1, max=127)),
        vol.Required("action_type"): vol.In([0, 1, 2]),
        vol.Optional("zone_id"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("extra_bytes_hex"): str,
    })]),
})
```

- [ ] **Step 2: Add the handler**

Append the handler function near the other `_handle_*` functions (after `_handle_replay_session`):

```python
async def _handle_set_schedule_plans(call: ServiceCall) -> None:
    """Replace one slot's full plan list, leave other slots untouched.

    Card-side flow: card holds the working set locally as the user edits;
    on Save it calls this service with the complete new plan list for ONE
    slot. The coordinator does the cloud round-trip; on success the next
    cloud refresh updates sensor attrs which the card re-reads.
    """
    from .cloud_state import ScheduleSlot, SchedulePlan

    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    cs = getattr(coordinator, "cloud_state", None)
    if cs is None:
        LOGGER.warning("set_schedule_plans: cloud_state not yet populated")
        return
    target_slot_id = int(call.data["slot_id"])
    new_plan_dicts = call.data["plans"]
    new_plans = tuple(
        SchedulePlan(
            time_min=int(p["time_min"]),
            weekday_mask=int(p["weekday_mask"]),
            action_type=int(p["action_type"]),
            zone_id=p.get("zone_id"),
            extra_bytes=bytes.fromhex(p["extra_bytes_hex"]) if p.get("extra_bytes_hex") else b"",
        )
        for p in new_plan_dicts
    )
    new_slots = []
    found = False
    for slot in cs.schedule.slots:
        if slot.slot_id == target_slot_id:
            new_slots.append(ScheduleSlot(
                slot_id=slot.slot_id,
                name=slot.name,
                raw_blob_b64="",
                plans=new_plans,
            ))
            found = True
        else:
            new_slots.append(slot)
    if not found:
        # Slot not in current cloud state — append a new one.
        new_slots.append(ScheduleSlot(
            slot_id=target_slot_id, name="", raw_blob_b64="", plans=new_plans,
        ))
    ok = await coordinator.write_schedule(new_slots)
    LOGGER.info(
        "set_schedule_plans: slot %d, %d plan(s), accepted=%s",
        target_slot_id, len(new_plans), ok,
    )
```

- [ ] **Step 3: Register the service**

In `services.py:async_register_services`, after the existing registrations, add:

```python
    hass.services.async_register(
        DOMAIN, SERVICE_SET_SCHEDULE_PLANS,
        _handle_set_schedule_plans, schema=SCHEMA_SET_SCHEDULE_PLANS,
    )
```

In `async_unregister_services`, add `SERVICE_SET_SCHEDULE_PLANS` to the `for svc in (...)` tuple.

- [ ] **Step 4: Add to `services.yaml`**

Append to `custom_components/dreame_a2_mower/services.yaml`:

```yaml

set_schedule_plans:
  name: Set schedule plans
  description: >
    Replace one slot's full plan list (Spring & Summer or Autumn & Winter)
    with a new set of mowing plans. The cloud's atomic unit is the slot
    blob, so this service replaces the entire slot rather than mutating
    individual plans. Used by the bundled Schedule custom card.
  fields:
    slot_id:
      name: Slot ID
      description: 0 = Spring & Summer, 1 = Autumn & Winter
      required: true
      example: 0
      selector: { number: { min: 0, max: 1, step: 1 } }
    plans:
      name: Plans
      description: >
        List of plans. Each plan is a dict with keys: time_min (int 0-1439),
        weekday_mask (int 1-127, bit 0 = Mon), action_type (0=All-area,
        1=Zone, 2=Edge), zone_id (int, required for Zone/Edge),
        extra_bytes_hex (str, hex-encoded, optional — only Edge has this
        for round-trip fidelity).
      required: true
```

- [ ] **Step 5: Validate YAML + commit**

```bash
python -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/services.yaml')); print('YAML OK')"
python -m pytest -q
git add custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml
git commit -m "feat(services): set_schedule_plans — replace one slot's plan list"
```

---

## Task 17: Custom Lovelace card scaffold (slot tabs + plan list + delete)

**Files:**
- Create: `dashboards/cards/dreame-a2-schedule-card.js`

This task lands the basic card: read sensor attrs, display slots as tabs, show plans as a list, support deleting a plan. Add/edit modals + grid view come in Task 18.

- [ ] **Step 1: Create the card file**

Create `dashboards/cards/dreame-a2-schedule-card.js`:

```javascript
/* Dreame A2 Mower — Schedule edit card.
 *
 * Reads sensor.dreame_a2_mower_schedule_count attributes for slot/plan data;
 * calls dreame_a2_mower.set_schedule_plans service to mutate.
 *
 * Layout: slot tabs + plan list + add/edit/delete buttons.
 * Add/edit modal + weekly-grid view land in a follow-up step.
 */

const SLOT_DEFAULTS = {
  0: "Spr & Sum Schedule",
  1: "Aut & Win Schedule",
};

const ACTION_LABELS = {
  0: "All-area",
  1: "Zone",
  2: "Edge",
};

const ACTION_COLORS = {
  0: "#a3d977", // green — All-area
  1: "#7fb3ff", // blue — Zone
  2: "#ff8a8a", // red — Edge
};

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

class DreameA2ScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeSlot = 0;
    this._stateRef = null;
  }

  setConfig(config) {
    this._sensor = config.sensor || "sensor.dreame_a2_mower_schedule_count";
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._sensor];
    if (!state) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;">Sensor ${this._sensor} not available</div></ha-card>`;
      return;
    }
    if (this._stateRef === state) return; // no change
    this._stateRef = state;
    this._render(state);
  }

  _render(state) {
    const slots = state.attributes.slots || [];
    const slotTabs = slots
      .map(
        (s, i) =>
          `<button class="tab ${i === this._activeSlot ? "active" : ""}" data-slot="${i}">${
            s.name || SLOT_DEFAULTS[s.slot_id] || `Schedule ${s.slot_id + 1}`
          }</button>`,
      )
      .join("");
    const active = slots[this._activeSlot] || { plans: [] };
    const planList = active.plans
      .map(
        (p, idx) => `
        <div class="plan" style="border-left: 4px solid ${ACTION_COLORS[p.action_type ?? 0]};">
          <div class="plan-info">
            <strong>${p.time}</strong> ${ACTION_LABELS[p.action_type ?? 0] || p.action}
            ${p.zone_id != null ? `(Zone ${p.zone_id})` : ""}
            <div class="days">${(p.days || []).join(", ")}</div>
          </div>
          <button class="delete" data-slot="${this._activeSlot}" data-plan="${idx}">Delete</button>
        </div>`,
      )
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; }
        .tabs { display: flex; gap: 4px; margin-bottom: 12px; }
        .tab { padding: 6px 12px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer; }
        .tab.active { background: var(--primary-color); color: var(--text-primary-color); }
        .plan { display: flex; justify-content: space-between; align-items: center; padding: 8px; margin: 4px 0; border: 1px solid var(--divider-color); }
        .plan-info { flex: 1; }
        .days { font-size: 0.85em; color: var(--secondary-text-color); }
        .delete { padding: 4px 10px; cursor: pointer; }
        .add { display: block; margin-top: 12px; padding: 8px 14px; cursor: pointer; }
        .empty { padding: 12px; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="tabs">${slotTabs}</div>
        <div class="plans">
          ${planList || '<div class="empty">No plans configured.</div>'}
        </div>
        <button class="add">+ Add plan</button>
      </ha-card>
    `;
    this.shadowRoot.querySelectorAll(".tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        this._activeSlot = parseInt(btn.dataset.slot, 10);
        this._render(this._stateRef);
      }),
    );
    this.shadowRoot.querySelectorAll(".delete").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._deletePlan(
          parseInt(btn.dataset.slot, 10),
          parseInt(btn.dataset.plan, 10),
        ),
      ),
    );
    this.shadowRoot.querySelector(".add").addEventListener("click", () =>
      alert("Add modal — implemented in next task"),
    );
  }

  async _deletePlan(slotIdx, planIdx) {
    const slots = this._stateRef.attributes.slots;
    const slot = slots[slotIdx];
    if (!slot) return;
    const newPlans = slot.plans.filter((_, i) => i !== planIdx).map((p) => ({
      time_min: this._parseHhmm(p.time),
      weekday_mask: this._buildWeekdayMask(p.days),
      action_type: p.action_type ?? 0,
      ...(p.zone_id != null ? { zone_id: p.zone_id } : {}),
    }));
    await this._hass.callService("dreame_a2_mower", "set_schedule_plans", {
      slot_id: slot.slot_id,
      plans: newPlans,
    });
  }

  _parseHhmm(s) {
    const [hh, mm] = s.split(":").map((x) => parseInt(x, 10));
    return hh * 60 + mm;
  }

  _buildWeekdayMask(days) {
    let mask = 0;
    for (const d of days) {
      const idx = WEEKDAY_LABELS.indexOf(d);
      if (idx >= 0) mask |= 1 << idx;
    }
    return mask;
  }

  getCardSize() {
    return 4;
  }
}

customElements.define("dreame-a2-schedule-card", DreameA2ScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-schedule-card",
  name: "Dreame A2 Schedule",
  description: "Edit Spr & Sum / Aut & Win mowing schedules",
});
console.info("dreame-a2-schedule-card v1.0.2a1 loaded");
```

- [ ] **Step 2: Commit**

```bash
mkdir -p dashboards/cards
git add dashboards/cards/dreame-a2-schedule-card.js
git commit -m "feat(card): schedule card scaffold with slot tabs + plan list + delete"
```

---

## Task 18: Custom card — Add/Edit modals + weekly grid + overlap validation

**Files:**
- Modify: `dashboards/cards/dreame-a2-schedule-card.js` (extend with modals + grid)

This task adds the full edit UX: modal forms for adding and editing plans, client-side overlap validation matching the app's behavior, and a weekly-grid visualization of plans.

- [ ] **Step 1: Replace the card file**

Replace the entire file content with:

```javascript
/* Dreame A2 Mower — Schedule edit card (full UX).
 *
 * Reads sensor.dreame_a2_mower_schedule_count, writes via
 * dreame_a2_mower.set_schedule_plans. Supports add / edit / delete
 * with client-side overlap validation matching the app's behavior.
 */

const SLOT_DEFAULTS = {
  0: "Spr & Sum Schedule",
  1: "Aut & Win Schedule",
};

const ACTION_LABELS = { 0: "All-area", 1: "Zone", 2: "Edge" };
const ACTION_COLORS = { 0: "#a3d977", 1: "#7fb3ff", 2: "#ff8a8a" };
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PLAN_DURATION_MIN = 120; // app reserves 2h per plan regardless of action

class DreameA2ScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeSlot = 0;
    this._stateRef = null;
    this._editingPlan = null; // { slotIdx, planIdx } | null
  }

  setConfig(config) {
    this._sensor = config.sensor || "sensor.dreame_a2_mower_schedule_count";
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._sensor];
    if (!state) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;">Sensor ${this._sensor} not available</div></ha-card>`;
      return;
    }
    if (this._stateRef === state && !this._modal) return;
    this._stateRef = state;
    this._render(state);
  }

  _render(state) {
    const slots = state.attributes.slots || [];
    const tabs = slots
      .map(
        (s, i) =>
          `<button class="tab ${i === this._activeSlot ? "active" : ""}" data-slot="${i}">${
            s.name || SLOT_DEFAULTS[s.slot_id] || `Schedule ${s.slot_id + 1}`
          }</button>`,
      )
      .join("");
    const active = slots[this._activeSlot] || { plans: [], slot_id: this._activeSlot };
    const grid = this._renderGrid(active.plans);
    const list = active.plans
      .map(
        (p, idx) => `
        <div class="plan" style="border-left: 4px solid ${ACTION_COLORS[p.action_type ?? 0]};">
          <div class="plan-info">
            <strong>${p.time}</strong> ${ACTION_LABELS[p.action_type ?? 0]}
            ${p.zone_id != null ? `(Zone ${p.zone_id})` : ""}
            <div class="days">${(p.days || []).join(", ")}</div>
          </div>
          <div>
            <button class="edit" data-slot="${this._activeSlot}" data-plan="${idx}">Edit</button>
            <button class="delete" data-slot="${this._activeSlot}" data-plan="${idx}">Delete</button>
          </div>
        </div>`,
      )
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; }
        .tabs { display: flex; gap: 4px; margin-bottom: 12px; }
        .tab { padding: 6px 12px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer; }
        .tab.active { background: var(--primary-color); color: var(--text-primary-color); }
        .grid { display: grid; grid-template-columns: 40px repeat(7, 1fr); gap: 1px; background: var(--divider-color); margin-bottom: 12px; font-size: 0.75em; }
        .grid > div { background: var(--card-background-color); padding: 2px 4px; min-height: 18px; position: relative; }
        .grid .header { background: var(--secondary-background-color); text-align: center; font-weight: bold; }
        .grid .plan-block { color: white; padding: 2px 4px; font-size: 0.7em; cursor: pointer; }
        .plan { display: flex; justify-content: space-between; align-items: center; padding: 8px; margin: 4px 0; border: 1px solid var(--divider-color); }
        .plan-info { flex: 1; }
        .days { font-size: 0.85em; color: var(--secondary-text-color); }
        button { padding: 4px 10px; cursor: pointer; margin-left: 4px; }
        .add { display: block; margin-top: 12px; padding: 8px 14px; }
        .empty { padding: 12px; color: var(--secondary-text-color); }
        .modal-bg { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .modal { background: var(--card-background-color); padding: 20px; border-radius: 4px; min-width: 320px; max-width: 90vw; }
        .modal h3 { margin-top: 0; }
        .modal label { display: block; margin: 8px 0 4px; font-weight: bold; }
        .modal select, .modal input { width: 100%; padding: 6px; box-sizing: border-box; }
        .modal .day-toggles { display: flex; gap: 4px; }
        .modal .day-toggles button { flex: 1; padding: 6px; }
        .modal .day-toggles button.on { background: var(--primary-color); color: var(--text-primary-color); }
        .modal .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
        .error { color: var(--error-color, red); font-size: 0.85em; margin-top: 4px; }
      </style>
      <ha-card>
        <div class="tabs">${tabs}</div>
        ${grid}
        <div class="plans">
          ${list || '<div class="empty">No plans configured.</div>'}
        </div>
        <button class="add">+ Add plan</button>
      </ha-card>
      ${this._modal || ""}
    `;
    this.shadowRoot.querySelectorAll(".tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        this._activeSlot = parseInt(btn.dataset.slot, 10);
        this._modal = null;
        this._render(this._stateRef);
      }),
    );
    this.shadowRoot.querySelectorAll(".delete").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._deletePlan(parseInt(btn.dataset.slot, 10), parseInt(btn.dataset.plan, 10)),
      ),
    );
    this.shadowRoot.querySelectorAll(".edit").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._openEditModal(parseInt(btn.dataset.slot, 10), parseInt(btn.dataset.plan, 10)),
      ),
    );
    this.shadowRoot.querySelector(".add").addEventListener("click", () =>
      this._openAddModal(),
    );
    this._wireModal();
  }

  _renderGrid(plans) {
    const cells = ["<div class='header'></div>"];
    for (const d of WEEKDAY_LABELS) cells.push(`<div class='header'>${d}</div>`);
    // 24 hourly rows
    for (let h = 0; h < 24; h++) {
      cells.push(`<div>${String(h).padStart(2, "0")}</div>`);
      for (let day = 0; day < 7; day++) {
        const planAtThisCell = plans.find((p) => {
          const startMin = this._parseHhmm(p.time);
          const startHr = Math.floor(startMin / 60);
          const dayBit = 1 << day;
          const dayMatches = (p.days || []).includes(WEEKDAY_LABELS[day]);
          return dayMatches && h === startHr;
        });
        if (planAtThisCell) {
          const action = planAtThisCell.action_type ?? 0;
          cells.push(
            `<div class='plan-block' style='background:${ACTION_COLORS[action]};' title='${planAtThisCell.time} ${ACTION_LABELS[action]}'>${planAtThisCell.time}</div>`,
          );
        } else {
          cells.push("<div></div>");
        }
      }
    }
    return `<div class='grid'>${cells.join("")}</div>`;
  }

  _openAddModal() {
    this._editingPlan = null;
    this._modal = this._modalHtml({
      time_min: 480, // default 08:00
      weekday_mask: 0,
      action_type: 0,
      zone_id: null,
    });
    this._render(this._stateRef);
  }

  _openEditModal(slotIdx, planIdx) {
    const plan = this._stateRef.attributes.slots[slotIdx].plans[planIdx];
    this._editingPlan = { slotIdx, planIdx };
    this._modal = this._modalHtml({
      time_min: this._parseHhmm(plan.time),
      weekday_mask: this._buildWeekdayMask(plan.days || []),
      action_type: plan.action_type ?? 0,
      zone_id: plan.zone_id ?? null,
    });
    this._render(this._stateRef);
  }

  _modalHtml(plan) {
    const hh = String(Math.floor(plan.time_min / 60)).padStart(2, "0");
    const mm = String(plan.time_min % 60).padStart(2, "0");
    const dayBtns = WEEKDAY_LABELS.map(
      (d, i) =>
        `<button type='button' class='day-btn ${plan.weekday_mask & (1 << i) ? "on" : ""}' data-day='${i}'>${d}</button>`,
    ).join("");
    const actionOptions = Object.entries(ACTION_LABELS)
      .map(
        ([k, v]) => `<option value='${k}' ${plan.action_type == k ? "selected" : ""}>${v}</option>`,
      )
      .join("");
    return `
      <div class='modal-bg'>
        <div class='modal'>
          <h3>${this._editingPlan ? "Edit plan" : "Add plan"}</h3>
          <label>Action</label>
          <select id='action'>${actionOptions}</select>
          <label>Zone (Zone/Edge only)</label>
          <input id='zone_id' type='number' min='0' value='${plan.zone_id ?? ""}' />
          <label>Time</label>
          <input id='time' type='time' value='${hh}:${mm}' />
          <label>Days</label>
          <div class='day-toggles'>${dayBtns}</div>
          <div class='error' id='error'></div>
          <div class='actions'>
            <button type='button' id='cancel'>Cancel</button>
            <button type='button' id='save'>Save</button>
          </div>
        </div>
      </div>
    `;
  }

  _wireModal() {
    if (!this._modal) return;
    const root = this.shadowRoot;
    let mask = 0;
    root.querySelectorAll(".day-btn").forEach((btn) => {
      if (btn.classList.contains("on")) mask |= 1 << parseInt(btn.dataset.day, 10);
      btn.addEventListener("click", () => {
        const bit = 1 << parseInt(btn.dataset.day, 10);
        if (btn.classList.contains("on")) {
          btn.classList.remove("on");
          mask &= ~bit;
        } else {
          btn.classList.add("on");
          mask |= bit;
        }
      });
    });
    root.querySelector("#cancel").addEventListener("click", () => {
      this._modal = null;
      this._render(this._stateRef);
    });
    root.querySelector("#save").addEventListener("click", () => {
      const action_type = parseInt(root.querySelector("#action").value, 10);
      const zoneVal = root.querySelector("#zone_id").value;
      const zone_id = zoneVal === "" ? null : parseInt(zoneVal, 10);
      const time = root.querySelector("#time").value;
      const time_min = this._parseHhmm(time);
      const errEl = root.querySelector("#error");

      if (mask === 0) {
        errEl.textContent = "Select at least one day.";
        return;
      }
      if ((action_type === 1 || action_type === 2) && zone_id == null) {
        errEl.textContent = "Zone/Edge plans require a zone_id.";
        return;
      }
      // Overlap check (mirrors the app's same-slot validation)
      const slot = this._stateRef.attributes.slots[this._activeSlot];
      const otherPlans = (slot.plans || []).filter((_, i) =>
        this._editingPlan ? i !== this._editingPlan.planIdx : true,
      );
      for (const other of otherPlans) {
        const otherStart = this._parseHhmm(other.time);
        const otherMask = this._buildWeekdayMask(other.days || []);
        if ((otherMask & mask) === 0) continue; // no shared weekday
        const aStart = time_min;
        const aEnd = time_min + PLAN_DURATION_MIN;
        const bStart = otherStart;
        const bEnd = otherStart + PLAN_DURATION_MIN;
        if (aStart < bEnd && bStart < aEnd) {
          errEl.textContent = `Overlaps existing plan at ${other.time}.`;
          return;
        }
      }

      const newPlan = { time_min, weekday_mask: mask, action_type };
      if (zone_id != null) newPlan.zone_id = zone_id;

      const updatedPlans = (slot.plans || []).map((p, idx) => {
        if (this._editingPlan && idx === this._editingPlan.planIdx) {
          return newPlan;
        }
        return {
          time_min: this._parseHhmm(p.time),
          weekday_mask: this._buildWeekdayMask(p.days),
          action_type: p.action_type ?? 0,
          ...(p.zone_id != null ? { zone_id: p.zone_id } : {}),
        };
      });
      if (!this._editingPlan) updatedPlans.push(newPlan);

      this._hass.callService("dreame_a2_mower", "set_schedule_plans", {
        slot_id: slot.slot_id,
        plans: updatedPlans,
      });
      this._modal = null;
      this._render(this._stateRef);
    });
  }

  async _deletePlan(slotIdx, planIdx) {
    const slot = this._stateRef.attributes.slots[slotIdx];
    if (!slot) return;
    const newPlans = (slot.plans || [])
      .filter((_, i) => i !== planIdx)
      .map((p) => ({
        time_min: this._parseHhmm(p.time),
        weekday_mask: this._buildWeekdayMask(p.days),
        action_type: p.action_type ?? 0,
        ...(p.zone_id != null ? { zone_id: p.zone_id } : {}),
      }));
    await this._hass.callService("dreame_a2_mower", "set_schedule_plans", {
      slot_id: slot.slot_id,
      plans: newPlans,
    });
  }

  _parseHhmm(s) {
    const [hh, mm] = s.split(":").map((x) => parseInt(x, 10));
    return hh * 60 + mm;
  }

  _buildWeekdayMask(days) {
    let mask = 0;
    for (const d of days) {
      const idx = WEEKDAY_LABELS.indexOf(d);
      if (idx >= 0) mask |= 1 << idx;
    }
    return mask;
  }

  getCardSize() {
    return 6;
  }
}

customElements.define("dreame-a2-schedule-card", DreameA2ScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-schedule-card",
  name: "Dreame A2 Schedule",
  description: "Edit Spr & Sum / Aut & Win mowing schedules",
});
console.info("dreame-a2-schedule-card v1.0.2a1 (full UX) loaded");
```

- [ ] **Step 2: Commit**

```bash
git add dashboards/cards/dreame-a2-schedule-card.js
git commit -m "feat(card): full Add/Edit/Delete UX + weekly grid + overlap validation"
```

---

## Task 19: Reference the new card in dashboard YAML

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Add `lovelace_resources` reference**

If the dashboard YAML has a top-level `resources:` block, add to it; otherwise insert at the top:

```yaml
resources:
  - url: /local/dreame_a2_mower/dreame-a2-schedule-card.js
    type: module
```

(The `/local/` path means the file must be SCP'd to `/homeassistant/www/dreame_a2_mower/` not just to the dashboards dir. Task 21 covers the SCP step.)

- [ ] **Step 2: Replace the markdown plan-list with the custom card**

Find the existing Schedule view's markdown card that lists plans (the one with "### Configured slots"). Replace that card with:

```yaml
      - type: custom:dreame-a2-schedule-card
        sensor: sensor.dreame_a2_mower_schedule_count
```

Keep the sibling markdown card for "Editing limitation" notes if it's already useful, or remove it (the new card subsumes the placeholder).

- [ ] **Step 3: Validate YAML + commit**

```bash
python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print('YAML OK')"
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): wire custom schedule card into Schedule view"
```

---

## Task 20: Cleanup — delete `_write_setting_placeholder`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Verify no callers remain**

```
grep -rn "_write_setting_placeholder" custom_components/dreame_a2_mower/ tests/ 2>/dev/null | grep -v __pycache__
```

Expected: 1 result — the definition itself in `coordinator.py`. If any other matches appear, fix them first (they're stragglers from earlier rewires).

- [ ] **Step 2: Delete the method**

In `custom_components/dreame_a2_mower/coordinator.py`, find `async def _write_setting_placeholder(` and delete the entire method body.

- [ ] **Step 3: Run full suite**

```
python -m pytest -q
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "refactor(coordinator): remove _write_setting_placeholder (no callers)"
```

---

## Task 21: Documentation updates

**Files:**
- Modify: `docs/research/g2408-research-journal.md` (SCHEDULE blob format + Systemic finding)
- Create: `docs/research/cloud-write-reference.md` (general read/write reference)
- Modify: `docs/TODO.md` (close 3 entries, mark MAP write as Phase 2)

- [ ] **Step 1: Update `docs/research/g2408-research-journal.md`**

Find the section `### SCHEDULE blob format (decoded 2026-05-08)`. Replace the byte-format diagram with the variable-length version:

```
Record format (variable length, 7/8/9 bytes by action_type):

  +------+--------+------------+-----------+-----------+----------+--+--+------+
  | 0xAA |  len   | day|action |  time_lo  |  time_hi  | reserved |  |  | 0xED |
  +------+--------+------------+-----------+-----------+----------+--+--+------+
     0       1          2            3            4          5     6  7    [last]

  byte 0:  0xAA — start sentinel
  byte 1:  total record length (7=All-area, 8=Zone, 9=Edge)
  byte 2:  high nibble = weekday (1=Mon..7=Sun)
           low nibble  = action_type (0=All-area, 1=Zone, 2=Edge)
  byte 3:  time_lo
  byte 4:  high nibble = action_type (redundant — likely format discriminator)
           low nibble  = time_hi  →  time_min = byte[3] | ((byte[4] & 0x0F) << 8)
  byte 5:  reserved (always 0x00 in observed data)
  byte 6:  Zone/Edge: zone_id; All-area: 0xED end sentinel
  byte 7:  Zone: 0xED end sentinel; Edge: extra reserved byte (always 0x00)
  byte 8:  Edge only: 0xED end sentinel
```

Action codes (verified live 2026-05-08 with user's app-added Zone Wed 16:00 + Edge Sat 19:00):
- `0` = All-area mowing
- `1` = Zone mowing (zone_id at byte 6)
- `2` = Edge mowing (zone_id at byte 6, reserved2 at byte 7)

Find the section `#### Systemic finding: g2408 cloud rejects direct \`set_properties\` for most siids (2026-05-08)`. Append a "RESOLVED" note at the top of that section:

```markdown
**RESOLVED 2026-05-08** — the alternative dispatch path is the
`dreame-user-iot/iotuserdata/setDeviceData` endpoint with payload
`{"did": <did>, "data": {<chunked-key>: <value>, ...}}`. Server-enforced
1024-char chunk cap; large blobs split as `KEY.0..N + KEY.info`.
Verified writable end-to-end: AI_HUMAN.0, SCHEDULE.0, SETTINGS chunked.

For the full read/write reference see `docs/research/cloud-write-reference.md`.
```

(Then keep the original "Two write attempts via cloud_client.set_property..." paragraph as historical record below.)

- [ ] **Step 2: Create `docs/research/cloud-write-reference.md`**

Create the new file with:

```markdown
# Cloud read/write reference (g2408)

This document is the canonical reference for talking to g2408's Dreame
Cloud (`eu.iot.dreame.tech:19973`). It covers both READ and WRITE paths
for the chunked-batch surface.

## Authentication

`DreameA2CloudClient(username, password, country="eu")` then
`client.login()`. Region for the user's account is `eu`. After login,
call `client.get_devices()` to discover the device, then
`client.get_device_info()` to populate `_host` (needed for routing).

## READ — `get_batch_device_datas([])`

The empty-list batch returns ALL chunked keys the device has.
Endpoint: `dreame-user-iot/iotuserdata/getDeviceData` (via wrapper).
Payload: `{"did": <did>, "model": [<key_list_or_empty>]}`.
Returns: `{<key>: <value>, ...}` dict.

Confirmed key families (g2408 fw 4.3.6_0550):
- `MAP.0..45 + MAP.info` — boundary geometry, mowing zones, exclusion
  zones, etc. Map 0 + Map 1 split at MAP.info byte offset.
- `M_PATH.0..N + M_PATH.info` — persisted mow trajectories from prior
  sessions. Per-map split at M_PATH.info byte offset.
- `SETTINGS.0..N + SETTINGS.info` — per-map mowing-behaviour settings
  (mowingHeight, mowingDirection, edgeMowingAuto, etc.). Dual-level
  structure: two top-level entries, both `mode: 0`. Entry 0 is
  canonical; entry 1's semantic is unknown.
- `SCHEDULE.0 + SCHEDULE.info` — schedule slots + plans. JSON shape
  `{"d": [[id, mode, name, base64_blob], ...], "v": version}`.
- `AI_HUMAN.0` — Capture Photos AI Obstacles toggle. JSON-encoded bool.
- `FBD_NTYPE.0 + .info` — forbidden-area node types per map.
- `OTA_INFO.0 + .info` — firmware update status `(int, percent_int)`.
- `TASKID.0 + .info` — current/last task ID.
- `prop.s_*` — Xiaomi-style standalone properties (auth_config, auto_upgrade, pri_plugin).

## WRITE — `setDeviceData` (the chunked-batch write surface)

**Confirmed working 2026-05-08 for AI_HUMAN, SCHEDULE, SETTINGS.**

Endpoint: `dreame-user-iot/iotuserdata/setDeviceData`
Payload: `{"did": <did>, "data": {<key>: <value>, ...}}`
Wrapper: `cloud_client.set_batch_device_datas(props)` (the wrapper
sends payload under `data`, NOT `model`).

**Server-enforced cap: 1024 chars per value.** Large blobs need
chunking: `KEY.0..N + KEY.info(total_length_str)`.

Use `cloud_client.write_chunked_key(key_prefix, value, info=None)` —
handles chunking automatically. `info` defaults to `str(len(value))`
when chunking; omitted for single-chunk writes (matches the
AI_HUMAN.0 / SCHEDULE.0 single-chunk pattern observed live).

**Success response:** `{"code": 0, "success": true, "msg": "设置成功"}`
("setup successful" in Chinese).

**Common failure response:**
- `{"code": 10007, "msg": "value值不能超过1024个字符"}` — value > 1024
  chars not chunked.
- `{"code": 10007, "msg": "data:must not be empty"}` — payload sent
  under wrong field name (e.g. `model` instead of `data`).
- `{"code": 80001, "msg": "设备可能不在线..."}` — wrong RPC path
  entirely (this is the rejection direct `set_properties` gives for
  most siids on g2408 — use this endpoint instead).

## Confirmed-writable keys (Phase 1)

| Key | Single-chunk? | Notes |
|---|---|---|
| `AI_HUMAN.0` | yes | JSON-encoded bool: `'"true"'` / `'"false"'` |
| `SCHEDULE.0` | yes (typically <500 chars) | Bump `v` field on each write |
| `SETTINGS.0..N` | no — dual-level structure ~1780 chars | Read-modify-write entry 0 |

## TBD (Phase 2/3)

| Key | Status | Notes |
|---|---|---|
| `MAP.0..N` | NOT TESTED | Risk: corrupting boundary geometry could brick the map. Phase 2 — needs auto-backup mechanism. |
| `M_PATH.0..N` | NOT TESTED | Likely writable (same surface) but writing prior trajectories has no obvious user value. |
| `OTA_INFO.0` | UNSAFE | Firmware-managed; do not write. |
| `TASKID.0` | UNSAFE | Firmware-managed; do not write. |
| `FBD_NTYPE.0` | NOT TESTED | Phase 2 — likely writable; correlates with map editing. |
| `prop.s_*` | NOT TESTED | Probably read-only Xiaomi metadata. |

## Why `set_properties` (MIoT path) doesn't work for most siids

Direct MIoT `set_property(siid, piid, value)` rejects with **80001**
("device may be offline / command timeout") for most siids on g2408.
Tried 2026-05-08:
- `s8.2` (SCHEDULE per upstream docs) — 80001
- `s4.22` (AI_DETECTION per upstream docs) — 80001

The setDeviceData chunked-batch endpoint is the working alternative
for everything in the cloud-batch read surface. Direct MIoT may still
work for siids that came up in the integration's existing tested set
(`s2.50` routed_action for tasks, etc.).

## Live-test harness

Probes preserved in `/tmp/`:
- `probe_schedule_write.py` — schedule add/restore round-trip
- `probe_ai_human_write.py` — toggle round-trip
- `probe_writable_surface.py` — SETTINGS chunked round-trip
- `probe_batch_write.py` — payload-shape discovery (the original
  finding of `data` vs `model` field)

All bypass HA — pure Python with stubbed `homeassistant.const` import,
direct cloud_client usage. Useful template for Phase 2/3 probing.
```

- [ ] **Step 3: Update `docs/TODO.md`**

Open `docs/TODO.md` and:

a) **DELETE** these three entries (now resolved):
- `### Capture SETTINGS write wire format`
- `### Capture SCHEDULE write dispatch path (encoder is done)`
- `### AI_HUMAN write capability`

b) **ADD** at the top of "## Open" — a new entry for Phase 2:

```markdown
### Phase 2: MAP write — programmatic boundary/zone editing

**Why:** With chunked-batch writes confirmed working (Phase 1 done in
v1.0.2a1), the MAP surface is the next big capability. Drawing
boundaries and editing mowing/exclusion zones from HA without walking
the mower would be a major UX win.
**Done when:** A safe MAP write surface exists with auto-backup of the
current MAP blob before any write, restore-from-backup mechanism, and
a Lovelace card for boundary editing.
**Status:** open
**Cross-refs:** spec
`docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
"Phase 2"; `docs/research/cloud-write-reference.md`.
```

c) **ADD** a separate "EdgeMaster / Mowing Efficiency cloud field re-verification" entry:

```markdown
### Re-verify EdgeMaster / Mowing Efficiency cloud-field correlations

**Why:** `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md`
catalogued EdgeMaster (`s6p2[2]`) and Mowing Efficiency (`s6p2[1]`)
as BT-only / not-in-cloud-CFG. Those claims predate the
2026-05-08 cloud-discovery findings and may be outdated; both could
now be writable via `setDeviceData` if the cloud surfaces them under a
chunked-batch key we haven't probed.
**Done when:** Toggle each in the app while monitoring the empty-batch
read; if any chunked-batch key changes, surface as a new entity. If
neither changes, document as confirmed BT-only post-cloud-discovery.
**Status:** open
**Cross-refs:** historical doc; `docs/research/cloud-write-reference.md`.
```

- [ ] **Step 4: Validate + commit**

```bash
python -m pytest -q
git add docs/research/g2408-research-journal.md docs/research/cloud-write-reference.md docs/TODO.md
git commit -m "docs: SCHEDULE variable-length format + cloud-write-reference; close 3 TODOs"
```

---

## Task 22: Version bump + release v1.0.2a1

**Files:**
- Modify: `manifest.json` (via `tools/release.sh`)

- [ ] **Step 1: Write release notes**

```bash
cat > /tmp/release_1_0_2a1_notes.md <<'EOF'
## v1.0.2a1 — Integration is now read/write

The 15 SETTINGS-driven entities + AI_HUMAN switch + SCHEDULE all
become writable via the newly-discovered `setDeviceData` chunked-
batch endpoint. Previously every SETTINGS entity write was a no-op
that just logged + refreshed; now they actually mutate cloud state.

### What you'll see

- All number / switch / select entities under SETTINGS now write back
  to the cloud when changed in HA. The Dreame app will reflect the
  change within a few seconds.
- `switch.dreame_a2_mower_capture_photos_ai_obstacles` (renamed from
  ai_human_detection — entity_id unchanged) actually toggles now.
- New custom Lovelace card on the Work Logs > Schedule view for
  add/edit/delete of mowing plans. Calls a new
  `dreame_a2_mower.set_schedule_plans` service under the hood.
- Three new switches matching the app's per-category AI toggles:
  - `switch.dreame_a2_mower_ai_recognition_humans`
  - `switch.dreame_a2_mower_ai_recognition_animals`
  - `switch.dreame_a2_mower_ai_recognition_objects`
  These replace the old `number.dreame_a2_mower_obstacle_avoidance_ai`
  bitfield.

### App-mirror naming pass

Several entity labels updated to match the Dreame app exactly. Entity
unique_ids unchanged so existing automations keep working. New labels:
- "Mowing height" → "Mowing Height"
- "Mowing direction" → "Mowing Direction"
- "Mowing direction mode" → "Mowing Pattern" (options now Striped /
  Crisscross / Chequerboard)
- "Edge mowing auto" → "Automatic Edge Mowing"
- "Edge mowing safe" → "Safe Edge Mowing"
- "Edge mowing obstacle avoidance" → "Obstacle Avoidance on Edges"
- "Obstacle avoidance enabled" → "LiDAR Obstacle Recognition"
- "Obstacle avoidance height" → "Obstacle Avoidance Height"
- "Obstacle avoidance distance" → "Obstacle Avoidance Distance"
- "AI human detection" → "Capture Photos AI Obstacles"

### Fixed: SCHEDULE decoder broke on Zone/Edge plans

The previous decoder hardcoded 7-byte records and silently mis-parsed
any Zone (8-byte) or Edge (9-byte) plan. Now handles variable-length
records correctly. `sensor.dreame_a2_mower_schedule_count` attributes
include `zone_id` per plan + correct action labels (all_area / zone /
edge).

### Manual cleanup needed

After upgrade, remove the orphaned entity from HA's registry:
- `number.dreame_a2_mower_obstacle_avoidance_ai`

(If you used this in any automation, replace with the relevant of the
3 new `switch.ai_recognition_*` entities.)

### Failure handling

If a write is rejected by the cloud (network error or server-side
validation), the entity reverts to the previous value and a
persistent_notification appears with the reason. Notifications dedupe
per entity_id so repeat failures replace rather than stack.

### Out of scope (Phase 2)

- MAP write (drawing boundaries / zones from HA) — needs an auto-
  backup mechanism before it can ship safely.
- Other chunked keys (FBD_NTYPE, M_PATH) — opt-in per use case.
- EdgeMaster / Mowing Efficiency cloud-field re-verification — the
  historical "BT-only" claim predates the cloud-discovery findings;
  one of them might actually be writable here too.
EOF
```

- [ ] **Step 2: SCP the new card + dashboard yaml + run release**

```bash
sshpass -p $(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt) ssh -o StrictHostKeyChecking=no root@$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt) 'mkdir -p /homeassistant/www/dreame_a2_mower'
sshpass -p $(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt) scp -o StrictHostKeyChecking=no dashboards/cards/dreame-a2-schedule-card.js root@$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt):/homeassistant/www/dreame_a2_mower/dreame-a2-schedule-card.js
sshpass -p $(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt) scp -o StrictHostKeyChecking=no dashboards/mower/dashboard.yaml root@$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt):/homeassistant/dashboards/mower/dashboard.yaml
tools/release.sh 1.0.2a1 --notes-file /tmp/release_1_0_2a1_notes.md
```

Expected: tests pass, manifest bumped to `1.0.2a1`, tag pushed, GitHub release created (Latest, not prerelease, not draft), HACS refresh triggered.

- [ ] **Step 3: Orphan cleanup**

After HACS picks up the new release + the user restarts HA, remove the orphaned `number.dreame_a2_mower_obstacle_avoidance_ai` entity from the registry:

```bash
python3 - <<'PY'
import json
import websocket
lines = open("/data/claude/homeassistant/ha-credentials.txt").read().splitlines()
host, llat = lines[0], lines[3]
ws = websocket.create_connection(f"ws://{host}:8123/api/websocket", timeout=10)
ws.recv()
ws.send(json.dumps({"type": "auth", "access_token": llat}))
ws.recv()
ws.send(json.dumps({
    "id": 1,
    "type": "config/entity_registry/remove",
    "entity_id": "number.dreame_a2_mower_obstacle_avoidance_ai",
}))
print("remove orphan:", ws.recv())
ws.close()
PY
```

- [ ] **Step 4: Live-verify the writes**

In HA's UI:
1. Toggle `switch.dreame_a2_mower_automatic_edge_mowing` — verify the Dreame app reflects the change
2. Change `number.dreame_a2_mower_mowing_height` — verify the app reflects the change
3. Toggle `switch.dreame_a2_mower_ai_recognition_humans` — verify
4. Open the Schedule view; add a test plan via the custom card — verify it appears in the app
5. Delete the test plan — verify it disappears in the app

If any write is rejected, check `system_log/list` via WebSocket for the rejection reason — the failure-handling layer logs full response bodies.

- [ ] **Step 5: Commit (if release.sh didn't already)**

`tools/release.sh` commits the manifest bump itself. No extra commit needed.
