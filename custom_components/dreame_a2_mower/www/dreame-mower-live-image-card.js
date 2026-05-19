// Live image card for camera entities — bypasses HA's <hui-image>
// 10-second polling interval. Watches the entity's `entity_picture`
// attribute and updates the <img src> on every state push, so picker
// or slider changes that re-render the underlying PNG produce a
// sub-second visual refresh instead of the ~5s lag picture-entity
// exhibits.
//
// Use in a dashboard:
//
//   - type: custom:dreame-mower-live-image-card
//     entity: camera.dreame_a2_mower_map
//     # All optional:
//     max_width: "50%"       # CSS max-width on the <img>
//     aspect_ratio: "1 / 1"  # CSS aspect-ratio (e.g. for square frame)
//     object_fit: contain    # CSS object-fit ('contain' or 'cover')
//
// Why this exists: HA's built-in picture-entity / picture-glance
// cards render camera images via <hui-image>, which polls cameras
// every UPDATE_INTERVAL = 10000 ms (see
// frontend/src/panels/lovelace/components/hui-image.ts) and does not
// subscribe to entity_picture state-change events. Average wait for
// a manually-triggered re-render is ~5s. This card reads
// entity_picture from the entity state directly and updates the img
// src as soon as the state push arrives.

class DreameMowerLiveImageCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("entity is required");
    }
    this._config = config;
    this._lastUrl = null;
  }

  set hass(hass) {
    this._hass = hass;
    const ent = hass.states[this._config.entity];
    if (!ent) {
      this._renderEmpty(`entity ${this._config.entity} not found`);
      return;
    }
    const url = ent.attributes && ent.attributes.entity_picture;
    if (!url) {
      this._renderEmpty(`no entity_picture for ${this._config.entity}`);
      return;
    }
    if (url === this._lastUrl) {
      return;
    }
    this._lastUrl = url;
    this._renderImage(url);
  }

  _ensureShadow() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    return this.shadowRoot;
  }

  _renderEmpty(reason) {
    const root = this._ensureShadow();
    root.innerHTML = `
      <style>
        :host { display: block; }
        .placeholder {
          padding: 16px;
          text-align: center;
          color: var(--secondary-text-color, #888);
          font-style: italic;
        }
      </style>
      <div class="placeholder">${reason}</div>
    `;
  }

  _renderImage(url) {
    const root = this._ensureShadow();
    const cfg = this._config;
    const maxWidth = cfg.max_width || "100%";
    const aspect = cfg.aspect_ratio ? `aspect-ratio: ${cfg.aspect_ratio};` : "";
    const objectFit = cfg.object_fit ? `object-fit: ${cfg.object_fit};` : "";
    // Replace the entire <img> on every URL change so the browser
    // refetches without us having to manually crossfade. The PNG view
    // returns Cache-Control: no-store so this is a true network fetch.
    root.innerHTML = `
      <style>
        :host { display: block; }
        img {
          display: block;
          max-width: ${maxWidth};
          width: 100%;
          height: auto;
          margin: 0 auto;
          ${aspect}
          ${objectFit}
        }
      </style>
      <img src="${url}" alt="" />
    `;
  }

  getCardSize() {
    return 4;
  }

  static getConfigElement() {
    // No bundled visual config editor — users edit YAML directly.
    return null;
  }

  static getStubConfig() {
    return { entity: "camera.dreame_a2_mower_map" };
  }
}

// Guard against double-define when both the auto-register (via
// frontend.add_extra_js_url in __init__.py) and a user-managed
// Lovelace resource pointing at this same URL are present. Without
// the guard, the second customElements.define() call throws and
// the dashboard renders blank.
if (!customElements.get("dreame-mower-live-image-card")) {
  customElements.define("dreame-mower-live-image-card", DreameMowerLiveImageCard);

  // Register with the HA card picker so it shows up in the
  // "Add card" UI. Only register once per page load, matching the
  // customElements.define guard above.
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-mower-live-image-card",
    name: "Dreame Mower Live Image",
    description:
      "Camera image that refreshes immediately on entity_picture state change, " +
      "bypassing HA's 10s camera-poll interval.",
  });
}
