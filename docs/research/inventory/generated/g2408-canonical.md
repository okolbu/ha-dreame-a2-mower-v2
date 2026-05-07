<!-- DO NOT EDIT BY HAND. Source: docs/research/inventory/inventory.yaml. Regenerate via `python tools/inventory_gen.py`. -->

# g2408 Protocol — Canonical Reference

## Properties

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1 | heartbeat | 20-byte blob | WIRED |  |
| s1p2 | ota_state | int (enum) | APK-KNOWN |  |
| s1p3 | ota_progress | int 0..100 | APK-KNOWN | % (×1.0) |
| s1p4 | mowing_telemetry | 33-byte / 8-byte / 10-byte variants | WIRED |  |
| s1p5 | hardware_serial | string (e.g., "G2408053AEE0006232") | WIRED | string (×1.0) |
| s1p50 | state_change_ping | empty_dict | WIRED |  |
| s1p51 | dock_position_update_trigger | empty_dict | WIRED |  |
| s1p52 | task_end_flush | empty_dict | WIRED |  |
| s1p53 | obstacle_flag | bool | WIRED |  |
| s2p1 | mode | int (enum) | WIRED |  |
| s2p2 | error_code | int (state/error code) | WIRED |  |
| s2p50 | task_envelope | TASK envelope; multiple op-code classes | WIRED |  |
| s2p51 | multiplexed_config | shape varies by setting | WIRED |  |
| s2p52 | preference_update_trigger | empty_dict | WIRED |  |
| s2p53 | voice_download_progress | int 0..100 | SEEN-UNDECODED |  |
| s2p54 | lidar_upload_progress | int 0..100 | WIRED | % (×1.0) |
| s2p55 | ai_obstacle_report | list | SEEN-UNDECODED |  |
| s2p56 | task_state | {status: list of [task_type, sub_state] pairs} | WIRED |  |
| s2p57 | robot_shutdown_trigger | dict (shutdown signal) | APK-KNOWN |  |
| s2p58 | self_check_result | dict {d: {mode, id, result}} | APK-KNOWN |  |
| s2p61 | map_update_trigger | dict (map update signal) | APK-KNOWN |  |
| s2p62 | task_progress_flag | int | SEEN-UNDECODED |  |
| s2p65 | slam_task_label | string | WIRED |  |
| s2p66 | lawn_area_snapshot | list[float, int] | WIRED | m² (×1.0) |
| s3p1 | battery_level | int 0..100 | WIRED | % (×1.0) |
| s3p2 | charging_status | int (enum) | WIRED |  |
| s4p21 | obstacle_avoidance | int (enum) | UPSTREAM-KNOWN |  |
| s4p22 | ai_detection | int (enum) | UPSTREAM-KNOWN |  |
| s4p23 | cleaning_mode | int (enum) | UPSTREAM-KNOWN |  |
| s4p26 | customized_cleaning | string (JSON) | UPSTREAM-KNOWN |  |
| s4p27 | child_lock | bool (0/1) | UPSTREAM-KNOWN |  |
| s4p44 | cruise_type | int (enum) | UPSTREAM-KNOWN |  |
| s4p47 | scheduled_clean | string (JSON) | UPSTREAM-KNOWN |  |
| s4p49 | intelligent_recognition | int (enum / bool) | UPSTREAM-KNOWN |  |
| s4p59 | pet_detective | int (enum / bool) | UPSTREAM-KNOWN |  |
| s4p68 | device_snapshot_bundle | list of {code, did, piid, siid, value} property snapshots — bulk multi-property read, NOT a single-value property | UNCLASSIFIED |  |
| s4p83 | device_capability | int (bitmask) | UPSTREAM-KNOWN |  |
| s5p104 | slam_relocate_counter | int | WIRED |  |
| s5p105 | s5p105_raw | int (small enum) | WIRED |  |
| s5p106 | s5p106_raw | int | WIRED |  |
| s5p107 | energy_index | int | WIRED | energy_index (×1.0) |
| s5p108 | s5p108_raw | int | SEEN-UNDECODED |  |
| s6p1 | map_data_signal | int {200, 300} | WIRED |  |
| s6p2 | frame_info | list[int, int, bool, int] len 4 | WIRED |  |
| s6p3 | wifi_signal_push | list[bool, int] | WIRED |  |
| s6p117 | dock_nav_state | int | WIRED |  |
| s99p20 | lidar_object_name | string (OSS object key) | WIRED |  |

### s1p1 — `heartbeat`

Mower-alive ping sent every ~45 seconds regardless of state, plus extra
emissions during state transitions. 0xCE delimiters at bytes [0] and [19].

Key decoded bytes (partial — full catalog in heartbeat_bytes section, Task 9):
- [1] & 0x02: Drop / Robot tilted
- [1] & 0x01: Bumper hit (no corresponding s2p2 transition)
- [2] & 0x02: Lift / Robot lifted
- [3] & 0x80: Lift lockout / PIN required
- [6] & 0x08: Charging paused — battery temperature too low
- [10] & 0x80: Latched low-temp event flag (set since last power-cycle)
- [10] & 0x02: One-shot active-alert flag (self-clears 30–90 s)
- [17]: WiFi RSSI as signed byte (b if b<128 else b−256)

Per-byte decode lives in the heartbeat_bytes section (Task 9).
Confirmed 2026-04-17 through 2026-05-05 across the full probe corpus.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1`

### s1p2 — `ota_state`

OTA firmware-update state. Apk-documented via OTAState enum (L57342):
0=UNDEFINED, 1=IDLE, 2=UPGRADING, 3=UPGRADE_SUCCESS, 4=UPGRADE_FAILED,
5=CANNOT_UPGRADE. Apk subscribes to this property at L181402-181404 and
surfaces it in the OTA progress UI. Not observed in g2408 probe corpus
(no firmware update was captured during the probe period).

Expect to see transitions 1→2→3 (or 1→2→4) during the next OTA event.
Should fire before/after s1p3 (OTA progress) pushes.

**Open questions:**
- Capture s1p2 transitions during the next firmware update to confirm value semantics.
- Does g2408 emit CANNOT_UPGRADE (5) when battery is too low for OTA?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:2`

### s1p3 — `ota_progress`

OTA firmware-update download/install progress counter, 0..100. Apk-
documented at L181422-181424; surfaces as the progress bar in the
OTA update UI. Not observed in g2408 probe corpus (no firmware update
was captured during the probe period).

Expected behaviour: pushes incrementally from 0 to 100 while s1p2 is
UPGRADING (2). A jump to 100 followed by s1p2 → UPGRADE_SUCCESS (3)
marks the completed update.

**Open questions:**
- Capture s1p3 during the next firmware update to confirm 0..100 range and cadence.

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:3`

### s1p4 — `mowing_telemetry`

Position, phase, area, and distance telemetry. Three frame lengths observed
on g2408: 33-byte (full telemetry during active mowing), 8-byte (beacon
variant during idle/docked, start-of-leg preamble, BUILDING sessions, and
post-FTRTS dock-navigation), 10-byte (one per BUILDING session at zone-save
moment).

All variants share 0xCE delimiters and a common X/Y position at bytes [1-5]
(20-bit signed packed decode, both axes in map-scale mm). X-axis confirmed
via fixture; Y-axis decode corrected in alpha.98 (prior code had a 16× Y
overshoot compensated by scattered 0.625 factors, all removed).

The 33-byte frame additionally carries: sequence (bytes [6-7]), phase_raw
(byte [8] — index into firmware's per-zone task plan, NOT a mowing/transit
enum), motion vectors / path history (bytes [10-21]), distance_deci
(bytes [24-25], ÷10 → m), total_area_cent (bytes [26-27], ÷100 → m²),
area_mowed_cent (bytes [29-30], ÷100 → m²). area_mowed_cent advancing while
position is stationary is the blades-on detector.

Per-byte decode lives in telemetry_fields and telemetry_variants sections
(Task 10). Confirmed 2026-04-17 through 2026-05-05.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:4`

### s1p5 — `hardware_serial`

Hardware serial as printed on the device chassis. Fetched on demand
via cloud RPC `get_properties(siid=1, piid=5)`; never pushed
spontaneously via MQTT (it never changes after manufacturing).

Confirmed across all 4 cloud dumps captured 2026-05-04 → 2026-05-06:
consistent value `"G2408053AEE0006232"`. The integration's
coordinator handles the field at `coordinator.py:409` —
`_apply_property_to_state` checks for (1, 5) and writes the string
to `MowerState.hardware_serial` if non-empty. Surfaced as
`sensor.hardware_serial` (sensor.py:516) plus the `device-info
"Serial Number"` field. Distinct from `cfg_individual.DEV.sn`
which is the authoritative source preferred by the coordinator's
`_refresh_dev` path; s1p5 is the fallback when DEV's RPC fails.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:409`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s1p50 — `state_change_ping`

Lightweight "something changed, consider re-fetching" ping. No payload.
Fires at session start (paired with s1p51), at BUILDING zone-save (multiple
pulses in the same second), at zone/exclusion edits (paired with s2p50
o=215), and at maintenance-point save (two pulses 1 s apart, no other
context).

A standalone s1p50 (no s1p51, no s2p50) is the signal to re-fetch whatever
the integration caches from the cloud — in practice, the MAP.* dataset.

See docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes for the full role catalogue and
the correction note (2026-04-23) on earlier session-boundary hypotheses.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:50`

### s1p51 — `dock_position_update_trigger`

Dock-position-update trigger per apk decompilation. Fires when the dock pose
changes; consumer should re-fetch via the routed getDockPos action (siid:2
aiid:50 m:'g' t:'DOCK'). Also fires co-incident with s1p50 at every mowing
session start (the firmware emits both in the same second when a run begins),
but the primary semantic is dock-pose change, not session boundary.

2026-04-23 correction: earlier hypothesis called this a "session-start
companion to s1p50 based on observed co-occurrence". Co-occurrence is real
but the apk specifies dock-pose change as the primary trigger.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:51`

### s1p52 — `task_end_flush`

Task-ended flush/commit ping. No payload. Fires at session complete
(s2p2 = 48) on both natural end (12:33:09 on 2026-04-20) and user-cancel
(18:06:19). Does not fire at BUILDING end. Also fires immediately before
the cloud event_occured siid=4 eiid=1 session-summary push (2026-04-22
16:35:17).

2026-04-23 correction: the earlier "s1p52 + s2p52 bracket session ends"
hypothesis is wrong per apk decompilation. s2p52's primary semantic is
mowing-preference-update trigger, not session-end. The apparent co-occurrence
at session boundaries is firmware bookkeeping (re-emitting prefs as part of
teardown).

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:52`

### s1p53 — `obstacle_flag`

Set True when the mower detects an obstacle, person, or animal during mowing.
Never sent False automatically — the HA entity must auto-clear after ~30 s
of no refresh, otherwise it latches indefinitely.

Apk names this slot "BLE Connection Status" but g2408 behaviour is
obstacle-detection: 26 triggers observed in ~15 min near an exclusion zone,
mean duration ~6.6 s. Cleared to False at 21:04:46 on 2026-04-18 as a
side-effect of a state transition, not by an obstacle-clear event.

Separate from human-presence detection, which goes through the Dreame cloud
push-notification service directly and is not observable via MQTT.

Note: apk name "BLE Connection Status" does not match g2408 wire behaviour.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:61`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:53`

### s2p1 — `mode`

Mower mode/activity enum per apk decompilation. Previously hypothesized as
a mystery enum {1, 2, 5}; apk reveals the full mapping. Note the upstream
dreame-mova-mower mapping swaps (2,1) and (2,2) vs g2408 actual — the g2408
overlay in types.py swaps them back.

Value 16 is labelled STATION_RESET in the legacy upstream enum (still used in
lawn_mower.py for now); the actual semantics are "docked, refusing to charge
because battery is below safe-charge temperature" — confirmed 2026-04-26
across 5 occurrences during cold morning hours, every entry coincident with
s1p1 byte[6]=0x08.

Value 3 (PAUSED) confirmed in probe corpus: 5 observations in two files
(2026-04-17 and 2026-04-22/28/29), always co-incident with s2p56
status=[[1,4]]. Previously thought to fold into mode 1.

Value 11 (BUILDING) confirmed 2026-04-20 17:00:09 when user triggered
"Expand Lawn" from the Dreame app.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:1`

### s2p2 — `error_code`

State and error code per apk decompilation. Previously misread as a state
machine with values {27, 43, 48, ...}; apk reveals it carries fault indices
catalogued in apk FaultIndex (e.g. 0=HANGING, 24=BATTERY_LOW, 27=HUMAN_DETECTED,
56=BAD_WEATHER, 73=TOP_COVER_OPEN).

Key values observed on g2408: 27=idle, 31=Failed to return to station,
33=Failure transition, 43=Battery temperature low charging stopped,
48=Mowing complete, 50=Manual session start, 53=Scheduled session start,
54=Returning, 56=Rain protection activated, 60=Frost-protection-suppressed,
70=Mowing, 71=Positioning failed, 75=Arrived at Maintenance Point.

See state_codes section for full value table (Task 12). Anything outside the
known set produces a one-shot [PROTOCOL_NOVEL] s2p2 WARNING.

Note: upstream dreame-mova-mower mapping treats (2,2) as ERROR and (2,1) as
STATE — reversed vs g2408. The g2408 overlay corrects this.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:62`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:2`

### s2p50 — `task_envelope`

TASK envelope — multiple operation classes sharing this slot. Two major
shapes observed:

1. Flat fields (session-task metadata, session start): {area_id, exe,
   o:100, region_id:[1], time, t:'TASK'}
2. Wrapped map-edit: {d:{exe, o, status, ...}, t:'TASK'}

Confirmed opcode catalog (partial — full catalog in opcodes section, Task 8):
o=100 global mow start, o=101 edge mow, o=102 zone mow, o=103 spot mow,
o=109 task-start failed, o=201 operation completed, o=204 map-edit request,
o=215 map-edit confirm (carries id and ids), o=218 delete, o=234 save zone
geometry, o=401 takePic, o=-1 error abort, o=3 task cancelled, o=6 explicit
Recharge.

The cloud occasionally drops s2p50 deliveries under load. The integration
triggers a MAP rebuild on o=215 or o=201 with status:true && error:0.
The s2p50 echo is NOT a faithful copy of the input (firmware canonicalizes
payloads). Detailed opcode catalog lives in opcodes section (Task 8).

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:50`

### s2p51 — `multiplexed_config`

All "More Settings" toggles in the Dreame app that travel via cloud share
this single property. The payload shape discriminates the setting. Confirmed
shapes include: {end, start, value} for DND; {value: [enabled, start, end]}
for Low-Speed Nighttime; {value: 0|1} for single-toggle settings (Child
Lock, Frost Protection, Auto Recharge Standby, AI Obstacle Photos,
Navigation Path); {value: [b,b,b,b]} for 4-bool settings (MSG_ALERT /
VOICE — wire-ambiguous, disambiguated via getCFG diff); {value: [6-element
list]} for Charging config; {value: [8-element list]} for LED Period;
{value: [3-element list]} for Anti-Theft; {value: [9-element list]} for
Human Presence Alert; {text, voice} for Language; {time, tz} for timestamp
heartbeat.

Also overloads to a consumables runtime counter shape {value: [blade_min,
brush_min, robot_min, link_module_min]} — discriminated from the 4-bool
shape by any element > 1 or < 0.

Detail in s2p51_shapes section (Task 11). Confirmed 2026-04-17 through
2026-04-30 via live toggle testing.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:51`

### s2p52 — `preference_update_trigger`

Mowing-preference-update trigger per apk decompilation. Fires when PRE
settings change; consumer should re-fetch via the routed getCFG action
(siid:2 aiid:50 m:'g' t:'CFG').

2026-04-23 correction: previously hypothesized as a session-end companion
to s1p52 based on observed co-occurrence at session end (16:35:17.786 →
18.031). Per apk, the semantic is preference-change, not session-end. The
firmware fires s2p52 at session end because it re-emits prefs as part of
teardown, not because this is a dedicated session-end signal.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:52`

### s2p53 — `voice_download_progress`

Apk says VOICE_DOWNLOAD_PROGRESS_PCT — progress counter for downloading a
voice pack to the mower. Observed 5 times in the probe corpus but never
pushing meaningful progress on g2408 (values all near 0 or 100 with no
intermediate ticks). No voice-pack download was initiated during the corpus
capture window, so these may be startup-time residue or idle-state pings.

Confirm by triggering a language change from the app while probe is running.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §VOICE_DOWNLOAD_PROGRESS_PCT`

### s2p54 — `lidar_upload_progress`

LiDAR point-cloud upload progress counter, 0..100. Published roughly once
per second while the upload runs. Triggered by the user tapping "View LiDAR
Map" in the Dreame app, provided the current scan differs from the last-
uploaded one (reopening with no scan change is a no-op).

Confirmed 2026-04-20 17:41:58–17:42:28: s2p54 = 0 at upload start, then
10, 16, 21..45, 61, 100. Total wire time: 30 seconds, 2.45 MB PCD.

s99p20 (the OSS object key) arrives BEFORE s2p54 = 100 (at 61% in the
observed capture). The integration keys off s99p20 rather than waiting for
s2p54 = 100.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:54`

### s2p55 — `ai_obstacle_report`

Apk says AI_OBSTACLE_REPORT — a list of AI-camera-detected obstacle events.
Observed 14 times in the probe corpus but always an empty list on g2408.
No AI camera triggers were observed in the user's corpus: the g2408 may
require AOP (AI Obstacle Photos) to be enabled and an actual obstacle to be
encountered, or the AI report may only populate when the Dreame cloud
processes a captured image.

Cannot confirm semantics without a corpus capture that includes an actual
AI detection event.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §AI_OBSTACLE_REPORT`

### s2p56 — `task_state`

Cloud status push — internal task-state ack. Wire envelope: {"status": []}
(no active task), {"status": [[1, 0]]} (running), {"status": [[1, 2]]}
(complete / transitional), {"status": [[1, 4]]} (paused-pending-resume /
recharge boundary). A 3-element variant {"status": [[1, 0, 0]]} observed on
newer firmware.

The integration extracts status[0][1] (the sub-state int) as
task_state_code: 0=running, 4=paused, 2=complete, None=no task.

The session-state machine uses task_state_code for begin_session /
begin_leg / session-end transitions: 0→4→0 is a recharge round-trip;
4→0 triggers begin_leg; prev∈{0,4} and new∈{2,None} means session ended.

Confirmed g2408 sub-state values from 2026-04-29/30 corpus. Note: wire shape
is a dict, not a bare int — a common decode trap for apk-decompiled code.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:56`

### s2p57 — `robot_shutdown_trigger`

Robot shutdown trigger. Apk subscribes at L181482-181512 and dispatches
a 5-second-delay sequence culminating in a firmware shutdown or reboot.
Described in apk as "Robot Shutdown" — fires during OTA reboot or device
power-down cycles. Consumer is expected to wait 5 s then treat the device
as offline.

Never observed in g2408 probe corpus (no OTA event or power-down was
captured during the probe period). Expect to see this during the next
firmware update, immediately before the mower goes offline.

**Open questions:**
- Capture s2p57 push during the next firmware update to confirm payload shape and timing.
- Is this a command echo or a push the device sends spontaneously?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:57`

### s2p58 — `self_check_result`

Self-check / diagnostics result. Apk subscribes at L141634 and L142731;
payload shape is {d: {mode, id, result}}. Triggered by the apk's
setSelfCheck command ({m:'s', t:'CHECK', d:{mode, status}}). The apk
renders these as in-app diagnostic results for each subsystem.

Never observed in g2408 probe corpus. To capture: trigger "Self-Check"
from the Dreame app's Maintenance → Self-Diagnosis menu.

**Open questions:**
- What mode/id/result values does g2408 emit? Trigger Self-Check from Maintenance menu.
- How many s2p58 pushes appear per self-check run (one per subsystem or a summary)?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:58`

### s2p61 — `map_update_trigger`

Map-update trigger. Apk subscribes at L181514-181515 and calls
loadMap() on receipt. Signals that a new map snapshot is available
on the cloud. Similar in spirit to s1p50 (state_change_ping) and
s6p1 (map_data_signal) but a distinct slot targeting the full map
reload path.

Never observed in g2408 probe corpus. May fire after map-building
sessions or when the device uploads a new map version. Distinct from
s6p1 = 300 (which fires at recharge-leg boundaries), this appears to
be the "full map pushed to cloud" notification.

**Open questions:**
- When exactly does s2p61 fire relative to s6p1 and s1p50 in a map-building session?
- Confirm payload shape (empty dict or carries map metadata).

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:61`

### s2p62 — `task_progress_flag`

Apk says task progress flag. Observed 16 times in the probe corpus. Semantic
on g2408 not yet pinned — values and timing have not been correlated with
specific task events in the available captures. Needs a dedicated
toggle-correlation test.

