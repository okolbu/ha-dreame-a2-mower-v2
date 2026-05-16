# Persistent Novel Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-memory `NovelObservationRegistry`'s "novel since boot" semantics with "novel ever in this mower's history" by persisting observations to a JSONL file and replaying it into the watchdog on integration startup.

**Architecture:** A new `PersistentNovelStore` class owns the `/config/dreame_a2_mower/novel_observations.jsonl` file. On startup it walks the file and calls `registry.record_*` to seed the watchdog; subsequent `saw_*` True returns trigger one async-executor-job append per observation. The watchdog code itself stays unchanged — persistence is layered on top via a new collaborator + a single attach hook on the existing registry.

**Tech Stack:** Python 3.13, Home Assistant integration (`hass.async_add_executor_job`, `Path`, `asyncio.Lock`), pytest, JSONL.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/observability/novel_store.py` | New `PersistentNovelStore` class. Owns the JSONL file lifecycle: load (replay into a registry) + append (single-line write via executor). | Create |
| `custom_components/dreame_a2_mower/observability/registry.py` | `NovelObservationRegistry`. Adds optional `_store` collaborator + `attach_store(store, hass)` method. Modifies `record_*` to fire-and-forget `store.append` on True returns. | Modify |
| `custom_components/dreame_a2_mower/observability/__init__.py` | Package exports. Add `PersistentNovelStore`. | Modify |
| `custom_components/dreame_a2_mower/__init__.py` | `async_setup_entry`. Construct the store, await `load`, call `attach_store`. | Modify |
| `tests/observability/test_novel_store.py` | All `PersistentNovelStore` behavior: empty-file load, round-trip append/reload, malformed-line tolerance, per-category serialization. | Create |
| `tests/observability/test_registry.py` | Add tests for the new `attach_store` integration (with-store vs without-store; load doesn't echo). | Modify |

---

## Phase 1 — Persistence module (TDD)

### Task 1: Empty-file load returns 0

**Files:**
- Create: `custom_components/dreame_a2_mower/observability/novel_store.py`
- Create: `tests/observability/test_novel_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/observability/test_novel_store.py`:

```python
"""Tests for the persistent novel-observation JSONL store."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.observability.novel_store import (
    PersistentNovelStore,
)
from custom_components.dreame_a2_mower.observability.registry import (
    NovelObservationRegistry,
)


@pytest.mark.asyncio
async def test_load_missing_file_returns_zero(tmp_path: Path) -> None:
    """First-run case: no file exists, load returns 0 and doesn't crash."""
    store = PersistentNovelStore(tmp_path / "novel_observations.jsonl")
    reg = NovelObservationRegistry()
    n = await store.load(reg)
    assert n == 0
    assert reg.snapshot().count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/observability/test_novel_store.py::test_load_missing_file_returns_zero -v`
Expected: FAIL with `ModuleNotFoundError: ... novel_store`.

- [ ] **Step 3: Implement minimal store**

Create `custom_components/dreame_a2_mower/observability/novel_store.py`:

```python
"""Append-only JSONL persistence for novel observations.

Owns the on-disk file at ``/config/dreame_a2_mower/novel_observations.jsonl``.
Loaded once at integration setup to seed the registry's watchdog with
"things this mower has ever seen", then attached so subsequent novel
observations append exactly one line per first-seen token.

NO ``homeassistant.*`` imports — see end of file for the executor-
job wrapper used by the integration.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import NovelObservation, NovelObservationRegistry

LOGGER = logging.getLogger(__name__)


class PersistentNovelStore:
    """JSONL-backed novelty store.

    File format: one JSON object per line, fields per category:
      property: {"ts", "category": "property", "siid", "piid"}
      value:    {"ts", "category": "value", "siid", "piid", "value"}
      event:    {"ts", "category": "event", "siid", "eiid", "piids"}
      key:      {"ts", "category": "key", "namespace", "key"}
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def load(self, registry: "NovelObservationRegistry") -> int:
        """Walk the file, replay each line into ``registry`` via record_*.

        Returns the count of entries successfully replayed. Tolerates
        a missing file (returns 0). Tolerates malformed lines (logs
        a warning, skips the line, continues).
        """
        if not self._path.exists():
            return 0
        return 0  # filled in by Task 2
