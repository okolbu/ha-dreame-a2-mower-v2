# WebGL LiDAR Card — Feasibility Assessment (2026-04-19)

Pre-implementation research for TODO A10 (interactive WebGL point-cloud Lovelace card). No code yet — this doc captures the assessment so when/if we come back to build it, we don't re-derive the decisions.

## TL;DR

~1 weekend for an alpha, ~1 week to polished. Three.js + `PCDLoader` + `OrbitControls` is the pragmatic stack; vanilla WebGL is doable but saves ~150 KB at a cost of ~1 day's development. Performance at 145k points is a non-issue on any 2020+ integrated GPU. Top risks: coordinate-frame / RGB-packing disagreements with the PNG view, and HACS+frontend-cache UX on first install.

## 1. Raw WebGL with `gl.POINTS` — minimum size

A from-scratch orbit camera + point renderer is genuinely small. Points are the simplest WebGL primitive: one `gl.drawArrays(gl.POINTS, 0, N)` call, one interleaved VBO (16 B/vertex matches the PCD row exactly), no index buffer, no lighting, no normals. `gl_PointCoord` + `discard` gives round splats almost free.

Realistic line counts for a from-scratch implementation (no libraries):

- Vertex shader: ~15 lines (MVP matrix, `gl_PointSize = uSize / gl_Position.w` for distance attenuation, pass-through color).
- Fragment shader: ~8 lines (round splat via `gl_PointCoord`, optional depth-based dim).
- JS: context + shader compile/link helpers ~60; buffer upload ~10; mat4 utilities (perspective, lookAt, multiply, rotate) ~80 inline or ~2 KB via `gl-matrix`; orbit camera (mouse/touch drag = yaw/pitch, wheel = zoom, shift-drag = pan) ~80; render loop ~15.

**~250–300 lines of hand-written JS + ~25 lines of GLSL** for a credible first version. MDN's tutorial ([Getting started with WebGL](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/Tutorial/Getting_started_with_WebGL) / [Creating 3D objects](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/Tutorial/Creating_3D_objects_using_WebGL)) covers everything; the cube example translates directly — change `gl.TRIANGLES` to `gl.POINTS`, drop the index buffer.

## 2. PCD binary parsing

Hand-rolling is trivial. The header is a fixed-form ASCII block (`VERSION`, `FIELDS x y z rgb`, `SIZE 4 4 4 4`, `TYPE F F F U`, `POINTS N`, `DATA binary`). Split on the first `\nDATA binary\n` → rest is raw bytes. For 145k × 16 B = 2.32 MB, a single `new Float32Array(buf, headerLen, N*4)` view suffices and uploads directly to the VBO; the vertex shader unpacks the packed uint32 RGB via `floor(mod(v, 256.0))/255.0`.

**~40 lines**: `TextDecoder` on the first 512 bytes for header, `DataView`/typed-array for body. No library needed. Reference: [three.js `PCDLoader`](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/loaders/PCDLoader.js) (~400 LOC, MIT) — handles compressed binary too but we don't need that.

## 3. Three.js vs vanilla tradeoff

Three.js min+gzip is ~170 KB; with `PCDLoader` + `OrbitControls` + `Points` + `PointsMaterial` tree-shaken you realistically land at **130–180 KB gzipped**, not the 600 KB raw figure. Three.js's tree-shaking is limited by core side effects.

| | Three.js | Vanilla |
|---|---|---|
| Time to prototype | 1–2 h | 1–2 days |
| Payload | 130–180 KB gz | 8–12 KB gz |
| Free quality | MSAA, touch, damping, DPR | roll your own |

For a single-purpose HACS card, **Three.js** is the pragmatic pick. 150 KB one-time download is invisible on LAN; the dev-time savings match the weekend budget.

## 4. Performance at 145k points

