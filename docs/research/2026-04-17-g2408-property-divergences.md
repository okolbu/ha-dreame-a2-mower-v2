# g2408 siid/piid Divergence Catalog

Derived from probe-log analysis (`probe_log_20260417_095500.jsonl`, 2443 MQTT messages over a full mowing session) to inform Plan C's property-mapping overlay.

## Observed g2408 siid/piid combinations

| siid.piid | events | example values | upstream name at same siid.piid | classification |
|-----------|--------|----------------|---------------------------------|----------------|
| 1.1 | 884 | list(len=20) | — | New (blob) |
| 1.4 | 1125 | list(len=33); list(len=8) | — | New (blob) |
| 1.50 | 2 | `{}` | — | New (session marker) |
| 1.51 | 2 | `{}` | — | New (session marker) |
| 1.52 | 2 | `{}` | — | New (session marker) |
| 1.53 | 87 | False; True | — | New (boolean) |
| 2.1 | 11 | 1; 2; 5 | STATE | Match-but-different-semantics |
| 2.2 | 9 | 48; 54; 70 | ERROR | Divergence (g2408 emits state codes here) |
| 2.50 | 3 | `{d, t}` keys | — | New (session event) |
| 2.51 | 49 | `{end, start, value}`, `{time, tz}` | — | New (multiplexed config) |
| 2.56 | 4 | `{status}` keys | — | New (status push) |
| 3.1 | 239 | 90; 91; 92 | BATTERY_LEVEL | Match |
| 3.2 | 7 | 0; 1; 2 | CHARGING_STATUS | Match |
| 5.105 | 3 | 1 | — | New (unknown telemetry) |
| 5.106 | 8 | 3; 5; 7 | — | New (unknown telemetry) |
| 5.107 | 6 | 133; 176; 250 | — | New (dynamic, unknown) |
| 6.1 | 1 | 300 | MAP_DATA | Match |
| 6.2 | 9 | list(len=4) | FRAME_INFO | Match |

**Totals:** 18 distinct g2408 siid/piid combinations. 6 already match upstream names (but see 2.1/2.2 semantic swap below). 12 are new to g2408.

## The critical divergence: `STATE` and `ERROR` are swapped at siid=2

Upstream's mapping assigns:
- `DreameMowerProperty.STATE → (2, 1)`
- `DreameMowerProperty.ERROR → (2, 2)`

But on g2408:
- **siid=2, piid=1** emits values like 1, 2, 5 (small enumerations; semantics unknown — possibly a high-level mode or warning code).
- **siid=2, piid=2** emits values 48, 54, 70, 50, 27 — these are the g2408 **state codes** documented in project memory (mowing=70, returning=54, complete=48, session_started=50, idle=27).

Upstream will read 48/54/70 as "ERROR" codes and 1/2/5 as "STATE" values — both wrong. The overlay must swap the assignments for g2408.

## Second-order finding: `s1p4` has two payload lengths

1.4 emits both 33-byte (1119 events) and 8-byte frames (6 events). Plan B's `decode_s1p4` only handles 33-byte frames and will reject 8-byte frames with `InvalidS1P4Frame`. The blob dispatcher in Task 4 must catch this and log without poisoning entity state.

The 8-byte variant is likely a sentinel or heartbeat-style ping (e.g. "I'm alive but not mowing"). Decoding that variant is deferred — Plan B scope was 33-byte frames only.

## New properties requiring enum entries + overlay

| Property name | g2408 siid.piid | payload | Decoder | Covered by Plan C task |
|---------------|-----------------|---------|---------|------------------------|
| `HEARTBEAT` | 1.1 | 20-byte list | `decode_s1p1` | Task 5 |
| `MOWING_TELEMETRY` | 1.4 | 33-byte list | `decode_s1p4` | Task 4 |
| `OBSTACLE_FLAG` | 1.53 | bool | (none — plain scalar) | Task 8 |
| `MULTIPLEXED_CONFIG` | 2.51 | dict | `decode_s2p51` | Task 5 |

## Properties to defer (documented for later plans)

Events observed but not in Plan C scope:

| siid.piid | semantic guess | count | why deferred |
|-----------|----------------|-------|--------------|
| 1.50, 1.51, 1.52 | Session boundary markers (`{}` empty dicts) | 2 each | Low-value — session lifecycle is already derivable from state transitions |
| 2.50 | Session task metadata `{d, t}` | 3 | Useful but not blocking HA entities — Plan E (map) may consume |
| 2.56 | Cloud status push `{status}` | 4 | Internal acknowledgements; no user-facing need |
| 5.105, 5.106, 5.107 | Unknown dynamic values | 3/8/6 | Research needed to identify meaning — project memory Open Item #4 |

Leaving these un-mapped means they're silently dropped by `_message_callback`. No behaviour regression vs pre-overlay.

## Actions for Plan C

### Task 2 — `_G2408_OVERLAY` minimum entries

```python
_G2408_OVERLAY: dict[DreameMowerProperty, dict[str, int]] = {
    # g2408 swaps STATE and ERROR compared to upstream.
    DreameMowerProperty.STATE: {siid: 2, piid: 2},
    DreameMowerProperty.ERROR: {siid: 2, piid: 1},
}
```

### Task 4 — extend overlay + enum

```python
class DreameMowerProperty(IntEnum):
    ...
    MOWING_TELEMETRY = <new_int>

_G2408_OVERLAY[DreameMowerProperty.MOWING_TELEMETRY] = {siid: 1, piid: 4}
```

### Task 5 — extend overlay + enum

```python
class DreameMowerProperty(IntEnum):
    ...
    HEARTBEAT = <new_int>
    MULTIPLEXED_CONFIG = <new_int>

_G2408_OVERLAY[DreameMowerProperty.HEARTBEAT] = {siid: 1, piid: 1}
_G2408_OVERLAY[DreameMowerProperty.MULTIPLEXED_CONFIG] = {siid: 2, piid: 51}
```

### Task 8 — extend overlay + enum

```python
class DreameMowerProperty(IntEnum):
    ...
    OBSTACLE_FLAG = <new_int>

_G2408_OVERLAY[DreameMowerProperty.OBSTACLE_FLAG] = {siid: 1, piid: 53}
```

### Matches needing no overlay

- 3.1 BATTERY_LEVEL
- 3.2 CHARGING_STATUS
- 6.1 MAP_DATA
- 6.2 FRAME_INFO

These should work out-of-the-box for g2408 once the overlay is wired in Task 3. If after Task 10 deploy any of these still shows "Unavailable", double-check that the entity binding in `sensor.py` uses the right `DreameMowerProperty` enum key.
