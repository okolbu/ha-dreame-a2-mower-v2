# Mower Path Render Styling Design

**Date:** 2026-05-17
**Closes:** `project_render_styling_todo` (after all 3 phases ship)

## Goal

Bring the static work_log.png + replay-card animation in line with the Dreame app's two-tone green aesthetic, add dynamic pre-start visualization, and fix the animation engine's segment-teleport behavior so the icon walks the path and the stroke fills in behind it.

## Non-goals

- Striped pre-start preview for edge or spot modes (the doc explicitly notes the app's app-side spot picker / graphical selection is not what the integration uses — we have dropdowns).
- Toggling between Dreame-app colors and a custom user palette. Palette is fixed.
- Persisting the fat-vs-thin replay-card preference across sessions (per-card per-browser only).
- Renaming or restructuring existing palette keys beyond what's needed for the new colors.

## Background

Current state of rendering:
- `custom_components/dreame_a2_mower/map_render.py` has `_DEFAULT_PALETTE` (zone fills, exclusion, ignore-obstacle, spot, nav, dock, maintenance points) + a `_TRAIL_COLOR = (70, 70, 70, 220)` (dark grey, width 3) used by both static work_log.png and as the underlay in the replay-card.
- `dreame-mower-replay-card.js` paints an animated red overlay on top of the base PNG, segment by segment, with the mower icon teleporting between segment endpoints.
- The Dreame app uses two greens — a **light green** for the lawn baseline / completed-mow strokes and a **dark green** for the "about to mow" pattern and the visual background of an active mow.

The doc that initiated this work (`mower-path-segments-render-style.txt`) catalogues eight specific issues; this design covers all of them across three phases.

## Architecture

Three phases land independently. Each phase is self-contained and provides user-visible value on its own.

```
P1 — palette + traversal layer + (verify maintenance points)
        |
        v
P2 — animation engine rewrite + fat/thin toggle
        |
        v
P3 — pre-start dynamic viz + per-map direction tracking
```

The renderer (`map_render.py`) is shared between static work_log.png and the replay-card base image, so changing palette there propagates everywhere. The replay-card JS only owns the animated overlay + the toggle + the icon-traversal animation engine.

---

## Phase 1: Color palette + traversal layer + maintenance points

### Palette changes (`map_render.py`)

| Key | Current | New | Purpose |
|---|---|---|---|
| `zone_fills[0]` | `(178, 223, 138, 200)` light-green α200 | `(178, 223, 138, 255)` light-green opaque | "lawn base" / "post-mow stroke" — matches app |
| `dark_green` (NEW) | n/a | `(100, 160, 70, 255)` (same RGB as current `zone_outline`, now used as a fill too) | "pre-mow / cutting target" / active-mow background |
| `ignore_fill` | `(0, 177, 0, 50)` greenish | `(90, 140, 230, 90)` blueish-green semi-transparent | matches app's "ignore obstacle" rendering |
| `ignore_outline` | `(0, 149, 0, 200)` | `(60, 110, 200, 220)` blueish-green outline | (consistent with new fill) |
| `_TRAIL_COLOR` | `(70, 70, 70, 220)` | **DROPPED** — replaced by two purpose-specific colors below | — |
| `mow_trail_color` (NEW) | n/a | `(178, 223, 138, 255)` light-green α255 (same as lawn) | overlays on dark-green base where mowing happened |
| `traversal_color` (NEW) | n/a | `(130, 130, 130, 220)` medium grey | dock-return / cross-map traversal, drawn LAST (always on top) |
| `_TRAIL_LINE_WIDTH` | `3` | unchanged — for thin mode | (fat mode width derived from blade width in P2) |

`zone_outline` keeps its current value `(100, 160, 70, 255)` — it's the same colour as `dark_green` and gives the lawn polygons a defined edge. (`dark_green` is just a more descriptive alias for the same RGB when used in fill contexts.)

### Traversal layer split (`map_render.py:render_with_trail`)

Current `render_with_trail` paints ALL trail points in a single color. Split into two passes:

1. **Mowing strokes**: read from `cloud_track_segments` (the cloud-curated mowing-only segments). Paint in `mow_trail_color`.
2. **Traversal**: read from `_local_legs`. Subtract the cloud-track point set; what remains is dock-return + cross-map traversal. Paint in `traversal_color`. Drawn AFTER mowing strokes so it stays visible.

If `_local_legs` is empty, fall back to drawing only the cloud_track_segments (no traversal visible — same as today for sessions before T8 of session-data-completeness landed).

### Maintenance points

Already rendered (`map_render.py:390-422`). No code change. Verify visually in the next session render that they're showing.

### Static work_log.png concrete change

Switch the "lawn background" in `render_base_map`: when the session is "completed" (i.e. `render_with_trail` is being called for a finished session), the lawn polygon fill is `dark_green`, and the `mow_trail_color` strokes paint over it. The pre-stroke lawn shows as dark green wherever the mower didn't reach. This matches the app's post-mow visual.

(During-active-mow rendering through `render_main_view` will use the same logic. P3 adds the pre-start stripe variant.)

### Tests (P1)

- `tests/protocol/test_palette_constants.py` — assert the new keys exist with the documented RGBA tuples; existing tests that check `zone_fills[0]` opacity get updated.
- `tests/protocol/test_render_traversal_split.py` — feed a synthetic session with cloud_track_segments + local_legs that include a dock-return arc; render via `render_with_trail`; verify pixel-sampling that the dock-return arc renders in `traversal_color` and the mowing strokes in `mow_trail_color`.

### Commits / scope estimate (P1)

3–5 commits, ~150 LOC change in `map_render.py` + ~80 LOC of new tests. Low risk.

---

## Phase 2: Animation engine + fat-vs-thin toggle

### Animation rewrite (`dreame-mower-replay-card.js`)

Replace the current segment-teleport logic in `_tick` / `_renderAt` with progressive-reveal:

1. **Per-frame state**: `currentSegmentIdx`, `progressIntoSegment` (0–1), `elapsedMs`.
2. **Position interpolation**: for the current segment, use SVG `getPointAtLength(progressIntoSegment * segmentLength)` to compute the icon's `(x, y)`. Heading from segment tangent.
3. **Stroke reveal**: draw the current segment as an SVG `<path>` with `stroke-dasharray="totalLen"` and `stroke-dashoffset="(1 - progress) * totalLen"`. As progress increments, the offset decreases, the stroke fills in behind the icon.
4. **Segment transition**: when progress reaches 1.0, mark segment as "drawn complete" (replace the animated dash with a static stroke), advance `currentSegmentIdx`. If the next segment's start point is far from the current segment's end (i.e. there's a traversal gap), animate the icon along a straight line at the configured `traversalSpeedPxPerSec` to bridge it (rendered as a grey traversal stroke that stays after).
5. **Charging windows**: when the timeline enters a `time_charging` window (from session attributes), snap the icon to the dock coords and freeze; resume from the dock once the window ends. Resolves the "icon on lawn during charging" bug.

### Fat-vs-thin toggle

- New button in the card next to play/pause/replay: icon switches between two stroke-width settings.
- **Fat (default)**: stroke-width = `pixels_per_mm * 220` (22cm blade width); paint in `mow_trail_color` (light green). This produces the "lawn turns light green where mowed" visual — matches the app.
- **Thin**: stroke-width = 3 px; paint in `(50, 100, 30, 220)` dark-green α220 (NEW palette key `mow_trail_thin_color` so static + JS can share the same value). Shows individual pass lines.
- Both modes use the same color for traversal (grey, on top).
- Persist toggle state in `localStorage` keyed by `${camera_entity_id}:render_style`. Per-browser; not per-HA-user.

### Tests (P2)

- Static-only tests on the new `mow_trail_thin_color` palette key.
- The animation rewrite is JS — no Python tests. Manual verification: replay a known session, check icon traverses smoothly, stroke reveals as icon moves, charging window freezes icon at dock.

### Commits / scope estimate (P2)

JS work is heavier — likely 4–6 commits, ~300 LOC change in the card + ~50 LOC of Python palette additions. Medium risk on the animation engine (interpolation math + dash offset coordination); easy to ship in feature-flag fashion (keep old engine behind a `?engine=legacy` URL param for one release if needed).

---

## Phase 3: Pre-start dynamic viz

### State tracking

New `MowerState` field, per map:

```python
@dataclass
class MowerState:
    ...
    last_all_area_mow_direction_deg: dict[int, int | None] = field(default_factory=dict)
    # map_id -> last direction in degrees [0, 180) for the most recent
    # all_area or zone session. None = no prior mow recorded for this map.
```

(Per-map dict keyed by `map_id`; mirrors the existing `MowerState.maps_by_id` pattern.)

**Inference at session-finalize**: in the existing `_dispatch_finalize_action` finalize path (after the cloud OSS fetch lands), call a new pure helper `infer_mow_direction(track_segments) -> int | None`:

```python
def infer_mow_direction(track_segments):
    """Return dominant mow direction in degrees [0, 180).

    Aggregates segment-by-segment net displacement: for each segment of
    length >= MIN_SEGMENT_M, atan2(dy, dx) → angle; reduce mod 180 (because
    stripe direction is line-direction, not vector-direction); weight by
    segment length; return the circular mean of the result. None if no
    qualifying segment was found.
    """
```

Only update `MowerState.last_all_area_mow_direction_deg[map_id]` when the finished session's `target_mode` was ALL_AREA or ZONE (not edge, not spot). Persist via `in_progress.json` (so it survives restarts) + add the field to the recorder-merge backfill path so HA's recorder also has it.

### Renderer dispatch

In `render_main_view` (which the live camera entity uses), add a new branch:

```python
def render_main_view(...):
    if state.mow_session != MowSession.IN_SESSION:
        # Idle path — show pre-start preview.
        target = state.task_target_mode
        if target in (TargetMode.ALL_AREA, TargetMode.ZONE):
            return render_base_map(
                ...,
                stripe_overlay=_compute_stripe_overlay(
                    map_data,
                    angle_deg=next_direction(state, map_id),
                    stripe_width_mm=STRIPE_WIDTH_MM,  # tunable cosmetic, see helper
                ),
            )
        if target in (TargetMode.EDGE, TargetMode.SPOT):
            return render_base_map(..., lawn_fill=light_green)  # all-light-green, no stripes
        # No target — same as Active (defensive)
        return render_with_trail(...)
    # Active mow — same as today (mow strokes overlay dark-green lawn).
    return render_with_trail(...)
```

### `next_direction` computation

```python
def next_direction(state, map_id) -> int:
    last = state.last_all_area_mow_direction_deg.get(map_id)
    if last is None:
        return 0  # first-mow baseline
    mode = state.settings_mowing_direction_mode  # "same" | "chequer" | "criss_cross"
    if mode == "same":
        return last
    if mode == "chequer":
        return (last + 90) % 180
    if mode == "criss_cross":
        return (last + 45) % 180
    return last  # unknown mode — pretend "same"
```

### Stripe overlay

New helper `_compute_stripe_overlay(map_data, angle_deg, stripe_width_mm)`:
- Compute lawn polygon bounding box, expand to cover rotated stripes.
- Generate alternating dark-green / light-green bands of width `stripe_width_mm / pixel_size_mm`, oriented at `angle_deg` from horizontal.
- Clip the bands to the lawn polygon (PIL `ImageDraw.polygon` with mask).
- Return the overlay as an RGBA layer to composite onto the base.

**Stripe width tuning note**: The app's stripes appear to be partly cosmetic — the real mow takes more passes than the visible stripes suggest. So `stripe_width_mm` is NOT literal blade width (22cm). Start with a cosmetic value (e.g. `STRIPE_WIDTH_MM = 400`) chosen for visual clarity on typical lawns, expose it as a module constant we can tune after seeing it live. Could become a per-map setting later if a single value doesn't read well across very small (Map 2) and very large (Map 1) lawns.

### Tests (P3)

- `tests/unit/test_infer_mow_direction.py` — feed known cloud_track_segments (horizontal mow, vertical mow, criss-cross) and assert the inferred angle is within tolerance.
- `tests/unit/test_next_direction.py` — exhaustive table-driven test of all 12 combinations (3 modes × {last=None, last=0, last=45, last=90, last=135}).
- `tests/protocol/test_stripe_overlay.py` — render a tiny synthetic map at angle=0, angle=45, angle=90; pixel-sample to verify stripe orientation and band widths.
- Existing render-base-map tests get one new case: idle + all_area target → stripe overlay present.

### Commits / scope estimate (P3)

Largest phase. 6–8 commits, ~250 LOC across `mower/state.py` (new field), `coordinator/_session.py` (finalize-time inference), `coordinator/_restore_merge.py` (handling), `map_render.py` (stripe overlay + dispatch), `_recorder_merge.py` (backfill). Medium risk — depends on the `target_mode` and `mowing_direction_mode` enums being available and stable on the state.

---

## Open questions / probes

1. **Cloud SETTINGS angle field**: a quick scan of `inventory.yaml` and the `dreame_cloud_dumps/` SETTINGS dumps may turn up an angle-shaped field (0/45/90/135) the app uses for mow direction. If found, we can read it directly and skip the inference step in P3. Probe is cheap (one grep); land before P3 starts.
2. **`mowing_direction_mode` value strings**: the integration's `select.dreame_a2_mower_map_N_mowing_pattern` probably exposes the three modes; verify the actual value strings used (`"same"`, `"chequer"`, etc.) so `next_direction` branches on the right keys.
3. **First-mow direction baseline**: design assumes 0° (along mower X-axis when docked). If the cloud's first-mow default differs (e.g. always 90°), match that for consistency.

These don't block the design — they're 1-line tweaks in P3 once probed.

## Phasing

P1 → P2 → P3 sequenced one at a time. P1 ships standalone in a release. P2 ships standalone in another release (animation rewrite needs its own user-visible release notes). P3 ships last because it needs the most state-tracking work and is the highest risk.

Estimate: P1 = 1 day, P2 = 2 days, P3 = 2–3 days. All-in: ~1 week of focused work.
