# Session Replay Animation — Design

**Date:** 2026-05-15
**Status:** Draft (pending user review)
**Author:** brainstorm session

## Problem

The Sessions tab currently shows a static "work-log" PNG: the mower's full
trajectory for the picked session drawn in one pass over the base map.
It's accurate but inert — you can't tell from the picture how the session
*unfolded*: where it started, what order it covered, where it paused.

The request: an optional animated replay that draws the trail
segment-by-segment, fits a 2-3 h real session into ≤30 s of playback, and
honors mid-session pauses (charging, stuck, faulted) as proportional
freezes in the animation so the timing reads as truthful.

## Non-goals (v1)

- Distinguishing pause causes visually (charging vs stuck vs fault).
  v1 treats all non-mowing intervals as one "pause" category. v2 may
  add per-cause icons.
- Variable playback speed (1× / 2× / 0.5×). Single fixed speed in v1.
- Multi-session compare overlays.
- Battery / WiFi overlays synchronized to the trail head.
- Replacing the existing static work-log render — that stays as the
  default; animation is opt-in via a toggle.

## Architecture

Two-sided change:

```
┌──────────────────────────┐    ┌──────────────────────────────┐
│ Integration (Python)     │    │ Dashboard (YAML)             │
│                          │    │                              │
│ sensor.picked_session    │    │ input_boolean.animate_session │
│   .legs                  │───▶│                              │
│   .state_samples         │    │ conditional: animate=false   │
│   .map_projection        │    │   → existing static camera   │
│   .base_map_image_url    │    │ conditional: animate=true    │
│                          │    │   → html-template-card       │
│                          │    │     <svg> + JS               │
│                          │    │     reads attrs, animates    │
└──────────────────────────┘    └──────────────────────────────┘
```

### Integration side

Four new keys in `session_card.build_picked_session_summary`'s output
dict (which becomes `sensor.dreame_a2_mower_picked_session`'s extra
state attributes):

| Attribute | Type | Source |
|---|---|---|
| `legs` | `list[list[[x_m, y_m]]]` | Already computed for the distance helper at `session_card.py:44-46`. Just expose. |
| `state_samples` | `list[[ts_s, state_value]]` | Already read at `session_card.py:268`. Just expose. |
| `map_projection` | `{ png_w, png_h, px_per_m, origin_m_x, origin_m_y }` | Factor out of `map_render.py` (transform already exists and is correct — used by the static PNG path). |
| `base_map_image_url` | `str` | `/api/camera_proxy/camera.dreame_a2_mower_session_replay?token=…` (or the equivalent URL for whichever camera serves the work-log PNG). |

Pure-additive change — no migrations, no entity renames, no breaking
schema. The dashboard side ignores attributes it doesn't use.

### Dashboard side

