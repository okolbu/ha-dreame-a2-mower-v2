# B2a Domain/Protocol Refactors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six behavior-preserving domain/protocol refactors — shrink three long functions, delete a dead module, make protocol decoder naming consistent, and split the schedule module into decode/encode.

**Architecture:** Pure structural/behavior-preserving changes. Each item is independent. The existing per-area test suites are the characterization safety net; full suite (`python -m pytest tests -q`, baseline **1602 passed / 4 skipped**) must stay green at every commit.

**Tech Stack:** Python 3, Home Assistant custom integration, pytest. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-20-b2a-domain-protocol-design.md`

**Context:** On branch `main` (HEAD `dd53f0f`). Commit each task on `main` with the `audit-b2a:` prefix, authored as the user, no co-author trailer. Do NOT push (user ships after). Tasks are ordered safest-first.

---

## File Structure

| File | Change |
|---|---|
| `protocol/pose.py` | **delete** (T1) |
| `tests/protocol/test_pose.py` | **delete** (T1) |
| `protocol/pcd.py` | rename `parse_pcd`→`decode_pcd`, `parse_pcd_header`→`decode_pcd_header` (T2) |
| `camera.py` | update 2 pcd import+call sites (T2) |
| `tests/protocol/test_pcd.py`, `tests/protocol/test_pcd_render.py` | update pcd names (T2) |
| `inventory.yaml` | update prose mention of `parse_pcd_header` (T2) |
| `CLAUDE.md` | add "Protocol decoder naming" note (T2) |
| `protocol/schedule_decode.py`, `protocol/schedule_encode.py` | **create** (T3) |
| `protocol/schedule.py` | reduce to re-export shim (T3) |
| `protocol/config_s2p51.py` | `_decode_list_payload` → `{length: handler}` dispatch (T4) |
| `archive/session.py` | extract `_assess_local_completeness` + `_commit_to_index` (T5) |
| `map_decoder.py` | `parse_cloud_map` → orchestrator + per-section helpers (T6) |

---

### Task 1: Delete dead `protocol/pose.py` (item #4)

**Files:**
- Delete: `custom_components/dreame_a2_mower/protocol/pose.py`
- Delete: `tests/protocol/test_pose.py`

- [ ] **Step 1: Confirm zero runtime importers**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -rn "protocol.pose\|from .pose import\|from ..pose import\|import pose\b" custom_components/ tests/
```
Expected: only `tests/protocol/test_pose.py` references it. If `protocol/__init__.py` re-exports a pose symbol, note it for Step 3.

- [ ] **Step 2: Delete both files**

```bash
git rm custom_components/dreame_a2_mower/protocol/pose.py tests/protocol/test_pose.py
```

- [ ] **Step 3: Remove any stale re-export**

```bash
grep -n "pose" custom_components/dreame_a2_mower/protocol/__init__.py
```
If a `pose` import/re-export line exists, delete it. If not, no change.

- [ ] **Step 4: Verify**

```bash
grep -rn "\bpose\b" custom_components/dreame_a2_mower/protocol/__init__.py || echo "no pose in __init__ (good)"
python -m pytest tests -q
```
Expected: 1601 passed, 4 skipped (one fewer than baseline — `test_pose.py` removed).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b2a: delete dead protocol/pose.py (telemetry has the live inline _decode_pose)"
```

---

### Task 2: Protocol decoder naming — `parse_pcd*` → `decode_pcd*` (item #5)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/pcd.py`
- Modify: `custom_components/dreame_a2_mower/camera.py`
- Modify: `tests/protocol/test_pcd.py`, `tests/protocol/test_pcd_render.py`
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (prose)
- Modify: `custom_components/dreame_a2_mower/CLAUDE.md`

- [ ] **Step 1: Rename the two functions in `pcd.py`**

In `protocol/pcd.py`: rename `def parse_pcd_header(` → `def decode_pcd_header(` and `def parse_pcd(` → `def decode_pcd(`. Update the internal call (`parse_pcd` calls `parse_pcd_header` at L113 → `decode_pcd_header`).

