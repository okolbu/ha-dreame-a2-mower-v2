// Dreame A2 LiDAR Card — pure-WebGL point-cloud viewer with optional
// 2D-map underlay and live splat-size slider.
//
// Consumes the `.pcd` at /api/dreame_a2_mower/lidar/latest.pcd, renders
// with `gl.POINTS` and an orbit camera. Optionally textures a quad at
// Z=0 from the base-map PNG (`camera.dreame_a2_mower_map`) so the lawn
// shows under the 3D points. No external libraries — raw WebGL 1.0
// with ~40 LOC of mat4 helpers + ~30 LOC PCD parser.
//
// Usage (Lovelace YAML):
//   - url: /dreame_a2_mower/dreame-a2-lidar-card.js
//     type: module
//   cards:
//     - type: custom:dreame-a2-lidar-card
//       # All optional:
//       # point_size: 3            (default 2.5; live slider overrides)
//       # background: '#111'       (default black)
//       # url: /api/dreame_a2_mower/lidar/latest.pcd
//       # show_map: true           (default false)
//       # map_entity: camera.dreame_a2_mower_map
//
// Controls: drag to orbit, wheel to zoom. Bottom controls: slider for
// splat size (1-12 px), toggle for map underlay.
//
// Feasibility write-up: docs/research/webgl-lidar-card-feasibility.md

const VERTEX_SRC = `
  attribute vec3 aPos;
  attribute vec4 aColor;
  uniform mat4 uMVP;
  uniform float uPointSize;
  varying vec4 vColor;
  void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    // Direct pixel size — no distance attenuation. Clip-space w at
    // default zoom is ~O(scene radius), which made previous
    // uPointSize / w formula clamp to the minimum 1 px regardless of
    // slider value. Plain uPointSize matches what the slider's
    // numeric readout promises.
    gl_PointSize = clamp(uPointSize, 1.0, 48.0);
    // PCL packs rgb as 0x00RRGGBB. Little-endian memory layout is
    // [B, G, R, 0]; WebGL reads that as (B, G, R, 0). Swizzle to RGB.
    vColor = vec4(aColor.b, aColor.g, aColor.r, 1.0);
  }
`;

const FRAGMENT_SRC = `
  precision mediump float;
  varying vec4 vColor;
  uniform float uSoftEdge;
  void main() {
    vec2 d = gl_PointCoord - vec2(0.5);
    float r2 = dot(d, d);
    if (r2 > 0.25) discard;
    // Hard-edge circle when uSoftEdge=0 (crisp dots at small sizes).
    // Soft falloff when uSoftEdge=1 (alpha fades from centre to edge,
    // so overlapping large splats blend into a pseudo-surface look).
    float alpha = mix(1.0, 1.0 - smoothstep(0.1, 0.25, r2), uSoftEdge);
    gl_FragColor = vec4(vColor.rgb, alpha);
  }
`;

// --- Textured-quad shaders for the optional map underlay ---
const QUAD_VERTEX_SRC = `
  attribute vec3 aPos;
  attribute vec2 aUV;
  uniform mat4 uMVP;
  varying vec2 vUV;
  void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    vUV = aUV;
  }
`;

const QUAD_FRAGMENT_SRC = `
  precision mediump float;
  varying vec2 vUV;
  uniform sampler2D uTex;
  uniform float uAlpha;
  uniform float uDesat;
  void main() {
    vec4 c = texture2D(uTex, vUV);
    // Desaturate towards luma so the underlay reads as background
    // rather than competing with the coloured ground points (both
    // naturally end up green otherwise). uDesat=0 keeps original
    // colour; 1 fully monochrome.
    float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    vec3 rgb = mix(c.rgb, vec3(luma), uDesat);
    gl_FragColor = vec4(rgb, c.a * uAlpha);
  }
`;

// --------------- mat4 helpers ---------------

function mat4Perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  const m = new Float32Array(16);
  m[0] = f / aspect; m[5] = f;
  m[10] = (far + near) * nf; m[11] = -1;
  m[14] = 2 * far * near * nf;
  return m;
}

function mat4LookAt(eye, target, up) {
  const [ex, ey, ez] = eye;
  const [tx, ty, tz] = target;
  let zx = ex - tx, zy = ey - ty, zz = ez - tz;
  const zl = Math.hypot(zx, zy, zz);
  zx /= zl; zy /= zl; zz /= zl;
  let xx = up[1] * zz - up[2] * zy;
  let xy = up[2] * zx - up[0] * zz;
  let xz = up[0] * zy - up[1] * zx;
  const xl = Math.hypot(xx, xy, xz);
  xx /= xl; xy /= xl; xz /= xl;
  const yx = zy * xz - zz * xy;
  const yy = zz * xx - zx * xz;
  const yz = zx * xy - zy * xx;
  const m = new Float32Array(16);
  m[0] = xx; m[1] = yx; m[2] = zx; m[3] = 0;
  m[4] = xy; m[5] = yy; m[6] = zy; m[7] = 0;
  m[8] = xz; m[9] = yz; m[10] = zz; m[11] = 0;
  m[12] = -(xx * ex + xy * ey + xz * ez);
  m[13] = -(yx * ex + yy * ey + yz * ez);
  m[14] = -(zx * ex + zy * ey + zz * ez);
  m[15] = 1;
  return m;
}

function mat4Multiply(a, b) {
  const out = new Float32Array(16);
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
      out[i * 4 + j] = s;
    }
  }
  return out;
}

function compileShader(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error("shader compile: " + gl.getShaderInfoLog(s));
  }
  return s;
}

function linkProgram(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error("program link: " + gl.getProgramInfoLog(p));
  }
  return p;
}

// --------------- PCD parser ---------------

function parsePCD(buffer) {
  const headerBytes = new Uint8Array(buffer, 0, Math.min(1024, buffer.byteLength));
  const headerText = new TextDecoder("ascii").decode(headerBytes);
  const dataIdx = headerText.indexOf("DATA binary");
  if (dataIdx < 0) throw new Error("Unsupported PCD: need DATA binary");
  const nl = headerText.indexOf("\n", dataIdx);
  const bodyOffset = nl + 1;
  const pointsMatch = headerText.match(/\nPOINTS\s+(\d+)/);
  if (!pointsMatch) throw new Error("PCD header missing POINTS");
  const points = parseInt(pointsMatch[1], 10);
  const fieldsMatch = headerText.match(/\nFIELDS\s+([^\n]+)/);
  const fields = fieldsMatch ? fieldsMatch[1].trim().split(/\s+/) : [];
  const hasRGB = fields.indexOf("rgb") >= 0;
  const bpp = hasRGB ? 16 : 12;
  if (buffer.byteLength < bodyOffset + points * bpp) {
    throw new Error(`PCD truncated: body short`);
  }
  return { points, bpp, bodyOffset, hasRGB };
}

function computeStats(buffer, bodyOffset, bpp, n) {
  const view = new DataView(buffer);
  let sx = 0, sy = 0, sz = 0;
  let minx = Infinity, maxx = -Infinity;
  let miny = Infinity, maxy = -Infinity;
  let minz = Infinity, maxz = -Infinity;
  for (let i = 0; i < n; i++) {
    const o = bodyOffset + i * bpp;
    const x = view.getFloat32(o, true);
    const y = view.getFloat32(o + 4, true);
    const z = view.getFloat32(o + 8, true);
    sx += x; sy += y; sz += z;
    if (x < minx) minx = x; if (x > maxx) maxx = x;
    if (y < miny) miny = y; if (y > maxy) maxy = y;
    if (z < minz) minz = z; if (z > maxz) maxz = z;
  }
  return {
    centroid: [sx / n, sy / n, sz / n],
    bbox: [[minx, miny, minz], [maxx, maxy, maxz]],
    radius: Math.max(maxx - minx, maxy - miny, maxz - minz) / 2,
  };
}