**Open questions:**
- What values appear and when? Cross-correlate with s2p1 and s2p2 transitions.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §task_progress_flag`

### s2p65 — `slam_task_label`

SLAM / nav task-type string. Two values confirmed on g2408:

'TASK_SLAM_RELOCATE' — fires 3× in ~1 second when the mower kicks off a
LiDAR relocalization to re-anchor against the saved map. Paired with s5p104
(SLAM relocate counter = 7) in the same burst. Occurs after the mower wakes
in an unknown position (e.g. manual mode ended outside the known map area).

'TASK_NAV_DOCK' — fires once at the start of an explicit dock-navigation
phase. Confirmed 2026-05-05 across two integration-launched edge runs:
fires when the mower enters the post-FTRTS retry path (not on clean
autonomous returns). Paired with s6p117 = 1 in the same second.

Not seen during clean autonomous returns where s2p1: 5→6 fires directly
without intervening NAV_DOCK.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:92`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s2p66 — `lawn_area_snapshot`

Lawn-size snapshot. First element = total mowable lawn area in m² (matches
event_occured piid 14 from the session-summary exactly). Second element
unknown — decreased by 8 when area grew by 5 m², so not
perimeter-proportional; candidates include blade-hours ×10, unique path
segments, or a total-distance-mown counter.

Observed [379, 1394] on 2026-04-17, [384, 1386] on 2026-04-20 after a
manual "Expand Lawn". Fires at the end of a BUILDING session and probably
periodically during mowing. First element can be float on the wire
(e.g., 383.5 after partial-area expansion) — cast to float before use.

The integration uses the session-summary's map_area field as the primary
source for total_lawn_area_m2, since s2p66 pushes infrequently (multi-day
gaps in probe corpus).

**Open questions:**
- What does the second list element represent? Candidates: blade-hours ×10, path segments, total-distance-mown counter.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:95`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s3p1 — `battery_level`

Battery percentage. Integer 0..100. Pushes on change during mowing and
charging. The primary battery-state signal for the HA integration.
Confirmed across the full probe corpus 2026-04-17 through 2026-05-05.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:57`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 3 piid:1`

### s3p2 — `charging_status`

Charging status enum. On g2408, value 0 means "not charging" (enum offset
vs upstream — upstream mapping expects 1 for not-charging). Confirmed across
the full probe corpus: transitions to 1 when mower docks and charging starts,
drops to 0 when mowing resumes.

Used in the integration as the authoritative "charging started" signal
(s3p2 → 1) to confirm dock arrival, particularly when s2p50 o=6 echo is
unreliable.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:58`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 3 piid:2`

### s4p21 — `obstacle_avoidance`

Obstacle-avoidance mode selector. Upstream mower forks define OBSTACLE_AVOIDANCE
at (4, 21) in DreameMowerPropertyMapping. The legacy integration reads and writes
this property to control AI-obstacle avoidance sensitivity. On g2408 obstacle
behaviour is governed by s2p1 and s2p2, but this property slot may co-exist.

**Open questions:**
- Is s4p21 present on g2408 firmware? Probe with a direct SIID 4 PIID 21 GET to confirm.
- If present, does the enum match the legacy ObstacleAvoidance values (0=disabled, 1=enabled, 2=intensive)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:687)`, `github.com/nicolasglg/dreame-mova-mower (types.py:740)`

### s4p22 — `ai_detection`

AI-based pet/obstacle detection mode. Upstream mower forks define AI_DETECTION
at (4, 22) in DreameMowerPropertyMapping. Controls whether the camera-based AI
detection is active during mowing. On g2408 no camera module has been confirmed;
this slot may be a no-op or absent.

**Open questions:**
- Is s4p22 present on g2408 firmware? g2408 has no confirmed camera module.
- Does s4p22 interact with s4p59 (PET_DETECTIVE)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:688)`, `github.com/nicolasglg/dreame-mova-mower (types.py:741)`

### s4p23 — `cleaning_mode`

Mowing / cleaning mode selector. Upstream mower forks define CLEANING_MODE
at (4, 23). Controls the active mowing behaviour (e.g. edge-only, zone, spot).
On g2408 the equivalent is the task-type sent via the s5a1 action envelope;
this property slot may be a read-back or may not be used.

**Open questions:**
- Is s4p23 present on g2408 firmware? Probe with direct GET to confirm.
- If present, does the enum match the legacy CleaningMode (0=standard, 1=quiet, 2=boost)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:689)`, `github.com/nicolasglg/dreame-mova-mower (types.py:742)`

### s4p26 — `customized_cleaning`

Per-zone customised cleaning settings. Upstream mower forks define
CUSTOMIZED_CLEANING at (4, 26) — carries a JSON blob with per-zone
pass-count and cutting-height overrides. On g2408 these settings are
embedded in the s5a1 task envelope; this property may carry a persisted
read-back of the last settings.

**Open questions:**
- Is s4p26 present on g2408 firmware? Probe with direct GET.
- If present, does the JSON schema match the legacy CustomizedCleaning format?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:691)`, `github.com/nicolasglg/dreame-mova-mower (types.py:744)`

### s4p27 — `child_lock`

Child-lock / panel-lock property. Upstream mower forks define CHILD_LOCK
at (4, 27). On g2408 child-lock is toggled via the cfg_toggle mechanism
(setting key 'CLS') which writes through s2a50 o:8, NOT by directly
writing s4p27. The property slot may still exist as a read-back surface.

**Open questions:**
- Is s4p27 present on g2408 firmware? The greenfield uses cfg CLS not a direct property write.
- If present, does writing s4p27=1 work on g2408, or must the cfg_toggle path be used?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:692)`, `github.com/nicolasglg/dreame-mova-mower (types.py:745)`

### s4p44 — `cruise_type`

Cruise / patrol mode type. Upstream mower forks define CRUISE_TYPE at (4, 44).
Controls whether the mower follows cruise points or a fixed patrol pattern.
The g2408 mower does not expose cruise-point behaviour in current captures;
this slot may be present but unused or not applicable to this model.

**Open questions:**
- Is s4p44 present on g2408 firmware? Cruise functionality not seen in probe corpus.
- Does cruisePoints in the OSS map blob connect to s4p44?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:699)`, `github.com/nicolasglg/dreame-mova-mower (types.py:752)`

### s4p47 — `scheduled_clean`

Schedule configuration property. Upstream mower forks define SCHEDULED_CLEAN
at (4, 47). Carries a JSON blob describing the active mowing schedule(s).
On g2408 scheduling is managed through the s2p50 / cfg mechanism (fields SCH,
SNS, etc.); this s4p47 slot may carry a read-back or may be the canonical
schedule store.

**Open questions:**
- Is s4p47 present on g2408 firmware? Probe with direct GET.
- If present, is this the canonical schedule store or a read-back of what went through s2p50?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:700)`, `github.com/nicolasglg/dreame-mova-mower (types.py:753)`

### s4p49 — `intelligent_recognition`

Intelligent multi-map recognition flag. Upstream mower forks define
INTELLIGENT_RECOGNITION at (4, 49). In the legacy integration this is
exposed as the 'multi_map' attribute; when enabled the device can maintain
separate maps for different lawn areas. Status on g2408 is unknown.

**Open questions:**
- Is s4p49 present on g2408 firmware? Probe with direct GET.
- Does multi-map capability affect the s6p8 MAP_LIST behaviour on g2408?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:702)`, `github.com/nicolasglg/dreame-mova-mower (types.py:755)`

### s4p59 — `pet_detective`

Pet-detection mode. Upstream mower forks define PET_DETECTIVE at (4, 59).
Enables AI-based pet detection so the mower can avoid animals during mowing.
Requires camera AI (s4p22). On g2408 no camera module is confirmed; this
slot is likely absent or a no-op.

**Open questions:**
- Is s4p59 present on g2408 firmware? Likely absent — g2408 has no confirmed camera.
- If present, does it interact with s4p22 (AI_DETECTION)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:706)`, `github.com/nicolasglg/dreame-mova-mower (types.py:759)`

### s4p68 — `device_snapshot_bundle`

Discovered 2026-05-06 in `dreame_cloud_dumps/dump_20260506T110907.json`
via `dreame_cloud_dump.py`'s `_PROP_PROBES` sweep. Calling
`get_properties(siid=4, piid=68)` returns a curated bundle of
multiple unrelated properties' current values rather than a
single-property value. The 2026-05-06 capture returned 8 entries:
s1p1 (heartbeat blob), s1p2 (OTA state), s1p3 (OTA progress),
s1p4 (mowing telemetry — empty list when no session), s1p5 (HW
serial), s2p1 (mode = 13 CHARGING_COMPLETED), s3p1 (battery
%), s3p2 (charging status).

This is the FIRST observed cloud-RPC-only slot (no MQTT push
observed in the probe corpus). It behaves like apk-style "bulk
device snapshot" / "loadStatus" endpoints documented in upstream
mower / vacuum code. The exact meaning of the (4, 68) coordinate
itself is unclear: it's not a property-value but an action that
happens to be invoked via `get_properties`. The bundle's
contents — heartbeat + OTA state + telemetry + serial + mode +
battery + charging — match what an "is the device alive and
what's it doing" snapshot endpoint would return.

Practical use: the integration could call this once at config-
flow init / coordinator startup to seed initial state without
waiting for the first MQTT push. That's an axis-4-style enhancement
worth considering once the response shape is confirmed across
more dumps.

**Open questions:**
- Confirm response shape across more dumps — does the bundle always carry exactly these 8 entries, or does it expand based on device state?
- Is the bundle's content static (always s1p1-5, s2p1, s3p1-2) or dynamic (e.g., includes s1p4 telemetry only during active mowing)? The 2026-05-06 capture had s1p4 empty (idle); a mowing-time capture would test this.
- Is there an aiid=68 action that takes a parameter list of (siid, piid) pairs and returns a custom bundle? The fact that get_properties accepts (4, 68) and returns multi-property data suggests so.
- Are there sibling slots s4p67 or s4p69 with similar bundle behaviour? Probe sweep can confirm.
- Capture procedure: see g2408-capture-procedures.md §7 cloud-dump cadence re-test — running the dump with --no-properties=false during different device states (idle, mowing, charging, post-FTRTS) will populate the slot's behaviour catalog.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s4p83 — `device_capability`

Device capability bitmask. Upstream mower forks define DEVICE_CAPABILITY at
(4, 83). A bitmask advertising optional feature support (camera AI, multi-map,
cruise, etc.). Useful for probing g2408 to understand which optional features
the firmware exposes without needing to test each individually.

**Open questions:**
- Is s4p83 present on g2408 firmware? Probe with direct GET — value would reveal camera/AI/cruise capability flags.
- What bitmask values correspond to which features? Cross-reference with legacy DreameDeviceCapability enum.

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:709)`, `github.com/nicolasglg/dreame-mova-mower (types.py:762)`

### s5p104 — `slam_relocate_counter`

SLAM relocate counter. Fires exclusively alongside s2p65 = 'TASK_SLAM_RELOCATE'
bursts — three pushes in ~1 second at each relocalization start. Value has
been 7 in every capture across the probe corpus; role unclear (retry count?
relocate mode enum?).

Quiet-listed in the integration so it does not re-fire [PROTOCOL_NOVEL] on
every relocate. Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- Is the constant value 7 a retry count, mode enum, or firmware constant?

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:131`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p105 — `s5p105_raw`

Small enum with values {1, 2, 4} observed across the corpus 2026-04-17 to
2026-04-30: 84× value 1, 9× value 2, 3× value 4. Value 1 is the steady-
state; 2 and 4 fire transiently.

Driver unknown — possibly a session-mode marker. Often fires alongside
s5p106 and s5p107 in the same second. Cross-reference timestamps against
s2p1 STATE transitions to identify context for non-1 values.

Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- What triggers values 2 and 4? Correlate against s2p1 transitions.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:135`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p106 — `s5p106_raw`

Purpose unknown. 157 observations across 5 days show values 1-8 with rare 9
(1×) and 11 (1×, 2026-04-24 14:43). Not a clean decimal or hex counter
(value 10 / 0xA never observed), and not a clean bitfield (10/12-15 also
missing).

Cadence is usually ~30 min between pushes but occasionally multi-hour gaps,
after which the jump is not monotonic (e.g. 1 at 11:12 → 11 at 14:43 → 4
at 15:13). No clear correlation with mowing state or battery; periodic
pushes fire while the mower is docked.

Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- Value 10/0xA never observed — is this a bitmask with a forbidden bit, or a sparse enum?

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:139`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p107 — `energy_index`

Energy / discharge index property (upstream dreame-mower const.py:83,
comment "energy/discharge index property"). Observed range 1–250. Upstream
stores the raw int and computes energy_delta = new - old on every update.

Treat as push-on-change, not periodic. A stable load may produce no push
for tens of minutes; pushes mark transitions between discharge regimes
(entering a slope, hitting a tuft, blade-load change).

80 pushes across 4 weeks; stratified by s2p1 mode shows a load-weighted
gradient: CHARGED median 63, CHARGING 100, MOWING median 133 (n=53).
Within-MOWING range 4–246 is wide enough to encode slope/turn-rate/blade-
load. Pearson against battery-drop-rate over preceding 10 min is +0.24
(n=40) — direction-correct but noisy due to integer-quantized battery and
event-driven cadence.

Often fires alongside s5p105 / s5p106 in the same second. Surfaced as
sensor.energy_index (diagnostic, default-disabled) once flat-vs-slope
decode is confirmed.

**Open questions:**
- Does median energy_index rise on sloped lawns vs flat? User's lawn is flat — needs a sloped-lawn contributor to confirm mWh-over-interval interpretation.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:143`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `alternatives/dreame-mower/dreame/types.py (const.py:83)`

### s5p108 — `s5p108_raw`

Only one observation in the probe corpus. Semantic unknown. No apk
documentation found. Cannot characterize without more captures.

**Open questions:**
- Only 1 observation. What value was it? What was the mower state at that moment?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s6p1 — `map_data_signal`

Map-readiness signal. Cycles 200 ↔ 300 to signal "new map available".
Value 300 fires at auto-recharge-leg-start (the exact millisecond s2p2 → 54
and s2p1 → 2 → 5), confirmed twice in the 2026-04-20 full-run at 09:14:09
and 11:13:04. This is the primary mid-session "map may have been refreshed"
signal; triggers the upstream map pipeline.

NOT a session-completion signal — that is the event_occured siid=4 eiid=1.
The 2026-04-20 run produced two s6p1=300 pushes (one per recharge interrupt)
plus one event_occured, each with distinct meaning.

Value 200 observed during other mowing states. Surfaced as s6p1_raw
diagnostic sensor.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:147`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### s6p2 — `frame_info`

FRAME_INFO / settings-saved tripwire + general-mode carrier. Four-element
list. Three of four elements decoded 2026-04-26 via live toggles:

[0] = Mowing Height in millimetres — observed 70→60→50 while user stepped
app slider 7.0cm→6.0cm→5.0cm. Range 30-70mm in 5mm steps (matches app's
3-7cm in 0.5cm increments). Surfaced as sensor.mowing_height (cm).

[1] = Mowing Efficiency — 0=Standard, 1=Efficient. Surfaced as
sensor.mow_mode.

[2] = EdgeMaster — bool. Earlier "constant True" reading was wrong; all
prior captures happened to have EdgeMaster ON. Toggle test 20:31 flipped it
cleanly. Surfaced as sensor.edgemaster.

[3] = Unknown — observed 2 in 25/25 captures across 8 days and settings
changes. Confirmed NOT to be Safe Edge Mowing, Automatic Edge Mowing,
Mowing Direction, Obstacle Avoidance on Edges, LiDAR Obstacle Recognition,
or its sub-setting. Most plausible: protocol/schema version or frame-type
ID.

Also functions as the "settings-saved tripwire": every BT-only settings
change kicks the device into re-publishing s6p2 even when no element changes,
giving the integration a "user changed something" signal.

**Open questions:**
- What is element [3]? Always 2 across 25+ captures regardless of mode or settings.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:103`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s6p3 — `wifi_signal_push`

WiFi signal push on g2408: [cloud_connected, rssi_dbm]. NOT the OSS object
key that upstream calls OBJECT_NAME — upstream's slot is unused on g2408
(the session-summary key arrives via event_occured instead, see §7.4).

The integration's overlay remaps OBJECT_NAME to 999/998 so the map handler
does not misinterpret s6p3 pushes as map-object-name strings.

cloud_connected (bool): true if the mower has an active cloud connection.
rssi_dbm (int): WiFi RSSI in dBm. The live s1p1 byte[17] RSSI value takes
over after startup; s6p3 seeds the initial rssi_dbm value.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:112`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s6p117 — `dock_nav_state`

Dock-nav state marker. Confirmed 2026-05-05 as a dock-navigation state
marker that fires at the start of explicit TASK_NAV_DOCK phases, paired
with s2p65 = 'TASK_NAV_DOCK' in the same second.

Three captures: (a) 2026-04-24 13:30:14 value 1 after mowing-complete +
stuck-on-garden-hose situation. (b) 2026-05-05 08:59:03 transition ?→1
paired with TASK_NAV_DOCK after run 1's FTRTS-then-retry path. (c)
2026-05-05 09:24:02 transition 3→1 paired with TASK_NAV_DOCK after run 2's
FTRTS.

Pattern: fires only on the explicit dock-nav retry path that follows an
FTRTS bounce — not on clean autonomous returns where s2p1: 5→6 happens
directly. Hypothesis: s6p117 is a dock-nav sub-state counter; 1 = "active
dock-approach", 3 = some earlier state (relocate? planning? not always
observed because the property only pushes on transition).

Suppressed in coordinator via _SUPPRESSED_SLOTS (no NOVEL warnings while
semantics are being confirmed).

**Open questions:**
- What does value 3 represent? Not always observed at the start of TASK_NAV_DOCK — may be a prior-state read.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s99p20 — `lidar_object_name`

LiDAR point-cloud OSS object key. Published by the mower each time the user
taps "View LiDAR Map" in the Dreame app and the current scan differs from
the last-uploaded one. Arrives BEFORE s2p54 = 100 (at 61% progress in the
observed capture).

Key format: ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.bin
Example: "ali_dreame/2026/04/20/BM16nnnn/-11229nnnn_154157120.0550.bin"

The integration's _handle_lidar_object_name fetches the binary blob via
cloud.get_interim_file_url (getDownloadUrl endpoint) → OSS signed URL →
HTTP GET → writes to LidarArchive under
<config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd.
Content-addressed by md5; re-tapping the same scan is a no-op.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:125`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 99 piid:20`

## Events

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| event_s4eiid1 | session_complete | list of {piid, value} args | WIRED |  |

### event_s4eiid1 — `session_complete`

Fires once per completed (or user-aborted) mowing session. Distinct from
the properties_changed MQTT method — this arrives as event_occured with
siid=4 eiid=1.

piid 9 carries the session-summary OSS object key (.json file). The
integration keys off piid 9 to fetch and archive the full session summary.

Key piids observed across 6 captures (2026-04-17..2026-04-20, including
one user-cancel): piid 1 (always 100), piid 2 (end-code enum: 31/36/69/
128/170/195/217; 36=user-cancel), piid 3 (area mowed × 100 in centiares),
piid 7 (stop-reason: 1=natural, 3=user-cancel), piid 8 (unix session-start
timestamp), piid 9 (OSS key), piid 11 (0 or 1), piid 60 (-1 normal, 101
user-cancel), piid 13 (always []), piid 14 (total mowable lawn area m²
rounded int), piid 15 (always 0).

See docs/research/inventory/generated/g2408-canonical.md § Events for the full piid catalog and
§7.5 for the OSS fetch flow. A one-shot [PROTOCOL_NOVEL] WARNING fires the
first time a new piid appears in the arguments list.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MAP Daten userData Keys`

## Actions

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1a3 | reset_lensbrush |  | APK-KNOWN |  |
| s4a3 | suppress_fault |  | WIRED |  |
| s5a1 | start_mowing |  | WIRED |  |
| s5a1_zone | start_zone_mow |  | WIRED |  |
| s5a1_edge | start_edge_mow |  | WIRED |  |
| s5a1_spot | start_spot_mow |  | WIRED |  |
| s5a2 | stop |  | WIRED |  |
| s5a3 | dock |  | WIRED |  |
| s5a4 | pause |  | WIRED |  |
| s7a1 | find_bot |  | WIRED |  |
| s9a1 | reset_blades |  | APK-KNOWN |  |
| s10a1 | reset_side_brush |  | APK-KNOWN |  |
| s11a1 | reset_filter |  | APK-KNOWN |  |
| s16a1 | reset_sensor |  | APK-KNOWN |  |
| s17a1 | reset_tank_filter |  | APK-KNOWN |  |
| s19a1 | reset_silver_ion |  | APK-KNOWN |  |
| s24a1 | reset_squeegee |  | APK-KNOWN |  |
| cfg_write_cls | lock_bot_toggle |  | WIRED |  |
| local_only_finalize | finalize_session |  | WIRED |  |

