<!-- DO NOT EDIT BY HAND. Source: docs/research/inventory/inventory.yaml. Regenerate via `python tools/inventory_gen.py`. -->

# g2408 Protocol — Canonical Reference

## Properties

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1 | heartbeat | 20-byte blob | WIRED |  |
| s1p4 | mowing_telemetry | 33-byte / 8-byte / 10-byte variants | WIRED |  |
| s1p50 | state_change_ping | empty_dict | DECODED-UNWIRED |  |
| s1p51 | dock_position_update_trigger | empty_dict | DECODED-UNWIRED |  |
| s1p52 | task_end_flush | empty_dict | DECODED-UNWIRED |  |
| s1p53 | obstacle_flag | bool | WIRED |  |
| s2p1 | mode | int (enum) | WIRED |  |
| s2p2 | error_code | int (state/error code) | WIRED |  |
| s2p50 | task_envelope | TASK envelope; multiple op-code classes | DECODED-UNWIRED |  |
| s2p51 | multiplexed_config | shape varies by setting | WIRED |  |
| s2p52 | preference_update_trigger | empty_dict | DECODED-UNWIRED |  |
| s2p53 | voice_download_progress | int 0..100 | SEEN-UNDECODED |  |
| s2p54 | lidar_upload_progress | int 0..100 | DECODED-UNWIRED | % (×1.0) |
| s2p55 | ai_obstacle_report | list | SEEN-UNDECODED |  |
| s2p56 | task_state | {status: list of [task_type, sub_state] pairs} | WIRED |  |
| s2p62 | task_progress_flag | int | SEEN-UNDECODED |  |
| s2p65 | slam_task_label | string | WIRED |  |
| s2p66 | lawn_area_snapshot | list[float, int] | WIRED | m² (×1.0) |
| s3p1 | battery_level | int 0..100 | WIRED | % (×1.0) |
| s3p2 | charging_status | int (enum) | WIRED |  |
| s5p104 | slam_relocate_counter | int | WIRED |  |
| s5p105 | s5p105_raw | int (small enum) | WIRED |  |
| s5p106 | s5p106_raw | int | WIRED |  |
| s5p107 | energy_index | int | WIRED | energy_index (×1.0) |
| s5p108 | s5p108_raw | int | SEEN-UNDECODED |  |
| s6p1 | map_data_signal | int {200, 300} | WIRED |  |
| s6p2 | frame_info | list[int, int, bool, int] len 4 | WIRED |  |
| s6p3 | wifi_signal_push | list[bool, int] | WIRED |  |
| s6p117 | dock_nav_state | int | DECODED-UNWIRED |  |
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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`

### s1p50 — `state_change_ping`

Lightweight "something changed, consider re-fetching" ping. No payload.
Fires at session start (paired with s1p51), at BUILDING zone-save (multiple
pulses in the same second), at zone/exclusion edits (paired with s2p50
o=215), and at maintenance-point save (two pulses 1 s apart, no other
context).

A standalone s1p50 (no s1p51, no s2p50) is the signal to re-fetch whatever
the integration caches from the cloud — in practice, the MAP.* dataset.

See docs/research/g2408-protocol.md §4.7 for the full role catalogue and
the correction note (2026-04-23) on earlier session-boundary hypotheses.

**See also:** `docs/research/g2408-protocol.md §4.7`

### s1p51 — `dock_position_update_trigger`

Dock-position-update trigger per apk decompilation. Fires when the dock pose
changes; consumer should re-fetch via the routed getDockPos action (siid:2
aiid:50 m:'g' t:'DOCK'). Also fires co-incident with s1p50 at every mowing
session start (the firmware emits both in the same second when a run begins),
but the primary semantic is dock-pose change, not session boundary.

2026-04-23 correction: earlier hypothesis called this a "session-start
companion to s1p50 based on observed co-occurrence". Co-occurrence is real
but the apk specifies dock-pose change as the primary trigger.

**See also:** `docs/research/g2408-protocol.md §4.7`

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

**See also:** `docs/research/g2408-protocol.md §4.7`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:61`, `docs/research/g2408-protocol.md §3.5`

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

Value 11 (BUILDING) confirmed 2026-04-20 17:00:09 when user triggered
"Expand Lawn" from the Dreame app.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/g2408-protocol.md §4.2`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:62`, `docs/research/g2408-protocol.md §4.1`

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

