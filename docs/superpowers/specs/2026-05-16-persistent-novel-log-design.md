# Persistent Novel Log — Design

**Date:** 2026-05-16
**Status:** Draft (pending user review)

## Problem

The integration's `NovelObservationRegistry` (and underlying
`UnknownFieldWatchdog`) tracks first-observations of unexpected
MQTT/API fields. Today this state is in-memory only — every HA
restart wipes the "have I seen this?" sets.

Two consequences:

1. **Reboots flag known things as novel.** Every restart, the
   first observation of every slot's first value re-fires the
   `[NOVEL/value]` log line. The sensor list fills with same-as-
   yesterday entries. Genuine first-observations get drowned out.

2. **Rare events get lost.** A truly novel value that fires once
   between reboots (e.g., `s6p1=201` first observed 2026-05-15
   12:18) gets logged once, then erased by the next restart.
   Users investigating "what fired this notification?" have only
   the (large, slow-to-grep) probe-log corpus to fall back on.

Per the existing TODO in `project_persistent_novel_log_todo.md`
and the user's "we want users to mail back findings" framing, the
log needs to be a curated record of genuine firsts — not a
since-boot dump.

## Non-goals

- General-purpose persistence framework. This is a single
  registry with a single storage backend.
- Cross-mower / cross-installation aggregation. Each mower's
  catalog is local to its `/config/dreame_a2_mower/` directory.
- Pruning by age or quota. The existing watchdog caps
  (`MAX_VALUES_PER_PROP = 32` per slot, similar caps on event
  PIIDs and method names) bound the total catalog size at a
  knowable maximum (≈ a few thousand lines on a fully-decoded
  mower). Pruning logic is YAGNI.

## Architecture

```
┌────────────────────────────────────────────────────┐
│ MQTT/API observation → record_value(siid, piid, v)│
│                                                    │
│ NovelObservationRegistry                           │
│  ├─ UnknownFieldWatchdog (in-memory _seen_* sets) │
│  └─ append-on-True → PersistentNovelStore          │
│                                                    │
│ PersistentNovelStore                               │
│  ├─ append(observation) → asyncio executor → fsync│
│  └─ load() → walk file, replay into watchdog      │
└────────────────────────────────────────────────────┘
        │
        ▼
/config/dreame_a2_mower/novel_observations.jsonl
  one JSON object per line, append-only
```

The watchdog and registry stay almost as-is — just one new
collaborator (`PersistentNovelStore`) and one new lifecycle hook
(load on integration setup).

## Storage format

`/config/dreame_a2_mower/novel_observations.jsonl` — newline-
terminated JSON, one observation per line.

Per category, the line shape is:

```jsonl
{"ts": 1747358400, "category": "property", "siid": 6, "piid": 1}
{"ts": 1747358401, "category": "value", "siid": 6, "piid": 1, "value": 201}
{"ts": 1747358402, "category": "event", "siid": 4, "eiid": 1, "piids": [1, 8, 14]}
{"ts": 1747358403, "category": "key", "namespace": "session_summary", "key": "obs"}
```

Why JSONL:

- Append-only writes are atomic at the OS level for typical line
  sizes (< 4 KB write is atomic on Linux ext4). No `os.replace`
  dance needed.
- Crash-tolerance: a partial last line from a power loss is
  caught at JSON-decode time on next load and skipped with a
  warning, not a hard failure.
- Grep-friendly for users mailing back findings ("look for any
  line containing `siid=2 piid=2 value=`").
- Trivial to roll up: `wc -l` shows the catalog size, `cut`
  builds quick distributions.

## Components

### `PersistentNovelStore` (new — `observability/novel_store.py`)

```python
class PersistentNovelStore:
    """Append-only JSONL persistence for novel observations.

    Owns the file lifecycle (load on init, append on each True
    return from the registry's record_*). Does NOT own the watchdog
    state — that stays in NovelObservationRegistry.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()  # serialise concurrent appends

    async def load(self, registry: NovelObservationRegistry) -> int:
        """Walk the JSONL file, replay each line into registry's
        watchdog. Returns the count of replayed entries. Tolerates
        missing file (first-run case) and corrupted lines.
        """

    async def append(self, observation: NovelObservation, hass) -> None:
        """Append one line. Wrapped in hass.async_add_executor_job
        to avoid the blocking-call detector."""
```

### `NovelObservationRegistry` (existing — minor extension)

Adds an optional `_store: PersistentNovelStore | None` collaborator
and a flag for whether to persist. When present, the existing
`record_*` methods grow a single line:

```python
def record_value(self, siid, piid, value, now_unix) -> bool:
    if not self._watchdog.saw_value(siid, piid, value):
        return False
    obs = NovelObservation(...)
    self._observations.append(obs)  # in-memory list (existing)
    if self._store is not None:
        # fire-and-forget; the store handles its own lock
        asyncio.create_task(self._store.append(obs, self._hass))
    return True
```

The store and the in-memory list both grow together. The store is
the durable record; the in-memory list is the dashboard's window
into it.

### `__init__.py` integration setup

In `async_setup_entry`, after the coordinator is constructed but
before the first MQTT connection:

```python
store = PersistentNovelStore(
    Path(hass.config.path("dreame_a2_mower")) / "novel_observations.jsonl"
)
loaded = await store.load(coordinator.novel_registry)
LOGGER.info("[novel] replayed %d known observations from disk", loaded)
coordinator.novel_registry.attach_store(store, hass)
```

The `attach_store` step happens AFTER `load` so the load itself
doesn't echo back into the file (the load uses the watchdog's
`saw_*` to dedupe; if the loaded value was already in the file
from an earlier session, `saw_*` returns False and we don't
re-append).

