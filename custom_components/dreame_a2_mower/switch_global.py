"""Device settings switch entities, description table, and wire-value builder helpers for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a switch platform.  It is imported by switch.py (the real
platform entry).

Contains the CFG/AI-recognition/edge-mowing/obstacle-avoidance switch classes and the SWITCHES
description table plus its wire-value builder helpers (_build_* / _field_updates_*).  Most switches
here read/write per-active-map settings via map_device_info (CFG transport); DreameA2AiHumanDetectionSwitch
is mower-scoped (parent device).  The dedicated per-map map-binding switch (DreameA2MapEdgemasterSwitch)
lives in switch_map.py instead.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .const import LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState
from ._switch_base import (
    DreameA2SwitchEntityDescription,
    _AiRecognitionBitSwitch,
    _AI_HUMANS_BIT,
    _AI_ANIMALS_BIT,
    _AI_OBJECTS_BIT,
)
from ._settings_writes import (
    settings_optimistic_write as _settings_switch_optimistic_write,
)


# ---------------------------------------------------------------------------
# Wire-value builders — settable switches
# ---------------------------------------------------------------------------

def _build_cls(state: MowerState, enabled: bool) -> int:
    """CLS wire value: single int {0, 1}."""
    return int(enabled)


def _cls_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"child_lock_enabled": enabled}


def _build_dnd(state: MowerState, enabled: bool) -> dict:
    """DND wire value: ``{value, time:[start_min, end_min]}``.

    Verified live 2026-05-09: g2408 accepts the named-key format
    ``{"value":<0|1>, "time":[<start>, <end>]}`` for both on and off
    states (bare ``{"value":0}`` is rejected with r=-3 — always send
    the full form regardless of enabled bit). cloud_client.set_cfg
    sends a dict as ``d`` directly. See
    docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md.

    Defaults: start_min=1200 (20:00), end_min=480 (08:00) — the confirmed
    factory values observed on g2408.
    """
    return {
        "value": int(enabled),
        "time": [
            int(state.dnd_start_min or 1200),
            int(state.dnd_end_min or 480),
        ],
    }


def _dnd_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"dnd_enabled": enabled}


def _build_wrp(state: MowerState, enabled: bool) -> dict:
    """WRP wire value: ``{value, time:<resume_hours>}``.

    Verified live 2026-05-09 (cloud + device app round-trip 4h→6h→4h):
    g2408 accepts the named-key format and the firmware applies it
    (Dreame app reflected the change in real time). cloud_client.set_cfg
    sends a dict as ``d`` directly. See
    docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md.

    The ioBroker catalog also lists a ``sen`` (rain-sensor sensitivity)
    field, and g2408 silently accepts ``sen ∈ {0,1,2,3}`` in the
    payload (r=0 across all four). However the value isn't echoed back
    in getCFG (the cloud read returns only the 2-element ``[enabled,
    hours]`` shape) and the Dreame app doesn't surface a sensitivity
    UI on this firmware — scale and effect are unknown. We omit ``sen``
    entirely from our writes so we don't push a value we can't read
    back. Verified 2026-05-09 that WRP accepts ``{value, time}`` alone.

    Default resume_hours=0 means "Don't Mow After Rain" (no auto-resume).
    """
    return {
        "value": int(enabled),
        "time": int(state.rain_protection_resume_hours or 0),
    }


def _wrp_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"rain_protection_enabled": enabled}


def _build_low(state: MowerState, enabled: bool) -> dict:
    """LOW wire value: ``{value, time:[start_min, end_min]}``.

    Verified live 2026-05-09: g2408 accepts the named-key format. Same
    "always send the full form regardless of enabled bit" rule as DND.
    cloud_client.set_cfg sends a dict as ``d`` directly. See
    docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md.

    Defaults mirror DND defaults: 20:00→08:00.
    """
    return {
        "value": int(enabled),
        "time": [
            int(state.low_speed_at_night_start_min or 1200),
            int(state.low_speed_at_night_end_min or 480),
        ],
    }


def _low_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"low_speed_at_night_enabled": enabled}


def _build_bat_custom_charging(state: MowerState, enabled: bool) -> list:
    """BAT wire value: list(6) [recharge_pct, resume_pct, unknown_flag,
    custom_charging, start_min, end_min].

    CFG.BAT confirmed on g2408 (coordinator._property_apply.cfg_to_state_updates §BAT).
    All 6 fields are stored in MowerState, so full reconstruction is safe.

    BAT[2] = unknown_flag is consistently 1 in all observed data; the
    hard-coded value is the same as in number.py (F4.6.1 decision).
    """
    return [
        int(state.auto_recharge_battery_pct or 15),    # [0] recharge_pct
        int(state.resume_battery_pct or 95),            # [1] resume_pct
        1,                                              # [2] unknown_flag (always 1)
        int(enabled),                                   # [3] custom_charging  (new)
        int(state.charging_start_min or 0),             # [4] start_min
        int(state.charging_end_min or 0),               # [5] end_min
    ]


def _bat_custom_charging_field_updates(
    state: MowerState, enabled: bool
) -> dict[str, Any]:
    return {"custom_charging_enabled": enabled}


def _build_ata_lift(state: MowerState, enabled: bool) -> list:
    """ATA wire value: list(3) [lift_alarm, offmap_alarm, realtime_location].

    CFG.ATA confirmed on g2408
    (coordinator._property_apply.cfg_to_state_updates §ATA, all 3 indices
    individually verified 2026-04-27).  All 3 fields are stored in MowerState,
    so full reconstruction is safe.
    """
    return [
        int(enabled),                                        # [0] lift_alarm  (new)
        int(state.anti_theft_offmap_alarm or False),         # [1] offmap_alarm
        int(state.anti_theft_realtime_location or False),    # [2] realtime_location
    ]


def _ata_lift_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_lift_alarm": enabled}


def _build_ata_offmap(state: MowerState, enabled: bool) -> list:
    """ATA wire value with offmap_alarm overridden."""
    return [
        int(state.anti_theft_lift_alarm or False),           # [0] lift_alarm
        int(enabled),                                        # [1] offmap_alarm  (new)
        int(state.anti_theft_realtime_location or False),    # [2] realtime_location
    ]


def _ata_offmap_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_offmap_alarm": enabled}


def _build_ata_realtime(state: MowerState, enabled: bool) -> list:
    """ATA wire value with realtime_location overridden."""
    return [
        int(state.anti_theft_lift_alarm or False),           # [0] lift_alarm
        int(state.anti_theft_offmap_alarm or False),         # [1] offmap_alarm
        int(enabled),                                        # [2] realtime_location  (new)
    ]


def _ata_realtime_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_realtime_location": enabled}


# ---------------------------------------------------------------------------
# AMBIGUOUS_TOGGLE single-int CFG keys (FDP / STUN / AOP / PROT)
# All four toggle-confirmed 2026-04-30 (see protocol/config_s2p51.py).
# Wire shape: int {0, 1}. Trivial reconstruction.
# ---------------------------------------------------------------------------

def _build_int_toggle(_state: MowerState, enabled: bool) -> int:
    return int(enabled)


def _fdp_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"frost_protection_enabled": enabled}


def _stun_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"auto_recharge_standby_enabled": enabled}


def _aop_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"ai_obstacle_photos_enabled": enabled}


# ---------------------------------------------------------------------------
# MSG_ALERT — Notification Preferences (4-bool list)
# Slots [anomaly, error, task, consumables_messages] confirmed 2026-04-30.
# All four MowerState fields stored, so full reconstruction is safe.
# ---------------------------------------------------------------------------

def _build_msg_alert_with(
    state: MowerState, idx: int, enabled: bool
) -> list[int]:
    """Reconstruct CFG.MSG_ALERT with element ``idx`` overridden to ``enabled``."""
    current = (
        state.msg_alert_anomaly,
        state.msg_alert_error,
        state.msg_alert_task,
        state.msg_alert_consumables,
    )
    return [
        int(enabled if i == idx else bool(current[i] or False))
        for i in range(4)
    ]


def _build_msg_alert_anomaly(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 0, enabled)


def _build_msg_alert_error(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 1, enabled)


def _build_msg_alert_task(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 2, enabled)


def _build_msg_alert_consumables(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 3, enabled)


def _msg_alert_anomaly_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_anomaly": enabled}


def _msg_alert_error_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_error": enabled}


def _msg_alert_task_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_task": enabled}


def _msg_alert_consumables_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_consumables": enabled}


# ---------------------------------------------------------------------------
# VOICE — Voice Prompt Modes (4-bool list)
# Slots [regular_notification, work_status, special_status, error_status]
# confirmed 2026-04-30. Full reconstruction safe.
# ---------------------------------------------------------------------------

def _build_voice_with(
    state: MowerState, idx: int, enabled: bool
) -> list[int]:
    current = (
        state.voice_regular_notification,
        state.voice_work_status,
        state.voice_special_status,
        state.voice_error_status,
    )
    return [
        int(enabled if i == idx else bool(current[i] or False))
        for i in range(4)
    ]


def _build_voice_regular(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 0, enabled)


def _build_voice_work(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 1, enabled)


def _build_voice_special(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 2, enabled)


def _build_voice_error(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 3, enabled)


def _voice_regular_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_regular_notification": enabled}


def _voice_work_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_work_status": enabled}


def _voice_special_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_special_status": enabled}


def _voice_error_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_error_status": enabled}


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------

SWITCHES: tuple[DreameA2SwitchEntityDescription, ...] = (
    # ------------------------------------------------------------------
    # Settable: CLS — child lock
    # Wire shape: single int {0, 1}. Trivially reconstructible.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="child_lock",
        name="Child lock",
        icon="mdi:lock",
        value_fn=lambda s: s.child_lock_enabled,
        cfg_key="CLS",
        build_value_fn=_build_cls,
        field_updates_fn=_cls_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: DND — do-not-disturb
    # Wire shape: list(3) [enabled, start_min, end_min].
    # All 3 fields stored in MowerState (dnd_enabled, dnd_start_min,
    # dnd_end_min).  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="dnd",
        name="Do not disturb",
        icon="mdi:sleep",
        value_fn=lambda s: s.dnd_enabled,
        cfg_key="DND",
        build_value_fn=_build_dnd,
        field_updates_fn=_dnd_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: WRP — rain protection
    # Wire shape: list(2) [enabled, resume_hours].
    # Both fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="rain_protection",
        name="Rain protection",
        icon="mdi:weather-rainy",
        value_fn=lambda s: s.rain_protection_enabled,
        cfg_key="WRP",
        build_value_fn=_build_wrp,
        field_updates_fn=_wrp_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: LOW — low speed at night
    # Wire shape: list(3) [enabled, start_min, end_min].
    # All 3 fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="low_speed_at_night",
        name="Low speed at night",
        icon="mdi:weather-night",
        value_fn=lambda s: s.low_speed_at_night_enabled,
        cfg_key="LOW",
        build_value_fn=_build_low,
        field_updates_fn=_low_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[3] — custom charging period
    # Wire shape: list(6) [recharge_pct, resume_pct, unknown_flag(=1),
    #             custom_charging, start_min, end_min].
    # All 6 fields stored in MowerState.  unknown_flag hard-coded to 1
    # (only observed value — same decision as F4.6.1 number.py).
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="custom_charging_period",
        name="Custom charging period",
        icon="mdi:battery-clock",
        value_fn=lambda s: s.custom_charging_enabled,
        cfg_key="BAT",
        build_value_fn=_build_bat_custom_charging,
        field_updates_fn=_bat_custom_charging_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[0] — lift alarm
    # Wire shape: list(3) [lift_alarm, offmap_alarm, realtime_location].
    # All 3 fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_lift_alarm",
        name="Anti-theft lift alarm",
        icon="mdi:alarm-light",
        value_fn=lambda s: s.anti_theft_lift_alarm,
        cfg_key="ATA",
        build_value_fn=_build_ata_lift,
        field_updates_fn=_ata_lift_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[1] — off-map alarm
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_offmap_alarm",
        name="Anti-theft off-map alarm",
        icon="mdi:map-marker-alert",
        value_fn=lambda s: s.anti_theft_offmap_alarm,
        cfg_key="ATA",
        build_value_fn=_build_ata_offmap,
        field_updates_fn=_ata_offmap_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[2] — realtime location
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_realtime_location",
        name="Anti-theft realtime location",
        icon="mdi:crosshairs-gps",
        value_fn=lambda s: s.anti_theft_realtime_location,
        cfg_key="ATA",
        build_value_fn=_build_ata_realtime,
        field_updates_fn=_ata_realtime_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: AMBIGUOUS_TOGGLE single-int CFG keys (a62)
    # All four toggle-confirmed 2026-04-30. CFG int {0, 1}, trivial build.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="frost_protection",
        name="Frost protection",
        icon="mdi:snowflake-alert",
        value_fn=lambda s: s.frost_protection_enabled,
        cfg_key="FDP",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_fdp_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="auto_recharge_standby",
        name="Auto recharge after extended standby",
        icon="mdi:battery-clock",
        value_fn=lambda s: s.auto_recharge_standby_enabled,
        cfg_key="STUN",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_stun_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="ai_obstacle_photos",
        name="AI obstacle photos",
        icon="mdi:camera-iris",
        value_fn=lambda s: s.ai_obstacle_photos_enabled,
        cfg_key="AOP",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_aop_field_updates,
    ),
    # ------------------------------------------------------------------
    # Settable: MSG_ALERT — Notification Preferences (a62)
    # Four switches sharing CFG.MSG_ALERT 4-bool list. Slots
    # [anomaly, error, task, consumables_messages] toggle-confirmed
    # 2026-04-30. Full reconstruction safe (all 4 in MowerState).
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="msg_alert_anomaly",
        name="Notification: Anomaly messages",
        icon="mdi:alert-octagon",
        value_fn=lambda s: s.msg_alert_anomaly,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_anomaly,
        field_updates_fn=_msg_alert_anomaly_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_error",
        name="Notification: Error messages",
        icon="mdi:alert-circle",
        value_fn=lambda s: s.msg_alert_error,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_error,
        field_updates_fn=_msg_alert_error_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_task",
        name="Notification: Task messages",
        icon="mdi:clipboard-text",
        value_fn=lambda s: s.msg_alert_task,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_task,
        field_updates_fn=_msg_alert_task_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_consumables",
        name="Notification: Consumables messages",
        icon="mdi:tools",
        value_fn=lambda s: s.msg_alert_consumables,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_consumables,
        field_updates_fn=_msg_alert_consumables_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: VOICE — Voice Prompt Modes (a62)
    # Four switches sharing CFG.VOICE 4-bool list. Slots
    # [regular_notification, work_status, special_status, error_status]
    # toggle-confirmed 2026-04-30. Full reconstruction safe.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="voice_regular_notification",
        name="Voice: Regular notification prompt",
        icon="mdi:bullhorn",
        value_fn=lambda s: s.voice_regular_notification,
        cfg_key="VOICE",
        build_value_fn=_build_voice_regular,
        field_updates_fn=_voice_regular_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_work_status",
        name="Voice: Work status prompt",
        icon="mdi:bullhorn-variant",
        value_fn=lambda s: s.voice_work_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_work,
        field_updates_fn=_voice_work_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_special_status",
        name="Voice: Special status prompt",
        icon="mdi:bullhorn-variant-outline",
        value_fn=lambda s: s.voice_special_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_special,
        field_updates_fn=_voice_special_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_error_status",
        name="Voice: Error status prompt",
        icon="mdi:alert-octagon-outline",
        value_fn=lambda s: s.voice_error_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_error,
        field_updates_fn=_voice_error_field_updates,
    ),

    # ------------------------------------------------------------------
    # Read-only: LIT[0] — LED period (main enable)
    #
    # CFG.LIT = list(8) [enabled, start_min, end_min, standby, working,
    #                    charging, error, unknown_trailing_toggle].
    # MowerState stores indices 0, 3, 4, 5, 6 but NOT 1 (start_min),
    # 2 (end_min), or 7 (unknown_trailing_toggle).  The full 8-element
    # list cannot be safely reconstructed → read-only in F4.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_period",
        name="LED period",
        icon="mdi:led-on",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.led_period_enabled,
        # cfg_key intentionally omitted — read-only in F4
    ),

    # ------------------------------------------------------------------
    # Read-only: LIT[3] — LED in standby
    # Same reason as led_period (LIT indices 1, 2, 7 not in MowerState).
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_standby",
        name="LED in standby",
        icon="mdi:led-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.led_in_standby,
        # cfg_key intentionally omitted — read-only in F4
    ),

    # ------------------------------------------------------------------
    # Read-only: LIT[4] — LED while working
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_working",
        name="LED while working",
        icon="mdi:led-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.led_in_working,
        # cfg_key intentionally omitted — read-only in F4
    ),

    # ------------------------------------------------------------------
    # Read-only: LIT[5] — LED while charging
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_charging",
        name="LED while charging",
        icon="mdi:led-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.led_in_charging,
        # cfg_key intentionally omitted — read-only in F4
    ),

    # ------------------------------------------------------------------
    # Read-only: LIT[6] — LED on error
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_error",
        name="LED on error",
        icon="mdi:led-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.led_in_error,
        # cfg_key intentionally omitted — read-only in F4
    ),

    # ------------------------------------------------------------------
    # Read-only: REC[0] — human presence alert enabled
    #
    # CFG.REC = list(9) [enabled, sensitivity, standby, mowing, recharge,
    #                    patrol, alert, photo_consent, push_min].
    # MowerState stores only [0] (enabled) and [1] (sensitivity).
    # Elements [2..8] are not decoded → full 9-element list cannot be
    # safely reconstructed → read-only in F4.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="human_presence_alert",
        name="Human presence alert",
        icon="mdi:motion-sensor",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.human_presence_alert_enabled,
        # cfg_key intentionally omitted — read-only in F4 (REC partially decoded)
    ),

    # NOTE — parent-level `edgemaster` removed 2026-05-15. It was a
    # read-only mirror of the LAST ACTIVE MAP's s6.2[2] value, which
    # is misleading on a multi-map device. Replaced by per-map
    # ``DreameA2MapEdgemasterSwitch`` (read-only, reads from PRE
    # shadow per map). Symmetric to the mowing-efficiency removal.
)


# ---------------------------------------------------------------------------
# SETTINGS-driven switch entities (Task 8)
# ---------------------------------------------------------------------------

class DreameA2EdgeMowingAutoSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Edge mowing auto — per-map SETTINGS switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_edge_mowing_auto"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "settings_edge_mowing_auto")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Automatic Edge Mowing"
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("edgeMowingAuto")
        return None if raw is None else bool(raw)

    @property
    def available(self) -> bool:
        # See DreameA2Switch.available — return False on None to collapse
        # HA's two-button assumed-state widget into a single greyed-out toggle.
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingAuto", new_value=True,
            state_field="settings_edge_mowing_auto",
            map_id=self._map_id,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingAuto", new_value=False,
            state_field="settings_edge_mowing_auto",
            map_id=self._map_id,
        )


class DreameA2EdgeMowingSafeSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Edge mowing safe — per-map SETTINGS switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_edge_mowing_safe"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "settings_edge_mowing_safe")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Safe Edge Mowing"
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("edgeMowingSafe")
        return None if raw is None else bool(raw)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingSafe", new_value=True,
            state_field="settings_edge_mowing_safe",
            map_id=self._map_id,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingSafe", new_value=False,
            state_field="settings_edge_mowing_safe",
            map_id=self._map_id,
        )


class DreameA2EdgeMowingObstacleAvoidanceSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Edge mowing obstacle avoidance — per-map SETTINGS switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_edge_mowing_obstacle_avoidance"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "settings_edge_mowing_obstacle_avoidance")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Obstacle Avoidance on Edges"
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("edgeMowingObstacleAvoidance")
        return None if raw is None else bool(raw)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingObstacleAvoidance", new_value=True,
            state_field="settings_edge_mowing_obstacle_avoidance",
            map_id=self._map_id,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="edgeMowingObstacleAvoidance", new_value=False,
            state_field="settings_edge_mowing_obstacle_avoidance",
            map_id=self._map_id,
        )


class DreameA2ObstacleAvoidanceEnabledSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """Obstacle avoidance enabled — per-map SETTINGS switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "settings_obstacle_avoidance_enabled"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "settings_obstacle_avoidance_enabled")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "LiDAR Obstacle Recognition"
        self._attr_device_info = map_device_info(
            coordinator, map_id,
            name=getattr(coordinator.cloud_state.maps_by_id.get(map_id), "name", None),
        )

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        raw = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceEnabled")
        return None if raw is None else bool(raw)

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="obstacleAvoidanceEnabled", new_value=True,
            state_field="settings_obstacle_avoidance_enabled",
            map_id=self._map_id,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _settings_switch_optimistic_write(
            self, field="obstacleAvoidanceEnabled", new_value=False,
            state_field="settings_obstacle_avoidance_enabled",
            map_id=self._map_id,
        )


class DreameA2AiHumanDetectionSwitch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """AI human detection — reads from cloud_state.ai_human_enabled."""

    _attr_has_entity_name = True
    _attr_translation_key = "cloud_state_ai_human_enabled"
    _attr_name = "Capture Photos AI Obstacles"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "cloud_state_ai_human_enabled")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        return cs.ai_human_enabled

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        ok = await coord.write_ai_human_enabled(True)
        if ok:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        ok = await coord.write_ai_human_enabled(False)
        if ok:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()


class DreameA2AiRecognitionHumansSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Humans (bit 0) — per-map."""

    _BIT = _AI_HUMANS_BIT
    _attr_translation_key = "ai_recognition_humans"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_humans")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Humans"


class DreameA2AiRecognitionAnimalsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Animals (bit 1) — per-map."""

    _BIT = _AI_ANIMALS_BIT
    _attr_translation_key = "ai_recognition_animals"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_animals")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Animals"


class DreameA2AiRecognitionObjectsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Objects (bit 2) — per-map."""

    _BIT = _AI_OBJECTS_BIT
    _attr_translation_key = "ai_recognition_objects"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_objects")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Objects"