**See also:** `docs/research/g2408-protocol.md §4.6`

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

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/g2408-protocol.md §6`

### s2p52 — `preference_update_trigger`

Mowing-preference-update trigger per apk decompilation. Fires when PRE
settings change; consumer should re-fetch via the routed getCFG action
(siid:2 aiid:50 m:'g' t:'CFG').

2026-04-23 correction: previously hypothesized as a session-end companion
to s1p52 based on observed co-occurrence at session end (16:35:17.786 →
18.031). Per apk, the semantic is preference-change, not session-end. The
firmware fires s2p52 at session end because it re-emits prefs as part of
teardown, not because this is a dedicated session-end signal.

**See also:** `docs/research/g2408-protocol.md §4.7`

### s2p53 — `voice_download_progress`

Apk says VOICE_DOWNLOAD_PROGRESS_PCT — progress counter for downloading a
voice pack to the mower. Observed 5 times in the probe corpus but never
pushing meaningful progress on g2408 (values all near 0 or 100 with no
intermediate ticks). No voice-pack download was initiated during the corpus
capture window, so these may be startup-time residue or idle-state pings.

Confirm by triggering a language change from the app while probe is running.

**See also:** `docs/research/g2408-protocol.md §2.1`, `apk: ioBroker.dreame/apk.md §VOICE_DOWNLOAD_PROGRESS_PCT`

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

**See also:** `docs/research/g2408-protocol.md §7.3b`

### s2p55 — `ai_obstacle_report`

Apk says AI_OBSTACLE_REPORT — a list of AI-camera-detected obstacle events.
Observed 14 times in the probe corpus but always an empty list on g2408.
No AI camera triggers were observed in the user's corpus: the g2408 may
require AOP (AI Obstacle Photos) to be enabled and an actual obstacle to be
encountered, or the AI report may only populate when the Dreame cloud
processes a captured image.

Cannot confirm semantics without a corpus capture that includes an actual
AI detection event.

**See also:** `docs/research/g2408-protocol.md §2.1`, `apk: ioBroker.dreame/apk.md §AI_OBSTACLE_REPORT`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:80`, `docs/research/g2408-protocol.md §8.4`

### s2p62 — `task_progress_flag`

Apk says task progress flag. Observed 16 times in the probe corpus. Semantic
on g2408 not yet pinned — values and timing have not been correlated with
specific task events in the available captures. Needs a dedicated
toggle-correlation test.

**Open questions:**
- What values appear and when? Cross-correlate with s2p1 and s2p2 transitions.

**See also:** `docs/research/g2408-protocol.md §2.1`, `apk: ioBroker.dreame/apk.md §task_progress_flag`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:92`, `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:95`, `docs/research/g2408-protocol.md §2.1`

### s3p1 — `battery_level`

Battery percentage. Integer 0..100. Pushes on change during mowing and
charging. The primary battery-state signal for the HA integration.
Confirmed across the full probe corpus 2026-04-17 through 2026-05-05.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:57`, `docs/research/g2408-protocol.md §2.1`

### s3p2 — `charging_status`

Charging status enum. On g2408, value 0 means "not charging" (enum offset
vs upstream — upstream mapping expects 1 for not-charging). Confirmed across
the full probe corpus: transitions to 1 when mower docks and charging starts,
drops to 0 when mowing resumes.

Used in the integration as the authoritative "charging started" signal
(s3p2 → 1) to confirm dock arrival, particularly when s2p50 o=6 echo is
unreliable.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:58`, `docs/research/g2408-protocol.md §2.1`

### s5p104 — `slam_relocate_counter`

SLAM relocate counter. Fires exclusively alongside s2p65 = 'TASK_SLAM_RELOCATE'
bursts — three pushes in ~1 second at each relocalization start. Value has
been 7 in every capture across the probe corpus; role unclear (retry count?
relocate mode enum?).

Quiet-listed in the integration so it does not re-fire [PROTOCOL_NOVEL] on
every relocate. Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- Is the constant value 7 a retry count, mode enum, or firmware constant?

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:131`, `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:135`, `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:139`, `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:143`, `docs/research/g2408-protocol.md §2.1`, `alternatives/dreame-mower/dreame/types.py (const.py:83)`

### s5p108 — `s5p108_raw`

Only one observation in the probe corpus. Semantic unknown. No apk
documentation found. Cannot characterize without more captures.

**Open questions:**
- Only 1 observation. What value was it? What was the mower state at that moment?

**See also:** `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:147`, `docs/research/g2408-protocol.md §7.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:103`, `docs/research/g2408-protocol.md §2.1`

### s6p3 — `wifi_signal_push`