```bash
sed -i 's/\bparse_pcd_header\b/decode_pcd_header/g; s/\bparse_pcd\b/decode_pcd/g' custom_components/dreame_a2_mower/protocol/pcd.py
```

- [ ] **Step 2: Update all call sites**

```bash
sed -i 's/\bparse_pcd_header\b/decode_pcd_header/g; s/\bparse_pcd\b/decode_pcd/g' \
  custom_components/dreame_a2_mower/camera.py \
  tests/protocol/test_pcd.py \
  tests/protocol/test_pcd_render.py \
  custom_components/dreame_a2_mower/inventory.yaml
```
(`camera.py` has the import + call at ~L349/366/439/469; the test files import + call; `inventory.yaml` has one prose mention. The `\b` word boundary keeps `decode_pcd_header` from being doubly-rewritten.)

- [ ] **Step 3: Verify no stale names remain**

```bash
grep -rn "\bparse_pcd\b\|\bparse_pcd_header\b" custom_components/ tests/ || echo "no stale parse_pcd* names (good)"
grep -rn "\bdecode_pcd\b\|\bdecode_pcd_header\b" custom_components/dreame_a2_mower/protocol/pcd.py
```
Expected: first prints the "good" line; second shows the two renamed defs.

- [ ] **Step 4: Add the naming-convention note to CLAUDE.md**

Append a section to `custom_components/dreame_a2_mower/CLAUDE.md` (after an existing `---` divider):

```markdown
## Protocol decoder naming (convention)

In `protocol/`, decoder entry points follow a name convention:

- `decode_*` — decodes a **binary** frame/blob (bytes → dataclass). Examples:
  `decode_s1p1`, `decode_s1p4`, `decode_s2p51`, `decode_pcd`, `decode_pcd_header`.
- `parse_*` — decodes **JSON / batch** structures (dict/str → dataclass).
  Examples: `parse_session_summary`, `parse_schedule_batch`, `parse_settings_batch`.

When adding a new decoder, pick the prefix by input type. (PCD was renamed
from `parse_pcd*` to `decode_pcd*` in B2a to fit this rule.)
```

- [ ] **Step 5: Verify + commit**

```bash
python -m pytest tests/protocol/test_pcd.py tests/protocol/test_pcd_render.py -q
python -m pytest tests -q
```
Expected: pcd tests pass; full suite 1601 passed, 4 skipped (unchanged from Task 1).

```bash
git add -A
git commit -m "audit-b2a: rename parse_pcd*/parse_pcd_header to decode_pcd* + document decoder naming"
```

---

### Task 3: Split `protocol/schedule.py` into decode/encode (item #6)

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/schedule_decode.py`
- Create: `custom_components/dreame_a2_mower/protocol/schedule_encode.py`
- Modify: `custom_components/dreame_a2_mower/protocol/schedule.py` (→ re-export shim)

- [ ] **Step 1: Read `schedule.py`'s module imports and the 5 functions**

`schedule.py` defines: `_decode_one_record` (L73), `_decode_blob` (L109), `parse_schedule_batch` (L250) [decode]; `encode_schedule_blob` (L165), `build_schedule_set_value` (L223) [encode]. Note its top-of-file imports (e.g. `SchedulePlan`/`ScheduleData` from `..cloud_state`, stdlib like `base64`/`struct`, etc.) — you'll copy the ones each new module needs.

- [ ] **Step 2: Create `schedule_decode.py`**

Move `_decode_one_record`, `_decode_blob`, `parse_schedule_batch` VERBATIM into a new `protocol/schedule_decode.py`. Start it with `from __future__ import annotations` and exactly the imports those three functions reference (copy from `schedule.py`'s import block; include `_LOGGER`/`logging` if they log, the `SchedulePlan`/`ScheduleData` imports, and any stdlib). After moving, `grep` each candidate import name in the new file to confirm it's used.

- [ ] **Step 3: Create `schedule_encode.py`**

Move `encode_schedule_blob`, `build_schedule_set_value` VERBATIM into a new `protocol/schedule_encode.py`, with `from __future__ import annotations` and the imports those two functions reference.

- [ ] **Step 4: Reduce `schedule.py` to a re-export shim**

Replace `schedule.py`'s body with:

```python
"""Schedule wire format — re-export shim (B2a split into decode/encode).

Decode lives in schedule_decode.py, encode in schedule_encode.py. This shim
preserves the `protocol.schedule` import path for existing callers
(coordinator/_writes.py, cloud_client/_fetchers.py, tests).
"""
from __future__ import annotations