Trivially 60 fps on any 2020+ GPU. One draw call, ~2 MB VBO, no overdraw. [Potree](https://potree.github.io/) renders tens of millions of points at 60 fps in WebGL — we're three orders of magnitude under that.

- 2020 laptop (Iris Xe / M1): trivial, 144 fps if vsync allows.
- Raspberry Pi 4 (VideoCore VI): 30–60 fps; cap `gl_PointSize` ≤ 3 px to stay fill-rate-friendly.
- Mid-range phone: fine; main risk is thermal throttling over minutes.

Gotchas:
- `gl_PointSize` max is implementation-defined in WebGL 1 (typically 64); clamp in-shader.
- Round splats via `discard` disable early-Z on some mobile GPUs — negligible at this scale.
- Retina DPR multiplies fragment work 4×; scale point size inversely.

## 5. Home Assistant custom card integration

Per the [custom-card docs](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/):

- Card is an `HTMLElement` subclass registered with `customElements.define("dreame-lidar-card", …)`.
- HA sets `this.hass` whenever state changes.
- Distribution: single JS file dropped in `/config/www/` and registered as a Lovelace resource. HACS supports via `hacs.json` + release asset.
- **Auth**: use `this.hass.auth.data.access_token` in a `Bearer` header — HA refreshes it automatically, no long-lived token needed.
  ```js
  const r = await fetch(url, {
    headers: { Authorization: `Bearer ${this.hass.auth.data.access_token}` }
  });
  const buf = await r.arrayBuffer();
  ```

Pitfalls:
- Card may be constructed multiple times on re-render — cache the ArrayBuffer on a module-level `Map` keyed by URL.
- HA frontend and add-ons can be different-origin in some configs — CORS headers must come from our `HomeAssistantView`.
- Ship as `type: module`; frontend supports ES modules natively, no transpile needed.

## 6. Recommendation

**~1 weekend alpha, ~1 week polished.** Three.js path gets a working card in an afternoon; remaining time is HA glue, auto-refresh on new scans, responsive sizing, theming against HA's dark/light backgrounds.

### Top unknowns that could blow the estimate

1. **Coordinate-frame mismatch.** Our existing top-down PNG went through half a dozen reflect/rotate passes before it matched the app. The 3D card's viewing basis might need similar tuning before it looks "right" — add hours, not days.
2. ~~**Color channel encoding.** Packed `rgb` uint32 has platform-endianness history. `0x00RRGGBB` vs `0x00BBGGRR` will produce blue trees until diagnosed. Cheap fix once spotted, can eat half a day of confused testing.~~ **Resolved at implementation time 2026-04-19**: the `.bgr` swizzle in the vertex shader (commit `03de4af`) works out of the box on this g2408 firmware. Little-endian byte order in the VBO = `[B, G, R, 0]` at each 4-byte rgb slot; WebGL reads that as `aColor = (B, G, R, 0)/255`; shader swizzles to `.bgr` = `(R, G, B)`. User confirmed colours render right-way-up.
3. **HACS + frontend resource reload UX.** First-time installs trip on browser cache; users will report "card not found" until hard-reload. Mitigate with a version query string on the resource URL.

### Minimum-viable alpha deliverable

- Single JS file registered as `custom:dreame-lidar-card`
- Fetches `/api/dreame_a2_mower/lidar/latest.pcd` with session bearer token on mount + on `hass` entity-change for configurable scan-id sensor
- Mouse drag = orbit, wheel = zoom (no touch yet)
- Per-point color from PCD RGB, fixed point size
- Error state on fetch fail; loading spinner during parse
- No config UI — YAML-only `type: custom:dreame-lidar-card`, `entity: sensor.dreame_a2_mower_archived_lidar_scans`

Everything beyond that (touch, screenshot, color-by-height, measurement, multi-scan diff) is v1+ and not required to validate the approach.

## Sources

- [MDN — Getting started with WebGL](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/Tutorial/Getting_started_with_WebGL)
- [MDN — Creating 3D objects using WebGL](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/Tutorial/Creating_3D_objects_using_WebGL)
- [PCD file format spec (PCL)](https://pointclouds.org/documentation/tutorials/pcd_file_format.html)
- [three.js `PCDLoader` source](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/loaders/PCDLoader.js)
- [three.js PCD example](https://threejs.org/examples/webgl_loader_pcd.html)
- [Potree (million-point WebGL renderer)](https://potree.github.io/)
- [HA custom-card developer doc](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)
- [HA Authentication API](https://developers.home-assistant.io/docs/auth_api/)
