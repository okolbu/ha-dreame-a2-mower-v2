# g2408 Protocol Inventory

This directory holds the canonical, machine-readable description of every
protocol artefact the integration touches on a Dreame A2 (`g2408`) lawn
mower.

## Files

| File | Role |
|------|------|
| `inventory.yaml` | Source of truth. Edit by hand. |
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
# observed slot is missing:
python tools/inventory_audit.py

# Read-only live probe (asks before each batch); produces a delta
# JSON for the reviewer to merge by hand:
python tools/inventory_probe.py --read-only
```
