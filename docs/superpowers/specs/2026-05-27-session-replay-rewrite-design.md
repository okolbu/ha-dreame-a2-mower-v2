# Session Replay — Architecture Rewrite

**Date:** 2026-05-27
**Status:** Draft (pending user review)
**Supersedes:** `2026-05-15-session-replay-animation-design.md`,
`2026-05-08-replay-session-cleanup-design.md`

## Problem

The animated session replay does not reflect how the mow actually unfolded.
Visible symptoms across affected sessions:

- **Out-of-order rendering.** Multiple lawn patches appear to be mowed
  simultaneously, as if several mowers were running in parallel.
  (E.g., `2026-05-27 07:58` shows roughly half the lawn complete on
  animation frame 2.)
- **Charging time vanishes from the replay.** Some sessions never show
  the mower freezing at the dock during a mid-mow recharge.
  Others (e.g., `2026-05-20 07:58`) defer most of the mowing to the
  last third of the animation, completely misrepresenting the
  session's true pacing.
- **Mid-mow traversals draw in green.** Repositioning between mowed
  strips (where the blades aren't cutting new grass) renders as
  mowing. The mower is never shown moving "with blades up" on the
  actual lawn, only during dock-to-spot drives.
- **The last segment of a dock-to-spot traversal is colored mowing.**
  Of N traversal segments from dock to the spot, the first N-1 are
  grey and the last is green.
- **No back-to-dock return drawn.** The end-of-session MQTT fires
  while the mower is still on the lawn, so the homeward arc is never
  captured.

Underlying causes (verified by code review):

1. **No per-point timing is persisted.** Per-leg `start_ts`/`end_ts` is
   the finest resolution available. Inside a leg covering 12 min of
   dock-to-spot-to-mowing, the JS card has no way to know when each
   point happened, so it invents timing by cumulative path length.
   A 50 m mowing leg gets twice the screen-time of a 25 m traversal
   leg even if the traversal took longer wall-clock.
2. **`compute_legs_timeline_from_diff` drops timestamps.** The OSS-diff
   path (taken whenever both local and cloud trails are present, i.e.
   the common case for finished mows) emits `{role, pts}` records with
   no `start_ts`/`end_ts`. The JS card's `hasRealTimes` check fails →
   fallback to length-driven cumulative scheduling.
3. **`set_mowing` defaults to True and flips only on s2p1 task_state
   changes.** Inter-strip repositioning during a mow keeps
   task_state=WORKING, so the leg never flips → no grey during mowing.
   The "last traversal segment before mowing is green" is the same bug:
   pre-classification telemetry inherits the True default before the
   first s2p1 transition.
4. **Two parallel classifiers fight.** `_legs_meta` (per-leg task-state
   based) versus `_diff_legs_timeline` (spatial coverage of cloud
   against local). They disagree, and the JS uses whichever wins the
   `if/elif` chain at attribute build time.
5. **`live_map` stops capturing at end-of-session MQTT.** The 3-5 min
   drive back to dock isn't recorded.

The architecture splits "ordering" from "classification" and stitches
them with cumulative-length heuristics. A session has one ground truth
— where the mower was at time T, with blades up or down — and the
current design reconstructs it from three lossy projections that don't
agree.

## Solution

A single per-point time-ordered event stream is captured during the
session, classified on append, validated and refined at finalize,
persisted in the archive, and replayed in real wall-clock order
(scaled by a fixed compression factor) by the JS card.

### Principles

1. **Time end-to-end.** Every captured position carries `t` (unix
   seconds, ms precision). Replay walks the stream in real-time order
   scaled by one compression factor. No length-driven scheduling, no
   synthesized pause budgets — gaps in the stream ARE the pauses.
2. **Classification is data, not control flow.** Each point carries a
   `role` field. The classifier runs once on point-append (live), then
   once again at finalize (with cloud validation + smoothing). The
   archived `role` is final — JS does no re-classification.
3. **Cloud track is a validator, not the spine.** Stored verbatim as
   `cloud_track`. Used by the classifier to upgrade `traversal` to
   `mowing` when a point lies inside a cloud-mowed area (the
   re-mow-over-already-cut-grass case). If OSS fetch fails, animation
   still works on local data alone.
4. **Clean break on archive format.** New archives have `track`,
   `cloud_track`, the existing scalar streams, and metadata. Old
   archives must be rebuilt via the existing probe-log tool
   (`tools/rebuild_session.py`). No dual-mode reader. No legacy branch.

## Non-goals (v1)

- Variable per-segment colour (e.g., colouring by mowing mode or by
  edge-vs-fill). Replay v1 is two-color: mowing (green), traversal
  (grey).
- Segment-colored progress slider (showing mowing/charging/rain
  phases inline on the scrub bar). Future enhancement.
- Real-world / OSM-tile background variant.
- Multi-session overlay compare.
- Per-cause pause icons beyond the three already-known states
  (charging, rain, fault). Future enhancement.

## Data model

### Per-point capture

```python
@dataclass(slots=True, frozen=True)
class TrackPoint:
    t: float                     # unix seconds, ms precision
    x_m: float                   # cloud-frame metres, charger-relative
    y_m: float
    area_m2: float               # cumulative area_mowed from this same s1p4
    heading_deg: float | None    # from s1p4 if present
    task_state: int              # latest known s2p1 code at point time; diagnostic
    role: str                    # "mowing" | "traversal" — assigned by classifier
```

### Archive shape

```json
{
  "track":        [ {t, x_m, y_m, area_m2, heading_deg, task_state, role}, ... ],
  "cloud_track":  [ [[x_m, y_m], ...], ... ],
  "state_samples":          [ [t, code], ... ],
  "battery_samples":        [ [t, pct], ... ],
  "charging_status_samples":[ [t, code], ... ],
  "error_samples":          [ [t, code], ... ],
  "wifi_samples":           [ [x, y, rssi, t], ... ],
  "settings_snapshot":      { ... },
  "summary": {
    "start_ts": int, "end_ts": int,
    "mode": int, "pre_type": int, "start_mode": int,
    "area_mowed_m2": float, "map_area_m2": float, "duration_min": int,
    "result": int, "stop_reason": int,
    "faults": [...], "obstacles": [...], "ai_obstacle": [...]
    /* anything that was already in SessionSummary EXCEPT track_segments */
  }
}
```

Removed entirely (no longer written, no longer read):
`_local_legs`, `_mowing_legs`, `_traversal_legs`, `_legs_meta`,
`legs`, `mowing_legs`, `traversal_legs`, `local_leg_count`.

The `legs_timeline` attribute name survives as the card's JS-facing
input, but its producer is rewritten — it now flows from
`derive_render_legs(track)` rather than `_legs_meta` /
`_diff_legs_timeline` paths.

### Render-time leg derivation

`session_card._summary_trail_legs` rebuilds the JS-consumable shape
from `track` on every attribute build:

```python
def derive_render_legs(track, pen_up_gap_ms=30_000):
    """Split track into maximal contiguous runs sharing role with no
    pen-up boundary between consecutive points.

    Pen-up boundary: dt > pen_up_gap_ms (default 30 s).
    Role flip:       role[i] != role[i+1].

    Returns: list of {role, start_ts, end_ts, pts: [(x,y), ...]}
    """
```

The JS card receives exactly this shape under `legs_timeline`, which
becomes its single input.

## Capture

### `LiveMapState` rewrite

The dataclass loses every leg-related field and grows a single
time-coded `track`.

```python
@dataclass(slots=True)
class LiveMapState:
    started_unix: int | None = None
    last_telemetry_unix: float | None = None
    session_ending: bool = False              # NEW — extends capture past cloud end
    track: list[TrackPoint] = field(default_factory=list)

    # Latest task_state from s2p1 — tagged onto each new point.
    _last_task_state: int = -1
    # Last appended point's area, for area_delta classification.
    _last_area_m2: float = 0.0

    # Other streams unchanged: wifi_samples / battery_samples /
    # charging_status_samples / state_samples / error_samples /
    # charge_at_start / settings_snapshot.

    # REMOVED: legs, leg_is_mowing, leg_start_ts, leg_end_ts,
    #          _current_is_mowing, set_mowing(), begin_leg(),
    #          mowing_legs property, traversal_legs property.
```

### Append flow

```python
def update_task_state(self, t: float, code: int) -> None:
    """Called from MQTT handler on every s2p1 push.

    Records the sample under state_samples (existing behavior) AND
    updates self._last_task_state so subsequent append_point() tags
    the point with the current code.
    """

def append_point(
    self, t: float, x_m: float, y_m: float,
    area_m2: float, heading_deg: float | None,
) -> None:
    # 1. Dedup: skip if <20 cm from last point AND <500 ms elapsed.
    # 2. Classify (stage 1, live):
    prev_area = self._last_area_m2 if self.track else 0.0
    area_delta = area_m2 - prev_area
    role = "mowing" if area_delta > 0 else "traversal"
    # 3. Append.
    self.track.append(TrackPoint(
        t=t, x_m=x_m, y_m=y_m,
        area_m2=area_m2, heading_deg=heading_deg,
        task_state=self._last_task_state, role=role,
    ))
    self._last_area_m2 = area_m2
    self.last_telemetry_unix = t
```

### Lifecycle — capture until docked

The cloud "end-of-session" signal now flips `session_ending = True`
rather than ending capture. Capture continues to append points to the
same `track` list while `session_ending` is True. `finalize()` runs
(closing the archive) when one of:

- `charging_status` flips to CHARGING (mower physically on dock pins), or
- 10 min watchdog elapses since `session_ending = True`, or
- A new session begins (force-closes the previous).

The OSS fetch still triggers on end-of-session — runs in parallel with
continued capture; merges at finalize time.

### Disk write cadence

Unchanged: `_persist_in_progress` runs on its 30 s debounced
dirty-gated timer (one write per 30 s of active capture), plus one
archive write on finalize. The per-point stream replaces `_local_legs`
in the in-memory state, so on-disk size stays comparable (a 2 h
session at 5 Hz dedups to roughly the same point count as today's
trail).

If size becomes a pain point, the in-progress trail can move to an
append-only NDJSON sidecar that grows incrementally; the
small JSON keeps everything else. This is an implementation knob, not
an architectural change — defer until measured.

## Classifier

Two-stage. Both stages use only fields already in the per-point
stream + the optional `cloud_track`.

### Stage 1 — On point-append (live, O(1))

```
area_delta = point.area_m2 - prev_area_m2     (prev = 0 for first point)
role       = "mowing" if area_delta > 0 else "traversal"
```

That is the entire stage 1. Live render uses this immediately so the
live trail is correctly coloured as the mow proceeds.

### Stage 2 — On finalize, after cloud OSS arrives (one-shot, O(N))

1. **Cloud-coverage rescue.** Build the spatial grid (reuses
   `_build_cloud_grid` from `trail_diff.py`). For each point whose
   role is currently `traversal`, query the grid for cloud-segment
   coverage with `tol_m = 0.6`. If within tolerance of any cloud
   segment, upgrade to `mowing`. Catches re-mow loops and
   sub-counter-tick mowing.

2. **Smoothing.** 3-pass sliding-window pass: any point whose role
   differs from BOTH immediate neighbours flips to the neighbour
   role. Collapses 1-2 point classification stutters at strip
   boundaries.

3. **Persist.** Update each `TrackPoint.role` in the archive's
   `track`. The archived classification is final.

### Degraded mode (no cloud)

If OSS fetch fails, Stage 2 step 1 is skipped. Steps 2-3 still run.
Result: re-mow loops show as traversal grey — defensible (they didn't
add new mowed area). Live render and replay both still work.

## Rendering (JS card)

The card keeps its shadow DOM, controls, scrub bar, and dock-snap. The
timing engine is replaced.

### `_startAnimation` rewrite

```js
const FIRST_T = a.track_first_ts;
const LAST_T  = a.track_last_ts;
const WALL_DUR_MS = (LAST_T - FIRST_T) * 1000;

// Compression: constant simulated-time speed (default 200×).
// Replay-speed slider scales this.
const compression = this._currentReplaySpeed();
const ANIM_DUR_MS = clamp(WALL_DUR_MS / compression, 3_000, 90_000);

// Each leg gets its real share of the animation timeline.
this._timeline = legs.map(leg => ({
    start_ms: ((leg.start_ts - FIRST_T) * 1000) / compression,
    end_ms:   ((leg.end_ts   - FIRST_T) * 1000) / compression,
    role: leg.role,
}));
this._totalMs = ANIM_DUR_MS;
```

The `legGapMs`, `pauseBudgetMs`, `local_leg_count`, and
`hasRealTimes`-vs-length-driven branching machinery is deleted.

### `_renderAt(ms)` simplification

For each leg, draw it relative to `ms` against its `start_ms`/`end_ms`
slot. Between legs (`prev.end_ms ≤ ms < next.start_ms` and the gap is
NOT a pen-up boundary), interpolate the mower icon along the straight
line between leg endpoints. For pen-up gaps (legs derived as
non-touching by the producer), leave the icon at the previous leg's
endpoint until `ms ≥ next.start_ms` — no straight-line stroke is
drawn.

Charging-window snap (icon to dock during charges) stays — same
algorithm, but the charging windows are mapped to animation time via
the same compression factor.

### Replay-speed slider

A new range input next to the scrub bar. Position maps log-scaled to
50× .. 800× compression. Default 200×. Persisted in `localStorage`
under a key that includes the integration's slug.

### Pause overlay labels

When `_renderAt` notices the playhead is in a between-leg gap of
significant duration AND a `state_sample` in that wall-clock window
matches `CHARGING` / rain / fault, render a small text overlay
(`🔋 charging — 32 min`, `🌧 rain delay`, `⚠ stuck`). The label
fades in/out at the gap boundaries. No animation, no per-cause icon
art in v1.

### Default compression sanity check

| Real duration | Anim duration (200×) | Clamped |
|---|---|---|
| 5 min      | 1.5 s   | 3 s (floor) |
| 30 min     | 9 s     | 9 s         |
| 2 h        | 36 s    | 36 s        |
| 6 h        | 108 s   | 90 s (cap)  |
| 19 h rain  | 342 s   | 90 s (cap)  |

The cap on the long tail is the trade-off for finite watch time.
Users can scale up further via the slider for short sessions.

## Migration

### One-time rebuild for existing archives

The existing `tools/rebuild_session.py` is updated to:

1. Walk `sessions/*.json` for files missing the new `track` key.
2. For each archive's `start_ts`/`end_ts` window, find the
   covering probe-log files.
3. Replay the probe-log s1p4 stream through a stripped-down
   `LiveMapState` (same `append_point` logic) to rebuild `track`.
4. Run the finalize-stage classifier (cloud rescue + smoothing)
   using the archive's existing `cloud_track` (or its previous
   `summary.track_segments` if `cloud_track` isn't yet stored).
5. Replace the archive's content with the new shape, deleting all
   removed keys.

This is dev-box-only; the user runs it once after upgrading the
integration. New sessions captured after upgrade write the new shape
natively.

### Code removed

- `LiveMapState.set_mowing`, `begin_leg`, `mowing_legs`,
  `traversal_legs`, `leg_is_mowing`, `leg_start_ts`, `leg_end_ts`,
  `_current_is_mowing`.
- `_inject_live_map_into_raw_dict`'s `_local_legs` /
  `_mowing_legs` / `_traversal_legs` / `_legs_meta` writes.
- `coordinator/_mqtt_handlers.py` — `set_mowing(...)` call site
  replaced with `update_task_state(t, code)`.
- `session_card._summary_trail_legs`'s legacy branch (everything
  that doesn't read `track`).
- `session_card._compute_distance_m`'s `summary.track_segments`
  fallback (the new function walks `track` directly).
- `protocol/trail_diff.py`'s `compute_legs_timeline_from_diff` (no
  longer called; the per-point classifier does its job better).
  `compute_traversal_from_diff` may also become unused — verify
  during implementation. The grid-builder helpers
  (`_build_cloud_grid`, `_make_coverage_check`) survive and are
  reused by the classifier's cloud-rescue stage.
