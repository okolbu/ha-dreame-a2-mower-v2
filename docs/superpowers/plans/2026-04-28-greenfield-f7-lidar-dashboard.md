# F7 LiDAR + Dashboard Polish + Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the LiDAR archive + WebGL Lovelace card from legacy, surface a `s99p20`-driven point cloud as a top-down camera entity pair, ship the dashboard YAML organized per the app's screens, and tag v1.0.0a0 — the cutover candidate.

**Architecture:** Three independent slices. (1) `archive/lidar.py` lifted from legacy + wired into a new `_handle_lidar_object_name` MQTT branch in the coordinator. (2) Two camera entities pointing at the existing `protocol/pcd_render.py` (top-down PNG at 512² thumbnail and original-res popout) plus a HTTP view that streams the latest archived `.pcd` file to the WebGL card. (3) `dashboards/mower/dashboard.yaml` redesigned per spec §9, plus a `show_lidar_fullscreen` service.

**Tech Stack:** Python 3.11+, Home Assistant `Camera` + `HomeAssistantView` + `StaticPathConfig`, `numpy` + `Pillow` (already required by F2 base map render), pure WebGL 1.0 (no third-party JS deps).

---

## Context for the implementer

### Where this fits

F1–F6 already shipped (latest tag `v0.6.0a1`). The integration today decodes the full MQTT surface, runs the session lifecycle end-to-end with archives, persists in-progress state across reboots, surfaces ~31 sensors plus diagnostics, and ships `download_diagnostics`. F7 makes the LiDAR feature work and rebuilds the showcase dashboard. After F7 the project is ready for live cutover from the legacy integration.

### What's already in the repo (F7 baseline)

- `protocol/pcd.py` — PCD v0.7 binary parser (`parse_pcd(bytes) -> PointCloud`). 147 LOC, fully tested.
- `protocol/pcd_render.py` — top-down PNG renderer (`render_top_down(cloud, width, height, tilt_deg=0.0)`). 128 LOC, fully tested.
- `custom_components/dreame_a2_mower/archive/session.py` — F5 session archive. The lidar archive will mirror its shape (atomic writes, `index.json`, retention policy).
- `custom_components/dreame_a2_mower/coordinator.py` — already has `_handle_event_occured` for session-summary OSS fetch (similar pattern for LiDAR fetch).
- `custom_components/dreame_a2_mower/cloud_client.py` — `get_interim_file_url(object_name) -> str` and `get_file(url) -> bytes` (F5.6.1 already uses these).
- `custom_components/dreame_a2_mower/camera.py` — `DreameA2MapCamera` (the F2 base map entity, 53 LOC) — pattern to copy for the new LiDAR entities.
- `custom_components/dreame_a2_mower/__init__.py` — already does `async_setup_entry`. F7 adds a static-path registration here.
- `custom_components/dreame_a2_mower/const.py` — already has `DOMAIN`, `PLATFORMS`. F7 adds three CONF_* options and an attribute icon.
- `custom_components/dreame_a2_mower/config_flow.py` — F7 extends the options flow with the three new LiDAR retention options.
- `custom_components/dreame_a2_mower/services.py` + `services.yaml` — already has 10 services. F7 adds `show_lidar_fullscreen`.

### What's in legacy that gets lifted (lift-on-demand)

- `lidar_archive.py` (213 LOC) at `/data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/lidar_archive.py` — content-addressed PCD archive with retention. Lift verbatim into `archive/lidar.py`; only changes are: drop the `_LOGGER` module import in favor of relative `..const.LOGGER`, follow the new layering (`archive/` is layer-2: NO `homeassistant.*` imports — the legacy file is already clean).
- `www/dreame-a2-lidar-card.js` (770 LOC) at `/data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js` — pure-WebGL 1.0 viewer with orbit camera + map underlay. Lift verbatim into `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`. No code changes — its API contract (`/api/dreame_a2_mower/lidar/latest.pcd`, `camera.dreame_a2_mower_map`) is honored by F7.
- `s99p20` dispatch logic (`device.py:_handle_lidar_object_name`, `_fetch_lidar_scan`) — lift the *behavior*, not the file. Greenfield equivalent goes in `coordinator.py` next to `_handle_event_occured`.
- `LidarPcdDownloadView` (legacy `camera.py:1498-1534`) — lift the HTTP view into greenfield `camera.py` or a new `http_views.py` (see Task F7.6.1 — choose `camera.py` to keep the entity-adjacent pattern).

### Layering invariant (DO NOT VIOLATE)

| Path | HA imports allowed? |
|---|---|
| `protocol/` | NO |
| `custom_components/dreame_a2_mower/mower/` | NO |
| `custom_components/dreame_a2_mower/observability/` | NO |
| `custom_components/dreame_a2_mower/archive/` | NO ← `archive/lidar.py` MUST stay HA-import-free |
| `custom_components/dreame_a2_mower/live_map/` | NO |
| Top-level `custom_components/dreame_a2_mower/*.py` | YES |

### MQTT trigger context

The mower announces a new LiDAR scan via MQTT property push: `properties_changed`, `siid=99 piid=20 value=<object_name_str>`. Today greenfield's coordinator.handle_property_push runs the property through `apply_property_to_state`, which doesn't recognize (99, 20) — so it's currently logged once via the F6 `[NOVEL/property]` warning and dropped. F7 adds the slot to `mower/property_mapping.py` and routes it to a new `_handle_lidar_object_name(object_name)` handler.

### Spec sections this plan satisfies

- §5.7: LiDAR popout entity pair (`camera.dreame_a2_mower_lidar_top_down` 512×512 thumbnail + `camera.dreame_a2_mower_lidar_top_down_full` original-res). 3D interactive view via WebGL Lovelace card. Service `dreame_a2_mower.show_lidar_fullscreen`.
- §5.8: LiDAR archive retention (default 20 entries / 200 MB, options-flow-configurable: count 1..50, MB 50..2000).
- §5.9: PCD download URL is auth-required (`requires_auth = True`).
- §6 acceptance:
  - "LiDAR archive: every `s99.20` OSS key triggers fetch + dedup + write to `<config>/dreame_a2_mower/lidar/`."
  - "LiDAR size cap enforced: when `CONF_LIDAR_ARCHIVE_MAX_MB` is exceeded, oldest scans evicted until under cap."
  - "All archive disk I/O is async."
- §9: Showcase `dashboards/mower/dashboard.yaml` redesigned with the seven views (Mower, Mowing settings, More settings, Schedule, LiDAR, Sessions, Diagnostics).
- §7: F7 estimate is 1 wk; this plan has 14 tasks across 8 phases.

### File structure delivered by F7

```
custom_components/dreame_a2_mower/
├── archive/
│   └── lidar.py                    # NEW — lifted from legacy
├── camera.py                       # MODIFIED — adds 2 entities + 1 HTTP view
├── coordinator.py                  # MODIFIED — _handle_lidar_object_name, retention enforcement, archive index load
├── config_flow.py                  # MODIFIED — 3 new options
├── const.py                        # MODIFIED — 3 new CONF_LIDAR_* keys
├── mower/
│   └── property_mapping.py         # MODIFIED — adds (99, 20) entry
├── services.py                     # MODIFIED — show_lidar_fullscreen
├── services.yaml                   # MODIFIED — show_lidar_fullscreen
├── www/                            # NEW directory
│   └── dreame-a2-lidar-card.js     # lifted verbatim from legacy
├── translations/en.json            # MODIFIED — entity names
├── __init__.py                     # MODIFIED — register www/ static paths

dashboards/
└── mower/
    └── dashboard.yaml              # NEW — 7-view showcase

docs/
├── lidar.md                        # NEW — user setup guide
└── cutover.md                      # NEW — runbook for swap-out

tests/
├── archive/
│   └── test_lidar.py               # NEW
├── integration/
│   ├── test_lidar_camera.py        # NEW
│   └── test_lidar_view.py          # NEW
└── mower/
    └── test_property_mapping.py    # MODIFIED if it tests (99, 20)
```

### Where parity-checklist items map to tasks

