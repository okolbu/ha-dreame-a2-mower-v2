# Dreame A2 (`g2408`) Protocol — Overview

> **Status — STABLE OVERVIEW.** Cross-cutting prose only (transport layer, OSS fetch, coordinate math, novel-property guide). Per-entity wire formats and per-slot semantics live in the authoritative docs below — when this doc and the entity-validation-matrix disagree on a wire format, the matrix wins. Last reviewed 2026-05-09; mostly evergreen but watch for drift in the transport-layer section as the integration's RPC surface evolves.

This is the cross-cutting reference for the `g2408` protocol. For
**slot-by-slot detail** (every property / event / action / CFG key /
heartbeat byte / telemetry field / etc.) see the canonical doc:

- **`docs/research/inventory/generated/g2408-canonical.md`** — generated
  from `docs/research/inventory/inventory.yaml` (the source of truth).
- **`docs/research/inventory/README.md`** — how to read and extend the
  inventory.

For the **history of how we figured each thing out** (hypothesis cycles,
deprecated readings, dated findings) see the research journal:

- **`docs/research/g2408-research-journal.md`** — topic-clustered. *Read for context, not as current truth.* Many entries describe hypotheses that were later refined or disproved; the "Quick answer" header on each topic is the current reading, but everything below it is timeline.

For the **per-entity authoritative source of truth** (every HA entity, its
read source, write path, and live-verification status):

- **`docs/research/entity-validation-matrix.md`** — when in doubt, this wins.

For the **cloud transport layer** (auth, endpoints, payload framing, response
codes for routed-action / set_cfg / setDeviceData / chunked-batch):

- **`docs/research/cloud-write-reference.md`**.

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

## s2p2 — error / fault code (apk FaultIndex)

**Important**: `s2p2` is the **error_code / fault index** per apk
decompilation, NOT a state machine and NOT a pure "notification code".
The Dreame app's push notifications align with fault transitions
because the cloud uses fault changes as APNS triggers, but the
underlying semantic is "current fault/state index from apk §FaultIndex."

Live-correlated codes (historical + 2026-05-11 cross-reference
against app notification history). Values not in this table will fire
exactly one `[PROTOCOL_NOVEL] s2p2 carried unknown value=…` WARNING.

Each row's **Confidence** column distinguishes confirmed mappings
(live-correlated against the app notification or apk decompilation)
from working hypotheses that need more evidence. **HYPOTHESIS** rows
must NOT be relied on for automation triggers without independent
verification.

