# Block 1 Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the read-only Block 1 discovery findings doc with phase-ready inventories for B1a/b/c/d plus broader-sweep sections and deferred-split sketches.

**Architecture:** Like the meta pass, this is documentation production. No source touched. Each task fills one section of one output file (`docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`) and commits it. Validation steps cross-check the doc against the live filesystem (every file:line cited resolves to real code).

**Tech Stack:** Bash (`grep`, `find`, `wc`), Python stdlib `ast` for AST checks, Markdown for output. No new dependencies.

**Reference docs (do NOT modify):**
- Parent design: `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
- Discovery design: `docs/superpowers/specs/2026-05-19-block1-discovery-design.md`
- Ground truth (meta-pass output): `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`
- Repo conventions: `CLAUDE.md` (coordinator-structure section is authoritative for mixin concerns)

**Output file:** `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`

**Hard rules:**
- No edits to any file under `custom_components/dreame_a2_mower/`, `dashboards/`, `tools/`, or `tests/`.
- Output goes only to the one findings doc. If you spot something out of B1 scope, file it in § 5.4 as "out-of-scope note", do not act on it.
- Use the **finding format** specified in the discovery-design spec § "Finding format":
  ```
  - **[bucket]** `file.py:LL` — short description.
    Evidence: <one-line>. Disposition: <phase | defer>.
  ```
  Buckets: `dead`, `dup`, `refactor`, `bug`, `better`.

---

## Task 1: Scaffold the discovery findings doc

**Files:**
- Create: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`

- [ ] **Step 1: Create the file with section headers**

Write this exact content:

```markdown
# Block 1 — Discovery Findings

**Date:** 2026-05-19
**Status:** in progress — populated task-by-task per plan
**Plan:** `docs/superpowers/plans/2026-05-19-block1-discovery.md`
**Design:** `docs/superpowers/specs/2026-05-19-block1-discovery-design.md`
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Ground truth (meta):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

This document is read-only output of the Block 1 discovery pass. It captures
phase-ready inventories for the four remediation phases (B1a/b/c/d), a
broader sweep of B1 surface findings, and deferred-split sketches for the
four coordinator files >800 LOC.

Every finding uses the format:
`- **[bucket]** \`file.py:LL\` — short description. Evidence: <line>. Disposition: <phase | defer>.`

Buckets: `dead` (remove), `dup` (consolidate), `refactor` (split/simplify), `bug` (fix), `better` (cleaner option).

## 1. B1a — Cleanup inventory

### 1.1 Dead-code candidates
(populated by Task 2)

### 1.2 Silent-swallow log additions
(populated by Task 2)

### 1.3 Uncancelled handles / timers
(populated by Task 2)

### 1.4 Coordinator-mixin import consolidation
(populated by Task 2)

## 2. B1b — Retry helper inventory

### 2.1 Helper contract
(populated by Task 3)

### 2.2 Call sites
(populated by Task 3)

### 2.3 Stacked-loop elimination
(populated by Task 3)

## 3. B1c — `_cached_*` shadow inventory

### 3.1 Every `_cached_*` attribute on the coordinator
(populated by Task 4)

### 3.2 Readers per attribute
(populated by Task 4)

### 3.3 Removal sequence
(populated by Task 4)

## 4. B1d — `cloud_client.py` split plan

### 4.1 Function-by-function placement table
(populated by Task 5)

### 4.2 Module-level state placement
(populated by Task 5)

### 4.3 Test import impact
(populated by Task 5)

## 5. Broader sweep

### 5.1 Refreshers inventory (`_refreshers.py`)
(populated by Task 6)

### 5.2 Settings-write fan-out
(populated by Task 6)

### 5.3 MQTT subscription lifecycle
(populated by Task 6)

### 5.4 Out-of-scope notes (catch-all)
(populated by Task 6)

## 6. Deferred coordinator-split sketches

### 6.1 `coordinator/_core.py`
(populated by Task 7)

### 6.2 `coordinator/_refreshers.py`
(populated by Task 7)

### 6.3 `coordinator/_session.py`
(populated by Task 7)

