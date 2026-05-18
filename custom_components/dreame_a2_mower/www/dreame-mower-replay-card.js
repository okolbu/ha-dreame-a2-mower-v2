// Dreame A2 Mower — Session Replay Card
//
// Animates the trail of an archived mowing session over the base map,
// fitting any session into <=30 s of playback with proportional freezes
// during non-mowing intervals.
//
// Reads sensor.dreame_a2_mower_picked_session attributes:
//   legs: list[list[[x_m, y_m]]]
//   state_samples: list[[ts_s, state_value]]
//   map_projection: { bx1_mm, by1_mm, bx2_mm, by2_mm, pixel_size_mm, width_px, height_px, dock_xy_mm? } | null
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
    // Mowing-vs-traversal split: when session_card.py exposes the two
    // classified lists, use them. Mowing legs are rendered first (lower
    // SVG z-order); traversal legs appended last so they render ON TOP
    // of mowing strokes (matching the Python static renderer's z-order).
    // Fall back to the legacy union `legs` list when the new attributes
    // are absent (old archived sessions / back-compat).
    const rawMowing = a.mowing_legs || [];
    const rawTraversal = a.traversal_legs || [];
    const useSplit = rawMowing.length > 0 || rawTraversal.length > 0;
    // legSpecs: ordered array of { pts, role } — mowing first, traversal last.
    const legSpecs = useSplit
      ? [
          ...rawMowing.map(leg => ({ pts: leg, role: 'mowing' })),
          ...rawTraversal.map(leg => ({ pts: leg, role: 'traversal' })),
        ].filter(s => s.pts && s.pts.length >= 2)
      : (a.legs || [])
          .filter(leg => leg && leg.length >= 2)
          .map(leg => ({ pts: leg, role: 'mowing' }));
    // Stash roles parallel to paths so _applyRenderStyle can look them up.
    this._pathRoles = legSpecs.map(s => s.role);
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
        </svg>
        </div>
        <div class="controls">
          <button id="btn-play" title="Play">▶</button>
          <button id="btn-pause" title="Pause">⏸</button>
          <button id="btn-replay" title="Replay">↻</button>
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

    // --- Charging-window detection (Task 9) ---
    // Build [start_ms, end_ms] pairs for contiguous charging runs relative
    // to session start. state_samples code=6 means CHARGING (matches
    // _CHARGING_STATE_CODE in session_card.py). These windows are used in
    // _renderAt to snap the icon to the dock during charging pauses.
    this._chargingWindowsMs = [];
    {
      const stateSamples = a.state_samples || [];
      const sessionStartUnix = a.started_at_unix || 0;
      const CHARGING_CODE = 6;
      let runStart = null;
      for (const sample of stateSamples) {
        if (!Array.isArray(sample) || sample.length < 2) continue;
        const [tsUnix, code] = sample;
        const ms = (tsUnix - sessionStartUnix) * 1000;
        if (code === CHARGING_CODE && runStart === null) {
          runStart = ms;
        } else if (code !== CHARGING_CODE && runStart !== null) {
          this._chargingWindowsMs.push([runStart, ms]);
          runStart = null;
        }
      }
      if (runStart !== null) {
        // Open charging run reaching end of session — close at totalMs.
        this._chargingWindowsMs.push([runStart, acc]);
      }
    }

    // --- Dock pixel position (Task 9) ---
    // dock_xy_mm is in renderer-frame coordinates (post-midline-reflection).
    // Pixel formula: px = (dock_x_mm - bx1_mm) / pixel_size_mm
    //                py = (dock_y_mm - by1_mm) / pixel_size_mm
    // Note: NO FLIP_TOP_BOTTOM — the dock position is already in renderer
    // coords (pre-flip); the base PNG flip does NOT apply to renderer-coord
    // overlays (see map_render._renderer_to_px and the bx1/by1 subtraction
    // correction added in v1.0.0a3 to fix dock/exclusion-zone pixel offsets).
    this._dockPxX = undefined;
    this._dockPxY = undefined;
    {
      const proj = a.map_projection;
      if (proj && proj.dock_xy_mm && proj.bx1_mm !== undefined && proj.by1_mm !== undefined) {
        const psm = proj.pixel_size_mm;
        if (psm && psm > 0) {
          this._dockPxX = (proj.dock_xy_mm[0] - proj.bx1_mm) / psm;
          this._dockPxY = (proj.dock_xy_mm[1] - proj.by1_mm) / psm;
        }
      }
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
          iconX = point.x;
          iconY = point.y;
        } else if (paths.length > 0) {
          // Pre-first-segment: anchor to the very start of the trail so
          // the marker doesn't sit at (0,0) in the top-left corner.
          const point = paths[0].getPointAtLength(0);
          iconX = point.x;
          iconY = point.y;
        }
      }

      // Charging-window dock snap (Task 9): if the playhead is inside a
      // charging run, override icon position with the dock pixel coords,
      // freezing the mower icon at the dock rather than leaving it
      // stranded mid-lawn during the charging pause.
      if (
        iconX !== null &&
        this._chargingWindowsMs &&
        this._chargingWindowsMs.length > 0 &&
        this._dockPxX !== undefined &&
        this._dockPxY !== undefined
      ) {
        const inCharging = this._chargingWindowsMs.some(
          ([s, e]) => ms >= s && ms <= e,
        );
        if (inCharging) {
          iconX = this._dockPxX;
          iconY = this._dockPxY;
        }
      }

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
