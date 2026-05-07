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

### Decode `paths` key in cloud-map response

**Why:** When a map has a connecting path (e.g. multi-map setup with
gray "navigation path" rendered between dock and a remote map), the
cloud `MAP.*` response carries this geometry under the `paths` key.
Legacy upstream's `map_data_parser.py:221` parses it as a list of
`MowerPath {path_id, path, path_type}`. The greenfield's
`parse_cloud_map` doesn't read this key — the path is invisible in
the rendered map even though the firmware sends it.
**Done when:** `MapData` gains a `nav_paths` field; `parse_cloud_map`
populates it from the cloud `paths` entries; renderer overlays them.
A multi-map test fixture proves both maps' nav paths render.
**Status:** open
**Cross-refs:** `map_decoder.py:222` `parse_cloud_map`; legacy
`alternatives/dreame-mower/.../map_data_parser.py:221`

---

### Writable `select.active_map` (capture wire format)

**Why:** The bundled `select.dreame_a2_mower_active_map` is read-only
because the cloud "set active map" action wire format isn't decoded.
The Dreame app shows other-map thumbnails as small windows on the
main view; tapping one swaps active. This is a frequent user action,
so capturing the wire format is high-value.
**Done when:** `select.active_map.async_select_option` writes to the
firmware via the captured action; option-select in HA results in
`MAPL[i][1]` flipping after the next CFG poll.
**Status:** blocked-by-capture (probe procedure: tap an other-map
thumbnail in app while probe log records; diff s2.50 / setCFG /
properties_changed traffic between the tap and the resulting MAPL
update).
**Cross-refs:** `docs/superpowers/specs/2026-05-07-multi-map-design.md`
§ "Out of scope"

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
