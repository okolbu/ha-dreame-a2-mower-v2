# g2408 Protocol Inventory Consolidation — Axis 1 Design

**Status:** Spec, awaiting review
**Author:** session 2026-05-05
**Supersedes:** none — first axis-1 spec
**Sibling axes (out of scope here):** axis 2 (doc restructure), axis 3 (harness), axis 4 (decoder enrichment), axis 5 (live-test gap closure)

---

## 1. Problem

Each previous "protocol review" of the Dreame A2 (`g2408`) integration has felt complete at the time, but within days a new MQTT slot or apk-known property surfaces that the review didn't catch. The recent examples are `s1p2` (`FIRMWARE_INSTALL_STATE`) and `s1p3` (`FIRMWARE_DOWNLOAD_PROGRESS`) — both documented in upstream repos but absent from our integration's mapping until the watchdog flagged them.

The structural cause is that "what we know" lives in three places that drift independently:

- Prose in `docs/research/g2408-protocol.md` (1821 lines, layered findings)
- Hard-coded tables in `custom_components/dreame_a2_mower/mower/property_mapping.py`, `mower/actions.py`, `protocol/config_s2p51.py`, `_SUPPRESSED_SLOTS`
- Cross-references to upstream sources (`ioBroker.dreame/apk.md`, `alternatives/dreame-mower`, `dreame-mova-mower`, `ha-dreame-a2-mower-legacy`) scattered through one-off research notes

When a new slot appears on the wire, the runtime watchdog (`[PROTOCOL_NOVEL]`) fires correctly — but only if the slot was missing from the hand-maintained suppression list. There is no mechanism that says "this slot is *known* to firmware but not yet *seen* on this device" or "we expect to see this when feature X happens".

## 2. Goal of axis 1

Produce a single machine-readable source of truth (`inventory.yaml`) that catalogues every protocol artefact the integration touches or could touch on a g2408. Generate a human-readable canonical reference doc from it. Defer everything else to later axes.

The inventory must answer, for every protocol slot, a fixed set of questions:

- Has this been observed on the wire on g2408? When?
- Is the semantic confirmed, hypothesised, or unknown?
- Is it documented in the apk decompilation?
- Is it referenced by an alt-repo (and which)?
- Does the integration already wire it (and where in code)?
- Is it confirmed Bluetooth-only / cloud-write-invisible / not-on-g2408?

Rows where every field is `null` or `false` represent the gaps that the runtime watchdog and contributors should be encouraged to close.

### What "production-ready, not feature-complete" means here

Per the user's framing: the integration ships when

1. Every **knowable** thing on g2408 has a documented row in the inventory and is wired in code OR has an explicit reason it isn't (BT-only, not-on-g2408, deferred-by-design).
2. Every **unknown** is enumerated with a procedure for capturing it.
3. The runtime warns loudly and discoverably when a wire shape arrives that isn't in the inventory.

Axis 1 produces the inventory. Axes 2-5 deliver the doc cleanup, runtime wiring, decoder enrichment, and gap closure that round it out.

## 3. Non-goals (deferred to other axes)

- Restructuring `g2408-protocol.md` from layered-findings into "current state" prose — axis 2.
- Splitting `TODO.md` into open work vs. archived findings — axis 2.
- Wiring the runtime to load `inventory.yaml` for `[PROTOCOL_NOVEL]` suppression — axis 3.
- Building the probe-log diff CI check — axis 3.
- Adding new HA entities for slots the inventory marks `DECODED-UNWIRED` — axis 4.
- Live-testing apk-known opcodes that haven't been verified — axis 5.
- Capture-test procedures for fakeable features (pathways, multi-lawn) and event-driven ones (firmware update, change PIN, patrol logs) — axis 5.

## 4. Architecture

### 4.1 File layout