### s1a3 — `reset_lensbrush`

Reset the Lens Brush wear counter. From legacy DreameMowerActionMapping
RESET_LENSBRUSH (types.py:831). Note: the worklist incorrectly listed
this as (s27, a1); the canonical legacy mapping is {siid:1, aiid:3}.
Lens brush is a camera-cleaning accessory on vacuums; unclear whether
g2408 uses this siid/aiid pair for any mower accessory.

**Open questions:**
- Does action(1,3) apply to g2408? siid:1 is the heartbeat/telemetry service — aiid:3 on siid:1 is unusual. Verify legacy mapping is not a typo.

**See also:** `apk: ioBroker.dreame/apk.md §siid:1 aiid:3`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:831)`

### s4a3 — `suppress_fault`

Suppress / clear the current active fault or warning. Wired via routed
action s2a50 with o:11 (suppressFault opcode). Verified in legacy
DreameMowerActionMapping as CLEAR_WARNING (types.py:813).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:190`, `apk: ioBroker.dreame/apk.md §Actions o:11 suppressFault`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:813)`

### s5a1 — `start_mowing`

Trigger a global all-area mowing run. On g2408 the direct action(siid=5,
aiid=1) call returns 80001 ("device unreachable"); the working path is
the routed action siid=2 aiid=50 {m:'a', o:100, t:'TASK'}.

The same (siid=5, aiid=1) wire entry is shared by START_ZONE_MOW
(o:102), START_EDGE_MOW (o:101), and START_SPOT_MOW (o:103) — they
differ only in the routed_o opcode and the payload. See opcodes o100,
o101, o102, o103 for the respective TASK envelope shapes.

**Open questions:**
- Direct action(5,1) consistently returns 80001; routed path via s2a50 o:100 is the confirmed working path.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:153`, `apk: ioBroker.dreame/apk.md §Actions o:100 globalMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_zone — `start_zone_mow`

Zone-specific mowing run. Same (siid=5, aiid=1) wire entry as
start_mowing but dispatched via routed action s2a50 with o:102 and
payload {m:'a', p:0, o:102, d:{region:[zone_ids]}}.

zone_ids are scalar ints from MAP.*.mowingAreas.value. Alias
START_ZONE_MOW in MowerAction enum. Routed-action opcode see o102.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:157`, `apk: ioBroker.dreame/apk.md §Actions o:102 zoneMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_edge — `start_edge_mow`

Edge-mowing-only run (perimeter tracing). Same (siid=5, aiid=1) wire
entry dispatched via routed action s2a50 with o:101 and payload
{m:'a', p:0, o:101, d:{edge:[[map_id, contour_id], ...]}}.

Critical: d.edge must NOT be empty — the firmware interprets [] as
"every contour including merged sub-zone seams", draining the edge
budget on internal boundaries and causing wheel-bind → FTRTS. The app
sends explicit [[1, 0], ...] pairs (outer perimeter only). The
integration's _edge_mow_payload() enforces [[1,0]] as last-resort
fallback and prefers contour_ids populated from cached map data.

See docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes for the full failure-mode
write-up (2026-05-05, three live captures).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:162`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:101 edgeMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_spot — `start_spot_mow`

Spot mowing run on defined spot areas. Same (siid=5, aiid=1) wire
entry dispatched via routed action s2a50 with o:103 and payload
{m:'a', p:0, o:103, d:{area:[spot_ids]}}.

spot_ids from MAP.*.spotAreas.value. Confirmed end-to-end live
2026-04-29 (per project memory). Echo: {area_id:[N], exe:T,
o:103, region_id:[], status:T, time:N}.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:167`, `apk: ioBroker.dreame/apk.md §Actions o:103 spotMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a2 — `stop`

Stop the current mowing run (without returning to dock). Verified in
legacy DreameMowerActionMapping (types.py:811). On g2408, direct
action returns 80001; routed path is the fallback.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:175`, `apk: ioBroker.dreame/apk.md §Actions o:3 stopControl`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:811)`

### s5a3 — `dock`

Send the mower back to the docking station (charge). Also used as
RECHARGE (alias for DOCK with the explicit "head to charger now"
semantic). Verified in legacy DreameMowerActionMapping (types.py:810).
On g2408, direct action returns 80001; routed path is the fallback.
Expected s2p1 transition: any → RETURNING → CHARGING.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:173`, `apk: ioBroker.dreame/apk.md §Actions o:7 stopBackCharge`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:810)`

### s5a4 — `pause`

Pause the current mowing run in-place. Verified in legacy
DreameMowerActionMapping (types.py:809). On g2408, direct action
returns 80001; the integration retries via routed action if needed.
Expected s2p1 transition: WORKING → PAUSED.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:172`, `apk: ioBroker.dreame/apk.md §Actions o:4 pauseControl`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:809)`

### s7a1 — `find_bot`

Trigger the "Find My Mower" beep/LED sequence on the robot. Wired via
routed action s2a50 with o:9 (findBot opcode). Verified in legacy
DreameMowerActionMapping as LOCATE (types.py:821). On g2408, the
routed path (o:9) is the working channel.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:178`, `apk: ioBroker.dreame/apk.md §Actions o:9 findBot`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:821)`

### s9a1 — `reset_blades`

Reset the Blades wear counter. From legacy DreameMowerActionMapping
RESET_BLADES (types.py:825). The g2408 CMS[0] tracks blade wear
(confirmed); whether sending this action resets CMS[0] on g2408
firmware is unconfirmed. Vacuum-derived — vacuum blades vs mower
blades may differ in firmware handler.

**Open questions:**
- Does action(9,1) reset CMS[0] (blade_min) on g2408? Needs live test.

**See also:** `apk: ioBroker.dreame/apk.md §siid:9 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:825)`

### s10a1 — `reset_side_brush`

Reset the Side Brush wear counter. From legacy DreameMowerActionMapping
RESET_SIDE_BRUSH (types.py:826). Side brush is a vacuum accessory; the
g2408 mower equivalent is the Cleaning Brush (CMS[1]). Whether
action(10,1) resets CMS[1] on g2408 is unconfirmed.

**Open questions:**
- Does action(10,1) reset CMS[1] (brush_min) on g2408? Needs live test.

**See also:** `apk: ioBroker.dreame/apk.md §siid:10 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:826)`

### s11a1 — `reset_filter`

Reset the Filter wear counter. From legacy DreameMowerActionMapping
RESET_FILTER (types.py:827). Filter is vacuum-specific; unclear whether
g2408 has a filter or which CMS slot this would reset.

**Open questions:**
- Does action(11,1) apply to g2408? No matching CMS slot identified.

**See also:** `apk: ioBroker.dreame/apk.md §siid:11 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:827)`

### s16a1 — `reset_sensor`

Reset the Sensor dirty-life counter. From legacy DreameMowerActionMapping
RESET_SENSOR (types.py:828). Sensor cleaning is a vacuum maintenance
item; whether g2408 exposes a sensor-dirty counter is unknown.

**Open questions:**
- Does action(16,1) apply to g2408? No sensor-dirty CMS slot confirmed.

**See also:** `apk: ioBroker.dreame/apk.md §siid:16 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:828)`

### s17a1 — `reset_tank_filter`

Reset the Tank Filter wear counter. From legacy DreameMowerActionMapping
RESET_TANK_FILTER (types.py:829). Tank filter is a vacuum/mop accessory;
g2408 has no tank/mop hardware.

**Open questions:**
- Does action(17,1) apply to g2408? g2408 has no tank/mop hardware.

**See also:** `apk: ioBroker.dreame/apk.md §siid:17 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:829)`

### s19a1 — `reset_silver_ion`

Reset the Silver Ion filter wear counter. From legacy
DreameMowerActionMapping RESET_SILVER_ION (types.py:830). Silver ion
filter is a vacuum/mop accessory; g2408 has no such accessory.

**Open questions:**
- Does action(19,1) apply to g2408? Silver ion is vacuum-only accessory.

**See also:** `apk: ioBroker.dreame/apk.md §siid:19 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:830)`

### s24a1 — `reset_squeegee`

Reset the Squeegee wear counter. From legacy DreameMowerActionMapping
RESET_SQUEEGEE (types.py:832). Squeegee is a mop/vacuum accessory;
g2408 has no squeegee.

**Open questions:**
- Does action(24,1) apply to g2408? g2408 has no squeegee.

**See also:** `apk: ioBroker.dreame/apk.md §siid:24 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:832)`

### cfg_write_cls — `lock_bot_toggle`

Toggle the child lock (mower panel lockout). No (siid, aiid) entry in
legacy or greenfield; CHILD_LOCK is a property write, not an action
call. The integration dispatches LOCK_BOT_TOGGLE via coordinator
write_setting("CLS", toggled_value) using the cfg_toggle_field
mechanism. Reads the current child_lock_enabled from coordinator.data,
computes not bool(current), and calls write_setting("CLS", toggled).
Confirmed g2408: CLS is the authoritative child-lock setting
(docs/research/inventory/generated/g2408-canonical.md § CFG keys).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:184`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`

### local_only_finalize — `finalize_session`

Integration-internal action; no cloud call is ever issued. The
dispatch_action local_only branch calls _run_finalize_incomplete()
(F5.10.1) to close out any session that ended without a clean
event_occured signal (e.g. session ended during HA restart).
local_only: true in the ActionEntry — the cloud-action path is
never reached.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:195`

## Routed-action opcodes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| o_minus_1 | error_abort | {m:'a', d:{o:-1, status:true, exe:true}, t:'TASK'} | WIRED |  |
| o0 | reset_control | {m:'a', o:0} | APK-KNOWN |  |
| o2 | joystick_start | {m:'a', o:2} | APK-KNOWN |  |
| o3 | cancel | {m:'a', d:{o:3}, t:'TASK'} (echo only) | WIRED |  |
| o4 | joystick_pause | {m:'a', o:4} | APK-KNOWN |  |
| o5 | joystick_continue | {m:'a', o:5} | APK-KNOWN |  |
| o6 | recharge | {m:'a', d:{o:6}, t:'TASK'} (echo only) | WIRED |  |
| o7 | joystick_stop_back | {m:'a', o:7} | APK-KNOWN |  |
| o8 | set_ota | {m:'a', o:8, d:{...}} | APK-KNOWN |  |
| o9 | find_bot | {m:'a', o:9} | WIRED |  |
| o10 | upload_map | {m:'a', o:10} | APK-KNOWN |  |
| o11 | suppress_fault | {m:'a', o:11} | WIRED |  |
| o12 | lock_bot | {m:'a', o:12, d:{lock: 0|1}} | APK-KNOWN |  |
| o15 | remote_setting | {m:'a', p:0, o:15, d:{c: 0|1} | {h: height*10}} | APK-KNOWN |  |
| o100 | global_mower | {m:'a', o:100, t:'TASK', area_id:N, region_id:[1], time:N, exe:T} | WIRED |  |
| o101 | edge_mower | {m:'a', o:101, d:{edge:[[map_id, contour_id], ...]}, t:'TASK'} | WIRED |  |
| o102 | zone_mower | {m:'a', o:102, d:{region:[zone_id, ...]}, t:'TASK'} | WIRED |  |
| o103 | spot_mower | {m:'a', o:103, d:{area:[spot_id, ...]}, t:'TASK'} | WIRED |  |
| o104 | plan_mower | {m:'a', o:104, d:{...}} | APK-KNOWN |  |
| o105 | obstacle_mower | {m:'a', o:105, d:{...}} | APK-KNOWN |  |
| o107 | start_cruise_point | {m:'a', o:107, d:{...}} | APK-KNOWN |  |
| o108 | start_cruise_side | {m:'a', o:108, d:{...}} | APK-KNOWN |  |
| o109 | start_clean_point | {m:'a', d:{o:109, status:false, exe:true}, t:'TASK'} (echo only) | WIRED |  |
| o110 | start_learning_map | {m:'a', o:110} | APK-KNOWN |  |
| o200 | change_map | {m:'a', o:200, d:{map_id:N}} | APK-KNOWN |  |
| o201 | exit_build_map | {m:'a', d:{o:201, status:true, error:0}, t:'TASK'} (echo) | WIRED |  |
| o204 | edit_map | {m:'a', d:{o:204, exe:T, status:T, ...}, t:'TASK'} (echo) | WIRED |  |
| o205 | clear_map | {m:'a', o:205} | APK-KNOWN |  |
| o206 | expand_map | {m:'a', o:206} | APK-KNOWN |  |
| o215 | map_edit_confirm_legacy | {m:'a', d:{o:215, id:N, ids:[...], exe:T, status:T}, t:'TASK'} (echo) | WIRED |  |
| o218 | delete_zone | {m:'a', d:{o:218, id:N, ids:[], exe:T, status:T}, t:'TASK'} (echo) | WIRED |  |
| o234 | save_zone_geometry | {m:'a', d:{o:234, id:N, ids:[], exe:T, status:T}, t:'TASK'} (echo) | WIRED |  |
| o400 | start_binocular | {m:'a', o:400} | APK-KNOWN |  |
| o401 | take_pic | {m:'a', o:401} | WIRED |  |
| o503 | cutter_bias | {m:'a', o:503, d:{...}} | APK-KNOWN |  |

### o_minus_1 — `error_abort`

Error abort / teardown cleanup marker. Fires on s2p50 immediately
after a failed task (typically paired with o:109 task-start-failed).
status=true indicates the cleanup is complete; no id/ids fields.
Firmware-idiomatic for "no specific op — this is a cleanup marker".

Observed 2026-04-20 19:34:20 immediately after an o:109 task-start
failure: mower emits s2p50 o:109 status:false, then 0 ms later
s2p50 o:-1 status:true (abort ack).

Also fires as teardown for map-edit sequences (§2.1): o:204 → o:234
(or o:215/o:218) → o:201 → o:-1.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:-1 error abort`

### o0 — `reset_control`

Joystick reset — resets the manual joystick control state. Apk-
documented (ioBroker cross-reference §action operations). Not observed
on g2408 wire; likely only used during manual-control / BT joystick
sessions.

**Open questions:**
- Confirm g2408 responds to o:0 in any reachable state.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o2 — `joystick_start`

Joystick control — start moving. Part of the o:2–7 manual joystick
control group (start/stop/pause/continue/pauseBack/stopBack). Apk-
documented; not observed on g2408 wire.

**Open questions:**
- Confirm joystick opcodes 2-7 work on g2408 via cloud (vs BT-only).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o3 — `cancel`

Task cancelled echo — fires on s2p50 when the user hits Cancel / Stop
during an active mowing session. Fires ~1 s after s2p2=48. Does not
carry id/ids. Observed 2026-04-20 as a status echo from the firmware;
the integration does NOT send o:3 as a command — Stop/Pause are
action(5,2) and action(5,4).

Also listed in apk as joystick "stop" (o:2-7 group); in s2p50 echo
context it is the canonical "user-cancel" marker.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:3 stopControl`

### o4 — `joystick_pause`

Joystick control — pause. Part of the o:2–7 manual joystick control
group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o5 — `joystick_continue`

Joystick control — continue / resume. Part of the o:2–7 manual joystick
control group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o6 — `recharge`

Explicit Recharge command echo — fires on s2p50 when the user taps the
app Recharge button (send mower home). Echo is unreliable: observed
2026-04-20 18:09:56, 18:25:57, 04-27 10:12:18, 04-29 20:47:18 (all on
dock-arrival), but on 2026-05-05 09:24 a confirmed app Recharge that
successfully drove the mower home fired zero o:6 echo at all. The cloud
occasionally drops this delivery.

Detection of Recharge should lean on s2p1: ?→5→6 plus s3p2→1, NOT on
the s2p50 o:6 echo.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:6 pauseBackCharge`

### o7 — `joystick_stop_back`

Joystick control — stopBack. Part of the o:2–7 manual joystick control
group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o8 — `set_ota`

Trigger OTA (over-the-air firmware update). Apk-documented; not observed
on g2408 wire. Expected to carry OTA metadata in d field.

**Open questions:**
- What is the d-field payload shape for OTA? Apk source needed.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o9 — `find_bot`

Find My Mower — triggers audible beep and/or LED flash on the robot.
Used by the integration's FIND_BOT action via routed action s2a50.
Apk-documented as findBot. No echo observed on s2p50 — command is
fire-and-forget.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:178`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o10 — `upload_map`

Trigger map upload to cloud. Apk-documented as uploadMap. Not observed
on g2408 wire; the integration does not use this opcode (map fetches
go through the OSS/REST path, not this action).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o11 — `suppress_fault`

Suppress / clear the current active fault or warning. Used by the
integration's SUPPRESS_FAULT action via routed action s2a50. Apk-
documented as suppressFault.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:190`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o12 — `lock_bot`

Lock the mower (panel child lock). Apk-documented as lockBot. The
integration dispatches child-lock via CFG write ("CLS") rather than
this opcode; this opcode may be an alternative channel or app-only path.

**Open questions:**
- Does o:12 work in parallel with CFG.CLS write, or is one canonical?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o15 — `remote_setting`

Remote-control settings push. Apk-documented at L175109-175121 as
remoteSetting. Sent during a joystick-control session to adjust mower
parameters without stopping the joystick stream. Two observed d-field
shapes:
  - {c: 0|1}        — camera on/off during remote control
  - {h: height*10}  — cutting height in mm ×10 (e.g., 50mm → h:500)

Sent via BLE+IOT channel (not BLE-only like joystick data). Must be
sent while an active joystick session is running (between o:2 start
and o:3 stop). Not a standalone configuration path — only valid in
remote-control context.

Never observed on g2408 wire; the integration does not implement
joystick remote control.

**Open questions:**
- Are c and h the only sub-parameters, or can other fields be passed?
- Does the firmware accept o:15 outside an active joystick session?

**See also:** `apk: ioBroker.dreame/apk.md §Remote Control remoteSetting L175109`

### o100 — `global_mower`

All-area mowing session start. Observed as a flat-field s2p50 push
(not wrapped in d:{}) at session start: {area_id:N, exe:T, o:100,
region_id:[1], time:N, t:'TASK'}. The integration sends this via
routed action s2a50 {m:'a', o:100} for START_MOWING. Apk-documented
as globalMower.

Echo arrives seconds after the routed action; confirms the mower has
accepted the task. See §4.3 "Session start" for the full sequence.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:155`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o101 — `edge_mower`

Edge-mowing-only task launch. The firmware canonicalizes the inbound
d.edge [[m,c],...] list into group_id for its echo:
{exe:T, group_id:[[m,c],...], o:101, status:T, time:N}.

Echo is identical regardless of input (empty vs explicit contour list),
so the s2p50 echo cannot be used to discriminate launch paths.

Critical: d.edge:[] is NOT "all outer contours" — it is "every contour
including internal seam boundaries", causing wheel-bind → FTRTS. Always
send explicit [[map_id, contour_index], ...] pairs. Confirmed 2026-05-05
(three live edge-mow runs; see §4.6.1).

Observed in probe corpus from 2026-04-26 onward.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:163`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o102 — `zone_mower`

Zone-specific mowing task launch. zone_ids are scalar ints from
MAP.*.mowingAreas.value. Distinct from o:101 edge contours (which use
[map_id, contour_index] 2-tuples). Observed in probe corpus per §4.6.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:158`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o103 — `spot_mower`

Spot mowing task launch. spot_ids from MAP.*.spotAreas.value. Echo:
{area_id:[N], exe:T, o:103, region_id:[], status:T, time:N}. Confirmed
end-to-end live 2026-04-29. Cloud spotAreas.area=0 in echo — actual
spot coordinates from telemetry, not from echo (per project memory
g2408-session-archive-quirks).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:168`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o104 — `plan_mower`

Scheduled / planned mowing run. Apk-documented as planMower. Not
observed on g2408 wire; scheduled mowing is triggered by the Dreame
cloud at the configured time, not by the integration. d-field payload
shape unknown.

**Open questions:**
- What d-field does planMower carry? Apk source needed.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o105 — `obstacle_mower`

Obstacle-aware mowing mode. Apk-documented as obstacleMower. Not
observed on g2408 wire. Exact semantics and d-field unknown.

**Open questions:**
- How does obstacleMower differ from globalMower on g2408?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o107 — `start_cruise_point`

Patrol to a specific point. Apk-documented as startCruisePoint. Not
observed on g2408 wire. Used by some Dreame robot models for autonomous
patrol waypoint navigation.

**Open questions:**
- Does g2408 support patrol/cruise modes at all?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o108 — `start_cruise_side`

