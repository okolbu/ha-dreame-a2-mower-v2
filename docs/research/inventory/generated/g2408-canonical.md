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

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s5a1 | start_mowing |  | WIRED |  |
| s5a1_zone | start_zone_mow |  | WIRED |  |
| s5a1_edge | start_edge_mow |  | WIRED |  |
| s5a1_spot | start_spot_mow |  | WIRED |  |
| s5a4 | pause |  | WIRED |  |
| s5a3 | dock |  | WIRED |  |
| s5a2 | stop |  | WIRED |  |
| s7a1 | find_bot |  | WIRED |  |
| s4a3 | suppress_fault |  | WIRED |  |
| cfg_write_cls | lock_bot_toggle |  | WIRED |  |
| local_only_finalize | finalize_session |  | WIRED |  |
| s9a1 | reset_blades |  | APK-KNOWN |  |
| s10a1 | reset_side_brush |  | APK-KNOWN |  |
| s11a1 | reset_filter |  | APK-KNOWN |  |
| s16a1 | reset_sensor |  | APK-KNOWN |  |
| s17a1 | reset_tank_filter |  | APK-KNOWN |  |
| s19a1 | reset_silver_ion |  | APK-KNOWN |  |
| s1a3 | reset_lensbrush |  | APK-KNOWN |  |
| s24a1 | reset_squeegee |  | APK-KNOWN |  |

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

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:153`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_zone — `start_zone_mow`

Zone-specific mowing run. Same (siid=5, aiid=1) wire entry as
start_mowing but dispatched via routed action s2a50 with o:102 and
payload {m:'a', p:0, o:102, d:{region:[zone_ids]}}.

zone_ids are scalar ints from MAP.*.mowingAreas.value. Alias
START_ZONE_MOW in MowerAction enum. Routed-action opcode see o102.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:157`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

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

See docs/research/g2408-protocol.md §4.6.1 for the full failure-mode
write-up (2026-05-05, three live captures).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:162`, `docs/research/g2408-protocol.md §4.6.1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_spot — `start_spot_mow`

Spot mowing run on defined spot areas. Same (siid=5, aiid=1) wire
entry dispatched via routed action s2a50 with o:103 and payload
{m:'a', p:0, o:103, d:{area:[spot_ids]}}.

spot_ids from MAP.*.spotAreas.value. Confirmed end-to-end live
2026-04-29 (per project memory). Echo: {area_id:[N], exe:T,
o:103, region_id:[], status:T, time:N}.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:167`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a4 — `pause`

Pause the current mowing run in-place. Verified in legacy
DreameMowerActionMapping (types.py:809). On g2408, direct action
returns 80001; the integration retries via routed action if needed.
Expected s2p1 transition: WORKING → PAUSED.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:172`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:809)`

### s5a3 — `dock`

Send the mower back to the docking station (charge). Also used as
RECHARGE (alias for DOCK with the explicit "head to charger now"
semantic). Verified in legacy DreameMowerActionMapping (types.py:810).
On g2408, direct action returns 80001; routed path is the fallback.
Expected s2p1 transition: any → RETURNING → CHARGING.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:173`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:810)`

### s5a2 — `stop`

Stop the current mowing run (without returning to dock). Verified in
legacy DreameMowerActionMapping (types.py:811). On g2408, direct
action returns 80001; routed path is the fallback.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:175`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:811)`

### s7a1 — `find_bot`

Trigger the "Find My Mower" beep/LED sequence on the robot. Wired via
routed action s2a50 with o:9 (findBot opcode). Verified in legacy
DreameMowerActionMapping as LOCATE (types.py:821). On g2408, the
routed path (o:9) is the working channel.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:178`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:821)`

### s4a3 — `suppress_fault`

Suppress / clear the current active fault or warning. Wired via routed
action s2a50 with o:11 (suppressFault opcode). Verified in legacy
DreameMowerActionMapping as CLEAR_WARNING (types.py:813).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:190`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:813)`

### cfg_write_cls — `lock_bot_toggle`

Toggle the child lock (mower panel lockout). No (siid, aiid) entry in
legacy or greenfield; CHILD_LOCK is a property write, not an action
call. The integration dispatches LOCK_BOT_TOGGLE via coordinator
write_setting("CLS", toggled_value) using the cfg_toggle_field
mechanism. Reads the current child_lock_enabled from coordinator.data,
computes not bool(current), and calls write_setting("CLS", toggled).
Confirmed g2408: CLS is the authoritative child-lock setting
(docs/research/g2408-protocol.md §6.2 CLS).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:184`, `docs/research/g2408-protocol.md §6.2`