```
docs/research/inventory/
  inventory.yaml             # source of truth
  README.md                  # how to read / extend the inventory
  generated/
    g2408-canonical.md       # generated chapter-style reference
    coverage-report.md       # generated audit; empty when axis 1 is done
tools/
  inventory_gen.py           # YAML → markdown generator
  inventory_audit.py         # walks probe logs; reports slots not in YAML
  inventory_probe.py         # read-only live probe; emits a JSON delta
                             # against current YAML for reviewer to merge
OLD/alternatives_archive_2026-05-05/
  README.md                  # one-line "absorbed into inventory.yaml; see <github URLs>"
  alternatives/              # moved from /data/claude/homeassistant/alternatives/
  ioBroker.dreame/           # moved from /data/claude/homeassistant/ioBroker.dreame/
  dreame-mova-mower/         # moved from /data/claude/homeassistant/dreame-mova-mower/
  ha-dreame-a2-mower-legacy/ # moved from /data/claude/homeassistant/ha-dreame-a2-mower-legacy/
```

The YAML is one file with multiple top-level sections (not split per category). Cross-section grep beats per-section diffs because a single slot's status is computed from evidence across multiple sources.

The alt-repo clones are physically moved (not deleted) so the original git history is preserved if a future investigation needs them. The integration repo carries the absorbed knowledge in `inventory.yaml`; the user-level working directory loses the loose clones.

### 4.2 YAML row shape

Top-level structure:

```yaml
_sources:
  apk_md: "github.com/TA2k/ioBroker.dreame/blob/main/apk.md"
  alt_repos:
    iobroker_dreame: "github.com/TA2k/ioBroker.dreame"
    dreame_mower: "github.com/antondaubert/dreame-mower"
    dreame_vacuum: "github.com/Tasshack/dreame-vacuum"
    dreame_mova_mower: "github.com/nicolasglg/dreame-mova-mower"
    legacy: "github.com/okolbu/ha-dreame-a2-mower-legacy"
  probe_log_corpus:
    - "probe_log_20260417_093127.jsonl"
    - "probe_log_20260417_095500.jsonl"
    - "probe_log_20260418_163423.jsonl"
    - "probe_log_20260418_202802.jsonl"
    - "probe_log_20260419_130434.jsonl"   # 14.7k frames, primary corpus
  cloud_dump_corpus:
    # Glob: dreame_cloud_dumps/dump_*.json — all files matching this pattern at
    # build time are walked. Listed below for traceability; the audit tool
    # globs at run time so newly-added dumps are picked up automatically.
    - "dreame_cloud_dumps/dump_20260504T215633.json"
    - "dreame_cloud_dumps/dump_20260505T000828.json"
    # A third dump is in flight at spec-write time (2026-05-05). Once it
    # lands, re-running the audit will pull it in without spec edits.

properties:        [list of property rows]
events:            [list of event_occured rows]
actions:           [list of (siid, aiid) rows]
opcodes:           [list of routed-action 'o' codes]
cfg_keys:          [list of all-keys CFG dictionary entries]
cfg_individual:    [list of getCFG t:'X' separate-call endpoints]
heartbeat_bytes:   [list of s1p1 byte rows; one per byte/bit]
telemetry_fields:  [list of s1p4 33-byte field rows]
telemetry_variants: [list of s1p4 frame-length variants: 7/8/10/13/22/33/44]
s2p51_shapes:      [list of multiplexed-config payload shapes]
state_codes:       [list of s2p2 enum entries]
mode_enum:         [list of s2p1 enum entries]
oss_map_keys:      [list of MAP.* top-level keys]
session_summary_fields: [list of session-summary JSON keys]
m_path_encoding:   [list of M_PATH structural rules]
lidar_pcd:         [list of LiDAR PCD header/payload fields]
```

### 4.3 Per-row schema