| Acceptance item | Task |
|---|---|
| `archive/lidar.py` exists, lifted verbatim, layer-2 | F7.1.1 |
| LiDAR size cap enforced | F7.1.2 |
| `s99.20` triggers fetch + dedup + archive write | F7.2.1, F7.2.2 |
| `camera.lidar_top_down` 512² thumbnail + `_full` original | F7.3.1, F7.3.2 |
| `/api/dreame_a2_mower/lidar/latest.pcd` HTTP endpoint | F7.4.1 |
| WebGL Lovelace card served at `/dreame_a2_mower/dreame-a2-lidar-card.js` | F7.5.1 |
| `dreame_a2_mower.show_lidar_fullscreen` service | F7.6.1 |
| Options flow: count 1..50, MB 50..2000 | F7.7.1 |
| `dashboards/mower/dashboard.yaml` 7-view showcase | F7.8.1 |
| `docs/lidar.md` + `docs/cutover.md` | F7.9.1, F7.9.2 |
| Final sweep + tag `v1.0.0a0` | F7.10.1 |

---

## Phase F7.1 — `archive/lidar.py` lift

### Task F7.1.1: Lift `lidar_archive.py` verbatim into `archive/lidar.py`

**Files:**
- Copy: legacy `/data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/lidar_archive.py` → `custom_components/dreame_a2_mower/archive/lidar.py`
- Modify: `custom_components/dreame_a2_mower/archive/__init__.py` — re-export
- Test: `tests/archive/test_lidar.py`

- [ ] **Step 1: Copy the legacy file**

```bash
cp /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/lidar_archive.py \
   /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/archive/lidar.py
```

- [ ] **Step 2: Verify it's HA-import-free already**

Run: `grep -n "homeassistant" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/archive/lidar.py`
Expected: empty output. The legacy file is already clean (uses `logging.getLogger(__name__)` directly).

- [ ] **Step 3: Re-export from the archive package**

Read the existing `custom_components/dreame_a2_mower/archive/__init__.py`. Append:

```python
from .lidar import ArchivedLidarScan, LidarArchive

__all__ = [...existing..., "ArchivedLidarScan", "LidarArchive"]
```

(Replace `[...existing...]` with the actual current `__all__` contents — read the file first.)

- [ ] **Step 4: Write basic round-trip tests**

Create `tests/archive/test_lidar.py`:

```python
"""Tests for archive/lidar.py — lifted from legacy."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.archive.lidar import (
    ArchivedLidarScan,
    LidarArchive,
)


def test_archive_starts_empty(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    assert arch.count == 0
    assert arch.latest() is None
    assert arch.list_scans() == []


def test_archive_persists_scan(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    pcd_bytes = b"# .PCD v0.7 - Point Cloud Data file format\nDUMMY"
    entry = arch.archive("dreame/lidar/abc.pcd", unix_ts=1700000000, data=pcd_bytes)
    assert entry is not None
    assert entry.size_bytes == len(pcd_bytes)
    assert entry.object_name == "dreame/lidar/abc.pcd"
    assert (tmp_path / entry.filename).read_bytes() == pcd_bytes
    assert arch.count == 1


def test_archive_dedupes_by_md5(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    same = b"identical-bytes"
    first = arch.archive("a.pcd", 1700000000, same)
    second = arch.archive("b.pcd", 1700000005, same)
    assert first is not None
    assert second is None  # md5 collision skips the write
    assert arch.count == 1


def test_archive_index_round_trip(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    arch.archive("a.pcd", 1700000000, b"AAA")
    arch.archive("b.pcd", 1700000010, b"BBB")
    # New instance — should rehydrate from index.json
    arch2 = LidarArchive(tmp_path)
    assert arch2.count == 2
    latest = arch2.latest()
    assert latest is not None
    assert latest.unix_ts == 1700000010


def test_archive_empty_payload_returns_none(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    assert arch.archive("anywhere", 1700000000, b"") is None
    assert arch.count == 0


def test_archive_corrupt_index_starts_fresh(tmp_path: Path) -> None:
    """Mirrors SessionArchive: a malformed index.json doesn't crash setup."""
    (tmp_path / "index.json").write_text("not json {{{")
    arch = LidarArchive(tmp_path)
    assert arch.count == 0
```

- [ ] **Step 5: Run the new tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/archive/test_lidar.py -v`
Expected: 6 tests pass.

- [ ] **Step 6: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 570 passed / 4 skipped (564 + 6).

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/archive/lidar.py custom_components/dreame_a2_mower/archive/__init__.py tests/archive/test_lidar.py && git commit -m "F7.1.1: lift LidarArchive from legacy"
```

### Task F7.1.2: Add MB-cap retention to `LidarArchive`

The legacy archive only enforces a count cap; spec §5.8 requires both count AND total-size cap (default 200 MB). PCDs run 2-3 MB each, so a count of 50 could legitimately blow past 200 MB.

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/lidar.py`
- Test: `tests/archive/test_lidar.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/archive/test_lidar.py`:

```python
def test_archive_enforces_size_cap(tmp_path: Path) -> None:
    """When max_mb is set and the cumulative size exceeds it, oldest
    scans are evicted until under cap."""
    arch = LidarArchive(tmp_path, retention=0, max_bytes=10)
    arch.archive("oldest.pcd", 1700000000, b"AAAAA")  # 5 bytes, total=5
    arch.archive("middle.pcd", 1700000010, b"BBBBB")  # 5 bytes, total=10 (at cap)
    arch.archive("newest.pcd", 1700000020, b"CCCCC")  # 5 bytes — evict oldest
    scans = arch.list_scans()
    assert len(scans) == 2
    files = sorted(s.filename for s in scans)
    # oldest.pcd is gone; middle and newest remain
    assert "oldest" not in " ".join(files)
    # File on disk also gone
    for s in scans:
        assert (tmp_path / s.filename).is_file()
    # The evicted PCD's file is removed too
    assert sum(p.stat().st_size for p in tmp_path.glob("*.pcd")) <= 10


def test_archive_size_cap_zero_means_unlimited(tmp_path: Path) -> None:
    """max_bytes=0 disables the size cap (matches retention=0 semantics)."""
    arch = LidarArchive(tmp_path, retention=0, max_bytes=0)
    for i in range(5):
        arch.archive(f"scan{i}.pcd", 1700000000 + i, b"X" * 100)
    assert arch.count == 5


def test_archive_count_cap_and_size_cap_both_enforced(tmp_path: Path) -> None:
    """Both caps are independent; whichever bites first prunes."""
    arch = LidarArchive(tmp_path, retention=3, max_bytes=10000)
    for i in range(5):
        arch.archive(f"scan{i}.pcd", 1700000000 + i, b"X" * 100)
    assert arch.count == 3
    # And the OLDEST two are gone
    kept = {s.filename for s in arch.list_scans()}
    for i in (0, 1):
        assert f"scan{i}.pcd" not in kept
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/archive/test_lidar.py -k "size_cap or count_cap_and_size" -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'max_bytes'`.

- [ ] **Step 3: Add the size cap to `LidarArchive`**

Read the current `archive/lidar.py`. Modify `__init__` signature:

```python
def __init__(self, root: Path, retention: int = 0, max_bytes: int = 0) -> None:
    """`retention` = max number of PCDs to keep on disk. 0 means unlimited.
    `max_bytes` = total cumulative size cap in bytes. 0 means unlimited.
    Both caps run independently after every archive write — whichever
    triggers first prunes oldest-first.
    """
    self._root = Path(root)
    self._root.mkdir(parents=True, exist_ok=True)
    self._index: list[ArchivedLidarScan] = []
    self._retention = int(retention) if retention else 0
    self._max_bytes = int(max_bytes) if max_bytes else 0
    self._index_loaded: bool = False