from .schedule_decode import (
    _decode_blob,
    _decode_one_record,
    parse_schedule_batch,
)
from .schedule_encode import (
    build_schedule_set_value,
    encode_schedule_blob,
)

__all__ = [
    "_decode_blob",
    "_decode_one_record",
    "parse_schedule_batch",
    "build_schedule_set_value",
    "encode_schedule_blob",
]
```
(If `test_schedule.py` imports any symbol not in this list, add it to both the import and `__all__`.)

- [ ] **Step 5: Verify**

```bash
python -c "import ast; [ast.parse(open(f).read()) for f in ('custom_components/dreame_a2_mower/protocol/schedule.py','custom_components/dreame_a2_mower/protocol/schedule_decode.py','custom_components/dreame_a2_mower/protocol/schedule_encode.py')]; print('parse ok')"
python -m pytest tests/protocol/test_schedule.py -q
python -m pytest tests -q
```
Expected: parse ok; schedule tests pass; full suite 1601 passed, 4 skipped. The 3 importers (`coordinator/_writes.py`, `cloud_client/_fetchers.py`, `tests/protocol/test_schedule.py`) resolve unchanged through the shim.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "audit-b2a: split protocol/schedule.py into schedule_decode + schedule_encode (re-export shim)"
```

---

### Task 4: `config_s2p51._decode_list_payload` → length dispatch (item #2)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/config_s2p51.py`
- Test: `tests/protocol/test_config_s2p51.py`

- [ ] **Step 1: Confirm characterization coverage**

```bash
grep -nE "len|n ?== ?[0-9]|RAIN_PROTECTION|ANTI_THEFT|LOW_SPEED_NIGHT|CONSUMABLES|AMBIGUOUS_4LIST|CHARGING|LED_PERIOD|HUMAN_PRESENCE" tests/protocol/test_config_s2p51.py
```
The dispatch handles lengths `2,3,4,6,8,9`. Confirm the test file already exercises each length (incl. the `n==3` Low-Speed-vs-Anti-Theft `any(v>1)` split and the `n==4` Consumables-vs-Ambiguous split). For any length-case not asserted, add a one-line characterization test asserting `decode_s2p51`/`_decode_list_payload` returns the expected `Setting` for a representative input BEFORE refactoring. Run `python -m pytest tests/protocol/test_config_s2p51.py -q` → green.

- [ ] **Step 2: Extract per-length helpers and a dispatch table**

In `config_s2p51.py`, replace `_decode_list_payload` (currently L127-255) with per-length helper functions plus a dispatch dict. Each `_decode_lenN(value)` contains the VERBATIM body of the corresponding `if n == N:` block (the `return S2P51Event(...)` statement(s), including the `n==3`/`n==4` discrimination logic). Then:

```python
_LIST_DECODERS = {
    2: _decode_len2,
    3: _decode_len3,
    4: _decode_len4,
    6: _decode_len6,
    8: _decode_len8,
    9: _decode_len9,
}


def _decode_list_payload(value: list[int]) -> S2P51Event:
    n = len(value)
    handler = _LIST_DECODERS.get(n)
    if handler is None:
        raise S2P51DecodeError(f"unknown list payload shape (len={n}): {value!r}")
    try:
        return handler(value)
    except (ValueError, TypeError) as e:
        raise S2P51DecodeError(f"malformed list payload {value!r}: {e}") from e
```

The `_decode_lenN` functions must be defined ABOVE `_LIST_DECODERS` (the dict references them). Keep the exact same exception messages and the same unknown-shape `S2P51DecodeError` text so behavior is byte-identical.

- [ ] **Step 3: Verify**

```bash
python -m pytest tests/protocol/test_config_s2p51.py -q
python -m pytest tests -q
```
Expected: config tests pass; full suite 1601 passed, 4 skipped.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b2a: config_s2p51 _decode_list_payload -> {length: handler} dispatch"
```

---

### Task 5: `archive/session.archive()` — extract two steps (item #3)

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py`
- Test: `tests/archive/test_session.py`

- [ ] **Step 1: Confirm characterization coverage**

```bash
grep -nE "def test|archive\(|dedup|incomplete|_local_legs|local_trail_complete|prune" tests/archive/test_session.py
```
Confirm `tests/archive/test_session.py` covers: the `(md5, start_ts)` dedup (re-archiving the same session returns None), the partial-trail flag (`local_trail_complete` False when `_local_legs` is short vs duration), and the incomplete-placeholder prune. For any of these not asserted, add a focused characterization test BEFORE refactoring. Run `python -m pytest tests/archive/test_session.py -q` → green.

- [ ] **Step 2: Extract `_assess_local_completeness`**

Move the partial-trail heuristic block (currently `archive()` L504-540 — the `local_complete = True; if isinstance(raw_json, dict) and "_local_legs" in raw_json: ...` block including its `_LOGGER.warning`) into a new method, keeping logic verbatim:

```python
def _assess_local_completeness(self, raw_json, summary, stem: str) -> bool:
    """Heuristic: is the local-captured trail complete? (verbatim from archive())"""
    local_complete = True
    if isinstance(raw_json, dict) and "_local_legs" in raw_json:
        ...  # the moved block, returning False + warning when short
    return local_complete
```
In `archive()`, replace the block with `local_complete = self._assess_local_completeness(raw_json, summary, stem)`.

- [ ] **Step 3: Extract `_commit_to_index`**

Move the index-mutation tail (currently L547-563 — `self._index.append(entry)`, the `if md5 != "(incomplete)": self._prune_incomplete_for(start_ts)`, `self._save_index()`, `self._enforce_retention()`, `return entry`) into:

```python
def _commit_to_index(self, entry, *, md5: str, start_ts: int):
    """Append a freshly-written archive entry to the index + prune/persist. (verbatim)"""
    self._index.append(entry)
    if md5 != "(incomplete)":
        self._prune_incomplete_for(start_ts)
    self._save_index()
    self._enforce_retention()
    return entry
```
In `archive()`, after building `entry = ArchivedSession.from_summary(...)`, replace the tail with `return self._commit_to_index(entry, md5=md5, start_ts=start_ts)`. The dedup check and file-write stay in `archive()`.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/archive/test_session.py -q
python -m pytest tests -q
```
Expected: archive tests pass; full suite 1601 passed, 4 skipped.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b2a: archive() extract _assess_local_completeness + _commit_to_index"
```

---

### Task 6: `map_decoder.parse_cloud_map` → orchestrator + section helpers (item #1)

