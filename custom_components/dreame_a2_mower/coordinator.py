"""Coordinator for the Dreame A2 Mower integration.

Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
MowerState, and the dispatch from inbound MQTT pushes to state
updates. Entities subscribe to coordinator updates and read from
``coordinator.data`` (the MowerState).
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .archive.lidar import LidarArchive
from .archive.session import ArchivedSession, SessionArchive
from .wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from .cloud_client import DreameA2CloudClient
from .const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
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
from .inventory.loader import load_inventory
from .live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from .live_map.finalize import decide as _finalize_decide
from .live_map.state import LiveMapState
from .mower.actions import ACTION_TABLE, MowerAction
from .mower.property_mapping import PROPERTY_MAPPING, resolve_field
from .mower.state import ChargingStatus, MowerState
from .mower.state_machine import MowerStateMachine
from .mqtt_client import DreameA2MqttClient
from .observability import FreshnessTracker, NovelObservationRegistry
from .observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from .protocol import config_s2p51 as _s2p51
from .protocol import heartbeat as _heartbeat
from .protocol import session_summary as _session_summary
from .protocol import telemetry as _telemetry
from .protocol import wheel_bind as _wheel_bind

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
    27: ("human_detected", "Human detected"),
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


def _read_last_position_from_archive(archive) -> tuple[float, float] | None:
    """Read the last (x_m, y_m) point from the most recent finalized session.

    Returns None if no archive exists, no sessions on disk, or the most
    recent session has no `_local_legs` points.

    Used as a cold-start fallback for the position snapshot when no s1p4
    telemetry has fired since HA restart but a prior session was archived.
    """
    archive.load_index()
    sessions = list(archive.list_sessions())
    if not sessions:
        return None
    # list_sessions() returns newest-first. Skip in-progress synthetic entry.
    for entry in sessions:
        if getattr(entry, "still_running", False):
            continue
        blob_path = archive.root / entry.filename
        try:
            data = json.loads(blob_path.read_text())
        except (OSError, ValueError):
            continue
        legs = data.get("_local_legs") or []
        for leg in reversed(legs):
            if isinstance(leg, list) and leg:
                last = leg[-1]
                if isinstance(last, list) and len(last) >= 2:
                    try:
                        return float(last[0]), float(last[1])
                    except (TypeError, ValueError):
                        continue
        # else: no usable legs in this session, try the next one
    return None


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


class DreameA2MowerCoordinator(DataUpdateCoordinator[MowerState]):
    """Coordinates MQTT + cloud clients and the typed MowerState."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-based; we don't poll
        )
        self.entry = entry
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._country = entry.data[CONF_COUNTRY]

        # Initialize empty MowerState — fields fill in as MQTT pushes arrive
        self.data = MowerState()

        # Live session state machine (F5.3.1).
        self.live_map = LiveMapState()
        self._prev_task_state: int | None = None
        # Event-entity refs populated by event.py's async_setup_entry.
        # Coordinator's _fire_lifecycle dispatcher calls these to surface
        # transitions to HA. None until the platform setup completes;
        # _fire_lifecycle race-skips with a DEBUG log when not yet wired.
        self._lifecycle_event: Any = None
        self._alert_event: Any = None
        # Tracks the previous mower_in_dock value for rising/falling edge
        # detection of dock_arrived / dock_departed events. None at
        # startup; explicit `is True` / `is False` comparisons in
        # _on_state_update mean the first push doesn't fire spuriously.
        self._prev_in_dock: bool | None = None
        # Tracks the previous s2p2 / error_code value for notification-event
        # synthesis. Fires dreame_a2_mower_alert events on transitions to
        # known codes (S2P2_NOTIFICATION_MAP). None at startup so the first
        # push doesn't fire spuriously on HA boot.
        self._prev_error_code: int | None = None
        # Stores the most-recent fired notification for sensor.last_notification.
        # Shape: {"event_type": str, "text": str, "code": int, "fired_at": int}
        self._last_notification: dict | None = None

        # Session archive — persists completed sessions to disk (F5.4.1, F5.6.1).
        # <config>/dreame_a2_mower/sessions/ — matches legacy layout.
        sessions_dir = hass.config.path(DOMAIN, "sessions")
        self.session_archive = SessionArchive(Path(sessions_dir))
        # F7.7.1: apply retention from options (if set), else use default.
        opts = getattr(entry, "options", {}) or {}
        session_keep = int(
            opts.get(CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP)
        )
        if hasattr(self.session_archive, "set_retention"):
            self.session_archive.set_retention(session_keep)

        # F7.2.2: LiDAR archive — persists PCD scans announced via s99p20.
        # Layout: <config>/dreame_a2_mower/lidar/<map_id>/  (per-map subdirs).
        # F7.7.1: retention and max_bytes read from entry.options at startup.
        # T12: per-map archive dict; lazy-init via lidar_archive_for(map_id).
        lidar_dir = hass.config.path(DOMAIN, "lidar")
        self._lidar_archive_root: Path = Path(lidar_dir)
        self._lidar_archive_root.mkdir(parents=True, exist_ok=True)
        self._lidar_archive_retention: int = int(
            opts.get(CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP)
        )
        self._lidar_archive_max_bytes: int = (
            int(opts.get(CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB))
            * 1024 * 1024
        )
        # dict[int, LidarArchive] — populated lazily by lidar_archive_for().
        self.lidar_archives: dict[int, LidarArchive] = {}
        self._last_lidar_object_name: str | None = None

        # WiFi archive — persists heatmap objects fetched from OSS.
        # Layout: <config>/dreame_a2_mower/wifi_archive/
        # Store is created here; index loaded from disk at startup.
        wifi_archive_dir = Path(hass.config.path(DOMAIN, "wifi_archive"))
        self._wifi_archive_store: WifiArchiveStore = WifiArchiveStore(wifi_archive_dir)
        self._wifi_archive_index: list[WifiArchiveEntry] = self._wifi_archive_store.load_index()

        # Unified cloud state — populated by _refresh_cloud_state every 10 min.
        # All cloud-fetched data (maps, settings, schedule, mow paths, etc.)
        # lives here. Properties below maintain backwards-compat for entities
        # that were written against the previous _cached_* attributes.
        self.cloud_state: Any = None  # CloudState | None — actual import deferred

        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        # Four independent PNG cache slots, one per render pipeline:
        #   _main_view_png         — active map + live trail (Main view)
        #   _static_map_pngs_by_id — per-map static base + M_PATH (cumulative)
        #   _work_log_png          — picker-selected archived session
        #   _active_map_base_png   — active map base only (no trail, no M_PATH);
        #                            shown as the Work Log camera's empty state
        # Each slot is owned by one render path; no shared mutability.
        self._main_view_png: bytes | None = None
        self._work_log_png: bytes | None = None
        self._active_map_base_png: bytes | None = None
        # Tracks the active map's md5 the last time we rendered
        # _active_map_base_png — used by _render_active_map_base to dedup.
        self._active_map_base_md5: str | None = None
        # Single coordinator-wide mutex serializing all chunked-batch
        # cloud writes (SETTINGS / SCHEDULE / AI_HUMAN). Each per-domain
        # helper acquires this around the read-modify-write sequence so
        # two near-simultaneous entity writes can't race on the same blob.
        # Hold time per write is sub-second; cross-blob writes are rare
        # so a single mutex (vs per-blob) keeps reasoning simple.
        self._chunked_write_lock: asyncio.Lock = asyncio.Lock()
        # Debounce timer for tripwire-driven cloud refreshes.
        # When the firmware pushes a "settings-saved" MQTT slot
        # (see _SETTINGS_TRIPWIRE_SLOTS), we schedule a deferred
        # _refresh_cloud_state. Bursts coalesce: each fresh tripwire
        # cancels any pending fire and pushes the deadline back, so
        # one final refresh runs after the burst settles.
        self._cloud_refresh_debounce_handle: asyncio.TimerHandle | None = None
        self._static_map_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
        # Active map (from MAPL polling). None until first MAPL response.
        self._active_map_id: int | None = None
        # Cross-map LiDAR archive selection — drives DreameA2LidarSelectedCamera.
        # Tuple of (map_id, filename) — None means "show latest scan from active map".
        self._lidar_render_entry: tuple[int, str] | None = None
        # WiFi archive selection — drives DreameA2WifiSelectedCamera.
        # Tuple of (map_id, object_name) — None means "latest from active map".
        self._wifi_render_entry: tuple[int, str] | None = None
        # Last archive refresh result — updated by refresh_wifi_archive.
        self._wifi_archive_last_refresh: dict = {}
        # Throttle live re-renders to at most one per N seconds; the
        # mower pushes s1.4 every ~5s during a mow which would otherwise
        # cause one PIL render per push. Burst-coalesce via a dirty flag.
        self._live_trail_dirty: bool = False
        self._last_live_render_unix: float = 0.0

        # Dirty flag for in-progress persistence (F5.7.1).
        # Set by _on_state_update after every append_point; cleared by
        # _persist_in_progress after a successful disk write.
        self._live_map_dirty: bool = False

        # Novel-observation registry (F6.2.1).
        # Tracks first-sightings of unknown protocol tokens so the watchdog
        # WARNING fires only once per token per process lifetime.
        self.novel_registry = NovelObservationRegistry()
        # Per-field freshness tracker (F6.6.1).
        # Records the last unix timestamp each MowerState field changed.
        self.freshness = FreshnessTracker()

        # Multi-dimensional state machine — canonical source of behavioural
        # state (activity, location, session). Entities read from
        # state_machine.snapshot().
        self.state_machine = MowerStateMachine()
        self._state_store: Store | None = None  # initialised in _async_update_data
        # Map cache persistence — stores the raw fetch_map dict (JSON-able)
        # so map metadata sensors populate immediately on reload instead of
        # waiting for the first cloud roundtrip. Initialised in
        # _async_update_data alongside _state_store.
        self._maps_cache_store: Store | None = None

    @property
    def sn(self) -> str | None:
        """Hardware serial number — preferred over `entry_id` for stable HA identifiers.

        Two sources, in priority order:
          1. `_cloud.serial_number` — set by `_handle_device_info` if the
             cloud's device-info response carried `sn`. Reliable when the
             device-info call returns the field, which `get_devices()`
             frequently does NOT.
          2. `data.hardware_serial` — set by `_refresh_dev()` from the
             routed-action s2.50 `{m:'g', t:'DEV'}` payload, which
             *always* carries `sn` on g2408. This runs synchronously
             during `async_config_entry_first_refresh`, so it's
             reliably populated by the time the migration retry checks.
        """
        client = self._cloud if hasattr(self, "_cloud") else None
        from_cloud = getattr(client, "serial_number", None) if client is not None else None
        if from_cloud:
            return from_cloud
        data = getattr(self, "data", None)
        return getattr(data, "hardware_serial", None) if data is not None else None

    async def _async_update_data(self) -> MowerState:
        """First-refresh path — auth, device discovery, MQTT subscribe.

        Subsequent refreshes are push-driven via the MQTT callback;
        this method only re-runs if the user manually refreshes the
        integration.
        """
        if not hasattr(self, "_cloud"):
            # Restore the state machine from disk before any new signals arrive.
            if self._state_store is None:
                self._state_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_state_{self.entry.entry_id}",
                )
            try:
                await self.state_machine.load_persisted(self._state_store)
            except Exception:
                LOGGER.exception(
                    "state_machine.load_persisted failed; continuing with initial snapshot"
                )

            self._cloud = await self.hass.async_add_executor_job(
                self._init_cloud
            )

            # Restore any in-progress session BEFORE _init_mqtt subscribes
            # to the mower's status topic. If we restored after MQTT, the
            # broker's retained s2p56 message could land between any of the
            # subsequent `await`s, fire begin_session(now_unix), and clobber
            # the disk-persisted legs with the current restart timestamp.
            # See coordinator.py:_restore_in_progress for the full race
            # narrative; pairing this with the `not live_map.is_active()`
            # guard in _on_state_update is the trail-loss-on-restart fix.
            await self._restore_in_progress()

            await self.hass.async_add_executor_job(self._init_mqtt)

            # Periodic cloud-state refresh. The MQTT-driven s6p2 tripwire
            # (see _SETTINGS_TRIPWIRE_SLOTS) catches most app-side saves
            # within ~5 s, but some BT-only settings (obstacleAvoidanceHeight,
            # mowing direction, edge mowing toggles, AI bits) don't push
            # any MQTT signal. The periodic poll is the fallback for those.
            # 2 min gives a tight worst-case latency without hammering the
            # cloud — a full refresh costs ~6 RPCs, so 3 RPC/min average.
            async def _periodic_cloud_state(_now: Any) -> None:
                await self._refresh_cloud_state()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cloud_state, timedelta(minutes=2)
                )
            )
            await self._refresh_cloud_state()

            # Schedule CFG refresh every 10 minutes; also fire one immediately
            # so blade-life / side-brush-life are populated at startup.
            async def _periodic_cfg(_now: Any) -> None:
                await self._refresh_cfg()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cfg, timedelta(minutes=10)
                )
            )
            await self._refresh_cfg()

            # Schedule LOCN refresh every 60 seconds; also fire one immediately
            # so GPS position is populated at startup.
            async def _periodic_locn(_now: Any) -> None:
                await self._refresh_locn()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_locn, timedelta(seconds=60)
                )
            )
            await self._refresh_locn()

            # Schedule DEV refresh every 6 hours; also fire one immediately
            # so the hardware serial / firmware version land at startup
            # (the s1p5 fallback path mostly returns 80001).
            async def _periodic_dev(_now: Any) -> None:
                await self._refresh_dev()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dev, timedelta(hours=6)
                )
            )
            await self._refresh_dev()

            # Schedule NET refresh every hour; also fire one immediately
            # so wifi_ssid / wifi_ip / wifi_rssi_dbm have values at boot
            # (otherwise the RSSI sensor sits Unknown for ~45 s waiting
            # for the first s1p1 heartbeat).
            async def _periodic_net(_now: Any) -> None:
                await self._refresh_net()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_net, timedelta(hours=1)
                )
            )
            await self._refresh_net()

            # Schedule DOCK refresh every 60s; mower-in-dock is the
            # most useful field and benefits from quicker updates so
            # automations can trigger on dock arrival/departure.
            async def _periodic_dock(_now: Any) -> None:
                await self._refresh_dock()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dock, timedelta(seconds=60)
                )
            )
            await self._refresh_dock()

            # Schedule MIHIS refresh every 10 min; also fire one
            # immediately so the lifetime-totals sensors switch from
            # the local-archive seed to the cloud-authoritative numbers
            # right after HA reload.
            async def _periodic_mihis(_now: Any) -> None:
                await self._refresh_mihis()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_mihis, timedelta(minutes=10)
                )
            )
            await self._refresh_mihis()

            # Schedule MAP refresh every 6 hours; also fire one immediately
            # so the camera entity has a PNG at startup.
            async def _periodic_map(_now: Any) -> None:
                await self._refresh_map()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_map, timedelta(hours=6)
                )
            )
            # Restore the parsed map cache from disk before the first cloud
            # fetch so map-metadata sensors populate immediately on reload.
            # The subsequent _refresh_map will overwrite with fresh data
            # once the cloud responds.
            if self._maps_cache_store is None:
                self._maps_cache_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_maps_{self.entry.entry_id}",
                )
            try:
                await self._load_persisted_maps()
            except Exception:
                LOGGER.exception(
                    "_load_persisted_maps failed; continuing with empty cache"
                )
            await self._refresh_map()

            # Seed the WiFi archive picker cache so select.wifi_archive has
            # options immediately (before the user presses any refresh button).
            # Best-effort: failures are non-fatal; the picker stays empty and
            # the user can trigger a refresh manually.
            try:
                await self.refresh_wifi_archive()
            except Exception as _ex:
                LOGGER.debug("Initial WiFi archive fetch failed: %s", _ex)

            # Schedule session-finalize retry every RETRY_INTERVAL_SECONDS (60s).
            # Consults finalize.decide() each tick; dispatches AWAIT_OSS_FETCH /
            # FINALIZE_INCOMPLETE / NOOP as appropriate.
            async def _periodic_session(_now: Any) -> None:
                await self._periodic_session_retry()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _periodic_session,
                    timedelta(seconds=RETRY_INTERVAL_SECONDS),
                )
            )

            # v1.0.0a43: hourly cloud-property poll for slow-changing slots
            # the mower never (or rarely) pushes spontaneously. Today this
            # only targets s6.3 (cloud_connected + wifi_rssi_dbm) so the
            # signal-strength sensor doesn't sit Unknown forever between
            # the mower's sparse pushes. Fails silently on 80001 (the
            # standard g2408 cloud-RPC rejection) — no log spam.
            async def _periodic_slow_poll(_now: Any) -> None:
                await self._poll_slow_properties()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_slow_poll, timedelta(hours=1)
                )
            )
            await self._poll_slow_properties()

            # Load session archive index from disk (non-blocking via executor).
            await self.hass.async_add_executor_job(self.session_archive.load_index)
            archived_count = self.session_archive.count
            if archived_count:
                # v1.0.0a22 / a23: seed total_lawn_area_m2 from the most
                # recent archived session's map_area_m2 so the user sees
                # a value at boot (s2.66 pushes rarely on g2408). Run
                # list_sessions through the executor — it touches
                # in_progress.json synchronously and would otherwise trip
                # HA's blocking-I/O detector and silently raise. (a22
                # called it from the event loop and the seed never fired.)
                seed_lawn = None
                seed_latest_md5: str | None = None
                seed_latest_unix: int | None = None
                seed_latest_area: float | None = None
                seed_latest_duration: int | None = None
                # v1.0.0a42: seed first_mowing_date from the local
                # archive at boot. mowing_count / total_mowing_time_min
                # / total_mowed_area_m2 are now provided by MIHIS via
                # _apply_cloud_state_to_mower_state (Task 17); the
                # lifetime accumulators for those three were dropped.
                # first_mowing_date has no MIHIS equivalent so it
                # remains archive-sourced here.
                #   - first_mowing_date (unix ts)
                first_ts: int | None = None
                try:
                    sessions = await self.hass.async_add_executor_job(
                        self.session_archive.list_sessions
                    )
                    for s in sorted(sessions, key=lambda x: x.end_ts, reverse=True):
                        if seed_lawn is None and getattr(s, "map_area_m2", 0):
                            seed_lawn = float(s.map_area_m2)
                        # Pick the most-recent NON in-progress entry to seed
                        # Latest session area / duration / time. Without this
                        # seed those entities go Unknown after every HA
                        # reload until the next session finalizes.
                        if (
                            seed_latest_md5 is None
                            and not getattr(s, "still_running", False)
                            and getattr(s, "md5", "")
                        ):
                            seed_latest_md5 = str(s.md5)
                            seed_latest_unix = int(s.end_ts)
                            seed_latest_area = float(s.area_mowed_m2 or 0.0)
                            seed_latest_duration = int(s.duration_min or 0)
                        # Track first non-in-progress session start for
                        # first_mowing_date (no cloud equivalent — keep
                        # local-archive sourcing). MIHIS now provides
                        # mowing_count / total_mowing_time_min /
                        # total_mowed_area_m2 via _apply_cloud_state_to_mower_state
                        # at startup, so the lifetime accumulators were
                        # dropped in Task 17.
                        if not getattr(s, "still_running", False):
                            start_ts = int(getattr(s, "start_ts", 0) or 0)
                            if start_ts > 0 and (first_ts is None or start_ts < first_ts):
                                first_ts = start_ts
                except Exception as _ex:
                    LOGGER.warning(
                        "Could not seed session-summary fields from archive: %s", _ex
                    )
                seed_updates: dict[str, Any] = {
                    "archived_session_count": archived_count,
                }
                if seed_lawn is not None:
                    seed_updates["total_lawn_area_m2"] = seed_lawn
                if seed_latest_md5 is not None:
                    # `seed_latest_md5` is used purely as a "we found a
                    # finalized session" sentinel; the md5 itself is no
                    # longer surfaced (latest_session_md5 was pruned in
                    # F10 — see docs/research/state-machines/orphan-fields.md).
                    seed_updates["latest_session_unix_ts"] = seed_latest_unix
                    seed_updates["latest_session_area_m2"] = seed_latest_area
                    seed_updates["latest_session_duration_min"] = seed_latest_duration
                if first_ts is not None and self.data.first_mowing_date is None:
                    # Field is typed `str | None` and surfaced as a sensor
                    # value. Format as a local-tz YYYY-MM-DD so users see a
                    # date rather than a raw unix timestamp.
                    from datetime import datetime
                    try:
                        seed_updates["first_mowing_date"] = (
                            datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
                        )
                    except (OSError, OverflowError, ValueError):
                        pass
                self.data = dataclasses.replace(self.data, **seed_updates)

                # SM-seed (position-fix #1): if the snapshot has no position
                # yet (cold-start with no s1p4 since restart), pull the last
                # known position from the most recent finalized session
                # archive so the position entities don't sit Unknown
                # indefinitely while the mower is idle.
                snap = self.state_machine.snapshot()
                if snap.position_x_m is None:
                    seed = await self.hass.async_add_executor_job(
                        _read_last_position_from_archive, self.session_archive,
                    )
                    if seed is not None:
                        import time as _time
                        x_m, y_m = seed
                        self.state_machine.handle_position(
                            x_m=x_m,
                            y_m=y_m,
                            north_m=None,
                            east_m=None,
                            now_unix=int(_time.time()),
                        )
                        LOGGER.info(
                            "Seeded snapshot.position from session_archive: "
                            "(%.3f, %.3f)",
                            x_m,
                            y_m,
                        )

            # F7.2.2: same pattern for the LiDAR archive.
            # Load index for all existing per-map subdirs so the count
            # sensor populates on first refresh.
            # iterdir() does blocking scandir under the hood — must run in
            # an executor or HA logs a "blocking call inside event loop"
            # warning at every startup.
            def _list_lidar_subdirs() -> list[tuple[int, "Path"]]:
                out: list[tuple[int, "Path"]] = []
                for sub in self._lidar_archive_root.iterdir():
                    if sub.is_dir() and sub.name.isdigit():
                        try:
                            out.append((int(sub.name), sub))
                        except ValueError:
                            pass
                return out
            _lidar_count = 0
            try:
                _subdirs = await self.hass.async_add_executor_job(
                    _list_lidar_subdirs
                )
            except (OSError, FileNotFoundError):
                _subdirs = []
            for _map_id, _sub in _subdirs:
                try:
                    _arch = self.lidar_archive_for(_map_id)
                    await self.hass.async_add_executor_job(_arch.load_index)
                    _lidar_count += _arch.count
                except Exception as _ex:
                    LOGGER.debug(
                        "[LIDAR] startup index load failed for %s: %s", _sub, _ex
                    )
            if _lidar_count:
                self.data = dataclasses.replace(
                    self.data, archived_lidar_count=_lidar_count
                )

            # _restore_in_progress already ran above (before _init_mqtt).

            # Schedule 30-second debounced persist of the in-progress trail.
            # Only writes when live_map is active AND dirty (new point appended).
            async def _periodic_persist(_now: Any) -> None:
                await self._persist_in_progress(_now)

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _periodic_persist,
                    timedelta(seconds=30),
                )
            )

            # Schedule state-machine tick every 10 seconds. Handles HB
            # staleness checks, s2p2=71 disambiguation, and debounced persist.
            @callback
            def _state_machine_tick(_now: Any) -> None:
                import time as _time
                now_unix = int(_time.time())
                try:
                    self.state_machine.tick(now_unix=now_unix)
                except Exception:
                    LOGGER.exception("state_machine.tick failed")
                # Cold-boot telemetry reconciliation. MQTT properties_changed
                # only fires on change, so a mid-session integration restart
                # never receives the start events. Use continuous telemetry
                # (area_mowed + position) to infer the right state.
                try:
                    data = self.data
                    self.state_machine.reconcile_from_telemetry(
                        live_map_active=self.live_map.is_active(),
                        area_mowed_m2=getattr(data, "area_mowed_m2", None),
                        position_x_m=getattr(data, "position_x_m", None),
                        position_y_m=getattr(data, "position_y_m", None),
                        dock_x_mm=getattr(data, "dock_x_mm", None),
                        dock_y_mm=getattr(data, "dock_y_mm", None),
                        now_unix=now_unix,
                    )
                except Exception:
                    LOGGER.exception("state_machine.reconcile_from_telemetry failed")
                # Sync snapshot.charging back to coord.data.charging_status
                # so the charging_status sensor reflects the state machine's
                # inferred state (e.g. battery-rise → charging=True after a
                # reload that missed the explicit s3p2 push).
                try:
                    from .mower.state import ChargingStatus
                    snap_charging = self.state_machine.snapshot().charging
                    inferred = (
                        ChargingStatus.CHARGING if snap_charging
                        else ChargingStatus.NOT_CHARGING
                    )
                    if self.data.charging_status != inferred:
                        self.async_set_updated_data(
                            dataclasses.replace(
                                self.data, charging_status=inferred,
                            )
                        )
                except Exception:
                    LOGGER.exception("charging_status sync failed")
                # Debounced save: only write if dirty and store is ready.
                if self.state_machine.is_dirty() and self._state_store is not None:
                    self.hass.async_create_task(
                        self.state_machine.save_persisted(self._state_store)
                    )

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _state_machine_tick,
                    timedelta(seconds=10),
                )
            )

        return self.data

    def _apply_mapl(self, mapl: Any) -> None:
        """Update _active_map_id from a MAPL response.

        MAPL is a list of rows, each row is `[map_id, is_active, ?, ?, ?]`.
        Sets `_active_map_id` to the row whose col 1 == 1. If no row
        matches (transient), keep the previous value. Bad payloads are
        ignored.

        When `_active_map_id` actually changes, fires `async_update_listeners`
        so camera + select entities push their new state to the frontend
        without waiting for the next full coordinator broadcast.
        """
        if not isinstance(mapl, list):
            return
        prev_active = self._active_map_id
        for row in mapl:
            if not isinstance(row, list) or len(row) < 2:
                continue
            try:
                if int(row[1]) == 1:
                    new_active = int(row[0])
                    if new_active != prev_active:
                        self._active_map_id = new_active
                        # Re-apply cloud_state → MowerState so SETTINGS-keyed
                        # fields (settings_mowing_height, settings_edge_mowing_*,
                        # settings_obstacle_avoidance_*, settings_obstacle_avoidance_ai)
                        # populate now that we know which map is active. On cold
                        # start _refresh_cloud_state runs first and sees
                        # _active_map_id=None, so without this re-apply the
                        # SETTINGS-driven entities stay unavailable until the
                        # next 10-min refresh.
                        if getattr(self, "cloud_state", None) is not None:
                            self._apply_cloud_state_to_mower_state()
                        # Fire listeners so camera + select push state to the
                        # frontend without waiting for the next coordinator
                        # broadcast.
                        update_listeners = getattr(self, "async_update_listeners", None)
                        if callable(update_listeners):
                            update_listeners()
                    self._sync_map_subdevices()
                    return
            except (TypeError, ValueError):
                continue
        # No row matched; keep previous _active_map_id (do nothing).
        self._sync_map_subdevices()

    async def _refresh_mapl(self) -> None:
        """Re-poll MAPL only (no full CFG refresh)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_mapl raised: %s", ex)
            return
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
        elif isinstance(mapl_resp, list):
            # fetch_mapl can return a bare list per Task 7 implementation.
            self._apply_mapl(mapl_resp)

    async def _refresh_cfg(self) -> None:
        """Fetch CFG via routed-action and update MowerState.

        Extracts blade / side-brush wear percentages from CFG.CMS plus all
        other settings fields added in F4.1.1: child lock, volume, language,
        DND, PRE (mowing prefs), WRP (rain protection), LOW (low-speed night),
        BAT (charging config), LIT (LED/headlight config), ATA (anti-theft),
        REC (human presence alert).

        The g2408 CFG dict does not contain cleaning-history keys
        (TC / TT / CN / FCD are not present in the confirmed 24-key
        schema — see docs/research/g2408-protocol.md §6.2 alpha.85 dump).
        Those MowerState fields remain None until a source is identified.

        All blocking I/O runs in the executor per spec §3.
        """
        if not hasattr(self, "_cloud"):
            return

        cfg = await self.hass.async_add_executor_job(self._cloud.fetch_cfg)
        if cfg is None:
            return

        # ---- CMS: per-consumable wear ----
        # Same shape as the s2p51 CONSUMABLES push:
        # [blades_min, cleaning_brush_min, robot_maintenance_min, link_module]
        # Thresholds + slot identity come from protocol/config_s2p51.py so
        # there's a single source of truth between this CFG path and the
        # live CONSUMABLES path. `-1` in any slot means "no timer applies".
        blades_life_pct: float | None = None
        cleaning_brush_life_pct: float | None = None
        robot_maintenance_life_pct: float | None = None
        cms = cfg.get("CMS")
        if isinstance(cms, list) and len(cms) >= 3:
            try:
                blades_life_pct = _consumable_pct_remaining(
                    int(cms[0]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[0]
                )
                cleaning_brush_life_pct = _consumable_pct_remaining(
                    int(cms[1]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[1]
                )
                robot_maintenance_life_pct = _consumable_pct_remaining(
                    int(cms[2]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[2]
                )
            except (TypeError, ValueError, ZeroDivisionError) as ex:
                LOGGER.warning("[CFG] CMS decode error: %s — cms=%r", ex, cms)

        # ---- CLS: child lock ----
        # CFG.CLS = int {0, 1}. Confirmed on g2408 (docs/research §6.2).
        child_lock_enabled: bool | None = None
        cls_raw = cfg.get("CLS")
        if cls_raw is not None:
            try:
                child_lock_enabled = bool(int(cls_raw))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] CLS decode error: %s — cls=%r", ex, cls_raw)

        # ---- VOL: voice volume ----
        # CFG.VOL = int 0..100. Confirmed on g2408.
        volume_pct: int | None = None
        vol_raw = cfg.get("VOL")
        if vol_raw is not None:
            try:
                volume_pct = int(vol_raw)
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] VOL decode error: %s — vol=%r", ex, vol_raw)

        # ---- LANG: language indices ----
        # CFG.LANG = list(2) [text_idx, voice_idx]. Confirmed on g2408.
        # language_code stores a human-readable key like "text=2,voice=7";
        # language_text_idx / language_voice_idx carry the raw indices.
        language_code: str | None = None
        language_text_idx: int | None = None
        language_voice_idx: int | None = None
        lang_raw = cfg.get("LANG")
        if isinstance(lang_raw, list) and len(lang_raw) >= 2:
            try:
                language_text_idx = int(lang_raw[0])
                language_voice_idx = int(lang_raw[1])
                language_code = f"text={language_text_idx},voice={language_voice_idx}"
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LANG decode error: %s — lang=%r", ex, lang_raw)

        # ---- DND: do-not-disturb ----
        # CFG.DND = list(3) [enabled, start_min, end_min] where start_min and
        # end_min are integer minutes-from-midnight (confirmed via iobroker
        # cross-ref: [0, 1200, 480] = off, 20:00→08:00).
        dnd_enabled: bool | None = None
        dnd_start_min: int | None = None
        dnd_end_min: int | None = None
        dnd_raw = cfg.get("DND")
        if isinstance(dnd_raw, list) and len(dnd_raw) >= 3:
            try:
                dnd_enabled = bool(int(dnd_raw[0]))
                dnd_start_min = int(dnd_raw[1])
                dnd_end_min = int(dnd_raw[2])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] DND decode error: %s — dnd=%r", ex, dnd_raw)

        # ---- PRE: mowing preferences ----
        # On g2408 PRE is list(2) [zone_id, mode] — NOT the full 10-element APK
        # schema (docs/research §6.2 §PRE-schema). Elements 2..9 do not exist on
        # this firmware version; pre_mowing_height_mm and pre_edgemaster come from
        # s6.2 push events instead.
        pre_zone_id: int | None = None
        pre_mowing_efficiency: int | None = None
        pre_mowing_height_mm: int | None = None  # only set if PRE has >=3 elements
        pre_edgemaster: bool | None = None  # only set if PRE has >=9 elements
        pre_raw = cfg.get("PRE")
        if isinstance(pre_raw, list):
            try:
                if len(pre_raw) >= 1:
                    pre_zone_id = int(pre_raw[0])
                if len(pre_raw) >= 2:
                    pre_mowing_efficiency = int(pre_raw[1])
                if len(pre_raw) >= 3:
                    pre_mowing_height_mm = int(pre_raw[2])
                if len(pre_raw) >= 9:
                    pre_edgemaster = bool(pre_raw[8])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] PRE decode error: %s — pre=%r", ex, pre_raw)

        # ---- WRP: rain protection ----
        # CFG.WRP = list(2) [enabled, resume_hours]. Confirmed on g2408 (isolated
        # toggle 2026-04-24). resume_hours=0 → "Don't Mow After Rain" (no auto-resume).
        rain_protection_enabled: bool | None = None
        rain_protection_resume_hours: int | None = None
        wrp_raw = cfg.get("WRP")
        if isinstance(wrp_raw, list) and len(wrp_raw) >= 2:
            try:
                rain_protection_enabled = bool(int(wrp_raw[0]))
                rain_protection_resume_hours = int(wrp_raw[1])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] WRP decode error: %s — wrp=%r", ex, wrp_raw)

        # ---- LOW: low-speed nighttime mode ----
        # CFG.LOW = list(3) [enabled, start_min, end_min]. Confirmed on g2408
        # (live toggle 2026-04-24). Same shape as DND. Example: [1, 1200, 480].
        low_speed_at_night_enabled: bool | None = None
        low_speed_at_night_start_min: int | None = None
        low_speed_at_night_end_min: int | None = None
        low_raw = cfg.get("LOW")
        if isinstance(low_raw, list) and len(low_raw) >= 3:
            try:
                low_speed_at_night_enabled = bool(int(low_raw[0]))
                low_speed_at_night_start_min = int(low_raw[1])
                low_speed_at_night_end_min = int(low_raw[2])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LOW decode error: %s — low=%r", ex, low_raw)

        # ---- BAT: charging config ----
        # CFG.BAT = list(6) [recharge_pct, resume_pct, unknown_flag,
        #                     custom_charging, start_min, end_min].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51 CHARGING decoder.
        auto_recharge_battery_pct: int | None = None
        resume_battery_pct: int | None = None
        custom_charging_enabled: bool | None = None
        charging_start_min: int | None = None
        charging_end_min: int | None = None
        bat_raw = cfg.get("BAT")
        if isinstance(bat_raw, list) and len(bat_raw) >= 6:
            try:
                auto_recharge_battery_pct = int(bat_raw[0])
                resume_battery_pct = int(bat_raw[1])
                # bat_raw[2] = unknown_flag (consistently 1; semantic TBD)
                custom_charging_enabled = bool(int(bat_raw[3]))
                charging_start_min = int(bat_raw[4])
                charging_end_min = int(bat_raw[5])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] BAT decode error: %s — bat=%r", ex, bat_raw)

        # ---- LIT: headlight / LED config ----
        # CFG.LIT = list(8) [enabled, start_min, end_min, standby, working,
        #                     charging, error, unknown].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51 LED_PERIOD decoder.
        led_period_enabled: bool | None = None
        led_in_standby: bool | None = None
        led_in_working: bool | None = None
        led_in_charging: bool | None = None
        led_in_error: bool | None = None
        lit_raw = cfg.get("LIT")
        if isinstance(lit_raw, list) and len(lit_raw) >= 7:
            try:
                led_period_enabled = bool(int(lit_raw[0]))
                # lit_raw[1] = start_min (charging-schedule; not in MowerState F4)
                # lit_raw[2] = end_min   (charging-schedule; not in MowerState F4)
                led_in_standby = bool(int(lit_raw[3]))
                led_in_working = bool(int(lit_raw[4]))
                led_in_charging = bool(int(lit_raw[5]))
                led_in_error = bool(int(lit_raw[6]))
                # lit_raw[7] = unknown trailing toggle (not yet characterised)
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LIT decode error: %s — lit=%r", ex, lit_raw)

        # ---- ATA: anti-theft alarm ----
        # CFG.ATA = list(3) [lift_alarm, offmap_alarm, realtime_location].
        # Confirmed on g2408 (all 3 indices individually verified 2026-04-27).
        anti_theft_lift_alarm: bool | None = None
        anti_theft_offmap_alarm: bool | None = None
        anti_theft_realtime_location: bool | None = None
        ata_raw = cfg.get("ATA")
        if isinstance(ata_raw, list) and len(ata_raw) >= 3:
            try:
                anti_theft_lift_alarm = bool(int(ata_raw[0]))
                anti_theft_offmap_alarm = bool(int(ata_raw[1]))
                anti_theft_realtime_location = bool(int(ata_raw[2]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] ATA decode error: %s — ata=%r", ex, ata_raw)

        # ---- REC: human presence alert ----
        # CFG.REC = list(9) [enabled, sensitivity, standby, mowing, recharge,
        #                     patrol, alert, photo_consent, push_min].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51
        # HUMAN_PRESENCE_ALERT decoder.
        # REC[7] is `photo_consent` — privacy-policy acceptance for the
        # "Capture Photos of AI-Detected Obstacles" feature (CFG.AOP).
        # See MowerState.photo_consent docstring + binary_sensor.photo_consent.
        human_presence_alert_enabled: bool | None = None
        human_presence_alert_sensitivity: int | None = None
        photo_consent: bool | None = None
        rec_raw = cfg.get("REC")
        if isinstance(rec_raw, list) and len(rec_raw) >= 2:
            try:
                human_presence_alert_enabled = bool(int(rec_raw[0]))
                human_presence_alert_sensitivity = int(rec_raw[1])
                if len(rec_raw) >= 8:
                    photo_consent = bool(int(rec_raw[7]))
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

        frost_protection_enabled = _cfg_bool("FDP")
        auto_recharge_standby_enabled = _cfg_bool("STUN")
        ai_obstacle_photos_enabled = _cfg_bool("AOP")
        # CFG.PROT mapping: {0: direct, 1: smart}. We store True iff smart.
        navigation_path_smart = _cfg_bool("PROT")

        # ---- MSG_ALERT (Notification Preferences, 4-bool list) ----
        # Slots: [anomaly, error, task, consumables_messages].
        msg_alert_anomaly: bool | None = None
        msg_alert_error: bool | None = None
        msg_alert_task: bool | None = None
        msg_alert_consumables: bool | None = None
        msg_alert_raw = cfg.get("MSG_ALERT")
        if isinstance(msg_alert_raw, list) and len(msg_alert_raw) >= 4:
            try:
                msg_alert_anomaly = bool(int(msg_alert_raw[0]))
                msg_alert_error = bool(int(msg_alert_raw[1]))
                msg_alert_task = bool(int(msg_alert_raw[2]))
                msg_alert_consumables = bool(int(msg_alert_raw[3]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] MSG_ALERT decode error: %s — raw=%r", ex, msg_alert_raw)

        # ---- VOICE (Voice Prompt Modes, 4-bool list) ----
        # Slots: [regular_notification, work_status, special_status, error_status].
        voice_regular_notification: bool | None = None
        voice_work_status: bool | None = None
        voice_special_status: bool | None = None
        voice_error_status: bool | None = None
        voice_raw = cfg.get("VOICE")
        if isinstance(voice_raw, list) and len(voice_raw) >= 4:
            try:
                voice_regular_notification = bool(int(voice_raw[0]))
                voice_work_status = bool(int(voice_raw[1]))
                voice_special_status = bool(int(voice_raw[2]))
                voice_error_status = bool(int(voice_raw[3]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] VOICE decode error: %s — raw=%r", ex, voice_raw)

        new_state = dataclasses.replace(
            self.data,
            # CMS — wear percentages
            blades_life_pct=blades_life_pct,
            cleaning_brush_life_pct=cleaning_brush_life_pct,
            robot_maintenance_life_pct=robot_maintenance_life_pct,
            # total_mowing_time_min, total_mowed_area_m2, mowing_count,
            # first_mowing_date: not present in g2408 CFG (24-key schema).
            # Leave unchanged (None) until a source is identified.
            # CLS — child lock
            child_lock_enabled=child_lock_enabled,
            # VOL — voice volume
            volume_pct=volume_pct,
            # LANG — language indices
            language_code=language_code,
            language_text_idx=language_text_idx,
            language_voice_idx=language_voice_idx,
            # DND — do-not-disturb (integer minutes-from-midnight on wire)
            dnd_enabled=dnd_enabled,
            dnd_start_min=dnd_start_min,
            dnd_end_min=dnd_end_min,
            # PRE — mowing preferences (g2408: only [0]=zone_id, [1]=mode;
            #        height + edgemaster come from s6.2 push instead)
            pre_zone_id=pre_zone_id,
            pre_mowing_efficiency=pre_mowing_efficiency,
            pre_mowing_height_mm=pre_mowing_height_mm,
            pre_edgemaster=pre_edgemaster,
            # WRP — rain protection
            rain_protection_enabled=rain_protection_enabled,
            rain_protection_resume_hours=rain_protection_resume_hours,
            # LOW — low-speed nighttime
            low_speed_at_night_enabled=low_speed_at_night_enabled,
            low_speed_at_night_start_min=low_speed_at_night_start_min,
            low_speed_at_night_end_min=low_speed_at_night_end_min,
            # BAT — charging config
            auto_recharge_battery_pct=auto_recharge_battery_pct,
            resume_battery_pct=resume_battery_pct,
            custom_charging_enabled=custom_charging_enabled,
            charging_start_min=charging_start_min,
            charging_end_min=charging_end_min,
            # LIT — headlight / LED config
            led_period_enabled=led_period_enabled,
            led_in_standby=led_in_standby,
            led_in_working=led_in_working,
            led_in_charging=led_in_charging,
            led_in_error=led_in_error,
            # ATA — anti-theft alarm
            anti_theft_lift_alarm=anti_theft_lift_alarm,
            anti_theft_offmap_alarm=anti_theft_offmap_alarm,
            anti_theft_realtime_location=anti_theft_realtime_location,
            # REC — human presence alert
            human_presence_alert_enabled=human_presence_alert_enabled,
            human_presence_alert_sensitivity=human_presence_alert_sensitivity,
            photo_consent=photo_consent,
            # AMBIGUOUS_TOGGLE single-int settings
            frost_protection_enabled=frost_protection_enabled,
            auto_recharge_standby_enabled=auto_recharge_standby_enabled,
            ai_obstacle_photos_enabled=ai_obstacle_photos_enabled,
            navigation_path_smart=navigation_path_smart,
            # MSG_ALERT — notification preferences (4 toggles)
            msg_alert_anomaly=msg_alert_anomaly,
            msg_alert_error=msg_alert_error,
            msg_alert_task=msg_alert_task,
            msg_alert_consumables=msg_alert_consumables,
            # VOICE — voice prompt modes (4 toggles)
            voice_regular_notification=voice_regular_notification,
            voice_work_status=voice_work_status,
            voice_special_status=voice_special_status,
            voice_error_status=voice_error_status,
        )
        if new_state != self.data:
            self.async_set_updated_data(new_state)

        # Poll MAPL for active-map detection.
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_cfg: MAPL poll raised: %s", ex)
            mapl_resp = None
        self._apply_mapl(mapl_resp if isinstance(mapl_resp, list) else None)

    async def refresh_wifi_archive(self) -> dict:
        """Fetch all cloud wifimap objects and archive new ones to disk.

        Idempotent: objects already on disk are skipped. Returns:
            {"fetched": int, "new": int, "archive_total": int}
        """
        import time as _time

        if self._wifi_archive_store is None or not hasattr(self, "_cloud"):
            return {"fetched": 0, "new": 0, "archive_total": 0}

        extents = self._build_map_extents()
        candidates = await self.hass.async_add_executor_job(
            lambda: self._cloud.list_wifi_candidates(map_extents=extents)
        )
        if not isinstance(candidates, list):
            candidates = []

        new_count = 0
        now_ts = int(_time.time())
        for cand in candidates:
            obj_name = cand.get("object_name") if isinstance(cand, dict) else None
            if not isinstance(obj_name, str):
                continue
            if self._wifi_archive_store.has_object(obj_name):
                continue
            body = await self.hass.async_add_executor_job(
                self._download_and_archive_wifi, obj_name, now_ts
            )
            if body is not None:
                new_count += 1

        self._wifi_archive_index = self._wifi_archive_store.load_index()
        result = "downloaded" if new_count > 0 else "no_data"
        self._wifi_archive_last_refresh = {
            "last_attempt_unix": int(_time.time()),
            "result": result,
            "fetched": len(candidates),
            "new": new_count,
        }
        self.async_update_listeners()

        return {
            "fetched": len(candidates),
            "new": new_count,
            "archive_total": len(self._wifi_archive_index),
        }

    def _download_and_archive_wifi(
        self, object_name: str, first_seen_unix: int
    ) -> dict | None:
        """Executor-side: download body from OSS and write to disk."""
        url = self._cloud.get_interim_file_url(object_name)
        if not url:
            return None
        raw = self._cloud.get_file(url)
        if not raw:
            return None
        try:
            import json as _json
            body = _json.loads(raw)
        except Exception:
            return None
        if not isinstance(body, dict) or "data" not in body:
            return None
        self._wifi_archive_store.archive(object_name, body, first_seen_unix)
        return body


    async def _refresh_locn(self) -> None:
        """Fetch LOCN and update MowerState.position_lat/lon."""
        if not hasattr(self, "_cloud"):
            return
        locn = await self.hass.async_add_executor_job(self._cloud.fetch_locn)
        if locn is None:
            return
        pos = locn.get("pos") if isinstance(locn, dict) else None
        if not isinstance(pos, list) or len(pos) != 2:
            return
        lon, lat = pos
        if lon == -1 and lat == -1:
            # Sentinel — dock origin not configured. Leave fields as None.
            new_state = dataclasses.replace(self.data, position_lat=None, position_lon=None)
        else:
            new_state = dataclasses.replace(
                self.data, position_lat=float(lat), position_lon=float(lon)
            )
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_mihis(self) -> None:
        """Fetch CFG.MIHIS → authoritative lifetime mowing totals.

        Returns ``{area: m², count: sessions, start: unix_ts, time: minutes}``
        matching the app's Work Logs header. v1.0.0a75 attempted to read
        this from the all-keys CFG dump but MIHIS is a separate
        `getCFG t:'MIHIS'` endpoint, so that path always returned None
        and the local-archive seed was never overridden. Fixed in a79.

        The local-archive aggregation at startup remains as a fallback
        — if the cloud RPC fails for any reason the entities stay on
        the local sums until the next refresh succeeds.
        """
        if not hasattr(self, "_cloud"):
            return
        mihis = await self.hass.async_add_executor_job(self._cloud.fetch_mihis)
        if not isinstance(mihis, dict):
            return

        updates: dict[str, Any] = {}
        try:
            if "area" in mihis:
                updates["total_mowed_area_m2"] = float(mihis["area"])
            if "time" in mihis:
                updates["total_mowing_time_min"] = int(mihis["time"])
            if "count" in mihis:
                updates["mowing_count"] = int(mihis["count"])
            # MIHIS.start is a firmware-hardcoded sentinel (1704038400 =
            # 2023-12-31 00:00:00 UTC) that is identical across every cloud
            # dump regardless of mowing activity. Confirmed against 5 dumps
            # 2026-05-04..06: count/area/time evolved while start stayed
            # constant. It is NOT the user's first mow, so do not surface
            # it as first_mowing_date — the local-archive seed at boot
            # (coordinator.py: archived sessions sweep) provides the real
            # earliest-session date.
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[MIHIS] decode error: %s — raw=%r", ex, mihis)
            return

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_dock(self) -> None:
        """Fetch CFG.DOCK → populate dock-state fields on MowerState.

        DOCK returns ``{dock: {connect_status, in_region, x, y, yaw,
        near_x, near_y, near_yaw, path_connect}}``. We pull the inner
        dict and map each field 1:1 onto MowerState. `mower_in_dock`
        is the only one labelled with semantic meaning; the rest are
        named with the `dock_*` prefix and surfaced for diagnostics.
        """
        if not hasattr(self, "_cloud"):
            return
        dock_outer = await self.hass.async_add_executor_job(self._cloud.fetch_dock)
        if not isinstance(dock_outer, dict):
            return
        dock = dock_outer.get("dock") if isinstance(dock_outer.get("dock"), dict) else dock_outer
        if not isinstance(dock, dict):
            return

        def _i(name: str) -> int | None:
            v = dock.get(name)
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        connect_status = dock.get("connect_status")
        in_region = dock.get("in_region")

        updates: dict[str, Any] = {}
        # mower_in_dock was removed from MowerState (SM-14); dock location is
        # now owned by the state machine via handle_cloud_poll below.
        if in_region is not None:
            updates["dock_in_lawn_region"] = bool(in_region)
        for src, dst in (
            ("x", "dock_x_mm"),
            ("y", "dock_y_mm"),
            ("yaw", "dock_yaw"),
        ):
            v = _i(src)
            if v is not None:
                updates[dst] = v

        if not updates:
            return

        # Feed the dock dict to the state machine before committing the
        # legacy MowerState update so SM sees the same signal source.
        import time as _time
        try:
            self.state_machine.handle_cloud_poll(
                source="DOCK", payload=dock, now_unix=int(_time.time())
            )
        except Exception:
            LOGGER.exception("state_machine.handle_cloud_poll(DOCK) failed")

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_net(self) -> None:
        """Fetch CFG.NET → populate wifi_ssid / wifi_ip / wifi_rssi_dbm.

        NET returns ``{current: ssid, list: [{ip, rssi, ssid}, …]}``.
        We pull the matching entry from `list` (where `ssid == current`)
        and populate the three fields. The s1p1 byte[17] live RSSI
        overrides this once heartbeats start flowing — but until then
        the sensor would otherwise sit Unknown for ~45 s after HA boot.
        """
        if not hasattr(self, "_cloud"):
            return
        net = await self.hass.async_add_executor_job(self._cloud.fetch_net)
        if not isinstance(net, dict):
            return

        current_ssid = net.get("current")
        ap_list = net.get("list") if isinstance(net.get("list"), list) else []
        match = next(
            (
                ap for ap in ap_list
                if isinstance(ap, dict) and ap.get("ssid") == current_ssid
            ),
            None,
        )

        updates: dict[str, Any] = {}
        if isinstance(current_ssid, str) and current_ssid:
            updates["wifi_ssid"] = current_ssid
        if match is not None:
            ip = match.get("ip")
            rssi = match.get("rssi")
            if isinstance(ip, str) and ip:
                updates["wifi_ip"] = ip
            if isinstance(rssi, int):
                # Only seed the RSSI if the heartbeat hasn't already
                # populated it — avoid overwriting a live value with a
                # potentially stale catalogue entry.
                if self.data.wifi_rssi_dbm is None:
                    updates["wifi_rssi_dbm"] = rssi

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_dev(self) -> None:
        """Fetch DEV {fw, mac, ota, sn} and update MowerState.

        DEV is the authoritative source for hardware_serial — the s1p5
        cloud `get_properties` path is unreliable on g2408 (mostly returns
        80001). Once DEV has populated `hardware_serial` we can drop s1p5
        from the slow-poll list. firmware_version source could also move
        here in a future change; today we leave the cloud-record path
        alone since DEV.fw matched it in the 2026-05-04 dump.

        DEV.ota's semantic is unconfirmed (user has Auto-update Firmware
        OFF in the app but DEV.ota = 1). Provisionally surfaced as
        `ota_capable_raw` while we figure out what it actually represents.
        """
        if not hasattr(self, "_cloud"):
            return
        dev = await self.hass.async_add_executor_job(self._cloud.fetch_dev)
        if not isinstance(dev, dict):
            return

        new_serial = dev.get("sn")
        new_fw = dev.get("fw")
        new_ota = dev.get("ota")

        updates: dict[str, Any] = {}
        if isinstance(new_serial, str) and new_serial:
            updates["hardware_serial"] = new_serial
        if isinstance(new_fw, str) and new_fw:
            updates["firmware_version"] = new_fw
        if new_ota is not None:
            try:
                updates["ota_capable_raw"] = int(new_ota)
            except (TypeError, ValueError):
                pass

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)
            if "hardware_serial" in updates:
                self._update_device_registry_serial(updates["hardware_serial"])

    def _compute_target_area_m2(self, state: MowerState) -> float | None:
        """Effective area for the current mowing target.

        Behaves like the Dreame app's "this is what will be mowed"
        readout. Source-of-truth order:

        1. Live s1.4 telemetry's per-task area
           (``task_total_area_m2``) when a session is active. This
           is the firmware's own "target" figure; it covers any
           combination of selected zones/spots without the cloud map
           round-trip.
        2. Cloud-map area_m2 of the selected zone(s) or spot(s) when
           the user has picked a target. Used pre-session so the
           dashboard shows the planned target before pressing Start.
        3. Full lawn area otherwise (the sensor's original meaning).
        """
        from .mower.state import ActionMode

        # Priority 1: live telemetry while mowing.
        # Use live_map.is_active() — session_active was removed from MowerState (SM-14).
        live_task_area = state.task_total_area_m2
        if (
            self.live_map.is_active()
            and live_task_area is not None
            and live_task_area > 0
        ):
            return float(live_task_area)

        map_data = self._cached_maps_by_id.get(self._active_map_id)
        mode = state.action_mode
        if map_data is not None:
            if mode == ActionMode.ZONE and state.active_selection_zones:
                wanted = set(state.active_selection_zones)
                total = 0.0
                for z in getattr(map_data, "mowing_zones", ()):
                    if z.zone_id in wanted:
                        total += float(getattr(z, "area_m2", 0.0) or 0.0)
                if total > 0:
                    return total
            if mode == ActionMode.SPOT and state.active_selection_spots:
                wanted = set(state.active_selection_spots)
                total = 0.0
                matched: list[tuple[int, str, float]] = []
                for s in getattr(map_data, "spot_zones", ()):
                    if s.spot_id in wanted:
                        matched.append(
                            (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                        )
                        total += matched[-1][2]
                if total > 0:
                    return total
                # v1.0.0a51: log once when SPOT mode would target a real
                # selection but we can't compute an area — distinguishes
                # "spot not found in cached map" from "spot found but
                # cloud sent area=0".
                if not getattr(self, "_target_area_diagnostics_logged", False):
                    available = [
                        (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                        for s in getattr(map_data, "spot_zones", ())
                    ]
                    LOGGER.warning(
                        "[F5] target_area: SPOT mode wanted=%s matched=%s "
                        "available=%s — falling back to total_lawn_area_m2",
                        list(wanted), matched, available,
                    )
                    self._target_area_diagnostics_logged = True
        # All-areas, edge mode, or no selection / no area data yet:
        # fall back to the full lawn area (the sensor's original
        # meaning).
        return state.total_lawn_area_m2

    async def _poll_slow_properties(self) -> None:
        """One-off pull of slot values the mower rarely pushes.

        Targets:
          - (6, 3): [cloud_connected, rssi_dbm] tuple
          - (1, 5): hardware serial string (only while still unknown — once
            captured it never changes, so we drop it from the param set)

        Failures are swallowed: cloud RPCs against g2408 frequently
        return 80001 ("device unreachable via cloud relay") and that
        is fine; the sensor just stays at whatever value the most
        recent push left it at.
        """
        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            return
        did = getattr(cloud, "device_id", None)
        if not did:
            return
        params: list[dict[str, Any]] = [
            {"did": str(did), "siid": 6, "piid": 3},
        ]
        if getattr(self.data, "hardware_serial", None) is None:
            params.append({"did": str(did), "siid": 1, "piid": 5})
        try:
            response = await self.hass.async_add_executor_job(
                cloud.get_properties, params
            )
        except Exception as ex:
            LOGGER.debug("slow-poll get_properties raised: %s", ex)
            return
        # Log the raw response once at INFO so a future RE pass can see
        # exactly what g2408 returns for siid=6/piid=3 — important for
        # the (likely) 80001 vs (hopeful) success branches. Subsequent
        # ticks fall back to DEBUG to avoid log spam.
        if not getattr(self, "_slow_poll_logged", False):
            LOGGER.info("slow-poll get_properties (siid=6, piid=3) → %r", response)
            self._slow_poll_logged = True
        else:
            LOGGER.debug("slow-poll get_properties (siid=6, piid=3) → %r", response)
        if not isinstance(response, list):
            return
        import time as _time
        now_unix = int(_time.time())
        for entry in response:
            if not isinstance(entry, dict):
                continue
            if entry.get("code") != 0:
                continue
            siid = int(entry.get("siid", 0))
            piid = int(entry.get("piid", 0))
            value = entry.get("value")
            if value is None:
                continue
            # Cold-boot seeding: feed each cloud-fetched property through
            # the state machine so it learns the current task_state /
            # battery / charging even when MQTT never re-pushes them.
            sm = getattr(self, "state_machine", None)
            if sm is not None:
                try:
                    sm.handle_mqtt_property(
                        siid=siid, piid=piid, value=value, now_unix=now_unix,
                    )
                except Exception:
                    LOGGER.exception(
                        "state_machine.handle_mqtt_property failed for s%dp%d",
                        siid, piid,
                    )
            new_state = apply_property_to_state(self.data, siid, piid, value)
            if new_state != self.data:
                # Watch the emergency_stop transition and surface a
                # persistent_notification when it sets / dismiss when it
                # clears. byte[3] bit 7 sets on safety event (lid/lift)
                # and clears ONLY on PIN entry, so this notification
                # mirrors the Dreame app's modal popup exactly.
                self._handle_emergency_stop_transition(
                    self.data.emergency_stop, new_state.emergency_stop,
                )
                self.async_set_updated_data(new_state)
                # Push the hardware serial into the device registry as soon
                # as it lands. DeviceInfo set at entity-init time can't see
                # the value (state is None during construction), so without
                # this nudge the user-facing "Serial Number" field stays
                # empty until the next HA reload.
                if (
                    new_state.hardware_serial is not None
                    and (siid, piid) == (1, 5)
                ):
                    self._update_device_registry_serial(new_state.hardware_serial)

    def _handle_emergency_stop_transition(
        self, prev: bool | None, new: bool | None,
    ) -> None:
        """Surface a persistent_notification mirroring the Dreame app's
        modal popup when the mower goes into the PIN-required lockout
        state, and dismiss it when the user enters the PIN to clear.

        byte[3] bit 7 (state.emergency_stop) is the load-bearing latch:
        sets on safety event (lid open OR lift), clears ONLY on PIN
        entry. So this notification's lifecycle exactly matches the
        app's "Emergency stop activated. Enter PIN code on the robot
        to unlock it." popup.
        """
        # Treat None (state not yet known) the same as False for trigger
        # purposes — handles the first heartbeat after HA restart where
        # the prior state was None and the mower is already in lockout.
        prev_active = prev is True
        new_active = new is True
        if prev_active and not new_active:
            try:
                from homeassistant.components import persistent_notification as _pn
                _pn.async_dismiss(
                    self.hass,
                    notification_id=f"{DOMAIN}_emergency_stop_{self.entry.entry_id}",
                )
                LOGGER.info("emergency_stop cleared — persistent_notification dismissed")
            except Exception as ex:
                LOGGER.warning("emergency_stop dismiss failed: %s", ex)
            return
        if prev_active or not new_active:
            return
        # Transition (None|False) → True: post the modal-equivalent banner.
        try:
            from homeassistant.components import persistent_notification as _pn
            _pn.async_create(
                self.hass,
                message=(
                    "The mower has triggered its safety lockout. **Enter "
                    "the PIN code on the robot to unlock it.** The mower "
                    "will not mow until the PIN is entered.\n\n"
                    "This notification will dismiss automatically once "
                    "the PIN is accepted."
                ),
                title="Dreame A2 Mower — Emergency stop activated",
                notification_id=f"{DOMAIN}_emergency_stop_{self.entry.entry_id}",
            )
            LOGGER.info("emergency_stop activated — persistent_notification posted")
        except Exception as ex:
            LOGGER.warning("emergency_stop notification create failed: %s", ex)

    def _update_device_registry_serial(self, serial: str) -> None:
        """Reflect the real hardware serial onto the device record."""
        try:
            from homeassistant.helpers import device_registry as dr
        except ImportError:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.entry.entry_id)})
        if device is None:
            LOGGER.debug(
                "hardware_serial fetched but device record not yet registered "
                "(serial=%r) — will pick up on next entity registration",
                serial,
            )
            return
        if device.serial_number == serial:
            return
        registry.async_update_device(device.id, serial_number=serial)
        LOGGER.info("device serial_number updated to %s", serial)

    def _get_device_registry(self) -> object | None:
        """Return the HA device registry, or None if unavailable in this test env."""
        try:
            from homeassistant.helpers import device_registry as dr
        except ImportError:
            return None
        return dr.async_get(self.hass)

    def _sync_map_subdevices(self) -> None:
        """Add HA devices for new map_ids; remove devices for dropped ones.

        Called whenever `_cached_maps_by_id` may have changed (after
        `_apply_mapl` and after `_refresh_map`). No-ops if `self.hass` or
        `self.entry` is missing or None (test stubs may not have them set).
        """
        if not hasattr(self, "hass") or self.hass is None:
            return
        if not hasattr(self, "entry") or self.entry is None:
            return
        from ._devices import _stable_id, map_device_info

        registry = self._get_device_registry()
        if registry is None:
            return
        stable = _stable_id(self)
        wanted_ids = set(self._cached_maps_by_id.keys())

        for map_id, map_data in self._cached_maps_by_id.items():
            info = map_device_info(self, map_id, getattr(map_data, "name", None))
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                **info,
            )

        # Remove orphan map sub-devices belonging to this entry.
        # HA device identifiers are typed as `set[tuple[str, str]]` but in
        # the wild some integrations store longer tuples. Iterate defensively.
        prefix = f"{stable}_map_"
        for dev in list(registry.devices.values()):
            for ident_tuple in dev.identifiers:
                if len(ident_tuple) < 2 or ident_tuple[0] != DOMAIN:
                    continue
                ident = ident_tuple[1]
                if not isinstance(ident, str) or not ident.startswith(prefix):
                    continue
                try:
                    map_id = int(ident.removeprefix(prefix))
                except ValueError:
                    continue
                if map_id not in wanted_ids:
                    registry.async_remove_device(dev.id)
                break

    def _schedule_cloud_refresh(
        self, *, delay_sec: float = 5.0, reason: str = "tripwire",
    ) -> None:
        """Debounced cloud-state refresh — coalesces bursts of MQTT
        settings tripwires (s6p2 etc.) into a single fetch.

        Called from the MQTT event-loop hop on every tripwire push.
        Each call cancels any pending fire and arms a new timer so a
        burst of settings saves results in exactly one refresh once
        the burst settles. Default delay 5s — short enough that HA
        reflects an app-side edit within a few seconds, long enough
        to coalesce the 1-3 tripwires the firmware tends to emit per
        save (FRAME_INFO + an echo or two).
        """
        loop = self.hass.loop
        if self._cloud_refresh_debounce_handle is not None:
            self._cloud_refresh_debounce_handle.cancel()

        def _fire() -> None:
            self._cloud_refresh_debounce_handle = None
            LOGGER.info(
                "[cloud] settings tripwire (%s) → refreshing cloud state",
                reason,
            )
            self.hass.async_create_task(self._refresh_cloud_state())

        self._cloud_refresh_debounce_handle = loop.call_later(delay_sec, _fire)

    async def _refresh_cloud_state(self) -> None:
        """Single-shot fetch of the full cloud state.

        Called every 10 min via the periodic timer. Replaces the
        previous _refresh_cfg + _refresh_map + _refresh_mihis +
        _refresh_locn + _refresh_dock + _refresh_net + _refresh_dev
        + _poll_slow_properties series.

        On success: self.cloud_state is replaced atomically. Entities
        and consumers re-render via async_update_listeners.
        On failure: self.cloud_state is left unchanged.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            new_state = await self.hass.async_add_executor_job(
                self._cloud.fetch_full_cloud_state
            )
        except Exception as ex:
            LOGGER.warning("[cloud] _refresh_cloud_state raised: %s", ex)
            return
        if new_state is None:
            LOGGER.debug("[cloud] _refresh_cloud_state: fetch returned None")
            return
        self.cloud_state = new_state
        # Mirror legacy attributes that downstream code reads. These
        # become inert once all consumers move to cloud_state directly,
        # but the migration is staged across Task 7+ steps.
        self._cached_maps_by_id = new_state.maps_by_id
        # Re-render PNGs for any map whose md5 changed.
        await self._render_maps_from_cloud_state()
        # Update derived MowerState fields from CFG / SETTINGS / MIHIS.
        self._apply_cloud_state_to_mower_state()
        # Notify entity listeners of the new data.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    async def _render_maps_from_cloud_state(self) -> None:
        """Render CLEAN base PNGs for each map in cloud_state.maps_by_id.

        `_static_map_pngs_by_id` is the per-map base cache used by
        DreameA2PerMapCamera (Map Selector + Settings & Zones tabs).
        These are picker / overview surfaces — they should show the
        boundary + zones + dock + exclusion/ignore/maintenance
        overlays only. NO historical M_PATH fill, NO live trails.

        The active-map view (Mower tab) gets its own render with
        trails + M_PATH via `_render_main_view()` → `_main_view_png`,
        used exclusively by DreameA2MapCamera.
        """
        if self.cloud_state is None:
            return
        from .map_render import render_base_map
        for map_id, map_data in self.cloud_state.maps_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            if prev_md5 == map_data.md5 and map_id in self._static_map_pngs_by_id:
                continue
            png = await self.hass.async_add_executor_job(
                render_base_map, map_data,
            )
            if png:
                self._static_map_pngs_by_id[map_id] = png
                self._last_map_md5_by_id[map_id] = map_data.md5
        # Also populate _main_view_png so DreameA2MapCamera reads a fresh
        # active-map render after every cloud_state refresh.
        await self._render_main_view()
        # And populate _active_map_base_png — the Work Log camera's
        # empty-state image (clean base, no trail, no M_PATH).
        await self._render_active_map_base()

    def _apply_cloud_state_to_mower_state(self) -> None:
        """Push CFG / MIHIS / SETTINGS-derived fields onto MowerState.

        Mirrors what _refresh_cfg / _refresh_mihis used to do, now
        sourcing from cloud_state. SETTINGS-driven MowerState fields
        added in Task 8.
        """
        if self.cloud_state is None:
            return
        cs = self.cloud_state
        updates: dict[str, Any] = {}
        # MIHIS lifetime totals
        mihis = cs.mihis or {}
        if "area" in mihis:
            updates["total_mowed_area_m2"] = float(mihis["area"])
        if "time" in mihis:
            updates["total_mowing_time_min"] = int(mihis["time"])
        if "count" in mihis:
            updates["mowing_count"] = int(mihis["count"])
        # SETTINGS-driven per-active-map fields.
        active_id = self._active_map_id
        if active_id is not None:
            sm = cs.settings.by_map_id_canonical.get(active_id) or {}
            for src, dst in (
                ("mowingHeight", "settings_mowing_height"),
                ("mowingDirection", "settings_mowing_direction"),
                ("mowingDirectionMode", "settings_mowing_direction_mode"),
                ("cutterPosition", "settings_cutter_position"),
                ("cutterPositionHeight", "settings_cutter_position_height"),
                ("edgeMowingNum", "settings_edge_mowing_num"),
                ("edgeMowingWalkMode", "settings_edge_mowing_walk_mode"),
                ("obstacleAvoidanceHeight", "settings_obstacle_avoidance_height"),
                ("obstacleAvoidanceDistance", "settings_obstacle_avoidance_distance"),
                ("obstacleAvoidanceSensitivity", "settings_obstacle_avoidance_sensitivity"),
                ("obstacleAvoidanceAi", "settings_obstacle_avoidance_ai"),
            ):
                if src in sm:
                    try:
                        updates[dst] = int(sm[src])
                    except (TypeError, ValueError):
                        pass
            for src, dst in (
                ("edgeMowingAuto", "settings_edge_mowing_auto"),
                ("edgeMowingSafe", "settings_edge_mowing_safe"),
                ("edgeMowingObstacleAvoidance", "settings_edge_mowing_obstacle_avoidance"),
                ("obstacleAvoidanceEnabled", "settings_obstacle_avoidance_enabled"),
            ):
                if src in sm:
                    updates[dst] = bool(sm[src])
        # CFG keys → MowerState (same fields as _refresh_cfg used to set;
        # the existing _refresh_cfg stays for now to do the heavy lifting,
        # see Task 7 step 6).
        if not updates:
            return
        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _load_persisted_maps(self) -> None:
        """Restore `_cached_maps_by_id` from the on-disk cache.

        Reads the raw fetch_map dict last persisted by `_save_persisted_maps`,
        parses it via `parse_cloud_maps`, and populates the cache + sub-
        device registry so map-metadata sensors light up immediately on
        reload. The subsequent `_refresh_map` will overwrite with fresh
        data; this just removes the empty-cache gap.

        Silently no-ops when no cache exists or the stored payload is
        unusable. Per-map PNGs are not pre-rendered (the cloud-driven
        refresh handles those).
        """
        if self._maps_cache_store is None:
            return
        raw = await self._maps_cache_store.async_load()
        if not isinstance(raw, dict):
            return
        # Store-loaded dicts have str keys; re-cast map_id back to int.
        try:
            cloud_response = {int(k): v for k, v in raw.items()}
        except (TypeError, ValueError):
            LOGGER.warning("[map] persisted map cache has unparsable keys; ignoring")
            return
        if not cloud_response:
            return
        from .map_decoder import parse_cloud_maps
        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _load_persisted_maps: parse returned empty")
            return
        self._cached_maps_by_id = parsed_by_id
        self._sync_map_subdevices()
        LOGGER.info(
            "[map] _load_persisted_maps: restored %d map(s) from cache",
            len(parsed_by_id),
        )

    async def _save_persisted_maps(self, cloud_response: dict[int, Any]) -> None:
        """Write the raw fetch_map dict to disk so next reload is instant."""
        if self._maps_cache_store is None:
            return
        # Store serialises via JSON; int keys become str on roundtrip.
        await self._maps_cache_store.async_save(cloud_response)

    async def _refresh_map(self) -> None:
        """Fetch the cloud MAP.* batch, parse all maps, and re-render
        per-map base-map PNGs. Updates `_cached_maps_by_id` and
        `_static_map_pngs_by_id`.

        Per-map md5 dedup: if a map's md5 hasn't changed since the last
        fetch, skip re-rendering that map (unless a live trail is active
        on the active map — trail changes even when the base map hasn't).

        v1.0.0a33: notify listeners when any map's zones/spots change so
        select.zone / select.spot escape "(no map yet)" without waiting
        for the next state push.

        Live-trail re-render path uses _cached_maps_by_id[_active_map_id]
        as the base map.

        All blocking I/O and rendering run in the executor per spec §3.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return

        from .map_decoder import parse_cloud_maps
        from .map_render import render_base_map

        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return

        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _refresh_map: parse_cloud_maps returned empty")
            return

        # Persist the raw cloud response so the next reload starts with
        # sensors populated. Best-effort; failures are non-fatal.
        if getattr(self, "_maps_cache_store", None) is not None:
            try:
                await self._save_persisted_maps(cloud_response)
            except Exception:
                LOGGER.exception("_save_persisted_maps failed; continuing")

        # v1.0.0a33: detect zones/spots changes across ALL maps before
        # overwriting the cache, so we can fire update_listeners once
        # if any map changed its selectable areas.
        zones_spots_changed = False
        for map_id, map_data in parsed_by_id.items():
            prev_map_data = self._cached_maps_by_id.get(map_id)
            prev_zones = getattr(prev_map_data, "mowing_zones", ()) if prev_map_data else ()
            prev_spots = getattr(prev_map_data, "spot_zones", ()) if prev_map_data else ()
            if (
                prev_map_data is None
                or map_data.mowing_zones != prev_zones
                or map_data.spot_zones != prev_spots
            ):
                zones_spots_changed = True
                break

        # Update the MapData cache with all parsed maps.
        self._cached_maps_by_id = parsed_by_id

        # Render per-map BASE PNGs (no trails) into the per-map cache.
        # The active-map trail overlay is rendered separately into
        # `_main_view_png` by `_render_main_view()`.
        for map_id, map_data in parsed_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            # `_static_map_pngs_by_id` is the per-map BASE cache (used
            # by Map Selector + Settings & Zones tiles). Always render
            # base-only here; the active-map trail overlay lives in
            # `_main_view_png` via `_render_main_view()`. Mixing the
            # two paints mower trails onto the static map-selector
            # tiles, which is jarring.
            if prev_md5 == map_data.md5:
                LOGGER.debug(
                    "[MAP] map_id=%s md5 unchanged (%s) — skipping re-render",
                    map_id, map_data.md5,
                )
                continue
            png = await self.hass.async_add_executor_job(render_base_map, map_data)
            if png:
                self._static_map_pngs_by_id[map_id] = png
                self._last_map_md5_by_id[map_id] = map_data.md5
            LOGGER.info(
                "[MAP] map_id=%s rendered base map PNG (%d bytes), md5=%s",
                map_id,
                len(png) if png else 0,
                map_data.md5,
            )

        # Notify listeners (camera entity, select entities) if zones/spots
        # changed on any map.
        if zones_spots_changed:
            update_listeners = getattr(self, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()

        # Populate _main_view_png so DreameA2MapCamera reads a fresh
        # active-map render after every map fetch.
        await self._render_main_view()

        # Sync HA sub-devices to the updated _cached_maps_by_id.
        self._sync_map_subdevices()

    def _current_mower_position(self) -> tuple[float, float] | None:
        """Return the current mower (x_m, y_m) cloud-frame position, or
        None when either coordinate is unset. Used by the live-map
        renders to draw the position marker."""
        x = self.data.position_x_m
        y = self.data.position_y_m
        if x is None or y is None:
            return None
        return (float(x), float(y))

    def _current_mower_heading(self) -> float | None:
        """Return the mower's current heading in degrees, or None."""
        h = self.data.position_heading_deg
        return float(h) if h is not None else None

    async def _rerender_live_trail(
        self,
        position: tuple[float, float] | None = None,
        heading: float | None = None,
    ) -> None:
        """Re-render the cached map with the current live trail.

        v1.0.0a19: position + heading are passed explicitly by the
        _on_state_update hook so the icon reflects the SAME push that
        just appended to live_map. Without this, reading self.data
        inside the scheduled task could see either the old or new
        state depending on whether async_set_updated_data has run yet,
        and the icon would lag behind the trail.
        """
        map_data = self._cached_maps_by_id.get(self._active_map_id)
        if map_data is None or not self.live_map.is_active():
            return
        from .map_render import render_with_trail
        legs = list(self.live_map.legs)
        if position is None:
            position = self._current_mower_position()
        if heading is None:
            heading = self._current_mower_heading()
        png = await self.hass.async_add_executor_job(
            render_with_trail, map_data, legs, None, position, heading,
        )
        LOGGER.debug(
            "[MAP] live trail re-render: legs=%d points=%d bytes=%d pos=%s hdg=%s",
            len(legs), self.live_map.total_points(), len(png) if png else 0,
            position, heading,
        )
        await self._render_main_view()

    async def _render_main_view(self) -> None:
        """Render the active map's Main view (base + live trail + mower icon).

        Writes the result to self._main_view_png. No-ops gracefully when:
        - _active_map_id is None (active map not yet known)
        - _cached_maps_by_id has no entry for the active map
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self._cached_maps_by_id.get(active_id)
        if map_data is None:
            return
        from functools import partial

        from .map_render import render_main_view

        legs = list(self.live_map.legs) if self.live_map.is_active() else None
        if (
            self.data.position_x_m is not None
            and self.data.position_y_m is not None
        ):
            mower_pos: tuple[float, float] | None = (
                float(self.data.position_x_m),
                float(self.data.position_y_m),
            )
        else:
            mower_pos = None
        heading = self._current_mower_heading()
        png = await self.hass.async_add_executor_job(
            partial(
                render_main_view,
                map_data,
                legs=legs,
                mower_position_m=mower_pos,
                mower_heading_deg=heading,
            )
        )
        if png:
            self._main_view_png = png
        # Also keep the work-log empty-state PNG fresh. Md5-deduped, so
        # the no-op fast-path runs after the first render per map version.
        await self._render_active_map_base()

    async def _render_active_map_base(self) -> None:
        """Render the active map's clean base (no trail, no mower icon, no M_PATH).

        Writes the result to self._active_map_base_png. Used as the Work
        Log camera's empty-state image (when no session is picked) — it
        shows "this is the map your work logs would render on" without
        confusing the user with cumulative mow history.

        Md5-deduped: re-renders only when the active map's MapData.md5
        changes (or when the cache slot is empty). Safe to call from
        every _render_main_view trigger because the actual PIL render
        runs at most once per map version.
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self._cached_maps_by_id.get(active_id)
        if map_data is None:
            return
        current_md5 = getattr(map_data, "md5", None)
        if (
            self._active_map_base_png is not None
            and self._active_map_base_md5 == current_md5
        ):
            return  # already have a fresh render for this md5
        from .map_render import render_base_map
        png = await self.hass.async_add_executor_job(
            render_base_map, map_data,
        )
        if png:
            self._active_map_base_png = png
            self._active_map_base_md5 = current_md5

    async def write_schedule(
        self,
        new_slots: tuple[Any, ...] | list[Any],
    ) -> bool:
        """Push a new SCHEDULE blob to the cloud via write_chunked_key.

        new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
        source of truth; .raw_blob_b64 is ignored — re-encoded). Bumps
        the schedule version by 1 and refreshes cloud_state on success.
        """
        from .protocol.schedule import build_schedule_set_value

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule: cloud client not ready")
            return False
        cs = self.cloud_state
        current_v = cs.schedule.version if cs is not None else 0
        new_v = current_v + 1
        json_value = build_schedule_set_value(tuple(new_slots), version=new_v)
        LOGGER.info(
            "[schedule-write] v %d → %d, len(d)=%d, json_len=%d",
            current_v, new_v, len(new_slots), len(json_value),
        )
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SCHEDULE", json_value,
            )
            if not ok:
                LOGGER.warning("[schedule-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    async def write_ai_human_enabled(self, enabled: bool) -> bool:
        """Toggle AI_HUMAN.0 (Capture Photos AI Obstacles) via write_chunked_key.

        Cloud value is a JSON-encoded boolean string (`"true"` / `"false"`).
        Privacy auth is gated app-side; here we trust that AI_HUMAN.0
        being writable means the user has accepted the policy in the app.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_ai_human_enabled: cloud client not ready")
            return False
        value = '"true"' if enabled else '"false"'
        LOGGER.info("[ai-human-write] AI_HUMAN.0 → %s", value)
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "AI_HUMAN", value,
            )
            if not ok:
                LOGGER.warning("[ai-human-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    def _fetch_fresh_settings_blob(self) -> list[dict[str, Any]] | None:
        """Pull SETTINGS chunks fresh from the cloud and return the
        decoded list. Returns None if the fetch fails or the response
        is malformed.

        Runs in the executor (called via async_add_executor_job from
        write_settings). Targets only the SETTINGS keys instead of the
        full empty-batch dump — one HTTP round-trip, ~1-2KB response.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return None
        # Optimistic key list — we only need the chunks the cloud
        # actually has. We over-fetch up to .8 (8 chunks = 8KB total
        # blob) plus .info; missing keys come back as None and are
        # filtered by the chunk-walk below.
        keys = [f"SETTINGS.{i}" for i in range(8)] + ["SETTINGS.info"]
        try:
            response = self._cloud.get_batch_device_datas(keys)
        except Exception as ex:  # pragma: no cover — defensive
            LOGGER.debug("[settings-write] fresh fetch raised: %s", ex)
            return None
        if not isinstance(response, dict):
            return None
        info = response.get("SETTINGS.info")
        if info is None:
            return None
        try:
            total = int(info)
        except (TypeError, ValueError):
            return None
        chunks: list[str] = []
        i = 0
        while True:
            chunk = response.get(f"SETTINGS.{i}")
            if chunk is None:
                break
            chunks.append(str(chunk))
            i += 1
        if not chunks:
            return None
        full = "".join(chunks)[:total]
        import json as _json
        try:
            parsed = _json.loads(full)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None

    async def write_settings(self, *, map_id: int, field: str, value: Any) -> bool:
        """Push one SETTINGS field change to the cloud.

        Pre-write fresh-fetch: pulls the current SETTINGS blob from the
        cloud right before the write so the resulting blob carries
        whatever values the app (or another HA instance) most recently
        saved. Without this step, HA's read-modify-write would be based
        on the last 10-min poll's snapshot — every other field on every
        map would be stamped back to its stale value, clobbering anything
        the app changed in the meantime.

        Read-modify-write mutates the target field on every entry that
        carries the target map_id; other fields and other maps are left
        untouched. Serializes against _chunked_write_lock so concurrent
        writes can't race against the same fresh fetch.

        Returns True iff cloud accepted (code=0). Triggers a cloud_state
        refresh on success so the local view reflects what landed.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_settings: cloud client not ready")
            return False
        from .protocol.settings import parse_settings_batch, write_setting

        async with self._chunked_write_lock:
            # Always try a fresh fetch first so the RMW is on cloud-current data.
            fresh_raw = await self.hass.async_add_executor_job(
                self._fetch_fresh_settings_blob,
            )
            if fresh_raw is not None:
                settings_raw = fresh_raw
                # Mirror onto cloud_state so subsequent reads see fresh values.
                # Defensive: cloud_state may not exist yet if write happens
                # before the first periodic refresh.
                cs = self.cloud_state
                if cs is not None:
                    self.cloud_state = dataclasses.replace(
                        cs, settings=parse_settings_batch(fresh_raw),
                    )
            else:
                # Fresh fetch failed; fall back to the cached state and accept
                # the higher-stale-cache risk for this one write.
                cs = self.cloud_state
                if cs is None:
                    LOGGER.warning(
                        "write_settings: cloud_state empty and fresh fetch failed"
                    )
                    return False
                settings_raw = cs.settings.raw
                LOGGER.warning(
                    "[settings-write] fresh fetch failed; falling back to cached state"
                )
            try:
                new_raw = write_setting(
                    settings_raw, map_id=map_id, field=field, value=value,
                )
            except KeyError as ex:
                LOGGER.warning("write_settings: KeyError %s", ex)
                return False
            import json as _json
            json_value = _json.dumps(new_raw, separators=(",", ":"))
            LOGGER.info(
                "[settings-write] field=%s map=%d value=%r json_len=%d (fresh=%s)",
                field, map_id, value, len(json_value), fresh_raw is not None,
            )
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SETTINGS", json_value,
            )
            if not ok:
                LOGGER.warning("[settings-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    async def replay_session(self, session_md5: str) -> None:
        """Backwards-compat alias for the Work Log render method.

        Kept so the public dreame_a2_mower.replay_session service (and any
        user automations referencing it) keep working after the rename.
        """
        await self.render_work_log_session(session_md5)

    async def render_work_log_session(self, session_md5: str) -> None:
        """Render an archived session's path into _work_log_png.

        Look up the session by md5 in session_archive, parse its track
        segments via parse_session_summary, then render via
        render_work_log using the archived legs.  Updates
        _work_log_png in-place — the work-log camera entity serves whatever is
        cached, so the replay is immediately visible.

        This is one-shot: the next _refresh_map tick (every 6 hours, or
        sooner on map-data change) restores the live view.

        Args:
            session_md5: The md5 string of the archived session.

        Logs a warning and returns early if:
        - The md5 does not match any session in the archive.
        - The raw JSON cannot be loaded from disk.
        - parse_session_summary raises (malformed data).
        - _refresh_map hasn't fetched map data yet (no cloud client).
        """
        import time as _time

        from .map_decoder import parse_cloud_map
        from .map_render import render_work_log

        replay_start_unix = _time.monotonic()
        LOGGER.info("[F5.9.1] render_work_log_session: looking up md5=%s", session_md5)

        # --- 1. Find the ArchivedSession entry. The picker passes either:
        #   - the unique filename (post-v1.0.0a53; only key with no
        #     collisions when multiple sessions share an md5), OR
        #   - a 32-char md5 (legacy, also used by the public
        #     dreame_a2_mower.replay_session service). Match either.
        # When multiple entries share an md5 (g2408 reuses md5 across
        # sessions on an unchanged map — see project memo
        # 'g2408 session-archive + target-area quirks'), pick the most
        # recent by end_ts so the user gets the entry they actually
        # see at the top of the picker label list.
        sessions = await self.hass.async_add_executor_job(
            self.session_archive.list_sessions
        )
        by_filename = next(
            (s for s in sessions if s.filename == session_md5), None
        )
        if by_filename is not None:
            entry = by_filename
        else:
            md5_matches = [s for s in sessions if s.md5 == session_md5]
            entry = max(md5_matches, key=lambda s: s.end_ts, default=None)
        if entry is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: no session with key=%s in archive "
                "(%d sessions total)", session_md5, len(sessions)
            )
            return

        # --- 2. Load the raw JSON from disk ---
        raw_dict = await self.hass.async_add_executor_job(
            self.session_archive.load, entry
        )
        if raw_dict is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: failed to load raw JSON for md5=%s "
                "(filename=%s)", session_md5, entry.filename
            )
            return

        # --- 3. Parse the session summary to extract track_segments ---
        from .protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: parse_session_summary failed for "
                "md5=%s: %s", session_md5, ex
            )
            return

        # track_segments is tuple[tuple[tuple[float,float],...],...]
        # render_work_log expects list[list[tuple[float,float]]]
        legs: list[list[tuple[float, float]]] = [
            list(seg) for seg in summary.track_segments
        ]

        # Replay-only overlay: each Obstacle.polygon is already a tuple
        # of (x_m, y_m) pairs (the protocol decoder handled the cm→m
        # conversion). Pass empty list rather than None when the session
        # has none, so the renderer's branch is consistent.
        obstacle_polygons_m: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]

        # v1.0.0a54 fallback: g2408 omits `track` / `old_track` from
        # spot/zone session_summary JSONs entirely, so summary.track_segments
        # is empty. The auto-finalize path now stores the locally-collected
        # legs under `_local_legs` so the replay can still draw a path.
        if not legs:
            local = raw_dict.get("_local_legs") or []
            if isinstance(local, list):
                rebuilt: list[list[tuple[float, float]]] = []
                for leg in local:
                    pts = [
                        (float(p[0]), float(p[1]))
                        for p in leg
                        if isinstance(p, (list, tuple)) and len(p) >= 2
                    ]
                    if pts:
                        rebuilt.append(pts)
                if rebuilt:
                    legs = rebuilt

        if not legs:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: key=%s has no track segments "
                "(no cloud track + no _local_legs fallback)", session_md5
            )
            # Fall through — render_work_log handles empty legs gracefully
            # (produces same output as render_base_map).

        # --- 4. Resolve which map to render against (MM Task 11: cross-map replay).
        # Use the map_id stamped on the archived session so replays from a
        # non-active map render against their own base map, not today's active.
        # Fall back to _active_map_id when map_id is -1 (legacy entries).
        session_map_id = getattr(entry, "map_id", -1)
        target_map_id = (
            session_map_id if session_map_id != -1 else self._active_map_id
        )
        map_data = (
            self._cached_maps_by_id.get(target_map_id)
            if target_map_id is not None
            else None
        )
        if map_data is None and self._cached_maps_by_id:
            # No map for the session's stamped id — fall back to any cached map
            # rather than making the replay entirely black. Log a warning so the
            # user knows the render may be wrong.
            fallback_id = min(self._cached_maps_by_id.keys())
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: map_id=%r not in cache (have: %s); "
                "falling back to map_id=%r",
                target_map_id,
                sorted(self._cached_maps_by_id.keys()),
                fallback_id,
            )
            target_map_id = fallback_id
            map_data = self._cached_maps_by_id[fallback_id]
        if map_data is None:
            # Cache entirely empty — try a live fetch as a last resort (slow).
            if not hasattr(self, "_cloud"):
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: cloud client not ready yet; "
                    "cannot fetch map for replay"
                )
                return
            cloud_response = await self.hass.async_add_executor_job(
                self._cloud.fetch_map
            )
            if cloud_response is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: fetch_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            map_data = parse_cloud_map(cloud_response)
            if map_data is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: parse_cloud_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self._cached_maps_by_id[active_id] = map_data
            target_map_id = active_id

        # --- 5. Render and cache ---
        # async_add_executor_job only forwards positional args, so use
        # functools.partial to bake obstacle_polygons_m in as a kwarg.
        from functools import partial

        png = await self.hass.async_add_executor_job(
            partial(
                render_work_log,
                map_data,
                legs=legs,
                obstacle_polygons_m=obstacle_polygons_m,
            )
        )
        self._work_log_png = png
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        LOGGER.warning(
            "[F5.9.1] render_work_log_session: rendered work-log PNG (%d bytes) "
            "for key=%s, legs=%d, total_points=%d, elapsed=%dms",
            len(png) if png else 0,
            session_md5,
            len(legs),
            sum(len(leg) for leg in legs),
            elapsed_ms,
        )
        # Tell HA the camera image changed so it triggers an immediate
        # refresh instead of waiting for the next coordinator tick.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _resolve_finalize_map_id(self) -> int:
        """Map id to stamp on a session being finalized.

        Active-map at finalize time is the canonical answer; if no
        active map yet (rare — MAPL not yet polled), fall back to the
        lowest-id cached map; if no maps cached at all, sentinel -1.
        """
        if self._active_map_id is not None:
            return int(self._active_map_id)
        if self._cached_maps_by_id:
            return min(self._cached_maps_by_id.keys())
        return -1

    def _init_cloud(self) -> DreameA2CloudClient:
        """Authenticate with the Dreame cloud and pick up device info."""
        client = DreameA2CloudClient(
            username=self._username,
            password=self._password,
            country=self._country,
        )
        client.login()
        # Discover and pin the g2408 in the cloud device list. Without
        # this _did is None and get_device_info()'s API call returns no
        # data → _host stays None → mqtt_host_port() raises.
        client.select_first_g2408()
        client.get_device_info()  # refreshes _host with OTC info
        host, port = client.mqtt_host_port()
        self._mqtt_host = host
        self._mqtt_port = port
        LOGGER.info(
            "Cloud auth ok; device %s model=%s host=%s",
            client.device_id,
            client.model,
            self._mqtt_host,
        )
        return client

    def _init_mqtt(self) -> None:
        """Open the MQTT connection and subscribe to the mower's status topic."""
        self._mqtt = DreameA2MqttClient()
        self._mqtt.register_callback(self._on_mqtt_message)
        # Raw-MQTT archive intentionally NOT attached here.
        #
        # We empirically confirmed (2026-05-12) that the integration sees
        # exactly the same MQTT stream as the external probe_a2_mqtt.py —
        # same topic, same slots, byte-identical payloads in side-by-side
        # samples. Having both write the same data to disk doubles I/O
        # for no analytic value. The MqttArchive class is kept (see
        # protocol/mqtt_archive.py) and the .attach_archive hook is kept;
        # re-enable here only for short debug windows when probe is off.
        # See docs/research/gps-tracking-todo.md "What we already know
        # NOT to be the path" for the parity check.
        username, password = self._cloud.mqtt_credentials()
        client_id = self._cloud.mqtt_client_id()
        topic = self._cloud.mqtt_topic()
        # MQTT bootstrap diagnostics — v1.0.0a8 originally fired persistent
        # notifications for these to make early-bring-up debugging visible
        # without HA log access. Now that the integration is stable, demoted
        # to DEBUG-level log lines so the notification panel stays clean for
        # actual user-visible events (e.g. emergency_stop). Re-enable as
        # `LOGGER.warning(...)` plus `_pn.create(...)` if you need to
        # diagnose an MQTT-bringup regression on a fresh install.
        LOGGER.debug(
            "MQTT bootstrap: host=%s:%s client_id=%s "
            "username_len=%d password_len=%d topic=%s "
            "did_set=%s uid_set=%s model=%r",
            self._mqtt_host, self._mqtt_port, client_id,
            len(username) if username else 0,
            len(password) if password else 0,
            topic,
            self._cloud._did is not None,
            self._cloud._uid is not None,
            self._cloud._model,
        )

        def _on_first_inbound(topic: str) -> None:
            LOGGER.debug(
                "MQTT first inbound: topic=%r (subscribed=%r)",
                topic, self._cloud.mqtt_topic(),
            )

        def _on_broker_connected() -> None:
            LOGGER.debug("MQTT CONNACK accepted by broker for topic=%s", topic)
        self._mqtt.register_connected_callback(_on_broker_connected)
        self._mqtt._on_first_message = _on_first_inbound
        self._mqtt.connect(
            host=self._mqtt_host,
            port=self._mqtt_port,
            username=username,
            password=password,
            client_id=client_id,
        )
        # subscribe() now caches the topic; the actual paho subscribe
        # fires from _on_connect after CONNACK (v1.0.0a6 fix).
        self._mqtt.subscribe(topic)
        LOGGER.info("Subscribed to %s", topic)

    def _on_mqtt_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Dispatcher for inbound MQTT messages.

        Handles two method types:
        - ``properties_changed`` — individual property pushes (siid/piid/value).
        - ``event_occured`` — event notifications (siid/eiid + arguments list).
          siid=4 eiid=1 carries the OSS object name in arguments[piid=9].
        """
        method = payload.get("method")
        if method == "properties_changed":
            params = payload.get("params") or []
            for p in params:
                if "siid" in p and "piid" in p:
                    self.handle_property_push(
                        siid=int(p["siid"]),
                        piid=int(p["piid"]),
                        value=p.get("value"),
                    )
                    import time as _time
                    _now_unix = int(_time.time())
                    _sm_siid = int(p["siid"])
                    _sm_piid = int(p["piid"])
                    _sm_value = p.get("value")
                    if (_sm_siid, _sm_piid) == (1, 1):
                        # s1p1 heartbeat — decode and route to handle_heartbeat.
                        try:
                            _blob = _coerce_blob(_sm_value, "s1.1")
                            if _blob is not None:
                                _hb = _heartbeat.decode_s1p1(_blob)
                                self.state_machine.handle_heartbeat(
                                    hb=_hb, now_unix=_now_unix
                                )
                        except Exception:
                            LOGGER.exception("state_machine.handle_heartbeat failed")
                    else:
                        try:
                            self.state_machine.handle_mqtt_property(
                                siid=_sm_siid,
                                piid=_sm_piid,
                                value=_sm_value,
                                now_unix=_now_unix,
                            )
                        except Exception:
                            LOGGER.exception("state_machine.handle_mqtt_property failed")
        elif method == "event_occured":
            # F5.6.1: capture OSS object name from siid=4 eiid=1
            params = payload.get("params") or {}
            siid = int(params.get("siid", 0))
            eiid = int(params.get("eiid", 0))
            if siid == 4 and eiid == 1:
                arguments = params.get("arguments") or []
                self.hass.loop.call_soon_threadsafe(
                    lambda args=arguments: self.hass.loop.create_task(
                        self._handle_event_occured(args)
                    )
                )

    def _on_state_update(self, new_state: MowerState, now_unix: int) -> MowerState:
        """Hook fired after apply_property_to_state. Updates LiveMapState
        based on s2p56 transitions and appends s1p4 positions to the
        current leg.

        Returns a possibly-modified MowerState (with session_active /
        session_started_unix / session_track_segments synced from LiveMapState).
        """
        new_task_state = new_state.task_state_code
        prev = self._prev_task_state

        # v1.0.0a18: task_state_code semantics changed when the s2.56
        # extract_value was fixed to read status[0][1] (the sub-state).
        # New mapping: 0 = running, 4 = paused-pending-resume,
        # None = no task (status: []). begin_session fires on any
        # transition from None to a non-None task; begin_leg fires on
        # 4 → 0 (recharge resume).
        if new_task_state != prev:
            # v1.0.0a48: bumped to WARNING so the trail is visible in
            # the HA default log without enabling DEBUG. Each mow only
            # produces a handful of these so noise stays low.
            LOGGER.warning(
                "[F5] task_state_code transition %r → %r (live_map.is_active=%s)",
                prev, new_task_state, self.live_map.is_active(),
            )
        # Begin a session whenever we transition from a non-active code
        # (None=idle, 2=complete) to an active code (0=running,
        # 4=paused). prev=4→new=0 is the recharge-resume case which
        # starts a new leg rather than a new session.
        is_active_now = new_task_state in (0, 4)
        was_active_before = prev in (0, 4)
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # means _restore_in_progress repopulated legs/started_unix
            # from disk (mid-mow HA restart). begin_session would clear
            # legs to [[]] and reset started_unix to now_unix, abandoning
            # the pre-restart trail. Just continue appending to the
            # restored leg.
            self.live_map.begin_session(now_unix)
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_STARTED,
                {
                    "at_unix": int(now_unix),
                    "action_mode": (
                        new_state.action_mode.value
                        if new_state.action_mode is not None
                        else None
                    ),
                    "target_area_m2": new_state.target_area_m2,
                },
            )
            # Re-poll MAPL so the live trail lands on the firmware's
            # current active map, even if the last 10-min CFG poll was
            # before the user switched maps.
            hass = getattr(self, "hass", None)
            if hass is not None:
                hass.async_create_task(self._refresh_mapl())
        elif prev == 0 and new_task_state == 4:
            # Mid-mow pause. Reason is best-effort: if the previous
            # tick's MowerState exposed an obvious cause use it,
            # otherwise "unknown". Don't gate fire on reason detection.
            reason = "unknown"
            if new_state.battery_level is not None and new_state.battery_level <= 20:
                reason = "recharge_required"
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_PAUSED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                    "reason": reason,
                },
            )
        elif prev == 4 and new_task_state == 0:
            self.live_map.begin_leg()
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_RESUMED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                },
            )

        # Telemetry append: if session is active and a position is available
        # and something changed this tick, append the current position.
        if (
            self.live_map.is_active()
            and new_state.position_x_m is not None
            and new_state.position_y_m is not None
            and (new_state != self.data)  # something changed
        ):
            before_pts = self.live_map.total_points()
            self.live_map.append_point(
                new_state.position_x_m, new_state.position_y_m, now_unix
            )
            # Mark dirty if a point was actually added (dedup may have skipped it).
            if self.live_map.total_points() > before_pts:
                self._live_map_dirty = True
                # v1.0.0a18: throttle live-trail re-renders to ~1/s so
                # the camera entity reflects the moving mower without
                # PIL re-rendering on every 5-Hz s1.4 push.
                self._live_trail_dirty = True
                if now_unix - self._last_live_render_unix >= 1.0:
                    self._last_live_render_unix = float(now_unix)
                    self._live_trail_dirty = False
                    hass = getattr(self, "hass", None)
                    if hass is not None:
                        # v1.0.0a19: pass the live position + heading
                        # from new_state so the icon lands at the END
                        # of the just-appended path, not at whatever
                        # self.data happened to be when the scheduled
                        # task runs.
                        hass.async_create_task(
                            self._rerender_live_trail(
                                position=(
                                    float(new_state.position_x_m),
                                    float(new_state.position_y_m),
                                ),
                                heading=(
                                    float(new_state.position_heading_deg)
                                    if new_state.position_heading_deg is not None
                                    else None
                                ),
                            )
                        )

        # Sync MowerState's session view from LiveMapState. session_distance_m
        # is integrated from the trail (sum of segment lengths within each
        # leg, pen-up gaps excluded) — see LiveMapState.total_distance_m().
        # Cleared to None when no session is active so the sensor goes
        # unavailable between mows rather than persisting the last value.
        new_state = dataclasses.replace(
            new_state,
            session_started_unix=self.live_map.started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
            session_distance_m=(
                self.live_map.total_distance_m() if self.live_map.is_active() else None
            ),
            target_area_m2=self._compute_target_area_m2(new_state),
        )

        self._prev_task_state = new_task_state

        # Dock arrival/departure rising/falling edges. Read current dock
        # state from the state machine (SM-14: mower_in_dock removed from
        # MowerState; Location.AT_DOCK is the canonical source). Explicit
        # `is True` / `is False` on _prev_in_dock so the boot-time None
        # doesn't fire a spurious arrived/departed event.
        # Defensive: test fixtures construct via __new__ without __init__,
        # so state_machine may be missing; treat as "not at dock" then.
        from .mower.state_snapshot import Location as _Location
        _sm = getattr(self, "state_machine", None)
        _sm_at_dock: bool = (
            _sm is not None and _sm.snapshot().location == _Location.AT_DOCK
        )
        if self._prev_in_dock is False and _sm_at_dock:
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_ARRIVED, {"at_unix": int(now_unix)}
            )
        elif self._prev_in_dock is True and not _sm_at_dock:
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_DEPARTED, {"at_unix": int(now_unix)}
            )
        self._prev_in_dock = _sm_at_dock

        # F13 — s2p2 notification synthesis. Fire dreame_a2_mower_alert on
        # transitions to known notification codes. The first push on HA boot
        # is intentionally suppressed (_prev_error_code starts as None so
        # new_code != old_code but we require new_code != None as well as
        # old_code != None to avoid firing stale codes on restart).
        # Boot-suppression: if old_code is None we just record the current
        # value without firing, so the NEXT change fires correctly.
        new_error_code = new_state.error_code
        old_error_code = self._prev_error_code
        if (
            new_error_code is not None
            and new_error_code != old_error_code
            and old_error_code is not None  # suppress first-push-after-boot
            and new_error_code in S2P2_NOTIFICATION_MAP
        ):
            event_type, text = S2P2_NOTIFICATION_MAP[new_error_code]
            self._fire_alert(event_type, text, new_error_code, now_unix)
        self._prev_error_code = new_error_code

        # F6 review fix #1: record freshness AFTER all derivations so
        # session-derived fields (session_active, session_started_unix,
        # session_track_segments) are stamped with accurate timestamps.
        self.freshness.record(self.data, new_state, now_unix=now_unix)

        # F7.2.2: kick off LiDAR fetch when object_name flips to a new key.
        prev_lidar = getattr(self.data, "latest_lidar_object_name", None)
        if (
            new_state.latest_lidar_object_name is not None
            and new_state.latest_lidar_object_name != prev_lidar
        ):
            self.hass.async_create_task(
                self._handle_lidar_object_name(
                    new_state.latest_lidar_object_name, now_unix
                )
            )

        return new_state

    # -----------------------------------------------------------------------
    # F5.6.1 — event_occured handler + periodic retry
    # -----------------------------------------------------------------------

    async def _handle_event_occured(self, arguments: list[dict[str, Any]]) -> None:
        """Handle an event_occured (siid=4 eiid=1) message.

        Extracts the OSS object name from ``arguments[piid=9]`` and stores it
        as ``pending_session_object_name`` + ``pending_session_first_event_unix``
        on MowerState so the periodic retry loop can pick it up.

        Called on the event loop (via call_soon_threadsafe) — safe to call
        async_set_updated_data directly.
        """
        import time as _time
        object_name: str | None = None
        for arg in arguments:
            if int(arg.get("piid", -1)) == 9:
                object_name = str(arg.get("value", "")) or None
                break

        if not object_name:
            LOGGER.warning(
                "[F5.6.1] event_occured (siid=4 eiid=1): no piid=9 argument "
                "or empty value — arguments=%r",
                arguments,
            )
            return

        LOGGER.info(
            "[F5.6.1] event_occured: OSS object_name=%r — scheduling fetch",
            object_name,
        )
        now_unix = int(_time.time())
        new_state = dataclasses.replace(
            self.data,
            pending_session_object_name=object_name,
            pending_session_first_event_unix=now_unix,
            pending_session_last_attempt_unix=None,
            pending_session_attempt_count=0,
        )
        self.async_set_updated_data(new_state)

    # -----------------------------------------------------------------------
    # F7.2.2 — LiDAR scan fetch + archive
    # -----------------------------------------------------------------------

    def lidar_archive_for(self, map_id: int) -> LidarArchive:
        """Return (or lazily create) the LidarArchive for *map_id*.

        Creates a new :class:`LidarArchive` under
        ``<_lidar_archive_root>/<map_id>/`` on first access and caches it
        in :attr:`lidar_archives`.  The per-archive retention and size caps
        are inherited from the coordinator's option values.
        """
        if map_id not in self.lidar_archives:
            self.lidar_archives[map_id] = LidarArchive(
                self._lidar_archive_root,
                retention=self._lidar_archive_retention,
                max_bytes=self._lidar_archive_max_bytes,
                map_id=map_id,
            )
        return self.lidar_archives[map_id]

    def list_lidar_archive_entries(self) -> list[tuple[int, Any]]:
        """Aggregate all LiDAR scans across maps, newest first.

        Returns list of (map_id, ArchivedLidarScan) tuples. Used by the
        cross-map LiDAR archive picker (``select.dreame_a2_mower_lidar_archive``).
        """
        out: list[tuple[int, Any]] = []
        for map_id, archive in self.lidar_archives.items():
            for entry in archive.entries():
                out.append((map_id, entry))
        out.sort(key=lambda x: x[1].unix_ts, reverse=True)
        return out

    def set_lidar_render_entry(self, map_id: int | None, filename: str | None) -> None:
        """Set which LiDAR scan the selected-camera renders. None resets to default."""
        if map_id is None or filename is None:
            self._lidar_render_entry = None
        else:
            self._lidar_render_entry = (map_id, filename)
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _build_map_extents(self) -> dict[int, tuple[float, float, float, float]]:
        """Build map_id → (bx1, by1, bx2, by2) in cm for all cached maps.

        Used by refresh_wifi_archive to pass geometry hints to
        cloud_client.list_wifi_candidates for cross-map heatmap matching.
        Falls back to empty dict when no maps are cached or extent fields
        are unavailable.
        """
        extents: dict[int, tuple[float, float, float, float]] = {}
        for map_id, map_data in self._cached_maps_by_id.items():
            try:
                bx1 = float(getattr(map_data, "bx1", 0.0))
                by1 = float(getattr(map_data, "by1", 0.0))
                bx2 = float(getattr(map_data, "bx2", 0.0))
                by2 = float(getattr(map_data, "by2", 0.0))
                extents[map_id] = (bx1, by1, bx2, by2)
            except (TypeError, ValueError, AttributeError):
                continue
        return extents

    def set_wifi_render_entry(
        self, map_id: int | None, object_name: str | None
    ) -> None:
        """Set which WiFi heatmap the archive camera renders.

        ``object_name`` is the only identity used now (since the
        archive picker always passes ``map_id=None``: heatmap →
        map_id correlation is unsolved — see
        ``docs/research/wifi-heatmap-todo.md``). Pass
        ``object_name=None`` to clear the selection.
        """
        if object_name is None:
            self._wifi_render_entry = None
        else:
            self._wifi_render_entry = (map_id, object_name)
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    async def _handle_lidar_object_name(
        self, object_name: str, now_unix: int
    ) -> None:
        """Fetch and archive a LiDAR PCD scan announced via s99p20.

        Called from `_on_state_update` whenever
        `MowerState.latest_lidar_object_name` flips to a new key.
        Idempotent: caches the last-handled object_name to avoid
        re-fetching while the property re-asserts.

        Failures are logged at WARNING and swallowed — observability
        never breaks telemetry, and the user can re-trigger the upload
        from the app.
        """
        if not object_name or object_name == self._last_lidar_object_name:
            return
        self._last_lidar_object_name = object_name
        LOGGER.info("[LIDAR] s99p20 announced object_name=%r", object_name)

        # T12: route to the per-map archive for the currently active map.
        active_id = getattr(self, "_active_map_id", None)
        if active_id is None:
            LOGGER.debug(
                "[LIDAR] push received but _active_map_id unknown — dropping %s",
                object_name,
            )
            return

        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            LOGGER.warning(
                "[LIDAR] fetch skipped (no cloud client): %s", object_name
            )
            return

        try:
            url = await self.hass.async_add_executor_job(
                cloud.get_interim_file_url, object_name
            )
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url failed for %s: %s",
                object_name, ex,
            )
            return
        if not url:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url returned None for %s",
                object_name,
            )
            return

        try:
            raw = await self.hass.async_add_executor_job(cloud.get_file, url)
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_file failed for %s: %s", object_name, ex
            )
            return
        if not raw:
            LOGGER.warning(
                "[LIDAR] get_file returned empty for %s", object_name
            )
            return

        archive = self.lidar_archive_for(active_id)

        entry = await self.hass.async_add_executor_job(
            archive.archive, object_name, now_unix, raw
        )
        if entry is None:
            LOGGER.debug(
                "[LIDAR] dedup hit (md5 already archived): %s", object_name
            )
            return

        LOGGER.info(
            "[LIDAR] archived %s (%d bytes) in map %d, total=%d",
            entry.filename, entry.size_bytes, active_id, archive.count,
        )
        # Update archived_lidar_count on the state for the count sensor.
        self.async_set_updated_data(
            dataclasses.replace(
                self.data, archived_lidar_count=archive.count
            )
        )

    async def _periodic_session_retry(self) -> None:
        """Periodic tick (every RETRY_INTERVAL_SECONDS) for session finalization.

        Calls ``finalize.decide(state, prev_task_state, now_unix)`` and
        dispatches the returned action.  All cloud I/O and disk I/O go through
        the executor per spec §3.
        """
        import time as _time
        now_unix = int(_time.time())
        action = _finalize_decide(self.data, self._prev_task_state, now_unix)
        if action == FinalizeAction.NOOP:
            return
        # v1.0.0a48: bumped to WARNING so the trail shows up in the
        # default HA log. Only fires on non-NOOP actions, which means
        # at most a handful per mow.
        LOGGER.warning(
            "[F5.6.1] _periodic_session_retry: action=%s "
            "task_state=%r prev=%r pending_oss=%r",
            action.name,
            self.data.task_state_code,
            self._prev_task_state,
            self.data.pending_session_object_name,
        )
        await self._dispatch_finalize_action(action, now_unix)

    async def _dispatch_finalize_action(
        self, action: FinalizeAction, now_unix: int
    ) -> None:
        """Dispatch a FinalizeAction from the finalize gate.

        BEGIN_SESSION / BEGIN_LEG: already handled by _on_state_update on every
            property push; nothing to do in the retry path.
        AWAIT_OSS_FETCH / FINALIZE_COMPLETE: fetch the cloud-summary JSON,
            parse it, archive it, and update MowerState.
        FINALIZE_INCOMPLETE: archive whatever live_map has with an "(incomplete)"
            suffix in the md5 field, then clear pending state.
        NOOP: do nothing.

        All blocking I/O runs in the executor per spec §3.
        """
        if action in (FinalizeAction.BEGIN_SESSION, FinalizeAction.BEGIN_LEG, FinalizeAction.NOOP):
            return

        if action in (FinalizeAction.AWAIT_OSS_FETCH, FinalizeAction.FINALIZE_COMPLETE):
            await self._do_oss_fetch(now_unix)
            return

        if action == FinalizeAction.FINALIZE_INCOMPLETE:
            await self._run_finalize_incomplete(now_unix)
            return

        LOGGER.warning("[F5.6.1] _dispatch_finalize_action: unhandled action=%s", action)

    async def _do_oss_fetch(self, now_unix: int) -> None:
        """Attempt to download and archive the cloud-summary JSON.

        1. call ``cloud_client.get_interim_file_url(object_name)`` to get a
           signed URL (blocking — executor).
        2. call ``cloud_client.get_file(url)`` to download the raw bytes
           (blocking — executor).
        3. Parse via ``protocol.session_summary.parse_session_summary``.
        4. Archive via ``SessionArchive.archive`` (blocking — executor).
        5. On success: clear pending fields, populate latest_session_*, call
           ``live_map.end_session()``.
        6. On failure: increment ``pending_session_attempt_count``.

        All blocking I/O goes through hass.async_add_executor_job per spec §3.
        """
        object_name = self.data.pending_session_object_name
        if not object_name:
            return

        # Guard: cloud client may not be ready during early boot.
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: cloud client not ready; "
                "object_name=%r — will retry next tick",
                object_name,
            )
            return

        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: fetching object_name=%r (attempt #%s)",
            object_name,
            (self.data.pending_session_attempt_count or 0) + 1,
        )

        # Increment attempt count and record last_attempt_unix before the fetch
        # so retries are tracked even if the fetch hangs or raises.
        new_count = (self.data.pending_session_attempt_count or 0) + 1
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_attempt_count=new_count,
                pending_session_last_attempt_unix=now_unix,
            )
        )

        # Step 1: get signed URL (blocking).
        try:
            signed_url: str | None = await self.hass.async_add_executor_job(
                self._cloud.get_interim_file_url, object_name
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_interim_file_url raised: %s", ex
            )
            return

        if not signed_url:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_interim_file_url returned None "
                "for object_name=%r",
                object_name,
            )
            return

        # Step 2: download raw bytes (blocking).
        try:
            raw_bytes: bytes | None = await self.hass.async_add_executor_job(
                self._cloud.get_file, signed_url
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_file raised: %s", ex
            )
            return

        if not raw_bytes:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_file returned None for url=%r",
                signed_url,
            )
            return

        # Step 3: parse JSON.
        try:
            raw_dict: dict[str, Any] = json.loads(raw_bytes)
        except (json.JSONDecodeError, ValueError) as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: JSON decode failed: %s — raw[:200]=%r",
                ex,
                raw_bytes[:200],
            )
            return

        # F6.4.1: schema-validate the JSON shape. Each novel key fires
        # [NOVEL_KEY/session_summary] WARNING once per process via the
        # registry's record_key gate.
        for key in _SESSION_SUMMARY_CHECK.diff_keys(raw_dict):
            if self.novel_registry.record_key("session_summary", key, now_unix):
                LOGGER.warning(
                    "%s key=%s — JSON shape drift, parser may need an update",
                    LOG_NOVEL_KEY_SESSION_SUMMARY, key,
                )

        # v1.0.0a54: inject the locally-tracked legs into the raw JSON
        # before archiving. Spot/zone session_summaries on g2408 lack
        # the cloud's `track`/`old_track` fields entirely (confirmed
        # against the user's 2026-04-30 spot 1 vs 2026-04-22 all-areas
        # JSONs); without this the replay picker draws an empty trail.
        # We have the actual path in live_map.legs at this point —
        # save it under our own key so the replay renderer can read it.
        if self.live_map.legs and any(self.live_map.legs):
            raw_dict["_local_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg in self.live_map.legs
                if leg
            ]

        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: parse_session_summary failed: %s", ex
            )
            return

        # Step 4: archive (blocking disk I/O).
        # Stamp the map_id so the replay picker can show [Map N] prefix.
        finalize_map_id = self._resolve_finalize_map_id()
        try:
            archived_entry: ArchivedSession | None = await self.hass.async_add_executor_job(
                self.session_archive.archive, summary, raw_dict, finalize_map_id
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_oss_fetch: archive raised: %s", ex)
            return

        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: archived session md5=%r area=%.1fm² "
            "duration=%dmin (already_exists=%s)",
            summary.md5,
            summary.area_mowed_m2,
            summary.duration_min,
            archived_entry is None,
        )
        # v1.0.0a50: when md5 dedup hits we silently land on an
        # already-archived entry — picker will not show a new row.
        # Surface object_name + parsed start/end so the cloud's
        # md5-recycling can be diagnosed and (if needed) the dedup
        # rule reworked to use object_name or start_ts instead.
        if archived_entry is None:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: md5 dedup hit — "
                "object_name=%r start_ts=%s end_ts=%s area=%.1f map_area=%s "
                "(picker will NOT show a new row; cloud reused md5)",
                object_name,
                summary.start_ts,
                summary.end_ts,
                summary.area_mowed_m2,
                summary.map_area_m2,
            )

        # Step 5: update MowerState — clear pending, populate latest_session_*,
        # increment archived_session_count, end the live_map session.
        # The in_progress.json file must be removed too; without that, the
        # picker keeps synthesizing a phantom "in progress" entry from disk
        # alongside the freshly-archived row (same bug v1.0.0a25 fixed for
        # the manual Finalize path; v1.0.0a42 closes the auto-finalize hole).
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.delete_in_progress
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: delete_in_progress raised: %s", ex
            )
        self._fire_mowing_ended(
            now_unix=now_unix,
            area_mowed_m2=summary.area_mowed_m2,
            duration_min=summary.duration_min,
            completed=True,
        )
        self.live_map.end_session()
        new_count = self.session_archive.count
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_object_name=None,
                pending_session_first_event_unix=None,
                pending_session_last_attempt_unix=None,
                pending_session_attempt_count=None,
                latest_session_unix_ts=summary.end_ts,
                latest_session_area_m2=summary.area_mowed_m2,
                latest_session_duration_min=summary.duration_min,
                # v1.0.0a22: pull total lawn area from the session
                # summary's `map_area` field. s2.66 (the MQTT push that
                # also carries this value) fires rarely on g2408, so
                # session-summary is the more reliable source of truth.
                # Only update when the summary has a non-zero map_area
                # (some incomplete entries set it to 0).
                total_lawn_area_m2=(
                    float(summary.map_area_m2)
                    if summary.map_area_m2 else self.data.total_lawn_area_m2
                ),
                archived_session_count=new_count,
                session_started_unix=None,
                session_track_segments=(),
            )
        )

    async def _run_finalize_incomplete(self, now_unix: int) -> None:
        """Archive whatever the live_map has as an "(incomplete)" session.

        Builds a minimal ArchivedSession directly from LiveMapState (no cloud
        summary), archives it, then clears pending state and ends the session.

        The archived entry has md5="(incomplete)" so callers can distinguish it
        from a cloud-fetched session.

        Called from two paths:
          - ``_dispatch_finalize_action(FinalizeAction.FINALIZE_INCOMPLETE)``
            (periodic retry gate, F5.6.1)
          - ``dispatch_action(MowerAction.FINALIZE_SESSION, ...)``
            (manual escape hatch, F5.10.1)
        """

        LOGGER.info(
            "[F5.6.1] _do_finalize_incomplete: giving up on cloud summary; "
            "archiving incomplete session (started_unix=%s, legs=%d)",
            self.live_map.started_unix,
            len(self.live_map.legs),
        )

        # Build a minimal ArchivedSession from whatever we have.
        # v1.0.0a24: if live_map is empty (session already ended but
        # in_progress.json wasn't promoted because the cloud summary
        # never arrived), fall back to the on-disk in_progress.json.
        # Without this, pressing the "Finalize stuck session" button
        # after a session ended would either silently no-op or write
        # a 0-area / 0-duration bogus entry.
        if self.live_map.is_active() or self.live_map.legs:
            start_ts = self.live_map.started_unix or now_unix
            end_ts = now_unix
            area = self.data.area_mowed_m2 or 0.0
        else:
            # Try the disk fallback.
            try:
                disk_data = await self.hass.async_add_executor_job(
                    self.session_archive.read_in_progress
                )
            except Exception as ex:
                LOGGER.warning("finalize_incomplete: read_in_progress failed: %s", ex)
                disk_data = None
            if disk_data:
                start_ts = int(disk_data.get("session_start_ts", 0)) or now_unix
                end_ts = int(disk_data.get("last_update_ts", now_unix)) or now_unix
                area = float(disk_data.get("area_mowed_m2", 0.0))
                LOGGER.info(
                    "finalize_incomplete: live_map empty; rebuilt from on-disk "
                    "in_progress.json (start_ts=%s, end_ts=%s, area=%.1f m²)",
                    start_ts, end_ts, area,
                )
            else:
                LOGGER.info(
                    "finalize_incomplete: no live session and no on-disk in_progress; "
                    "nothing to finalize — exiting"
                )
                return
        duration_min = max(0, (end_ts - start_ts) // 60)

        # Write a minimal JSON to disk so the session isn't silently lost.
        # Uses the same archive() mechanism but with a synthesised summary-like dict.
        incomplete_payload: dict[str, Any] = {
            "start": start_ts,
            "end": end_ts,
            "time": duration_min,
            "areas": area,
            "md5": "(incomplete)",
            "_note": "Cloud summary fetch expired; this entry was generated locally.",
        }

        # Build a duck-typed proxy that satisfies SessionArchive.archive(summary).
        # We use a SimpleNamespace because class-level attribute assignments can't
        # reference the enclosing function's local variables in Python.
        import types as _types
        proxy = _types.SimpleNamespace(
            md5="(incomplete)",
            end_ts=end_ts,
            start_ts=start_ts,
            duration_min=duration_min,
            area_mowed_m2=area,
            map_area_m2=0,
            mode=0,
            result=0,
            stop_reason=0,
        )

        try:
            await self.hass.async_add_executor_job(
                self.session_archive.archive, proxy, incomplete_payload,
                self._resolve_finalize_map_id()
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_finalize_incomplete: archive raised: %s", ex)

        # Without this, the synthesized in-progress entry keeps
        # reappearing in the picker after every finalize, leaving the
        # archived entry _and_ a phantom "in progress" row side-by-side.
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.delete_in_progress
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_finalize_incomplete: delete_in_progress raised: %s", ex)

        # Clear pending state, end live_map session.
        self._fire_mowing_ended(
            now_unix=now_unix,
            area_mowed_m2=area,
            duration_min=(
                int((now_unix - start_ts) / 60)
                if start_ts > 0
                else None
            ),
            completed=False,
        )
        self.live_map.end_session()
        new_count = self.session_archive.count
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_object_name=None,
                pending_session_first_event_unix=None,
                pending_session_last_attempt_unix=None,
                pending_session_attempt_count=None,
                archived_session_count=new_count,
                session_started_unix=None,
                session_track_segments=(),
            )
        )

    def register_event_entities(self, *, lifecycle: Any, alert: Any) -> None:
        """Called from event.py's async_setup_entry to wire the event
        entities the coordinator's dispatcher fires through.

        Stored as plain attributes (no weakref needed — entities live
        for the integration's lifetime). The lifecycle and alert
        parameters are the EventEntity instances created by
        event.py's setup call.
        """
        self._lifecycle_event = lifecycle
        self._alert_event = alert

    def _fire_lifecycle(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> None:
        """Race-safe dispatcher to the lifecycle event entity.

        Drops the call with a DEBUG log if the entity isn't yet wired
        (transient on startup before event.py's async_setup_entry has
        run). Delegates payload-cleaning to the entity's `trigger`
        wrapper.
        """
        ent = self._lifecycle_event
        if ent is None:
            LOGGER.debug(
                "[event] _fire_lifecycle(%r) dropped — entity not yet registered",
                event_type,
            )
            return
        ent.trigger(event_type, event_data)

    def _fire_mowing_ended(
        self,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
    ) -> None:
        """Fire the mowing_ended lifecycle event AND notify state machine.

        Called from both _do_oss_fetch (FINALIZE_COMPLETE, summary-driven)
        and _run_finalize_incomplete (FINALIZE_INCOMPLETE, best-effort).
        Delegates payload-shape consistency to one place.

        State-machine sync: the finalize gate can fire on a cloud-
        detected task_state transition (prev ∈ {0,4} → new ∈ {2,None})
        without a matching MQTT push. Without this hook the state
        machine stays IN_SESSION + MOWING indefinitely while the
        lifecycle event correctly reports the session ended.
        """
        self._fire_lifecycle(
            EVENT_TYPE_MOWING_ENDED,
            {
                "at_unix": int(now_unix),
                "area_mowed_m2": area_mowed_m2,
                "duration_min": duration_min,
                "completed": bool(completed),
            },
        )
        sm = getattr(self, "state_machine", None)
        if sm is not None:
            try:
                sm.end_session(now_unix=int(now_unix))
            except Exception:
                LOGGER.exception("state_machine.end_session failed")

    def _fire_alert(self, event_type: str, text: str, code: int, now_unix: int) -> None:
        """Race-safe dispatcher to the alert event entity.

        Called from _on_state_update when s2p2 (error_code) transitions to a
        known notification code. Drops the call with a DEBUG log if the alert
        entity is not yet wired (transient on startup before event.py's
        async_setup_entry has run). Also stashes the notification for
        sensor.last_notification.

        NOTE: _fire_alert is called from _on_state_update which is called from
        _apply (already on the event loop via call_soon_threadsafe). The
        sensor.last_notification entity will refresh when _apply subsequently
        calls async_set_updated_data — no extra call needed here.
        """
        self._last_notification = {
            "event_type": event_type,
            "text": text,
            "code": code,
            "fired_at": now_unix,
        }
        LOGGER.warning(
            "[F13] s2p2 alert: code=%d event_type=%r text=%r",
            code, event_type, text,
        )
        ent = self._alert_event
        if ent is None:
            LOGGER.debug(
                "[event] _fire_alert(%r) dropped — alert entity not yet registered",
                event_type,
            )
            return
        ent.trigger(event_type, {"text": text, "code": code, "source": "s2p2"})

    # -----------------------------------------------------------------------
    # F5.7.1 — In-progress restore on HA boot + 30s debounced persist
    # -----------------------------------------------------------------------

    async def _restore_in_progress(self) -> None:
        """Restore a live session from sessions/in_progress.json on HA boot.

        Called once from _async_update_data's first-refresh path, AFTER
        cloud auth but BEFORE _init_mqtt subscribes. Running before MQTT
        ensures broker-retained s2p56 pushes can't beat us into
        _on_state_update and call begin_session(now_unix), which would
        clobber the disk-restored legs and started_unix.

        Reads the in-progress entry via executor (blocking disk I/O). If a
        previous session was still active when HA shut down, repopulates
        LiveMapState.legs + started_unix and syncs MowerState fields
        (session_active=True, session_started_unix, session_track_segments).
        Also seeds _prev_task_state=0 so the finalize gate's session-end
        detection works on the next MQTT tick.

        Defensive guard: if for any reason live_map is already active when
        we get here, skip the restore so we don't stomp a freshly-started
        session. With the pre-MQTT ordering this branch is unreachable in
        normal operation, but the guard is kept as belt-and-suspenders.
        """
        data: dict | None = await self.hass.async_add_executor_job(
            self.session_archive.read_in_progress
        )
        if data is None:
            LOGGER.debug("[F5.7.1] _restore_in_progress: no in-progress file on disk")
            return

        # If the MQTT push for a new session already started live_map before
        # we got here, don't stomp the fresh session with the old disk data.
        if self.live_map.is_active():
            LOGGER.info(
                "[F5.7.1] _restore_in_progress: live_map already active "
                "(MQTT arrived before restore); skipping disk restore"
            )
            return

        try:
            started_unix = int(data.get("session_start_ts", 0) or 0)
        except (TypeError, ValueError):
            started_unix = 0

        if started_unix <= 0:
            LOGGER.warning(
                "[F5.7.1] _restore_in_progress: in-progress entry has no "
                "valid session_start_ts — discarding"
            )
            return

        # Restore legs: list[list[[x_m, y_m]]] on disk → list[list[tuple]]
        raw_legs = data.get("legs", [])
        legs: list[list[tuple[float, float]]] = []
        try:
            for raw_leg in raw_legs:
                legs.append([(float(pt[0]), float(pt[1])) for pt in raw_leg])
        except (TypeError, ValueError, IndexError) as ex:
            LOGGER.warning(
                "[F5.7.1] _restore_in_progress: legs decode error %s — "
                "starting with empty legs",
                ex,
            )
            legs = []

        LOGGER.info(
            "[F5.7.1] _restore_in_progress: restoring session started_unix=%d, "
            "legs=%d, total_points=%d",
            started_unix,
            len(legs),
            sum(len(leg) for leg in legs),
        )

        # Populate LiveMapState.
        self.live_map.started_unix = started_unix
        self.live_map.legs = legs if legs else [[]]
        self.live_map.last_telemetry_unix = int(data.get("last_update_ts", 0) or 0) or None

        # Seed state machine: an in_progress.json on disk proves a real
        # mow session was active. Without this, the state machine would
        # stay BETWEEN_SESSIONS until the next start event — which only
        # fires on the NEXT session, not the current one.
        sm = getattr(self, "state_machine", None)
        if sm is not None:
            try:
                import time as _time
                sm.seed_in_session(now_unix=int(_time.time()))
            except Exception:
                LOGGER.exception(
                    "state_machine.seed_in_session failed during restore"
                )

        # Seed _prev_task_state to "running" so the finalize gate's
        # session-end detection (prev ∈ {0,4} → new ∈ {2,None}) fires on
        # the next MQTT tick if the mower has actually gone idle while
        # HA was off. Without this, prev stays None at boot and the
        # idle-while-off case wouldn't trigger FINALIZE_INCOMPLETE.
        self._prev_task_state = 0

        # Sync MowerState.
        new_state = dataclasses.replace(
            self.data,
            session_started_unix=started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
        )
        self.async_set_updated_data(new_state)
        LOGGER.info("[F5.7.1] _restore_in_progress: MowerState updated (session restored from disk)")

    async def _persist_in_progress(self, _now: Any = None) -> None:
        """Write the current live_map state to sessions/in_progress.json.

        Scheduled every 30 seconds via async_track_time_interval.  Only
        writes when the session is active AND the dirty flag is set
        (i.e. at least one new point has been appended since the last write).
        This debounces the persist: if the mower is idle no new points arrive
        so no unnecessary disk I/O occurs.

        All blocking I/O goes through hass.async_add_executor_job per spec §3.
        """
        if not self.live_map.is_active():
            return
        if not self._live_map_dirty:
            LOGGER.debug("[F5.7.1] _persist_in_progress: live_map not dirty — skipping")
            return

        payload: dict[str, Any] = {
            "session_start_ts": self.live_map.started_unix,
            # legs: serialise as list[list[list[float]]] so JSON round-trips cleanly.
            "legs": [list(list(pt) for pt in leg) for leg in self.live_map.legs],
            "area_mowed_m2": self.data.area_mowed_m2 or 0.0,
            "map_area_m2": 0,
        }
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.write_in_progress, payload
            )
            # Clear the dirty flag only on successful write.
            self._live_map_dirty = False
            LOGGER.debug(
                "[F5.7.1] _persist_in_progress: wrote in_progress.json "
                "(started_unix=%s, legs=%d, points=%d)",
                self.live_map.started_unix,
                len(self.live_map.legs),
                self.live_map.total_points(),
            )
        except Exception as ex:
            # Non-fatal — next tick will retry.
            LOGGER.warning("[F5.7.1] _persist_in_progress: write failed: %s", ex)

    def handle_property_push(self, siid: int, piid: int, value: Any) -> None:
        """Apply a property push and notify entities. Called from the
        MQTT message callback (which runs on paho's background thread).

        Per spec §3 async-first commitment: state updates must reach
        HA's coordinator on the event loop. We hop the thread boundary
        via call_soon_threadsafe; the actual async_set_updated_data
        call lands on the event loop's next iteration.
        """
        import time as _time
        now = int(_time.time())

        # Novelty checks BEFORE the early-return: unmapped slots produce
        # `new_state == self.data` (no field touched), so they must be
        # logged here or they'd be silently dropped. Blob-payload slots
        # (s1.1, s1.4, s2.51) are dispatched in apply_property_to_state
        # via dedicated handlers; treat them as known to avoid the
        # per-tick novelty noise their varying payloads would generate.
        key = (int(siid), int(piid))
        if key in _SETTINGS_TRIPWIRE_SLOTS:
            # Firmware-saved-settings tripwire (s6p2 etc.) — schedule a
            # debounced cloud refresh so app/BT-side edits surface in HA
            # within seconds instead of waiting for the next 10-min poll.
            # Continues into the normal mapping path below: tripwire
            # slots also carry decoded state (e.g. s6p2 frame elements).
            self.hass.loop.call_soon_threadsafe(
                lambda k=key: self._schedule_cloud_refresh(
                    reason=f"s{k[0]}p{k[1]}"
                ),
            )
        if key in _SUPPRESSED_SLOTS:
            # s1p50 is the firmware's "something changed" empty-ping. For
            # multi-map, every map-swap fires it (confirmed 2026-05-07).
            # Treat it as a MAPL-repoll trigger so active-map detection has
            # sub-second latency instead of waiting for the next 10-min
            # CFG poll. Other s1p50 cases (zone-edits, maintenance saves)
            # benefit from the cheap re-poll too — MAPL is a ~100 ms RPC.
            if key == (1, 50):
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(self._refresh_mapl())
                )
            return  # echo of our own command; nothing to record
        if key in _BLOB_SLOTS:
            pass  # handled by dedicated blob applier; suppress novelty
        elif key in PROPERTY_MAPPING:
            if self.novel_registry.record_value(siid, piid, value, now):
                # First-time value for an already-mapped slot is informational
                # (e.g. s1p53 obstacle_flag toggling True for the first time
                # after install); the slot is recognised so there is nothing
                # for the user to action. Keep [NOVEL/property] at WARN since
                # that one signals a protocol gap.
                LOGGER.info(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        elif key in _INVENTORY.apk_known_never_seen:
            # The slot is in the inventory as APK-KNOWN but seen_on_wire:false.
            # Now that we've observed it, prompt the contributor to upgrade the
            # inventory row to seen_on_wire:true. Logged at INFO since the slot
            # is "known" in the data sense — the contributor action is to
            # update the row, not to file a new protocol gap.
            if self.novel_registry.saw_property(siid, piid):
                LOGGER.info(
                    "[PROTOCOL_NOVEL/apk-confirmed] siid=%s piid=%s value=%r "
                    "— APK-known slot now observed on wire; consider upgrading "
                    "inventory row to seen_on_wire:true",
                    siid, piid, value,
                )
        else:
            if self.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
                )

        # Catalog-miss check runs regardless of whether the slot is mapped or
        # apk-known: any property with a value_catalog in the inventory should
        # have its observed values cross-checked. Misses log at WARNING since
        # they likely indicate a protocol gap (firmware emitting a value the
        # catalog hasn't enumerated yet).
        catalog = _INVENTORY.value_catalogs.get(key)
        if catalog is not None and value not in catalog:
            if self.novel_registry.record_value(siid, piid, value, now):
                LOGGER.warning(
                    "[NOVEL/value/catalog-miss] siid=%s piid=%s value=%r "
                    "— not in catalog %r; please file a protocol gap",
                    siid, piid, value, sorted(catalog.keys()),
                )

        new_state = apply_property_to_state(self.data, siid, piid, value)
        if new_state == self.data:
            return

        # SM-mutator (R6): persist position across reboot. s1p4 is the only
        # slot that writes position_x_m/position_y_m on MowerState; route
        # those writes through the state machine so the StateSnapshot
        # cold-boot restore picks up the last-known pose.
        # position_north_m / position_east_m have no live write path on
        # g2408 today (only state_snapshot restore touches them), so pass
        # them as None and let handle_position no-op those fields.
        if (int(siid), int(piid)) == (1, 4):
            sm = getattr(self, "state_machine", None)
            if sm is not None and new_state.position_x_m is not None:
                try:
                    sm.handle_position(
                        x_m=new_state.position_x_m,
                        y_m=new_state.position_y_m,
                        north_m=None,
                        east_m=None,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_position failed")

        def _apply() -> None:
            # _on_state_update mutates live_map (legs, started_unix, etc.) and
            # updates _prev_task_state / _live_map_dirty.  It must run on the
            # event loop so those shared objects are never mutated from paho's
            # background thread while the loop is iterating them.
            hopped = self._on_state_update(new_state, now)
            # Surface the persistent_notification banner that mirrors the
            # Dreame app's modal popup. Fires on emergency_stop transition
            # (byte[3] bit 7), the load-bearing PIN-required latch.
            self._handle_emergency_stop_transition(
                self.data.emergency_stop, hopped.emergency_stop,
            )
            self.async_set_updated_data(hopped)

        self.hass.loop.call_soon_threadsafe(_apply)

    # -----------------------------------------------------------------------
    # Settings write surface (F4.5.1)
    # -----------------------------------------------------------------------

    #: CFG keys whose wire value is passed directly to set_cfg().
    #: All multi-field CFG keys (DND, LIT, BAT, WRP, LOW, ATA, REC) are
    #: also in this set — the entity layer builds the full array/dict value
    #: and passes it here; the coordinator relays verbatim.
    _CFG_SINGLE_KEYS: frozenset[str] = frozenset(
        {
            "CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC",
            # AMBIGUOUS_TOGGLE single-int keys (a62 — toggle-confirmed 2026-04-30):
            "FDP", "STUN", "AOP", "PROT",
            # AMBIGUOUS_4LIST 4-bool keys (a62 — slot-confirmed 2026-04-30):
            "MSG_ALERT", "VOICE",
        }
    )

    async def write_setting(
        self,
        cfg_key: str,
        new_full_value: Any,
        field_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Write a settings value to the mower via the CFG write path.

        The entity layer (F4.6.x) is responsible for constructing the full
        wire-level value (e.g. the complete DND list ``[enabled, start_min,
        end_min]``) and passing it as ``new_full_value``.  This method relays
        it to the right ``cloud_client`` method without interpreting the value.

        ``cfg_key`` must be one of the known CFG key strings (``CLS``, ``VOL``,
        ``LANG``, ``DND``, ``WRP``, ``LOW``, ``BAT``, ``LIT``, ``ATA``,
        ``REC``) or the special key ``PRE`` (full-array write via
        ``cloud_client.set_pre``).

        Optimistic state update (optional):
          If ``field_updates`` is provided it must be a ``{field_name: value}``
          dict whose keys are valid ``MowerState`` field names.  The state is
          updated optimistically before the cloud call and reverted if the cloud
          call fails.  When ``field_updates`` is ``None`` (the default) no
          optimistic update is applied — the entity layer handles its own
          optimistic state.

        Returns ``True`` on cloud success, ``False`` on failure.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_setting %s: cloud client not ready", cfg_key)
            return False

        if cfg_key not in self._CFG_SINGLE_KEYS and cfg_key != "PRE":
            LOGGER.warning("write_setting: unknown cfg_key %r", cfg_key)
            return False

        # Optimistic update — snapshot state and apply field_updates now.
        prior_state = self.data
        if field_updates:
            try:
                self.async_set_updated_data(
                    dataclasses.replace(self.data, **field_updates)
                )
            except TypeError as ex:
                LOGGER.warning(
                    "write_setting %s: invalid field_updates %r — %s; skipping optimistic update",
                    cfg_key, field_updates, ex,
                )
                # Don't revert — no update was applied; just proceed with the write.

        # Dispatch to the right cloud_client method.
        success = await self._dispatch_cfg_write(cfg_key, new_full_value)

        if not success:
            LOGGER.warning(
                "write_setting %s=%r: cloud write failed; reverting optimistic update",
                cfg_key, new_full_value,
            )
            if field_updates and self.data != prior_state:
                self.async_set_updated_data(prior_state)

        return success

    async def _dispatch_cfg_write(self, cfg_key: str, value: Any) -> bool:
        """Route a CFG write to the appropriate cloud_client method.

        All CFG single-key writes use ``cloud_client.set_cfg``.
        ``PRE`` uses ``cloud_client.set_pre`` (full-array write).

        Runs the blocking I/O in the executor per spec §3.
        """
        if cfg_key == "PRE":
            if not isinstance(value, list):
                LOGGER.warning(
                    "_dispatch_cfg_write PRE: expected list, got %r",
                    type(value).__name__,
                )
                return False
            return await self.hass.async_add_executor_job(
                self._cloud.set_pre, value
            )

        # All other CFG keys — single-key set via set_cfg().
        return await self.hass.async_add_executor_job(
            self._cloud.set_cfg, cfg_key, value
        )

    async def dispatch_action(
        self, action: MowerAction, parameters: dict[str, Any] | None = None
    ) -> None:
        """Dispatch a typed mower action.

        Looks up the action in ACTION_TABLE. local_only actions are handled
        internally (currently only FINALIZE_SESSION — its actual
        implementation lands in F5). Cloud actions go via the routed path
        (s2 aiid=50) since the direct (siid, aiid) call returns 80001 on
        g2408.

        For actions that have a ``routed_o`` opcode, uses
        ``cloud_client.routed_action(op, extra)`` — the working path on g2408.
        For actions that have only ``siid``/``aiid`` (no opcode), falls back
        to a direct ``cloud_client.action(siid, aiid)`` call.

        Errors and timeouts are logged but not raised — the integration
        keeps going. F4+ surfaces persistent failures via diagnostic
        sensors.
        """
        parameters = parameters or {}
        entry = ACTION_TABLE.get(action)
        if entry is None:
            LOGGER.warning("dispatch_action: unknown action %r", action)
            return

        if entry.get("local_only"):
            # FINALIZE_SESSION — integration-internal action; routes to the
            # finalize-incomplete path (F5.10.1).  Forces an "(incomplete)"
            # archive of whatever the live_map currently holds, clears
            # pending_session_* state, and calls live_map.end_session().
            # Safe to call even when no session is active (no-ops cleanly).
            if action == MowerAction.FINALIZE_SESSION:
                import time as _time
                LOGGER.info(
                    "dispatch_action: FINALIZE_SESSION — running finalize-incomplete path"
                )
                await self._run_finalize_incomplete(int(_time.time()))
            else:
                LOGGER.info(
                    "dispatch_action: local-only %s — no implementation yet", action.name
                )
            return

        # cfg_toggle_field path — reads the named MowerState field, computes
        # the toggled (boolean NOT) value, and calls write_setting.
        # Used for LOCK_BOT_TOGGLE → CFG key CLS.  This branch runs before
        # the cloud-client path; write_setting itself handles executor dispatch.
        cfg_toggle_field = entry.get("cfg_toggle_field")
        if cfg_toggle_field is not None:
            cfg_key = entry.get("cfg_key")
            if not cfg_key:
                LOGGER.warning(
                    "dispatch_action %s: cfg_toggle_field set but cfg_key missing — skipped",
                    action.name,
                )
                return
            current = getattr(self.data, cfg_toggle_field, None)
            toggled = not bool(current)
            LOGGER.info(
                "dispatch_action: %s toggle %s=%r → %r via write_setting(%r)",
                action.name, cfg_toggle_field, current, toggled, cfg_key,
            )
            await self.write_setting(
                cfg_key,
                int(toggled),  # CLS wire value is int {0, 1}
                field_updates={cfg_toggle_field: toggled},
            )
            return

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("dispatch_action: cloud client not ready; %s deferred", action.name)
            return

        routed_o = entry.get("routed_o")
        payload_fn = entry.get("payload_fn")

        # START_EDGE_MOW default-contour resolution. When the caller doesn't
        # specify ``contour_ids``, we want to edge every zone's outer
        # perimeter (entries in the cached map's contour table whose
        # second-int = 0). This matches the Dreame app's behaviour and
        # avoids the firmware's "edge every contour including merged
        # sub-zone seams" mode that drains the edge-mode budget on
        # invisible internal segments and triggers FTRTS.
        # See docs/research/g2408-protocol.md §4.6 (2026-05-05 finding).
        if action == MowerAction.START_EDGE_MOW and not parameters.get("contour_ids"):
            map_data = self._cached_maps_by_id.get(self._active_map_id)
            avail = getattr(map_data, "available_contour_ids", ()) if map_data else ()
            outer = [list(cid) for cid in avail if len(cid) == 2 and cid[1] == 0]
            if outer:
                parameters = {**parameters, "contour_ids": outer}
                LOGGER.info(
                    "dispatch_action: START_EDGE_MOW defaulting contour_ids to "
                    "all outer perimeters %s (from %d cached contours)",
                    outer, len(avail),
                )
            # else: fall through to _edge_mow_payload's [[1, 0]] last-resort
            # fallback (map data not loaded yet on this start).

        try:
            extra = payload_fn(parameters) if payload_fn else None
        except ValueError as ex:
            LOGGER.warning("dispatch_action %s: payload error: %s", action.name, ex)
            return

        LOGGER.info(
            "dispatch_action: %s via routed op=%s extra=%s",
            action.name, routed_o, extra,
        )

        try:
            if routed_o is not None:
                # Action opcode path — works on g2408 (cfg_action.call_action_op).
                await self.hass.async_add_executor_job(
                    self._cloud.routed_action, routed_o, extra
                )
            else:
                # Direct siid/aiid path — returns 80001 on g2408 for most actions,
                # but included for completeness (PAUSE/DOCK/STOP/etc. may succeed
                # via this path on some firmware or cloud configurations).
                siid = entry.get("siid")
                aiid = entry.get("aiid")
                if siid is None or aiid is None:
                    LOGGER.warning(
                        "dispatch_action: %s has no routed_o and no siid/aiid — skipped",
                        action.name,
                    )
                    return
                await self.hass.async_add_executor_job(
                    self._cloud.action, siid, aiid
                )
        except Exception as ex:
            LOGGER.warning("dispatch_action %s failed: %s", action.name, ex)

    # ------------------------------------------------------------------
    # Unified mowing-mode wrappers (used by DreameA2MowingModeSelect)
    # ------------------------------------------------------------------

    async def _ensure_active_map(self, map_id: int) -> None:
        """Switch to map_id via SET_ACTIVE_MAP (op=200) if it isn't already active.

        No-op when the requested map is already active or when
        _active_map_id is None (not yet polled — single-map devices never
        set it, so we fall through and let the firmware pick).  Logs a
        warning and continues on failure so the subsequent mow command
        still fires against whatever map is currently active.
        """
        current = self._active_map_id
        if current is None or current == map_id:
            return
        try:
            await self.dispatch_action(
                MowerAction.SET_ACTIVE_MAP, {"map_id": map_id}
            )
        except Exception as ex:
            LOGGER.warning(
                "start_mowing: SET_ACTIVE_MAP(map_id=%d) failed: %s — "
                "proceeding with current active map %s",
                map_id,
                ex,
                current,
            )

    async def start_mowing_all_areas(self, *, map_id: int) -> None:
        """Start all-areas mow on the given map (op=100).

        Switches the active map first if needed.  The all-areas TASK
        envelope doesn't carry a map_id itself; op=200 SET_ACTIVE_MAP
        must be sent first when the requested map isn't already active.
        """
        await self._ensure_active_map(map_id)
        await self.dispatch_action(MowerAction.START_MOWING, {})

    async def start_mowing_edge(self, *, map_id: int) -> None:
        """Start edge mow on the given map (op=101)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(MowerAction.START_EDGE_MOW, {})

    async def start_mowing_zone(self, *, map_id: int, zone_id: int) -> None:
        """Start zone mow for a specific zone on the given map (op=102)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_ZONE_MOW, {"zones": [zone_id]}
        )

    async def start_mowing_spot(self, *, map_id: int, spot_id: int) -> None:
        """Start spot mow for a specific spot on the given map (op=103)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_SPOT_MOW, {"spots": [spot_id]}
        )