### 6.4 `coordinator/_mqtt_handlers.py`
(populated by Task 7)
```

- [ ] **Step 2: Validate file created**

Run: `wc -l docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`
Expected: roughly 70 lines.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: scaffold discovery findings doc"
```

---

## Task 2: Populate § 1 — B1a cleanup inventory

Fill in the four B1a sub-sections (dead-code, silent-swallow, uncancelled handles, mixin imports).

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 1.1–1.4)

- [ ] **Step 1: § 1.1 Dead-code candidates — migration code analysis**

For each of these files, read the contents and assess:
- `custom_components/dreame_a2_mower/_migration.py` (468 LOC)
- `custom_components/dreame_a2_mower/_lidar_migration.py` (75 LOC)
- `custom_components/dreame_a2_mower/_settings_writes.py` (77 LOC)

For each migration file, answer:
- What version-to-version migration does it perform?
- What state would be lost if it were removed today?
- Is anything that calls it still calling it (`grep -rn 'from .*_migration import\|import _migration' custom_components/`)?
- Per memory `feedback_no_migration_overengineering.md`: "single-user dev: skip async_migrate_entry / registry-rename code. Reinstall is fine".

Write findings under § 1.1, one per file. Use the finding format. Example:

```markdown
- **[dead]** `_migration.py:1–468` — entity-registry migration v1→v2 (entry_id → SN-based unique_id rewrite).
  Evidence: `__init__.py` calls `async_migrate_entry` which delegates here.
  Disposition: B1a — likely deletable per memory; the next reinstall will land on the v2 layout. Discovery to confirm by reading the actual entry_version flag.
```

- [ ] **Step 2: § 1.1 Dead-code candidates — dead branches**

Run:
```bash
cd custom_components/dreame_a2_mower
grep -rn "if False\|elif False\|# TODO.*remove\|# DEAD\|XXX" --include='*.py' | grep -v __pycache__ | head -30
```

For each hit, open the file and judge whether it's a true dead branch or an intentional flag. Write findings under § 1.1.

- [ ] **Step 3: § 1.1 Dead-code candidates — unused imports across the 9 coordinator mixins**

The meta-pass review found that across 9 coordinator mixins, the 5-line `from ..protocol import …` block is duplicated, but most mixins use only a subset. Determine which.

For each of `_core.py`, `_cloud_state.py`, `_lidar_oss.py`, `_mqtt_handlers.py`, `_property_apply.py`, `_refreshers.py`, `_rendering.py`, `_session.py`, `_writes.py`:

```bash
# For each protocol submodule, count usages inside the mixin (excluding the import line)
mixin=_core.py   # change per file
for mod in _s2p51 _heartbeat _telemetry _session_summary _wheel_bind; do
  count=$(grep -c "\b${mod}\b" custom_components/dreame_a2_mower/coordinator/$mixin)
  echo "$mixin uses $mod: $count occurrences (incl import line)"
done
```

Build a 9×5 usage table. Any cell with `1` (just the import line, no actual use) is a dead import.

Write the table into § 1.4. For each cell with `1`, record a `[dead]` finding.

Also do the same for the observability imports (`FreshnessTracker`, `NovelObservationRegistry`) across the same 9 mixins.

- [ ] **Step 4: § 1.2 Silent-swallow log additions**

For each silent swallow already known (from meta § 4.3 + Task 7 follow-up), produce a row:

```markdown
- **[bug]** `cloud_client.py:1835` — silent `except Exception: pass` in `parse_full_cloud_state` SETTINGS section.
  Evidence: `grep -A2 "except Exception" cloud_client.py | head -3`.
  Disposition: B1a — add `_LOGGER.debug("settings batch parse failed: %s", e, exc_info=True)`.
```

Sites to enumerate:
- 14 silent swallows in `cloud_client.py:1835–1960` (per meta § 4.3)
- `cloud_client.py:940` and `cloud_client.py:1114` (per Task 7 follow-up — OSS JSON parse helpers)

For each, propose a one-line `_LOGGER.debug` message that names the context (which batch / which key / which fetcher).