WiFi signal push on g2408: [cloud_connected, rssi_dbm]. NOT the OSS object
key that upstream calls OBJECT_NAME — upstream's slot is unused on g2408
(the session-summary key arrives via event_occured instead, see §7.4).

The integration's overlay remaps OBJECT_NAME to 999/998 so the map handler
does not misinterpret s6p3 pushes as map-object-name strings.

cloud_connected (bool): true if the mower has an active cloud connection.
rssi_dbm (int): WiFi RSSI in dBm. The live s1p1 byte[17] RSSI value takes
over after startup; s6p3 seeds the initial rssi_dbm value.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:112`, `docs/research/g2408-protocol.md §2.1`

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

**See also:** `docs/research/g2408-protocol.md §2.1`

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

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:125`, `docs/research/g2408-protocol.md §7.3b`

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

See docs/research/g2408-protocol.md §7.4 for the full piid catalog and
§7.5 for the OSS fetch flow. A one-shot [PROTOCOL_NOVEL] WARNING fires the
first time a new piid appears in the arguments list.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/g2408-protocol.md §7.4`

## Actions

_(none)_
## Routed-action opcodes

_(none)_
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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 AOP`, `apk: ioBroker.dreame/apk.md §setX AOP`

### ATA — `anti_theft_alarm`

Anti-Theft Alarm. Confirmed 2026-04-24, all three indices individually
verified 2026-04-27. Shape [lift_alarm, offmap_alarm, realtime_location]
matches the s2p51 ANTI_THEFT decoder exactly.
Toggle test: [0,0,0]→[1,0,0] Lift, →[1,1,0] Off-Map, →[1,1,1]
Real-Time Location. Each index ∈ {0,1}.
Surfaced as sensor.anti_theft (state=on if any sub-flag enabled,
per-flag bools in attributes). Sample: [0,0,0].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 ATA`, `apk: ioBroker.dreame/apk.md §setX ATA`

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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 BAT`, `apk: ioBroker.dreame/apk.md §setX BAT`

### BP — `bp_unknown`

TBD. Same shape as WRP list(2). Sample: [1, 4]. No toggle-correlation
test performed; semantics unknown. Exposed as diagnostic only.

**Open questions:**
- BP[0] and BP[1] — no toggle correlation yet; shape matches WRP but meaning unknown.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 BP`, `apk: ioBroker.dreame/apk.md §setX BP`

### CLS — `child_lock`

Child Lock. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.child_lock_cfg. A switch.child_lock entity already exists
wired to DreameMowerProperty.CHILD_LOCK, but on g2408 the
authoritative read path is CFG.CLS. Sample: 0 (off).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 CLS`, `apk: ioBroker.dreame/apk.md §setX CLS`

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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 CMS`, `apk: ioBroker.dreame/apk.md §setX CMS`

### DLS — `daylight_savings`

Daylight savings flag (hypothesized). Observed stable at 0 across
all captures. No toggle-correlation test performed. May be firmware-
managed automatically via TIME (IANA timezone). Sample: 0.

**Open questions:**
- DLS — is this firmware-managed when TIME is set, or user-settable? No toggle test done.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 DLS`, `apk: ioBroker.dreame/apk.md §setX DLS`

### DND — `do_not_disturb`

Do-Not-Disturb. Apk-catalogued. Shape [enabled, start_min, end_min]
with start_min/end_min in minutes-from-midnight. Sample: [0, 1260, 420]
= off, would-be 21:00→07:00.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 DND`, `apk: ioBroker.dreame/apk.md §setX DND`

### FDP — `frost_protection`

Frost Protection. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.frost_protection. Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 FDP`, `apk: ioBroker.dreame/apk.md §setX FDP`

### LANG — `language`

Language. Confirmed 2026-04-24. Shape [text_idx, voice_idx].
text_idx = app/UI language; voice_idx = robot voice language.
Observed indices: voice_idx=7 → Norwegian. Transported via s2p51
shape {"text": N, "voice": M} — decoded as Setting.LANGUAGE.
Surfaced as sensor.robot_voice (state = voice language name where
known, raw indices as attrs). Sample: [2, 7].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 LANG`, `apk: ioBroker.dreame/apk.md §setX LANG`

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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 LIT`, `apk: ioBroker.dreame/apk.md §setX LIT`

### LOW — `low_speed_nighttime`

