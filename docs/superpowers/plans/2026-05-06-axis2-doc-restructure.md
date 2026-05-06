# Axis 2 — Doc Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `g2408-protocol.md` and `TODO.md` from layered-findings into clean current-state docs, with all historical material moved to a new topic-clustered `g2408-research-journal.md`. Two dated side-files absorbed and deleted.

**Architecture:** Phase A creates skeletons; Phase B migrates cross-cutting prose to the slim protocol doc; Phase C distributes per-topic dated content to the journal; Phase D migrates TODO; Phase E absorbs the side-files; Phase F sweeps `inventory.yaml` cite paths; Phase G runs an orphan-paragraph completeness check. No content moves silently — every paragraph in the originals must be accounted for in the destinations.

**Tech Stack:** Plain markdown editing. One small Python helper script (`tools/journal_completeness_check.py`) for the orphan-paragraph audit (one-shot, not permanent CI). PyYAML for inventory cite updates. Pytest for the completeness-check tests.

---

## Setup notes for the implementer

- Working directory: `/data/claude/homeassistant/ha-dreame-a2-mower`.
- Spec: `docs/superpowers/specs/2026-05-06-axis2-doc-restructure-design.md`. Read it before starting.
- Source documents to migrate FROM:
  - `docs/research/g2408-protocol.md` — 1821 lines.
  - `docs/TODO.md` — 1082 lines.
  - `docs/research/2026-04-17-g2408-property-divergences.md` — 130 lines.
  - `docs/research/2026-04-23-iobroker-dreame-cross-reference.md` — 410 lines.
- Target documents:
  - `docs/research/g2408-protocol.md` — REPLACED IN PLACE with slim hybrid overview (~300-400 lines).
  - `docs/research/g2408-research-journal.md` — NEW topic-clustered journal.
  - `docs/TODO.md` — REPLACED IN PLACE with slim open-items-only list.
- Inventory + canonical doc are unchanged (axis 1 owns those).
- The project is on `main` and pushes to `origin/main` directly per the user's `feedback_cleanup_push_cadence` memory note. Push commits as you land them, not all at the end.
- The user has a token-cap subscription. Be efficient: avoid speculative reading of unrelated files; use grep + targeted Read with offsets for the large source docs.

---

## File structure summary

```
docs/research/g2408-protocol.md             # rewritten in place (slim hybrid)
docs/research/g2408-research-journal.md     # new
docs/TODO.md                                # rewritten in place (open items only)
docs/research/2026-04-17-g2408-property-divergences.md     # deleted
docs/research/2026-04-23-iobroker-dreame-cross-reference.md  # deleted
docs/research/inventory/inventory.yaml      # edited only for protocol_doc cite paths
docs/research/inventory/generated/g2408-canonical.md        # regenerated after inventory edits
tools/journal_completeness_check.py         # new (one-shot audit)
tests/tools/test_journal_completeness.py    # new (tests for the audit)
tests/tools/fixtures/                       # new completeness-check fixtures
```

---

## Task 1: Phase A — Create skeletons (slim protocol, journal, slim TODO)

**Files:**
- Modify: `docs/research/g2408-protocol.md` (write skeleton; old content stashed mid-task as `g2408-protocol.md.OLD` then removed at end of phase)
- Create: `docs/research/g2408-research-journal.md`
- Modify: `docs/TODO.md` (write skeleton; old content stashed as `TODO.md.OLD` then removed at end of phase)

The skeletons are placeholders with the right top-level structure. Phase B-D fills them in. Stashing old content mid-task lets later phases grep the OLD files; the stashes are removed at end of Phase G.

- [ ] **Step 1: Stash old source files (preserves them as `.OLD` siblings during migration)**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
cp docs/research/g2408-protocol.md docs/research/g2408-protocol.md.OLD
cp docs/TODO.md docs/TODO.md.OLD
```

These `.OLD` files are working copies the migration phases grep against. They'll be deleted in Task 18 (Phase G acceptance).

- [ ] **Step 2: Write the slim protocol doc skeleton**

Replace `docs/research/g2408-protocol.md` with:

```markdown
# Dreame A2 (`g2408`) Protocol — Overview

This is the cross-cutting reference for the `g2408` protocol. For
**slot-by-slot detail** (every property / event / action / CFG key /
heartbeat byte / telemetry field / etc.) see the canonical doc:

- **`docs/research/inventory/generated/g2408-canonical.md`** — generated
  from `docs/research/inventory/inventory.yaml` (the source of truth).
- **`docs/research/inventory/README.md`** — how to read and extend the
  inventory.

For the **history of how we figured each thing out** (hypothesis cycles,
deprecated readings, dated findings) see the research journal:

- **`docs/research/g2408-research-journal.md`** — topic-clustered.

This file holds only the cross-cutting prose that doesn't fit per-slot
or per-topic: transport-layer architecture, OSS fetch flow, coordinate-
frame math, and the contributor-facing PROTOCOL_NOVEL guide.

---

## Table of contents

