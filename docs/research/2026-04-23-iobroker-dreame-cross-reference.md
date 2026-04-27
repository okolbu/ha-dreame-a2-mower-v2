# Cross-reference vs `ioBroker.dreame` (TA2k) — 2026-04-23

Source repo: `https://github.com/TA2k/ioBroker.dreame` cloned to
`/data/claude/homeassistant/ioBroker.dreame/`. Includes a complete
`apk.md` from APK decompilation of the Dreame Smart Life Flutter app
+ React Native plugin bundle. Notes which mower model the analysis
targets: **g2568a** (different family from our **g2408**), so
some byte-layout findings need cross-validation against our
captures before adopting.

This document catalogs what's NEW, what CONFIRMS, what CONTRADICTS
existing `g2408-protocol.md` content, plus action items.

---

## Major new capability — settings via action calls

The single biggest discovery: **everything we documented as
"BT-only" is reachable via an MIoT action call** with a JSON
payload routed by an `m` (mode) + `t` (type) field.

```
action {
  siid: 2,
  aiid: 50,
  in: [{ m: 'g'|'s'|'a'|'r', t: 'CFG'|'PRE'|'CMS'|'OBJ'|...,
         d: {...optional payload...} }]
}
```

Result lands in `result.out[0]`.

### get-config types (`m:'g'`)

| `t` | Returns | Notes |
|---|---|---|
| `CFG` | All settings dict (WRP, DND, BAT, CLS, VOL, LIT, AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE) | One call gets everything. Our `s2p51` properties_changed only fires on user-side changes; `getCFG` is the read API. |
| `DEV` | Device info (SN, MAC, FW) | |
| `NET` | WiFi info | |
| `IOT` | IoT-Verbindungs-Info | |
| `MAPL` | Map list | |
| `MAPI` | Map info for index | |
| `MAPD` | Map data (chunked) | We use the userdata HTTP path; this is an alternative. |
| `DOCK` | Dock pos `{x, y, yaw, connect_status, path_connect, in_region}` | New — gives lawn-connection status of dock! |
| `MISTA` | Current mission status | |
| `MITRC` | Current mission path | New — could be the live path source! |
| `MIHIS` | Mission history | New — alternative to our session_archive iteration. |
| `CMS` | Wear minutes `[blade, brush, robot]` | We have CMS in s2p51 schema; this is the read API. |
| `PIN` | PIN status | |
| `OBS` | Obstacle data | |
| `AIOBS` | AI obstacle data | We have AI_OBSTACLE_REPORT via s2p55 push; this is the read API. |
| `LOCN` | GPS position `{lon, lat}` | New — mower has GPS! |
| `RPET` | Rain protection end time | |
| `PRE` | Mowing prefs per zone | The thing we thought was BT-only |
| `PREI` | Mowing prefs info | |
| `OBJ` | Object fetch with `d:{type:'wifimap'|'3dmap'}` | 3D LiDAR upload trigger |
| `REMOTE` | Remote-control settings | |

### set-config types (`m:'s'`)

| `t` | Payload | Notes |
|---|---|---|
| `WRP` | `{value, time, sen}` | Rain protection, 3 elements (we knew 2) |
| `DND` | `{value, time:[start,end]}` | DND |
| `CLS` | `{value}` | Child lock |
| `BAT` | `{type:'power'|'charging', value}` | Battery |
| `VOL` | `{value}` | Volume |
| `AOP` | `{value}` | AI obstacle avoidance |
| `STUN` | `{value}` | Anti-theft |
| `LIT` | `{value, time, light[4], fill}` | **Headlight settings — new feature** |
| `REC` | `{value, sen, mode, report}` | Camera recording |
| `LANG` | `{type:'text'|'voice', value}` | Language |
| `LOCN` | `{pos}` | Set GPS |
| `PIN` | `{type:'auth'|'update'|'forget', value}` | PIN admin |
| `WINFO` | `{appWeather}` | Weather hint from app |
| `ARM` | `{value}` | Alarm/anti-theft trigger |
| `FDP` | `{value}` | Frost protection |
| `CMS` | `{value:[blade, brush, robot]}` | Reset wear meters |
| `CHECK` | `{mode, status}` | Self-check trigger |
| `PRE` | `{value: PRE_array}` | Set mowing preferences (read-modify-write) |

### action operations (`m:'a'` with `o:OPCODE`)