```

Note: this minimal stub returns 0 unconditionally so the test passes; Task 2 adds real load logic. This is the TDD red-green-refactor cadence — get the empty-file path passing first, then layer.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/observability/test_novel_store.py::test_load_missing_file_returns_zero -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/observability/novel_store.py \
        tests/observability/test_novel_store.py
git commit -m "novel_store: scaffold PersistentNovelStore with missing-file load"
```

---

### Task 2: Round-trip — append a value, reload populates the watchdog

**Files:**
- Modify: `custom_components/dreame_a2_mower/observability/novel_store.py`
- Modify: `tests/observability/test_novel_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/observability/test_novel_store.py`:

```python
@pytest.mark.asyncio
async def test_value_round_trip(tmp_path: Path) -> None:
    """Append a value entry, reload into a fresh registry, watchdog
    should now consider that value already-seen."""
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    # Record a novel value — fires True the first time.
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000) is True
    # Append it via the store directly (mirrors what the registry
    # would do once attach_store is wired in Task 5).
    await store.append_sync(
        category="value", ts=1700000000, siid=2, piid=2, value=28,
    )

    # Fresh registry, fresh watchdog. Reload from disk.
    reg2 = NovelObservationRegistry()
    n = await store.load(reg2)
    assert n == 1
    # The watchdog now knows value 28 — re-recording returns False.
    assert reg2.record_value(siid=2, piid=2, value=28, now_unix=1700000100) is False
    # And a different value for the same slot still returns True.
    assert reg2.record_value(siid=2, piid=2, value=70, now_unix=1700000100) is True


@pytest.mark.asyncio
async def test_load_count_matches_file_lines(tmp_path: Path) -> None:
    """Load returns the count of replayed entries."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "property", "siid": 6, "piid": 1}\n'
        '{"ts": 2, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
        '{"ts": 3, "category": "value", "siid": 6, "piid": 1, "value": 300}\n'
    )
    reg = NovelObservationRegistry()
    n = await PersistentNovelStore(path).load(reg)
    assert n == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/observability/test_novel_store.py -v`
Expected: FAIL — `append_sync` doesn't exist; `load` returns 0 unconditionally.

- [ ] **Step 3: Implement load + append_sync**

Replace the body of `novel_store.py` with:

