"""Coordinator for the Dreame A2 Mower integration.

Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
MowerState, and the dispatch from inbound MQTT pushes to state
updates. Entities subscribe to coordinator updates and read from
``coordinator.data`` (the MowerState).
"""
from __future__ import annotations

import base64
import dataclasses
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .archive.lidar import LidarArchive
from .archive.session import ArchivedSession, SessionArchive
from .cloud_client import DreameA2CloudClient
from .mqtt_client import DreameA2MqttClient
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
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOGGER,
)
from .observability import FreshnessTracker, NovelObservationRegistry
from .observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from .live_map.finalize import FinalizeAction, RETRY_INTERVAL_SECONDS, decide as _finalize_decide
from .live_map.state import LiveMapState
from .mower.actions import ACTION_TABLE, MowerAction
from .mower.property_mapping import PROPERTY_MAPPING, resolve_field
from .mower.state import ChargingStatus, MowerState, State

from .protocol import telemetry as _telemetry
from .protocol import heartbeat as _heartbeat
from .protocol import config_s2p51 as _s2p51
from .protocol import session_summary as _session_summary
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
from .inventory.loader import load_inventory

# Inventory snapshot computed once at import. Kept module-level for the
# fast-path lookup the legacy literal frozenset provided. Migration from
# hardcoded set: see docs/superpowers/specs/2026-05-06-axis3-runtime-harness-design.md.
_INVENTORY = load_inventory()
_SUPPRESSED_SLOTS: frozenset[tuple[int, int]] = _INVENTORY.suppressed_slots


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
        try:
            new_value: Any = State(int(value))
        except (ValueError, TypeError):
            LOGGER.warning(
                "%s s2.1 STATE: value=%r outside known State enum — dropping",
                LOG_NOVEL_PROPERTY,
                value,
            )
            return state
        return dataclasses.replace(state, state=new_value)

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
        # Layout: <config>/dreame_a2_mower/lidar/  (matches legacy).
        # F7.7.1: retention and max_bytes read from entry.options at startup.
        lidar_dir = hass.config.path(DOMAIN, "lidar")
        self.lidar_archive = LidarArchive(
            Path(lidar_dir),
            retention=int(
                opts.get(CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP)
            ),
            max_bytes=int(
                opts.get(CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB)
            ) * 1024 * 1024,
        )
        self._last_lidar_object_name: str | None = None

        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        self._cached_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
        # Active map (from MAPL polling). None until first MAPL response.
        self._active_map_id: int | None = None
        # Currently rendered map (defaults to active; transient override
        # during replay-session pick to the session's map_id).
        self._render_map_id: int | None = None
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

    @property
    def cached_map_png(self) -> bytes | None:
        """Backwards-compat: PNG of the currently-rendered map.

        Reads `_cached_pngs_by_id[_render_map_id]` (or `_active_map_id`
        when render isn't overridden). Returns None when no map is
        cached or the active/render id isn't in the cache yet.
        """
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            # Fall back to lowest-numbered map_id when we have any cached
            # but haven't seen MAPL yet.
            if self._cached_pngs_by_id:
                target = min(self._cached_pngs_by_id.keys())
            else:
                return None
        return self._cached_pngs_by_id.get(target)

    @cached_map_png.setter
    def cached_map_png(self, png: bytes | None) -> None:
        """Backwards-compat setter: writes to the currently-rendered map's slot.

        Used by replay_session and _rerender_live_trail. The target id
        is `_render_map_id` (replay) or `_active_map_id` (live).
        """
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = min(self._cached_pngs_by_id.keys()) if self._cached_pngs_by_id else 0
        if png is None:
            self._cached_pngs_by_id.pop(target, None)
        else:
            self._cached_pngs_by_id[target] = png

    @property
    def _cached_map_data(self) -> Any:
        """Backwards-compat: MapData of the currently-rendered map."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            if self._cached_maps_by_id:
                target = min(self._cached_maps_by_id.keys())
            else:
                return None
        return self._cached_maps_by_id.get(target)

    @_cached_map_data.setter
    def _cached_map_data(self, value: Any) -> None:
        """Backwards-compat setter: writes to the currently-rendered map's slot."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = getattr(value, "map_id", 0) if value is not None else 0
        if value is None:
            self._cached_maps_by_id.pop(target, None)
        else:
            self._cached_maps_by_id[target] = value

    @property
    def _last_map_md5(self) -> str | None:
        """Backwards-compat: md5 of the currently-rendered map."""
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            if self._last_map_md5_by_id:
                target = min(self._last_map_md5_by_id.keys())
            else:
                return None
        return self._last_map_md5_by_id.get(target)

    @_last_map_md5.setter
    def _last_map_md5(self, value: str | None) -> None:
        target = self._render_map_id if self._render_map_id is not None else self._active_map_id
        if target is None:
            target = min(self._last_map_md5_by_id.keys()) if self._last_map_md5_by_id else 0
        if value is None:
            self._last_map_md5_by_id.pop(target, None)
        else:
            self._last_map_md5_by_id[target] = value

    async def _async_update_data(self) -> MowerState:
        """First-refresh path — auth, device discovery, MQTT subscribe.

        Subsequent refreshes are push-driven via the MQTT callback;
        this method only re-runs if the user manually refreshes the
        integration.
        """
        if not hasattr(self, "_cloud"):
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
            await self._refresh_map()

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
                # v1.0.0a42: aggregate lifetime stats from the local
                # archive at boot. Legacy fetched these from cloud
                # slots s12.1-12.4 but on g2408 that path returns
                # 80001 — the legacy itself fell back to local
                # aggregation (dreame/device.py:2970+). We have the
                # same archive, so do the same. Fields filled here:
                #   - mowing_count
                #   - total_mowing_time_min
                #   - total_mowed_area_m2
                #   - first_mowing_date (unix ts)
                count_total = 0
                time_total = 0
                area_total = 0.0
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
                        # Lifetime aggregates — exclude in-progress entries
                        # so a stuck session doesn't double-count once it
                        # eventually finalizes.
                        if not getattr(s, "still_running", False):
                            count_total += 1
                            time_total += int(getattr(s, "duration_min", 0) or 0)
                            area_total += float(getattr(s, "area_mowed_m2", 0.0) or 0.0)
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
                    seed_updates["latest_session_md5"] = seed_latest_md5
                    seed_updates["latest_session_unix_ts"] = seed_latest_unix
                    seed_updates["latest_session_area_m2"] = seed_latest_area
                    seed_updates["latest_session_duration_min"] = seed_latest_duration
                # MIHIS (cloud-authoritative lifetime totals) ran a few
                # lines above; if it landed it has already populated
                # these fields with the app's exact numbers. Don't
                # clobber them with the local-archive sums — only seed
                # the fields that MIHIS didn't fill (offline boot,
                # first install before any cloud refresh, etc.).
                if count_total > 0 and self.data.mowing_count is None:
                    seed_updates["mowing_count"] = count_total
                if count_total > 0 and self.data.total_mowing_time_min is None:
                    seed_updates["total_mowing_time_min"] = time_total
                if count_total > 0 and self.data.total_mowed_area_m2 is None:
                    seed_updates["total_mowed_area_m2"] = area_total
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

            # F7.2.2: same pattern for the LiDAR archive.
            await self.hass.async_add_executor_job(self.lidar_archive.load_index)
            archived_lidar = self.lidar_archive.count
            if archived_lidar:
                self.data = dataclasses.replace(
                    self.data, archived_lidar_count=archived_lidar
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

        return self.data

    def _apply_mapl(self, mapl: Any) -> None:
        """Update _active_map_id from a MAPL response.

        MAPL is a list of rows, each row is `[map_id, is_active, ?, ?, ?]`.
        Sets `_active_map_id` to the row whose col 1 == 1. If no row
        matches (transient), keep the previous value. Bad payloads are
        ignored.
        """
        if not isinstance(mapl, list):
            return
        for row in mapl:
            if not isinstance(row, list) or len(row) < 2:
                continue
            try:
                if int(row[1]) == 1:
                    self._active_map_id = int(row[0])
                    return
            except (TypeError, ValueError):
                continue
        # No row matched; keep previous _active_map_id (do nothing).

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
        blades_life_pct: "float | None" = None
        cleaning_brush_life_pct: "float | None" = None
        robot_maintenance_life_pct: "float | None" = None
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
        child_lock_enabled: "bool | None" = None
        cls_raw = cfg.get("CLS")
        if cls_raw is not None:
            try:
                child_lock_enabled = bool(int(cls_raw))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] CLS decode error: %s — cls=%r", ex, cls_raw)

        # ---- VOL: voice volume ----
        # CFG.VOL = int 0..100. Confirmed on g2408.
        volume_pct: "int | None" = None
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
        language_code: "str | None" = None
        language_text_idx: "int | None" = None
        language_voice_idx: "int | None" = None
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
        dnd_enabled: "bool | None" = None
        dnd_start_min: "int | None" = None
        dnd_end_min: "int | None" = None
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
        pre_zone_id: "int | None" = None
        pre_mowing_efficiency: "int | None" = None
        pre_mowing_height_mm: "int | None" = None  # only set if PRE has >=3 elements
        pre_edgemaster: "bool | None" = None  # only set if PRE has >=9 elements
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
        rain_protection_enabled: "bool | None" = None
        rain_protection_resume_hours: "int | None" = None
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
        low_speed_at_night_enabled: "bool | None" = None
        low_speed_at_night_start_min: "int | None" = None
        low_speed_at_night_end_min: "int | None" = None
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
        auto_recharge_battery_pct: "int | None" = None
        resume_battery_pct: "int | None" = None
        custom_charging_enabled: "bool | None" = None
        charging_start_min: "int | None" = None
        charging_end_min: "int | None" = None
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
        led_period_enabled: "bool | None" = None
        led_in_standby: "bool | None" = None
        led_in_working: "bool | None" = None
        led_in_charging: "bool | None" = None
        led_in_error: "bool | None" = None
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
        anti_theft_lift_alarm: "bool | None" = None
        anti_theft_offmap_alarm: "bool | None" = None
        anti_theft_realtime_location: "bool | None" = None
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
        human_presence_alert_enabled: "bool | None" = None
        human_presence_alert_sensitivity: "int | None" = None
        rec_raw = cfg.get("REC")
        if isinstance(rec_raw, list) and len(rec_raw) >= 2:
            try:
                human_presence_alert_enabled = bool(int(rec_raw[0]))
                human_presence_alert_sensitivity = int(rec_raw[1])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] REC decode error: %s — rec=%r", ex, rec_raw)


        # ---- AMBIGUOUS_TOGGLE shape members (single-int CFG keys) ----
        # All four use CFG int {0, 1}. Confirmed 2026-04-30 via toggle tests;
        # these CFG keys were previously read but never plumbed to MowerState.
        def _cfg_bool(name: str) -> "bool | None":
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
        msg_alert_anomaly: "bool | None" = None
        msg_alert_error: "bool | None" = None
        msg_alert_task: "bool | None" = None
        msg_alert_consumables: "bool | None" = None
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
        voice_regular_notification: "bool | None" = None
        voice_work_status: "bool | None" = None
        voice_special_status: "bool | None" = None
        voice_error_status: "bool | None" = None
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

        def _i(name: str) -> "int | None":
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
        if connect_status is not None:
            updates["mower_in_dock"] = bool(connect_status)
        if in_region is not None:
            updates["dock_in_lawn_region"] = bool(in_region)
        for src, dst in (
            ("x", "dock_x_mm"),
            ("y", "dock_y_mm"),
            ("yaw", "dock_yaw"),
            ("near_x", "dock_near_x"),
            ("near_y", "dock_near_y"),
            ("near_yaw", "dock_near_yaw"),
            ("path_connect", "dock_path_connect"),
        ):
            v = _i(src)
            if v is not None:
                updates[dst] = v

        if not updates:
            return

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

    def _compute_target_area_m2(self, state: MowerState) -> "float | None":
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
        live_task_area = state.task_total_area_m2
        if (
            state.session_active
            and live_task_area is not None
            and live_task_area > 0
        ):
            return float(live_task_area)

        map_data = getattr(self, "_cached_map_data", None)
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
            except Exception as ex:  # noqa: BLE001
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
        except Exception as ex:  # noqa: BLE001
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

    async def _refresh_map(self) -> None:
        """Fetch the cloud MAP.* batch, parse all maps, and re-render
        per-map base-map PNGs. Updates `_cached_maps_by_id` and
        `_cached_pngs_by_id`.

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
        from .map_render import render_base_map, render_with_trail

        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return

        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _refresh_map: parse_cloud_maps returned empty")
            return

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

        # Render per-map PNGs; apply trail only to the active map.
        # When _active_map_id is None (not yet polled), treat any map as
        # the active one so the trail renders on the only/first map.
        active_id = self._active_map_id
        live_active = self.live_map.is_active()
        for map_id, map_data in parsed_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            # A map is "active" if it matches the known active id, OR if no
            # active id is set yet (single-map / not-yet-polled fallback).
            is_active = active_id is None or map_id == active_id

            if is_active and live_active:
                # Live session on this map — always re-render; trail
                # changes even when the base map md5 is unchanged.
                legs = list(self.live_map.legs)
                mower_pos = self._current_mower_position()
                png = await self.hass.async_add_executor_job(
                    render_with_trail, map_data, legs, None, mower_pos, self._current_mower_heading()
                )
                if png:
                    self._cached_pngs_by_id[map_id] = png
                    self._last_map_md5_by_id[map_id] = map_data.md5
                LOGGER.info(
                    "[MAP] map_id=%s rendered trail PNG (%d bytes), md5=%s, legs=%d, points=%d",
                    map_id,
                    len(png) if png else 0,
                    map_data.md5,
                    len(legs),
                    self.live_map.total_points(),
                )
            else:
                # No active trail on this map — base map only; md5-deduped.
                if prev_md5 == map_data.md5:
                    LOGGER.debug(
                        "[MAP] map_id=%s md5 unchanged (%s) — skipping re-render",
                        map_id, map_data.md5,
                    )
                    continue
                png = await self.hass.async_add_executor_job(render_base_map, map_data)
                if png:
                    self._cached_pngs_by_id[map_id] = png
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

    def _current_mower_position(self) -> "tuple[float, float] | None":
        """Return the current mower (x_m, y_m) cloud-frame position, or
        None when either coordinate is unset. Used by the live-map
        renders to draw the position marker."""
        x = self.data.position_x_m
        y = self.data.position_y_m
        if x is None or y is None:
            return None
        return (float(x), float(y))

    def _current_mower_heading(self) -> "float | None":
        """Return the mower's current heading in degrees, or None."""
        h = self.data.position_heading_deg
        return float(h) if h is not None else None

    async def _rerender_live_trail(
        self,
        position: "tuple[float, float] | None" = None,
        heading: "float | None" = None,
    ) -> None:
        """Re-render the cached map with the current live trail.

        v1.0.0a19: position + heading are passed explicitly by the
        _on_state_update hook so the icon reflects the SAME push that
        just appended to live_map. Without this, reading self.data
        inside the scheduled task could see either the old or new
        state depending on whether async_set_updated_data has run yet,
        and the icon would lag behind the trail.
        """
        map_data = getattr(self, "_cached_map_data", None)
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
        self.cached_map_png = png
        LOGGER.debug(
            "[MAP] live trail re-render: legs=%d points=%d bytes=%d pos=%s hdg=%s",
            len(legs), self.live_map.total_points(), len(png) if png else 0,
            position, heading,
        )

    async def replay_session(self, session_md5: str) -> None:
        """Render an archived session's path into cached_map_png.

        Look up the session by md5 in session_archive, parse its track
        segments via parse_session_summary, then render via
        render_with_trail using the archived legs.  Updates
        cached_map_png in-place — the camera entity serves whatever is
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
        from .map_render import render_with_trail

        replay_start_unix = _time.monotonic()
        LOGGER.info("[F5.9.1] replay_session: looking up md5=%s", session_md5)

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
                "[F5.9.1] replay_session: no session with key=%s in archive "
                "(%d sessions total)", session_md5, len(sessions)
            )
            return

        # --- 2. Load the raw JSON from disk ---
        raw_dict = await self.hass.async_add_executor_job(
            self.session_archive.load, entry
        )
        if raw_dict is None:
            LOGGER.warning(
                "[F5.9.1] replay_session: failed to load raw JSON for md5=%s "
                "(filename=%s)", session_md5, entry.filename
            )
            return

        # --- 3. Parse the session summary to extract track_segments ---
        from .protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.9.1] replay_session: parse_session_summary failed for "
                "md5=%s: %s", session_md5, ex
            )
            return

        # track_segments is tuple[tuple[tuple[float,float],...],...]
        # render_with_trail expects list[list[tuple[float,float]]]
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
                "[F5.9.1] replay_session: key=%s has no track segments "
                "(no cloud track + no _local_legs fallback)", session_md5
            )
            # Fall through — render_with_trail handles empty legs gracefully
            # (produces same output as render_base_map).

        # --- 4. Use the cached MapData. The periodic _refresh_map runs at
        # boot + every 6h, so the cache is almost always populated by the
        # time the user clicks a replay. Only fall back to a fresh
        # cloud.fetch_map when the cache is empty — that path can take
        # 30 s on g2408 because the same cloud HTTP API often 80001s.
        # v1.0.0a52: was unconditionally fetching, making every picker
        # change ~30 s slow. ---
        map_data = getattr(self, "_cached_map_data", None)
        if map_data is None:
            if not hasattr(self, "_cloud"):
                LOGGER.warning(
                    "[F5.9.1] replay_session: cloud client not ready yet; "
                    "cannot fetch map for replay"
                )
                return
            cloud_response = await self.hass.async_add_executor_job(
                self._cloud.fetch_map
            )
            if cloud_response is None:
                LOGGER.warning(
                    "[F5.9.1] replay_session: fetch_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            map_data = parse_cloud_map(cloud_response)
            if map_data is None:
                LOGGER.warning(
                    "[F5.9.1] replay_session: parse_cloud_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            # Hydrate the cache so subsequent replays don't re-fetch either.
            self._cached_map_data = map_data

        # --- 5. Render and cache ---
        # async_add_executor_job only forwards positional args, so use
        # functools.partial to bake obstacle_polygons_m in as a kwarg.
        from functools import partial

        png = await self.hass.async_add_executor_job(
            partial(
                render_with_trail,
                map_data,
                legs,
                obstacle_polygons_m=obstacle_polygons_m,
            )
        )
        self.cached_map_png = png
        # Invalidate the md5 cache so a subsequent _refresh_map re-renders
        # even if the map payload hasn't changed.
        self._last_map_md5 = None
        # 2026-05-05 picker fix: bump the replay counter so the camera
        # entity rotates its access_token on every replay-session pick,
        # even when two sequential replays produce byte-identical PNGs.
        # Without this, the HA frontend caches the entity_picture URL
        # and serves the previous replay's image. The byte-equality
        # guard in `camera._handle_coordinator_update` is correct for
        # live-trail re-renders (which DO change byte-for-byte) but
        # misses replays-of-the-same-or-similar-archive. See
        # docs/TODO.md "Replay-session picker — inconsistent rendering".
        self._replay_counter = getattr(self, "_replay_counter", 0) + 1
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        LOGGER.warning(
            "[F5.9.1] replay_session: rendered replay PNG (%d bytes) "
            "for md5=%s, legs=%d, total_points=%d, elapsed=%dms",
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
            session_active=self.live_map.is_active(),
            session_started_unix=self.live_map.started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
            session_distance_m=(
                self.live_map.total_distance_m() if self.live_map.is_active() else None
            ),
            target_area_m2=self._compute_target_area_m2(new_state),
        )

        self._prev_task_state = new_task_state

        # Dock arrival/departure rising/falling edges. Explicit `is True` /
        # `is False` so the boot-time None state doesn't fire a spurious
        # arrived/departed event.
        if (
            self._prev_in_dock is False
            and new_state.mower_in_dock is True
        ):
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_ARRIVED, {"at_unix": int(now_unix)}
            )
        elif (
            self._prev_in_dock is True
            and new_state.mower_in_dock is False
        ):
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_DEPARTED, {"at_unix": int(now_unix)}
            )
        self._prev_in_dock = new_state.mower_in_dock

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

        if self.lidar_archive is None:
            LOGGER.debug("[LIDAR] archive disabled, skipping write")
            return

        entry = await self.hass.async_add_executor_job(
            self.lidar_archive.archive, object_name, now_unix, raw
        )
        if entry is None:
            LOGGER.debug(
                "[LIDAR] dedup hit (md5 already archived): %s", object_name
            )
            return

        LOGGER.info(
            "[LIDAR] archived %s (%d bytes), total=%d",
            entry.filename, entry.size_bytes, self.lidar_archive.count,
        )
        # Update archived_lidar_count on the state for the count sensor.
        self.async_set_updated_data(
            dataclasses.replace(
                self.data, archived_lidar_count=self.lidar_archive.count
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
        try:
            archived_entry: ArchivedSession | None = await self.hass.async_add_executor_job(
                self.session_archive.archive, summary, raw_dict
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
                latest_session_md5=summary.md5,
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
                session_active=False,
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
        import time as _time

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
                self.session_archive.archive, proxy, incomplete_payload
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
                session_active=False,
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
        """Fire the mowing_ended lifecycle event.

        Called from both _do_oss_fetch (FINALIZE_COMPLETE, summary-driven)
        and _run_finalize_incomplete (FINALIZE_INCOMPLETE, best-effort).
        Delegates payload-shape consistency to one place.
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

        # Seed _prev_task_state to "running" so the finalize gate's
        # session-end detection (prev ∈ {0,4} → new ∈ {2,None}) fires on
        # the next MQTT tick if the mower has actually gone idle while
        # HA was off. Without this, prev stays None at boot and the
        # idle-while-off case wouldn't trigger FINALIZE_INCOMPLETE.
        self._prev_task_state = 0

        # Sync MowerState.
        new_state = dataclasses.replace(
            self.data,
            session_active=True,
            session_started_unix=started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
        )
        self.async_set_updated_data(new_state)
        LOGGER.info("[F5.7.1] _restore_in_progress: MowerState updated (session_active=True)")

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
        if key in _SUPPRESSED_SLOTS:
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
        field_updates: "dict[str, Any] | None" = None,
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
                LOGGER.warning("_dispatch_cfg_write PRE: expected list, got %r", type(value).__name__)
                return False
            return await self.hass.async_add_executor_job(
                self._cloud.set_pre, value
            )

        # All other CFG keys — single-key set via set_cfg().
        return await self.hass.async_add_executor_job(
            self._cloud.set_cfg, cfg_key, value
        )

    async def dispatch_action(
        self, action: MowerAction, parameters: "dict[str, Any] | None" = None
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
            map_data = getattr(self, "_cached_map_data", None)
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
