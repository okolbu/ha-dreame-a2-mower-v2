# Session calendar one-tap-replay — research TODO

> **Status — DEFERRED.** Last evaluated 2026-05-13.

## Current state (v1.0.9a2+)

The Sessions tab uses HACS `atomic-calendar-revive` for the calendar
visual. Works for at-a-glance month overview of archived mow sessions.
The calendar event `summary` is formatted by
`custom_components/dreame_a2_mower/calendar.py::_event_from_entry()` to
match `select.dreame_a2_mower_work_log`'s option label byte-for-byte
(pinned by `tests/integration/test_calendar.py::test_calendar_summary_matches_work_log_label`).

To replay a session today: see it on the calendar → look at the Replay
picker dropdown below → find the matching label (sorted recent-first)
→ tap. Two surfaces, two clicks (open dropdown + select).

## Why not one-tap

Both candidate cards fail in different ways:

1. **HA-native `type: calendar`** — the more-info popup that opens on
   event tap is hard-coded in the HA frontend (summary / start / end /
   description only). No extension point for buttons or service calls.

2. **atomic-calendar-revive (v10.2.2)** — has a top-level `tap_action`
   config but:
   - Fires the SAME service call regardless of which event was tapped
   - `service_data` is passed verbatim to `hass.callService`; no
     templating like `{{event.summary}}` or `<event-title>` substitution
   - Bottom event-list panel in Calendar mode has no hide option
   - Both gaps are unaddressed in upstream (GitHub discussions #1389
     resolved tap action support but not per-event data passing; no
     issue tracks the hide-list ask).

   Confirmed by reading the bundled JS and by checking docs at
   https://docs.totaldebug.uk/atomic-calendar-revive/ + GitHub
   discussions on 2026-05-13.

## Proposed solution (F)

Write a bundled custom JS card at
`custom_components/dreame_a2_mower/www/dreame-a2-session-calendar.js`,
registered the same way as the existing `dreame-a2-lidar-card.js` and
`dreame-a2-schedule-card.js` (via `hass.http.async_register_static_paths`
in `__init__.py`).

### Card design

- **Inputs:** reads from `calendar.dreame_a2_mower_sessions`
  (`async_get_events`) for the visible month window.
- **Visual:** 7-column month grid, similar to atomic-calendar-revive.
  Each day-cell shows a mower icon if any session ended that day.
- **Per-event interaction:** clicking a session inside a day-cell
  calls `select.select_option` with `entity_id:
  select.dreame_a2_mower_work_log` and `option: <event.summary>`. The
  Replay picker below updates → `camera.dreame_a2_mower_work_log`
  renders the chosen session.
- **Bonus:** a small popup on event tap showing duration, area,
  distance (the same fields currently in the calendar event
  description).
- **Drops:** the atomic-calendar-revive HACS dep.

### Effort estimate

~half-day of frontend work:
- ~2h grid layout + month navigation + cell rendering
- ~1h event fetch + session-on-day matching
- ~1h tap_action wire + popup
- ~1h polish + minor card-config UI (entity picker)

### Files affected

- New: `custom_components/dreame_a2_mower/www/dreame-a2-session-calendar.js`
- Modify: `dashboards/mower/dashboard.yaml` (swap card type, drop the
  Replay picker since the new card subsumes it)
- Modify: `lovelace.yaml` resources (drop atomic-calendar-revive line,
  no new entry needed since the static path is already registered)

### Acceptance

- Calendar grid visually equivalent to atomic-calendar-revive's
  Calendar mode
- Single tap on a session in any day-cell jumps the replay picker
- No dependency on atomic-calendar-revive (can be removed via HACS)

## Why not now

You'd shipped 18 tasks today (Phase 1 + Phase 2 + release v1.0.9a2)
plus the atomic-calendar-revive wire-up. Accepting E for this round
clears the cleanup spec; F is its own focused half-day task with a
clean kickoff later.

## Related

- `tests/integration/test_calendar.py::test_calendar_summary_matches_work_log_label`
  — pins the work_log label format. A custom card depends on this
  same byte-for-byte match.
- `custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js` —
  reference for how a bundled JS card is written + registered.
- `cleanups.txt` — original Sessions #4 ask: "calendar view be
  possible for the sessions".
