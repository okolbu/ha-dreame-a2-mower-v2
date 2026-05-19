# Integration Audit — Meta Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the shared architecture / domain-ownership / cross-cutting-smells document that all four subsequent audit blocks reference instead of rediscovering.

**Architecture:** This is a **read-only** discovery pass. No code changes. Each task fills one section of a single output document and commits it. Validation steps cross-check the doc against the live filesystem (every file mentioned exists; line counts match).

**Tech Stack:** Bash (`find`, `grep`, `wc`, `awk`), Python stdlib `ast` for import parsing, Markdown for output. No new dependencies.

**Output file:** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

**Reference:** the audit overview spec at `docs/superpowers/specs/2026-05-19-integration-audit-overview.md` defines the deliverable shape — re-read its "Meta pass" section before starting.

**Hard rules:**
- No edits to any file under `custom_components/dreame_a2_mower/`.
- No edits to dashboards, tools, tests, or any other source.
- Output goes only to the one meta-pass doc. If you spot a finding mid-task, append it to the doc's "later-block backlog" section — do not act on it.

---

## Task 1: Scaffold the meta-pass doc

**Files:**
- Create: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

- [ ] **Step 1: Create the file with section headers**

Write this exact content:

```markdown
# Integration Audit — Meta Pass

**Date:** 2026-05-19
**Status:** in progress — populated task-by-task per plan
`docs/superpowers/plans/2026-05-19-integration-audit-meta.md`
**Parent spec:** `docs/superpowers/specs/2026-05-19-integration-audit-overview.md`

This document is the shared ground-truth referenced by all four subsequent
audit blocks. It is read-only output of the meta pass — no remediation lives
here.

## 1. Module map

(populated by Task 2)

## 2. Dependency graph

(populated by Task 3)

## 3. Domain-concept ownership

(populated by Task 4)

## 4. Cross-cutting smells

### 4.1 Retry / poll / backoff loops
(populated by Task 5)

### 4.2 Scheduling patterns
(populated by Task 6)

### 4.3 Error handling patterns
(populated by Task 7)

### 4.4 Large files & long functions
(populated by Task 8)

### 4.5 Other cross-cutting smells
(populated by Task 9)

## 5. Later-block backlog

Items spotted during meta pass that belong to a specific later block.
Each entry: `[Bx] short label — one-line description`.

(populated incrementally; empty at start)
```

- [ ] **Step 2: Validate file created**