- JS card: `_computePauseIntervals`, `legGapMs`, `pauseBudgetMs`,
  length-driven branch of `_startAnimation`, the `hasRealTimes`
  check, the `a.mowing_legs` / `a.traversal_legs` / `a.legs`
  fallback chain in `_render`.

### Code added

- `LiveMapState.update_task_state(t, code)`.
- `LiveMapState.append_point(...)` rewritten to take `area_m2` and
  `heading_deg`, classify inline.
- `session_card.derive_render_legs(track, pen_up_gap_ms)`.
- `session_card._compute_distance_m(track)` — also produces
  `distance_mowing_m` / `distance_traversal_m` split.
- Classifier finalize pass — new module or extension of
  `live_map/finalize.py`.
- JS replay-speed slider + log-scaled compression mapping + clamped
  animation duration.

### Inventory updates required

Per the repo's fact-discipline rule, the following inventory entries
need verifications added (`status: verified` once wire-confirmed,
otherwise `presumed`):

- `summary_track_segments` — semantic change: cloud parser still
  yields it; integration stores under `cloud_track` and stops
  surfacing to dashboard.
- New entry: `archive_track` (the per-point stream shape).
- New entry: `archive_cloud_track` (verbatim cloud blob).
- Retract any `_local_legs`, `_legs_meta`, `_mowing_legs`,
  `_traversal_legs` mentions in `inventory.yaml` / `entity-inventory.yaml`.