```yaml
- id: "s2p52"                  # category-unique id; used for cross-refs
  siid: 2                       # only for properties / events / actions
  piid: 52
  name: "preference_update_trigger"
  category: "trigger"           # property | blob | trigger | event | multiplexed
  payload_shape: "empty_dict"   # one-line wire shape

  # Optional: numeric wire→display conversion. Omitted for booleans / strings /
  # multiplexed shapes whose units depend on sub-payload (those go on the
  # sub-field rows under telemetry_fields / s2p51_shapes / etc.).
  unit:
    wire: "cm"                  # what the wire carries (cm, mm, decimetres,
                                #   centiares, signed_dbm, minutes_from_midnight,
                                #   unix_seconds, percent_x100, raw_bytes, ...)
    display: "m"                # canonical user-facing unit
    scale: 0.01                 # multiplier from wire value to display value
    format: "{:.2f}"            # optional rendering hint
    notes: |
      Lawn distances are reported in cm on the wire but displayed in metres
      with 2 decimals. Use scale not /100 division to avoid integer-floor.

  # Optional: enum value catalog for properties whose wire is a small int.
  # Omitted when the row carries a continuous numeric or a structured payload.
  value_catalog:
    0: "off"
    1: "on"

  semantic: |
    Fires when PRE settings change; consumer should re-fetch via getCFG.
    Earlier hypothesis ("session-end marker") was wrong — see journal entry
    2026-04-23.

  status:
    seen_on_wire: true
    first_seen: "2026-04-17"
    last_seen: "2026-04-30"
    decoded: confirmed          # confirmed | hypothesized | unknown
    bt_only: false
    not_on_g2408: false

  references:
    apk: "ioBroker.dreame/apk.md §parseRobotPose"
    alt_repos:
      - "alternatives/dreame-mower/dreame/types.py:725"
    integration_code: null      # null = unwired
    protocol_doc: "g2408-protocol.md §4.7"

  open_questions:
    - "Does this also fire on PIN-update, or only PRE?"
```

The same schema applies to events, actions, opcodes, CFG keys, etc. — fields that don't apply to a row's category (e.g. `siid` on a CFG-key row, or `unit` on a boolean row) are simply omitted. Generator handles missing fields gracefully.

The `status` block is structured (multiple booleans + timestamps) rather than a single enum so the generator can compute a derived single-label status per row in one place.

#### Unit handling for compound payloads

Compound payloads (s1p4 33-byte telemetry, s2p51 multiplexed config) carry multiple values with different units. The parent property row (`s1p4`, `s2p51`) does **not** carry a `unit` block; the units live on the sub-rows under `telemetry_fields:` and `s2p51_shapes:`. Same pattern for OSS map blobs — the parent `s6p1 MAP_DATA` row has no unit, but `oss_map_keys.boundary` has `wire: cm, display: m, scale: 0.01`, and so on. This keeps unit declarations close to the values they describe.

Vocabulary for `unit.wire` values is open but the generator validates against a known list to catch typos: `cm`, `mm`, `m`, `decimetres`, `centiares`, `m2`, `m2_x100`, `signed_dbm`, `unsigned_byte`, `signed_byte`, `minutes_from_midnight`, `unix_seconds`, `percent`, `percent_x100`, `degrees`, `degrees_x256` (e.g. heading byte ÷ 255 × 360), `bool`, `enum`, `raw_bytes`, `string`. Adding a new wire encoding requires a one-line entry in `tools/inventory_gen.py:_UNIT_VOCAB` so it stays explicit.

### 4.4 Status taxonomy (computed from booleans)

The generator maps the boolean fields to a single human-readable label per row:

| Label              | Condition |
|--------------------|-----------|
| `WIRED`            | `references.integration_code` is non-null |
| `DECODED-UNWIRED`  | `seen_on_wire: true` AND `decoded: confirmed` AND `integration_code: null` |
| `SEEN-UNDECODED`   | `seen_on_wire: true` AND `decoded != confirmed` |
| `APK-KNOWN`        | `seen_on_wire: false` AND `references.apk` non-null |
| `UPSTREAM-KNOWN`   | `seen_on_wire: false` AND `references.apk: null` AND `references.alt_repos` non-empty |
| `BT-ONLY`          | `bt_only: true` |
| `NOT-ON-G2408`     | `not_on_g2408: true` |

A row that fits multiple labels picks the first matching one in the table order.

### 4.5 Generator output

`g2408-canonical.md` is one file with chapters mirroring the YAML sections (transport, properties, events, actions, opcodes, CFG keys, cfg_individual, heartbeat bytes, telemetry frames, s2p51 shapes, state codes, mode enum, OSS map keys, session-summary, M_PATH, LiDAR PCD).

Per-chapter rendering:
- A status-summary table at the top (one row per inventory entry, with the derived label).
- Per-row prose below the table — the `semantic` block rendered verbatim, followed by an "Open questions" sub-list rendered from `open_questions` (omitted when empty).
- Cross-references rendered as a "See also" footer per row, listing the apk / alt-repo / integration-code / protocol-doc references.
- A "do not edit by hand — source is `inventory.yaml`" banner at the top of every generated file.