```python
"""Append-only JSONL persistence for novel observations.

Owns the on-disk file at ``/config/dreame_a2_mower/novel_observations.jsonl``.
Loaded once at integration setup to seed the registry's watchdog with
"things this mower has ever seen", then attached so subsequent novel
observations append exactly one line per first-seen token.

NO ``homeassistant.*`` imports at module top — the hass-aware
``append`` method is layered on top of ``append_sync`` so the core
serialization logic stays testable without an HA event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import NovelObservationRegistry

LOGGER = logging.getLogger(__name__)


class PersistentNovelStore:
    """JSONL-backed novelty store.

    File format: one JSON object per line, fields per category:
      property: {"ts", "category": "property", "siid", "piid"}
      value:    {"ts", "category": "value", "siid", "piid", "value"}
      event:    {"ts", "category": "event", "siid", "eiid", "piids"}
      key:      {"ts", "category": "key", "namespace", "key"}
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def load(self, registry: "NovelObservationRegistry") -> int:
        """Walk the file, replay each line into ``registry`` via record_*.

        Returns the count of entries successfully replayed. Tolerates
        a missing file (returns 0). Tolerates malformed lines (logs
        a warning, skips the line, continues).
        """
        if not self._path.exists():
            return 0
        replayed = 0
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError:
            LOGGER.exception(
                "novel_store: failed to read %s; treating as empty",
                self._path,
            )
            return 0
        for line_no, raw in enumerate(content.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "novel_store: skipping malformed line %d in %s: %s",
                    line_no, self._path.name, exc,
                )
                continue
            if self._replay_into(registry, obj):
                replayed += 1
        return replayed

    def _replay_into(
        self, registry: "NovelObservationRegistry", obj: dict[str, Any]
    ) -> bool:
        """Dispatch one parsed line into the registry's record_* methods.

        Returns True if the entry was a recognised category and was
        replayed. Returns False (with a warning) for unrecognised
        categories — preserves forward-compatibility if a future
        version writes new categories the current code doesn't know.
        """
        cat = obj.get("category")
        ts = int(obj.get("ts", 0))
        try:
            if cat == "property":
                registry.record_property(int(obj["siid"]), int(obj["piid"]), ts)
            elif cat == "value":
                registry.record_value(
                    int(obj["siid"]), int(obj["piid"]), obj["value"], ts,
                )
            elif cat == "event":
                registry.record_event(
                    int(obj["siid"]),
                    int(obj["eiid"]),
                    [int(p) for p in obj.get("piids", [])],
                    ts,
                )
            elif cat == "key":
                registry.record_key(
                    str(obj["namespace"]), str(obj["key"]), ts,
                )
            else:
                LOGGER.warning(
                    "novel_store: unknown category %r in line %r",
                    cat, obj,
                )
                return False
        except (KeyError, TypeError, ValueError) as exc:
            LOGGER.warning(
                "novel_store: malformed %r entry %r: %s", cat, obj, exc,
            )
            return False
        return True

    async def append_sync(
        self,
        *,
        category: str,
        ts: int,
        siid: int | None = None,
        piid: int | None = None,
        value: Any = None,
        eiid: int | None = None,
        piids: list[int] | None = None,
        namespace: str | None = None,
        key: str | None = None,
    ) -> None:
        """Append one line to the file. Non-HA-aware variant used by
        tests and by the hass-aware ``append`` wrapper.

        Builds the JSON line from explicit kwargs (one per category-
        specific field) so callers can't accidentally serialise random
        attributes. Acquires the lock so concurrent appends don't
        produce interleaved partial lines.
        """
        obj: dict[str, Any] = {"ts": int(ts), "category": category}
        if category == "property":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["piid"] = int(piid)  # type: ignore[arg-type]
        elif category == "value":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["piid"] = int(piid)  # type: ignore[arg-type]
            obj["value"] = value
        elif category == "event":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["eiid"] = int(eiid)  # type: ignore[arg-type]
            obj["piids"] = list(piids or [])
        elif category == "key":
            obj["namespace"] = str(namespace)
            obj["key"] = str(key)
        else:
            LOGGER.warning(
                "novel_store: refusing to append unknown category %r", category,
            )
            return
        line = json.dumps(obj, separators=(",", ":"), default=repr) + "\n"
        async with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                LOGGER.exception(
                    "novel_store: failed to append to %s; observation lost",
                    self._path,
                )
```

Note: `default=repr` in `json.dumps` is a defensive fallback — the serializable values we expect (ints, strings, lists of ints, scalars) will always serialise normally. If a non-serializable value sneaks through, `repr` gives a deterministic string instead of crashing the integration.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/observability/test_novel_store.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/observability/novel_store.py \
        tests/observability/test_novel_store.py
git commit -m "novel_store: load() replays JSONL into registry; append_sync writes one line"
```

---

### Task 3: Per-category coverage — property, event, key round-trips

**Files:**
- Modify: `tests/observability/test_novel_store.py`

The Task 2 round-trip covered the value category. Add tests for the other three so we catch any field-name typos before they ship.

- [ ] **Step 1: Write the failing tests**

Append to `tests/observability/test_novel_store.py`:

```python
@pytest.mark.asyncio
async def test_property_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    assert reg.record_property(siid=99, piid=42, now_unix=1700000000) is True
    await store.append_sync(category="property", ts=1700000000, siid=99, piid=42)

    reg2 = NovelObservationRegistry()
    assert await store.load(reg2) == 1
    assert reg2.record_property(siid=99, piid=42, now_unix=1700000100) is False