### local_only_finalize — `finalize_session`

Integration-internal action; no cloud call is ever issued. The
dispatch_action local_only branch calls _run_finalize_incomplete()
(F5.10.1) to close out any session that ended without a clean
event_occured signal (e.g. session ended during HA restart).
local_only: true in the ActionEntry — the cloud-action path is
never reached.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:195`

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

### s1a3 — `reset_lensbrush`

Reset the Lens Brush wear counter. From legacy DreameMowerActionMapping
RESET_LENSBRUSH (types.py:831). Note: the worklist incorrectly listed
this as (s27, a1); the canonical legacy mapping is {siid:1, aiid:3}.
Lens brush is a camera-cleaning accessory on vacuums; unclear whether
g2408 uses this siid/aiid pair for any mower accessory.

**Open questions:**
- Does action(1,3) apply to g2408? siid:1 is the heartbeat/telemetry service — aiid:3 on siid:1 is unusual. Verify legacy mapping is not a typo.

**See also:** `apk: ioBroker.dreame/apk.md §siid:1 aiid:3`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:831)`

### s24a1 — `reset_squeegee`

Reset the Squeegee wear counter. From legacy DreameMowerActionMapping
RESET_SQUEEGEE (types.py:832). Squeegee is a mop/vacuum accessory;
g2408 has no squeegee.

**Open questions:**
- Does action(24,1) apply to g2408? g2408 has no squeegee.

**See also:** `apk: ioBroker.dreame/apk.md §siid:24 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:832)`

## Routed-action opcodes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| o_minus_1 | error_abort | {m:'a', d:{o:-1, status:true, exe:true}, t:'TASK'} | DECODED-UNWIRED |  |
| o0 | reset_control | {m:'a', o:0} | APK-KNOWN |  |
| o2 | joystick_start | {m:'a', o:2} | APK-KNOWN |  |
| o3 | cancel | {m:'a', d:{o:3}, t:'TASK'} (echo only) | DECODED-UNWIRED |  |
| o4 | joystick_pause | {m:'a', o:4} | APK-KNOWN |  |
| o5 | joystick_continue | {m:'a', o:5} | APK-KNOWN |  |
| o6 | recharge | {m:'a', d:{o:6}, t:'TASK'} (echo only) | DECODED-UNWIRED |  |
| o7 | joystick_stop_back | {m:'a', o:7} | APK-KNOWN |  |
| o8 | set_ota | {m:'a', o:8, d:{...}} | APK-KNOWN |  |
| o9 | find_bot | {m:'a', o:9} | WIRED |  |
| o10 | upload_map | {m:'a', o:10} | APK-KNOWN |  |
| o11 | suppress_fault | {m:'a', o:11} | WIRED |  |
| o12 | lock_bot | {m:'a', o:12, d:{lock: 0|1}} | APK-KNOWN |  |
| o100 | global_mower | {m:'a', o:100, t:'TASK', area_id:N, region_id:[1], time:N, exe:T} | WIRED |  |
| o101 | edge_mower | {m:'a', o:101, d:{edge:[[map_id, contour_id], ...]}, t:'TASK'} | WIRED |  |
| o102 | zone_mower | {m:'a', o:102, d:{region:[zone_id, ...]}, t:'TASK'} | WIRED |  |
| o103 | spot_mower | {m:'a', o:103, d:{area:[spot_id, ...]}, t:'TASK'} | WIRED |  |
| o104 | plan_mower | {m:'a', o:104, d:{...}} | APK-KNOWN |  |
| o105 | obstacle_mower | {m:'a', o:105, d:{...}} | APK-KNOWN |  |
| o107 | start_cruise_point | {m:'a', o:107, d:{...}} | APK-KNOWN |  |
| o108 | start_cruise_side | {m:'a', o:108, d:{...}} | APK-KNOWN |  |
| o109 | start_clean_point | {m:'a', d:{o:109, status:false, exe:true}, t:'TASK'} (echo only) | DECODED-UNWIRED |  |
| o110 | start_learning_map | {m:'a', o:110} | APK-KNOWN |  |
| o200 | change_map | {m:'a', o:200, d:{map_id:N}} | APK-KNOWN |  |
| o201 | exit_build_map | {m:'a', d:{o:201, status:true, error:0}, t:'TASK'} (echo) | DECODED-UNWIRED |  |
| o204 | edit_map | {m:'a', d:{o:204, exe:T, status:T, ...}, t:'TASK'} (echo) | DECODED-UNWIRED |  |
| o205 | clear_map | {m:'a', o:205} | APK-KNOWN |  |
| o206 | expand_map | {m:'a', o:206} | APK-KNOWN |  |
| o215 | map_edit_confirm_legacy | {m:'a', d:{o:215, id:N, ids:[...], exe:T, status:T}, t:'TASK'} (echo) | DECODED-UNWIRED |  |
| o218 | delete_zone | {m:'a', d:{o:218, id:N, ids:[], exe:T, status:T}, t:'TASK'} (echo) | DECODED-UNWIRED |  |
| o234 | save_zone_geometry | {m:'a', d:{o:234, id:N, ids:[], exe:T, status:T}, t:'TASK'} (echo) | DECODED-UNWIRED |  |
| o400 | start_binocular | {m:'a', o:400} | APK-KNOWN |  |
| o401 | take_pic | {m:'a', o:401} | DECODED-UNWIRED |  |
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

