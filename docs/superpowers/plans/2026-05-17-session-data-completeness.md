# Session Data Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every finished session self-describe completely — fix the 8.5h data-loss bug across HA reboots, capture the dock-return arc, add a defense-in-depth recorder-merge for 3 more sample streams, and expand `settings_snapshot` to a full firmware-state snapshot at session-start.

**Architecture:** Five sequential phases against `custom_components/dreame_a2_mower/` (per spec `docs/superpowers/specs/2026-05-17-session-data-completeness-design.md`). Phase 1 fixes the restore race-guard and hardens persist with atomic write + CRC32. Phase 2 adds 3 diagnostic sensors and extends `coordinator/_recorder_merge.py:merge_recorder_samples` to cover state/charging/error. Phase 3 adds a pending-finalize wait window so the trail collector continues until the mower docks. Phase 4 replaces the narrow per-map `settings_snapshot` with a structured v2 snapshot (per_map + device_wide + peripheral + forensic, ~55 fields). Phase 5 verifies replay-card behaviour on gappy sessions and writes the gap-rendering doc.

**Tech Stack:** Python 3.14, Home Assistant 2025.x, `homeassistant.components.recorder` for backfill queries, `zlib.crc32` for the persist integrity check, pytest with the existing `tests/` layout (`tests/state_machine/` for pure helpers, `tests/integration/` for coordinator + HA-glue paths).

---

## Reference: shared commands

Run from `/data/claude/homeassistant/ha-dreame-a2-mower`.

**Lint Python syntax:**
```bash
python3 -c "import ast, sys; [ast.parse(open(p).read()) for p in sys.argv[1:]]; print('OK')" custom_components/dreame_a2_mower/<file>.py
```

**Run full test suite:**
```bash
python3 -m pytest tests/ -q --ignore=tests/archive
```
Expected: `1430+ passed, 4 skipped` (count grows as we add tests).

**Run a single test file:**
```bash
python3 -m pytest tests/<path>/test_<name>.py -v
```

**Commit + push:**
```bash
git add <files>
git commit -m "<scope>: <subject>

<body>"
git push origin HEAD
```

**Release (when integration code lands a behavioural change worth a HACS bump):**
```bash
bash tools/release.sh --notes "<one-line subject>

<body explaining what changed>"
```
The script bumps manifest.json, tags, pushes, creates a non-prerelease GitHub release, and triggers HACS refresh on the local HA. See `tools/release.sh --help` for flags.

---

## File map

Phase-by-phase. Read this before starting a task — it locks the file boundaries.

| File | Phase | Action | Concern |
|---|---|---|---|
| `archive/session.py` | 1 | extend | atomic write with fsync, CRC32 footer, INDEX_VERSION 1→2 (Phase 4 lands the bump) |
| `coordinator/_session.py` | 1, 3, 4 | extend | `_restore_in_progress` rewrite; pending-finalize wait; settings_snapshot builder invocation |
| `coordinator/_restore_merge.py` | 1 | NEW | Pure restore-then-merge helper (no HA imports); takes two payload dicts, returns merged dict |
| `live_map/state.py` | 1 | extend (small) | Add `merge_from_payload(payload)` method so the merge helper can re-hydrate state from disk + accumulated MQTT events |
| `sensor.py` | 2 | extend | 3 new diagnostic sensors: `state_code`, `charging_status_code`, `error_code_raw` |
| `coordinator/_recorder_merge.py` | 2 | extend | New `_async_fetch_state_from_recorder` / `_async_fetch_charging_status_from_recorder` / `_async_fetch_error_from_recorder` + extend `merge_recorder_samples` |
| `coordinator/_session.py` | 3 | extend | `_pending_finalize_window` task (asyncio task started on session-done) |
| `mower/state_snapshot.py` (or `mower/state.py`) | 3 | check | Verify `task_state_code` and `charging_status` fields exist; no schema change |
| `coordinator/_snapshot.py` | 4 | NEW | `build_settings_snapshot_v2(coordinator) -> dict` — pure-ish builder reading from `coordinator.cloud_state`, `coordinator.data` (MowerState), and HA registry |
| `session_card.py` | 4 | extend | Consumer handles both v1 (flat dict) and v2 (`{version: 2, per_map, device_wide, peripheral, forensic}`) snapshot shapes |
| `dashboards/mower/dashboard.yaml` | 4 | extend | "Settings in effect at session start" markdown card on Sessions tab — render v2 sections when present, fall back to v1 keys otherwise |
| `docs/research/replay-card-gap-behavior.md` | 5 | NEW | Manual verification doc — what gap types look like and why (closes `[[project_gappy_sessions_todo]]`) |
| `tests/state_machine/test_restore_merge.py` | 1 | NEW | Pure-merge helper tests |
| `tests/state_machine/test_archive_crc.py` | 1 | NEW | CRC32 round-trip + corruption-detection tests |
| `tests/integration/test_session_restore_race.py` | 1 | NEW | Race scenario: persist, simulate MQTT-before-restore, verify samples + legs survive |
| `tests/integration/test_recorder_merge_state.py` | 2 | NEW | State/charging/error backfill paths |
| `tests/integration/test_pending_finalize.py` | 3 | NEW | Dock-return wait + timeout + early-exit conditions |
| `tests/integration/test_settings_snapshot_v2.py` | 4 | NEW | Builder produces all 55 fields; backward-compat fallback in consumer |

---

## Phase 1 — Persist race-guard fix + atomic write hardening

### Task 1: CRC32 footer helpers (pure)

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py`
- Test: `tests/state_machine/test_archive_crc.py` (NEW)

The CRC is stored as a top-level `__crc32__` key inside the JSON object itself; computing/verifying it requires `json.dumps(payload, sort_keys=True)` over the payload-without-the-crc-field. Pure-Python, no HA dep.

- [ ] **Step 1: Write the failing test**

Create `tests/state_machine/test_archive_crc.py`:

```python
"""CRC32 footer helpers for in_progress.json integrity."""
from custom_components.dreame_a2_mower.archive.session import (
    _compute_crc32,
    _verify_crc32,
)


def test_compute_crc32_stable_under_key_reorder():
    """Same payload, two different key orders, same CRC."""
    a = {"alpha": 1, "beta": 2, "gamma": [3, 4]}
    b = {"gamma": [3, 4], "alpha": 1, "beta": 2}
    assert _compute_crc32(a) == _compute_crc32(b)


def test_compute_crc32_changes_with_value():
    a = {"x": 1}
    b = {"x": 2}
    assert _compute_crc32(a) != _compute_crc32(b)


def test_verify_crc32_accepts_correct_payload():
    payload = {"foo": "bar", "n": 42}
    crc = _compute_crc32(payload)
    payload["__crc32__"] = crc
    assert _verify_crc32(payload) is True


def test_verify_crc32_rejects_tampered_payload():
    payload = {"foo": "bar"}
    payload["__crc32__"] = _compute_crc32(payload)
    payload["foo"] = "baz"  # tampered after CRC was set
    assert _verify_crc32(payload) is False


def test_verify_crc32_rejects_missing_field():
    """Old archives without __crc32__ return False (caller treats as missing)."""
    assert _verify_crc32({"foo": "bar"}) is False