// --------------- Card element ---------------

class DreameA2LidarCard extends HTMLElement {
  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._loaded = false;
    this._gl = null;
    this._pointProgram = null;
    this._quadProgram = null;
    this._pointVBO = null;
    this._quadVBO = null;
    this._mapTex = null;
    this._mapTexReady = false;
    this._mapQuadWorld = null; // [[x0,y0],[x1,y1]] in world metres
    this._nPoints = 0;
    this._centroid = [0, 0, 0];
    this._radius = 1;
    this._pointSize = 2.5;
    this._showMap = false;
    this._mapAlpha = 0.85;
    this._yaw = Math.PI / 4;
    this._pitch = Math.PI / 4;
    this._distance = 0;
    this._dragging = false;
    this._lastX = 0;
    this._lastY = 0;
    this._dpr = window.devicePixelRatio || 1;
  }

  setConfig(config) {
    this._config = config || {};
    // Priority for each setting: YAML config wins (user's explicit
    // choice) → saved localStorage (last in-card tweak) → sensible
    // default.
    const saved = this._loadSaved();
    const pick = (cfgKey, savedKey, dflt) =>
      this._config[cfgKey] !== undefined
        ? this._config[cfgKey]
        : saved[savedKey] !== undefined
        ? saved[savedKey]
        : dflt;

    this._pointSize = Number(pick("point_size", "pointSize", 2.5));
    this._showMap = Boolean(pick("show_map", "showMap", false));
    this._mapZ = Number(pick("map_z", "mapZ", 0.0));
    // Default both flips ON — user-verified 2026-04-19 on g2408: the
    // PCD is in the mower's native frame which matches the FLIPPED
    // rendering of the base map PNG (our `_build_map_from_cloud_data`
    // applies X + Y midline reflections; see
    // docs/research/cloud-map-geometry.md). calibration_points
    // themselves come from the renderer's un-flipped Point.to_img,
    // so we need the UVs flipped in BOTH axes to compensate.
    this._mapFlipX = Boolean(pick("map_flip_x", "mapFlipX", true));
    this._mapFlipY = Boolean(pick("map_flip_y", "mapFlipY", true));
    // Soft-edge splat factor: 0 = hard-edged circles, 1 = soft fade.
    // Soft fade makes large splats blend into a pseudo-surface look
    // rather than showing as discrete fuzzy balls. Default soft.
    this._softEdge = Number(pick("soft_edge", "softEdge", 1.0));
    // Underlay desaturation — default 1.0 (fully monochrome) so the
    // background lawn-green doesn't blend with the PCD's ground-green.
    this._mapDesat = Number(pick("map_desat", "mapDesat", 1.0));
    // Whether the Z slider was explicitly set by the user — if so,
    // skip the bbox-min-Z auto-default below.
    this._mapZExplicit = this._config.map_z !== undefined || saved.mapZ !== undefined;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .wrap { position: relative; width: 100%; aspect-ratio: 1 / 1; background: ${this._config.background || "#111"}; border-radius: var(--ha-card-border-radius, 12px); overflow: hidden; }
        canvas { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
        canvas:active { cursor: grabbing; }
        .status { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #bbb; font-family: var(--primary-font-family, sans-serif); font-size: 14px; pointer-events: none; }
        .status.err { color: #f88; }
        .hint { position: absolute; bottom: 8px; right: 10px; font-size: 11px; color: #888; font-family: monospace; pointer-events: none; }
        .timestamp { position: absolute; bottom: 8px; left: 10px; font-size: 11px; color: #888; font-family: monospace; pointer-events: none; }
        .controls {
          position: absolute; top: 8px; left: 8px; display: flex; flex-direction: column; gap: 6px;
          background: rgba(20, 20, 20, 0.55); padding: 6px 10px; border-radius: 8px;
          font-family: var(--primary-font-family, sans-serif); font-size: 12px; color: #ddd;
          backdrop-filter: blur(2px);
        }
        .controls label { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
        .controls input[type=range] { width: 110px; }
        .controls input[type=checkbox] { margin: 0; }
        .map-controls { display: none; flex-direction: column; gap: 4px; margin-left: 18px; }
        .map-controls.active { display: flex; }
        .map-controls .row { display: flex; gap: 8px; align-items: center; font-size: 11px; }
        .map-controls input[type=range] { width: 90px; }
      </style>
      <ha-card>
        <div class="wrap">
          <canvas></canvas>
          <div class="controls">
            <label>Splat
              <input type="range" class="splat" min="1" max="40" step="0.5" value="${this._pointSize}">
              <span class="splat-val">${this._pointSize}</span>
            </label>
            <label>
              <input type="checkbox" class="soft" ${this._softEdge >= 0.5 ? "checked" : ""}>
              Soft splats
            </label>
            <label>
              <input type="checkbox" class="showmap" ${this._showMap ? "checked" : ""}>
              Map underlay
            </label>
            <div class="map-controls ${this._showMap ? "active" : ""}">
              <div class="row">Z
                <input type="range" class="mapz" min="-5" max="5" step="0.1" value="${this._mapZ}">
                <span class="mapz-val">${this._mapZ.toFixed(1)}</span>
              </div>
              <div class="row">
                <label><input type="checkbox" class="flipx" ${this._mapFlipX ? "checked" : ""}> Flip X</label>
                <label><input type="checkbox" class="flipy" ${this._mapFlipY ? "checked" : ""}> Flip Y</label>
              </div>
            </div>
          </div>
          <div class="status">Loading…</div>
          <div class="hint"></div>
          <div class="timestamp"></div>
        </div>
      </ha-card>
    `;
    this._canvas = this.shadowRoot.querySelector("canvas");
    this._status = this.shadowRoot.querySelector(".status");
    this._hint = this.shadowRoot.querySelector(".hint");
    this._timestamp = this.shadowRoot.querySelector(".timestamp");
    this._splat = this.shadowRoot.querySelector(".splat");
    this._splatVal = this.shadowRoot.querySelector(".splat-val");
    this._softCb = this.shadowRoot.querySelector(".soft");
    this._showMapCb = this.shadowRoot.querySelector(".showmap");
    this._mapControls = this.shadowRoot.querySelector(".map-controls");
    this._mapZInput = this.shadowRoot.querySelector(".mapz");
    this._mapZVal = this.shadowRoot.querySelector(".mapz-val");
    this._flipXCb = this.shadowRoot.querySelector(".flipx");
    this._flipYCb = this.shadowRoot.querySelector(".flipy");
    this._bindInput();
  }

  set hass(hass) {
    this._hass = hass;
    // Guard the fetch behind three conditions so navigation races don't
    // leave the card blank:
    //   1. Config has been applied (setConfig built the shadow DOM).
    //   2. Shadow DOM is live (attached; not in the middle of teardown).
    //   3. We haven't already started the initial fetch.
    // Without this guard HA's occasional "set hass before setConfig" path
    // (seen when a dashboard is restored after navigation) triggered a
    // _setStatus() call against `undefined` DOM refs, the exception was
    // caught silently, and the card sat blank until a browser refresh.
    if (!this._loaded && this._config && this._status) {
      this._fetchAndRender();
    }
  }

  connectedCallback() {
    // HA recycles custom elements across view navigations — the element
    // may be disconnected when the user leaves the Mower dashboard and
    // re-attached on return. `_startRenderLoop` self-terminates on
    // `isConnected === false`, so it won't run after disconnection;
    // re-kick it here whenever the card comes back into the DOM if we
    // already have a point cloud loaded. Also retries the initial fetch
    // if it never ran (handles the rare set-hass-before-setConfig race).
    if (this._gl && this._nPoints > 0) {
      this._startRenderLoop();
    } else if (!this._loaded && this._hass && this._config && this._status) {
      this._fetchAndRender();
    }
  }

  getCardSize() { return 6; }

  // --- localStorage persistence ---
  // One shared key regardless of how many card instances there are —
  // users typically only have one LiDAR card on their dashboard.
  // If that assumption breaks we can key by `this._config.entity`
  // later. Wrapped in try/except so private-browsing / disabled
  // storage don't crash the card.
  _storageKey() { return "dreame-a2-lidar-card.settings.v1"; }
  _loadSaved() {
    try {
      const raw = window.localStorage.getItem(this._storageKey());
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }
  _saveSaved() {
    try {
      window.localStorage.setItem(
        this._storageKey(),
        JSON.stringify({
          pointSize: this._pointSize,
          softEdge: this._softEdge,
          showMap: this._showMap,
          mapZ: this._mapZ,
          mapFlipX: this._mapFlipX,
          mapFlipY: this._mapFlipY,
        })
      );
      // From now on the user has explicitly picked a Z, so don't
      // auto-reset it to bbox-min-Z on next PCD load.
      this._mapZExplicit = true;
    } catch (_) {
      /* ignore */
    }
  }

  async _fetchAndRender() {
    if (!this._hass) return;
    this._loaded = true;
    try {
      const token = this._hass.auth?.data?.access_token;
      if (!token) throw new Error("No HA access token");
      const url = this._config.url || "/api/dreame_a2_mower/lidar/latest.pcd";
      this._setStatus("Fetching point cloud…");
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // `Last-Modified` comes from HA's static-path handler: it reflects
      // the PCD file's mtime on disk, which = the moment the integration
      // archived the scan after the mower's s99p20 OSS push (see
      // docs/research/g2408-protocol.md §7.3b). Show it bottom-left so
      // users have a clear visual cue whether the 3D view is current.
      const lm = r.headers.get("last-modified");
      if (lm && this._timestamp) {
        const d = new Date(lm);
        if (!isNaN(d)) {
          this._timestamp.textContent = `scan: ${d.toLocaleString()}`;
        } else {
          this._timestamp.textContent = `scan: ${lm}`;
        }
      }
      const buf = await r.arrayBuffer();
      this._setStatus("Parsing…");
      const meta = parsePCD(buf);
      this._nPoints = meta.points;
      const stats = computeStats(buf, meta.bodyOffset, meta.bpp, meta.points);
      this._centroid = stats.centroid;
      this._radius = Math.max(stats.radius, 1);
      this._bbox = stats.bbox;
      // When the user hasn't explicitly configured `map_z`, default to
      // the point cloud's bbox-min-Z so the map plane lands at ground
      // level on the first render instead of Z=0 (which typically
      // floats above the grass by ~1 m on this device).
      if (!this._mapZExplicit) {
        this._mapZ = stats.bbox[0][2];
        if (this._mapZInput) {
          this._mapZInput.value = this._mapZ.toFixed(1);
          this._mapZVal.textContent = this._mapZ.toFixed(1);
        }
      }
      this._distance = this._radius * 2.5;
      this._hint.textContent = `${meta.points.toLocaleString()} pts · r=${this._radius.toFixed(1)}m`;
      this._setStatus("");
      this._initGL(buf, meta);
      if (this._showMap) await this._loadMapUnderlay();
      this._startRenderLoop();
    } catch (ex) {
      console.error("[dreame-a2-lidar-card]", ex);
      this._setStatus(`Error: ${ex.message}`, true);
    }
  }

  _setStatus(msg, isError = false) {
    this._status.textContent = msg;
    this._status.classList.toggle("err", isError);
    this._status.style.display = msg ? "flex" : "none";
  }

  _initGL(buffer, meta) {
    const gl = this._canvas.getContext("webgl", { antialias: true, premultipliedAlpha: true });
    if (!gl) throw new Error("WebGL not available");
    this._gl = gl;
    gl.clearColor(0, 0, 0, 0);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // Point-cloud program
    const pVs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SRC);
    const pFs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC);
    this._pointProgram = linkProgram(gl, pVs, pFs);
    const body = new Uint8Array(buffer, meta.bodyOffset, meta.points * meta.bpp);
    this._pointVBO = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this._pointVBO);
    gl.bufferData(gl.ARRAY_BUFFER, body, gl.STATIC_DRAW);
    this._pointLocs = {
      aPos: gl.getAttribLocation(this._pointProgram, "aPos"),
      aColor: gl.getAttribLocation(this._pointProgram, "aColor"),
      uMVP: gl.getUniformLocation(this._pointProgram, "uMVP"),
      uPointSize: gl.getUniformLocation(this._pointProgram, "uPointSize"),
      uSoftEdge: gl.getUniformLocation(this._pointProgram, "uSoftEdge"),
    };
    this._pointBPP = meta.bpp;
    this._pointHasRGB = meta.hasRGB;

    // Quad program (for map underlay)
    const qVs = compileShader(gl, gl.VERTEX_SHADER, QUAD_VERTEX_SRC);
    const qFs = compileShader(gl, gl.FRAGMENT_SHADER, QUAD_FRAGMENT_SRC);
    this._quadProgram = linkProgram(gl, qVs, qFs);
    this._quadLocs = {
      aPos: gl.getAttribLocation(this._quadProgram, "aPos"),
      aUV: gl.getAttribLocation(this._quadProgram, "aUV"),
      uMVP: gl.getUniformLocation(this._quadProgram, "uMVP"),
      uTex: gl.getUniformLocation(this._quadProgram, "uTex"),
      uAlpha: gl.getUniformLocation(this._quadProgram, "uAlpha"),
      uDesat: gl.getUniformLocation(this._quadProgram, "uDesat"),
    };
  }

  async _loadMapUnderlay() {
    try {
      const entityId = this._config.map_entity || "camera.dreame_a2_mower_map";
      const state = this._hass.states?.[entityId];
      if (!state) throw new Error(`${entityId} not found`);
      const calib = state.attributes?.calibration_points;
      const token = this._hass.auth?.data?.access_token;
      if (!calib || calib.length < 3) {
        console.warn("[dreame-a2-lidar-card] no calibration_points on", entityId);
        return;
      }

      // Fetch the PNG and capture its pixel dimensions so we can turn
      // the four image corners into world-metre quad corners.
      const mapUrl = `/api/camera_proxy/${entityId}?token=${state.attributes?.access_token || ""}`;
      const r = await fetch(mapUrl, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`map HTTP ${r.status}`);
      const blob = await r.blob();
      const bmp = await createImageBitmap(blob);

      const gl = this._gl;
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bmp);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this._mapTex = tex;

      // calibration_points: list of 3 entries `{mower:{x,y}, map:{x,y}}`.
      // `mower.*` is mower-frame mm (includes all the
      // reflections/rotations the base renderer applied); `map.*` is
      // pixels in the served PNG. Fit the affine mower_mm → pixel:
      //   px = a*x + b*y + tx
      //   py = c*x + d*y + ty
      // then invert to pixel → mower_mm, and transform the 4 PNG
      // corners to get the quad's world coords.
      const [p0, p1, p2] = calib;
      const x0 = p0.mower.x, y0 = p0.mower.y;
      const x1 = p1.mower.x, y1 = p1.mower.y;
      const x2 = p2.mower.x, y2 = p2.mower.y;
      const u0 = p0.map.x, v0 = p0.map.y;
      const u1 = p1.map.x, v1 = p1.map.y;
      const u2 = p2.map.x, v2 = p2.map.y;
      const det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
      if (Math.abs(det) < 1e-9) throw new Error("calib colinear");
      const a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det;
      const b = ((x1 - x0) * (u2 - u0) - (x2 - x0) * (u1 - u0)) / det;
      const c = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det;
      const d = ((x1 - x0) * (v2 - v0) - (x2 - x0) * (v1 - v0)) / det;
      const tx = u0 - a * x0 - b * y0;
      const ty = v0 - c * x0 - d * y0;
      // Invert the 2x2 to get pixel → mower_mm
      const idet = 1 / (a * d - b * c);
      const inv_a = d * idet, inv_b = -b * idet;
      const inv_c = -c * idet, inv_d = a * idet;
      const px2mm = (px, py) => {
        const ox = px - tx, oy = py - ty;
        return [inv_a * ox + inv_b * oy, inv_c * ox + inv_d * oy];
      };

      const W = bmp.width, H = bmp.height;
      // Quad corners (world metres): translate pixel corners through
      // the inverse affine and divide by 1000 (mm → m).
      const cornersPx = [[0, 0], [W, 0], [W, H], [0, H]];
      const cornersM = cornersPx.map(([px, py]) => {
        const [mmx, mmy] = px2mm(px, py);
        return [mmx / 1000, mmy / 1000];
      });

      // Cache the four mower-frame corners so the Z slider and flip
      // checkboxes can rebuild the quad cheaply without re-solving
      // the affine.
      this._mapCorners = cornersM;
      this._quadVBO = gl.createBuffer();
      this._rebuildMapQuad();
      this._mapTexReady = true;
    } catch (ex) {
      console.warn("[dreame-a2-lidar-card] map underlay failed:", ex);
      this._showMap = false;
      if (this._showMapCb) this._showMapCb.checked = false;
    }
  }

  _bindInput() {
    this._canvas.addEventListener("mousedown", (e) => {
      this._dragging = true;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
    });
    window.addEventListener("mouseup", () => { this._dragging = false; });
    window.addEventListener("mousemove", (e) => {
      if (!this._dragging) return;
      const dx = e.clientX - this._lastX;
      const dy = e.clientY - this._lastY;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
      this._yaw -= dx * 0.01;
      this._pitch -= dy * 0.01;
      this._pitch = Math.max(-Math.PI / 2 + 0.05, Math.min(Math.PI / 2 - 0.05, this._pitch));
    });
    this._canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = Math.exp(e.deltaY * 0.001);
      this._distance = Math.min(this._radius * 8, Math.max(this._radius * 0.2, this._distance * f));
    }, { passive: false });

    this._splat.addEventListener("input", () => {
      this._pointSize = parseFloat(this._splat.value);
      this._splatVal.textContent = this._pointSize;
      this._saveSaved();
    });

    this._softCb.addEventListener("change", () => {
      this._softEdge = this._softCb.checked ? 1.0 : 0.0;
      this._saveSaved();
    });

    this._showMapCb.addEventListener("change", async () => {
      this._showMap = this._showMapCb.checked;
      this._mapControls.classList.toggle("active", this._showMap);
      if (this._showMap && !this._mapTexReady && this._gl) {
        await this._loadMapUnderlay();
      }
      this._saveSaved();
    });

    this._mapZInput.addEventListener("input", () => {
      this._mapZ = parseFloat(this._mapZInput.value);
      this._mapZVal.textContent = this._mapZ.toFixed(1);
      this._rebuildMapQuad();
      this._saveSaved();
    });
    this._flipXCb.addEventListener("change", () => {
      this._mapFlipX = this._flipXCb.checked;
      this._rebuildMapQuad();
      this._saveSaved();
    });
    this._flipYCb.addEventListener("change", () => {
      this._mapFlipY = this._flipYCb.checked;
      this._rebuildMapQuad();
      this._saveSaved();
    });
  }

  _rebuildMapQuad() {
    // Re-upload the quad VBO with the currently-selected Z + UV flips.
    // Uses cached inverse-calibration output. Cheap — 6 vertices.
    if (!this._mapCorners || !this._gl || !this._quadVBO) return;
    const [Atl, Atr, Abr, Abl] = this._mapCorners;
    const z = this._mapZ;
    // UV assignment: (0,0) TL by default. `map_flip_x` swaps U, `map_flip_y` swaps V.
    const u0 = this._mapFlipX ? 1 : 0;
    const u1 = this._mapFlipX ? 0 : 1;
    const v0 = this._mapFlipY ? 1 : 0;
    const v1 = this._mapFlipY ? 0 : 1;
    const data = new Float32Array([
      Atl[0], Atl[1], z, u0, v0,
      Atr[0], Atr[1], z, u1, v0,
      Abr[0], Abr[1], z, u1, v1,
      Atl[0], Atl[1], z, u0, v0,
      Abr[0], Abr[1], z, u1, v1,
      Abl[0], Abl[1], z, u0, v1,
    ]);
    this._gl.bindBuffer(this._gl.ARRAY_BUFFER, this._quadVBO);
    this._gl.bufferData(this._gl.ARRAY_BUFFER, data, this._gl.STATIC_DRAW);
  }

  _startRenderLoop() {
    let lastResize = 0;
    const tick = () => {
      if (!this.isConnected) return;
      const now = performance.now();
      if (now - lastResize > 250) {
        this._resizeIfNeeded();
        lastResize = now;
      }
      this._draw();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  _resizeIfNeeded() {
    const c = this._canvas;
    const w = (c.clientWidth * this._dpr) | 0;
    const h = (c.clientHeight * this._dpr) | 0;
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
      this._gl.viewport(0, 0, w, h);
    }
  }

  _draw() {
    const gl = this._gl;
    if (!gl) return;
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const [cx, cy, cz] = this._centroid;
    const ex = cx + this._distance * Math.cos(this._pitch) * Math.cos(this._yaw);
    const ey = cy + this._distance * Math.cos(this._pitch) * Math.sin(this._yaw);
    const ez = cz + this._distance * Math.sin(this._pitch);
    const aspect = this._canvas.width / Math.max(this._canvas.height, 1);
    const proj = mat4Perspective(Math.PI / 3, aspect, 0.1, this._radius * 40);
    const view = mat4LookAt([ex, ey, ez], this._centroid, [0, 0, 1]);
    const mvp = mat4Multiply(proj, view);

    // Draw map underlay first so point cloud depth-tests over it.
    if (this._showMap && this._mapTexReady && this._quadVBO) {
      gl.useProgram(this._quadProgram);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._quadVBO);
      const stride = 5 * 4;
      gl.enableVertexAttribArray(this._quadLocs.aPos);
      gl.vertexAttribPointer(this._quadLocs.aPos, 3, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(this._quadLocs.aUV);
      gl.vertexAttribPointer(this._quadLocs.aUV, 2, gl.FLOAT, false, stride, 12);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this._mapTex);
      gl.uniform1i(this._quadLocs.uTex, 0);
      gl.uniform1f(this._quadLocs.uAlpha, this._mapAlpha);
      gl.uniform1f(this._quadLocs.uDesat, this._mapDesat);
      gl.uniformMatrix4fv(this._quadLocs.uMVP, false, mvp);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.disableVertexAttribArray(this._quadLocs.aUV);
    }

    // Points on top (depth test keeps roof points above ground points).
    gl.useProgram(this._pointProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this._pointVBO);
    gl.enableVertexAttribArray(this._pointLocs.aPos);
    gl.vertexAttribPointer(this._pointLocs.aPos, 3, gl.FLOAT, false, this._pointBPP, 0);
    if (this._pointHasRGB) {
      gl.enableVertexAttribArray(this._pointLocs.aColor);
      gl.vertexAttribPointer(this._pointLocs.aColor, 4, gl.UNSIGNED_BYTE, true, this._pointBPP, 12);
    }
    gl.uniformMatrix4fv(this._pointLocs.uMVP, false, mvp);
    gl.uniform1f(this._pointLocs.uPointSize, this._pointSize * this._dpr);
    gl.uniform1f(this._pointLocs.uSoftEdge, this._softEdge);
    gl.drawArrays(gl.POINTS, 0, this._nPoints);
  }
}

customElements.define("dreame-a2-lidar-card", DreameA2LidarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-lidar-card",
  name: "Dreame A2 LiDAR Card",
  description: "Interactive WebGL 3D view of the mower's LiDAR point-cloud scan.",
});