```

Add a new private method right after `_enforce_retention`:

```python
def _enforce_size_cap(self) -> None:
    """Prune oldest PCDs until total on-disk size is at or below the cap.
    No-op when cap is 0 (unlimited) or already under cap."""
    cap = getattr(self, "_max_bytes", 0)
    if not cap or cap <= 0:
        return
    sorted_idx = sorted(self._index, key=lambda s: s.unix_ts)
    total = sum(s.size_bytes for s in sorted_idx)
    if total <= cap:
        return
    pruned = 0
    while sorted_idx and total > cap:
        scan = sorted_idx.pop(0)
        try:
            (self._root / scan.filename).unlink(missing_ok=True)
        except OSError as ex:
            _LOGGER.warning(
                "LidarArchive: failed to prune %s: %s", scan.filename, ex,
            )
        total -= scan.size_bytes
        pruned += 1
    kept_files = {s.filename for s in sorted_idx}
    self._index = [s for s in self._index if s.filename in kept_files]
    if pruned:
        self._save_index()
        _LOGGER.info(
            "LidarArchive: pruned %d scan(s) to honor max_bytes=%d (now %d B)",
            pruned, cap, total,
        )
```

In `archive(...)`, after the existing `_enforce_retention()` call, add:

```python
self._enforce_size_cap()
```

Add a setter to mirror `set_retention`:

```python
def set_max_bytes(self, max_bytes: int) -> None:
    self._max_bytes = int(max_bytes) if max_bytes else 0
    self._enforce_size_cap()
```

- [ ] **Step 4: Run all archive/lidar tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/archive/test_lidar.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 573 passed / 4 skipped (570 + 3).

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/archive/lidar.py tests/archive/test_lidar.py && git commit -m "F7.1.2: LidarArchive size-cap retention"
```

---

## Phase F7.2 — `s99p20` MQTT trigger + fetch

### Task F7.2.1: Map (99, 20) in property_mapping; coordinator stores object_name

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/property_mapping.py`
- Modify: `custom_components/dreame_a2_mower/mower/state.py` (add field)
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (`apply_property_to_state` knows the new field)
- Test: `tests/mower/test_property_mapping.py` (or wherever the existing PROPERTY_MAPPING tests live — find via grep)

- [ ] **Step 1: Add the MowerState field**

Read `custom_components/dreame_a2_mower/mower/state.py`. After the existing F6 section, append:

```python
# ------ F7 fields ------

# Source: s99.20 (confirmed). Persistence: volatile.
# Last LiDAR-scan OSS object key announced by the mower. The
# coordinator's _handle_lidar_object_name uses this to schedule a
# fetch + archive write. Cleared on successful archive insertion.
latest_lidar_object_name: str | None = None
```

- [ ] **Step 2: Add the property mapping entry**

Read `custom_components/dreame_a2_mower/mower/property_mapping.py`. Find the `PROPERTY_MAPPING` dict. Append:

```python
(99, 20): PropertyMappingEntry(field_name="latest_lidar_object_name"),
```

(If the existing entries cite a §-section in a comment, match the style — cite §5.7 / §6 LiDAR archive item.)

- [ ] **Step 3: Write the failing tests**

Find the existing property-mapping tests with `grep -rn "PROPERTY_MAPPING" tests/`. Add a test for the new entry — example pattern; adapt to the existing test file's conventions:

```python
def test_property_mapping_includes_lidar_object_name():
    from custom_components.dreame_a2_mower.mower.property_mapping import PROPERTY_MAPPING
    entry = PROPERTY_MAPPING[(99, 20)]
    assert entry.field_name == "latest_lidar_object_name"


def test_apply_property_lidar_object_name_updates_state():
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.mower.state import MowerState

    state = MowerState()
    new = apply_property_to_state(state, 99, 20, "dreame/lidar/abcdef.pcd")
    assert new.latest_lidar_object_name == "dreame/lidar/abcdef.pcd"
```

If the test file already imports `apply_property_to_state`, no new imports are needed.

- [ ] **Step 4: Run tests to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -k "lidar_object_name" -v`
Expected: FAIL — field doesn't exist or mapping missing.

- [ ] **Step 5: Verify state-derivation chain**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 575 passed / 4 skipped (573 + 2).

If the generic field-application fallback in `apply_property_to_state` (added in F5.3.1) handles it automatically, no further coordinator changes needed. If not, follow the F5.3.1 pattern. Read coordinator.py around the `apply_property_to_state` function (search for the func def).

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/mower/state.py custom_components/dreame_a2_mower/mower/property_mapping.py tests/ && git commit -m "F7.2.1: map (99, 20) → latest_lidar_object_name"
```

### Task F7.2.2: Coordinator `_handle_lidar_object_name` fetch + archive write

When `latest_lidar_object_name` flips to a new key, schedule an OSS fetch + archive write via the executor pool.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`
- Test: `tests/integration/test_coordinator.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_coordinator.py` (use the established `_make_coordinator_for_finalize_tests` pattern):

```python
# ---------------------------------------------------------------------------
# F7.2.2: LiDAR scan fetch on s99p20
# ---------------------------------------------------------------------------


def test_lidar_object_name_change_triggers_fetch_and_archive(monkeypatch):
    """A new latest_lidar_object_name causes _handle_lidar_object_name to
    fetch the OSS blob, dedupe by md5, and write to the archive."""
    import asyncio
    from pathlib import Path

    coord = _make_coordinator_for_finalize_tests()
    # The coordinator helper bypasses __init__ — wire the lidar_archive
    # the way F7.2.2 expects.
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
    coord.lidar_archive = LidarArchive(Path(coord.hass.config.path("dreame_a2_mower", "lidar")))

    # Stub the cloud's get_interim_file_url + get_file
    fake_pcd = b"# .PCD v0.7\nDUMMY"
    async def _fake_url(_a, _b=None):
        return "https://example/abc.pcd"
    async def _fake_get(_url):
        return fake_pcd

    coord._cloud.get_interim_file_url = _fake_url
    coord._cloud.get_file = _fake_get

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    coord.hass.async_add_executor_job = _fake_executor

    asyncio.get_event_loop().run_until_complete(
        coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000000)
    )

    # Same call again — md5 dedupe, no second archive insertion
    asyncio.get_event_loop().run_until_complete(
        coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000005)
    )

    assert coord.lidar_archive.count == 1
    latest = coord.lidar_archive.latest()
    assert latest is not None
    assert latest.object_name == "dreame/lidar/abc.pcd"


def test_lidar_object_name_unchanged_skips_fetch(monkeypatch):
    """If _handle_lidar_object_name receives the same object_name as last
    time, no cloud fetch is attempted."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    coord._last_lidar_object_name = "dreame/lidar/already.pcd"

    fetch_count = 0
    async def _fake_url(_a, _b=None):
        nonlocal fetch_count
        fetch_count += 1
        return "https://example/already.pcd"
    coord._cloud.get_interim_file_url = _fake_url

    asyncio.get_event_loop().run_until_complete(
        coord._handle_lidar_object_name("dreame/lidar/already.pcd", now_unix=1700000000)
    )
    assert fetch_count == 0
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_coordinator.py -k "lidar_object_name_change or lidar_object_name_unchanged" -v`
Expected: AttributeError on `_handle_lidar_object_name`.

- [ ] **Step 3: Wire the handler**

Read `coordinator.py`. Find the `_make_coordinator_for_finalize_tests` helper signature requirements (it's in the test file; don't modify). The handler lives next to `_handle_event_occured`.

In `coordinator.py` `__init__`, after `self.session_archive = SessionArchive(...)`:

```python
# F7.2.2: LiDAR archive — persists PCD scans announced via s99p20.
# Layout: <config>/dreame_a2_mower/lidar/  (matches legacy).
lidar_dir = hass.config.path(DOMAIN, "lidar")
self.lidar_archive = LidarArchive(
    Path(lidar_dir),
    retention=int(entry.options.get(CONF_LIDAR_ARCHIVE_KEEP, 20)),
    max_bytes=int(entry.options.get(CONF_LIDAR_ARCHIVE_MAX_MB, 200)) * 1024 * 1024,
)
self._last_lidar_object_name: str | None = None
```

Imports (add near the existing archive import):

```python
from .archive.lidar import LidarArchive
from .const import CONF_LIDAR_ARCHIVE_KEEP, CONF_LIDAR_ARCHIVE_MAX_MB
```

