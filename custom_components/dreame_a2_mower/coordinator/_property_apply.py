"""Module-level helpers for property push handling.

Constants and pure functions that apply a (siid, piid, value) push to
a MowerState dataclass. Extracted from the original ``coordinator.py``
2026-05-15 as part of the coordinator-decomposition refactor (see
``docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md``).

The original module docstring follows.
"""
# Original coordinator.py docstring (verbatim):
# Coordinator for the Dreame A2 Mower integration.
#
# Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
# MowerState, and the dispatch from inbound MQTT pushes to state
# updates. Entities subscribe to coordinator updates and read from
# ``coordinator.data`` (the MowerState).
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..inventory.loader import load_inventory
from ..live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from ..live_map.finalize import decide as _finalize_decide
from ..live_map.state import LiveMapState
from ..mower.actions import ACTION_TABLE, MowerAction
from ..mower.property_mapping import PROPERTY_MAPPING, resolve_field
from ..mower.state import ChargingStatus, MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import telemetry as _telemetry
from ..protocol import wheel_bind as _wheel_bind

# F6.4.1: schema checker — instantiated once at module level.
_SESSION_SUMMARY_CHECK = SchemaCheck(SCHEMA_SESSION_SUMMARY)

# (siid, piid) slots whose payload is a binary blob handled by a
# dedicated _apply_* function below. They are NOT in PROPERTY_MAPPING
# (which is for field-style slots) but they ARE handled, so the
# novelty check in handle_property_push must skip them — otherwise
# every heartbeat tick would re-arm the watchdog with new bytes.
_BLOB_SLOTS: frozenset[tuple[int, int]] = frozenset({(1, 1), (1, 4), (2, 51)})

# (siid, piid) slots intentionally suppressed from the novelty
# pipeline — typically command echoes that the mower re-broadcasts as
# a property change after we send a TASK. Logging or recording them
# is noise.
#   (2, 50) — action-surface TASK envelope (echo of our own command).
#   (1, 50) / (1, 51) — empty-dict {} pushes during a mow; content
#                       not yet decoded.
#   (1, 52) — empty-dict {} session-boundary marker ("task ended /
#             flush"); confirmed in docs/research §4.7. We rely on
#             s2p56 transitions for the state machine, so logging
#             this would just be noise.
#   (6, 117) — observed as small int (e.g. 3) during a session;
#              unmapped on g2408 and not driving any state machine.

# Inventory snapshot computed once at import. Kept module-level for the
# fast-path lookup the legacy literal frozenset provided. Migration from
# hardcoded set: see docs/superpowers/specs/2026-05-06-axis3-runtime-harness-design.md.
_INVENTORY = load_inventory()
_SUPPRESSED_SLOTS: frozenset[tuple[int, int]] = _INVENTORY.suppressed_slots

# Slots that the device pushes as a "settings-saved tripwire" — fires
# every time the firmware persists a settings change (whether the
# trigger was the Dreame app, BT, or HA). Receiving one of these
# schedules a debounced cloud-state refresh so app-side edits show up
# in HA within seconds instead of waiting for the next 2-min poll.
#
# - (6, 2) FRAME_INFO: confirmed tripwire 2026-04-26 — fires on any
#   settings save even when none of the four frame elements change.
#   See docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md
#   §"settings-saved tripwire".
_SETTINGS_TRIPWIRE_SLOTS: frozenset[tuple[int, int]] = frozenset({(6, 2)})

# Notification slug map — keyed off s2p2 value, value = stable HA event_type
# slug. Hardcoded text was dropped 2026-05-26: the integration now fetches the
# authoritative text live from /dreame-messaging/user/device-messages/v2 on each
# s2p2 transition (see _NotificationsMixin), so this map only needs to identify
# the *slug* — the user-visible string comes from the cloud's
# localizationContents in the account's language.
#
# Slugs marked 'cloud-verified 2026-05-26' were empirically extracted from the
# cloud's message store; the others are best-guess identifiers that survive
# until they're verified the same way.
#
# Source: docs/research/app-notification-history-2026-05-16.md § Empirical s2p2 mapping.
S2P2_EVENT_TYPES: dict[int, str] = {
    0:   "hanging",
    23:  "emergency_stop",
    27:  "human_detected",
    28:  "blades_worn",                     # cloud-verified 2026-05-26
    30:  "maintenance_reminder",
    31:  "positioning_failed_stuck",
    33:  "positioning_failed_transient",
    36:  "failed_to_start_task",            # cloud-verified 2026-05-26
    43:  "battery_temp_low_charging_paused",
    47:  "task_cancelled",                  # mova [MOWER] community-confirmed
    48:  "mowing_complete",                 # cloud-verified 2026-05-26
    50:  "mowing_started",                  # cloud-verified 2026-05-26
    53:  "scheduled_mowing_started",
    54:  "low_battery_return",
    56:  "rain_protection",                 # cloud-verified 2026-05-26
    63:  "schedule_cancelled_busy",         # cloud-verified 2026-05-26
    70:  "continue_unfinished_task",        # cloud-verified 2026-05-26
    71:  "positioning_failure",
    73:  "top_cover_open",
    75:  "arrived_at_maintenance_point",
    78:  "robot_in_hidden_zone",
    117: "station_disconnected",
}

