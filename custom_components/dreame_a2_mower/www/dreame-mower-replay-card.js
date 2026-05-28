// Dreame A2 Mower — Session Replay Card
//
// Animates the trail of an archived mowing session over the base map.
// Uses a fixed compression ratio (default ~200×, slider-adjustable 50–800×),
// clamped to 3–90 s of playback. Pauses (charging, rain delay) surface as
// labelled overlay windows rather than being silently skipped.
//
// Reads sensor.dreame_a2_mower_picked_session attributes:
//   legs_timeline: list[{role, start_ts, end_ts, pts:[[x_m, y_m],...]}]
//   track_first_ts, track_last_ts: int | null (session wall-clock bounds)
//   state_samples: list[[ts_unix, state_value]]  (charging code=6)
//   map_projection: { bx1_mm, by1_mm, bx2_mm, by2_mm, pixel_size_mm, width_px, height_px, dock_xy_mm? } | null
//   base_map_image_url / base_map_image_url_no_trail: str
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
    this._hass = hass;
    const state = hass.states[this._entityId];
    if (!state) {
      this._renderMissing();
      return;
    }
    // Include filename so attribute-only updates (same picker label,
    // different underlying session) also trigger a re-render. Covers
    // edge cases where state.state stays as "(pick a session)" but the
    // picked entry changed via a different path.
    const stateKey = `${state.state}|${state.last_changed}|${state.attributes.filename || ""}`;
    if (stateKey !== this._lastStateKey) {
      this._lastStateKey = stateKey;
      this._render(state);
    }
    // Re-apply render style when the trail width entity changes so the
    // new width takes effect immediately without a full re-render.
    const newWidth = this._currentTrailWidth();
    if (newWidth !== this._lastTrailWidth) {
      this._lastTrailWidth = newWidth;
      if (this._paths && this._paths.length) this._applyRenderStyle();
    }
  }

  _renderMissing() {
    this.shadowRoot.innerHTML = `
      <div style="padding:12px;">
        Picked-session entity not found — set <code>entity:</code>.
      </div>`;
  }

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

  _render(state) {
    const a = state.attributes || {};
    const proj = a.map_projection;
    // Use the no-trail base when available (replay card draws the trail via
    // animated SVG; if the base image already has the trail painted, the user
    // sees both during animation). Fall back to the with-trail URL for sessions
    // that pre-date this attribute (graceful degradation).
    const url = a.base_map_image_url_no_trail || a.base_map_image_url;
    if (!proj || !url) {
      this.shadowRoot.innerHTML = `
        <ha-card><div style="padding:12px;">
          Waiting for map projection / base image…
        </div></ha-card>`;
      return;
    }
    // Stash projection so _applyRenderStyle can reference it if needed.
    this._proj = proj;
    // Filter out single-point legs — SVG <path d="M x y"/> with any
    // stroke style still renders as a stroke-width-sized dot. Drop them
    // entirely so the animation matches the static work_log.png (Python's
    // ImageDraw.line() is a no-op for <2 points).
    //
    // stroke-linecap: butt (default; explicit here for clarity) — NOT
    // "round". With round caps, a 2-point leg of span < ~0.5m renders as
    // a fat dot too (the round caps overlap). Butt caps make short legs
    // appear as thin lines that fade into the background like PIL's
    // draw.line() rasterization does. Keep linejoin: round so longer
    // legs still join smoothly at vertices.
    //
    // legs_timeline is the single source: ordered records
    // {role, start_ts, end_ts, pts} carrying real per-leg unix timestamps.
    // Render order is the timeline order (mowing/traversal interleaved as
    // they occurred); _applyRenderStyle colours each path by its role.
    const rawTimeline = a.legs_timeline || [];
    const legSpecs = rawTimeline
      .filter(rec => rec && rec.pts && rec.pts.length >= 2
                     && (rec.role === 'mowing' || rec.role === 'traversal'))
      .map(rec => ({
        pts: rec.pts, role: rec.role,
        start_ts: rec.start_ts, end_ts: rec.end_ts,
      }));
    // Stash roles parallel to paths so _applyRenderStyle can look them up.
    this._pathRoles = legSpecs.map(s => s.role);
    this._legSpecs = legSpecs;
    const paths = legSpecs.map((s, i) => `
      <path d="${this._buildLegPathD(s.pts, proj)}"
            fill="none" stroke="rgb(220,40,40)" stroke-width="3"
            stroke-linecap="butt" stroke-linejoin="round"
            data-leg-index="${i}" />
    `).join("");
    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>
          /* The sibling static work_log picture-entity card uses
           * aspect_ratio: 1/1 + object-fit: contain, so a portrait map
           * (e.g. 637×717) is letterboxed inside a square frame with
           * whitespace on its left and right. The animated SVG card must
           * match that layout exactly, otherwise the rendered map jumps
           * in size when the user flips between static and animated. */
          .map-wrap {
            aspect-ratio: 1 / 1;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
          }
          svg {
            display: block;
            /* preserveAspectRatio="xMidYMid meet" inside a square box
             * shrinks the viewBox to fit, matching object-fit: contain. */
            max-width: 100%;
            max-height: 100%;
            width: 100%;
            height: 100%;
          }
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
        </style>
        <div class="map-wrap">
        <svg viewBox="0 0 ${proj.width_px} ${proj.height_px}"
             xmlns="http://www.w3.org/2000/svg"
             preserveAspectRatio="xMidYMid meet">
          <image href="${url}"
                 x="0" y="0"
                 width="${proj.width_px}" height="${proj.height_px}" />
          ${paths}
          <circle id="head" r="6" fill="rgb(255,140,0)" stroke="white" stroke-width="2"
                  cx="0" cy="0" visibility="hidden" />
          <text id="pause-label" x="50%" y="14" text-anchor="middle"
                font-size="13" fill="white"
                style="paint-order:stroke;stroke:black;stroke-width:3px;"
                visibility="hidden"></text>
        </svg>
        </div>
        <div class="controls">
          <button id="btn-play" title="Play">▶</button>
          <button id="btn-pause" title="Pause">⏸</button>
          <button id="btn-replay" title="Replay">↻</button>
          <button id="btn-step-back" title="Step back one segment">⏮</button>
          <button id="btn-step-fwd" title="Step forward one segment">⏭</button>
          <input id="scrub" type="range" min="0" max="1000" value="0"
                 style="flex: 1; max-width: 240px;" />
          <label style="display:flex;align-items:center;gap:4px;font-size:12px;">
            speed
            <input id="speed" type="range" min="0" max="1000" value="500"
                   style="width:90px;" />
          </label>
        </div>
      </ha-card>`;
    this._lastAttrs = a;
    this._startAnimation(a);

    // Controls are wired against a single playhead state machine
    // (_playheadMs / _isPlaying / _tick). Buttons just toggle state;
    // the rAF loop reads state every frame and updates the SVG +
    // slider accordingly.
    this.shadowRoot.getElementById("btn-play").onclick = () => {
      // If we're at the end, replaying-from-zero is the obviously-correct
      // behaviour for ▶. Otherwise resume from the current playhead.
      if (this._playheadMs >= this._totalMs) {
        this._playheadMs = 0;
      }
      this._isPlaying = true;
      this._ensureRaf();
    };
    this.shadowRoot.getElementById("btn-pause").onclick = () => {
      this._isPlaying = false;
      // Don't stop the rAF; it's harmless when idle (the tick early-
      // returns if !isPlaying and the playhead doesn't move). Stopping
      // rAF on pause would break the "slider drag while paused" case
      // because we still need to repaint after each oninput.
    };
    this.shadowRoot.getElementById("btn-replay").onclick = () => {
      this._playheadMs = 0;
      this._isPlaying = true;
      this._ensureRaf();
    };
    this.shadowRoot.getElementById("btn-step-back").onclick = () =>
      this._stepSegment(-1);
    this.shadowRoot.getElementById("btn-step-fwd").onclick = () =>
      this._stepSegment(1);
    // Slider becomes a true bidirectional control:
    //  - oninput (user drags): set _playheadMs, suppress slider self-
    //    update via _userDraggingScrub while the pointer is held.
    //  - rAF tick (in _tick): writes back into the slider so it
    //    follows playback automatically.
    const scrub = this.shadowRoot.getElementById("scrub");
    scrub.oninput = (e) => {
      const frac = parseInt(e.target.value, 10) / 1000;
      this._playheadMs = frac * (this._totalMs || 1);
      this._renderAt(this._playheadMs);
    };
    const onPointerDown = () => { this._userDraggingScrub = true; };
    const onPointerUp   = () => { this._userDraggingScrub = false; };
    // pointerdown/up covers mouse + touch + pen. Fall back to mouse
    // events for older browsers via the same handler.
    scrub.onpointerdown = onPointerDown;
    scrub.onpointerup   = onPointerUp;
    scrub.onmousedown   = onPointerDown;
    scrub.onmouseup     = onPointerUp;
    scrub.ontouchstart  = onPointerDown;
    scrub.ontouchend    = onPointerUp;

    const speed = this.shadowRoot.getElementById("speed");
    if (speed) {
      const saved = parseFloat(localStorage.getItem("dreame_a2_mower_replay_speed"));
      if (Number.isFinite(saved)) speed.value = String(Math.round(saved * 1000));
      speed.oninput = () => {
        localStorage.setItem(
          "dreame_a2_mower_replay_speed",
          String(parseInt(speed.value, 10) / 1000),
        );
        const frac = this._totalMs ? this._playheadMs / this._totalMs : 0;
        this._startAnimation(this._lastAttrs || {});
        this._playheadMs = frac * (this._totalMs || 1);
        this._renderAt(this._playheadMs);
      };
    }
  }

  _startAnimation(a) {
    // Cancel any rAF from a previous session/render. _isPlaying gates
    // playhead advancement; clearing _rafHandle and re-requesting on
    // the next _ensureRaf is the clean teardown.
    if (this._rafHandle) {
      cancelAnimationFrame(this._rafHandle);
      this._rafHandle = null;
    }

    const paths = Array.from(
      this.shadowRoot.querySelectorAll("path[data-leg-index]")
    );
    if (paths.length === 0) {
      // Empty session (e.g. spot mow with no captured trail). Clear ALL
      // per-render state — without this, _paths kept stale orphan path
      // elements from the previous render, and the next scrub.oninput /
      // residual rAF tick would call _renderAt which loops i<_paths.length
      // and reads _timeline[i]=undefined → "Cannot read properties of
      // undefined (reading 'end_ms')" at line 562. Cleared 2026-05-26.
      this._paths = [];
      this._pathLengths = [];
      this._legSpecs = [];
      this._timeline = [];
      this._pointTimes = [];
      this._pauseWindows = [];
      this._totalMs = 0;
      this._playheadMs = 0;
      this._isPlaying = false;
      return;
    }

    // Cache path refs + lengths so _renderAt doesn't have to re-query
    // the DOM or recompute getTotalLength on every frame.
    this._paths = paths;
    this._pathLengths = paths.map(p => p.getTotalLength());

    // --- Time-coded timeline (single source of truth) ---
    const FIRST_T = Number(a.track_first_ts);
    const LAST_T  = Number(a.track_last_ts);
    const wallDurMs = Math.max(1, (LAST_T - FIRST_T) * 1000);
    const compression = this._currentReplaySpeed();   // log-scaled, Task 15
    const MIN_MS = 3000, MAX_MS = 90000;
    this._totalMs = Math.min(MAX_MS, Math.max(MIN_MS, wallDurMs / compression));
    const scale = this._totalMs / wallDurMs;           // anim-ms per wall-ms

    const specs = this._legSpecs || [];
    this._timeline = specs.map((leg, i) => {
      const startMs = (leg.start_ts - FIRST_T) * 1000 * scale;
      const endMs   = (leg.end_ts   - FIRST_T) * 1000 * scale;
      return { leg: i, start_ms: startMs,
               end_ms: Math.max(startMs + 1, endMs),
               dur: Math.max(1, endMs - startMs) };
    });

    // Per-point anim-times for the step buttons. Each captured s1p4 point is
    // ONE "segment"; the step buttons walk these uniformly (vs leg boundaries,
    // which vary wildly — a continuous mow can be one 500-point leg). Within a
    // leg, points are placed by cumulative path length so the time matches how
    // the animation draws the leg (length-proportional).
    this._pointTimes = [];
    for (let i = 0; i < specs.length; i++) {
      const pts = specs[i].pts || [];
      const slot = this._timeline[i];
      const cum = [0];
      for (let j = 1; j < pts.length; j++) {
        const dx = pts[j][0] - pts[j - 1][0];
        const dy = pts[j][1] - pts[j - 1][1];
        cum.push(cum[j - 1] + Math.hypot(dx, dy));
      }
      const total = cum[cum.length - 1] || 1;
      for (let j = 0; j < pts.length; j++) {
        this._pointTimes.push(slot.start_ms + (cum[j] / total) * slot.dur);
      }
    }
    this._pointTimes.sort((p, q) => p - q);

    // Initialize all paths to fully-hidden. The rAF tick will reveal
    // them progressively as _playheadMs advances.
    paths.forEach((p, i) => {
      p.style.strokeDasharray = this._pathLengths[i];
      p.style.strokeDashoffset = this._pathLengths[i];
    });
    // Apply the current render style (fat/thin) to all paths now that
    // _paths is populated. This ensures the correct stroke/color is set
    // before the first frame renders.
    this._applyRenderStyle();
    const marker = this.shadowRoot.getElementById("head");
    if (marker) marker.setAttribute("visibility", "visible");

    // --- Pause overlay windows (Task 16) ---
    // Build [{start_ms, end_ms, label}] on the compressed axis for any
    // contiguous run of a recognised pause-state code. Currently detects:
    //   state_samples code=6  → charging pause ("🔋 charging")
    //   error_samples code=56 → rain delay   ("🌧 rain delay")
    // These windows are shown as a text label in _renderAt.
    this._pauseWindows = [];
    {
      const addWindows = (samples, matchFn, label) => {
        let runStart = null, runStartUnix = null;
        for (const s of samples || []) {
          if (!Array.isArray(s) || s.length < 2) continue;
          const [tsUnix, code] = s;
          const ms = (tsUnix - FIRST_T) * 1000 * scale;
          if (matchFn(code) && runStart === null) {
            runStart = ms; runStartUnix = tsUnix;
          } else if (!matchFn(code) && runStart !== null) {
            this._pauseWindows.push({
              start_ms: runStart, end_ms: ms,
              label: `${label} — ${Math.round((tsUnix - runStartUnix) / 60)} min`,
            });
            runStart = null;
          }
        }
        if (runStart !== null) {
          this._pauseWindows.push({ start_ms: runStart, end_ms: this._totalMs, label });
        }
      };
      addWindows(a.state_samples, c => c === 6, "🔋 charging");
      addWindows(a.error_samples, c => c === 56, "🌧 rain delay");
    }


    // Reset playhead state and kick off the rAF loop.
    this._playheadMs = 0;
    this._isPlaying = true;
    this._lastTickMs = null;
    this._ensureRaf();
  }

  _ensureRaf() {
    // Idempotent: if a frame is already scheduled, don't double-schedule.
    if (this._rafHandle) return;
    this._lastTickMs = null;
    this._rafHandle = requestAnimationFrame((now) => this._tick(now));
  }

  _tick(now) {
    this._rafHandle = null;
    // First tick after _ensureRaf has no delta — treat as 0 ms advance.
    if (this._lastTickMs == null) {
      this._lastTickMs = now;
    }
    const deltaMs = now - this._lastTickMs;
    this._lastTickMs = now;

    if (this._isPlaying) {
      this._playheadMs += deltaMs;
      if (this._playheadMs >= this._totalMs) {
        this._playheadMs = this._totalMs;
        this._isPlaying = false;
      }
    }

    this._renderAt(this._playheadMs);

    // Keep the loop alive while playing OR while the user might be
    // dragging the slider (so seek-while-paused repaints come back
    // through the same code path). Stop when both are false to free
    // the rAF callback cycle.
    if (this._isPlaying || this._userDraggingScrub) {
      this._rafHandle = requestAnimationFrame((t) => this._tick(t));
    }
  }

  _stepSegment(dir) {
    // Pause and jump the playhead to the next (dir>0) / previous (dir<0)
    // captured s1p4 point — ONE segment per click. Uses per-point anim-times
    // (_pointTimes) rather than leg boundaries: legs vary wildly in size (a
    // continuous mow can be one 500-point leg), so leg-stepping moved many
    // stripes at once. Point-stepping is uniform — one captured movement each.
    this._isPlaying = false;
    const pts = this._pointTimes || [];
    if (!pts.length || !this._totalMs) return;
    const cur = this._playheadMs;
    const EPS = 0.5;  // ms — don't stick on the current point
    let target;
    if (dir > 0) {
      target = pts.find((t) => t > cur + EPS);
      if (target === undefined) target = this._totalMs;
    } else {
      let prev = 0;
      for (const t of pts) { if (t < cur - EPS) prev = t; else break; }
      target = prev;
    }
    this._playheadMs = target;
    this._renderAt(this._playheadMs);
  }

  _renderAt(ms) {
    // Pure render — sets the SVG / slider to reflect a given playhead
    // position. Idempotent; safe to call from rAF tick OR from slider
    // oninput while paused.
    if (!this._paths || !this._timeline) return;
    // Defensive: paths and timeline must be in lock-step. If a previous
    // render left _paths populated and the latest reset cleared
    // _timeline (or vice versa), bail out rather than indexing past
    // the end of _timeline and reading .end_ms on undefined.
    if (this._paths.length === 0 || this._timeline.length !== this._paths.length) return;
    const paths = this._paths;
    const lengths = this._pathLengths;

    let activeLeg = -1;
    for (let i = 0; i < paths.length; i++) {
      const slot = this._timeline[i];
      const L = lengths[i];
      if (ms >= slot.end_ms) {
        paths[i].style.strokeDashoffset = 0;
      } else if (ms <= slot.start_ms) {
        paths[i].style.strokeDashoffset = L;
      } else {
        const frac = (ms - slot.start_ms) / slot.dur;
        paths[i].style.strokeDashoffset = L * (1 - frac);
        activeLeg = i;
      }
    }

    // Head marker follows the active leg's current point. If we're
    // sitting at a between-leg gap, anchor to the end of the last
    // completed leg so the marker doesn't disappear.
    const marker = this.shadowRoot.getElementById("head");
    if (marker) {
      let iconX = null;
      let iconY = null;
      if (activeLeg >= 0) {
        const slot = this._timeline[activeLeg];
        const L = lengths[activeLeg];
        const frac = (ms - slot.start_ms) / slot.dur;
        const point = paths[activeLeg].getPointAtLength(L * frac);
        iconX = point.x;
        iconY = point.y;
      } else {
        // No active leg — we're between legs. Find the last completed leg
        // and freeze the icon at its endpoint during the gap (no straight-line
        // draw across pen-up gaps). The charging-window snap below can still
        // override this to lock at dock.
        let prevIdx = -1;
        for (let i = 0; i < this._timeline.length; i++) {
          if (this._timeline[i].end_ms <= ms) prevIdx = i;
        }
        if (prevIdx >= 0) {
          const point = paths[prevIdx].getPointAtLength(lengths[prevIdx]);
          iconX = point.x;
          iconY = point.y;
        } else if (paths.length > 0) {
          const point = paths[0].getPointAtLength(0);
          iconX = point.x;
          iconY = point.y;
        }
      }

      // During a charging/rain pause the playhead sits in the between-leg gap
      // after the drive-to-dock leg, so the icon naturally freezes at that
      // leg's last point — which IS the dock, projected through the SAME flip
      // as the trail. (The old dock-snap override computed a separate dock
      // pixel WITHOUT the trail's vertical flip, mirroring the icon about the
      // image centre — removed.)
      if (iconX !== null) {
        marker.setAttribute("cx", iconX.toFixed(2));
        marker.setAttribute("cy", iconY.toFixed(2));
      }
    }

    // Slider auto-update — suppress while user is dragging so we don't
    // fight their input.
    if (!this._userDraggingScrub) {
      const scrub = this.shadowRoot.getElementById("scrub");
      if (scrub) {
        const v = Math.round((ms / (this._totalMs || 1)) * 1000);
        // Only write back if it changed; avoids triggering oninput
        // recursion on browsers that fire it on programmatic value set.
        if (parseInt(scrub.value, 10) !== v) scrub.value = String(v);
      }
    }

    // Pause-overlay label (Task 16): show text when playhead is inside a
    // known pause window (charging / rain-delay), hidden otherwise.
    const label = this.shadowRoot.getElementById("pause-label");
    if (label) {
      const win = (this._pauseWindows || []).find(w => ms >= w.start_ms && ms <= w.end_ms);
      if (win) {
        label.textContent = win.label;
        label.setAttribute("visibility", "visible");
      } else {
        label.setAttribute("visibility", "hidden");
      }
    }
  }

  _currentReplaySpeed() {
    // Log-scaled compression 50x .. 800x; slider 0..1000, default mid (~200x).
    const el = this.shadowRoot && this.shadowRoot.getElementById("speed");
    let frac = 0.5;
    if (el) {
      frac = parseInt(el.value, 10) / 1000;
    } else {
      const saved = parseFloat(localStorage.getItem("dreame_a2_mower_replay_speed"));
      if (Number.isFinite(saved)) frac = saved;
    }
    const MIN = Math.log(50), MAX = Math.log(800);
    return Math.exp(MIN + (MAX - MIN) * frac);
  }

  // Read the trail_render_width from the integration's number entity.
  // Falls back to 24 if the entity is not yet available.
  _currentTrailWidth() {
    const ent = this._hass && this._hass.states && this._hass.states['number.dreame_a2_mower_trail_render_width'];
    const v = parseFloat(ent && ent.state);
    return Number.isFinite(v) ? Math.round(v) : 24;
  }

  _applyRenderStyle() {
    if (!this._paths || !this._paths.length) return;
    const widthPx = this._currentTrailWidth();
    // Colors match the Python palette in map_render.py:
    //   mow_trail_color  = (178, 223, 138, 255) → light green
    //   traversal_color  = (130, 130, 130, 220) → medium grey, α=220/255≈0.86
    const mowingColor = 'rgb(178, 223, 138)';
    const traversalColor = 'rgba(130, 130, 130, 0.86)';
    const roles = this._pathRoles || [];
    for (let i = 0; i < this._paths.length; i++) {
      const role = roles[i];
      this._paths[i].style.stroke = (role === 'traversal') ? traversalColor : mowingColor;
      this._paths[i].style.strokeWidth = widthPx;
    }
  }

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
