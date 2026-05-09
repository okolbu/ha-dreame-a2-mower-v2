# s2p51 multiplexed-config — passive scan (2026-05-09)

Task 3 read-side evidence. Scanned the entire probe log
`probe_log_20260419_130434.jsonl` for `s2p51` fires (3 weeks of capture).

**Total s2p51 fires:** 205
**Window:** 2026-04-19 16:37 → 2026-05-09 13:48

## Wire shapes observed (all match `protocol/config_s2p51.py:_decode_list_payload`)

| Shape (decoder routes to `Setting`) | Fires | First | Last | Sample payload |
|---|---|---|---|---|
| `TIMESTAMP` `{time, tz}` | 78 | 2026-04-19 16:37 | 2026-05-09 13:48 | `{'time': '1778327304', 'tz': 'Europe/Oslo'}` |
| `AMBIGUOUS_TOGGLE` `{value: int}` | 42 | 2026-04-24 14:31 | 2026-05-09 09:57 | `{'value': 0}` and `{'value': 1}` (~equal) |
| `AMBIGUOUS_4LIST` `{value: list[4]}` (bools) | 34 | 2026-04-24 17:04 | 2026-04-30 22:40 | `[1, 1, 1, 1]`, `[0, 1, 1, 1]`, `[1, 0, 1, 1]`, etc. (all 4 indices observed flipping) |
| `HUMAN_PRESENCE_ALERT` `{value: list[9]}` | 15 | 2026-04-24 16:52 | 2026-04-27 12:14 | `[1, 1, 1, 1, 1, 1, 0, 1, 3]` (REC[6]/REC[7] flipping in samples) |
| `ANTI_THEFT` `{value: list[3]}` (3-bool) | 12 | 2026-04-24 16:50 | 2026-04-27 16:15 | `[1, 0, 0]`, `[0, 0, 0]` etc. — all-bool; routes to ATA |
| `LED_PERIOD` `{value: list[8]}` | 8 | 2026-04-23 21:54 | 2026-04-24 16:50 | `[1, 480, 1200, 1, 1, 1, 1, 1]` and `[0, 480, 1200, ...]` — LIT[0] toggle |
| `LOW_SPEED_NIGHT` or `DND` `{value: list[3]}` (time-window) | 5 | 2026-04-23 22:59 | 2026-04-29 19:13 | `[1, 1200, 480]` (20:00→08:00) — ambiguous between LOW and DND, discriminator: any element > 1 |
| `CHARGING` `{value: list[6]}` | 4 | 2026-04-23 23:26 | 2026-04-24 17:12 | `[15, 95, 1, 0, 1080, 480]` and `[15, 95, 1, 1, 1080, 480]` — BAT[3] custom_charging toggle |
| `RAIN_PROTECTION` `{value: list[2]}` | 3 | 2026-04-24 16:43 | 2026-04-24 16:44 | `[0, 3]`, `[1, 4]` — WRP toggle + resume_hours change |
| `CONSUMABLES` `{value: list[4]}` (counters) | 3 | 2026-04-30 19:40 | 2026-04-30 19:57 | `[3084, 3084, 0, -1]` → `[3084, 0, 0, -1]` — brush replacement (CMS[1] zeroed) |
| `LANGUAGE` `{text, voice}` | 1 | 2026-04-24 17:02 | 2026-04-24 17:02 | `{'text': 2, 'voice': 7}` |

## What this verifies (✓ live)

- **The s2p51 wire is alive** — fires across 3 weeks of operation; not a stale assumption.
- **The integration's `_decode_list_payload` covers every shape that has appeared** — no novel shapes seen.
- **The Setting enum dispatch table is correct** — every shape routes to a known `Setting` (RAIN_PROTECTION / LOW_SPEED_NIGHT / ANTI_THEFT / DND / CHARGING / LED_PERIOD / HUMAN_PRESENCE_ALERT / LANGUAGE / TIMESTAMP / CONSUMABLES / AMBIGUOUS_TOGGLE / AMBIGUOUS_4LIST).
- **Most CFG-backed entities have been actually exercised** in the captured window (multiple distinct values per shape) — the user has changed many settings via the app over 3 weeks; each save fired s2p51.

## What this does NOT verify

- **Per-entity disambiguation for ambiguous-toggle / ambiguous-4-list shapes.** The `AMBIGUOUS_TOGGLE` shape carries 0|1 with no discriminator — could be CLS, FDP, STUN, AOP, or PROT. Without a `cfg_keys_raw _last_diff` sensor (currently absent from the integration; was apparently in legacy alpha.123+ — see retired `entity-sync-matrix.md` notes), the integration cannot tell which CFG key the user toggled. Same problem for `AMBIGUOUS_4LIST` between MSG_ALERT and VOICE.
  - **Implication:** the read path's *first-stage* decode (s2p51 → Setting enum) is verified ✓. The *second-stage* dispatch (Setting → specific MowerState field) for ambiguous shapes relies on the integration knowing which CFG key changed, which today requires a controlled getCFG diff. Without that mechanism, ambiguous-shape pushes could be silently misattributed.