**See also:** `docs/research/g2408-protocol.md §4.6`

### o0 — `reset_control`

Joystick reset — resets the manual joystick control state. Apk-
documented (ioBroker cross-reference §action operations). Not observed
on g2408 wire; likely only used during manual-control / BT joystick
sessions.

**Open questions:**
- Confirm g2408 responds to o:0 in any reachable state.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o2 — `joystick_start`

Joystick control — start moving. Part of the o:2–7 manual joystick
control group (start/stop/pause/continue/pauseBack/stopBack). Apk-
documented; not observed on g2408 wire.

**Open questions:**
- Confirm joystick opcodes 2-7 work on g2408 via cloud (vs BT-only).

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o3 — `cancel`

Task cancelled echo — fires on s2p50 when the user hits Cancel / Stop
during an active mowing session. Fires ~1 s after s2p2=48. Does not
carry id/ids. Observed 2026-04-20 as a status echo from the firmware;
the integration does NOT send o:3 as a command — Stop/Pause are
action(5,2) and action(5,4).

Also listed in apk as joystick "stop" (o:2-7 group); in s2p50 echo
context it is the canonical "user-cancel" marker.

**See also:** `docs/research/g2408-protocol.md §4.6`

### o4 — `joystick_pause`

Joystick control — pause. Part of the o:2–7 manual joystick control
group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o5 — `joystick_continue`

Joystick control — continue / resume. Part of the o:2–7 manual joystick
control group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o6 — `recharge`

Explicit Recharge command echo — fires on s2p50 when the user taps the
app Recharge button (send mower home). Echo is unreliable: observed
2026-04-20 18:09:56, 18:25:57, 04-27 10:12:18, 04-29 20:47:18 (all on
dock-arrival), but on 2026-05-05 09:24 a confirmed app Recharge that
successfully drove the mower home fired zero o:6 echo at all. The cloud
occasionally drops this delivery.

Detection of Recharge should lean on s2p1: ?→5→6 plus s3p2→1, NOT on
the s2p50 o:6 echo.

**See also:** `docs/research/g2408-protocol.md §4.6`

### o7 — `joystick_stop_back`

Joystick control — stopBack. Part of the o:2–7 manual joystick control
group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o8 — `set_ota`

Trigger OTA (over-the-air firmware update). Apk-documented; not observed
on g2408 wire. Expected to carry OTA metadata in d field.

**Open questions:**
- What is the d-field payload shape for OTA? Apk source needed.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o9 — `find_bot`

Find My Mower — triggers audible beep and/or LED flash on the robot.
Used by the integration's FIND_BOT action via routed action s2a50.
Apk-documented as findBot. No echo observed on s2p50 — command is
fire-and-forget.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:178`, `docs/research/g2408-protocol.md §6.2`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o10 — `upload_map`

Trigger map upload to cloud. Apk-documented as uploadMap. Not observed
on g2408 wire; the integration does not use this opcode (map fetches
go through the OSS/REST path, not this action).

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o11 — `suppress_fault`

Suppress / clear the current active fault or warning. Used by the
integration's SUPPRESS_FAULT action via routed action s2a50. Apk-
documented as suppressFault.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:190`, `docs/research/g2408-protocol.md §6.2`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o12 — `lock_bot`

Lock the mower (panel child lock). Apk-documented as lockBot. The
integration dispatches child-lock via CFG write ("CLS") rather than
this opcode; this opcode may be an alternative channel or app-only path.

**Open questions:**
- Does o:12 work in parallel with CFG.CLS write, or is one canonical?

**See also:** `docs/research/g2408-protocol.md §6.2`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o100 — `global_mower`