(Both CONF constants are added in F7.7.1; if they don't exist yet, define them as `int` defaults inline here so this task can land before F7.7.1. Use `getattr` with fallback to be safe: `int(getattr(entry, "options", {}).get("lidar_archive_keep", 20))`.)

Add the load_index call alongside the session_archive load (search for `self.session_archive.load_index` — same place, parallel call):

```python
await self.hass.async_add_executor_job(self.lidar_archive.load_index)
```

Add the new handler method (place it adjacent to `_handle_event_occured`):

```python
async def _handle_lidar_object_name(
    self, object_name: str, now_unix: int
) -> None:
    """Fetch the announced PCD blob and archive it.

    Called from `_on_state_update` whenever
    `latest_lidar_object_name` flips to a new key. Idempotent on the
    same key (we cache the last-handled object_name to avoid re-fetching
    while the property re-asserts).

    Failures are logged at WARNING and swallowed — observability never
    breaks telemetry.
    """
    if not object_name or object_name == self._last_lidar_object_name:
        return
    self._last_lidar_object_name = object_name
    LOGGER.info("[LIDAR] s99p20 announced object_name=%r", object_name)
    cloud = getattr(self, "_cloud", None)
    if cloud is None:
        LOGGER.warning("[LIDAR] fetch skipped (no cloud client): %s", object_name)
        return
    try:
        url = await self.hass.async_add_executor_job(
            cloud.get_interim_file_url, object_name
        )
    except Exception as ex:
        LOGGER.warning("[LIDAR] get_interim_file_url failed for %s: %s", object_name, ex)
        return
    if not url:
        LOGGER.warning("[LIDAR] get_interim_file_url returned None for %s", object_name)
        return
    try:
        raw = await self.hass.async_add_executor_job(cloud.get_file, url)
    except Exception as ex:
        LOGGER.warning("[LIDAR] get_file failed for %s: %s", object_name, ex)
        return
    if not raw:
        LOGGER.warning("[LIDAR] get_file returned empty for %s", object_name)
        return
    entry = await self.hass.async_add_executor_job(
        self.lidar_archive.archive, object_name, now_unix, raw
    )
    if entry is None:
        LOGGER.debug("[LIDAR] dedup hit (md5 already archived): %s", object_name)
        return
    LOGGER.info(
        "[LIDAR] archived %s (%d bytes), total=%d",
        entry.filename, entry.size_bytes, self.lidar_archive.count,
    )
    # Update lidar_archive_count on MowerState for the count sensor (F7.3.1
    # adds the sensor; the field already lives on MowerState as
    # `archived_lidar_count` per F7.2.1 update).
    new_state = dataclasses.replace(self.data, archived_lidar_count=self.lidar_archive.count)
    self.async_set_updated_data(new_state)
```

Wire it into `_on_state_update`. Find the existing logic at the bottom (around line 1075). Before the `return new_state`, add a check:

```python
# F7.2.2: kick off LiDAR fetch when object_name changes.
if (
    new_state.latest_lidar_object_name is not None
    and new_state.latest_lidar_object_name != getattr(self.data, "latest_lidar_object_name", None)
):
    self.hass.async_create_task(
        self._handle_lidar_object_name(
            new_state.latest_lidar_object_name, now_unix
        )
    )
```

(`async_create_task` because `_handle_lidar_object_name` is `async` and `_on_state_update` is sync.)

- [ ] **Step 4: Add `archived_lidar_count` field to MowerState**

In `mower/state.py` next to `archived_session_count`:

```python
# Source: F7.2.2 — count of archived LiDAR scans on disk. Persistence: persistent.
archived_lidar_count: int | None = None
```

Update the F7.2.2 task's coordinator setup to load and set this on first refresh (mirror the `archived_session_count` block):

```python
archived_lidar = self.lidar_archive.count
if archived_lidar:
    self.data = dataclasses.replace(self.data, archived_lidar_count=archived_lidar)
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_coordinator.py -k "lidar" -v`
Expected: 2 new tests pass.

- [ ] **Step 6: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 577 passed / 4 skipped (575 + 2).

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/mower/state.py tests/integration/test_coordinator.py && git commit -m "F7.2.2: handle s99p20 — fetch + archive PCD scan"
```

---

## Phase F7.3 — LiDAR camera entity pair

### Task F7.3.1: Top-down thumbnail camera (512×512)

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`
- Modify: `custom_components/dreame_a2_mower/translations/en.json`
- Test: `tests/integration/test_lidar_camera.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_lidar_camera.py`:

```python
"""Tests for LiDAR camera entities."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import (
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
)


def _fake_pcd_bytes(n: int = 50) -> bytes:
    """Build a minimal valid binary PCD blob with n random points."""
    rng = np.random.default_rng(seed=42)
    xyz = rng.uniform(-5.0, 5.0, size=(n, 3)).astype(np.float32)
    body = xyz.tobytes()
    header = (
        b"VERSION 0.7\n"
        b"FIELDS x y z\n"
        b"SIZE 4 4 4\n"
        b"TYPE F F F\n"
        b"COUNT 1 1 1\n"
        f"WIDTH {n}\n".encode()
        + b"HEIGHT 1\n"
        b"VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n".encode()
        + b"DATA binary\n"
    )
    return header + body


def test_top_down_camera_returns_png_when_archive_has_scan(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, _fake_pcd_bytes())

    class _Coord:
        lidar_archive = arch
        entry = type("E", (), {"entry_id": "abc"})()
        _cloud = None

    cam = DreameA2LidarTopDownCamera(_Coord())
    import asyncio
    png = asyncio.get_event_loop().run_until_complete(cam.async_camera_image())
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    img = Image.open(io.BytesIO(png))
    assert img.size == (512, 512)


def test_top_down_camera_returns_none_when_archive_empty(tmp_path: Path):
    arch = LidarArchive(tmp_path)

    class _Coord:
        lidar_archive = arch
        entry = type("E", (), {"entry_id": "abc"})()
        _cloud = None

    cam = DreameA2LidarTopDownCamera(_Coord())
    import asyncio
    png = asyncio.get_event_loop().run_until_complete(cam.async_camera_image())
    assert png is None


def test_full_resolution_camera_returns_larger_png(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, _fake_pcd_bytes())

    class _Coord:
        lidar_archive = arch
        entry = type("E", (), {"entry_id": "abc"})()
        _cloud = None

    cam = DreameA2LidarTopDownFullCamera(_Coord())
    import asyncio
    png = asyncio.get_event_loop().run_until_complete(cam.async_camera_image())
    assert png is not None
    img = Image.open(io.BytesIO(png))
    assert img.size == (1024, 1024)  # full-resolution preset
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_lidar_camera.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the camera classes**

Read the existing `custom_components/dreame_a2_mower/camera.py` (53 LOC). Append:

```python
import io
from pathlib import Path

from protocol.pcd import parse_pcd
from protocol.pcd_render import render_top_down


class _LidarCameraBase(CoordinatorEntity[DreameA2MowerCoordinator], Camera):
    """Shared rendering for the top-down LiDAR camera entities.

    Subclasses set ``_resolution`` to the desired (width, height) tuple.
    Reads the latest PCD bytes from the coordinator's lidar_archive,
    parses, and renders to PNG. Returns ``None`` when no scan archived.
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _resolution: tuple[int, int] = (512, 512)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
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

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        archive = getattr(self.coordinator, "lidar_archive", None)
        if archive is None:
            return None
        latest = archive.latest()
        if latest is None:
            return None
        pcd_path = archive.root / latest.filename
        if not pcd_path.is_file():
            return None
        try:
            pcd_bytes = await self.hass.async_add_executor_job(pcd_path.read_bytes)
            cloud = await self.hass.async_add_executor_job(parse_pcd, pcd_bytes)
        except Exception:
            return None
        w, h = self._resolution
        # Default 45° tilt — far more readable than pure top-down for
        # this scene; matches legacy default.
        img = await self.hass.async_add_executor_job(
            render_top_down, cloud, w, h, 8, (0, 0, 0), 45.0,
        )
        buf = io.BytesIO()
        await self.hass.async_add_executor_job(img.save, buf, "PNG")
        return buf.getvalue()


class DreameA2LidarTopDownCamera(_LidarCameraBase):
    """Dashboard thumbnail (512×512) — fast, low-memory."""

    _attr_translation_key = "lidar_top_down"
    _resolution = (512, 512)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lidar_top_down"


class DreameA2LidarTopDownFullCamera(_LidarCameraBase):
    """Full-resolution popout (1024×1024)."""

    _attr_translation_key = "lidar_top_down_full"
    _resolution = (1024, 1024)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lidar_top_down_full"
```

Update `async_setup_entry` to register the new entities:

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DreameA2MapCamera(coordinator),
        DreameA2LidarTopDownCamera(coordinator),
        DreameA2LidarTopDownFullCamera(coordinator),
    ])
```

Note: `render_top_down` returns a `PIL.Image.Image` instance, not raw bytes. The implementation above calls `.save()` to a `BytesIO`. If `render_top_down` already returns bytes (read `protocol/pcd_render.py` to confirm), simplify accordingly.

- [ ] **Step 4: Add translations**

In `translations/en.json` `entity.camera`:

```json
"lidar_top_down": {
    "name": "LiDAR (top-down)"
},
"lidar_top_down_full": {
    "name": "LiDAR (full resolution)"
}
```

(If `entity.camera` doesn't yet exist, add it as a sibling of `entity.sensor`.)

- [ ] **Step 5: Run tests to confirm pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_lidar_camera.py -v`
Expected: 3 tests pass.

- [ ] **Step 6: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 580 passed / 4 skipped (577 + 3).

- [ ] **Step 7: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/translations/en.json tests/integration/test_lidar_camera.py && git commit -m "F7.3.1: LiDAR top-down camera entities (thumbnail + full)"
```

---

## Phase F7.4 — HTTP view for raw PCD download

The WebGL Lovelace card fetches `/api/dreame_a2_mower/lidar/latest.pcd` to render in 3D. Provide that endpoint with auth gating.

### Task F7.4.1: `LidarPcdDownloadView`

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py` — append the view + register
- Test: `tests/integration/test_lidar_view.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_lidar_view.py`:

```python
"""Tests for the /api/dreame_a2_mower/lidar/latest.pcd HTTP view."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView


def test_view_returns_404_when_no_archive(tmp_path: Path):
    """When no coordinator has a lidar_archive, return 404."""
    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {}}
    request.app = {"hass": hass}
    resp = asyncio.get_event_loop().run_until_complete(view.get(request))
    assert resp.status == 404