Run this to enumerate any silent swallows in `cloud_client.py` you might have missed:
```bash
python3 <<'PY'
import ast, pathlib
p = pathlib.Path("custom_components/dreame_a2_mower/cloud_client.py")
tree = ast.parse(p.read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.ExceptHandler):
        # Look for handler bodies that are just pass, return None, or a non-logging single statement
        body = node.body
        if len(body) == 1:
            s = body[0]
            if isinstance(s, ast.Pass):
                print(f"L{node.lineno}: pass")
            elif isinstance(s, ast.Return):
                print(f"L{node.lineno}: return {ast.dump(s.value) if s.value else 'None'}")
            elif isinstance(s, ast.Assign):
                print(f"L{node.lineno}: assign")
PY
```

Add any newly discovered silent swallow to § 1.2.

- [ ] **Step 5: § 1.3 Uncancelled handles / timers**

The meta § 4.2 found one leak: `coordinator/_device_sync.py:291` (`_cloud_refresh_debounce_handle`).

Verify no other handles in B1 files are uncancelled. Run:
```bash
cd custom_components/dreame_a2_mower
grep -rn "loop.call_later\|loop.call_soon\|async_call_later\|async_track_time_interval\|async_track_point_in_time\|async_track_state_change" --include='*.py' | grep -v __pycache__ | grep -E "coordinator/|^cloud_client|^mqtt_client|^_settings_writes" | head -40
```

For each hit:
- Read the surrounding code.
- Is the return value (unsubscribe handle) registered with `async_on_unload` or `self.entry.async_on_unload`?
- If not, is it stored to `self.<attr>` and explicitly cancelled in some lifecycle hook?
- If neither, it's a potential leak — write a `[bug]` finding.

Confirm the `_cloud_refresh_debounce_handle` finding from meta § 4.2 is still accurate (re-read line 291 ± 20).

- [ ] **Step 6: § 1.4 Coordinator-mixin import consolidation — write the analysis**

Using the table from Step 3, write up § 1.4 with:
- The 9×5 usage table for protocol imports + the 9×2 table for observability imports.
- A summary count: how many import lines are dead (cell=1) vs live (cell ≥ 2).
- The recommended consolidation approach (options: shared mixin base, `coordinator/_imports.py` re-export module, or just inline-and-delete after dead-import removal).

Don't decide which option to use — that's the B1a plan's decision. Just list the options with trade-offs.

- [ ] **Step 7: Cross-validate all file:line references in § 1**

