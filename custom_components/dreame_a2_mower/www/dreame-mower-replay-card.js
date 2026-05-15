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
          <input id="scrub" type="range" min="0" max="1000" value="0"
                 style="flex: 1; max-width: 240px;" />
        </div>
      </ha-card>`;
    this._startAnimation(a);

    this.shadowRoot.getElementById("btn-play").onclick = () => {
      this._activeAnimations.forEach(an => {
        an.play();
        // The rAF chain self-terminated when paused; one rAF restarts it.
        // The closure's tick function is captured by the animation context.
        // Use a manual ticker: read state and reposition head until anim finishes.
        const marker = this.shadowRoot.getElementById("head");
        const paths = Array.from(this.shadowRoot.querySelectorAll("path[data-leg-index]"));
        const i = parseInt(an.effect?.target?.dataset?.legIndex ?? "-1", 10);
        if (i < 0 || !paths[i] || !marker) return;
        const p = paths[i];
        const L = parseFloat(p.style.strokeDasharray) || p.getTotalLength();
        const dur = an.effect?.getTiming?.()?.duration || 0;
        const resumeTick = () => {
          if (an.playState === "finished" || an.playState === "idle" || an.playState === "paused") return;
          const t = an.currentTime || 0;
          const offset = L - (t / dur) * L;
          const point = p.getPointAtLength(L - offset);
          marker.setAttribute("cx", point.x.toFixed(2));
          marker.setAttribute("cy", point.y.toFixed(2));
          requestAnimationFrame(resumeTick);
        };
        requestAnimationFrame(resumeTick);
      });
    };
    this.shadowRoot.getElementById("btn-pause").onclick = () => {
      this._activeAnimations.forEach(an => an.pause());
      // Pending setTimeouts can't be paused; clear and remember.
      this._pendingTimeouts.forEach(t => clearTimeout(t));
      this._pendingTimeouts = [];
    };
    this.shadowRoot.getElementById("btn-replay").onclick = () => {
      // Force a full re-render which cancels existing animations and
      // restarts the chain from t=0.
      this._lastStateKey = null;
      this._render(state);
    };
    this.shadowRoot.getElementById("scrub").oninput = (e) => {
      const frac = parseInt(e.target.value, 10) / 1000;
      const target_ms = frac * (this._totalMs || 1);
      this._seekTo(target_ms);
    };
  }

  _startAnimation(a) {
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

    const marker = this.shadowRoot.getElementById("head");
    if (marker) marker.setAttribute("visibility", "visible");

    // Initialize all paths to fully-hidden (dashoffset = full length).
    paths.forEach((p, i) => {
      p.style.strokeDasharray = lengths[i];
      p.style.strokeDashoffset = lengths[i];
    });

    const legGapPauseMs = paths.length > 1
      ? pauseBudgetMs / (paths.length - 1)
      : 0;

    // Precompute cumulative timeline so scrub can map fraction → leg state.
    let acc = 0;
    this._timeline = [];
    paths.forEach((p, i) => {
      const dur = paths.length === 1
        ? TOTAL_MS
        : (lengths[i] / totalLength) * drawBudgetMs;
      this._timeline.push({ leg: i, start_ms: acc, end_ms: acc + dur, dur });
      acc += dur;
      if (i < paths.length - 1) acc += legGapPauseMs;
    });
    this._totalMs = acc;

    // TODO (v2): align pause intervals to leg boundaries instead of distributing
    // pauseBudgetMs uniformly. See spec § Timing model. Requires correlating
    // state_samples timestamps with inferred per-leg time spans.

    // Chain leg animations. Each setTimeout fires the next leg's animate().
    let cumulativeDelay = 0;
    paths.forEach((p, i) => {
      // Single-leg case: legGapPauseMs is 0 so pauseBudgetMs would be lost.
      // Give the lone leg the full TOTAL_MS so the 30s target is honored even
      // when the session has pause time but only one trail leg (the common
      // mow-resume-via-recharge case which the cloud reports as one segment).
      const dur = paths.length === 1
        ? TOTAL_MS
        : (lengths[i] / totalLength) * drawBudgetMs;
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
          if (anim.playState === "finished" || anim.playState === "idle" || anim.playState === "paused") return;
          const t = anim.currentTime || 0;
          const offset = lengths[i] - (t / dur) * lengths[i];
          const point = p.getPointAtLength(lengths[i] - offset);
          if (marker) {
            marker.setAttribute("cx", point.x.toFixed(2));
            marker.setAttribute("cy", point.y.toFixed(2));
          }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      };
      if (cumulativeDelay === 0) {
        start();
      } else {
        const t = setTimeout(start, cumulativeDelay);
        this._pendingTimeouts.push(t);
      }
      cumulativeDelay += dur;
      if (i < paths.length - 1) cumulativeDelay += legGapPauseMs;
    });
  }

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

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