def test_view_returns_404_when_archive_empty(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    coord = MagicMock()
    coord.lidar_archive = arch

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.get_event_loop().run_until_complete(view.get(request))
    assert resp.status == 404


def test_view_returns_file_response_when_scan_present(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, b"# .PCD v0.7\nDUMMY")
    coord = MagicMock()
    coord.lidar_archive = arch

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.get_event_loop().run_until_complete(view.get(request))
    # Either FileResponse or StreamResponse depending on aiohttp version.
    assert resp.status == 200
    assert "attachment" in resp.headers.get("Content-Disposition", "")
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_lidar_view.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the view**

Append to `custom_components/dreame_a2_mower/camera.py`:

```python
from aiohttp import web
from homeassistant.components.http import HomeAssistantView


class LidarPcdDownloadView(HomeAssistantView):
    """HTTP endpoint that serves the most recent archived ``.pcd`` blob.

    GET ``/api/dreame_a2_mower/lidar/latest.pcd`` (auth required).
    Returns the file with ``Content-Disposition: attachment``. The
    coordinator is looked up from ``hass.data`` on each request so a
    config-entry reload is picked up without re-registering the view.
    """

    url = "/api/dreame_a2_mower/lidar/latest.pcd"
    name = "api:dreame_a2_mower:lidar_latest"
    requires_auth = True

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        archive = None
        for coordinator in entries.values():
            if getattr(coordinator, "lidar_archive", None) is not None:
                archive = coordinator.lidar_archive
                break
        if archive is None:
            return web.Response(status=404, text="LiDAR archive disabled")
        latest = archive.latest()
        if latest is None:
            return web.Response(status=404, text="No LiDAR scans archived yet")
        path = archive.root / latest.filename
        if not path.is_file():
            return web.Response(status=404, text="Archived scan file missing")
        resp = web.FileResponse(path=path)
        resp.headers["Content-Type"] = "application/octet-stream"
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{latest.filename}"'
        )
        return resp
```

Register the view in `async_setup_entry` (only once per process):

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DreameA2MapCamera(coordinator),
        DreameA2LidarTopDownCamera(coordinator),
        DreameA2LidarTopDownFullCamera(coordinator),
    ])
    # Register the auth-gated PCD download endpoint exactly once per HA
    # process. Subsequent config-entry reloads hit the same view.
    if not getattr(hass, "_dreame_a2_lidar_view_registered", False):
        hass.http.register_view(LidarPcdDownloadView())
        hass._dreame_a2_lidar_view_registered = True
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/integration/test_lidar_view.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 583 passed / 4 skipped (580 + 3).

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/camera.py tests/integration/test_lidar_view.py && git commit -m "F7.4.1: LidarPcdDownloadView serves /api/.../latest.pcd"
```

---

## Phase F7.5 — Lift the WebGL Lovelace card

### Task F7.5.1: Lift `dreame-a2-lidar-card.js` + register `/dreame_a2_mower/` static path

**Files:**
- Copy: legacy `www/dreame-a2-lidar-card.js` → `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`
- Modify: `custom_components/dreame_a2_mower/__init__.py`
- (no automated test — JS is server-side static)

- [ ] **Step 1: Copy the card**

```bash
mkdir -p /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/www
cp /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js \
   /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```

- [ ] **Step 2: Verify it's intact**

Run: `wc -l /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`
Expected: 770 lines.

Run: `head -3 /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`
Expected: starts with `// Dreame A2 LiDAR Card — pure-WebGL point-cloud viewer ...`.

- [ ] **Step 3: Register the static path in `__init__.py`**

Read `custom_components/dreame_a2_mower/__init__.py`. Inside `async_setup_entry`, after the coordinator is created and BEFORE `await hass.config_entries.async_forward_entry_setups(...)`:

```python
# F7.5.1: register the bundled WebGL LiDAR card at /dreame_a2_mower/<file>.
# Done once per HA process; reloads are no-op.
if not getattr(hass, "_dreame_a2_static_registered", False):
    from pathlib import Path as _Path
    _www = _Path(__file__).parent / "www"
    if _www.is_dir():
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths(
                [StaticPathConfig(f"/{DOMAIN}", str(_www), False)]
            )
        except ImportError:
            try:
                await hass.http.async_register_static_paths(
                    [(f"/{DOMAIN}", str(_www), False)]
                )
            except Exception:
                LOGGER.warning(
                    "Static-path registration for LiDAR card skipped "
                    "(unsupported HA version). Copy %s into /config/www/ "
                    "manually if you want the bundled card.", _www,
                )
    hass._dreame_a2_static_registered = True
```

- [ ] **Step 4: Smoke-compile + sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m compileall -q custom_components/dreame_a2_mower/ && python -m pytest tests/ -q`
Expected: clean compile + 583 passed (no new tests).

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js custom_components/dreame_a2_mower/__init__.py && git commit -m "F7.5.1: lift WebGL LiDAR card; register /dreame_a2_mower/ static path"
```

---

## Phase F7.6 — `show_lidar_fullscreen` service

The service is a thin convenience wrapper that fires a HA browser-mod-style event a Lovelace card can listen to. It's a UI hook, not a mower-control surface.