```bash
# Extract every file:line from § 1
awk '/^## 1\./,/^## 2\./' docs/superpowers/specs/2026-05-19-block1-discovery-findings.md \
  | grep -oE '`[^`]+\.py:[0-9]+`' | tr -d '`' | sort -u
```

For each `file.py:LL`:
- Confirm the file exists.
- Confirm the line is within the file's LOC range.
- Spot-check 3 references by opening the file at that line.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 1 B1a cleanup inventory"
```

---

## Task 3: Populate § 2 — B1b retry helper inventory

Fill in the three B1b sub-sections.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 2.1–2.3)

- [ ] **Step 1: § 2.1 Helper contract**

Read `cloud_client.py:1387` (`request()`), `cloud_client.py:1219` (`get_file()`), `cloud_client.py:578` (`send()`) carefully. Identify what each loop varies:
- Per-attempt action (HTTP request vs file fetch vs RPC send)
- Failure predicate (what counts as "retry-worthy")
- Inter-attempt delay (none / fixed 8s)
- Attempt count (parameterised)
- Deadline (none currently)

Write § 2.1 as a specification for the helper:

```markdown
### 2.1 Helper contract

**Proposed signature:**
```python
async def _cloud_request_with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    delay_s: float = 0.0,
    deadline_s: float | None = None,
    should_retry: Callable[[Exception], bool] = _is_retryable,
) -> T:
    """One attempt = one call to coro_factory(). Retries on should_retry(exc) returning True.
    Sleeps delay_s between attempts. Aborts when attempts exhausted or deadline exceeded.
    """
```

(adjust the actual signature based on what cleanly fits the 3 call sites — this is the discovery doc proposing, not the plan binding)
```

Explain how each of the 3 existing call sites maps onto the helper.

- [ ] **Step 2: § 2.2 Call sites**

For each of the 3 call sites, write a finding with file:line + proposed flip:

```markdown
- **[dup]** `cloud_client.py:1387` — `request()` 3-iter loop.
  Evidence: `while retries < retry_count + 1` on a synchronous block.
  Disposition: B1b — wrap the inner HTTP call with `_cloud_request_with_retry(...)` using existing `retry_count` parameter as `max_attempts`. Note: this site runs in an executor thread (blocking), so the helper needs a sync sibling OR the wrap goes around the executor-submit call from `_api_call`.
```

Do this for `request`, `get_file`, and `send`. The `send()` finding must explicitly note that the outer `for attempt in range(attempts)` loop is removed (the inner `request()` loop is the only retry).

- [ ] **Step 3: § 2.3 Stacked-loop elimination**

Write one finding documenting the stacked-loop bug:

```markdown
- **[bug]** `cloud_client.py:578` — action method effective retry ceiling is 3×3=9, not 3.
  Evidence: `send(method="action")` enters `for attempt in range(3)`. Inside the loop body, `_api_call → request()` runs its own retry loop with default `retry_count=2` → 3 attempts. Per outer iteration, 3 inner attempts × 1 outer × 8s sleep ⇒ up to 9 attempts and ~16–24s of `time.sleep` on the calling thread.
  Disposition: B1b — remove the outer `for attempt in range(attempts)` loop entirely; let the inner retry handle attempt counting; replace `time.sleep(8)` with the helper's `delay_s` parameter (or `asyncio.sleep` if context permits).
```

- [ ] **Step 4: Cross-validate § 2**

Same file:line check as Task 2 Step 7.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 2 B1b retry helper inventory"
```

---

## Task 4: Populate § 3 — `_cached_*` shadow inventory

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 3.1–3.3)

- [ ] **Step 1: § 3.1 Every `_cached_*` attribute**

```bash
cd custom_components/dreame_a2_mower
grep -rn "self\._cached_\|coordinator\._cached_" --include='*.py' | grep -v __pycache__
```