All-area mowing session start. Observed as a flat-field s2p50 push
(not wrapped in d:{}) at session start: {area_id:N, exe:T, o:100,
region_id:[1], time:N, t:'TASK'}. The integration sends this via
routed action s2a50 {m:'a', o:100} for START_MOWING. Apk-documented
as globalMower.

Echo arrives seconds after the routed action; confirms the mower has
accepted the task. See §4.3 "Session start" for the full sequence.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:155`, `docs/research/g2408-protocol.md §4.3`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

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

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:163`, `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o102 — `zone_mower`

Zone-specific mowing task launch. zone_ids are scalar ints from
MAP.*.mowingAreas.value. Distinct from o:101 edge contours (which use
[map_id, contour_index] 2-tuples). Observed in probe corpus per §4.6.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:158`, `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o103 — `spot_mower`

Spot mowing task launch. spot_ids from MAP.*.spotAreas.value. Echo:
{area_id:[N], exe:T, o:103, region_id:[], status:T, time:N}. Confirmed
end-to-end live 2026-04-29. Cloud spotAreas.area=0 in echo — actual
spot coordinates from telemetry, not from echo (per project memory
g2408-session-archive-quirks).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:168`, `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o104 — `plan_mower`

Scheduled / planned mowing run. Apk-documented as planMower. Not
observed on g2408 wire; scheduled mowing is triggered by the Dreame
cloud at the configured time, not by the integration. d-field payload
shape unknown.

**Open questions:**
- What d-field does planMower carry? Apk source needed.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o105 — `obstacle_mower`

Obstacle-aware mowing mode. Apk-documented as obstacleMower. Not
observed on g2408 wire. Exact semantics and d-field unknown.

**Open questions:**
- How does obstacleMower differ from globalMower on g2408?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o107 — `start_cruise_point`

Patrol to a specific point. Apk-documented as startCruisePoint. Not
observed on g2408 wire. Used by some Dreame robot models for autonomous
patrol waypoint navigation.

**Open questions:**
- Does g2408 support patrol/cruise modes at all?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o108 — `start_cruise_side`

Patrol along an edge. Apk-documented as startCruiseSide. Not observed
on g2408 wire. Companion to o:107.

**Open questions:**
- Does g2408 support cruise-side mode?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

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

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o110 — `start_learning_map`

Start BUILDING mode (map learning / initial mapping run). Apk-documented
as startLearningMap. Used when the mower needs to build its first map or
expand an existing one. Not directly observed on g2408 wire in probe
corpus; the integration does not currently wire this action.

**Open questions:**
- Confirm g2408 honours o:110 for BUILDING mode start.

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o200 — `change_map`

Switch the active map. Apk-documented as changeMap. Not observed on
g2408 wire; the integration does not currently implement multi-map
switching.

**Open questions:**
- Does g2408 support multiple maps? changeMap d-field shape?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

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

**See also:** `docs/research/g2408-protocol.md §2.1`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o204 — `edit_map`

Map-edit request echo — fires first in a zone / exclusion-zone add /
edit / delete sequence, before the save or delete confirmation opcode.
Apk-documented as editMap. On g2408 observed as the first of the
map-edit pair (204 → 234/215/218 → 201).

Observed 2026-04-20 and confirmed in the 2026-04-26 Designated Ignore
Obstacle Zone create/resize/delete corpus.

**See also:** `docs/research/g2408-protocol.md §2.1`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o205 — `clear_map`

Clear / wipe the current map. Apk-documented as clearMap. Not observed
on g2408 wire; the integration does not expose a clear-map action.

**Open questions:**
- Does clearMap fully wipe all zones and the map polygon on g2408?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o206 — `expand_map`

Expand the current lawn map (add new area to existing map). Apk-
documented as expandMap; also referenced in §4.3 "Expand Lawn" context.
Not directly observed on g2408 wire in probe corpus.

**See also:** `docs/research/g2408-protocol.md §4.3`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o215 — `map_edit_confirm_legacy`

Legacy map-edit confirmation echo. Older captures (2026-04-20) show
o:215 as the "second of the map-edit pair" (zone edit confirm), carrying
id and ids fields. Later captures (2026-04-26) show o:234 in the same
role. The integration triggers a MAP rebuild on o:215 OR o:201 with
status:true error:0 — covers both old and new confirmation opcode.

**See also:** `docs/research/g2408-protocol.md §2.1`

### o218 — `delete_zone`

Zone / exclusion-zone delete echo. Carries the deleted entity's id;
ids:[] in all observed captures. CONFIRMED via multiple captures
matching user-delete narrative in the 2026-04-26 Designated Ignore
Obstacle Zone corpus. One outlier capture from an untraced UI flow
(likely an edit-cancel processed as delete-and-recreate). Sequence:
o:204 → o:218 → o:201.

**See also:** `docs/research/g2408-protocol.md §2.1`

### o234 — `save_zone_geometry`

Save zone / exclusion-zone geometry echo. CONFIRMED — fires for both
create new (new firmware-assigned id) and resize existing (same id).
Carries the saved entity's id; ids:[] in all observed captures. Sequence:
o:204 → o:234 → o:201. Confirmed 2026-04-26 from Designated Ignore
Obstacle Zone create/resize/delete tests.

**See also:** `docs/research/g2408-protocol.md §2.1`

### o400 — `start_binocular`

Camera-stream start (binocular/stereo camera activation). Apk-documented
as startBinocular. Not observed on g2408 wire; likely a camera-streaming
feature not yet wired in the integration.

**Open questions:**
- Does g2408 support startBinocular? Related to takePic (o:401) flow?

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

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

**See also:** `docs/research/g2408-protocol.md §4.6`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o503 — `cutter_bias`

Blade calibration / bias correction. Apk-documented as cutterBias.
Referenced in §6.2 opcode list. Not observed on g2408 wire; the
integration does not currently expose a blade-calibration action. d-field
payload shape (calibration parameters) unknown.

**Open questions:**
- What d-field does cutterBias carry? When should calibration be triggered?

**See also:** `docs/research/g2408-protocol.md §6.2`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

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

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1_b0 | frame_delimiter_start | byte (likely 0xCE) | SEEN-UNDECODED |  |
| s1p1_b1_bit1 | drop_tilt | single bit | WIRED | bool (×1.0) |
| s1p1_b1_bit0 | bumper_hit | single bit | WIRED | bool (×1.0) |
| s1p1_b2_bit1 | lift | single bit | WIRED | bool (×1.0) |
| s1p1_b3_bit7 | lift_lockout_pin_required | single bit | WIRED | bool (×1.0) |
| s1p1_b4 | human_presence_detection | byte | WIRED | byte (×1.0) |
| s1p1_b5 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b6_bit3 | charging_paused_batt_temp_low | single bit | WIRED | bool (×1.0) |
| s1p1_b7 | state_transition_marker | byte | WIRED | byte (×1.0) |
| s1p1_b8 | undocumented | byte | SEEN-UNDECODED |  |
| s1p1_b9 | mow_start_pulse | byte | WIRED | byte (×1.0) |
| s1p1_b10_bit7 | batt_temp_low_latched | single bit | WIRED | bool (×1.0) |
| s1p1_b10_bit1 | safety_alert_active | single bit | WIRED | bool (×1.0) |
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

**See also:** `docs/research/g2408-protocol.md §3.4`

### s1p1_b1_bit1 — `drop_tilt`

Drop / Robot tilted — set while the mower is held off-level.
Confirmed 2026-04-30 19:37:05 against the app's "Robot tilted"
notification; cleared at 19:37:13 when the mower was set back
down. Wire mask: byte[1] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b1_bit0 — `bumper_hit`

Bumper hit — confirmed 2026-04-30 19:37:13 against the app's
"Bumper error" notification. Important: this event has no
corresponding s2p2 transition — it surfaces only via this bit.
Wire mask: byte[1] & 0x01.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b2_bit1 — `lift`

Lift / Robot lifted — confirmed 2026-04-30 19:37:57 against the
app's "Robot lifted" notification. Wire mask: byte[2] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b5 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b7 — `state_transition_marker`

State transition marker. Values: 0=idle, 1 or 4 = state
transitions. Exact semantics of 1 vs 4 not yet pinned down.
Decoded by the integration as state_raw on the Heartbeat
dataclass.

**Open questions:**
- Distinguish the semantic difference between value 1 and value 4; correlate with specific s2p1/s2p2 transitions.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b8 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

### s1p1_b9 — `mow_start_pulse`

0/64 pulse at mow start. Pulses from 0 to 64 and back to 0
at the beginning of a mowing session. Exact timing relative to
s2p2/s2p1 transitions not yet pinned down. Single-class
datapoint.

**Open questions:**
- Is value 64 specific to mowing start or does it appear in other session types (BUILDING, edge)?

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b11_b12 — `monotonic_counter`

Monotonic counter, little-endian u16 spanning bytes [11-12].
Increments with each heartbeat emission. Used by the integration
to detect duplicate or out-of-order heartbeat deliveries. Decoded
via struct.unpack_from("<H", data, 11).

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b13 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

### s1p1_b14 — `startup_state_machine`

Startup state machine byte. Transitions through a fixed sequence
during device boot: 0 → 64 → 68 → 4 → 5 → 7 → 135. Steady-state
value after full boot is 135. Useful for detecting incomplete
startup or firmware boot stall (e.g. mower stuck at 64 would
indicate a boot-loop).

**Open questions:**
- Are all 7 states observed on every cold boot, or is the sequence firmware-version dependent?

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b15 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

### s1p1_b16 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

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

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

### s1p1_b18 — `undocumented`

Observed on the wire (every heartbeat carries this byte) but not
yet characterised. Contributors with reproducible test scenarios
should file a finding linking the value range to a device event.

**Open questions:**
- Determine value range and stationarity across mowing/idle/charging.

**See also:** `docs/research/g2408-protocol.md §3.4`

### s1p1_b19 — `frame_delimiter_end`

End-of-frame delimiter. Hypothesised 0xCE by analogy with
s1p4 telemetry framing; verify against probe-log heartbeat
captures. Confirmed by the decode_s1p1 guard in heartbeat.py
which checks data[-1] == FRAME_DELIMITER (0xCE).

**Open questions:**
- Cross-check b[19] = 0xCE against probe-log heartbeat captures.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/g2408-protocol.md §3.4`

