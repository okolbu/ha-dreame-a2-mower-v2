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

_(none)_
## cfg_individual endpoints

_(none)_
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