For each unique `_cached_<name>`, note:
- Where it's defined (`self._cached_<name> = ...`)
- The canonical CloudState field that should replace it (read CloudState's structure: `head -40 cloud_state.py`)

Write § 3.1 as a table:

```markdown
| Attribute | Defined at | Canonical replacement | Notes |
|---|---|---|---|
| `_cached_maps_by_id` | `coordinator/_core.py:192` | `CloudState.maps_by_id` | Confirmed shadow per meta § 4.5. |
| ... | | | |
```

If there are no other `_cached_*` attributes beyond `_cached_maps_by_id`, write "Only one shadow attribute exists" and proceed.

- [ ] **Step 2: § 3.2 Readers per attribute**

For each attribute from § 3.1, find every reader:

```bash
attr=_cached_maps_by_id
grep -rn "self\.$attr\|coordinator\.$attr\|\.${attr}" custom_components/dreame_a2_mower --include='*.py' | grep -v __pycache__ | sort
```

For each reader, write a finding:

```markdown
- **[dup]** `select.py:NNN` — reads `coordinator._cached_maps_by_id` in `<class>.<method>`.
  Evidence: `<line content>`.
  Disposition: B1c — replace with `coordinator.cloud_state.maps_by_id`.
```

Group by file in subsection bullets if the count per file is large. The meta § 4.5 figure was 22 in `select.py`, 7 in `switch.py`; verify your real count and update.

- [ ] **Step 3: § 3.3 Removal sequence**

For each attribute, decide and document:
- Does the writer (`self._cached_<name> = X`) need to land first (as a backward-compat shim) or can it be deleted same-commit as the last reader? Answer: same-commit is fine since this is single-user dev with no rolling deploy.
- Is there ordering between attributes (e.g. one references the other)? Answer based on the cache definitions.

Write § 3.3 as a short prose block + numbered sequence:

```markdown
### 3.3 Removal sequence

1. Update every reader (file:line list per § 3.2) to use `CloudState.<field>`.
2. Delete `self._cached_*` writers in `coordinator/_core.py` (and any other definition sites).
3. Verify with `grep -rn "_cached_" custom_components/dreame_a2_mower --include='*.py' | grep -v __pycache__` — should return zero hits (or only legitimate non-shadow uses).
```

- [ ] **Step 4: Cross-validate § 3**

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 3 _cached_* shadow inventory"
```

---

## Task 5: Populate § 4 — `cloud_client.py` split plan

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 4.1–4.3)

- [ ] **Step 1: § 4.1 Function-by-function placement table**

Read `cloud_client.py` (2197 lines) and enumerate every top-level function and class. Use this AST script:

```bash
python3 <<'PY'
import ast, pathlib
p = pathlib.Path("custom_components/dreame_a2_mower/cloud_client.py")
tree = ast.parse(p.read_text())
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        end = node.end_lineno; loc = end - node.lineno + 1
        print(f"FN   L{node.lineno:4d} ({loc:4d} LOC)  {node.name}")
    elif isinstance(node, ast.ClassDef):
        print(f"CLS  L{node.lineno:4d}             {node.name}")
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = m.end_lineno; loc = end - m.lineno + 1
                print(f"  M  L{m.lineno:4d} ({loc:4d} LOC)  {node.name}.{m.name}")
PY
```

For each function/method, assign a target submodule from the parent design spec's proposed split:
- `_auth.py` — login, token, region, refresh
- `_rpc.py` — `get_properties`, `set_properties`, `action`, `request`, `_api_call`, `send`
- `_oss.py` — `get_file`, OSS signed-URL fetch, lidar/wifi blob retrieval
- `_discovery.py` — device list, capabilities query, region/realm lookup
- `_batch.py` — `fetch_full_cloud_state`, batch parser glue
- `__init__.py` — `CloudClient` class shell, public re-exports

Write § 4.1 as a table:

```markdown
| Current name | Current line | LOC | Target submodule | Notes |
|---|---|---|---|---|
| `CloudClient.__init__` | NN | NN | `__init__.py` | stays on the class |
| `CloudClient._login` | NN | NN | `_auth.py` | |
| ... | | | | |
```

If a function doesn't fit any submodule cleanly, propose a new submodule or note ambiguity — but don't invent submodules to dodge a hard placement call. The parent design spec is authoritative.

- [ ] **Step 2: § 4.2 Module-level state placement**

Run:
```bash
python3 <<'PY'
import ast, pathlib
p = pathlib.Path("custom_components/dreame_a2_mower/cloud_client.py")
tree = ast.parse(p.read_text())
for node in tree.body:
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        print(f"ASSIGN  L{node.lineno:4d}  {names}")
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        print(f"ANN     L{node.lineno:4d}  {node.target.id}")
PY
```

For each module-level constant / helper, assign it a target submodule (or "shared in `__init__.py`" if it's used across multiple).

Write § 4.2 as a similar table.

- [ ] **Step 3: § 4.3 Test import impact**

```bash
grep -rn "from custom_components.dreame_a2_mower.cloud_client\|from ..cloud_client\|import cloud_client" tests/ --include='*.py' | head -20
grep -rn "from custom_components.dreame_a2_mower.cloud_client\|from \.cloud_client\|import cloud_client" custom_components/dreame_a2_mower --include='*.py' | head -20
```

For each importer, judge whether the import would break after the split. Imports that use `from ...cloud_client import CloudClient` will continue to work via the new `cloud_client/__init__.py` re-export. Imports that reach into `cloud_client._<helper>` (private functions) may break — flag those.

Write § 4.3 as a list of importers and their post-split status.

- [ ] **Step 4: Cross-validate § 4**

Check that the function names in your table all exist:
```bash
for name in $(awk '/^## 4\./,/^## 5\./' docs/superpowers/specs/2026-05-19-block1-discovery-findings.md | grep -oE '`[A-Za-z_][A-Za-z_0-9]*\.\?[A-Za-z_][A-Za-z_0-9]*`' | tr -d '`' | sort -u); do
  grep -q "def ${name##*.}" custom_components/dreame_a2_mower/cloud_client.py || echo "MISSING: $name"
done
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 4 cloud_client split plan"
```

---

## Task 6: Populate § 5 — Broader sweep

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 5.1–5.4)

- [ ] **Step 1: § 5.1 Refreshers inventory**

Read `coordinator/_refreshers.py` (802 LOC). For each top-level method that starts with `_refresh_` or `async_refresh_`, capture:
- Name
- What data it refreshes (cloud SETTINGS / CFG / MAP / etc.)
- Cadence (called by `async_track_time_interval` at what interval?) — cross-reference meta § 4.2 (12 sites in `_core.py:385,397,…`).
- Overlap with other refreshers (e.g. does `_refresh_map` get covered by the broader `_refresh_full_cloud_state`?)
- Whether it can be cancelled if a higher-tier refresh is running.

Write § 5.1 as a table:

```markdown
| Method | Refreshes | Cadence | Overlap | Notes |
|---|---|---|---|---|
| `_refresh_full_cloud_state` | all CloudState batches | 10 min | base case | canonical |
| `_refresh_settings` | SETTINGS.* batch | 2 min | subset of above | redundant? |
| ... | | | | |
```

Flag any refresher that is (a) called from nowhere, (b) overlapped by a higher-tier refresher with no different cadence, or (c) does the same fetch as another refresher.

- [ ] **Step 2: § 5.2 Settings-write fan-out trace**

Trace an example settings-write end-to-end. Pick `switch.rain_protection` (or any settings-switch).

```bash
grep -n "rain_protection\|RAIN_PROTECTION\|rain_resume" custom_components/dreame_a2_mower/switch.py | head -10
```

Read the switch's `async_turn_on`. Follow the chain:
- entity calls → `_settings_writes.helper` → `coordinator/_writes.py:write_setting` → `cloud_client.set_property` (or `set_cfg`).

Write § 5.2 as a step-by-step trace with file:line at each hop. Document any branching (e.g. some settings go through a different path).

Flag if there's more than one fan-out path doing the same thing.

- [ ] **Step 3: § 5.3 MQTT subscription lifecycle**

```bash
grep -rn "subscribe\|unsubscribe\|client\.on_message\|on_connect\|on_disconnect" custom_components/dreame_a2_mower/mqtt_client.py custom_components/dreame_a2_mower/coordinator/ --include='*.py'
```

Trace:
- Where `paho.Client` is created.
- What topics are subscribed (`mqtt_client.subscribe` call sites).
- Whether the subscribed topics are unsubscribed on coordinator shutdown.
- Whether `paho.Client.loop_start` / `loop_stop` are balanced.
- Whether the `on_message` callback path can deadlock if the event loop is paused.

Write § 5.3 as a short prose block + a list of any leaks/findings.

- [ ] **Step 4: § 5.4 Out-of-scope notes (catch-all)**

Anything you spotted during T2-T6 that:
- Is in B1 scope but doesn't fit § 1-5 cleanly, OR
- Is out of B1 scope but worth flagging for a later block

goes here as bullets. Each bullet labelled `[BNote]` or `[scope]` plus a one-liner.

- [ ] **Step 5: Cross-validate § 5**

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 5 broader sweep (refreshers / settings-write / MQTT lifecycle / catch-all)"
```

---

## Task 7: Populate § 6 — Deferred coordinator-split sketches

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` (§ 6.1–6.4)

For each of the 4 coordinator files >800 LOC, write a one-paragraph sketch (NOT a plan — these splits are deferred):

- [ ] **Step 1: § 6.1 `coordinator/_core.py` (828 LOC)**

Read the file's top-level method list. The file currently holds: `__init__`, `_async_update_data`, properties (`cloud_state`, etc.), `_init_cloud`, `_init_mqtt`. Propose a possible split shape:

```markdown
### 6.1 `coordinator/_core.py` (828 LOC)

Current concern: lifecycle + orchestration + transport-init. Possible split:
- `_core_lifecycle.py` — `__init__`, `_async_update_data`, properties.
- `_core_init.py` — `_init_cloud`, `_init_mqtt`, transport bootstrap.

Risks: `__init__` sets a large amount of shared state read by every mixin (per CLAUDE.md "Only `_CoreMixin` owns `__init__`"); splitting requires either splitting the init or co-locating both halves.

Status: deferred — execute in a separate cycle.
```

Write this for `_core.py`, applying the same shape (one paragraph each).

- [ ] **Step 2: § 6.2 `coordinator/_refreshers.py` (802 LOC)**

Same shape. Likely split: by data domain (cloud-state refresh / lidar refresh / wifi refresh / sub-device refresh).

- [ ] **Step 3: § 6.3 `coordinator/_session.py` (925 LOC)**

Same shape. Likely split: restore + persist (one half) vs finalize + replay + work-log render (other half).

- [ ] **Step 4: § 6.4 `coordinator/_mqtt_handlers.py` (810 LOC)**

Same shape. Likely split: message routing (top-level dispatch) vs per-property handlers (state-update glue) vs MAPL apply.

- [ ] **Step 5: Cross-validate § 6**

Confirm each filename mentioned exists in the current tree.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: § 6 deferred coordinator-split sketches"
```

---

## Task 8: Final consistency pass

Cross-validate everything end-to-end, flip status to complete, push.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md`

- [ ] **Step 1: Read the whole doc**

Open the doc and read every section.

- [ ] **Step 2: Validate every file:line reference**

```bash
for ref in $(grep -oE '`[a-zA-Z_./][a-zA-Z_./0-9]*\.py:[0-9]+`' docs/superpowers/specs/2026-05-19-block1-discovery-findings.md | tr -d '`' | sort -u); do
  file="${ref%:*}"
  line="${ref#*:}"
  # Resolve to integration path
  for prefix in "" "custom_components/dreame_a2_mower/"; do
    fullpath="${prefix}${file}"
    if [ -f "$fullpath" ]; then
      maxline=$(wc -l < "$fullpath")
      if [ "$line" -gt "$maxline" ]; then
        echo "OUT-OF-RANGE: $ref (file has $maxline lines)"
      fi
      continue 2
    fi
  done
  echo "MISSING: $ref"
done
```

Expected: no MISSING or OUT-OF-RANGE output.

- [ ] **Step 3: Validate finding-format consistency**

```bash
# Every finding bullet should start with [bucket]
grep -E "^- \*\*\[" docs/superpowers/specs/2026-05-19-block1-discovery-findings.md | head -20
# Buckets should be one of: dead, dup, refactor, bug, better, BNote, scope
grep -oE '^- \*\*\[[a-zA-Z]+\]' docs/superpowers/specs/2026-05-19-block1-discovery-findings.md | sort -u
```

Confirm only the valid bucket names appear.

- [ ] **Step 4: Spot-check phase coverage**

For each phase B1a/B1b/B1c/B1d, count findings:
```bash
for phase in B1a B1b B1c B1d; do
  c=$(grep -c "Disposition: $phase" docs/superpowers/specs/2026-05-19-block1-discovery-findings.md)
  echo "$phase: $c findings"
done
```

Each phase should have ≥1 finding (the meta pass already gave us multiple). If any phase has 0, double-check it wasn't missed.

- [ ] **Step 5: Flip the status line**

Replace:
```markdown
**Status:** in progress — populated task-by-task per plan
```
with:
```markdown
**Status:** complete — 2026-05-19
```

- [ ] **Step 6: Remove any remaining `(populated by Task N)` placeholders**

```bash
grep -n "populated by Task" docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
```

Should return nothing. If anything remains, you missed a section — write the section before flipping status.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-block1-discovery-findings.md
git commit -m "audit-b1-disco: final consistency pass + status complete"
```

- [ ] **Step 8: Push**

```bash
git push origin main
```

Per memory `feedback_cleanup_push_cadence.md`: during P1–P7 pre-launch cleanup, push regularly for traceability.

---

## Done

The discovery doc now lives at `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` with all sections populated.

**Next:** brainstorm B1a (cleanup wins). The B1a cycle will read § 1.1–1.4 of this doc as its task input.