## Telemetry (s1p4) fields

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_33b_delim_start |  | byte (0xCE) | DECODED-UNWIRED |  |
| s1p4_33b_x_mm |  | 20-bit signed; x = (b[2]<<28 | b[1]<<20 | b[0]<<12) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_y_mm |  | 20-bit signed; y = (b[4]<<24 | b[3]<<16 | b[2]<<8) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_static_b5 |  | byte (0x00) | DECODED-UNWIRED |  |
| s1p4_33b_sequence |  | uint16_le | WIRED |  |
| s1p4_33b_start_index |  | uint24_le | WIRED |  |
| s1p4_33b_phase_raw |  | uint8 | WIRED |  |
| s1p4_33b_static_b9 |  | byte (0x00) | DECODED-UNWIRED |  |
| s1p4_33b_delta_1 |  | 2 × int16_le (dx1, dy1) | WIRED |  |
| s1p4_33b_delta_2 |  | 2 × int16_le (dx2, dy2) | WIRED |  |
| s1p4_33b_delta_3 |  | 2 × int16_le (dx3, dy3) | WIRED |  |
| s1p4_33b_flag_22 |  | byte | SEEN-UNDECODED |  |
| s1p4_33b_flag_23 |  | byte | SEEN-UNDECODED |  |
| s1p4_33b_distance_dm |  | uint16_le; value / 10 → m | WIRED | m (×0.1) |
| s1p4_33b_total_area_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b28 |  | byte (0x00 on small lawns) | SEEN-UNDECODED |  |
| s1p4_33b_area_mowed_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b31 |  | byte (0x00 on small lawns) | SEEN-UNDECODED |  |
| s1p4_33b_delim_end |  | byte (0xCE) | DECODED-UNWIRED |  |
| s1p4_8b_delim_start |  | byte (0xCE) | DECODED-UNWIRED |  |
| s1p4_8b_x_mm |  | 20-bit signed; SAME decoder as 33-byte x_mm | WIRED | m (×0.001) |
| s1p4_8b_y_mm |  | 20-bit signed; SAME decoder as 33-byte y_mm | WIRED | m (×0.001) |
| s1p4_8b_static_b5 |  | byte (0x00) | DECODED-UNWIRED |  |
| s1p4_8b_heading_byte |  | byte | WIRED | degrees (×1.4117647) |
| s1p4_8b_delim_end |  | byte (0xCE) | DECODED-UNWIRED |  |
| s1p4_10b_delim_start |  | byte (0xCE) | DECODED-UNWIRED |  |
| s1p4_10b_x_cm |  | int16_le | SEEN-UNDECODED | m (×0.01) |
| s1p4_10b_y_mm |  | int16_le | SEEN-UNDECODED | m (×0.001) |
| s1p4_10b_static_b5 |  | byte (0x00) | SEEN-UNDECODED |  |
| s1p4_10b_unknown_6_7 |  | uint16_le (observed 5570 = 0x15C2) | SEEN-UNDECODED |  |
| s1p4_10b_static_b8 |  | byte (0x00) | SEEN-UNDECODED |  |
| s1p4_10b_delim_end |  | byte (0xCE) | DECODED-UNWIRED |  |