### Task F7.6.1: `dreame_a2_mower.show_lidar_fullscreen` service

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.py`
- Modify: `custom_components/dreame_a2_mower/services.yaml`
- Test: `tests/integration/test_services.py` (or wherever existing service tests live — find via grep)

- [ ] **Step 1: Write the failing test**

Find the existing services tests:

```
grep -rln "set_active_selection\|mow_zone\b" /data/claude/homeassistant/ha-dreame-a2-mower-v2/tests/
```

Append to whichever file holds them (likely `tests/integration/test_services.py` or `test_coordinator.py`):

```python
def test_show_lidar_fullscreen_service_fires_event():
    """The service fires a `dreame_a2_mower_lidar_fullscreen` event on
    the bus. Lovelace cards listen for it to pop up the full-screen
    LiDAR view."""
    import asyncio
    from custom_components.dreame_a2_mower.services import (
        async_register_services,
    )
    from unittest.mock import MagicMock, AsyncMock

    hass = MagicMock()
    hass.services.has_service.return_value = False
    hass.services.async_register = MagicMock()
    hass.bus.async_fire = MagicMock()

    asyncio.get_event_loop().run_until_complete(async_register_services(hass))

    # Find the show_lidar_fullscreen handler from the service registration calls.
    handlers = {
        call.args[1]: call.args[2]
        for call in hass.services.async_register.call_args_list
        if call.args[0] == "dreame_a2_mower"
    }
    assert "show_lidar_fullscreen" in handlers
    handler = handlers["show_lidar_fullscreen"]

    call = MagicMock()
    call.data = {}
    asyncio.get_event_loop().run_until_complete(handler(call))
    hass.bus.async_fire.assert_called_once()
    assert hass.bus.async_fire.call_args[0][0] == "dreame_a2_mower_lidar_fullscreen"
```

- [ ] **Step 2: Run test to confirm failure**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -k "show_lidar_fullscreen" -v`
Expected: FAIL — handler not registered.

- [ ] **Step 3: Implement the service**

Read `custom_components/dreame_a2_mower/services.py`. Find `async_register_services`. Append a new handler:

```python
async def _handle_show_lidar_fullscreen(call: ServiceCall) -> None:
    """Fire a bus event a Lovelace card can listen for to pop up the
    full-resolution LiDAR view. The handler accepts no parameters today;
    the convention exists for future extensibility (e.g. a specific
    archived md5 to display)."""
    call.hass.bus.async_fire(
        "dreame_a2_mower_lidar_fullscreen",
        {},
    )
```

Register it in `async_register_services` (alongside the other services):

```python
hass.services.async_register(
    DOMAIN,
    "show_lidar_fullscreen",
    _handle_show_lidar_fullscreen,
    schema=vol.Schema({}),
)
```

(`vol` is already imported in services.py for the existing services. Confirm imports.)

In `services.yaml`, append:

```yaml
show_lidar_fullscreen:
  name: Show LiDAR fullscreen
  description: >
    Fires a `dreame_a2_mower_lidar_fullscreen` event on the HA bus.
    Lovelace cards configured to listen for this event can pop up the
    full-resolution LiDAR view.
  fields: {}
```

If `async_register_services` deregisters with a list of names, append `"show_lidar_fullscreen"` there too. Read the existing `async_unregister_services` shape and mirror it.

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -k "show_lidar_fullscreen" -v`
Expected: pass.

- [ ] **Step 5: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: 584 passed / 4 skipped (583 + 1).

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/ && git commit -m "F7.6.1: dreame_a2_mower.show_lidar_fullscreen service"
```

---

## Phase F7.7 — Options-flow extension

### Task F7.7.1: Three new CONF keys + options-flow surface

Spec §5.8: count 1..50 (default 20), MB 50..2000 (default 200). Plus `CONF_MQTT_ARCHIVE_RETAIN_DAYS` already exists in legacy and should be carried over.

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`
- Modify: `custom_components/dreame_a2_mower/config_flow.py`
- Test: `tests/integration/test_config_flow.py` (if exists; otherwise extend existing config-flow tests)

- [ ] **Step 1: Add CONF keys**

In `const.py`:

```python
CONF_LIDAR_ARCHIVE_KEEP: Final = "lidar_archive_keep"
CONF_LIDAR_ARCHIVE_MAX_MB: Final = "lidar_archive_max_mb"
CONF_SESSION_ARCHIVE_KEEP: Final = "session_archive_keep"

DEFAULT_LIDAR_ARCHIVE_KEEP: Final = 20
DEFAULT_LIDAR_ARCHIVE_MAX_MB: Final = 200
DEFAULT_SESSION_ARCHIVE_KEEP: Final = 50
```

- [ ] **Step 2: Wire into options flow**

Read `config_flow.py` to find `class OptionsFlowHandler` (or whatever the existing options class is named). Inside its `async_step_init`, extend the schema:

```python
import voluptuous as vol
from homeassistant import config_entries

# in OptionsFlowHandler.async_step_init:
schema = vol.Schema({
    vol.Optional(
        CONF_LIDAR_ARCHIVE_KEEP,
        default=self.config_entry.options.get(
            CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP
        ),
    ): vol.All(int, vol.Range(min=1, max=50)),
    vol.Optional(
        CONF_LIDAR_ARCHIVE_MAX_MB,
        default=self.config_entry.options.get(
            CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB
        ),
    ): vol.All(int, vol.Range(min=50, max=2000)),
    vol.Optional(
        CONF_SESSION_ARCHIVE_KEEP,
        default=self.config_entry.options.get(
            CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP
        ),
    ): vol.All(int, vol.Range(min=1, max=200)),
    # ...existing options spread/extended here...
})
```

If the existing options flow uses `vol.Schema` differently (read it first), adapt to its style. Don't introduce a parallel options class.

- [ ] **Step 3: Hook the listener — apply changes at runtime**

In `__init__.py:async_setup_entry`, after the coordinator is created, register an options-update listener that calls `set_retention` and `set_max_bytes` on the live `lidar_archive`:

```python
async def _options_updated(hass_arg, entry_arg):
    coord = hass_arg.data[DOMAIN].get(entry_arg.entry_id)
    if coord is None:
        return
    if hasattr(coord, "lidar_archive"):
        coord.lidar_archive.set_retention(
            int(entry_arg.options.get(CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP))
        )
        coord.lidar_archive.set_max_bytes(
            int(entry_arg.options.get(CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB))
            * 1024 * 1024
        )
    if hasattr(coord, "session_archive"):
        # (session_archive set_retention is from F4 — call if available)
        if hasattr(coord.session_archive, "set_retention"):
            coord.session_archive.set_retention(
                int(entry_arg.options.get(CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP))
            )

entry.async_on_unload(entry.add_update_listener(_options_updated))
```

(If a similar listener already exists for other options — read `__init__.py` first — extend it.)

- [ ] **Step 4: Tests**

Find existing config_flow tests via `grep -rln "OptionsFlow\|async_step_init" tests/`. Append:

```python
def test_options_flow_offers_lidar_retention_keys():
    """The options flow's schema must include CONF_LIDAR_ARCHIVE_KEEP
    and CONF_LIDAR_ARCHIVE_MAX_MB with the documented bounds."""
    from custom_components.dreame_a2_mower.config_flow import OptionsFlowHandler
    from custom_components.dreame_a2_mower.const import (
        CONF_LIDAR_ARCHIVE_KEEP,
        CONF_LIDAR_ARCHIVE_MAX_MB,
    )
    from unittest.mock import MagicMock

    entry = MagicMock()
    entry.options = {}
    handler = OptionsFlowHandler(entry)
    schema_keys = {str(k) for k in handler._build_schema().schema.keys()}
    assert CONF_LIDAR_ARCHIVE_KEEP in schema_keys
    assert CONF_LIDAR_ARCHIVE_MAX_MB in schema_keys
```

This test assumes the OptionsFlowHandler exposes a `_build_schema()` method returning the voluptuous schema. If the existing handler builds the schema inline inside `async_step_init`, refactor it to a `_build_schema()` helper as part of this task — the helper makes the schema testable and is a small, contained change. If the existing handler already has a different way to introspect the schema, mimic that instead.

- [ ] **Step 5: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green. New test count varies depending on what already exists — aim for at least one assertion that the schema includes the new keys.

- [ ] **Step 6: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/config_flow.py custom_components/dreame_a2_mower/__init__.py tests/ && git commit -m "F7.7.1: options flow — LiDAR + session archive retention"
```

---

## Phase F7.8 — Showcase dashboard

### Task F7.8.1: `dashboards/mower/dashboard.yaml` — 7 views per spec §9

**Files:**
- Create: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Create the dashboard YAML**

The spec §9 lists seven views: Mower (live map + state strip + action strip + active selection + alerts), Mowing settings, More settings, Schedule, LiDAR (3D card + popout button + archive count), Sessions (latest summary + archive list + replay/finalize buttons), Diagnostics (novel observations + raw protocol sensors + archive counts + endpoints).