### Sensor + diagnostics (existing — no change)

The existing `sensor.dreame_a2_mower_novel_observations` keeps
showing the in-memory `_observations` list. Its semantics shift
from "novel since boot" to "novel ever (across this mower's
history, capped at 200 most-recent)" — a strict improvement. No
config or attribute changes needed; consumers see better data.

## Lifecycle

```
HA boot
  ↓
async_setup_entry runs
  ↓
construct coordinator (with empty NovelObservationRegistry)
  ↓
construct PersistentNovelStore(path)
  ↓
await store.load(registry)
  └─ for each line in file: registry.record_*(...) which
     populates the watchdog's _seen_* sets via saw_*. Each
     load-time record_* returns True (first time the watchdog
     sees the entry this process), populates the in-memory
     observations list, and (because store isn't attached yet)
     does NOT re-append to disk.
  ↓
registry.attach_store(store, hass)
  ↓
... normal operation: every record_* that returns True
    asynchronously appends one line to the file ...
```

## Concurrency / blocking-call protection

- File I/O wrapped in `hass.async_add_executor_job(_sync_append, ...)`
  so the event loop isn't blocked. Memory note
  `feedback_ha_dev_gotchas.md` flagged the integration for an
  existing `read_text` blocking-call WARNING — this design avoids
  adding another.
- An asyncio.Lock inside `PersistentNovelStore` serialises
  concurrent appends so partial-line interleaving is impossible
  even if multiple `saw_*` returns True in the same tick.
- Append uses Python's text-mode file with `os.O_APPEND`
  semantics on Unix (atomic per-line for ≤ PIPE_BUF size, ~4 KB
  on Linux). Each observation line is well under 4 KB.

## Error handling

- **Missing file at startup**: treated as a first-run case;
  load returns 0; integration proceeds normally.
- **Malformed JSON line**: caught with `json.JSONDecodeError`,
  the line is skipped with a `LOGGER.warning(...)`, and load
  continues. The file is not rewritten — assumes the user can
  spot-fix manually if the malformed line matters.
- **File unwritable** (permissions, full disk): the first
  failed append logs `LOGGER.exception(...)` and the store
  silently falls back to in-memory mode for the rest of the
  session. Coordinator continues.

## Testing

- `tests/observability/test_novel_store.py` (new):
  - Empty file → load returns 0
  - Round-trip: append 5 distinct observations, reload → all 5
    populate the watchdog so a re-record returns False
  - Malformed last line: load succeeds, returns N-1 entries
  - Per-category coverage: property / value / event / key all
    serialise and reload identically

- `tests/observability/test_novel_registry_with_store.py` (new):
  - Registry without store: behaves as today
  - Registry with store: every True return triggers exactly one
    append; False returns trigger zero appends
  - Loaded entries don't re-append on first observation
    (post-load record_* sees the value as already-known)

- Integration smoke test (manual): boot HA twice; first boot
  shows N novel entries appended; second boot shows zero novel
  entries despite the same MQTT traffic.

## Migration

- **Existing installs**: file doesn't exist on first boot after
  upgrade. The first observation of every value, property,
  event, and key in the user's MQTT/API traffic gets appended
  as "novel." This is one-time noise (a few hundred lines over
  the first day or two of use) — after that, the file
  represents the user's universe of known things and only
  genuinely-new observations are flagged.
- The existing in-memory sensor will look like the current
  behavior on the first boot post-upgrade (lots of "novel"
  battery percentages etc.) but quiet down within a session.
- No retroactive seeding from the historical probe corpus —
  considered as an option but rejected: the probe corpus isn't
  part of the integration's own state, and the seeding cost is
  one mowing session.

## Risks

1. **File grows unbounded if the integration's caps fail**.
   Mitigation: the watchdog has explicit per-slot caps
   (`MAX_VALUES_PER_PROP = 32`, etc.). The file size stays
   bounded by `max_slots * max_values_per_slot * line_length` ≈
   a few hundred KB worst case. Acceptable.

2. **Concurrent HA instances writing the same file**. Not
   currently possible (HA is single-process per instance) but
   if it became possible (e.g., HA migration), append mode would
   produce interleaved-line garbage. Out of scope; would need
   file locking via `fcntl` if it became a concern.

3. **Disk pressure**. The file is a single JSONL on the same
   filesystem as `/config/`. If `/config/` runs out of space,
   appends fail (graceful degradation per error-handling above).
   Same risk as the integration's existing session/wifi archives;
   no new mitigation needed.

## Out of scope

- A frontend service / button to clear or rotate the file. Users
  can `mv` the file manually if they want a fresh catalog.
- A diagnostics-download integration (the existing diagnostics
  flow already includes the in-memory observation list; the
  on-disk file is reachable via SSH / Samba).
- Encryption at rest. The file contains MQTT slot identifiers
  and values, no credentials.

## Acceptance criteria

- After two restarts of HA with the same MQTT traffic, the
  novel-observations sensor shows zero new entries on the
  second boot (assuming no genuinely-new observations occurred
  between).
- A new value (e.g., manually-injected `s6p1=999` via a probe
  tool) appears as a new line in `novel_observations.jsonl`
  within ~1 second of observation.
- Deleting `novel_observations.jsonl` and rebooting causes
  the file to repopulate with the user's universe of known
  values within one mowing session, after which the steady-
  state behavior resumes.
- A malformed line in the file does not prevent the integration
  from starting; the line is skipped with a warning.