One new HACS install: `html-template-card`
([gadgetchnnl/lovelace-html-template-card](https://github.com/PiotrMachowski/lovelace-html-template-card)
or equivalent — confirm the most-maintained fork during install).

One new helper:
`input_boolean.dreame_a2_mower_animate_session` (default off).

Sessions-tab map area becomes a conditional pair:

```yaml
- type: conditional
  conditions:
    - entity: input_boolean.dreame_a2_mower_animate_session
      state: "off"
  card:
    type: picture-entity
    entity: camera.dreame_a2_mower_session_replay   # current behavior
- type: conditional
  conditions:
    - entity: input_boolean.dreame_a2_mower_animate_session
      state: "on"
  card:
    type: custom:html-template-card
    content: |
      <svg viewBox="0 0 {{ projection.png_w }} {{ projection.png_h }}">
        ... (see Animation mechanism below) ...
      </svg>
      <div class="controls">
        <button id="play">▶</button>
        <button id="pause">⏸</button>
        <button id="replay">↻</button>
        <input type="range" id="scrub" min="0" max="1000" value="0">
      </div>
      <script> ... ~80 lines, see below ... </script>
```

## Animation mechanism

### Coordinate transform

Per the user, `render_work_log` already projects `(x_m, y_m) → pixel`
correctly. The mechanical step is exposing that transform's parameters
(`px_per_m`, `origin_m_x`, `origin_m_y`, `png_w`, `png_h`) as a dict on
the sensor so the SVG can reproduce it:

```js
// Exact form mirrors render_work_log's existing projection — that's the
// load-bearing constraint. Don't re-derive; copy whatever map_render does.
const px = (m_x) => (m_x - proj.origin_m_x) * proj.px_per_m;
const py = (m_y) => (m_y - proj.origin_m_y) * proj.px_per_m;
```

The SVG `viewBox="0 0 png_w png_h"` matches the base map image's
pixel grid 1:1.

### Trail drawing

One `<path>` per leg. Each path is built once at mount as
`"M px(p0) py(p0) L px(p1) py(p1) L ..."`. The "drawing" effect uses
`stroke-dasharray` set to the path's `getTotalLength()` and animates
`stroke-dashoffset` from `length → 0` via the Web Animations API
(`path.animate([{strokeDashoffset: L}, {strokeDashoffset: 0}], {duration: …})`).

### Timing model

```
session_duration = end_ts - start_ts          # wall-clock seconds
mowing_duration  = sum of intervals where state ∈ "mowing"
pause_duration   = session_duration - mowing_duration

draw_budget_s    = 30 * (mowing_duration / session_duration)
pause_budget_s   = 30 * (pause_duration  / session_duration)
total_animation  = 30s
```

The drawing budget is split across legs proportional to each leg's
share of total trajectory length. Pause budget is split across pause
intervals proportional to each pause's share of total pause time.

A leg's `animate()` is followed by a `setTimeout` of length
`pause_budget_for_this_pause_ms` before the next leg's `animate()`
starts. The head marker stays put during the pause (no extra code —
it's just not moved).

### State → mowing/pause classification

A v1-pragmatic mapping until per-value semantics are nailed down:

| state_value | interpretation |
|---|---|
| `1`, `2`, `3` | mowing (advancing trail) |
| `5`, `6` | returning / docking (pause) |
| everything else | pause |

If the inferred pause durations look off in real sessions, we revisit
this table — it lives in the JS and is trivial to tune.

### Head marker

`<circle r="6" fill="orange">` whose `cx`/`cy` are updated on each
animation tick via the path's `getPointAtLength(L - currentOffset)`.

### Controls

Plain HTML; ~80 lines of JS in total:

- ▶ / ⏸: `web Animations` `.play()` / `.pause()` on the leg animation
  currently running, plus pause/resume of any pending `setTimeout`.
- ↻: cancel all pending animations and re-trigger from t=0.
- Scrub: maps slider value 0–1000 to a fractional position in the
  precomputed timeline; calls `.currentTime = ...` on the active
  animation and short-circuits prior legs to their fully-drawn state.

### Autoplay on session pick

The card's root JS listens for `hass-state-changed` on
`sensor.dreame_a2_mower_picked_session`. On change, it tears down the
current animation and rebuilds from the new session's attributes.
If the toggle is off, no card is mounted at all (the conditional hides
it), so the change costs nothing.

## Open questions for implementation

These are non-blocking — surface during the writing-plans step:

1. **map_projection schema** — exact field names and units. The
   integration-side answer comes from reading `map_render.py`'s
   current transform.
2. **base_map_image_url stability** — HA proxies camera URLs through
   tokens that rotate. Either include the token in the attribute
   (rotates each restart, fine for a UI value) or pin a stable
   route. Resolve at implementation.
3. **html-template-card fork choice** — multiple forks exist; pick the
   one with current maintenance and CSP-friendly behavior.
4. **state_value semantics** — confirm the mowing-vs-pause table by
   sampling state_samples from real sessions before committing the JS.

## Risks

1. **html-template-card CSP / inline JS** — Home Assistant's frontend
   CSP may restrict inline `<script>` or specific Web Animations API
   usage. Verify with a 10-line proof-of-concept before writing the
   full animation code. If blocked, alternatives: card-mod with raw
   JS, or fall back to a custom Lit card.
2. **Very long sessions** — 10 000+ point trajectories may stress
   `getTotalLength()` / `getPointAtLength()`. Mitigation: if seen in
   the wild, downsample legs via Ramer–Douglas–Peucker at the
   integration boundary before exposing. Defer until observed.
3. **Conditional-card re-mount kills playback** — toggling the
   animation switch off then on may reset rather than resume. v1 UX
   acceptable; document as known limitation.

## Out of scope (defer to v2+)

- Pause-cause icons (charging ⚡ / stuck ⛔ / fault ⚠)
- Variable playback speed
- Multi-session overlay compare
- Battery/WiFi overlay synchronized with trail head
- Per-leg coloring by mowing strategy (edge / spot / area)
- Obstacle / AI-obstacle dots animated in at the moment they were detected

## Acceptance criteria

- Toggle in the Sessions tab switches between static and animated.
- A 2 h session with one mid-session recharge plays back in ≤30 s
  total, with the recharge interval clearly visible as a freeze.
- The animated trail's final state is pixel-equivalent to the static
  PNG (same legs, same path).
- Play / pause / replay / scrub all work without console errors.
- Picking a different session while animated mode is on tears down
  the current animation and starts the new one within ~500 ms.
