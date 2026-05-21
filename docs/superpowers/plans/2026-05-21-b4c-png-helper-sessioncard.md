# B4c — PNG helper + session_card split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) Extract a shared `_png.py` (`encode_png` + `png_response`) and route the 8 PIL→PNG sites + 2 PNG view-responses through it; (2) split `session_card.build_picked_session_summary` (~260 LOC) into 5 section helpers + a thin orchestrator. Behavior-preserving.

**Architecture:** `_png.py` at the package root holds `encode_png(image, *, optimize=False) -> bytes` (pure PIL) and `png_response(body, *, cache=…, extra_headers=None)` (aiohttp, imported lazily inside it). `build_picked_session_summary` becomes an orchestrator that merges five `_summary_*` helpers and computes the one cross-section field.

**Tech Stack:** Python 3, HA custom integration (vanilla stubbed-HA test venv), Pillow, aiohttp, pytest.

**Spec:** `docs/superpowers/specs/2026-05-21-b4c-png-helper-sessioncard-design.md`

**Context:** branch `main`. **TEST ENV: use `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest …`** (system `python3` is 3.14/broken; do NOT pip install — no real HA / no p-h-c-c). Baseline (full `pytest tests`): **1591 passed, 4 skipped**. Commit on `main`, `audit-b4c:` prefix, authored as user, **no co-author trailer**, do NOT push. Conventions: move bodies VERBATIM; prune imports per-name; re-export/expose only what real callers use.

---

## File Structure

| File | Change |
|---|---|
| `custom_components/dreame_a2_mower/_png.py` | NEW — `encode_png`, `png_response` (T2) |
| `custom_components/dreame_a2_mower/map_render/base_map.py` | use `encode_png` (T2) |
| `custom_components/dreame_a2_mower/map_render/trail.py` | use `encode_png` ×2 (T2) |
| `custom_components/dreame_a2_mower/map_render/main_view.py` | use `encode_png` ×2 (T2) |
| `custom_components/dreame_a2_mower/wifi_map_render.py` | use `encode_png`; drop `from io import BytesIO` if now unused (T2) |
| `custom_components/dreame_a2_mower/protocol/pcd_render.py` | use `encode_png(…, optimize=True)` ×2; prune `import io` if now unused (T2) |
| `custom_components/dreame_a2_mower/_camera_views.py` | use `png_response` in MapImageView + WorkLogImageView (T2) |
| `tests/unit/test_png.py` | NEW — encode_png/png_response unit tests (T2) |
| `tests/integration/test_picked_session.py` | add characterization test (T1) |
| `custom_components/dreame_a2_mower/session_card.py` | split `build_picked_session_summary` (T3) |

---

### Task 1: Characterization test for `build_picked_session_summary` (before any refactor)

Pins the FULL output BEFORE T3 touches the function. Must PASS on current code.

**File:** `tests/integration/test_picked_session.py` (reuse its existing `_make_entry_from_raw` + the `short.json` fixture + `parse_session_summary`).

- [ ] **Step 1: Add a full-output characterization test**

Append a test that builds the summary for `tests/protocol/data/sessions/short.json` and asserts the COMPLETE returned dict equals a captured baseline. Generate the baseline by running the current builder and copying its exact output:
```python
def test_build_picked_session_summary_characterization():
    """Pin the FULL output dict of build_picked_session_summary before the
    B4c split. Generated against the pre-refactor code; the split (T3) must
    reproduce it byte-for-byte."""
    import json
    from pathlib import Path
    from types import SimpleNamespace  # noqa: F401 (used via _make_entry_from_raw)
    from custom_components.dreame_a2_mower.session_card import build_picked_session_summary, format_session_label
    from custom_components.dreame_a2_mower.protocol.session_summary import parse_session_summary
    raw = json.loads((Path("tests/protocol/data/sessions/short.json")).read_text())
    entry = _make_entry_from_raw(raw)
    summary = parse_session_summary(raw)
    result = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label=format_session_label(entry),
    )
    expected = {  # <-- IMPLEMENTER: paste the actual dict printed by the current code
        ...
    }
    assert result == expected
```
To produce `expected`: run a throwaway snippet with the venv python that prints `repr(result)` for the current code, and paste it. If the literal is unwieldy (large `battery_samples`/`state_samples`/`legs` lists), instead assert: (a) `set(result) == set(expected_keys)` (the full key set), (b) every scalar/derived key equals its captured value (esp. `m2_per_pct`, `coverage_pct`, `completed`, `result_label`, `charge_used_pct`, `local_leg_count`), and (c) `len()` + first/last element of each list field (`battery_samples`, `state_samples`, `wifi_samples`, `legs`, `mowing_legs`, `traversal_legs`, `legs_timeline`). Either form is acceptable; the goal is that a behavior change in any section is caught.

