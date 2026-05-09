# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
For overall protocol architecture see `docs/research/g2408-protocol.md`.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

### Phase 2: MAP write — programmatic boundary/zone editing

**Why:** With chunked-batch writes confirmed working (Phase 1 done in
v1.0.2a1), the MAP surface is the next big capability. Drawing
boundaries and editing mowing/exclusion zones from HA without walking
the mower would be a major UX win.
**Done when:** A safe MAP write surface exists with auto-backup of the
current MAP blob before any write, restore-from-backup mechanism, and
a Lovelace card for boundary editing.
**Status:** open
**Cross-refs:** spec
`docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
"Phase 2"; `docs/research/cloud-write-reference.md`.

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

### SETTINGS dual-entry — closed 2026-05-09

**Why:** Originally open as "decode the dual-entry semantic". v1.0.2a2
read from the LAST entry; v1.0.2a3 corrected to entry 0 after a
controlled cloud diff against a two-device app save proved entry 0
is the user-saved entry (versioned, app-reflecting) and entry 1 is
a firmware-applied mirror (stays at `version: 0`, lags arbitrarily).
Writes propagate to both entries (defensive). See
`docs/research/cloud-write-reference.md` "Dual-entry semantic" and
the 2026-05-09 entry of `docs/research/g2408-research-journal.md`.
**Status:** done (no further work).
**Cross-refs:** commit `b25b5ac` (v1.0.2a2), commit pending (v1.0.2a3);
fixture `tests/protocol/fixtures/2026-05-08-settings-sample.json`.

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

**Why:** The Dreame app shows a 3-stage popup ("Repositioning..." →
"Repositioning Successful" → "Mowing started") at every dock departure.
No MQTT property carrying this state has been identified yet — three
dock departures on 2026-05-05 produced no `s2p65` or `s5p104..107` events.
**Done when:** The MQTT property (or cloud-only push) carrying relocate-state
is identified, or confirmed cloud-only (in which case document and close).
**Status:** blocked-by-capture
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


### LiDAR archive — per-map?

**Why:** Today's `lidar_archive` is a flat folder; if the mower keeps
distinct LiDAR scans for each map (likely on physically-distinct
maps; ambiguous on overlapping ones like the user's current setup),
the archive layout needs a `map_id` field too.
**Done when:** Either (a) confirmed shared across maps and documented;
or (b) a `map_id` field is added to lidar_archive entries and the
LiDAR card filters/displays per-map scans.
**Status:** open (investigation)
**Cross-refs:** `custom_components/dreame_a2_mower/lidar_archive.py`;
`docs/multi-map.md` "Limitations" section

---

### Render `nav_paths` overlay on the camera

**Why:** `MapData.nav_paths` is decoded from the cloud `paths` key
(connecting paths between maps, rendered in the app as gray
polylines). The greenfield decodes them but the renderer doesn't draw
them yet.
**Done when:** `map_render` overlays `nav_paths` as a styled gray
polyline (similar to live-trail rendering); a multi-map test fixture
visually confirms the overlay aligns with the user's app screenshot.
**Status:** open (Phase 2 polish)
**Cross-refs:** `map_render.py`; `MapData.nav_paths`

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
**Status:** blocked-by-capture (no known Patrol trigger in current app)
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

## Capture the Dreame app's write RPC for BT-only settings

**Why:** A whole class of g2408 settings — AI Obstacle Recognition
(humans/animals/objects), Mowing Direction, Edge Mowing Auto/Safe/
Obstacle Avoidance, LiDAR Obstacle Recognition, Obstacle Avoidance
Distance/Height/Sensitivity, Mowing Height, Cutter Position,
Mowing Pattern, Edge Walk Mode, Edge Passes, Start from Stop Point,
Pathway Obstacle Avoidance — are visible in cloud SETTINGS (so HA
can READ them) but the device firmware does not apply HA's writes
via `setDeviceData`. The full list and per-entity status lives in
`docs/research/entity-sync-matrix.md`. Live-confirmed 2026-05-09
that HA writes land in cloud SETTINGS but the app keeps showing the
pre-write value even after an app restart (verified for AI bits).

The Dreame app's "Save" tap on these screens drives the device
via some unknown RPC — likely a specific MIoT siid/piid combination
that does NOT return 80001 on g2408, or a routed-action target we
haven't enumerated. Once captured, HA could write the same RPC and
all these entities flip from "Cloud-only — app does not refresh"
to "Yes — full propagation".

**Done when:** an HTTPS sniff of the Dreame app's traffic during a
"Save" tap on the AI Obstacle Recognition (or any other BT-only)
screen identifies the wire format, the RPC is wired into a
`coordinator.write_*` method, and a live test confirms the Dreame
app reflects the HA-initiated change without the user having to
re-save in the app.
**Status:** open (deferred — needs user-side traffic capture).
**Cross-refs:** `docs/research/entity-sync-matrix.md` (full list of
affected entities); `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md`
§"Cloud-write-invisible-on-MQTT settings"; `docs/research/g2408-research-journal.md` 2026-05-09 entry.

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
**Cross-refs:** `custom_components/dreame_a2_mower/coordinator.py:1097-1107`;
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