## Testing

### Unit tests

- `LiveMapState.append_point`: dedup, role classification by
  area_delta, task_state inheritance, first-point area-from-zero
  semantics.
- `LiveMapState.update_task_state`: tagging next point only,
  state_samples recording.
- Classifier stage 2: cloud rescue upgrades, smoothing collapses
  1-2 point stutters, degraded mode without cloud.
- `derive_render_legs`: pen-up gap > 30 s breaks legs, role flip
  breaks legs, contiguous same-role no-gap stretches stay one leg.
- `_compute_distance_m(track)`: pen-up gaps excluded, role split
  sums match total.

### Integration tests

- End-to-end: feed a synthetic probe-log replay through the
  coordinator MQTT handler, verify archive `track` is the expected
  shape, classifier roles match expectations.
- Lifecycle: end-of-session MQTT does NOT close capture; CHARGING
  flip closes capture; 10 min watchdog closes capture.
- Card output: `session_card` derives `legs_timeline` from `track`,
  attribute dict has expected `track_first_ts` / `track_last_ts`.

### Live validation

Three real sessions before declaring v1 done:

1. A short spot mow (verify the dock-to-spot traversal is fully
   grey, the spot is fully green, the dock-return is grey).
2. A long all-areas mow with one mid-mow recharge (verify charging
   freeze is visible at dock at the correct anim time; inter-strip
   moves render as grey).