| value | bits | meaning | Confidence | Source / evidence |
|---|---|---|---|---|
| 0 | 00000000 | HANGING | apk | apk fault index 0; observed 2026-04-30 19:37:13 (only) |
| 1 | 00000001 | unknown | UNCONFIRMED | observed 2026-04-30 19:37:05 (only, cluster with 0, 9) |
| 9 | 00001001 | unknown | UNCONFIRMED | observed 2026-04-30 19:37:57 (only) |
| 23 | 00010111 | EMERGENCY_STOP | apk + correlation | apk fault index 23; 4/4 fires 2026-05-09 21:56-22:18 match app push "Emergency stop is activated. Tap to view the solution." 23 fires immediately followed (~0-1s) by 73 (TOP_COVER_OPEN) — the cover-open is what physically triggers the emergency stop. App shows the 23 message; the 73 doesn't surface a separate notification in this pairing |
| 27 | 00011011 | HUMAN_DETECTED | apk + observation | apk fault index 27; 50 firings Apr 20-24 (user reports heavy human-presence testing in that window) |
| 28 | 00011100 | Blades severely worn — replace soon | correlation | 2026-05-15 16:18:51 fired 1s after a 70 (continue_unfinished_task); the user observed app push "Blades are severely worn. Replace them soon" at the same minute. The wear%-from-CMS sensor lives elsewhere; this s2p2 code is what triggers the cloud push. App-side may repeat the notification (3 additional repeats observed same day with no fresh s2p2 transition). |
| 30 | 00011110 | Maintenance reminder active mid-mow | memory | from `feedback_g2408_maintenance_state` memory note |
| 31 | 00011111 | Positioning-failed-stuck (post-33→31 sequence) | observation | 2026-04-20 19:28 after Manual-session ended off-dock |
| 33 | 00100001 | Positioning-failed-stuck (pre-31 transient) | observation | 2026-04-20 19:28 same incident; 33→31 is the canonical "stuck" pair |
| 36 | 00100100 | unknown | UNCONFIRMED | single observation 2026-04-20 19:34:20 in Apr 20 evening cluster (user notes that evening was likely Manual-mode runs which do not appear in the work log) |
| 43 | 00101011 | Battery temperature too low — charging paused | apk + correlation | apk + 2026-04-20 06:25/07:54 firings match app "Battery temperature is low. Charging stopped." plus `s1p1 byte[6] & 0x08` low-temp flag |
| 48 | 00110000 | Mowing complete / session ended | correlation | 2/2 firings 2026-05-11 match app "Mowing complete" |
| 50 | 00110010 | Normal mow active | memory | from `project_g2408_maintenance_state` memory note |
| 53 | 00110101 | Scheduled mowing started | correlation | 1/1 match 07:58 "Sched mow started" |
| 54 | 00110110 | Low battery — returning to dock | correlation | 6/7 align with "Low batt" notifications |
| 56 | 00111000 | BAD_WEATHER / Rain protection — water on LiDAR | apk + correlation | apk fault 56; 1/1 match 13:33 "Water on lidar"; also 2026-05-04 hose-down test |
| 60 | 00111100 | unknown — observed 2026-04-27 07:58:02 (Monday) at scheduled-mow-start minute, but no work log entry implies the mow did not actually run | HYPOTHESIS: scheduled mow cancelled due to pre-condition fail (low temp, etc.) — sibling to 53 | user hypothesis 2026-05-11 from work-log absence |
| 63 | 00111111 | Scheduled task cancelled — Robot working | correlation | 1/1 match 17:30 "Sched task cancelled" |
| 70 | 01000110 | Continue unfinished task / mowing (edge or standard) | correlation | 7/8 align with "Continue" |
| 71 | 01000111 | Positioning failure — now confirmed THREE contexts, distinguished by what follows: (a) 33→31 cascade = hard-stuck waiting for user help; (b) 5→s1p4→6 = firmware-initiated SLAM relocation for self-recovery + mowing resumes; (c) lone 71 → s2p1=5→6 (returning → docked) with NO mowing resume = watchdog auto-return from idle-outside-station-too-long (app surfaces this third context as "The robot is on standby outside the station for too long. Automatically returning to the station."). Same s2p2 code, three behaviors, three different app texts. | observation | (a) 2026-04-20 19:28; (b) 2026-04-27 11:52 controlled tests; (c) 2026-05-12 21:00:41 (probe_log_20260510_190812.jsonl) |
| 73 | 01001001 | TOP_COVER_OPEN | apk + observation | apk fault 73; 2026-05-04 5-test series. Note: the PIN-required lockout (`s1p1 byte[3] bit 7`) is a separate flag that clears only on PIN entry, NOT on cover close — cover-open and PIN-lockout are independent states despite often firing together |
| 75 | 01001011 | Arrived at Maintenance Point | observation | 2026-04-20 18:18:05 after Head-to-MP task; apk also lists same code as LOW_BATTERY_TURN_OFF — same code may have two meanings depending on preceding state, NOT confirmed which applies when |
| 78 | 01001110 | ROBOT_IN_HIDDEN_ZONE | apk | apk fault catalog; not observed in our probe logs |
| 117 | 01110101 | STATION_DISCONNECTED | apk | apk fault catalog; not observed in our probe logs |

**Single-shot observations** (`s2p2 = {0, 1, 9, 36, 60, 75}` each seen
once in 22 days of probe captures) — per user note, "Only 1 of anything
is likely to be a non-standard event, as we've tried most things multiple
times" — meaning these are likely real events tied to specific actions
rather than recurring states. Codes 60 and 36 in particular still lack
correlated app-side or work-log evidence to confirm meaning.

The `s5p107` slot is a per-event UUID/hash (different value per
firing, no stable meaning) — NOT a notification code despite firing
near notification times.

## s6.2 — User-edit profile push (PRE-family)

**Wire shape**: `[mowing_height_mm, mowing_efficiency, edgemaster_bool, byte3]` (4-element list; byte[3] is usually 2 but not strictly constant — see element notes below)

**Encoding**:
- `[0]` (mowing_height_mm): integer, millimetres. User-visible values: 30, 40, 50, 60 (cm × 10).
- `[1]` (mowing_efficiency): integer enum. `0` = Standard, `1` = Efficient. **Verified live 2026-05-14**.
- `[2]` (edgemaster): boolean. False = Off, True = On. **Verified live 2026-05-14**.
- `[3]`: usually 2 (64 of 65 historical pushes in `probe_log_20260419_130434.jsonl`), but **not constant** — observed `198` once at 2026-05-10 17:04:16 in the value `[60, 0, True, 198]`. That outlier coincided with a mid-mow efficiency change (byte[1] flipped 1→0 in the same push); the 198 didn't re-appear in subsequent captures. Meaning still unknown; not yet ruled-in or ruled-out for any specific app setting. Earlier "constant 2" claim retracted 2026-05-14.