Low-Speed Nighttime. Confirmed 2026-04-24 via live toggle. Shape
[enabled, start_min, end_min] with start_min/end_min in
minutes-from-midnight. Shape matches the s2p51 LOW_SPEED_NIGHT
decoder. User example: [1, 1200, 480] = enabled, 20:00→08:00 next
day. Surfaced as sensor.low_speed_nighttime.
Sample: [1, 1200, 480].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 LOW`, `apk: ioBroker.dreame/apk.md §setX LOW`

### MSG_ALERT — `notification_preferences`

Notification Preferences. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [anomaly_messages, error_messages, task_messages,
consumables_messages]. Default sample [1,1,1,1] = all four enabled.
Wire shape collides with VOICE — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Sample: [1, 1, 1, 1].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 MSG_ALERT`, `apk: ioBroker.dreame/apk.md §setX MSG_ALERT`

### PATH — `path_unknown`

Unknown on g2408. Observed stable at 1 (true) through a Navigation
Path toggle test 2026-04-25 — NOT the Navigation Path setting despite
earlier user guess (PROT is Navigation Path). Semantic TBD.
Exposed as sensor.cfg_path_raw (disabled-by-default diagnostic) so
the raw int is visible for future toggle-correlation tests.
Sample: true (coerced to 1).

**Open questions:**
- PATH — stable at true/1 through nav-path toggle; purpose still unknown.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 PATH`, `apk: ioBroker.dreame/apk.md §setX PATH`

### PRE — `mowing_preferences`

Mowing preferences. g2408 has 2 elements [zone_id, mode], not the
apk's 10. Alpha.86 removed the entities that read PRE[2..9]; only
mow_mode and mow_mode_efficient (both reading PRE[1]) remain.
zone_id selects which zone's preferences to apply; mode is the
mowing mode for that zone. Sample: [0, 0].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 PRE`, `apk: ioBroker.dreame/apk.md §setX PRE`

### PROT — `navigation_path`

Navigation Path. Confirmed 2026-04-24 via isolated single-toggle with
cfg_keys_raw diff visible on HA alpha.123+. Mapping {0: "direct",
1: "smart"} matches the order shown in the app. Surfaced as
sensor.navigation_path. The field name is cryptic but the toggle
correlation is unambiguous: toggling Nav Path smart→direct flipped
PROT 1→0 with no other CFG key moving. Sample: 1 (smart).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 PROT`, `apk: ioBroker.dreame/apk.md §setX PROT`

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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 REC`, `apk: ioBroker.dreame/apk.md §setX REC`

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

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 STUN`, `apk: ioBroker.dreame/apk.md §setX STUN`

### TIME — `timezone`

Timezone IANA name, e.g. 'Europe/Oslo'. Exposed as
mower_timezone sensor. Sample: "Europe/Oslo".

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 TIME`, `apk: ioBroker.dreame/apk.md §setX TIME`

### VER — `cfg_version`

CFG-update revision counter. Corrected 2026-04-24 — was previously
mis-labelled "firmware version". Monotonic increment on every
successful CFG write; useful as a tripwire for toggle-correlation
research. Distinct from the actual firmware version surfaced by
sensor.firmware_version (which reads device.info.version, a separate
cloud field). Surfaced as diagnostic sensor.cfg_version.
Sample: 444.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 VER`, `apk: ioBroker.dreame/apk.md §setX VER`

### VOICE — `voice_prompt_modes`

Voice Prompt Modes. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [regular_notification_prompt, work_status_prompt,
special_status_prompt, error_status_prompt].
Wire shape collides with MSG_ALERT — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Surfaced as sensor.voice_prompt_modes (state = count enabled 0..4,
per-mode bools in attrs). Sample: [1, 1, 1, 1].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 VOICE`, `apk: ioBroker.dreame/apk.md §setX VOICE`

### VOL — `robot_voice_volume`

Robot Voice volume. Confirmed 2026-04-24. Mapping is percentage
0..100. Surfaced as sensor.robot_voice_volume. Sample: 72.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 VOL`, `apk: ioBroker.dreame/apk.md §setX VOL`

### WRF — `weather_forecast_reference`

Weather Forecast Reference. Mapping {0: off, 1: on}. Surfaced as
sensor.weather_forecast_reference. Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 WRF`, `apk: ioBroker.dreame/apk.md §setX WRF`

### WRP — `rain_protection`