3. A rain-delay session (verify the rain-delay overlay shows, the
   animation freezes during the rain window, total animation
   duration is clamped).

## Risks

1. **`tools/rebuild_session.py` must round-trip cleanly.** The
   probe-log tool needs to produce archives indistinguishable from
   live-captured ones, or replay behaviour will diverge between
   rebuilt and native archives. Mitigation: a single source of
   truth for `append_point` + classifier — both code paths import
   from `live_map.state` / the classifier module.

2. **`task_state` per-point cost.** A 2 h session at 5 Hz yields
   ~36 000 points × ~8 bytes for the int = ~280 KB. Within
   `in_progress.json` budget. If the future point-stream grows
   additional fields (e.g., RSSI), revisit the NDJSON-sidecar
   option.

3. **Cloud rescue tolerance miscalibration.** If `tol_m = 0.6` is
   too loose, traversal arcs adjacent to mowed strips get upgraded
   to mowing. If too tight, the rescue doesn't catch re-mow loops.
   The `trail_diff.py` tests already exercise this; carry over the
   same default and the same test cases.

4. **HA disk-wear sensitivity.** The 30 s debounced cadence is
   unchanged, so no net new disk traffic. But the per-point
   payload grows incrementally — verify the JSON write stays under
   a few MB even for the worst-case 19 h session. Cap the
   in-progress payload size if needed (drop the head of `track`
   when approaching limit; rebuild at finalize via probe-log if
   exceeded).