# Event type fired when s2p2 carries a value not in S2P2_EVENT_TYPES — the
# cloud still provides authoritative text in the event payload, but the slug
# is generic so HA can register the event_type up-front.
S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"


def _coerce_blob(value: Any, slot_label: str) -> bytes | None:
    """Normalize an MQTT blob payload to a ``bytes`` object.

    Three on-wire shapes are accepted:
    - ``str`` — base64-encoded (legacy/cloud format)
    - ``bytes`` / ``bytearray`` — raw byte string
    - ``list`` of ``int`` — JSON-array representation (live g2408 format,
      paho deserializes JSON arrays to Python lists)

    Returns ``None`` and logs a WARNING when the value can't be coerced.
    """
    if isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            LOGGER.warning(
                "%s %s: value not base64-decodable: %r",
                LOG_NOVEL_PROPERTY,
                slot_label,
                value[:32],
            )
            return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        try:
            return bytes(value)
        except (TypeError, ValueError) as ex:
            LOGGER.warning(
                "%s %s: list payload not bytes-convertible: %s",
                LOG_NOVEL_PROPERTY,
                slot_label,
                ex,
            )
            return None
    LOGGER.warning(
        "%s %s: unexpected value type %s",
        LOG_NOVEL_PROPERTY,
        slot_label,
        type(value).__name__,
    )
    return None