Build `dashboards/mower/dashboard.yaml` using ONLY standard Lovelace cards plus the bundled `custom:dreame-a2-lidar-card`. Do NOT use `xiaomi-vacuum-map-card` (per memory).

```yaml
title: Dreame A2 Mower
views:
  - title: Mower
    path: mower
    icon: mdi:robot-mower-outline
    cards:
      - type: picture-entity
        entity: camera.dreame_a2_mower_map
        name: Live Map
        camera_view: live
        show_state: false
      - type: entities
        title: State
        entities:
          - entity: lawn_mower.dreame_a2_mower
          - entity: sensor.dreame_a2_mower_battery_level
          - entity: sensor.dreame_a2_mower_charging_status
          - entity: binary_sensor.dreame_a2_mower_obstacle_detected
          - entity: binary_sensor.dreame_a2_mower_rain_protection_active
      - type: horizontal-stack
        title: Actions
        cards:
          - type: button
            entity: button.dreame_a2_mower_recharge
            tap_action:
              action: call-service
              service: button.press
              target:
                entity_id: button.dreame_a2_mower_recharge
          - type: button
            entity: button.dreame_a2_mower_find_bot
            tap_action:
              action: call-service
              service: dreame_a2_mower.find_bot
          - type: button
            entity: button.dreame_a2_mower_finalize_session
      - type: entities
        title: Active Selection
        entities:
          - entity: select.dreame_a2_mower_action_mode
          - entity: sensor.dreame_a2_mower_active_selection
      - type: entities
        title: Alerts
        entities:
          - entity: binary_sensor.dreame_a2_mower_positioning_failed
          - entity: binary_sensor.dreame_a2_mower_battery_temp_low
          - entity: sensor.dreame_a2_mower_error_code

  - title: Mowing Settings
    path: mowing-settings
    icon: mdi:grass
    cards:
      - type: entities
        title: General Mode
        entities:
          - entity: number.dreame_a2_mower_mowing_height_cm
          - entity: switch.dreame_a2_mower_edge_brushing
          - entity: number.dreame_a2_mower_blade_speed
          - entity: number.dreame_a2_mower_path_overlap_cm

  - title: More Settings
    path: more-settings
    icon: mdi:cog-outline
    cards:
      - type: entities
        title: Rain protection
        entities:
          - entity: switch.dreame_a2_mower_rain_protection
          - entity: number.dreame_a2_mower_rain_resume_delay_min
      - type: entities
        title: Frost protection
        entities:
          - entity: switch.dreame_a2_mower_frost_protection
          - entity: number.dreame_a2_mower_frost_temp_threshold
      - type: entities
        title: Do Not Disturb / Charging / Lighting / Photo
        entities:
          - entity: switch.dreame_a2_mower_dnd_enabled
          - entity: time.dreame_a2_mower_dnd_start
          - entity: time.dreame_a2_mower_dnd_end
          - entity: switch.dreame_a2_mower_charging_lighting
          - entity: switch.dreame_a2_mower_obstacle_photo

  - title: Schedule
    path: schedule
    icon: mdi:calendar-clock
    cards:
      - type: entities
        title: Schedule master toggles
        entities:
          - entity: switch.dreame_a2_mower_schedule_spring_summer
          - entity: switch.dreame_a2_mower_schedule_autumn_winter
      - type: markdown
        title: Schedule slots
        content: |
          Per-slot schedule editing is BT-only on the g2408 today; this
          integration only exposes the master enable/disable toggles
          and a read-only summary. Use the Dreamehome app for slot
          editing.

  - title: LiDAR
    path: lidar
    icon: mdi:cube-scan
    cards:
      - type: custom:dreame-a2-lidar-card
        url: /api/dreame_a2_mower/lidar/latest.pcd
        show_map: true
        map_entity: camera.dreame_a2_mower_map
      - type: horizontal-stack
        cards:
          - type: button
            name: Show fullscreen
            tap_action:
              action: call-service
              service: dreame_a2_mower.show_lidar_fullscreen
          - type: entity
            entity: sensor.dreame_a2_mower_lidar_archive_count
            name: Archived scans

  - title: Sessions
    path: sessions
    icon: mdi:history
    cards:
      - type: entities
        title: Latest session
        entities:
          - entity: sensor.dreame_a2_mower_latest_session_area_m2
          - entity: sensor.dreame_a2_mower_latest_session_duration_min
          - entity: sensor.dreame_a2_mower_latest_session_unix_ts
      - type: entities
        title: Archive
        entities:
          - entity: sensor.dreame_a2_mower_archived_session_count
      - type: horizontal-stack
        cards:
          - type: button
            name: Finalize stuck session
            tap_action:
              action: call-service
              service: dreame_a2_mower.finalize_session
          - type: markdown
            content: |
              Use **Finalize stuck session** if a mowing session has
              stopped on the mower but the integration is still showing
              "fetching summary" for more than 30 minutes.

  - title: Diagnostics
    path: diagnostics
    icon: mdi:wrench-cog-outline
    cards:
      - type: entities
        title: Novel observations
        entities:
          - entity: sensor.dreame_a2_mower_novel_observations
          - entity: sensor.dreame_a2_mower_data_freshness
          - entity: sensor.dreame_a2_mower_api_endpoints_supported
      - type: entities
        title: Raw protocol sensors
        entities:
          - entity: sensor.dreame_a2_mower_task_state_code
          - entity: sensor.dreame_a2_mower_mowing_phase
          - entity: sensor.dreame_a2_mower_slam_task_label
      - type: entities
        title: Archive counts
        entities:
          - entity: sensor.dreame_a2_mower_archived_session_count
          - entity: sensor.dreame_a2_mower_lidar_archive_count
```

