# Cloud read/write reference (g2408)

This document is the canonical reference for talking to g2408's Dreame
Cloud (`eu.iot.dreame.tech:19973`). It covers both READ and WRITE paths
for the chunked-batch surface.

## Authentication

`DreameA2CloudClient(username, password, country="eu")` then
`client.login()`. Region for the user's account is `eu`. After login,
call `client.get_devices()` to discover the device, then
`client.get_device_info()` to populate `_host` (needed for routing).

## READ — `get_batch_device_datas([])`

The empty-list batch returns ALL chunked keys the device has.
Endpoint: `dreame-user-iot/iotuserdata/getDeviceData` (via wrapper).
Payload: `{"did": <did>, "model": [<key_list_or_empty>]}`.
Returns: `{<key>: <value>, ...}` dict.

Confirmed key families (g2408 fw 4.3.6_0550):
- `MAP.0..45 + MAP.info` — boundary geometry, mowing zones, exclusion
  zones, etc. Map 0 + Map 1 split at MAP.info byte offset.
- `M_PATH.0..N + M_PATH.info` — persisted mow trajectories from prior
  sessions. Per-map split at M_PATH.info byte offset.
- `SETTINGS.0..N + SETTINGS.info` — per-map mowing-behaviour settings
  (mowingHeight, mowingDirection, edgeMowingAuto, etc.). Dual-level
  structure: two top-level entries, both `mode: 0`. **The LAST entry
  is firmware-authoritative** (verified 2026-05-09): when the user
  edits a setting in the Dreame app, only the last entry updates; if
  a reader takes entry 0 it sees stale values. The integration reads
  `raw[-1]` and writes to ALL entries — see "Dual-entry semantic"
  below.
- `SCHEDULE.0 + SCHEDULE.info` — schedule slots + plans. JSON shape
  `{"d": [[id, mode, name, base64_blob], ...], "v": version}`. The
  per-slot `mode` field (entry index 1, NOT the SETTINGS top-level
  `mode`) is **1 for the active/primary slot, 0 for an empty/secondary
  slot** — must be round-tripped on writes; hardcoding 0 turns an
  active slot off (verified 2026-05-09 by parse/encode round-trip
  against live cloud value, byte-identical).
- `AI_HUMAN.0` — Capture Photos AI Obstacles toggle. JSON-encoded bool.
- `FBD_NTYPE.0 + .info` — forbidden-area node types per map.
- `OTA_INFO.0 + .info` — firmware update status `(int, percent_int)`.
- `TASKID.0 + .info` — current/last task ID.
- `prop.s_*` — Xiaomi-style standalone properties (auth_config, auto_upgrade, pri_plugin).

## WRITE — `setDeviceData` (the chunked-batch write surface)

**Confirmed working 2026-05-08 for AI_HUMAN, SCHEDULE, SETTINGS.**

Endpoint: `dreame-user-iot/iotuserdata/setDeviceData`
Payload: `{"did": <did>, "data": {<key>: <value>, ...}}`
Wrapper: `cloud_client.set_batch_device_datas(props)` (the wrapper
sends payload under `data`, NOT `model`).

**Server-enforced cap: 1024 chars per value.** Large blobs need
chunking: `KEY.0..N + KEY.info(total_length_str)`.

Use `cloud_client.write_chunked_key(key_prefix, value, info=None)` —
handles chunking automatically. `info` defaults to `str(len(value))`
when chunking; omitted for single-chunk writes (matches the
AI_HUMAN.0 / SCHEDULE.0 single-chunk pattern observed live).

**Success response:** `{"code": 0, "success": true, "msg": "设置成功"}`
("setup successful" in Chinese).

**Common failure response:**
- `{"code": 10007, "msg": "value值不能超过1024个字符"}` — value > 1024
  chars not chunked.
- `{"code": 10007, "msg": "data:must not be empty"}` — payload sent
  under wrong field name (e.g. `model` instead of `data`).
- `{"code": 80001, "msg": "设备可能不在线..."}` — wrong RPC path
  entirely (this is the rejection direct `set_properties` gives for
  most siids on g2408 — use this endpoint instead).

## Confirmed-writable keys (Phase 1)

| Key | Single-chunk? | Notes |
|---|---|---|
| `AI_HUMAN.0` | yes | JSON-encoded bool: `'"true"'` / `'"false"'` |
| `SCHEDULE.0` | yes (typically <500 chars) | Bump `v` field on each write; preserve per-slot `mode` (1=active, 0=empty) |
| `SETTINGS.0..N` | no — dual-level structure ~1780 chars | Read-modify-write the LAST entry (firmware-authoritative); writes propagate to ALL entries |

## Dual-entry semantic (SETTINGS)

`SETTINGS` always carries TWO top-level dict entries, both with
`mode: 0` and the same `settings` map_id keys. Despite the matching
keys their *values* can diverge — they are NOT interchangeable.

Live evidence 2026-05-09 (g2408 fw 4.3.6_0550, snapshot of the
user's account at the time):

```
entry0/map0: obstacleAvoidanceAi=6  mowingDirection=0    edgeMowingWalkMode=0
entry0/map1: obstacleAvoidanceAi=7  mowingDirection=180  edgeMowingWalkMode=0
entry1/map0: obstacleAvoidanceAi=7  mowingDirection=180  edgeMowingWalkMode=1
entry1/map1: obstacleAvoidanceAi=7  mowingDirection=180  edgeMowingWalkMode=1
```

Behaviour, observed across two write paths:

- **App edits** update entry 1 only. Entry 0 drifts stale.
- **Integration writes via `setDeviceData`**: writing to entry 0 only
  is silently accepted (cloud returns `code=0`) but the firmware/app
  keeps reading entry 1 — the toggle never appears in the app. Found
  while debugging the AI obstacle-recognition switches; see commit
  `db507c9 fix(settings): write to BOTH dual-level entries`.
- **Integration reads from entry 0** (legacy, pre-2026-05-09) showed
  stale values whenever the user used the app to change a setting.
  Fixed by switching the canonical read to `raw[-1]`.

Concrete rule for any future client:

1. **Read** the last entry as the canonical source of truth.
2. **Write** by mutating the target field on every entry that carries
   the target `map_id`. Other map_ids in those entries are left
   alone (this preserves per-map customisation).

Entry 1's exact role beyond "firmware-authoritative" is still
unknown — possible interpretations include "current applied" vs
"user-staged", a journal/log layer, or per-mode profiles where
both currently happen to use `mode: 0`. Reading the last entry is
forwards-compatible with any of those.

## SCHEDULE per-slot mode flag

The wire shape `[slot_id, mode, name, blob_b64]` carries a per-slot
`mode` (entry index 1) that is distinct from the SETTINGS top-level
`mode` field. Live values (verified 2026-05-09):

```
[0, 1, "Spr & Sum Schedule", <blob with 5 plans>]   # active/primary
[1, 0, "",                   <blob with 1 plan>]    # empty/secondary
```

The flag survives across captures even when the same slot's plan
list is edited, so it does NOT track plan count. Best current
hypothesis: 1=user-active, 0=template/empty. Whether the slot's
"Enabled" toggle in the app maps to this byte is not yet confirmed
(the blob is byte-identical between toggled and untoggled states —
the toggle lives elsewhere, see g2408-research-journal.md).

Round-trip rule: parsers MUST capture this byte and encoders MUST
re-emit it. Earlier integration code hardcoded `0` and would have
silently disabled an active slot on every save via the
`set_schedule_plans` service.

## TBD (Phase 2/3)

| Key | Status | Notes |
|---|---|---|
| `MAP.0..N` | NOT TESTED | Risk: corrupting boundary geometry could brick the map. Phase 2 — needs auto-backup mechanism. |
| `M_PATH.0..N` | NOT TESTED | Likely writable (same surface) but writing prior trajectories has no obvious user value. |
| `OTA_INFO.0` | UNSAFE | Firmware-managed; do not write. |
| `TASKID.0` | UNSAFE | Firmware-managed; do not write. |
| `FBD_NTYPE.0` | NOT TESTED | Phase 2 — likely writable; correlates with map editing. |
| `prop.s_*` | NOT TESTED | Probably read-only Xiaomi metadata. |

## Why `set_properties` (MIoT path) doesn't work for most siids

Direct MIoT `set_property(siid, piid, value)` rejects with **80001**
("device may be offline / command timeout") for most siids on g2408.
Tried 2026-05-08:
- `s8.2` (SCHEDULE per upstream docs) — 80001
- `s4.22` (AI_DETECTION per upstream docs) — 80001

The setDeviceData chunked-batch endpoint is the working alternative
for everything in the cloud-batch read surface. Direct MIoT may still
work for siids that came up in the integration's existing tested set
(`s2.50` routed_action for tasks, etc.).

## Live-test harness

Probes preserved in `/tmp/`:
- `probe_schedule_write.py` — schedule add/restore round-trip
- `probe_ai_human_write.py` — toggle round-trip
- `probe_writable_surface.py` — SETTINGS chunked round-trip
- `probe_batch_write.py` — payload-shape discovery (the original
  finding of `data` vs `model` field)

All bypass HA — pure Python with stubbed `homeassistant.const` import,
direct cloud_client usage. Useful template for Phase 2/3 probing.