`coverage-report.md` is the audit complement. Three sections:

1. **Probe-log slots not in inventory** — every `(siid, piid)`, `(siid, eiid)`, payload shape variant, or value range observed in the corpus that isn't represented as an inventory row.
2. **Cloud-dump artefacts not in inventory** — every CFG key, every `cfg_individual` endpoint, every `candidates` probe response in the dumps that isn't in the inventory.
3. **Apk-documented entries not in inventory** — entries the apk references that have no row.

Goal: this file is empty when axis 1 is done.

### 4.6 Cross-walk procedure (the build itself)

Sequential, scripted where possible:

1. **Walk probe-log corpus** — extract every observed `(siid, piid)`, `(siid, eiid)`, payload shape, and value range. Seed `properties.*.status.seen_on_wire`, `first_seen`, `last_seen`. Capture one example payload per slot for the doc.
2. **Parse cloud dumps** — extract every CFG key (with shape), every `cfg_individual` endpoint (with response or error code). Seed the `cfg_keys` and `cfg_individual` sections.
3. **Read `apk.md`** in `ioBroker.dreame/apk.md` — extract every documented siid/piid/aiid/CFG key. Seed `references.apk`.
4. **Read alt-repo property dictionaries** — `alternatives/dreame-mower/dreame/types.py`, `alternatives/dreame-vacuum/`, `dreame-mova-mower`. Seed `references.alt_repos`.
5. **Read greenfield code** — `mower/property_mapping.py`, `mower/actions.py`, `protocol/config_s2p51.py`, `protocol/cfg_action.py`, `protocol/telemetry.py`, `protocol/heartbeat.py`, `protocol/session_summary.py`, `coordinator.py`. Seed `references.integration_code` with `file:line` for every protocol slot the integration handles. (Reverse: rows whose `integration_code` is `null` after this step are the candidates for axis 4.)
6. **Read legacy code** — `ha-dreame-a2-mower-legacy` — diff against greenfield to spot decoders the rewrite dropped. Seed open questions where the diff is meaningful.
7. **Run read-only live probes** (with explicit "is this a good time to probe?" gate before each batch — the user noted some configs are locked during a mowing run, so a probe could yield wrong conclusions):
   - One fresh `getCFG` to confirm 24-key list + diff vs the 2026-05-05 dump.
   - Probe each `cfg_individual` target name we haven't tried (CMS as a routed-action, OBJ, REMOTE, MAPI by index, plus apk-documented ones).
   - `get_properties` for every apk-known piid we haven't seen on the wire (most will return 80001; a few may return data).
   - Walk the existing dump's `candidates` list to record which target names returned non-error.
   The probe tool emits a JSON delta the reviewer merges into the YAML manually; no auto-write.
8. **Synthesize** — produce `inventory.yaml` with one row per slot, populating every field that has evidence and leaving `null` where nothing is known. The `semantic` and `open_questions` blocks are hand-written, lifting the best content from `g2408-protocol.md` and the journal entries.
9. **Generate** — run `tools/inventory_gen.py` to produce `g2408-canonical.md` and `coverage-report.md`. Iterate until coverage-report is empty.
10. **Lint** — `tools/inventory_audit.py` re-walks the probe logs against the YAML and asserts no novel slots. Also asserts: every `decoded: confirmed` row has either `integration_code` or `bt_only` or `not_on_g2408`. CI-friendly.
11. **Archive alt-repo clones** — move the four alt-repo directories (`alternatives/`, `ioBroker.dreame/`, `dreame-mova-mower/`, `ha-dreame-a2-mower-legacy/`) from the user's working directory to `OLD/alternatives_archive_2026-05-05/`. The clones are kept (not deleted) for two reasons:
    a. **Protocol-info fallback** — past reviews repeatedly missed slots that turned out to be documented in these repos. Keeping them lets a future axis revisit a corner that was glossed in this pass.
    b. **HA UX patterns** — the legacy and Tasshack-derived integrations made specific choices about how to surface device state to users (which fields are sensors vs diagnostics, naming conventions, attribute layout). Those choices feed axes 4 (decoder enrichment / new entities) and 5 (live-test gap closure) more than the protocol bytes themselves.

    `OLD/README.md` records both purposes plus the one-line invocation for re-consulting (e.g. `grep -r 'siid.*piid' OLD/alternatives_archive_2026-05-05/`).