- [ ] **Step 2: Run it against current code — must PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_picked_session.py -q`
Expected: all pass (existing + new). If the new test cannot be made to pass on CURRENT code, STOP — the baseline capture is wrong.

- [ ] **Step 3: Commit**
```bash
git add tests/integration/test_picked_session.py
git commit -m "audit-b4c: characterization test pinning build_picked_session_summary output"
```

---

### Task 2: `_png.py` helper + route all call sites

**Files:** create `_png.py` + `tests/unit/test_png.py`; edit the 6 render/view files.

- [ ] **Step 1: Create `custom_components/dreame_a2_mower/_png.py`**
```python
"""Shared PNG (de)serialisation helpers."""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


def encode_png(image: Image.Image, *, optimize: bool = False) -> bytes:
    """Serialise a PIL image to PNG bytes."""
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=optimize)
    return buf.getvalue()


def png_response(body: bytes, *, cache: str = "no-store, max-age=0",
                 extra_headers: dict[str, str] | None = None):
    """aiohttp Response for a PNG body with an explicit Cache-Control."""
    from aiohttp import web  # deferred: keep encode_png importers free of aiohttp
    headers = {"Cache-Control": cache}
    if extra_headers:
        headers.update(extra_headers)
    return web.Response(body=body, content_type="image/png", headers=headers)