| `o` | Function | Notes |
|---|---|---|
| 0 | resetControl | Joystick reset |
| 2-7 | start/stop/pause/continue/pauseBack/stopBack control | Joystick control |
| 8 | setOTA | Trigger OTA |
| 9 | findBot | Find My Mower (sound) |
| 10 | uploadMap | Cloud upload |
| 11 | suppressFault | Hide error/warning |
| 12 | lockBot | Lock mower |
| **100** | globalMower | We documented as `o:100` in s2p50 |
| 101 | edgeMower | Edge-mowing-only mode |
| 102 | zoneMower (with `region`) | Zone-specific mowing |
| 103 | spotMower | Spot mowing |
| 104 | planMower | Scheduled run |
| 105 | obstacleMower | |
| 107 | startCruisePoint | Patrol-to-point |
| 108 | startCruiseSide | Patrol along edge |
| 109 | startCleanPoint | Go to clean point |
| **110** | startLearningMap | BUILDING mode start |
| 200 | changeMap | Switch active map |
| 201 | exitBuildMap | Exit BUILDING |
| **204** | editMap | We saw this in s2p50 logs |
| 205 | clearMap | |
| **206** | expandMap | We documented "Expand Lawn" in §4.3 |
| **400** | startBinocular | **Camera-stream start** |
| 401 | takePic | Take photo |
| 503 | cutterBias | Blade calibration |

---

## SIID 2 piid catalog — major corrections

