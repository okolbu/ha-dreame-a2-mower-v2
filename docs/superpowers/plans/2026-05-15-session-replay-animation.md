# Session Replay Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional animated replay of an archived mowing session to the Sessions tab — trail drawn segment-by-segment over the base map, ≤ 30 s total playback, proportional freezes during non-mowing intervals. Toggle between current static work-log image and the new animation.

**Architecture:** Two-sided change. The Python integration adds four pure-additive attributes to `sensor.dreame_a2_mower_picked_session` (`legs`, `state_samples`, `map_projection`, `base_map_image_url`). A new single-file custom Lovelace card co-distributed under `custom_components/dreame_a2_mower/www/` reads those attributes and renders an SVG trail animation with `stroke-dasharray` + Web Animations API. Dashboard YAML adds an `input_boolean` toggle and a conditional pair (static-camera vs custom-card) on the Sessions tab.

**Tech Stack:** Python 3.13 + Home Assistant integration framework (`session_card.build_picked_session_summary`, `coordinator/_session.py`, `map_render.py`); single-file ES6 module exposing a `customElements.define`'d `HTMLElement` with shadow DOM; existing static-paths registration in `__init__.py:130-155` already serves `www/`; SCP-deploy for the Lovelace YAML.

---

## File Structure

**Python (integration side):**

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/map_render.py` | Map rendering (existing). Adds `extract_projection(map_data)` helper. | Modify |
| `custom_components/dreame_a2_mower/session_card.py` | `build_picked_session_summary` (existing). Accepts `map_projection` kwarg; emits 4 new attributes. | Modify |
| `custom_components/dreame_a2_mower/coordinator/_session.py` | `render_work_log_session` (existing). Passes `map_projection` when calling `build_picked_session_summary`. | Modify |
| `tests/protocol/test_session_card.py` | Existing session_card tests. Add assertions for the 4 new attributes. | Modify |
| `tests/unit/test_map_projection.py` | New unit test for `extract_projection`. | Create |

**JavaScript (card side):**

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` | Custom Lovelace card: shadow DOM, SVG renderer, animation lifecycle, controls. | Create |

**Dashboard (deployment side):**

| File | Responsibility | Action |
|---|---|---|
| `dashboards/mower/dashboard.yaml` | Live dashboard. Adds the conditional pair on the Sessions tab + a resource entry. | Modify |
| (HA host) `/config/configuration.yaml` or helpers UI | Adds `input_boolean.dreame_a2_mower_animate_session`. | Modify |

**Documentation:**

| File | Responsibility | Action |
|---|---|---|
| `README.md` | Brief mention of how to enable the animated replay (toggle + resource entry). | Modify |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | Add verification record for the new attributes on `sensor.dreame_a2_mower_picked_session`. | Modify |

---

## Phase 1 — Integration-side data exposure (TDD)

### Task 1: `extract_projection` helper

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (add new function at bottom of file)
- Create: `tests/unit/test_map_projection.py`

