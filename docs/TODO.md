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

### Fix replay-image flow bypassing custom view (picture-entity quirk)

**Why:** HA's `picture-entity` card fetches via `/api/camera_proxy/` directly,
bypassing `entity_picture` and our `MapImageView` with its `Cache-Control:
no-store` headers. The banner-clear-on-fetch mechanism is dead code for
production traffic.
**Done when:** Dashboard's replay map updates without a browser refresh after
picking a new session; or the `MapImageView` `get()` path gets at least one
hit per pick in `system_log/list` output.
**Status:** open
**Cross-refs:** journal topic `Live-confirmed status board`

---

### Fix live-map popout first-load image missing

**Why:** Opening the Live Map popout on a cold dashboard load shows chrome
(header, buttons) but no map image. Browser refresh always fixes it,
suggesting a race between camera entity state and the popout's `<img src>`
binding.
**Done when:** First-load of the popout renders the map image without a
browser refresh in a fresh session.
**Status:** open
**Cross-refs:** journal topic `Live-confirmed status board`

---

### Investigate MIHIS.start factory-date mismatch

**Why:** `first_mowing_date` sourced from `CFG.MIHIS.start` shows `2023-12-31`,
predating the user's ownership by 2+ years. Likely a factory test mow timestamp
or firmware-shipped sentinel.
**Done when:** The source of `MIHIS.start = 1704038400` is identified (factory
test vs firmware default vs tz artefact) and either the field is corrected or
a note is added to the sensor explaining the discrepancy.
**Status:** open
**Cross-refs:** inventory row `cfg_mihis_start`; canonical § cfg_individual endpoints

---

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

### Dashboard contextual button rows per mower state

**Why:** The Dreame app shows different button rows depending on state (Docked:
Start/Recharge; Mowing: Pause/Stop; Paused: Continue/End/Recharge; etc.).
The HA dashboard currently shows all buttons regardless of state.
**Done when:** The mower dashboard's main card uses `conditional` cards keyed
off `lawn_mower.dreame_a2_mower` to render the correct per-state button row,
matching the visual reference in `/data/claude/homeassistant/IMG_4413..4422.PNG`.
**Status:** open
**Cross-refs:** `/config/dashboards/mower/dashboard.yaml`

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