Patrol along an edge. Apk-documented as startCruiseSide. Not observed
on g2408 wire. Companion to o:107.

**Open questions:**
- Does g2408 support cruise-side mode?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o109 — `start_clean_point`

"Go to clean point" command / task-start-failed echo. Apk-documents
this as startCleanPoint (go to a designated cleaning point). On g2408
it is observed exclusively as a status:false echo on s2p50 — indicating
a task command was rejected because the mower was in a bad state
(e.g. Positioning Failed, s2p2=71).

First observed 2026-04-20 19:34:20: the mower emitted o:109
status:false (task rejected), immediately followed by o:-1 status:true
(abort cleanup). The integration monitors for o:109 + status:false as
the "task start failed" signal.

Whether o:109 as a command (not echo) does anything useful on g2408
is unknown.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o110 — `start_learning_map`

Start BUILDING mode (map learning / initial mapping run). Apk-documented
as startLearningMap. Used when the mower needs to build its first map or
expand an existing one. Not directly observed on g2408 wire in probe
corpus; the integration does not currently wire this action.

**Open questions:**
- Confirm g2408 honours o:110 for BUILDING mode start.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o200 — `change_map`

Switch the active map. Apk-documented as changeMap. Not observed on
g2408 wire; the integration does not currently implement multi-map
switching.

**Open questions:**
- Does g2408 support multiple maps? changeMap d-field shape?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o201 — `exit_build_map`

Apk: exitBuildMap — exits BUILDING/learning-map mode. On g2408, o:201
is observed as a status echo on s2p50 that closes every map-edit
sequence (create zone, resize, delete): the always-trailing
{o:201, status:true, error:0} arrival is the integration's universal
"refetch + rebuild map" trigger.

The dual role (command: exit building mode / echo: map-edit complete)
reflects that the same opcode number is reused in both contexts by the
firmware. The integration keys on o:201 status:true error:0 for the
map rebuild trigger (§2.1).

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o204 — `edit_map`

Map-edit request echo — fires first in a zone / exclusion-zone add /
edit / delete sequence, before the save or delete confirmation opcode.
Apk-documented as editMap. On g2408 observed as the first of the
map-edit pair (204 → 234/215/218 → 201).

Observed 2026-04-20 and confirmed in the 2026-04-26 Designated Ignore
Obstacle Zone create/resize/delete corpus.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o205 — `clear_map`

Clear / wipe the current map. Apk-documented as clearMap. Not observed
on g2408 wire; the integration does not expose a clear-map action.

**Open questions:**
- Does clearMap fully wipe all zones and the map polygon on g2408?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o206 — `expand_map`

Expand the current lawn map (add new area to existing map). Apk-
documented as expandMap; also referenced in §4.3 "Expand Lawn" context.
Not directly observed on g2408 wire in probe corpus.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o215 — `map_edit_confirm_legacy`

Legacy map-edit confirmation echo. Older captures (2026-04-20) show
o:215 as the "second of the map-edit pair" (zone edit confirm), carrying
id and ids fields. Later captures (2026-04-26) show o:234 in the same
role. The integration triggers a MAP rebuild on o:215 OR o:201 with
status:true error:0 — covers both old and new confirmation opcode.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit confirm`

### o218 — `delete_zone`

Zone / exclusion-zone delete echo. Carries the deleted entity's id;
ids:[] in all observed captures. CONFIRMED via multiple captures
matching user-delete narrative in the 2026-04-26 Designated Ignore
Obstacle Zone corpus. One outlier capture from an untraced UI flow
(likely an edit-cancel processed as delete-and-recreate). Sequence:
o:204 → o:218 → o:201.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit delete`

### o234 — `save_zone_geometry`

Save zone / exclusion-zone geometry echo. CONFIRMED — fires for both
create new (new firmware-assigned id) and resize existing (same id).
Carries the saved entity's id; ids:[] in all observed captures. Sequence:
o:204 → o:234 → o:201. Confirmed 2026-04-26 from Designated Ignore
Obstacle Zone create/resize/delete tests.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit save geometry`

### o400 — `start_binocular`

Camera-stream start (binocular/stereo camera activation). Apk-documented
as startBinocular. Not observed on g2408 wire; likely a camera-streaming
feature not yet wired in the integration.

**Open questions:**
- Does g2408 support startBinocular? Related to takePic (o:401) flow?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o401 — `take_pic`

Take a photo via the mower's onboard camera. Observed on s2p50 via
HA-integration button press (2026-04-27). Two distinct firmware echoes:
(a) docked: {o:401, exe:true, status:true, error:0} — accepted but
silently skipped (dock obscures camera); (b) lawn-stopped BT-disconnected:
{o:401, exe:true, status:false} — rejected.

NOTE: The Dreame app's Take Picture button does NOT use this opcode.
Comparison test 2026-04-27 10:59 showed zero MQTT traffic when the app
successfully captured an image — the app uses a separate cloud HTTP/OSS
surface. Integration use of o:401 is best-case a no-op, worst-case a
rejection. See §4.6 for the full comparison test write-up.

**See also:** `custom_components/dreame_a2_mower/coordinator.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o503 — `cutter_bias`

Blade calibration / bias correction. Apk-documented as cutterBias.
Referenced in §6.2 opcode list. Not observed on g2408 wire; the
integration does not currently expose a blade-calibration action. d-field
payload shape (calibration parameters) unknown.

**Open questions:**
- What d-field does cutterBias carry? When should calibration be triggered?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

## CFG keys

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| AOP | ai_obstacle_photos | int {0,1} | WIRED |  |
| ATA | anti_theft_alarm | list[int(3)] [lift_alarm, offmap_alarm, realtime_location] | WIRED |  |
| BAT | charging_config | list[int(6)] [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min] | WIRED |  |
| BP | bp_unknown | list[int(2)] [?, ?] | WIRED |  |
| CLS | child_lock | int {0,1} | WIRED |  |
| CMS | consumables_wear_meters | list[int(4)] [blade_min, brush_min, robot_min, aux_min] | WIRED |  |
| DLS | daylight_savings | int=0 | WIRED |  |
| DND | do_not_disturb | list[int(3)] [enabled, start_min, end_min] | WIRED |  |
| FDP | frost_protection | int {0,1} | WIRED |  |
| LANG | language | list[int(2)] [text_idx, voice_idx] | WIRED |  |
| LIT | lights_led_period | list[int(8)] [enabled, start_min, end_min, standby, working, charging, error, unknown] | WIRED |  |
| LOW | low_speed_nighttime | list[int(3)] [enabled, start_min, end_min] | WIRED |  |
| MSG_ALERT | notification_preferences | list[int(4)] [anomaly, error, task, consumables] | WIRED |  |
| PATH | path_unknown | int {0,1} (observed as bool true) | WIRED |  |
| PRE | mowing_preferences | list[int(2)] [zone_id, mode] | WIRED |  |
| PROT | navigation_path | int {0,1} | WIRED |  |
| REC | human_presence_detection | list[int(9)] [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photo_consent, push_min] | WIRED |  |
| STUN | auto_recharge_standby | int {0,1} | WIRED |  |
| TIME | timezone | str (IANA timezone name) | WIRED |  |
| VER | cfg_version | int (monotonic counter) | WIRED |  |
| VOICE | voice_prompt_modes | list[int(4)] [regular_notification, work_status, special_status, error_status] | WIRED |  |
| VOL | robot_voice_volume | int 0..100 | WIRED | % (×1.0) |
| WRF | weather_forecast_reference | int {0,1} | WIRED |  |
| WRP | rain_protection | list[int(2)] [enabled, resume_hours] | WIRED |  |

### AOP — `ai_obstacle_photos`

Capture Photos of AI-Detected Obstacles. Confirmed 2026-04-24 via
isolated single-toggle. Mapping {0: off, 1: on} matches the app.
Surfaced as sensor.ai_obstacle_photos. Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX AOP`

### ATA — `anti_theft_alarm`

Anti-Theft Alarm. Confirmed 2026-04-24, all three indices individually
verified 2026-04-27. Shape [lift_alarm, offmap_alarm, realtime_location]
matches the s2p51 ANTI_THEFT decoder exactly.
Toggle test: [0,0,0]→[1,0,0] Lift, →[1,1,0] Off-Map, →[1,1,1]
Real-Time Location. Each index ∈ {0,1}.
Surfaced as sensor.anti_theft (state=on if any sub-flag enabled,
per-flag bools in attributes). Sample: [0,0,0].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX ATA`

### BAT — `charging_config`

Charging config. Confirmed 2026-04-24. Shape matches the s2p51
CHARGING decoder exactly: [recharge_pct, resume_pct, unknown_flag,
custom_charging, start_min, end_min].
recharge_pct = auto-recharge when battery drops below this;
resume_pct = resume mowing when battery above this;
unknown_flag consistently observed =1 (purpose TBD);
custom_charging bool toggles the schedule window;
start_min/end_min = window in minutes-from-midnight.
Surfaced as sensor.charging_config.
Sample: [15, 95, 1, 0, 1080, 480] → recharge@15%, resume@95%, window
off, would-be 18:00→08:00.

**Open questions:**
- unknown_flag [2] always=1 — purpose unknown.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX BAT`

### BP — `bp_unknown`

TBD. Same shape as WRP list(2). Sample: [1, 4]. No toggle-correlation
test performed; semantics unknown. Exposed as diagnostic only.

**Open questions:**
- BP[0] and BP[1] — no toggle correlation yet; shape matches WRP but meaning unknown.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX BP`

### CLS — `child_lock`

Child Lock. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.child_lock_cfg. A switch.child_lock entity already exists
wired to DreameMowerProperty.CHILD_LOCK, but on g2408 the
authoritative read path is CFG.CLS. Sample: 0 (off).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX CLS`

### CMS — `consumables_wear_meters`

Consumables wear meters. Wear meters in minutes. Apk documents 3
fields; g2408 has 4. Max-minutes: [6000, 30000, 3600, ?].
blade_min/brush_min/robot_min confirmed vs app. CMS[3] semantic TBD
— likely tied to Link Module (cellular connectivity, electronics that
age — most plausible wear candidate), Garage, or Charging Station
MCA10. User without any of those accessories will see CMS[3]=0 or -1.
Confirmation needs a user with a Link Module to compare CMS[3] vs
app-side fault/firmware indicator. Sample: [3084, 0, 0, -1].

**Open questions:**
- CMS[3] semantic — Link Module, Garage, or MCA10? Needs user with Link Module.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX CMS`

### DLS — `daylight_savings`

Daylight savings flag (hypothesized). Observed stable at 0 across
all captures. No toggle-correlation test performed. May be firmware-
managed automatically via TIME (IANA timezone). Sample: 0.

**Open questions:**
- DLS — is this firmware-managed when TIME is set, or user-settable? No toggle test done.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX DLS`

### DND — `do_not_disturb`

Do-Not-Disturb. Apk-catalogued. Shape [enabled, start_min, end_min]
with start_min/end_min in minutes-from-midnight. Sample: [0, 1260, 420]
= off, would-be 21:00→07:00.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX DND`

### FDP — `frost_protection`

Frost Protection. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.frost_protection. Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX FDP`

### LANG — `language`

Language. Confirmed 2026-04-24. Shape [text_idx, voice_idx].
text_idx = app/UI language; voice_idx = robot voice language.
Observed indices: voice_idx=7 → Norwegian. Transported via s2p51
shape {"text": N, "voice": M} — decoded as Setting.LANGUAGE.
Surfaced as sensor.robot_voice (state = voice language name where
known, raw indices as attrs). Sample: [2, 7].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LANG`

### LIT — `lights_led_period`

Lights / LED period. Confirmed 2026-04-24. Shape matches the s2p51
LED_PERIOD decoder exactly: [enabled, start_min, end_min, standby,
working, charging, error, unknown].
[0] Custom LED Activation Period on/off, [1] window start
(min-from-midnight), [2] window end, [3] scenario "In Standby",
[4] "In Working", [5] "In Charging", [6] "In Error State", [7]
unknown trailing toggle (app-visible, purpose unclear).
Surfaced as sensor.headlight_enabled (on/off from [0]) +
sensor.headlight_schedule ([1]/[2] plus scenario flags and [7] as
attributes). Sample: [0, 480, 1200, 1, 1, 1, 1, 1] = LEDs off
(custom period disabled), would-be 08:00→20:00, all scenarios on.

**Open questions:**
- LIT[7] — unknown trailing toggle; app shows an extra field whose purpose isn't obvious.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LIT`

### LOW — `low_speed_nighttime`

Low-Speed Nighttime. Confirmed 2026-04-24 via live toggle. Shape
[enabled, start_min, end_min] with start_min/end_min in
minutes-from-midnight. Shape matches the s2p51 LOW_SPEED_NIGHT
decoder. User example: [1, 1200, 480] = enabled, 20:00→08:00 next
day. Surfaced as sensor.low_speed_nighttime.
Sample: [1, 1200, 480].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LOW`

### MSG_ALERT — `notification_preferences`

Notification Preferences. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [anomaly_messages, error_messages, task_messages,
consumables_messages]. Default sample [1,1,1,1] = all four enabled.
Wire shape collides with VOICE — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Sample: [1, 1, 1, 1].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX MSG_ALERT`

### PATH — `path_unknown`

Unknown on g2408. Observed stable at 1 (true) through a Navigation
Path toggle test 2026-04-25 — NOT the Navigation Path setting despite
earlier user guess (PROT is Navigation Path). Semantic TBD.
Exposed as sensor.cfg_path_raw (disabled-by-default diagnostic) so
the raw int is visible for future toggle-correlation tests.
Sample: true (coerced to 1).

**Open questions:**
- PATH — stable at true/1 through nav-path toggle; purpose still unknown.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PATH`

### PRE — `mowing_preferences`

Mowing preferences. g2408 has 2 elements [zone_id, mode], not the
apk's 10. Alpha.86 removed the entities that read PRE[2..9]; only
mow_mode and mow_mode_efficient (both reading PRE[1]) remain.
zone_id selects which zone's preferences to apply; mode is the
mowing mode for that zone. Sample: [0, 0].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PRE`

### PROT — `navigation_path`

Navigation Path. Confirmed 2026-04-24 via isolated single-toggle with
cfg_keys_raw diff visible on HA alpha.123+. Mapping {0: "direct",
1: "smart"} matches the order shown in the app. Surfaced as
sensor.navigation_path. The field name is cryptic but the toggle
correlation is unambiguous: toggling Nav Path smart→direct flipped
PROT 1→0 with no other CFG key moving. Sample: 1 (smart).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PROT`

### REC — `human_presence_detection`

Human Presence Detection Alert. Confirmed 2026-04-24. Shape matches
the s2p51 HUMAN_PRESENCE_ALERT decoder exactly: [enabled, sensitivity,
standby, mowing, recharge, patrol, alert, photo_consent, push_min].
sensitivity ∈ {0,1,2} = low/medium/high. scenario_* fields enable
detection per activity class. alert covers voice prompts + in-app
notifications. photo_consent is the privacy opt-in for sending
captured human photos. push_min is the push-notification cooldown
in minutes (observed: 3/10/20).
Surfaced as sensor.human_presence_alert.
Sample: [1, 1, 1, 1, 1, 1, 0, 1, 3].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX REC`

### STUN — `auto_recharge_standby`

Auto Recharge After Extended Standby. Confirmed 2026-04-24. Mapping
{0: off, 1: on}. Surfaced as sensor.auto_recharge_standby. Was
previously mislabelled as "Anti-Theft" in sensor.py (upstream vacuum
codebase naming that doesn't apply on g2408).
Behaviour observed 2026-04-27: when STUN=1 and the mower is idle
outside the dock for ~1 hour (BT-orphaned manual stop ~10:55 →
auto-return 11:52:47 = 57 min), the firmware fires s2p2=71 +
s2p1=5 simultaneously and self-navigates back to the dock. Dreame
app notification confirms: "The robot is on standby outside the
station for too long. Automatically returning to the station."
Whether the timeout duration is a firmware constant or stored in
another (still uncatalogued) CFG slot is unknown — STUN itself is
just an enable flag. Sample: 1 (on).

**Open questions:**
- STUN standby timeout duration — firmware constant or hidden CFG slot?

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX STUN`

### TIME — `timezone`

Timezone IANA name, e.g. 'Europe/Oslo'. Exposed as
mower_timezone sensor. Sample: "Europe/Oslo".

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX TIME`

### VER — `cfg_version`

CFG-update revision counter. Corrected 2026-04-24 — was previously
mis-labelled "firmware version". Monotonic increment on every
successful CFG write; useful as a tripwire for toggle-correlation
research. Distinct from the actual firmware version surfaced by
sensor.firmware_version (which reads device.info.version, a separate
cloud field). Surfaced as diagnostic sensor.cfg_version.
Sample: 444.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VER`

### VOICE — `voice_prompt_modes`

Voice Prompt Modes. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [regular_notification_prompt, work_status_prompt,
special_status_prompt, error_status_prompt].
Wire shape collides with MSG_ALERT — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Surfaced as sensor.voice_prompt_modes (state = count enabled 0..4,
per-mode bools in attrs). Sample: [1, 1, 1, 1].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VOICE`

### VOL — `robot_voice_volume`

Robot Voice volume. Confirmed 2026-04-24. Mapping is percentage
0..100. Surfaced as sensor.robot_voice_volume. Sample: 72.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VOL`

### WRF — `weather_forecast_reference`

Weather Forecast Reference. Mapping {0: off, 1: on}. Surfaced as
sensor.weather_forecast_reference. Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX WRF`

### WRP — `rain_protection`

Rain Protection. Confirmed 2026-04-24 via live toggle. Shape
[enabled, resume_hours]. enabled ∈ {0,1}; resume_hours ∈ {0..24}
where 0 = "Don't Mow After Rain" (no auto-resume), 1..24 resumes N
hours after rain ends. Wire shape mirrors the s2p51 RAIN_PROTECTION
decoder. Surfaced as sensor.rain_protection. Distinct from
binary_sensor.rain_protection_active which tracks "raining right now"
via s2p2=56. Sample: [1, 4].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX WRP`

## cfg_individual endpoints

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| AIOBS | ai_obstacle_data | (observed: r=-3 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| ARM | arm_alarm | {m:'s', t:'ARM', d:{value}} | APK-KNOWN |  |
| CFG | all_keys_cfg | {d: {AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG, LIT, LOW, MSG_ALERT, PATH, PRE, PROT, REC, STUN, TIME, VER, VOICE, VOL, WRF, WRP}} | WIRED |  |
| CHECK | self_check_command | {m:'s', t:'CHECK', d:{mode, status}} | APK-KNOWN |  |
| CMS | consumables_individual | {value: [blade_min, brush_min, robot_min, aux_min]} | WIRED |  |
| DEV | device_info | {fw, mac, ota, sn} | WIRED |  |
| DOCK | dock_state_and_position | {dock: {connect_status, in_region, x, y, yaw, near_x, near_y, near_yaw, path_connect}} | WIRED |  |
| IOT | iot_connection_status | {status: bool} | APK-KNOWN |  |
| LOCN | dock_gps_origin | {pos: [lon, lat]} | WIRED |  |
| MAPD | map_data | (observed: r=-3 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| MAPI | map_info | (observed: r=-3 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| MAPL | map_list | [[int×5], [int×5]] (2 rows × 5 cols) | APK-KNOWN |  |
| MIHIS | lifetime_mowing_aggregates | {area, count, start, time} | WIRED |  |
| MISTA | mission_status | {fin: int (centiares mowed), prg: int (basis points = round(fin*10000/total)), status: [[task_type, sub_state]], total: int (centiares planned)} | DECODED-UNWIRED |  |
| MITRC | mission_track | (observed: r=-1 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| NET | wifi_info | {current: ssid, list: [{ip, rssi, ssid}, ...]} | WIRED |  |
| OBS | obstacle_data | (observed: r=-3 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| PIN | pin_status | {result, time} | APK-KNOWN |  |
| PRE | preference_endpoint | (observed: r=-3 on individual fetch in all 3 dumps; SAME-NAMED key in cfg_keys IS readable via all-keys CFG) | APK-KNOWN |  |
| PREI | preference_info | {type, ver: [[zone_id, ver], ...]} | APK-KNOWN |  |
| REMOTE | remote_control_settings | {remote: {}} | APK-KNOWN |  |
| RPET | rain_protection_end_time | {endTime: int} | APK-KNOWN |  |
| WINFO | app_weather_info | {m:'s', t:'WINFO', d:{appWeather}} | APK-KNOWN |  |

### AIOBS — `ai_obstacle_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. Previously concluded `not_on_g2408: true`, but MISTA
reversed that conclusion when it flipped from r=-3/r=-1 to a
successful payload between dump 2 and dump 3 — establishing
that error responses are stateful or transient, not negative
proof of firmware support. With only 3 data points this row
is downgraded to `decoded: hypothesized` and
`not_on_g2408: false`.

**Open questions:**
- Capture this endpoint during an AI-obstacle detection event (s1p53 transition).
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX AIOBS`

### ARM — `arm_alarm`

Arm/disarm the anti-theft alarm. Apk SET command at setArm sends
{m:'s', t:'ARM', d:{value}} to enable or disable the device alarm.
Distinct from ATA (Anti-Theft Alarm configuration) and STUN (Auto
Recharge After Extended Standby).

Likely overlaps with or complements the PIN lock system. Never directly
observed on g2408; the Dreame app exposes this via Security settings.
The payload value enum is unknown (0=disarm, 1=arm is the likely mapping).

**Open questions:**
- value enum: 0=disarm, 1=arm? Or is there a third state (e.g., partial-arm)?
- How does ARM interact with ATA and PIN? Are they layered or mutually exclusive?

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle ARM setArm`

### CFG — `all_keys_cfg`

The all-keys CFG fetch — getCFG t:'CFG' returns the full 24-key
settings dict. This is the primary mechanism for reading all CFG
keys in a single call; individual keys are documented in the
cfg_keys section. Already wired via cfg_action.py.
Sample: full dict with 24 keys as documented in cfg_keys section.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §getX CFG`

### CHECK — `self_check_command`

Self-check / diagnostics trigger. Apk-documented SET command at L176631:
setSelfCheck sends {m:'s', t:'CHECK', d:{mode, status}} to launch the
self-diagnostic sequence. The result arrives on s2p58 (siid:2 piid:58)
as {d:{mode, id, result}}.

Never wired in the integration — the Dreame app's Self-Diagnosis flow
is the primary user surface. Not a GET (no read endpoint). The paired
subscribe slot is s2p58.

mode and status semantics for the d-field are unknown; presumably
mode selects which subsystem to check (motor, blades, sensors, etc.)
and status starts or cancels the check.

**Open questions:**
- What values does mode take for each subsystem check on g2408?
- Trigger from Maintenance → Self-Diagnosis in Dreame app and capture s2p58 result.

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle CHECK setSelfCheck`

### CMS — `consumables_individual`

Consumables wear meters via the individual endpoint — same data as
CFG.CMS but wrapped in {value: [...]}. Not separately wired;
integration reads CMS data via the all-keys CFG fetch.
Sample: {value: [3084, 0, 0, -1]}.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX CMS`

### DEV — `device_info`

Authoritative device identifiers. Wired in v1.0.0a76. sn is the
hardware serial (replaces flaky s1p5 cloud RPC), fw is the firmware
version, mac cross-checks the cloud device record's mac, ota semantic
UNCONFIRMED (NOT the Auto-update Firmware app toggle — values
disagree). Sample: {fw: "4.3.6_0550", mac: "10:06:48:A2:5A:1B",
ota: 1, sn: "G2408053AEE0006232"}.

**Open questions:**
- ota field — NOT the Auto-update Firmware toggle; semantics unconfirmed.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX DEV`

### DOCK — `dock_state_and_position`

Dock state + map-frame position. Wired in v1.0.0a78.
connect_status:1 → mower currently in dock (authoritative — more
reliable than inferring from s2p1==6 CHARGING). in_region flips
depending on whether the dock sits inside the mowable polygon.
yaw matches compass bearing for the X-axis of the dock-relative
frame (unit unclear; near_yaw:1912 suggests possibly deci-degrees
but doesn't fit if yaw:112 is degrees). x,y = dock position in
map frame — NOT necessarily (0,0) despite earlier assumptions.
near_*/path_connect semantics still TBD.
Sample: {connect_status:1, in_region:0, x:151, y:23, yaw:112,
near_x:19, near_y:-3, near_yaw:1912, path_connect:0}.

**Open questions:**
- near_x/near_y/near_yaw — approach point for path-to-dock?
- yaw unit — degrees fits yaw:112 but near_yaw:1912 doesn't.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX DOCK`

### IOT — `iot_connection_status`

IoT cloud connection alive flag (presumed). Not wired. Semantic
unconfirmed; status:True observed when integration is online.
Sample: {status: true}.

**Open questions:**
- IOT.status — does it flip to false on cloud disconnect or always true while reachable?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX IOT`

### LOCN — `dock_gps_origin`

Dock GPS origin (not real-time mower position). Wired.
Confirmed 2026-04-27: response shape is a 2-element pos array, NOT
the iobroker-doc-implied {lon, lat} dict. Default value when dock's
GPS origin has never been written via setLOCN is [-1, -1] (sentinel
for "not configured"). Stores the dock origin, not the live mower
coordinate. The Dreame app's "real-time Google Maps view" is computed
client-side from this stored origin plus the mower's local-frame xy
plus MapHeader.heading_to_north_deg.
Sample: {pos: [-1, -1]} (not configured).

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX LOCN`

### MAPD — `map_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.

**Open questions:**
- Capture during a map-edit operation (zone create/delete) — MAPD may carry the chunked map blob.
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPD`

### MAPI — `map_info`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.

**Open questions:**
- Capture with explicit map_index argument once we identify the inbound parameter shape.
- Test with values from cfg_individual.MAPL once that endpoint stabilises.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPI`

### MAPL — `map_list`

2 rows × 5 cols. Plausibly per-map-slot metadata or active/configured
flags; needs operation-correlated capture (create/delete zone, cycle
map slots) to settle. Not wired. Sample: [[0,1,1,1,0],[1,0,0,0,0]].

**Open questions:**
- MAPL rows/cols — per-map-slot metadata? Needs create/delete zone correlation.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPL`

### MIHIS — `lifetime_mowing_aggregates`

Authoritative lifetime mowing aggregates matching the app's Work Logs
header exactly. Wired in v1.0.0a79/a80. area = total m², time =
total minutes, count = sessions, start = unix timestamp of first
cleaning (origin unclear; user's value 1704038400 predates ownership
by 2+ years — possibly factory test mow or firmware default;
investigation TBD). Sample: {area:4745, count:34, start:1704038400,
time:3134}.

**Open questions:**
- MIHIS.start timestamp origin — factory test mow or firmware default? Predates ownership.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MIHIS`

### MISTA — `mission_status`

Current mission status — cloud-poll mirror of s1p4 33-byte
telemetry's area counters. Decoded 2026-05-06 by cross-correlating
7 cloud dumps with 120 s1p4 33-byte MQTT frames during the run
that started 17:47 (MQTT log: probe_log_20260419_130434.jsonl).

Field mapping (confirmed Δ ≤ 4 cs across all 7 paired samples,
most exact at the same wallclock second):

  - total ≡ s1p4_33b_total_area_centiares (bytes 26-27, uint16_le, ÷100 → m²)
  - fin   ≡ s1p4_33b_area_mowed_centiares (bytes 29-30, uint16_le, ÷100 → m²)
  - prg   = round(fin × 10000 / total) — basis points (per-myriad), redundant
  - status[0] = [task_type, sub_state] — same enum as s2p56

Unit: centiares (= dm² = 0.01 m² = 100 cm²). For this lawn,
total = 33900 cs = 339 m².

Net info value: strict subset of s1p4 + s2p56. No new data over
MQTT subscription; useful only when MQTT is unavailable or one
wants a single-poll progress probe.

Pollability quirk: returns r=-1 / r=-3 when mower is fully idle
(2026-05-04, 2026-05-05 morning dumps). Returns r=0 with
all-zeros {fin:0, prg:0, status:[[1,-1]], total:0} in
primed-but-not-running state. Returns r=0 with live counters
only when actively mowing. Use as a "mower running?" probe.

Envelope: m:"r" (response method), q (link/RSSI proxy 70-80
observed during run), r:0 (OK code).

**Open questions:**
- Worth wiring as axis-4 sensor when MQTT unavailable? Otherwise redundant with s1p4 + s2p56.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MISTA`

### MITRC — `mission_track`

APK-documented endpoint (apk-named "Mission Track" — likely
carries live trail / completed track). The 3 cloud dumps so far
all returned r=-1. r=-1 is empirically NOT proof of feature
absence — sibling MISTA flipped from r=-1 to a successful
payload between dump 2 and dump 3. Downgraded to
`decoded: hypothesized` pending further evidence.

**Open questions:**
- Capture during an active mowing session — MITRC is apk-named 'mission tracking', likely carries live trail.
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MITRC`

### NET — `wifi_info`

Currently-associated AP and per-AP last-seen RSSI. Wired in
v1.0.0a77 — populates wifi_ssid / wifi_ip and seeds wifi_rssi_dbm
at startup before s1p1 byte[17] live RSSI takes over.
Sample: {current:"T55", list:[{ip:"10.0.0.128", rssi:-66, ssid:"T55"}]}.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX NET`

### OBS — `obstacle_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.

**Open questions:**
- Capture immediately after an obstacle event (s1p53 True transition).
- Cross-reference with AIOBS — both apk-described as obstacle endpoints, semantics distinct.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX OBS`

### PIN — `pin_status`

Likely the lift-lockout PIN-state flow: result:0 = no PIN-required
event pending, time:0 = no last-PIN-entry timestamp. Partial
documentation in §3.4 byte[10] bit 1. Not wired.
Sample: {result:0, time:0}.

**Open questions:**
- PIN.result and PIN.time — exact semantics of the lift-lockout flow TBD.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PIN`

### PRE — `preference_endpoint`

APK-documented endpoint. The individual `getCFG t:'PRE'` fetch
returns r=-3 in all 3 cloud dumps so far, but the **all-keys**
CFG fetch (`getCFG t:'CFG'`) DOES return a `PRE` key with the
[zone_id, mode] 2-element list (see `cfg_keys.PRE`). So the
data exists on g2408 — only the individual-target fetch path
doesn't work. This is a clear case where r=-3 isn't proof of
feature absence; it just means "this endpoint name doesn't
accept the individual-fetch form on this firmware". Could also
be the same data via two different paths, or a different
endpoint that happens to share a name. `decoded: hypothesized`
because we haven't confirmed individual-fetch will never work;
with only 3 dumps the sample is too small.

**Open questions:**
- Reconcile with cfg_keys.PRE: same name, different access paths. Same data via different paths, or different endpoints with shared name?
- Test whether the individual-fetch starts working in later dumps (cf. MISTA flip).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PRE`

### PREI — `preference_info`

Preference info. type:0 observed. ver is a two-row version array —
likely per-PRE-row config-version counter. ver:[[0,78],[1,3]] means
zone 0 at version 78, zone 1 at version 3. Not wired.
Sample: {type:0, ver:[[0,78],[1,3]]}.

**Open questions:**
- PREI.type field — purpose unknown; observed always 0.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PREI`

### REMOTE — `remote_control_settings`

Remote-control settings GET. Apk-documented at L176199 as
getRemote = {m:'g', t:'REMOTE'}. Stored in the app's settings object
as remote:{} (L182984). The exact fields of the remote settings dict
are unknown — likely includes default cutting height and camera state
for joystick sessions.

Paired with SET commands via o:15 (remote_setting opcode). The GET
is used by the app to initialize the remote-control UI with persisted
defaults. Not wired in the integration.

**Open questions:**
- What fields does the remote settings dict contain? Height, camera, max-speed?

**See also:** `apk: ioBroker.dreame/apk.md §Remote Control getRemote L176199`

### RPET — `rain_protection_end_time`

Possibly schedule repeat-end timestamp or rain-protection-end
timestamp (0 = no end / not active). Not wired.
Sample: {endTime: 0}.

**Open questions:**
- RPET.endTime — rain-protection-end unix timestamp or schedule repeat-end? Needs non-zero capture.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX RPET`

### WINFO — `app_weather_info`

App-to-device weather push. Apk SET command sends the current app-side
weather observation to the mower firmware so it can make local rain-
protection decisions without a separate cloud weather lookup. Distinct
from WRP (rain protection settings) and the s2p2=56 rain-protection-
active signal.

No corresponding GET; this is a one-way app→device push. The appWeather
payload shape is not fully documented in the apk.

Never directly observed on g2408; fired by the app automatically when
it detects rain conditions or on a periodic sync interval.

**Open questions:**
- What is the appWeather payload shape? Temperature, precipitation, forecast array?
- How does firmware use appWeather vs internal rain sensor?

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle WINFO setAppWeather`

## Heartbeat (s1p1) bytes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1_b0 | frame_delimiter_start | byte (likely 0xCE) | WIRED |  |
| s1p1_b1_bit0 | bumper_hit | single bit | WIRED | bool (×1.0) |
| s1p1_b1_bit1 | drop_tilt | single bit | WIRED | bool (×1.0) |
| s1p1_b2_bit1 | lift | single bit | WIRED | bool (×1.0) |
| s1p1_b3_bit7 | lift_lockout_pin_required | single bit | WIRED | bool (×1.0) |
| s1p1_b4 | human_presence_detection | byte | WIRED | byte (×1.0) |
| s1p1_b5 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b6_bit3 | charging_paused_batt_temp_low | single bit | WIRED | bool (×1.0) |
| s1p1_b7 | state_transition_marker | byte | WIRED | byte (×1.0) |
| s1p1_b8 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b9 | mow_start_pulse | byte | WIRED | byte (×1.0) |
| s1p1_b10_bit1 | safety_alert_active | single bit | WIRED | bool (×1.0) |
| s1p1_b10_bit7 | batt_temp_low_latched | single bit | WIRED | bool (×1.0) |
| s1p1_b11_b12 | monotonic_counter | uint16_le (bytes [11-12]) | WIRED | count (×1.0) |
| s1p1_b13 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b14 | startup_state_machine | byte | WIRED | byte (×1.0) |
| s1p1_b15 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b16 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b17 | wifi_rssi_dbm | byte (signed int8) | WIRED | dBm (×1.0) |
| s1p1_b18 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b19 | frame_delimiter_end | byte (likely 0xCE) | WIRED |  |

### s1p1_b0 — `frame_delimiter_start`

Start-of-frame delimiter. Hypothesised 0xCE by analogy with
s1p4 telemetry framing; verify against probe-log heartbeat
captures.

**Open questions:**
- Cross-check b[0] = 0xCE against probe-log heartbeat captures.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py:70`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b1_bit0 — `bumper_hit`

Bumper hit — confirmed 2026-04-30 19:37:13 against the app's
"Bumper error" notification. Important: this event has no
corresponding s2p2 transition — it surfaces only via this bit.
Wire mask: byte[1] & 0x01.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b1_bit1 — `drop_tilt`

Drop / Robot tilted — set while the mower is held off-level.
Confirmed 2026-04-30 19:37:05 against the app's "Robot tilted"
notification; cleared at 19:37:13 when the mower was set back
down. Wire mask: byte[1] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b2_bit1 — `lift`

Lift / Robot lifted — confirmed 2026-04-30 19:37:57 against the
app's "Robot lifted" notification. Wire mask: byte[2] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b3_bit7 — `lift_lockout_pin_required`

Lift lockout / PIN required (the app calls this "Emergency stop
is activated"). Set on lift OR top-cover-open; cleared ONLY by
typing the PIN on the device. Re-confirmed 2026-05-04 across a
5-test controlled series: the bit clears ONLY on PIN entry; lid
close, set-down, or any other physical-state restoration does NOT
clear it. Smoking-gun was the dock-only test (lid open → lid
close, NO PIN typed) where the bit stayed asserted after the lid
closed. Then a follow-up test where the user opened lid → typed
PIN → closed lid showed byte[3] cleared at PIN time (lid still
open), confirming the trigger is the PIN, not the lid.
Wire mask: byte[3] & 0x80.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b4 — `human_presence_detection`

Human-presence-detection pulse. Pulses 0x00 → 0x08 → 0x00
lasting ~0.8 s during a human-presence-detection event.
Evidence: session 2 (2026-04-18) showed byte[4]=0x08 exactly
twice at 21:04:39.580 and 21:04:40.210; the user confirmed the
Dreame app raised a human-in-mapped-area alert at that same
moment. Byte is 0x00 at all other times across the whole session.
Single-event datapoint — reproduce before relying on it.

**Open questions:**
- Single-event datapoint. Reproduce with a controlled human-in-zone test to confirm 0x08 is the canonical sentinel value.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b5 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b6_bit3 — `charging_paused_batt_temp_low`

Charging paused — battery temperature too low. Asserted while
the mower is docked but refusing to charge because the battery
is below its safe-charge threshold; clears when the cell warms
up (or momentarily, while the charger retries). Evidence:
2026-04-20 the Dreame app raised "Battery temperature is low.
Charging stopped." at 06:25 and 07:54; at 06:25:42 byte[6] went
0x00 → 0x08 coincident with s2p2 dropping from 48 to 43; at
07:54:39 byte[6] flipped 0x08 → 0x00 → 0x08 → 0x00 while the
mower bounced STATION_RESET ↔ CHARGING_COMPLETED. Cleared to 0
once charging resumed around 07:58 and stayed 0 through the
following mowing session. Wire mask: byte[6] & 0x08.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b7 — `state_transition_marker`

State transition marker. Values: 0=idle, 1 or 4 = state
transitions. Exact semantics of 1 vs 4 not yet pinned down.
Decoded by the integration as state_raw on the Heartbeat
dataclass.

**Open questions:**
- Distinguish the semantic difference between value 1 and value 4; correlate with specific s2p1/s2p2 transitions.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b8 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b9 — `mow_start_pulse`

0/64 pulse at mow start. Pulses from 0 to 64 and back to 0
at the beginning of a mowing session. Exact timing relative to
s2p2/s2p1 transitions not yet pinned down. Single-class
datapoint.

**Open questions:**
- Is value 64 specific to mowing start or does it appear in other session types (BUILDING, edge)?

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b10_bit1 — `safety_alert_active`

One-shot active-alert flag (paired with the Dreame app's
"Emergency stop activated" push notification + the mower's red
LED + voice prompt). Pinned down 2026-05-04 across a 5-test
controlled series: sets ~1 s after byte[3] bit 7 sets (shortly
after the safety event); self-clears 30–90 s later regardless
of state — including while the lid is still open and PIN has not
been entered. Variable timer (4/18/33/53/77 s observed) suggesting
it is reset by sensor activity or an internal alert-window timer,
not a fixed value. NOT a "PIN-acceptance secondary latch" as the
earlier hypothesis claimed — the smoking-gun was the dock-only
test where byte[10] cleared at 20:20:24 with the lid still open
and no PIN ever typed. Independent of the byte[3] bit 7 lockout
(which only clears on PIN). The base 0x80 bit (latched low-temp
flag) stays asserted independently; only bit 1 is the alert.
Surfaced as binary_sensor.safety_alert_active.
Wire mask: byte[10] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b10_bit7 — `batt_temp_low_latched`

Latched battery-temp-low flag. Set after the first low-temp
charging-pause event of the day; remains set for the rest of
the session regardless of subsequent charge-resume. Observed to
set at 06:25:42 together with byte[6]=0x08 and remain 0x80
through the 07:54 re-trigger, the 07:58 mowing start, and every
subsequent heartbeat in the session. Normal value at a cold-boot
idle charge is 0x00 (confirmed: 2026-04-19 13:04–14:29 all show
byte[10]=0). Best guess: "battery-temp-low event has occurred
since last power-cycle" maintenance flag. Cleared state
unconfirmed (reproduce with a fresh boot after a warm day).
Wire mask: byte[10] & 0x80.

**Open questions:**
- When does this bit clear? Hypothesis is power-cycle reset — needs a warm-day fresh-boot capture to confirm.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b11_b12 — `monotonic_counter`

Monotonic counter, little-endian u16 spanning bytes [11-12].
Increments with each heartbeat emission. Used by the integration
to detect duplicate or out-of-order heartbeat deliveries. Decoded
via struct.unpack_from("<H", data, 11).

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b13 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b14 — `startup_state_machine`

Startup state machine byte. Transitions through a fixed sequence
during device boot: 0 → 64 → 68 → 4 → 5 → 7 → 135. Steady-state
value after full boot is 135. Useful for detecting incomplete
startup or firmware boot stall (e.g. mower stuck at 64 would
indicate a boot-loop).

**Open questions:**
- Are all 7 states observed on every cold boot, or is the sequence firmware-version dependent?

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b15 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b16 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b17 — `wifi_rssi_dbm`

WiFi RSSI in dBm as a signed byte (b if b<128 else b−256).
Tracks the live signal to the currently associated AP. Confirmed
2026-04-30 20:09–20:16 by toggling APs and watching the app's
5-stage signal line move in lockstep: 0xBD = −67 dBm ("Strong"),
0xA8 = −88 dBm ("Weak" after killing closest AP and the mower
fell back to a more distant one), 0xC0 = −64 dBm (snapped onto
closer AP after restoration), 0x9F = −97 dBm (briefly during
dropout). No special "disconnected" sentinel observed — value
just keeps tracking whatever the radio detects.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b18 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b19 — `frame_delimiter_end`

End-of-frame delimiter. Hypothesised 0xCE by analogy with
s1p4 telemetry framing; verify against probe-log heartbeat
captures. Confirmed by the decode_s1p1 guard in heartbeat.py
which checks data[-1] == FRAME_DELIMITER (0xCE).

**Open questions:**
- Cross-check b[19] = 0xCE against probe-log heartbeat captures.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

## Telemetry (s1p4) fields

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_8b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_8b_x_mm |  | 20-bit signed; SAME decoder as 33-byte x_mm | WIRED | m (×0.001) |
| s1p4_8b_y_mm |  | 20-bit signed; SAME decoder as 33-byte y_mm | WIRED | m (×0.001) |
| s1p4_8b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_8b_heading_byte |  | byte | WIRED | degrees (×1.4117647) |
| s1p4_8b_delim_end |  | byte (0xCE) | WIRED |  |
| s1p4_10b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_10b_x_cm |  | int16_le | WIRED | m (×0.01) |
| s1p4_10b_y_mm |  | int16_le | WIRED | m (×0.001) |
| s1p4_10b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_10b_unknown_6_7 |  | uint16_le (observed 5570 = 0x15C2) | SEEN-UNDECODED |  |
| s1p4_10b_static_b8 |  | byte (0x00) | SEEN-UNDECODED |  |
| s1p4_10b_delim_end |  | byte (0xCE) | WIRED |  |
| s1p4_33b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_33b_x_mm |  | 20-bit signed; x = (b[2]<<28 | b[1]<<20 | b[0]<<12) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_y_mm |  | 20-bit signed; y = (b[4]<<24 | b[3]<<16 | b[2]<<8) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_33b_sequence |  | uint16_le | WIRED |  |
| s1p4_33b_start_index |  | uint24_le | WIRED |  |
| s1p4_33b_phase_raw |  | uint8 | WIRED |  |
| s1p4_33b_static_b9 |  | byte (0x00) | WIRED |  |
| s1p4_33b_delta_1 |  | 2 × int16_le (dx1, dy1) | WIRED |  |
| s1p4_33b_delta_2 |  | 2 × int16_le (dx2, dy2) | WIRED |  |
| s1p4_33b_delta_3 |  | 2 × int16_le (dx3, dy3) | WIRED |  |
| s1p4_33b_flag_22 |  | byte | WIRED |  |
| s1p4_33b_flag_23 |  | byte | WIRED |  |
| s1p4_33b_distance_dm |  | uint16_le; value / 10 → m | WIRED | m (×0.1) |
| s1p4_33b_total_area_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b28 |  | byte (0x00 on small lawns) | WIRED |  |
| s1p4_33b_area_mowed_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b31 |  | byte (0x00 on small lawns) | WIRED |  |
| s1p4_33b_delim_end |  | byte (0xCE) | WIRED |  |

### s1p4_8b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_8b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. During idle/docked the value converges
near 0. During BUILDING sessions it tracks live mower X position as the
mower traces the new boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. Leg-start preamble frames carry a
near-0xFFFF sentinel Y (the mower hasn't localised yet). BUILDING
frames carry live real Y coordinates as the mower traces the boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_static_b5 — ``

Static 0x00 byte. Present in all 8-byte captures including BUILDING mode.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:162`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_8b_heading_byte — ``

Mower heading in the dock-relative frame. Confirmed 2026-04-24 with
heading_correlate.py: compared 5,586 consecutive-pair samples from
probe_log_20260419_130434.jsonl — computed motion direction atan2(dy,dx)
vs byte[6]/255*360 decode. Result: median angular error 13°, 54% of
samples under 15° error, 67% under 30°. Clear central peak at 0-14°;
diffuse tail at pivot turns where atan2 is ill-conditioned (position
barely moves between frames). Leg-start preamble values (123-125) are
consistent with "~180° = mower facing away from dock while leaving".
Surfaced as sensor.heading_deg.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose (angle field)`

### s1p4_8b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_x_cm — ``

X position at the moment the zone-save event fired. Likely same
dock-relative coordinate frame as the 8/33-byte variants. Single
capture only (2026-04-20 17:03:41, sample byte sequence
[0xCE, 139, 0, 240, 77, 0, 194, 21, 0, 0xCE]).

**Open questions:**
- Does [1-2] use int16_le or the same 20-bit packed decode as the 8/33-byte frames? Only 1 sample — needs more BUILDING captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_y_mm — ``

Y position at the zone-save moment. Sample value 19952 mm is consistent
with the mower being on the far side of the lawn during BUILDING.
Decoder provisional — only one capture available.

**Open questions:**
- Verify y decode on a second BUILDING capture.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_static_b5 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_unknown_6_7 — ``

Unknown uint16 at the zone-save moment. Observed 0x15C2 = 5570 on
2026-04-20 in the single capture. Candidates: sequence counter for the
new polygon's perimeter points, zone-id assigned by the firmware, or
a general capture-sequence counter. Needs more BUILDING sessions to
disambiguate.

**Open questions:**
- Decode bytes [6-7] — point count? zone id? sequence counter? Correlate with number of 8-byte frames in the preceding BUILDING session.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_static_b8 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_33b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:193`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm).
Origin (0,0) = charging station. +X points toward the house (mower's
nose direction when docked); -X points into the lawn. X is in cm on
the old int16 layout; the 20-bit decode and ×10 scaling unifies both
axes to mm. See §3.1 coordinate-frame notes. apk-corrected decoder
landed in alpha.98.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm).
±Y is perpendicular to the X axis (left/right when facing the house).
Y-axis calibration: tape-measure-verified 0.625 factor (encoder
over-reports by ~1.6×); factor is per-install configurable. Confirmed
alpha.98 via full probe-corpus replay (14.7k frames).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_static_b5 — ``