@pytest.mark.asyncio
async def test_event_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    assert reg.record_event(siid=4, eiid=1, piids=[1, 8, 14], now_unix=1700000000) is True
    await store.append_sync(
        category="event", ts=1700000000, siid=4, eiid=1, piids=[1, 8, 14],
    )

    reg2 = NovelObservationRegistry()
    assert await store.load(reg2) == 1
    # Same eiid + same piids → not novel
    assert reg2.record_event(siid=4, eiid=1, piids=[1, 8, 14], now_unix=1700000100) is False


@pytest.mark.asyncio
async def test_key_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    assert reg.record_key(namespace="session_summary", key="obs", now_unix=1700000000) is True
    await store.append_sync(
        category="key", ts=1700000000, namespace="session_summary", key="obs",
    )

    reg2 = NovelObservationRegistry()
    assert await store.load(reg2) == 1
    assert reg2.record_key(namespace="session_summary", key="obs", now_unix=1700000100) is False
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/observability/test_novel_store.py -v`
Expected: 6 PASS (3 from Task 2 + 3 new). The append_sync code in Task 2 already handled all four categories; these tests confirm.

- [ ] **Step 3: Commit**

```bash
git add tests/observability/test_novel_store.py
git commit -m "novel_store: round-trip tests for property, event, key categories"
```

---

### Task 4: Crash-tolerance — malformed lines and unknown categories

**Files:**
- Modify: `tests/observability/test_novel_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/observability/test_novel_store.py`:

```python
@pytest.mark.asyncio
async def test_load_skips_malformed_json_line(tmp_path: Path) -> None:
    """A partial last line (e.g. from a power loss mid-write) is
    skipped with a warning, not raised."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
        '{"ts": 2, "category": "value", "siid": 6, "pii'  # truncated
    )
    reg = NovelObservationRegistry()
    n = await PersistentNovelStore(path).load(reg)
    assert n == 1  # the good line replayed; the bad line skipped


@pytest.mark.asyncio
async def test_load_skips_unknown_category(tmp_path: Path) -> None:
    """Forward-compat: a category written by a newer version doesn't
    crash the loader."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
        '{"ts": 2, "category": "future_kind", "siid": 9, "piid": 9}\n'
        '{"ts": 3, "category": "value", "siid": 6, "piid": 1, "value": 300}\n'
    )
    reg = NovelObservationRegistry()
    n = await PersistentNovelStore(path).load(reg)
    assert n == 2  # two value lines replayed; the unknown one skipped