**Per-map nature**: app-side only. The device protocol exposes ONLY the
active map's last-pushed values. Storage is in the Dreame app's local
state, not on the device. **Verified 2026-05-14**: map switching does
NOT trigger an s6.2 push; only the s1p50 "something changed" ping
fires. Editing on map1 vs map2 produces packets with different values
for [0]/[2] because the app pushes the FULL active-map profile on any
settings-page save (verified by flipping efficiency on map1 → caused
height AND edgemaster to update too).

**Modelling implication**: per-map values can be learnt over time by
tagging each s6.2 push with the currently-active map_id (from MAPL
poll cache). Initial state has no per-map data; converges as the user
saves settings on each map. See `state_machine.handle_pre_shadow_update`
and the per-map diagnostic sensors
`sensor.<map>_pre_mowing_height_cm`,
`sensor.<map>_pre_mowing_efficiency`,
`sensor.<map>_pre_edgemaster`.

**Live test sequence used to verify** (2026-05-14 19:30–19:36 local,
g2408 fw 4.3.6_0550, integration v1.0.10a7):

| Time | Action | s6.2 result |
|---|---|---|
| 19:33:21 | Map2 efficiency Standard→Efficient, save | `[60, 1, 1, 2]` (byte[1]=1; [0]/[2] reflect map2's full state) |
| 19:35:35 | Map2 efficiency Efficient→Standard, save | `[60, 0, 1, 2]` (byte[1] 1→0, confirming byte[1] is efficiency) |
| 19:36:00 | Switch active map → Map1 | NO s6.2 push. Only s1p50 ping. |
| 19:36:42 | Map1 efficiency Efficient→Standard, save | `[30, 0, 0, 2]` (full map1 profile pushed: height 60→30, edgemaster 1→0, efficiency stays 0) |

**Second test 2026-05-14 20:10–20:12: isolated EdgeMaster toggles** (same
firmware/integration). Confirms EdgeMaster cleanly flips byte[2] when
toggled alone, and re-confirms the silent map-switch (no s6.2 emission):

| Time | Action | s6.2 result |
|---|---|---|
| 20:10:48 | Map1 EdgeMaster Off→On, save | `[30, 0, True, 2]` (only byte[2] differs from prior frame) |
| 20:11:14 | Map1 EdgeMaster On→Off, save | `[30, 0, False, 2]` |
| ~20:11:3x | Switch active map → Map2 (map2's stored state was On) | NO s6.2 push. Only s1p50 ping. (re-confirmed.) |
| 20:11:50 | Map2 EdgeMaster On→Off, save | `[60, 0, False, 2]` (byte[0] reflects map2's stored 60mm height) |
| 20:12:34 | Map2 EdgeMaster Off→On, save | `[60, 0, True, 2]` |

**Encoding note**: the JSON payload always carries byte[2] as a bool
(`true`/`false`), but the probe's PRETTY renderer prints the list as
hex bytes and shows `0x00`/`0x01`. Same property, same data, different
display formats — there is no "JSON vs byte" encoding split.

**No value-dedup (corrected 2026-05-14)**: every Save-button press in
the Mowing Settings screen emits an s6.2 `properties_changed`, even
when no field value actually changed. Verified by 3 deliberate noop
saves at 21:07:47, 21:08:38, 21:08:46 — all three pushed
`[60, 0, True, 2]` unchanged from the previous push. (An earlier test
~20:42 that produced **no** MQTT turned out to be a different flow —
the user entered the screen, modified a value, reverted, and exited
**without saving** by dismissing the unsaved-changes warning. That
path never reaches the device's save handler, so it's silent for a
different reason.)

Integration implication: don't infer "write succeeded" from "we saw
the echo" — the cardinality is 1 save-press → 1 s6.2 push, regardless
of whether the value changed. Conversely, silence on s6.2 means
"no save happened" (user dismissed without saving, or a write surface
that doesn't reach the device-side save handler).

**Open**: whether s6.2 is also written by anything other than the
Mowing Settings page save (e.g., automation, schedule, voice control,
mid-mow change). The one historical `byte[3]=198` outlier
(2026-05-10 17:04:16) happened during a mid-mow efficiency change,
which is suggestive but not conclusive — needs more samples.

## 7. See also

- `docs/research/inventory/README.md`
- `docs/research/inventory/generated/g2408-canonical.md`
- `docs/research/g2408-research-journal.md`
- `docs/research/cloud-map-geometry.md` — coordinate-frame math, renderer-side
- `docs/TODO.md` — open work list
