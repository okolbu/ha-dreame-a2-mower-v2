# Next-steps handoff — 2026-05-30

A self-contained orientation for a FRESH session. Read this, then the linked
specs/plans/inventory. Everything below is committed and pushed to `origin/main`.

## Standing discipline (read first — load-bearing)

- **Corpus-validate every protocol claim.** Never confirm a g2408 wire/value claim
  from a single run. Validate across all probe logs (`/data/claude/homeassistant/probe_log_*.jsonl`,
  9 logs). If it doesn't hold corpus-wide it is `partial`/`presumed`, not `verified`.
  Tonight this caught THREE wrong "facts" that old docs asserted (s2p2=28 off-dock
  marker; a fabricated "19h rain-paused mow"; reversed/ wrong card mode labels).
  See memory `feedback_corpus_validate_protocol_claims`.
- **Old docs may be wrong/guesswork.** Treat apk/vacuum-derived names and any
  single-sample "always X" claim as suspect until corpus-checked.
- **Tests + venv:** run `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`
  (system python is broken). Baseline ~1676 passed. Commit by explicit path (a 2nd
  process commits concurrently — never `git add -A`). Project commits straight to
  `main` (HACS pulls origin/main); push when a chunk is green.
- **Fact discipline:** record protocol facts in `inventory.yaml` (wire) /
  `entity-inventory.yaml` (entities) in the same change. Blank-spots tracker:
  `docs/research/knowledge-gaps.md`.

## What shipped tonight (context)

- **Non-mow session capture** (head-to-maintenance-point + manual runs typed as their
  own sessions; fixes the four-runs-merged bug). Spec:
  `docs/superpowers/specs/2026-05-30-non-mow-session-capture-design.md`; plan:
  `docs/superpowers/plans/2026-05-30-non-mow-session-capture.md`. Classifier:
  `live_map/classify.py:classify_session_type` (mow-evidence rule). Memory:
  `project_non_mow_sessions_shipped`.
- **Protocol corrections** (all in `inventory.yaml`, with verifications): s2p2 28=blade-wear
  (not off-dock), 71=standby-return (not positioning-failed), 76=cannot-reach-maint,
  51=patrol-start (not filter-blocked), 2=robot-trapped, 4=left-drive-wheel-error,
  74=patrol-ended. `s2p56` task_state_code now reads `status[0][-1]` (last element =
  stage; surfaces 3-element done/paused). `s2p50` op=15=manual, op=108=patrol.
  `summary.mode`=mow-type (100 all/101 edge/102 zone/103 spot/108 patrol);
  `start_mode` 1=scheduled/0=manual. `s4 eiid1` event: piid1=mode/op, piid9=OSS
  object name, piid13=fault timeline `[[ts,code]]`.

## Recommended next steps (in priority order)

### 1. Surface the new fault codes as notifications (highest value)
`s2p2` 2 (trapped), 4 (left-wheel error), 51 (patrol-start), 74 (patrol-end) are in
`mower/error_codes.py:ERROR_CODE_DESCRIPTIONS` but NOT in `S2P2_EVENT_TYPES`, so they
don't fire `event.dreame_a2_mower_notification`. A user wants a "Robot trapped" / wheel-
error alert. Add slugs to `S2P2_EVENT_TYPES` (error_codes.py) + the **lockstep** copies:
`const.NOTIFICATION_EVENT_TYPES`, `translations/en.json`, `logbook.py:_NOTIFICATION_MESSAGES`,
and the keys-test expected set (`tests/integration/test_notification_synthesizer.py`).
Decide which are alert-worthy (trapped/wheel = yes; patrol start/end = lifecycle, maybe).
Note 2/4/74/51 are `partial` (single observation) — fine to surface, text comes from the
cloud anyway.

### 2. Patrol as a 4th session_type
Extends the shipped non-mow feature. Patrol = `s2p50 op=108` / `s2p2=51` /
`summary.mode=108`, blades-up (area=0). IMPORTANT difference from head-to-point: patrol
PRODUCES a cloud OSS summary (s4 eiid1 piid9), so it finalizes via the **cloud** path
(has md5), not local. Today the classifier (`classify_session_type`) would mis-fall it
to `maintenance_run`. Add `patrol` (detect op=108 / s2p2=51 / mode=108), keep it on the
cloud-finalize path, `[Patrol]` label, 0-area card. Reuse the Task-7 boundary logic.

### 3. Live-map can't-track during patrol (needs HA-side)
During the 2026-05-30 patrol the live map didn't track the mower, BUT the wire had valid
`s1p4` positions and `begin_session` should fire (`s2p56=[[1,0,0]]→task_state 0`). So it's
a handling/render bug, not missing data. Needs the HA-side look: the live camera entity /
any `live_map`/render error during a patrol (the user can pull the HA log). Candidate:
the cruise/patrol path may be gated somewhere, or the live re-render throttle.

### 4. AI-photo / endpoint probing (new — see TODO)
The app shows AI obstacle photos with an overlay (e.g. "human 80%"). A SECOND app
instance on another device shows the SAME historical photos → they sync via the cloud
API, not BT. No "photo taken" MQTT slot is identified. So there is almost certainly a
photo/AI cloud endpoint, parallel to the `device-messages/v2` notification endpoint we
already found. Probe for photo/AI-sounding endpoints. Start from
`reference_app_api_probe` (memory), `probe_a2_endpoints.py`, the apk teardown, and the
`device-messages/v2` discovery pattern. Related inventory: AI_HUMAN / AIOBS / s2p55
ai_obstacle_report / o:401 takePic / photo_consent (REC[7]). See TODO item.

### 5. Cleanups (lower priority)
- DRY the mode enum: 100-103/108 maps in `mow_type_from_mode`, `session_card.MODE_LABELS`,
  state-machine op_map, and `summary.mode`/`arg1` — one canonical source.
- Broader vacuum-name sweep (TODO "Audit for misleading authoritative-sounding names") —
  51 was one; the `s2p2` 37-78 fault catalog + `s4p*` slots likely hide more.
- `s2p56` 3-element MIDDLE value (always 0 — segment/lap index?), `STOP_REASON_LABELS`/
  `PRE_TYPE_LABELS` completion, the s4 eiid1 new piids 10/12 (patrol-introduced, unknown).
- The "decouple multi-variable state couplings" + "doc-hygiene audit" TODO items.

### 6. End-to-end validation of the shipped feature
Trigger a few head-to-maintenance-point runs (after moving the hose) and confirm the
four-runs-merge is gone in the archive (separate `[To Point]` entries with outcomes),
and eyeball the non-mow picked-session card. This is the only piece the tests can't cover.

## Pointers
- Open-work list: `docs/TODO.md`; resolved: `docs/DONE.md`.
- Specs/plans: `docs/superpowers/specs/` and `docs/superpowers/plans/`.
- Truth: `inventory.yaml` (wire) / `entity-inventory.yaml` (entities); gaps:
  `docs/research/knowledge-gaps.md`.
- Memories (`/home/ok/.claude/projects/-data-claude-homeassistant/memory/`): start at
  `MEMORY.md`.
</content>
