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
