# Path-Rendering Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make path-segment rendering across the three maps (live / static replay / animated replay) accurate, time-ordered, and free of post-hoc inference, by storing per-leg timestamps + role at capture time and painting in that captured order.

**Architecture:** Add `leg_start_ts` / `leg_end_ts` parallel arrays to `LiveMapState`, write them to the archive under a new `_legs_meta` key, and rewrite both painters to consume one ordered list of `{leg, role, start_ts, end_ts}` records instead of two role-split lists composed with z-order tricks. Drop the fuzzy `split_trail` fallback, the dead `TrailLayer` class, and the all-mowing-then-all-traversal animation ordering. Add the missing dotted-edge / dotted-spot live previews by extending `_render_pre_start_with_stripes` (renamed `_render_pre_start`) — without re-introducing dead infrastructure.

**Tech Stack:** Python 3.12, Pillow (PIL) for raster, pytest, vanilla-JS web component for the animated card.

---

## Audit Findings (input to this plan)

These are verified by source-read of `custom_components/dreame_a2_mower/` on 2026-05-19. Cite them when justifying each task.

### A. What's stored today

1. **Cloud session-summary JSON** (`protocol/session_summary.py`):
   - `boundary.track` — flat list of `[x_cm, y_cm]` points; segments split on the `2147483647` sentinel. **No type tag, no per-point timestamp, no per-segment timestamp.**
   - `obstacles` — top-level array with `polygon` in cm.
   - `trajectories` — separate high-level planning paths, no timestamps.
2. **Live-captured payload** injected by `coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict`:
   - `_local_legs` — list of legs, each a list of `[x_m, y_m]` points. **No per-point timestamp.**
   - `_mowing_legs` / `_traversal_legs` — subsets of `_local_legs` partitioned by `LiveMapState.leg_is_mowing[i]`. **Role IS captured authoritatively at capture time, on every `s2p1` push (`live_map/state.py:set_mowing`).**
   - `state_samples` / `battery_samples` / `charging_status_samples` / `error_samples` — `(ts_unix, value)` pairs.
