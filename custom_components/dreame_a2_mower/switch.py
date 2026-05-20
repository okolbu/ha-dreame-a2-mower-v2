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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from ._switch_base import DreameA2Switch
from .switch_global import (
    SWITCHES,
    DreameA2EdgeMowingAutoSwitch,
    DreameA2EdgeMowingSafeSwitch,
    DreameA2EdgeMowingObstacleAvoidanceSwitch,
    DreameA2ObstacleAvoidanceEnabledSwitch,
    DreameA2AiHumanDetectionSwitch,
    DreameA2AiRecognitionHumansSwitch,
    DreameA2AiRecognitionAnimalsSwitch,
    DreameA2AiRecognitionObjectsSwitch,
    # Re-exported so existing tests that import builders from switch still work.
    _build_ata_lift,
    _build_ata_offmap,
    _build_ata_realtime,
    _build_bat_custom_charging,
    _build_cls,
    _build_dnd,
    _build_int_toggle,
    _build_low,
    _build_msg_alert_anomaly,
    _build_msg_alert_consumables,
    _build_msg_alert_error,
    _build_msg_alert_task,
    _build_voice_error,
    _build_voice_regular,
    _build_voice_special,
    _build_voice_work,
    _build_wrp,
)
from .switch_map import DreameA2MapEdgemasterSwitch


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
    entities: list = [DreameA2Switch(coordinator, desc) for desc in SWITCHES]
    entities.append(DreameA2AiHumanDetectionSwitch(coordinator))
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.extend([
            DreameA2EdgeMowingAutoSwitch(coordinator, map_id=map_id),
            DreameA2EdgeMowingSafeSwitch(coordinator, map_id=map_id),
            DreameA2EdgeMowingObstacleAvoidanceSwitch(coordinator, map_id=map_id),
            DreameA2ObstacleAvoidanceEnabledSwitch(coordinator, map_id=map_id),
            DreameA2AiRecognitionHumansSwitch(coordinator, map_id=map_id),
            DreameA2AiRecognitionAnimalsSwitch(coordinator, map_id=map_id),
            DreameA2AiRecognitionObjectsSwitch(coordinator, map_id=map_id),
            DreameA2MapEdgemasterSwitch(coordinator, map_id=map_id),
        ])
    async_add_entities(entities)
