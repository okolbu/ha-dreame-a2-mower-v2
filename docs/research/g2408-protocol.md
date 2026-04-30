# Dreame A2 (`g2408`) Protocol Reference

Consolidated findings from MQTT + Dreame cloud probing of a live A2 mower. Complements
[`2026-04-17-g2408-property-divergences.md`](./2026-04-17-g2408-property-divergences.md)
(property-mapping divergence catalog) with wire-level detail for each property and a
map-fetch flow model.

Primary probe tool: `probe_a2_mqtt.py` (top-level in repo — authenticates as the Dreame
app, subscribes to `/status/<did>/...` and passes raw payloads through a pretty-printer).
Findings cover model `dreame.mower.g2408`, region `eu`, firmware as shipped 2026-04 on
the user's device.

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
- ❌ `lawn_mower.start` / `.pause` / `.dock` service calls route via `action()`
  → hit 80001, silent no-op from the user's perspective.
- ❌ `set_property` writes (config changes) route the same way.
- ❌ `get_properties(...)` one-shot pulls.

**Scope of what still works** (different cloud endpoint, different auth path):
- ✅ MQTT property push from the mower → HA coordinator (the whole read pipeline).
- ✅ Session-summary JSON fetch via `get_interim_file_url` + OSS signed URL.
- ✅ LiDAR PCD fetch via the same getDownloadUrl / OSS path.
- ✅ Login / device discovery / getDevices.

So historically we've pulled session-summary JSONs and LiDAR point clouds
successfully even while the command path was returning 80001 the entire
session. The two paths share the account session cookie but hit different
endpoints on the Dreame cloud; the write path needs the mower's RPC tunnel
to be open, the fetch path does not.

**Working hypothesis** (unchanged): the g2408's cloud-RPC tunnel opens only
during a narrow post-handshake window; our fork has never hit one in
practice. The 2026-04-17 probe captured 5 `s6p1: 200 ↔ 300` cycles over
12 hours that DID trigger successful map fetches — but those were using
the getDownloadUrl / OSS path, not the RPC tunnel.

**Future work:** an MQTT-publish write path on the `/request/` or `/command/`
topic would bypass 80001 entirely. See open item 0 in the
`project_g2408_reverse_eng.md` memory.

---

## 2. MQTT property catalog

Siid/piid combinations observed on g2408. All properties arrive as JSON-encoded
`properties_changed` or `event_occured` messages on the `/status/.../eu/` topic.

### 2.1 Summary table