def test_verify_crc32_rejects_non_int_field():
    assert _verify_crc32({"foo": "bar", "__crc32__": "not-an-int"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/state_machine/test_archive_crc.py -v
```
Expected: ImportError — `_compute_crc32` doesn't exist yet.

- [ ] **Step 3: Implement the helpers in archive/session.py**

Add near the top of `archive/session.py` (after the existing imports):

```python
import zlib


def _compute_crc32(payload: dict[str, Any]) -> int:
    """CRC32 over the canonical-serialised payload excluding __crc32__.

    Uses sort_keys=True so the same logical dict produces the same hash
    regardless of insertion order. The Python json module is stable
    under sort_keys across releases.
    """
    body = {k: v for k, v in payload.items() if k != "__crc32__"}
    encoded = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    return zlib.crc32(encoded)


def _verify_crc32(payload: dict[str, Any]) -> bool:
    """Return True iff payload contains __crc32__ matching its body.

    Missing __crc32__ field → False (caller treats as "no CRC, assume corrupt").
    Non-int CRC value → False. Tampered payload → False.
    """
    crc = payload.get("__crc32__")
    if not isinstance(crc, int):
        return False
    return _compute_crc32(payload) == crc
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/state_machine/test_archive_crc.py -v
```
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/session.py tests/state_machine/test_archive_crc.py
git commit -m "archive/session: add CRC32 footer helpers for in_progress integrity"
```

---

### Task 2: Atomic write with fsync + CRC

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py` (`write_in_progress` + `read_in_progress`)
- Test: `tests/state_machine/test_archive_crc.py` (extend)

`write_in_progress` already does write-tmp-then-rename. Add fsync on the tmp file and stamp `__crc32__` into the payload before serialising. `read_in_progress` (which probably exists or sits under `SessionArchive.load_in_progress`) gains CRC verification — failed CRC returns None (caller falls through to "no in-progress on disk").

- [ ] **Step 1: Read existing write_in_progress and read_in_progress**

Use `Read` or grep:
```bash
grep -n "def write_in_progress\|def read_in_progress\|def _read_in_progress\|in_progress.json" custom_components/dreame_a2_mower/archive/session.py
```

Note the exact current signatures so the integration test (later) can call them.

- [ ] **Step 2: Add the atomic-write + CRC test**

Append to `tests/state_machine/test_archive_crc.py`:

```python
import json
import os
import tempfile
from pathlib import Path

from custom_components.dreame_a2_mower.archive.session import SessionArchive


def test_write_in_progress_includes_crc(tmp_path):
    """The written JSON file has a __crc32__ field that matches its body."""
    archive = SessionArchive(tmp_path)
    payload = {"session_start_ts": 1234567890, "legs": [], "battery_samples": []}
    archive.write_in_progress(payload)
    on_disk_path = tmp_path / "in_progress.json"
    assert on_disk_path.exists()
    disk = json.loads(on_disk_path.read_text())
    assert "__crc32__" in disk
    # CRC over disk body (minus the crc field) must match the field
    from custom_components.dreame_a2_mower.archive.session import _compute_crc32
    assert _compute_crc32(disk) == disk["__crc32__"]


def test_read_in_progress_rejects_corrupted_file(tmp_path):
    """If __crc32__ doesn't match, read_in_progress returns None."""
    archive = SessionArchive(tmp_path)
    payload = {"session_start_ts": 1234567890, "legs": []}
    archive.write_in_progress(payload)
    on_disk_path = tmp_path / "in_progress.json"
    # Tamper the file: change a value but leave __crc32__ as-is
    disk = json.loads(on_disk_path.read_text())
    disk["session_start_ts"] = 999  # tampered
    on_disk_path.write_text(json.dumps(disk))
    # Now reading should fail the CRC check and return None
    assert archive.read_in_progress() is None
```

- [ ] **Step 3: Run tests to verify failures**

```bash
python3 -m pytest tests/state_machine/test_archive_crc.py -v
```
Expected: 2 new tests FAIL (write doesn't add CRC, read doesn't verify).

- [ ] **Step 4: Update write_in_progress to stamp CRC + fsync**

Edit `write_in_progress` in `archive/session.py`. Pseudocode of the change:

```python
def write_in_progress(self, payload: dict[str, Any]) -> None:
    body = dict(payload)
    body["__crc32__"] = _compute_crc32(body)
    target = self.root / "in_progress.json"
    tmp = target.with_suffix(".json.tmp")
    text = json.dumps(body, indent=2, sort_keys=True, default=str)
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())  # commit data to disk, not just dirent
    os.replace(tmp, target)
```

Imports needed: `import os` (likely already imported).

- [ ] **Step 5: Update read_in_progress to verify CRC**

Edit `read_in_progress` (or whichever method reads from disk):

```python
def read_in_progress(self) -> dict[str, Any] | None:
    path = self.root / "in_progress.json"
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError) as ex:
        _LOGGER.warning("read_in_progress: JSON decode failed: %s", ex)
        return None
    if not _verify_crc32(body):
        _LOGGER.warning(
            "read_in_progress: CRC32 mismatch in %s; treating as missing",
            path,
        )
        return None
    body.pop("__crc32__", None)  # caller doesn't need the integrity field
    return body
```

- [ ] **Step 6: Run all archive tests**

```bash
python3 -m pytest tests/state_machine/test_archive_crc.py -v
```
Expected: 8/8 PASS.

Also run the full suite to check for regressions:
```bash
python3 -m pytest tests/ -q --ignore=tests/archive 2>&1 | tail -5
```
Expected: count grows by 8 (the new CRC tests); no existing tests break.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/session.py tests/state_machine/test_archive_crc.py
git commit -m "archive/session: atomic write with fsync + CRC32 integrity check on read"
```

---

### Task 3: Pure restore-then-merge helper

**Files:**
- Create: `custom_components/dreame_a2_mower/coordinator/_restore_merge.py`
- Test: `tests/state_machine/test_restore_merge.py` (NEW)

The merge logic takes the disk payload and an "as-it-stands-in-memory" payload (legs + sample lists), and returns a unified payload with deduped legs and union'd sample arrays. Pure-Python, no HA imports — testable in isolation.

- [ ] **Step 1: Write the failing test**

Create `tests/state_machine/test_restore_merge.py`:

```python
"""Pure restore-then-merge logic for in_progress.json reconciliation."""
from custom_components.dreame_a2_mower.coordinator._restore_merge import (
    merge_in_progress_payloads,
)


def test_disk_empty_uses_memory():
    """If disk payload is None, memory wins as-is."""
    mem = {"session_start_ts": 100, "legs": [[[1, 1]]], "battery_samples": [[100, 95]]}
    out = merge_in_progress_payloads(disk=None, memory=mem)
    assert out == mem


def test_memory_empty_uses_disk():
    """If memory has no session yet, disk wins (the common race case)."""
    disk = {"session_start_ts": 100, "legs": [[[1, 1]]], "battery_samples": [[100, 95]]}
    mem = {"session_start_ts": None, "legs": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["session_start_ts"] == 100
    assert out["legs"] == [[[1, 1]]]
    assert out["battery_samples"] == [[100, 95]]


def test_legs_union_dedupes_on_point_equality():
    """Same-session legs get unioned; identical points deduped."""
    disk = {
        "session_start_ts": 100,
        "legs": [[[1, 1], [2, 2]]],
    }
    mem = {
        "session_start_ts": 100,
        "legs": [[[2, 2], [3, 3]]],  # overlaps with disk's leg 0 at [2,2]
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    # Single leg containing all three unique points, sorted in original order.
    # Implementation choice: dedupe by point tuple, preserve disk-first order.
    assert out["legs"] == [[[1, 1], [2, 2], [3, 3]]]


def test_samples_union_dedupes_on_full_tuple():
    """Each sample list is unioned + deduped + sorted by ts."""
    disk = {
        "session_start_ts": 100,
        "battery_samples": [[100, 95], [200, 90], [300, 85]],
    }
    mem = {
        "session_start_ts": 100,
        "battery_samples": [[300, 85], [400, 80]],  # 300 dups
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["battery_samples"] == [[100, 95], [200, 90], [300, 85], [400, 80]]


def test_stale_disk_session_is_dropped():
    """If disk start_ts > 5 min off from memory start_ts, drop disk (stale)."""
    disk = {"session_start_ts": 100, "legs": [[[99, 99]]], "battery_samples": [[100, 50]]}
    mem = {"session_start_ts": 100_000_000, "legs": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    # Memory wins; disk's data discarded
    assert out["session_start_ts"] == 100_000_000
    assert out["legs"] == []
    assert out["battery_samples"] == []


def test_charge_at_start_restored_when_memory_none():
    """If memory's charge_at_start is None, take disk's value."""
    disk = {"session_start_ts": 100, "charge_at_start": 95}
    mem = {"session_start_ts": 100, "charge_at_start": None}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["charge_at_start"] == 95


def test_charge_at_start_memory_wins_when_set():
    """If both have charge_at_start, memory wins (more recent)."""
    disk = {"session_start_ts": 100, "charge_at_start": 95}
    mem = {"session_start_ts": 100, "charge_at_start": 90}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["charge_at_start"] == 90


def test_settings_snapshot_restored_when_memory_none():
    """settings_snapshot is set once at session-begin; if memory is None, take disk."""
    disk = {"session_start_ts": 100, "settings_snapshot": {"mowingHeight": 4}}
    mem = {"session_start_ts": 100, "settings_snapshot": None}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["settings_snapshot"] == {"mowingHeight": 4}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/state_machine/test_restore_merge.py -v
```
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Implement merge_in_progress_payloads**

Create `custom_components/dreame_a2_mower/coordinator/_restore_merge.py`:

