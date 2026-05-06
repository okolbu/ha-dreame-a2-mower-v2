# g2408 Protocol Inventory

> **2026-05-06 note:** `inventory.yaml` moved from `docs/research/inventory/`
> to `custom_components/dreame_a2_mower/` so HACS-installed users get the
> file alongside the runtime code. The generated docs (`g2408-canonical.md`,
> `coverage-report.md`) remain here under `generated/`. The schema and
> contributor workflow described below are otherwise unchanged.

This directory holds the canonical, machine-readable description of every
protocol artefact the integration touches on a Dreame A2 (`g2408`) lawn
mower.

## Files

| File | Role |
|------|------|
| `../../custom_components/dreame_a2_mower/inventory.yaml` | Source of truth. Edit by hand. |
| `generated/g2408-canonical.md` | Human-readable reference. Generated. |
| `generated/coverage-report.md` | Audit complement. Empty when complete. |
| `README.md` | This file. |

## Adding a row

Pick the right section (`properties`, `events`, `actions`, etc.) and
append a new entry. The generic schema:

```yaml
- id: "s2p52"                  # category-unique id; used in cross-refs
  siid: 2                       # only for properties/events/actions
  piid: 52                      # ditto
  name: "preference_update_trigger"
  category: "trigger"           # property | blob | trigger | event | multiplexed
  payload_shape: "empty_dict"

  unit:                          # only for numeric scalars; omit for bool/struct
    wire: "cm"
    display: "m"
    scale: 0.01
    format: "{:.2f}"
    notes: "optional clarifying note"

  value_catalog:                 # only for enums; omit otherwise
    0: "off"
    1: "on"

  semantic: |
    Multi-paragraph human-readable description. Lives here, not in
    g2408-protocol.md. Cite confirmation evidence.

  status:
    seen_on_wire: true
    first_seen: "2026-04-17"     # date of first probe-log appearance
    last_seen: "2026-04-30"
    decoded: confirmed           # confirmed | hypothesized | unknown
    bt_only: false
    not_on_g2408: false

  references:
    apk: "ioBroker.dreame/apk.md §parseRobotPose"
    alt_repos:
      - "alternatives/dreame-mower/dreame/types.py:725"
    integration_code: "custom_components/dreame_a2_mower/mower/property_mapping.py:80"
    protocol_doc: "docs/research/g2408-protocol.md §4.7"

  open_questions:
    - "Does this also fire on PIN-update, or only PRE?"
```

Fields that don't apply to a row's category are simply omitted.

## Status taxonomy

The generator computes a single label per row from the booleans in `status`:

| Label | Condition |
|-------|-----------|
| `WIRED` | `references.integration_code` is non-null |
| `DECODED-UNWIRED` | seen + decoded confirmed + no integration handler |
| `SEEN-UNDECODED` | seen on wire, decoded != confirmed |
| `APK-KNOWN` | not seen, documented in apk |
| `UPSTREAM-KNOWN` | not seen, only in alt repos |
| `BT-ONLY` | feature exists but cloud-invisible |
| `NOT-ON-G2408` | confirmed missing/error on g2408 firmware |

A row matching multiple conditions picks the first row in the table.

## Unit vocabulary

`unit.wire` values are validated against a closed list. To add a new wire
encoding, extend `_UNIT_VOCAB` in `tools/inventory_gen.py` in the same
commit as the row that introduces it. Current vocab:

```
cm, mm, m, decimetres, centiares, m2, m2_x100, signed_dbm,
unsigned_byte, signed_byte, minutes_from_midnight, unix_seconds,
percent, percent_x100, degrees, degrees_x256, bool, enum,
raw_bytes, string
```

## Tools

```bash
# Render canonical doc + coverage report:
python tools/inventory_gen.py

# Audit committed corpus against the inventory; non-zero exit if any
# observed slot is missing OR if any inventory claim contradicts the corpus:
python tools/inventory_audit.py

# Run only the consistency checks (skip presence checks):
python tools/inventory_audit.py --consistency

# Read-only live probe (asks before each batch); produces a delta
# JSON for the reviewer to merge by hand:
python tools/inventory_probe.py --read-only
```

### Consistency checks

The audit runs two passes by default:

**Presence pass** (5 sections): verifies every (siid, piid), event, CFG key,
and `cfg_individual` endpoint observed in the probe/dump corpus has an inventory
row. This catches omissions — things we saw but didn't document.

**Consistency pass** (3 sections): reconciles every _claim_ in the inventory
against the corpus. Specifically:

1. **`not_on_g2408: true` rows**: scan all `dump_*.json` files for an `ok`
   response under that endpoint name. If ANY dump shows `ok` → contradiction
   (the endpoint does respond, so the row is wrong).
2. **`seen_on_wire: false` rows** (properties): scan all `probe_log_*.jsonl`
   for the slot's (siid, piid). If observed → contradiction (the slot was seen,
   so the row is wrong).
3. **`value_catalog` membership**: for property rows with a `value_catalog` AND
   `seen_on_wire: true`, collect every scalar value observed in the probe corpus
   for that (siid, piid). Any value not in the catalog → contradiction (possible
   novel enum value that the row should document).

The consistency pass exists because the presence pass was blind to _wrong_
claims in existing rows — only catching missing rows.

### Empirical caveat: r=-1 / r=-3 are not proof of feature absence

`r=-1` and `r=-3` responses from `cfg_individual` endpoints are **stateful or
transient** — they do not prove the feature is absent from the firmware. The
MISTA endpoint, for example, returned `r=-1` in dumps 1 and 2 but a full `ok`
payload in dump 3 (same firmware, different mower state). With only 3 cloud
dumps in the corpus, the sample is too small to claim non-support. Any row
previously marked `not_on_g2408: true` solely on the basis of `r=-1`/`r=-3`
responses has been downgraded to `decoded: hypothesized`.

## What "decoded: confirmed" means

`decoded: confirmed` is a strong claim — it means **direct, load-bearing
evidence exists** in at least one of these forms:

- (a) The integration's runtime code reads the slot from MQTT/API and surfaces
  a value in Home Assistant (`references.integration_code` is populated and the
  value is non-fabricated).
- (b) The wire shape is documented in a primary source (apk.md decompilation,
  or a referenced alt-repo), AND the slot was directly observed in the probe
  corpus with a value consistent with that documentation.

`decoded: confirmed` does NOT mean "we believe this is correct" or "this is
probably right". It means evidence is direct and the claim is load-bearing. If
only partial evidence exists (apk-documented but not seen on wire, or seen on
wire but semantics inferred), the row stays at `decoded: hypothesized`.

## Caveats and what's still uncertain

- **Structurally absent slots**: firmware-update slots (s1p2, s1p3), patrol
  logs, multi-floor maps, and change-PIN sequences have no probe-log
  observations because no such events occurred during the capture period. They
  remain `decoded: hypothesized` with open questions to trigger future capture.
- **Small-sample problem with r=-1 / r=-3**: only 3 cloud dumps exist. Any
  endpoint that returned errors in all dumps may still respond `ok` under
  different mower state (post-mow, mid-mow, BT-active, etc.). Watchdog passes
  should retry these endpoints in varied states before marking anything
  `not_on_g2408: true`.
- **Watchdog's role**: the consistency audit is the standing watchdog. Running
  it against new probe logs or cloud dumps as they arrive will surface any
  new `seen_on_wire` contradictions or novel enum values automatically.