### 4.7 Live-probe safety rules

- The probe tool is read-only by construction. No `set_*` calls, no actions with side effects.
- Before each probe **batch**, the tool prints "About to send N read-only RPCs to <model> (<did>); current state shows <s2p1 mode> <s2p2 code>. Continue?" — user types `y` or `n`.
- Probes that fail with `80001` are normal on g2408 and don't fail the run.
- Probes that fail with `r=-1` / `r=-3` are recorded as "endpoint not supported on g2408" — also a successful inventory outcome.
- The tool never writes to `inventory.yaml` directly. It produces `tools/inventory_probe_delta.json` with the reviewer to merge by hand.

## 5. Tooling specification

### 5.1 `tools/inventory_gen.py`

Plain Python, stdlib only (`yaml` from `PyYAML` if available; otherwise a hand-rolled subset since we control the schema). No Jinja or external templating — string formatting suffices.

Inputs: `docs/research/inventory/inventory.yaml`
Outputs: `docs/research/inventory/generated/g2408-canonical.md`, `docs/research/inventory/generated/coverage-report.md`

Behaviour: idempotent; run as part of `pytest -k generated_docs_in_sync` in CI to catch hand-edits to generated files.

### 5.2 `tools/inventory_audit.py`

Inputs: `inventory.yaml`, glob of probe-log files (`probe_log_*.jsonl`), glob of cloud-dump files (`dreame_cloud_dumps/dump_*.json`).

Outputs: stdout report of slots/events/CFG-keys observed in inputs but absent from the YAML. Exit code 0 if all observations are accounted for; non-zero otherwise.

CI integration: a future axis 3 task wires this into PR checks. For axis 1, it's run by hand to drive iteration.

### 5.3 `tools/inventory_probe.py`

Inputs: HA / Dreame credentials from `ha-credentials.txt` / `server-credentials.txt` (read in situ, never copied out).

Behaviour: prompts before each probe batch (per §4.7), records every response, writes `tools/inventory_probe_delta.json`. Never modifies `inventory.yaml`.

The reviewer (a future axis-1 implementation step) merges the delta by hand, deciding per row whether the response confirms a hypothesis, contradicts one, or surfaces a novel slot.

## 6. Acceptance criteria

Axis 1 is done when all of the following hold:

1. `docs/research/inventory/inventory.yaml` exists with a row for every protocol artefact in scope (the 16 layers per §4.2).
2. Every `(siid, piid)` and `(siid, eiid)` observed in the probe-log corpus has an inventory row with `seen_on_wire: true`.
3. Every CFG key in the latest cloud dump has an inventory row.
4. Every apk-documented siid/piid/aiid/CFG-key/opcode has an inventory row (with `seen_on_wire: false` if not in our corpus).
5. Every (siid, piid) / (siid, aiid) / CFG key / opcode that the greenfield code currently handles has a row with `references.integration_code` populated to a `file:line` cite.
6. `tools/inventory_audit.py` exits 0 on the committed corpus + cloud dumps.
7. `tools/inventory_gen.py` produces `g2408-canonical.md` and an **empty** `coverage-report.md`.
8. The four alt-repo clones are moved to `OLD/alternatives_archive_2026-05-05/` with a `README.md` explaining the dual-purpose retention.
9. `docs/research/inventory/README.md` documents how to add a row, run the generator, run the audit, run a live probe.
10. Every numeric row that is exposed (or could plausibly be exposed) as an HA entity has a `unit` block specifying `wire`, `display`, and `scale`. Wire values must match the validated vocabulary (`tools/inventory_gen.py:_UNIT_VOCAB`); rows that introduce a new wire encoding extend the vocabulary in the same commit.
11. Every enum row (e.g. `s2p1` mode, `s2p2` state codes, charging-status, charging-pause-cause) has a `value_catalog` mapping integer values to user-facing labels.

