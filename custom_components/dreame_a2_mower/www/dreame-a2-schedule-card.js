/* Dreame A2 Mower — Schedule edit card (full UX).
 *
 * Reads sensor.dreame_a2_mower_schedule_count, writes via
 * dreame_a2_mower.set_schedule_plans. Supports add / edit / delete
 * with client-side overlap validation matching the app's behavior.
 */

const SLOT_DEFAULTS = {
  0: "Spr & Sum Schedule",
  1: "Aut & Win Schedule",
};

const ACTION_LABELS = { 0: "All-area", 1: "Zone", 2: "Edge" };
const ACTION_COLORS = { 0: "#a3d977", 1: "#7fb3ff", 2: "#ff8a8a" };
const ACTION_FROM_LABEL = { all_area: 0, zone: 1, edge: 2 };
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PLAN_DURATION_MIN = 120; // app reserves 2h per plan regardless of action

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
    this._editingPlan = null; // { slotIdx, planIdx } | null
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
    if (this._stateRef === state && !this._modal) return;
    this._stateRef = state;
    this._render(state);
  }

  _render(state) {
    const slots = state.attributes.slots || [];
    const tabs = slots
      .map(
        (s, i) =>
          `<button class="tab ${i === this._activeSlot ? "active" : ""}" data-slot="${i}">${
            s.name || SLOT_DEFAULTS[s.slot_id] || `Schedule ${s.slot_id + 1}`
          }</button>`,
      )
      .join("");
    const active = slots[this._activeSlot] || { plans: [], slot_id: this._activeSlot };
    const grid = this._renderGrid(active.plans);
    const list = active.plans
      .map((p, idx) => {
        const at = _actionTypeOf(p);
        return `
        <div class="plan" style="border-left: 4px solid ${ACTION_COLORS[at]};">
          <div class="plan-info">
            <strong>${p.time}</strong> ${ACTION_LABELS[at]}
            ${p.zone_id != null ? `(Zone ${p.zone_id})` : ""}
            <div class="days">${(p.days || []).join(", ")}</div>
          </div>
          <div>
            <button class="edit" data-slot="${this._activeSlot}" data-plan="${idx}">Edit</button>
            <button class="delete" data-slot="${this._activeSlot}" data-plan="${idx}">Delete</button>
          </div>
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
        .grid { display: grid; grid-template-columns: 40px repeat(7, 1fr); gap: 1px; background: var(--divider-color); margin-bottom: 12px; font-size: 0.75em; }
        .grid > div { background: var(--card-background-color); padding: 2px 4px; min-height: 18px; position: relative; }
        .grid .header { background: var(--secondary-background-color); text-align: center; font-weight: bold; }
        .grid .plan-block { color: white; padding: 2px 4px; font-size: 0.7em; cursor: pointer; }
        .plan { display: flex; justify-content: space-between; align-items: center; padding: 8px; margin: 4px 0; border: 1px solid var(--divider-color); }
        .plan-info { flex: 1; }
        .days { font-size: 0.85em; color: var(--secondary-text-color); }
        button { padding: 4px 10px; cursor: pointer; margin-left: 4px; }
        .add { display: block; margin-top: 12px; padding: 8px 14px; }
        .empty { padding: 12px; color: var(--secondary-text-color); }
        .modal-bg { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .modal { background: var(--card-background-color); padding: 20px; border-radius: 4px; min-width: 320px; max-width: 90vw; }
        .modal h3 { margin-top: 0; }
        .modal label { display: block; margin: 8px 0 4px; font-weight: bold; }
        .modal select, .modal input { width: 100%; padding: 6px; box-sizing: border-box; }
        .modal .day-toggles { display: flex; gap: 4px; }
        .modal .day-toggles button { flex: 1; padding: 6px; }
        .modal .day-toggles button.on { background: var(--primary-color); color: var(--text-primary-color); }
        .modal .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
        .error { color: var(--error-color, red); font-size: 0.85em; margin-top: 4px; }
      </style>
      <ha-card>
        <div class="tabs">${tabs}</div>
        ${grid}
        <div class="plans">
          ${list || '<div class="empty">No plans configured.</div>'}
        </div>
        <button class="add">+ Add plan</button>
      </ha-card>
      ${this._modal || ""}
    `;
    this.shadowRoot.querySelectorAll(".tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        this._activeSlot = parseInt(btn.dataset.slot, 10);
        this._modal = null;
        this._render(this._stateRef);
      }),
    );
    this.shadowRoot.querySelectorAll(".delete").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._deletePlan(parseInt(btn.dataset.slot, 10), parseInt(btn.dataset.plan, 10)),
      ),
    );
    this.shadowRoot.querySelectorAll(".edit").forEach((btn) =>
      btn.addEventListener("click", () =>
        this._openEditModal(parseInt(btn.dataset.slot, 10), parseInt(btn.dataset.plan, 10)),
      ),
    );
    this.shadowRoot.querySelector(".add").addEventListener("click", () =>
      this._openAddModal(),
    );
    this._wireModal();
  }

  _renderGrid(plans) {
    const cells = ["<div class='header'></div>"];
    for (const d of WEEKDAY_LABELS) cells.push(`<div class='header'>${d}</div>`);
    for (let h = 0; h < 24; h++) {
      cells.push(`<div>${String(h).padStart(2, "0")}</div>`);
      for (let day = 0; day < 7; day++) {
        // The app reserves PLAN_DURATION_MIN (120) per plan — paint
        // both the start hour cell AND the next hour to match.
        const planAtThisCell = plans.find((p) => {
          const startMin = this._parseHhmm(p.time);
          const startHr = Math.floor(startMin / 60);
          const dayMatches = (p.days || []).includes(WEEKDAY_LABELS[day]);
          return dayMatches && (h === startHr || h === startHr + 1);
        });
        if (planAtThisCell) {
          const action = _actionTypeOf(planAtThisCell);
          const startMin = this._parseHhmm(planAtThisCell.time);
          const startHr = Math.floor(startMin / 60);
          const isStartHour = h === startHr;
          // Show the time label only on the starting hour cell; the
          // continuation cell stays coloured but blank for clarity.
          cells.push(
            `<div class='plan-block' style='background:${ACTION_COLORS[action]};' title='${planAtThisCell.time} ${ACTION_LABELS[action]}'>${isStartHour ? planAtThisCell.time : ""}</div>`,
          );
        } else {
          cells.push("<div></div>");
        }
      }
    }
    return `<div class='grid'>${cells.join("")}</div>`;
  }

  _openAddModal() {
    this._editingPlan = null;
    this._modal = this._modalHtml({
      time_min: 480,
      weekday_mask: 0,
      action_type: 0,
      zone_id: null,
    });
    this._render(this._stateRef);
  }

  _openEditModal(slotIdx, planIdx) {
    const plan = this._stateRef.attributes.slots[slotIdx].plans[planIdx];
    this._editingPlan = { slotIdx, planIdx };
    this._modal = this._modalHtml({
      time_min: this._parseHhmm(plan.time),
      weekday_mask: this._buildWeekdayMask(plan.days || []),
      action_type: _actionTypeOf(plan),
      zone_id: plan.zone_id ?? null,
    });
    this._render(this._stateRef);
  }

  _modalHtml(plan) {
    const hh = String(Math.floor(plan.time_min / 60)).padStart(2, "0");
    const mm = String(plan.time_min % 60).padStart(2, "0");
    const dayBtns = WEEKDAY_LABELS.map(
      (d, i) =>
        `<button type='button' class='day-btn ${plan.weekday_mask & (1 << i) ? "on" : ""}' data-day='${i}'>${d}</button>`,
    ).join("");
    const actionOptions = Object.entries(ACTION_LABELS)
      .map(
        ([k, v]) => `<option value='${k}' ${plan.action_type == k ? "selected" : ""}>${v}</option>`,
      )
      .join("");
    return `
      <div class='modal-bg'>
        <div class='modal'>
          <h3>${this._editingPlan ? "Edit plan" : "Add plan"}</h3>
          <label>Action</label>
          <select id='action'>${actionOptions}</select>
          <label>Zone (Zone/Edge only)</label>
          <input id='zone_id' type='number' min='0' value='${plan.zone_id ?? ""}' />
          <label>Time</label>
          <input id='time' type='time' value='${hh}:${mm}' />
          <label>Days</label>
          <div class='day-toggles'>${dayBtns}</div>
          <div class='error' id='error'></div>
          <div class='actions'>
            <button type='button' id='cancel'>Cancel</button>
            <button type='button' id='save'>Save</button>
          </div>
        </div>
      </div>
    `;
  }

  _wireModal() {
    if (!this._modal) return;
    const root = this.shadowRoot;
    let mask = 0;
    root.querySelectorAll(".day-btn").forEach((btn) => {
      if (btn.classList.contains("on")) mask |= 1 << parseInt(btn.dataset.day, 10);
      btn.addEventListener("click", () => {
        const bit = 1 << parseInt(btn.dataset.day, 10);
        if (btn.classList.contains("on")) {
          btn.classList.remove("on");
          mask &= ~bit;
        } else {
          btn.classList.add("on");
          mask |= bit;
        }
      });
    });
    root.querySelector("#cancel").addEventListener("click", () => {
      this._modal = null;
      this._render(this._stateRef);
    });
    root.querySelector("#save").addEventListener("click", () => {
      const action_type = parseInt(root.querySelector("#action").value, 10);
      const zoneVal = root.querySelector("#zone_id").value;
      const zone_id = zoneVal === "" ? null : parseInt(zoneVal, 10);
      const time = root.querySelector("#time").value;
      const time_min = this._parseHhmm(time);
      const errEl = root.querySelector("#error");

      if (mask === 0) {
        errEl.textContent = "Select at least one day.";
        return;
      }
      if ((action_type === 1 || action_type === 2) && zone_id == null) {
        errEl.textContent = "Zone/Edge plans require a zone_id.";
        return;
      }
      const slot = this._stateRef.attributes.slots[this._activeSlot];
      const otherPlans = (slot.plans || []).filter((_, i) =>
        this._editingPlan ? i !== this._editingPlan.planIdx : true,
      );
      for (const other of otherPlans) {
        const otherStart = this._parseHhmm(other.time);
        const otherMask = this._buildWeekdayMask(other.days || []);
        if ((otherMask & mask) === 0) continue;
        const aStart = time_min;
        const aEnd = time_min + PLAN_DURATION_MIN;
        const bStart = otherStart;
        const bEnd = otherStart + PLAN_DURATION_MIN;
        if (aStart < bEnd && bStart < aEnd) {
          errEl.textContent = `Overlaps existing plan at ${other.time}.`;
          return;
        }
      }

      const newPlan = { time_min, weekday_mask: mask, action_type };
      if (zone_id != null) newPlan.zone_id = zone_id;

      const updatedPlans = (slot.plans || []).map((p, idx) => {
        if (this._editingPlan && idx === this._editingPlan.planIdx) {
          return newPlan;
        }
        return {
          time_min: this._parseHhmm(p.time),
          weekday_mask: this._buildWeekdayMask(p.days),
          action_type: _actionTypeOf(p),
          ...(p.zone_id != null ? { zone_id: p.zone_id } : {}),
        };
      });
      if (!this._editingPlan) updatedPlans.push(newPlan);

      this._hass.callService("dreame_a2_mower", "set_schedule_plans", {
        slot_id: slot.slot_id,
        plans: updatedPlans,
      });
      this._modal = null;
      this._render(this._stateRef);
    });
  }

  async _deletePlan(slotIdx, planIdx) {
    const slot = this._stateRef.attributes.slots[slotIdx];
    if (!slot) return;
    const newPlans = (slot.plans || [])
      .filter((_, i) => i !== planIdx)
      .map((p) => ({
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
    return 6;
  }
}

customElements.define("dreame-a2-schedule-card", DreameA2ScheduleCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-schedule-card",
  name: "Dreame A2 Schedule",
  description: "Edit Spr & Sum / Aut & Win mowing schedules",
});
console.info("dreame-a2-schedule-card v1.0.2a1 (full UX) loaded");
