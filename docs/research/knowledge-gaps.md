# g2408 Knowledge Gaps — MQTT push & cloud-API retvals

A **blank-spots companion** to `inventory.yaml`. The inventory records what is
*known* (and how confident we are); this file is the inverse view — the *missing*
and *uncertain* understanding, gathered in one place because gaps are hard to
find by reading the known-facts docs slot-by-slot.

Covers **both** wire surfaces, because going slot-by-slot in the integration
turns up unknowns in each:
- **MQTT `/status/` push** — `properties_changed` (siid/piid): s1p*, s2p*, s5p*, s6p*.
- **Cloud-API retvals** — CFG keys, routed-action opcodes, batch device-data
  (MAP*/MISTA/MITRC/OBS), OSS session-summary JSON, device events.

## How to keep this in sync (don't hand-maintain in parallel)

`inventory.yaml` stays the **single source of truth**. This file is a curated
cross-cut that can be **regenerated**: an entry belongs here iff its
`status.decoded != confirmed` **or** it has `open_questions`. Skeleton refresh:

```python
import yaml
d = yaml.safe_load(open('custom_components/dreame_a2_mower/inventory.yaml'))
def walk(n):
    if isinstance(n, dict):
        if 'id' in n and ('status' in n or 'semantic' in n):
            st = n.get('status', {}) or {}
            yield n['id'], n.get('name'), st.get('decoded'), len(n.get('open_questions') or [])
        for v in n.values(): yield from walk(v)
    elif isinstance(n, list):
        for it in n: yield from walk(it)
for id_, name, dec, oq in walk(d):
    if dec != 'confirmed' or oq: print(id_, name, dec, oq)
```

Corpus numbers below are from `probe_log_*.jsonl` (9 logs, 2026-04-17…05-30;
66,149 s1p1 + 69,254 s1p4 frames) via the census snippet at the end. Baseline
inventory tally at time of writing: **195 confirmed / 121 hypothesized /
12 unknown / 4 partial** across 332 entries.