### s1p4_33b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm).
Origin (0,0) = charging station. +X points toward the house (mower's
nose direction when docked); -X points into the lawn. X is in cm on
the old int16 layout; the 20-bit decode and ×10 scaling unifies both
axes to mm. See §3.1 coordinate-frame notes. apk-corrected decoder
landed in alpha.98.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm).
±Y is perpendicular to the X axis (left/right when facing the house).
Y-axis calibration: tape-measure-verified 0.625 factor (encoder
over-reports by ~1.6×); factor is per-install configurable. Confirmed
alpha.98 via full probe-corpus replay (14.7k frames).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_static_b5 — ``

Static 0x00 byte between the packed XY block and the sequence field.

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_sequence — ``

Path-point sequence number (lower 16 bits of the uint24 start_index at
bytes [7-9]). Frame-over-frame increments monotonically; used by the
integration to detect skipped frames. Part of the start_index field
documented in apk §parseRobotTrace — the full counter is at bytes [7-9].

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_start_index — ``

Path-point sequence counter (uint24 LE). Confirmed on g2408: one-off
script over 14,684 consecutive-frame transitions found 5,796 increments
vs only 10 decrements; 10 decrements all look like new-session resets.
Zero INT24-MAX saturation. Distribution concentrated in 0..10k per
session. Matches apk §parseRobotTrace "uint24 LE path-point sequence
id" exactly.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

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

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_static_b9 — ``