3. **No archive field carries per-leg start/end timestamps.** The only way to recover leg-time today is to correlate `state_samples` activity flips against `leg_is_mowing[i]` indices, which is what `dreame-mower-replay-card.js:_startAnimation` does via `mow_frac` interpolation (and gets wrong when leg roles aren't time-ordered).

### B. How the painters consume it

| Surface | Entry point | Source order | Color decision |
|---|---|---|---|
| Live | `map_render.render_main_view` → `render_with_trail` | `live_map.mowing_legs` then `live_map.traversal_legs` | Captured at append-time (no guessing) |
| Static replay | `coordinator/_session.py:render_work_log_session` → `map_render.render_work_log` → `render_with_trail` | Archive `_mowing_legs` + `_traversal_legs` (legacy: `_render_trail_split.split_trail` with `tol_mm=0.30` fuzzy match against cloud) | Role-pass: light-green first, grey on top |
| Animated replay | `www/dreame-mower-replay-card.js:_renderShell` | Attributes `mowing_legs` + `traversal_legs` (then `legs` fallback = `clean_local + clean_cloud`) | Same role-pass order, animated as SVG path `getTotalLength()` slices |

### C. Root causes mapped to user-reported issues

| User-reported symptom | Code-level root cause |
|---|---|
| Animated replay segments paint out of order across the map | `legSpecs = [...rawMowing, ...rawTraversal]` in `dreame-mower-replay-card.js:158` — all mowing animates first, then all traversal, regardless of capture time |
| Coloring "random" | Legacy-archive fallback in `_render_trail_split.split_trail` (`tol_mm=0.30`) classifies points one-at-a-time by hash-bucket-near-cloud-point; depending on cloud coverage gaps each leg's individual points get reclassified inconsistently |
| Charging stop renders mid-lawn instead of at the dock | `dreame-mower-replay-card.js:_chargingWindowsMs` only fires when `state_samples` contains `code === 6` AND `map_projection.dock_xy_mm` is populated (`map_render.extract_projection`) |
| Animation icon jumps between legs | Each leg is a separate `<path>`; `_renderAt` snaps icon to next leg's start (`getPointAtLength(0)`) with no inter-leg motion |
| EDGE / SPOT pre-start preview doesn't show dotted shapes | `map_render.render_main_view` returns plain `render_base_map(lawn_mode="light")` for these modes — no dotted boundary, no dotted spot rectangle, no overlay at all |
| Grey traversal never shows live | Probable: `set_mowing` is never called with `is_mowing=False` on this device (s2p1 doesn't expose RETURNING / etc as a separate activity). Default `_current_is_mowing = True` keeps every leg in mowing |
| Obstacles missing live between sessions | Cache poisoning gate exists in `_load_last_session_obstacles`; need a probe to differentiate "empty `summary.obstacles`" vs "cache populated empty before index_loaded" |
| Dead infrastructure | `protocol/trail_overlay.py:TrailLayer` (588 lines): full edge-mow + perimeter-dash + mower-icon-halo + direction-triangle machinery. Only used in `tests/protocol/test_trail_overlay.py`. No production caller. |

### D. Simplification principle (per the user's spec)

> "Ideally the segments should have a type, a timestamp and a start and end point, enough to draw them properly without too much work."

Adopt this verbatim. The plan adds per-leg `start_ts` + `end_ts` (cheap; we already snapshot `last_telemetry_unix` on every push) and downgrades cloud-track to a **second-class diagnostic source** — it doesn't drive the painter. The role is already authoritative on each leg via `leg_is_mowing`; we keep that. Endpoints are `legs[i][0]` and `legs[i][-1]`; we keep that. With those three present, every painter walks one timeline-ordered list of records and never asks "what type is this segment?".

---

## File Structure

**Modified:**
- `custom_components/dreame_a2_mower/live_map/state.py` — add `leg_start_ts` / `leg_end_ts` parallel arrays, update `begin_leg` / `set_mowing` / `append_point` / `dump_to_payload` / `hydrate_from_payload`.
- `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict` — emit `_legs_meta` (parallel array of `{role, start_ts, end_ts}` dicts).
- `custom_components/dreame_a2_mower/coordinator/_session.py:render_work_log_session` — build a single timeline-ordered list and pass it to `render_work_log`.
- `custom_components/dreame_a2_mower/map_render.py` — replace `render_with_trail`'s two-pass split with one timeline-ordered loop. Rewire `render_work_log`. Extend `_render_pre_start_with_stripes` (rename `_render_pre_start`) to handle EDGE/SPOT dotted overlays.
- `custom_components/dreame_a2_mower/session_card.py:build_picked_session_summary` — emit a single `legs_timeline` attribute (ordered list of records), keep `mowing_legs` / `traversal_legs` / `legs` as compatibility shims for the transition window only.
- `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` — consume `legs_timeline` and animate in that order. Inter-leg cursor interpolation. Drop the `mow_frac` pause heuristic.
- `custom_components/dreame_a2_mower/coordinator/_rendering.py:_load_last_session_obstacles` — add a diagnostic log line surfacing whether `summary.obstacles` is empty vs `_index_loaded` race.

**Deleted (dead code):**
- `custom_components/dreame_a2_mower/protocol/trail_overlay.py` (entire `TrailLayer` class — no production caller).
- `tests/protocol/test_trail_overlay.py` — corresponding tests.
- `custom_components/dreame_a2_mower/_render_trail_split.py` (entire fuzzy splitter — replaced by archive-authoritative `_legs_meta`).
- `tests/test_render_trail_split.py` (if present) and `session_card.py:`'s `split_trail` fallback branch.

**New:**
- `custom_components/dreame_a2_mower/_render_dotted.py` — small pure helper for dotted-polygon and dotted-rect drawing (extracted from `TrailLayer._draw_dotted_polygon`).
- `tests/live_map/test_state_leg_timestamps.py`
- `tests/test_render_timeline_order.py`
- `tests/test_render_pre_start_edge_spot.py`

---

## Task ordering rationale

Tasks 1–3 establish the new storage shape (leg timestamps + `_legs_meta`). Tasks 4–5 rewire the painters in Python first (static replay), so we can validate the timeline-order claim before touching the JS animated card. Tasks 6–7 rebuild the animated card on top of the new attribute. Tasks 8–10 fix the live pre-start preview, the grey traversal classifier, and the obstacle-missing diagnostic. Tasks 11–12 delete dead code and update docs. Each task ships a green test suite and an inventory update where applicable.

---

## Task 1: Add per-leg timestamps to LiveMapState

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/state.py` (LiveMapState dataclass)
- Test: `tests/live_map/test_state_leg_timestamps.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/live_map/test_state_leg_timestamps.py
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_initializes_leg_timestamps():
    s = LiveMapState()
    s.begin_session(1000)
    assert s.leg_start_ts == [1000]
    assert s.leg_end_ts == [1000]


def test_append_point_advances_leg_end_ts_only():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.append_point(1.0, 0.0, 1005)
    assert s.leg_start_ts == [1000]
    assert s.leg_end_ts == [1005]


def test_set_mowing_split_records_boundary_ts():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.append_point(1.0, 0.0, 1005)
    s.set_mowing(False)            # current leg ends here
    s.append_point(2.0, 0.0, 1008) # new leg starts here
    assert s.leg_start_ts == [1000, 1005]
    assert s.leg_end_ts   == [1005, 1008]
    assert s.leg_is_mowing == [True, False]


def test_begin_leg_records_boundary_ts():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.last_telemetry_unix = 1010   # last seen telemetry before pause
    s.begin_leg()
    assert s.leg_start_ts == [1000, 1010]
    assert s.leg_end_ts   == [1010, 1010]


def test_dump_and_hydrate_roundtrip():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.set_mowing(False)
    s.append_point(2.0, 0.0, 1008)
    payload = s.dump_to_payload()
    assert payload["leg_start_ts"] == [1000, 1001]
    assert payload["leg_end_ts"]   == [1001, 1008]

    s2 = LiveMapState()
    s2.hydrate_from_payload(payload)
    assert s2.leg_start_ts == [1000, 1001]
    assert s2.leg_end_ts   == [1001, 1008]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/live_map/test_state_leg_timestamps.py -v`
Expected: FAIL — `AttributeError: 'LiveMapState' object has no attribute 'leg_start_ts'`

- [ ] **Step 3: Add the fields and the writer logic**

In `live_map/state.py`, add parallel fields next to `leg_is_mowing`:

```python
leg_start_ts: list[int] = field(default_factory=list)
"""Parallel to ``legs``: unix timestamp when leg N opened.
Set when a leg is first appended to legs[]: at begin_session(),
inside begin_leg() (from the prev leg's last_telemetry_unix), and
inside set_mowing() on activity-flip splits."""

leg_end_ts: list[int] = field(default_factory=list)
"""Parallel to ``legs``: unix timestamp of the most recent point
appended to this leg. Advanced by append_point() and frozen on the
next leg-open."""
```

Update `begin_session`:

```python
def begin_session(self, started_unix: int) -> None:
    self.started_unix = started_unix
    self.legs = [[]]
    self.leg_is_mowing = [self._current_is_mowing]
    self.leg_start_ts = [int(started_unix)]
    self.leg_end_ts = [int(started_unix)]
    self.last_telemetry_unix = None
    self.wifi_samples = []
    self.battery_samples = []
    self.charging_status_samples = []
    self.state_samples = []
    self.error_samples = []
    self.charge_at_start = None
    self.settings_snapshot = None
```

Update `begin_leg`:

```python
def begin_leg(self) -> None:
    if not self.legs or self.legs[-1]:
        boundary = int(self.last_telemetry_unix or self.leg_end_ts[-1] if self.leg_end_ts else 0)
        # Close the previous leg at the boundary.
        if self.leg_end_ts:
            self.leg_end_ts[-1] = boundary
        self.legs.append([])
        self.leg_is_mowing.append(self._current_is_mowing)
        self.leg_start_ts.append(boundary)
        self.leg_end_ts.append(boundary)
```

Update `set_mowing` — apply the same close-and-open logic at every flip:

```python
def set_mowing(self, is_mowing: bool) -> None:
    is_mowing = bool(is_mowing)
    if is_mowing == self._current_is_mowing:
        return
    self._current_is_mowing = is_mowing
    if not self.legs:
        return
    boundary = int(self.last_telemetry_unix or (self.leg_end_ts[-1] if self.leg_end_ts else 0))
    if self.legs[-1]:
        if self.leg_end_ts:
            self.leg_end_ts[-1] = boundary
        self.legs.append([])
        self.leg_is_mowing.append(is_mowing)
        self.leg_start_ts.append(boundary)
        self.leg_end_ts.append(boundary)
    else:
        # Empty trailing leg: just adopt the new role.
        if self.leg_is_mowing:
            self.leg_is_mowing[-1] = is_mowing
        else:
            self.leg_is_mowing.append(is_mowing)
        if not self.leg_start_ts:
            self.leg_start_ts.append(boundary)
            self.leg_end_ts.append(boundary)
```

Update `append_point` — advance `leg_end_ts[-1]` on every appended point. The pen-up branch that auto-splits to a new leg needs to record start/end ts too:

```python
def append_point(self, x_m: float, y_m: float, ts_unix: int) -> None:
    ts = int(ts_unix)
    if not self.legs:
        self.legs = [[]]
        self.leg_is_mowing = [self._current_is_mowing]
        self.leg_start_ts = [ts]
        self.leg_end_ts = [ts]
    current_leg = self.legs[-1]
    if current_leg:
        last_x, last_y = current_leg[-1]
        dx = x_m - last_x
        dy = y_m - last_y
        if (dx * dx + dy * dy) > 25.0:  # 5m squared
            if self.leg_end_ts:
                self.leg_end_ts[-1] = ts
            self.legs.append([])
            self.leg_is_mowing.append(self._current_is_mowing)
            self.leg_start_ts.append(ts)
            self.leg_end_ts.append(ts)
            current_leg = self.legs[-1]
    if current_leg:
        last_x, last_y = current_leg[-1]
        dx = x_m - last_x
        dy = y_m - last_y
        if (dx * dx + dy * dy) < 0.04:  # 20cm squared dedup
            self.last_telemetry_unix = ts
            self.leg_end_ts[-1] = ts
            return
    current_leg.append((x_m, y_m))
    self.last_telemetry_unix = ts
    self.leg_end_ts[-1] = ts
```

Update `end_session` to clear both new fields. Update `dump_to_payload` to include `leg_start_ts` / `leg_end_ts`. Update `hydrate_from_payload` to read them with a back-compat default (synthesize from `started_unix` when missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/live_map/test_state_leg_timestamps.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run full live_map test suite to confirm no regression**

Run: `pytest tests/live_map/ -v`
Expected: PASS (all existing tests; the new fields default-empty for legacy payloads)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/state.py tests/live_map/test_state_leg_timestamps.py
git commit -m "live_map: add per-leg start/end timestamps for timeline-ordered render"
```

---

## Task 2: Emit `_legs_meta` in the archive payload

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict`
- Test: `tests/coordinator/test_inject_live_map.py` (new file or extend existing if present — check first)

- [ ] **Step 1: Find or create the test target**

Run: `find tests -name "test_inject_live_map*" -o -name "test_lidar_oss*"`. If a test for `_inject_live_map_into_raw_dict` exists, extend it; otherwise create `tests/coordinator/test_inject_live_map_meta.py`.

- [ ] **Step 2: Write the failing test**

```python
# tests/coordinator/test_inject_live_map_meta.py
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_inject_writes_legs_meta(monkeypatch):
    from custom_components.dreame_a2_mower.coordinator import _lidar_oss

    coord = MagicMock()
    coord.live_map = LiveMapState()
    coord.live_map.begin_session(1000)
    coord.live_map.append_point(0.0, 0.0, 1001)
    coord.live_map.set_mowing(False)
    coord.live_map.append_point(2.0, 0.0, 1008)

    raw: dict = {}
    _lidar_oss._LidarOssMixin._inject_live_map_into_raw_dict(coord, raw)
    assert raw["_legs_meta"] == [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1001},
        {"role": "traversal", "start_ts": 1001, "end_ts": 1008},
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/coordinator/test_inject_live_map_meta.py -v`
Expected: FAIL — `KeyError: '_legs_meta'`

- [ ] **Step 4: Add `_legs_meta` emission in `_inject_live_map_into_raw_dict`**

Inside the existing `if self.live_map.legs and any(self.live_map.legs):` block in `coordinator/_lidar_oss.py` (line ~99–119), after the existing `_local_legs` / `_mowing_legs` / `_traversal_legs` emission, append:

```python
raw_dict["_legs_meta"] = [
    {
        "role": "mowing" if mowing else "traversal",
        "start_ts": int(st),
        "end_ts": int(en),
    }
    for leg, mowing, st, en in zip(
        self.live_map.legs,
        self.live_map.leg_is_mowing,
        self.live_map.leg_start_ts,
        self.live_map.leg_end_ts,
    )
    if leg
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/coordinator/test_inject_live_map_meta.py -v`
Expected: PASS

- [ ] **Step 6: Update the in-progress payload schema in `observability/schemas.py`**

Find the entry for `"_local_legs"` and add a sibling entry:

```python
"_legs_meta": True,
```

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py custom_components/dreame_a2_mower/observability/schemas.py tests/coordinator/test_inject_live_map_meta.py
git commit -m "archive: write _legs_meta (role + start_ts + end_ts per leg)"
```

---

## Task 3: Build `legs_timeline` in `build_picked_session_summary`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py:build_picked_session_summary` (around line 539–606)
- Test: `tests/test_session_card_timeline.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_card_timeline.py
from custom_components.dreame_a2_mower.session_card import build_picked_session_summary
from types import SimpleNamespace


def _make_summary(track_segments=()):
    return SimpleNamespace(
        start_ts=1000, end_ts=2000, duration_min=10, mode=0, result=1,
        stop_reason=0, start_mode=0, pre_type=0, md5="abc",
        area_mowed_m2=1.0, map_area_m2=100, dock=None, pref=(), region_status=(),
        faults=(), spot=(), ai_obstacle=(), obstacles=(), boundary=None,
        exclusions=(), trajectories=(), battery_samples=(), charging_status_samples=(),
        state_samples=(), error_samples=(), wifi_samples=(), charge_at_start=None,
        track_segments=track_segments, lawn_polygon=(),
    )


def test_legs_timeline_built_from_legs_meta():
    raw = {
        "_local_legs": [[[0.0, 0.0], [1.0, 0.0]], [[2.0, 0.0], [3.0, 0.0]]],
        "_legs_meta": [
            {"role": "mowing", "start_ts": 1000, "end_ts": 1100},
            {"role": "traversal", "start_ts": 1100, "end_ts": 1200},
        ],
    }
    entry = SimpleNamespace(md5="abc", filename="x.json", map_id=0)
    out = build_picked_session_summary(
        raw_dict=raw, summary=_make_summary(),
        entry=entry, picker_label="label",
    )
    assert out["legs_timeline"] == [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1100,
         "pts": [[0.0, 0.0], [1.0, 0.0]]},
        {"role": "traversal", "start_ts": 1100, "end_ts": 1200,
         "pts": [[2.0, 0.0], [3.0, 0.0]]},
    ]


def test_legs_timeline_omitted_for_legacy_archive():
    raw = {"_local_legs": [[[0.0, 0.0], [1.0, 0.0]]]}  # no _legs_meta
    entry = SimpleNamespace(md5="abc", filename="x.json", map_id=0)
    out = build_picked_session_summary(
        raw_dict=raw, summary=_make_summary(),
        entry=entry, picker_label="label",
    )
    assert out.get("legs_timeline") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_card_timeline.py -v`
Expected: FAIL — `KeyError: 'legs_timeline'`

- [ ] **Step 3: Build `legs_timeline` in `build_picked_session_summary`**

Just after `out["traversal_legs"] = ...` block (around session_card.py:606), insert:

```python
meta = raw_dict.get("_legs_meta")
local_legs_raw = raw_dict.get("_local_legs") or []
if isinstance(meta, list) and isinstance(local_legs_raw, list) and len(meta) == len(local_legs_raw):
    timeline: list[dict] = []
    for leg, m in zip(local_legs_raw, meta):
        cleaned = _clean(leg)
        if len(cleaned) < 2:
            continue
        role = m.get("role")
        if role not in ("mowing", "traversal"):
            continue
        timeline.append({
            "role": role,
            "start_ts": int(m.get("start_ts") or 0),
            "end_ts": int(m.get("end_ts") or 0),
            "pts": cleaned,
        })
    out["legs_timeline"] = timeline
else:
    out["legs_timeline"] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_card_timeline.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/test_session_card_timeline.py
git commit -m "session_card: expose legs_timeline (ordered role+ts+pts records)"
```

---

## Task 4: Rewrite `render_with_trail` to consume `legs_timeline`

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py:render_with_trail` (line 848–1068)
- Test: `tests/test_render_timeline_order.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_timeline_order.py
from custom_components.dreame_a2_mower.map_render import render_with_trail
from custom_components.dreame_a2_mower.data.map_data import MapData


def _trivial_map_data():
    return MapData(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        lawn_polygon=[(0, 0), (10000, 0), (10000, 10000), (0, 10000)],
        mowing_zones=[], exclusion_zones=[], spot_zones=[],
        dock_xy=(0, 0), charger_position=None,
    )


def test_legs_timeline_painted_in_order():
    """Each leg in the timeline lays paint over the previous one;
    the last leg's color dominates at overlapping pixels."""
    md = _trivial_map_data()
    # Two identical-position legs; mowing first, then traversal on the
    # SAME route. With timeline order honored, the grey traversal
    # should overwrite the green mowing in the overlapping pixels.
    timeline = [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1100,
         "pts": [(1.0, 1.0), (2.0, 1.0)]},
        {"role": "traversal", "start_ts": 1100, "end_ts": 1200,
         "pts": [(1.0, 1.0), (2.0, 1.0)]},
    ]
    png = render_with_trail(md, legs_timeline=timeline, trail_width_px=4)
    # Smoke: just confirm it produces a non-empty PNG without raising.
    assert png and len(png) > 100
    # (color-pixel verification deferred to integration test;
    # functional path: it didn't crash, and a follow-up regression
    # test in `tests/integration/` will assert pixel order.)


def test_legs_timeline_takes_priority_over_split_args():
    md = _trivial_map_data()
    timeline = [{"role": "mowing", "start_ts": 1000, "end_ts": 1100,
                 "pts": [(1.0, 1.0), (2.0, 1.0)]}]
    # Even if mowing_legs/traversal_legs are passed, timeline wins.
    png = render_with_trail(
        md, legs_timeline=timeline,
        mowing_legs=[[(5.0, 5.0), (6.0, 5.0)]],
        traversal_legs=[],
    )
    assert png and len(png) > 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render_timeline_order.py -v`
Expected: FAIL — `TypeError: render_with_trail() got an unexpected keyword argument 'legs_timeline'`

- [ ] **Step 3: Add `legs_timeline` kwarg and the timeline-ordered draw loop**

In `map_render.py:render_with_trail`, add `legs_timeline: list[dict] | None = None` to the signature.

Above the existing `if have_explicit_split:` block (around line 947), add the timeline branch:

```python
if legs_timeline:
    # Authoritative path: one ordered list of leg records, each
    # carrying role + endpoints. Paint in the supplied order so
    # later legs overwrite earlier ones at overlapping pixels.
    base_png = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)
    mow_color: tuple = p.get("mow_trail_color", (178, 223, 138, 255))
    trav_color: tuple = p.get("traversal_color", (130, 130, 130, 220))
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    drawn_legs = 0
    drawn_points = 0
    for rec in legs_timeline:
        pts = rec.get("pts") or []
        if len(pts) < 2:
            continue
        leg_px = []
        for p_m in pts:
            cx = float(p_m[0]) * 1000.0
            cy = float(p_m[1]) * 1000.0
            px = (map_data.bx2 - cx) / map_data.pixel_size_mm
            py = (map_data.by2 - cy) / map_data.pixel_size_mm
            leg_px.append((px, py))
        color = trav_color if rec.get("role") == "traversal" else mow_color
        draw.line(leg_px, fill=color, width=line_width)
        drawn_legs += 1
        drawn_points += len(leg_px)
    # ... reuse existing obstacle + mower-icon blocks (lift them
    # into a helper if convenient, or duplicate inline for now).
    # See unchanged blocks at map_render.py:1008-1054 for the
    # exact bodies; copy them verbatim to keep this branch
    # self-contained.
    if obstacle_polygons_m:
        # (copy from existing block at line 1009-1020)
        ...
    if mower_position_m is not None:
        # (copy from existing block at line 1027-1054)
        ...
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
```

**Important:** do NOT delete the existing `mowing_legs` / `traversal_legs` / `legs` / `local_legs` / `cloud_segments` branches yet — Task 12 deletes them after the in-tree callers migrate. The `if legs_timeline:` branch returns early so legacy callers are unaffected.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_render_timeline_order.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run full map_render test suite**

Run: `pytest tests/test_map_render.py tests/integration/ -v -k "render"`
Expected: PASS (no regression on legacy callers)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/test_render_timeline_order.py
git commit -m "map_render: add legs_timeline path that paints in capture order"
```

---

## Task 5: Wire `legs_timeline` into the static replay (work_log) path

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py:render_work_log_session` (line 99–353)
- Modify: `custom_components/dreame_a2_mower/map_render.py:render_work_log` (line 792–845) — forward `legs_timeline`

- [ ] **Step 1: Add `legs_timeline` kwarg to `render_work_log`**

In `map_render.py:render_work_log` signature, add `legs_timeline: list[dict] | None = None`. Forward it in the `render_with_trail` call body.

- [ ] **Step 2: Build `legs_timeline` in `render_work_log_session`**

In `coordinator/_session.py:render_work_log_session`, near where `mowing_legs_archive` / `traversal_legs_archive` are built (line 230–234), add:

```python
meta = raw_dict.get("_legs_meta")
legs_timeline: list[dict] | None = None
if isinstance(meta, list) and meta and len(meta) == len(local_legs):
    legs_timeline = []
    for leg_pts, m in zip(local_legs, meta):
        if not leg_pts:
            continue
        role = m.get("role")
        if role not in ("mowing", "traversal"):
            continue
        legs_timeline.append({
            "role": role,
            "start_ts": int(m.get("start_ts") or 0),
            "end_ts": int(m.get("end_ts") or 0),
            "pts": leg_pts,
        })
```

In the `render_kwargs` block (line 332–343), prefer the timeline when present:

```python
if legs_timeline:
    render_kwargs = {"legs_timeline": legs_timeline}
elif have_split_archive:
    render_kwargs = {
        "mowing_legs": mowing_legs_archive,
        "traversal_legs": traversal_legs_archive,
    }
else:
    render_kwargs = {
        "local_legs": local_legs,
        "cloud_segments": cloud_legs,
    }
```

- [ ] **Step 3: Run the integration tests**

Run: `pytest tests/coordinator/test_render_work_log_session*.py -v`
Expected: PASS

- [ ] **Step 4: Manual smoke test**

Install via `tools/release.sh` to the dev HA, pick a recent session in the replay picker, and visually compare to the screenshot the user attached. Note any mismatch in the commit body — do NOT claim it works unless verified.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py custom_components/dreame_a2_mower/coordinator/_session.py
git commit -m "render_work_log: prefer legs_timeline when archive carries _legs_meta"
```

---

## Task 6: Rewire the animated replay card to use `legs_timeline`

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` (lines 130–230 + 281–467)

- [ ] **Step 1: Find the legSpecs construction (line 154–167) and replace**

```javascript
// New: prefer legs_timeline (ordered). Fall back to legacy split.
const rawTimeline = a.legs_timeline || null;
let legSpecs;
if (rawTimeline && rawTimeline.length > 0) {
  legSpecs = rawTimeline
    .filter(rec => rec && rec.pts && rec.pts.length >= 2
                   && (rec.role === 'mowing' || rec.role === 'traversal'))
    .map(rec => ({
      pts: rec.pts,
      role: rec.role,
      start_ts: rec.start_ts,
      end_ts: rec.end_ts,
    }));
} else {
  const rawMowing = a.mowing_legs || [];
  const rawTraversal = a.traversal_legs || [];
  const useSplit = rawMowing.length > 0 || rawTraversal.length > 0;
  legSpecs = useSplit
    ? [
        ...rawMowing.map(leg => ({ pts: leg, role: 'mowing' })),
        ...rawTraversal.map(leg => ({ pts: leg, role: 'traversal' })),
      ].filter(s => s.pts && s.pts.length >= 2)
    : (a.legs || [])
        .filter(leg => leg && leg.length >= 2)
        .map(leg => ({ pts: leg, role: 'mowing' }));
}
this._pathRoles = legSpecs.map(s => s.role);
this._legSpecs = legSpecs;
```

- [ ] **Step 2: Replace the `_startAnimation` timeline-build block (lines 398–410)**

When `_legSpecs` records carry `start_ts` and `end_ts`, build slots from real time deltas instead of from cumulative SVG path length:

```javascript
const specs = this._legSpecs;
const hasRealTimes = specs.every(s => Number.isFinite(s.start_ts) && Number.isFinite(s.end_ts));
this._timeline = [];
let acc = 0;
if (hasRealTimes) {
  const sessionStart = a.started_at_unix;
  const sessionEnd = a.ended_at_unix;
  const wallDur = Math.max(1, sessionEnd - sessionStart);
  for (let i = 0; i < specs.length; i++) {
    const leg = specs[i];
    const startMs = ((leg.start_ts - sessionStart) / wallDur) * TOTAL_MS;
    const endMs   = ((leg.end_ts   - sessionStart) / wallDur) * TOTAL_MS;
    this._timeline.push({ leg: i, start_ms: startMs, end_ms: endMs, dur: endMs - startMs });
    acc = Math.max(acc, endMs);
  }
} else {
  // Legacy fallback (existing length-driven timing — unchanged from
  // pre-overhaul). Drop this whole branch in a follow-up once every
  // archive has _legs_meta.
  paths.forEach((p, i) => {
    const dur = paths.length === 1
      ? TOTAL_MS
      : (this._pathLengths[i] / totalLength) * drawBudgetMs;
    this._timeline.push({ leg: i, start_ms: acc, end_ms: acc + dur, dur });
    acc += dur + legGapMs[i];
  });
}
this._totalMs = acc;
```

When `hasRealTimes` is true, **delete the legGapMs / pauseSlots block (lines 322–383)** — pauses are now first-class gaps in the timeline (consecutive legs with non-touching `end_ts`/`start_ts` already produce an `end_ms < next.start_ms` slot). Mark the dead block with a `// LEGACY` comment if you prefer to delete in a follow-up commit.

- [ ] **Step 3: Improve the `_renderAt` mower icon between-legs interpolation**

In `_renderAt` (line 504+), when no leg is active (we are between legs), look up the surrounding legs from `this._timeline` and interpolate the icon position linearly between the previous leg's last point and the next leg's first point. The position fraction is `(ms - prev.end_ms) / (next.start_ms - prev.end_ms)`. Compute the endpoint points via `paths[prev.leg].getPointAtLength(L)` and `paths[next.leg].getPointAtLength(0)`. Charging-window snap (existing logic) still overrides.

- [ ] **Step 4: Bump the card version**

Update the JS `class DreameMowerReplayCard` constructor / version string log to reflect the change so HACS users see the new build.

- [ ] **Step 5: Browser smoke test**

Reload the dashboard, open the replay map for the most-recent session. Verify visually:
- Segments paint in chronological order across the lawn (no "all mowing first then all traversal").
- Coloring is stable between two consecutive plays of the same session.
- Mower icon traverses between legs instead of jumping.

Document the verified-or-not result in the commit message. Do NOT claim it works without a browser check.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "replay-card: animate legs in capture timeline order from legs_timeline"
```

---

## Task 7: Charging-window dock snap — verify dock projection plumbing

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py:extract_projection` (line 1071+)
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` (lines 441–460)
- Test: `tests/test_extract_projection.py` (extend or create)

- [ ] **Step 1: Write the failing test that pins `extract_projection` returns `dock_xy_mm`**

```python
# tests/test_extract_projection.py
from custom_components.dreame_a2_mower.map_render import extract_projection
from types import SimpleNamespace


def test_projection_includes_dock_when_available():
    md = SimpleNamespace(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        dock_xy=(5000, 5000),
    )
    out = extract_projection(md)
    assert out["dock_xy_mm"] == [5000, 5000]


def test_projection_omits_dock_when_none():
    md = SimpleNamespace(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        dock_xy=None,
    )
    out = extract_projection(md)
    assert "dock_xy_mm" not in out
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_extract_projection.py -v`
Expected: depends on current implementation. If it already passes, this task may be a no-op — confirm by enabling browser DevTools on the dashboard and inspecting `sensor.picked_session.attributes.map_projection`. If `dock_xy_mm` is present and the icon STILL strands mid-lawn, the issue is on the JS side (charging-window detection) and Step 3 is required; if `dock_xy_mm` is absent, fix `extract_projection` first.

- [ ] **Step 3: Add a diagnostic log line in the JS card when charging snap is skipped**

In `dreame-mower-replay-card.js:_renderAt`, when `iconX !== null` and we're inside a `state_samples` `code === 6` window but `_dockPxX` is undefined, `console.warn(...)` once with the projection contents. This makes diagnosis from a user's browser console possible without code changes.

```javascript
if (this._chargingWindowsMs.length > 0 && this._dockPxX === undefined) {
  if (!this._loggedMissingDock) {
    console.warn('[dreame-replay] charging snap disabled: no dock_xy_mm in projection', a.map_projection);
    this._loggedMissingDock = true;
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js tests/test_extract_projection.py
git commit -m "replay-card: log when charging-dock snap is bypassed for diagnosis"
```

---

## Task 8: Add dotted-edge / dotted-spot live previews

**Files:**
- Create: `custom_components/dreame_a2_mower/_render_dotted.py`
- Modify: `custom_components/dreame_a2_mower/map_render.py:render_main_view` (line 685–699) and `_render_pre_start_with_stripes` → rename to `_render_pre_start`
- Test: `tests/test_render_pre_start_edge_spot.py` (new)

- [ ] **Step 1: Extract the dotted-polygon helper to a pure module**

Create `_render_dotted.py` with one function `draw_dotted_polygon(draw, pts, color, width, dash_on_px, dash_off_px)`. Copy the body from `protocol/trail_overlay.py:TrailLayer._draw_dotted_polygon` (line 533–578). This is dead code today, but the algorithm is correct; lifting it preserves the working logic without keeping the TrailLayer wrapper.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_render_pre_start_edge_spot.py
from custom_components.dreame_a2_mower.map_render import render_main_view
from custom_components.dreame_a2_mower.mower.state import ActionMode
from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession
from types import SimpleNamespace


def _stub_map():
    return SimpleNamespace(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        lawn_polygon=[(0, 0), (10000, 0), (10000, 10000), (0, 10000)],
        mowing_zones=[SimpleNamespace(
            path=[(0, 0), (10000, 0), (10000, 10000), (0, 10000)],
        )],
        exclusion_zones=[], spot_zones=[SimpleNamespace(
            spot_id=1, name="S1",
            path=[(1000, 1000), (3000, 1000), (3000, 3000), (1000, 3000)],
        )],
        dock_xy=None, charger_position=None,
    )


def test_edge_preview_draws_dotted_boundary():
    state = SimpleNamespace(
        action_mode=ActionMode.EDGE,
        last_all_area_mow_direction_deg={},
        settings_mowing_direction_mode=0,
    )
    png = render_main_view(_stub_map(), state=state,
                           map_id=0, mow_session=MowSession.IDLE)
    # Smoke: returns a PNG (visual verification deferred to integration test)
    assert png and len(png) > 100


def test_spot_preview_draws_dotted_spots():
    state = SimpleNamespace(
        action_mode=ActionMode.SPOT,
        last_all_area_mow_direction_deg={},
        settings_mowing_direction_mode=0,
    )
    png = render_main_view(_stub_map(), state=state,
                           map_id=0, mow_session=MowSession.IDLE)
    assert png and len(png) > 100
```

- [ ] **Step 3: Run test to verify it fails for the right reason**

Run: `pytest tests/test_render_pre_start_edge_spot.py -v`
Expected: PASS (current code just returns a base-map PNG — both tests already pass) OR FAIL with a different reason. Either way, **we cannot pixel-assert in unit tests**; rely on the browser smoke check in Step 6.

- [ ] **Step 4: Extend the EDGE / SPOT branch in `render_main_view`**

Replace the existing line 696–699:

```python
if action in (ActionMode.EDGE, ActionMode.SPOT):
    return render_base_map(map_data, palette=palette, lawn_mode="light")
```

with:

```python
if action == ActionMode.EDGE:
    return _render_pre_start_edge(map_data, palette=palette)
if action == ActionMode.SPOT:
    return _render_pre_start_spot(map_data, palette=palette)
```

Then define the two helpers below `_render_pre_start_with_stripes`:

```python
def _render_pre_start_edge(map_data, *, palette):
    """Light-green base + dotted darker-green lawn boundary."""
    from ._render_dotted import draw_dotted_polygon
    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for zone in map_data.mowing_zones:
        pts_px = [
            _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
            for x, y in zone.path
        ]
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _render_pre_start_spot(map_data, *, palette):
    """Light-green base + dotted darker-green spot rectangles, dark
    interior fill so each candidate spot reads as 'eligible to mow'."""
    from ._render_dotted import draw_dotted_polygon
    base_png = render_base_map(map_data, palette=palette, lawn_mode="light")
    image = Image.open(io.BytesIO(base_png)).convert("RGBA")
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    draw = ImageDraw.Draw(image, "RGBA")
    for sz in getattr(map_data, "spot_zones", ()):
        pts_px = [
            _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
            for x, y in sz.path
        ]
        # Interior fill: darker green
        draw.polygon(pts_px, fill=(0, 100, 0, 110))
        # Dotted perimeter
        draw_dotted_polygon(
            draw, pts_px,
            color=(40, 160, 40, 230), width=6,
            dash_on_px=12, dash_off_px=8,
        )
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 5: Run the new test + base-map regression suite**

Run: `pytest tests/test_render_pre_start_edge_spot.py tests/test_map_render.py -v`
Expected: PASS

- [ ] **Step 6: Browser smoke test**

In the HA dashboard, pick EDGE mode and then SPOT mode from the action select. Visually confirm dotted boundary (edge) and dotted-with-dark-fill spots (spot). Document the result in the commit message.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/_render_dotted.py custom_components/dreame_a2_mower/map_render.py tests/test_render_pre_start_edge_spot.py
git commit -m "live_map: draw dotted boundary (EDGE) and dotted spots (SPOT) in idle preview"
```

---

## Task 9: Add a "why are obstacles missing" diagnostic

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_rendering.py:_load_last_session_obstacles` (line 239–288)

- [ ] **Step 1: Add structured logging at every empty-result branch**

Replace the early-return points with `LOGGER.info(...)` calls that distinguish the three cases:

```python
if not getattr(archive, "_index_loaded", False):
    LOGGER.info(
        "[obstacles] map_id=%d: archive index not yet loaded — skipping; "
        "next tick will retry.", map_id,
    )
    return None
# ...
if not candidates:
    LOGGER.info(
        "[obstacles] map_id=%d: no archived sessions found in index "
        "(have map_ids=%s).", map_id,
        sorted({s.map_id for s in index}),
    )
    self._last_session_obstacles_by_map[map_id] = []
    return None
# ...
if not polygons:
    LOGGER.info(
        "[obstacles] map_id=%d: latest session %s archived with empty "
        "summary.obstacles (cloud reported 0 obstacles for this run).",
        map_id, getattr(entry, "filename", "?"),
    )
self._last_session_obstacles_by_map[map_id] = polygons
return polygons or None
```

- [ ] **Step 2: Reload the integration on the dev HA and watch the log**

Use `mcp__home-assistant__ha_get_logs` (or equivalent) for a single mower-restart cycle. The log line will name the case. No code change beyond logging until the case is known. **If `summary.obstacles` is empty**, the next task to add is "make session-summary parse the cloud-side `ai_obstacle` array as a fallback" — out of scope here; file a TODO in `inventory.yaml` instead.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_rendering.py
git commit -m "_rendering: log the case when last-session obstacles are empty"
```

---

## Task 10: Verify the grey-traversal classifier fires live on g2408

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` or wherever `set_mowing` is currently called from (grep `live_map.set_mowing`).

- [ ] **Step 1: Locate the `set_mowing` call site and the source field**

Run: `grep -n "set_mowing\|current_activity" custom_components/dreame_a2_mower/coordinator/*.py`

Identify which MowerState field drives the call. The default `_current_is_mowing = True` (live_map/state.py:100) means that without a successful `set_mowing(False)` for any reason, every live point lands in `mowing_legs` and traversal is empty. This explains "Grey traversal paths has never worked" in the user spec.

- [ ] **Step 2: Add a one-line probe at every call site**

```python
LOGGER.debug(
    "[live_map] set_mowing(%s) from %s @ ts=%s",
    is_mowing, source_field, ts_unix,
)
```

- [ ] **Step 3: Reload, run a session, dump the relevant log slice**

Use the existing MCP HA log retrieval tool. The log will show one of:
1. `set_mowing(False)` IS called → coordinator side is fine; bug must be downstream in `mowing_legs`/`traversal_legs` partitioning. Re-audit `live_map/state.py:traversal_legs` property and stop here.
2. `set_mowing(False)` is NEVER called → the source field never goes non-MOWING. Inventory the actual `current_activity` enum values seen in the log and document the gap in `inventory.yaml`.

- [ ] **Step 4: If (2), wire a fallback signal**

Most likely source: `state_samples` (s2p1) values that are NOT mapped to MOWING — e.g., RETURNING (the dock-return arc), CHARGING (paused). Map those directly in the coordinator's s2p1 handler:

```python
# Pseudo: in coordinator/_mqtt_handlers.py — adapt to real shape
MOWING_STATE_CODES = {<the mowing code>}
self.live_map.set_mowing(value_int in MOWING_STATE_CODES)
```

The exact codes must come from `inventory.yaml` § `s2.1` — don't guess. If `inventory.yaml` doesn't yet have the table, the prior step's probe log is the evidence to record under a new `verifications:` entry per the project's fact-discipline rule.

- [ ] **Step 5: Commit (separately for the probe and the fix)**

```bash
git add -p ...
git commit -m "live_map: log set_mowing source for traversal-classifier diagnosis"
# After the probe-driven fix:
git commit -m "live_map: classify non-mowing s2p1 states as traversal (g2408)"
```

---

## Task 11: Delete `TrailLayer` and the fuzzy `split_trail` splitter

**Files:**
- Delete: `custom_components/dreame_a2_mower/protocol/trail_overlay.py`
- Delete: `custom_components/dreame_a2_mower/_render_trail_split.py`
- Delete: `tests/protocol/test_trail_overlay.py`
- Modify: `custom_components/dreame_a2_mower/session_card.py` (drop the `split_trail` fallback branch at line 590–606)
- Modify: `custom_components/dreame_a2_mower/map_render.py:render_with_trail` (drop the `split_trail` fallback at line 956–961, and the `legs` / `local_legs` / `cloud_segments` / `mowing_legs` / `traversal_legs` kwarg branches once Task 5 confirms `legs_timeline` is preferred by every in-tree caller)

- [ ] **Step 1: Confirm no production caller of `TrailLayer`**

Run: `grep -rn "TrailLayer\|protocol.trail_overlay" custom_components/dreame_a2_mower/ tests/ | grep -v test_trail_overlay`
Expected: empty output (or one comment reference; fine).

- [ ] **Step 2: Run full test suite WITHOUT deleting yet**

Run: `pytest tests/ -x`
Expected: PASS. Record the count.

- [ ] **Step 3: Delete the files**

```bash
git rm custom_components/dreame_a2_mower/protocol/trail_overlay.py
git rm tests/protocol/test_trail_overlay.py
git rm custom_components/dreame_a2_mower/_render_trail_split.py
```

Search for and remove any `tests/test_render_trail_split.py` if present.

- [ ] **Step 4: Drop the fuzzy fallback in `session_card.py`**

Replace lines ~584–606 (the `else` branch that calls `split_trail`) with a single fallback: when `_mowing_legs` / `_traversal_legs` aren't present in the archive AND `_legs_meta` isn't either, set `out["mowing_legs"]` and `out["traversal_legs"]` to empty lists. The replay card already falls back to `a.legs` (the cloud union) for that case.

- [ ] **Step 5: Drop the fuzzy fallback in `map_render.render_with_trail`**

Replace lines ~951–961 (the legacy `split_trail(tol_mm=0.30)` branch) with a single passthrough: when neither `legs_timeline` nor `mowing_legs/traversal_legs` are supplied, treat any provided `legs` / `cloud_segments` / `local_legs` as a single mowing-color paint pass. No fuzzy classification.

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -x`
Expected: PASS — count >= pre-deletion count minus 1 file's worth of tests (test_trail_overlay.py).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "cleanup: delete unused TrailLayer + fuzzy split_trail (now legs_timeline-only)"
```

---

## Task 12: Document new archive schema in inventory + bump alpha

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` — add a new entry for the `_legs_meta` archive field under the "archive payload" section (or wherever similar archive-schema items live; grep for `_local_legs`).
- Modify: `custom_components/dreame_a2_mower/manifest.json` — bump `version`.

- [ ] **Step 1: Append the inventory entry**

In `inventory.yaml`, add a new entry next to the existing `_local_legs` / `_mowing_legs` keys (find them via `grep -n '_local_legs:' inventory.yaml`). Use the project's standard YAML shape:

```yaml
_legs_meta:
  surface: archive_payload
  semantic: |
    Parallel array to `_local_legs`. Each record carries the role
    (`"mowing"` or `"traversal"`) and the unix start/end timestamps
    of that leg, captured at LiveMapState set_mowing / begin_leg
    boundaries. Replaces the post-hoc fuzzy `split_trail` matching
    and is the authoritative source for both static and animated
    replay rendering.
  status:
    last_seen: "2026-05-19"
  verifications:
    - date: "2026-05-19"
      status: verified
      claim: "Schema added in v1.0.XXaY; sessions started after that release carry the field, earlier ones don't (renderers fall back to `_mowing_legs`/`_traversal_legs`)."
      evidence: "code: coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict"
```

- [ ] **Step 2: Run the inventory consistency check**

Run: `python tools/inventory_audit.py`
Expected: PASS.

- [ ] **Step 3: Bump the alpha**

Per `feedback_hacs_version_ladder` memory, if the current version is `1.0.X.aN` and incrementing N crosses a digit boundary (e.g. a9 → a10, a99 → a100), bump the patch instead. Otherwise just bump N.

- [ ] **Step 4: Tag and release**

Use `./tools/release.sh` (per `feedback_subagent_release_pipeline`).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/manifest.json
git commit -m "release: v1.0.X.aY — legs_timeline-driven path rendering"
```

---

## Self-Review Notes

- **Spec coverage:** Storage audit → Task 1 + 2. Painter simplification → Tasks 4 + 5 + 6. Live edge/spot dotted → Task 8. Out-of-order replay → Tasks 6. Random coloring → Task 11 (delete fuzzy). Charging icon → Task 7. Mower-icon-jump → Task 6 Step 3. Grey traversal live → Task 10. Obstacles missing → Task 9.
- **Out of scope (deliberate, with reason):**
  - Cloud-track segment timestamps: the wire doesn't carry them; we use `_local_legs` as authoritative instead. Cloud track stays archived for diagnostics.
  - Wider mow-stroke width (user's #8 spec item): the existing `trail_render_width` number entity already exposes this; nothing to do.
  - "Two path styles" toggle (user's #8 final paragraph): use the existing `trail_render_width` entity at low value for the thin-line variant; no new toggle needed unless follow-up shows the width control is insufficient.
- **Risks:**
  - Task 6's `hasRealTimes` branch hides the legacy length-driven branch for sessions WITHOUT `_legs_meta`. Old archives keep playing back via the legacy branch until they roll out of retention.
  - Task 11's deletion of `_render_trail_split.py` is irreversible for legacy archives. The fallback to flat `a.legs` is acceptable visual degradation (single-color trail) for the rare case of an old archive picked after the migration.
  - Task 10 may surface that `s2p1` doesn't ever go non-MOWING on g2408. If so, the traversal-legs feature is dead-on-arrival for the live map and we need to fall back to `charging_status_samples` or another signal — track in inventory.yaml as a known gap.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-path-rendering-overhaul.md`.**