def _apply_s1p1_heartbeat(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.1 heartbeat blob and apply its flags to MowerState.

    Accepts a base64 string, raw bytes/bytearray, or a list of ints
    (the g2408 on-wire format via paho's JSON-list deserialization).
    Malformed blobs are dropped with a WARNING and state is returned
    unchanged.
    """
    blob = _coerce_blob(value, "s1.1")
    if blob is None:
        return state

    try:
        decoded = _heartbeat.decode_s1p1(blob)
    except Exception as ex:
        LOGGER.warning("%s s1.1 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
        return state

    return dataclasses.replace(
        state,
        battery_temp_low=getattr(decoded, "battery_temp_low", None),
        drop_tilt=getattr(decoded, "drop_tilt", None),
        bumper=getattr(decoded, "bumper", None),
        lift=getattr(decoded, "lift", None),
        emergency_stop=getattr(decoded, "emergency_stop", None),
        safety_alert_active=getattr(decoded, "safety_alert_active", None),
        wifi_rssi_dbm=getattr(decoded, "wifi_rssi_dbm", None),
    )


def _apply_s1p4_telemetry(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.4 telemetry blob and apply its fields to MowerState.

    Accepts a base64 string, raw bytes/bytearray, or a list of ints
    (the g2408 on-wire format via paho's JSON-list deserialization).
    Dispatches to ``decode_s1p4`` for 33-byte frames and
    ``decode_s1p4_position`` for 8-byte BEACON / 10-byte BUILDING frames.
    Malformed blobs are dropped with a WARNING.
    """
    blob = _coerce_blob(value, "s1.4")
    if blob is None:
        return state

    if len(blob) == _telemetry.FRAME_LENGTH:
        # Full 33-byte telemetry frame — all fields available.
        try:
            decoded = _telemetry.decode_s1p4(blob)
        except Exception as ex:
            LOGGER.warning("%s s1.4 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
            return state
        # Wheel-bind diagnostic: detect "position held while area counter
        # advances" using the prior frame's pose + area. See
        # protocol/wheel_bind.py for the threshold rationale.
        wb = _wheel_bind.detect_wheel_bind(
            prev_x_m=state.position_x_m,
            prev_y_m=state.position_y_m,
            prev_area_mowed_m2=state.area_mowed_m2,
            prev_consecutive_frames=state.wheel_bind_consecutive_frames,
            new_x_m=decoded.x_m,
            new_y_m=decoded.y_m,
            new_area_mowed_m2=decoded.area_mowed_m2,
        )
        # Surface a one-shot WARNING on each rising edge so the HA log
        # shows "the mower is wedged" without flooding on every frame.
        if wb.active and not state.wheel_bind_active:
            LOGGER.warning(
                "Wheel-bind detected at pos=(%.2f, %.2f) — area_mowed advancing "
                "while wheels stationary. Common precursor to FTRTS on edge runs. "
                "consecutive_frames=%d",
                decoded.x_m, decoded.y_m, wb.consecutive_frames,
            )
        return dataclasses.replace(
            state,
            position_x_m=decoded.x_m,
            position_y_m=decoded.y_m,
            position_heading_deg=decoded.heading_deg,
            mowing_phase=decoded.phase_raw,
            area_mowed_m2=decoded.area_mowed_m2,
            # uint24 read survives lawns > 655 m² where the legacy
            # uint16 read at the same byte slot truncates.
            task_total_area_m2=decoded.total_uint24_m2,
            wheel_bind_active=wb.active,
            wheel_bind_consecutive_frames=wb.consecutive_frames,
        )
    elif len(blob) in (_telemetry.FRAME_LENGTH_BEACON, _telemetry.FRAME_LENGTH_BUILDING):
        # Short frame (8-byte BEACON or 10-byte BUILDING) — position only.
        try:
            decoded_pos = _telemetry.decode_s1p4_position(blob)
        except Exception as ex:
            LOGGER.warning("%s s1.4 short-frame decode failed: %s", LOG_NOVEL_PROPERTY, ex)
            return state
        return dataclasses.replace(
            state,
            position_x_m=decoded_pos.x_m,
            position_y_m=decoded_pos.y_m,
        )
    else:
        LOGGER.warning(
            "%s s1.4: unexpected blob length %d — dropping",
            LOG_NOVEL_PROPERTY,
            len(blob),
        )
        return state


def _project_north_east(
    x_m: float | None,
    y_m: float | None,
    bearing_deg: float | None,
) -> tuple[float | None, float | None]:
    """Project dock-frame (x_m, y_m) into compass-frame (north_m, east_m).

    Convention: ``bearing_deg`` is the compass bearing (CW from north) of
    the dock's local X axis. The dock Y axis is 90 deg CCW from X
    (right-hand frame).

    With ``bearing_deg == 0`` (dock X points north, dock Y points west):
    ``north_m = x_m`` and ``east_m = -y_m`` would be the strict CCW-Y
    interpretation. We pick the more common engineering convention where
    Y is to the LEFT of forward X (so positive y is "left" of the dock
    when facing along its X axis):

    .. code:: python

        north_m =  x_m * cos(yaw) - y_m * sin(yaw)
        east_m  =  x_m * sin(yaw) + y_m * cos(yaw)

    Returns ``(None, None)`` when any input is ``None`` (no projection
    possible — used to keep the position_north_m / position_east_m
    sensors Unknown until the user supplies a bearing).

    If the resulting N/E values are clearly wrong (signs flipped or 90
    deg rotated) after live verification, the user adjusts the bearing
    value rather than us swapping conventions in code.
    """
    if x_m is None or y_m is None or bearing_deg is None:
        return (None, None)
    yaw_rad = math.radians(bearing_deg)
    cos_y, sin_y = math.cos(yaw_rad), math.sin(yaw_rad)
    north_m = x_m * cos_y - y_m * sin_y
    east_m = x_m * sin_y + y_m * cos_y
    return (north_m, east_m)


def _apply_s2p51_settings(state: MowerState, value: Any) -> MowerState:
    """Decode the s2.51 multiplexed-config payload and update MowerState.

    The payload is a dict decoded from the on-wire MQTT JSON value.
    Dispatches by Setting variant and reads sub-fields via event.values.
    Non-dict payloads and S2P51DecodeError are dropped with a WARNING.
    AMBIGUOUS_TOGGLE, AMBIGUOUS_4LIST, and TIMESTAMP log at DEBUG and are
    skipped (no MowerState field assignment possible without extra context).
    """
    if not isinstance(value, dict):
        LOGGER.warning(
            "%s s2.51: expected dict, got %s — dropping",
            LOG_NOVEL_PROPERTY,
            type(value).__name__,
        )
        return state
    try:
        event = _s2p51.decode_s2p51(value)
    except _s2p51.S2P51DecodeError as ex:
        LOGGER.warning(
            "%s s2.51 decode failed: %s — payload=%r",
            LOG_NOVEL_PROPERTY,
            ex,
            value,
        )
        return state

    setting = event.setting
    v = event.values

    if setting == _s2p51.Setting.RAIN_PROTECTION:
        return dataclasses.replace(
            state,
            rain_protection_enabled=v.get("enabled"),
            rain_protection_resume_hours=v.get("resume_hours"),
        )

    if setting == _s2p51.Setting.LOW_SPEED_NIGHT:
        return dataclasses.replace(
            state,
            low_speed_at_night_enabled=v.get("enabled"),
            low_speed_at_night_start_min=v.get("start_min"),
            low_speed_at_night_end_min=v.get("end_min"),
        )

    if setting == _s2p51.Setting.ANTI_THEFT:
        return dataclasses.replace(
            state,
            anti_theft_lift_alarm=v.get("lift_alarm"),
            anti_theft_offmap_alarm=v.get("offmap_alarm"),
            anti_theft_realtime_location=v.get("realtime_location"),
        )

    if setting == _s2p51.Setting.DND:
        return dataclasses.replace(
            state,
            dnd_enabled=v.get("enabled"),
            dnd_start_min=v.get("start_min"),
            dnd_end_min=v.get("end_min"),
        )

    if setting == _s2p51.Setting.CHARGING:
        return dataclasses.replace(
            state,
            auto_recharge_battery_pct=v.get("recharge_pct"),
            resume_battery_pct=v.get("resume_pct"),
            custom_charging_enabled=v.get("custom_charging"),
            charging_start_min=v.get("start_min"),
            charging_end_min=v.get("end_min"),
        )

    if setting == _s2p51.Setting.LED_PERIOD:
        return dataclasses.replace(
            state,
            led_period_enabled=v.get("enabled"),
            led_in_standby=v.get("standby"),
            led_in_working=v.get("working"),
            led_in_charging=v.get("charging"),
            led_in_error=v.get("error"),
        )

    if setting == _s2p51.Setting.HUMAN_PRESENCE_ALERT:
        return dataclasses.replace(
            state,
            human_presence_alert_enabled=v.get("enabled"),
            human_presence_alert_sensitivity=v.get("sensitivity"),
            human_presence_scenario_standby=v.get("standby"),
            human_presence_scenario_mowing=v.get("mowing"),
            human_presence_scenario_recharge=v.get("recharge"),
            human_presence_scenario_patrol=v.get("patrol"),
            human_presence_alert_voice=v.get("alert"),
            human_presence_alert_push_interval_min=v.get("push_min"),
        )

    if setting == _s2p51.Setting.LANGUAGE:
        return dataclasses.replace(
            state,
            language_text_idx=v.get("text_idx"),
            language_voice_idx=v.get("voice_idx"),
        )

    if setting == _s2p51.Setting.TIMESTAMP:
        return dataclasses.replace(
            state,
            last_settings_change_unix=v.get("time"),
        )

    if setting == _s2p51.Setting.CONSUMABLES:
        return _apply_consumables(state, v.get("counters", []))

    # AMBIGUOUS_TOGGLE and AMBIGUOUS_4LIST cannot be mapped to a single
    # MowerState field without external context (e.g. getCFG diff). Log at
    # DEBUG and leave state unchanged.
    LOGGER.debug("s2.51 unmapped setting=%s event=%r", setting, event)
    return state


def _consumable_pct_remaining(counter: int, threshold_min: int | None) -> float | None:
    """Return remaining-life % for a slot, or None if untracked / out of range."""
    if threshold_min is None or counter < 0:
        return None
    used_pct = (counter / threshold_min) * 100.0
    remaining = 100.0 - used_pct
    if remaining < 0.0:
        remaining = 0.0
    return round(remaining, 1)


def cfg_to_state_updates(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pure CFG dict -> MowerState field updates.

    Only includes a field when its CFG key is present and decodes cleanly;
    an absent or malformed key is omitted (the caller keeps the prior value).
    pre_mowing_height_mm / pre_edgemaster are intentionally NOT ported here —
    they are owned by the s6.2 push (mower/property_mapping.py:114,117).

    The decode bodies are ported verbatim from the legacy ``_refresh_cfg``
    (``coordinator/_refreshers.py``): identical guards, casts, threshold
    indices, and ``LOGGER.warning`` calls. The only change is the pattern —
    default-None local + unconditional ``dataclasses.replace`` kwarg becomes a
    guarded ``updates[field] = decoded`` — plus the two push-owned exclusions.
    """
    updates: dict[str, Any] = {}

    # ---- CMS: per-consumable wear ----
    # Same shape as the s2p51 CONSUMABLES push:
    # [blades_min, cleaning_brush_min, robot_maintenance_min, link_module]
    # Thresholds + slot identity come from protocol/config_s2p51.py so
    # there's a single source of truth between this CFG path and the
    # live CONSUMABLES path. `-1` in any slot means "no timer applies".
    cms = cfg.get("CMS")
    if isinstance(cms, list) and len(cms) >= 3:
        try:
            updates["blades_life_pct"] = _consumable_pct_remaining(
                int(cms[0]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[0]
            )
            updates["cleaning_brush_life_pct"] = _consumable_pct_remaining(
                int(cms[1]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[1]
            )
            updates["robot_maintenance_life_pct"] = _consumable_pct_remaining(
                int(cms[2]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[2]
            )
        except (TypeError, ValueError, ZeroDivisionError) as ex:
            LOGGER.warning("[CFG] CMS decode error: %s — cms=%r", ex, cms)

    # ---- CLS: child lock ----
    # CFG.CLS = int {0, 1}. Confirmed on g2408 (docs/research §6.2).
    cls_raw = cfg.get("CLS")
    if cls_raw is not None:
        try:
            updates["child_lock_enabled"] = bool(int(cls_raw))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] CLS decode error: %s — cls=%r", ex, cls_raw)

    # ---- VOL: voice volume ----
    # CFG.VOL = int 0..100. Confirmed on g2408.
    vol_raw = cfg.get("VOL")
    if vol_raw is not None:
        try:
            updates["volume_pct"] = int(vol_raw)
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] VOL decode error: %s — vol=%r", ex, vol_raw)

    # ---- LANG: language indices ----
    # CFG.LANG = list(2) [text_idx, voice_idx]. Confirmed on g2408.
    # language_code stores a human-readable key like "text=2,voice=7";
    # language_text_idx / language_voice_idx carry the raw indices.
    lang_raw = cfg.get("LANG")
    if isinstance(lang_raw, list) and len(lang_raw) >= 2:
        try:
            language_text_idx = int(lang_raw[0])
            language_voice_idx = int(lang_raw[1])
            updates["language_text_idx"] = language_text_idx
            updates["language_voice_idx"] = language_voice_idx
            updates["language_code"] = f"text={language_text_idx},voice={language_voice_idx}"
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] LANG decode error: %s — lang=%r", ex, lang_raw)

    # ---- DND: do-not-disturb ----
    # CFG.DND = list(3) [enabled, start_min, end_min] where start_min and
    # end_min are integer minutes-from-midnight (confirmed via iobroker
    # cross-ref: [0, 1200, 480] = off, 20:00→08:00).
    dnd_raw = cfg.get("DND")
    if isinstance(dnd_raw, list) and len(dnd_raw) >= 3:
        try:
            updates["dnd_enabled"] = bool(int(dnd_raw[0]))
            updates["dnd_start_min"] = int(dnd_raw[1])
            updates["dnd_end_min"] = int(dnd_raw[2])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] DND decode error: %s — dnd=%r", ex, dnd_raw)

    # ---- PRE: mowing preferences ----
    # On g2408 PRE is list(2) [zone_id, mode] — NOT the full 10-element APK
    # schema (docs/research §6.2 §PRE-schema). Elements 2..9 do not exist on
    # this firmware version; pre_mowing_height_mm and pre_edgemaster come from
    # s6.2 push events instead and are intentionally NOT ported here.
    pre_raw = cfg.get("PRE")
    if isinstance(pre_raw, list):
        try:
            if len(pre_raw) >= 1:
                updates["pre_zone_id"] = int(pre_raw[0])
            if len(pre_raw) >= 2:
                updates["pre_mowing_efficiency"] = int(pre_raw[1])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] PRE decode error: %s — pre=%r", ex, pre_raw)

    # ---- WRP: rain protection ----
    # CFG.WRP = list(2) [enabled, resume_hours]. Confirmed on g2408 (isolated
    # toggle 2026-04-24). resume_hours=0 → "Don't Mow After Rain" (no auto-resume).
    wrp_raw = cfg.get("WRP")
    if isinstance(wrp_raw, list) and len(wrp_raw) >= 2:
        try:
            updates["rain_protection_enabled"] = bool(int(wrp_raw[0]))
            updates["rain_protection_resume_hours"] = int(wrp_raw[1])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] WRP decode error: %s — wrp=%r", ex, wrp_raw)

    # ---- LOW: low-speed nighttime mode ----
    # CFG.LOW = list(3) [enabled, start_min, end_min]. Confirmed on g2408
    # (live toggle 2026-04-24). Same shape as DND. Example: [1, 1200, 480].
    low_raw = cfg.get("LOW")
    if isinstance(low_raw, list) and len(low_raw) >= 3:
        try:
            updates["low_speed_at_night_enabled"] = bool(int(low_raw[0]))
            updates["low_speed_at_night_start_min"] = int(low_raw[1])
            updates["low_speed_at_night_end_min"] = int(low_raw[2])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] LOW decode error: %s — low=%r", ex, low_raw)

    # ---- BAT: charging config ----
    # CFG.BAT = list(6) [recharge_pct, resume_pct, unknown_flag,
    #                     custom_charging, start_min, end_min].
    # Confirmed on g2408 (docs/research §6.2). Matches s2.51 CHARGING decoder.
    bat_raw = cfg.get("BAT")
    if isinstance(bat_raw, list) and len(bat_raw) >= 6:
        try:
            updates["auto_recharge_battery_pct"] = int(bat_raw[0])
            updates["resume_battery_pct"] = int(bat_raw[1])
            # bat_raw[2] = unknown_flag (consistently 1; semantic TBD)
            updates["custom_charging_enabled"] = bool(int(bat_raw[3]))
            updates["charging_start_min"] = int(bat_raw[4])
            updates["charging_end_min"] = int(bat_raw[5])
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] BAT decode error: %s — bat=%r", ex, bat_raw)

    # ---- LIT: headlight / LED config ----
    # CFG.LIT = list(8) [enabled, start_min, end_min, standby, working,
    #                     charging, error, unknown].
    # Confirmed on g2408 (docs/research §6.2). Matches s2.51 LED_PERIOD decoder.
    lit_raw = cfg.get("LIT")
    if isinstance(lit_raw, list) and len(lit_raw) >= 7:
        try:
            updates["led_period_enabled"] = bool(int(lit_raw[0]))
            # lit_raw[1] = start_min (charging-schedule; not in MowerState F4)
            # lit_raw[2] = end_min   (charging-schedule; not in MowerState F4)
            updates["led_in_standby"] = bool(int(lit_raw[3]))
            updates["led_in_working"] = bool(int(lit_raw[4]))
            updates["led_in_charging"] = bool(int(lit_raw[5]))
            updates["led_in_error"] = bool(int(lit_raw[6]))
            # lit_raw[7] = unknown trailing toggle (not yet characterised)
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] LIT decode error: %s — lit=%r", ex, lit_raw)

    # ---- ATA: anti-theft alarm ----
    # CFG.ATA = list(3) [lift_alarm, offmap_alarm, realtime_location].
    # Confirmed on g2408 (all 3 indices individually verified 2026-04-27).
    ata_raw = cfg.get("ATA")
    if isinstance(ata_raw, list) and len(ata_raw) >= 3:
        try:
            updates["anti_theft_lift_alarm"] = bool(int(ata_raw[0]))
            updates["anti_theft_offmap_alarm"] = bool(int(ata_raw[1]))
            updates["anti_theft_realtime_location"] = bool(int(ata_raw[2]))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] ATA decode error: %s — ata=%r", ex, ata_raw)

    # ---- REC: human presence alert ----
    # CFG.REC = list(9) [enabled, sensitivity, standby, mowing, recharge,
    #                     patrol, voice, photo_consent, push_min].
    # Confirmed on g2408 (docs/research §6.2). Matches s2.51
    # HUMAN_PRESENCE_ALERT decoder.
    # REC[7] is `photo_consent` — privacy-policy acceptance for the
    # "Capture Photos of AI-Detected Obstacles" feature (CFG.AOP).
    # See MowerState.photo_consent docstring + binary_sensor.photo_consent.
    rec_raw = cfg.get("REC")
    if isinstance(rec_raw, list) and len(rec_raw) >= 2:
        try:
            updates["human_presence_alert_enabled"] = bool(int(rec_raw[0]))
            updates["human_presence_alert_sensitivity"] = int(rec_raw[1])
            if len(rec_raw) >= 9:
                updates["human_presence_scenario_standby"] = bool(int(rec_raw[2]))
                updates["human_presence_scenario_mowing"] = bool(int(rec_raw[3]))
                updates["human_presence_scenario_recharge"] = bool(int(rec_raw[4]))
                updates["human_presence_scenario_patrol"] = bool(int(rec_raw[5]))
                updates["human_presence_alert_voice"] = bool(int(rec_raw[6]))
                updates["photo_consent"] = bool(int(rec_raw[7]))
                updates["human_presence_alert_push_interval_min"] = int(rec_raw[8])
            elif len(rec_raw) >= 8:
                updates["photo_consent"] = bool(int(rec_raw[7]))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] REC decode error: %s — rec=%r", ex, rec_raw)

    # ---- AMBIGUOUS_TOGGLE shape members (single-int CFG keys) ----
    # All four use CFG int {0, 1}. Confirmed 2026-04-30 via toggle tests;
    # these CFG keys were previously read but never plumbed to MowerState.
    def _cfg_bool(name: str) -> bool | None:
        raw = cfg.get(name)
        if raw is None:
            return None
        try:
            return bool(int(raw))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] %s decode error: %s — raw=%r", name, ex, raw)
            return None

    for cfg_key, field in (
        ("FDP", "frost_protection_enabled"),
        ("STUN", "auto_recharge_standby_enabled"),
        ("AOP", "ai_obstacle_photos_enabled"),
        # CFG.PROT mapping: {0: direct, 1: smart}. We store True iff smart.
        ("PROT", "navigation_path_smart"),
    ):
        v = _cfg_bool(cfg_key)
        if v is not None:
            updates[field] = v

    # ---- MSG_ALERT (Notification Preferences, 4-bool list) ----
    # Slots: [anomaly, error, task, consumables_messages].
    msg_alert_raw = cfg.get("MSG_ALERT")
    if isinstance(msg_alert_raw, list) and len(msg_alert_raw) >= 4:
        try:
            updates["msg_alert_anomaly"] = bool(int(msg_alert_raw[0]))
            updates["msg_alert_error"] = bool(int(msg_alert_raw[1]))
            updates["msg_alert_task"] = bool(int(msg_alert_raw[2]))
            updates["msg_alert_consumables"] = bool(int(msg_alert_raw[3]))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] MSG_ALERT decode error: %s — raw=%r", ex, msg_alert_raw)

    # ---- VOICE (Voice Prompt Modes, 4-bool list) ----
    # Slots: [regular_notification, work_status, special_status, error_status].
    voice_raw = cfg.get("VOICE")
    if isinstance(voice_raw, list) and len(voice_raw) >= 4:
        try:
            updates["voice_regular_notification"] = bool(int(voice_raw[0]))
            updates["voice_work_status"] = bool(int(voice_raw[1]))
            updates["voice_special_status"] = bool(int(voice_raw[2]))
            updates["voice_error_status"] = bool(int(voice_raw[3]))
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[CFG] VOICE decode error: %s — raw=%r", ex, voice_raw)

    return updates


def _apply_consumables(state: MowerState, counters: list[int]) -> MowerState:
    """Update consumable life percentages from an s2.51 CONSUMABLES counter array.

    Slot layout & thresholds come from `protocol.config_s2p51`
    (CONSUMABLE_SLOT_NAMES, CONSUMABLE_THRESHOLDS_MIN) so external scripts
    that read the same array — e.g. mower_tail.py — share a single
    threshold registry. `-1` in any slot means "no timer applies"
    (e.g. integrated Link Module) → leave that field unchanged
    (CFG.CMS may still populate it via a different path).
    """
    if len(counters) != 4:
        LOGGER.warning(
            "%s s2.51 CONSUMABLES: expected 4 counters, got %d — dropping",
            LOG_NOVEL_PROPERTY,
            len(counters),
        )
        return state

    thresholds = _s2p51.CONSUMABLE_THRESHOLDS_MIN
    blades = _consumable_pct_remaining(counters[0], thresholds[0])
    brush = _consumable_pct_remaining(counters[1], thresholds[1])
    maint = _consumable_pct_remaining(counters[2], thresholds[2])

    return dataclasses.replace(
        state,
        blades_life_pct=blades if blades is not None else state.blades_life_pct,
        cleaning_brush_life_pct=brush if brush is not None else state.cleaning_brush_life_pct,
        robot_maintenance_life_pct=maint if maint is not None else state.robot_maintenance_life_pct,
    )


def apply_property_to_state(
    state: MowerState, siid: int, piid: int, value: Any
) -> MowerState:
    """Return a new MowerState with the given property push applied.

    Returns the unchanged state if (siid, piid) is unknown OR if value
    can't be coerced to the field's expected type. Logs at WARNING in
    both cases (caller can override via the LOGGER override).

    Pure function — no side effects beyond logging. F1's three known
    fields (state, battery_level, charging_status) are handled here;
    F2..F7 extend the dispatch.
    """
    # Blob-shaped pushes have their own handler — dispatch before
    # consulting PROPERTY_MAPPING (which does not include blob keys).
    if (siid, piid) == (1, 1):
        return _apply_s1p1_heartbeat(state, value)
    if (siid, piid) == (1, 4):
        return _apply_s1p4_telemetry(state, value)
    if (siid, piid) == (1, 5):
        # s1.5 = hardware serial string. Fetched on demand via cloud RPC
        # — never pushed spontaneously since it never changes. Any non-
        # empty string value lands as-is; anything else is dropped.
        if isinstance(value, str) and value:
            return dataclasses.replace(state, hardware_serial=value)
        return state
    if (siid, piid) == (2, 51):
        return _apply_s2p51_settings(state, value)

    # Check for multi_field entry first (updates multiple fields from one push)
    entry = PROPERTY_MAPPING.get((siid, piid))
    if entry is not None and entry.multi_field is not None:
        updates = {}
        for field_name_mf, extract_fn in entry.multi_field:
            try:
                updates[field_name_mf] = extract_fn(value)
            except (TypeError, ValueError) as ex:
                LOGGER.debug("multi_field extract %s failed: %s", field_name_mf, ex)
        return dataclasses.replace(state, **updates)

    field_name = resolve_field((siid, piid), value)
    if field_name is None:
        # `handle_property_push` already logs and dedups unmapped slots
        # via the novel_registry. Don't re-log here every tick — that's
        # what produced the per-push spam pre-v1.0.0a4.
        return state

    if field_name == "state":
        # MowerState.state was removed (SM-14). The state machine
        # (coordinator.state_machine) now owns behavioural state via
        # handle_mqtt_property. Drop the legacy mutator; return state unchanged
        # so the apply chain continues for other fields.
        return state

    if field_name == "battery_level":
        try:
            return dataclasses.replace(state, battery_level=int(value))
        except (ValueError, TypeError):
            return state

    if field_name == "charging_status":
        try:
            return dataclasses.replace(state, charging_status=ChargingStatus(int(value)))
        except (ValueError, TypeError):
            LOGGER.warning(
                "%s s3.2 CHARGING_STATUS: value=%r outside enum — dropping",
                LOG_NOVEL_PROPERTY,
                value,
            )
            return state

    # Generic fallback — any PROPERTY_MAPPING entry whose field_name is a
    # plain MowerState field (int, bool, str, float) lands here.  The value is
    # assigned verbatim; the extract_value callable in the mapping entry, if
    # present, is applied first so the coordinator doesn't duplicate transform
    # logic that lives in the mapping table.
    entry_for_field = PROPERTY_MAPPING.get((siid, piid))
    if entry_for_field is not None and field_name is not None:
        coerced = entry_for_field.extract_value(value) if entry_for_field.extract_value else value
        try:
            return dataclasses.replace(state, **{field_name: coerced})
        except TypeError as ex:
            LOGGER.warning(
                "%s siid=%d piid=%d field=%r coerce failed: %s",
                LOG_NOVEL_PROPERTY, siid, piid, field_name, ex,
            )
            return state

    # Resolved to an unknown field name — should never happen given the
    # current PROPERTY_MAPPING table, but fail safe.
    LOGGER.warning(
        "%s siid=%d piid=%d resolved to unknown field=%r",
        LOG_NOVEL_PROPERTY,
        siid,
        piid,
        field_name,
    )
    return state