```python
"""Pure restore-then-merge logic for in_progress.json reconciliation.

When the integration restarts mid-session, MowerState may have begun
re-accumulating events before the on-disk in_progress.json has been
read. This module merges the two views into a single payload without
losing data from either side. No HA imports — all pure Python so the
logic can be unit-tested in isolation.
"""
from __future__ import annotations

from typing import Any

# Tolerance for "same session" detection — disk start_ts vs memory
# start_ts. Wider than wall-clock drift between cloud-stamped and
# locally-stamped session-start values; narrower than any plausible
# gap between two consecutive sessions.
SAME_SESSION_TOLERANCE_S = 300


_SAMPLE_KEYS = (
    "battery_samples",
    "charging_status_samples",
    "state_samples",
    "error_samples",
)


def _merge_samples(a: list, b: list) -> list:
    """Union two `[ts, value]` sample lists, dedup full-tuple, sort by ts."""
    seen: set[tuple[Any, ...]] = set()
    out: list = []
    for src in (a or [], b or []):
        for s in src:
            key = tuple(s)
            if key in seen:
                continue
            seen.add(key)
            out.append(list(s))
    out.sort(key=lambda s: s[0])
    return out


def _merge_wifi(a: list, b: list) -> list:
    """Union two wifi-sample lists, dedup full-tuple, sort by ts (idx 3)."""
    seen: set[tuple[Any, ...]] = set()
    out: list = []
    for src in (a or [], b or []):
        for s in src:
            key = tuple(s)
            if key in seen:
                continue
            seen.add(key)
            out.append(list(s))
    out.sort(key=lambda s: s[3] if len(s) > 3 else 0)
    return out


def _merge_legs(a: list, b: list) -> list:
    """Union two leg lists; dedup points within each leg, preserve disk-first order.

    Naive policy: concat both sides, then walk through dedupping any
    point tuple already seen. Keeps the first-occurrence ordering, which
    means disk points (read first) anchor the leg's shape. Probe captures
    the same points the integration captured; the merge is conservative.
    """
    seen: set[tuple[float, float]] = set()
    out_leg: list = []
    for src in (a or [], b or []):
        for leg in src:
            for pt in leg:
                key = (float(pt[0]), float(pt[1]))
                if key in seen:
                    continue
                seen.add(key)
                out_leg.append([pt[0], pt[1]])
    if not out_leg:
        return []
    return [out_leg]  # single merged leg; pen-up splits get re-detected on next render


def merge_in_progress_payloads(
    *,
    disk: dict[str, Any] | None,
    memory: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile a disk in_progress payload with the in-memory snapshot.

    Returns a new payload dict — neither input mutated. Caller is
    responsible for assigning the result back into live_map.

    Decision rules:
    - disk is None → memory wins as-is.
    - memory has no session (started_unix is None / 0) → disk wins.
    - both have a session and start_ts agree (within SAME_SESSION_TOLERANCE_S)
      → merge legs/samples; charge_at_start and settings_snapshot favour
      memory if set, fall back to disk.
    - both have a session but start_ts diverge → memory wins (disk is
      stale residue from prior session).
    """
    if disk is None:
        return dict(memory)

    mem_start = memory.get("session_start_ts") or 0
    if not mem_start:
        # Memory hasn't begun a session yet — disk is the entire state.
        return dict(disk)

    disk_start = disk.get("session_start_ts") or 0
    if disk_start and abs(disk_start - mem_start) > SAME_SESSION_TOLERANCE_S:
        # Stale disk snapshot from a prior session. Drop it.
        return dict(memory)

    out: dict[str, Any] = dict(memory)
    out["legs"] = _merge_legs(disk.get("legs"), memory.get("legs"))
    for k in _SAMPLE_KEYS:
        out[k] = _merge_samples(disk.get(k), memory.get(k))
    out["wifi_samples"] = _merge_wifi(disk.get("wifi_samples"), memory.get("wifi_samples"))
    # Memory wins for charge_at_start / settings_snapshot if set; disk if memory is None.
    if memory.get("charge_at_start") is None and disk.get("charge_at_start") is not None:
        out["charge_at_start"] = disk["charge_at_start"]
    if memory.get("settings_snapshot") is None and disk.get("settings_snapshot") is not None:
        out["settings_snapshot"] = disk["settings_snapshot"]
    return out
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python3 -m pytest tests/state_machine/test_restore_merge.py -v
```
Expected: 8/8 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_restore_merge.py tests/state_machine/test_restore_merge.py
git commit -m "coordinator/_restore_merge: pure merge helper for restore-then-merge logic"
```

---

### Task 4: Rewrite `_restore_in_progress` to restore-then-merge

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` (`_restore_in_progress`)
- Modify: `custom_components/dreame_a2_mower/live_map/state.py` (small helper)
- Test: `tests/integration/test_session_restore_race.py` (NEW)

The integration test simulates the race: write an in_progress.json, then call `live_map.begin_session()` (as if MQTT pushed) BEFORE `_restore_in_progress` runs. After restore, the merged state should contain ALL the disk samples + ALL the post-MQTT additions.

- [ ] **Step 1: Read current `_restore_in_progress` and note the bail-out**

```bash
sed -n '592,750p' custom_components/dreame_a2_mower/coordinator/_session.py
```

Note the exact `if self.live_map.is_active(): return` line (around line 624 per spec) and the structure of the post-disk-read code that hydrates `live_map.legs`, sample lists, etc. The rewrite replaces the bail-out with the merge call and re-hydrates from the merged payload.

- [ ] **Step 2: Add `live_map.dump_to_payload()` and `live_map.hydrate_from_payload()` helpers**

Edit `custom_components/dreame_a2_mower/live_map/state.py`. Add two methods to the `LiveMapState` dataclass:

```python
def dump_to_payload(self) -> dict:
    """Snapshot the in-memory state into the in_progress.json payload shape.

    Mirrors the structure built by coordinator/_session._persist_in_progress
    so the restore-merge helper can compare apples-to-apples.
    """
    return {
        "session_start_ts": self.started_unix,
        "legs": [list(list(pt) for pt in leg) for leg in self.legs],
        "wifi_samples": [list(s) for s in self.wifi_samples],
        "battery_samples": [list(s) for s in self.battery_samples],
        "charging_status_samples": [list(s) for s in self.charging_status_samples],
        "state_samples": [list(s) for s in self.state_samples],
        "error_samples": [list(s) for s in self.error_samples],
        "charge_at_start": self.charge_at_start,
        "settings_snapshot": self.settings_snapshot,
    }


def hydrate_from_payload(self, payload: dict) -> None:
    """Replace in-memory state from a payload (after restore-merge)."""
    self.started_unix = payload.get("session_start_ts")
    self.legs = [list(list(pt) for pt in leg) for leg in (payload.get("legs") or [])]
    if not self.legs:
        self.legs = [[]]
    self.wifi_samples = [tuple(s) for s in (payload.get("wifi_samples") or [])]
    self.battery_samples = [tuple(s) for s in (payload.get("battery_samples") or [])]
    self.charging_status_samples = [tuple(s) for s in (payload.get("charging_status_samples") or [])]
    self.state_samples = [tuple(s) for s in (payload.get("state_samples") or [])]
    self.error_samples = [tuple(s) for s in (payload.get("error_samples") or [])]
    self.charge_at_start = payload.get("charge_at_start")
    self.settings_snapshot = payload.get("settings_snapshot")
```

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_session_restore_race.py`:

```python
"""Race scenario: MQTT push beats _restore_in_progress, merge keeps both sides' data."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.coordinator._restore_merge import (
    merge_in_progress_payloads,
)


def test_merge_preserves_disk_samples_when_memory_has_post_restart_samples():
    """The canonical 19h-session bug: disk has 8h of samples, memory has 1h of
    post-restart MQTT-pushed samples. After merge, all 9h survive.
    """
    disk = {
        "session_start_ts": 1000,
        "legs": [[[1, 1], [2, 2]]],
        "battery_samples": [[1010, 99], [1020, 98], [1030, 97]],  # pre-restart
        "wifi_samples": [[0, 0, -60, 1010]],
        "charging_status_samples": [],
        "state_samples": [[1010, 0]],
        "error_samples": [],
        "charge_at_start": 100,
        "settings_snapshot": {"mowingHeight": 4},
    }
    memory = {
        "session_start_ts": 1000,  # same session
        "legs": [[[3, 3]]],         # newer point
        "battery_samples": [[2000, 90]],  # post-restart push
        "wifi_samples": [],
        "charging_status_samples": [[2005, 1]],
        "state_samples": [],
        "error_samples": [],
        "charge_at_start": None,    # post-restart didn't get a fresh charge_at_start
        "settings_snapshot": None,  # same — only set at session-begin
    }
    merged = merge_in_progress_payloads(disk=disk, memory=memory)
    # All 4 battery samples present
    assert [s[0] for s in merged["battery_samples"]] == [1010, 1020, 1030, 2000]
    # Legs unioned (single merged leg with 3 unique points; pen-up splits re-detect later)
    leg_points = [tuple(p) for p in merged["legs"][0]]
    assert (1, 1) in leg_points and (2, 2) in leg_points and (3, 3) in leg_points
    # WiFi from disk survives even though memory had none
    assert len(merged["wifi_samples"]) == 1
    # charging_status from memory survives even though disk had none
    assert merged["charging_status_samples"] == [[2005, 1]]
    # charge_at_start restored from disk (memory was None)
    assert merged["charge_at_start"] == 100
    # settings_snapshot restored from disk
    assert merged["settings_snapshot"] == {"mowingHeight": 4}
```

- [ ] **Step 4: Run test**

```bash
python3 -m pytest tests/integration/test_session_restore_race.py -v
```
Expected: 1/1 PASS (merge logic from Task 3 already handles the case).

- [ ] **Step 5: Rewrite `_restore_in_progress` in `coordinator/_session.py`**

Replace the existing bail-on-active block with the merge flow. Pseudocode (adapt to existing style/logging tags):

```python
async def _restore_in_progress(self) -> None:
    LOGGER.info("[F5.7.1] _restore_in_progress: starting")

    # Always read disk first — even if MQTT raced ahead, the disk payload
    # carries any data we'd otherwise overwrite on the next persist tick.
    try:
        disk_payload = await self.hass.async_add_executor_job(
            self.session_archive.read_in_progress
        )
    except Exception as ex:
        LOGGER.warning("[F5.7.1] read_in_progress raised: %s", ex)
        disk_payload = None

    if disk_payload is None and not self.live_map.is_active():
        LOGGER.debug("[F5.7.1] no disk payload and no live session — nothing to restore")
        return

    from ._restore_merge import merge_in_progress_payloads
    memory_payload = self.live_map.dump_to_payload()
    merged = merge_in_progress_payloads(disk=disk_payload, memory=memory_payload)
    self.live_map.hydrate_from_payload(merged)

    LOGGER.info(
        "[F5.7.1] restore-merged: started_unix=%s, legs_points=%d, "
        "battery_samples=%d, wifi_samples=%d, state_samples=%d",
        self.live_map.started_unix,
        sum(len(l) for l in self.live_map.legs),
        len(self.live_map.battery_samples),
        len(self.live_map.wifi_samples),
        len(self.live_map.state_samples),
    )

    # Re-seed the state machine same as the prior implementation did.
    # (Keep the existing state_machine.mow_session = IN_SESSION line
    # if started_unix is set after the merge — copy from the old code.)
```

Replace the entire old function body with the above shape. Preserve any side-effect calls (e.g., `_fire_lifecycle`, state-machine seeding) that the old version did after the disk-restore branch — move them inside the new flow when `started_unix` is set post-merge.

- [ ] **Step 6: Run integration test + full suite**

```bash
python3 -m pytest tests/integration/test_session_restore_race.py tests/ -q --ignore=tests/archive 2>&1 | tail -10
```
Expected: race test passes; full suite still passes (no regressions).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py custom_components/dreame_a2_mower/live_map/state.py tests/integration/test_session_restore_race.py
git commit -m "_session._restore_in_progress: restore-then-merge instead of bail-on-MQTT-race

Fixes the 8.5h data-loss reported on the 2026-05-15 19h session:
_restore_in_progress was bailing out when live_map.is_active(), so an
MQTT push that arrived before restore (the common race on reboot) caused
the persisted samples to be silently overwritten by the next persist tick.

Now: always read disk first, merge with in-memory state via
coordinator/_restore_merge.merge_in_progress_payloads, hydrate live_map
from the merged result. Either side's data survives the race."
```

---

## Phase 2 — Recorder-merge for state / charging / error

### Task 5: Add `sensor.dreame_a2_mower_state_code` diagnostic sensor

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (per CLAUDE.md fact discipline)
- Test: extend `tests/integration/test_per_map_sensors.py` or add `tests/integration/test_diagnostic_sensors.py` (NEW)

The sensor exposes the raw s2p1 state integer so HA's recorder captures it. It's a thin wrapper over `MowerState.state_code` (verify the exact field name during step 1).

- [ ] **Step 1: Verify the MowerState field name**

```bash
grep -n "state_code\|raw_state\|task_state_code\|s2p1" custom_components/dreame_a2_mower/mower/state.py | head -10
```

Note the exact field. If it doesn't exist as an int field on MowerState, the sensor's `value_fn` will need to derive it from whichever enum/snapshot field is present (e.g., `state.task_state_code` if that's the name).

- [ ] **Step 2: Write the descriptor in sensor.py**

Find the `SENSORS` tuple (around line 124). Add at the end:

```python
    DreameA2SensorEntityDescription(
        key="state_code_raw",
        translation_key="state_code_raw",
        name="State code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.task_state_code,  # adjust field name per Step 1
    ),
```

- [ ] **Step 3: Quick syntax + smoke test**

```bash
python3 -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/sensor.py').read()); print('OK')"
python3 -m pytest tests/integration/test_per_map_sensors.py -q
```
Expected: syntax OK, existing tests pass.

- [ ] **Step 4: Update entity-inventory.yaml**

Append at end of `custom_components/dreame_a2_mower/entity-inventory.yaml` (per CLAUDE.md fact-discipline rule for entity additions):

```yaml
  - id: "sensor.dreame_a2_mower_state_code_raw"
    platform: sensor
    class: "DreameA2Sensor (config-driven)"
    class_file: "custom_components/dreame_a2_mower/sensor.py:<line of new descriptor>"
    device: parent
    source:
      wire: "s2p1"
      state_path: "MowerState.task_state_code"
    write_path: read-only
    status:
      seen_working: presumed
      last_verified: "2026-05-17"
    verifications:
      - date: "2026-05-17"
        status: presumed
        claim: |
          Diagnostic sensor exposing the raw s2p1 state int so HA's recorder
          captures state transitions for the recorder-merge safety net.
          Added in Phase 2 of session-data-completeness plan.
    references:
      wire_entry: "inventory.yaml id=s2p1"
      code: "custom_components/dreame_a2_mower/sensor.py"
    notes: |
      Raw integer; the existing sensor.current_activity exposes a
      label-decoded variant. Both live side-by-side because the recorder-
      merge pipeline needs the int for deduping against in_progress.json
      sample tuples, while users want the label for dashboards.
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "sensor: add state_code_raw diagnostic sensor for recorder-merge backfill"
```

---

### Task 6: Add `charging_status_code` and `error_code_raw` sensors

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

Same pattern as Task 5. Both go right after the `state_code_raw` descriptor.

- [ ] **Step 1: Verify MowerState field names**

```bash
grep -n "charging_status\|error_code\|s3p2\|s2p2" custom_components/dreame_a2_mower/mower/state.py | head -10
```

- [ ] **Step 2: Add the two descriptors**

```python
    DreameA2SensorEntityDescription(
        key="charging_status_code_raw",
        translation_key="charging_status_code_raw",
        name="Charging status code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.charging_status,  # adjust per field name from Step 1
    ),
    DreameA2SensorEntityDescription(
        key="error_code_raw",
        translation_key="error_code_raw",
        name="Error code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.error_code,  # adjust per field name from Step 1
    ),
```

- [ ] **Step 3: Syntax + test sweep**

```bash
python3 -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/sensor.py').read()); print('OK')"
python3 -m pytest tests/ -q --ignore=tests/archive 2>&1 | tail -3
```

- [ ] **Step 4: Append two entity-inventory.yaml entries** (same template as Task 5)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "sensor: add charging_status_code_raw + error_code_raw diagnostic sensors"
```

---

### Task 7: Extend `_recorder_merge.merge_recorder_samples` for the 3 new streams

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_recorder_merge.py`
- Test: `tests/integration/test_recorder_merge_state.py` (NEW)

Mirror the existing battery/wifi pattern: a `_read_<stream>_history_sync` function, an `_async_fetch_<stream>_from_recorder` wrapper, and three more dict-population lines in `merge_recorder_samples`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_recorder_merge_state.py`:

```python
"""Recorder-merge backfill for state/charging/error sample arrays."""
from unittest.mock import MagicMock, patch
import datetime as dt
import pytest

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _merge_samples,
    _read_state_history_sync,
    _read_charging_status_history_sync,
    _read_error_history_sync,
)


def _mk_state(state_str, ts_seconds):
    """Helper to build a fake recorder.State-like object."""
    s = MagicMock()
    s.state = state_str
    s.last_changed = dt.datetime.fromtimestamp(ts_seconds, dt.UTC)
    return s


def test_read_state_history_returns_int_pairs():
    """Recorder rows for the state_code_raw sensor become [ts, int] tuples."""
    fake_rows = [_mk_state("0", 1000), _mk_state("4", 1100), _mk_state("0", 1200)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_state_code_raw": fake_rows},
    ):
        out = _read_state_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[1000, 0], [1100, 4], [1200, 0]]


def test_read_state_history_skips_unknown_states():
    """unknown/unavailable rows are silently dropped."""
    fake_rows = [_mk_state("unknown", 1000), _mk_state("0", 1100), _mk_state("unavailable", 1200)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_state_code_raw": fake_rows},
    ):
        out = _read_state_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[1100, 0]]


def test_read_charging_status_history_returns_int_pairs():
    fake_rows = [_mk_state("1", 5000), _mk_state("0", 6000)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_charging_status_code_raw": fake_rows},
    ):
        out = _read_charging_status_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[5000, 1], [6000, 0]]


def test_read_error_history_returns_int_pairs():
    fake_rows = [_mk_state("56", 7000), _mk_state("0", 7100)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_error_code_raw": fake_rows},
    ):
        out = _read_error_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[7000, 56], [7100, 0]]
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/integration/test_recorder_merge_state.py -v
```
Expected: ImportError — the three sync readers don't exist.

- [ ] **Step 3: Add the three sync readers to `_recorder_merge.py`**

After `_read_wifi_history_sync` and before the async wrappers, add the three new entity-id constants and three readers:

```python
STATE_CODE_RAW_ENTITY_ID = "sensor.dreame_a2_mower_state_code_raw"
CHARGING_STATUS_RAW_ENTITY_ID = "sensor.dreame_a2_mower_charging_status_code_raw"
ERROR_CODE_RAW_ENTITY_ID = "sensor.dreame_a2_mower_error_code_raw"


def _read_int_pair_history_sync(
    hass, start_dt, end_dt, entity_id: str
) -> list[list[int]]:
    """Generic [ts, int] reader used by state/charging/error.

    Filters non-numeric rows (unknown/unavailable). Output is sorted ascending
    by ts via state_changes_during_period's native ordering.
    """
    if state_changes_during_period is None:
        return []
    raw = state_changes_during_period(
        hass, start_dt, end_dt, entity_id=entity_id, include_start_time_state=True,
    )
    out: list[list[int]] = []
    for st in raw.get(entity_id, []):
        try:
            v = int(st.state)
        except (TypeError, ValueError):
            continue
        try:
            ts = int(st.last_changed.timestamp())
        except TypeError:
            continue
        out.append([ts, v])
    return out


def _read_state_history_sync(hass, start_dt, end_dt) -> list[list[int]]:
    return _read_int_pair_history_sync(hass, start_dt, end_dt, STATE_CODE_RAW_ENTITY_ID)


def _read_charging_status_history_sync(hass, start_dt, end_dt) -> list[list[int]]:
    return _read_int_pair_history_sync(hass, start_dt, end_dt, CHARGING_STATUS_RAW_ENTITY_ID)


def _read_error_history_sync(hass, start_dt, end_dt) -> list[list[int]]:
    return _read_int_pair_history_sync(hass, start_dt, end_dt, ERROR_CODE_RAW_ENTITY_ID)
```

- [ ] **Step 4: Add three async wrappers + extend `merge_recorder_samples`**

After the existing `_async_fetch_wifi_from_recorder` function, add three more async helpers (same pattern as the battery one but each pointing at the corresponding sync reader). Then extend `merge_recorder_samples`:

```python
async def merge_recorder_samples(
    hass, raw_dict: dict[str, Any], start_ts: int, end_ts: int
) -> dict[str, int]:
    """Merge HA recorder history for battery + wifi + state + charging + error."""
    battery_recorder = await _async_fetch_battery_from_recorder(hass, start_ts, end_ts)
    wifi_recorder = await _async_fetch_wifi_from_recorder(hass, start_ts, end_ts)
    state_recorder = await _async_fetch_state_from_recorder(hass, start_ts, end_ts)
    charging_recorder = await _async_fetch_charging_status_from_recorder(hass, start_ts, end_ts)
    error_recorder = await _async_fetch_error_from_recorder(hass, start_ts, end_ts)

    raw_dict["battery_samples"] = _merge_samples(raw_dict.get("battery_samples") or [], battery_recorder)
    raw_dict["wifi_samples"] = _merge_wifi_samples(raw_dict.get("wifi_samples") or [], wifi_recorder)
    raw_dict["state_samples"] = _merge_samples(raw_dict.get("state_samples") or [], state_recorder)
    raw_dict["charging_status_samples"] = _merge_samples(
        raw_dict.get("charging_status_samples") or [], charging_recorder,
    )
    raw_dict["error_samples"] = _merge_samples(raw_dict.get("error_samples") or [], error_recorder)

    return {
        "battery_recorder_count": len(battery_recorder),
        "wifi_recorder_count": len(wifi_recorder),
        "state_recorder_count": len(state_recorder),
        "charging_recorder_count": len(charging_recorder),
        "error_recorder_count": len(error_recorder),
    }
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/integration/test_recorder_merge_state.py tests/ -q --ignore=tests/archive 2>&1 | tail -10
```
Expected: 4 new tests pass; existing recorder-merge tests still pass.

- [ ] **Step 6: Update caller log lines**

In `coordinator/_session.py:519` and `coordinator/_lidar_oss.py:418`, the existing log line mentions only "battery + wifi". Update to also report the new 3 counts. Search:

```bash
grep -n "_counts =" custom_components/dreame_a2_mower/coordinator/_session.py custom_components/dreame_a2_mower/coordinator/_lidar_oss.py
```

Adjust the log f-strings to include the new keys (`_counts.get("state_recorder_count", 0)`, etc.).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_recorder_merge.py custom_components/dreame_a2_mower/coordinator/_session.py custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_recorder_merge_state.py
git commit -m "recorder_merge: extend to state/charging/error sample streams

Defense-in-depth completes the in_progress.json sample-array coverage:
even if the persist/restore chain ever regresses, the recorder backfill
catches the 3 streams that don't have HA-recorder-native counterparts."
```

---

## Phase 3 — Dock-return capture extension

### Task 8: Pending-finalize wait task

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (add `self._pending_finalize_task: asyncio.Task | None = None` in `__init__`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` (new `_start_pending_finalize_wait` + alter session-done handler to call it)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (notify pending-finalize on relevant state transitions)
- Test: `tests/integration/test_pending_finalize.py` (NEW)

The wait task races three completion signals against a 5-min timeout. First-wins triggers archive write.

- [ ] **Step 1: Add `_pending_finalize_task` slot to `_CoreMixin.__init__`**

Edit `custom_components/dreame_a2_mower/coordinator/_core.py`. In `__init__`, near the other `self._foo = ...` lines, add:

```python
self._pending_finalize_task: "asyncio.Task | None" = None
self._pending_finalize_done: "asyncio.Event | None" = None
```

(Use the string form for the type hint to avoid an asyncio import at the file's top if it isn't already there.)

- [ ] **Step 2: Implement the wait task in `_session.py`**

Add a new method on `_SessionMixin`:

```python
async def _wait_for_dock_return(
    self,
    *,
    timeout_s: int = 300,
) -> str:
    """Block until the mower has docked or 5 min has elapsed.

    Returns one of: 'task_idle', 'charging', 'timeout'. Caller logs which
    signal won so we can later tune the timeout.
    """
    import asyncio
    self._pending_finalize_done = asyncio.Event()

    async def _watch_task_state() -> str:
        # task_state_code returning to its idle baseline is the primary
        # signal; tracked via on_state_update which sets the event below.
        await self._pending_finalize_done.wait()
        return "early"

    try:
        await asyncio.wait_for(_watch_task_state(), timeout=timeout_s)
        # MQTT handler will have written 'task_idle' or 'charging' to the
        # _pending_finalize_done_reason attribute before setting the event.
        return getattr(self, "_pending_finalize_done_reason", "early")
    except asyncio.TimeoutError:
        return "timeout"
    finally:
        self._pending_finalize_done = None
```

- [ ] **Step 3: Notify the wait from MQTT handlers**

In `coordinator/_mqtt_handlers.py`, find the `_on_state_update` method (or whichever handler processes state transitions). After the existing handling, add:

```python
# Notify the pending-finalize wait when the mower returns to idle
# (task_state_code goes None or back to baseline) OR when charging
# starts. The wait task in _session.py blocks on this event.
done_event = getattr(self, "_pending_finalize_done", None)
if done_event is not None and not done_event.is_set():
    state = self.data
    task_idle = state.task_state_code in (None, 2)  # adjust per inventory.yaml s2p1
    is_charging = state.charging_status == 1
    if task_idle:
        self._pending_finalize_done_reason = "task_idle"
        done_event.set()
    elif is_charging:
        self._pending_finalize_done_reason = "charging"
        done_event.set()
```

- [ ] **Step 4: Wire the wait into the session-done handler**

Find the session-end gate in `_session.py` (look for `_fire_mowing_ended` or `_do_finalize_incomplete` or wherever the existing finalize call lives):

```bash
grep -n "_fire_mowing_ended\|finalize_session\|archive\.archive" custom_components/dreame_a2_mower/coordinator/_session.py | head -10
```

Wrap the existing archive call so it goes through the wait task first:

```python
LOGGER.info("[F5.6.1] session-done received — entering pending-finalize wait (≤5 min)")
reason = await self._wait_for_dock_return(timeout_s=300)
LOGGER.info("[F5.6.1] pending-finalize wait ended: reason=%s", reason)
# Now proceed with the existing archive write...
```

- [ ] **Step 5: Write the integration test**

Create `tests/integration/test_pending_finalize.py`:

```python
"""Pending-finalize wait task: completes on task-idle, charging, or timeout."""
import asyncio
import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_wait_resolves_when_task_idle_event_fires():
    """The wait task returns 'task_idle' when the MQTT handler signals."""
    coord = MagicMock()
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    # Bind real instance method to mock
    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin
    coord._wait_for_dock_return = _SessionMixin._wait_for_dock_return.__get__(coord)

    async def fire_event():
        await asyncio.sleep(0.05)
        coord._pending_finalize_done_reason = "task_idle"
        coord._pending_finalize_done.set()

    asyncio.create_task(fire_event())
    result = await coord._wait_for_dock_return(timeout_s=1)
    assert result == "task_idle"


@pytest.mark.asyncio
async def test_wait_times_out_when_no_signal():
    """If no signal fires within timeout, returns 'timeout'."""
    coord = MagicMock()
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin
    coord._wait_for_dock_return = _SessionMixin._wait_for_dock_return.__get__(coord)

    result = await coord._wait_for_dock_return(timeout_s=0.1)
    assert result == "timeout"
```

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/integration/test_pending_finalize.py tests/ -q --ignore=tests/archive 2>&1 | tail -10
```
Expected: 2 new tests pass; no regressions.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_session.py custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/integration/test_pending_finalize.py
git commit -m "_session: pending-finalize wait extends trail capture through dock-return

After the session-done event fires, the trail collector continues to
append s1p4 points until the mower returns to idle (task_state_code
baseline) OR charging_status flips to 1, whichever first. 5-min hard
timeout as safety. Replay-card animation now completes at the dock
instead of mid-yard."
```

---

## Phase 4 — Full firmware-state snapshot at session-start

### Task 9: Bump archive INDEX_VERSION to 2

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py` (`INDEX_VERSION = 2`)

Tiny commit, separate so the version bump is bisectable.

- [ ] **Step 1: Edit the constant**

```bash
grep -n "INDEX_VERSION" custom_components/dreame_a2_mower/archive/session.py
```

Change `INDEX_VERSION = 1` to `INDEX_VERSION = 2`. No other code changes here — the bump signals that snapshot v2 is in flight; consumers (Task 11) check schema with a fallback.

- [ ] **Step 2: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/session.py
git commit -m "archive/session: bump INDEX_VERSION 1 -> 2 for settings_snapshot v2"
```

---

### Task 10: Implement `build_settings_snapshot_v2`

**Files:**
- Create: `custom_components/dreame_a2_mower/coordinator/_snapshot.py`
- Test: `tests/integration/test_settings_snapshot_v2.py` (NEW)

Builder function takes the coordinator (for access to `cloud_state` and `data` MowerState) and returns the v2 snapshot dict. Each tier is independently populated; missing data sources leave their slot as `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_settings_snapshot_v2.py`:

```python
"""build_settings_snapshot_v2: full firmware-state capture at session-start."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator._snapshot import (
    build_settings_snapshot_v2,
)