Static 0x00 byte between the packed XY block and the sequence field.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:188`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_sequence — ``

Path-point sequence number (lower 16 bits of the uint24 start_index at
bytes [7-9]). Frame-over-frame increments monotonically; used by the
integration to detect skipped frames. Part of the start_index field
documented in apk §parseRobotTrace — the full counter is at bytes [7-9].

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_start_index — ``

Path-point sequence counter (uint24 LE). Confirmed on g2408: one-off
script over 14,684 consecutive-frame transitions found 5,796 increments
vs only 10 decrements; 10 decrements all look like new-session resets.
Zero INT24-MAX saturation. Distribution concentrated in 0..10k per
session. Matches apk §parseRobotTrace "uint24 LE path-point sequence
id" exactly.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_phase_raw — ``

Index into the firmware's pre-planned job sequence. NOT a mowing/transit
enum — confirmed 2026-04-18 via live trajectory across a 3-hour session.
Phase advances monotonically through the plan; once a value is done it
never repeats in the same session.

Session 2 observations: phase 1=dock transit corridor, 2=zone area-fill
(west), 3=zone area-fill (middle), 4=zone area-fill (east), 5=edge mow,
6-7=next edge/zone passes. phase=15 observed in last 23 frames of
2026-04-20 full-run (post-complete return, counters frozen).

Current Phase enum labels (MOWING/TRANSIT/PHASE_2/RETURNING) are
placeholder and should be retired. Expose as task_phase diagnostic
sensor. Multiple values per session are normal.

**Open questions:**
- Values 8-14 unobserved — are they edge-variant indices on denser lawns or post-complete transport codes?
- Legacy protocol/trail_overlay.py used phase ∈ {1,3} to colour transit segments TRANSIT_COLOR (blue) vs mowing (dark grey); greenfield retired the entire phase-based colouring in favour of area-counter delta discrimination (live_map.py:147-152). Re-evaluate whether phase-byte colouring should be reinstated during axis 4 map-display work.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_static_b9 — ``

Static 0x00 byte separating phase_raw from the delta block.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:188`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_delta_1 — ``

First path-history delta (Δ1). Carries the offset from the current pose
to a recent prior path point. When |dx| > 32766 AND |dy| > 32766 the
Δ is ABSOLUTE (not relative) — the apk sentinel for relocalisation /
run-start jumps. Confirmed via ±INT16 saturation pattern across 14.6k
frames (motion_vectors_correlate.py).

Apk §parseRobotTrace: each 33-byte frame carries current pose PLUS
3 path-point offsets — so the integration receives 4 points per frame
without waiting for frame N+1.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_delta_2 — ``

Second path-history delta (Δ2). Same sentinel rule as delta_1:
|dx|>32766 AND |dy|>32766 → ABSOLUTE. Caveat: Δ2 saturates more
regularly than Δ1/Δ3 during steady motion (often (+INT16_MAX,
-INT16_MIN)) — may be a reserved slot on g2408 where only Δ1+Δ3
carry real data, or a different sentinel semantic than described in
the apk. Full path-history decode validation needed before shipping
a decoder change (see §3.1 validation steps).

**Open questions:**
- Δ2 saturates more than Δ1/Δ3 — reserved slot or different sentinel? Validate with mid-session frame plot against known path.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_delta_3 — ``

Third path-history delta (Δ3). Same sentinel rule as delta_1/delta_2.
Δ1.dx and Δ3.dx are often nearly equal magnitude in steady-motion
captures (−267 vs −262 mm/frame), suggesting Δ1/Δ3 may point to the
same prior point under different references, or the Δ ordering is
different on g2408 vs the apk description. Validated against 14.6k
frames — saturation pattern matches the apk sentinel.

**Open questions:**
- Δ1.dx ≈ Δ3.dx in steady motion — are Δ1/Δ3 pointing to the same prior point, or is the oldest→newest ordering different on g2408?

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_flag_22 — ``

Initialisation-complete flag. Observed 0 at session start, transitions
to 1 after initialisation. Value stays 1 throughout the mowing session.

**Open questions:**
- What triggers the 0→1 transition exactly? Is it localisation-complete or first-pose-published?

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:239`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_flag_23 — ``

Observed constant value 2 across all captures. Likely a protocol-version
or frame-type marker. Not known to change.

**Open questions:**
- Does byte[23] ever differ from 2? If always 2, it may be a frame-format version constant.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:239`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_distance_dm — ``

Total distance driven in the current session, in decimetres (raw ÷ 10 → m).
Resets at session start. Ticks forward whenever the mower moves —
including blades-up transit legs. Frame-to-frame delta can detect
motion (non-zero) vs stationary. Used alongside area_mowed_cent for
blades-on/off detection (both counters tick when cutting, distance
alone ticks on transit).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_total_area_centiares — ``

Total mowable lawn area for the active session, INCLUDING area under
exclusion zones (user-confirmed 2026-04-25). area_mowed_cent plateaus
at (total - excluded), not at total. Resets each session. The apk
documents this as uint24 at bytes [26-28]; byte [28] is currently
treated as static on g2408 (small lawns keep it at 0x00).

**Open questions:**
- Switch to apk's uint24 decode for lawns > 655 m²; currently uint16 + static high byte.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b28 — ``

High byte of the apk-documented uint24 total_area field at [26-28].
Treated as static (0x00) on the user's ~384 m² lawn where the uint16
[26-27] suffices. For lawns > 655 m² this byte will be non-zero and
must be included in the decode. See open question on total_area_centiares.

**Open questions:**
- Confirm byte[28] is non-zero on lawns > 655 m²; needs a contributor with a larger install.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:243`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_area_mowed_centiares — ``

Area mowed with blades down in the current session. Ticks ONLY when
blades are physically cutting (confirmed 2026-04-22 20:47-20:50: stayed
flat during dock-exit transit, started ticking the moment cutting
began). Used as the primary blades-on/off detector in
live_map.DreameA2LiveMap._handle_coordinator_update (each captured
path point tagged with cutting=1 if this counter ticked). Apk documents
as uint24 [29-31]; byte [31] currently static on g2408 small-lawn
captures.

**Open questions:**
- Switch to uint24 decode [29-31] for lawns where mowed area > 655 m².

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b31 — ``

High byte of the apk-documented uint24 area_mowed field at [29-31].
Treated as static (0x00) on the user's lawn. Non-zero for installs
where the mowed area exceeds 655 m² in a single session.

**Open questions:**
- Confirm byte[31] is non-zero on large-lawn installs (mowed area > 655 m² per session).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:244`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:195`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

## Telemetry frame variants

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_7b | unknown_g2568a_variant |  | APK-KNOWN |  |
| s1p4_8b | beacon |  | WIRED |  |
| s1p4_10b | building_save_marker |  | WIRED |  |
| s1p4_13b | unknown_other_model_variant |  | APK-KNOWN |  |
| s1p4_22b | unknown_other_model_variant_22 |  | APK-KNOWN |  |
| s1p4_33b | mowing_telemetry_full |  | WIRED |  |
| s1p4_44b | unknown_other_model_variant_44 |  | APK-KNOWN |  |

### s1p4_7b — `unknown_g2568a_variant`

Documented in apk for g2568a and other Dreame mower/vacuum models.
Never observed in any g2408 capture. If a future g2408 firmware update
or a different region variant surfaces this length, the integration
emits a one-shot [PROTOCOL_NOVEL] s1p4 short frame len=7 WARNING with
raw bytes.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_8b — `beacon`

Position-only beacon variant. Emitted in four situations on g2408:
(1) idle/docked/remote-control, (2) start-of-leg preamble (~37-45 s
after each s2p1→1, three consecutive frames observed 2026-04-20 before
33-byte stream resumed), (3) throughout BUILDING sessions (47 frames
at 5 s cadence during 2026-04-20 17:00-17:04), (4) post-FTRTS
dock-navigation phase (confirmed 2026-05-05: ~25 frames over ~90 s
when s2p65='TASK_NAV_DOCK' fires). Carries XY + heading byte; no
phase/area/distance fields.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b — `building_save_marker`

Fires exactly once per BUILDING session at the moment the new zone is
saved — confirmed 2026-04-20 17:03:41 coincident with the first
s1p50={} in that second. All other 47 frames of that BUILDING session
were 8-byte beacons. Bytes [6-7] carry an unidentified uint16
(observed 5570 = 0x15C2 — possibly point-count, zone-id, or sequence
counter).

**Open questions:**
- Decode bytes [6-7] — point count? zone id? sequence counter?
- Confirm this fires on every BUILDING session, not just map expansions.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:162`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_13b — `unknown_other_model_variant`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_22b — `unknown_other_model_variant_22`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_33b — `mowing_telemetry_full`

Full mowing-session telemetry. Used throughout an active TASK including
auto-recharge return legs. Carries position (20-bit packed XY),
path-history deltas (Δ1/Δ2/Δ3), phase index, sequence counter, distance
driven, total lawn area, and area mowed (blades-down). Switches to the
8-byte beacon at session boundaries and during BUILDING.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_44b — `unknown_other_model_variant_44`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

## s2p51 multiplexed-config shapes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p51_ai_obstacle_photos |  | {value: 0|1} | WIRED |  |
| s2p51_ambiguous_4list |  | {value: [b, b, b, b]} | WIRED |  |
| s2p51_ambiguous_toggle |  | {value: 0|1} | WIRED |  |
| s2p51_anti_theft |  | {value: [lift_alarm, offmap_alarm, realtime_location]} | WIRED |  |
| s2p51_auto_recharge_standby |  | {value: 0|1} | WIRED |  |
| s2p51_charging_config |  | {value: [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]} | WIRED |  |
| s2p51_child_lock |  | {value: 0|1} | WIRED |  |
| s2p51_consumables_runtime |  | {value: [blades_min, brush_min, maintenance_min, link_module]} | WIRED |  |
| s2p51_dnd |  | {end: int, start: int, value: 0|1} | WIRED | HH:MM local (×1.0) |
| s2p51_frost_protection |  | {value: 0|1} | WIRED |  |
| s2p51_human_presence_alert |  | {value: [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]} | WIRED |  |
| s2p51_language |  | {text: int, voice: int} | WIRED |  |
| s2p51_led_period |  | {value: [enabled, start_min, end_min, standby, working, charging, error, reserved]} | WIRED |  |
| s2p51_low_speed_nighttime |  | {value: [enabled, start_min, end_min]} | WIRED |  |
| s2p51_msg_alert |  | {value: [anomaly, error, task, consumables]} | WIRED |  |
| s2p51_navigation_path |  | {value: 0|1} | WIRED |  |
| s2p51_rain_protection |  | {value: [enabled, resume_hours]} | WIRED |  |
| s2p51_timestamp |  | {time: unix_ts_str, tz: 'IANA_timezone'} | WIRED | ISO8601 (×1.0) |
| s2p51_voice |  | {value: [regular_notif, work_status, special_status, error_status]} | WIRED |  |

### s2p51_ai_obstacle_photos — ``

AI Obstacle Photos single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, FDP, STUN,
PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level AOP is fully decoded: 0=off, 1=on (capture photos of
AI-detected obstacles). Confirmed 2026-04-24 via isolated single-toggle.
Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_ambiguous_4list — ``

Wire-level ambiguous shape — two distinct CFG keys share this exact
payload on the wire: MSG_ALERT (Notification Preferences:
[anomaly, error, task, consumables]) and VOICE (Voice Prompt Modes:
[regular_notif, work_status, special_status, error_status]).

Both carry a 4-element list of booleans; the envelope carries no
key discriminator. The decoder emits Setting.AMBIGUOUS_4LIST and
the integration disambiguates via sensor.cfg_keys_raw._last_diff.

Discrimination from the CONSUMABLES shape (also a 4-element list)
is performed first: any element > 1 or < 0 routes to CONSUMABLES;
the remaining 4-bool list is then the ambiguous MSG_ALERT/VOICE shape.

All 8 slot semantics (4 from MSG_ALERT + 4 from VOICE) are
wire-confirmed 2026-04-30 via single-row toggles. This is a
wire-format limitation, not a missing decoder — both settings are
fully understood at the slot level (see s2p51_msg_alert,
s2p51_voice).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_ambiguous_toggle — ``

Wire-level ambiguous shape — five distinct CFG keys share this exact
payload on the wire: CLS (Child Lock), FDP (Frost Protection),
STUN (Auto Recharge Standby), AOP (AI Obstacle Photos), PROT
(Navigation Path; {0: direct, 1: smart}).

The firmware does not name the setting in the s2p51 envelope; the
envelope only carries {value: 0|1} with no key discriminator. The
decoder emits Setting.AMBIGUOUS_TOGGLE and the integration
disambiguates via sensor.cfg_keys_raw._last_diff (which names the
actual CFG key that flipped on the next CFG snapshot).

This is a wire-format limitation, not a missing decoder — every
individual setting is fully understood at the slot level (see
s2p51_child_lock, s2p51_frost_protection, s2p51_auto_recharge_standby,
s2p51_ai_obstacle_photos, s2p51_navigation_path). Membership of the
5-key set is wire-confirmed 2026-04-30 (all five individually toggled).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_anti_theft — ``

Anti-Theft Alarm. Three-element list:
  [0] lift_alarm — alarm on lift detection.
  [1] offmap_alarm — alarm when mower leaves mapped area.
  [2] realtime_location — enable real-time location sharing.