ioBroker apk decode (line refs into Dreame plugin's `index.android.bundle`):

| piid | apk says | Our doc says | Status |
|---|---|---|---|
| 1 | Device Status (1=Working, 2=Standby, ...) | s2p1 small enum {1,2,5} unknown | **CORRECTION**: it's the main status enum |
| 2 | Error Code | s2p2 STATE — values {27, 43, 48, ...} | **CORRECTION**: it's the error code, NOT a state code. Our "state" interpretation is wrong. |
| 50 | Task Execution Info `{d:{o:operation}}` | TASK envelope | Confirmed |
| 51 | Settings Update — triggers `loadSettingData() → getCFG()` | MULTIPLEXED_CONFIG | Confirmed; the value is a hint, the real fetch is via `getCFG` action |
| **52** | **Mowing Preference Update — triggers `loadMowingPreference()`** | We had: empty-dict session-end marker | **CORRECTION**: not a session marker; it's the trigger to re-fetch PRE settings. We were wrong about the "s1p52 + s2p52 brackets a session" hypothesis. |
| 53 | Voice Download Progress (%) | unknown | NEW |
| 54 | 3D Map Progress (%) | LiDAR upload progress 0..100 | Confirmed |
| 55 | AI Obstacle Detection `{obs:[...]}` | AI_OBSTACLE_REPORT | Confirmed |
| 56 | Zone Status `{status:[[id,state],...]}` | STATUS_LIST | Confirmed |
| 57 | Robot Shutdown (5s delay then shutdown) | unknown | NEW |
| 58 | Self-Check Result `{d:{mode,id,result}}` | unknown | NEW |
| 61 | Map Update — triggers `loadMap()` | s6p1 was our map-ready signal | NEW: SIID 2 also has a map-update piid? Or apk model uses different siid layout? |

**Action item**: re-evaluate `s2p1` and `s2p2` interpretations against this. Our doc treats `s2p2` as the state machine (50=session-start, 48=mowing-complete, etc.) but apk says s2p2 is the error code. Either:
- Our g2408 firmware repurposes s2p2 (different from g2568a)
- OR our state-machine reading is the error-code field showing 0/normal codes that we misinterpreted as state values

---

## SIID 1 piid catalog — partial confirmations

| piid | apk says | Our doc | Status |
|---|---|---|---|
| 1 | Heartbeat (20-byte: error[10], battery, seq+state, robot-state-bitfield, working-state, BLE-RSSI, WiFi-RSSI, LTE-RSSI) | HEARTBEAT 20-byte (battery temp low at byte[6]&0x08) | **DIFFERENT LAYOUT**: apk says bytes 1-10 are an error code, our doc has byte[6] as battery-temp-low. Likely g2408-vs-g2568a divergence — needs cross-check. |
| 2 | OTA State | unknown | NEW |
| 3 | OTA Progress | unknown | NEW |
| **4** | Robot Pose — variable lengths **7/10/13/22/33/44** bytes | We have 8/10/33 | **MORE FRAMES**: 7, 13, 22, 44 byte variants exist (different mower models or stages). 33-byte layout differs significantly: apk says bytes 1-6 = pose (12-bit packed), 7-21 = trace deltas, 22-31 = task progress. Our doc has bytes 1-2 = x_cm int16le and 24-25 = distance_deci. **MAJOR DISCREPANCY** — our reading might be for g2408-specific layout. |
| 50 | unknown — empty handler `{}` | UNKNOWN_DICT | Confirmed unknown |
| 51 | **Dock Position Update Trigger** — triggers `loadDockPos()` | session-start pair w/ s1p50 | **CORRECTION**: not a session marker. It's a "dock position changed, re-fetch via `getDockPos`" signal. Our s1p50/s1p51 pair hypothesis needs revisiting. |
| 52 | unknown — empty handler `{}` | task-end flush | Apk doesn't classify as session-end either; just an empty handler. |
| 53 | BLE Connection Status | OBSTACLE_FLAG (bool, obstacle near mower) | **POSSIBLE CORRECTION**: apk says BLE connection state. We have field-verified obstacle behavior. Likely different on g2408 — verify. |

---

## Pose decoder — apk says 12-bit packed, NOT int16_le

Our `protocol/telemetry.py` `decode_s1p4` decodes the 33-byte frame as
plain `int16_le` for x_cm/y_mm. The apk decompilation shows:

```javascript
function parseRobotPose(payload) {
  // payload = bytes 1-6 of the s1p4 frame (after 0xCE)
  var x = payload[2] << 28 | payload[1] << 20 | payload[0] << 12;
  x = x >> 12;  // arithmetic right shift — sign extension
  var y = payload[4] << 24 | payload[3] << 16 | payload[2] << 8;
  y = y >> 12;
  var angle = payload.length > 5 ? payload[5] / 255 * 360 : 0;
  return { x: x, y: y, angle: angle };
}
```

Bytes 0-5 hold 3 packed values: x (24-bit signed), y (24-bit signed),
angle (8-bit, ÷255 × 360 → degrees). **X and Y share byte 2 — bit-packed**.

Coordinates are then `* 10` for map display.

**Implications for our decoder**:
- If g2408 actually uses the same packing, our int16_le decoder has been
  "lucky" — the low 16 bits of the 24-bit packed value happens to equal
  what int16_le produces when the values are small. For larger coords
  the decoder would diverge.
- We've never observed coords beyond ~30 m × 30 m so the issue hasn't
  bitten us, but a lawn larger than ±32 m would expose it.
- Our integration would also be missing an **angle** value for the
  mower icon orientation.

**Action**: write a test: decode the same captured s1p4 bytes both
ways and compare. Cross-check against the cloud-summary's `start`/`end`
pose if it has one. Also check whether the angle byte matches mower
heading observed in app.

---

## Task progress (bytes 22-31) — different schema than ours

apk:
```javascript
function parseRobotTask(payload) {
  var regionId = payload[0];
  var taskId   = payload[1];
  var percent  = payload[3] << 8 | payload[2];           // ÷100 = %
  var total    = payload[6] << 16 | payload[5] << 8 | payload[4]; // ÷100 = m²
  var finish   = payload[9] << 16 | payload[8] << 8 | payload[7]; // ÷100 = m²
  return { regionId, taskId, percent, total, finish };
}
```

Our doc's interpretation of bytes 22-31:
```
[22-23] flags
[24-25] uint16_le distance_deci ÷10 → m
[26-27] uint16_le total_area_cent ÷100 → m²
[28]    static
[29-30] uint16_le area_mowed_cent ÷100 → m²
```

apk's interpretation says bytes 22-31 of the FRAME contain a task
struct of 10 bytes (offset 0..9 within those 10 bytes). Within that
sub-struct:
- byte[0] = regionId
- byte[1] = taskId
- bytes[2-3] = percent ÷100
- bytes[4-6] = total m² × 100 (uint24)
- bytes[7-9] = finish m² × 100 (uint24)

So our `total_area_cent` (bytes 26-27, uint16) might actually be
the *low 2 bytes* of a **uint24** at frame bytes 26-28 → the mower
can report total areas larger than 655 m² with the upper byte that we
discarded. Same for area_mowed at bytes 29-31 (we treat as
uint16+static, apk says uint24).

For our small lawn (300 m²), no observable error. For larger lawns
the upper byte starts to matter.

Also — we don't have **regionId** or **taskId** parsed. These could
help identify which zone / leg / task is currently active.

**Action**: confirm against captures. If the byte layout matches,
extend our decoder to:
- read uint24 instead of uint16+static for the area fields
- expose regionId, taskId, percent

The `percent` field in particular is a **mowing-progress %** that we
don't currently surface — it's what the app shows on the mowing screen.

---

## Cloud MAP payload — schema confirmed

Our `[MAP_SCHEMA]` dump catalogs 17 keys; apk confirms each with
semantics:

| Key | Confirmed semantics |
|---|---|
| `boundary` | `{x1, y1, x2, y2}` (we knew) |
| `mowingAreas.value` | `[[id, {name, path:[{x,y},...]}], ...]` zone polygons |
| `forbiddenAreas.value` | `[[id, {path:[{x,y},...]}], ...]` exclusion polygons |
| `paths` | Connection paths between zones (NEW understanding) |
| `spotAreas` | Spot-mowing zones |
| `cleanPoints` | Maintenance / clean points |
| `cruisePoints` | Patrol points |
| `obstacles.value` | `[[id, {x, y, ...}], ...]` AI obstacles |
| `contours.value` | `[[id, {type, path:[{x,y}]}], ...]` boundary contour polygons |
| `notObsAreas` | Zones where obstacle detection is suppressed |
| `cut`, `merged`, `mapIndex`, `hasBack` | Map metadata |
| `md5sum`, `totalArea`, `name` | Self-explanatory |

This validates everything in our cloud-map RE work. No surprises.

## M_PATH — separate userData key for the live path

We didn't know about this. The mowing path is in a **separate**
`M_PATH.0..N + M_PATH.info` userData blob, not in `MAP.*`:

- Array of `[x, y]` pairs or `null` (segment delimiters)
- Sentinel `[32767, -32768]` = path break
- Coordinates are ~10× smaller than MAP coords (apply `*10` for
  map-frame projection)

**Action**: add `M_PATH` parsing to our cloud-map fetch path so we
can hydrate the live trail from the cloud after a fresh in-progress
session is created (e.g. boot mid-mow with no in_progress.json yet).
Currently our trail layer only has telemetry-captured points; the
cloud's M_PATH would be a much richer source.

---

## PRE settings array — schema captured

The big one. PRE is a 10-element array sent via
`{m:'s', t:'PRE', d:{value: pre_array}}`:

```
PRE = [zone, mode, height_mm, obstacle_mm, coverage%,
       direction_change, adaptive, ?, edge_detection, auto_edge]
```

Field meanings:
- PRE[0] = zone id (which zone these settings apply to)
- PRE[1] = `mode`: 0=Standard, 1=Efficient (our **Mowing Efficiency**)
- PRE[2] = `height_mm` (our **Mowing Height**)
- PRE[3] = `obstacle_mm` (our **Obstacle Avoidance Distance**)
- PRE[4] = `coverage%` (NEW — we didn't have this)
- PRE[5] = `direction_change` 0=auto, 1=off (our **Mowing Direction**)
- PRE[6] = `adaptive` (NEW)
- PRE[7] = unknown — could be EdgeMaster / Safe Edge Mowing
- PRE[8] = `edge_detection` (separate from edge_mowing — NEW)
- PRE[9] = `auto_edge` / edge_mowing (our **Edge Mowing**)

**Read pattern** (read-modify-write):
1. `getCFG` → returns `result.d.PRE` array
2. Modify desired index
3. `setPRE` with the modified array

**Action**: this unblocks ALL the "BT-only" entries we documented as
inaccessible. Implementation ladder:
1. Add `getCFG` action call to coordinator at startup → populate read-only sensors for cutting-height, mow-mode, edge-mowing, etc.
2. Add Number / Switch entities for write-back via setPRE.

This is the highest-impact-per-LOC change in the entire review.

---

## Settings (CFG) — full documented defaults

apk plugin defaults (line L182958):

| Key | Default | Schema |
|---|---|---|
| WRP | `[1, 8, 0]` | Rain Protection: `[enabled, wait_hours, sensitivity]` (we had 2; the 3rd is new) |
| DND | `[0, 1200, 480]` | DND: `[enabled, start_min, end_min]` |
| CLS | `0` | Child lock |
| BAT | `[15, 100, 1, 0, 1080, 480]` | `[return%, max%, charge_en, ?, start_min, end_min]` (the `?` at index 3 is our `unknown_flag`) |
| LOW | `[0, 1200, 480]` | Low-speed night |
| VOL | `80` | Volume 0-100 |
| LIT | `[0, 480, 1200, 1, 1, 1, 1]` | **Headlight 4 lights** (we had no concept of this) |
| AOP | `0` | AI obstacle |
| REC | `[0, 1, 0, 0, 0, 0, 0, 0]` | Camera (8-element — we had AI Obstacle Photos toggle only) |
| STUN | `0` | Anti-theft |
| ATA | `[0, 0, 0]` | **Auto Task Adjustment** (NEW concept) |
| PATH | `1` | **Path display mode** (new — what does this control?) |
| WRF | `false` | **Weather Forecast Reference** (new) |
| PROT | `0` | **Protection Mode** (new — different from Frost/Rain) |
| CMS | `[blade_min, brush_min, robot_min]` | Wear minutes (max 6000 / 30000 / 3600) |

**Action**: many of these settings are new entity opportunities once
we wire `getCFG` and the corresponding setters.

---

## Action items summary (priority-ordered)

### Immediate (high value, low risk)

1. **Implement `getCFG` action call at coordinator init** — populates state for all settings (PRE included), no behavior change, just additional read-only sensors.
2. **Cross-validate s1p4 pose decode** — write a test that decodes the same captured frame both ways (current int16_le vs apk's 12-bit packed) and compares against expected positions from cloud summary. If divergence found, switch to apk's algorithm.
3. **Reinterpret s2p52** — remove our "session-end marker" hypothesis from the protocol doc; it's a **mowing-preference-changed trigger** that prompts re-fetch via getCFG. Update the area-counter blade-discriminator finding remains correct.
4. **Reinterpret s1p51** — it's a **dock-position-update trigger**, not a session-start marker. Update protocol doc §4.7.
5. **Reinterpret s2p1 / s2p2** — apk says 1=Working/Status enum, 2=Error code. Our `s2p2` "state machine" interpretation may be wrong — those values may be error codes or sub-state of s2p1. Verify against captures.

### Medium-term (new features)

6. **Add Number/Switch entities for PRE settings** — cutting height, mow mode, direction change, edge mowing, edge detection. Read via `getCFG`, write via `{m:'s', t:'PRE', d:{value: pre_array}}`.
7. **Add HEADLIGHT entity group** (LIT settings) — enable/disable + time range + 4 light controls.
8. **Add CMS wear-meter sensors** — blade %, brush %, robot maintenance % from `getCFG.CMS`.
9. **Add `s1p4` task fields** — regionId, taskId, percent (mowing progress %), and uint24 area decoding.
10. **Add `getDockPos` integration** — surface dock connection status + yaw.

### Long-term (deeper RE)

11. **Cross-check pose decoder on lawn >32m** — confirm whether int16_le has been "lucky" for us or actually correct on g2408 firmware.
12. **Implement M_PATH userData fetch** — alternate path source for boot-mid-mow restoration when in_progress.json is empty.
13. **Document additional `s2p` properties** (52-61): 53=Voice DL progress, 57=Robot Shutdown, 58=Self-Check, 61=Map Update — wire to entities or at least suppress PROTOCOL_NOVEL warnings.
14. **Action 503 `cutterBias`** — blade calibration; investigate UX (button entity with confirmation).
15. **Action 11 `suppressFault`** — could be a "clear warning" button.

### Notes / caveats

- `apk.md` analyses the **g2568a** firmware — not the g2408 we
  target. Layout details (especially binary frames) need
  cross-validation. The semantic findings (action call routing,
  CFG keys, action opcodes) are likely portable since the
  React Native plugin is shared across mowers.
- Our existing **g2408 area-counter discriminator** (alpha.73)
  is unaffected — apk doesn't address phase byte semantics.

---

## File pointers in the ioBroker repo

- `apk.md` — the decompilation summary
- `lib/dreame.js` — vacuum-only utility
- `main.js`:
  - `loadMowerSettings` — getCFG call + key parsing (line ~3012)
  - `sendMowerCommand` — action wrapper (line ~2994)
  - `getMowerMap` — userData HTTP fetch + MAP/M_PATH parsing (line ~2448)
  - PRE state definitions (line ~862)
  - PRE setter dispatch (line ~3533)
- `README.md` §"Mower (A2, A2 1200, ...)" — user-facing entity list