Validation-process shorthands are defined in [§Validation playbook](#validation-playbook).

---

## 1. s1p1 heartbeat — byte/bit gaps (20-byte push, 66,149 frames)

| Byte/bit | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| `[5]` | unknown | 99% `0x00`, rare {2,16,18} | purpose of the rare non-zero flags | LABEL: timestamp the rare frames vs device events |
| `[8]` | unknown | 97% `0x00`, rare {1,16,128,129} | rare flag; distinct from `[9]` mow_start_pulse | LABEL |
| `[13]` | **partial** | 19 vals; 255 docked, 35 mowing, 40 returning, 17-27 building | not pinned to an enum; companion to `[14]`? | XTAB by mode + LABEL transitions; test `[13][14][15]` as one block |
| `[14]` | **partial** | 28 vals; 0 docked, 135 mowing, 0x80-range returning/idle, 164 tilt-lockout | enumerate the 0x80-range sub-states | LABEL: a clean return-to-dock; tilt/fault captures extend it |
| `[15]` | **partial** | 11 vals {0,1,2,3,4,5,6,17,18,20,54}; 54 at undock-onset, 18 in reorient | likely a **bitfield**, not enum | LABEL: separate the bits across idle/returning/reorient |
| `[18]` | unknown | 90% `186`, rare {126,127,180,196,203} | rare status/flag | LABEL |
| `[4]` sub-bits | confirmed (name) | multi-bit: 0(68%),0x10(16%),0x08(8%),0x40(6%) | only "human_presence" named; the other bits uncharacterized | XTAB each bit vs state |
| `[1][2][3][6][10]` other bits | confirmed (some bits) | flags 99% clear | only specific bits decoded (tilt/bumper/lift/PIN/temp/safety/latch); **remaining bits never examined** | LABEL safety/fault events |
| `[10]&0x80` | confirmed | 93% set (docked+warm too) | labelled "low-temp latch" but trigger not cleanly pinned (see 2026-05-30 note — it is NOT off-dock) | capture a cold-night→warm power-cycle to see if it ever clears |

Solidly known: `[0]`/`[19]`=0xCE delims, `[16]`=128 const, `[7]` state marker,
`[9]` mow_start_pulse, `[11-12]` counter, `[17]` RSSI.

---

## 2. s1p4 telemetry — byte gaps (33-byte push, 68,801 frames; +449 8-byte, +4 10-byte)

| Field | Status | Gap | Validate |
|---|---|---|---|
| `[10-21]` motion vectors / path history (`delta_2`,`delta_3`) | hypothesized | not decoded — likely per-axis velocity / recent-path deltas | XTAB deltas vs frame-to-frame (dx,dy); the heading validator at `heading_correlate.py` is the template |
| `[22]` region_id / `[23]` task_id (`flag_22`,`flag_23`) | hypothesized | values seen but mapping to map regions/tasks unconfirmed | LABEL: run zone/region-specific mows |
| `[28]`,`[31]` static bytes | hypothesized | assumed static; semantic unknown | scan corpus for any non-static occurrence |
| 10-byte BUILDING variant `[6-7]` | unknown | two extra bytes during map-learn not decoded | LABEL: capture an Expand-Lawn / map-build |
| overlapping reads `[24-25]` (percent vs distance), `[26-28]`/`[29-31]` (uint24 vs uint16 area) | confirmed-both | the "Task 4" field-validation never blessed ONE interpretation; both still computed | pick a known-area mow, compare both decodes vs app-reported area |

---

## 3. s2p* status / event slots

| Slot | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| s2p2 codes 20, 33 | hypothesized | fired only in the 2026-05-25 12:32 failure burst | text cloud-pruned; meaning unknown | repro within cloud retention, then device-messages/v2 fetch; or apk FaultIndex L94618-94697 |
| s2p2 conflicts 23/43/75 | mixed | seen | apk fault-label vs event-slug disagree | controlled trigger per code |
| s2p2 catalog 37-78 (RIGHT_MAGNET, FLOW_ERROR, …) | hypothesized | **never observed** | vacuum/apk-derived; may not exist on g2408 | wait-for-event; treat as unconfirmed |
| s2p53 voice_download_progress | hypothesized | 5 occ {0,50,100} | shape presumed | LABEL: trigger a voice-pack download |
| s2p55 ai_obstacle_report | hypothesized | 23 dict | wire shape unknown (no AI-obstacle capture) | wait-for-event (AI obstacle w/ photo) |
| s2p57 / s2p58 / s2p61 / s2p62 | hypothesized | s2p62 always `0`; others sparse | shutdown/self-check/map-update/progress semantics presumed | LABEL respective triggers |
| s2p65 slam_relocate | (str) | 18 occ | only fires on relocate (mostly the FAILED one) | already partly mapped; capture a clean relocate |
| s2p66 lawn_area_snapshot | confirmed | 2 occ | very rare; trigger unclear | LABEL |

Confirmed-with-followups: s2p1 (mode enum — value 3/14 + s2p56-umbrella open, see
TODO), s2p51 (multiplexed config — shapes catalogued, some sub-shapes presumed),
s2p56 (lifecycle), s2p50 (TASK envelope opcodes — see §6).

---

## 4. s5p* / s6p* slots

| Slot | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| **s5p105** | hypothesized | 106 occ, vals {1,2,3,4} | small enum, meaning unknown; fires during reorient (~+13s) | LABEL: correlate value vs activity phase |
| **s5p106** | hypothesized | **1426 occ**, vals 1-20 | fires often, purpose unknown; reorient housekeeping candidate | XTAB vs mode/phase; high frequency = good signal to crack |
| s5p107 energy_index | confirmed | 279 occ, 1-250 | units/derivation (discharge index) not fully pinned | compare vs battery-drop rate |
| s5p108 | **unknown** | 3 occ, val {1} | almost never fires; semantic unknown | wait-for-more-data |
| s6p1 map_data_signal | confirmed | 68 occ {200,201,300} | the 200/201/300 transition semantics (which = "new map ready") | LABEL: map-edit / swap events |
| s6p2 frame_info | confirmed | 93 occ, list[4] | per-field meaning of the 4 ints | LABEL |
| s6p3 Link Module | (list[2]) | 124 occ | cellular daily ping; field meaning | n/a unless cracking cellular |
| s6p117 dock_nav_state | confirmed | 11 occ {1,3} | the value enum (only 1,3 seen) | LABEL dock approach |

---

## 5. Documented but NEVER seen on g2408 (vacuum-inherited)

Census over 66k+ frames shows **zero occurrences** — these are upstream/apk
catalog carried into the integration that the g2408 firmware does not emit on the
`/status/` topic. Candidates to flag `not_on_g2408: true` (or clearly mark
"upstream catalog, unobserved") so they stop reading as live gaps:

- **s4p21, s4p22, s4p23, s4p26, s4p27, s4p44, s4p47, s4p49, s4p59, s4p68, s4p83**
  (obstacle_avoidance / ai_detection / cleaning_mode / child_lock / cruise_type /
  scheduled_clean / pet_detective / device_capability / device_snapshot_bundle…)
  — all vacuum-side MIoT properties; the g2408 surfaces these via CFG/SETTINGS instead.
- **s1p2 / s1p3** (OTA state/progress) — never captured (no firmware update during
  probe period). Genuinely g2408 but **wait-for-OTA**.
- Reset actions **s9a1/s10a1/s11a1/s16a1/s17a1/s19a1/s24a1/s1a3** and many opcodes
  are *action* surfaces (aiid), not push — they won't appear in this census; see §6.

**Validation:** the absence is itself corpus-confirmed (9 logs). Low-risk to
deprioritize; if any ever appears, it's a `[PROTOCOL_NOVEL]` and will be flagged.

---

## 6. Cloud-API retval gaps (not MQTT push)

These return from cloud calls (routed-action / getCFG / batch device-data / OSS),
so they need an integration-slot or a probe call to observe — not the status tail.

**CFG keys (getCFG / setX):**
| Key | Status | Gap | Validate |
|---|---|---|---|
| BP, PATH | hypothesized | placeholder semantics — suspected Pathway Obstacle Avoidance | CFG-DIFF: create a pathway in app, snapshot getCFG before/after |
| DLS | hypothesized | daylight-savings flag, stable 0 | CFG-DIFF across a DST boundary |
| PIN | hypothesized | PIN status read/write shape unknown | LABEL: change PIN with probe running (BT-only suspected) |
| PRE / PREI | hypothesized | g2408 PRE=[0,0]; not the vacuum 10-elt shape | confirmed-absent shape; encoder over-inflates (see TODO PRE bug) |
| AIOBS / OBS | hypothesized | AI-obstacle data blob shape | wait-for-event |
| CMS[3] | **partial** | unidentified (Link/Garage/MCA10/summary) — -1 always here | needs a unit WITH one of those accessories |
| IOT, ARM, REMOTE, WINFO, CHECK, RPET | hypothesized | connection-status / alarm / remote-settings / weather / self-check / rain-end-time | CFG-DIFF or LABEL per feature |

**Batch device-data / map retvals:** MAPD, MAPI, MITRC, OBS (hypothesized);
MAPL, MISTA (confirmed w/ open qs). Gap: per-field decode of the map-info and
mission-track structures. Validate: fetch via probe + diff against a known map state.

**Routed-action opcodes (s2p50 TASK / o-codes):** many hypothesized — o104/105
(plan/obstacle mower), o107/108 (cruise point/side), o110 (learn map), o205/206
(clear/expand map), o400 (binocular), o503 (cutter bias), o8 (OTA), o12 (lock — see
lock_robot incident memory), o15 (remote setting), joystick o2/4/5/7. Gap: confirm
each fires the intended action on g2408. Validate: **docked-window probe only**
(the o-code brute-force start-action incident — never blind-probe aiid≠50).

**OSS session-summary fields:** mode, result, stop_reason, start_mode, pre_type,
region_status, faults, edge_status — hypothesized/unknown. Gap: value enums.
Validate: collect summaries across varied session outcomes (complete / rain-stop /
fail-to-reach / zone / edge) and diff.

**Device events (s4 eiid1 args):** arg11, arg13, arg15 unknown; arg1/arg2/arg60
hypothesized. Validate: correlate event args with the session that fired them.

---

## 7. Cross-surface / behavioral gaps (tracked in TODO.md)

- **Reorient popup driver** — off the sniffed wire (popup edges land in the MQTT
  silent window on bare heartbeats; cloud poll/push suspected). Best MQTT proxy is
  the `[undock → s1p50/s1p51]` bracket. (inventory § s1p51 open_q.)
- **GPS world-coordinate read path** — LOCN returns sentinel; the app's surface is
  unidentified. (TODO.)
- **Write path (Phase 3)** — ~28 entities write to a cloud-cache surface the device
  doesn't apply; the app's real write RPC is uncaptured. (TODO.)
- **summary_map track over-segmentation** — TRACK_BREAK_MARKER trigger unknown. (TODO.)

---

## Validation playbook

Referenced as shorthands above:

- **XTAB** — corpus cross-tab: bucket the byte/value by a known condition
  (s2p1 mode, dock-state, temp-state) over all 9 logs. Proves/【dis】proves a
  hypothesis without a new capture. Tooling pattern: stream `probe_log_*.jsonl`,
  build per-event timelines, `Counter` per bucket. (See the s1p1/s2p2 work
  2026-05-30.) **A claim is not `verified` from one run — it must hold corpus-wide**
  ([[feedback-corpus-validate-protocol-claims]]).
- **LABEL** — labelled-event capture: timestamp a physical/app action (±1-2 s) and
  diff the wire in that window. Used for tilt/lift/lid, undock/reorient, popup edges.
- **CFG-DIFF** — toggle one setting in the app, snapshot getCFG (or the empty-batch
  read) before/after, diff the changed key. The canonical write-surface probe.
- **wait-for-event** — rare triggers (OTA, AI-obstacle, Patrol, firmware update):
  keep the probe running; the slot is `[PROTOCOL_NOVEL]`-flagged when it first fires.
- **device-messages/v2 fetch** — for s2p2 notification *text*: GET the cloud message
  store within its (~10-record) retention window after the code fires.
- **docked-window probe** — for action/opcode confirmation: only probe with the
  mower docked and watched; never brute-force siid/aiid (start-action incident).

## Priority blank-spots (most-fireable, best ROI first)

1. **s1p1 `[13][14][15]` state block** — fires every heartbeat; XTAB + one labelled
   return-to-dock likely cracks the locomotion sub-states (and gives an on-wire
   reorient signal).
2. **s5p106** (1426 occ) + **s5p105** — frequent, unknown, fire during reorient.
3. **s2p2 codes 20/33** — need a repro within cloud retention for the text.
4. **s1p4 `[10-21]` motion vectors** — high-value for richer telemetry; XTAB-able now.
5. **CFG BP/PATH** — one app-side pathway creation + CFG-DIFF closes it.
</content>