Each index ∈ {0,1}. Shape is unambiguous by list length (3-element;
distinct from LOW which is also 3-element but CFG key is different
and ATA uses security-semantics vs LOW's time-window semantics).
All three indices individually confirmed 2026-04-27 via single-slot
toggles: [0,0,0]→[1,0,0]→[1,1,0]→[1,1,1]. Disambiguated at runtime
via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_auto_recharge_standby — ``

Auto Recharge After Extended Standby single-toggle. Wire shape {value: 0|1}.
On the wire this shape is shared by four other single-bool CFG keys (CLS,
FDP, AOP, PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level STUN is fully decoded: 0=off, 1=on. Confirmed
2026-04-24 via isolated single-toggle. Disambiguated at runtime via
getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_charging_config — ``

Charging configuration. Six-element list:
  [0] recharge_pct — auto-recharge when battery drops below this percent.
  [1] resume_pct — resume mowing when battery rises above this percent.
  [2] unknown_flag — always observed =1; purpose TBD.
  [3] custom_charging — bool, enables the charging schedule window.
  [4] start_min — charging window start in minutes from midnight.
  [5] end_min — charging window end in minutes from midnight.
Shape is unambiguous by list length (6-element). Confirmed 2026-04-24.
Sample: [15, 95, 1, 0, 1080, 480] → recharge@15%, resume@95%, window
off, would-be 18:00→08:00.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_child_lock — ``

Child Lock (panel lockout) single-toggle. Wire shape {value: 0|1}.
On the wire this shape is shared by four other single-bool CFG keys
(FDP, STUN, AOP, PROT) — see s2p51_ambiguous_toggle for the
wire-level ambiguity. At the slot level CLS is fully decoded:
0=off, 1=on. Confirmed 2026-04-24 via isolated single-toggle.
Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_consumables_runtime — ``

Consumables runtime counters. Four-element list of per-consumable
elapsed runtime in minutes:
  [0] blades_min — blade runtime (threshold 6000 min ≈ 100 h).
  [1] brush_min — cleaning brush runtime (threshold 30000 min ≈ 500 h).
  [2] maintenance_min — robot maintenance runtime (threshold 3600 min ≈ 60 h).
  [3] link_module — Link Module; -1 on g2408 (integrated, no wear timer).
The app displays (threshold − counter) / threshold as remaining percent.

Wire-level disambiguation from the 4-bool MSG_ALERT/VOICE shape: any
element > 1 or < 0 routes to CONSUMABLES; otherwise the payload is the
ambiguous 4-bool list (see s2p51_ambiguous_4list).

Confirmed 2026-04-30 19:57:16 by resetting the Cleaning Brush in the
app: array changed from [3084, 3084, 0, -1] to [3084, 0, 0, -1] (only
index 1 changed). Threshold cross-check: counter 3084 ≈ 51.4 h against
100 h total gives 48.6% remaining — matches app display.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_dnd — ``

Wired in s2p51 push when user toggles DND or edits the window.
Shape is unambiguous on the wire (named keys end/start/value, not a
list — no collision with any other s2p51 shape). start/end are
minutes from midnight; the active timezone is carried by CFG.TIME
(IANA name). Confirmed via live toggle 2026-04-24.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_frost_protection — ``

Frost Protection single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, STUN,
AOP, PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level FDP is fully decoded: 0=off, 1=on. Confirmed
2026-04-24 via isolated single-toggle. Disambiguated at runtime via
getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_human_presence_alert — ``

Human Presence Detection Alert. Nine-element list:
  [0] enabled — detection on/off.
  [1] sensitivity — 0=low, 1=medium, 2=high.
  [2] standby — detect in standby scenario.
  [3] mowing — detect while mowing.
  [4] recharge — detect while recharging.
  [5] patrol — detect during patrol.
  [6] alert — emit voice prompt + in-app notification on detection.
  [7] photos — photo consent (privacy opt-in for sending captured images).
  [8] push_min — push-notification cooldown in minutes (observed: 3/10/20).
Shape is unambiguous by list length (9-element). Confirmed 2026-04-24.
Sample: [1, 1, 1, 1, 1, 1, 0, 1, 3].

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_language — ``

Language setting. Named-key dict (not a list):
  text — app/UI language index.
  voice — robot voice language index (e.g., 7 = Norwegian).
Shape is unambiguous on the wire (named keys text/voice distinguish it
from all list-shaped payloads). Confirmed 2026-04-24. Transported via
s2p51 shape {"text": N, "voice": M}; decoded as Setting.LANGUAGE.
Sample: {"text": 2, "voice": 7}.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_led_period — ``

LED / Headlight activation period. Eight-element list:
  [0] enabled — custom LED period on/off.
  [1] start_min — window start in minutes from midnight.
  [2] end_min — window end in minutes from midnight.
  [3] standby — LED on in standby scenario (bool).
  [4] working — LED on while mowing (bool).
  [5] charging — LED on while charging (bool).
  [6] error — LED on in error state (bool).
  [7] reserved — trailing toggle, app-visible; purpose unclear.
Shape is unambiguous by list length (8-element). Confirmed 2026-04-24.
Sample: [0, 480, 1200, 1, 1, 1, 1, 1] = LEDs off (custom period
disabled), would-be 08:00→20:00, all scenarios on.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_low_speed_nighttime — ``

Low-Speed Nighttime mode. Three-element list: [enabled, start_min, end_min].
enabled ∈ {0,1}; start_min and end_min are minutes from midnight.
User example: [1, 1200, 480] = enabled, 20:00 → 08:00 next day.
Shape is unambiguous by list length (3-element). Confirmed via live
toggle 2026-04-24 with CFG.LOW diff matching. start/end in
minutes-from-midnight; timezone from CFG.TIME.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_msg_alert — ``

Notification Preferences. Four-bool list:
  [0] anomaly — anomaly-type messages.
  [1] error — error messages.
  [2] task — task-related messages.
  [3] consumables — consumables messages.
Wire shape {value: [b, b, b, b]} is ambiguous with VOICE (see
s2p51_ambiguous_4list). Disambiguation requires getCFG diff via
sensor.cfg_keys_raw._last_diff on the next CFG snapshot. All four
slots individually wire-confirmed 2026-04-30 via single-row toggles.
Default: [1, 1, 1, 1] = all enabled.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_navigation_path — ``

Navigation Path single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, FDP,
STUN, AOP) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level PROT is fully decoded: 0=Direct path, 1=Smart path.
Confirmed 2026-04-24 via isolated single-toggle with cfg_keys_raw
diff: toggling Nav Path smart→direct flipped PROT 1→0 with no other
CFG key changing. Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_rain_protection — ``

Rain Protection. Two-element list:
  [0] enabled — rain protection on/off.
  [1] resume_hours — hours after rain stops before resuming mowing.
                     0 = "Don't Mow After Rain" (no auto-resume),
                     1..24 = resume N hours after rain ends.
Shape is unambiguous by list length (2-element). Confirmed 2026-04-24
via live toggle with CFG.WRP diff. Shape matches the WRP CFG key exactly.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_timestamp — ``

Timestamp heartbeat. Named-key dict overloading the s2p51 slot:
  time — string-encoded unix timestamp (seconds since epoch).
  tz — IANA timezone name matching CFG.TIME (e.g. 'Europe/Oslo').
Shape is unambiguous on the wire (named keys time/tz distinguish it
from all list-shaped and value-keyed payloads). Fires periodically as
a clock-sync or heartbeat signal; the integration uses it to confirm
the mower's configured timezone. Sample: {"time": "1714953600",
"tz": "Europe/Oslo"}.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_voice — ``

Voice Prompt Modes. Four-bool list:
  [0] regular_notif — regular notification prompts.
  [1] work_status — work status prompts.
  [2] special_status — special status prompts.
  [3] error_status — error status prompts.
Wire shape {value: [b, b, b, b]} is ambiguous with MSG_ALERT (see
s2p51_ambiguous_4list). Disambiguation requires getCFG diff via
sensor.cfg_keys_raw._last_diff on the next CFG snapshot. All eight
slot semantics (4 from MSG_ALERT + 4 from VOICE) wire-confirmed
2026-04-30. Default: [1, 1, 1, 1] = all enabled.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

## s2p2 state codes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p2_27 | IDLE |  | WIRED |  |
| s2p2_31 | FAILED_TO_RETURN_TO_STATION |  | WIRED |  |
| s2p2_33 | FAILURE_TRANSITION |  | WIRED |  |
| s2p2_37 | RIGHT_MAGNET |  | WIRED |  |
| s2p2_38 | FLOW_ERROR |  | WIRED |  |
| s2p2_39 | INFRARED_FAULT |  | WIRED |  |
| s2p2_40 | CAMERA_FAULT |  | WIRED |  |
| s2p2_41 | STRONG_MAGNET |  | WIRED |  |
| s2p2_43 | BATT_TEMP_LOW |  | WIRED |  |
| s2p2_44 | AUTO_KEY_TRIG |  | WIRED |  |
| s2p2_45 | P3V3_FAULT |  | WIRED |  |
| s2p2_46 | CAMERA_IDLE |  | WIRED |  |
| s2p2_47 | TASK_CANCELLED |  | WIRED |  |
| s2p2_48 | MOWING_COMPLETE |  | WIRED |  |
| s2p2_49 | LDS_BUMPER |  | WIRED |  |
| s2p2_50 | SESSION_STARTING_MANUAL |  | WIRED |  |
| s2p2_51 | FILTER_BLOCKED |  | WIRED |  |
| s2p2_53 | SESSION_STARTING_SCHEDULED |  | WIRED |  |
| s2p2_54 | RETURNING |  | WIRED |  |
| s2p2_56 | RAIN_PROTECTION |  | WIRED |  |
| s2p2_57 | EDGE_2 |  | WIRED |  |
| s2p2_58 | ULTRASONIC_FAULT |  | WIRED |  |
| s2p2_59 | NO_GO_ZONE |  | WIRED |  |
| s2p2_60 | FROST_SUPPRESSED_SCHEDULED |  | WIRED |  |
| s2p2_61 | ROUTE_FAULT |  | WIRED |  |
| s2p2_62 | ROUTE_2 |  | WIRED |  |
| s2p2_63 | BLOCKED_2 |  | WIRED |  |
| s2p2_64 | BLOCKED_3 |  | WIRED |  |
| s2p2_65 | RESTRICTED |  | WIRED |  |
| s2p2_66 | RESTRICTED_2 |  | WIRED |  |
| s2p2_67 | RESTRICTED_3 |  | WIRED |  |
| s2p2_70 | MOWING |  | WIRED |  |
| s2p2_71 | POSITIONING_FAILED_OR_AUTO_RECOVER |  | WIRED |  |
| s2p2_73 | TOP_COVER_OPEN |  | WIRED |  |
| s2p2_75 | ARRIVED_AT_MAINTENANCE_POINT |  | WIRED |  |
| s2p2_78 | ROBOT_IN_HIDDEN_ZONE |  | WIRED |  |
| s2p2_117 | STATION_DISCONNECTED |  | WIRED |  |

### s2p2_27 — `IDLE`

Idle — steady-state code when the mower is at rest with no active
task. Also observed transiently (emitted twice in one second) during
BT-to-cloud session hand-off windows, so it is not literal "idle" at
every occurrence. A runtime value of 27 may be a brief in-between
marker during session transitions; correlate with s2p1 to confirm.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_31 — `FAILED_TO_RETURN_TO_STATION`

Failed to return to station / idle-after-error. Two observed paths:
(a) 33→31 after a documented failure transition (positioning failed,
task-start failed). (b) 48→31 direct with no preceding 33 — the
firmware's post-edge auto-dock planner could not route home from a
stuck pose (confirmed 2026-05-05, two edge-mow runs). Recovery
requires an explicit Recharge command; the s2p50 op-code-6 echo is
unreliable, so detection relies on s2p1: 5→6 plus s3p2→1. The
integration maps this to binary_sensor.dreame_a2_mower_failed_to_
return_to_station (PROBLEM class).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_33 — `FAILURE_TRANSITION`

Failure transition — fires at the moment a task fails (positioning,
task-start, return). Precedes s2p1→2 (IDLE) and s2p2=31 by ~1 s.
The combined 33→31 pair is one of two paths into code 31; the other
is direct 48→31 after an edge-mow auto-dock failure.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_37 — `RIGHT_MAGNET`

Right magnet hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_38 — `FLOW_ERROR`

Flow error hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_39 — `INFRARED_FAULT`

Infrared sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_40 — `CAMERA_FAULT`

Camera sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_41 — `STRONG_MAGNET`

Strong magnet hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_43 — `BATT_TEMP_LOW`

Battery temperature is low; charging stopped. Drives the Dreame app
notification "Battery temperature is low. Charging stopped."
Confirmed 2026-04-20: byte[6]=0x08 in s1p1 heartbeat fires coincident
with this code. Republished on every re-entry into the condition
(each re-emission triggers a fresh app notification). Clears once
the battery warms and charging resumes.

Note: §8.3 apk catalog lists code 43 as "RTC" (clock / battery-backed
time); the wire-confirmed §4.1 semantics (low-temp charging hold) take
precedence for the g2408 model. The apk label may apply to a different
firmware variant.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_44 — `AUTO_KEY_TRIG`

Unintentional key press (auto key triggered). Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_45 — `P3V3_FAULT`

3.3 V power rail fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_46 — `CAMERA_IDLE`

Camera idle (informational). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_47 — `TASK_CANCELLED`

Scheduled task cancelled (status, not error). Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus on the g2408 (manual cancels use code 48 + s2p50
op-code 3 instead).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_48 — `MOWING_COMPLETE`

Mowing run finished cleanly. Also reused for user-cancel ("End" from
app) — distinguish via s2p50 op-code 3 (cancel echo) vs natural
completion (no op-code 3). Also precedes 48→31 on post-edge auto-dock
planner failure (the mower declares the task complete then immediately
fails to return).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_49 — `LDS_BUMPER`

Bumper / LDS event. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus
(bumper hits on the g2408 surface via s1p1 heartbeat byte[1]&0x01
with no corresponding s2p2 transition — see §5.3).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_50 — `SESSION_STARTING_MANUAL`

Session started via manual start from the app. Fires in the same
second as the cloud task envelope on s2p50. Distinct from code 53
(scheduled start). Observed during state transitions on 2026-04-29;
the §8.3 apk-decompiled enum has no name for this value — treat as a
status code rather than a fault.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_51 — `FILTER_BLOCKED`

Filter blocked — maintenance required. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_53 — `SESSION_STARTING_SCHEDULED`

Scheduled-session start — confirmed by two identical captures on
2026-04-20 (07:58:02 and 17:30:02). Fires in the same second as
s2p56→{'status':[]}, then s3p2→0 and s2p1→1 (MOWING) one second
later, then s1p50/s1p51→{} and s2p56→[[1,0]] ~40 s later. Distinct
from manual starts which emit code 50 instead. No s2p50 task-metadata
block fires on scheduled starts.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_54 — `RETURNING`

Returning to station. Fires alongside s2p1→5 (RETURNING) during
a low-battery auto-return sequence. Also listed in §8.3 as "EDGE"
(edge-mow fault) for other firmware variants; the wire-confirmed
g2408 meaning is returning-to-station.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_56 — `RAIN_PROTECTION`

Rain protection activated — water detected on the LiDAR. Fires
DURING a mowing run when precipitation is detected. Distinct from
code 60 (frost-suppressed scheduled task, which fires before a run
starts). Listed in §8.3 as "LASER (rain protection)".

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_57 — `EDGE_2`

Alternative edge-mow fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_58 — `ULTRASONIC_FAULT`

Ultrasonic sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_59 — `NO_GO_ZONE`

Reached a no-go / exclusion zone. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_60 — `FROST_SUPPRESSED_SCHEDULED`

Frost-protection-suppressed scheduled task — fires at the configured
scheduled-start time when the firmware's ambient-temperature check
refuses to launch the mow. Confirmed 2026-04-27 07:58:02. Drives
the Dreame app notification "Temperature too low. Frost Protection is
activated. The Scheduled task will start later." The mower wakes
briefly, fires this code, optionally runs a quick s1p53 obstacle-
sensor self-test pulse, then settles back to s2p1=13
(CHARGING_COMPLETED) ~10 minutes later. Distinct from code 53
(scheduled task did start) and code 56 (rain pause during a run).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_61 — `ROUTE_FAULT`

Navigation route fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_62 — `ROUTE_2`

Alternative navigation route fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_63 — `BLOCKED_2`

Obstacle blocking (variant 2). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_64 — `BLOCKED_3`

Obstacle blocking (variant 3). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_65 — `RESTRICTED`

Restricted area. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_66 — `RESTRICTED_2`

Restricted area (alternative variant). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_67 — `RESTRICTED_3`

Restricted area (second alternative variant). Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_70 — `MOWING`

Mowing in progress (edge or standard). Fires during active mowing
to indicate the current mowing phase. Transitions to code 54
(RETURNING) on low-battery auto-return.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_71 — `POSITIONING_FAILED_OR_AUTO_RECOVER`

Positioning failure or auto-recovery from idle. Two distinct
contexts: (a) Hard-stuck "Positioning Failed" — mower cannot
localize on the saved map; app shows "Positioning Failed";
recovery requires a TASK_SLAM_RELOCATE pass. Confirmed 2026-04-20
19:28:19. (b) Auto-return-from-idle — confirmed 2026-04-27
11:52:47 after BT-orphaned manual stop left the mower idle for
~55 min; code 71 fired alongside s2p1=5 (RETURNING) and the
mower self-navigated home. The two contexts are distinguished by
what follows: 33→31 means stuck (user help needed); 5→telemetry→6
means self-recovery succeeded.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_73 — `TOP_COVER_OPEN`

Top cover open — mechanical fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_75 — `ARRIVED_AT_MAINTENANCE_POINT`

Arrived at Maintenance Point — confirmed 2026-04-20 18:18:05 when
the mower reached a user-set maintenance point after tapping "Head
to Maintenance Point". Fires in the same second as s2p1→2 (IDLE),
followed by s1p52={}. No event_occured summary for Head-to-MP tasks.

Note: §8.3 apk catalog lists code 75 as "LOW_BATTERY_TURN_OFF";
the wire-confirmed §4.1 semantics (arrived at MP) take precedence
for the g2408 model.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_78 — `ROBOT_IN_HIDDEN_ZONE`

Robot in hidden zone — navigation fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_117 — `STATION_DISCONNECTED`

Station (dock) communications disconnected. Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

## s2p1 mode enum

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p1_1 | MOWING |  | WIRED |  |
| s2p1_2 | IDLE |  | WIRED |  |
| s2p1_3 | PAUSED |  | DECODED-UNWIRED |  |
| s2p1_5 | RETURNING |  | WIRED |  |
| s2p1_6 | CHARGING |  | WIRED |  |
| s2p1_11 | BUILDING |  | WIRED |  |
| s2p1_13 | CHARGING_COMPLETED |  | WIRED |  |
| s2p1_14 | UPDATING |  | APK-KNOWN |  |
| s2p1_16 | BATT_TEMP_HOLD |  | WIRED |  |

### s2p1_1 — `MOWING`

Active mowing-related task. Real mowing, head-to-maintenance-point,
and manual mode all use this value. Distinguish the specific
operation via s2p2 code (50=manual start, 53=scheduled start,
70=mid-mow) or s2p50 envelope. Fires when mowing begins and stays
set for the duration of the mowing leg.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_2 — `IDLE`

Idle — no active task, mower is at rest (on or off the dock). Used
as the post-mow settled state (after MOWING_COMPLETE), after a
task cancel, and transiently between state transitions. Also
observed immediately after arriving at the maintenance point
(fires in the same second as s2p2=75).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_3 — `PAUSED`

Pause / brief hold state. Per §2.1 apk decompilation and confirmed
in probe corpus: observed 5× across two probe log files
(2026-04-17 21:01:38, 2026-04-17 22:04:25, 2026-04-22 09:02:52,
2026-04-28 23:10:53, 2026-04-29 20:43:30), each co-incident with
s2p56 status=[[1,4]] — consistent with a sub-task transition or
a brief firmware-internal hold. The earlier hypothesis that "the
mower's pause UX folds into mode 1 with sub-state in s2p56" is
disproved by direct observation.

**Open questions:**
- What user action or firmware event triggers s2p1=3? Correlate timestamps against app UI actions.
- Is s2p56 status=[[1,4]] always co-incident or just coincidental in these 5 captures?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §s2.1 status enum`

### s2p1_5 — `RETURNING`

Returning to station. Fires during low-battery auto-return, after
user-cancel Recharge command, and during post-FTRTS dock-navigation
phases. During the post-FTRTS dock-nav path the mower emits 8-byte
beacon frames on s1p4 (not 33-byte telemetry) — see §3.2. Sequence:
MOWING(1)→IDLE(2)→RETURNING(5)→CHARGING(6) for a clean auto-return.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_6 — `CHARGING`

Charging — mower is docked and actively charging. Transitions
to CHARGING_COMPLETED (13) when full. Brief flicker entries into
BATT_TEMP_HOLD (16) are common when the battery is cold and the
charger retries (see §4.4).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_11 — `BUILDING`

Manual map-learn / zone-expand. Confirmed 2026-04-20 17:00:09
when the user triggered "Expand Lawn" from the Dreame app. The
mower left the dock, drove the new perimeter for ~4 min emitting
8-byte s1p4 frames (not 33-byte telemetry), then returned. A
single 10-byte frame fires at the exact moment the expand
completes (zone-saved marker). Sequence:
CHARGING(6)→BUILDING(11)→IDLE(2)→RETURNING(5)→CHARGING(6).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_13 — `CHARGING_COMPLETED`

Charging completed — mower is docked, battery is full, no active
task scheduled. Steady-state between mowing sessions. Also the
settled state after a frost-suppressed scheduled task (s2p2=60)
where the mower wakes briefly at schedule time and returns without
mowing.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_14 — `UPDATING`

Firmware update in progress; the mower transitions through
s2p1=14 during OTA. Per apk decompilation in §2.1.

**Open questions:**
- Confirm transition through s2p1=14 by capturing during the next firmware update.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §s2.1 status enum`

### s2p1_16 — `BATT_TEMP_HOLD`

Docked, refusing to charge because the battery is below its
safe-charge temperature. Misnamed STATION_RESET in the legacy
upstream enum (still used in lawn_mower.py for compatibility);
the actual semantics are pause-for-cold, not station-reset.
Re-confirmed 2026-04-26: 5 occurrences between 03:45–07:00
local (cold morning hours), every entry coincident with
s1p1[6]=0x08 (charging paused — temp low flag), every exit
coincident with s1p1[6]=0. Brief 2 s flicker entries common
(cold-check that immediately cleared); longer 1 h holds occur
when the cell needs to warm. Always transitions to either
CHARGING(6) or CHARGING_COMPLETED(13).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

