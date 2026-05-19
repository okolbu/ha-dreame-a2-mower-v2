# B1c — `_cached_maps_by_id` Shadow Removal + Redundant Refresher Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `_cached_maps_by_id` shadow attribute (the last pre-CloudState residue) by routing 60 readers to `self.cloud_state.maps_by_id`, replacing the one in-place mutation with `dataclasses.replace`, deleting the 4 writer/init sites, and cleaning 6 stale doc-mentions. Also delete `_refresh_cfg` and `_refresh_mihis` — redundant 10-min refreshers covered by the 2-min `_refresh_cloud_state`.

**Architecture:** Six sequential tasks, low-risk first. Readers route first (entity platforms then coordinator submodules) so the shadow attribute becomes write-only and harmless. Then the mutation gets rewritten using the frozen CloudState's `dataclasses.replace` pattern. Then the now-unused writers + init disappear. Then the redundant refreshers go. Final verification + push.

**Tech Stack:** Python, `dataclasses.replace` (already imported in `_session.py`), pytest. No new dependencies, no new files.

**Reference docs (do NOT modify):**
- Design: `docs/superpowers/specs/2026-05-19-block1c-shadow-removal-design.md`
- Discovery (inventory): `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 3 + § 5.1
- Parent: `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`

**Output:** 6 commits prefixed `audit-b1c:`. Push to `origin/main` after T6.

**Hard rules:**
- Every task ends with `pytest tests/ -q` green.
- T1–T4 must NOT change any user-visible behaviour. Reads change source attribute; writes change shape; no entity/service surface change.
- T5 is the ONLY task with documented behaviour delta: CFG/MIHIS staleness drops from 10 min worst-case to 2 min worst-case.
- No edits outside the files named in each task.
- Verify line numbers with `grep -n` before each Edit — line numbers in this plan are from the pre-execution snapshot and will drift as commits land.

---

## Task 1: Route 44 entity-platform readers to `coordinator.cloud_state.maps_by_id`

**Files (all modify):**
- `custom_components/dreame_a2_mower/select.py` — 21 sites
- `custom_components/dreame_a2_mower/camera.py` — 11 sites
- `custom_components/dreame_a2_mower/switch.py` — 7 sites
- `custom_components/dreame_a2_mower/sensor.py` — 3 sites
- `custom_components/dreame_a2_mower/number.py` — 2 sites

Pattern in entity files: `coordinator._cached_maps_by_id<suffix>` (e.g. `.keys()`, `.get(map_id)`, `.items()`). Replacement: `coordinator.cloud_state.maps_by_id<same suffix>`.

- [ ] **Step 1: Pre-edit per-file baseline counts**

Capture the count of `_cached_maps_by_id` per file (must match the table above):

```bash
for f in select.py camera.py switch.py sensor.py number.py; do
  echo "$f: $(grep -c _cached_maps_by_id custom_components/dreame_a2_mower/$f)"
done
```

Expected: `select.py: 21`, `camera.py: 11`, `switch.py: 7`, `sensor.py: 3`, `number.py: 2`. If any count differs from this, STOP — files have drifted; re-read discovery § 3.2 reader list.

- [ ] **Step 2: Replace all 5 files**

For each file, use Edit with `replace_all: true`:

```
old_string: coordinator._cached_maps_by_id
new_string: coordinator.cloud_state.maps_by_id
```

After each file's Edit, run `python -m py_compile custom_components/dreame_a2_mower/<file>` to catch immediate syntax issues.

If any file has a reader that uses `self._cached_maps_by_id` (entity classes that hold a coordinator reference under a different name), grep first:
```bash
grep -n "self._cached_maps_by_id\|cached_maps_by_id" custom_components/dreame_a2_mower/<file>
```
If the substring shape differs, handle individually with file-specific Edit. The discovery doc only confirmed the `coordinator._cached_maps_by_id` pattern, but verify before relying on `replace_all`.

- [ ] **Step 3: Verify entity-platform refs are gone**

```bash
for f in select.py camera.py switch.py sensor.py number.py; do
  c=$(grep -c _cached_maps_by_id custom_components/dreame_a2_mower/$f)
  if [ "$c" != "0" ]; then
    echo "LEFTOVER: $f has $c refs"
  fi
