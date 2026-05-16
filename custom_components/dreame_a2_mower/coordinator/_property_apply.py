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
from ..observability import FreshnessTracker, NovelObservationRegistry
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import session_summary as _session_summary
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
# in HA within seconds instead of waiting for the next 10-min poll.
#
# - (6, 2) FRAME_INFO: confirmed tripwire 2026-04-26 — fires on any
#   settings save even when none of the four frame elements change.
#   See docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md
#   §"settings-saved tripwire".
_SETTINGS_TRIPWIRE_SLOTS: frozenset[tuple[int, int]] = frozenset({(6, 2)})

# Notification reason codes — keyed off s2p2. The Dreame cloud uses
# these to dispatch APNS/FCM pushes to the user's phone; the integration
# mirrors them as HA events so local automations can react.
# Source: docs/research/g2408-protocol.md § "s2p2 — notification reason codes"
# (correlated against app notification history 2026-05-11).
S2P2_NOTIFICATION_MAP: dict[int, tuple[str, str]] = {
    0: ("hanging", "Hanging"),
    23: ("emergency_stop", "Emergency stop activated"),
    27: ("human_detected", "Human detected"),
    28: ("blades_worn", "Blades severely worn — replace soon"),
    30: ("maintenance_reminder", "Maintenance reminder active"),
    31: ("positioning_failed_stuck", "Positioning failed — waiting for help"),
    33: ("positioning_failed_transient", "Positioning failed (transient)"),
    43: ("battery_temp_low_charging_paused", "Battery temperature low — charging paused"),
    48: ("mowing_complete", "Mowing complete"),
    50: ("mowing_started", "Mowing started"),
    53: ("scheduled_mowing_started", "Scheduled mowing started"),
    54: ("low_battery_return", "Low battery — returning to dock"),
    56: ("rain_protection", "Rain protection — water on LiDAR"),
    63: ("schedule_cancelled_busy", "Scheduled task cancelled — Robot working"),
    70: ("continue_unfinished_task", "Robot will continue the unfinished task"),
    71: ("positioning_failure", "Positioning failure (auto-recovery or stuck)"),
    73: ("top_cover_open", "Top cover open"),
    75: ("arrived_at_maintenance_point", "Arrived at maintenance point"),
    78: ("robot_in_hidden_zone", "Robot in hidden zone"),
    117: ("station_disconnected", "Station disconnected"),
}

# Event type fired when s2p2 carries a value not in S2P2_NOTIFICATION_MAP —
# surfaces novel codes for future research without flooding the log.
S2P2_NOVEL_EVENT_TYPE = "novel_s2p2"


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