## OSS map blob keys

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| map_key_boundary | boundary | {x1, y1, x2, y2} | WIRED |  |
| map_key_cleanPoints | cleanPoints | {dataType:'Map', value:[[pt_id, {id, type, shapeType, path:[{x,y}]}]...]} | WIRED |  |
| map_key_contours | contours | {dataType:'Map', value:[[[map_id, ?], {id, type, shapeType, path:[{x,y},...]}]]} | WIRED |  |
| map_key_cruisePoints | cruisePoints | {dataType:'Map', value:[]} | APK-KNOWN |  |
| map_key_cut | cut | [] | UNCLASSIFIED |  |
| map_key_forbiddenAreas | forbiddenAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...], angle}]...]} | WIRED |  |
| map_key_hasBack | hasBack | bool | WIRED |  |
| map_key_mapIndex | mapIndex | int | WIRED |  |
| map_key_md5sum | md5sum | hex string (MD5) | WIRED |  |
| map_key_merged | merged | bool | WIRED |  |
| map_key_mowingAreas | mowingAreas | {dataType:'Map', value:[[id, {name, path:[{x,y},...]}], ...]} | WIRED |  |
| map_key_name | name | string | WIRED |  |
| map_key_notObsAreas | notObsAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...], angle}]...]} | WIRED |  |
| map_key_obstacles | obstacles | {dataType:'Map', value:[]} | UNCLASSIFIED |  |
| map_key_paths | paths | {dataType:'Map', value:[]} | APK-KNOWN |  |
| map_key_spotAreas | spotAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...]}]...]} | WIRED |  |
| map_key_totalArea | totalArea | float (m²) | WIRED | m² (×1.0) |

### map_key_boundary — `boundary`

Axis-aligned bounding rectangle of the entire map area. Used by the integration
as the viewport extent when rendering the camera overlay image. Less detailed
than the contours polygon.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:240)`

### map_key_cleanPoints — `cleanPoints`

Maintenance Points — user-pinned markers in the app. Sample 2026-04-24 has
one entry at (2820, 12760) mm in cloud frame; the app supports multiple per
map. Consumed since alpha.91 (multi-point support since alpha.93):
sensor.maintenance_points_count carries the full list; the
dreame_a2_mower.mower_go_to_maintenance_point service selects by optional
point_id or defaults to the first point.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_contours — `contours`

Actual lawn outline polyline — 52-point polygon on a ~384 m² lawn (more
detailed than the axis-aligned boundary rectangle). Consumed since alpha.91:
drawn on the base-map PNG as a 2-px WALL outline in _build_map_from_cloud_data
so the real grass perimeter is visible over zone fills.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:230)`

### map_key_cruisePoints — `cruisePoints`

Patrol / cruise points the mower visits in sequence. Empty on all g2408
captures (value=[]). Purpose confirmed by apk; the container is present even
when empty.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `apk: ioBroker.dreame/apk.md §cruisePoints`

### map_key_cut — `cut`

Always empty on g2408 captures (bare list, no dataType wrapper). Purpose
unknown — possibly cut-line geometry for zone boundaries or a firmware
placeholder.

**Open questions:**
- Does cut ever populate? What triggers it? Is it zone-boundary cut lines or something else?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_forbiddenAreas — `forbiddenAreas`

Classic exclusion / no-go zones (red in the Dreame app). Each entry is a
[key, record] pair; shapeType=2 = rotated rectangle (path = unrotated corners,
angle = rotation degrees). id matches the s2p50 entity id from create / delete
events. Distinct from notObsAreas despite sharing the same shape.
Surfaced as sensor.exclusion_zones (state=zone count, attrs.zones=per-zone geometry).

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:211)`

### map_key_hasBack — `hasBack`

Whether this map has a "back" (secondary map layer or reverse side). Meaning
not fully confirmed on g2408; consumed by the integration's map pipeline but
effect on rendering is not surfaced to the user.

**Open questions:**
- What does hasBack=true trigger in the app? Multi-level map? Reverse traversal?

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_mapIndex — `mapIndex`

Map index — identifies which saved map this blob represents. The integration
uses mapIndex when selecting the active map for rendering.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:249)`

### map_key_md5sum — `md5sum`

MD5 checksum of the map blob, used for deduplication in the integration's
map cache. A fresh fetch returns the same md5sum if the map has not changed
since the last pull.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_merged — `merged`

Whether this map is a merged composite of multiple partial maps. Consumed by
the integration; exact semantics not verified on g2408.

**Open questions:**
- Is merged ever true on g2408? Does it relate to the Expand Lawn workflow?

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_mowingAreas — `mowingAreas`

Zone polygons — the mowable areas the user has defined. Each entry carries an
id (used in o:102 zone-mow command), a name, and a path of {x,y} vertices in
cloud frame. The integration uses these for the zone-mow service and to
annotate the camera map overlay.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:186)`

### map_key_name — `name`

Human-readable map name as set by the user in the Dreame app.

**See also:** `custom_components/dreame_a2_mower/map_decoder.py:387`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_notObsAreas — `notObsAreas`

Designated Ignore Obstacle zones (green in the Dreame app). Separate top-level
key from forbiddenAreas despite identical payload shape. Confirmed 2026-04-27.
Sample: id=101, type=10, shapeType=2 (axis-aligned, angle=0).
Rendered in green via Area.subtype="ignore" in _build_map_from_cloud_data.
Surfaced as sensor.designated_ignore_zones.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_obstacles — `obstacles`

Auto-detected runtime obstacles. Empty on g2408 captures (value=[]). Populated
during / after a mow run — not by user drawings. Not to be confused with
notObsAreas (user-drawn ignore zones).

**Open questions:**
- When does obstacles populate? Is it the AI-detected obstacle list or physical obstacle markers?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_paths — `paths`

Historical or planned mow paths. Empty on g2408 captures. Per apk cross-
reference: connection paths between zones. May populate during an active
mowing session (not verified on g2408).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `apk: ioBroker.dreame/apk.md §paths`, `github.com/antondaubert/dreame-mower (map_data_parser.py:221 — inter-zone navigation paths)`

### map_key_spotAreas — `spotAreas`

Spot-mow target zones. type=3 (WorkingMode.SPOT), shapeType=7 (axis-aligned
rectangle, no angle field). Populated lazily — may take hours to sync after a
spot mow runs. Sample: 4-corner rectangle (-360,-5320)..(-3560,-2840).
Surfaced as sensor.spot_zones.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:200)`

### map_key_totalArea — `totalArea`

Total mowable area in m² as stored in the map blob. Matches event_occured
piid 14 (total lawn area rounded int) and session-summary map_area field
to within rounding.

**See also:** `custom_components/dreame_a2_mower/map_decoder.py:522`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:247)`

## Session-summary JSON fields

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| event_s4eiid1_arg1 | event_arg_flag | int (always 100) | SEEN-UNDECODED |  |
| event_s4eiid1_arg11 | event_arg11 | int (0 or 1) | SEEN-UNDECODED |  |
| event_s4eiid1_arg13 | event_arg13_list | [] (always empty) | SEEN-UNDECODED |  |
| event_s4eiid1_arg14 | total_lawn_area_m2 | int (m² rounded) | WIRED | m² (×1.0) |
| event_s4eiid1_arg15 | event_arg15 | int (always 0) | SEEN-UNDECODED |  |
| event_s4eiid1_arg2 | end_code | int (enum) | SEEN-UNDECODED |  |
| event_s4eiid1_arg3 | area_mowed_centiares | int (centiares = m² × 100) | WIRED | m² (×0.01) |
| event_s4eiid1_arg60 | abort_reason | int (-1 or 101) | SEEN-UNDECODED |  |
| event_s4eiid1_arg7 | stop_reason | int (enum) | WIRED |  |
| event_s4eiid1_arg8 | session_start_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| event_s4eiid1_arg9 | session_summary_oss_object_key | string (OSS object key path) | WIRED |  |
| summary_areas | area_mowed_m2 | float (m²) | WIRED | m² (×1.0) |
| summary_dock | dock_pose | [x_cm, y_cm, heading_deg] | WIRED | m (×0.01) |
| summary_end | session_end_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| summary_faults | faults | [] (empty on normal completion) | UNCLASSIFIED |  |
| summary_map_area | total_lawn_area_m2 | int (m²) | WIRED | m² (×1.0) |
| summary_map_list | map_list | [{id, type, name, area, etime, time, data:[[x,y]...], track:[...]}, ...] | WIRED |  |
| summary_map_track | mow_path | [[x, y] | [2147483647, 2147483647], ...] | WIRED | m (×0.01) |
| summary_md5 | content_md5 | hex string (MD5) | WIRED |  |
| summary_mode | mode | int (enum) | WIRED |  |
| summary_obstacle | obstacle_list | [{id, type, data:[[x_cm, y_mm]...]}, ...] | WIRED |  |
| summary_pre_type | pre_type | int | UNCLASSIFIED |  |
| summary_region_status | region_status | [[zone_id, status], ...] | UNCLASSIFIED |  |
| summary_result | result | int | WIRED |  |
| summary_start | session_start_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| summary_start_mode | start_mode | int | UNCLASSIFIED |  |
| summary_stop_reason | stop_reason | int | WIRED |  |
| summary_time | duration_minutes | int (minutes) | WIRED |  |
| summary_trajectory | trajectory_list | [{id:[int, int], data:[[x, y]...]}, ...] | UNCLASSIFIED |  |

### event_s4eiid1_arg1 — `event_arg_flag`

Constant flag in every captured event_occured siid=4 eiid=1. Value always 100
across six captures. Likely a protocol version marker or a fixed flag byte.

**Open questions:**
- Does piid=1 ever differ from 100? May encode firmware version or event schema.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg11 — `event_arg11`

Binary flag. Observed values: 0 and 1 across six captures. Semantics unknown.

**Open questions:**
- What does piid=11 flag? Correlate with session type or outcome.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg13 — `event_arg13_list`

Always an empty list across all captures. Purpose unknown — possibly a
placeholder for a future extension or fault-code list.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg14 — `total_lawn_area_m2`

Total mowable lawn area in m² (rounded int). 379 pre-2026-04-18, 384 after
user added a zone in-app. Matches map_area and rounded map[0].area in the
session-summary JSON. User confirmed the lawn grew by ~5 m² when the new zone
was added.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg15 — `event_arg15`

Always 0 across all captures. Purpose unknown.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg2 — `end_code`

End-code enum. Observed values across six captures: 31, 36, 69, 128, 170, 195,
217. 36 confirmed as user-cancel (2026-04-20 18:06). Other values from natural
completions. Likely encodes finish-cause (scheduled vs manual, rain-interrupted,
normal, etc.); does NOT distinguish partial vs full coverage (confirmed: 323/384
ratio was full reachable area under an exclusion zone, not a partial run).

**Open questions:**
- Map the full enum: which value = scheduled-complete, rain-abort, fault-abort?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg3 — `area_mowed_centiares`

Area mowed this session in centiares (m² × 100). Observed values: 5232, 6647
(user-cancel at 66.47 m²), 10759, 19613, 28744, 31133. Matches the final
s1p4 area_mowed_m2 reading at session end to within recharge-leg-transit
overhead.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg60 — `abort_reason`

Abort-specific reason code. -1 on normal completion; 101 on the first
observed user-cancel (2026-04-20 18:06). The first non-(-1) value was
captured on the user-cancel run.

**Open questions:**
- Are there abort codes beyond 101? Does 101 always mean user-cancel?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg7 — `stop_reason`

Stop reason. 1 = natural completion; 3 = user-cancel (confirmed 2026-04-20
abort). Matches the stop_reason direction in the session-summary JSON (which
uses -1 for normal end — different encoding).

**Open questions:**
- Are there other stop-reason codes beyond 1 and 3 (rain, fault, etc.)?

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg8 — `session_start_unix`

Session start timestamp in Unix seconds. Confirmed: the 2026-04-20 morning
run value 1776664681 → 05:58:01 UTC = 07:58:01 local, exact match to s2p2
→ 1 at 07:58:03. The user-cancel run emitted 1776699000 = 15:30:00 UTC =
17:30:00 local — session-start, not cancel-time. Independent of end reason.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg9 — `session_summary_oss_object_key`

Path to the session-summary JSON in Aliyun OSS. Format:
ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.json.
The integration fetches this URL via cloud's getDownloadUrl
(the interim endpoint — getOss1dDownloadUrl returns 404 for this
object class) then GETs the OSS signed URL.
Fires for both natural completion and user-cancel.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### summary_areas — `area_mowed_m2`

Area mowed this session in m². Matches event_occured piid 3 (centiares ÷100)
to within recharge-leg-transit overhead.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_dock — `dock_pose`

Dock coordinates and heading in mower frame. x, y in cm; heading in degrees.
Used by the live-map overlay to position the dock icon.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_end — `session_end_unix`

Session end timestamp in Unix seconds.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_faults — `faults`

Fault list recorded during the session. Empty on normal completion.
Not yet decoded from a faulted-session capture.

**Open questions:**
- What fault objects look like? Capture during an actual fault event.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_map_area — `total_lawn_area_m2`

Total mowable lawn area in m² (rounded int). Matches event_occured piid 14.
Primary source for total_lawn_area_m2 in the integration (preferred over s2p66
which pushes infrequently).

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_map_list — `map_list`

List of map area entries. Each entry carries the zone id, type (0=lawn area,
2=exclusion zone), optional name, area in m², timing fields, a data polygon
(lawn boundary), and a track array (mow path). Exclusion zones carry a
description sub-object instead of track.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_map_track — `mow_path`

Mow path as [x, y] pairs in cm. Max-int sentinel [2147483647, 2147483647]
marks segment breaks (e.g. between mowing legs separated by a dock-recharge).
Used by LiveMapState to draw completed track segments on the camera overlay.

**Open questions:**
- Legacy live_map.py:20 defined PATH_DEDUPE_METRES = 0.2 m and skipped appending a path point if it was within 0.2 m of the last point (live_map.py:135-162), preventing micro-segment noise in the live trail. The greenfield dropped this deduplication during the rewrite. Re-evaluate during axis 4: does the session-summary track data contain enough micro-segments to warrant client-side deduplication when rendering, or is the firmware already deduping before archiving?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_md5 — `content_md5`

MD5 content hash of this session-summary JSON. Used by
SessionArchive for deduplication — re-archiving the same session
is a no-op.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_mode — `mode`

Session mode code. Value 100 observed on all captured sessions. Enum not
fully decoded.

**Open questions:**
- Does mode distinguish all-areas vs zone vs spot vs edge sessions?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_obstacle — `obstacle_list`

Physical obstacles encountered during the session. Each entry has an id,
type int, and a data polygon of [x_cm, y_mm] vertex pairs. Rendered on
the camera map overlay as obstacle polygons via LiveMapState.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_pre_type — `pre_type`

Mowing preference type. Not yet decoded from g2408 captures.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_region_status — `region_status`

Per-zone mowing status list. Each entry is [zone_id, status_int].
Status values not fully decoded.

**Open questions:**
- What status values exist? Does 0=complete, 1=skipped, 2=partial?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_result — `result`

Session result code. Value 1 observed on normal completions. Enum not fully
decoded.

**Open questions:**
- What values indicate partial coverage, rain interrupt, or error?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_start — `session_start_unix`

Session start timestamp in Unix seconds. Matches event_occured piid 8
(session-start unix timestamp) to the second. Confirmed across four session
captures 2026-04-17..2026-04-20.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_start_mode — `start_mode`

Session start-trigger mode (scheduled vs manual vs app-button etc.).
Not yet decoded from g2408 captures.

**Open questions:**
- What values distinguish scheduled, manual-app, voice, and HA-service starts?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_stop_reason — `stop_reason`

Stop reason code. -1 observed on normal session end.

**Open questions:**
- What stop_reason corresponds to user-cancel vs rain vs fault?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_time — `duration_minutes`

Session duration in minutes. No scale conversion — value is directly in minutes.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_trajectory — `trajectory_list`

High-level planning path. Each entry has a composite id (two ints) and a
data array of [x, y] waypoints. Purpose: likely the routing skeleton used
by the firmware's path planner (not the actual mow track — that is in
map[].track).

**Open questions:**
- How does trajectory differ from map[].track? Is it the pre-computed plan vs actual path?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

## M_PATH encoding

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| m_path_chunked | chunked_assembly | M_PATH.0 + M_PATH.1 + ... + M_PATH.info | WIRED |  |
| m_path_scale | coordinate_scale_x10 | [x, y] int16 pairs | WIRED | m (×0.01) |
| m_path_sentinel | segment_break_sentinel | [32767, -32768] | WIRED |  |

### m_path_chunked — `chunked_assembly`

The M_PATH live trail is chunked across multiple userdata keys with
M_PATH.info supplying the split position. Reassemble by concatenating
M_PATH.0..N in order before parsing the points array.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:129`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `apk: ioBroker.dreame/apk.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

### m_path_scale — `coordinate_scale_x10`

M_PATH coordinates are ~10× smaller than MAP.* coordinates. Multiply each
raw [x, y] value by 10 before projecting onto the map image. The scale factor
was derived from the ioBroker cross-reference; not yet independently validated
against a g2408 capture where M_PATH and MAP.* are both present.

**Open questions:**
- Validate ×10 factor against a live g2408 M_PATH + MAP capture mid-mow.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:129`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

### m_path_sentinel — `segment_break_sentinel`

Sentinel value marking a path segment break in M_PATH. Equivalent in role to
the [2147483647, 2147483647] max-int sentinel in the session-summary map[].track
array, but using 16-bit max/min values because M_PATH coordinates are 16-bit
signed integers.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:29`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

## LiDAR PCD format

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| pcd_ascii_header | pcd_ascii_header | ASCII text block terminated by 'DATA binary\n' | WIRED |  |
| pcd_data_binary | pcd_binary_body | N × bytes_per_point little-endian binary | WIRED |  |
| pcd_oss_path | pcd_oss_object_key | string (OSS object key, .bin extension) | WIRED |  |
| pcd_upload_trigger | pcd_upload_trigger | user-initiated via Dreame app 'View LiDAR Map' | WIRED |  |

### pcd_ascii_header — `pcd_ascii_header`

PCD v0.7 ASCII header. Required keys: VERSION, FIELDS, SIZE, TYPE, COUNT,
WIDTH, HEIGHT, POINTS, DATA (optional: VIEWPOINT). The g2408 firmware emits
a binary-DATA unorganised cloud (HEIGHT=1). The integration's parse_pcd_header
in pcd.py finds the DATA line, splits on newline, decodes key-value pairs,
and validates all required keys are present before advancing body_offset to
the first post-header byte.

Observed g2408 header shape:
  VERSION 0.7
  FIELDS x y z rgb
  SIZE 4 4 4 4
  TYPE F F F U
  COUNT 1 1 1 1
  WIDTH <N>
  HEIGHT 1
  VIEWPOINT 0 0 0 1 0 0 0
  POINTS <N>
  DATA binary

153 261 points confirmed in the 2026-04-20 capture (2.45 MB total).

**See also:** `custom_components/dreame_a2_mower/protocol/pcd.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_data_binary — `pcd_binary_body`

Binary point data block immediately following the header. Layout per field
descriptor from the header: each field is a little-endian word of the
declared SIZE bytes and TYPE. For the g2408 shape (FIELDS x y z rgb, SIZE 4
4 4 4, TYPE F F F U): 4× float32 per point = 16 bytes per point. The 'rgb'
field is packed as a uint32 (R<<16 | G<<8 | B). The integration uses
numpy.frombuffer with a structured dtype to decode all fields in one pass.

**See also:** `custom_components/dreame_a2_mower/protocol/pcd.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_oss_path — `pcd_oss_object_key`

Aliyun OSS path for the LiDAR PCD binary blob. Arrives in s99p20 BEFORE
s2p54 = 100 (at ~61% upload progress). Format:
ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.bin.
The integration fetches via cloud.get_interim_file_url (getDownloadUrl
endpoint) → signed OSS URL → HTTP GET, then writes to the LiDAR archive
under <config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd.
Content-addressed by md5; re-tapping the same scan is a no-op.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_upload_trigger — `pcd_upload_trigger`

The PCD upload is triggered by the user tapping "View LiDAR Map" in the
Dreame app, provided the current scan differs from the last-uploaded one.
Re-opening the screen with no scan change is a no-op (the firmware skips
the upload). The upload takes ~30 seconds for a 2.45 MB / 153 261-point
cloud over WiFi. s2p54 (0..100 progress) drives the progress indicator;
s99p20 signals completion before the final s2p54 = 100 tick.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

