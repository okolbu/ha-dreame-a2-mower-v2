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

A single-file custom Lovelace card co-distributed with the
integration. No third-party HACS install required.

**File layout:**

```
custom_components/dreame_a2_mower/
  www/
    dreame-mower-replay-card.js    # ~250 lines, one ES6 module
  __init__.py                       # registers /local-static path
```

The integration's `async_setup_entry` adds a static path so the JS is
served at a stable URL (e.g. `/dreame_a2_mower/dreame-mower-replay-card.js`)
and registers it as a Lovelace resource so HA loads it on dashboard
mount. This is the same pattern HACS uses for its bundled cards — just
without the HACS layer.

**Why a custom card, not html-template-card:**

The earlier draft of this spec proposed `html-template-card` for
inline `<svg>` + `<script>`. On closer inspection that card uses
`innerHTML` to render its template, and the HTML5 spec strips
`<script>` tags assigned via `innerHTML`. Inline event handlers
(`onclick=`, `onload=`) may execute but Home Assistant's frontend CSP
can block them, and issue #10 on the card's repo is open with no
maintainer-blessed workaround. The reliability problems are not worth
fighting when a single-file custom card delivers the same UX with
fewer moving parts and ships through the integration's existing
distribution channel.

**Helper:**

`input_boolean.dreame_a2_mower_animate_session` (default off) — the
user-facing toggle.

**Dashboard YAML:**

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
    type: custom:dreame-mower-replay-card
    entity: sensor.dreame_a2_mower_picked_session
```

The card pulls everything it needs from the entity's attributes
(`legs`, `state_samples`, `map_projection`, `base_map_image_url`).
No further YAML configuration required for v1.

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

One `<path>` per leg, rendered inside the card's shadow DOM. Each path
is built once at mount as `"M px(p0) py(p0) L px(p1) py(p1) L ..."`.
The "drawing" effect uses `stroke-dasharray` set to the path's
`getTotalLength()` and animates `stroke-dashoffset` from `length → 0`
via the Web Animations API (`path.animate([{strokeDashoffset: L},
{strokeDashoffset: 0}], {duration: …})`). Shadow DOM means the card's
CSS and animation lifecycle are isolated from the rest of the
dashboard.

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

The custom card receives a fresh `hass` object every time HA state
changes (standard Lovelace card protocol — `set hass(hass)`). On each
update the card compares the picked-session sensor's `last_changed` or
`state` to its cached value; if it changed, it tears down the current
animation (`element.getAnimations().forEach(a => a.cancel())`) and
rebuilds from the new session's attributes.

If the toggle is off, the card isn't mounted at all (the conditional
hides it), so the change costs nothing.

## Open questions for implementation

These are non-blocking — surface during the writing-plans step:

1. **map_projection schema** — exact field names and units. The
   integration-side answer comes from reading `map_render.py`'s
   current transform.
2. **base_map_image_url stability** — HA proxies camera URLs through
   tokens that rotate. Either include the token in the attribute
   (rotates each restart, fine for a UI value) or pin a stable
   route. Resolve at implementation.
3. **Static-path registration vs. HACS plugin route** — decide whether
   the JS ships via the integration's own static-paths registration
   (single source of truth, version-locked to the integration) or as
   a HACS frontend plugin (familiar to users, but doubles release
   surface). Recommend the static-paths route.
4. **state_value semantics** — confirm the mowing-vs-pause table by
   sampling state_samples from real sessions before committing the
   card JS.

## Risks

1. **Lovelace resource registration** — the integration needs to add
   the card's JS as a Lovelace resource (or have the user add it
   manually). HA changed this API in 2024; verify the current
   recommended path. If `lovelace.resources` is dashboard-storage-mode
   only, YAML-mode dashboards may need a separate `resources:` entry
   documented in the integration README.
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

### OSM-tile variant (deferred)

A second card variant could render the same animation over a real-world
OpenStreetMap (or similar) tile background instead of the mower's
learned-map PNG. The user has both the dock GPS coordinate and the dock
yaw, which is everything needed to project `(x_m, y_m) → (lat, lon)`
via a local-tangent-plane approximation (good to <1 % over a yard-sized
area).

If pursued: the integration would expose a parallel `legs_latlon`
attribute on `picked_session` (only when dock GPS + yaw are
configured), and a second html-template-card variant would overlay
the SVG trail on a Leaflet tile layer. The trade-off is loss of
mower-specific context (no obstacles, no-go zones, dock marker) in
exchange for real-world recognizability — useful for the
"show family / show visitors" use case.

This was evaluated as a Plan B during brainstorming because
`timeline_card` and other GPS-coord cards looked promising. None of
them deliver animated playback with scrub controls, so the v1 SVG
approach won regardless. The dock GPS/yaw projection is captured here
so it doesn't have to be re-discovered later.

## Acceptance criteria

- Toggle in the Sessions tab switches between static and animated.
- A 2 h session with one mid-session recharge plays back in ≤30 s
  total, with the recharge interval clearly visible as a freeze.
- The animated trail's final state is pixel-equivalent to the static
  PNG (same legs, same path).
- Play / pause / replay / scrub all work without console errors.
- Picking a different session while animated mode is on tears down
  the current animation and starts the new one within ~500 ms.
