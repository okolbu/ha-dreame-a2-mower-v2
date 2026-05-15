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

  getCardSize() { return 6; }
}

customElements.define("dreame-mower-replay-card", DreameMowerReplayCard);
