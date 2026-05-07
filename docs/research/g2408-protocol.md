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

### Observed OSS-fetch failure modes

- **`getFileUrl("")` returns a signed URL that 404s** — querying without an
  object name gives a syntactically valid signed URL pointing at an empty
  bucket entry. Confirms the bucket is empty for the guess; treat as
  "object key not yet pushed", not as auth failure.
- **`get_properties(s6p3)` returns `None`** while the mower is idle — the
  property only materialises when there's a pending map. Don't poll it;
  observe the push on its arrival.
- **`get_properties(...)` returns `{"code":10001,"msg":"消息不能读取"}`** when the
  mower is idle — Chinese "message cannot be read"; the cloud→mower RPC
  channel is quiescent, so no property snapshot can be pulled on demand.
  Same family as 80001 (§1.2).
- **`_request_current_map()` fails with 80001 during active mowing** — for the
  same reason `sendCommand` always fails on g2408 (§1.2). The OSS fetch
  pipeline still works in parallel; the RPC tunnel does not.

### Multi-map (MAP.* split via MAP.info)

When the device has multiple cloud-side maps, the `MAP.0..MAP.27`
batch response carries all of them concatenated in the joined string.
The auxiliary key `MAP.info` is the byte offset where the second
map's JSON starts; parse each segment as its own JSON list.

Each segment is wrapped as a one-element list whose inner dict has
the standard map keys (`boundary`, `mowingAreas`, `contours`, etc.)
plus `mapIndex` (0-indexed) and `name`.

Active-map detection uses `cfg_individual.MAPL` — a list of rows,
one per map. Row layout `[map_id, is_active, ?, ?, ?]`; the row with
col 1 == 1 is the active map. Cols 2–4 are undecoded as of 2026-05-07.

The integration's `cloud_client.fetch_map` returns
`dict[map_id, dict] | None`; `map_decoder.parse_cloud_maps` returns
`dict[map_id, MapData]` with each `MapData.map_id`, `MapData.name`,
and `MapData.nav_paths` populated.

See journal topic [Multi-map support — wire confirmation 2026-05-07].

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

## 6. Confirmed working — live status

_(Filled in Phase D from the OLD TODO.md's "Live-confirmed" bullet list.)_

## 7. See also

- `docs/research/inventory/README.md`
- `docs/research/inventory/generated/g2408-canonical.md`
- `docs/research/g2408-research-journal.md`
- `docs/research/cloud-map-geometry.md` — coordinate-frame math, renderer-side
- `docs/TODO.md` — open work list
