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
    // Include filename so attribute-only updates (same picker label,
    // different underlying session) also trigger a re-render. Covers
    // edge cases where state.state stays as "(pick a session)" but the
    // picked entry changed via a different path.
    const stateKey = `${state.state}|${state.last_changed}|${state.attributes.filename || ""}`;
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

  _projectPoint(x_m, y_m, proj) {
    const cloud_x = x_m * 1000;
    const cloud_y = y_m * 1000;
    const px = (proj.bx2_mm - cloud_x) / proj.pixel_size_mm;
    const py_pre = (proj.by2_mm - cloud_y) / proj.pixel_size_mm;
    // FLIP_TOP_BOTTOM applied to base PNG by render_with_trail.
    const py = proj.height_px - py_pre;
    return [px, py];
  }

  _MOWING_STATES = new Set([1, 2, 3]);

  _computePauseIntervals(stateSamples, startTs, endTs) {
    // Returns list of {start, end} pause intervals (in epoch seconds).
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
    const url = a.base_map_image_url;
    if (!proj || !url) {
      this.shadowRoot.innerHTML = `
        <ha-card><div style="padding:12px;">
          Waiting for map projection / base image…
        </div></ha-card>`;
      return;
    }
    // Stash projection so _applyRenderStyle can compute pixel-accurate fat width.
    this._proj = proj;
    // Restore render style from localStorage (per entity_id, default fat).
    if (this._renderStyle === undefined) {
      this._renderStyle = localStorage.getItem(
        `dreame_replay_render_style:${this._entityId}`
      ) || 'fat';
    }
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
    const legs = (a.legs || []).filter(leg => leg && leg.length >= 2);
    const paths = legs.map((leg, i) => `
      <path d="${this._buildLegPathD(leg, proj)}"
            fill="none" stroke="rgb(220,40,40)" stroke-width="3"
            stroke-linecap="butt" stroke-linejoin="round"
            data-leg-index="${i}" />
    `).join("");
    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>
          svg { display: block; width: 100%; height: auto; }
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
        <svg viewBox="0 0 ${proj.width_px} ${proj.height_px}"
             xmlns="http://www.w3.org/2000/svg"
             preserveAspectRatio="xMidYMid meet">
          <image href="${url}"
                 x="0" y="0"
                 width="${proj.width_px}" height="${proj.height_px}" />
          ${paths}
          <circle id="head" r="6" fill="rgb(255,140,0)" stroke="white" stroke-width="2"
                  cx="0" cy="0" visibility="hidden" />
        </svg>
        <div class="controls">
          <button id="btn-play" title="Play">▶</button>
          <button id="btn-pause" title="Pause">⏸</button>
          <button id="btn-replay" title="Replay">↻</button>
          <button id="btn-style" class="ctrl-btn" title="Toggle render style (fat ↔ thin)">
            <svg width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
              <rect x="2" y="5" width="16" height="5" fill="currentColor"/>
              <rect x="2" y="13" width="16" height="2" fill="currentColor"/>
            </svg>
          </button>
          <input id="scrub" type="range" min="0" max="1000" value="0"
                 style="flex: 1; max-width: 240px;" />
        </div>
      </ha-card>`;
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
    this.shadowRoot.getElementById("btn-style").onclick = () => {
      this._renderStyle = this._renderStyle === 'fat' ? 'thin' : 'fat';
      localStorage.setItem(
        `dreame_replay_render_style:${this._entityId}`,
        this._renderStyle
      );
      this._applyRenderStyle();
    };

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
      this._timeline = [];
      this._totalMs = 0;
      this._playheadMs = 0;
      this._isPlaying = false;
      return;
    }

    // Cache path refs + lengths so _renderAt doesn't have to re-query
    // the DOM or recompute getTotalLength on every frame.
    this._paths = paths;
    this._pathLengths = paths.map(p => p.getTotalLength());
    const totalLength = this._pathLengths.reduce((s, l) => s + l, 0) || 1;

    // Animation duration: distance-driven with a 30s cap and a 2s floor.
    // TARGET_M_PER_S is the simulated mower speed in the animation —
    // tuned so a typical full-yard mow (~1500 m of trail) plays in ~30s
    // and a small edge-mow (~100 m) plays in ~2s instead of being
    // stretched to the full 30s. distance_m comes from the session
    // attribute (_compute_distance_m, sum of pairwise euclidean across
    // legs).
    const TARGET_M_PER_S = 50;
    const MIN_MS = 2000;
    const MAX_MS = 30000;
    const distance_m = Number(a.distance_m) || 0;
    const TOTAL_MS = distance_m > 0
      ? Math.min(MAX_MS, Math.max(MIN_MS, (distance_m / TARGET_M_PER_S) * 1000))
      : MAX_MS;

    // Pause budget classification (state_samples-driven, see Task 12 of
    // the original plan and the local_leg_count fix in commit 65def0a).
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

    // Pause placement: position each state_samples-derived pause at the
    // leg whose cumulative-length fraction matches the pause's mowing-
    // time fraction in real wall-clock. Works regardless of how the
    // local-trail collector segmented _local_legs — handles both the
    // well-split case (multiple local_legs, pauses naturally land at
    // their boundaries) AND the collapsed-single-leg case (one big
    // local_leg covering multiple charges; pauses land at the
    // proportional positions among the cloud_legs that follow).
    //
    // Replaces the earlier local_leg_count-based gap allocation
    // (65def0a) which produced 0 visible pauses when the integration
    // collapsed multi-charge sessions into a single _local_legs entry.
    const legGapMs = new Array(paths.length).fill(0);
    if (pauseSeconds > 0 && pauses.length > 0 && mowSeconds > 0) {
      // Compute each pause's mowing-time fraction at the moment it
      // started (i.e., "after this much pure mowing, the mower paused").
      let mowSecAtPauseStart = 0;
      let lastRealEnd = startTs;
      const pauseSlots = [];
      for (const p of pauses) {
        mowSecAtPauseStart += Math.max(0, p.start - lastRealEnd);
        pauseSlots.push({
          mow_frac: mowSecAtPauseStart / mowSeconds,
          duration_ms: ((p.end - p.start) / pauseSeconds) * pauseBudgetMs,
        });
        lastRealEnd = p.end;
      }
      // Walk legs in order; attribute each pause to the first leg
      // whose end-fraction-of-trail-length passes the pause's
      // mow_frac. Cumulative length serves as a proxy for cumulative
      // mowing time (assumes constant mowing speed — fine for v1).
      let cumLen = 0;
      let pi = 0;
      for (let i = 0; i < paths.length; i++) {
        cumLen += this._pathLengths[i];
        const endFrac = cumLen / totalLength;
        while (pi < pauseSlots.length && pauseSlots[pi].mow_frac <= endFrac) {
          legGapMs[i] += pauseSlots[pi].duration_ms;
          pi++;
        }
      }
      // Pauses that fall past the end-of-trail (math edge case from
      // float rounding, or trailing-pause sessions) anchor to the
      // last leg so their budget isn't lost.
      while (pi < pauseSlots.length) {
        legGapMs[paths.length - 1] += pauseSlots[pi].duration_ms;
        pi++;
      }
    }

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

    // Build the timeline (single source of truth for "when each leg
    // starts / ends in animation-ms"). Used by _renderAt to figure out
    // which leg corresponds to a given _playheadMs. legGapMs[i] is the
    // pause to insert AFTER leg i.
    let acc = 0;
    this._timeline = [];
    paths.forEach((p, i) => {
      const dur = paths.length === 1
        ? TOTAL_MS
        : (this._pathLengths[i] / totalLength) * drawBudgetMs;
      this._timeline.push({ leg: i, start_ms: acc, end_ms: acc + dur, dur });
      acc += dur + legGapMs[i];
    });
    this._totalMs = acc;

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

  _renderAt(ms) {
    // Pure render — sets the SVG / slider to reflect a given playhead
    // position. Idempotent; safe to call from rAF tick OR from slider
    // oninput while paused.
    if (!this._paths || !this._timeline) return;
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
      if (activeLeg >= 0) {
        const slot = this._timeline[activeLeg];
        const L = lengths[activeLeg];
        const frac = (ms - slot.start_ms) / slot.dur;
        const point = paths[activeLeg].getPointAtLength(L * frac);
        marker.setAttribute("cx", point.x.toFixed(2));
        marker.setAttribute("cy", point.y.toFixed(2));
      } else {
        // No active leg — find the last leg whose end_ms <= ms (most
        // recently finished). Marker rests at its endpoint.
        let lastDone = -1;
        for (let i = 0; i < this._timeline.length; i++) {
          if (this._timeline[i].end_ms <= ms) lastDone = i;
          else break;
        }
        if (lastDone >= 0) {
          const L = lengths[lastDone];
          const point = paths[lastDone].getPointAtLength(L);
          marker.setAttribute("cx", point.x.toFixed(2));
          marker.setAttribute("cy", point.y.toFixed(2));
        }
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
  }

  _applyRenderStyle() {
    if (!this._paths || !this._paths.length) return;
    // Compute fat stroke width: 22cm blade width in SVG pixels.
    // pixel_size_mm is mm-per-pixel; blade is 220mm → pixels = 220 / pixel_size_mm.
    // Fall back to 24px if projection is unavailable (unlikely post-_startAnimation).
    const pixelSizeMm = (this._proj && this._proj.pixel_size_mm) ? this._proj.pixel_size_mm : 9.17;
    const fatWidthPx = Math.max(8, Math.round(220 / pixelSizeMm));
    const thinWidthPx = 3;
    const fatColor   = 'rgb(178, 223, 138)';
    const thinColor  = 'rgba(50, 100, 30, 0.86)';
    const isFat = this._renderStyle === 'fat';
    for (const p of this._paths) {
      p.style.stroke = isFat ? fatColor : thinColor;
      p.style.strokeWidth = isFat ? fatWidthPx : thinWidthPx;
    }
  }

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