Static 0x00 byte separating phase_raw from the delta block.

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_delta_1 — ``

First path-history delta (Δ1). Carries the offset from the current pose
to a recent prior path point. When |dx| > 32766 AND |dy| > 32766 the
Δ is ABSOLUTE (not relative) — the apk sentinel for relocalisation /
run-start jumps. Confirmed via ±INT16 saturation pattern across 14.6k
frames (motion_vectors_correlate.py).

Apk §parseRobotTrace: each 33-byte frame carries current pose PLUS
3 path-point offsets — so the integration receives 4 points per frame
without waiting for frame N+1.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

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

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_delta_3 — ``

Third path-history delta (Δ3). Same sentinel rule as delta_1/delta_2.
Δ1.dx and Δ3.dx are often nearly equal magnitude in steady-motion
captures (−267 vs −262 mm/frame), suggesting Δ1/Δ3 may point to the
same prior point under different references, or the Δ ordering is
different on g2408 vs the apk description. Validated against 14.6k
frames — saturation pattern matches the apk sentinel.

**Open questions:**
- Δ1.dx ≈ Δ3.dx in steady motion — are Δ1/Δ3 pointing to the same prior point, or is the oldest→newest ordering different on g2408?

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_flag_22 — ``

Initialisation-complete flag. Observed 0 at session start, transitions
to 1 after initialisation. Value stays 1 throughout the mowing session.

**Open questions:**
- What triggers the 0→1 transition exactly? Is it localisation-complete or first-pose-published?

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_flag_23 — ``

Observed constant value 2 across all captures. Likely a protocol-version
or frame-type marker. Not known to change.

**Open questions:**
- Does byte[23] ever differ from 2? If always 2, it may be a frame-format version constant.

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_distance_dm — ``

Total distance driven in the current session, in decimetres (raw ÷ 10 → m).
Resets at session start. Ticks forward whenever the mower moves —
including blades-up transit legs. Frame-to-frame delta can detect
motion (non-zero) vs stationary. Used alongside area_mowed_cent for
blades-on/off detection (both counters tick when cutting, distance
alone ticks on transit).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`

### s1p4_33b_total_area_centiares — ``

Total mowable lawn area for the active session, INCLUDING area under
exclusion zones (user-confirmed 2026-04-25). area_mowed_cent plateaus
at (total - excluded), not at total. Resets each session. The apk
documents this as uint24 at bytes [26-28]; byte [28] is currently
treated as static on g2408 (small lawns keep it at 0x00).

**Open questions:**
- Switch to apk's uint24 decode for lawns > 655 m²; currently uint16 + static high byte.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b28 — ``

High byte of the apk-documented uint24 total_area field at [26-28].
Treated as static (0x00) on the user's ~384 m² lawn where the uint16
[26-27] suffices. For lawns > 655 m² this byte will be non-zero and
must be included in the decode. See open question on total_area_centiares.

**Open questions:**
- Confirm byte[28] is non-zero on lawns > 655 m²; needs a contributor with a larger install.

**See also:** `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

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

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b31 — ``