**Note:** Some entity IDs above are aspirational — they're what spec §5 says should exist. If F1–F7 didn't actually create one of them (e.g., the `sensor.dreame_a2_mower_lidar_archive_count` is referenced from F7.2.2 but maybe wasn't surfaced as a sensor yet), either add the sensor in F7.10.1 or drop it from the dashboard. To check, run:

```
grep -rn "lidar_archive_count\|archived_lidar_count\|frost_protection\|frost_temp_threshold\|charging_lighting" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/sensor.py /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/switch.py /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/number.py
```

For each missing entity, EITHER add it to the appropriate platform file OR remove the line from the dashboard YAML. Do not leave references to non-existent entities. If you remove some, leave a markdown card explaining what was deferred and to which post-cutover work.

- [ ] **Step 2: Smoke-validate the YAML**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: no exception (valid YAML).

- [ ] **Step 3: Add a lidar_archive_count sensor**

Add to `sensor.py` SENSORS tuple (next to `archived_session_count`):

```python
DreameA2SensorEntityDescription(
    key="lidar_archive_count",
    translation_key="lidar_archive_count",
    icon="mdi:cube-scan",
    state_class=SensorStateClass.MEASUREMENT,
    value_fn=lambda s: s.archived_lidar_count,
),
```

Add the translation to `translations/en.json` `entity.sensor`:

```json
"lidar_archive_count": {
    "name": "LiDAR archive count"
}
```

- [ ] **Step 4: Run full sweep**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q`
Expected: green; new sensor count test (if existing) updates.

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add dashboards/mower/dashboard.yaml custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/translations/en.json && git commit -m "F7.8.1: showcase dashboard YAML + sensor.lidar_archive_count"
```

---

## Phase F7.9 — User-facing docs + cutover runbook

### Task F7.9.1: `docs/lidar.md` — user setup guide

**Files:**
- Create: `docs/lidar.md`

- [ ] **Step 1: Write the doc**

```markdown
# LiDAR — user guide

This integration archives every LiDAR scan the mower uploads (announced
on MQTT slot s99p20) and renders it three ways: a top-down PNG
thumbnail, a full-resolution PNG popout, and a 3D interactive WebGL
view via the bundled Lovelace card.

## Entities

| Entity | What |
|---|---|
| `camera.dreame_a2_mower_lidar_top_down` | 512×512 thumbnail (45° tilt). Default-enabled. |
| `camera.dreame_a2_mower_lidar_top_down_full` | 1024×1024 popout. Default-enabled. |
| `sensor.dreame_a2_mower_lidar_archive_count` | Count of archived `.pcd` files on disk. |

## 3D viewer setup

1. The integration ships a Lovelace card at
   `/dreame_a2_mower/dreame-a2-lidar-card.js`. Add it as a Lovelace
   resource (Settings → Dashboards → Resources → ADD RESOURCE):

   - URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`
   - Type: `JavaScript Module`

2. Add a card to your dashboard:

   ```yaml
   - type: custom:dreame-a2-lidar-card
     url: /api/dreame_a2_mower/lidar/latest.pcd
     show_map: true
     map_entity: camera.dreame_a2_mower_map
     point_size: 3
   ```

3. Drag to orbit; wheel to zoom; bottom slider adjusts splat size; toggle
   the map underlay if the lawn outline isn't visible.

## Archive retention

Configure under Settings → Devices & Services → Dreame A2 Mower →
Configure → Options:

| Option | Default | Range |
|---|---|---|
| LiDAR archive count cap | 20 | 1..50 |
| LiDAR archive size cap (MB) | 200 | 50..2000 |

When either cap is reached, oldest scans are evicted oldest-first. PCDs
run 2–3 MB each on this hardware, so the size cap is the more useful
of the two for most users.

## Manual download

The most recent `.pcd` blob is served (auth required) at:

```
GET /api/dreame_a2_mower/lidar/latest.pcd
```

Save it locally and open in Open3D, CloudCompare, or MeshLab for the
full interactive 3D view.

## Service

`dreame_a2_mower.show_lidar_fullscreen` fires a
`dreame_a2_mower_lidar_fullscreen` event on the HA bus. Lovelace cards
can listen for this event to pop up a full-screen LiDAR view.
```

- [ ] **Step 2: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add docs/lidar.md && git commit -m "F7.9.1: docs/lidar.md user setup guide"
```

### Task F7.9.2: `docs/cutover.md` — runbook

**Files:**
- Create: `docs/cutover.md`

- [ ] **Step 1: Write the doc**

```markdown
# Cutover runbook — legacy → greenfield

This document describes how to swap the legacy `okolbu/ha-dreame-a2-mower`
integration for the greenfield `okolbu/ha-dreame-a2-mower-v2`. Run the
parity checklist (spec §6) first; cut over only after every item passes.

## Pre-flight

1. **Capture session and LiDAR archives.** The legacy integration
   stores archives at `/config/dreame_a2_mower/{sessions,lidar}/`. Back
   them up to a tarball or another path. The greenfield integration
   uses the SAME paths so archives are picked up automatically — but
   if the cutover doesn't go to plan, you want a known-good copy.

2. **Snapshot the legacy config-entry options** from
   Settings → Devices & Services → Dreame A2 Mower → Configure. Note
   station bearing, retention caps, MQTT-archive enable, etc.

3. **Confirm the parity checklist passes.** §6 of the spec lists 48
   items. Each should demonstrably work in greenfield before cutover.

## Cutover steps

1. Stop HA (or at minimum disable the legacy integration in
   Settings → Devices & Services).

2. Remove the legacy custom component:
   ```
   rm -rf /config/custom_components/dreame_a2_mower
   ```

3. Install the greenfield component (HACS or manual git clone). The
   custom-component path stays the same: `dreame_a2_mower`.

4. Restart HA.

5. Configure the new integration. Username/password are re-entered
   (they are NOT migrated — credential storage is HA-encrypted under
   the config entry, not on disk in a portable form).

6. Enter the same options as the legacy snapshot (station bearing,
   retention caps).

7. Verify on the dashboard:
   - Live map renders with the archived dock pin and exclusion zones.
   - Mower state shows correctly (battery, charging, mode).
   - LiDAR thumbnail is populated (only after the next `s99p20` push;
     to force one, tap "Download LiDAR map" in the Dreame app).
   - Session archive list is preserved; replay works against existing
     md5s.

8. Re-add the bundled Lovelace card resource if you used it before:
   - URL `/dreame_a2_mower/dreame-a2-lidar-card.js`, type module.

## Rollback

If something is broken:

1. Remove `/config/custom_components/dreame_a2_mower` again.
2. Restore the legacy integration from git or HACS.
3. Restart HA.
4. The archives at `/config/dreame_a2_mower/` are unchanged and will
   pick up under the legacy integration.

The greenfield integration does NOT delete or rewrite archive entries
written by the legacy version.

## Repo cleanup post-cutover

Once you've confirmed greenfield is stable for at least one full
session cycle, rename the legacy repo to `-legacy`:

```
gh repo rename okolbu/ha-dreame-a2-mower okolbu/ha-dreame-a2-mower-legacy
```

…and update any HACS pin to point at `ha-dreame-a2-mower-v2`.
```

- [ ] **Step 2: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git add docs/cutover.md && git commit -m "F7.9.2: docs/cutover.md runbook"
```

---

## Phase F7.10 — Final sweep + tag v1.0.0a0

### Task F7.10.1: Verify everything + tag

**Files:**
- (none new)

- [ ] **Step 1: Verify layering invariant**

Run:
```
grep -rn "from homeassistant\|import homeassistant" /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/{mower,live_map,archive,observability}/
```
Expected: empty.

- [ ] **Step 2: Smoke-compile**

Run:
```
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m compileall -q custom_components/dreame_a2_mower/ protocol/
```
Expected: empty output.

- [ ] **Step 3: Final pytest sweep**

Run:
```
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && python -m pytest tests/ -q
```
Expected: ALL tests pass. Baseline before F7 was 564 / 4 skipped. F7 adds approximately 20 new tests; expect ~584+ passing.

- [ ] **Step 4: Verify dashboard YAML still loads**

Run:
```
python -c "import yaml; yaml.safe_load(open('/data/claude/homeassistant/ha-dreame-a2-mower-v2/dashboards/mower/dashboard.yaml'))"
```
Expected: no exception.

- [ ] **Step 5: Verify the WebGL card was lifted intact**

Run:
```
diff /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js /data/claude/homeassistant/ha-dreame-a2-mower-v2/custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js
```
Expected: no output (files identical).

- [ ] **Step 6: Tag v1.0.0a0**

If the sweep is clean, no commit needed:

```
cd /data/claude/homeassistant/ha-dreame-a2-mower-v2 && git tag v1.0.0a0
```

(If the sweep found issues, fix them, commit, then tag.)

Do NOT push. The controller pushes commit + tag.

---

## Self-review checklist

- [ ] `archive/lidar.py` lifted from legacy with no behavioral change beyond the size-cap addition.
- [ ] `LidarArchive` honors both count cap (1..50) and MB cap (50..2000) independently.
- [ ] `s99p20` MQTT trigger reaches `_handle_lidar_object_name` via the `latest_lidar_object_name` field on MowerState.
- [ ] `_handle_lidar_object_name` is idempotent on repeat object_names.
- [ ] `camera.dreame_a2_mower_lidar_top_down` renders 512×512; `_full` renders 1024×1024.
- [ ] Both cameras return None when archive empty.
- [ ] `/api/dreame_a2_mower/lidar/latest.pcd` requires auth and returns the most-recent archived blob.
- [ ] `/dreame_a2_mower/dreame-a2-lidar-card.js` is served as a static path; URL stable.
- [ ] `dreame_a2_mower.show_lidar_fullscreen` fires the documented bus event.
- [ ] Options flow exposes count + MB caps with correct bounds.
- [ ] `dashboards/mower/dashboard.yaml` validates as YAML and references only entities the integration actually creates.
- [ ] `docs/lidar.md` and `docs/cutover.md` are present.
- [ ] `observability/`, `mower/`, `live_map/`, `archive/` remain HA-import-free.
- [ ] pytest sweep is green.
- [ ] v1.0.0a0 tag created.

## What this plan does NOT do

Out of scope for F7 (deferred to post-cutover):
- Migration of legacy archives between layouts (greenfield uses the
  same paths — no migration needed).
- Auto-detection of g2408 vs other models (single-model integration
  per spec §10).
- Multi-mower-per-account.
- Voice-pack and stream-camera (vacuum-only on upstream; g2408 has no
  front camera).
- Pre-cutover live verification on the user's mower — that happens
  manually after this plan ships, against the parity checklist.