The card needs the exact projection params that `render_base_map` already uses internally (`bx2`, `by2`, `pixel_size_mm`, `width_px`, `height_px`), plus the knowledge that the base PNG is flipped vertically (FLIP_TOP_BOTTOM is applied in `render_with_trail`). Expose them as one dict so the card can reproduce the projection without re-deriving.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_map_projection.py`:

```python
"""Unit tests for map_render.extract_projection."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.dreame_a2_mower.map_render import extract_projection


def test_extract_projection_returns_five_keys():
    map_data = SimpleNamespace(
        bx2=12345.6, by2=7890.1, pixel_size_mm=50.0,
        width_px=637, height_px=717,
    )
    proj = extract_projection(map_data)
    assert proj == {
        "bx2_mm": 12345.6,
        "by2_mm": 7890.1,
        "pixel_size_mm": 50.0,
        "width_px": 637,
        "height_px": 717,
    }


def test_extract_projection_none_returns_none():
    """Sessions may be picked before MapData is fetched. Don't crash."""
    assert extract_projection(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_map_projection.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_projection'`.

- [ ] **Step 3: Implement the helper**

Append to `custom_components/dreame_a2_mower/map_render.py` (after the last function, before any module-end constants):

```python
def extract_projection(map_data: "MapData | None") -> dict | None:
    """Expose the projection params the card needs to reproduce render_with_trail.

    Returns the five fields the card consumes to project (x_m, y_m) to
    pixel coords matching the base PNG:

      cloud_x = x_m * 1000
      cloud_y = y_m * 1000
      px      = (bx2_mm - cloud_x) / pixel_size_mm
      py_pre  = (by2_mm - cloud_y) / pixel_size_mm
      py      = height_px - py_pre  # FLIP_TOP_BOTTOM applied to base PNG

    Returns None when called with no MapData — the picked-session sensor
    may fire before the cloud map fetch completes.
    """
    if map_data is None:
        return None
    return {
        "bx2_mm": map_data.bx2,
        "by2_mm": map_data.by2,
        "pixel_size_mm": map_data.pixel_size_mm,
        "width_px": map_data.width_px,
        "height_px": map_data.height_px,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_map_projection.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/unit/test_map_projection.py
git commit -m "map_render: expose projection params via extract_projection

Card-side animation needs the bx2/by2/pixel_size_mm/width_px/height_px
that render_base_map uses internally to project (x_m, y_m) -> pixel.
extract_projection returns them as a flat dict; None when MapData is
not yet available (sensor may fire before cloud map fetch completes)."
```

---

### Task 2: Expose `legs` on picked_session

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py:344` (just before `return out`)
- Modify: `tests/protocol/test_session_card.py`

`session_card._compute_distance_m` already pulls `legs` from `raw_dict["_local_legs"]` or `summary.track_segments` (line 44-46). Mirror that read into the output dict so the card consumes the same list.

- [ ] **Step 1: Add a failing test**

Add to `tests/protocol/test_session_card.py` (after the existing `format_session_label` tests):

```python
def test_picked_session_summary_exposes_legs():
    """legs (list[list[[x_m, y_m]]]) must appear on the output dict.

    The card consumes this list as the per-leg trajectory to animate.
    Falls back to summary.track_segments when _local_legs is missing.
    """
    raw, summary, entry = _load_session("normal_2h_session")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert "legs" in out
    assert isinstance(out["legs"], list)
    assert len(out["legs"]) >= 1
    # Every point is a 2-tuple/list of floats
    first_pt = out["legs"][0][0]
    assert len(first_pt) == 2
    assert all(isinstance(c, (int, float)) for c in first_pt)
```

Replace `"normal_2h_session"` with the name of an actual fixture in `tests/protocol/data/sessions/`. List the available fixtures with `ls tests/protocol/data/sessions/` and pick one that has a non-empty trajectory.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_legs -v`
Expected: FAIL with `KeyError: 'legs'` or `AssertionError: 'legs' not in {...}`.

- [ ] **Step 3: Implement**

In `session_card.py`, just before the final `return out` (around line 344), add:

```python
    # Card-side trail animation reads this; same source as _compute_distance_m.
    legs_raw = raw_dict.get("_local_legs") or [
        list(seg) for seg in summary.track_segments
    ]
    out["legs"] = [
        [[float(p[0]), float(p[1])] for p in leg if len(p) >= 2]
        for leg in legs_raw
        if leg
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_legs -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: expose legs on picked_session attributes

Same source as the existing distance helper (_local_legs with summary
track-segments fallback). The custom replay card consumes this list as
the per-leg trajectory to animate."
```

---

### Task 3: Expose `state_samples` on picked_session

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py` (around line 320 where `state_transition_count` is already computed)
- Modify: `tests/protocol/test_session_card.py`

`state_samples` is already read at line 268 (local variable `ss`). The card uses it to classify mowing-vs-pause intervals for the timing model. Pure passthrough.

- [ ] **Step 1: Add a failing test**

```python
def test_picked_session_summary_exposes_state_samples():
    """state_samples (list[[ts_s, state_value]]) must appear on the output.

    The card uses this to classify mowing vs pause intervals.
    """
    raw, summary, entry = _load_session("normal_2h_session")  # same fixture name
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert "state_samples" in out
    assert isinstance(out["state_samples"], list)
    if out["state_samples"]:
        ts, sv = out["state_samples"][0]
        assert isinstance(ts, (int, float))
        assert isinstance(sv, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_state_samples -v`
Expected: FAIL with `KeyError`/`AssertionError`.

- [ ] **Step 3: Implement**

In `session_card.py`, near where `state_transition_count` is set (around line 320), add:

```python
    # Card-side animation reads state_samples to classify mowing-vs-pause
    # intervals for the proportional pause-budget timing model.
    out["state_samples"] = [
        [int(t), int(v)] for t, v in ss
        if isinstance(t, (int, float)) and isinstance(v, (int, float))
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_state_samples -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: expose state_samples on picked_session attributes

Passthrough of the already-read state_samples list. Card uses this
to compute pause intervals (anything not in the mowing state set)
for the proportional pause-budget timing model."
```

---

### Task 4: Plumb `map_projection` through `render_work_log_session`

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py:193` (signature) and around line 344 (output)
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py:190` (call site)
- Modify: `tests/protocol/test_session_card.py`

`build_picked_session_summary` doesn't currently know about MapData. Add a `map_projection: dict | None = None` kwarg and emit it. The coordinator's `render_work_log_session` already has MapData in scope (it just looked it up to call `render_work_log`); pass it through via `extract_projection`.

- [ ] **Step 1: Add a failing test**

```python
def test_picked_session_summary_exposes_map_projection():
    """map_projection (5-key dict) must appear on the output when supplied."""
    raw, summary, entry = _load_session("normal_2h_session")
    proj = {
        "bx2_mm": 12345.6, "by2_mm": 7890.1, "pixel_size_mm": 50.0,
        "width_px": 637, "height_px": 717,
    }
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
        map_projection=proj,
    )
    assert out["map_projection"] == proj


def test_picked_session_summary_map_projection_is_none_when_not_supplied():
    """Default to None so the card knows projection isn't available yet."""
    raw, summary, entry = _load_session("normal_2h_session")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert out["map_projection"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_map_projection tests/protocol/test_session_card.py::test_picked_session_summary_map_projection_is_none_when_not_supplied -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'map_projection'`.

- [ ] **Step 3: Implement signature + emit**

In `session_card.py:193`, change the signature:

```python
def build_picked_session_summary(
    raw_dict: dict[str, Any],
    summary: Any,
    entry: Any,
    picker_label: str,
    *,
    map_projection: dict | None = None,
) -> dict[str, Any]:
```

In the same function, just before the final `return out`, add:

```python
    out["map_projection"] = map_projection
```

- [ ] **Step 4: Wire the call site**

In `coordinator/_session.py:190`, find:

```python
            self._picked_session_summary = build_picked_session_summary(
                raw_dict=raw_dict,
                summary=summary,
                entry=entry,
                picker_label=picker_label,
            )
```

Change to:

```python
            from ..map_render import extract_projection

            # map_data was resolved earlier in this function (around line 253).
            # If MapData wasn't available, extract_projection returns None and
            # the card stays in its "no projection yet" branch.
            self._picked_session_summary = build_picked_session_summary(
                raw_dict=raw_dict,
                summary=summary,
                entry=entry,
                picker_label=picker_label,
                map_projection=extract_projection(map_data),
            )
```

Verify that `map_data` is in scope at the call site by reading the function: it's resolved into a local var at lines 253-271. If for some reason the function returned before that (e.g. archive parse failure), the call to `build_picked_session_summary` would not be reached — so we don't need a separate guard.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/protocol/test_session_card.py -k 'map_projection' -v`
Expected: PASS (2 tests).

Also run the full session_card suite to ensure nothing regressed:
Run: `pytest tests/protocol/test_session_card.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py custom_components/dreame_a2_mower/coordinator/_session.py tests/protocol/test_session_card.py
git commit -m "session_card: plumb map_projection through render_work_log_session

Coordinator already resolves MapData before calling render_work_log;
extract_projection(map_data) turns it into a 5-key dict the card uses
to reproduce render_with_trail's projection. None when MapData isn't
available yet — the card stays in its 'no projection' branch."
```

---

### Task 5: Expose `base_map_image_url` on picked_session

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py` (around line 344)
- Modify: `tests/protocol/test_session_card.py`
- Optional verification: `custom_components/dreame_a2_mower/camera.py` (no edit; just confirm the URL is stable)

The existing `WorkLogImageView` at `camera.py:823` serves the work-log PNG at `/api/dreame_a2_mower/work-log.png` (verify exact route). The card consumes this as the SVG's `<image href=...>` background. Static string — no per-entry computation needed.

- [ ] **Step 1: Verify the existing route**

Run:
```bash
grep -nE "url = |url ?= ?['\"]" custom_components/dreame_a2_mower/camera.py | head
grep -n "WorkLogImageView\|class .*View\|url = " custom_components/dreame_a2_mower/camera.py | head
```

Look at the `WorkLogImageView` class definition (line 823) and note the `url` attribute. Use that exact path in the test below.

- [ ] **Step 2: Write the failing test**

```python
def test_picked_session_summary_exposes_base_map_image_url():
    """base_map_image_url is a static path; card uses it as <image href=...>."""
    raw, summary, entry = _load_session("normal_2h_session")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    # Path must match what WorkLogImageView.url declares in camera.py.
    assert out["base_map_image_url"].startswith("/api/dreame_a2_mower/")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_base_map_image_url -v`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `session_card.py`, just before the final `return out`:

```python
    # Static path — WorkLogImageView serves the active work-log PNG without
    # auth, same as the live-map view. The card consumes this as the SVG's
    # <image href=...> background so the trail aligns with the base map.
    out["base_map_image_url"] = "/api/dreame_a2_mower/work-log.png"
```

If the URL in `camera.py` is different from `/api/dreame_a2_mower/work-log.png`, use the exact one you found in step 1.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/protocol/test_session_card.py::test_picked_session_summary_exposes_base_map_image_url -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/session_card.py tests/protocol/test_session_card.py
git commit -m "session_card: expose base_map_image_url on picked_session

Static path to WorkLogImageView's unauthenticated endpoint. Card uses
this as the SVG <image href=...> background; the trail SVG overlays
the same pixel grid the static PNG was rendered into."
```

---

### Task 6: Update entity-inventory verification record

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

Per the project's fact-discipline rule (CLAUDE.md), we touched the entity's source surface. Add a verification record on `sensor.dreame_a2_mower_picked_session`.

- [ ] **Step 1: Edit the entry**

Find the `sensor.dreame_a2_mower_picked_session` entry (currently around line 272 in `entity-inventory.yaml`) and add a new verification under its `verifications:` list:

```yaml
      - date: "2026-05-15"
        status: verified
        claim: "extra_state_attributes now also exposes legs (list[list[[x_m,y_m]]]), state_samples (list[[ts,state]]), map_projection ({bx2_mm,by2_mm,pixel_size_mm,width_px,height_px} or None), and base_map_image_url (static /api/dreame_a2_mower/work-log.png) — consumed by the dreame-mower-replay-card custom Lovelace card"
        evidence: "tests/protocol/test_session_card.py::test_picked_session_summary_exposes_{legs,state_samples,map_projection,base_map_image_url}"
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "entity-inventory: record new picked_session attributes

legs / state_samples / map_projection / base_map_image_url for the
replay-card consumer. Evidence: the four new tests in
tests/protocol/test_session_card.py."
```

---

## Phase 2 — Custom Lovelace card scaffold

### Task 7: Scaffold `dreame-mower-replay-card.js` (renders attributes only)

**Files:**
- Create: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Mirror the structure of `dreame-a2-schedule-card.js` (the existing template at ~352 LOC). First milestone: card mounts, reads picked_session attributes, displays them as text. No SVG yet.

- [ ] **Step 1: Create the file**

```javascript
// Dreame A2 Mower — Session Replay Card
//
// Animates the trail of an archived mowing session over the base map,
// fitting any session into <=30 s of playback with proportional freezes
// during non-mowing intervals.
//
// Reads sensor.dreame_a2_mower_picked_session attributes:
//   legs: list[list[[x_m, y_m]]]
//   state_samples: list[[ts_s, state_value]]
//   map_projection: { bx2_mm, by2_mm, pixel_size_mm, width_px, height_px } | null
//   base_map_image_url: str
//   started_at_unix, ended_at_unix
//
// Usage (Lovelace YAML):
//   resources:
//     - url: /dreame_a2_mower/dreame-mower-replay-card.js
//       type: module
//   ...
//   - type: custom:dreame-mower-replay-card
//     entity: sensor.dreame_a2_mower_picked_session

class DreameMowerReplayCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entityId = null;
    this._lastStateKey = null;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("entity is required (sensor.dreame_a2_mower_picked_session)");
    }
    this._entityId = config.entity;
  }

  set hass(hass) {
    const state = hass.states[this._entityId];
    if (!state) {
      this._renderMissing();
      return;
    }
    const stateKey = `${state.state}|${state.last_changed}`;
    if (stateKey === this._lastStateKey) return;
    this._lastStateKey = stateKey;
    this._render(state);
  }

  _renderMissing() {
    this.shadowRoot.innerHTML = `
      <div style="padding:12px;">
        Picked-session entity not found — set <code>entity:</code>.
      </div>`;
  }

  _render(state) {
    const a = state.attributes || {};
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding:12px; font-family: monospace; font-size: 11px;">
          <div><strong>Session:</strong> ${state.state}</div>
          <div>legs: ${(a.legs || []).length}</div>
          <div>state_samples: ${(a.state_samples || []).length}</div>
          <div>map_projection: ${a.map_projection ? "yes" : "no"}</div>
          <div>base_map_image_url: ${a.base_map_image_url || "-"}</div>
        </div>
      </ha-card>`;
  }

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
```

- [ ] **Step 2: Deploy the JS to HA**

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js \
  "$USER@$HOST:/config/custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js"
```

The integration's static-path registration (`__init__.py:130-155`) auto-serves the file at `/dreame_a2_mower/dreame-mower-replay-card.js` after the next HA reload. Restart HA or reload the integration to pick up the new file.

- [ ] **Step 3: Add a Lovelace resource entry**

Either via Settings → Dashboards → Resources UI, or by editing the dashboards/storage backend. Add:
- URL: `/dreame_a2_mower/dreame-mower-replay-card.js`
- Type: module

Verify the JS loads in the browser by opening DevTools → Network and refreshing the dashboard.

- [ ] **Step 4: Drop the card on a scratch view to verify mount**

Temporarily add to any Lovelace view (e.g. a new scratch tab):

```yaml
- type: custom:dreame-mower-replay-card
  entity: sensor.dreame_a2_mower_picked_session
```

Pick a session in the existing picker. The card should display: session label, legs count > 0, state_samples count > 0, `map_projection: yes`, and the base_map_image_url.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: scaffold dreame-mower-replay-card (text-only mount)

HTMLElement + shadow DOM + setConfig + set hass + _render mirrors the
existing dreame-a2-schedule-card structure. This first milestone just
displays the picked-session attributes as text to confirm the card
mounts and reads its inputs correctly. SVG + animation follow."
```

---

### Task 8: Render base map + SVG overlay (no trail yet)

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Replace the text-only `_render` with an SVG whose `viewBox` matches `map_projection.width_px × .height_px` and whose `<image>` is the base map PNG.

- [ ] **Step 1: Replace `_render`**

```javascript
  _render(state) {
    const a = state.attributes || {};
    const proj = a.map_projection;
    const url = a.base_map_image_url;
    if (!proj || !url) {
      this.shadowRoot.innerHTML = `
        <ha-card><div style="padding:12px;">
          Waiting for map projection / base image…
        </div></ha-card>`;
      return;
    }
    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>
          svg { display: block; width: 100%; height: auto; }
        </style>
        <svg viewBox="0 0 ${proj.width_px} ${proj.height_px}"
             xmlns="http://www.w3.org/2000/svg"
             preserveAspectRatio="xMidYMid meet">
          <image href="${url}"
                 x="0" y="0"
                 width="${proj.width_px}" height="${proj.height_px}" />
        </svg>
      </ha-card>`;
  }
```

- [ ] **Step 2: Deploy and verify**

Run the SCP command from Task 7 Step 2. Refresh the dashboard. The card should now show the actual base-map PNG with no overlay.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: render base map as SVG <image> background"
```

---

### Task 9: Render static `<path>` per leg (no animation yet)

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Add a `_buildLegPath(leg, proj)` helper and emit one `<path>` per leg. Use the projection from spec § Coordinate transform plus the vertical flip from `render_work_log_session`.

- [ ] **Step 1: Add helpers + path emission**

In the class, add:

```javascript
  _projectPoint(x_m, y_m, proj) {
    const cloud_x = x_m * 1000;
    const cloud_y = y_m * 1000;
    const px = (proj.bx2_mm - cloud_x) / proj.pixel_size_mm;
    const py_pre = (proj.by2_mm - cloud_y) / proj.pixel_size_mm;
    // FLIP_TOP_BOTTOM applied to base PNG by render_with_trail.
    const py = proj.height_px - py_pre;
    return [px, py];
  }

  _buildLegPathD(leg, proj) {
    if (!leg || leg.length === 0) return "";
    const parts = [];
    for (let i = 0; i < leg.length; i++) {
      const [px, py] = this._projectPoint(leg[i][0], leg[i][1], proj);
      parts.push(`${i === 0 ? "M" : "L"} ${px.toFixed(2)} ${py.toFixed(2)}`);
    }
    return parts.join(" ");
  }
```

Update `_render` to emit `<path>` per leg:

```javascript
  _render(state) {
    const a = state.attributes || {};
    const proj = a.map_projection;
    const url = a.base_map_image_url;
    if (!proj || !url) {
      this.shadowRoot.innerHTML = `
        <ha-card><div style="padding:12px;">
          Waiting for map projection / base image…
        </div></ha-card>`;
      return;
    }
    const legs = a.legs || [];
    const paths = legs.map((leg, i) => `
      <path d="${this._buildLegPathD(leg, proj)}"
            fill="none" stroke="rgb(220,40,40)" stroke-width="3"
            stroke-linecap="round" stroke-linejoin="round"
            data-leg-index="${i}" />
    `).join("");
    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>
          svg { display: block; width: 100%; height: auto; }
        </style>
        <svg viewBox="0 0 ${proj.width_px} ${proj.height_px}"
             xmlns="http://www.w3.org/2000/svg"
             preserveAspectRatio="xMidYMid meet">
          <image href="${url}"
                 x="0" y="0"
                 width="${proj.width_px}" height="${proj.height_px}" />
          ${paths}
        </svg>
      </ha-card>`;
  }
```

- [ ] **Step 2: Deploy and verify against the static PNG**

Deploy via SCP. The trail polylines should overlay the base map at the same positions as `camera.dreame_a2_mower_session_replay` shows them. If they're flipped or shifted, the most likely cause is the vertical-flip line (`const py = proj.height_px - py_pre`). Pick a real session and compare side-by-side with the existing work-log card.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: render static trail polylines per leg

_projectPoint mirrors render_trail_overlay's (bx2 - x*1000)/grid
formula plus render_with_trail's FLIP_TOP_BOTTOM. _buildLegPathD
emits SVG path d= strings. One <path> per leg so animations can
target them individually."
```

---

## Phase 3 — Animation

### Task 10: Trail draw animation (uniform pace, no pauses)

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Per leg: set `stroke-dasharray=L` and `stroke-dashoffset=L`, then `path.animate([{strokeDashoffset:L},{strokeDashoffset:0}], {duration})`. Sequence legs back-to-back. Total fixed 30 s for now (pause-aware timing comes in Task 12).

- [ ] **Step 1: Add animation setup after `_render`**

In `_render`, just after `this.shadowRoot.innerHTML = ...`, call:

```javascript
    this._startAnimation();
```

Add the method:

```javascript
  _startAnimation() {
    // Cancel any in-flight animations (replay or session-change reload).
    if (this._activeAnimations) {
      this._activeAnimations.forEach(a => a.cancel());
    }
    if (this._pendingTimeouts) {
      this._pendingTimeouts.forEach(t => clearTimeout(t));
    }
    this._activeAnimations = [];
    this._pendingTimeouts = [];

    const paths = Array.from(
      this.shadowRoot.querySelectorAll("path[data-leg-index]")
    );
    if (paths.length === 0) return;

    // Compute total trail length (sum across legs) — used to budget
    // duration per leg proportional to that leg's share.
    const lengths = paths.map(p => p.getTotalLength());
    const totalLength = lengths.reduce((s, l) => s + l, 0) || 1;

    const TOTAL_MS = 30000;  // hard 30s cap; pause-aware redistribution in Task 12

    // Initialize all paths to fully-hidden (dashoffset = full length).
    paths.forEach((p, i) => {
      p.style.strokeDasharray = lengths[i];
      p.style.strokeDashoffset = lengths[i];
    });

    // Chain leg animations. Each setTimeout fires the next leg's animate().
    let cumulativeDelay = 0;
    paths.forEach((p, i) => {
      const dur = (lengths[i] / totalLength) * TOTAL_MS;
      const start = () => {
        const anim = p.animate(
          [
            { strokeDashoffset: lengths[i] },
            { strokeDashoffset: 0 },
          ],
          { duration: dur, fill: "forwards", easing: "linear" }
        );
        this._activeAnimations.push(anim);
      };
      if (cumulativeDelay === 0) {
        start();
      } else {
        const t = setTimeout(start, cumulativeDelay);
        this._pendingTimeouts.push(t);
      }
      cumulativeDelay += dur;
    });
  }
```

- [ ] **Step 2: Deploy and verify**

Deploy. Pick a session. The trail should draw itself across ~30s. If the animation runs but the path doesn't reveal correctly, the most likely cause is the path's stroke not having `fill: forwards` or the dasharray not being set before animate() runs.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: animate trail with stroke-dasharray draw effect

Per leg: set dasharray=length, dashoffset=length, then animate
dashoffset to 0 with linear easing over a fraction of the 30s
budget proportional to that leg's share of total length. Legs
chain back-to-back via setTimeout. Pause-aware redistribution
comes next."
```

---

### Task 11: Head marker

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Add a `<circle>` that follows the current path's drawing tip via `getPointAtLength(L - currentOffset)`. Update on `requestAnimationFrame` for smoothness while an animation is running.

- [ ] **Step 1: Add marker + tracker**

In `_render`, after the path emission, just before `</svg>`:

```html
          <circle id="head" r="6" fill="rgb(255,140,0)" stroke="white" stroke-width="2"
                  cx="0" cy="0" visibility="hidden" />
```

In `_startAnimation`, just before the `paths.forEach` chain, capture the marker:

```javascript
    const marker = this.shadowRoot.getElementById("head");
    if (marker) marker.setAttribute("visibility", "visible");
```

Replace each leg's `start` closure with:

```javascript
      const start = () => {
        const anim = p.animate(
          [
            { strokeDashoffset: lengths[i] },
            { strokeDashoffset: 0 },
          ],
          { duration: dur, fill: "forwards", easing: "linear" }
        );
        this._activeAnimations.push(anim);

        // Drive the head marker via rAF while this leg animates.
        const tick = () => {
          if (anim.playState === "finished" || anim.playState === "idle") return;
          // currentTime is in ms; map to dashoffset, then to point on path.
          const t = anim.currentTime || 0;
          const offset = lengths[i] - (t / dur) * lengths[i];
          const point = p.getPointAtLength(lengths[i] - offset);
          marker.setAttribute("cx", point.x.toFixed(2));
          marker.setAttribute("cy", point.y.toFixed(2));
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      };
```

- [ ] **Step 2: Deploy and verify**

The orange circle should follow the drawing tip across each leg. At leg boundaries the marker may jump — that's correct (the mower lifts the pen, no continuous motion between legs).

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: head marker follows the drawing tip via getPointAtLength"
```

---

### Task 12: Pause-aware timing model

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Replace the uniform-pace logic with the spec's two-budget model: drawing budget proportional to mowing time, pause budget proportional to pause time, total still ≤ 30 s.

- [ ] **Step 1: Add pause-interval computation**

Add the classifier and interval extractor:

```javascript
  _MOWING_STATES = new Set([1, 2, 3]);

  _computePauseIntervals(stateSamples, startTs, endTs) {
    // Returns list of {ts_start, ts_end} pause intervals (in session seconds).
    // Uses spec §State→mowing/pause: states 1,2,3 = mowing; everything else = pause.
    if (!stateSamples || stateSamples.length === 0) return [];
    const pauses = [];
    let curPauseStart = null;
    for (let i = 0; i < stateSamples.length; i++) {
      const [ts, sv] = stateSamples[i];
      const isMowing = this._MOWING_STATES.has(sv);
      if (!isMowing && curPauseStart === null) {
        curPauseStart = ts;
      } else if (isMowing && curPauseStart !== null) {
        pauses.push({ start: curPauseStart, end: ts });
        curPauseStart = null;
      }
    }
    if (curPauseStart !== null) {
      pauses.push({ start: curPauseStart, end: endTs });
    }
    // Clip to session bounds.
    return pauses
      .map(p => ({
        start: Math.max(p.start, startTs),
        end: Math.min(p.end, endTs),
      }))
      .filter(p => p.end > p.start);
  }
```

- [ ] **Step 2: Reshape `_startAnimation` budget logic**

Inside `_startAnimation`, after `const lengths = ...`, replace the constant `TOTAL_MS` with the budget calculation:

```javascript
    const TOTAL_MS = 30000;
    const startTs = a.started_at_unix || 0;
    const endTs = a.ended_at_unix || startTs + 1;
    const sessionDuration = Math.max(1, endTs - startTs);
    const pauses = this._computePauseIntervals(
      a.state_samples || [], startTs, endTs
    );
    const pauseSeconds = pauses.reduce((s, p) => s + (p.end - p.start), 0);
    const mowSeconds = sessionDuration - pauseSeconds;
    const drawBudgetMs = TOTAL_MS * (mowSeconds / sessionDuration);
    const pauseBudgetMs = TOTAL_MS * (pauseSeconds / sessionDuration);
```

`a` is the `state.attributes` dict; pass it through `_startAnimation` by changing the call site `this._startAnimation()` to `this._startAnimation(a)` and the method to `_startAnimation(a) {`.

- [ ] **Step 3: Insert pause delays between legs**

The challenge: the spec talks about pauses *between legs*, but pauses are dated by `state_samples` timestamps. A simple-but-honest approximation for v1: split `pauseBudgetMs` evenly across the gaps *between* consecutive legs, weighted by each gap's portion of `pauseSeconds`.

A leg gap is the time between the previous leg's end and the current leg's start. For v1 we approximate this by counting how many pause intervals overlap *between* legs, but a simpler approximation that fits the spec's "proportional to each pause's share" is: distribute pauseBudgetMs across the gaps using the count of legs - 1.

Replace the chain logic with:

```javascript
    const legGapPauseMs = paths.length > 1
      ? pauseBudgetMs / (paths.length - 1)
      : 0;

    let cumulativeDelay = 0;
    paths.forEach((p, i) => {
      const dur = (lengths[i] / totalLength) * drawBudgetMs;
      const start = () => { /* same animate() + rAF marker tick as Task 11 */ };
      if (cumulativeDelay === 0) {
        start();
      } else {
        const t = setTimeout(start, cumulativeDelay);
        this._pendingTimeouts.push(t);
      }
      cumulativeDelay += dur;
      if (i < paths.length - 1) cumulativeDelay += legGapPauseMs;
    });
```

Note: this is intentionally a v1 approximation. The "proportional to each pause's share of pause time" version in the spec is correct but requires aligning pause intervals to leg boundaries — which itself is approximate because trajectory points don't carry timestamps. Leave a TODO comment referencing the spec section and revisit only if real sessions look wrong.

```javascript
    // TODO (v2): align pause intervals to leg boundaries instead of distributing
    // pauseBudgetMs uniformly. See spec § Timing model. Requires correlating
    // state_samples timestamps with inferred per-leg time spans.
```

- [ ] **Step 4: Deploy and verify**

Pick a 2 h session with a mid-session recharge. Total playback should be ≤ 30 s; the recharge should appear as a visible freeze (~3-4 s for a 20-min charge in a 2 h session). If playback feels too fast/slow, sanity-check `mowSeconds` / `pauseSeconds` in DevTools console (add `console.log` lines inside `_startAnimation`).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: pause-aware timing model splits 30s into draw + pause budgets

state_samples drives pause-interval detection (states 1/2/3 = mowing,
else pause). drawBudgetMs scales legs proportionally; pauseBudgetMs
splits across gaps between legs. v1 approximation — see TODO ref to
spec timing model."
```

---

### Task 13: Play / pause / replay controls

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Add a toolbar below the SVG with three buttons. Hook to `_activeAnimations` and `_pendingTimeouts`.

- [ ] **Step 1: Add toolbar markup**

In `_render`, after `</svg>`:

```html
        <div class="controls">
          <button id="btn-play" title="Play">▶</button>
          <button id="btn-pause" title="Pause">⏸</button>
          <button id="btn-replay" title="Replay">↻</button>
        </div>
```

In the `<style>`:

```css
          .controls {
            display: flex; gap: 8px; padding: 8px;
            justify-content: center;
          }
          .controls button {
            background: var(--card-background-color);
            color: var(--primary-text-color);
            border: 1px solid var(--divider-color);
            border-radius: 4px; padding: 4px 12px;
            font-size: 16px; cursor: pointer;
          }
```

- [ ] **Step 2: Wire button handlers in `_render`**

After the `_startAnimation(a)` call:

```javascript
    this.shadowRoot.getElementById("btn-play").onclick = () => {
      this._activeAnimations.forEach(an => an.play());
      this._pauseUntil = null;  // see pause handler below
    };
    this.shadowRoot.getElementById("btn-pause").onclick = () => {
      this._activeAnimations.forEach(an => an.pause());
      // Pending setTimeouts can't be paused; clear and remember elapsed.
      this._pauseUntil = Date.now();
      this._pendingTimeouts.forEach(t => clearTimeout(t));
      this._pendingTimeouts = [];
    };
    this.shadowRoot.getElementById("btn-replay").onclick = () => {
      this._lastStateKey = null;  // force a full re-render
      this._render(state);
    };
```

Note: full pause/resume across pending leg-start setTimeouts is non-trivial. v1 acceptable: pause works mid-leg (Web Animations API), but pause-then-play across a between-leg gap may skip. Document as a known limitation.

- [ ] **Step 3: Deploy and verify**

▶ resumes a paused animation. ⏸ freezes it. ↻ restarts from t=0. Mid-leg pause/resume should work cleanly; pausing in a between-leg gap may behave oddly — that's the documented limitation.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: play/pause/replay buttons via Web Animations API

▶/⏸ control via .play()/.pause() on _activeAnimations; ↻ triggers a
full re-render which cancels and rebuilds. Mid-leg pause works
correctly; pause across a between-leg gap is documented as a v1
limitation."
```

---

### Task 14: Scrub slider

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

A `<input type="range" min="0" max="1000">` mapped to a fractional position in the total timeline. Setting the slider position cancels current animations and rebuilds the state at that scrubbed position.

- [ ] **Step 1: Add slider markup**

In `_render`, inside the `.controls` div, after the replay button:

```html
          <input id="scrub" type="range" min="0" max="1000" value="0"
                 style="flex: 1; max-width: 240px;" />
```

- [ ] **Step 2: Precompute a timeline of (cumulative_ms, leg_index)**

Inside `_startAnimation(a)`, after the legGapPauseMs setup, build the timeline:

```javascript
    // Precompute cumulative timeline so scrub can map fraction → leg state.
    let acc = 0;
    this._timeline = [];
    paths.forEach((p, i) => {
      const dur = (lengths[i] / totalLength) * drawBudgetMs;
      this._timeline.push({ leg: i, start_ms: acc, end_ms: acc + dur, dur });
      acc += dur;
      if (i < paths.length - 1) acc += legGapPauseMs;
    });
    this._totalMs = acc;
```

- [ ] **Step 3: Wire slider input**

After the existing button handlers in `_render`:

```javascript
    this.shadowRoot.getElementById("scrub").oninput = (e) => {
      const frac = parseInt(e.target.value, 10) / 1000;
      const target_ms = frac * (this._totalMs || 1);
      this._seekTo(target_ms);
    };
```

- [ ] **Step 4: Implement `_seekTo`**

```javascript
  _seekTo(target_ms) {
    // Cancel everything in-flight.
    if (this._activeAnimations) this._activeAnimations.forEach(a => a.cancel());
    if (this._pendingTimeouts) this._pendingTimeouts.forEach(t => clearTimeout(t));
    this._activeAnimations = [];
    this._pendingTimeouts = [];

    const paths = Array.from(
      this.shadowRoot.querySelectorAll("path[data-leg-index]")
    );
    paths.forEach((p, i) => {
      const slot = this._timeline[i];
      const L = parseFloat(p.style.strokeDasharray) || p.getTotalLength();
      if (target_ms >= slot.end_ms) {
        // Fully drawn.
        p.style.strokeDashoffset = 0;
      } else if (target_ms <= slot.start_ms) {
        // Fully hidden.
        p.style.strokeDashoffset = L;
      } else {
        // Partial.
        const local_t = target_ms - slot.start_ms;
        const frac = local_t / slot.dur;
        p.style.strokeDashoffset = L * (1 - frac);
      }
    });

    // Update head marker to the active leg's current point.
    const active = this._timeline.find(s =>
      target_ms >= s.start_ms && target_ms <= s.end_ms
    );
    const marker = this.shadowRoot.getElementById("head");
    if (active && marker) {
      const p = paths[active.leg];
      const L = parseFloat(p.style.strokeDasharray) || p.getTotalLength();
      const local_t = target_ms - active.start_ms;
      const frac = local_t / active.dur;
      const point = p.getPointAtLength(L * frac);
      marker.setAttribute("cx", point.x.toFixed(2));
      marker.setAttribute("cy", point.y.toFixed(2));
    }
  }
```

- [ ] **Step 5: Deploy and verify**

Dragging the slider should immediately reposition the trail: legs before the position fully drawn, the active leg partially drawn, legs after the position hidden, head marker at the active position. Releasing the slider does not resume — playback stays paused at the scrubbed position. Pressing ▶ would currently restart from t=0 (a known limitation that v1 accepts).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: scrub slider seeks within precomputed timeline

_timeline records {leg, start_ms, end_ms} per leg. Slider input
calls _seekTo which cancels animations and sets dashoffset per
leg to the scrubbed position. Head marker repositions to the
active leg's current point."
```

---

### Task 15: Autoplay on session pick

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

Already partially handled: `set hass(hass)` compares `last_changed` and re-renders. Verify it works for the picked-session entity specifically.

- [ ] **Step 1: Verify by switching sessions in the picker**

Pick session A. Watch animation play. Without refreshing the page, pick session B. The card should:
1. Cancel session A's animations
2. Re-render with session B's data
3. Start session B's animation from t=0

The cancel-on-rerender happens automatically because `_startAnimation` calls `cancel()` on `_activeAnimations` at the top.

- [ ] **Step 2: If it doesn't work**

Most likely cause: the `set hass(hass)` early-return key (`state|last_changed`) is too coarse. The picked_session sensor's `last_changed` updates when the picker fires, so this should work. If not, change `_lastStateKey` to also include `state.attributes.md5` or `state.attributes.filename`:

```javascript
const stateKey = `${state.state}|${state.last_changed}|${state.attributes.filename || ""}`;
```

- [ ] **Step 3: Commit (only if Step 2 needed)**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "card: include filename in re-render key for cross-session pick"
```

---

## Phase 4 — Dashboard integration

### Task 16: Add `input_boolean` helper

**Files:**
- HA host UI (Settings → Devices & Services → Helpers) OR `/config/configuration.yaml`

- [ ] **Step 1: Create the helper**

Via the UI: Settings → Devices & Services → Helpers → Create → Toggle.
- Name: `Dreame A2 Mower animate session`
- Icon: `mdi:animation-play`
- Default state: off
- Entity ID will be `input_boolean.dreame_a2_mower_animate_session`

Or via YAML:

```yaml
# /config/configuration.yaml
input_boolean:
  dreame_a2_mower_animate_session:
    name: Animate session replay
    initial: false
    icon: mdi:animation-play
```

Restart HA / reload helpers and confirm `input_boolean.dreame_a2_mower_animate_session` exists in Developer Tools → States.

---

### Task 17: Conditional pair in the dashboard YAML

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` (the existing static replay-map block)

- [ ] **Step 1: Find the existing static replay block**

Run: `grep -n 'session_replay\|big replay\|work-log' dashboards/mower/dashboard.yaml | head`

The block is somewhere on the Sessions tab (around the "big replay map" comment). Note the existing card type and entity.

- [ ] **Step 2: Replace with the conditional pair**

In place of the existing single picture-entity card for the work-log replay, insert:

```yaml
- type: conditional
  conditions:
    - entity: input_boolean.dreame_a2_mower_animate_session
      state: "off"
  card:
    type: picture-entity
    # Use whatever was there before (probably camera.dreame_a2_mower_session_replay
    # or similar). Preserve the exact entity that was in the block being replaced.
    entity: camera.dreame_a2_mower_session_replay
    show_state: false
    show_name: false
- type: conditional
  conditions:
    - entity: input_boolean.dreame_a2_mower_animate_session
      state: "on"
  card:
    type: custom:dreame-mower-replay-card
    entity: sensor.dreame_a2_mower_picked_session
```

Plus a toggle entity row somewhere in the session-summary area:

```yaml
- type: entities
  entities:
    - entity: input_boolean.dreame_a2_mower_animate_session
      name: Animate session replay
```

Add the resource entry to the dashboard's `resources:` section (or, for storage-mode dashboards, to the Lovelace resources via Settings → Dashboards):

```yaml
resources:
  - url: /dreame_a2_mower/dreame-mower-replay-card.js
    type: module
```

If `resources:` doesn't already exist at the top of `dashboard.yaml`, add it.

- [ ] **Step 3: Deploy and verify**

Standard SCP deploy of the dashboard:

```bash
read -r HOST < /data/claude/homeassistant/ha-credentials.txt
USER=$(sed -n 2p /data/claude/homeassistant/ha-credentials.txt)
PWD=$(sed -n 3p /data/claude/homeassistant/ha-credentials.txt)
STAMP=$(date +%Y%m%d_%H%M%S)
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" \
  "cp /config/dashboards/mower/dashboard.yaml /config/dashboards/mower/dashboard.yaml.bak-${STAMP}"
sshpass -p "$PWD" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
  "$USER@$HOST:/config/dashboards/mower/dashboard.yaml"
sshpass -p "$PWD" ssh -o StrictHostKeyChecking=no "$USER@$HOST" "md5sum /config/dashboards/mower/dashboard.yaml"
md5sum /data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml
```

Hashes must match. Refresh the Sessions tab. Toggle the helper on → animated card mounts. Toggle off → static work-log image returns.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: toggle between static work-log and animated replay

input_boolean.dreame_a2_mower_animate_session controls a conditional
pair on the Sessions tab. Off: existing picture-entity stays. On:
custom:dreame-mower-replay-card mounts and animates. Resource entry
points at the integration's static-path-served JS."
```

---

### Task 18: Document in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a short section**

Find an appropriate spot (probably near the existing dashboard/HACS install instructions) and add:

```markdown
### Animated session replay

The Sessions tab includes an optional animated replay that draws the
mower's trail over the base map at ≤30s total, with proportional
freezes during charging/stuck/faulted intervals.

To enable:

1. Add a Lovelace resource (Settings → Dashboards → Resources → Add):
   - URL: `/dreame_a2_mower/dreame-mower-replay-card.js`
   - Type: JavaScript Module
2. Create an `input_boolean.dreame_a2_mower_animate_session` toggle helper.
3. Refresh the dashboard. Toggle ON to switch from the static
   work-log image to the animated replay.

The JS ships with the integration — no separate HACS install needed.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: enable-the-replay-card instructions"
```

---

### Task 19: End-to-end acceptance check

**Files:**
- None (verification only)

- [ ] **Step 1: Acceptance criteria from the spec**

Verify each criterion against the live HA dashboard:

- [ ] Toggle in the Sessions tab switches between static and animated.
- [ ] A 2 h session with one mid-session recharge plays back in ≤ 30 s total, with the recharge interval clearly visible as a freeze.
- [ ] The animated trail's final state is pixel-equivalent to the static PNG (same legs, same path).
- [ ] Play / pause / replay / scrub all work without console errors (check DevTools console).
- [ ] Picking a different session while animated mode is on tears down the current animation and starts the new one within ~500 ms.

- [ ] **Step 2: Push everything to remote**

```bash
git push origin HEAD
```

Per the project's CLAUDE.md cleanup-window push cadence ([feedback_push_upstream_regularly.md] in memory), push as soon as each phase wraps so HACS users get incremental builds. Final push closes out v1 of the replay feature.

---

## Self-review checklist

After completing the plan above, the implementer should verify:

- [ ] All four picked_session attributes (`legs`, `state_samples`, `map_projection`, `base_map_image_url`) appear in `Developer Tools → States → sensor.dreame_a2_mower_picked_session.attributes` for a real picked session.
- [ ] The static-mode card (toggle OFF) renders the same image it did before this plan started.
- [ ] The animated card (toggle ON) plays without console errors on Chrome and Firefox.
- [ ] Switching sessions while animated mode is on does not leak `setTimeout`s or animations (check DevTools → Performance → Memory).
- [ ] `pytest tests/protocol/test_session_card.py tests/unit/test_map_projection.py` all pass.
- [ ] The CI `outstanding retractions` step still shows the rain-protection-active retraction unchanged (this plan didn't touch it; the gate should stay quiet).