| siid.piid | Name | Shape | Meaning |
|---|---|---|---|
| 1.1 | `HEARTBEAT` | 20-byte blob | Mower-alive ping; state machine hints; see §3.2 |
| 1.4 | `MOWING_TELEMETRY` | 33/10/8-byte blob | Position, phase, area, distance; see §3.1 |
| 1.5 | **`HW_SERIAL`** | string | Hardware serial as printed on the device, e.g. `G2408053AEE000nnnn`. Confirmed 2026-04-30 via api_probe — value never changes, never pushed via `properties_changed`. Fetch on demand via cloud `get_properties` with siid=1, piid=5. Cloud RPC is unreliable on g2408 (mostly 80001) so the fetch may need to retry; once obtained, cache it. Surfaced in HA as `sensor.hardware_serial` and as the device-info "Serial Number" field. Distinct from three other identifiers the integration also exposes for clarity: the cloud `did` (Dreame internal device record ID, signed int32, e.g. `-11229nnnn` — used by the cloud API; surfaced as `sensor.cloud_device_id`), and the WiFi MAC (e.g. `10:06:48:xx:xx:xx` — pulled from the cloud device record's `mac` field in `get_devices()` / `select_first_g2408()`; surfaced as `sensor.mac_address` and wired into HA's device-card via `DeviceInfo.connections={(CONNECTION_NETWORK_MAC, mac)}`). |
| 1.50 | — | `{}` | Empty dict at session boundaries |
| 1.51 | — | `{}` | Empty dict at session boundaries |
| 1.52 | — | `{}` | Empty dict at session boundaries |
| 1.53 | `OBSTACLE_FLAG` | bool | Obstacle / person detected near mower (§5) |
| 2.1 | **Status enum** (g2408) — `1=Working/Mowing, 2=Standby, 3=Paused, 5=Returning, 6=Charging, 11=Mapping, 13=Charged, 14=Updating` per apk decompilation. **Correction:** previously hypothesized as `{1, 2, 5}` mystery enum; apk reveals the full mapping. | small enum mapping |
| 2.2 | **Error code** per apk decompilation (NOT a state machine — the previous "STATE values {27, 43, 48, ...}" reading was wrong). Values map to fault indices catalogued in apk §FaultIndex (e.g. 0=HANGING, 24=BATTERY_LOW, 27=HUMAN_DETECTED, 56=BAD_WEATHER, 73=TOP_COVER_OPEN). | error code |
| 2.50 | TASK envelope — multiple operation classes | shape varies by `d.o` | Session start (mowing): flat fields `{area_id, exe, o:100, region_id:[1], time, t:'TASK'}`. **Map-edit** (zone / exclusion-zone add/edit/delete): wrapped `{d:{exe, o, status, ...}, t:'TASK'}`. Confirmed opcode catalog (2026-04-26 from Designated Ignore Obstacle Zone create / resize / delete tests): `204` = request initiated (always first); `234` = **save zone geometry** (CONFIRMED — fires for both *create new* and *resize existing*; same opcode, new `id` on create, existing `id` on resize; `ids:[]` in both cases); `215` = legacy edit-confirm (older capture, same general role as 234); `218` = **delete** (CONFIRMED via multiple captures matching user delete narrative; carries the deleted entity's `id`; one outlier capture from a UI flow we didn't trace — likely an edit-cancel processed as delete-and-recreate). `201` = operation completed successfully (`status:true`, `error:0`); `-1` = teardown/cleanup. **Move/drag** uses a different (still-uncatalogued) opcode pattern — pending capture. The integration triggers a MAP rebuild on `o:215` *or* `o:201` with `status:true && error:0` — covers create / resize / delete uniformly via the always-trailing 201. Note: the cloud occasionally drops s2p50 deliveries when the backend is under load; the user observed one delete that fired no MQTT at all but a retry seconds later did. |
| 2.51 | `MULTIPLEXED_CONFIG` | shape varies | App "More Settings" writes (§6) |
| 2.56 | Cloud status push | `{status}` | Internal ack |
| 2.65 | **SLAM task-type string** | string | First string-valued property observed on this mower. Carries a task-type label like `'TASK_SLAM_RELOCATE'`. Fires 3× in 1 second at the moment the mower kicks off a LiDAR relocalization (re-anchor to the saved map). Other label values likely exist for other SLAM modes — catalogue as seen. See §4.8. |
| 2.66 | Lawn-size snapshot | `[area_m2, ???]` | **First element = total mowable lawn area in m²** (matches `event_occured` piid 14 from the session-summary exactly). Observed `[379, 1394]` 2026-04-17, `[384, 1386]` 2026-04-20 after a manual "Expand Lawn". Second element unknown — decreased by 8 when area grew by 5 m², so not perimeter-proportional; candidates: blade-hours ×10, unique path segments, or a total-distance-mown counter. Fires at the end of a BUILDING session (§4.3) and probably periodically during mowing. |
| 3.1 | `BATTERY_LEVEL` | int `0..100` | % battery |
| 3.2 | `CHARGING_STATUS` | int `{0, 1, 2}` | `0`=not charging on g2408 (enum offset vs upstream) |
| 5.104 | **SLAM relocate counter** | `7` | Fires exclusively alongside `s2p65 = 'TASK_SLAM_RELOCATE'` bursts — three pushes in ~1 s at relocalization start. Value has been `7` in every capture; role unclear (retry count? relocate mode enum?). Quiet-listed so it doesn't re-fire `[PROTOCOL_NOVEL]` on every relocate. |
| 5.105 | — | `1` | Mid-session appearance, unknown |
| 5.106 | — | `1..9, 11` (no 10) | **Purpose unknown.** Originally hypothesised as a 1→7 rolling counter but longer captures invalidate that: 157 observations across 5 days show values dominated by 1-8 with rare 9 (1×) and 11 (1×, 2026-04-24 14:43). Not a clean decimal nor hex counter (value 10 / 0xA never observed), and not a clean bitfield (10/12-15 also missing). Cadence is usually ~30 min between pushes but occasionally a multi-hour gap, after which the jump is not monotonic (e.g. `1` at 11:12 → `11` at 14:43 → `4` at 15:13). No clear correlation with mowing state or battery; periodic pushes fire while the mower is docked. |
| 5.107 | — | `{14, 15, 43, 56, 133, 158, 165, 176, 190, 196, 240, 250}` | Dynamic, changes at session boundaries and mid-mow. Unknown. Live 2026-04-24 mowing run added `240`; `56` is observed at session teardown (see §4.9 example). |
| 6.1 | `MAP_DATA` | `{200, 300}` | Map-readiness signal; `300` at auto-recharge-leg-start (§7.1). |
| 6.2 | `FRAME_INFO` / **settings-saved tripwire + general-mode carrier** | list len 4 `[mowing_height_mm, mow_mode, edgemaster, ?]` | **Three of four elements decoded 2026-04-26** via live toggles. **[0] = Mowing Height in millimetres** — observed `70 → 60 → 50` while user stepped the app slider `7.0cm → 6.0cm → 5.0cm`. Range 30-70mm in 5mm steps (matches app's 3-7cm in 0.5cm increments). **[1] = Mowing Efficiency** — `0=Standard`, `1=Efficient`. **[2] = EdgeMaster** — bool. The earlier "constant True" reading was wrong; all prior captures just happened to have EdgeMaster ON. Toggle test 20:31:14-:33 flipped it cleanly. **[3] = ? still unknown** — observed `2` in 25/25 captures across 8 days, settings changes, mowing/docked/BUILDING sessions. Confirmed NOT to be Safe Edge Mowing, Automatic Edge Mowing, Mowing Direction, Obstacle Avoidance on Edges, LiDAR Obstacle Recognition, or its Obstacle Avoidance Height sub-setting (none of those flip any frame element, including [3], when toggled — even when stepping through multiple bands). Most plausible remaining hypotheses: protocol/schema version or frame-type ID. The "int-encoded multi-state app setting" hypothesis is now disfavoured since we've stepped multiple-value settings without seeing it move. All three identified Mowing Height, Efficiency, and EdgeMaster are **NOT in CFG**: `CFG.VER` does not increment when toggled. **Also functions as the "settings-saved tripwire"**: every BT-only settings change kicks the device into re-publishing `s6p2` even when no element changes — gives the integration an "user changed something" signal even when the change itself is invisible. Surfaced as `sensor.mowing_height` (cm), `sensor.mow_mode`, `sensor.edgemaster`. |
| 6.3 | **WiFi signal push** (g2408) / `OBJECT_NAME` (upstream) | list `[bool, int]` on g2408 | `[cloud_connected, rssi_dbm]`. NOT the OSS object key — upstream's `OBJECT_NAME` slot is unused on g2408 (session-summary key arrives via `event_occured` instead, see §7.4). Our overlay remaps `OBJECT_NAME` to `999/998` so the map handler does not misinterpret s6p3 pushes. |
| 6.117 | **(single-observation, unclassified)** | `int` (observed: `1`) | One observation: 2026-04-24 13:30:14. Context was compound and can't be disambiguated from one sample: (a) post `mowing_complete` transition, (b) mower physically stuck in a garden hose (user-reported "Failed to return to station" app notification), (c) `s2p65 = 'TASK_NAV_DOCK'` announced 1 s later. The firing could be associated with any or all of: end-of-mow signalling, stuck-detection, dock-nav start/retry. Without a second capture under cleaner conditions (a successful mow that parks normally, OR a stuck event mid-mow), we can't pick the semantic. Kept listed here so the watchdog doesn't re-NOVEL on every restart; label intentionally neutral. Not consumed. |

### 2.2 Upstream-divergence cheat-sheet

The upstream `dreame-mova-mower` mapping is built for other Dreame mowers and swaps
two critical properties at siid=2:

| | upstream | g2408 actual |
|---|---|---|
| `(2, 1)` | `STATE` | misc mode (1/2/5) |
| `(2, 2)` | `ERROR` | `STATE` codes (48, 54, 70, 50, 27, …) |

The g2408 overlay (`_G2408_OVERLAY` in `types.py`) swaps these back. See
`2026-04-17-g2408-property-divergences.md` for the full divergence catalog.

---

## 3. Blob decoders

### 3.1 `s1p4` — MOWING_TELEMETRY (33-byte frame)

Full frame, used throughout an active mowing task:

```
offset  type         field
[0]     uint8        0xCE          frame delimiter
[1-2]   int16_le     x_cm          X position in centimetres (charger-relative)
[3-4]   int16_le     y_mm          Y position in millimetres (charger-relative)
[5]     uint8        0x00          static
[6-7]   uint16_le    sequence
[8]     uint8        phase         0=MOWING, 1=TRANSIT, 2=PHASE_2, 3=RETURNING
[9]     uint8        0x00          static
[10-17] 4× int16_le  motion vectors; mv1 ≈ X velocity (mm/s);
                     mv2 ≈ Y velocity; others likely heading / angular rate
[18-21] 2× int16_le  paired sentinel/active pattern, unknown quantity
[22-23] flags        [22] 0→1 after init; [23]=2
[24-25] uint16_le    distance_deci      decimetres (raw ÷ 10 → m). Not a %.
[26-27] uint16_le    total_area_cent    centi-m² (raw ÷ 100 → m²). Not a %.
                                        NOTE: counts the lawn outline
                                        INCLUDING area under exclusion
                                        zones; area_mowed plateaus at
                                        (total - excluded), not at total.
                                        User-confirmed 2026-04-25.
[28]    uint8        0x00          static
[29-30] uint16_le    area_mowed_cent    centi-m² (raw ÷ 100 → m²). Not a %.
[31]    uint8        0x00          static
[32]    uint8        0xCE          frame delimiter
```

#### Detecting blades-down (cutting) vs blades-up (transit)

The s1p4 frame doesn't carry an explicit blades-state bit. Two
candidate signals were investigated:

1. **`phase` (byte[8])** — DOES NOT WORK on this firmware.
   Field-captured 2026-04-22: an obvious blades-up dock-to-mowing-
   resume drive (~50 m straight line) and the subsequent mowing
   pattern BOTH had `phase = 2` throughout. Across 4 probe logs
   the byte ranges 0..16+ with no clean cutting-vs-transit
   correlation. See TODO `s1p4 phase byte semantics` for the
   per-log distribution.

2. **`area_mowed_cent` (byte[29-30])** — WORKS PERFECTLY. The
   firmware's own area counter only ticks forward when blades
   are physically cutting. Confirmed 2026-04-22 20:47-20:50:
   ```
   20:47:44  pos=( +0.00, -0.10)  area=164.31m²       ← at dock
   20:47:49  pos=( -2.03, -0.08)  area=164.31m² (Δ=0) ← driving out
   20:47:54  pos=( -4.09, -0.07)  area=164.31m² (Δ=0)  blades up
   20:47:59  pos=( -6.14, -0.08)  area=164.31m² (Δ=0)
   20:48:04  pos=( -8.17, -0.13)  area=164.31m² (Δ=0)
   20:48:09  pos=( -9.76, -1.04)  area=164.31m² (Δ=0)
   20:48:14  pos=(-10.53, -1.70)  area=164.38m² Δ=+0.07 ← cutting starts
   20:48:49  pos=( -3.14,+10.73)  area=164.44m² Δ=+0.06
   20:48:54  pos=( -1.77,+12.91)  area=164.55m² Δ=+0.11
   20:48:59  pos=( -0.43,+15.09)  area=164.61m² Δ=+0.06
   ```
   Same pattern with `distance_deci` (byte[24-25]). Either
   counter's frame-to-frame delta is a one-bit blades-on/off
   signal. The integration uses this in
   `live_map.DreameA2LiveMap._handle_coordinator_update` to
   tag each captured path point with a `cutting` flag (1 = area
   counter ticked forward in the segment leading TO this point;
   0 = stayed constant).

#### Naming convention

The `_deci` / `_cent` suffixes refer to scale factors (SI
prefixes), NOT percentages:
- `_deci` = deci- = raw value × 0.1 → the decoded value is in tenths
  of the base unit. For `distance_deci`, base unit is metres, so
  raw 1664 means 166.4 m.
- `_cent` = centi- = raw value × 0.01 → the decoded value is in
  hundredths of the base unit. For `*_area_cent`, base unit is
  m², so raw 16430 means 164.30 m². The encoding is just the
  firmware's way of keeping two decimals of precision in a
  uint16_le without using floats — the field's actual semantic is
  plain m² (or plain metres for distance).

Neither field is in the range 0-100; both routinely exceed those
bounds (a 300 m² lawn stores `total_area_cent = 30000`).

Distance / area counters reset at the start of each mowing session.

#### Coordinate frame (charger-relative)

- **Origin (0, 0) = charging station.** Verified by convergence on return-to-dock.
- **+X axis points toward the house** (the nose direction when the mower is docked).
  -X points away from the house into the lawn.
- **±Y is perpendicular**, left/right when facing the house.
- The lawn polygon sits at whatever angle fences happen to take relative to this
  mower frame — there is no rotation applied per session.
- X is in **cm** at bytes [1-2]. Y is in **mm** at bytes [3-4]. The axes use
  different scales on the wire.

#### Y-axis calibration

The Y wheel's encoder reports ~1.6× the true distance. Multiply raw `y_mm` by **0.625**
(configurable per-install) to land in real metres. X needs no calibration.

Origin of the 0.625 factor is tape-measure-verified across two sessions:

| Mower position | Laser-measured | Decoder Y (mm) | Factor (actual / decoder) |
|---|---|---|---|
| Paused on Y-aligned straight-line at dock | 10.3 m | 16624 | 0.620 |
| Peak session Y during mow | ~10.0 m (est) | 15855 | 0.631 |

Cross-tested 2026-04-17 under both X-axis and Y-axis mowing patterns: the 0.625
constant applies to Y regardless of which axis is sweeping, so it's firmware /
encoder — not turn-drift accumulation.

#### Phase byte semantics — **byte [8] is a task-phase index**

Byte `[8]` drives the `Phase` enum. Current labels (`MOWING / TRANSIT / PHASE_2 /
RETURNING`) reflect an **earlier, incorrect interpretation** — they should be
considered placeholders. The real semantic, confirmed 2026-04-18 via live
trajectory observation across a 3-hour session:

**`phase_raw` is the index into the mower firmware's pre-planned job sequence.**
The firmware decomposes each mowing task into an ordered list of sub-tasks
(area-fill of each zone, edge passes, …), and the byte reports which sub-task
the mower is currently on. Phase advances monotonically through the plan; once
a value is done the mower never returns to it in the same session.

Session 2 observations by phase:

| phase_raw | Samples | X range | Y range (cal) | Likely role |
|---|---|---|---|---|
| 1 | 33 | -10.3..-9.0 m | -5.7..6.8 m | Dock transit corridor |
| 2 | 329 | -10.4..2.9 m | -9.8..15.0 m | Zone area-fill (west) |
| 3 | 293 | 0.2..14.4 m | -9.8..4.5 m | Zone area-fill (middle strip) |
| 4 | 234+ | 12.1..20.5 m | -1.5..6.7 m | Zone area-fill (east / the user's newly-added-and-merged zone) |
| 5 | 22+ | 7.3..20.7 m | -5.1..1.5 m | **Edge mow** — narrow Y spread, spans multiple zones in X |
| 6 | 29+ | -6.6..8.6 m | -14.0..-6.2 m | Next edge/zone |
| 7 | 3+ | -9.6..-8.7 m | -8.4..-6.3 m | Just starting — semantic TBD |

Transitions (monotonic, non-repeating, each at a crisp coordinate):

```
19:08:01  ph 1 → 2    at x = -10.21 m   (dock exit)
19:35:56  ph 2 → 3    at x =   2.86 m   (zone boundary)
20:56:01  ph 3 → 4    at x =  14.35 m   (into user's merged zone)
21:15:41  ph 4 → 5    at x =  20.22 m   (far east — area-fill done, edge mow starts)
21:17:31  ph 5 → 6    at x =   8.18 m   (next edge/zone)
21:20:06  ph 6 → 7    at x =  -8.70 m
```

**`phase_raw = 15` during post-complete return** (new 2026-04-20): the last
23 `s1p4` frames of the full-run (12:33:11-12:33:56, *after* `s2p56=[[1,2]]`
and `s2p2=48` declared the task complete and before the mower reached the
dock) all reported `phase_raw = 15`. Counters were frozen at the session's
final values (`distance=10000` decis, `mowed=29358` centi-m²) — the mower
was no longer mowing, just driving home. Treat high phase values as
"return-home" rather than a real task index; the post-complete return
reuses the phase slot rather than emitting a separate state. Earlier phases
topped out at 7 so 8-15 are either edge-variant indices on denser lawns or
specific post-complete transport codes — more captures needed to separate.

The **first group** (low phase values) look like per-zone area-fills: each
occupies a distinct non-overlapping X region and is stable over hundreds of
samples inside it. The **later group** (higher values, starting around 5) have
different spatial shapes — narrow Y spread and crossing several zone
boundaries in X — consistent with perimeter / edge-mow passes once all the
bulk area-fill is done.

**User-visible artefact confirming the zone-indexed plan:** the user added a
new in-app zone that auto-merged with an existing one on close (area overlap
triggers auto-merge). The firmware still plans two separate area-fill phases
for the two components — mower stops and turns at the former-now-invisible
boundary at X=14.35 m, which is exactly where `phase_raw` flips 3→4. The
in-app merge collapsed the display but not the internal task plan.

**Practical implications:**
- The `Phase` enum labels `MOWING/TRANSIT/PHASE_2/RETURNING` should be retired.
  They carry meaning the byte does not have.
- Expose the raw integer as a `task_phase` or `mowing_zone` diagnostic sensor
  rather than translating through the misleading enum.
- Multiple values per session is expected — we saw 6 distinct values in one
  session here. Decoder should accept any small positive int.
- Different mowing jobs (all-zones vs single-zone vs edge-only) will likely
  expose different subsets of phase values.
- No single value is "edge mode" or "transit" universally — the meaning of a
  phase value is bound to the current task plan, which is itself determined by
  the zone layout. Cross-user portability of exact values is unlikely.

### 3.2 `s1p4` — 8-byte beacon variant

Emitted in **three** distinct situations, same layout:

1. **Idle / docked / remote control** — mower parked, sending position-only heartbeats.
2. **Start-of-leg preamble** — fired exactly once ~37-45 s after each `s2p1 → 1` transition (session start, and each resume after an auto-recharge interrupt). Three consecutive 8-byte frames observed during the 2026-04-20 full-run (07:58:40, 10:03:55, 12:07:50) before the 33-byte telemetry stream resumed for that leg.
3. **Throughout a BUILDING session** — during `s2p1 = 11` (manual map-learn / "Expand Lawn") the mower does **not** emit the 33-byte telemetry frame at all; every s1p4 push is an 8-byte frame carrying live position as the mower traces the new boundary. Confirmed 2026-04-20 17:00:09–17:04:00: 47 consecutive 8-byte frames at ~5 s cadence (no 33-byte frame in between), plus one 10-byte frame at 17:03:41 marking the save moment.

Layout (X/Y at the same offsets as the 33-byte frame, no phase/session/area fields):

```
[0]     0xCE
[1-2]   int16_le   x_cm               (small positive during preamble)
[3-4]   int16_le   y_mm               (near-zero / negative sentinel -64..-96)
[5]     0x00
[6]     uint8      123..125           TBD — monotonic across legs (see open item)
[7]     0xCE
```

Raw samples from 2026-04-20 run (leg-start preamble shape — Y=0xFFFF sentinel):
- `07:58:40  [0xCE, 19, 0, 192, 0xFF, 0xFF, 125, 0xCE]`
- `10:03:55  [0xCE, 20, 0, 160, 0xFF, 0xFF, 125, 0xCE]`
- `12:07:50  [0xCE, 30, 0, 192, 0xFF, 0xFF, 123, 0xCE]`

BUILDING-mode samples (same 8-byte shape, real Y values, byte[6] varies widely):
- `17:01:01  [0xCE, 6, 0, 192, 0xFF, 0xFF, 250, 0xCE]`  (at dock, sentinel Y)
- `17:01:11  [0xCE, 235, 255, 47, 3, 0, 69, 0xCE]`      (X=-21 cm, Y=815 mm)
- `17:02:16  [0xCE, 72, 1, 144, 73, 0, 4, 0xCE]`        (X=328 cm, Y=18.83 m)
- `17:03:11  [0xCE, 9, 2, 80, 110, 0, 126, 0xCE]`       (X=521 cm, Y=28.24 m)

byte[6] is the **mower heading** (confirmed 2026-04-24). Scale `byte / 255 *
360` gives the angle in degrees in the dock-relative frame (0° = dock's
+X axis, 90° = +Y). Validation: ran `heading_correlate.py` across 5586
consecutive-pair samples from `probe_log_20260419_130434.jsonl`, computing
the motion direction `atan2(dy, dx)` and comparing to the byte[6] decode
— **median angular error 13°**, 54% of samples under 15°, 67% under 30°.
Clear central peak at 0-14° in the error histogram, with a diffuse tail
corresponding to pivot turns where position barely moves between frames
and `atan2` is ill-conditioned. The earlier hypothesis about preamble
values (123..125) is consistent with "dock-relative heading ~180° =
mower facing away from the dock entry while leaving", not a special
preamble role. Surfaced as `sensor.heading_deg`.

**Bytes [7-21] — trace data on g2408 (2026-04-24, partially validated
against the probe-log corpus).** Derived from the ioBroker.dreame
`apk.md` reference at `/data/claude/homeassistant/ioBroker.dreame/apk.md`
§"parseRobotTrace". ioBroker.dreame is not g2408-specific (it targets
the whole Dreame/Mova line), so the layout was validated against our
14.6k-frame probe-log corpus before being adopted. Validation results
are recorded inline below.

**Byte [7-9] start_index — CONFIRMED on g2408**. One-off script ran
over all 14,684 consecutive-frame transitions and found 5,796
increments vs only 10 decrements, zero large jumps, zero INT24-MAX
saturation, distribution concentrated in 0..10k (never reaching 10k+
over a full session). The 10 decrements all look like new-session
resets. Matches "uint24 LE path-point sequence counter" perfectly.

```
Bytes 7-9:   start_index   uint24 LE  — path-point sequence id
Bytes 10-13: Δ1 = (dx1, dy1)          — 2 × int16 LE
Bytes 14-17: Δ2 = (dx2, dy2)          — 2 × int16 LE
Bytes 18-21: Δ3 = (dx3, dy3)          — 2 × int16 LE

  if |dx_i| > 32766 AND |dy_i| > 32766 → that Δ_i is ABSOLUTE, not relative.
```

So each s1p4 frame carries the current pose PLUS the last 3 path-point
offsets, which is why the motion-vector correlator couldn't fit a simple
velocity model: the fields aren't motion vectors at all, they're **four
points of recent path history per frame**. The ±INT16 saturation pattern
we observed across ~14.6k frames (`motion_vectors_correlate.py` run)
matches the documented absolute-vs-relative sentinel exactly — when the
mower jumps (relocalisation, start-of-run), the firmware sets all four
bytes to ±0xFFFF/0x8000 and stores the absolute coordinate in the next
frame's pose.

**Caveats that fall out of the raw-value dump** (see
`motion_vectors_correlate.py`):
- Δ2 at bytes [14-17] is often `(+INT16_MAX, -INT16_MIN)` during steady
  motion — the apk describes this as "absolute" sentinel but Δ2 appears
  to saturate more regularly than Δ1/Δ3, which is suspicious. Could be
  a reserved slot on g2408 (only Δ1 + Δ3 carry data), or a different
  sentinel semantic than the apk describes.
- In row 2 of the sample (vx=+378 mm/s steady), Δ1.dx=-267 and
  Δ3.dx=-262 — almost the same magnitude, not monotonically decreasing
  as "oldest → newest" would predict. That could mean Δ1/Δ3 point to
  the SAME prior point under different references, or the layout is
  genuinely different on g2408.

**Validation steps before shipping a decoder change**:
1. Pick a mid-session frame from `probe_log_20260419_130434.jsonl` with
   known pose `(x, y)`. Apply the apk decode to bytes [7-21]. Plot
   `(pose + Δ1, pose + Δ2, pose + Δ3)` against the session's rendered
   path. If the points land on recent path segments, decoder is valid.
2. Correlate the uint24 start_index at bytes [7-9] across consecutive
   frames — should increment monotonically if it's a path-point sequence
   counter. If it jitters or wraps, the layout is different.
3. Only then modify `protocol/telemetry.py` and consider enriching
   live_map path accumulation.

**Bytes [1-6] — position decode CONFIRMED on g2408 (2026-04-24, alpha.98)**:
`telemetry.py` now uses the apk's 20-bit signed packed decode for
bytes [1-5], with X using bytes `[1,2,3_low_nibble]` and Y using bytes
`[3_high_nibble,4,5]`. Results are scaled ×10 per the apk's "map
coordinates" rule so both `x_mm` and `y_mm` are in map-scale
millimetres (= same frame as MAP/cleanPoints/dock positions). Earlier
versions used a broken int16 LE at [1-2]/[3-4] with a 16× Y overshoot
compensated by scattered `0.625` / `0.000625` factors downstream; all
of those are removed in alpha.98. Reference formulae:

```javascript
x = (payload[2] << 28 | payload[1] << 20 | payload[0] << 12) >> 12
y = (payload[4] << 24 | payload[3] << 16 | payload[2] << 8) >> 12
```

**Validation** (alpha.98 pre-landing):
- **Fixture `captured_s1p4_frames.json`**: 5 dock-departure frames with
  a documented ground-truth westward path. 20-bit decode reproduces
  X: 0 → -203 → -409 → -614 → -817 cm (× 10 = mm) exactly matching
  the old int16 decode (which works because for small coords bytes[3]'s
  low nibble is 0 or 0xF = sign extension). Y small (-6 cm to -9 cm),
  consistent with the mower hugging Y=0 during straight-line dock exit.
- **Full probe corpus (14.7k frames)**: X always matches the old int16
  × 10; Y is 1/16× the old int16 value (the old decoder was reading the
  wrong bits of b[3]). Downstream `* 0.625` compensation is gone.

**Historical note for readers of older commits**: pre-alpha.98 code
named the fields `x_cm` and `y_mm`; the X name was roughly honest
(raw cm × 10 = mm), but the Y name lied — it was actually
"(20-bit-Y-in-cm) × 16", and scattered magic factors (`* 0.000625`,
`* 0.625`, `y_factor=0.625`) compensated for the decoder bug. All
renamed to `x_mm` / `y_mm` (both in map-scale mm) + compensations
removed in alpha.98.

The integration decodes the position correctly via `decode_s1p4_position`. As of
v2.0.0-alpha.7 each novel short-frame length also logs the raw bytes once at
WARNING (`[PROTOCOL_NOVEL] s1p4 short frame len=…`) so contributors capturing
future variants can see the undecoded bytes without running a separate probe
script.

**Other variants observed by apk decompilation (g2568a)**: 7, 13,
22, 44 byte lengths exist on other mower models. We've only
observed 8 / 10 / 33 on g2408. If a future capture surfaces a
new length, the integration emits a one-shot `[PROTOCOL_NOVEL]
s1p4 short frame len=N` warning with the raw bytes — see
§7 PROTOCOL_NOVEL catalog.

### 3.3 `s1p4` — 10-byte BUILDING variant

Emitted **exactly once per BUILDING session**, at the moment the new zone is
saved — i.e. as the mower finishes the perimeter trace and the firmware
commits the map delta. Confirmed 2026-04-20 17:03:41 at the same second
`s1p50 = {}` fired (first of three in that second). The other 47 frames of
the BUILDING session were all the 8-byte variant (§3.2).

```
[0]     0xCE
[1-2]   int16_le   x_cm
[3-4]   int16_le   y_mm
[5]     0x00
[6-7]   uint16_le  ??  (observed 0x15C2 = 5570 on 2026-04-20; probably a
                       sequence counter, zone-id, or point count for the
                       new polygon — needs more captures to disambiguate)
[8]     0x00
[9]     0xCE
```

Sample: `[0xCE, 139, 0, 240, 77, 0, 194, 21, 0, 0xCE]` → X=139 cm, Y=19952 mm,
bytes[6-7] uint16_le = 5570.

### 3.4 `s1p1` — HEARTBEAT (20-byte blob)

Sent every ~45 seconds regardless of state, plus extra emissions during state transitions. `0xCE` delimiters at the ends.

| bytes | meaning |
|---|---|
| [1] `& 0x02` | **Drop / Robot tilted** — set while the mower is held off-level. Confirmed 2026-04-30 19:37:05 against the app's "Robot tilted" notification; cleared at 19:37:13 when the mower was set back down. |
| [1] `& 0x01` | **Bumper hit** — confirmed 2026-04-30 19:37:13 against the app's "Bumper error" notification. **Important:** this event has *no* corresponding `s2p2` transition — it surfaces only via this bit. |
| [2] `& 0x02` | **Lift / Robot lifted** — confirmed 2026-04-30 19:37:57 against the app's "Robot lifted" notification. |
| [3] `& 0x80` | **Emergency stop activated** — confirmed 2026-04-30 19:39:35 against the app's "Emergency stop is activated" notification; cleared 10 s later at 19:39:45. |
| [4] | pulse `0x00 → 0x08 → 0x00` lasting ~0.8 s during a **human-presence-detection event**. Evidence: session 2 (2026-04-18) showed byte[4]=0x08 exactly twice at 21:04:39.580 and 21:04:40.210; the user confirmed the Dreame app raised a human-in-mapped-area alert at that same moment. Byte is `0x00` at all other times across the whole session. Single-event datapoint — reproduce before relying on it. |
| [6] `& 0x08` | **Charging paused — battery temperature too low.** Asserted while the mower is docked but refusing to charge because the battery is below its safe-charge threshold; clears when the cell warms up (or momentarily, while the charger retries). Evidence: 2026-04-20 the Dreame app raised *"Battery temperature is low. Charging stopped."* at 06:25 and 07:54; at 06:25:42 byte[6] went `0x00 → 0x08` coincident with `s2p2` dropping from 48 (MOWING_COMPLETE) to 43, at 07:54:39 byte[6] flipped `0x08 → 0x00 → 0x08 → 0x00` while the mower bounced `STATION_RESET ↔ CHARGING_COMPLETED` and re-emitted `s2p2 = 43`. Cleared to 0 once charging resumed around 07:58 and stayed 0 through the following mowing session. |
| [7] | 0=idle, 1 or 4 = state transitions |
| [9] | 0/64 pulse at mow start |
| [10] `& 0x80` | **Latched** after the first low-temp charging-pause event of the day — observed to set at 06:25:42 together with byte[6]`=0x08` and remain `0x80` through the 07:54 re-trigger, the 07:58 mowing start, and every subsequent heartbeat in the session. Normal value at a cold-boot/idle charge is `0x00` (confirmed: 2026-04-19 13:04–14:29 all show byte[10]=0). Best guess: "battery-temp-low event has occurred since last power-cycle" maintenance flag. Cleared state unconfirmed (reproduce with a fresh boot after a warm day). |
| [10] `& 0x02` | **Water on lidar / rain protection** — set when the lidar dome detects moisture; the mower auto-returns within ~50 s. Confirmed 2026-04-30 19:39:35 against the app's "Water is detected on the Lidar. Rain protection is activated. Returning to the station." notification. The base `0x80` bit (from the latched low-temp flag, see above) stays asserted; only bit 1 toggles for water. |
| [11-12] | monotonic counter (little-endian u16) |
| [14] | state machine during startup: 0 → 64 → 68 → 4 → 5 → 7 → 135 |
| [17] | **WiFi RSSI in dBm** as a signed byte (`b if b<128 else b−256`). Tracks the live signal to the currently associated AP. Confirmed 2026-04-30 20:09–20:16 by toggling APs and watching the app's 5-stage signal line move in lockstep: 0xBD = −67 dBm ("Strong"), 0xA8 = −88 dBm ("Weak" after killing closest AP and the mower fell back to a more distant one), 0xC0 = −64 dBm (snapped onto closer AP after restoration), 0x9F = −97 dBm (briefly during dropout). No special "disconnected" sentinel observed — value just keeps tracking whatever radio detects. |

See §4.4 for the companion `s2p2 = 43` signal and the app-notification semantics.

Related coincident MQTT events at the same human-presence moment (21:04:39):
- `s2p2 = 27` (IDLE) emitted **twice** in a single second while the mower was
  demonstrably still moving (MOWING_TELEMETRY position continued changing through
  the window). So `s2p2 = 27` at runtime is not literal "idle" — it may be a
  query-response or alert-acknowledgement token.
- `s1p53` (OBSTACLE_FLAG) went `True → False` 7 s later at 21:04:46 — but it had
  been latched True since 20:43:16 (an earlier obstacle, ~21 min prior), so the
  clear is not directly tied to the human event; more likely a side-effect of
  whatever state transition happened.

### 3.5 `s1p53` — OBSTACLE_FLAG

Boolean. Set `True` when the mower detects an obstacle/person/animal during mowing.
**Never sent `False` automatically** — HA entity must auto-clear after ~30 s of no
refresh, otherwise it latches indefinitely. See Open Item 0e in
`project_g2408_reverse_eng` memory.

---

## 4. State machine

### 4.1 `s2p2` state codes

| Value | Meaning |
|---|---|
| 27 | idle |
| 31 | **Idle-after-error** — follows `s2p1 = 2 (IDLE)` after a failed task. Observed three times 2026-04-20 19:29-19:35 each time a *Positioning Failed* / *Failed to return* sequence ended. Paired with `s2p2 = 33` immediately preceding. |
| 33 | **Failure transition** — fires at the moment a task fails (positioning, task-start, return). Precedes `s2p1 → 2 (IDLE)` + `s2p2 = 31` by ~1 s. Combined 33→31 pair is the g2408's "task errored out, now idle" pattern. |
| 43 | **Battery temperature is low; charging stopped.** Drives the Dreame app notification of the same name. Observed to be republished on every (re-)entry into the condition — i.e. each re-emission causes a fresh app notification, not just the first one. See §4.4. |
| 48 | mowing complete |
| 50 | session started (manual start from the app) |
| 53 | **Scheduled-session start** — confirmed by two identical captures on 2026-04-20: morning run at 07:58:02 and afternoon run at 17:30:02. Both fired the exact same second-level sequence: `s2p56 → {'status':[]}` and `s2p2 → 53` in the same second, then `s3p2 → 0` + `s2p1 → 1 (MOWING)` one second later, then `s1p50/s1p51 → {}` and `s2p56 → [[1,0]]` ~40 s later when the mower starts emitting 33-byte telemetry. Distinct from manual starts which emit `s2p2 = 50` instead. Enum: `SESSION_STARTING_SCHEDULED`. |
| 54 | returning |
| 56 | **Rain protection activated** — water detected on the LiDAR. See §4.3 rain-pause. |
| 60 | **Frost-protection-suppressed scheduled task** — fires at the configured scheduled-start time when the firmware's ambient-temperature check refuses to launch the mow. Confirmed 2026-04-27 07:58:02 (the user's scheduled-mow trigger). Drives the Dreame app notification *"Temperature too low. Frost Protection is activated. The Scheduled task will start later."* The mower wakes briefly to evaluate the schedule, fires `s2p2 = 60`, optionally a quick `s1p53` obstacle-sensor self-test pulse, then settles back to `s2p1 = 13 (CHARGING_COMPLETED)` ~10 minutes later. Distinct from `s2p2 = 53` (scheduled-task did start) and `s2p2 = 56` (rain pause; that one fires DURING a run). Implication: **scheduled mows DO emit MQTT at the trigger time when something prevents them from running** — earlier doc claim that scheduled-mows have "no MQTT signal at all" was only true for normal-start runs. |
| 70 | mowing (edge / standard) |
| 71 | **Positioning failure or auto-recovery from idle** — observed two distinct contexts: (a) **Hard-stuck "Positioning Failed"** — mower cannot localize itself on the saved map (e.g. parked outside the known area, or LiDAR loop-closure failed). The Dreame app shows the notification *"Positioning Failed"*. Confirmed 2026-04-20 19:28:19 after the user ended a Manual session not-fully-in-the-dock; in that case any return-to-station / start-task commands failed with `s2p2 = 33 → 31` while the condition persisted, and recovery required the user to drive the mower back into a known area where a `s2p65 = 'TASK_SLAM_RELOCATE'` pass (§4.8) could re-anchor. (b) **Auto-return-from-idle** — confirmed 2026-04-27 11:52:47: after a BT-orphaned manual stop left the mower idle on the lawn for ~55 minutes, `s2p2=71` fired alongside `s2p1=5` (RETURNING) in the same second, the mower self-navigated back to the dock, and `s2p1=6` (CHARGING) followed within a minute. So `71` isn't always a hard fault; the firmware can also use it as the trigger code when re-acquiring positioning to drive home autonomously after extended idle. The two contexts are distinguished by what follows: 33→31 means stuck and waiting for user help; 5 → s1p4 telemetry → 6 means self-recovery succeeded. |
| 75 | **Arrived at Maintenance Point** — confirmed 2026-04-20 18:18:05 when mower reached a user-set maintenance point after tapping *Head to Maintenance Point*. Fires in the same second as `s2p1 → 2 (IDLE)`, followed by `s1p52 = {}`. No `event_occured` summary for Head-to-MP tasks. See §4.3 "Go to Maintenance Point". |

Anything **outside** this set arriving on `s2p2` will log exactly one WARNING
(`[PROTOCOL_NOVEL] s2p2 carried unknown value=…`) so new firmware codes surface
without flooding the log.

### 4.2 `s2p1` mode enum (separate from state)

| Value | Meaning |
|---|---|
| 1 | MOWING |
| 2 | IDLE |
| 5 | RETURNING |
| 6 | CHARGING |
| 11 | **BUILDING** — manual map-learn / zone-expand. Confirmed 2026-04-20 17:00:09 when user triggered "Expand Lawn" from the Dreame app. Mower left the dock, drove the new perimeter for ~4 min, then returned. See §4.3 "Manual lawn expansion". |
| 13 | CHARGING_COMPLETED |
| 16 | **BATT_TEMP_HOLD** — docked, refusing to charge because the battery is below its safe-charge temperature. *Misnamed `STATION_RESET` in the legacy upstream enum (still used in `lawn_mower.py` for now); the actual semantics are pause-for-cold, not station-reset.* Re-confirmed 2026-04-26: 5 occurrences between 03:45–07:00 local (cold morning hours), every entry coincident with `s1p1[6]=0x08` (the "charging paused — temp low" event flag from §5.3), every exit coincident with `s1p1[6]=0`. Brief 2 s flicker entries are common ("battery cold-check that immediately cleared"); longer 1 h holds occur when the cell needs to warm before charging can resume. Always transitions to either `6` (CHARGING — cell warm enough now, top-up starts) or `13` (CHARGING_COMPLETED — false alarm, no top-up needed). |

### 4.3 Observed session transitions

**Low-battery auto-return** (well-formed; triggers map push):
```
MOWING(1) → IDLE(2) → RETURNING(5) → CHARGING(6)
s2p2: 70 → 54
s6p1:    → 300   ← MAP_DATA ready signal
s2p56:   → [[1,4]]
s1p4 converges to (0,0)
```

**Manual "End" while docked** (no map push):
```
s2p2 → 48 (MOWING_COMPLETE)
s1p52 → {}
s2p50 → {task metadata}
no s6p1, no state transitions
```

**Manual session start** (user-initiated from the app):
```
s2p56: [[1,4]] → []
s2p2:   → 50                  ← manual-start code
CHARGING → MOWING
s2p50 gains {area_id, exe, o:100, region_id:[1], time:10510, t:'TASK'}
s5p107 changes dynamically: 176 → 250 → 133 → 158 → 240 (driver unknown;
cycling enum of ~5 known values, new values still surfacing mid-session —
see §2.1's s5p107 value-catalogue and the `[PROTOCOL_VALUE_NOVEL]` logger)
```

**Scheduled session start** (cloud fires schedule at configured time — confirmed
2026-04-20 across two independent captures, 07:58:02 and 17:30:02):
```
HH:MM:02  s2p56 = {'status': []}   (task-list cleared ready for new task)
HH:MM:02  s2p2  = 53                ← scheduled-start code (distinct from 50)
HH:MM:03  s3p2  = 0                 (stops charging)
HH:MM:03  s2p1  = 1                 (MOWING)
HH:MM:46  s1p4 (33-byte) frames begin arriving
          (one observation had an 8-byte preamble at +37 s before the 33-byte
          stream resumed; the other went straight to 33-byte at +43 s)
HH:MM:44  s1p50 = {} + s1p51 = {}   (session-boundary markers)
HH:MM:45  s2p56 = {'status': [[1,0]]} (task now running)
```
**No `s2p50` fires on scheduled starts** — the task metadata block is only
emitted on manual starts. Scheduled runs rely on the cloud to know the plan.
**No `s6p1 = 300` either** — the map-ready signal is recharge-leg-only.

**Manual lawn expansion / zone edit** (observed 2026-04-20 17:00:09–17:06:06, user tapped *"Expand Lawn"* in the Dreame app):
```
CHARGING(6) → BUILDING(11) → IDLE(2) → RETURNING(5) → CHARGING(6)
              ↑ s2p1=11 (previously unlabelled, now confirmed)

s3p2: 1 → 0 (charging stops as mower prepares to leave dock)
s1p50 = {} + s1p51 = {}  (session-boundary markers, same as mowing)
s1p4  = 8-byte frames with real X/Y telemetry during the drive
        (not the 0xFFFF sentinel — active position tracking)
s1p4  = one 10-byte frame fires at the exact moment the expand
        completes (17:03:41 — same second s1p50 fires again).
        Likely the "zone saved" marker.
s6p2  = [60, 0, True, 2] at 17:03:42 (see §2.1). Previously [35,0,T,2]
s2p66 = [384, 1386] at 17:04:02 — mowable-area snapshot after save
        (first int matches event_occured piid=14 from morning run).
s1p53 = True  (obstacle flag — mower nosing around the boundary)
```
**No `event_occured` siid=4 eiid=1**, no `s2p2` code change, no `s2p50`.
These are mowing-session artefacts; BUILDING is a distinct session class.

Under-counting of newly-added area is likely if the new zone overlaps
an existing **exclusion zone** — the exclusion polygon filters BEFORE
the mowable-area sum, so any overlap subtracts from the reported
area. If `s2p66[0]` or event_occured piid=14 doesn't budge after an
expand, check for overlapping exclusions first.

**User-cancel abort** (observed 2026-04-20 18:06:18 — user hit *Cancel* from the Dreame app mid-session):
```
s2p1 = 2   (IDLE)             — task cancelled
s2p2 = 48  (MOWING_COMPLETE)  — reused for abort (same code as natural end)
s1p52 = {}                    — session-boundary marker
s2p50 = {'d':{'exe':True, 'o':3, 'status':True}, 't':'TASK'}
                              — NEW operation code o=3 for "cancelled"
event_occured siid=4 eiid=1   — session-summary JSON uploaded (!)
```

**The mower does NOT auto-return to dock after a cancel.** `s2p1` stops at
`2 (IDLE)` with no `→ 5 (RETURNING)` transition. The robot stays where
it last was on the lawn. To bring it home, the user must explicitly hit
*Recharge* in the app (which issues a separate `s2p1 → 5` RPC). This is
firmware behaviour, not an integration choice.

**Earlier "aborted sessions skip the summary" memory note was wrong** —
the abort DID emit `event_occured` with a fresh JSON OSS key. Distinguishing
fields from natural completion:
- `piid 7` = 3 (previously only 1 observed; 3 = user-cancel)
- `piid 2` = 36 (new end-code; naturals give 31/69/128/170/195)
- `piid 60` = 101 (first non-`-1` observation; maybe "abort reason")
- `piid 3` = centiares-mowed at abort time (here 6647 → 66.47 m²)

So the session-summary-JSON pipeline covers aborts too. Integration
behaviour is correct: `_fetch_session_summary` archives it and the
session-picker select shows "66.47 m² (N min)" for the cancelled run
alongside completed runs.

**Go to Maintenance Point** (observed 2026-04-20 18:16:40–18:18:05 — user tapped *Head to Maintenance Point* from the Dreame app; MP was set earlier the same session at x≈2.6 m, y≈20.4 m charger-relative):

```
HH:MM:39  s2p56 = {'status': []}            — task list cleared
HH:MM:40  s3p2  = 0                          — stops charging
HH:MM:40  s2p1  = 1 (MOWING)                 — NOTE: same state as real mowing
          NO s2p2 emitted (vs 50 manual / 53 scheduled / 70 mid-mow)
          NO s2p50 task metadata (either shape)
          NO coordinate anywhere in MQTT — destination was pushed to the
          mower via the cloud-command path we don't see on /status/
HH:MM+41s  s1p50 + s1p51 = {}                — session-start pair
HH:MM+42s  s2p56 = {'status': [[1, 0]]}     — task running
HH:MM+42s  33-byte s1p4 frames begin at phase_raw = 0
… mower drives to the MP …
           s1p4 position at arrival = MP coord (last frame before `s2p1 → 2`)
HH:MM:arrive  s2p56 = {'status': [[1, 2]]}   — task-complete (same as mowing end)
HH:MM:arrive  s2p1  = 2 (IDLE)
HH:MM:arrive+1s  s2p2  = 75                  — **arrived at MP** (new code)
HH:MM:arrive+1s  s1p52 = {}                  — end-of-task flush
```

**Identification challenge:** during the drive, MQTT does NOT distinguish
Head-to-MP from a real mowing task. Same `s2p1 = 1`, same `phase_raw = 0`,
no `s2p2` marker. The only way to know it's a go-to is when arrival fires
`s2p2 = 75`. If an integration wants to reflect "mower is going to MP" in
real time, it has to infer from context: a transition `s2p1: 6 → 1` with
no accompanying `s2p2 = {50, 53}` (neither manual nor scheduled mow start
code) implies go-to. The mower's final pre-arrival `s1p4` position is
effectively the MP coordinate — useful for future automation.

**Maintenance points:** the app supports multiple saved maintenance points;
the user selects which one to dispatch to. The selection + coord both live
in Dreame-cloud user-prefs, not MQTT. To enumerate them from HA would
require a separate cloud endpoint call (probably a new `get_batch_device_datas`
key family). Placement of a MP emits two `s1p50 = {}` pings only (§4.6).

No `event_occured siid=4 eiid=1` fires for a Head-to-MP arrival — the
session-summary JSON pipeline is mowing-session-specific.

**Manual mode** (observed 2026-04-20 18:26:18–18:28:19 — user selected *Manual* mow mode in the Dreame app; when started, the mower auto-drives off the dock, then the user drives it via on-screen controls with a separate blade on/off toggle):

```
HH:MM:17  s3p2 = 0                   — stops charging
HH:MM:18  s2p1 = 1 (MOWING)          — Manual session started
(… N minutes of driving — /status/ topic is SILENT …)
HH:MM:19  s2p1 = 2 (IDLE)            — session ended (user drove into dock
                                        and tapped End, or tapped End on
                                        the lawn)
```

**Manual mode is BT-mediated, not MQTT-mediated.** The Dreame app's own
map screen also does **not** show the Manual path afterwards (user
confirmed 2026-04-20: "the map does not show the manual run, but it
shows the path taken to/from the maintenance point"). So this isn't
"we missed a channel" — the mower genuinely stops broadcasting position
to the cloud during Manual, and the app is rendering from whatever the
cloud has, which is nothing. During the drive the /status/ topic emits:
- `s1p4`: **zero frames.** No position telemetry reaches the cloud.
- `s1p53`: zero. Obstacle detection not exposed to the cloud during
  Manual. (The mower still avoids obstacles for safety — the app's
  remote-control dispatches over BT carry the nudges and the blade
  toggle, and the mower's local LiDAR does its own thing.)
- `s2p2`: no code. No task-type marker.
- `s2p50`: no task metadata.
- blade on/off: invisible to MQTT. The *Mow* toggle is a BT command
  to the mower's motor controller.
- BT dropout → blade auto-stops for safety (per user 2026-04-20) —
  this too is invisible on /status/; the cloud never knows.
- `event_occured` siid=4 eiid=1: does **not** fire. No session-summary
  JSON is uploaded for Manual sessions.

**Integration implication:** HA cannot meaningfully render a Manual
mow on the live-map camera (no positions), cannot track blade-on time
for Manual, and the session-picker select will not include Manual
sessions (no archive entry). A user-facing note in the README under
"Modes" should say "Manual mode is invisible to HA beyond the
start/end state transitions — use the app directly, don't rely on
the HA camera during Manual driving".

After ending Manual with the mower parked in-dock-ish but not fully
aligned (user 2026-04-20: "not totally straight in the charger"),
`s3p2` stayed `0` (no charging started) and no further state
transition fired — consistent with the mower waiting for the user to
either re-dock or press Recharge.

**Mid-task recharge** (observed 2026-04-18): the mower can pause for a mid-task
recharge and resume mowing once topped off. The task is not considered complete
during this pause; `s1p4` telemetry continues throughout the return leg. No map
push observed at the pause itself — only at true session completion.

### 4.4 Low-temp charging-pause event

Confirmed 2026-04-20 from two live notifications ("Battery temperature is low.
Charging stopped.") at 06:25 and 07:54. All three signals below fire as one
atomic MQTT burst at the moment the Dreame app issues the notification:

```
s2p1 (STATE)            → 16  (STATION_RESET)       -- was 13 (CHARGING_COMPLETED)
s2p2                    → 43  (low-temp signal)     -- was 48 (MOWING_COMPLETE)
s1p1 HEARTBEAT byte[6]  |= 0x08                     -- was 0x00
s1p1 HEARTBEAT byte[10] |= 0x80  (latches for the session, see §3.4)
```

A **re-entry** (07:54 in our capture) republishes `s2p2 = 43` and re-pulses
byte[6] — so one Dreame app notification arrives per republish, not just on
rising edge. The HA integration piggybacks on the byte[6]`&0x08` bit
(`Heartbeat.battery_temp_low_flag` from the s1p1 decoder) and raises a
persistent-notification + `dreame_a2_mower_warning` event on the rising edge;
see `coordinator._heartbeat_changed`. We don't currently attach to `s2p2 = 43`
directly because the upstream property overlay keeps ERROR (`s2p2`) disabled
on g2408 to avoid upstream's vacuum-era misinterpretation of the same slot
(§2.2).

### 4.5 `s1p4` telemetry lifecycle

Position telemetry fires throughout an active TASK, including the return-to-dock
leg of a low-battery auto-recharge. It stops only when the task itself ends
(`s2p1` transitions to `2` = complete / cancelled).

### 4.6 Map-edit transport via `s2p50`

Zone / exclusion-zone / no-go-zone adds / edits / deletes travel over MQTT as
two `s2p50` pushes, both with the shape `{d: {...}, t: 'TASK'}`:

```json
{"d": {"exe": true, "o": 204, "status": true}, "t": "TASK"}
        ^^^ request — map edit starting
{"d": {"error": 0, "exe": true, "id": 101, "ids": [1], "o": 215, "status": true}, "t": "TASK"}
        ^^^ confirm — edit applied; `ids` = affected zone id(s), `id` = tx counter
```

Captured 2026-04-20 17:15:41 → 17:17:16 when the user resized the single
exclusion zone from the Dreame app. Neither push triggers `s2p1 = 11` (BUILDING
is reserved for drive-the-boundary operations), `s6p1 = 300` (no map-ready
signal), `s2p66` (area snapshot — stale until the next BUILDING or session
start), or `event_occured`.

**Integration behaviour** (2.0.0-alpha.17): the `o=215` confirm push triggers an
immediate `_build_map_from_cloud_data()` rebuild + camera-state nudge so the
Mower dashboard's base-map image reflects the new exclusion polygon within a
few seconds of the edit. Prior to this version the camera kept drawing the
stale polygon until HA was restarted.

**Scheduled-mow add / edit / delete: no MQTT signal at all.** The Dreame cloud
stores schedules app-side; nothing appears on the mower's `/status/` topic when
the user adds or edits a schedule. The mower only learns about the schedule
when the cloud wakes it for the configured time. So there's nothing for the
integration to observe at edit time — the schedule list itself has to be pulled
from the cloud API separately (not yet wired).

**Other `s2p50` operation codes** (catalog, extend as new ones appear):

| `d.o` | Meaning | Occurs when |
|---|---|---|
| -1  | **Error abort** — fires after a failed task (status=True, no id/ids). Observed 2026-04-20 19:34:20 immediately after an `o=109` task-start failure: the mower emits `s2p50 o=109 status:False` (failure), then 0 ms later `s2p50 o=-1 status:True` (abort ack). The -1 value is firmware-idiomatic for "no specific op — this is a cleanup marker". |
| 3   | task cancelled | user hits *Cancel* / *Stop* during an active mowing session. Fires 1 s after `s2p2 = 48`. Does **not** carry `id`/`ids`. See "User-cancel abort" in §4.3. |
| 6   | explicit Recharge command | user taps the app's *Recharge* button (either to send the mower home from a user-cancelled state, or any time the mower is away from the dock). Fires at the moment charging actually begins (`s2p1 → 6`, `s3p2 → 1`). Distinct from auto-recharge mid-session which emits NO `s2p50` at all. Confirmed 2026-04-20 18:09:56 and 18:25:57. |
| 109 | **Task start failed** — `status: False` (first observed `False` in any `s2p50` op-code). Fires when a cloud-issued task command (typically *Recharge* or *Start*) cannot be honoured because the mower is in a bad state, e.g. *Positioning Failed* (§4.1 code 71). Confirmed 2026-04-20 19:34:20 when the user's Recharge request failed while the mower was outside the known map. |
| 204 | map-edit request | zone / exclusion add / edit / delete: first of the pair |
| 215 | map-edit confirm | same edit: second of the pair, carries `id` and `ids` |
| 401 | **takePic** — routed-action `m:'a' o:401`. State-aware acceptance, observed two distinct firmware echoes 2026-04-27 via HA-integration button press: (a) **docked** → echo `{o:401, exe:true, status:true, error:0}` — command accepted but capture silently skipped because the dock obscures the camera (mirrors the Dreame app's behaviour of disabling its Take Picture button at the dock); (b) **BT-disconnected manual-mode-stopped on the lawn** → echo `{o:401, exe:true, status:false}` — command **rejected**: firmware refuses outright because the mower isn't in a "ready to capture" state. So `status:false` is a new s2p50 signal class distinct from `status:true error:0` (accepted) and `status:true error:N` (accepted-but-failed). **However: the Dreame app's Take Picture button doesn't use this opcode at all.** Comparison test 2026-04-27 10:59 — user pressed the app's Take Picture (mower in same lawn-stopped state as our rejected attempt 2 minutes earlier), got "Image uploaded successful" in the app, and the live MQTT capture shows **zero new messages** in the window (no s2p50, no event_occured, no method-other events). So the app's image capture flows through a separate cloud HTTP / OSS surface entirely — possibly a direct media-upload REST endpoint, possibly a different `siid:aiid` we haven't enumerated. Reading the apk's takePic flow handler is the next step to characterise the proper fetch path. Until then, `op:401` from the integration is best-case a no-op (firmware accepts but doesn't capture), worst-case a rejection. Auto-capture on AI human detection is presumably the same cloud-only flow. |

Flat-fields variants without the `d` wrapper are the session-task metadata
described under §4.3 "Session start" (`o: 100`).

**Maintenance-point placement** — tapping a spot on the map in the
Dreame app to define a custom maintenance location. Confirmed
2026-04-20 18:14:06–18:14:07: **two `s1p50 = {}` pulses, 1 second
apart**, and nothing else. No `s2p50` envelope, no coordinate payload,
no `s6p1`/`s6p3`. The actual coord lives in Dreame-cloud user-prefs
(probably alongside zones in the MAP.* dataset) — the `s1p50` pair is
just a "something changed, consider re-fetching" ping the mower sends
when the cloud applies the prefs update. The *Head to Maintenance
Point* button press (which actually moves the robot) is still
uncaptured.

See §4.7 for the full `s1p50` / `s1p51` / `s1p52` role catalogue —
the "something changed" ping fires at many more boundaries than just
this one.

**Still-silent app operations**:

- Scheduled-mow add / edit / delete (noted in §7.1).

### 4.7 Empty-dict `s1p50` / `s1p51` / `s1p52` / `s2p52` — lightweight state-change pings

All four slots carry an empty `{}` — no payload. Their role is positional:
which slot fires, and how many times, signals the event class. The
session-START half (s1p50 + s1p51) and the session-END half
(s1p52 + s2p52) together bracket every mowing run.

| Slot | Role | Observed triggers |
|---|---|---|
| `s1p50` | "something changed, consider re-fetching" ping | Session start (paired with s1p51), BUILDING save (multiple pulses), zone/exclusion edit (paired with `s2p50 o=215`), maintenance-point save (two pulses, 1 s apart, no other context) |
| `s1p51` | **Dock-position-update trigger** (apk decompilation) — fires when the dock pose changes; consumer should re-fetch via the routed `getDockPos` action (see §6.2). **Correction:** previously hypothesized as a session-start companion to `s1p50` based on observed co-occurrence at session-start. Co-occurrence is real (the firmware fires both within the same second when a mowing run begins) but the apk specifies `s1p51`'s primary semantic is dock-pose change. |
| `s1p52` | "task ended — flush / commit" | Session complete (`s2p2 = 48`). Observed at natural end (12:33:09 on 2026-04-20) and user-cancel (18:06:19). Doesn't fire at BUILDING end. Also fires immediately before the cloud `event_occured siid=4 eiid=1` session-summary push (2026-04-22 16:35:17). |
| `s2p52` | **Mowing-preference-update trigger** (apk decompilation) — fires when PRE settings change; consumer should re-fetch via the routed `getCFG` action (see §6.2). **Correction:** previously hypothesized as a session-end companion to `s1p52` based on observed co-occurrence at session end (16:35:17.786 → 18.031). Per apk, the semantic is preference-change, not session-end. The earlier hypothesis predicting "s1p52 + s2p52 together bracket session ends" no longer holds; the firmware just happens to fire `s2p52` at session end because it's also re-emitting prefs as part of session teardown. |

Practical implication: treat a standalone `s1p50` (no `s1p51`, no `s2p50`) as
a "something edited server-side" signal and re-fetch whatever you cache from
the cloud — in the integration's case, the MAP.* dataset. See §7.1.

**Note (2026-04-23 correction)**: an earlier hypothesis claimed
`s1p52 + s2p52` together bracket session ends, mirroring
`s1p50 + s1p51` at session start. The apk decompilation refutes
this — `s1p51` is a dock-update trigger and `s2p52` is a
preference-change trigger. The actual "session ended" signal
is the cloud `event_occured siid=4 eiid=1` push (§7.4) plus
the area-counter delta discriminator for blades-up/down (§3.1
"Detecting blades-down"). The apparent co-occurrence at session
boundaries is a side effect of firmware bookkeeping (re-emitting
prefs and dock pose when a session changes phase), not a
dedicated session-boundary signal.

### 4.8 Positioning-failed recovery via SLAM relocate

The mower relies on LiDAR-based SLAM to localize itself against the saved
map. When it wakes up outside the known area (e.g. user ended a Manual
session with the dock outside the mowing boundary, as observed
2026-04-20 19:27) or loop-closure fails for some other reason, it enters
a **Positioning Failed** state. Every cloud-issued task command in that
state fails.

**Failure pattern** (full capture 2026-04-20 19:28–19:35):

```
19:28:19  s2p2 = 71      — Positioning Failed (new code, §4.1)
19:28:19  s2p1 = 5        — attempts RETURNING, stays there for ~90 s
19:29:56  s2p2 = 33       — failure transition
19:29:57  s2p1 = 2 (IDLE) + s2p2 = 31 (idle-after-error)
          → "Failed to return to station" app notification

User retried Recharge at 19:34:20:
19:34:19  s2p2 = 33       — failure transition
19:34:20  s2p2 = 36       — cancellation / reset marker
19:34:20  s2p50 = {d:{o:109, status:False, exe:True}, t:TASK}
            — op-code 109 = "Task start failed" with status:False (first
              ever s2p50 with a False status — dedicated error path)
19:34:20  s2p1 = 2 (IDLE) + s1p52 = {}
19:34:20  s2p50 = {d:{o:-1, status:True, exe:True}, t:TASK}
            — op-code -1 = "Error abort" cleanup marker
19:34:21  s2p1 = 5        — retries RETURNING, fails again at 19:35:50
          → "Failed to start the task" app notification
```

**Recovery** (user physically drove the mower from the dock onto the
lawn via Manual mode, ended Manual, then tapped Recharge):

```
19:42:42  s2p1 = 1 (MOWING)                — Manual drive starts
19:42:52  s5p107 = 56, s5p105 = 1,
          s5p106 = 1, s5p104 = 7           — SLAM counters reset
19:42:52  s2p65 = 'TASK_SLAM_RELOCATE'     — LiDAR relocalization kicks
          … 3 pushes of s2p65 + s5p104      in (see §2.1 for s2p65's
          in 1 second …                     string-value nature)
19:42:58  s2p1 = 2 (IDLE)                  — relocate succeeded,
                                             mower now knows its position
19:43:00  s2p1 = 5 (RETURNING)             — retries RETURNING — works
                                             this time
19:44:01  s3p2 = 1                          — charging starts
19:44:07  s2p1 = 6 (CHARGING)              — docked successfully
```

**Integration implications:**

- `s2p2 = 71` is worth a `binary_sensor.dreame_a2_mower_positioning_failed`
  (PROBLEM class) so users know the mower is stuck needing manual
  intervention — the Dreame app's notification channel is the only
  existing UX for this and HA users rarely watch that.
- `s2p65 = 'TASK_SLAM_RELOCATE'` is the "mower is re-localizing" signal.
  Useful for a `sensor.dreame_a2_mower_slam_activity` that surfaces
  which SLAM task is running (RELOCATE now; future firmware may add
  MAPPING / LOOP_CLOSURE / etc).
- `s2p50 o=109 status:False` marks the end-of-failure-path; pairs with
  `o=-1` abort cleanup. Also worth reflecting via an event so
  automations can catch them.

---

## 5. Obstacle detection

`s1p53` fires `True` near obstacles and excluded areas during mowing. Observed
26 triggers in ~15 min near an exclusion zone, mean duration ~6.6 s. Separate
from human-presence detection (which goes through the Dreame cloud push-notification
service directly, not via MQTT — HA integration cannot observe it).

---

## 6. `s2p51` — multiplexed configuration writes

All "More Settings" toggles in the Dreame app that travel via cloud share this
single property. The payload shape discriminates the setting:

| Setting | Payload |
|---|---|
| Do Not Disturb | `{'end': min, 'start': min, 'value': 0\|1}` |
| Low-Speed Nighttime | `{'value': [enabled, start_min, end_min]}` |
| Navigation Path | `{'value': 0\|1}` (0=Direct, 1=Smart) |
| Charging config | `{'value': [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]}` |
| Auto Recharge Standby | `{'value': 0\|1}` |
| LED Period | `{'value': [enabled, start_min, end_min, standby, working, charging, error, reserved]}` |
| Anti-Theft | `{'value': [lift_alarm, offmap_alarm, realtime_location]}` |
| Child Lock | `{'value': 0\|1}` |
| Rain Protection | `{'value': [enabled, resume_hours]}` |
| Frost Protection | `{'value': 0\|1}` |
| AI Obstacle Photos | `{'value': 0\|1}` |
| Human Presence Alert | `{'value': [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]}` |
| Consumables runtime counters | `{'value': [blades_min, brush_min, maintenance_min, link_module]}` |
| Timestamp event | `{'time': 'unix_ts', 'tz': 'Europe/Oslo'}` |

Times are minutes from midnight. All confirmed via live toggle testing.

#### Consumables runtime counters — slot map and thresholds

The 4-element list shape collides with the 4-bool MSG_ALERT/VOICE shape. The decoder discriminates by element values: any element `> 1` or `< 0` routes to CONSUMABLES; otherwise the payload is the ambiguous 4-bool list.

| Index | Item (in app's "Consumables & Maintenance" page) | Threshold | Sentinel |
|---|---|---|---|
| 0 | #1 Blades | 6000 min ≈ 100 h | — |
| 1 | #2 Cleaning Brush | 30000 min ≈ 500 h | — |
| 2 | #3 Robot Maintenance | 3600 min ≈ 60 h | — |
| 3 | #4 Link Module | n/a | `-1` on g2408 — integrated, no wear timer |

Each slot is a per-consumable runtime counter (minutes); the app shows `(threshold − counter) / threshold` as a percent. Confirmed 2026-04-30 19:57:16 by fake-replacing the Cleaning Brush in the app — the array changed from `[3084, 3084, 0, -1]` to `[3084, 0, 0, -1]`, only index 1. Threshold values cross-checked: with counter `3084 ≈ 51.4 h`, blades show 48.6% remaining (matches 100 h total) and a Robot Maintenance counter of 3084 would show 14% remaining (matches the user's pre-acknowledge reading and the 60 h total).

Acknowledging "Robot maintenance done" in the app does **not** appear to echo a `properties_changed` message on the local MQTT status topic — the cloud accepts the ack but doesn't relay it back. The reset *does* land eventually (the slot value is 0 in subsequent CONSUMABLES emissions). `s2p51` also overloads to a heartbeat shape `{'time', 'tz'}` periodically; both shapes share the same property.

### 6.1 Cloud-visible vs Bluetooth-only settings

**Cloud/MQTT (visible in `s2p51` pushes):** Do Not Disturb, Low-Speed Nighttime,
Navigation Path, Charging config, Auto Recharge Standby, LED Period, Anti-Theft,
Child Lock, Rain Protection, Frost Protection, AI Obstacle Photos, Human Presence
Detection Alert.

**Cloud-readable via `getCFG` routed action (§6.2, confirmed on g2408 alpha.85):**
All 24 keys in the CFG dict: AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG,
LIT, LOW, MSG_ALERT, PATH, **PRE** (zone + mode — NOT the full apk schema —
see §6.2), PROT, REC, STUN, TIME, VER, **VOICE** (4 prompt toggles), VOL,
WRF, WRP. This includes settings previously thought to be BT-only:
**Mowing Efficiency** (PRE[1]), **Robot Voice/Volume** (VOICE + VOL),
**Notifications** (MSG_ALERT), **Language** (LANG), **Timezone** (TIME),
**Anti-Theft** (STUN), **Weather/Frost/Navigation-Path** (WRF/PROT/PATH).

> ⚠ **Naming caveat (corrected 2026-04-27):** the label "Bluetooth-only" is misleading. The HA integration successfully started an Edge Mow on 2026-04-27 09:42:58 via cloud routed-action `siid:2 aiid:50 op:101` with **zero BT connectivity to the mower** — the integration is purely cloud + MQTT. So the Dreame app's BT link almost certainly isn't carrying basic settings either; it's a side channel for bulk diagnostic / OTA / voice-pack data, not a parallel control protocol. The settings below are more accurately **"cloud-write-invisible-on-MQTT"**: the app probably writes them via routed-action `setX` calls (`m:'s'`) we haven't enumerated, which trigger only an `s6p2` tripwire as visible side-effect. They're *readable nowhere* on MQTT (CFG, OBS, AIOBS, MAP all stay clean), but probably *writable* via an unknown `setX` target. Worth probing the apk for the missing target names and trying writes from HA.

**Cloud-write-invisible-on-MQTT settings (formerly "Bluetooth-only", still invisible from cloud/HA on g2408):**
- Obstacle Avoidance Distance
- Obstacle Avoidance Height
- Start from Stop Point
- Pathway Obstacle Avoidance — **re-confirmed 2026-04-24** on alpha.124
  with `cfg_keys_raw` + `_last_diff` attrs: toggling the switch produced
  zero MQTT traffic and zero CFG diff. Note the app pairs the toggle
  with a map-draw component (per-pathway zone geometry); that zone data
  may still live in the cloud MAP.* dataset, but the on/off state of
  the feature itself is BT-local.
- **Mowing Direction** (incl. sub-settings — Crisscross / Chequerboard / 180°/90°) — re-confirmed 2026-04-26 alpha.140 with both `cfg_keys_raw _last_diff` and `s6p2` element-decode visible. Toggle fires `s6p2` as the "settings-saved tripwire" but every element of the frame stays unchanged — the value is BT-local.
- **Automatic Edge Mowing** — confirmed BT-only 2026-04-26 alpha.140 via toggle test. Same signature as Mowing Direction: s6p2 tripwire fires, no frame element flips.
- **Safe Edge Mowing** — confirmed BT-only 2026-04-26 alpha.140 via toggle test. Same signature.
- **Obstacle Avoidance on Edges** — confirmed BT-only 2026-04-26 alpha.140 via toggle test. Same signature (s6p2 tripwire, no frame element flips).
- **LiDAR Obstacle Recognition** (incl. sub-setting "Obstacle Avoidance Height") — confirmed BT-only 2026-04-26 alpha.140 via toggle test. Same signature. Note that the height sub-setting having multiple values (5/10/15/20 cm) didn't reveal anything in `s6p2[3]` either — that hypothesis is dead.
- **AI Obstacle Recognition** (3 sub-toggles: Humans, Animals, Objects) — all three confirmed BT-only 2026-04-26 alpha.140 via toggle test. Each fires the s6p2 tripwire with no CFG diff and no frame element change.
- **Obstacle Avoidance Distance** (3-state: 10cm / 15cm / 20cm) — confirmed BT-only 2026-04-26 alpha.140 via toggle test stepping all three values. Each step fires the s6p2 tripwire with no CFG diff and no frame element change. This is the second multi-band setting that doesn't move `s6p2[3]` — strong evidence that `[3]` is not a user-toggleable multi-state at all.
- **Spot placement** (small lawn-area mark for explicit spot-mow command) — confirmed BT-local 2026-04-26 alpha.148. Adding a spot fires two `s1p50 = {}` empty-dict pings (same pattern as Maintenance Point), but the cloud MAP.* payload returns an unchanged md5 across multiple spot adds, and `spotAreas` stays empty. **Even an active spot-mow run doesn't leak the coords**: a complete 7-minute spot mow on 2026-04-26 21:49–21:57 generated zero `s2p50` envelopes — the state stream had only `s2p2=50` (manual session-start, identical to all-area), `s2p1` mode transitions, and s1p4 telemetry. The launch went through `routed-action(siid:2 aiid:50 m:'a' o:103)` which does NOT echo on the s2p50 property channel, so the integration's MQTT listener never sees the launch envelope or the spot coords. End-of-mow added a new sub-state observation: `s2p56 = {status:[[1, 2]]}` fires just before `s2p2 = 48 (MOWING_COMPLETE)` — adding to the s2p56 catalog (previously known: `[[1, 0]]` running, `[[1, 4]]` paused-pending-resume). |

**Reclassified to cloud-visible 2026-04-26 (originally listed as BT-only):**
- Mowing Height — `s6p2[0]` in mm.
- Mowing Efficiency — `s6p2[1]` (0=Standard, 1=Efficient).
- EdgeMaster — `s6p2[2]` bool.
- Robot Voice / Volume — `CFG.LANG[1]` and `CFG.VOL`.

The original "BT-only" attribution was based on observing zero MQTT traffic when toggling, made when getCFG was unreachable due to a wrong URL path. With both `s6p2` parsed in full and CFG fetchable on every tripwire (alpha.139+), more BT-only settings may yet turn out to be cloud-readable.

The Dreame app holds a direct BT connection to the mower while open. Write-path
settings chosen by the app code itself; the user has no control over which
transport is used. For the HA integration this means **entities for BT-only
settings cannot exist** — users must be told explicitly in the README which
settings will be missing.

### 6.2 Routed action endpoint (siid:2 aiid:50)

> **2026-04-23 resolution (g2408):** Endpoint **confirmed working**
> on g2408 after URL correction. The apk-documented URL shape is
> `https://eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand`
> (with `-10000` iotComPrefix suffix hardcoded for Dreame brand;
> `-20000` for Mova brand). Our integration initially hit
> `/dreame-iot-com/device/sendCommand` without the suffix and got
> 404 NOT_FOUND. Root cause was a timing race: the first
> `refresh_cfg` call fires from `_connected_callback`, which runs
> BEFORE `_handle_device_info` populates `self._host` from the
> bind info. Without `_host`, URL construction yielded an empty
> prefix. Fix (alpha.80): when `method=='action'` and derived host
> is empty, fall back to the apk-hardcoded `-10000`. The fallback
> plus forced `https://` scheme unblocks the routed-action surface
> on g2408.
>
> First getCFG on g2408 returned **24 settings keys**:
> ```
> AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG, LIT, LOW,
> MSG_ALERT, PATH, PRE, PROT, REC, STUN, TIME, VER, VOICE, VOL,
> WRF, WRP
> ```
> All 15 apk-documented keys are present (`WRP/DND/BAT/CLS/VOL/LIT/AOP/REC/STUN/ATA/PATH/WRF/PROT/CMS/PRE`).
> The 9 extras (`BP, DLS, FDP, LANG, LOW, MSG_ALERT, TIME, VER, VOICE`)
> are g2408-specific and not catalogued in the apk — their schemas
> need further RE.

Per apk decompilation, the Dreame mower exposes most of its
configuration + control surface through a single MIoT action
call:

```
action {
  siid: 2,
  aiid: 50,
  in: [{ m: 'g'|'s'|'a'|'r', t: <target>, d: <optional payload> }]
}
```

`m` is the mode (`g`et / `s`et / `a`ction / `r`emote-control) and
`t` is the target. Result lands at `result.out[0]`. The
integration's `protocol/cfg_action.py` provides typed wrappers
(`get_cfg`, `get_dock_pos`, `set_pre`, `call_action_op`).

Most useful targets:

| `m` `t` | Returns | Used in |
|---|---|---|
| `g CFG` | All settings dict (WRP, DND, BAT, CLS, VOL, LIT, AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE) | `device.refresh_cfg` |
| `g DOCK` | `{x, y, yaw, connect_status, path_connect, in_region}` | `device.refresh_dock_pos` |
| `s PRE` | Write 10-element preferences array (read-modify-write) | `device.write_pre` |
| `a` `o:OP` | Action opcode (100 globalMower, 101 edgeMower, 9 findBot, 11 suppressFault, 12 lockBot, 401 takePic, 503 cutterBias …) | `device.call_action_opcode` |

The full opcode catalog and CFG-key schemas live in the apk
cross-reference: `docs/research/2026-04-23-iobroker-dreame-cross-reference.md`.

#### PRE schema

**Apk catalog (g2568a, 10 elements):**
`PRE = [zone, mode, height_mm, obstacle_mm, coverage%, direction_change, adaptive, ?, edge_detection, auto_edge]`

**g2408 (empirically, 2 elements):**
`PRE = [zone_id, mode]`

- PRE[0]: zone id
- PRE[1]: mode (0=Standard, 1=Efficient)

Indexes 2-9 from the apk schema **do not exist on g2408**. Cutting
height, obstacle distance, coverage %, direction change, edge
detection, and auto-edge toggles likely live in a different key or
are Bluetooth-only on g2408. Alpha.86 removed the entities that
read PRE[2..9]; only `mow_mode` and `mow_mode_efficient` (both
reading PRE[1]) remain.

#### g2408 CFG schema (alpha.85 dump, 24 keys)

Recorded 2026-04-23, firmware `dreame.mower.g2408` (`_host=10000.mt.eu.iot.dreame.tech:19973`):

| Key | Shape / sample | Semantic (confirmed or best-guess) |
|---|---|---|
| `AOP` | `int=1` | "Auto Operation" — best-guess config flag for whether scheduled mowing is honored (1=schedule active, 0=manual-only). Alternative: per-session manual-vs-scheduled flag (less likely since CFG is persistent and per-session info lives in `s2p2` enum like `SESSION_STARTING_SCHEDULED`). Disambiguate by toggling the app's schedule and watching `AOP` in the next CFG refetch. |
| `ATA` | `list(3) [0,0,0]` | Auto-task-adjust (apk-catalogued) |
| `BAT` | `list(6) [15, 95, 1, 0, 1080, 480]` | Charging schedule: `[min_pct, max_pct, enabled, custom, start_min, end_min]` = `[15%, 95%, on, off, 18:00, 08:00]` |
| `BP` | `list(2) [1, 3]` | TBD (same shape as WRP) |
| `CLS` | `int=0` | Auto-close / clean-slow? (TBD) |
| `CMS` | `list(4) [blade_min, brush_min, robot_min, aux_min]` | Wear meters. Apk documents 3; g2408 has 4. Max-minutes: `[6000, 30000, 3600, ?]`. Blade/brush/robot confirmed vs app. CMS[3] semantic TBD — likely tied to one of the app-visible "Consumables & Maintenance" accessories without a percentage: **Link Module** (cellular connectivity, electronics that age — most plausible wear candidate), **Garage** (dock enclosure, passive hardware), or **Charging Station MCA10** (secondary station for split lawns, passive hardware). User without any of those accessories will see CMS[3]=0 indistinguishable from "fresh accessory at 100%". Confirmation needs a user with a Link Module to compare CMS[3] vs an app-side fault/firmware indicator. |
| `DLS` | `int=0` | Daylight-savings? (TBD) |
| `DND` | `list(3) [enabled, start_min, end_min]` | Do-not-disturb (apk-catalogued). Sample `[0, 21:00, 07:00]` = off. |
| `FDP` | `int {0,1}` | **Frost Protection** (confirmed 2026-04-24 via isolated single-toggle). Mapping `{0: off, 1: on}` matches the app. Surfaced as `sensor.frost_protection`. |
| `WRP` | `list[int, int]` | **Rain Protection** (confirmed 2026-04-24 via live toggle). Shape `[enabled, resume_hours]`. `enabled ∈ {0,1}`; `resume_hours ∈ {0..24}`, where `0 = "Don't Mow After Rain"` (no auto-resume) and `1..24` resume N hours after rain ends. Shape matches the `s2p51` RAIN_PROTECTION decoder at §4.X. Surfaced as `sensor.rain_protection`. Distinct from `binary_sensor.rain_protection_active` which tracks "raining right now" via `s2p2=56`. |
| `LOW` | `list[int, int, int]` | **Low-Speed Nighttime** (confirmed 2026-04-24 via live toggle). Shape `[enabled, start_min, end_min]` with `start_min`/`end_min` in minutes-from-midnight. User example: `[1, 1200, 480]` = enabled, 20:00 → 08:00 next day. Shape matches the `s2p51` LOW_SPEED_NIGHT decoder. Surfaced as `sensor.low_speed_nighttime`. |
| `STUN` | `int {0,1}` | **Auto Recharge After Extended Standby** (confirmed 2026-04-24). Mapping `{0: off, 1: on}`. Surfaced as `sensor.auto_recharge_standby`. Was previously mislabelled as "Anti-Theft" in sensor.py (upstream vacuum codebase naming that doesn't apply on g2408). **Behaviour observed 2026-04-27**: when STUN=1 and the mower is idle outside the dock for ~1 hour (BT-orphaned manual stop ~10:55 → auto-return 11:52:47 = 57 min), the firmware fires `s2p2=71 + s2p1=5` simultaneously and self-navigates back to the dock. Dreame app notification confirms: *"The robot is on standby outside the station for too long. Automatically returning to the station."* Whether the timeout duration is a firmware constant or stored in another (still uncatalogued) CFG slot is unknown — STUN itself is just an enable flag. |
| `AOP` | `int {0,1}` | **Capture Photos of AI-Detected Obstacles** (confirmed 2026-04-24). Mapping `{0: off, 1: on}`. Surfaced as `sensor.ai_obstacle_photos`. |
| `CLS` | `int {0,1}` | **Child Lock** (confirmed 2026-04-24). Mapping `{0: off, 1: on}`. Surfaced as `sensor.child_lock_cfg`. A `switch.child_lock` entity already exists wired to `DreameMowerProperty.CHILD_LOCK`, but on g2408 the authoritative read path is `CFG.CLS`. |
| `REC` | `list[int × 9]` | **Human Presence Detection Alert** (confirmed 2026-04-24). Shape matches the `s2p51` HUMAN_PRESENCE_ALERT decoder exactly: `[enabled, sensitivity, standby, mowing, recharge, patrol, alert, photo_consent, push_min]`. `sensitivity ∈ {0, 1, 2}` = low / medium / high. `scenario_*` fields enable detection per activity class. `alert` covers voice prompts + in-app notifications. `photo_consent` is the privacy opt-in for sending captured human photos. `push_min` is the push-notification cooldown in minutes (observed: 3 / 10 / 20). Surfaced as `sensor.human_presence_alert`. |
| `LANG` | `list[int, int]` | **Language** (confirmed 2026-04-24). Shape `[text_idx, voice_idx]`. `text_idx` = app/UI language; `voice_idx` = robot voice language. Observed indices: `voice_idx = 7` → Norwegian. Transported via a previously-unknown `s2p51` shape `{"text": N, "voice": M}` — now decoded as `Setting.LANGUAGE`. Surfaced as `sensor.robot_voice` (state = voice language name where known, raw indices as attrs). |
| `VOL` | `int 0..100` | **Robot Voice volume** (confirmed 2026-04-24). Mapping is percentage. Surfaced as `sensor.robot_voice_volume`. |
| `VOICE` | `list[int × 4]` | **Voice Prompt Modes** (confirmed 2026-04-24; index `[1] = Work Status Prompt` confirmed 2026-04-27 by isolated toggle that produced an `s2p51` 4-bool list event with no other CFG key changing). Four bool toggles for which situations the robot speaks: `[regular_notification, work_status, special_status, error_status]`. **Wire shape collides with `MSG_ALERT`** — both ride `s2p51 {value: [b,b,b,b]}` and the firmware does not name the setting. The `s2p51` decoder therefore emits `Setting.AMBIGUOUS_4LIST`; resolve via `sensor.cfg_keys_raw` `_last_diff`. Surfaced as `sensor.voice_prompt_modes` (state = count enabled 0..4, per-mode bools in attrs). |
| `BAT` | `list[int × 6]` | **Charging config** (confirmed 2026-04-24). Shape matches the `s2p51` CHARGING decoder exactly: `[recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]`. `recharge_pct` = auto-recharge when battery drops below this; `resume_pct` = resume mowing when battery above this; `unknown_flag` consistently observed =1 (purpose TBD); `custom_charging` bool toggles the schedule window; `start_min`/`end_min` = window in minutes-from-midnight. Surfaced as `sensor.charging_config`. |
| `LIT` | `list[int × 8]` | **Lights** (confirmed 2026-04-24). Shape `[enabled, start_min, end_min, standby, working, charging, error, unknown]` — matches the `s2p51` LED_PERIOD decoder exactly. Per-index meaning: `[0]` Custom LED Activation Period on/off, `[1]` window start (min-from-midnight), `[2]` window end, `[3]` scenario "In Standby", `[4]` "In Working", `[5]` "In Charging", `[6]` "In Error State", `[7]` an unknown trailing toggle (user reported a last field in the app whose purpose isn't obvious). Surfaced as `sensor.headlight_enabled` (on/off from `[0]`) + `sensor.headlight_schedule` (time window from `[1]/[2]` plus all four scenario flags and `[7]` as attributes). Entity keys kept as `headlight_*` for dashboard compat; the app term is "Lights". |
| `ATA` | `list[int × 3]` | **Anti-Theft Alarm** (confirmed 2026-04-24, all three indices individually verified 2026-04-27). Shape `[lift_alarm, offmap_alarm, realtime_location]` — matches the `s2p51` ANTI_THEFT decoder exactly. Toggle test: `[0,0,0] → [1,0,0]` Lift, `[1,0,0] → [1,1,0]` Off-Map, `[1,1,0] → [1,1,1]` Real-Time Location. Surfaced as `sensor.anti_theft` (state=on if any sub-flag enabled, per-flag bools in attributes). |
| `LANG` | `list(2) [lang_id, variant]` | Voice pack language + variant. Sample `[2, 0]` corresponds to the **first entry in the app's Voice→Language list (English)** — so the language IDs are firmware-specific ordinals, NOT ISO codes or alphabetical. Prior guess (Norwegian-by-timezone) was wrong. LANG[1]=0 likely a dialect/variant flag. Needs a mapping table of firmware-ids-to-names, obtainable by cycling through the app's language list and capturing each LANG value. |
| `LIT` | `list(8) [enabled, start_min, end_min, l1, l2, l3, l4, reserved]` | Headlight (apk had 7; g2408 has 8 — extra byte likely reserved). |
| `LOW` | `list(3) [enabled, start_min, end_min]` | Low-speed night mode. Same shape as DND. |
| `MSG_ALERT` | `list[int × 4]` | **Notification Preferences** — app's per-event-type push toggles. Index → app-list-row pattern (app order = list-index order). Confirmed 2026-04-27: `[0] = Anomaly Messages` (clean isolated toggle 1→0), `[2] = Task Messages` (3rd app row = 3rd list element). `[1]` and `[3]` are the 2nd and 4th notification rows — labels not yet captured. Default sample `[1,1,1,1]` = all four enabled. **Wire shape collides with `VOICE`** — both ride `s2p51 {value: [b,b,b,b]}`; the `s2p51` decoder emits `Setting.AMBIGUOUS_4LIST` and resolution requires reading the `getCFG` diff to see which key flipped. |

#### LOCN — dock GPS origin (not real-time mower position)

`getCFG t:'LOCN'` on g2408 returns `{'d': {'pos': [lon, lat]}, 'm': 'r', 'q': N, 'r': 0}`. **Confirmed 2026-04-27**: the response shape is a 2-element `pos` array, NOT the iobroker-doc-implied `{lon, lat}` dict. Default value when the dock's GPS origin has never been written via `setLOCN` is `[-1, -1]` (sentinel for "not configured").

The endpoint stores the *dock origin*, not the live mower coordinate. Despite ATA[2] (Real-Time Location anti-theft) being on, `getLOCN` does not return a moving fix — the firmware has nothing real-time to report on this path. The Dreame app's "real-time Google Maps view" is therefore almost certainly **computed client-side** from this stored dock origin plus the mower's local-frame xy (mm) plus `MapHeader.heading_to_north_deg`, NOT delivered as a server push. Implication: HA's `device_tracker.dreame_mower_gps` will only become useful once `setLOCN` has been run with a real dock-origin lat/lon, and even then only as a *static dock pin* — moving-mower tracking would need the same client-side projection logic the app does.
| `PATH` | `int {0,1}` | **Unknown on g2408.** Observed stable at `1` through a Navigation Path toggle test 2026-04-25, so NOT the Navigation Path setting despite earlier user guess. Semantic TBD; exposed as `sensor.cfg_path_raw` (disabled-by-default diagnostic) so the raw int is visible for future toggle-correlation tests. |
| `PRE` | `list(2) [zone_id, mode]` | See above. |
| `PROT` | `int {0,1}` | **Navigation Path** (confirmed 2026-04-24 via isolated single-toggle with `cfg_keys_raw` diff visible on HA alpha.123+). Mapping `{0: "direct", 1: "smart"}` matches the order shown in the app. Surfaced as `sensor.navigation_path`. The field name is cryptic but the toggle correlation is unambiguous: toggling Nav Path `smart → direct` flipped PROT `1 → 0` with no other CFG key moving. Earlier alpha.89 guess "PROT = Frost Protection" was wrong — that mapping should not be reintroduced. |
| `REC` | `list(9) [1,1,1,1,1,1,1,0,3]` | Recharge config. First 7 = days-of-week? (TBD) |
| `STUN` | `int` | Anti-theft (0=off, 1=on) |
| `TIME` | `str` | Timezone IANA name, e.g. `'Europe/Oslo'`. Exposed as `mower_timezone` sensor. |
| `VER` | `int` | **CFG-update revision counter** (corrected 2026-04-24 — was previously mis-labelled "firmware version"). Monotonic increment on every successful CFG write; useful as a tripwire for toggle-correlation research. Distinct from the actual firmware version surfaced by `sensor.firmware_version` (which reads `device.info.version`, a separate cloud field). Surfaced as diagnostic `sensor.cfg_version`. |
| `VOICE` | `list(4) [regular_notif, work_status, special_status, error_status]` | App's Voice screen 4 toggles. Sample `[1,1,1,1]` = all on. Confirmed 2026-04-23 by user correlation. |
| `VOL` | `int` | Volume % (0..100) |
| `WRF` | `int` | Weather reference (0=off, 1=on) |
| `WRP` | `list(2) [1, 3]` | TBD (apk-catalogued but no schema) |

#### Empirical validation (Task 4 fixture)

`tests/protocol/fixtures/captured_s1p4_frames.json` records the
decoded uint24 task struct (region=1, task=3, percent=48.47%,
total=339 m², finish=164.31 m²) for a documented mid-session
capture. The total/finish values match the user's app reading
exactly, validating the apk's task-struct interpretation on
g2408.

---

## 7. Map-fetch flow (s6p1 / s6p3 + OSS)

> **See also:** [`cloud-map-geometry.md`](./cloud-map-geometry.md) for the
> coordinate-frame / rotation / reflection math every overlay writer needs
> after the map data is in memory.


This is the active investigation thread. The A2 does **not** push the map as a
single MQTT blob the way some older Dreame devices do. Instead:

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

### 7.1 Trigger conditions (from historical observations)

Fully re-measured during the 2026-04-20 full-run (07:58 → 12:33, two auto-recharge interrupts, one clean session end). The mechanism is clearer now than it appeared from earlier partial captures:

| Event | MQTT artefact | Notes |
|---|---|---|
| **Auto-recharge begins** (MOWING → RETURNING for top-off) | `s6p1 = 300` | Fires at the exact ms `s2p2 → 54`, `s2p1 → 2 → 5`. Confirmed twice in the 2026-04-20 run at 09:14:09 and 11:13:04. This is the primary mid-session "map may have been refreshed" signal. |
| **True session completion** (task done, not recharge) | `event_occured siid=4 eiid=1`, `piid 9 = ali_dreame/…/*.json` | Fires once at session end (12:33:12 — 3 s after `s2p2 = 48`). Carries the *session-summary* OSS key. See §7.4. |
| **LiDAR point-cloud upload** | `s2p54` 0..100 progress counter + `s99p20 = ali_dreame/…/*.bin` | Only when the user opens "Download LiDAR map" in the Dreame app, and only if the scan has changed since last upload. Not pushed passively. See §7.4.1 for full sequence. |
| User taps "End" while docked (no actual mowing) | (none) | No map push, no summary event. |
| Manual pause mid-mow | (none) | No map push. |
| Session start from dock | `s2p56: [[1,4]] → []`, `s2p1 → 1`, `s2p2 → 50` or `53` | No map push — the mower is just starting to generate new data. |

Key corrections vs. earlier notes:
- `s6p1 = 300` is **not** a session-completion signal. It's a recharge-leg-start signal. The session-completion trigger is the `event_occured` on its own dedicated method — which the integration now handles (§7.4).
- The 2026-04-20 run produced **two** `s6p1 = 300` pushes (once per recharge interrupt) plus **one** `event_occured`. Three distinct "map-ish" artefacts per session, each with its own meaning.

**Silent inflection points** (mower's internal map changes, no MQTT signal):

The mower does NOT broadcast a map-ready signal for:
- Scheduled session starts (`s2p2 = 53`, `s2p1 → 1`).
- Manual session starts (`s2p2 = 50`, `s2p1 → 1`).
- BUILDING-end (user tapped *Expand Lawn* or *Add Zone*; `s2p1: 11 → 2`).
- App-driven zone / exclusion edits (`s2p50` `o=215`, see §4.6) — this one
  is discoverable from MQTT, just not as `s6p1 = 300`.

For the first three, the MAP.* cloud dataset may have changed server-side
during the previous session boundary but the integration would never know.
**As of v2.0.0-alpha.19** the integration proactively re-pulls the cloud map at
each of these inflection points (see `_schedule_cloud_map_poll`) — cheap
because `_build_map_from_cloud_data` md5-dedupes a no-change result into a
no-op. Triggers are:

| Trigger | Condition | Handler |
|---|---|---|
| Integration setup / HA startup | one-shot | `_build_map_from_cloud_data` |
| Periodic freshness check | every 6h | coordinator `async_track_time_interval` → `_schedule_cloud_map_poll` |
| s2p2 session-start code | `value ∈ {50, 53}` | `_message_callback` → poll |
| BUILDING complete | `s2p1: 11 → *` transition | `_state_transition_map_poll` → poll |
| Dock departure | `s2p1: 6 → *` transition | `_state_transition_map_poll` → poll |
| Map-edit confirm | `s2p50 d.o == 215` | `_message_callback` → poll (§4.6) |
| Auto-recharge leg start | `s6p1 = 300` | upstream map pipeline |

All five poll paths funnel into the same `_build_map_from_cloud_data`,
which fetches 28 MAP.* cloud keys (one HTTP round-trip, ~100–200 KB)
and compares the top-level `md5sum` against the previously-seen value.
**No lightweight probe exists** — the Dreame cloud stores the md5 inside
the compressed payload, so a full fetch IS the cheapest freshness
check. Unchanged md5 → no camera state change, no Lovelace reload.

**LiDAR archive cannot be proactively polled.** The mower only emits
`s99p20` when the user taps *Download LiDAR map* in the Dreame app and
the scan has actually changed. No passive endpoint exposes the current
scan's md5 or timestamp — the archive is as fresh as the last app view.

### 7.2 Failure modes seen on our fork

1. **`getFileUrl("")` returns 404** — querying the OSS URL without the object
   name yields a signed URL that 404s, confirming the bucket is empty for the
   object name we guess.
2. **`get_properties(s6p3)` returns `None` while mower is idle** — the property
   only materializes when there's a pending map.
3. **`get_properties(anything)` returns `{"code":10001,"msg":"消息不能读取"}` when the
   mower is idle** — Chinese "message cannot be read"; the cloud→mower RPC
   channel is quiescent, so no property snapshot can be pulled on demand.
4. **Our fork's `_request_current_map()` fails with `80001`** during active mowing
   for the same reason `sendCommand` always fails — see §1.2.

### 7.3 What we know works

- The mower → cloud MQTT push pipeline works reliably.
- Mid-task recharge does **not** trigger a fresh map push; only actual session
  completion does.
- Historical 2026-04-17 data shows the upstream A1 Pro client DID fetch our A2's
  map successfully (file `map_live.png`), so the OSS side of the flow works.
- **2026-04-19 discovery**: the session-summary OSS object key arrives not as
  an `s6p3` property-change but inside an `event_occured` MQTT message that the
  integration was never listening for. See §7.5.

### 7.3b LiDAR point-cloud upload sequence

Triggered by the user tapping *"View LiDAR Map"* in the Dreame app, provided
the current scan differs from the last-uploaded one (reopening the screen with
no scan change is a no-op). Confirmed 2026-04-20 17:41:58–17:42:28 with a
full progress sample at 1 Hz:

```
17:41:58  s2p54 = 0         ← upload requested, mower prepping
…six 0-s pushes…
17:42:04  s2p54 = 10        ← firmware started staging the PCD
17:42:08  s2p54 = 16
17:42:11  s2p54 = 21, 26, 26, 26, 26, 26, 32, 32, 37, 40, 45
17:42:22  s2p54 = 61        ← partway through OSS upload
17:42:28  s99p20 = "ali_dreame/2026/04/20/BM16nnnn/-11229nnnn_154157120.0550.bin"
17:42:28  s2p54 = 100       ← done
```

`s2p54` is a 0..100 progress percent, published roughly once per second while
the upload runs. `s99p20` arrives **before** the `s2p54 = 100` marker (today at
61 %) — the integration should therefore key off `s99p20` (which always lands
before the final tick) rather than waiting for `s2p54 = 100`.

Total wire time today: 30 seconds, 2.45 MB PCD (153 261 points). The HA
integration's `_handle_lidar_object_name` → `get_interim_file_url` → OSS
fetch → archive path completes within a few seconds of the `s99p20` arrival;
the new file lands under `<config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd`
and is content-addressed by md5 (re-tapping the same scan is a no-op).

### 7.4 `event_occured` at session completion — the missing trigger

Exactly once per completed mowing session, the mower posts a second MQTT method
(`event_occured`, vs. the usual `properties_changed`) with service-id 4,
event-id 1. Four of these have been captured across 2026-04-17 / 2026-04-18:

```json
{
  "id": 2376, "method": "event_occured",
  "params": {
    "did": "-11229nnnn", "siid": 4, "eiid": 1,
    "arguments": [
      {"piid": 1,  "value": 100},
      {"piid": 2,  "value": 195},
      {"piid": 3,  "value": 31133},            ← area mowed in centiares (311.33 m²)
      {"piid": 7,  "value": 1},
      {"piid": 8,  "value": 1776522523},       ← unix timestamp
      {"piid": 9,  "value": "ali_dreame/2026/04/18/BM16nnnn/-11229nnnn_193738455.0550.json"},
      {"piid": 11, "value": 0}, {"piid": 60, "value": -1},
      {"piid": 13, "value": []}, {"piid": 14, "value": 384}, {"piid": 15, "value": 0}
    ]
  }
}
```

The `piid=9` value is the OSS object key for the session-summary JSON.

Decoded fields across six captures (2026-04-17..2026-04-20, incl. one user-cancel):

| piid | guess | observed values |
|---|---|---|
| 1 | constant / flag | always 100 |
| 2 | end-code | 31, 36, 69, 128, 170, 195, 217 — 36 = user-cancel (2026-04-20 18:06). Other values from natural completions. 2026-04-24 added 217. NOTE: the 2026-04-24 run's 323/384 ratio is NOT partial coverage — total_area includes area under exclusion zones, so 323 m² is the full reachable area (user-confirmed). So the end-code enum doesn't seem to distinguish "partial vs full coverage"; more likely it encodes finish-cause (scheduled vs manual trigger, rain-interrupted vs normal, etc). Needs more captures to map. |
| 3 | area mowed × 100 (m² × 100) | 5232, 6647 (cancel, 66.47 m²), 10759, 19613, 28744, 31133 — matches the final `s1p4` `area_mowed_m2` reading at session end to within recharge-leg-transit overhead. |
| 7 | stop-reason-ish | 1 = natural completion; 3 = user-cancel (confirmed by the 2026-04-20 abort). |
| 8 | unix timestamp of session **start** | 2026-04-20 morning run: 1776664681 → 05:58:01 UTC = 07:58:01 local, exact match to `s2p1 → 1` at 07:58:03. The 18:06 user-cancel emitted 1776699000 = 15:30:00 UTC = 17:30:00 local — again session-start, not cancel-time. Confirms piid 8 is session-start, independent of end reason. |
| 9 | **OSS object key (`.json`)** | `ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.json` — fires for both natural completion AND user-cancel. |
| 11 | ? | 0 or 1 |
| 60 | ? | -1 (normal) or 101 (user-cancel, first non-`-1` observation 2026-04-20 18:06). May be an abort-specific reason code. |
| 13 | empty list | `[]` |
| 14 | **total mowable lawn area (m², rounded int)** | 379 pre-2026-04-18, 384 after user added a zone in-app. Matches `map_area` and rounded `map[0].area` in the session-summary JSON — user-confirmed that the lawn grew by ~5 m² when the new zone was added. |
| 15 | ? | 0 |

A one-shot WARNING fires (`[PROTOCOL_NOVEL] event_occured …`) the first time a
given (siid, eiid) combo is seen, or when a known combo carries a new piid.
That makes silent firmware additions impossible to miss.

### 7.5 Fetching the session-summary JSON

Two distinct signed-URL endpoints on the Dreame cloud; the one that works for
this object key is the **interim** endpoint:

```
POST https://eu.iot.dreame.tech:13267/dreame-user-iot/iotfile/getDownloadUrl
body: {"did":"<did>","model":"dreame.mower.g2408","filename":"<obj-key>","region":"eu"}
→ {"code":0, "data":"https://dreame-eu.oss-eu-central-1.aliyuncs.com/iot/tmp/…?Expires=…&Signature=…", "expires_time":"…"}
```

The signed URL is valid for ~1 hour (no auth on the URL itself). `GET` it to
retrieve the full summary JSON (~56 KB for a 3-hour session).

The alternative endpoint `getOss1dDownloadUrl` (also signed) returned 404 —
that bucket is empty; it's for a different object class.

### 7.6 Session-summary JSON schema (as observed 2026-04-18)

```
{
  "start":        <unix>,                 mowing started
  "end":          <unix>,                 mowing ended
  "time":         <int>,                  duration in minutes
  "mode":         <int>,                  mode code (100 seen)
  "areas":        <float>,                m² mowed this session
  "map_area":     <int>,                  m² total mowable (383 on user's lawn)
  "result":       <int>,                  1 = success-ish
  "stop_reason":  <int>,                  -1 = normal end
  "start_mode":   <int>,
  "pre_type":     <int>,
  "md5":          <hex>,                  content hash
  "region_status": [[zone_id, status]...]
  "dock":         [<x>, <y>, <heading>],  dock coords in mower frame (cm)
  "pref":         [<int>...],
  "faults":       [],                     empty on normal completion
  "spot":         [],
  "ai_obstacle":  [],
  "obstacle":     [                        physical obstacles encountered
    {"id": <int>, "type": <int>,
     "data": [[x_cm, y_mm]...]}           polygon vertices
  ],
  "map":          [
    {  id: 1, type: 0, name: "",
       area: <float>, etime: <int>, time: <int>,
       data: [[x, y]...],                  lawn boundary polygon
       track: [[x, y] | [2147483647, 2147483647]...]   mow path; max-int = segment break
    },
    {  id: 101, type: 2,
       description: { type: 2, points: [[x,y]...] }   exclusion zone (4-point polygon)
    }
  ],
  "trajectory":   [
    {  id: [<int>, <int>],
       data: [[x, y]...]                   high-level planning path
    }
  ]
}
```

Coordinates are in the same mower frame as `s1p4` (x in cm, y in mm × some
scale — TBD whether it matches the 0.625 Y-calibration or needs a different
constant here).

### 7.7 Wiring state

| Piece | Status |
|---|---|
| Subscribe to `event_occured` | ✅ `device.py::_handle_event_occured` |
| Log object key at INFO | ✅ `[EVENT] event_occured siid=4 eiid=1 object_name=… area_mowed_m2=… total_lawn_m2=…` |
| Fetch + download the JSON | ✅ `device.py::_fetch_session_summary` — uses `cloud.get_interim_file_url` (the `getDownloadUrl` variant; the persistent `getOss1dDownloadUrl` 404s) |
| Decode JSON → typed dataclasses | ✅ `protocol/session_summary.py::parse_session_summary`, 18 unit tests |
| Expose overlay to camera/live-map | ✅ `live_map.LiveMapState.load_from_session_summary` — lawn polygon, exclusion zones, completed track segments, obstacle polygons, dock position all flow into `extra_state_attributes` automatically |
| Persist to disk | ✅ `session_archive.SessionArchive` — one JSON per session under `<ha_config>/dreame_a2_mower/sessions/`, content-addressed by `summary.md5`, idempotent re-archival |
| Expose archive as HA entity | ✅ `Archived Mowing Sessions` diagnostic sensor (state=count, attrs list recent 20 sessions) |
| Binary-blob map decoder (upstream-style encrypted) | ❌ not applicable to g2408 — superseded by the JSON path |

**Implementation is complete end-to-end.** Every time the mower finishes a session:

1. `event_occured` arrives on MQTT → `_handle_event_occured` parses the event
2. Inline fetch pulls the JSON from the Dreame cloud (signed OSS URL, ~1s)
3. `parse_session_summary` converts it to a `SessionSummary` dataclass
4. `device.latest_session_summary` / `.latest_session_raw` populated
5. `DreameA2LiveMap` picks it up on the next update tick and loads the overlay
6. Camera's `extra_state_attributes` gains `lawn_polygon`, `exclusion_zones`,
   `completed_track`, `obstacle_polygons`, `dock_position`
7. `SessionArchive` writes the raw JSON to disk and updates the index
8. `Archived Mowing Sessions` diagnostic sensor state increments

Off-repo helper `/data/claude/homeassistant/fetch_oss.py` can retrieve any
object key on demand for ad-hoc inspection.

### 7.8 MAP payload top-level keys (alpha.85 empirical dump)

The cloud's MAP.* JSON blob decodes to a single top-level dict.
`[MAP_SCHEMA]` + `[MAP_KEYS]` log lines on g2408 captured 17 keys;
the integration consumes 9 (`boundary, mowingAreas, forbiddenAreas,
md5sum, mapIndex, name, hasBack, merged, totalArea`). The other
8 are documented here with their g2408-observed shapes:

| Key | Shape (g2408) | Semantic |
|---|---|---|
| `forbiddenAreas` | `{dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}…], angle}]…]}` | **Classic exclusion / no-go zones** (red in the Dreame app). Designated Ignore Obstacle zones live in `notObsAreas`, NOT here (corrected 2026-04-27 once cloud sync caught up — initially we thought type=2 was the discriminator, but the *top-level key* is). `id` matches the s2p50 entity id from create / delete events. `shapeType=2` = rotated rectangle (path is the unrotated corners + `angle` is the rotation in degrees). Surfaced as `sensor.exclusion_zones` (state = zone count, attrs.zones = per-zone geometry). |
| `notObsAreas` | same shape as `forbiddenAreas` | **Designated Ignore Obstacle zones** (green in the Dreame app). Confirmed 2026-04-27 after the cloud propagated yesterday's edit: separate top-level key from `forbiddenAreas` despite same payload shape. Sample entry: `id=101, type=10, shapeType=2, path=4 corners, angle=0` (axis-aligned). The integration renders these on the camera map in green via `Area.subtype="ignore"` set in `_build_map_from_cloud_data`. Surfaced as `sensor.designated_ignore_zones`. |
| `spotAreas` | `{dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}…]}]…]}` | **Spots** for the spot-mow command. Confirmed 2026-04-27 after a spot mow had actually run — populated lazily, can take hours to sync. Each entry has `type=3` (matches apk `WorkingMode.SPOT=3` enum) and `shapeType=7` (axis-aligned rectangle, no `angle` field). Sample: 4-corner rectangle `(-360,-5320)..(-3560,-2840)`. Surfaced as `sensor.spot_zones`. |
| `contours` | `{dataType:'Map', value:[[[map_id, ?], {id, type, shapeType, path:[{x,y},…]}]]}` | **Actual lawn outline polyline** (52-point polygon on a ~384 m² lawn). More detailed than the axis-aligned `boundary` rectangle. **Consumed since alpha.91**: drawn on the base-map PNG as a 2-px `WALL` outline in `_build_map_from_cloud_data` so the real grass perimeter is visible over zone fills. |
| `cleanPoints` | `{dataType:'Map', value:[[pt_id, {id, type, shapeType, path:[{x,y}]}]…]}` | **Maintenance Points** — one or more user-pinned markers in the app. Live sample 2026-04-24 has one entry at `(2820, 12760)` mm in cloud frame; user confirmed the app supports multiple per map and the operator picks which one to target when dispatching a maintenance run. **Consumed since alpha.91 (multi-point support since alpha.93)**: `sensor.maintenance_points_count` carries the full list in attributes (each `{id, x_mm, y_mm}`); `sensor.maintenance_point_x_mm` / `_y_mm` show the first point's coords for quick reference. The `dreame_a2_mower.mower_go_to_maintenance_point` service takes an optional `point_id` to select a specific point, or defaults to the first. |
| `cruisePoints` | `{dataType:'Map', value:[]}` on our capture | Patrol/cruise points the mower visits in sequence. Empty when unused. |
| `cut` | `[]` | Always empty on our captures. Purpose unknown — possibly cut-line geometry for zone boundaries. |
| `obstacles` | `{dataType:'Map', value:[]}` | Auto-detected runtime obstacles (typically populated during/after a mow run, not by user drawings). |
| `paths` | `{dataType:'Map', value:[]}` | Historical/planned mow paths. Empty on our captures — may populate during an active mowing session (not verified). |

**`s2p50` ↔ `forbiddenAreas` correlation table** (2026-04-26 captures):

| Action | s2p50 opcode | Effect on `forbiddenAreas` |
|---|---|---|
| Create new ignore zone | `o:234 id=N ids:[]` | New entry added at key N (the firmware-assigned id) |
| Resize existing zone | `o:234 id=N ids:[]` | Existing entry at key N updated with new `path` / `angle` |
| Delete zone | `o:218 id=N ids:[]` | Entry at key N removed |
| Move existing zone | (different opcode pattern, not yet captured) | Likely entry at key N updated with new `path` |

Every saved op trails an `o:201 status:true error:0` completion push that the integration uses as the universal "refetch + rebuild map" trigger.

The uniform `{dataType:'Map', value:[...]}` wrapper suggests a
generic Map-with-entries container — each `value` is a list of
`[key, record]` pairs (like `Map.entries()` in JS, since the
cross-reference note in apk.md called these a serialized JS Map).
For all but `cut` the container is present even when empty.

### 7.4 Diagnostic logging currently enabled

`MAP_TRACE` INFO logs added in `dreame/map.py` at five branch points in
`update()` to trace the fetch decision. Enable at runtime via:

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X POST "http://$HA_HOST:8123/api/services/logger/set_level" \
  -d '{"custom_components.dreame_a2_mower.dreame.map":"debug",
       "custom_components.dreame_a2_mower.dreame.device":"debug",
       "custom_components.dreame_a2_mower.dreame.protocol":"debug"}'
```

Reverts on HA restart.

### 7.5 `[PROTOCOL_NOVEL]` WARNING catalog (for issue reporters)

Everything below logs at WARNING level, exactly **once per process lifetime per
distinct shape**, at HA's default `logger.default: warning` — so they're safe
against log flooding and visible without any extra logger tuning.

| Message prefix | Trigger | What it tells us |
|---|---|---|
| `[PROTOCOL_NOVEL] MQTT message with unfamiliar method=…` | MQTT message arrives with a method other than `properties_changed` or `event_occured` (e.g. `props`, `request`). | Firmware has a verb we don't decode yet. |
| `[PROTOCOL_NOVEL] properties_changed carried an unmapped siid=… piid=…` | Push arrived on an (siid, piid) not in the property mapping and not intercepted by a specific handler. | New field on an existing service — either a new feature or a firmware revision. |
| `[PROTOCOL_NOVEL] event_occured siid=… eiid=… with piids=…` | First occurrence of an (siid, eiid) combo OR known combo with a new piid in the argument list. | New event class, or existing event gained a field (e.g. a new reason code). |
| `[PROTOCOL_NOVEL] s2p2 carried unknown value=…` | `s2p2` push outside the known set `{27, 31, 33, 43, 48, 50, 53, 54, 56, 60, 70, 71, 75}`. | Firmware emitted a state code we don't recognise. See §4.1. |
| `[PROTOCOL_NOVEL] s1p4 short frame len=…` | `s1p4` push with a length other than 8 / 10 / 33. Raw bytes included in the log line. | Firmware emitted a telemetry frame variant we haven't reverse-engineered. The position is still decoded correctly; only the trailing bytes are un-decoded. |

When a user sees any of these, the right action is to open an issue with the
log line quoted verbatim — the raw values in the message are exactly what we
need to extend decoders.

**Not a `[PROTOCOL_NOVEL]` — don't report** (see §1.2 for the full story):

- `Cloud send error 80001 for get_properties/action (attempt X/Y)`
- `Cloud request returned None for get_properties/action (device may be in deep sleep)`

These are the g2408's expected response to cloud-RPC writes. They will repeat
every time the integration tries a write (buttons, services, config changes).
They do not indicate a new firmware issue.

**Observed but not yet mapped** (2026-04-20):

- `s2p66`, `s5p105`, `s5p106`, `s5p107` — already characterised in §2.1.
  These slots log at **DEBUG** with the prefix `[PROTOCOL_OBSERVED]`
  rather than `[PROTOCOL_NOVEL]` so they don't spam WARNING on every
  HA reload (the watchdog's in-memory dedup resets each time the device
  object is reconstructed). Anything outside this allowlist — a
  genuinely unmapped (siid, piid) — still produces the one-shot WARNING.
  If the user wants to confirm cadence or value range for these known-
  quiet slots, raise the integration's log level to DEBUG for
  `custom_components.dreame_a2_mower.dreame.device`.

---

## 8. Known unknowns

See `project_g2408_reverse_eng.md` memory for the full open-items list. The
shorter version here:

- **`s2p2` codes 50/56/70 vs current `StateCode` enum.** Today's
  `properties_g2408.py` maps `50 = SESSION_STARTED`, `56 = RAIN_PROTECTION`,
  `70 = MOWING`, `48 = MOWING_COMPLETE`. Probe runs on 2026-04-30 observed
  `s2p2 = 50` for steady-state mowing (not a one-shot session-start trigger),
  `70` as a ~1 s transient at the CHARGING→MOWING edge (not steady mowing),
  `56` after an emergency-stop auto-return (not water/rain — that's `73`,
  see §3.4 byte[10] bit 1), and `48` as the idle/charging code. Either
  `Property.STATE = (2, 2)` is wrong (the small-int enum on `s2p1` may be
  the real STATE) or `s2p2` is dual-purpose (state + error codes share one
  property). **Audit `coordinator.py` consumption before patching the enum.**
  See §4.1.
- `s2p1` small enum `{1, 2, 5}`: not the state, not the error. Possibly warning
  or mode sub-state.
- `s5p104 / s5p105 / s5p106 / s5p107`: dynamic telemetry values. Surfaced
  as default-disabled raw diagnostic sensors in v1.0.0a11/a20 so values are
  visible during ongoing RE. Observations from 2026-04-29 mow runs:
  `s5p104=7`, `s5p105=1`, `s5p106 ∈ {3, 5, 7, 8}` (transition-correlated),
  `s5p107=177`.
- `s1p4` motion-vector bytes `[10-21]`: velocity hints identified, full decode
  open.
- `s1p50 / s1p51 / s1p52`: empty dicts at session boundaries — may carry data
  in other scenarios. Suppressed in v1.0.0a20 (`_SUPPRESSED_SLOTS` in
  coordinator.py) to silence the per-tick `[NOVEL/property]` warnings while
  the semantics remain unknown.
- `s2p66`: `[379, 1394]` list — first element is total mowable lawn area
  (m²); second element unknown. v1.0.0a22 added a fallback path that pulls
  total lawn area from the session-summary's `map_area` field, since s2p66
  pushes infrequently (probe corpus shows multi-day gaps).
- `s6p1`: scalar int observed `200` during mow start. Possibly a wifi-
  related alternate encoding. Surfaced as `s6p1_raw` diagnostic sensor.
- `s6p2` FRAME_INFO: 4-tuple `[35, 0, True, 2]`, shape suggests
  `[battery_pct, flag, bool, version]` but not verified.

### 8.1 Wire-format gotchas (greenfield decode bugs caught in v1.0.0a18+)

The pre-greenfield integration's apk-decompiled enums carried implicit
assumptions about bare-int wire formats that the actual MQTT pushes
violate. Documented here so re-implementers don't repeat the trap:

- **`s2p56` is a dict, not a bare int.** Wire envelope:
  `{"status": []}` (no task), `{"status": [[1, 0]]}` (running),
  `{"status": [[1, 2]]}` (transitional), `{"status": [[1, 4]]}` (paused-
  pending-resume), `{"status": [[1, 0, 0]]}` (3-element variant on newer
  firmware). The integration extracts `status[0][1]` as the sub-state:
  `0` running, `4` paused, `2` other. `None` ↔ no task. F5's session-
  state machine fires `begin_session` on transition `None → not None`
  and `begin_leg` (recharge resume) on transition `4 → 0`.
- **`s2p50` is an *echo* of the mower's TASK responses.** Greenfield
  treats this slot as `_SUPPRESSED_SLOTS` (no NOVEL warnings, no field
  binding) because it duplicates the action surface we already publish.
  The mower re-broadcasts the TASK envelope with `{'d': {...}, 't':'TASK'}`
  shape — same shape as outbound, useful for protocol-RE but noise for
  the integration's state pipeline.
- **`s2p66` first element survives as float on the wire.** The decoder
  in `mower/property_mapping.py` casts `float(v[0])` to handle minor
  cloud-side rounding (e.g., observed `383.5` once after a partial-area
  expansion). The total_lawn_area sensor displays as integer m² but the
  underlying field is `float`.
- **CFG (`s2p51`) sub-payload `time` is an ISO-style dict, not Unix.**
  Observed `{'time': '1777405121', 'tz': 'Europe/Oslo'}` — the integer
  is wrapped in a string and accompanied by an explicit TZ name. The
  `s2p51` parser at `protocol/config_s2p51.py` handles this; documenting
  here so anyone hand-decoding probe output isn't surprised by the
  string-typed Unix timestamp.

### 8.2 Session-summary JSON schema observations (2026-04-29)

Real session-summary JSONs (downloaded from OSS via `event_occured`
siid=4 eiid=1) carry these keys at top level:

```
start, end, time, mode, result, stop_reason, start_mode, pre_type, md5,
areas, map_area, dock, pref, region_status, faults, spot, ai_obstacle,
obstacle, trajectory, map
```

Inside each `map[]` element, observed sub-keys:

```
track, obstacles, boundary, etime, id, name, time, type
```

The integration's parser (`protocol/session_summary.py`) tolerates
unknown keys, but the schema validator at
`observability/schemas.py:SCHEMA_SESSION_SUMMARY` is updated as new
keys land so the `[NOVEL_KEY/session_summary]` log doesn't false-fire.

### 8.3 s2p2 error code catalog extensions

Additional codes lifted from legacy's apk-decompiled `DreameMowerErrorCode`
(see `mower/error_codes.py:ERROR_CODE_DESCRIPTIONS`):

| Code | Name | Notes |
|---:|---|---|
| 37 | RIGHT_MAGNET | hardware fault |
| 38 | FLOW_ERROR | hardware fault |
| 39 | INFRARED_FAULT | sensor fault |
| 40 | CAMERA_FAULT | sensor fault |
| 41 | STRONG_MAGNET | hardware fault |
| 43 | RTC | clock / battery-backed time |
| 44 | AUTO_KEY_TRIG | unintentional key press |
| 45 | P3V3 | 3.3 V power rail fault |
| 46 | CAMERA_IDLE | informational |
| 47 | TASK_CANCELLED | **status, not error** — scheduled task cancelled |
| 48 | MOWING_COMPLETE | **status, not error** — mow finished cleanly |
| 49 | LDS_BUMPER | bumper / LDS event |
| 50 | (unnamed) | observed during state transitions on 2026-04-29 — apk-decompiled enum has no entry; treat as a status code rather than a fault for now |
| 51 | FILTER_BLOCKED | maintenance |
| 53 | SESSION_STARTING_SCHEDULED | scheduled-start kickoff (see §4.2 row 53) |
| 54 | EDGE | edge-mow fault |
| 56 | LASER (rain protection) | environmental — rain protection active |
| 57 | EDGE_2 | alt edge-fault |
| 58 | ULTRASONIC | sensor fault |
| 59 | NO_GO_ZONE | reached an exclusion zone |
| 61 | ROUTE | navigation fault |
| 62 | ROUTE_2 | alt navigation fault |
| 63 | BLOCKED_2 | obstacle blocking |
| 64 | BLOCKED_3 | obstacle blocking (alt) |
| 65 | RESTRICTED | restricted area |
| 66 | RESTRICTED_2 | restricted area (alt) |
| 67 | RESTRICTED_3 | restricted area (alt 2) |
| 71 | (positioning failed) | SLAM relocation needed |
| 73 | (top cover open) | mechanical |
| 75 | LOW_BATTERY_TURN_OFF | battery-induced shutdown |
| 78 | ROBOT_IN_HIDDEN_ZONE | navigation |
| 117 | STATION_DISCONNECTED | dock comms |

---

## 8.4 `s2p56` `status[0][1]` value catalog (g2408-confirmed)

The s2p56 dict envelope `{"status": [[a, b]]}` carries a `[task_type,
task_state]` pair. We extract `b` (status[0][1]) as `task_state_code`.
Confirmed values from probe captures (2026-04-29, 2026-04-30):

| `b` | meaning | typical sequence |
| --- | --- | --- |
| `0` | running (actively mowing) | session-start writes `[[1,0]]` or `[[2,0]]` |
| `2` | **complete** — mow finished, mower may still be returning to dock | `[[1,0]] → [[1,2]]` is the natural end-of-mow |
| `4` | paused / waiting to resume (recharge boundary) | `[[1,0]] → [[1,4]]` mid-session |
| `None` (status:[]) | fully idle, no active task | sometimes follows `2`, sometimes the mower stays at `2` indefinitely until a new task starts |

The first element `a` (task type) varies — `1` and `2` both observed —
but does not change the state-machine semantics.

**Implication for finalize gate**: a session has ended when
`prev_task_state ∈ {0, 4}` and `new_task_state ∈ {2, None}`. Waiting
for `None` alone is not enough — the mower can stay at `2` for the
whole return-to-dock window without ever flushing to `[]`.

---

## 9. References

- `probe_a2_mqtt.py` — live probe + pretty-printer
- `custom_components/dreame_a2_mower/protocol/telemetry.py` — `s1p4` decoder
- `custom_components/dreame_a2_mower/dreame/map.py` — map-fetch coordinator
- `docs/research/2026-04-17-g2408-property-divergences.md` — property-mapping catalog
- Probe-log samples under `/data/claude/homeassistant/probe_log_*.jsonl` (off-repo)
