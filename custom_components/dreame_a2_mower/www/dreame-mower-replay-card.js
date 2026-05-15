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
          <circle id="head" r="6" fill="rgb(255,140,0)" stroke="white" stroke-width="2"
                  cx="0" cy="0" visibility="hidden" />
        </svg>
      </ha-card>`;
    this._startAnimation();
  }

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

    const marker = this.shadowRoot.getElementById("head");
    if (marker) marker.setAttribute("visibility", "visible");

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

        // Drive the head marker via rAF while this leg animates.
        const tick = () => {
          if (anim.playState === "finished" || anim.playState === "idle") return;
          // currentTime is in ms; map to dashoffset, then to point on path.
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
    });
  }

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