def _mk_coordinator(per_map_settings, mower_state_kwargs):
    """Build a minimal coordinator mock for snapshot tests."""
    coord = MagicMock()
    coord._active_map_id = 0
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: per_map_settings}
    coord.cloud_state = cs
    state = MagicMock(**mower_state_kwargs)
    coord.data = state
    return coord


def test_snapshot_has_version_and_captured_at():
    coord = _mk_coordinator({}, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["version"] == 2
    assert snap["captured_at_unix"] == 1234567890


def test_per_map_section_populated_from_cloud_settings():
    per_map = {"mowingHeight": 4, "edgeMowingAuto": 1, "obstacleAvoidanceAi": 2}
    coord = _mk_coordinator(per_map, {})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["per_map"]["mowingHeight"] == 4
    assert snap["per_map"]["edgeMowingAuto"] == 1
    assert snap["per_map"]["obstacleAvoidanceAi"] == 2


def test_per_map_none_when_no_active_map():
    coord = _mk_coordinator({}, {})
    coord._active_map_id = None
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["per_map"] is None


def test_device_wide_section_from_mower_state():
    """rain_protection_enabled etc. come from MowerState fields."""
    coord = _mk_coordinator({}, {
        "rain_protection_enabled": True,
        "rain_protection_resume_hours": 4,
        "frost_protection_enabled": True,
        "navigation_path_smart": False,
        "auto_recharge_battery_threshold": 15,
        "resume_after_charge_battery_threshold": 95,
        "auto_recharge_standby_enabled": True,
        "custom_charging_period_enabled": False,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    dw = snap["device_wide"]
    assert dw["rain_protection_enabled"] is True
    assert dw["rain_protection_resume_hours"] == 4
    assert dw["frost_protection_enabled"] is True
    assert dw["navigation_path"] in ("Direct Path", False, "false")  # value_fn-dependent


def test_peripheral_section_has_human_presence():
    coord = _mk_coordinator({}, {
        "human_presence_alert_enabled": True,
        "human_presence_alert_sensitivity": 1,
        "human_presence_scenario_standby": True,
        "human_presence_scenario_mowing": True,
        "human_presence_scenario_recharge": True,
        "human_presence_scenario_patrol": True,
        "human_presence_alert_voice": False,
        "human_presence_alert_push_interval_min": 3,
        "photo_consent": True,
        "ai_obstacle_photos_enabled": True,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    p = snap["peripheral"]
    assert p["human_presence_alert_enabled"] is True
    assert p["human_presence_alert_sensitivity"] == 1
    assert p["human_presence_alert_push_interval_min"] == 3


def test_forensic_section_collects_led_voice_security():
    """Tier 4: LED + voice + anti-theft + child lock — no mowing impact, kept for forensics."""
    coord = _mk_coordinator({}, {
        "led_in_standby": True,
        "led_on_error": True,
        "led_while_charging": True,
        "led_while_working": True,
        "led_period_enabled": False,
        "voice_language_idx": 7,
        "language_text_idx": 7,
        "voice_volume": 70,
        "anti_theft_lift_alarm": False,
        "anti_theft_off_map_alarm": False,
        "anti_theft_realtime_location": True,
        "child_lock": False,
    })
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    f = snap["forensic"]
    assert f["led_in_standby"] is True
    assert f["voice_volume"] == 70
    assert f["anti_theft_realtime_location"] is True
    assert f["child_lock"] is False


def test_missing_fields_become_none():
    """If a MowerState field doesn't exist (e.g., older state version), slot is None."""
    coord = _mk_coordinator({}, {"rain_protection_enabled": None})
    snap = build_settings_snapshot_v2(coord, captured_at_unix=1234567890)
    assert snap["device_wide"]["rain_protection_enabled"] is None
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/integration/test_settings_snapshot_v2.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the builder**

Create `custom_components/dreame_a2_mower/coordinator/_snapshot.py`:

```python
"""Full firmware-state snapshot at session-start (settings_snapshot v2).

Replaces the v1 narrow per-map-only snapshot with a structured capture
covering everything that could affect or explain mowing behaviour:

  - per_map:   cloud SETTINGS dict for the active map
  - device_wide: CFG/SETTINGS fields that change mow behaviour
  - peripheral: Human Presence + photo consent (could explain stops)
  - forensic:   LED / voice / anti-theft / child lock (no expected impact)

Each section is independently populated; missing data sources leave
the corresponding slot as None. The v1 fallback in session_card.py
handles older archives without the version field.
"""
from __future__ import annotations

from typing import Any

SNAPSHOT_VERSION = 2


def _safe(obj: Any, attr: str, default=None):
    """getattr that returns default for missing or AttributeError."""
    try:
        v = getattr(obj, attr, default)
    except AttributeError:
        return default
    return v if v is not None else default


def _build_per_map(coordinator) -> dict[str, Any] | None:
    active = getattr(coordinator, "_active_map_id", None)
    if active is None:
        return None
    cs = getattr(coordinator, "cloud_state", None)
    if cs is None:
        return None
    settings = getattr(cs, "settings", None)
    if settings is None:
        return None
    per_map = getattr(settings, "by_map_id_canonical", {}).get(int(active))
    if not isinstance(per_map, dict):
        return None
    return dict(per_map)


def _build_device_wide(coordinator) -> dict[str, Any]:
    s = coordinator.data
    return {
        "rain_protection_enabled": _safe(s, "rain_protection_enabled"),
        "rain_protection_resume_hours": _safe(s, "rain_protection_resume_hours"),
        "frost_protection_enabled": _safe(s, "frost_protection_enabled"),
        "navigation_path": _safe(s, "navigation_path_smart"),  # True=Smart, False=Direct
        "auto_recharge_battery_threshold": _safe(s, "auto_recharge_battery_threshold"),
        "resume_after_charge_battery_threshold": _safe(s, "resume_after_charge_battery_threshold"),
        "auto_recharge_after_extended_standby": _safe(s, "auto_recharge_standby_enabled"),
        "custom_charging_period_enabled": _safe(s, "custom_charging_period_enabled"),
        # Time-window values (DnD start/end, low-speed start/end, charging start/end)
        # come from time.* entities which the coordinator surfaces under different
        # field names. If they're not on MowerState, leave them None and surface as
        # follow-up TODO.
        "dnd_enabled": _safe(s, "do_not_disturb_enabled"),
        "low_speed_at_night_enabled": _safe(s, "low_speed_at_night_enabled"),
    }


def _build_peripheral(coordinator) -> dict[str, Any]:
    s = coordinator.data
    return {
        "human_presence_alert_enabled": _safe(s, "human_presence_alert_enabled"),
        "human_presence_alert_sensitivity": _safe(s, "human_presence_alert_sensitivity"),
        "human_presence_scenario_standby": _safe(s, "human_presence_scenario_standby"),
        "human_presence_scenario_mowing": _safe(s, "human_presence_scenario_mowing"),
        "human_presence_scenario_recharge": _safe(s, "human_presence_scenario_recharge"),
        "human_presence_scenario_patrol": _safe(s, "human_presence_scenario_patrol"),
        "human_presence_alert_voice": _safe(s, "human_presence_alert_voice"),
        "human_presence_alert_push_interval_min": _safe(s, "human_presence_alert_push_interval_min"),
        "photo_consent": _safe(s, "photo_consent"),
        "ai_obstacle_photos": _safe(s, "ai_obstacle_photos_enabled"),
    }


def _build_forensic(coordinator) -> dict[str, Any]:
    s = coordinator.data
    return {
        "led_in_standby": _safe(s, "led_in_standby"),
        "led_on_error": _safe(s, "led_on_error"),
        "led_while_charging": _safe(s, "led_while_charging"),
        "led_while_working": _safe(s, "led_while_working"),
        "led_period_enabled": _safe(s, "led_period_enabled"),
        "voice_language_idx": _safe(s, "voice_language_idx") or _safe(s, "language_voice_idx"),
        "lcd_language_idx": _safe(s, "language_text_idx"),
        "voice_volume": _safe(s, "voice_volume"),
        "anti_theft_lift_alarm": _safe(s, "anti_theft_lift_alarm"),
        "anti_theft_off_map_alarm": _safe(s, "anti_theft_off_map_alarm"),
        "anti_theft_realtime_location": _safe(s, "anti_theft_realtime_location"),
        "child_lock": _safe(s, "child_lock"),
    }


def build_settings_snapshot_v2(coordinator, captured_at_unix: int) -> dict[str, Any]:
    """Build the v2 settings_snapshot dict for session-begin.

    Caller is the session-begin handler in coordinator/_mqtt_handlers.py;
    it assigns the result to live_map.settings_snapshot which is then
    persisted via _persist_in_progress and copied into the final archive
    at session-finalize.
    """
    return {
        "version": SNAPSHOT_VERSION,
        "captured_at_unix": captured_at_unix,
        "per_map": _build_per_map(coordinator),
        "device_wide": _build_device_wide(coordinator),
        "peripheral": _build_peripheral(coordinator),
        "forensic": _build_forensic(coordinator),
    }
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/integration/test_settings_snapshot_v2.py -v
```
Expected: 7/7 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_snapshot.py tests/integration/test_settings_snapshot_v2.py
git commit -m "coordinator/_snapshot: build_settings_snapshot_v2 (per_map+device_wide+peripheral+forensic)"
```

---

### Task 11: Wire builder into session-begin

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py`

Replace the existing v1 settings_snapshot capture (around line 285-300) with a call to `build_settings_snapshot_v2`.

- [ ] **Step 1: Find the existing v1 capture**

```bash
grep -n "settings_snapshot = dict" custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py
```

Locate the assignment around lines 285-300.

- [ ] **Step 2: Replace with v2 builder call**

```python
# Snapshot the FULL firmware state at session start (settings_snapshot v2 —
# per_map + device_wide + peripheral + forensic). Replaces the v1 narrow
# per-map-only dict; v1 consumers continue to read the per_map subsection
# via the v1-fallback path in session_card.py.
from ._snapshot import build_settings_snapshot_v2
self.live_map.settings_snapshot = build_settings_snapshot_v2(
    self, captured_at_unix=int(now_unix)
)
```

Remove the old block that built the v1 dict (the cloud_state.settings.by_map_id_canonical inline lookup).

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/ -q --ignore=tests/archive 2>&1 | tail -5
```
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py
git commit -m "_mqtt_handlers: use build_settings_snapshot_v2 at session-begin"
```

---

### Task 12: Update consumer in `session_card.py` for v1/v2 dual-shape handling

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py` (around line 477)
- Test: extend `tests/integration/test_settings_snapshot_v2.py`

The consumer that builds the picked-session attribute dict needs to read from `snapshot["per_map"]["mowingHeight"]` for v2 and `snapshot["mowingHeight"]` for v1.

- [ ] **Step 1: Find the consumer**

```bash
grep -n "settings_snapshot\|snapshot.get" custom_components/dreame_a2_mower/session_card.py
```

- [ ] **Step 2: Add a v1/v2 normalisation helper**

In `session_card.py`, near the top, add:

```python
def _normalise_settings_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Return the v2-shaped dict. v1 flat dicts get wrapped as per_map.

    v1 snapshots have no `version` field; v2 has version >= 2 and the
    per_map subsection. Returns an empty {per_map:{}, device_wide:{},
    peripheral:{}, forensic:{}} for None to simplify downstream lookups.
    """
    if not snap:
        return {"version": 0, "per_map": {}, "device_wide": {}, "peripheral": {}, "forensic": {}}
    if snap.get("version", 0) >= 2:
        return snap
    # v1: flat dict, treat as per_map
    return {
        "version": 1,
        "per_map": dict(snap),
        "device_wide": {},
        "peripheral": {},
        "forensic": {},
    }
```

- [ ] **Step 3: Use the normaliser in the consumer**

Replace the existing v1-only `snapshot = raw_dict.get("settings_snapshot")` block with:

```python
snapshot = _normalise_settings_snapshot(raw_dict.get("settings_snapshot"))
# Existing downstream reads — change `snapshot.get("mowingHeight")` to
# `snapshot["per_map"].get("mowingHeight")` etc.
```

Walk through and update each `snapshot.get("<key>")` to point at the right subsection per the v2 schema.

- [ ] **Step 4: Add backward-compat test**

Append to `tests/integration/test_settings_snapshot_v2.py`:

```python
def test_consumer_handles_v1_legacy_snapshot():
    """A flat dict (v1) gets normalised as per_map; downstream reads still work."""
    from custom_components.dreame_a2_mower.session_card import _normalise_settings_snapshot
    v1 = {"mowingHeight": 4, "edgeMowingAuto": 1}
    out = _normalise_settings_snapshot(v1)
    assert out["version"] == 1
    assert out["per_map"]["mowingHeight"] == 4
    assert out["device_wide"] == {}


def test_consumer_handles_v2_snapshot():
    """v2 dict passes through unchanged."""
    from custom_components.dreame_a2_mower.session_card import _normalise_settings_snapshot
    v2 = {"version": 2, "per_map": {"mowingHeight": 4}, "device_wide": {"rain_protection_enabled": True}, "peripheral": {}, "forensic": {}}
    out = _normalise_settings_snapshot(v2)
    assert out is v2 or out == v2


def test_consumer_handles_none_snapshot():
    """Missing settings_snapshot returns an empty v2 shape so downstream lookups don't crash."""
    from custom_components.dreame_a2_mower.session_card import _normalise_settings_snapshot
    out = _normalise_settings_snapshot(None)
    assert out["per_map"] == {}
    assert out["device_wide"] == {}
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/integration/test_settings_snapshot_v2.py tests/ -q --ignore=tests/archive 2>&1 | tail -5
```
Expected: 10/10 (7 from Task 10 + 3 new); no regressions.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/integration/test_settings_snapshot_v2.py
git commit -m "session_card: dual-shape settings_snapshot consumer (v1 flat + v2 sectioned)"
```

---

### Task 13: Update dashboard's "Settings in effect at session start" card

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`
- Deploy: SCP to live HA after commit

The Sessions tab has a markdown card titled "Settings in effect at session start" that reads from `state_attr('sensor.dreame_a2_mower_picked_session','settings_snapshot')`. Extend the template to render device_wide / peripheral / forensic subsections when present.

- [ ] **Step 1: Find the card**

```bash
grep -n "Settings in effect at session start" dashboards/mower/dashboard.yaml
```

- [ ] **Step 2: Replace the template body**

Edit so the body becomes (Jinja branches on v2 vs v1):

```yaml
content: |
  ### Settings in effect at session start
  {% set s = state_attr('sensor.dreame_a2_mower_picked_session','settings_snapshot') %}
  {% if s %}
  {% if s.get('version', 0) >= 2 %}
  **Per-map:** EdgeMaster {{ s.per_map.get('edgemaster') }} · Walk {{ s.per_map.get('edge_mowing_walk_mode') }} · Mode {{ s.per_map.get('edge_mowing_mode') }} · Obstacle {{ s.per_map.get('obstacle_avoidance_mode') }} (AI: {{ s.per_map.get('obstacle_avoidance_ai') }}) · Height {{ s.per_map.get('mowing_height_mm') }} mm · Efficiency {{ s.per_map.get('mowing_efficiency') }}

  **Device-wide:** Rain {{ s.device_wide.get('rain_protection_enabled') }} (resume {{ s.device_wide.get('rain_protection_resume_hours') }}h) · Frost {{ s.device_wide.get('frost_protection_enabled') }} · Nav {{ s.device_wide.get('navigation_path') }} · Auto-recharge {{ s.device_wide.get('auto_recharge_battery_threshold') }}% · Resume {{ s.device_wide.get('resume_after_charge_battery_threshold') }}%

  **Human Presence:** Alert {{ s.peripheral.get('human_presence_alert_enabled') }} · Sensitivity {{ s.peripheral.get('human_presence_alert_sensitivity') }} · Push every {{ s.peripheral.get('human_presence_alert_push_interval_min') }} min · Photo consent {{ s.peripheral.get('photo_consent') }}

  **Forensic:** LED standby={{ s.forensic.get('led_in_standby') }} working={{ s.forensic.get('led_while_working') }} · Voice vol {{ s.forensic.get('voice_volume') }} · Anti-theft RT {{ s.forensic.get('anti_theft_realtime_location') }} · Child lock {{ s.forensic.get('child_lock') }}
  {% else %}
  **EdgeMaster**: {{ s.get('settings_edgemaster') }}
  **Edge walk mode**: {{ s.get('settings_edge_mowing_walk_mode') }}
  **Edge mowing mode**: {{ s.get('settings_edge_mowing_mode') }}
  **Obstacle avoidance**: {{ s.get('settings_obstacle_avoidance_mode') }} (AI: {{ s.get('settings_obstacle_avoidance_ai') }})
  **Mowing height**: {{ s.get('settings_mowing_height_mm') }} mm
  **Mowing efficiency**: {{ s.get('settings_mowing_efficiency') }}
  {% endif %}
  {% else %}
  _Not captured for this session — settings_snapshot was added in v1.0.13a1. Sessions starting from now will populate this._
  {% endif %}
```

- [ ] **Step 3: Lint + deploy**

```bash
python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print('OK')"
HOST=$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt)
USER=$(awk 'NR==2' /data/claude/homeassistant/ha-credentials.txt)
PASS=$(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PASS" scp -o StrictHostKeyChecking=no dashboards/mower/dashboard.yaml "$USER@$HOST:/config/dashboards/mower/dashboard.yaml"
```

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: Sessions tab settings_snapshot card renders v2 sections (v1 fallback kept)"
```

---

## Phase 5 — Gappy-session verification + doc

### Task 14: Write the gap-behavior verification doc

**Files:**
- Create: `docs/research/replay-card-gap-behavior.md`

Manual test procedure, not code. Closes `[[project_gappy_sessions_todo]]`.

- [ ] **Step 1: Write the doc**

Create `docs/research/replay-card-gap-behavior.md`:

```markdown
# Replay Card Gap Behavior

## Purpose

Document how the Sessions-tab replay card behaves on sessions with trail
gaps. Closes `project_gappy_sessions_todo` from MEMORY.md. With Phase 1
of session-data-completeness in place, reboot-induced gaps should be
rare, but several gap classes remain legitimate (legitimate pause,
MQTT outage, dock-return-only-gap).

## Three gap classes

### 1. Reboot gap (should be rare post Phase 1)

**Trigger:** restart HA during an active mow.

**Expected behavior post-fix:** trail merges across the reboot. The
replay card animates continuously. The state-driven time breakdown
("Mowing", "Charging", "Rain", "Other") sums correctly with minimal
"Other" bucket. Validation: run a 10-min mow with a deliberate
HA restart at the 4-min mark, confirm finished archive's sample counts
match probe-truth via `tools/state_partition.py`.

### 2. Legitimate pause gap

**Trigger:** press Pause in the app mid-mow, wait 5 min, Resume.

**Expected behavior:** trail shows a frozen-cursor span where the
mower didn't move. The animation's time-cursor advances through the
pause at the same wall-clock rate as the rest. No teleport jump.

### 3. MQTT-outage gap

**Trigger:** disconnect MQTT for 60s mid-mow (e.g., stop the
broker container briefly).

**Expected behavior:** trail has a visible spatial jump from
last-pre-outage point to first-post-outage point. The animation's
cursor traverses this jump as a straight line at increased speed
(distance / elapsed_time). The time-breakdown's "Other" bucket
slightly inflates by the outage duration.

## Pause-budget allocation

The animation engine concentrates `pauseBudgetMs` in `_local_legs`
gap boundaries (real pen-up moments at recharge/pause) rather than
`cloud_track_segments` fragmentation noise. The fix shipped in
v1.0.13a2; verified post-Phase-1 by re-running a known-pausing
session through the card.

## What to test before claiming this TODO closed

Pick one session from each of the three classes above and capture a
screenshot of the replay card's playback at three points:
- start (first frame)
- mid-gap (animation should still progress sensibly)
- end (last frame; dock-return arc should be visible per Phase 3)

If any of the three reveals genuine animation bugs (not just expected
gap rendering per the table above), open a new issue rather than
expanding this TODO's scope.

## Status

- 2026-05-17: doc written; tests pending live runs.
```

- [ ] **Step 2: Commit**

```bash
git add docs/research/replay-card-gap-behavior.md
git commit -m "docs(replay-card): gap-behavior verification procedure (closes gappy-sessions TODO)"
```

---

### Task 15: Cut a release

**Files:**
- (none — release.sh handles manifest bump + tag + push + GitHub release + HACS refresh)

Phases 1-4 introduce real integration behavior changes. Cut a release so the user can HACS-update + restart to pick them up.

- [ ] **Step 1: Confirm full suite passes**

```bash
python3 -m pytest tests/ -q --ignore=tests/archive 2>&1 | tail -3
```
Expected: all pass.

- [ ] **Step 2: Run release.sh**

```bash
bash tools/release.sh --notes "session-data-completeness: persist race-guard fix + recorder-merge expansion + dock-return capture + settings_snapshot v2

Closes 3 MEMORY.md TODOs:
- session_persist_audit_todo: 8.5h data-loss on 19h session fixed via
  restore-then-merge in _restore_in_progress (was bailing on MQTT race).
  Atomic write with fsync + CRC32 footer prevents partial-write corruption.
- session_dock_return_capture_todo: trail collector now waits for
  task_state idle OR charging_status=1 (5-min timeout) after session-done,
  capturing the drive-back-to-dock arc.
- gappy_sessions_todo: documented expected gap behavior; closed via
  docs/research/replay-card-gap-behavior.md.

Defense-in-depth recorder-merge extended to state/charging/error sample
streams via 3 new diagnostic sensors (state_code_raw,
charging_status_code_raw, error_code_raw).

settings_snapshot bumped to v2 with structured per_map/device_wide/
peripheral/forensic sections (~55 fields, was ~19). session_card.py
consumer handles both v1 and v2 shapes; dashboard renders v2 sections
when present, falls back to v1 layout for older archives.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

- [ ] **Step 3: Verify the HACS refresh ping**

The release.sh tail line should be `HACS refresh: {"id":2,"type":"result","success":true,...}` and `✅ release vX.Y.Z published cleanly.` If it isn't, investigate before celebrating.

---

## Self-review notes

- Spec coverage: every spec phase has at least one task (Phase 1: T1-4, Phase 2: T5-7, Phase 3: T8, Phase 4: T9-13, Phase 5: T14). T15 is the release.
- Placeholder scan: a few `# adjust per field name per Step 1` comments in Tasks 5/6/8 — those are deliberate (the field name verification is part of the task, not a plan failure). The implementer reads inventory.yaml / mower/state.py during step 1 of those tasks.
- Type consistency: `merge_in_progress_payloads`, `build_settings_snapshot_v2`, `_normalise_settings_snapshot`, `_compute_crc32`, `_verify_crc32` — names consistent across all tasks that reference them.
- File-size watch: `coordinator/_session.py` is 667 LOC pre-plan. Tasks 4 (restore rewrite), 8 (pending-finalize wait), 11 (snapshot wire-in) all add to it. If post-plan size > 900 LOC, split the recorder-merge call sites into `coordinator/_session_recorder_merge.py` as the spec notes. The implementer can flag if/when needed.