```
(`encode_png(img)` with `optimize=False` is byte-identical to `img.save(buf, format="PNG")`; `optimize=True` matches pcd_render. PIL is type-only here.)

- [ ] **Step 2: Replace the 8 encode sites** (each VERBATIM-equivalent). Import depth: `map_render/*` → `from .._png import encode_png`; `wifi_map_render.py` → `from ._png import encode_png`; `protocol/pcd_render.py` → `from .._png import encode_png`. Put the import at module top.

| File:line | Before (3 lines) | After |
|---|---|---|
| `map_render/base_map.py` 434-436 | `buf = io.BytesIO()` / `image.save(buf, format="PNG")` / `png_bytes = buf.getvalue()` | `png_bytes = encode_png(image)` |
| `map_render/trail.py` 206-208 | same idiom (indented) → `png_bytes` | `png_bytes = encode_png(image)` |
| `map_render/trail.py` 349-351 | same → `png_bytes` | `png_bytes = encode_png(image)` |
| `map_render/main_view.py` 224-226 | `… return buf.getvalue()` | `return encode_png(image)` |
| `map_render/main_view.py` 260-262 | `… return buf.getvalue()` | `return encode_png(image)` |
| `wifi_map_render.py` 116-118 | `out = BytesIO()` / `img.save(out, format="PNG")` / `return out.getvalue()` | `return encode_png(img)` |
| `protocol/pcd_render.py` 118-120 | `… optimize=True … return buf.getvalue()` | `return encode_png(img, optimize=True)` |
| `protocol/pcd_render.py` 125-127 | same | `return encode_png(img, optimize=True)` |

- [ ] **Step 3: Replace the 2 PNG view responses** in `_camera_views.py`:
  - `MapImageView.get` (the `web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})` block, ~66-79):
    `return png_response(png, extra_headers={"Pragma": "no-cache"})`
  - `WorkLogImageView.get` (~114-118): `return png_response(png)`
  - Add `from ._png import png_response` at top. Do NOT touch the PCD/`no-cache` responses (different content type/headers) or any `web.Response(status=…)` error returns. Keep the explanatory comments (move the gist into `png_response`'s docstring or leave a one-liner at the call site).

- [ ] **Step 4: Per-name import prune.** After edits, grep each touched file for now-unused imports and remove them: `wifi_map_render.py` `from io import BytesIO` (likely now unused — confirm), `protocol/pcd_render.py` `import io` (confirm no other `io.` use), and any `io`/`BytesIO` left dangling in map_render files (NOTE: `io` is still used in base_map/trail/main_view for `io.BytesIO(base_png)` reads — do NOT remove those). Per-name grep, not "tests pass".

- [ ] **Step 5: Add `tests/unit/test_png.py`**
```python
"""Unit tests for the shared PNG helpers."""
from PIL import Image
from custom_components.dreame_a2_mower._png import encode_png


def test_encode_png_returns_valid_png():
    img = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
    data = encode_png(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    from io import BytesIO
    assert Image.open(BytesIO(data)).size == (4, 4)


def test_encode_png_optimize_is_valid_png():
    img = Image.new("RGB", (8, 8), (10, 20, 30))
    data = encode_png(img, optimize=True)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
```
(`png_response` needs aiohttp + isn't easily unit-tested under the stub harness; the `_camera_views` tests cover it. If trivial to test the header dict without a running app, add it; otherwise skip.)

- [ ] **Step 6: Run render + camera + new tests, then full suite**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_png.py tests/integration/test_map_render.py tests/integration/test_work_log_render.py tests/integration/test_main_view_render.py tests/protocol/test_render_work_log_uses_split.py tests/integration/test_wifi_renderer_orientation.py tests/integration/test_per_map_cameras.py tests/integration/test_lidar_view.py -q` → all pass.
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests -q` → **1592 passed, 4 skipped** (baseline + the 1 new test file's tests; exact count may be 1593 with both test_png cases — confirm no regressions vs baseline 1591).

- [ ] **Step 7: Commit**
```bash
git add custom_components/dreame_a2_mower/_png.py custom_components/dreame_a2_mower/map_render/ custom_components/dreame_a2_mower/wifi_map_render.py custom_components/dreame_a2_mower/protocol/pcd_render.py custom_components/dreame_a2_mower/_camera_views.py tests/unit/test_png.py
git commit -m "audit-b4c: extract _png.py (encode_png + png_response); route all PNG sites through it"
```

---

### Task 3: Split `build_picked_session_summary`

**File:** `custom_components/dreame_a2_mower/session_card.py` (function at L360-~620).

Move each comment-delimited section VERBATIM into a private helper that returns a partial dict; the orchestrator merges them. Section → helper (current line ranges, confirm by reading):

| Helper | Section (current lines) | Notes |
|---|---|---|
| `_summary_identity(summary, entry, picker_label, md5) -> dict` | identity & outcome 377-412 | incl. the `(incomplete)` / completed branch + `stop_reason_label` |
| `_summary_coverage_efficiency(summary, raw_dict) -> dict` | coverage & efficiency 414-432 | DROP the `m2_per_pct = None` placeholder (orchestrator sets it) |
| `_summary_energy_time(raw_dict, summary) -> dict` | energy & time 434-483 | DROP the `m2_per_pct` compute (478-481) — moves to orchestrator; KEEP `battery_samples` |
| `_summary_diagnostics(summary, raw_dict) -> dict` | diagnostics 485-514 | faults/obstacles/state/errors/wifi |
| `_summary_trail_legs(raw_dict, summary, map_projection) -> dict` | trail/legs union 523-end | keep the inner `_clean`; incl. legs, local_leg_count, mowing/traversal legs, legs_timeline, map_projection, and the trailing static-path url field (read to confirm) |

- [ ] **Step 1: Add the five `_summary_*` helpers** above `build_picked_session_summary`. Each: take the inputs its section reads, build a LOCAL `out: dict[str, Any] = {}` (or `d`), paste the section body VERBATIM writing into that local dict, `return` it. Drop ONLY the two `m2_per_pct` lines (placeholder + compute). `_summary_trail_legs` takes `map_projection` (it sets `out["map_projection"] = map_projection`).

- [ ] **Step 2: Replace the body of `build_picked_session_summary` with the orchestrator**
Keep the signature + docstring. New body:
```python
    md5 = getattr(entry, "md5", None) or raw_dict.get("md5")
    out: dict[str, Any] = {}
    out.update(_summary_identity(summary, entry, picker_label, md5))
    out.update(_summary_coverage_efficiency(summary, raw_dict))
    out.update(_summary_energy_time(raw_dict, summary))
    out.update(_summary_diagnostics(summary, raw_dict))
    out["settings_snapshot"] = _normalise_settings_snapshot(raw_dict.get("settings_snapshot"))
    out.update(_summary_trail_legs(raw_dict, summary, map_projection))
    # Cross-section: needs charge_used_pct (energy) + area (coverage).
    area = out.get("area_mowed_m2") or 0.0
    out["m2_per_pct"] = (area / out["charge_used_pct"]) if out.get("charge_used_pct", 0) > 0 and area else None
    return out
```
Preserve the original section ORDER via the update() order above. Verify the `m2_per_pct` expression matches the original (`if out["charge_used_pct"] > 0 and area`).

- [ ] **Step 3: Run characterization + picked-session + full suite**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_picked_session.py -q` → all pass (incl. the T1 characterization test — the dict must be byte-identical).
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests -q` → same count as after T2, no regressions.

- [ ] **Step 4: Confirm the orchestrator shape**
`grep -nE "def build_picked_session_summary|def _summary_" custom_components/dreame_a2_mower/session_card.py` → the 5 helpers above the orchestrator; eyeball that `build_picked_session_summary` is now the ~12-line driver (no inline section logic).

- [ ] **Step 5: Commit**
```bash
git add custom_components/dreame_a2_mower/session_card.py
git commit -m "audit-b4c: split build_picked_session_summary into 5 section helpers + thin orchestrator"
```

---

## Self-Review

**Spec coverage:** `_png.py` with both helpers + 8 encode sites + 2 view responses → T2 ✓; session_card 5-helper split + orchestrator m2_per_pct → T3 ✓; characterization-first → T1 ✓; png_response Pragma nuance handled via `extra_headers` ✓.
**Placeholder scan:** the only "paste actual values" is the T1 characterization baseline (a capture step, fully specified). All other code is complete.
**Type/name consistency:** `encode_png`/`png_response` signatures consistent across T2; `_summary_*` helper names + the orchestrator merge order consistent in T3; m2_per_pct expression matches the original.
**Risk:** T1 must pass on current code first (else baseline is wrong). T3's only non-mechanical bit is the cross-section m2_per_pct (centralised in the orchestrator) — the characterization test guards it.