The inventory is **not** required to have `decoded: confirmed` on every row at axis-1 completion. Rows can legitimately remain `decoded: hypothesized` or `decoded: unknown`; those become candidates for axis 5 (live-test gap closure). The hard requirement is that every observed thing has a row, and every row has a status.

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| YAML schema drift after axis 1 lands | `tools/inventory_audit.py` enforces schema and presence checks. Running it in CI is an axis-3 task; in axis 1, run manually. |
| Hand-merging `inventory_probe_delta.json` into `inventory.yaml` is error-prone | Probe tool emits a unified-diff-style delta and prints "review carefully before applying" — humans always read; auto-apply is intentionally absent. |
| The user's mower mid-mow status restricts which probes are safe | Per-batch gate (§4.7) shifts the responsibility to the user; tool refuses to run during a mowing session unless explicitly overridden. |
| Removing alt-repo clones loses access to source we may need to re-consult | Clones are **moved**, not deleted. Their git history stays available under `OLD/`. |
| Generator output drifts from YAML if someone hand-edits the markdown | The "do not edit by hand" banner + a `pytest` check that re-runs the generator and diffs ensures hand-edits are caught. |
| Inventory becomes a second place to maintain on top of `g2408-protocol.md` | Axis 2 dissolves this risk: `g2408-protocol.md` becomes a thin redirect to the generated canonical doc. Until then, both exist; the user accepted this transitional cost in the brainstorm. |

## 8. Hand-off to subsequent axes

- **Axis 2** (doc restructure): consumes the inventory; rewrites `g2408-protocol.md` and `TODO.md` to reference inventory rows by id rather than duplicating their semantic prose. Splits layered findings into `g2408-research-journal.md`.
- **Axis 3** (harness): runtime loads `inventory.yaml` and uses `seen_on_wire` + `decoded` to drive `[PROTOCOL_NOVEL]` suppression. CI runs `inventory_audit.py` against committed probe logs.
- **Axis 4** (decoder enrichment): every YAML row with `decoded: confirmed` AND `integration_code: null` is a candidate "expose this" task.
- **Axis 5** (live-test gap closure): every YAML row with `decoded: hypothesized | unknown` is a candidate test, with `open_questions` driving the test design.

## 9. Open assumptions to validate before coding

- The YAML lives in `docs/research/inventory/`. If the runtime should `import` it directly without a path-walk (axis 3 concern), it might prefer to live under `custom_components/dreame_a2_mower/protocol/`. Default to `docs/research/inventory/` for axis 1 and revisit at axis 3.
- The generator is plain Python, no Jinja or external deps. PyYAML is acceptable since the integration already depends on it indirectly via HA core.
- "Coverage-report empty" is the acceptance gate. If a more nuanced gate is wanted (e.g. "every observed slot has at least `decoded: hypothesized`"), call it out at review time.
- No automatic apply for `inventory_probe_delta.json` — humans always review and merge by hand, even if tedious.

## 10. References

- `/data/claude/homeassistant/ha-dreame-a2-mower/docs/research/g2408-protocol.md` — current layered-findings doc, source for `semantic` blocks
- `/data/claude/homeassistant/ha-dreame-a2-mower/docs/research/2026-04-17-g2408-property-divergences.md` — early divergence catalog
- `/data/claude/homeassistant/ha-dreame-a2-mower/docs/research/2026-04-23-iobroker-dreame-cross-reference.md` — apk cross-walk; primary input for `references.apk`
- `/data/claude/homeassistant/ha-dreame-a2-mower/docs/research/cloud-map-geometry.md` — coordinate-frame math; feeds `oss_map_keys` rows
- `/data/claude/homeassistant/ha-dreame-a2-mower/docs/lessons-from-legacy.md` — diff against greenfield
- `/data/claude/homeassistant/ha-dreame-a2-mower/TODO.md` and `docs/TODO.md` — gaps that become inventory `open_questions` content
- `/data/claude/homeassistant/ioBroker.dreame/apk.md` — primary apk decompilation source (to be archived to `OLD/` after absorption)
- `/data/claude/homeassistant/probe_log_*.jsonl` — wire-observation corpus
- `/data/claude/homeassistant/dreame_cloud_dumps/dump_*.json` — cloud-state corpus