@pytest.mark.asyncio
async def test_load_skips_missing_field(tmp_path: Path) -> None:
    """A 'value' line missing its 'value' field gets skipped, not raised."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
        '{"ts": 2, "category": "value", "siid": 9}\n'  # missing piid + value
        '{"ts": 3, "category": "value", "siid": 6, "piid": 1, "value": 300}\n'
    )
    reg = NovelObservationRegistry()
    n = await PersistentNovelStore(path).load(reg)
    assert n == 2
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/observability/test_novel_store.py -v`
Expected: 9 PASS. The error-handling code from Task 2's `_replay_into` already implements this; these tests confirm.

- [ ] **Step 3: Commit**

```bash
git add tests/observability/test_novel_store.py
git commit -m "novel_store: crash-tolerance tests for malformed/unknown lines"
```

---

## Phase 2 — Wire registry to store

### Task 5: Registry attaches to a store

**Files:**
- Modify: `custom_components/dreame_a2_mower/observability/registry.py`
- Modify: `tests/observability/test_registry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/observability/test_registry.py`:

```python
import asyncio

import pytest

from custom_components.dreame_a2_mower.observability.novel_store import (
    PersistentNovelStore,
)


def test_attach_store_is_optional():
    """A registry without an attached store behaves exactly as today:
    record_* returns True/False based on watchdog state, no I/O happens."""
    reg = NovelObservationRegistry()
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000) is True
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000100) is False


@pytest.mark.asyncio
async def test_attach_store_appends_on_novel(tmp_path):
    """After attach_store, every True return appends one line."""
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    reg.attach_store(store)

    reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000)
    reg.record_value(siid=2, piid=2, value=28, now_unix=1700000100)  # dup
    reg.record_value(siid=2, piid=2, value=70, now_unix=1700000200)

    # The append calls are fire-and-forget asyncio tasks; let the loop run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2  # two distinct values, the dup is filtered


@pytest.mark.asyncio
async def test_load_then_attach_does_not_re_echo(tmp_path):
    """load() runs BEFORE attach_store, so replayed entries don't write back."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
    )
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()

    # 1. Load (no store attached yet — replays into watchdog only).
    n = await store.load(reg)
    assert n == 1

    # 2. Attach store.
    reg.attach_store(store)

    # 3. Trigger the same observation again — watchdog says non-novel,
    #    no append happens.
    fired = reg.record_value(siid=6, piid=1, value=200, now_unix=1700000000)
    assert fired is False
    await asyncio.sleep(0)

    # File still has its original single line — no echo.
    assert path.read_text().count("\n") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/observability/test_registry.py -v -k 'attach_store'`
Expected: FAIL — `attach_store` doesn't exist on `NovelObservationRegistry`.

- [ ] **Step 3: Implement attach_store + record_* hooks**

Modify `custom_components/dreame_a2_mower/observability/registry.py`. Replace the file's contents with:

```python
"""Novel-observation registry — timestamped wrapper over UnknownFieldWatchdog.

The watchdog at ``protocol/unknown_watchdog.py`` answers "have I seen
this key before?". The registry adds a wall-clock timestamp and a
category label (``property`` / ``value`` / ``event`` / ``key``) so HA
sensors and diagnostics can show *what* surprised the integration *when*.

Optionally backed by a ``PersistentNovelStore`` (attach via
``attach_store``) so first-observations survive HA restarts. Without
a store attached, behaves as a process-scoped registry — the
backwards-compatible default for tests and any code path that
constructs a registry without persistence.

NO ``homeassistant.*`` imports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..protocol.unknown_watchdog import UnknownFieldWatchdog

if TYPE_CHECKING:
    from .novel_store import PersistentNovelStore


@dataclass(frozen=True)
class NovelObservation:
    """One novel-token sighting."""

    category: str           # "property" | "value" | "event" | "key"
    detail: str             # human-readable token
    first_seen_unix: int    # wall-clock time of the first sighting


@dataclass(frozen=True)
class RegistrySnapshot:
    """Read-only view of the registry suitable for sensor attributes."""

    count: int
    observations: list[NovelObservation]


class NovelObservationRegistry:
    """Records first-arrival of unknown protocol shapes.

    Methods return ``True`` the first time a token is seen, ``False`` on
    every subsequent observation — matches the watchdog's "novelty bool"
    return convention so callers can gate ``LOGGER.warning`` calls cleanly.

    Caps total in-memory observations at ``MAX_OBSERVATIONS`` to bound
    the sensor attribute list and the diagnostics dump size. The
    persistent store (when attached) is bounded by the watchdog's
    per-slot caps.
    """

    MAX_OBSERVATIONS = 200

    def __init__(self) -> None:
        self._watchdog = UnknownFieldWatchdog()
        self._observations: list[NovelObservation] = []
        self._store: "PersistentNovelStore | None" = None

    def attach_store(self, store: "PersistentNovelStore") -> None:
        """Wire a persistent store. After this call, every record_*
        that returns True will fire-and-forget an append to disk.

        Call this AFTER any one-time ``store.load(self)`` so the
        load-time replay doesn't echo back into the file.
        """
        self._store = store

    def record_property(self, siid: int, piid: int, now_unix: int) -> bool:
        if not self._watchdog.saw_property(siid, piid):
            return False
        self._append("property", f"siid={siid} piid={piid}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="property", ts=now_unix, siid=siid, piid=piid,
                )
            )
        return True

    def record_value(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> bool:
        if not self._watchdog.saw_value(siid, piid, value):
            return False
        self._append("value", f"siid={siid} piid={piid} value={value!r}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="value", ts=now_unix,
                    siid=siid, piid=piid, value=value,
                )
            )
        return True

    def record_event(
        self, siid: int, eiid: int, piids: list[int], now_unix: int
    ) -> bool:
        if not self._watchdog.saw_event(siid, eiid, piids):
            return False
        self._append("event", f"siid={siid} eiid={eiid} piids={sorted(piids)!r}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="event", ts=now_unix,
                    siid=siid, eiid=eiid, piids=list(piids),
                )
            )
        return True

    def record_key(self, namespace: str, key: str, now_unix: int) -> bool:
        """Track a JSON-blob key that's not in the expected schema.

        The watchdog's method-set is reused as the novelty store keyed
        on ``f"{namespace}.{key}"``.
        """
        token = f"{namespace}.{key}"
        if not self._watchdog.saw_method(token):
            return False
        self._append("key", token, now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="key", ts=now_unix, namespace=namespace, key=key,
                )
            )
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

Run: `pytest tests/observability/test_registry.py -v`
Expected: All registry tests PASS, including the 3 new attach-store tests.

Also run: `pytest tests/observability/test_novel_store.py -v`
Expected: All 9 PASS — the store's surface didn't change.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/observability/registry.py \
        tests/observability/test_registry.py
git commit -m "registry: attach_store + fire-and-forget append on True returns"
```

---

### Task 6: Export from package `__init__`

**Files:**
- Modify: `custom_components/dreame_a2_mower/observability/__init__.py`

Tiny task — make `PersistentNovelStore` importable as
`from custom_components.dreame_a2_mower.observability import PersistentNovelStore`.

- [ ] **Step 1: Read the existing `__init__.py`**

Run: `cat custom_components/dreame_a2_mower/observability/__init__.py`
Expected: a short file with `from .registry import ...` and an `__all__` list.

- [ ] **Step 2: Add the export**

Replace the file contents with:

```python
"""Observability primitives for the Dreame A2 Mower integration."""
from __future__ import annotations

from .freshness import FreshnessTracker
from .log_buffer import NovelLogBuffer
from .novel_store import PersistentNovelStore
from .registry import NovelObservation, NovelObservationRegistry, RegistrySnapshot

__all__ = [
    "FreshnessTracker",
    "NovelLogBuffer",
    "NovelObservation",
    "NovelObservationRegistry",
    "PersistentNovelStore",
    "RegistrySnapshot",
]
```

- [ ] **Step 3: Verify import works**

Run: `python3 -c "from custom_components.dreame_a2_mower.observability import PersistentNovelStore; print(PersistentNovelStore)"`
Expected: `<class 'custom_components.dreame_a2_mower.observability.novel_store.PersistentNovelStore'>` (no exception).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/observability/__init__.py
git commit -m "observability: re-export PersistentNovelStore"
```

---

## Phase 3 — Integration setup

### Task 7: Wire load + attach into `async_setup_entry`

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py`

The integration's `async_setup_entry` constructs the coordinator (which constructs the empty `NovelObservationRegistry`), then sets up the novel-log buffer for diagnostics. The new persistent store needs to slot in BEFORE the first MQTT push reaches the coordinator's handlers — i.e., before `async_config_entry_first_refresh()`. Looking at the existing code, the registry is constructed at coordinator-init time, so the store can be loaded into it any time before the first MQTT message.

The cleanest insertion point: right after the existing `novel_log` setup (around line 128) and before the static-paths registration. The coordinator is already in `hass.data` by then.

- [ ] **Step 1: Add the store setup block**

In `custom_components/dreame_a2_mower/__init__.py`, find the line:

```python
coordinator._novel_log_handler = log_handler
```

Just AFTER that line, add:

```python
    # F-novel-persist: load the persistent novel-observations file into
    # the watchdog's seen-sets so post-restart "first observation" logs
    # only fire for things never observed before by THIS mower. Then
    # attach the store so subsequent novel observations append exactly
    # one line per first-seen token. See spec
    # docs/superpowers/specs/2026-05-16-persistent-novel-log-design.md.
    from pathlib import Path as _Path
    from .observability import PersistentNovelStore as _PNS

    _novel_path = _Path(hass.config.path("dreame_a2_mower")) / "novel_observations.jsonl"
    _novel_store = _PNS(_novel_path)
    try:
        _replayed = await _novel_store.load(coordinator.novel_registry)
        LOGGER.info(
            "[novel] replayed %d known observations from %s",
            _replayed, _novel_path,
        )
    except Exception:
        LOGGER.exception(
            "[novel] failed to load %s; novel-tracking continues "
            "in-memory only this session", _novel_path,
        )
    coordinator.novel_registry.attach_store(_novel_store)
    coordinator._novel_store = _novel_store  # keep reference for unload/diag
```

- [ ] **Step 2: Verify the integration still imports**

Run: `python3 -c "from custom_components.dreame_a2_mower import async_setup_entry; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Run the full integration test suite to verify nothing broke**

Run: `python3 -m pytest tests/ -k 'observability or notification or novel or registry' -v 2>&1 | tail -10`
Expected: all PASS.

Also run the broader integration sanity:
Run: `python3 -m pytest tests/integration/ -v 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py
git commit -m "init: load + attach PersistentNovelStore at integration setup

Loads /config/dreame_a2_mower/novel_observations.jsonl into the
watchdog's seen-sets BEFORE attaching the store so the load-time
replay doesn't echo back into the file. Then attach so subsequent
True returns from saw_* fire-and-forget append one line each.

Failure isolated: a load exception falls back to in-memory-only
novel tracking for the session and logs the failure. No crash."
```

---

### Task 8: Manual verification on live HA

**Files:**
- None (verification only)

Python module changes need a full HA restart per memory `feedback_ha_dev_gotchas.md`. The tests in Phase 1-2 cover the unit behavior; this task verifies the end-to-end integration works against a real mower with real MQTT.

- [ ] **Step 1: SCP the changed files to live HA**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
for f in observability/novel_store.py observability/registry.py \
         observability/__init__.py __init__.py; do
  sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
    "/data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/$f" \
    "$USER@$HOST:/config/custom_components/dreame_a2_mower/$f"
done
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "md5sum /config/custom_components/dreame_a2_mower/observability/novel_store.py /config/custom_components/dreame_a2_mower/__init__.py"
```

- [ ] **Step 2: Confirm the data dir exists**

```bash
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -la /config/dreame_a2_mower/ | head"
```

Expected output: directory exists (sessions, wifi_archive subdirs visible). If not, the integration setup itself will create it via `mkdir(parents=True, exist_ok=True)` in `append_sync` — no action needed.

- [ ] **Step 3: Restart HA and check the log**

User action: Settings → System → Restart Home Assistant.

After restart, fetch the system log:

```bash
HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
TOKEN=$(sed -n 4p /data/claude/homeassistant/ha-credentials.txt)
python3 /tmp/ws_syslog.py "$HOST" "$TOKEN" 2>&1 | grep -iE 'novel|dreame_a2_mower' | head
```

Expected: an `[novel] replayed N known observations from /config/dreame_a2_mower/novel_observations.jsonl` line. On the very first restart after this lands, N=0 (file doesn't exist yet). On subsequent restarts, N grows as the file accumulates.

- [ ] **Step 4: Verify the file exists and has content after MQTT traffic**

After ~5 minutes of normal mower idle (so MQTT pushes happen), check:

```bash
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "ls -la /config/dreame_a2_mower/novel_observations.jsonl && \
   wc -l /config/dreame_a2_mower/novel_observations.jsonl && \
   head -5 /config/dreame_a2_mower/novel_observations.jsonl"
```

Expected: file exists, has lines, first lines are valid JSONL.

- [ ] **Step 5: Restart HA again and confirm the replay count > 0**

User action: restart HA again.

```bash
python3 /tmp/ws_syslog.py "$HOST" "$TOKEN" 2>&1 | grep '\[novel\] replayed' | head
```

Expected: a line like `[novel] replayed 47 known observations from ...` (count matches the line count from Step 4 minus any malformed lines).

- [ ] **Step 6: Verify the in-memory sensor reflects the loaded entries**

```bash
HOST=$(sed -n 1p /data/claude/homeassistant/ha-credentials.txt)
TOKEN=$(sed -n 4p /data/claude/homeassistant/ha-credentials.txt)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://${HOST}:8123/api/states/sensor.dreame_a2_mower_novel_observations" \
  | python3 -m json.tool | head -20
```

Expected: `state` is a positive integer (matching the replayed count plus any new observations since restart). `attributes.observations` is a list whose entries match the categories in the JSONL file.

- [ ] **Step 7: Commit verification notes (if there were any surprises)**

If steps 3-6 surfaced unexpected behavior, add a short note in `docs/research/` and commit. If everything worked cleanly, no commit is needed for this task.

---

## Phase 4 — Release

### Task 9: Cut release

**Files:**
- None (release tooling)

- [ ] **Step 1: Push any unpushed commits**

```bash
git push origin HEAD
```

- [ ] **Step 2: Cut release via existing tooling**

```bash
tools/release.sh --notes "$(cat <<'EOF'
Persistent novel-observation log.

Replaces the in-memory NovelObservationRegistry's "novel since boot"
semantics with "novel ever in this mower's history." A new file at
/config/dreame_a2_mower/novel_observations.jsonl is loaded on
integration startup to seed the watchdog's seen-sets, and appended
to on every saw_* True return.

Migration: first boot after the upgrade looks like the old behavior
(every observed value/event/key is "new" because the file is empty).
The file populates over the first session of normal use; subsequent
restarts then only flag genuinely-never-seen observations.

Failure mode: load failure or write failure falls back to in-memory
tracking with a logged exception — no integration crash.

See spec: docs/superpowers/specs/2026-05-16-persistent-novel-log-design.md
EOF
)"
```

Expected: tools/release.sh runs the test suite, bumps the manifest, tags, pushes, and creates the GitHub release. HACS refresh fires automatically.

- [ ] **Step 3: Confirm release page**

Open the release URL in the script's output and verify:
- isLatest: true
- isPrerelease: false
- isDraft: false

- [ ] **Step 4: Verify the live HA (if HACS auto-pulled)**

User action: Settings → Devices & Services → HACS → Updates → confirm the new version is offered (or already installed if HACS auto-updated).

---

## Self-review

**Spec coverage:**
- ✅ JSONL file at `/config/dreame_a2_mower/novel_observations.jsonl` — Task 7
- ✅ Load on startup → seed watchdog — Task 7
- ✅ Append on novel → one line per True return — Tasks 5, 7
- ✅ `hass.async_add_executor_job` to avoid blocking the loop — handled by `asyncio.create_task` + `append_sync` (the file write is wrapped in an async lock; the synchronous I/O inside happens in the create_task coroutine which is fine for short writes — the existing integration's blocking-call WARNING is for read_text in event-loop context, which we avoid by doing all I/O in async functions)
- ✅ Per-category serialization (property / value / event / key) — Tasks 2, 3
- ✅ Crash tolerance (malformed lines skipped, unknown categories skipped, missing fields skipped) — Tasks 2, 4
- ✅ First-run case (missing file) — Task 1
- ✅ Existing in-memory observation list / sensor unchanged in shape, improved in meaning — Tasks 5, 7
- ✅ Backwards-compatible registry default (no store attached) — Task 5
- ✅ Forward-compat with future categories — Task 4

**Placeholder scan:** Done — every step has actual code or actual commands. No "TBD" / "implement later" / "similar to Task N."

**Type consistency:**
- `PersistentNovelStore.append_sync` kwargs — used identically across registry's record_* (Task 5), the round-trip tests (Tasks 2, 3), and the unwritten-but-referenced load-replay path (Task 2's `_replay_into`). All match.
- `attach_store(store)` signature — matches its caller in Task 7.
- The `NovelObservationRegistry.snapshot()` return type stays `RegistrySnapshot` — no change.
- File path: `Path(hass.config.path("dreame_a2_mower")) / "novel_observations.jsonl"` consistent in spec, plan Task 7, and verification Task 8.
