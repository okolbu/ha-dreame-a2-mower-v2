# Cross-check: mova-mower (A1, v1.8.5) vs our A2 inventory — 2026-05-25

**Status: PROPOSAL.** Nothing here is applied to `inventory.yaml` /
`entity-inventory.yaml` yet. It is a validation pass against the updated
`OLD/alternatives_archive_2026-05-05/dreame-mova-mower` (manifest v1.8.5;
`device.py`/`sensor.py` refreshed 2026-05-25).

## Reading rules (important)

- That codebase is **partially vacuum-derived and primarily Dreame A1**; we are
  **A2 (g2408)**. So:
  - **High value-overlap → likely shared.** Where their table matches our
    wire-verified values, treat as corroboration.
  - **Divergence from our wire-verified findings → keep ours.** Many of their
    codes are unremapped vacuum lineage (their own `DreameMowerErrorCode`
    docstring says so).
  - **Their extra codes we've never seen → candidates only**, never adopt
    without an A2 wire/app observation.

---

## 1. s2p1 STATE (`DreameMowerState`) — re-opens our `4` call

Their enum is larger than ours and lists **`4 = ERROR`**. This means our
2026-05-25 inventory edit `4 = "Paused"` (taken from the A2 Flutter asset
`common_mower_protocol.json`) was **premature** and should be walked back.

| value | mova A1 | our inventory | verdict |
|---|---|---|---|
| 1,2,3,5,6,11,13,14 | MOWING/IDLE/PAUSED/RETURNING/CHARGING/BUILDING/CHARGING_COMPLETED/UPGRADING | same | ✅ shared |
| **4** | **ERROR** | "Paused" (added 2026-05-25, app asset) | ⚠️ **CONTESTED** |
| 16 | STATION_RESET | "Battery Temp Hold" (apk + 5× cold-morning confirms) | keep **ours** (A2-confirmed) |
| 15,23,24,25,26,27,29,30,97,98,99 | CLEAN_SUMMON/REMOTE_CONTROL/SMART_CHARGING/SECOND_CLEANING/HUMAN_FOLLOWING/SPOT_CLEANING/WAITING_FOR_TASK/STATION_CLEANING/SHORTCUT/MONITORING/MONITORING_PAUSED | absent | candidates (vacuum-lineage; SECOND/SPOT/STATION_CLEANING are vacuum concepts → unlikely on a mower) |

**On `4`:** three signals now disagree —
- A2 Flutter asset: `4 = Paused` (but that table is internally inconsistent:
  `3` = "Working" en / 暂停 zh).
- A1 vacuum code: `4 = ERROR`.
- A2 behaviour 2026-05-25 12:32: s2p1 held `4` for exactly 1 h then auto-resumed
  to `1` (MOWING), and the app pushed **"Failed to start the task. Please
  retry."** — that reads as an error/fault-hold awaiting the hourly retry, not a
  user pause.

**Proposed:** change inventory s2p1 `4` from `"Paused"` to a **contested**
note, leaning error-hold:
`4: "Error / fault-hold (CONTESTED — app display 'Paused' vs A1 'Error'; 12:32 'failed to start, retry' + 1 h auto-recover behaviour favours error-hold)"`,
status `partial`. Do **not** add the extra mova STATE values.

---

## 2. s2p2 error/fault (`DreameMowerErrorCode`) — overlaps confirm, divergences keep ours

Their docstring admits the table is vacuum-origin with only a few
community-`[MOWER]` remaps. Cross-check vs our wire/app-verified codes:

**Confirms ours (adopt confidence):**
- `31 = DOCK_RETURN_FAILED [MOWER]` ✅ (ours: "Failed to return to station")
- `48 = MOWING_COMPLETE [MOWER]` ✅
- `75 = LOW_BATTERY_TURN_OFF`, `78 = ROBOT_IN_HIDDEN_ZONE`, `117 = STATION_DISCONNECTED` ✅

**Diverges — keep OURS (A2 wire/app-verified):**
| code | mova A1 | ours (verified) | note |
|---|---|---|---|
| 28 | CHARGE_NO_ELECTRIC | blades severely worn (wear%-gated) | "undock/relocate marker (14/14)" DEBUNKED 2026-05-30 — biased single-log sample; see inventory § s2p2 retraction |
| 20 | BATTERY_LOW | NOT battery (fired at 95 %) | A2 wire-verified |
| 24 | CAMERA_OCCLUSION | "Battery low" (apk FaultIndex) | both unverified-on-A2 → **flag contested**, don't trust either |
| 56 | LASER | rain/bad-weather (app-verified) | keep ours |
| 63 | BLOCKED_2 | schedule_cancelled_busy (app 12:32) | keep ours; **note** mova uses `47 = TASK_CANCELLED [MOWER]` for cancellation — A1 may carry cancel on 47, A2 on 63 |

