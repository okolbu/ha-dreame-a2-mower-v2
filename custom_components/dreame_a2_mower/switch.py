"""Switch platform — settable and read-only boolean settings for the Dreame A2 Mower.

F4.6.2: Settable switches write via coordinator.write_setting with the full
        wire payload reconstructed from MowerState.  Read-only switches log a
        warning on toggle and no-op.

Settable (full wire payload reconstructible from MowerState):
  - switch.child_lock        → CFG.CLS  (bool, single value)
  - switch.dnd               → CFG.DND  (list[3]: enabled, start_min, end_min — all in MowerState)
  - switch.rain_protection   → CFG.WRP  (list[2]: enabled, resume_hours — both in MowerState)
  - switch.low_speed_at_night→ CFG.LOW  (list[3]: enabled, start_min, end_min — all in MowerState)
  - switch.custom_charging_period → CFG.BAT (list[6]: all 6 fields in MowerState)
  - switch.anti_theft_lift_alarm      → CFG.ATA (list[3]: all 3 in MowerState)
  - switch.anti_theft_offmap_alarm    → CFG.ATA (list[3]: all 3 in MowerState)
  - switch.anti_theft_realtime_location → CFG.ATA (list[3]: all 3 in MowerState)
  - switch.frost_protection            → CFG.FDP  (int 0|1)
  - switch.auto_recharge_standby       → CFG.STUN (int 0|1)
  - switch.ai_obstacle_photos          → CFG.AOP  (int 0|1)
  - switch.navigation_path_smart       → CFG.PROT (int 0|1; 1=smart, 0=direct)
  - switch.msg_alert_{anomaly,error,task,consumables} → CFG.MSG_ALERT (list[4])
  - switch.voice_{regular_notification,work_status,special_status,error_status}
                                        → CFG.VOICE (list[4])

Read-only (wire payload NOT fully reconstructible):
  - switch.led_period        → CFG.LIT  list(8) — indices 1, 2 (start_min, end_min) and
                                7 (unknown trailing toggle) are NOT stored in MowerState;
                                cannot safely reconstruct the full 8-element list.
  - switch.led_in_standby    → CFG.LIT  same reason
  - switch.led_in_working    → CFG.LIT  same reason
  - switch.led_in_charging   → CFG.LIT  same reason
  - switch.led_in_error      → CFG.LIT  same reason
  - switch.human_presence_alert → CFG.REC  list(9) — only [0] (enabled) and [1]
                                (sensitivity) decoded; [2..8] not in MowerState.

Live-verification concerns:
  - BAT[2] = unknown_flag is always 1 in observed data; reconstructed payload
    uses 1 as the hard-coded value.  Same concern as F4.6.1 number.py.
  - LIT[7] = unknown trailing toggle not characterised; this is why LIT-backed
    switches are read-only in F4.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2SwitchEntityDescription(SwitchEntityDescription):
    """Switch descriptor with typed value_fn and optional write helpers.

    ``value_fn``       — reads the current bool from MowerState.
    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
                         If None, the switch is read-only in F4.
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, new_enabled_bool).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update applied by coordinator.write_setting.
    """

    value_fn: Callable[[MowerState], bool | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, bool], Any] | None = None
    field_updates_fn: Callable[[MowerState, bool], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Wire-value builders — settable switches
# ---------------------------------------------------------------------------

def _build_cls(state: MowerState, enabled: bool) -> int:
    """CLS wire value: single int {0, 1}."""
    return int(enabled)


def _cls_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"child_lock_enabled": enabled}


def _build_dnd(state: MowerState, enabled: bool) -> list:
    """DND wire value: list(3) [enabled, start_min, end_min].

    CFG.DND confirmed on g2408 (coordinator._refresh_cfg §DND).
    All three fields are stored in MowerState (dnd_enabled, dnd_start_min,
    dnd_end_min), so full reconstruction is safe.

    Defaults: start_min=1200 (20:00), end_min=480 (08:00) — the confirmed
    factory values observed on g2408.
    """
    return [
        int(enabled),                             # [0] enabled  (new)
        int(state.dnd_start_min or 1200),         # [1] start_min
        int(state.dnd_end_min or 480),            # [2] end_min
    ]


def _dnd_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"dnd_enabled": enabled}


def _build_wrp(state: MowerState, enabled: bool) -> list:
    """WRP wire value: list(2) [enabled, resume_hours].

    CFG.WRP confirmed on g2408 (coordinator._refresh_cfg §WRP).
    Both fields are stored in MowerState (rain_protection_enabled,
    rain_protection_resume_hours), so full reconstruction is safe.

    Default resume_hours=0 means "Don't Mow After Rain" (no auto-resume).
    """
    return [
        int(enabled),                                   # [0] enabled  (new)
        int(state.rain_protection_resume_hours or 0),   # [1] resume_hours
    ]


def _wrp_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"rain_protection_enabled": enabled}


def _build_low(state: MowerState, enabled: bool) -> list:
    """LOW wire value: list(3) [enabled, start_min, end_min].

    CFG.LOW confirmed on g2408 (coordinator._refresh_cfg §LOW).
    All three fields are stored in MowerState (low_speed_at_night_enabled,
    low_speed_at_night_start_min, low_speed_at_night_end_min), so full
    reconstruction is safe.

    Defaults mirror DND defaults: 20:00→08:00.
    """
    return [
        int(enabled),                                         # [0] enabled  (new)
        int(state.low_speed_at_night_start_min or 1200),     # [1] start_min
        int(state.low_speed_at_night_end_min or 480),        # [2] end_min
    ]


def _low_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"low_speed_at_night_enabled": enabled}


def _build_bat_custom_charging(state: MowerState, enabled: bool) -> list:
    """BAT wire value: list(6) [recharge_pct, resume_pct, unknown_flag,
    custom_charging, start_min, end_min].

    CFG.BAT confirmed on g2408 (coordinator._refresh_cfg §BAT).
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

    CFG.ATA confirmed on g2408 (coordinator._refresh_cfg §ATA, all 3 indices
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


def _prot_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    # CFG.PROT mapping: 0 = direct path, 1 = smart path. The `enabled` flag
    # passed by HA's switch on/off corresponds to "smart" path being on.
    return {"navigation_path_smart": enabled}


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
    DreameA2SwitchEntityDescription(
        key="navigation_path_smart",
        name="Smart navigation path",
        icon="mdi:routes",
        value_fn=lambda s: s.navigation_path_smart,
        cfg_key="PROT",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_prot_field_updates,
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
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DreameA2Switch(coordinator, desc) for desc in SWITCHES]
    )


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2Switch(
    CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
    """A coordinator-backed switch entity.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_turn_on / async_turn_off is called.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2SwitchEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        client = coordinator._cloud  # may be None during very-early setup
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_value(False)

    async def _async_set_value(self, enabled: bool) -> None:
        """Write the new state to the mower via the coordinator."""
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "switch.%s: no write path configured (read-only in F4); "
                "ignoring turn_%s",
                desc.key,
                "on" if enabled else "off",
            )
            return

        # Build the full wire value expected by the firmware.
        if desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, enabled)
        else:
            wire_value = int(enabled)

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, enabled)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "switch.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )
