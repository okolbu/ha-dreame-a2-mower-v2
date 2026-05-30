# Dreame A2 (`g2408`) — Resolved Work

Items moved out of `docs/TODO.md` once closed. Newest first within each date.
For the full RE journey and shipped-version detail see
`docs/research/g2408-research-journal.md`.

Each entry keeps the original action title plus a one-paragraph resolution note.

---

### Decouple the s2p2 71/31/33 state model — orthogonal vars — DONE (2026-05-30)

The state machine had derived `positioning_health = STUCK` from a buffered "s2p2=71
then 31/33 within 30s" combination — but corpus showed **71 and 31/33 never co-occur**,
so that path never fired. Decoupled into orthogonal signals: STUCK is now set
**synchronously from s2p2=33** (the real positioning/off-dock-relocate failure, e.g.
the 12:32 relocate-fail → s2p1=4 Paused) and **cleared on a mowing resume** (s2p1=1);
71 carries no positioning side effect (it's "standby→returning"); 31 stays its own
`failed_to_return_to_station` sensor. Removed the entire `_s2p2_71` buffer + window
const + tick resolution. TDD: replaced the 71→31→STUCK test with 33→STUCK,
clears-on-resume, and 71+31-not-stuck tests. 908 tests pass. The broader "review other
multi-variable couplings" sweep remains as a spinoff TODO.

### Fix s2p2=71 mislabel — false "positioning failed" on standby-return — DONE (2026-05-30)

s2p2=71 = "standby outside station too long → auto-return" (text-confirmed), not the
apk's "positioning failed". Three consumers corrected: (1) `binary_sensor.positioning_failed`
re-keyed from raw `error_code==71` to the state machine's disambiguated
`positioning_health==STUCK` (71+31/33) — a plain standby-return resolves to LOCALIZED,
so it no longer false-trips (it had tripped at 18:26:50); (2) the notification slug
renamed `positioning_failure` → `standby_outside_station_too_long` across all 4 sync
points (error_codes.py, const.NOTIFICATION_EVENT_TYPES, en.json, logbook.py); (3)
error_codes.py description corrected. The state machine's existing 71+31→STUCK
disambiguation was already correct and left intact. TDD: 3 new tests
(positioning_failed off-on-standby / on-when-stuck, slug). Also completed the s2p2=76
slug wiring (logbook + keys-test) that the earlier add had left red. 741 tests pass.

### Capture "too long stopped outside the station" trigger — DONE (2026-05-30)

Identified: the notification is carried by **s2p2=71**, with app text "The robot is
on standby outside the station for too long. Automatically returning to the station."
(user-confirmed; also fetchable via device-messages/v2). Captured live 2026-05-30
18:26:50 — exactly 1h after the mower sat idle at the maintenance point — firing
s2p1 2→5 (idle→returning). Corpus: all 5 s2p2=71 occurrences are return-context, none
positioning-failure, so the apk "positioning failed" label is wrong for g2408.
Recorded in `inventory.yaml § s2p2`. NB this surfaced a mislabel bug
(binary_sensor.positioning_failed / slug) now tracked as its own TODO. Was the
`to-investigate.txt` item.

### Render `nav_paths` overlay on the camera — DONE (2026-05-30)

`MapData.nav_paths` (the cloud `paths` key — connecting paths between maps) now
render as gray polylines on the camera, matching the Dreame app. The renderer draws
them; the "decoded but not drawn" gap is closed.
**Cross-refs:** `map_render.py`; `MapData.nav_paths`.

### Rain-stop / mid-session pause handling — session continuity across HA restarts — DONE (2026-05-30)

Closed with the recently-added rain-start state + entity: a weather-hold is now
surfaced as its own state/entity rather than producing a phantom or a fragmented
two-entry archive. (Earlier groundwork: v1.0.13a4 `_prune_incomplete_for` cleanup of
the placeholder when the cloud summary lands, and v1.0.13a5's `_real_task_state_observed`
boot-stale latch that killed the 0 m² phantom.) If a future rain-pause still splits a
session across two archive entries, reopen with the captured timeline.
**Cross-refs:** `live_map/finalize.py`; `mower/state_machine.py`; `coordinator/_session.py`;
memory `project_g2408_session_archive_quirks`.

### Area-mowed-based time breakdown for sensor.picked_session — DONE (2026-05-30)

Superseded by the replay rework: the session card now reports a wall-clock breakdown
per event across the entire replay session, so the battery-drop-vs-area-delta
heuristic question is moot — the time split is no longer derived from a sampled
proxy. The original ask (add `area_mowed_samples` and prefer it over the battery-drop
heuristic) is closed as no-longer-needed.
**Cross-refs:** `session_card.py § _compute_time_breakdown`; `live_map/state.py`.

---

### Phase 3.5 Tier 1 — CFG complex-payload formats — DONE (v1.0.2a10, 2026-05-09)

`set_cfg` refactored to accept dict payloads, sent verbatim as `d`.
`WRP {value, time}`, `DND {value, time:[start,end]}`, `LOW {value, time:[start,end]}`
all live-verified on g2408 fw 4.3.6_0550. WRP end-to-end (HA → cloud → device →
app) confirmed via a 4h→6h→4h round-trip. **Important deviation from ioBroker's
catalog:** the bare `{value:0}` "off" form is rejected with `r=-3` on g2408 —
always send the full form. Optional `sen` field omitted (not surfaced in app, not
echoed in getCFG). Commit `c2ab186`; switch entities + WRP-resume-hours select
shipped.
**Cross-ref:** `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`.

### Phase 3.5 Tier 2 — PRE preferences — RULED OUT (not applicable to g2408, 2026-05-09)

Live-probed: g2408's `CFG.PRE = [0, 0]` (only 2 elements; ioBroker's
PRE[2]=cutting-height, PRE[9]=edge-mowing etc. don't exist here). Round-trip write
returns `r=-3`. The corresponding g2408 entities (cutting height, edge mowing)
live behind the SETTINGS chunked-batch surface — that part is still the open
Phase 3 cloud-cache-only gap (kept in TODO.md), but PRE itself is closed.

### Phase 3.5 Tier 3 — AutoSwitch (siid:4 piid:50) — RULED OUT (not applicable to g2408, 2026-05-09)

Live-probed: `get_properties [{siid:4, piid:50}]` returns `80001 设备可能不在线` —
the property doesn't exist on g2408 firmware. AutoSwitch is vacuum-side (and
possibly newer mower firmware).

---

### text-language picker — DONE (2026-05-09)

Text-language picker enumerated from user screenshots (lang1.PNG / lang2.PNG /
lang3.PNG). 33 entries, 1-indexed on g2408 (vs voice's 0-indexed).
`TEXT_LANGUAGE_NAMES` filled in; position 0 reserved as a `None` placeholder for a
possible future "use phone language" slot. **Lingering caveat:** T4 device-apply
confirmation was never closed out — picking "English" (or any option) in
`select.text_language` and confirming the Dreame app reflects the change would
fully verify it. Treated as done; reopen as a one-line verification if it ever
misbehaves.

### photo_consent + show_photo_privacy_policy — DONE (2026-05-09)

`binary_sensor.photo_consent` reads `REC[7]`; the verbatim "AI Obstacle
Recognition Privacy Policy" is bundled at
`custom_components/dreame_a2_mower/data/privacy_policy_photo.md` and surfaced via
the `dreame_a2_mower.show_photo_privacy_policy` service.

### SETTINGS dual-entry — DONE / closed (2026-05-09)

Originally open as "decode the dual-entry semantic". v1.0.2a2 read from the LAST
entry; v1.0.2a3 corrected to entry 0 after a controlled cloud diff against a
two-device app save proved entry 0 is the user-saved entry (versioned,
app-reflecting) and entry 1 is a firmware-applied mirror (stays at `version: 0`,
lags arbitrarily). Writes propagate to both entries (defensive). See
`docs/research/cloud-write-reference.md` "Dual-entry semantic" and the 2026-05-09
journal entry. Commit `b25b5ac` (v1.0.2a2), v1.0.2a3 follow-up; fixture
`tests/protocol/fixtures/2026-05-08-settings-sample.json`.

---

### External probe enum-mislabel — DONE (2026-05-25)

`probe_a2_analyze.py` retired to `OLD/`; `probe_a2_mqtt.py` now integration-sources
the s2p1/s2p2 labels instead of carrying its own vacuum-derived enum.

---

### Reconcile `mower/error_codes.py` with verified s2p2 findings — DONE (2026-05-28)

`ERROR_CODE_DESCRIPTIONS` still carried vacuum-derived guesses that conflicted with
verified codes — e.g. 63="Blocked" (verified: "Scheduled task cancelled — Robot
working"), 54="Edge fault" (notification map: "low_battery_return"). Resolution:
reconciled `ERROR_CODE_DESCRIPTIONS` against the cloud-verified s2p2→text mapping.
Corrected 50/63/54 and rewrote 28's note to the reconciled two-faces; added
cloud-verified 30/36/70; annotated the still-unconfirmed 23/43/75 (apk fault label
vs the `S2P2_EVENT_TYPES` slug) rather than asserting. Pinned by
`tests/mower/test_error_codes.py`; recorded under `inventory.yaml` § s2p2.

### s6.3 slow-poll item — SUPERSEDED (2026-05-26)

`_poll_slow_properties` was removed entirely and `MowerState.cloud_connected`
dropped. Heartbeat byte[17] already supplies fresh `wifi_rssi_dbm`, MQTT-up implies
cloud-connected, and DEV owns the serial. The new `binary_sensor.cloud_connected` +
`sensor.mqtt_age_s` are backed by `coordinator.last_mqtt_unix`, stamped on every
MQTT push.

### Blades-worn-from-wear% item — SUPERSEDED (2026-05-26)

Superseded by the cloud-notification feature — the cloud already wear%-gates the
"Blades severely worn" push server-side. The integration just relays whatever the
cloud actually pushed; no local wear% logic needed.
</content>
</invoke>