Rain Protection. Confirmed 2026-04-24 via live toggle. Shape
[enabled, resume_hours]. enabled ∈ {0,1}; resume_hours ∈ {0..24}
where 0 = "Don't Mow After Rain" (no auto-resume), 1..24 resumes N
hours after rain ends. Wire shape mirrors the s2p51 RAIN_PROTECTION
decoder. Surfaced as sensor.rain_protection. Distinct from
binary_sensor.rain_protection_active which tracks "raining right now"
via s2p2=56. Sample: [1, 4].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2 WRP`, `apk: ioBroker.dreame/apk.md §setX WRP`

## cfg_individual endpoints

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| AIOBS | ai_obstacle_data | (error r=-3 on g2408) | NOT-ON-G2408 |  |
| CFG | all_keys_cfg | {d: {AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG, LIT, LOW, MSG_ALERT, PATH, PRE, PROT, REC, STUN, TIME, VER, VOICE, VOL, WRF, WRP}} | WIRED |  |
| CMS | consumables_individual | {value: [blade_min, brush_min, robot_min, aux_min]} | WIRED |  |
| DEV | device_info | {fw, mac, ota, sn} | WIRED |  |
| DOCK | dock_state_and_position | {dock: {connect_status, in_region, x, y, yaw, near_x, near_y, near_yaw, path_connect}} | WIRED |  |
| IOT | iot_connection_status | {status: bool} | APK-KNOWN |  |
| LOCN | dock_gps_origin | {pos: [lon, lat]} | WIRED |  |
| MAPD | map_data | (error r=-3 on g2408) | NOT-ON-G2408 |  |
| MAPI | map_info | (error r=-3 on g2408) | NOT-ON-G2408 |  |
| MAPL | map_list | [[int×5], [int×5]] (2 rows × 5 cols) | APK-KNOWN |  |
| MIHIS | lifetime_mowing_aggregates | {area, count, start, time} | WIRED |  |
| MISTA | mowing_statistics | (error r=-1 on g2408) | NOT-ON-G2408 |  |
| MITRC | mi_tracking | (error r=-1 on g2408) | NOT-ON-G2408 |  |
| NET | wifi_info | {current: ssid, list: [{ip, rssi, ssid}, ...]} | WIRED |  |
| OBS | obstacle_data | (error r=-3 on g2408) | NOT-ON-G2408 |  |
| PIN | pin_status | {result, time} | APK-KNOWN |  |
| PRE | preference_endpoint | (error r=-3 on g2408) | NOT-ON-G2408 |  |
| PREI | preference_info | {type, ver: [[zone_id, ver], ...]} | APK-KNOWN |  |
| RPET | rain_protection_end_time | {endTime: int} | APK-KNOWN |  |

### AIOBS — `ai_obstacle_data`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-3 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 AIOBS`, `apk: ioBroker.dreame/apk.md §getX AIOBS`

### CFG — `all_keys_cfg`

The all-keys CFG fetch — getCFG t:'CFG' returns the full 24-key
settings dict. This is the primary mechanism for reading all CFG
keys in a single call; individual keys are documented in the
cfg_keys section. Already wired via cfg_action.py.
Sample: full dict with 24 keys as documented in cfg_keys section.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.2`, `apk: ioBroker.dreame/apk.md §getX CFG`

### CMS — `consumables_individual`

Consumables wear meters via the individual endpoint — same data as
CFG.CMS but wrapped in {value: [...]}. Not separately wired;
integration reads CMS data via the all-keys CFG fetch.
Sample: {value: [3084, 0, 0, -1]}.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/g2408-protocol.md §6.3 CMS`, `apk: ioBroker.dreame/apk.md §getX CMS`

### DEV — `device_info`

Authoritative device identifiers. Wired in v1.0.0a76. sn is the
hardware serial (replaces flaky s1p5 cloud RPC), fw is the firmware
version, mac cross-checks the cloud device record's mac, ota semantic
UNCONFIRMED (NOT the Auto-update Firmware app toggle — values
disagree). Sample: {fw: "4.3.6_0550", mac: "10:06:48:A2:5A:1B",
ota: 1, sn: "G2408053AEE0006232"}.

**Open questions:**
- ota field — NOT the Auto-update Firmware toggle; semantics unconfirmed.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/g2408-protocol.md §6.3 DEV`, `apk: ioBroker.dreame/apk.md §getX DEV`

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

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/g2408-protocol.md §6.3 DOCK`, `apk: ioBroker.dreame/apk.md §getX DOCK`

### IOT — `iot_connection_status`

IoT cloud connection alive flag (presumed). Not wired. Semantic
unconfirmed; status:True observed when integration is online.
Sample: {status: true}.

**Open questions:**
- IOT.status — does it flip to false on cloud disconnect or always true while reachable?

