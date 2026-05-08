/* Dreame A2 Mower — Schedule edit card.
 *
 * Reads sensor.dreame_a2_mower_schedule_count attributes for slot/plan data;
 * calls dreame_a2_mower.set_schedule_plans service to mutate.
 *
 * Layout: slot tabs + plan list + add/edit/delete buttons.
 * Add/edit modal + weekly-grid view land in a follow-up step.
 *
 * NOTE: The sensor exposes per-plan "action" as a string label
 * ("all_area", "zone", "edge") — NOT as an integer action_type.
 * The _actionTypeOf() helper derives the int via ACTION_FROM_LABEL reverse map.
 */

const SLOT_DEFAULTS = {
  0: "Spr & Sum Schedule",
  1: "Aut & Win Schedule",
};

const ACTION_LABELS = {
  0: "All-area",
  1: "Zone",
  2: "Edge",
};

const ACTION_COLORS = {
  0: "#a3d977", // green — All-area
  1: "#7fb3ff", // blue — Zone
  2: "#ff8a8a", // red — Edge
};

const ACTION_FROM_LABEL = { all_area: 0, zone: 1, edge: 2 };

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function _actionTypeOf(plan) {
  if (typeof plan.action_type === "number") return plan.action_type;
  return ACTION_FROM_LABEL[plan.action] ?? 0;
}

class DreameA2ScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeSlot = 0;
    this._stateRef = null;
  }

  setConfig(config) {
    this._sensor = config.sensor || "sensor.dreame_a2_mower_schedule_count";
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._sensor];
    if (!state) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;">Sensor ${this._sensor} not available</div></ha-card>`;
      return;
    }
    if (this._stateRef === state) return;
    this._stateRef = state;
    this._render(state);
  }

  _render(state) {
    const slots = state.attributes.slots || [];
    const slotTabs = slots
      .map(
        (s, i) =>
          `<button class="tab ${i === this._activeSlot ? "active" : ""}" data-slot="${i}">${
            s.name || SLOT_DEFAULTS[s.slot_id] || `Schedule ${s.slot_id + 1}`
          }</button>`,
      )
      .join("");
    const active = slots[this._activeSlot] || { plans: [] };
    const planList = active.plans
      .map((p, idx) => {
        const at = _actionTypeOf(p);
        return `
        <div class="plan" style="border-left: 4px solid ${ACTION_COLORS[at]};">
          <div class="plan-info">
            <strong>${p.time}</strong> ${ACTION_LABELS[at] || p.action}
            ${p.zone_id != null ? `(Zone ${p.zone_id})` : ""}
            <div class="days">${(p.days || []).join(", ")}</div>
          </div>
          <button class="delete" data-slot="${this._activeSlot}" data-plan="${idx}">Delete</button>
        </div>`;
      })
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; }
        .tabs { display: flex; gap: 4px; margin-bottom: 12px; }
        .tab { padding: 6px 12px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer; }
        .tab.active { background: var(--primary-color); color: var(--text-primary-color); }
        .plan { display: flex; justify-content: space-between; align-items: center; padding: 8px; margin: 4px 0; border: 1px solid var(--divider-color); }
        .plan-info { flex: 1; }
        .days { font-size: 0.85em; color: var(--secondary-text-color); }
        .delete { padding: 4px 10px; cursor: pointer; }
        .add { display: block; margin-top: 12px; padding: 8px 14px; cursor: pointer; }
        .empty { padding: 12px; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="tabs">${slotTabs}</div>
        <div class="plans">
          ${planList || '<div class="empty">No plans configured.</div>'}
        </div>
        <button class="add">+ Add plan</button>
      </ha-card>
    `;
    this.shadowRoot.querySelectorAll(".tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        this._activeSlot = parseInt(btn.dataset.slot, 10);
        this._render(this._stateRef);
      }),
    );
    this.shadowRoot.querySelectorAll(".delete").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._deletePlan(
          parseInt(btn.dataset.slot, 10),
          parseInt(btn.dataset.plan, 10),
        ),
      ),
    );
    this.shadowRoot.querySelector(".add").addEventListener("click", () =>
      alert("Add modal — implemented in next task"),
    );
  }

  async _deletePlan(slotIdx, planIdx) {
    const slots = this._stateRef.attributes.slots;
    const slot = slots[slotIdx];
    if (!slot) return;
    const newPlans = slot.plans.filter((_, i) => i !== planIdx).map((p) => ({
      time_min: this._parseHhmm(p.time),
      weekday_mask: this._buildWeekdayMask(p.days),
      action_type: _actionTypeOf(p),
      ...(p.zone_id != null ? { zone_id: p.zone_id } : {}),
    }));
    await this._hass.callService("dreame_a2_mower", "set_schedule_plans", {
      slot_id: slot.slot_id,
      plans: newPlans,
    });
  }

  _parseHhmm(s) {
    const [hh, mm] = s.split(":").map((x) => parseInt(x, 10));
    return hh * 60 + mm;
  }

  _buildWeekdayMask(days) {
    let mask = 0;
    for (const d of days) {
      const idx = WEEKDAY_LABELS.indexOf(d);
      if (idx >= 0) mask |= 1 << idx;
    }
    return mask;
  }

  getCardSize() {
    return 4;
  }
}

customElements.define("dreame-a2-schedule-card", DreameA2ScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-schedule-card",
  name: "Dreame A2 Schedule",
  description: "Edit Spr & Sum / Aut & Win mowing schedules",
});
console.info("dreame-a2-schedule-card v1.0.2a1 loaded");