done
```
Expected: no `LEFTOVER` output.

Confirm the replacement landed:
```bash
grep -c "coordinator.cloud_state.maps_by_id" custom_components/dreame_a2_mower/select.py
```
Should be 21 (the pre-edit count of the substring).

- [ ] **Step 4: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/switch.py custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/number.py
git commit -m "audit-b1c: route 44 entity-platform readers to cloud_state.maps_by_id"
```

---

## Task 2: Route 16 coordinator-submodule readers to `self.cloud_state.maps_by_id`

**Files (all modify):**
- `coordinator/_session.py` — 7 reads at L281, L285, L289, L294, L298, L435, L436 (NOT the mutation at L325)
- `coordinator/_rendering.py` — 3 reads at L129, L172, L324
- `coordinator/_device_sync.py` — 3 sites at L99, L237, L239
- `coordinator/_lidar_oss.py` — 1 read at L206
- `coordinator/_writes.py` — 1 read at L431
- `coordinator/_cloud_state.py` — 1 read at L304 (CAREFUL: this file also has 3 writes at L112, L244, L316 that we DON'T change here — see Step 4)

Pattern: `self._cached_maps_by_id` → `self.cloud_state.maps_by_id`.

- [ ] **Step 1: Pre-edit baseline counts**

```bash
for f in _session.py _rendering.py _device_sync.py _lidar_oss.py _writes.py; do
  echo "$f: $(grep -c _cached_maps_by_id custom_components/dreame_a2_mower/coordinator/$f)"
done
echo "_cloud_state.py: $(grep -c _cached_maps_by_id custom_components/dreame_a2_mower/coordinator/_cloud_state.py)"
```

Expected:
- `_session.py: 8` (7 reads + 1 mutation)
- `_rendering.py: 4` (3 reads + 1 comment)
- `_device_sync.py: 4` (3 sites + 1 comment)
- `_lidar_oss.py: 1`
- `_writes.py: 1`
- `_cloud_state.py: 8` (1 read + 3 writes + 4 docstring/comment)

If any number differs, STOP.

- [ ] **Step 2: Replace readers in `_session.py`, `_rendering.py`, `_device_sync.py`, `_lidar_oss.py`, `_writes.py`**

These files have only reads (plus comments in some — but the comments will be cleaned up in T4). Safe to use `replace_all` carefully — but `_session.py` has the mutation at L325 that must NOT change in T2.

For `_session.py` specifically: read context for each of the 7 reads. The mutation site is:
```python
self._cached_maps_by_id[active_id] = map_data
```
which is an ASSIGNMENT (LHS is the dict, RHS is the new value). The 7 reads use the attribute on the RHS only (`.get()`, `.keys()`, `.items()`, `if self._cached_maps_by_id:`, subscript read `[fallback_id]`).

The mutation site cannot be transformed by a simple `_cached_maps_by_id` → `cloud_state.maps_by_id` substitution because `self.cloud_state.maps_by_id[active_id] = ...` would try to mutate a frozen dataclass's field — that may or may not raise depending on whether the dict itself is frozen (it's not — `dict` is mutable; only `dataclass(frozen=True)` prevents attribute reassignment). HOWEVER it would mutate the shared dict in place, which IS the bug we want to remove (T3 fixes this with `dataclasses.replace`).

**Safest approach:** Use Edit with `replace_all: false` for each `_session.py` read site individually. Construct `old_string` to include enough context so the mutation line at L325 is NOT matched.

Example: the read at L281 `self._cached_maps_by_id.get(target_map_id)` is uniquely identifiable by its `.get(target_map_id)` suffix — use that whole expression as `old_string`.