This is the largest target (~440 LOC). Extract incrementally — one section at a time, running the suite after each — and commit once at the end.

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_decoder.py`
- Test: `tests/integration/test_map_decoder.py`

- [ ] **Step 1: Confirm characterization coverage**

```bash
python -m pytest tests/integration/test_map_decoder.py -q
grep -nE "def test|boundary|forbidden|notObs|spotAreas|mowingAreas|contours|maintenance|MapData" tests/integration/test_map_decoder.py
```
`parse_cloud_map` builds a `MapData` from a cloud dict in these sections (verified in source): (a) boundary parse + validation; (b) exclusion/ignore/spot zones via the nested `_accumulate` / `_accumulate_spots`; (c) bbox expansion over rotated corners; (d) exclusion-zone midline reflection; (e) mowing zones; (f) contour paths; (g) maintenance/clean points; (h) final `MapData(...)` assembly. Confirm `test_map_decoder.py` exercises a representative full cloud dict covering these. If coverage is thin for a section you're about to extract, add a focused characterization test asserting that section's field on the returned `MapData` BEFORE extracting it.

- [ ] **Step 2: Promote the nested accumulators to module-level helpers**

Convert the nested closures `_accumulate(entries_wrapper, subtype)` and `_accumulate_spots(entries_wrapper)` (which currently mutate local accumulator lists) into module-level functions that RETURN their parsed lists instead of mutating closure state — e.g. `_parse_exclusion_zones(forbidden_raw, ignore_raw, spot_raw) -> tuple[list, list]` (or per-call helpers returning each list). Update `parse_cloud_map` to assign from the returned values. Run `python -m pytest tests/integration/test_map_decoder.py -q` → green.

- [ ] **Step 3: Extract the remaining sections into module-level helpers**

One at a time (suite green after each extraction), extract: boundary parse+validate → `_parse_boundary(cloud_response)`; mowing zones → `_parse_mowing_zones(cloud_response)`; contour paths → `_parse_contours(cloud_response)`; maintenance/clean points → `_parse_maintenance_points(cloud_response)`. Each helper takes the inputs it needs and returns its parsed piece; move the logic VERBATIM (including coordinate transforms / reflections — do not alter any geometry math). Leave bbox-expansion and the final `MapData(...)` assembly inline in `parse_cloud_map` (they tie the pieces together). After all extractions, `parse_cloud_map` should read as: parse boundary → parse zones → expand bbox → reflect → parse mowing/contours/maintenance → assemble `MapData`.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/integration/test_map_decoder.py -q
python -m pytest tests -q
```
Expected: map decoder tests pass; full suite 1601 passed, 4 skipped.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b2a: split map_decoder.parse_cloud_map into per-section helpers"
```

---

### Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite + syntax check**

```bash
python -m pytest tests -q
python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('custom_components/dreame_a2_mower/**/*.py', recursive=True)]; print('all parse OK')"
```
Expected: 1601 passed, 4 skipped (baseline 1602 minus the deleted `test_pose.py`; plus any characterization tests added in T4/T5/T6); all parse OK.

- [ ] **Step 2: Confirm the refactors landed**

```bash
grep -rn "\bparse_pcd\b\|\bparse_pcd_header\b" custom_components/ tests/ || echo "pcd rename clean"
ls custom_components/dreame_a2_mower/protocol/pose.py 2>&1 | tail -1   # should be: No such file
ls custom_components/dreame_a2_mower/protocol/schedule_decode.py custom_components/dreame_a2_mower/protocol/schedule_encode.py
grep -n "_LIST_DECODERS" custom_components/dreame_a2_mower/protocol/config_s2p51.py
grep -n "_commit_to_index\|_assess_local_completeness" custom_components/dreame_a2_mower/archive/session.py
```

- [ ] **Step 3: Report for user ship decision** (no push — user runs push + release.sh).

---

## Self-Review

**Spec coverage:**
- #1 map_decoder split → T6. ✓
- #2 config_s2p51 dispatch → T4. ✓
- #3 archive index/completeness extraction → T5. ✓
- #4 delete pose → T1. ✓
- #5 pcd rename + CLAUDE.md note → T2. ✓
- #6 schedule split → T3. ✓
- #7 state_machine → out of scope (B2b), not in any task. ✓

**Placeholder scan:** No TBD/TODO. Function-split tasks (#1/#2/#3) specify the exact helper names/signatures + the verbatim-move instruction + the existing test file as the characterization gate + a concrete "add a test for any uncovered branch first" step. Mechanical tasks (#4/#5/#6) give exact commands.

**Type/name consistency:** New names are consistent across tasks — `decode_pcd`/`decode_pcd_header` (T2); `schedule_decode.py`/`schedule_encode.py` + shim (T3); `_LIST_DECODERS` + `_decode_lenN` (T4); `_assess_local_completeness`/`_commit_to_index` (T5); `_parse_boundary`/`_parse_exclusion_zones`/`_parse_mowing_zones`/`_parse_contours`/`_parse_maintenance_points` (T6). Test totals: baseline 1602 → 1601 after T1 (pose test deleted); T4/T5/T6 may add characterization tests (count rises accordingly) — the "1601" expectations are the floor.
