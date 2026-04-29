# Dreame A2 (g2408) v2 — Outstanding Work

Last updated: 2026-04-29 (v1.0.0a30).

## Open

### Dashboard: replicate the Dreame app's contextual button transitions

The Dreame mobile app shows different button rows depending on mower state:

| State                | App buttons                                       |
| -------------------- | ------------------------------------------------- |
| Docked / idle        | **Start**, **Recharge**                           |
| Charging / charged   | **Start**, **Recharge** (disabled)                |
| Mowing               | **Pause**, **Stop**                               |
| Paused               | **Continue**, **End**, **Recharge**               |
| Returning to dock    | **Start** (disabled), **End Return to Station**   |

The HA Device Info page is rigid — entities are listed in a grid and we
cannot show/hide them per state without custom card logic. Live
buttons today: Start, Pause (only when WORKING/MAPPING), Stop (when
WORKING/MAPPING/PAUSED), Recharge (always), Finalize (always).

What to build: a section on the mower dashboard
(`/config/dashboards/mower/dashboard.yaml`) that uses
`conditional` cards keyed off `lawn_mower.dreame_a2_mower` activity to
render the app-style button row per state. "Continue" reuses the
existing Start button (Start → already handles
WORKING/MAPPING/PAUSED transitions cloud-side). "End" reuses Stop.

Notes:
- Don't duplicate entities — wrap existing buttons in conditional
  cards.
- Recharge stays visible across multiple states per app convention.
- Dashboard sketches in the screenshots in `/data/claude/homeassistant/`
  (IMG_4413.PNG..IMG_4422.PNG capture the app's button layouts in each
  state) — use them as the visual reference.

## Recently shipped

- **v1.0.0a30** — `select.action_mode` / `zone` / `spot` persist across
  HA restart via RestoreEntity. Action mode used to silently snap back
  to All-areas after every reload, causing zone/spot users to trigger
  unintended all-areas mows.
- **v1.0.0a29** — `[NOVEL/value]` log demoted to INFO (informational
  first-time observation on a known slot). `[NOVEL/property]` (real
  protocol gap) stays WARN.
- **v1.0.0a28** — "Get Device OTC Info empty" demoted to INFO.
- **v1.0.0a27** — Start / Pause / Stop / Recharge buttons added to
  device page; Finalize moved out of Diagnostic so all five action
  buttons cluster together.
- **v1.0.0a26** — TASK-envelope wire formats verified against
  Tasshack's g2408-supporting upstream. Spot mow (op=103, `area`),
  zone mow (op=102, `region`) and edge mow (op=101, `edge:[[m,c]]`)
  all wired correctly; previously zone was wrong and spot was a
  local_only TODO.
- **v1.0.0a26** — Cloud-named zone/spot pickers (`select.zone`,
  `select.spot`) populate options dynamically from `MapData`.
- **v1.0.0a25** — Finalize Stuck Session deletes `in_progress.json`
  after archiving so the synthesized in-progress row stops
  reappearing.

## Live-confirmed

- Pause button (v1.0.0a27).
- Stop button (v1.0.0a27).
- Recharge button (v1.0.0a27) — successfully sent the mower back to dock.
- Spot mow attempted from integration (v1.0.0a26); needs re-test on
  v1.0.0a30 since the first attempt's second click started an all-areas
  mow due to action_mode reset (the bug a30 fixes).