**Candidate codes we don't have (A2-unconfirmed; mostly vacuum):**
`2 TRAPPED [MOWER]`, `19 ROBOT_LOST [MOWER]`, `22 BATTERY_PERCENTAGE`,
`29 BATTERY_FAULT`, `47 TASK_CANCELLED [MOWER]`, `49 LDS_BUMPER`,
`51 FILTER_BLOCKED`(vacuum), `58 ULTRASONIC`, `59 NO_GO_ZONE`,
`61/62 ROUTE`, `64–67 RESTRICTED`, `122 UNKNOWN_WARNING_2`,
`123 SELF_TEST_FAILED`, `1000 RETURN_TO_CHARGE_FAILED`. Worth watching for in
the probe corpus; **do not** import wholesale.

Side note: this corroborates the open TODO "reconcile mower/error_codes.py" —
our `63="Blocked"` and `54="Edge fault"` are vacuum carry-overs that conflict
with verified meanings.

---

## 3. CHARGING_STATUS (s3p2) — ours wins

| value | mova A1 | ours | observed A2 |
|---|---|---|---|
| 0 | (absent) | NOT_CHARGING | mowing/undocked = 0 ✓ |
| 1 | CHARGING | CHARGING | charging = 1 ✓ |
| 2 | NOT_CHARGING | CHARGED | docked+full shadow read = 2 ✓ |
| 3/5 | COMPLETED / RETURN_TO_CHARGE | — | unseen |

Our enum fits every A2 observation (incl. the 2026-05-25 shadow read `3.2=2`
while docked+full and `1→0` on undock); mova's `2=NOT_CHARGING` does not. **Keep
ours.**

---

## 4. API / MQTT endpoints — full corroboration, no new endpoints

Decoding mova's `DREAME_STRINGS` (gzip+b64) yields the same string table our
`cloud_client` uses, confirming the surface we reverse-engineered this session:

- Host/port `…iot.dreame.tech:13267`; salt `RAylYC%fmSKp7%Tq`; Basic auth
  `dreame_appv1:…`; `platform=IOS&grant_type=password|refresh_token`.
- `POST /dreame-auth/oauth/token`
- `dreame-user-iot/iotuserbind/device/{listV2,info}`
- `dreame-user-iot/iotstatus/devOTCInfo` (and `iotstatus/props` — our shadow read)
- `dreame-user-iot/iotuserdata` (setDeviceData — write)
- `dreame-iot-com/device/sendCommand` (the **relay** — our 80001 source)
- `iotfile` (file/OSS fetch)

No endpoints beyond what we already found. This independently confirms the
80001-resilient read (`iotstatus`) vs relay (`sendCommand`) split.

---

## 5. Property map / entities — vacuum-heavy; a few slots worth checking on A2

`DreameMowerProperty` has 137 (siid,piid) entries; siid 2/3 overlap us, siid 4
is a large vacuum-flavoured grab-bag, siid 5 = DND, siid 6 = map. Most entities
(sensor 35 / switch 30 / select 5 / number 1 / button 10 / time 4) are vacuum
features (child lock, Y-clean, AI/pet detection, auto-empty, dust collection)
that don't apply to the g2408.

**Slots worth a deliberate A2 probe** (plausibly real, we don't fully expose):
- `4.18 FAULTS`, `4.20 RELOCATION_STATUS` — we noted s4p20 never fired on the
  A2 off-dock path; mova confirms the slot exists (capture during a relocate).
- `4.47 SCHEDULED_CLEAN`, `4.63 CLEANING_PROGRESS`, `4.56/4.57 message prompts`,
  `4.11 RESUME_CLEANING`, `4.8 CLEANING_START_TIME`.

Not proposing entity changes — flagging these as probe targets only.

---

## Proposed inventory edits (for later, if accepted)

1. **s2p1 `4`**: `"Paused"` → contested error-hold note (§1), status `partial`.
   *(walks back the 2026-05-25 over-assertion)*
2. **s2p2 `24`**: annotate as contested (apk "Battery low" vs mova
   "CAMERA_OCCLUSION") — neither A2-verified.
3. **s2p2**: add an `open_question` — does A2 carry task-cancel on `47` (mova
   `[MOWER]`) in addition to the verified `63` schedule-cancel?
4. Leave all other A2 wire/app-verified s2p2 codes as-is (mova diverges but ours
   are verified).
5. error_codes.py reconciliation TODO already filed — mova corroborates it.

No change to API or charging-status entries — mova corroborates ours.
