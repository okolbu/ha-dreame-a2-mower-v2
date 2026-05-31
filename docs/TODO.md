# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For resolved / closed items see `docs/DONE.md`.
For the protocol *blank-spots* (undecoded bits/bytes, uncertain slots, corpus
coverage + how to validate each) see `docs/research/knowledge-gaps.md`.
For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
For overall protocol architecture see `docs/research/g2408-protocol.md`.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

### Probe for the AI-photo / obstacle-photo cloud endpoint

**Why:** The app shows AI obstacle photos with a confidence overlay (e.g. "human 80%"
= 80% it's a human in view). A SECOND app instance on another device shows the SAME
historical photo set → the photos sync via the cloud API, not BT. No "photo taken" MQTT
slot has been identified, so the photo list/metadata almost certainly lives behind a
cloud endpoint parallel to the `device-messages/v2` notification endpoint we already
found. Worth probing.
**Done when:** a photo/AI cloud endpoint (list + per-photo metadata incl. the
class+confidence overlay, e.g. "human 80%") is identified and documented, or ruled out.

**Progress (2026-05-31, `probe_ai_photo.py` + `iotstatus/history`/IPC sweeps):**
Systematically ruled the photo list OUT of every device-keyed surface reachable
with the integration's Dreame-Auth token (backend A):
- **batch device-data** — `getDeviceData` ignores the `key` filter and returns the
  full model; there is no AI/photo key. (Already true of every `dreame_cloud_dumps/`
  empty-batch read.)
- **`iotstatus/history`** (the device-data time-series query) — property-history for
  s2p55 / s2p51 / s1p53 → `{"list":[]}`; also empty for s2p1/s2p2 and siid=1/2
  event-history (eiid 1..20). This device historises nothing server-side.
- **`message-record/list`** categories 1..20 → 0 records (re-confirmed).
- **`device-messages/v2`** → empty (its ~6-7d retention window had no records at probe time).
- **guessed `/dreame-*/{ai-photo,obstacle-photos,device-photos}` paths** → 404.

**The one live lead:** `/smart-app/ipc/detection/event/list` — `libapp.so` carries a
full IPC event model (`imageUrl`, `picUrl`, `confidence`, `eventType`; detection
classes Human / Bird / Fire / Crying). It accepts our token (HTTP 400 *"Missing
necessary request parameters"*, **not** 404/auth), but the g2408 device record has
`videoStatus:null` + `featureCode:-1` → the mower is **not** enrolled as an IPC/camera
device, so this is most likely Dreame's security-camera product line. 7 param shapes
(deviceId/iotId/did × time/paging variants) all stayed at HTTP 400.

**Key state correction:** the feature is **ON at the cloud level** — `CFG.AOP=1` and
`REC[7] photo_consent=1` across all 8 dumps (2026-05-04..05-12). So the always-empty
`ai_obstacle[]` is **not** a disabled-feature artifact. This contradicts the stale
`reference_app_config` "Capture Photos AI Obstacles = Off" note (AOP maps to exactly
that switch — `switch_global.py:475/871`). Since the user reports the gallery syncing
to a 2nd app device, the photos DO exist cloud-side — on the app's own OAuth/Aliyun
backend (B/C), which our integration token can't fully drive.

**BREAKTHROUGH (2026-05-31) — Tasshack/dreame-vacuum analogue: there is NO separate
endpoint.** The vacuum integration reads obstacle photos inline from the map blob's
`ai_obstacle` array — the SAME field our `protocol/session_summary.py:140,385` already
parses (empty in our corpus). Per `OLD/.../dreame-vacuum/dreame/map.py:2086` +
`types.py:898`, each entry is `[x, y, type, possibility, key, file_name, random]`:
- photo exists only when `len>=7 and int(key)>=1000` (else it's a detection-only marker);
- `possibility` = the "human 80%" confidence (×100);
- `type` = obstacle class (vacuum enum 128-139 = furniture/clutter; the **mower's
  classes differ** — Human/Animal/Object per the app);
- `file_name` = an **OSS object name**, fetched via `get_interim_file_url(file_name)`
  — the SAME OSS path our mower already uses for maps/LiDAR (`cloud_client/_oss.py`).
The vacuum AES-CBC-decrypts the crop (its maps are encrypted binary); **g2408 maps are
plaintext JSON**, so the mower's `file_name` is likely a plaintext OSS key (decryption
need TBD). "2nd-device same set" = both apps read the same cloud blob's `ai_obstacle` +
fetch the same OSS objects — no per-account gallery service. Historical photos: vacuum
pulls them via `OBJECT_NAME` property-history; mower equivalent = MAPL/map-object history.

**LIVE TEST 2026-05-31 (partly refutes the vacuum analogue for LIVE surfaces).**
During a real walk-in-front mow where BOTH apps showed the new photo (mower still
mowing, not docked), every backend-A surface was empty: `getDeviceData` has NO
`ai_obstacle` key and all MAP `obstacles` are `[]`; siid=2/4/5 event-history + s2p55/
s2p51 property-history (last 90 min) empty; and the photo produced ZERO MQTT signal
(the `s2p51 {time,tz}` push is the clock heartbeat, not a detection). So unlike the
vacuum (ai_obstacle inline in the backend-A map blob), the g2408's LIVE photo lives
ONLY on the app's OAuth/Aliyun backend (B/C) — matching `/smart-app/ipc/detection/
event/list` accepting our token but rejecting all 24 param shapes. **The session-end
`.0550` `ai_obstacle` (the one backend-A field that's ever carried it) is still
unchecked for a detection session — that's the remaining MITM-free hope.** Tools:
`capture_ai_obstacle.py` (live MQTT) + `fetch_session_photos.py` (after-dock session
enumerator via `iotstatus/history` siid=4 eiid=1, piid=9=object_name).

**CONCLUSIVE 2026-05-31 — session-summary `ai_obstacle` REFUTED too.** The user gave
3 app-confirmed photo times; two (2026-05-30 19:15:20 + 19:22:54) fall inside the
05-30 19:00→19:27 session, yet that session's `.0550` summary has `ai_obstacle=[]`
(obstacle[LiDAR]=7). Photos captured but never written to ai_obstacle. Plus byte-diff
at all 3 photo times shows NO MQTT signal (byte[4] human-presence pulse never fired).
So the g2408's AI photos are on the app's B/C backend ONLY; `ai_obstacle` is a
vacuum-inherited slot the firmware never fills. The "MITM-free via session summary"
plan is dead.

**OBJ-list-by-type TESTED 2026-05-31 — negative.** The integration lists OSS objects
via `action(siid=2, aiid=50, [{m:'g', t:'OBJ', d:{type:'wifimap'}}])`. Swept ~40 types
while the mower was mowing (relay 80001 is intermittent — landed with retries; the
direct `dreame-iot-com-10000/device/sendCommand` call works, NOT probe_a2_mqtt's
`send()` which flaked). Result: the OBJ handler exposes ONLY map artifacts —
`wifimap` (1 obj `.0550.txt`) and `3dmap` (2 objs `.0550.bin` LiDAR) — every
photo/obstacle/human/camera/session/event name returned `{name:[]}`. Both real types
yield objects; no photo type does. So the OBJ list (the "list all images" candidate)
does NOT carry AI photos.

**Status:** backend-A EXHAUSTED — device-data, history, session-summary, MQTT, AND the
OBJ-list-by-type all tested empty for photos. Photos are B/C-backend-only. The ONLY
path is an **app HTTPS MITM** of the obstacle gallery (proxyman/) or cracking the
`/smart-app/ipc/detection/event/list` params (same wall as Phase-2 MAP write /
cruise-to-point). `fetch_session_photos.py` / `probe_obj_types.py` returning empty is
now confirmed-expected. Reframe the feature as MITM-gated.
**Next step (MITM-FREE):** capture the live MAP blob + session summary during/after a
**real detection** (walk in front of the mower mid-mow with AOP on) and check whether
`ai_obstacle` populates with 7-element entries; if so, fetch `file_name` via the existing
`get_interim_file_url`. Then surface as a per-obstacle camera/event entity. (The earlier
HTTPS-MITM step is now a fallback, not the primary path.)

**TOOL READY — `/data/claude/homeassistant/capture_ai_obstacle.py`** (dev-box only,
read-only; validated end-to-end 2026-05-31 against a real session summary — OSS
fetch + decode + obstacle-scan all confirmed working). Run it, then walk in front of
the mower mid-mow. It tails MQTT (flags s2p55/s2p51/s2p2/s1p1/s1p4 + event_occured
object_names), polls the cloud, downloads every OSS object it sees, dumps any
non-empty `ai_obstacle`/`obstacle` array (decoded per the vacuum analogue), and for
each `ai_obstacle` entry with a `file_name` downloads the photo bytes and classifies
them (JPEG/PNG/gzip/maybe-AES). Output → `ai_obstacle_capture_<ts>/` (capture.jsonl +
objects/ + SUMMARY.txt). `--test-object <name>` verifies the OSS path without waiting.
Once a capture confirms the on-wire `ai_obstacle` layout, wire the integration parse
(`session_summary.ai_obstacle` is already a raw tuple) + a per-obstacle camera/event entity.
**Implementation note:** `session_summary.ai_obstacle` is already parsed (raw tuple) and
`get_interim_file_url`/`get_file_url` already exist — wiring is mostly: parse the
7-element entry, fetch+maybe-decrypt `file_name`, expose confidence/type/coords.
**Cross-refs:** `OLD/alternatives_archive_2026-05-05/alternatives/dreame-vacuum`
(`dreame/map.py:2086`, `types.py:898`, `protocol.py:371`); GH `Tasshack/dreame-vacuum#1326`;
`inventory.yaml` § s2p55 (verifications 2026-05-31); `protocol/session_summary.py:140,385`;
`cloud_client/_oss.py`; `probe_ai_photo.py`; `docs/research/g2408-research-journal.md`.

---

### Probe `message-record/list` for the System/Sharing/Service/Activity tabs

**Why:** `device-messages/v2` returns only per-device (A2) records. The other
four tabs in the app come from `/dreame-message-push/v2/message-record/list`,
which returned `code=0 records=0` for `categories=[1..5]`. Possible reasons:
right category id is higher than 5, or `did` is the wrong filter for an
account-scoped endpoint, or content is behind v1 or a different service.
Not blocking the cloud-notification feature (we don't want Dreame-wide
announcements in the integration); just an open research question.
**Done when:** the actual category ids for System Messages and friends are
known, or we conclude the endpoint isn't reachable with current auth.
**Status:** open (low priority)
**Cross-refs:** `docs/research/app-api-surface-2026-05-25.md` § device-messages/v2; `probe_a2_endpoints.py`.

### Phase 2: MAP write — programmatic boundary/zone editing

**Why:** With chunked-batch writes confirmed working (Phase 1 done in
v1.0.2a1), the MAP surface is the next big capability. Drawing
boundaries and editing mowing/exclusion zones from HA without walking
the mower would be a major UX win.
**Done when:** A safe MAP write surface exists with auto-backup of the
current MAP blob before any write, restore-from-backup mechanism, and
a Lovelace card for boundary editing.
**What we tried (archived detail):** `probe_add_maintenance_point.py`
(2026-05-13) sent the `siid=2 aiid=50` TASK envelope for o:204→o:234→o:201
with 4 payload shapes — all HTTP 400 at `/device/sendCommand` (the cloud
doesn't route map-edit opcodes from us via this transport). Leading hypothesis:
the app POSTs geometry to a separate `/map`/`/region` HTTP endpoint and the
cloud emits the MQTT echoes server-side → needs an HTTPS MITM of a real
map-edit to find it. Fallback: `setDeviceData` MAP-blob write (risky; needs a
re-encode parity test first).
**Status:** open
**Cross-refs:** spec
`docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
"Phase 2"; `docs/research/cloud-write-reference.md`; archived research
`OLD/ha-dreame-a2-mower-docs/research/map-edit-write-todo.md`.

### Cruise-to-Point / Head-to-Maintenance-Point trigger button (op=109)

**PROTOCOL SOLVED — this is now pure implementation work (2026-05-31).** The
send shape is confirmed live end-to-end: `routed_action(109, {"point":[point_id]})`
made the mower drive from the dock to maintenance point 1 and arrive
(user-confirmed). Full detail in `inventory.yaml` o109 (verified 2026-05-31).

Key facts for the implementation:
- **Send:** `{m:'a', p:0, o:109, d:{point:[point_id]}}` via `routed_action` — the
  same path/transport as the working mow ops. The `d`-key is the target *type*
  (`point`), NOT spot's `{area:[id]}` (that key is rejected with `status:false`).
- **Per-map:** cleanPoints/maintenance points are per-map (`id` is per-map; on this
  account map 0 has ids 1,2, map 1 has none). A bare id worked because the target
  was on the **active** map — so `start_go_to_point` must `_ensure_active_map(map_id)`
  first (op=200), exactly like `start_mowing_spot`. (Untested whether
  `{point:[[map_id,id]]}` also works and avoids the map switch.)
- **Read side already done:** lifecycle `s2p50 status:true → s2p56=[[id,0]]→[[id,2]]
  → s2p1=2 → s2p2=75 arrived_at_maintenance_point → s1p52={}`; the notification
  synthesizer already fires arrival off `s2p2=75` (and `s2p2=76` = "cannot reach").
- **Transport/wake note:** an idle-docked g2408 80001s the first 1–2 sends (relay
  waking the device), then accepts; `send()` does NOT retry 80001. The HA
  integration rarely hits this (its constant cloud polling keeps the device
  engaged). If GO_TO_POINT ever flakes from a deep-idle dock, add a small
  wake-retry — but mow-start has the same property and works, so likely unneeded.

**Implementation checklist:**
1. `mower/actions.py`: add `MowerAction.GO_TO_POINT` (siid 5, aiid 1, routed_o 109,
   payload_fn `_go_to_point_payload`); `_go_to_point_payload(params)` → `{"point":
   [int(params["point_id"])]}` (raise on missing).
2. `coordinator/_writes.py`: `start_go_to_point(*, map_id, point_id)` →
   `_ensure_active_map(map_id)` then `dispatch_action(GO_TO_POINT, {"point_id":…})`,
   mirroring `start_mowing_spot`.
3. Per-map button entity reading the map's cleanPoints (one button per point, or a
   point select + a "go" button); follow the per-map naming convention.
4. `entity-inventory.yaml` entry; replace the dashboard "Head to Maintenance Point"
   placeholder.
5. Tests (TDD) for the payload fn + dispatch + active-map switch.

**Status:** open — protocol done; ready to implement (no further capture needed).
**Cross-refs:** `inventory.yaml` o109 (verified 2026-05-31) + o103 (wake-retry);
`tools/probe_cruise_to_point.py` (`--routed-shape`/`--routed-byid`/`--spot-control`,
all with `--retries`); `mower/actions.py` + `coordinator/_writes.py:start_mowing_spot`
(the pattern to mirror); archived research
`OLD/ha-dreame-a2-mower-docs/research/cruise-to-point-todo.md`.

### Re-verify EdgeMaster / Mowing Efficiency cloud-field correlations

**Why:** `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md`
catalogued EdgeMaster (`s6p2[2]`) and Mowing Efficiency (`s6p2[1]`)
as BT-only / not-in-cloud-CFG. Those claims predate the
2026-05-08 cloud-discovery findings and may be outdated; both could
now be writable via `setDeviceData` if the cloud surfaces them under a
chunked-batch key we haven't probed.
**Done when:** Toggle each in the app while monitoring the empty-batch
read; if any chunked-batch key changes, surface as a new entity. If
neither changes, document as confirmed BT-only post-cloud-discovery.
**Status:** open
**Cross-refs:** historical doc; `docs/research/cloud-write-reference.md`.

### Capture zone / edge action codes for SCHEDULE blob

**Why:** The SCHEDULE blob format was decoded 2026-05-08 (see
`protocol/schedule.py` for the verified record layout). The action-
type nibble has only been observed as `0` (All-area mowing) — the
zone (1?) and edge (2?) codes are not yet pinned down. The user's
Dreame app supports All-area / Zone / Edge plans; capturing one of
each in the cloud blob would close out the catalogue.
**Done when:** the user adds a Zone-mowing and Edge-mowing schedule
in the app, the next cloud dump is captured, and the `_ACTION_LABELS`
dict in `sensor.py` is updated with the verified codes (plus
appropriate test fixtures in `tests/protocol/test_schedule.py`).
**Status:** blocked-by-user-data
**Cross-refs:** `custom_components/dreame_a2_mower/protocol/schedule.py`;
`/data/claude/homeassistant/schedule-doc.txt`

### OTA_INFO field semantics

**Why:** v1.0.0a100 surfaces `cloud_state.ota_status` as
`(int, int)` — the test fixture observed `(2, 100)`. We assume
the first field is a status code and the second is a percent (0-100),
but neither has been confirmed during a real OTA update. The
sensor uses `state = ota_status[0]` and `attr percent = ota_status[1]`;
mapping numeric statuses to human-readable strings (idle / downloading /
applying / failed / etc.) requires observation during an actual OTA.
**Done when:** the status-code → state-string mapping is documented
in `docs/research/g2408-research-journal.md` and the sensor either
returns the string directly or exposes both via attributes.
**Status:** blocked-by-OTA-observation (next firmware update).
**Cross-refs:** spec "Out of scope" item 5.

### Add integration icon via home-assistant/brands PR

**Why:** The HA Integrations page shows a blank square or nothing next to the
Dreame A2 Mower entry. Icons must come from `home-assistant/brands`, not the
integration's own folder.
**Done when:** A PR is merged to `home-assistant/brands` adding
`custom_integrations/dreame_a2_mower/icon.png` + `icon@2x.png`; the icon
appears on the Integrations page and in HACS.
**Status:** open
**Cross-refs:** upstream `home-assistant/brands` repo; source image at `/data/claude/homeassistant/dreame-a2-icon-large.jpg`

---

### Surface dock-departure repositioning UX

**Why:** The Dreame app shows a 3-stage popup ("Exiting the station" /
"Repositioning..." → "Reorienting" / "Repositioning Successful" → the task
message, e.g. "Starting to mow" for a mow, "Heading to maintenance point" for
op=109) at every dock departure, BEFORE the first move. No MQTT property
carrying this exact relocate-state has been identified — three dock departures
on 2026-05-05 produced no `s2p65` or `s5p104..107` events; the popup driver is
off the sniffed wire (cloud-only, like the Reorient popup).

**Partially shipped (2026-05-31):** the *command-time awareness* half is done —
on any task-start echo (`s2p50` status:true, op ∈ {100,101,102,103,108,109})
the integration now sets the task-appropriate `current_activity`, leaves the
`AT_DOCK` location (→ `ON_LAWN`), and switches the live map out of the striped
pre-start preview into trail mode IMMEDIATELY, instead of lagging ~45s until
`s1p4` position telemetry resumes (the undock reorientation silence). Applies to
all session types. See `mower/state_machine.py:_apply_s2p50_task_envelope`
(`_TASK_START_OPS`), `map_render/main_view.py` (`_is_active_non_mow_session`),
`coordinator/_mqtt_handlers.py` (command-time `_render_main_view`). This removed
a false `IN_SESSION+MOWING+AT_DOCK → CHARGE_RESUME` reconcile at startup.

**Remaining (still blocked-by-capture):** identify WHICH MQTT/cloud message
drives each of the app's 3 popup steps, so we can surface the distinct
"Repositioning / Reorienting" sub-phase (deferred — needs a timed capture
correlating the popup edges to the wire; the popup itself is likely cloud-only).
**Done when:** the per-step relocate-state driver is identified, or confirmed
cloud-only (document + close the sub-phase).
**Status:** command-time awareness DONE; sub-phase messaging blocked-by-capture
**Procedure:** [docs/research/g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture](g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture)
**Cross-refs:** `docs/research/g2408-protocol.md §1` (80001 failure context); probe-log correlation needed

---

### Alert-tier event surface (follow-up to lifecycle PR)

**Why:** The lifecycle-tier event surface (a91) reserved
`event.dreame_a2_mower_alert` with empty `event_types`. Populate it
with `emergency_stop`, `lifted`, `tilted`, `stuck`, `bumper_error`,
`obstacle_with_photo`, `battery_low`, `battery_temperature_low`, `error`.
Add `CONF_NOTIFY` option toggle. Migrate the existing bespoke
`_handle_emergency_stop_transition` banner to a framework-managed
persistent_notification gated by CONF_NOTIFY.
**Done when:** All listed event_types fire from the appropriate
detection sites; `_handle_emergency_stop_transition` is replaced;
docs/events.md gains the alert section; emergency_stop banner
behavior is unchanged from the user's perspective.
**Status:** open
**Cross-refs:** `docs/superpowers/specs/2026-05-07-event-surface-design.md` § "Out of scope"

---

### Lifecycle event-surface PR — review-flagged cleanups

**Why:** The final whole-branch review of v1.0.0a91 (the lifecycle event
surface) flagged five non-blocking follow-ups that should not be lost:

1. **conftest.py placement** — `tests/event/conftest.py` stubs only
   `homeassistant.components.event` while the root `tests/conftest.py`
   already stubs every other HA component in one place. Fold into the
   root conftest for consistency.
2. **Unused `_attr_translation_key`** — both event entities set
   `_attr_translation_key="lifecycle"` / `"alert"` but `translations/en.json`
   has no `entity.event.*` block. Either add the translation entries
   or drop the unused keys.
3. **`_make_coordinator_for_persist_tests` fixture incomplete** —
   `tests/integration/test_coordinator.py` has three coordinator-stub
   fixtures; two set `_lifecycle_event` / `_alert_event` / `_prev_in_dock`,
   the persist one only sets `_prev_in_dock`. Latent foot-gun if a
   future test extends the persist case to call fire-paths.
4. **`mowing_ended` may double-fire on cloud md5 dedup hit** —
   `_do_oss_fetch` fires `_fire_mowing_ended` even when the cloud reused
   the md5 (dedup hit). The session was already finalized once; firing
   again is questionable. Add a guard or accept and document.
5. **`reason` heuristic in `mowing_paused`** — only emits
   `"recharge_required"` when `battery_level <= 20`; nullable
   `battery_level` always resolves to `"unknown"`. The threshold 20 is
   a magic number. Pull into a const, handle None explicitly, and
   consider expanding the reason vocabulary alongside the alert-tier PR.
**Done when:** Each of the five items is either fixed or explicitly
closed with a "won't fix because X" note.
**Status:** open
**Cross-refs:** final review on commit `e32c8f4..51f6883`;
`docs/superpowers/plans/2026-05-07-event-surface-lifecycle.md`

---

### Novel-observation sensor floods on continuous-integer slots

**Why:** `sensor.dreame_a2_mower_novel_observations` accumulated 51 entries
before a reboot 2026-05-07 and 5 since. All observed entries are
`category: value` for slots without a `value_catalog` — e.g. `s3p1`
battery_level (every new percentage triggers), `s5p107` energy_index
(int 1..250), `s1p53` obstacle_flag (True/False both fire on first
observation). The registry's first-time-seen-value path is correct as
a log signal but is noise on the user-visible sensor.
**Done when:** The sensor's `observations` attribute filters out
`category: value` entries for slots whose `_INVENTORY.value_catalogs`
entry is None. INFO-level logging of those novelty events stays so
contributor diagnostics aren't lost.
**Status:** open
**Cross-refs:** `coordinator.py` novelty dispatch around line 2843;
`observability/registry.py`

---

### Trigger a fresh WiFi heatmap render

**Why:** v1.0.3a7 ships a working `camera.dreame_a2_mower_wifi_heatmap`
that renders the **latest cached** WiFi map from OSS, plus a
`button.request_wifi_map` that refreshes the cache. But there's no
way for the integration to *trigger a fresh scan* on the device:

- `s6.aiid=4` (the "request fresh" path per ioBroker.dreame v0.3.7 +
  Tasshack `dreame-mover` — they fire-and-forget then wait 30s for
  the OSS object to appear) returns 80001 on g2408 — the siid=6 RPC
  tunnel is closed on this firmware. Verified 2026-05-09.
- Same `g.OBJ d={type:'wifimap'}` route returns 2 already-cached
  objects (auto-generated by the mower at unknown trigger times).

So today the user sees whatever the mower last decided to render —
not a freshly-commissioned scan. This is a niche feature on a robot
mower (most users don't care about WiFi coverage) but worth pinning.

**Suspected real path** (in priority order for a future sniff):

1. **Routed-action opcode** — like `op=10 GENERATE_3D_MAP`, there
   may be a `op=N REQUEST_WIFI_MAP` we haven't enumerated. Try a few
   sequential opcodes near 9-12 once docked, watching for new OSS
   objects 30-60s later.
2. **MQTT direct publish** to `/cmd/<did>/` — Xiaomi-pattern command
   bypass. Same suspected path as SCHEDULE writes.
3. **Different cloud HTTP endpoint** — outside the routed-action /
   chunked-batch / MIoT-property surfaces.
4. **A scheduled-trigger entity-of-interest** — maybe writing a
   specific CFG key (e.g. setting some "wifi diagnostics" flag) makes
   the device run its own scan and upload.

**Done when:**
1. We can call a method that produces a NEW wifimap OSS object within
   ~60s (verifiable: `g.OBJ d={type:'wifimap'}` returns a previously-
   unseen filename).
2. `button.request_wifi_map` triggers that fresh scan + auto-fetches
   the new file once it appears (no manual second tap needed).
3. Matrix row flipped from "✓ refresh-from-cache only" to "✓ end-to-end".

**Status:** open (Phase 3 — needs HTTPS+MQTT sniff while watching the
Dreame app's wifi-map UI; same sniff session can cover the SCHEDULE,
SETTINGS, AI_HUMAN, and BAT/REC/LANG-int-list gaps).
**Cross-refs:** `cloud_client.fetch_wifi_map`, `coordinator._refresh_wifi_map`,
`button.request_wifi_map`, `camera.dreame_a2_mower_wifi_heatmap`, the
matrix `button.request_wifi_map` row. Archived issue list (resolution unit
RESOLVED; open: heatmap→map correlation, overlay upsampling):
`OLD/ha-dreame-a2-mower-docs/research/wifi-heatmap-todo.md`.

---

### WiFi heatmap overlay on the live map

**Why:** v1.0.3a7 renders the WiFi heatmap as a standalone PNG
(`camera.dreame_a2_mower_wifi_heatmap`). The decoded JSON includes
`startX`, `startY`, `resolution`, `width`, `height` — all in the same
cloud-frame coordinate system as the lawn map. So the heatmap can be
reprojected onto the live-map renderer as a translucent layer, giving
users a "WiFi coverage by lawn area" view they can toggle on/off.

User suggestion 2026-05-09: "potentially a toggled heat map of
colored squares on top of the main map. Potentially oriented from the
dock?". Anchor is straightforward — same coordinate frame; the
existing renderer already handles cloud-frame → image-frame
transforms. Toggling can either be a switch entity ("WiFi overlay
on/off"; `MowerState.wifi_map_overlay_enabled`) or a Lovelace
picture-elements layer.

**Done when:**
1. `map_render` accepts a `wifi_map_data` kwarg that, when truthy,
   composites the RSSI cells over the lawn pixels at the right cloud-
   frame offsets and resolution.
2. A user-controllable switch (`switch.show_wifi_overlay` or similar)
   gates the overlay so it can be turned off.
3. The Mower-tab live map updates when the switch flips and when
   `MowerState.wifi_map_data` changes.
4. Cell rendering is alpha-blended (~50% so the lawn underneath is
   still visible) and uses the same red→yellow→green dBm gradient as
   the standalone camera.

**Status:** open (design+implement). Lower priority than the
GPS-coords gap and the SETTINGS Phase 3 sniff.
**Cross-refs:** `wifi_map_render.py`, `map_render` (live-map renderer),
`docs/research/cloud-map-geometry.md`.

---

### GPS world-coordinate read path — find the surface the Dreame app uses

**Why:** `device_tracker.dreame_a2_mower_location` is plumbed to the cloud `routed-action g.LOCN → {pos: [lon, lat]}` path, but on g2408 LOCN returns the `[-1, -1]` sentinel even with `switch.anti_theft_realtime_location` (CFG.ATA[2]) ON. The Dreame app's **Real-Time Location** sub-page nevertheless shows the mower at its correct world coordinates, so the app reads GPS from a different cloud / MQTT surface that the integration has not yet identified. The legacy fork hit the same wall (`coordinator.py:287-294`).

**Confirmed it's NOT**:
- `routed-action g.LOCN` (returns sentinel)
- LIDAR / odometry (those are mower-frame, not world-frame)
- a "dock GPS origin anchor" — user 2026-05-09 confirmed the mower has its own GNSS hardware
- the apk geofence subsystem (apk.md line 242 confirms it's for phone-GPS smart-lock auto-unlock, not the mower)

**Suspected candidates**:
- A different cloud routed-action key (`GPSPOS`, `GEOLOC`, etc.) we haven't probed
- An MQTT push: a `s2p51` message type beyond what we currently dispatch, or a broader robot-pose extension on `s1p4`
- A separate cloud HTTP endpoint outside the routed-action / chunked-batch surfaces
- ioBroker's apk catalog mentions `LOCN setLocation {pos}` for setting the GPS — the read counterpart on a healthy device may not be `getCFG` but rather a different envelope

**Done when:**
1. An HTTPS sniff of the Dreame app on the Real-Time Location page identifies the actual surface (request body + response shape).
2. `cloud_client` adds a fetch path (likely a new method, parallel to `fetch_locn`).
3. `_refresh_locn` is repointed (or a new `_refresh_gps_world` runs alongside).
4. `device_tracker.location` populates with valid lat/lon while ATA[2] is on; the dashboard's GPS map card renders.
5. Validation matrix row flips from ✗ live (KNOWN GAP) to ✓ end-to-end.

**Workaround for users right now**: open the Dreame app's Real-Time Location sub-page directly. The HA dashboard hides the map card while ATA[2] is off and falls back to a "toggle on to enable" notice — the same notice now mentions this gap so the user knows the integration's path isn't the same as the app's.

**Status:** open (Phase 3 — needs HTTPS capture). Recipe candidate to bundle with the broader Phase 3 sniff session (Phase 3 also covers SETTINGS / AI_HUMAN.0 / SCHEDULE writes).
**Cross-refs:** `docs/research/entity-validation-matrix.md` device_tracker row; `cloud_client.fetch_locn`; `coordinator._refresh_locn`; `OLD/alternatives_archive_2026-05-05/ha-dreame-a2-mower-legacy/custom_components/dreame_a2_mower/coordinator.py:287-294` (legacy reaching the same conclusion); archived negative-results detail `OLD/ha-dreame-a2-mower-docs/research/gps-tracking-todo.md`.

---

### LiDAR archive AND WiFi heatmap — per-map (CONFIRMED REQUIRED)

**Why:** The Dreame app's "pick the current map" screen exposes a
**dedicated LiDAR button per map** (user observation 2026-05-09) — so
the firmware does keep a distinct LIDAR blob for each map, not a
single global one. Today's `lidar_archive` is a flat folder; we need
to scope archives by `map_id` and surface per-map LIDAR cameras /
selectors so a user looking at Map 1 sees Map 1's LIDAR scans, not
Map 2's.

**Same gap applies to WiFi heatmaps** (v1.0.3a7+): the wifi map JSON
includes `startX`/`startY`/`resolution`/`width`/`height` in the
cloud-frame coordinate system, which is **per-map** (each map has its
own bbox). Currently `cloud_client.fetch_wifi_map` picks the newest
OSS object regardless of map; if the user has multiple maps, they'd
see whichever map was scanned most recently, not "the wifi map for
Map 1". Same coordination as LIDAR — needs `map_id` on cached entries
and per-map camera entities (or selector).

**Done when:**
1. lidar_archive entries carry a `map_id` field (or live in per-map
   subdirectories).
2. The LiDAR camera entities are per-map — `camera.lidar_top_down_<map_id>` /
   `camera.lidar_full_resolution_<map_id>` — or a single camera with a
   selector that picks which map's latest scan to render.
3. The fetch path knows which map a new LIDAR blob belongs to. Likely
   sourced from the same `s2p51` push or routed-action key that
   identifies the active map at scan time.
4. The LiDAR dashboard tab updates to show the relevant per-map view.
5. Backwards-compatibility: existing flat archives are migrated to
   "unknown map" or to the active map at migration time so we don't
   lose history.

**Status:** confirmed required (was investigation, now design+implement)
**Cross-refs:** `custom_components/dreame_a2_mower/lidar_archive.py`;
`docs/multi-map.md` "Limitations" section; dashboard `LiDAR` tab.

---

### `edgeMowingWalkMode` — identify the app-side setting

**Why:** The cloud SETTINGS field `edgeMowingWalkMode` is exposed as
`select.<map>_edge_walk_mode` (values `walk_0` / `walk_1`), but no
toggle in the Dreame app appears to correspond to it. Curiously the
JSON key order in `SETTINGS.0` roughly matches the order of toggles in
the app's Mowing Settings screen, and `edgeMowingWalkMode` sits
between `mowingHeight` and `edgeMowingAuto` — which is where the app
shows "Mowing Direction" (the Standard / Crisscross / Chequerboard
selector). That direction selector is already wired to the
`mowingDirectionMode` field (our `Mowing Pattern` select), so
`edgeMowingWalkMode` is plausibly something different — perhaps a
hidden/A-B flag, an edge-walk strategy parameter, or a deprecated
field.
**Done when:** Physical test: run an Edge mow on the same map twice,
once with `edgeMowingWalkMode=0` and once with `=1`, and observe
whether the mower's edge-tracing behaviour differs (path shape,
direction, lap count, speed). Either confirm a behavioural delta and
characterise it, or confirm no observable delta and document the
field as cosmetic/no-op so we can decide whether to keep the entity.
**Status:** open
**Cross-refs:** `select.py` § `DreameA2PerMapEdgeMowingWalkModeSelect`;
`docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
(field values observed: entry0/map0=0, entry0/map1=0, entry1/map0=1,
entry1/map1=1 — both states known to be accepted by the cloud).

---

### Audit protocol docs for debunked-knowledge leakage (corpus-validate conflicting claims)

**Why:** The s2p2=28 incident (2026-05-30) exposed a recurring failure mode:
a wrong reading derived from a **single biased log** ("28 = off-dock relocate
marker, fires 14/14 on every undock" — computed only from `probe_log_20260520`,
which happens to cover the worn-blade window) got promoted to a `verified:`
inventory entry and leaked into `error_codes.py`, the mova cross-check doc, and
the notification-history doc. The correct reading (28 = wear%-gated blade-wear
push) co-existed alongside it. A new session leaning on the "latest entry" nearly
re-propagated the wrong one. Two systemic risks: (a) conflicting doc entries where
"latest wins" silently regresses correct older info; (b) findings asserted from one
run that don't hold across the corpus.
**Done when:**
1. Sweep `inventory.yaml` + `docs/research/` for claims marked `verified` whose
   evidence is a **single** probe log, and re-validate each against the full
   corpus (`probe_log_*.jsonl`, 9 logs / ~66 undocks). Downgrade any that don't
   replicate corpus-wide to `partial`/`presumed` with a corpus note.
2. For every code/field with two or more conflicting `semantic:` or verification
   readings, add an explicit "current best reading + which older readings are
   superseded and why" so a future session can't silently pick the wrong one.
3. Document the rule in CLAUDE.md § Fact discipline: a wire-pattern claim is not
   `verified` from one run — it needs corpus-wide consistency; if it doesn't hold
   across the corpus it can't be confirmed. (Tooling: `_corpus.py` is a starting
   point — consider promoting it into `tools/`.)
**Status:** open
**Cross-refs:** `inventory.yaml § s2p2` (2026-05-30 retraction) + `§ s1p1`
(2026-05-30 corpus verification); `mower/error_codes.py` code 28; memory
`feedback_corpus_validate_protocol_claims`.

---

### Replace guesswork multi-variable state inferences with fact-based signals

**Why:** Reviewed (2026-05-30) every combination-gated state/action in
`mower/state_machine.py` + the `coordinator/` session handler. Most combinations are
**fact-based and fine** — keep them:
- `_apply_charging`: charging=True → location=AT_DOCK (physical invariant). ✓
- `_apply_cloud_dock`: ignore a stale cloud AT_DOCK while IN_SESSION+ON_LAWN (the
  5-10 min cloud DOCK lag is observed). ✓
- `_apply_s2p1_task_state`: s2p1=6 → CHARGE_RESUME vs IDLE by mow_session (real
  distinction; collapses two facts into one activity enum but the logic is sound). ✓
- `_apply_s2p56_lifecycle`: stage=2 + CRUISING_TO_POINT → AT_POINT (good composition:
  generic stage field + task type → meaning; redundant-but-consistent with s2p2=75). ✓

The **guesswork** combinations (your hunch — inference, not protocol fact):
1. `_reconcile_mow_activity` (state_machine.py ~434): IN_SESSION + MOWING + AT_DOCK →
   CHARGE_RESUME, comment literally "pick CHARGE_RESUME since that's how the mower
   behaves". Should read the actual charging/s3p2 signal, not guess from a triple.
2. `_reconcile_mow_activity` (~409): IN_SESSION + CHARGE_RESUME + off-dock + area>0 →
   MOWING — a 4-condition self-heal inference for a dropped MQTT push.
3. `_mqtt_handlers` (~376): pause **reason** = `recharge_required` if `battery<=20`
   (magic number, "best-effort") — should read the real pause cause (s2p2 in the pause
   window), not infer from battery. (Already noted in the lifecycle-review TODO.)
These are RECOVERY heuristics (self-heal stuck state from missing signals — see the
state-machine-audit), so they're load-bearing; **don't rip them out blindly**, replace
each with the fact-based signal where one exists, otherwise label it explicitly as an
inference fallback.
**Done when:** items 1-3 either read a direct signal or are explicitly marked
"inference fallback (no direct signal)"; a quick pass over `coordinator/_session.py`
finalize gate + `live_map/finalize.py` decide() confirms no other guesswork combos.
**Status:** open
**Cross-refs:** `mower/state_machine.py § _reconcile_mow_activity`;
`coordinator/_mqtt_handlers.py` pause-reason; memory `project_state_machine_audit`;
DONE.md "Decouple the s2p2 71/31/33 state model".

---

### Audit for misleading authoritative-sounding names on unverified/wrong meanings

**Why:** A sibling to the debunked-knowledge audit, but specifically about *names*:
apk/vacuum-derived identifiers that read as fact while the meaning is unverified or
wrong. Confirmed instances this session: s2p2=28 (off-dock-marker → blade-wear),
s2p2=71 (positioning_failure → standby-return), s1p1 byte[14] (startup_state_machine
→ locomotion_state), CMS[3] (Link Module → unidentified). Standing risks:
- The hypothesized `s2p2` fault catalog (state_codes `s2p2_37`=RIGHT_MAGNET, 38=FLOW_ERROR,
  40=CAMERA_FAULT, 49=LDS_BUMPER, 59=NO_GO_ZONE, …) — vacuum/apk names, **never observed
  on g2408**, but the NAME reads authoritative.
- `s2p2=20` is correctly flagged "NOT battery" in inventory + probe_a2_mqtt.py, BUT old
  probe jsonl entries have the stale `BATTERY_LOW` label baked in at capture time — a
  reader scanning a 05-25 log sees a wrong label with no caveat.
- Vacuum-side s4p* names (cleaning_mode, pet_detective…) for slots g2408 never emits.
**Done when:** a sweep of `inventory.yaml` (state_codes/mode_enum), `mower/error_codes.py`,
`probe_a2_*.py`, and the mova/apk cross-check docs flags every authoritative-looking
name whose meaning is `hypothesized`/`unknown`/contradicted, and either neutralizes it
(e.g. `s2p2_40_unverified` / "apk-name, unobserved on g2408") or annotates it inline so
it can't be mistaken for a confirmed g2408 fact. Decide a convention for marking
unverified names (the `decoded:` status helps but the bare identifier still misleads).
**Also (housekeeping, bundle while touching the probe tools):** the probe scripts
write log files (`probe_log_*.jsonl`) into `/data/claude/homeassistant/` root, which
is cluttered with test/log/temp files. Update the probe tooling to write into a
subdirectory (e.g. `probe_logs/`), and consider the same for the throwaway analysis
scripts (`_corpus.py`, `_reorient.py`, `_s1p1.py`, `_win.py`, …). Keep paths the
analysis scripts read in sync.
**Status:** open
**Cross-refs:** `inventory.yaml` § state_codes (s2p2_37..117 hypothesized names);
`mower/error_codes.py`; `probe_a2_mqtt.py` (+ log-path); `docs/research/mova-mower-a1-crosscheck-2026-05-25.md`;
sibling: "Audit protocol docs for debunked-knowledge leakage"; memory
`feedback_corpus_validate_protocol_claims`.

---

### s2p1 mode enum vs apk table — reconcile remaining conflicts + s2p56 umbrella question

**Why:** Folded in from `things.txt`. The apk's product-agnostic mode table lists
`3: "Working"`, but the probe corpus shows s2p1=3 always co-incident with s2p56
status `[[1,4]]` — decoded as "Paused" in `inventory.yaml § s2p1` (5 observations,
2026-04-17 and 2026-04-22/28/29). Value 16 ("Battery Temp Hold") is also ours, not
in the apk table. The label side is mostly reconciled already; the open part is the
**s2p56-vs-s2p1 relationship** — s2p56 also carries a task value, so one may be an
umbrella state ("in a session but currently charging") over the other. Side note
worth keeping: this is the *only* enum table the app exposes that is product-type
agnostic; every other table is vacuum-worded.
**Done when:** the s2p1↔s2p56 relationship is documented (is s2p56 the
session-umbrella state and s2p1 the instantaneous activity, or vice-versa?), and any
remaining apk-vs-wire label conflicts are annotated in `inventory.yaml § s2p1` /
`§ s2p56`.
**Status:** open (low priority — labels largely resolved; see `inventory.yaml § s2p1`)
**Cross-refs:** `inventory.yaml § s2p1`, `§ s2p56`; was `things.txt`.

---

### `summary_map[boundary_layer].track` over-segmentation — identify the break trigger

**Why:** The cloud's session-summary track field over-segments the mow path: in a
48-min Map 2 sample (2026-05-09), 27 single-point / 43 two-point / 24 three-point
segments out of 150 sit ON the eventual continuous trail (not outliers). The user's
read is "they appear to show something significant" — could be a load-bearing signal
we discard (pen-up / blade-state change / phase boundary / AI-obstacle proximity /
cloud heartbeat).
**Done when:** the break trigger is identified (the five candidate triggers + s1p4
decode steps are catalogued in `inventory.yaml § summary_map_track.open_questions`),
and the segments are either surfaced as a signal or documented as cloud-noise. NB the
replay card already filters <2-point legs, so this is a protocol question, not a
display bug.
**Status:** open (low priority)
**Cross-refs:** `inventory.yaml § summary_map_track.open_questions`;
`protocol/session_summary.py`; `live_map/trail.py`; memory
`project_track_oversegmentation_todo`.

---

### Session calendar — one-tap replay card

**Why:** The Sessions tab uses the HACS `atomic-calendar-revive` card, so
replaying a session is two surfaces / two clicks (find it on the calendar →
match the label in the Replay picker dropdown → tap). One-tap-from-the-calendar
isn't possible with either the HA-native `type: calendar` (hard-coded more-info
popup) or atomic-calendar-revive (its `tap_action` fires the same call for every
event — no per-event `{{event.summary}}` substitution). Both confirmed
2026-05-13.
**Done when:** a bundled custom JS card
(`www/dreame-a2-session-calendar.js`, registered like the existing lidar/schedule
cards) renders a month grid from `calendar.dreame_a2_mower_sessions` and, on a
session tap, calls `select.select_option` on `select.dreame_a2_mower_work_log`
with the event summary — driving the existing replay camera. Drops the
atomic-calendar-revive dep. (~half-day; the work_log label match is pinned by
`tests/integration/test_calendar.py`.)
**Status:** open (low priority — UX nicety).
**Cross-refs:** `www/dreame-a2-lidar-card.js` (bundled-card pattern);
`calendar.py::_event_from_entry`; archived design
`OLD/ha-dreame-a2-mower-docs/research/session-calendar-todo.md`.

---

## In-progress

_(none currently)_

---

## Blocked

### Mowing direction / Crisscross / Chequerboard pattern

**Why:** No observable property on the device's MQTT `/status/` topic carries
mowing direction or pattern. An 8-change test on 2026-05-04 produced eight
`s6p2` events all with the identical payload — the actual setting value is
absent from the outbound MQTT. Likely cloud-resident or BT-only.
**Done when:** A CFG key carrying the direction value is found via `getCFG`
brute-force (try `MOWP`, `MD`, `DIR`, `ANG`, `PAT`) OR the feature is
confirmed cloud/BT-only and documented as unsurfaceable.
**Status:** blocked-by-investigation (BT-only suspected)
**Cross-refs:** `docs/research/g2408-protocol.md §1.2` (80001 / BT channel)

---

### `ai_obstacle` blob format

**Why:** `SessionSummary.ai_obstacle` is typed `tuple[Any, ...]` because no
captured session has produced a non-empty value. Need an AI-obstacle trigger
event to capture the wire shape.
**Done when:** A session produces `ai_obstacle: [...]` in the OSS JSON;
fixture saved under `tests/protocol/fixtures/`; decoder and renderer updated.
**Status:** blocked-by-capture (need mower to detect an obstacle with AI camera)
**Procedure:** [docs/research/g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path](g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path)
**Cross-refs:** `protocol/session_summary.py`; journal topic `apk cross-walk findings`

---

### Patrol Logs — trigger and wire format

**Why:** The app's Work Logs has a "Patrol Logs" tab that is always empty on
the user's account. No way to initiate a Patrol from the current UI has been
found. Wire format and OSS schema are unknown.
**Done when:** A Patrol session is triggered, the s2p50/event_occured sequence
is captured, and the OSS JSON schema is documented.
**Status:** MOSTLY DONE 2026-05-30 — a patrol WAS triggered (app cruise-side)
and captured: `s2p50 op=108`, `s2p2=51` start / `74` end, `s4 eiid1 piid1=108`,
and a full OSS summary with `mode=108`, `start_mode=0`, `result=3`,
`stop_reason=101` (archive `2026-05-30_1780174930_f3473eba.json`). The
integration now types it `session_type=patrol`, cloud-finalizes it, and labels
it `[Patrol]` (commit `feat(sessions): patrol as a 4th session_type`).
Remaining: the app's "Patrol Logs" TAB is still empty (separate from the mower
session archive); per-field OSS schema for patrol-specific keys (new s4 eiid1
piids 10/12) still undecoded.
**Procedure:** [docs/research/g2408-capture-procedures.md#4-patrol-log-trigger-investigation](g2408-capture-procedures.md#4-patrol-log-trigger-investigation)
**Cross-refs:** journal topic `s2p50 op-code catalog`; apk opcodes 107/108

---

### Firmware update flow — capture wire sequence

**Why:** Only one firmware update has occurred on the user's mower, before the
integration was running. The MQTT sequence during an update (STATE=14,
s2p53 progress, s2p57 shutdown trigger) is undocumented.
**Done when:** An update is captured; MQTT sequence documented; HA behaviour
during update (sensors, entities) verified.
**Status:** blocked-by-rare-event (wait for next firmware update notification)
**Procedure:** [docs/research/g2408-capture-procedures.md#1-firmware-update-flow](g2408-capture-procedures.md#1-firmware-update-flow)
**Cross-refs:** journal topic `s2p50 op-code catalog`; inventory `s2p2_state_14`

---

### Change PIN Code — confirm wire format

**Why:** The app has a "Change PIN Code" action. The wire format is unknown —
likely BT-only given PIN is a security-critical local secret. The integration
cannot currently read or write PIN.
**Done when:** PIN change is attempted while probe log is running; result is
either a cloud wire sequence documented in `protocol/config_s2p51.py`, or
BT-only confirmed and documented in `docs/research/g2408-protocol.md §1`.
**Status:** blocked-by-capture
**Procedure:** [docs/research/g2408-capture-procedures.md#8-change-pin-code-wire-format](g2408-capture-procedures.md#8-change-pin-code-wire-format)
**Cross-refs:** journal topic `s1p1 byte[3] bit 7 PIN-required clarification`; `docs/research/g2408-protocol.md §1`

---

### Pathway Obstacle Avoidance test — CFG.BP / CFG.PATH semantics

**Why:** Two CFG keys (`BP`, `PATH`) still have placeholder semantics.
Hypothesis: they relate to Pathway Obstacle Avoidance. No pathways are defined
on the user's map so neither field has been observed changing.
**Done when:** A test pathway is created and toggled in the app; CFG snapshot
diff identifies which key(s) change and what values mean; entities added.
**Status:** blocked-by-test (user has no pathway defined; needs deliberate setup)
**Procedure:** [docs/research/g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable](g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable)
**Cross-refs:** journal topic `s2p51 multiplexed config — disambiguation evolution`; canonical § CFG keys

---

### `MowerAction.SUPPRESS_FAULT` semantics

**Why:** The service exists in the integration but has never been live-tested.
It is unclear whether "suppress fault" means acknowledge a technical
malfunction, clear a physical-alert latch, or is a generic dismiss. Adding
a UI button without knowing semantics risks confusing users or triggering
unintended state changes.
**Done when:** A known-safe fault is triggered (e.g. lift lockout), the
SUPPRESS_FAULT action is called, and the resulting state change is observed.
Outcome: either a button entity is added with the right display conditions, or
the service is documented as power-user-only.
**Status:** blocked-by-safe-test-design (need a controlled fault scenario)
**Cross-refs:** `custom_components/dreame_a2_mower/actions.py`; journal topic `s1p1 byte[3] bit 7 PIN-required clarification`

---

## Phase 3: capture the Dreame app's write RPC — covers 28+ entities across multiple cloud surfaces

**Why:** Audit Tasks 3 and 4 (2026-05-09) + the SCHEDULE round-up probe (also 2026-05-09) revealed that **multiple cloud surfaces the integration uses for writes are cloud-cache-only or have missing setters on g2408**. The Dreame app uses a different write surface that we haven't reverse-engineered.

**SCHEDULE-specific update 2026-05-09:** ran `/tmp/probe_schedule_write.py` testing 5 candidate paths against the SCHEDULE blob. All returned `r=0` (cloud accepts) but the `v` version field never bumped — meaning the cloud is silently dropping the writes on every alternative path too. Direct MIoT `s8.{1..5}` returns 80001 (RPC tunnel closed for siid=8 on this firmware). Confirms SCHEDULE is genuinely Phase 3: the Dreame app must use either MQTT-direct publish to `/cmd/<did>/` (bypassing cloud RPC) or a different HTTP endpoint outside the routed-action / chunked-batch / MIoT-property surfaces we've enumerated.

Affected entities (all silently fail to drive the device after the v1.0.2a9 partial fix):

1. **CFG int-list keys (7 entities + sub-rows):** DND, LOW, WRP, BAT, LIT, REC, LANG. The cloud's routed-action `s2.50 m='s' t=KEY` returns `r=-3` (no setter). Direct MIoT `set_property(siid, piid, value)` returns `80001`. `r=-3` confirmed to mean "no setter at this address" — not a wire-format issue (cloud is lenient on the keys it does support, e.g. coerced `[1,4]` to `1` for CLS). See `wire-captures/cfg-write-regression-2026-05-09.md`. **NEW HYPOTHESIS (2026-05-09):** ioBroker.dreame uses **named-key payloads** for these complex CFG keys instead of wrapped lists — e.g. `WRP = {value:1, time:8, sen:0}`, `DND = {value:1, time:[1200,480]}`, `LIT = {value:1, time:[480,1200], light:[1,1,1,1], fill:0}`. We always sent `{value: <list>}` which is rejected with r=-3. Likely fix: refactor `set_cfg` to accept arbitrary `d` dict, then live-probe one key at a time. Catalog and test cases: `wire-captures/iobroker-write-catalog-2026-05-09.md`.

2. **SETTINGS-backed entities (13 entities):** All "Mowing settings page" entities — number.mowing_height / _cutter_position / _cutter_position_height / _edge_mowing_num / _obstacle_avoidance_height / _distance / _sensitivity; select.mowing_direction / _mowing_direction_mode / _edge_walk_mode; switch.edge_mowing_auto / _safe / _obstacle_avoidance / .obstacle_avoidance_enabled; switch.ai_obstacle_recognition_humans / _animals / _objects. The `setDeviceData` chunked-batch surface accepts the writes and persists them in the cloud chunked-batch dump, but the device firmware never sees the change and the Dreame app reads from a different surface (verified live 2026-05-09 — Map 2 app showed all 3 AI bits on even after cold-restart, while cloud had ai=6). See `wire-captures/settings-surface-cloud-only-2026-05-09.md`.

3. **AI_HUMAN.0 (1 entity), SCHEDULE (1 service):** Same chunked-batch surface as SETTINGS — almost certainly the same cloud-cache-only behavior. Confirm in audit Tasks 5 and 6.

The Dreame app obviously has a working device-write path: 3 weeks of s2p51 push fires show settings actually changing on the device when the user toggles in the app. **The path is not in our cloud_client repertoire and not in the legacy integration's repertoire either.**

**Probe-safety incident** during Task 3 wire-format brute-forcing: an `s2.aiid=1` call inadvertently triggered a global-mower-start action (the device ignored `m='s' t='WRP'` and treated it as a normal start command). Brute-force search of siid/aiid combinations is therefore not safe. Future probing must EITHER stay on `aiid=50` (varying only m/t/d) OR run only when the mower is docked AND the user is watching.

**Done when:** an HTTPS sniff of the Dreame app's "Save" tap on the affected pages identifies the wire format. Likely candidates:
- MQTT direct command publish to a `/cmd/<did>/` topic (the legacy Xiaomi pattern)
- A different cloud HTTP endpoint we haven't probed
- A different `method=` field (not `set_properties` or `action`)
- A new siid/aiid combination not in the integration's repertoire

A single sniff session capturing 4-5 different settings (one mowing-settings-page toggle, one DND change, one AI_HUMAN toggle, one schedule edit) will likely reveal the missing surface — they probably all use the same one.

Once captured, the integration routes the affected ~28 entities through the new path, retests end-to-end, and the audit's ✗ rows flip to ✓.

**Status:** open (deferred — needs traffic capture; substantial follow-up code work after that). NB the CFG int-list portion may be solvable without a sniff — see the named-key hypothesis above and `iobroker-write-catalog-2026-05-09.md`.
**Cross-refs:** `docs/research/wire-captures/cfg-write-regression-2026-05-09.md`; `docs/research/wire-captures/settings-surface-cloud-only-2026-05-09.md`; `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`; probe-safety incident note in the CFG file.

---

## Phase 3.5: ioBroker-derived write surfaces (independent of the app sniff)

**Why:** Investigation of `OLD/alternatives_archive_2026-05-05/ioBroker.dreame` (synced 2026-05-09, latest commit `fe0db96` v0.3.7) revealed two write surfaces our integration doesn't use, plus several action commands we don't expose. Full catalog: `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`.

**Tiers 1–3 are closed — see `docs/DONE.md`:** Tier 1 (CFG complex-payload
formats) shipped in v1.0.2a10; Tier 2 (PRE preferences) and Tier 3 (AutoSwitch
siid:4 piid:50) were ruled out as not-applicable to g2408. Only Tier 4 below
remains open.

**Tier 4 — new actions ⚠ MOSTLY ALREADY COVERED:**
- find_robot op=9, stop, pause, dock, suppress_fault — already in our `MowerAction` enum.
- lock_robot op=12 — live-probed; accepted-but-no-effect on g2408 (see memory `project_lock_robot_op12_incident`). Effectively closed; not worth surfacing.
- Still uncovered: generate_3dmap op=10 with `d:{idx:0}` (needs new action shape), request_wifi_map siid:6 aiid:4 (different routing). Both deferred — need live probing in a docked window.

**WARNING from ioBroker commit `74467a3`:** `siid:2 aiid:3 in:[4]` was historically called "start zone mowing" but **actually triggers RETURN-TO-DOCK** on g2408. They had to remove it. Don't probe blindly.

**Status:** Tiers 1–3 closed (see DONE.md); Tier 4 has a small remaining surface (generate_3dmap / request_wifi_map shapes).
**Cross-ref:** `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md` (live-verification section at the end).

---

## Per-map device-info-page segmentation — research sub-devices

**Why:** Several entities are map-specific (mowing height, edge-mowing, mowing direction, AI obstacle bits, etc.) and currently appear flat under the single Dreame device on the device-info page. The HA device page has only three fixed sections — Controls / Configuration / Diagnostic — so there's no native way to label a section "Map 1" vs "Map 2" within a single device. A custom dashboard can group them, but the device-info page itself can't.

**Two paths to evaluate before committing:**

1. **Naming convention** — prefix entity `name=` with the map label, e.g. `"Map 1: Mowing height"`, `"Map 2: Mowing height"`. Lightweight, works today, no breaking changes. Drawback: the prefix shows up in voice / automation contexts where it reads awkwardly.

2. **Sub-devices** — HA 2024.10+ introduced device hierarchy via `via_device` and per-map child `DeviceInfo` (identifiers like `(DOMAIN, f"{entry_id}_map_{map_id}")`). Per-map entities live on the child device; each map becomes its own row in the devices list, with its own device-info page. Cleaner long-term but a sizable refactor and potentially affects entity unique_ids if not done carefully (could create entity orphans — see the `feedback_entity_rename_orphan.md` memory).

**Research before deciding:**

- Survey how other multi-map / multi-zone HA integrations handle this. Examples to look at: Roborock (multi-floor maps), Tasshack/Dreame (legacy fork — does the old integration use sub-devices?), Husqvarna Automower, Tesla (vehicle / charging), Mealie (recipes per shopping list)…
- Specifically check: do they actually create sub-devices, or do they prefix names? What are the migration pain points if they ever moved from one to the other?
- Check HA core docs / dev guidelines for whether sub-devices are recommended for "logical grouping inside one physical device" or only for "this physical device contains other physical devices."
- Confirm whether a sub-device's entities can be referenced from the parent's dashboard / lovelace card without extra plumbing.

**If sub-devices look viable**, plan the entity-id migration carefully — changing a unique_id pattern strands the old entity in the registry as "unavailable" (we hit this on the cloud_state architecture rename and had to remove orphans manually via WS `config/entity_registry/remove`).

**Status:** open (research-only; no code change yet).
**Cross-ref:** `feedback_entity_rename_orphan.md` (auto-memory), `custom_components/dreame_a2_mower/entity-inventory.yaml` per-entity entries (which entities are map-specific).

---

## Determine whether HA writes drive the device, or only update the cloud cache

**Why:** A whole class of g2408 settings — AI Obstacle Recognition
(humans/animals/objects), Mowing Direction, Edge Mowing Auto/Safe/
Obstacle Avoidance, LiDAR Obstacle Recognition, Obstacle Avoidance
Distance/Height/Sensitivity, Mowing Height, Cutter Position,
Mowing Pattern, Edge Walk Mode, Edge Passes, Start from Stop Point,
Pathway Obstacle Avoidance, EdgeMaster — are all readable from the
cloud and propagate end-to-end across app instances (verified
2026-05-09 via two-device test: toggle in app A, cold-start app B
on a different device → app B reflects the change without any BT
involvement). The full list and per-entity status lives in
`docs/research/entity-sync-matrix.md`.

The integration writes via `setDeviceData`. The cloud accepts the
write (CFG.VER bumps, SETTINGS reflects, refresh-button confirms).
What's NOT yet established is whether the device *firmware* applies
the HA-initiated write — i.e. whether the mower's actual behaviour
changes. Earlier we suspected "no" because the original Dreame app
session kept showing the pre-HA-write value, but that may simply be
the app's settings-screen UI cache (the same cache that hides
app-to-app changes until forced refresh).

**Right test (not yet performed):** HA writes X to a setting; then
cold-start a Dreame app instance that has never seen the device's
local cache. If it shows X, HA writes propagate fully and the
"doesn't apply" theory was a UI-cache illusion. If it shows the
pre-HA-write value, HA's `setDeviceData` only updated the cloud
cache and the device firmware uses a different write surface.

If HA writes are confirmed insufficient, the next step is HTTPS-
sniffing the Dreame app's "Save" tap to capture the actual RPC the
app uses (likely a routed-action `setX` target we haven't enumerated,
since direct MIoT `set_property` returns 80001 for most siids).

**Done when:** the test above is performed live and either:
1. HA writes confirmed end-to-end propagating → close as "no action,
   the apparent gap was UI cache"; OR
2. HA writes confirmed insufficient → app's actual write RPC is
   captured, wired into a `coordinator.write_*` method, and a
   follow-up live test confirms full propagation.
**Status:** open (deferred — needs user-side cold-start test, then
possibly a traffic capture).
**Cross-refs:** `docs/research/entity-sync-matrix.md` (full list of
affected entities); `docs/research/g2408-research-journal.md` 2026-05-09
entry "BT-only classification retracted".

---

## Deferred — write-path audit findings (2026-05-09)

Surfaced during the post-fix audit for additional structural
read/write mismatches like the SETTINGS dual-entry / SCHEDULE-mode
bugs (commits `b25b5ac` / `4868016` / `b89c574`). No other
dual-source storage shapes were found. Two encoder-side
findings still open; both are write paths whose hardcoded shape
doesn't match what the firmware actually stores.

### PRE encoder inflates `list(2)` to `list(10)` with hardcoded defaults

**Why:** Same class as the SCHEDULE `mode` bug. Live g2408 cloud has
`PRE = [0, 0]` (verified 2026-05-09 via `/tmp/probe_cfg_arrays.py`),
but `protocol/cfg_action.py:166` `set_pre()` rejects arrays with
`< 10` elements and `select.py:181` `_build_pre_efficiency` always
emits 10 elements, padding indices 2..9 with
`_PRE_PAD_DEFAULTS = [60, 0, 0, 0, 0, 0, 0, 0]`. First time the user
picks "Mowing Efficiency" in HA, the cloud's `[0, 0]` becomes
`[0, mode, 60, 0, 0, 0, 0, 0, 0, 0]` — the integration is
*inflating* a field that firmware kept short. Source comment claims
"may be trimmed server-side" but this is unverified, and even if
it is trimmed, the integration is sending data that doesn't reflect
firmware state.
**Done when:** `set_pre()` accepts the same length the firmware
stores (relax the 10-element minimum); `_build_pre_efficiency`
reads the current PRE list from `cs.cfg["PRE"]` and mutates only
the index it owns; live test on g2408 confirms PRE round-trips at
length 2 after a "Mowing Efficiency" toggle.
**Status:** open (deferred — schedule + AI work first)
**Cross-refs:** `custom_components/dreame_a2_mower/protocol/cfg_action.py:162`;
`custom_components/dreame_a2_mower/select.py:175-200`; live probe
`/tmp/probe_cfg_arrays.py`.

### BAT[2] hardcoded `1` in build helpers

**Why:** Three build helpers — `_build_bat_auto_recharge` (number.py),
`_build_bat_resume` (number.py), `_build_bat_custom_charging`
(switch.py:171) — all hardcode `BAT[2] = 1` instead of reading it
from MowerState. The decoder explicitly drops `BAT[2]` with
`# unknown_flag (consistently 1; semantic TBD)`. Live data confirms
`BAT[2] = 1` today (2026-05-09), so writes are correct now, but the
"consistently 1" assumption is brittle — if firmware ever stores
something else there, every BAT-related write clobbers it.
**Done when:** `bat_unknown_flag` is added to MowerState, populated
from `bat_raw[2]` in the CFG decoder, and the three build helpers
pass `int(state.bat_unknown_flag or 1)` instead of the literal `1`.
**Status:** open (deferred — defensive cleanup, low priority)
**Cross-refs:** `coordinator/_refreshers.py § _refresh_locn`;
`custom_components/dreame_a2_mower/switch.py:158-181`;
`custom_components/dreame_a2_mower/number.py:80-110`.

---

## Deferred from Task 17 (cloud-discovery integration)

### Legacy `_refresh_*` method consolidation

**Why:** `_refresh_cfg`, `_refresh_mihis`, `_refresh_dev`, `_refresh_net`,
`_poll_slow_properties` remain in place alongside `_refresh_cloud_state`.
They run on their own schedules and are still authoritative for some fields.
Task 17 dropped the three MIHIS-duplicate archive-seed paths
(`mowing_count`, `total_mowing_time_min`, `total_mowed_area_m2`) since
`_apply_cloud_state_to_mower_state` now covers them at startup, but a
full audit of the legacy refresh methods was deferred.
**Done when:** Each legacy method is walked:
1. Identify whether everything it sets is now sourced from `cloud_state`
   via `_apply_cloud_state_to_mower_state`.
2. For methods that are fully covered, drop them and their schedules.
3. For methods that set fields not yet in cloud_state, expand
   `_apply_cloud_state_to_mower_state` to cover them, then drop the legacy method.
4. Verify no entity contract is broken (run integration suite).
**Status:** open (deferred — audit needed before any removal)
**Cross-refs:** `coordinator.py` `_refresh_cfg` / `_refresh_mihis` /
`_refresh_dev` / `_refresh_net` / `_poll_slow_properties`;
`coordinator.py` `_apply_cloud_state_to_mower_state`