Run: `ls -la docs/superpowers/specs/2026-05-19-integration-audit-meta.md`
Expected: file exists, ~25 lines.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: scaffold meta-pass doc"
```

---

## Task 2: Module map

Catalogue every Python module under `custom_components/dreame_a2_mower/` with a one-line purpose and current LOC. Highlight files >800 LOC as refactor candidates.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 1)

- [ ] **Step 1: Enumerate all integration .py files with LOC**

Run:
```bash
cd custom_components/dreame_a2_mower
find . -name '*.py' -not -path '*/__pycache__/*' | xargs wc -l | sort -k2
```

Expected: list of every module with LOC, ending in a total. Capture this output — you'll use it for the table.

- [ ] **Step 2: For each module, read the top of the file to determine purpose**

For modules you don't immediately recognise, run:
```bash
head -30 <path>   # docstring + imports usually tell you
```

Group modules by package (top-level, coordinator/, mower/, protocol/, live_map/, observability/, inventory/, data/, archive/, translations/, www/).

Don't include `__pycache__/`, `__init__.py` files with 0 LOC, or `translations/*.json`.

- [ ] **Step 3: Write the module-map table into § 1**

Format (one section per package):

```markdown
### Top-level (custom_components/dreame_a2_mower/)

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 279 | HA entrypoint: setup/unload entry, platform forward, services register |
| `cloud_client.py` | 2197 | **>800 — refactor candidate.** Cloud HTTP + auth + RPC + blob fetch |
| ... | | |

### coordinator/

| File | LOC | Purpose |
|---|---|---|
| `_core.py` | 828 | **>800 — refactor candidate.** Coordinator orchestration |
| ... | | |
```

One line of purpose per file. Mark any file >800 LOC with **>800 — refactor candidate.** prefix.

- [ ] **Step 4: Validate every listed file exists**

Run:
```bash
cd custom_components/dreame_a2_mower
for f in $(grep -oE '`[^`]+\.py`' ../../docs/superpowers/specs/2026-05-19-integration-audit-meta.md | tr -d '`'); do
  test -f "$f" || echo "MISSING: $f"
done
```

Expected: no MISSING lines.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 1 module map"
```

---

## Task 3: Dependency graph

Extract import relationships across the integration; identify cycles, modules with high fan-in (many importers), and orphan modules (not imported by anyone, no entry point).

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 2)

- [ ] **Step 1: Extract internal imports**

Use Python AST for accuracy. Run this one-shot script (do not commit it):

```bash
python3 <<'PY'
import ast, pathlib, collections
root = pathlib.Path("custom_components/dreame_a2_mower")
edges = collections.defaultdict(set)
modules = set()
for p in root.rglob("*.py"):
    if "__pycache__" in p.parts: continue
    rel = str(p.relative_to(root))
    modules.add(rel)
    try:
        tree = ast.parse(p.read_text())
    except Exception as e:
        print(f"PARSE-ERR {rel}: {e}"); continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(".") or "dreame_a2_mower" in node.module:
                edges[rel].add(node.module)
        elif isinstance(node, ast.Import):
            for n in node.names:
                if "dreame_a2_mower" in n.name:
                    edges[rel].add(n.name)
fan_in = collections.Counter()
for src, dsts in edges.items():
    for d in dsts: fan_in[d] += 1
print("# fan_in_top20")
for m, n in fan_in.most_common(20):
    print(f"{n:3d}  {m}")
print("# total_modules =", len(modules))
print("# total_edges =", sum(len(v) for v in edges.values()))
PY
```

Capture the output.

- [ ] **Step 2: Detect cycles**

Run:
```bash
python3 <<'PY'
import ast, pathlib, collections
root = pathlib.Path("custom_components/dreame_a2_mower")
# Build module-name -> path map and reverse
def modname(p):
    parts = p.relative_to(root).with_suffix("").parts
    return ".".join(parts)
mods = {modname(p): p for p in root.rglob("*.py") if "__pycache__" not in p.parts}
edges = collections.defaultdict(set)
for name, p in mods.items():
    try: tree = ast.parse(p.read_text())
    except: continue
    pkg = name.rsplit(".", 1)[0] if "." in name else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # relative — resolve
                base = pkg.split(".")
                for _ in range(node.level - 1):
                    base = base[:-1] if base else base
                target = ".".join(filter(None, base + ([node.module] if node.module else [])))
            else:
                target = node.module or ""
            if target in mods:
                edges[name].add(target)
# Tarjan / cycle find
def cycles(g):
    WHITE, GREY, BLACK = 0, 1, 2
    color, stack, out = collections.defaultdict(int), [], []
    def dfs(u, path):
        color[u] = GREY
        for v in g.get(u, ()):
            if color[v] == GREY:
                idx = path.index(v) if v in path else None
                if idx is not None:
                    out.append(path[idx:] + [v])
            elif color[v] == WHITE:
                dfs(v, path + [v])
        color[u] = BLACK
    for n in list(g):
        if color[n] == WHITE:
            dfs(n, [n])
    return out
for c in cycles(edges):
    print(" -> ".join(c))
PY
```

Capture each cycle (one path per line). Empty output = no cycles.

- [ ] **Step 3: Detect orphan modules (no internal importers, not an entry point)**

Entry points are: `__init__.py` at every level, anything HA loads as a platform (`sensor.py`, `switch.py`, `select.py`, `number.py`, `binary_sensor.py`, `button.py`, `time.py`, `calendar.py`, `event.py`, `device_tracker.py`, `lawn_mower.py`, `logbook.py`, `diagnostics.py`, `config_flow.py`, `services.py`).

Use the fan-in table from Step 1: every module with fan-in 0 that is NOT in the entry-point list is an orphan candidate.

- [ ] **Step 4: Write § 2 with three subsections**

Format:

```markdown
## 2. Dependency graph

**Total modules:** N
**Total internal import edges:** M

### 2.1 Fan-in top-20 (most-imported modules)

| Module | Importers | Notes |
|---|---|---|
| `const` | 47 | central constants — expected |
| `cloud_state` | 23 | data hub — expected |
| ... | | |

### 2.2 Import cycles

(none) — OR — one bulleted line per cycle, full path.

### 2.3 Orphan modules

| Module | Reason if known |
|---|---|
| `_render_dotted` | not imported — check if dead post-overhaul |
| ... | |
```

The "Notes" column flags anything unexpected (e.g. `mqtt_client` having fan-in 1 would be a surprise).

- [ ] **Step 5: Validate**

Spot-check three lines from the fan-in table:
```bash
grep -r "from .*const" custom_components/dreame_a2_mower --include='*.py' | wc -l
```
Should be close to the fan-in number for `const` (off-by-a-few is fine, this is import-style variance).

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 2 dependency graph"
```

---

## Task 4: Domain-concept ownership table

For each domain concept, identify the four touchpoints: where it's **acquired** (transport), **stored** (data structure), **transformed** (business logic), **rendered** (entity/visual). Surfaces split ownership.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 3)

- [ ] **Step 1: List the concepts**

Use this exact set (matches the audit-overview spec):

1. cloud_state — cloud-poll snapshot
2. mower_state — live device state (s1, s2 MIIO properties)
3. session — mowing session lifecycle (start → in-progress → finalize → archive)
4. map — base map (lawn boundary, zones, spots, edge, dock)
5. settings — user-toggleable cloud settings (rain, DnD, child lock, etc.)
6. schedule — mowing calendar
7. lidar — LiDAR PCD frames + obstacles
8. wifi — wifi sample archive + heatmap
9. observability — novel-token registry, freshness, log buffer

- [ ] **Step 2: For each concept, trace it**

For each concept, grep for key symbols and read enough to identify the four files:

Example for `cloud_state`:
```bash
grep -rln "cloud_state\|CloudState" custom_components/dreame_a2_mower --include='*.py' | head -10
```

- **Acquired:** which file calls the cloud API / parses the response
- **Stored:** which dataclass / structure holds it
- **Transformed:** which file applies it to mower state or derives sensors
- **Rendered:** which entity/camera surfaces it

- [ ] **Step 3: Write § 3 as a table**

Format:

```markdown
## 3. Domain-concept ownership

| Concept | Acquired | Stored | Transformed | Rendered |
|---|---|---|---|---|
| cloud_state | `cloud_client.py` (`fetch_*`) | `cloud_state.py` (`CloudState`) | `coordinator/_cloud_state.py` | `sensor.py` cloud-sourced sensors |
| mower_state | `mqtt_client.py` + `coordinator/_mqtt_handlers.py` | `mower/state.py` (`MowerState`) | `coordinator/_property_apply.py`, `mower/state_machine.py` | `sensor.py`, `binary_sensor.py`, `lawn_mower.py` |
| ... | | | | |
```

Any cell that names >1 file is a candidate for split-ownership flag — note these in § 4.5 (other cross-cutting smells).

- [ ] **Step 4: Validate every cited file exists**

Same cross-check as Task 2 Step 4:
```bash
for f in $(grep -oE '`[^`]+\.py`' docs/superpowers/specs/2026-05-19-integration-audit-meta.md | tr -d '`'); do
  test -f "custom_components/dreame_a2_mower/$f" -o -f "$f" || echo "MISSING: $f"
done
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 3 domain-concept ownership"
```

---

## Task 5: Cross-cutting smell — retry / poll / backoff loops

Find every place that implements its own retry-with-backoff or poll loop; surface as cross-cutting smell for Block 1.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 4.1)

- [ ] **Step 1: Search for retry / backoff patterns**

Run these greps and capture output:

```bash
cd custom_components/dreame_a2_mower
echo "--- while + sleep + retry"
grep -rln "while " --include='*.py' | xargs grep -l "asyncio.sleep\|time.sleep" 2>/dev/null
echo "--- retry/backoff symbols"
grep -rn "retry\|backoff\|max_attempts\|MAX_RETRY" --include='*.py' | grep -v test | head -40
echo "--- explicit attempt counters"
grep -rn "for attempt in\|attempt < \|tries += " --include='*.py' | head -40
```

- [ ] **Step 2: Categorise each hit**

For each retry/backoff location, record: `file:line — short description — pattern (e.g. "fixed sleep + counter", "exponential", "deadline-bounded")`.

- [ ] **Step 3: Write § 4.1**

Format:

```markdown
### 4.1 Retry / poll / backoff loops

Block-1 candidate: consolidate into one helper.

| Location | Pattern | Notes |
|---|---|---|
| `cloud_client.py:NNN` — `_auth_with_retry` | fixed 3-attempt loop, 2s delay | |
| `coordinator/_writes.py:NNN` — finalize-gate | deadline-bounded (30min, 10x, 60s) | well-bounded, model for helper |
| ... | | |
```

If there are <3 hits, write "Only N occurrences — not worth consolidating".

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 4.1 retry/poll patterns"
```

---

## Task 6: Cross-cutting smell — scheduling patterns

Find every use of HA's time-based scheduling (`async_track_time_interval`, `async_call_later`, `async_track_point_in_time`, `async_track_state_change`, etc.) plus any home-grown timers.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 4.2)

- [ ] **Step 1: Search**

```bash
cd custom_components/dreame_a2_mower
grep -rn "async_track_time_interval\|async_call_later\|async_track_point_in_time\|async_track_state_change\|create_task\|asyncio\.sleep" --include='*.py' | head -60
```

- [ ] **Step 2: Categorise**

For each: `file:line — purpose — interval / one-shot — owner (is it cancelled on unload?)`.

The "owner" column is the key: unscheduled tasks on unload are a memory-leak smell.

- [ ] **Step 3: Write § 4.2**

```markdown
### 4.2 Scheduling patterns

Block-1 candidate: confirm every interval/timer is cancelled on coordinator shutdown.

| Location | API | Purpose | Interval | Cancelled? |
|---|---|---|---|---|
| `coordinator/_refreshers.py:NN` | `async_track_time_interval` | 10-min cloud poll | 600s | yes — listener in `_listeners` |
| ... | | | | |
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 4.2 scheduling patterns"
```

---

## Task 7: Cross-cutting smell — error handling patterns

Identify the dominant error-handling shapes in the codebase: bare `except`, `except Exception`, custom exception types, error swallowing vs propagation.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 4.3)

- [ ] **Step 1: Search**

```bash
cd custom_components/dreame_a2_mower
echo "--- bare except (anti-pattern)"
grep -rn "^[[:space:]]*except:$\|^[[:space:]]*except[[:space:]]*:" --include='*.py' | head -30
echo "--- except Exception count by file"
grep -rln "except Exception" --include='*.py' | xargs -I{} sh -c 'echo "$(grep -c "except Exception" {}) {}"' | sort -rn | head -20
echo "--- custom exception types defined"
grep -rn "^class .*Error\b\|^class .*Exception\b" --include='*.py'
echo "--- _LOGGER.error / .exception usage"
grep -rcn "_LOGGER\.\(error\|exception\)" --include='*.py' | sort -t: -k2 -rn | head -20
```

- [ ] **Step 2: Write § 4.3**

Format:

```markdown
### 4.3 Error handling patterns

| Pattern | Count | Locations / Notes |
|---|---|---|
| Bare `except:` (anti-pattern) | N | `file:line` (list all if N ≤ 5; else top 5 + "...") |
| `except Exception` swallowing | N | top files |
| Custom exception types | N | list them |
| `_LOGGER.error` without re-raise | N | top files |

**Block disposition:** If bare-except count > 0 → Block 1 cleanup target. If
custom exception types are inconsistent (some Errors, some Exceptions) → flag
for Block 1 naming pass.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 4.3 error handling patterns"
```

---

## Task 8: Cross-cutting smell — large files & long functions

Flag every refactor candidate by size: files >800 LOC and functions >80 LOC.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 4.4)

- [ ] **Step 1: Find files >800 LOC**

Already in Task 2's module map. Copy those rows here as the file list (don't re-grep).

- [ ] **Step 2: Find functions >80 LOC**

Run:
```bash
cd custom_components/dreame_a2_mower
python3 <<'PY'
import ast, pathlib
root = pathlib.Path(".")
hits = []
for p in root.rglob("*.py"):
    if "__pycache__" in p.parts: continue
    try: tree = ast.parse(p.read_text())
    except: continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > 80:
                hits.append((length, str(p), node.lineno, node.name))
for L, p, lno, name in sorted(hits, reverse=True):
    print(f"{L:4d}  {p}:{lno}  {name}")
PY
```

Capture output.

- [ ] **Step 3: Write § 4.4**

```markdown
### 4.4 Large files & long functions

#### Files >800 LOC (refactor candidates)

| File | LOC | Block | Notes |
|---|---|---|---|
| `cloud_client.py` | 2197 | B1 | auth + RPC + blob + discovery — split candidate |
| `select.py` | 1990 | B3 | many small selects, split by domain group |
| ... | | | |

#### Functions >80 LOC

| File | Line | Function | LOC | Block |
|---|---|---|---|---|
| `coordinator/_property_apply.py` | NN | `_apply_s2_props` | 123 | B1 |
| ... | | | | |
```

The "Block" column maps each candidate to its target block (B1/B2/B3/B4) using the audit-overview's block scope definitions.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 4.4 large file & long function refactor targets"
```

---

## Task 9: Other cross-cutting smells + later-block backlog finalisation

Catch-all for anything you noticed during tasks 2-8 that doesn't fit § 4.1-4.4 but touches >2 blocks. Also finalise the later-block backlog section.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` (§ 4.5, § 5)

- [ ] **Step 1: Re-scan your notes**

Look back at every "I noticed X" thought from tasks 2-8. Anything that:
- touches >2 blocks, AND
- isn't already captured under § 4.1-4.4

goes in § 4.5.

Examples of what fits here: duplicated constant definitions across modules, two conflicting capitalisation styles, two ways of formatting log messages, two ways of representing the same data structure across module boundaries.

- [ ] **Step 2: Write § 4.5**

Format:

```markdown
### 4.5 Other cross-cutting smells

| Smell | Locations | Blocks affected |
|---|---|---|
| Two `MowerState` snapshot representations | `mower/state.py`, `mower/state_snapshot.py` | B2 |
| ... | | |
```

If empty, write "None spotted beyond § 4.1-4.4."

- [ ] **Step 3: Confirm § 5 contains everything spotted-but-deferred**

Anything you wrote down during the meta pass that:
- is *not* a cross-cutting smell, AND
- belongs to a specific Block (B1/B2/B3/B4)

goes here. Re-read § 3 (domain ownership) for any split-ownership flags that haven't been recorded yet.

Format:
```markdown
## 5. Later-block backlog

- [B1] cloud_client.py file split — see § 4.4
- [B2] orphan MowerState fields per existing state-machine-audit findings
- [B3] check entity-registry orphans from past rename history
- [B4] README still says "v1.0.0a release candidate"
- ...
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: § 4.5 other smells + § 5 later-block backlog"
```

---

## Task 10: Final consistency pass

Read the whole doc end-to-end, fix any inconsistencies, and flip the status from "in progress" to "complete".

**Files:**
- Modify: `docs/superpowers/specs/2026-05-19-integration-audit-meta.md`

- [ ] **Step 1: Read the whole doc**

Open it in your editor (or `cat` it). Read every section.

- [ ] **Step 2: Cross-validate**

Check:
1. **Every file path mentioned exists** —
   ```bash
   for f in $(grep -oE '`[^`]+\.(py|md|yaml|json)`' docs/superpowers/specs/2026-05-19-integration-audit-meta.md | tr -d '`' | sort -u); do
     if [ ! -f "$f" ] && [ ! -f "custom_components/dreame_a2_mower/$f" ]; then
       echo "MISSING: $f"
     fi
   done
   ```
   Expected: no MISSING output.

2. **Every LOC number matches** — spot-check 5 random rows from § 1 against
   `wc -l <path>`.

3. **§ 4.4 functions-over-80-LOC are still over 80 LOC** — spot-check 3 of
   them with:
   ```bash
   awk 'NR>=LN && /^def \|^async def /' <file>
   ```
   (or just open the file and count). Should still be >80 LOC unless someone
   edited the file mid-meta-pass.

4. **§ 3 domain ownership cells consistent with § 1 module map** — every
   filename in § 3 appears in § 1.

5. **§ 5 backlog labels** — every item starts with `[Bx]` for some x ∈ {1,2,3,4}.

- [ ] **Step 3: Fix any inconsistencies inline**

If anything fails the cross-validate, fix it. Don't move on with broken refs.

- [ ] **Step 4: Flip the status line**

Replace:
```markdown
**Status:** in progress — populated task-by-task per plan
```
with:
```markdown
**Status:** complete — 2026-05-NN
```
(use today's actual date in the YYYY-MM-DD slot)

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-19-integration-audit-meta.md
git commit -m "audit-meta: final consistency pass + status complete"
```

- [ ] **Step 6: Push**

```bash
git push origin main
```

(Per memory: HACS pulls from origin/main; meta-pass adds only docs, no
installable change, but pushing keeps history visible.)

---

## Done

The meta-pass output now lives at `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` and is the reference doc for Blocks 1-4.

**Next:** brainstorm Block 1 (Data pipeline). That cycle's spec will cite this doc by section number rather than re-deriving any of it.