For `_rendering.py`, `_device_sync.py`, `_lidar_oss.py`, `_writes.py`: these have ONLY reads + comments. Use `replace_all: true` for the `self._cached_maps_by_id` substring → `self.cloud_state.maps_by_id`. Then individually handle the comment lines in T4. (The `replace_all` won't touch comments that contain `_cached_maps_by_id` as a bareword, because the substring `self._cached_maps_by_id` requires the `self.` prefix.)

Actually wait — the `_device_sync.py` and `_rendering.py` comments contain bareword `_cached_maps_by_id` (no `self.` prefix), so `replace_all=true` for `self._cached_maps_by_id` is safe to use here. Verify after each Edit:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_rendering.py
```
Should show only comment lines remaining (no `self.` prefix).

- [ ] **Step 3: Replace ONLY the read in `_cloud_state.py`**

The single read is at L304:
```python
prev_map_data = self._cached_maps_by_id.get(map_id)
```

Use Edit with this exact `old_string`:
```python
            prev_map_data = self._cached_maps_by_id.get(map_id)
```
And `new_string`:
```python
            prev_map_data = self.cloud_state.maps_by_id.get(map_id)
```

(Use `replace_all: false` — there's only one match and we don't want to touch the 3 writers at L112, L244, L316.)

- [ ] **Step 4: Verify reader replacements**

```bash
grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_session.py
# Expected: exactly 1 line — the mutation at L325 (will be fixed in T3)

grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_rendering.py
# Expected: no output (all 3 reads routed; comments don't use `self.` prefix)

grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_device_sync.py
# Expected: no output

grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_lidar_oss.py
# Expected: no output

grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_writes.py
# Expected: no output

grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_cloud_state.py
# Expected: 3 lines — the writes at L112, L244, L316 (will be deleted in T4)
```

Run: `python -m py_compile $(find custom_components/dreame_a2_mower/coordinator -name '*.py')`
Expected: clean.

- [ ] **Step 5: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/
git commit -m "audit-b1c: route 16 coordinator-submodule readers to cloud_state.maps_by_id"
```

---

## Task 3: Replace `_session.py` in-place mutation with `dataclasses.replace`

**Files:**
- Modify: `coordinator/_session.py:325` (the line is now ~L325 pre-T3; verify by `grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_session.py`).

The current mutation:
```python
            self._cached_maps_by_id[active_id] = map_data
```

This is the LAST writer of the shadow attribute. After T3 lands, only the 3 bulk-reassign writers in `_cloud_state.py` remain (deleted in T4).

- [ ] **Step 1: Read the context around the mutation**

```bash
grep -n "self\._cached_maps_by_id\[" custom_components/dreame_a2_mower/coordinator/_session.py
```
Expected: one match (the mutation). Note the line number.

Then `sed -n '<LN-5>,<LN+3>p' coordinator/_session.py` to see the surrounding ~8 lines for unique-context Edit.

You should see the preceding line is a comment like:
```python
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            active_id = self._active_map_id if self._active_map_id is not None else 0
```

- [ ] **Step 2: Confirm `dataclasses` is already imported**

```bash
grep -n "^import dataclasses\|^from dataclasses" custom_components/dreame_a2_mower/coordinator/_session.py
```
Expected: one match (`import dataclasses` at L9 per pre-T3 snapshot).

If the import is missing (shouldn't be), STOP and add it before proceeding.

- [ ] **Step 3: Apply the dataclasses.replace transform**

Use Edit:

`old_string`:
```python
            self._cached_maps_by_id[active_id] = map_data
```

`new_string`:
```python
            # Hydrate the active-map slot in the canonical CloudState.
            # CloudState is a frozen dataclass — use dataclasses.replace
            # with a new dict so other code holding the OLD cloud_state
            # reference doesn't see the mutation. Per audit: no such
            # reference holder exists; this is defensive.
            self.cloud_state = dataclasses.replace(
                self.cloud_state,
                maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
            )
```

Indentation: match the surrounding code (12 spaces of leading whitespace given the nesting).

- [ ] **Step 4: Verify no more `_cached_maps_by_id` references in `_session.py`**

```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_session.py
```
Expected: no output (all 8 references gone — 7 routed in T2, 1 just transformed).

Run: `python -m py_compile custom_components/dreame_a2_mower/coordinator/_session.py`
Expected: clean.

- [ ] **Step 5: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py
git commit -m "audit-b1c: rewrite _session.py mutation with dataclasses.replace"
```

---

## Task 4: Delete writers + init + clean stale comments

**Files (all modify):**
- `coordinator/_core.py` — delete init at L186
- `coordinator/_cloud_state.py` — delete 3 writes at L112, L244, L316 + clean 4 docstring/comment mentions at L214, L260, L271, L357
- `coordinator/_rendering.py` — clean 1 comment at L167
- `coordinator/_device_sync.py` — clean 1 comment at L223

After T4 the shadow attribute is fully gone from the codebase.

- [ ] **Step 1: Delete the init line in `_core.py`**

Confirm location:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_core.py
```
Expected: one match — the init line.

Read context (`sed -n '184,189p'`):
```python
        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        self._static_map_pngs_by_id: dict[int, bytes] = {}
```

Use Edit:

`old_string`:
```python
        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        self._static_map_pngs_by_id: dict[int, bytes] = {}
```

`new_string`:
```python
        self._static_map_pngs_by_id: dict[int, bytes] = {}
```

(Delete the comment line AND the init line.)

- [ ] **Step 2: Delete the 3 bulk-reassign writers in `_cloud_state.py`**

Locate:
```bash
grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_cloud_state.py
```
Expected: 3 matches at the writer lines (line numbers may have shifted slightly since the discovery doc was written; use `grep -n` output).

For each match, read the surrounding 3 lines to understand context (`sed -n '<LN-1>,<LN+1>p'`). Each writer is a single line:
- L112: `self._cached_maps_by_id = new_state.maps_by_id`
- L244: `self._cached_maps_by_id = parsed_by_id`
- L316: `self._cached_maps_by_id = parsed_by_id`

Each is INSIDE a method that ALSO updates `self.cloud_state` (or one of its derivations) — the shadow update is redundant once readers stop using it.

For each line, use Edit (`replace_all: false`) with the single line as `old_string` and empty `new_string` (delete the line).

After deleting all three, re-grep:
```bash
grep -n "self\._cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_cloud_state.py
```
Expected: no output (all writes gone). Note that 4 docstring/comment mentions remain (will be cleaned in Step 4).

- [ ] **Step 3: Verify the writer-deletion left the surrounding logic intact**

Sanity-check that the methods around the deleted lines still do useful work (e.g. each method still assigns to `self.cloud_state`):

```bash
sed -n '108,115p' custom_components/dreame_a2_mower/coordinator/_cloud_state.py  # around L112 writer
sed -n '240,248p' custom_components/dreame_a2_mower/coordinator/_cloud_state.py  # around L244 writer
sed -n '312,320p' custom_components/dreame_a2_mower/coordinator/_cloud_state.py  # around L316 writer
```

(Line numbers will have shifted slightly after the deletions; use `grep -n "def _refresh_\|def _apply_\|def _restore_"` to navigate.)

Each context should still have a clear non-shadow output (e.g. `self.cloud_state = new_state`, `self.cloud_state = dataclasses.replace(self.cloud_state, maps_by_id=parsed_by_id)`, or similar). If the only effect of the deleted writer was the shadow update, the method's purpose has now changed — STOP and report.

Run `python -m py_compile custom_components/dreame_a2_mower/coordinator/_cloud_state.py` after each delete.

- [ ] **Step 4: Clean the 4 docstring/comment mentions in `_cloud_state.py`**

Locate:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_cloud_state.py
```
Expected: 4 matches in comments/docstrings (L214, L260, L271, L357 pre-edit; numbers may have shifted after T2 + Step 2's deletes).

For each match, use Edit to replace the symbol name in-place: `_cached_maps_by_id` → `cloud_state.maps_by_id`. Don't rewrite the surrounding prose.

Example (L214 area):
```python
        """Restore `_cached_maps_by_id` from the on-disk cache.
```
→
```python
        """Restore `cloud_state.maps_by_id` from the on-disk cache.
```

Re-grep to confirm zero hits:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_cloud_state.py
```
Expected: no output.

- [ ] **Step 5: Clean the comment in `_rendering.py`**

Locate:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_rendering.py
```
Expected: 1 match at L167.

Read context (`sed -n '165,170p'`):
```python
        - _cached_maps_by_id has no entry for the active map
```

Edit:
- `old_string`: `        - _cached_maps_by_id has no entry for the active map`
- `new_string`: `        - cloud_state.maps_by_id has no entry for the active map`

- [ ] **Step 6: Clean the comment in `_device_sync.py`**

Locate:
```bash
grep -n "_cached_maps_by_id" custom_components/dreame_a2_mower/coordinator/_device_sync.py
```
Expected: 1 match at L223.

Read context (`sed -n '221,225p'`):
```python
        Called whenever `_cached_maps_by_id` may have changed (after
```

Edit:
- `old_string`: `        Called whenever `_cached_maps_by_id` may have changed (after`
- `new_string`: `        Called whenever `cloud_state.maps_by_id` may have changed (after`

- [ ] **Step 7: Verify the shadow attribute is fully gone**

```bash
grep -rn "_cached_maps_by_id" custom_components/dreame_a2_mower --include='*.py'
```
Expected: NO OUTPUT — the shadow attribute and every reference to it (including comments) is gone.

Run: `python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py' -not -path '*/__pycache__/*')`
Expected: clean.

- [ ] **Step 8: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/
git commit -m "audit-b1c: delete _cached_maps_by_id shadow (4 writers/init + 6 stale comments)"
```

---

## Task 5: Delete `_refresh_cfg` + `_refresh_mihis` + their timer registrations

**Files (all modify):**
- `coordinator/_refreshers.py` — delete `_refresh_cfg` method (L104+) and `_refresh_mihis` method (L510+)
- `coordinator/_core.py` — delete:
  - CFG block at L395–406 (comment + `_periodic_cfg` def + `async_on_unload(async_track_time_interval(...))` wrapper + initial-fire `await self._refresh_cfg()`)
  - MIHIS block at L462–472 (same shape)

**Pre-T5 verification:** the discovery doc confirmed `_refresh_cloud_state` (via `fetch_full_cloud_state`) covers CFG and MIHIS. Re-verify once before deleting.

- [ ] **Step 1: Pre-flight — confirm `_refresh_cloud_state` covers CFG and MIHIS**

```bash
grep -n "CFG\|MIHIS" custom_components/dreame_a2_mower/cloud_client.py | head -30
```

You should see references to `CFG.*` keys and `MIHIS.*` keys being parsed inside `fetch_full_cloud_state` (the function called by `_refresh_cloud_state`). Verify by reading the `fetch_full_cloud_state` body (`grep -n "def fetch_full_cloud_state" custom_components/dreame_a2_mower/cloud_client.py`).

If `fetch_full_cloud_state` does NOT include CFG / MIHIS in its batch fetch, STOP and report. The discovery claim was wrong; deletion would create a staleness bug.

- [ ] **Step 2: Read the CFG block in `_core.py`**

```bash
grep -n "_periodic_cfg\|_refresh_cfg" custom_components/dreame_a2_mower/coordinator/_core.py
```

Locate the registration block. Read the full block (`sed -n '395,406p'`):
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

- [ ] **Step 3: Delete the CFG block in `_core.py`**

Edit (`replace_all: false`):

`old_string`:
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

`new_string`: (empty — delete the entire block including the trailing blank line)

- [ ] **Step 4: Read the MIHIS block in `_core.py`**

Read the full block. Pre-T3 line numbers were ~462–472; after T1–T4 they will have shifted UP slightly. Locate with `grep -n "_periodic_mihis\|_refresh_mihis" custom_components/dreame_a2_mower/coordinator/_core.py`.

Pre-edit shape:
```python
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

Read the 2-3 lines BEFORE this block to know the comment context (e.g. whether there's an introductory comment). The `# the local-archive seed to the cloud-authoritative numbers` line is the TAIL of a longer comment block introducing the periodic MIHIS poll — the WHOLE comment block should go, not just the trailing two lines.

Use `sed -n` to see the full comment context. The MIHIS block typically includes a 4–6 line comment paragraph above the `async def _periodic_mihis`. Capture the entire paragraph for the `old_string`.

- [ ] **Step 5: Delete the MIHIS block in `_core.py`**

Use Edit (`replace_all: false`) with the FULL block including the introductory comment as `old_string` and empty as `new_string`. The block ends at `await self._refresh_mihis()`.

After this Edit, `python -m py_compile custom_components/dreame_a2_mower/coordinator/_core.py` should be clean.

- [ ] **Step 6: Delete `_refresh_cfg` method in `_refreshers.py`**

Locate:
```bash
grep -n "def _refresh_cfg\|def _refresh_" custom_components/dreame_a2_mower/coordinator/_refreshers.py | head -5
```

Read the full method body. Determine the line range from `def _refresh_cfg(self)` through the line immediately BEFORE the next method definition.

Use Edit with the full method body (signature + docstring + body + trailing blank line) as `old_string` and empty as `new_string`.

- [ ] **Step 7: Delete `_refresh_mihis` method in `_refreshers.py`**

Same shape as Step 6. Locate with grep, capture full method body, delete.

- [ ] **Step 8: Verify no leftover references**

```bash
grep -rn "_refresh_cfg\|_refresh_mihis\|_periodic_cfg\|_periodic_mihis" custom_components/dreame_a2_mower --include='*.py'
```
Expected: no output. If anything remains (e.g. a comment elsewhere referencing the old refresher), clean it up in this same task.

Run: `python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py' -not -path '*/__pycache__/*')`
Expected: clean.

- [ ] **Step 9: Run pytest**

Run: `pytest tests/ -q`
Expected: all tests pass. If any test references `_refresh_cfg` or `_refresh_mihis`, those tests were testing the deleted refreshers and should be removed (analogous to B1a's test cleanup pattern). Surface to the controller before deleting.

- [ ] **Step 10: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/
git commit -m "$(cat <<'EOF'
audit-b1c: delete _refresh_cfg + _refresh_mihis (covered by _refresh_cloud_state)

The 10-min _refresh_cfg and _refresh_mihis refreshers are redundant
with the 2-min _refresh_cloud_state which fetches the same CFG and
MIHIS batches via fetch_full_cloud_state. Deletion tightens CFG/MIHIS
staleness from 10 min worst-case to 2 min worst-case.

_refresh_map deletion (the third refresher discovery flagged as
redundant) is deferred — see B1c design § "What stays for later".
EOF
)"
```

---

## Task 6: Final verification + push + user-led smoke check

**Files:** none (read-only verification).

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 2: Compile every integration file**

Run:
```bash
python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py' -not -path '*/__pycache__/*')
```
Expected: clean.

- [ ] **Step 3: Final no-leftovers grep**

```bash
grep -rn "_cached_maps_by_id\|_refresh_cfg\|_refresh_mihis\|_periodic_cfg\|_periodic_mihis" custom_components/dreame_a2_mower --include='*.py'
```
Expected: no output. The shadow attribute and both deleted refreshers are completely gone (including comments).

- [ ] **Step 4: Confirm `cloud_state.maps_by_id` is the only access pattern**

```bash
grep -rn "cloud_state\.maps_by_id\|cloud_state\.\smaps_by_id" custom_components/dreame_a2_mower --include='*.py' | wc -l
```
Expected: roughly 60–65 references (the 60 routed readers + a handful of writers/sources of truth in `_cloud_state.py` + the `dataclasses.replace` in `_session.py`).

- [ ] **Step 5: `inventory_audit.py` check**

```bash
python tools/inventory_audit.py 2>&1 | tail -5
```
Expected: passes (no `[error]` output).

- [ ] **Step 6: Push to origin/main**

```bash
git push origin main
```

Per memory `feedback_push_upstream_regularly.md`: HACS pulls from origin/main; push to keep history visible.

- [ ] **Step 7: User-led smoke check**

After push, the user does this on their live HA:

1. Reload the integration config entry from the HA UI (or restart HA).
2. Confirm the map camera entity still renders (it reads from `cloud_state.maps_by_id` now).
3. Confirm every map-N sub-device still exists with its original `entity_id`.
4. **CFG propagation test:** toggle a CFG-driven setting (rain protection) from the HA UI. Within ~2 min, confirm a second-instance read (e.g. via the integration's diagnostics or a second client) reflects the change. The 2-min path (`_refresh_cloud_state`) now solely owns CFG refresh; if propagation is slow or missing, that's the regression to watch for.
5. **MIHIS propagation test:** the lifetime counters (cumulative-area, blade-life-percent, side-brush-life-percent, etc.) should still update on the 2-min schedule. After a mowing session, verify they reflect the new totals within 2-3 minutes.
6. Run `Refresh from cloud` button — should still trigger a full refresh.

If anything regresses:
- Map render / sub-device issues → likely T1, T2, T3, or T4. `git bisect` between B1c commits.
- CFG / MIHIS propagation delays → revert T5 specifically (`git revert <T5-SHA>`); the shadow removal stays.

---

## Done

After T6 passes, B1c is complete. Block 1 remaining: B1d (`cloud_client.py` 2197-LOC file split).

**Summary of B1c changes** (for the release note):
- Removed `_cached_maps_by_id` shadow attribute: ~71 references touched across 11 files; canonical reads via `cloud_state.maps_by_id` (frozen dataclass field).
- Rewrote the single in-place mutation (`_session.py`) to use `dataclasses.replace`.
- Deleted `_refresh_cfg` and `_refresh_mihis` — redundant 10-min refreshers covered by the 2-min `_refresh_cloud_state`. CFG/MIHIS staleness tightens 10 min → 2 min.
- Deferred: `_refresh_map`, `_poll_slow_properties`, `camera.py` `getattr`-guard simplification.