**See also:** `docs/research/g2408-protocol.md §6.3 IOT`, `apk: ioBroker.dreame/apk.md §getX IOT`

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

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/g2408-protocol.md §6.3 LOCN`, `apk: ioBroker.dreame/apk.md §getX LOCN`

### MAPD — `map_data`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-3 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 MAPD`, `apk: ioBroker.dreame/apk.md §getX MAPD`

### MAPI — `map_info`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-3 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 MAPI`, `apk: ioBroker.dreame/apk.md §getX MAPI`

### MAPL — `map_list`

2 rows × 5 cols. Plausibly per-map-slot metadata or active/configured
flags; needs operation-correlated capture (create/delete zone, cycle
map slots) to settle. Not wired. Sample: [[0,1,1,1,0],[1,0,0,0,0]].

**Open questions:**
- MAPL rows/cols — per-map-slot metadata? Needs create/delete zone correlation.

**See also:** `docs/research/g2408-protocol.md §6.3 MAPL`, `apk: ioBroker.dreame/apk.md §getX MAPL`

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

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/g2408-protocol.md §6.3 MIHIS`, `apk: ioBroker.dreame/apk.md §getX MIHIS`

### MISTA — `mowing_statistics`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-1 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 MISTA`, `apk: ioBroker.dreame/apk.md §getX MISTA`

### MITRC — `mi_tracking`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-1 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 MITRC`, `apk: ioBroker.dreame/apk.md §getX MITRC`

### NET — `wifi_info`

Currently-associated AP and per-AP last-seen RSSI. Wired in
v1.0.0a77 — populates wifi_ssid / wifi_ip and seeds wifi_rssi_dbm
at startup before s1p1 byte[17] live RSSI takes over.
Sample: {current:"T55", list:[{ip:"10.0.0.128", rssi:-66, ssid:"T55"}]}.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/g2408-protocol.md §6.3 NET`, `apk: ioBroker.dreame/apk.md §getX NET`

### OBS — `obstacle_data`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-3 per §6.3. Documented as known-unsupported; do not
retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 OBS`, `apk: ioBroker.dreame/apk.md §getX OBS`

### PIN — `pin_status`

Likely the lift-lockout PIN-state flow: result:0 = no PIN-required
event pending, time:0 = no last-PIN-entry timestamp. Partial
documentation in §3.4 byte[10] bit 1. Not wired.
Sample: {result:0, time:0}.

**Open questions:**
- PIN.result and PIN.time — exact semantics of the lift-lockout flow TBD.

**See also:** `docs/research/g2408-protocol.md §6.3 PIN`, `apk: ioBroker.dreame/apk.md §getX PIN`

### PRE — `preference_endpoint`

APK-documented but not supported on g2408 firmware. The cloud
returns r=-3 per §6.3. Note: distinct from CFG.PRE (the mowing
preferences key). This endpoint is the cfg_individual variant;
documented as known-unsupported; do not retry at runtime.

**See also:** `docs/research/g2408-protocol.md §6.3 PRE`, `apk: ioBroker.dreame/apk.md §getX PRE`

### PREI — `preference_info`

Preference info. type:0 observed. ver is a two-row version array —
likely per-PRE-row config-version counter. ver:[[0,78],[1,3]] means
zone 0 at version 78, zone 1 at version 3. Not wired.
Sample: {type:0, ver:[[0,78],[1,3]]}.

**Open questions:**
- PREI.type field — purpose unknown; observed always 0.

**See also:** `docs/research/g2408-protocol.md §6.3 PREI`, `apk: ioBroker.dreame/apk.md §getX PREI`

### RPET — `rain_protection_end_time`

Possibly schedule repeat-end timestamp or rain-protection-end
timestamp (0 = no end / not active). Not wired.
Sample: {endTime: 0}.

**Open questions:**
- RPET.endTime — rain-protection-end unix timestamp or schedule repeat-end? Needs non-zero capture.

**See also:** `docs/research/g2408-protocol.md §6.3 RPET`, `apk: ioBroker.dreame/apk.md §getX RPET`

## Heartbeat (s1p1) bytes

_(none)_
## Telemetry (s1p4) fields

_(none)_
## Telemetry frame variants

_(none)_
## s2p51 multiplexed-config shapes

_(none)_
## s2p2 state codes

_(none)_
## s2p1 mode enum

_(none)_
## OSS map blob keys

_(none)_
## Session-summary JSON fields

_(none)_
## M_PATH encoding

_(none)_
## LiDAR PCD format

_(none)_