## Acceptance criteria

- A spot mow renders dock-to-spot traversal in grey, the spot in
  green, the dock-return in grey. Last grey segment ends exactly
  where the green begins; first green ends exactly where the
  return grey begins.
- A 2 h all-areas mow with one mid-mow recharge plays back in ~36 s
  default speed. The recharge freezes the mower icon at the dock
  for the proportional share of the animation; the green polyline
  resumes from the next post-recharge point.
- A rain-delay session shows the rain-delay overlay during the
  proportional anim-time window and animation total stays under
  90 s even for 19 h sessions.
- Inter-strip repositioning during a mow renders as grey segments
  (no green stripes connecting non-adjacent mowed areas).
- Replay-speed slider scales the animation continuously across
  50×..800×; position persists across reloads.
- The card produces no console errors on any of the live-validation
  sessions or on archives lacking cloud_track.
- All existing archived sessions, after running
  `tools/rebuild_session.py`, replay correctly under the new card.

## Out of scope (defer)

- Segment-colored progress slider (mowing/charging/rain phases
  inline on the scrub bar).
- Per-cause pause icons (charging ⚡ / stuck ⛔ / fault ⚠ as graphic
  art rather than text).
- OSM-tile / real-world background variant.
- Multi-session compare overlays.
- Battery / WiFi overlays synchronized with trail head.
- Per-leg colouring by mowing mode (edge / spot / zone).
- Obstacle / AI-obstacle dots animated in at detection moment.