1. [Transport layer](#1-transport-layer)
2. [Coordinate frame](#2-coordinate-frame)
3. [Routed-action surface](#3-routed-action-surface)
4. [OSS fetch architecture](#4-oss-fetch-architecture)
5. [PROTOCOL_NOVEL — what to report when](#5-protocol_novel--what-to-report-when)
6. [Confirmed working — live status](#6-confirmed-working--live-status)
7. [See also](#7-see-also)

---

## 1. Transport layer

_(Filled in Phase B from the OLD doc's §1.)_

## 2. Coordinate frame

_(Filled in Phase B from the OLD doc's §3.1 sub-section + cloud-map-geometry.md cross-reference.)_

## 3. Routed-action surface

_(Filled in Phase B from the OLD doc's §6.2.)_

## 4. OSS fetch architecture

_(Filled in Phase B from the OLD doc's §7 — diagram + flow only, not per-slot details.)_

## 5. PROTOCOL_NOVEL — what to report when

_(Filled in Phase B from the OLD doc's §7.5.)_

## 6. Confirmed working — live status

_(Filled in Phase D from the OLD TODO.md's "Live-confirmed" bullet list.)_

## 7. See also

- `docs/research/inventory/README.md`
- `docs/research/inventory/generated/g2408-canonical.md`
- `docs/research/g2408-research-journal.md`
- `docs/research/cloud-map-geometry.md` — coordinate-frame math, renderer-side
- `docs/TODO.md` — open work list
```

- [ ] **Step 3: Write the journal skeleton**

Create `docs/research/g2408-research-journal.md`:

```markdown
# Dreame A2 (`g2408`) — Research Journal

Topic-clustered record of how each piece of the g2408 protocol got
figured out. Each topic carries a "Quick answer" of the current state,
a dated timeline of hypotheses and confirmations, deprecated readings
kept for traceability, and cross-references to inventory rows + canonical
chapters.

For **current state of any slot** see the canonical doc:
`docs/research/inventory/generated/g2408-canonical.md`.

For **the architectural overview** see `docs/research/g2408-protocol.md`.

For **open work** see `docs/TODO.md`.

---

## Topics

1. [s1p4 telemetry decoder evolution](#s1p4-telemetry-decoder-evolution)
2. [s1p1 byte[10] bit 1 saga (safety_alert_active)](#s1p1-byte10-bit-1-saga-safety_alert_active)
3. [s1p1 byte[3] bit 7 PIN-required clarification](#s1p1-byte3-bit-7-pin-required-clarification)
4. [Phase-byte semantics (s1p4 byte[8])](#phase-byte-semantics-s1p4-byte8)
5. [s2p1 mode + s2p2 state codes — what's enum vs error](#s2p1-mode--s2p2-state-codes--whats-enum-vs-error)
6. [s2p51 multiplexed config — disambiguation evolution](#s2p51-multiplexed-config--disambiguation-evolution)
7. [Edge-mow FTRTS + wheel-bind discovery (2026-05-05)](#edge-mow-ftrts--wheel-bind-discovery-2026-05-05)
8. [`s2p50` op-code catalog — incremental decode](#s2p50-op-code-catalog--incremental-decode)
9. [Map-fetch flow — `s6p1` / event_occured / OSS](#map-fetch-flow--s6p1--event_occured--oss)
10. [`cfg_individual` MISTA reversal (2026-05-06)](#cfg_individual-mista-reversal-2026-05-06)
11. [g2408 vs upstream divergence](#g2408-vs-upstream-divergence)
12. [apk cross-walk findings](#apk-cross-walk-findings)
13. [Recently shipped — version timeline](#recently-shipped--version-timeline)
14. [Live-confirmed status board](#live-confirmed-status-board)

---

## s1p4 telemetry decoder evolution

> **Quick answer (current state):** _(filled in Phase C)_

### Timeline

_(filled in Phase C from OLD g2408-protocol.md §3.1-3.3 dated content + alpha.98 fix story)_

### Cross-references

- Inventory: `s1p4_33b_x_mm`, `s1p4_33b_y_mm`, `s1p4_33b_phase_raw`, `s1p4_33b_distance_dm`, `s1p4_33b_total_area_centiares`, `s1p4_33b_area_mowed_centiares`, `s1p4_8b_heading_byte`, `s1p4_10b_unknown_6_7`
- Canonical: § Telemetry (s1p4) fields, § Telemetry frame variants

---

## s1p1 byte[10] bit 1 saga (safety_alert_active)

> **Quick answer (current state):** _(filled in Phase C)_

### Timeline

_(filled in Phase C from OLD TODO.md "byte[10] bit 1 semantics" section + g2408-protocol §3.4)_

### Deprecated readings

_(filled in Phase C — wrong hypotheses crossed out)_

### Cross-references

- Inventory: `s1p1_b10_bit1`, `s1p1_b10_bit7`, `s1p1_b3_bit7`
- Canonical: § Heartbeat (s1p1) bytes

---

## s1p1 byte[3] bit 7 PIN-required clarification

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## Phase-byte semantics (s1p4 byte[8])

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## s2p1 mode + s2p2 state codes — what's enum vs error

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## s2p51 multiplexed config — disambiguation evolution

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## Edge-mow FTRTS + wheel-bind discovery (2026-05-05)

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## `s2p50` op-code catalog — incremental decode

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## Map-fetch flow — `s6p1` / event_occured / OSS

> **Quick answer (current state):** _(filled in Phase C)_

_(template same as above; filled in Phase C)_

---

## `cfg_individual` MISTA reversal (2026-05-06)

> **Quick answer (current state):** Mission-status endpoint MISTA returned r=-1 in
> cloud dumps 1 and 2, then a successful payload `{fin:0, prg:0, status:[[1,-1]], total:0}`
> in dump 3. Established empirically that r=-1 / r=-3 responses are stateful or
> transient, NOT proof of feature absence. Triggered an axis-1 hardening pass that
> downgraded all 7 `not_on_g2408:true` rows to `decoded:hypothesized` and added a
> consistency-check audit that catches this drift class.

### Timeline

- **2026-05-04** — first cloud dump captured. AIOBS, MAPD, MAPI, MITRC, OBS, PRE, MISTA
  all returned errors (r=-3 or r=-1). Inventory rows marked `not_on_g2408: true`,
  `decoded: confirmed`.
- **2026-05-05** — second dump captured; same error responses; conclusion held.
- **2026-05-06** — third dump captured; MISTA returned a valid payload. Reviewer
  spotted the contradiction during axis-2 brainstorming.
- **2026-05-06** — axis-1 hardening pass: all 7 rows downgraded to
  `decoded: hypothesized`, `not_on_g2408: false`. Consistency-check audit added
  (`tools/inventory_audit.py --consistency`) that flags any `not_on_g2408:true` row
  with an `ok` response in any dump. Three new tests in
  `tests/tools/test_inventory_audit_probe.py`. Acceptance criterion #12 added.

### Deprecated readings

- ~~"r=-3 means the endpoint is not supported on this firmware"~~ — wrong; r=-3 is
  stateful or transient. Sample-of-3 was insufficient.
- ~~"endpoints returning errors should be marked `not_on_g2408: true`"~~ — wrong;
  insufficient negative-evidence threshold. New rule: only mark `not_on_g2408: true`
  when there's a positive corroborating signal (apk explicitly says "vacuum-only",
  or the integration tested a known-write and the device rejected it).

### Cross-references

- Inventory rows: `MISTA`, `AIOBS`, `MAPD`, `MAPI`, `MITRC`, `OBS`, `PRE` (the
  `cfg_individual.PRE` row, distinct from `cfg_keys.PRE`)
- Canonical: § cfg_individual endpoints
- Audit code: `tools/inventory_audit.py` `_consistency_check` function
- Spec: `docs/superpowers/specs/2026-05-05-g2408-protocol-inventory-design.md` §6
  acceptance criterion #12

---

## g2408 vs upstream divergence

> **Quick answer (current state):** _(filled in Phase E from `2026-04-17-g2408-property-divergences.md`)_

_(template; filled in Phase E)_

---

## apk cross-walk findings

> **Quick answer (current state):** _(filled in Phase E from residuals of `2026-04-23-iobroker-dreame-cross-reference.md`)_

_(template; filled in Phase E)_

---

## Recently shipped — version timeline

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Recently shipped (a52 → a87)" section, with each version distributed under the topic it touched. This top-level section keeps the chronological view; per-topic context lives in each topic's Timeline.)_

---

## Live-confirmed status board

> **Quick answer (current state):** _(filled in Phase D)_

_(filled in Phase D from OLD TODO.md "Live-confirmed" bullet list)_
```

- [ ] **Step 4: Write the slim TODO skeleton**

Replace `docs/TODO.md` with:

```markdown
# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
For overall protocol architecture see `docs/research/g2408-protocol.md`.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

_(filled in Phase D from OLD TODO.md "Open" section, items only)_

## In-progress

_(filled in Phase D — items the user has started but not completed)_

## Blocked

_(filled in Phase D — items waiting on external evidence, e.g., firmware-update capture)_
```

- [ ] **Step 5: Verify the skeletons are well-formed markdown**

```bash
# Confirm all three files exist and parse as markdown (no triple-fence drift):
for f in docs/research/g2408-protocol.md docs/research/g2408-research-journal.md docs/TODO.md; do
  echo "=== $f ==="
  python -c "
import pathlib
content = pathlib.Path('$f').read_text()
fences = content.count('\`\`\`')
print(f'  fence count: {fences} (must be even)')
print(f'  line count: {len(content.splitlines())}')
assert fences % 2 == 0, f'unbalanced code fences in $f'
"
done
```

Expected: each file has an even fence count (no broken code blocks).

- [ ] **Step 6: Commit Phase A**

```bash
git add docs/research/g2408-protocol.md docs/research/g2408-research-journal.md docs/TODO.md docs/research/g2408-protocol.md.OLD docs/TODO.md.OLD
git commit -m "docs(axis2): Phase A — slim doc skeletons

Stash OLD g2408-protocol.md and TODO.md as .OLD siblings while
migration runs. Replace in-place with skeletons:
- g2408-protocol.md: hybrid overview shell with TOC
- g2408-research-journal.md: topic-clustered shell with 14 topic
  templates seeded; MISTA reversal topic populated as a worked
  example
- TODO.md: open-items-only shell

Phase B-G fill in the migration. The .OLD files are working
copies removed at end of Phase G acceptance."
```

---

## Task 2: Phase B — Migrate § Transport (cross-cutting prose)

**Files:**
- Modify: `docs/research/g2408-protocol.md` (replace `## 1. Transport layer` placeholder)
- Reference: `docs/research/g2408-protocol.md.OLD` §1 (lines 15-87)

- [ ] **Step 1: Read OLD §1 to capture the canonical prose**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
sed -n '15,87p' docs/research/g2408-protocol.md.OLD
```

The output is the source for this section. It covers:
- Two-channel (cloud MQTT push + cloud HTTP RPC) + BT third channel
- Cloud endpoints table for region `eu`
- The `80001` failure mode explanation (section 1.2 in the OLD doc)

- [ ] **Step 2: Replace the `## 1. Transport layer` placeholder in slim doc**

Open `docs/research/g2408-protocol.md` and replace the line `_(Filled in Phase B from the OLD doc's §1.)_` with the lifted content. The structure inside the section should mirror OLD §1.1 and §1.2 as sub-sections:

```markdown
## 1. Transport layer

Two communication channels reach the mower, **plus a mobile-only third one**:

| Channel | Direction | Works on g2408? |
|---|---|---|
| Dreame cloud MQTT — device → cloud | **push from mower** | ✅ consistently |
| Dreame cloud HTTP `sendCommand` — cloud → device | **commands to mower** | ❌ returns HTTP code `80001` ("device unreachable") even while actively mowing |
| Bluetooth (phone ↔ mower direct) | **config writes from app** | ✅ but invisible from cloud/HA |

The HA integration's `protocol.py` has fallback logic for the HTTP failure path. In
practice the integration is **read-mostly** on g2408: telemetry arrives reliably via
the MQTT push; any property the mower exposes only in response to an HTTP poll is
effectively unavailable.

### 1.1 Cloud endpoints (region `eu`)

| Purpose | Endpoint |
|---|---|
| Auth | `https://eu.iot.dreame.tech:13267/dreame-user-iot/iotuserbind/` |
| Device info | `POST /dreame-user-iot/iotuserbind/device/info` |
| OTC info | `POST /dreame-user-iot/iotstatus/devOTCInfo` |
| MQTT broker | `10000.mt.eu.iot.dreame.tech:19973` (TLS) |
| MQTT status topic | `/status/<did>/<mac-hash>/dreame.mower.g2408/eu/` |
| `sendCommand` | `POST /dreame-iot-com-10000/device/sendCommand` (fails with 80001) |

### 1.2 `80001` failure mode — expected, not a bug

`cloud → mower` RPCs (`set_properties`, `action`, `get_properties`) fail as
`{"code": 80001, "msg": "device unreachable"}` **even while** the mower is
pushing live telemetry over MQTT on the same connection. The HA log surfaces
this as:

```
WARNING ... Cloud send error 80001 for get_properties (attempt 1/1): 设备可能不在线，指令发送超时。
WARNING ... Cloud request returned None for get_properties (device may be in deep sleep)
WARNING ... Cloud send error 80001 for action (attempt 1/3): 设备可能不在线，指令发送超时。
WARNING ... Cloud request returned None for action (device may be in deep sleep)
```

**This is the g2408's normal behaviour, not a transient error.** Treat these
WARNINGs as signal that the cloud-RPC write path is unavailable. Don't open
issues for them; they are already documented here. They persist across every
observed session (373 instances in one ~90 min session observation).

**Scope of what 80001 breaks:**
- ❌ `lawn_mower.start` / `.pause` / `.dock` service calls route via `action()` → hit 80001, silent no-op from the user's perspective.
- ❌ `set_property` writes (config changes) route the same way.
- ❌ `get_properties(...)` one-shot pulls.

**Scope of what still works** (different cloud endpoint, different auth path):
- ✅ MQTT property push from the mower → HA coordinator (the whole read pipeline).
- ✅ Session-summary JSON fetch via `get_interim_file_url` + OSS signed URL.
- ✅ LiDAR PCD fetch via the same getDownloadUrl / OSS path.
- ✅ Login / device discovery / getDevices.

The integration's primary write path on g2408 is therefore the **routed-action surface** (§3 below), which uses a different RPC envelope and works reliably.
```

- [ ] **Step 2 verification: render markdown locally to confirm formatting**

```bash
python -c "
import pathlib
content = pathlib.Path('docs/research/g2408-protocol.md').read_text()
sect = content.split('## 1. Transport layer')[1].split('## 2.')[0]
print(f'§1 lines: {len(sect.splitlines())}')
assert '80001' in sect
assert 'eu.iot.dreame.tech' in sect
print('ok')
"
```

Expected: `§1 lines: ~70`, `ok`.

- [ ] **Step 3: Commit Phase B-1**

```bash
git add docs/research/g2408-protocol.md
git commit -m "docs(axis2): Phase B-1 — migrate § Transport prose

Lifted verbatim from OLD g2408-protocol.md §1.1-1.2:
- Channel matrix (MQTT push + cloud HTTP RPC + BT side channel)
- eu cloud endpoints table
- 80001 failure-mode explanation + scope-of-impact
- Pointer to §3 routed-action surface as the working write path"
```

---

## Task 3: Phase B — Migrate § Coordinate frame, § Routed-action surface, § OSS architecture, § PROTOCOL_NOVEL

**Files:**
- Modify: `docs/research/g2408-protocol.md` (replace 4 remaining `_(Filled in Phase B...)_` placeholders)
- Reference: `docs/research/g2408-protocol.md.OLD` §3.1 sub-section, §6.2, §7, §7.5

- [ ] **Step 1: Identify the source line ranges in OLD doc**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -n "^### 3.1\|^#### Coordinate frame\|^#### Y-axis\|^### 6.2\|^## 7\|^### 7.5" docs/research/g2408-protocol.md.OLD
```

Use the line numbers to read each region with `Read` (offset + limit).

- [ ] **Step 2: Lift `## 2. Coordinate frame`**

Source: OLD doc, "#### Coordinate frame (charger-relative)" sub-section under §3.1, plus the immediately-following "#### Y-axis calibration" sub-section.

Open `docs/research/g2408-protocol.md` and replace the placeholder `_(Filled in Phase B from the OLD doc's §3.1 sub-section + cloud-map-geometry.md cross-reference.)_` with:

```markdown
## 2. Coordinate frame

The mower reports position in a **dock-relative frame**, defined by the charging-
station's pose. All s1p4 telemetry, MAP boundary polygons, exclusion zones, and
session-summary tracks share this frame.

- **Origin (0, 0) = charging station.** Verified by convergence on return-to-dock.
- **+X axis points toward the house** (the nose direction when the mower is docked).
  -X points away from the house into the lawn.
- **±Y is perpendicular**, left/right when facing the house.
- The lawn polygon sits at whatever angle fences happen to take relative to this
  mower frame — there is no rotation applied per session.
- X is in **cm** at bytes [1-2]. Y is in **mm** at bytes [3-4]. The axes use
  different scales on the wire — one of g2408's mild quirks. The s1p4 decoder
  normalises both to mm in `protocol/telemetry.py`.

### Y-axis calibration

The Y wheel's encoder reports ~1.6× the true distance. Multiply raw `y_mm` by
**0.625** (configurable per-install) to land in real metres. X needs no
calibration.

Origin of the 0.625 factor is tape-measure-verified across two sessions. The
constant applies regardless of which axis is currently sweeping, so it's
firmware / encoder — not turn-drift accumulation. Cross-tested 2026-04-17 under
both X-axis and Y-axis mowing patterns.

> Renderer-side coordinate math (camera transforms, image rotations, base-map
> calibration_points) lives in `docs/research/cloud-map-geometry.md`. The
> protocol-level frame definition is here; the rendering pipeline math is there.
```

- [ ] **Step 3: Lift `## 3. Routed-action surface`**

Source: OLD doc §6.2 (the m+t+o envelope explanation, NOT the per-key tables).

Open `docs/research/g2408-protocol.md` and replace the placeholder `_(Filled in Phase B from the OLD doc's §6.2.)_` with:

```markdown
## 3. Routed-action surface

g2408's `cloud → mower` RPC tunnel returns 80001 (§1.2) for direct
`(siid, aiid)` action calls. The integration's **working write path** is the
routed-action wrapper:

```
action {
  siid: 2,
  aiid: 50,
  in: [{ m: 'g'|'s'|'a'|'r', t: <target>, d: <optional payload> }]
}
```

`m` is the mode and `t` is the target; the result lands at `result.out[0]`.

| `m` | Mode | Examples |
|---|---|---|
| `g` | get | `t:'CFG'` returns the all-keys settings dict; `t:'DOCK'` returns dock state |
| `s` | set | `t:'WRP'` writes rain protection; `t:'PRE'` writes mowing preferences |
| `a` | action | `o:100` start mow; `o:101` edge mow; `o:102` zone mow; `o:103` spot mow |
| `r` | remote | joystick control during Manual mode (BT-mediated, mostly invisible to MQTT) |

The integration's `protocol/cfg_action.py` provides typed wrappers (`get_cfg`,
`get_dock_pos`, `set_pre`, `call_action_op`).

> **Per-target detail** — every CFG key, every cfg_individual endpoint, every
> opcode — lives in the canonical doc:
> `docs/research/inventory/generated/g2408-canonical.md`. Search for the
> chapters: "CFG keys", "cfg_individual endpoints", "Routed-action opcodes".

### URL nuance

The endpoint shape is:

```
https://eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand
```

The `-10000` suffix is hardcoded for Dreame brand devices; `-20000` is for Mova
brand. The integration's `protocol.py` falls back to the apk-hardcoded `-10000`
when the bind-info-derived host is empty (race in the connect callback).
```

- [ ] **Step 4: Lift `## 4. OSS fetch architecture`**

Source: OLD doc §7 (the diagram + fetch-flow prose, NOT the per-event piid catalog).

Open `docs/research/g2408-protocol.md` and replace the placeholder `_(Filled in Phase B from the OLD doc's §7 — diagram + flow only, not per-slot details.)_` with:

```markdown
## 4. OSS fetch architecture

The A2 does **not** push the map as a single MQTT blob the way some older Dreame
devices do. Instead:

```
┌─────────┐   1. map ready    ┌──────────────┐   2. upload    ┌──────────────┐
│  Mower  │ ───────────────→  │ Dreame cloud │ ─────────────→ │ Aliyun OSS   │
└─────────┘   (MQTT push)     └──────────────┘                │ bucket       │
     │                                                        └──────────────┘
     │ 3. push s6p1, s6p3 via MQTT                                      ▲
     │    - s6p1 value cycles 200 ↔ 300 to signal "new map available"  │
     │    - s6p3 carries the object-name key inside the bucket         │
     ▼                                                                  │
┌─────────┐   4. observe s6p3         ┌──────────────┐   5. HTTP fetch  │
│   HA    │ ─────────────────────────▶ │ OSS signed  │ ─────────────────┘
│  fork   │   getFileUrl(object_name)  │ URL (short- │
└─────────┘ ◀───────────────────────── │  lived)     │
                  PNG map data         └──────────────┘
```

Three distinct OSS-mediated payloads share this flow:

1. **MAP blob** — pushed when the mower wants the cloud to ingest a new map version.
   Trigger: `s6p1 = 300` at recharge-leg-start.
2. **Session-summary JSON** — pushed once per completed mowing session.
   Trigger: `event_occured siid=4 eiid=1`. The OSS object key arrives as the event's
   piid=9 argument.
3. **LiDAR point cloud (PCD)** — pushed when the user taps "Download LiDAR map" in the
   Dreame app and the scan has changed since last upload. Trigger: `s99p20` carries
   the OSS object key; `s2p54` reports 0..100% upload progress.

### The signed-URL fetch

The Dreame cloud has two signed-URL endpoints; the one that works on g2408 is the
**interim** endpoint:

```
POST https://eu.iot.dreame.tech:13267/dreame-user-iot/iotfile/getDownloadUrl
body: {"did":"<did>","model":"dreame.mower.g2408","filename":"<obj-key>","region":"eu"}
→ {"code":0, "data":"https://dreame-eu.oss-eu-central-1.aliyuncs.com/iot/tmp/…?Expires=…&Signature=…", "expires_time":"…"}
```

The signed URL is valid for ~1 hour and carries no auth; `GET` retrieves the payload.
The alternative endpoint `getOss1dDownloadUrl` returns 404 on g2408 — that bucket is
empty for this product.

> **Per-event piid catalogs**, **session-summary JSON schema**, **MAP top-level keys**,
> and **LiDAR PCD format** all live in the canonical doc:
> `docs/research/inventory/generated/g2408-canonical.md`. This file's job is the
> architectural shape; the data dictionaries belong with the inventory.
```

- [ ] **Step 5: Lift `## 5. PROTOCOL_NOVEL — what to report when`**

Source: OLD doc §7.5 (the contributor-facing WARNING catalog).

Open `docs/research/g2408-protocol.md` and replace the placeholder `_(Filled in Phase B from the OLD doc's §7.5.)_` with:

```markdown
## 5. PROTOCOL_NOVEL — what to report when

Everything below logs at WARNING level, exactly **once per process lifetime per
distinct shape**, at HA's default `logger.default: warning` — so they're safe
against log flooding and visible without any extra logger tuning.

| Message prefix | Trigger | What it tells us |
|---|---|---|
| `[PROTOCOL_NOVEL] MQTT message with unfamiliar method=…` | MQTT message arrives with a method other than `properties_changed` or `event_occured` (e.g. `props`, `request`). | Firmware has a verb we don't decode yet. |
| `[PROTOCOL_NOVEL] properties_changed carried an unmapped siid=… piid=…` | Push arrived on an (siid, piid) not in the property mapping and not intercepted by a specific handler. | New field on an existing service — either a new feature or a firmware revision. |
| `[PROTOCOL_NOVEL] event_occured siid=… eiid=… with piids=…` | First occurrence of an (siid, eiid) combo OR known combo with a new piid in the argument list. | New event class, or existing event gained a field (e.g. a new reason code). |
| `[PROTOCOL_NOVEL] s2p2 carried unknown value=…` | `s2p2` push outside the known set (see canonical § s2p2 state codes). | Firmware emitted a state code we don't recognise. |
| `[PROTOCOL_NOVEL] s1p4 short frame len=…` | `s1p4` push with a length other than 8 / 10 / 33. Raw bytes included in the log line. | Firmware emitted a telemetry frame variant we haven't reverse-engineered. |

When a user sees any of these, the right action is to open an issue at
[github.com/okolbu/ha-dreame-a2-mower/issues](https://github.com/okolbu/ha-dreame-a2-mower/issues)
with the log line quoted verbatim — the raw values in the message are exactly
what's needed to extend decoders.

**Not a `[PROTOCOL_NOVEL]` — don't report:**

- `Cloud send error 80001 for get_properties/action (attempt X/Y)`
- `Cloud request returned None for get_properties/action (device may be in deep sleep)`

These are the g2408's expected response to cloud-RPC writes (§1.2). They will repeat
every time the integration tries a write (buttons, services, config changes).
```

- [ ] **Step 6: Verify the slim protocol doc length is in budget**

```bash
wc -l docs/research/g2408-protocol.md
```

Expected: 250-500 lines. If under 250, the prose may be too terse — re-check that you lifted full sub-sections. If over 500, you've pulled per-slot detail that belongs in canonical — go back and trim.

- [ ] **Step 7: Commit Phase B-2**

```bash
git add docs/research/g2408-protocol.md
git commit -m "docs(axis2): Phase B-2 — migrate § Coordinate frame / Routed-action / OSS / PROTOCOL_NOVEL

Filled in the remaining four sections of the slim hybrid overview
from OLD g2408-protocol.md §3.1, §6.2, §7, §7.5. Cross-references
out to canonical for per-slot detail and to cloud-map-geometry for
renderer-side math."
```

---

## Task 4: Phase C — Distribute dated content to journal (s1p4 telemetry topic)

**Files:**
- Modify: `docs/research/g2408-research-journal.md` (fill `## s1p4 telemetry decoder evolution` topic)
- Reference: `docs/research/g2408-protocol.md.OLD` §3.1, §3.2, §3.3 dated entries

- [ ] **Step 1: Identify dated content in OLD §3.1-3.3**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
sed -n '143,500p' docs/research/g2408-protocol.md.OLD | grep -n "^####\|2026-04\|2026-05\|alpha\.[0-9]\|HISTORICAL\|earlier" | head -40
```

The output identifies the date-stamped findings that belong in the journal.

- [ ] **Step 2: Fill in the topic's "Quick answer"**

Open `docs/research/g2408-research-journal.md` and replace the placeholder `> **Quick answer (current state):** _(filled in Phase C)_` under `## s1p4 telemetry decoder evolution` with:

```markdown
> **Quick answer (current state):** s1p4 carries 33-byte mowing telemetry,
> 8-byte beacon, or 10-byte BUILDING-save markers. Bytes 0-5 use a 20-bit
> packed encoder (apk-corrected in alpha.98); X is in mm post-decode (was
> mistakenly named `x_cm`); Y has a per-install 0.625 calibration factor.
> 33-byte field decode is in canonical; the per-byte history is here.
```

- [ ] **Step 3: Fill in the topic's "Timeline"**

Replace `_(filled in Phase C from OLD g2408-protocol.md §3.1-3.3 dated content + alpha.98 fix story)_` with:

```markdown
- **2026-04-17** — first probe corpus captured. 33-byte and 8-byte variants
  observed; 10-byte not yet seen. Initial decoder lifted from upstream Tasshack
  with int16_le for X (cm) and Y (mm). Worked for small coordinates.
- **2026-04-20** — full-day capture (07:58 → 12:33). Two auto-recharge interrupts.
  Confirmed `phase_raw` byte[8] advances monotonically through the firmware's
  pre-planned job sequence (per-zone area-fill, then edge passes, then
  return-home transport). Earlier "MOWING / TRANSIT / PHASE_2 / RETURNING" enum
  retired; `phase_raw` now exposed as a raw int diagnostic.
- **2026-04-22** — blades-down vs blades-up detection: `phase` byte[8] does NOT
  work (a 50 m blades-up dock-resume drive AND the subsequent mowing both had
  `phase = 2`). `area_mowed_cent` (bytes 29-30) WORKS PERFECTLY — frame-to-frame
  delta is a one-bit blades-on/off signal. Integration uses this in
  `live_map.DreameA2LiveMap` to tag captured path points with a `cutting` flag.
- **2026-04-24** — apk decompilation reveals bytes 1-5 are 20-bit signed packed,
  not int16_le. Validated against probe-log corpus (5586 consecutive-pair
  samples): median angular error 13°, 54% under 15° at the heading byte (8b
  variant byte[6]). Decoder bug found: Y was 1/16× the true value; downstream
  `* 0.625` compensation patches were masking the bug for small lawns.
- **2026-04-29** — alpha.98 ships the apk-corrected decoder. X and Y both in
  map-scale mm. All scattered `0.625` and `0.000625` magic factors removed.
  All probe-corpus regression frames re-validated.
- **2026-04-30** — confirmed `start_index` (bytes 7-9 uint24 LE) is a path-point
  sequence counter — 5,796 monotonic increments vs only 10 decrements across
  14,684 transitions. Decrements all look like new-session resets.
- **2026-05-05** — confirmed the post-FTRTS dock-nav phase uses 8-byte beacon
  frames (~25 consecutive frames over ~90 s during run 1's recovery). 8-byte
  beacons fire in four distinct contexts: idle/docked, leg-start preamble,
  BUILDING (manual map-learn), and post-FTRTS dock-nav.

### Deprecated readings

- ~~`Phase` enum: MOWING / TRANSIT / PHASE_2 / RETURNING~~ — wrong; phase byte
  is a per-task-plan zone index, not a transit/cutting discriminator. Retired
  2026-04-20.
- ~~Y-axis raw decode is `int16_le` at bytes [3-4]~~ — wrong; Y is the upper
  bits of a 20-bit packed value at bytes [1-5]. The old decode happened to give
  values 16× the truth, partially compensated by scattered `0.625` factors.
  Fixed in alpha.98.
- ~~Bytes [10-21] are motion vectors (vx, vy, ω, etc.)~~ — wrong; per apk they
  are three "delta" pairs (recent path history); per probe data Δ2 saturates
  more than Δ1/Δ3 in a way the apk doesn't explain. Decoder still pending; the
  integration ignores these bytes.
- ~~`area_mowed_cent` is a 16-bit value at bytes 29-30~~ — incomplete; per apk
  it's uint24 [29-31]. For lawns ≤ 655 m² the upper byte is always 0 so the
  16-bit decode happens to work. Lawns > 655 m² will overflow; open question.
```

- [ ] **Step 4: Verify cross-references already populated by skeleton**

The Cross-references block was seeded by the Phase A skeleton; confirm it lists `s1p4_33b_*` plus heading_byte plus `s1p4_10b_unknown_6_7`. Spot-check by grep.

```bash
sed -n '/^## s1p4 telemetry decoder evolution/,/^## /p' docs/research/g2408-research-journal.md | grep "Inventory:" | head -1
```

Expected: a single `Inventory: s1p4_33b_x_mm, ...` line.

- [ ] **Step 5: Verify the journal still parses**

```bash
python -c "
import pathlib
content = pathlib.Path('docs/research/g2408-research-journal.md').read_text()
fences = content.count('\`\`\`')
print(f'fence count: {fences}')
assert fences % 2 == 0, 'unbalanced fences'
print('ok')
"
```

- [ ] **Step 6: Commit Phase C-1**

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase C-1 — s1p4 telemetry decoder evolution topic

Lifted dated content from OLD g2408-protocol.md §3.1-3.3 into the
journal's first topic. Quick answer + 7-entry timeline + 4
deprecated readings (Phase enum retirement, Y-axis decoder bug,
motion-vectors-not-actually-velocity, uint16-vs-uint24 area
encoding). Cross-references to inventory rows + canonical chapter."
```

---

## Task 5: Phase C — s1p1 byte[10] bit 1 saga + byte[3] bit 7 PIN-required

**Files:**
- Modify: `docs/research/g2408-research-journal.md` (fill 2 topic sections)
- Reference: `docs/TODO.md.OLD` "byte[10] bit 1 semantics — pinned down 2026-05-04" + sibling section; `docs/research/g2408-protocol.md.OLD` §3.4

- [ ] **Step 1: Identify the source content in TODO.md.OLD**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -n "byte\[10\] bit 1\|byte\[3\] bit 7\|safety_alert\|emergency_stop\|PIN" docs/TODO.md.OLD | head -25
```

- [ ] **Step 2: Read the relevant lines and extract the saga**

```bash
sed -n '345,510p' docs/TODO.md.OLD
```

Use the output to fill the two journal topics. Each follows the timeline + deprecated readings + cross-references shape.

- [ ] **Step 3: Fill `## s1p1 byte[10] bit 1 saga (safety_alert_active)`**

Open `docs/research/g2408-research-journal.md` and replace the topic's placeholders. Lift the timeline from the 5-test controlled series documented in OLD TODO.md (2026-05-04). Quick answer:

```markdown
> **Quick answer (current state):** byte[10] bit 1 is a one-shot active-alert
> flag. Sets ~1 s after byte[3] bit 7 sets (i.e. shortly after a safety event);
> self-clears 30-90 s later regardless of state — including while the lid is
> still open and PIN has not been entered. Variable timer (4 / 18 / 33 / 53 / 77 s
> observed). Pairs with the Dreame app's "Emergency stop activated" push
> notification + the mower's red LED + voice prompt. Surfaced as
> `binary_sensor.safety_alert_active` in v1.0.0a69.
```

Fill the timeline section with the 5-test series (Test 1 19:50 lift, Test 2 20:08 lid-only, Test 3 brief lift, smoking-gun dock-only, etc.) — lift verbatim from TODO.md.OLD.

Fill deprecated readings:

```markdown
### Deprecated readings

- ~~"byte[10] bit 1 = PIN-required latch (clears at PIN entry)"~~ — wrong;
  smoking-gun dock-only test had bit clear with lid still open and no PIN typed.
- ~~"byte[10] bit 1 = water_on_lidar (post-rain detection)"~~ — wrong; replaced
  by `error_code == 56` rain-protection signal in alpha.59.
- ~~"byte[10] bit 1 = post-fault-window timer (fixed N seconds)"~~ — wrong;
  observed clear lag varies 4-77 s, so it's not a fixed timer either.
- ~~"binary_sensor.dreame_a2_mower_pin_required" entity name~~ — renamed in
  alpha.69 to `binary_sensor.safety_alert_active` after semantics were pinned.
```

- [ ] **Step 4: Fill `## s1p1 byte[3] bit 7 PIN-required clarification`**

Quick answer:

```markdown
> **Quick answer (current state):** byte[3] bit 7 = "PIN required" /
> emergency-stop active. Sets on any safety event (lid open OR lift). Clears
> ONLY on PIN entry — does NOT clear when lid is closed or mower is set down.
> Surfaced as `binary_sensor.emergency_stop_activated`. Sticky-until-acknowledged
> by design; the Dreame app's "Emergency stop is activated" modal is the user-
> facing UX, the integration's persistent_notification (a70) is the HA mirror.
```

Fill timeline with the dated correction history (the bit was originally read as
"physical lift sensor", confirmed in alpha.58 to actually be the security-lockout
flag, etc.). Lift from TODO.md.OLD's "byte[3] bit 7 → 0 transition" notes.

Fill deprecated readings:

```markdown
### Deprecated readings

- ~~"byte[3] bit 7 = immediate physical lift sensor (sets on pickup, clears on
  setdown)"~~ — wrong; the bit is PIN-tied, not lift-tied. Smoking-gun was a
  dock-only lid-open-then-close test where the bit stayed asserted indefinitely
  after lid close, confirming PIN — not lid — is the trigger to clear.
- ~~"byte[3] bit 7 also signals top-cover-open"~~ — wrong; top-cover-open is
  signalled by `error_code == 73`, while byte[3] bit 7 is the broader "safety
  chain broken, PIN required" flag.
```

- [ ] **Step 5: Commit Phase C-2**

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase C-2 — s1p1 byte[10] bit 1 saga + byte[3] bit 7 PIN-required

Lifted the 5-test controlled series + correction history from OLD
TODO.md and OLD g2408-protocol.md §3.4. Two journal topics: the
multi-day byte[10] bit 1 saga (4 deprecated readings, including the
'pin_required' entity rename) and the byte[3] bit 7 PIN-tied
semantic (2 deprecated readings)."
```

---

## Task 6: Phase C — Phase-byte semantics + state codes + s2p51 disambiguation

**Files:**
- Modify: `docs/research/g2408-research-journal.md` (fill 3 topic sections)
- Reference: `docs/research/g2408-protocol.md.OLD` §3.1 phase-byte sub-section, §4.1, §4.2, §6

- [ ] **Step 1: Phase-byte semantics**

Source: OLD doc's "#### Phase byte semantics — **byte [8] is a task-phase index**" sub-section under §3.1. Lift the timeline of the rename from MOWING/TRANSIT/PHASE_2/RETURNING to "task-phase index", the 2026-04-18 trajectory observation, and the 2026-04-20 full-run findings.

Replace the placeholder under `## Phase-byte semantics (s1p4 byte[8])` with quick answer:

```markdown
> **Quick answer (current state):** byte[8] is a task-phase index — the firmware
> decomposes each mowing task into ordered sub-tasks (per-zone area-fill, edge
> passes, return-home transport) and reports which one is currently active.
> Phase advances monotonically; once a value is done, the mower never returns
> to it in the same session. `phase_raw = 15` during post-complete return is
> distinctive. Different mowing modes expose different subsets of phase values;
> values are NOT cross-user portable.
```

Timeline: lift the per-session observations table verbatim from OLD §3.1.

Deprecated readings:
```markdown
### Deprecated readings

- ~~`Phase` enum: MOWING / TRANSIT / PHASE_2 / RETURNING~~ — retired 2026-04-20.
  No single phase value is "edge mode" or "transit" universally; the meaning of
  a phase value is bound to the current task plan.
- ~~"phase_raw distinguishes blades-up from blades-down"~~ — wrong; both
  blades-up dock-resume and blades-down mowing fired phase=2 in 2026-04-22
  capture. Use `area_mowed_cent` delta instead.
```

- [ ] **Step 2: s2p1 mode + s2p2 state codes — what's enum vs error**

Source: OLD doc §2.2 "Upstream-divergence cheat-sheet" + §4.1 + §4.2 + the
2026-04-23 apk cross-reference correction.

Replace the placeholder under `## s2p1 mode + s2p2 state codes — what's enum vs error` with quick answer:

```markdown
> **Quick answer (current state):** g2408 SWAPS upstream's s2p1 / s2p2 meanings.
> Upstream's `(2, 1)` is STATE; on g2408 it's the small mode enum (1=Mowing,
> 2=Idle, 5=Returning, …). Upstream's `(2, 2)` is ERROR; on g2408 it's the
> wide state-code catalog (48=MOWING_COMPLETE, 50=manual-start, 53=scheduled-
> start, 70=mowing, …). The integration's overlay swaps these; per-code semantic
> is in the canonical doc's "s2p2 state codes" chapter.
```

Timeline: lift the 2026-04-17 divergence catalog finding + the 2026-04-23 apk
correction from `2026-04-23-iobroker-dreame-cross-reference.md`. (That whole
file folds in here — Task 8 absorbs the residuals; the s2p1/s2p2 swap is the
big one.)

Deprecated readings:
```markdown
### Deprecated readings

- ~~"s2p1 is the STATE field; s2p2 is the ERROR field"~~ — that's upstream
  Tasshack's mapping (vacuum-derived); g2408 has them swapped. The overlay was
  added 2026-04-17 and re-validated by apk cross-walk 2026-04-23.
- ~~"s2p2 = 27 is IDLE"~~ — partially wrong; s2p2 = 27 fires twice in a single
  second during a human-presence event while the mower is demonstrably still
  moving. So `27` at runtime is NOT literal idle — it may be a query-response
  or alert-acknowledgement token. Documented as IDLE in the canonical for now;
  open question.
- ~~"s2p2 = 73 is TOP_COVER_OPEN per apk"~~ — apk-correct, but the empirical
  fire pattern includes lift events too (s2p2=73 fired during a mid-mow lift,
  before any lid touch). Either the apk label is wrong for g2408 or the lift
  gesture also disturbs the lid sensor.
```

- [ ] **Step 3: s2p51 multiplexed config — disambiguation evolution**

Source: OLD doc §6 — track the evolution of payload-shape disambiguation from
"all settings ride one slot, hard to tell apart" through "named-key shapes are
unambiguous (DND, TIME)" through "`{value: 0|1}` and `{value: [b,b,b,b]}` are
ambiguous, fall back to `getCFG._last_diff`".

Quick answer:

```markdown
> **Quick answer (current state):** Every cloud-side settings change rides this
> slot. 17 distinct payload shapes documented; 15 unambiguous (named-key dicts
> or list shapes that fit only one CFG key) and 2 ambiguous on the wire
> (`{value: 0|1}` shared by 5 boolean settings, `{value: [b,b,b,b]}` shared by
> MSG_ALERT and VOICE). Disambiguation falls back to a `getCFG` snapshot diff
> on `sensor.cfg_keys_raw._last_diff`, run on each `s2p51` push.
```

Timeline: lift the dated discoveries (LIT 8-element schema, anti-theft 3-element
schema, language `{text, voice}` shape, MSG_ALERT and VOICE collision discovery
2026-04-30, ambiguous-toggle 5-key set 2026-04-30 confirmation).

Deprecated readings:
```markdown
### Deprecated readings

- ~~"`{value: 0|1}` is the Frost Protection toggle"~~ — partially right; FDP is
  one of the 5 keys that share this shape, but isolating which key flipped
  requires the getCFG diff.
- ~~"PRE has 10 elements per apk"~~ — true on g2568a; on g2408 PRE has only
  2 elements (zone_id, mode). The other 8 elements (cutting height, obstacle
  distance, coverage %, …) are BT-only on g2408 or live in a different slot.
```

- [ ] **Step 4: Commit Phase C-3**

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase C-3 — phase byte / s2p1 vs s2p2 / s2p51 disambiguation

Three journal topics: the phase-byte rename from a misleading
enum to a task-phase index (2026-04-20); the s2p1 vs s2p2 swap
that g2408 inherits from upstream's vacuum mapping (2026-04-17
overlay + 2026-04-23 apk correction); the s2p51 disambiguation
evolution (15 unambiguous + 2 wire-ambiguous shapes, getCFG diff
fallback)."
```

---

## Task 7: Phase C — Edge-mow FTRTS / s2p50 op-codes / Map-fetch flow

**Files:**
- Modify: `docs/research/g2408-research-journal.md` (fill 3 topic sections)
- Reference: `docs/research/g2408-protocol.md.OLD` §4.6 (s2p50 op-codes), §4.6.1 (FTRTS), §7 (map-fetch dated content)

- [ ] **Step 1: Edge-mow FTRTS + wheel-bind**

Source: OLD doc §4.6.1 (the "Edge-mow failure mode — wheel-bind + FTRTS (2026-05-05)" subsection).

Quick answer:

```markdown
> **Quick answer (current state):** Edge mow with `d.edge: []` (empty contour
> list) drains the firmware's edge-mode budget on irrelevant interior seam
> segments, causing wheel-bind + FTRTS on lawns with tight maneuvering spots
> near merged sub-zone seams. Always pass an explicit `[[map_id, contour_id]]`
> list (the Dreame app sends `[[1, 0]]` for outer perimeter only). Integration
> default is "all outer-perimeter contours from cached map" computed in
> `coordinator.dispatch_action`. Two new binary sensors surface the failure
> chain: `wheel_bind_active` (precursor) and `failed_to_return_to_station`
> (FTRTS condition itself).
```

Timeline: lift the three-run 2026-05-05 capture (run 1 + 2 integration-launched
empty `edge:[]` failed at 6 min, run 3 app-launched explicit `[[1,0]]` reached
ph 0→7 over 15 min and docked cleanly).

Deprecated readings:
```markdown
### Deprecated readings

- ~~"Empty `edge:[]` means 'edge every contour in the current map'"~~ — wrong;
  empty list traces internal merged-sub-zone seams, draining budget on
  invisible-in-app interior segments.
- ~~"Edge-mode firmware budget is per-task and unreachable"~~ — wrong; observed
  to fire at exactly `area_mowed_cent = 700, dist_dm = 10000` (= 7.00 m² /
  1000.0 m). Both caps are tied to the same underlying integrator.
```

- [ ] **Step 2: s2p50 op-code catalog**

Source: OLD doc §4.6.

Quick answer:

```markdown
> **Quick answer (current state):** s2p50 echoes the mower's TASK responses.
> 14 op-codes documented (3=cancel, 6=recharge, 100=mow start, 101=edge,
> 102=zone, 103=spot, 109=task-start-failed, 204=map-edit-request,
> 215=map-edit-confirm-old, 218=delete-zone, 234=save-zone-geometry,
> 401=takePic, -1=error-abort-cleanup, 6 partial). The full catalog is in
> canonical's "Routed-action opcodes" chapter; the journal carries the
> incremental discovery history.
```

Timeline: lift the dated discoveries — 2026-04-20 saw 204+215 from a zone
resize, 2026-04-26 distinguished 234 (save) from 218 (delete) via deliberate
add/edit/delete tests, 2026-04-27 confirmed 401 takePic accept/reject behaviour,
2026-05-05 confirmed echo can drop entirely under cloud load (the wedged-edge
recharge that fired no `o:6` echo).

- [ ] **Step 3: Map-fetch flow**

Source: OLD doc §7.

Quick answer:

```markdown
> **Quick answer (current state):** The mower pushes the map to OSS at
> recharge-leg-start (`s6p1 = 300`). Three distinct OSS-mediated payloads
> share this flow: MAP blob, session-summary JSON (per `event_occured`), and
> LiDAR PCD (per `s99p20`). Architecture diagram is in the slim protocol doc
> §4; per-event piid catalog and OSS object-key schema are in canonical
> § Session-summary fields and § OSS map blob keys.
```

Timeline: lift the 2026-04-19 `event_occured` discovery (the missing trigger
that unblocked session-summary fetching), 2026-04-20 dual-recharge capture,
the `s6p1 = 300 ↔ 200` cycle observation, the proactive cloud-map poll
implementation in v2.0.0-alpha.19.

Deprecated readings:
```markdown
### Deprecated readings

- ~~"`s6p1 = 300` is a session-completion signal"~~ — wrong; it's a
  recharge-leg-start signal. Session completion uses `event_occured siid=4
  eiid=1`.
- ~~"`getOss1dDownloadUrl` is the OSS fetch endpoint"~~ — wrong on g2408;
  returns 404. Use `getDownloadUrl` (the "interim" endpoint).
```

- [ ] **Step 4: Commit Phase C-4**

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase C-4 — edge-mow FTRTS / s2p50 op-codes / map-fetch flow

Three journal topics: the 2026-05-05 edge-mow failure-mode discovery
(d.edge:[] semantics + wheel-bind precursor); s2p50 op-code
catalog evolution (incremental discovery from zone-resize 204+215
through 234/218 distinction); map-fetch flow including the
2026-04-19 event_occured discovery that unblocked session-summary
fetching."
```

---

## Task 8: Phase E — Absorb the two dated side-files

**Files:**
- Delete: `docs/research/2026-04-17-g2408-property-divergences.md`
- Delete: `docs/research/2026-04-23-iobroker-dreame-cross-reference.md`
- Modify: `docs/research/g2408-research-journal.md` (fill 2 topics)

These files mostly went into inventory rows during axis 1; the residual prose folds into the journal.

- [ ] **Step 1: Lift `2026-04-17-g2408-property-divergences.md` content into journal topic "g2408 vs upstream divergence"**

```bash
cat docs/research/2026-04-17-g2408-property-divergences.md
```

The file is a 130-line divergence catalog. Replace the journal topic's
placeholders with:

```markdown
> **Quick answer (current state):** g2408's MQTT property surface diverges from
> upstream Tasshack's vacuum-derived mapping at two critical slots: s2p1 and
> s2p2 are SWAPPED. Plus 12 new-to-g2408 (siid, piid) combos that upstream
> doesn't define. The integration's overlay corrects the swap; new-g2408 slots
> get explicit decoder entries (heartbeat, telemetry, multiplexed config,
> obstacle flag).
```

Timeline:
```markdown
- **2026-04-17** — `probe_log_20260417_095500.jsonl` analysed. 18 distinct
  (siid, piid) combinations observed across 2443 messages. 6 match upstream
  names; 12 are new-to-g2408. Critical finding: upstream's `(2, 1)=STATE` and
  `(2, 2)=ERROR` are swapped on g2408. Overlay landed in alpha-overlay-c.
- **2026-04-23** — apk decompilation cross-walk confirmed the swap (apk says
  s2p1 = "Status" enum and s2p2 = "Error code"). The overlay is correct.
```

Then lift the divergence catalog table verbatim — it's part of the canonical
record. Add a note that the table is the historical seed; the current authoritative
list lives in `inventory.yaml`.

- [ ] **Step 2: Lift `2026-04-23-iobroker-dreame-cross-reference.md` residuals into journal topic "apk cross-walk findings"**

Most of this file's content was absorbed into inventory rows in axis 1 (Task 14
populated `references.apk` on 46 existing rows + added 9 new APK-KNOWN rows).
The residual prose worth journaling:

```bash
cat docs/research/2026-04-23-iobroker-dreame-cross-reference.md
```

Quick answer:

```markdown
> **Quick answer (current state):** apk.md (TA2k/ioBroker.dreame) decompilation
> revealed the routed-action wrapper as g2408's primary write surface, the full
> opcode catalog (op 0-503), the PRE 10-element schema (g2408 only uses 2 of
> the 10 — the rest are BT-only or vacuum-only), and corrected several upstream
> property mappings. apk.md targets g2568a so binary-frame layouts need
> g2408-specific validation; semantic findings (action call routing, CFG keys,
> opcodes) port correctly because the React Native plugin is shared across
> mower models.
```

Timeline:
```markdown
- **2026-04-23** — apk cross-reference doc captured 14 sections of findings:
  routed-action surface, full opcode catalog, settings (CFG / PRE / CMS),
  parseRobotState bitfield, MAP data structure, BLE characteristics, plus a
  prioritised action-items list.
- **2026-04-24** — apk-corrected pose decoder validated against probe corpus;
  alpha.98 fix removes scattered `0.625` magic factors.
- **2026-05-05** — apk's full opcode catalog populated `inventory.yaml` opcodes
  section (Task 14 of axis 1 plan).
- **2026-05-06** — residual content (g2568a-vs-g2408 caveats, action-items list
  remainders) folded into this journal topic. Source file deleted.
```

Cross-references:
```markdown
- Inventory rows: every row with `references.apk` populated (46 backfilled +
  9 added in axis 1's Task 14)
- Canonical: chapters that cite apk in their "See also" footer
- Slim protocol doc: §3 Routed-action surface
```

- [ ] **Step 3: Delete the absorbed side-files**

```bash
git rm docs/research/2026-04-17-g2408-property-divergences.md
git rm docs/research/2026-04-23-iobroker-dreame-cross-reference.md
```

- [ ] **Step 4: Verify the journal still parses**

```bash
python -c "
import pathlib
content = pathlib.Path('docs/research/g2408-research-journal.md').read_text()
fences = content.count('\`\`\`')
assert fences % 2 == 0, 'unbalanced fences'
print('ok:', len(content.splitlines()), 'lines')
"
```

- [ ] **Step 5: Commit Phase E**

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase E — absorb 2 dated side-files into journal

Folded 2026-04-17-g2408-property-divergences.md (whole file)
into journal topic 'g2408 vs upstream divergence'; folded
2026-04-23-iobroker-dreame-cross-reference.md residuals into
'apk cross-walk findings'. Both source files deleted; their
content lives in the journal + inventory rows from axis 1."
```

---

## Task 9: Phase D — Migrate TODO.md (open items + recently-shipped distribution)

**Files:**
- Modify: `docs/TODO.md` (fill the "Open" / "In-progress" / "Blocked" sections)
- Modify: `docs/research/g2408-research-journal.md` (fill "Recently shipped — version timeline" + per-topic version distribution + "Live-confirmed status board")
- Reference: `docs/TODO.md.OLD` (1082 lines)

This task does the heaviest re-classification. Walk OLD TODO.md section by section and route each entry to its destination.

- [ ] **Step 1: Walk OLD TODO.md and produce a routing manifest**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -n "^### \|^## " docs/TODO.md.OLD > /tmp/todo-sections.txt
cat /tmp/todo-sections.txt
```

For each section heading, classify in your head:
- (a) Open work — stays in slim TODO.md
- (b) Resolved/historical — moves to journal under best-fit topic
- (c) Recently shipped (a52 → current) — moves to journal "Recently shipped — version timeline" + cross-references the topic each version touched
- (d) Live-confirmed — moves to journal "Live-confirmed status board"

Write the manifest as a 4-column table on a scratchpad (or as a comment block in the commit body if needed).

- [ ] **Step 2: Fill `docs/TODO.md` "Open" section**

For every (a)-classified entry, write a slim TODO item using the §4.4 shape from the spec:

```markdown
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

Open items expected in OLD TODO.md (from earlier reads):
- Trail loss when HA restarts mid-mow — open
- Replay-image flow / picture-entity quirk — open
- Live-map popout first-load image missing — open
- Dock-departure repositioning UX (no MQTT signal yet) — open, blocked on capture
- Mowing direction / Crisscross / Chequerboard pattern (BT-only) — open, blocked
- ai_obstacle blob format — open, blocked on capture
- Patrol Logs investigation — open, blocked on capture
- MIHIS.start mismatch — open
- Firmware update flow capture — open, blocked on capture
- Change PIN code wire format — open, blocked on capture
- Pathway Obstacle Avoidance test — open, blocked on capture
- Dashboard contextual buttons (replicate Dreame app's per-state button rows) — open
- MowerAction.SUPPRESS_FAULT semantics — open, blocked on safe-test design
- Add an integration icon (home-assistant/brands PR) — open
- Live-map popout (the full-screen view) first-load missing — open

Each becomes one slim TODO entry. **Move to "Blocked" section** any entry whose
`Status: blocked-by-X` shows a real external dependency (capture during
firmware update; user has no Pathway Obstacle Avoidance set up; etc.).

- [ ] **Step 3: Fill `docs/research/g2408-research-journal.md` "Recently shipped" topic**

Lift the OLD TODO.md "Recently shipped (a52 → a87)" section verbatim under the
journal's `## Recently shipped — version timeline` topic. Each version entry is
a sub-section with the version number, date if available, and what shipped.

Cross-reference: under each version entry, add a `**Topic:** s1p4 telemetry decoder evolution`
line (or whichever topic the version touched) so a reader can jump to the saga
that version closed.

- [ ] **Step 4: Fill journal "Live-confirmed status board" topic**

Lift the OLD TODO.md "Live-confirmed" bullet list. Sample shape:

```markdown
> **Quick answer (current state):** End-to-end confirmed working as of
> 2026-05-06: Pause / Stop / Recharge buttons (a27); Spot mow (a34/a35); Zone
> mow; Edge mow (a134); Find My Robot (a67); maintenance reminders;
> consumable acks; WiFi RSSI live tracking; tilt/lift/bumper/emergency-stop
> binary_sensors.

### Detailed status

- _<each bullet from OLD TODO's 'Live-confirmed' section, lifted verbatim>_
```

- [ ] **Step 5: Verify TODO.md is in budget**

```bash
wc -l docs/TODO.md
```

Expected: 150-250 lines. If over 250, individual items have too much rationale —
move the rationale to the journal topic, leave a 2-sentence pointer in TODO.

- [ ] **Step 6: Commit Phase D**

```bash
git add docs/TODO.md docs/research/g2408-research-journal.md
git commit -m "docs(axis2): Phase D — migrate TODO.md and fill journal version timeline

Slim TODO.md: open items only, each in §4.4 shape (Why / Done
when / Status / Cross-refs). Items needing external evidence
(firmware-update capture, Pathway Obstacle Avoidance, Patrol
Logs) are in the Blocked section.

Journal: 'Recently shipped — version timeline' + 'Live-confirmed
status board' topics filled from OLD TODO.md.

OLD TODO.md still on disk as TODO.md.OLD until Phase G acceptance."
```

---

## Task 10: Phase F — Sweep `inventory.yaml` cite paths

**Files:**
- Modify: `docs/research/inventory/inventory.yaml` (update `references.protocol_doc` cites)
- Modify: `docs/research/inventory/generated/g2408-canonical.md` (regenerated)

Existing cites point at `docs/research/g2408-protocol.md §X.Y` anchors that mostly disappear from the slim doc. Update each to the right destination: canonical chapter (most), or slim doc (cross-cutting).

- [ ] **Step 1: Build the cite-update mapping**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -c "
import yaml
inv = yaml.safe_load(open('docs/research/inventory/inventory.yaml'))
seen = set()
for s in inv:
    if s.startswith('_') or not isinstance(inv.get(s), list): continue
    for r in inv.get(s, []):
        if not isinstance(r, dict): continue
        ref = (r.get('references') or {}).get('protocol_doc')
        if ref:
            seen.add(ref)
for r in sorted(seen):
    print(r)
" > /tmp/protocol-cites.txt
wc -l /tmp/protocol-cites.txt
cat /tmp/protocol-cites.txt
```

The output lists every distinct cite (likely 30-50 entries).

- [ ] **Step 2: For each cite, decide its new destination**

Cross-cutting cites that stay on the slim doc:
- `§1`, `§1.1`, `§1.2` → `docs/research/g2408-protocol.md §1 Transport layer` (or `§1.1`/`§1.2`)
- `§7.5` → `docs/research/g2408-protocol.md §5 PROTOCOL_NOVEL`
- `§3.1 Coordinate frame (charger-relative)` and Y-axis calibration → `docs/research/g2408-protocol.md §2 Coordinate frame`
- `§6.2` (when about the routed-action envelope, not the per-key tables) → `docs/research/g2408-protocol.md §3 Routed-action surface`
- `§7` (when about OSS architecture, not the piid tables) → `docs/research/g2408-protocol.md §4 OSS fetch architecture`

Per-slot cites that move to canonical:
- `§2.1` (property summary table) → `docs/research/inventory/generated/g2408-canonical.md § Properties`
- `§3.1`, `§3.2`, `§3.3` (per-byte telemetry detail) → `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields` or `§ Telemetry frame variants`
- `§3.4` (per-byte heartbeat detail) → `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`
- `§4.1` (s2p2 state codes table) → `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`
- `§4.2` (s2p1 mode enum) → `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`
- `§4.6`, `§4.6.1` (s2p50 op-code catalog) → `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`
- `§6` (s2p51 multiplexed config — the per-shape table) → `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`
- `§6.2` (when about per-CFG-key detail) → `docs/research/inventory/generated/g2408-canonical.md § CFG keys`
- `§6.3` → `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`
- `§7.4` (event_occured args) → `docs/research/inventory/generated/g2408-canonical.md § Events`
- `§7.6` (session-summary JSON schema) → `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`
- `§7.8` (MAP top-level keys) → `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`
- `§8.3` (s2p2 error code catalog extensions) → same as §4.1
- `§8.4` (s2p56 status[0][1] catalog) → look up in canonical's properties chapter for the s2p56 row's open_questions

Some rows may want BOTH a slim cite AND a canonical cite (e.g., heartbeat byte rows whose semantic is in canonical but architectural framing is in slim). The schema allows multiple references; add a separate field rather than crowding `protocol_doc`.

- [ ] **Step 3: Apply the cite updates via a focused Python helper**

Write a small one-shot script (don't commit it; just run it) that loads the yaml, updates cites per the mapping above, dumps back. **Use the same surgical approach as the MISTA fix — round-trip via yaml is fine for value-only updates because the structure is preserved.** But pin yaml's emitter settings (default_flow_style=False, sort_keys=False) so the diff is small.

```python
# /tmp/update_cites.py
import yaml, re
from pathlib import Path

p = Path('/data/claude/homeassistant/ha-dreame-a2-mower/docs/research/inventory/inventory.yaml')
text = p.read_text()

# Surgical sed-style replacements — preserves all formatting.
mapping = {
    # Cross-cutting (stay on slim)
    'docs/research/g2408-protocol.md §1.2': 'docs/research/g2408-protocol.md §1 Transport layer',
    'docs/research/g2408-protocol.md §1.1': 'docs/research/g2408-protocol.md §1 Transport layer',
    'docs/research/g2408-protocol.md §1':   'docs/research/g2408-protocol.md §1 Transport layer',
    'docs/research/g2408-protocol.md §7.5': 'docs/research/g2408-protocol.md §5 PROTOCOL_NOVEL',
    # Per-slot (move to canonical)
    'docs/research/g2408-protocol.md §2.1': 'docs/research/inventory/generated/g2408-canonical.md § Properties',
    'docs/research/g2408-protocol.md §3.1': 'docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields',
    'docs/research/g2408-protocol.md §3.2': 'docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants',
    'docs/research/g2408-protocol.md §3.3': 'docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants',
    'docs/research/g2408-protocol.md §3.4': 'docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes',
    'docs/research/g2408-protocol.md §4.1': 'docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes',
    'docs/research/g2408-protocol.md §4.2': 'docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum',
    'docs/research/g2408-protocol.md §4.6.1': 'docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes',
    'docs/research/g2408-protocol.md §4.6': 'docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes',
    'docs/research/g2408-protocol.md §6.3': 'docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints',
    'docs/research/g2408-protocol.md §6.2': 'docs/research/inventory/generated/g2408-canonical.md § CFG keys',
    'docs/research/g2408-protocol.md §6':   'docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes',
    'docs/research/g2408-protocol.md §7.4': 'docs/research/inventory/generated/g2408-canonical.md § Events',
    'docs/research/g2408-protocol.md §7.6': 'docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields',
    'docs/research/g2408-protocol.md §7.8': 'docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys',
    'docs/research/g2408-protocol.md §7':   'docs/research/g2408-protocol.md §4 OSS fetch architecture',
    'docs/research/g2408-protocol.md §8.3': 'docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes',
    'docs/research/g2408-protocol.md §8.4': 'docs/research/inventory/generated/g2408-canonical.md § Properties',
}

# Sort by length descending so longer-match patterns are tried first
# (otherwise '§1' would clobber '§1.1', '§1.2', etc.)
for pat, rep in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
    text = text.replace(pat, rep)

p.write_text(text)
print('ok')
```

Run it:

```bash
python /tmp/update_cites.py
```

- [ ] **Step 4: Verify the inventory still validates and renders**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py
python tools/inventory_gen.py
python -m pytest tests/tools/ -v
```

All four must succeed.

- [ ] **Step 5: Commit Phase F**

```bash
rm /tmp/update_cites.py
git add docs/research/inventory/
git commit -m "docs(axis2): Phase F — update inventory cite paths post-restructure

Per-slot cites moved from g2408-protocol.md to canonical
chapter anchors (§ Properties / § Telemetry fields /
§ Heartbeat bytes / § s2p2 state codes / § CFG keys / § Events
/ etc.). Cross-cutting cites point at the new slim
g2408-protocol.md sections (§1 Transport / §5 PROTOCOL_NOVEL
/ §4 OSS fetch architecture). Canonical doc regenerated."
```

---

## Task 11: Phase G — Build the orphan-paragraph completeness check (TDD)

**Files:**
- Create: `tools/journal_completeness_check.py`
- Create: `tests/tools/test_journal_completeness.py`
- Create: `tests/tools/fixtures/journal_complete/` (skeleton + complete fixture)

The orphan check walks each non-trivial paragraph in the OLD docs and asserts it appears (substring match, normalised whitespace) in either the slim doc, the journal, the canonical doc, or an explicit allowlist of "intentionally dropped" paragraphs (deprecated diagrams, redundant cross-references, etc.).

- [ ] **Step 1: Write failing tests**

`tests/tools/test_journal_completeness.py`:

```python
"""Tests for the orphan-paragraph completeness check."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "journal_complete"
TOOL = Path(__file__).parents[2] / "tools" / "journal_completeness_check.py"


def _run(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *extra_args],
        capture_output=True, text=True, check=False,
    )


def test_passes_when_every_paragraph_accounted_for() -> None:
    """If every paragraph in OLD appears in one of the destinations, exit 0."""
    result = _run([
        "--old", str(FIXTURES / "old_complete.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
    ])
    assert result.returncode == 0, result.stdout + result.stderr


def test_reports_orphan_when_paragraph_is_missing() -> None:
    """If OLD has a paragraph that doesn't appear in any destination,
    exit non-zero and the report names the paragraph."""
    result = _run([
        "--old", str(FIXTURES / "old_with_orphan.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
    ])
    assert result.returncode != 0
    assert "orphan" in result.stdout.lower()
    assert "this paragraph is unique" in result.stdout.lower()


def test_allowlist_skips_intentionally_dropped() -> None:
    """A paragraph in the allowlist is not flagged as an orphan."""
    result = _run([
        "--old", str(FIXTURES / "old_with_orphan.md"),
        "--destinations",
        str(FIXTURES / "slim.md"),
        str(FIXTURES / "journal.md"),
        "--allowlist", str(FIXTURES / "allowlist.txt"),
    ])
    assert result.returncode == 0, result.stdout
```

- [ ] **Step 2: Write the fixtures**

`tests/tools/fixtures/journal_complete/old_complete.md`:

```markdown
# Old Doc

## Section A

The mower has a heartbeat that fires every 45 seconds.

## Section B

The cloud RPC tunnel returns 80001 on g2408 reliably.
```

`tests/tools/fixtures/journal_complete/old_with_orphan.md`:

```markdown
# Old Doc

## Section A

The mower has a heartbeat that fires every 45 seconds.

## Section B

This paragraph is unique to OLD and won't appear anywhere else.

## Section C

The cloud RPC tunnel returns 80001 on g2408 reliably.
```

`tests/tools/fixtures/journal_complete/slim.md`:

```markdown
# Slim Doc

## Transport

The cloud RPC tunnel returns 80001 on g2408 reliably.
```

`tests/tools/fixtures/journal_complete/journal.md`:

```markdown
# Journal

## Heartbeat saga

The mower has a heartbeat that fires every 45 seconds.
```

`tests/tools/fixtures/journal_complete/allowlist.txt`:

```
This paragraph is unique to OLD and won't appear anywhere else.
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/tools/test_journal_completeness.py -v
```

Expected: 3 failures (tool doesn't exist).

- [ ] **Step 4: Implement the tool**

`tools/journal_completeness_check.py`:

```python
#!/usr/bin/env python3
"""Orphan-paragraph completeness check.

Walks an OLD doc and asserts every non-trivial paragraph appears
(substring match, whitespace-normalised) in at least one destination
file or in an explicit allowlist of intentionally-dropped paragraphs.

Exit 0: every paragraph accounted for.
Exit 1: at least one orphan; report names the paragraph.
Exit 2: usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Paragraphs shorter than this are skipped (one-liners, headers, list bullets
# of a couple words). Tunable; 80 is a reasonable cut.
_MIN_PARAGRAPH_LEN = 80


def _normalise(text: str) -> str:
    """Collapse whitespace to single spaces; strip; lowercase."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; strip; filter trivially short / heading-only."""
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Skip pure markdown headings (one line starting with #).
        lines = chunk.split("\n")
        if len(lines) == 1 and lines[0].lstrip().startswith("#"):
            continue
        # Skip code fences as units (they're complete; counted as one paragraph).
        if chunk.startswith("```"):
            paragraphs.append(chunk)
            continue
        if len(chunk) >= _MIN_PARAGRAPH_LEN:
            paragraphs.append(chunk)
    return paragraphs


def _load_allowlist(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(_normalise(line))
    return out


def check(
    old_path: Path,
    destination_paths: list[Path],
    allowlist: set[str],
) -> tuple[int, str]:
    """Return (exit_code, report_text)."""
    old_text = old_path.read_text()
    paragraphs = _split_paragraphs(old_text)

    destinations_text = "\n\n".join(p.read_text() for p in destination_paths if p.exists())
    destinations_normalised = _normalise(destinations_text)

    orphans: list[str] = []
    for p in paragraphs:
        norm = _normalise(p)
        if norm in destinations_normalised:
            continue
        if norm in allowlist:
            continue
        orphans.append(p)

    out: list[str] = []
    out.append(f"# Orphan-paragraph check\n\n")
    out.append(f"OLD doc: {old_path}\n")
    out.append(f"Destinations: {[str(d) for d in destination_paths]}\n")
    out.append(f"Allowlist size: {len(allowlist)}\n")
    out.append(f"Total non-trivial paragraphs in OLD: {len(paragraphs)}\n")
    out.append(f"Orphans: {len(orphans)}\n\n")
    for orphan in orphans:
        snippet = orphan[:200].replace("\n", " ")
        out.append(f"## Orphan\n\n{snippet}{'...' if len(orphan) > 200 else ''}\n\n")
    return (0 if not orphans else 1, "".join(out))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--destinations", type=Path, nargs="+", required=True)
    parser.add_argument("--allowlist", type=Path, default=None)
    args = parser.parse_args(argv)

    allowlist = _load_allowlist(args.allowlist)
    exit_code, report = check(args.old, args.destinations, allowlist)
    print(report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_journal_completeness.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit Phase G-tooling**

```bash
git add tools/journal_completeness_check.py tests/tools/test_journal_completeness.py tests/tools/fixtures/journal_complete/
git commit -m "feat(audit): orphan-paragraph completeness check + tests

One-shot audit (not permanent CI) that walks an OLD doc paragraph
by paragraph and asserts each one ≥80 chars appears (substring
match, whitespace-normalised) in at least one destination or in
an explicit allowlist. Used by axis-2 Phase G acceptance to gate
deletion of the OLD .OLD stash files."
```

---

## Task 12: Phase G — Run completeness check + acceptance + cleanup

**Files:**
- Run: `tools/journal_completeness_check.py` against the two OLD stashes
- Create (if needed): `docs/research/.completeness-allowlist.txt` for intentional drops
- Delete: `docs/research/g2408-protocol.md.OLD`
- Delete: `docs/TODO.md.OLD`

- [ ] **Step 1: Run the completeness check against OLD g2408-protocol.md**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python tools/journal_completeness_check.py \
  --old docs/research/g2408-protocol.md.OLD \
  --destinations \
    docs/research/g2408-protocol.md \
    docs/research/g2408-research-journal.md \
    docs/research/inventory/generated/g2408-canonical.md \
  --allowlist docs/research/.completeness-allowlist.txt 2>&1 | tee /tmp/completeness-protocol.txt
echo "exit: $?"
```

If exit != 0, the report names every orphan. For each orphan:
- If it's content that genuinely belongs somewhere and was missed, GO BACK to the relevant phase task and fold it in.
- If it's content that's intentionally dropped (e.g., a redundant diagram, a deprecated paragraph that no longer applies), add the first 200 chars to `docs/research/.completeness-allowlist.txt` (one entry per line).

Iterate until exit == 0. (Allowlist file is created on first need.)

- [ ] **Step 2: Run the completeness check against OLD TODO.md**

```bash
python tools/journal_completeness_check.py \
  --old docs/TODO.md.OLD \
  --destinations \
    docs/TODO.md \
    docs/research/g2408-research-journal.md \
  --allowlist docs/research/.completeness-allowlist.txt 2>&1 | tee /tmp/completeness-todo.txt
echo "exit: $?"
```

Same procedure as Step 1.

- [ ] **Step 3: Verify cite integrity (no dangling references)**

```bash
python -c "
import re
import yaml
from pathlib import Path

inv = yaml.safe_load(open('docs/research/inventory/inventory.yaml'))
slim_text = Path('docs/research/g2408-protocol.md').read_text()
canon_text = Path('docs/research/inventory/generated/g2408-canonical.md').read_text()

dangling = []
for s in inv:
    if s.startswith('_') or not isinstance(inv.get(s), list): continue
    for r in inv.get(s, []):
        if not isinstance(r, dict): continue
        ref = (r.get('references') or {}).get('protocol_doc')
        if not ref: continue
        # The cite is something like 'docs/research/X.md § Section name'.
        # Confirm the section anchor exists in the target file.
        m = re.match(r'(docs/[^ ]+) § (.+)', ref)
        if not m:
            continue
        target_path, anchor = m.group(1), m.group(2)
        target_text = Path(target_path).read_text() if Path(target_path).exists() else ''
        if anchor not in target_text:
            dangling.append((s, r['id'], ref))

if dangling:
    print(f'{len(dangling)} dangling cites:')
    for s, rid, ref in dangling[:20]:
        print(f'  {s}/{rid}: {ref}')
    raise SystemExit(1)
else:
    print('all protocol_doc cites resolve cleanly')
"
```

If non-zero, fix the cites in `inventory.yaml` (Task 10 mapping may have missed an edge case — augment and re-run).

- [ ] **Step 4: Run all audits and tests one more time**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py > /dev/null 2>&1; echo "audit exit: $?"
python -m pytest tests/tools/ -v 2>&1 | tail -5
```

All must pass.

- [ ] **Step 5: Delete the OLD stash files**

```bash
git rm docs/research/g2408-protocol.md.OLD
git rm docs/TODO.md.OLD
```

- [ ] **Step 6: Verify line-count budgets**

```bash
echo "slim protocol: $(wc -l < docs/research/g2408-protocol.md)"   # 250-500
echo "TODO:         $(wc -l < docs/TODO.md)"                        # 150-250
echo "journal:      $(wc -l < docs/research/g2408-research-journal.md)"
```

If slim or TODO are out of budget, address before commit.

- [ ] **Step 7: Final commit + push**

```bash
git add -A
git commit -m "docs(axis2): Phase G — completeness check passes; OLD stashes removed

Orphan-paragraph audit reports zero unaccounted paragraphs (with
allowlist for intentionally-dropped content). All inventory
protocol_doc cites resolve to existing anchors. Inventory schema
+ consistency audit + 17 pytest tests all green.

Axis 2 acceptance criteria #1-10 met:
- slim g2408-protocol.md in 250-500 line budget
- topic-clustered journal populated
- TODO.md ≤ 250 lines, all entries in §4.4 shape
- 2 dated side-files deleted; content in journal
- orphan-paragraph audit: 0
- protocol_doc cite resolution: 0 dangling
- inventory schema + audit + tests: all pass"

git push origin main
```

---

## Self-review summary

**Spec coverage check:**
- §3 Non-goals (deferred to other axes) — respected; no axis 3/4/5 work touched.
- §4.1 file layout — Tasks 1, 8, 12 (skeleton creation, side-file deletion, OLD stash cleanup).
- §4.2 slim protocol prose lift — Tasks 2, 3.
- §4.3 journal topic structure — Tasks 4, 5, 6, 7, 8, 9 (each topic populated).
- §4.4 slim TODO shape — Task 9.
- §4.5 side-file disposition — Task 8.
- §4.6 cross-reference integrity — Task 10 + Task 12 cite-resolution check.
- §4.7 validation — Tasks 11, 12 (orphan audit + cite-resolution).
- §5 execution model — Task list mirrors the phase ordering.
- §6 acceptance criteria — Task 12 verifies all 10.

**Placeholder scan:** every step shows actual content (markdown, code, commands). Steps that say "lift content from OLD §X.Y" point at exact line ranges and provide the canonical destination structure (Quick answer + Timeline + Deprecated readings + Cross-references). Data-entry tasks (4-9) reference the topic-template explicitly and provide a worked example.

**Type consistency:** the topic IDs in the journal skeleton (Task 1) match the topic headers used in Tasks 4-9. The cite-mapping in Task 10 enumerates every distinct § anchor that Tasks 6-13 of axis 1 produced; the migration is mechanical.