- **HA-write end-to-end propagation.** All these entities use `coordinator.write_setting → set_cfg → routed-action s2.50 s.<KEY>`. The cloud accepting the write doesn't prove the device firmware applies it. T4 (HA toggle + cold-start fresh app) is required per entity (or per representative entity in each shape class).

## Implications for the audit

| CFG-backed entity row | Read-mechanism evidence | Per-entity disambiguation | Write evidence |
|---|---|---|---|
| switch.child_lock (CLS) | ✓ live (AMBIGUOUS_TOGGLE shape fires) | ⚠ requires controlled T3 — could be confused with FDP/STUN/AOP/PROT | ⚠ T4 needed |
| switch.frost_protection (FDP) | ✓ live (AMBIGUOUS_TOGGLE shape) | ⚠ same | ⚠ T4 needed |
| switch.auto_recharge_standby (STUN) | ✓ live (AMBIGUOUS_TOGGLE shape) | ⚠ same | ⚠ T4 needed |
| switch.ai_obstacle_photos (AOP) | ✓ live (AMBIGUOUS_TOGGLE shape) | ⚠ same | ⚠ T4 needed |
| select.navigation_path (PROT) | ✓ live (AMBIGUOUS_TOGGLE shape) | ⚠ same | ⚠ T4 needed |
| switch.dnd (DND) | ✓ live (list[3] time-window shape, 5 fires `[1, 1200, 480]`) | ⚠ ambiguous with LOW (same shape, discriminate by any element > 1) | ⚠ T4 needed |
| switch.low_speed_at_night (LOW) | ✓ live (same shape as DND) | ⚠ same | ⚠ T4 needed |
| switch.anti_theft_lift / offmap / realtime (ATA × 3) | ✓ live (list[3] all-bool, 12 fires, all 3 indices observed) | ⚠ within ATA: which of 3 switches changed (per-index disambiguation) | ⚠ T4 needed |
| switch.custom_charging_period + 2 numbers (BAT) | ✓ live (list[6], 4 fires showing BAT[3] toggle) | ✓ shape uniquely BAT (no ambiguity) | ⚠ T4 needed |
| switch.led_period + 4 LED switches (LIT, READ-ONLY) | ✓ live (list[8] LED_PERIOD, 8 fires, LIT[0] toggle observed) | ✓ shape uniquely LIT | n/a (read-only) |
| switch.human_presence_alert + sensitivity (REC, READ-ONLY) | ✓ live (list[9], 15 fires, REC[6/7] observed flipping) | ✓ shape uniquely REC | n/a (read-only) |
| switch.msg_alert × 4 (MSG_ALERT) | ✓ live (list[4] all-bool, 34 fires across all index combos) | ⚠ ambiguous with VOICE (same shape) — requires getCFG diff | ⚠ T4 needed |
| switch.voice × 4 (VOICE) | ✓ live (same shape as MSG_ALERT) | ⚠ same | ⚠ T4 needed |
| switch.rain_protection + select.rain_protection_resume_hours (WRP) | ✓ live (list[2], 3 fires) | ✓ shape uniquely WRP | ⚠ T4 needed |
| select.language (LANG, READ-ONLY) | ✓ live ({text, voice} unique shape, 1 fire) | ✓ no ambiguity | n/a (read-only) |
| number.volume (VOL) | ⚠ no s2p51 fire observed in 3 weeks (probably just hasn't been changed) | n/a (no shape ambiguity) | ⚠ T4 needed |
| select.mowing_efficiency (PRE) | s6p2[1] live MQTT (separate from s2p51); no s2p51 fire observed for PRE | (PRE uses s6p2, not s2p51) | ⚠ T4 needed |

## Phase 2 candidate: revive `cfg_keys_raw _last_diff` sensor

The 3 ambiguous-shape classes (AMBIGUOUS_TOGGLE / AMBIGUOUS_4LIST / list[3]-time-window-vs-3bool) each cover 2-5 distinct CFG keys. Without a `cfg_keys_raw _last_diff` mechanism (which apparently existed in alpha.123+), the integration cannot uniquely identify which CFG key fired each ambiguous push.

The implementation: maintain a previous-CFG dict; on each s2p51 ambiguous fire, do an immediate `fetch_cfg`; diff the new vs previous; whichever key changed is the disambiguator.

**Status:** Phase 2 candidate; today the integration has the disambiguation gap.