High byte of the apk-documented uint24 area_mowed field at [29-31].
Treated as static (0x00) on the user's lawn. Non-zero for installs
where the mowed area exceeds 655 m² in a single session.

**Open questions:**
- Confirm byte[31] is non-zero on large-lawn installs (mowed area > 655 m² per session).

**See also:** `docs/research/g2408-protocol.md §3.1`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.1`

### s1p4_8b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.2`

### s1p4_8b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. During idle/docked the value converges
near 0. During BUILDING sessions it tracks live mower X position as the
mower traces the new boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.2`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. Leg-start preamble frames carry a
near-0xFFFF sentinel Y (the mower hasn't localised yet). BUILDING
frames carry live real Y coordinates as the mower traces the boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.2`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_static_b5 — ``

Static 0x00 byte. Present in all 8-byte captures including BUILDING mode.

**See also:** `docs/research/g2408-protocol.md §3.2`

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

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.2`, `apk: ioBroker.dreame/apk.md §parseRobotPose (angle field)`

### s1p4_8b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.2`

### s1p4_10b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_x_cm — ``

X position at the moment the zone-save event fired. Likely same
dock-relative coordinate frame as the 8/33-byte variants. Single
capture only (2026-04-20 17:03:41, sample byte sequence
[0xCE, 139, 0, 240, 77, 0, 194, 21, 0, 0xCE]).

**Open questions:**
- Does [1-2] use int16_le or the same 20-bit packed decode as the 8/33-byte frames? Only 1 sample — needs more BUILDING captures.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_y_mm — ``

Y position at the zone-save moment. Sample value 19952 mm is consistent
with the mower being on the far side of the lawn during BUILDING.
Decoder provisional — only one capture available.

**Open questions:**
- Verify y decode on a second BUILDING capture.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_static_b5 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_unknown_6_7 — ``

Unknown uint16 at the zone-save moment. Observed 0x15C2 = 5570 on
2026-04-20 in the single capture. Candidates: sequence counter for the
new polygon's perimeter points, zone-id assigned by the firmware, or
a general capture-sequence counter. Needs more BUILDING sessions to
disambiguate.

**Open questions:**
- Decode bytes [6-7] — point count? zone id? sequence counter? Correlate with number of 8-byte frames in the preceding BUILDING session.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_static_b8 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_10b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `docs/research/g2408-protocol.md §3.3`

## Telemetry frame variants

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_33b | mowing_telemetry_full |  | WIRED |  |
| s1p4_8b | beacon |  | WIRED |  |
| s1p4_10b | building_save_marker |  | SEEN-UNDECODED |  |
| s1p4_7b | unknown_g2568a_variant |  | APK-KNOWN |  |
| s1p4_13b | unknown_other_model_variant |  | APK-KNOWN |  |
| s1p4_22b | unknown_other_model_variant_22 |  | APK-KNOWN |  |
| s1p4_44b | unknown_other_model_variant_44 |  | APK-KNOWN |  |

### s1p4_33b — `mowing_telemetry_full`

Full mowing-session telemetry. Used throughout an active TASK including
auto-recharge return legs. Carries position (20-bit packed XY),
path-history deltas (Δ1/Δ2/Δ3), phase index, sequence counter, distance
driven, total lawn area, and area mowed (blades-down). Switches to the
8-byte beacon at session boundaries and during BUILDING.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.1`

### s1p4_8b — `beacon`

Position-only beacon variant. Emitted in four situations on g2408:
(1) idle/docked/remote-control, (2) start-of-leg preamble (~37-45 s
after each s2p1→1, three consecutive frames observed 2026-04-20 before
33-byte stream resumed), (3) throughout BUILDING sessions (47 frames
at 5 s cadence during 2026-04-20 17:00-17:04), (4) post-FTRTS
dock-navigation phase (confirmed 2026-05-05: ~25 frames over ~90 s
when s2p65='TASK_NAV_DOCK' fires). Carries XY + heading byte; no
phase/area/distance fields.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/g2408-protocol.md §3.2`

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

**See also:** `docs/research/g2408-protocol.md §3.3`

### s1p4_7b — `unknown_g2568a_variant`

Documented in apk for g2568a and other Dreame mower/vacuum models.
Never observed in any g2408 capture. If a future g2408 firmware update
or a different region variant surfaces this length, the integration
emits a one-shot [PROTOCOL_NOVEL] s1p4 short frame len=7 WARNING with
raw bytes.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_13b — `unknown_other_model_variant`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_22b — `unknown_other_model_variant_22`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_44b — `unknown_other_model_variant_44`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

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
