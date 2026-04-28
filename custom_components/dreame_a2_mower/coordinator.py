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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .archive.session import ArchivedSession, SessionArchive
from .cloud_client import DreameA2CloudClient
from .mqtt_client import DreameA2MqttClient
from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from .observability import NovelObservationRegistry
from .live_map.finalize import FinalizeAction, RETRY_INTERVAL_SECONDS, decide as _finalize_decide
from .live_map.state import LiveMapState
from .mower.actions import ACTION_TABLE, MowerAction
from .mower.property_mapping import PROPERTY_MAPPING, resolve_field
from .mower.state import ChargingStatus, MowerState, State

from protocol import telemetry as _telemetry
from protocol import heartbeat as _heartbeat
from protocol import config_s2p51 as _s2p51
from protocol import session_summary as _session_summary


def _apply_s1p1_heartbeat(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.1 heartbeat blob and apply its flags to MowerState.

    Accepts either a base64-encoded string (the on-wire MQTT shape) or
    raw bytes/bytearray. Malformed blobs are dropped with a WARNING and
    the state is returned unchanged.
    """
    if isinstance(value, str):
        try:
            blob = base64.b64decode(value)
        except Exception:
            LOGGER.warning(
                "%s s1.1: value not base64-decodable: %r",
                LOG_NOVEL_PROPERTY,
                value[:32],
            )
            return state
    elif isinstance(value, (bytes, bytearray)):
        blob = bytes(value)
    else:
        LOGGER.warning(
            "%s s1.1: unexpected value type %s",
            LOG_NOVEL_PROPERTY,
            type(value).__name__,
        )
        return state

    try:
        decoded = _heartbeat.decode_s1p1(blob)
    except Exception as ex:
        LOGGER.warning("%s s1.1 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
        return state

    return dataclasses.replace(
        state,
        battery_temp_low=getattr(decoded, "battery_temp_low", None),
    )


def _apply_s1p4_telemetry(state: MowerState, value: Any) -> MowerState:
    """Decode an s1.4 telemetry blob and apply its fields to MowerState.

    Accepts either a base64-encoded string (the on-wire MQTT shape) or
    raw bytes/bytearray. Dispatches to the full decoder (decode_s1p4)
    for 33-byte frames; falls back to the position-only decoder
    (decode_s1p4_position) for 8-byte BEACON and 10-byte BUILDING frames.
    Malformed blobs are dropped with a WARNING and the state is returned
    unchanged.
    """
    if isinstance(value, str):
        try:
            blob = base64.b64decode(value)
        except Exception:
            LOGGER.warning(
                "%s s1.4: value not base64-decodable: %r",
                LOG_NOVEL_PROPERTY,
                value[:32],
            )
            return state
    elif isinstance(value, (bytes, bytearray)):
        blob = bytes(value)
    else:
        LOGGER.warning(
            "%s s1.4: unexpected value type %s",
            LOG_NOVEL_PROPERTY,
            type(value).__name__,
        )
        return state

    if len(blob) == _telemetry.FRAME_LENGTH:
        # Full 33-byte telemetry frame — all fields available.
        try:
            decoded = _telemetry.decode_s1p4(blob)
        except Exception as ex:
            LOGGER.warning("%s s1.4 decode failed: %s", LOG_NOVEL_PROPERTY, ex)
            return state
        return dataclasses.replace(
            state,
            position_x_m=decoded.x_m,
            position_y_m=decoded.y_m,
            mowing_phase=decoded.phase_raw,
            area_mowed_m2=decoded.area_mowed_m2,
            total_distance_m=decoded.distance_m,
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

    # AMBIGUOUS_TOGGLE and AMBIGUOUS_4LIST cannot be mapped to a single
    # MowerState field without external context (e.g. getCFG diff). Log at
    # DEBUG and leave state unchanged.
    LOGGER.debug("s2.51 unmapped setting=%s event=%r", setting, event)
    return state


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
        LOGGER.warning(
            "%s siid=%d piid=%d value=%r — unmapped property",
            LOG_NOVEL_PROPERTY,
            siid,
            piid,
            value,
        )
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

        # Session archive — persists completed sessions to disk (F5.4.1, F5.6.1).
        # <config>/dreame_a2_mower/sessions/ — matches legacy layout.
        sessions_dir = hass.config.path(DOMAIN, "sessions")
        self.session_archive = SessionArchive(Path(sessions_dir))

        # Base-map PNG cache — populated by _refresh_map every 6 hours.
        self.cached_map_png: bytes | None = None
        self._last_map_md5: str | None = None

        # Dirty flag for in-progress persistence (F5.7.1).
        # Set by _on_state_update after every append_point; cleared by
        # _persist_in_progress after a successful disk write.
        self._live_map_dirty: bool = False

        # Novel-observation registry (F6.2.1).
        # Tracks first-sightings of unknown protocol tokens so the watchdog
        # WARNING fires only once per token per process lifetime.
        self.novel_registry = NovelObservationRegistry()

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

            # Load session archive index from disk (non-blocking via executor).
            await self.hass.async_add_executor_job(self.session_archive.load_index)
            archived_count = self.session_archive.count
            if archived_count:
                self.data = dataclasses.replace(
                    self.data, archived_session_count=archived_count
                )

            # Restore any in-progress session from before the last HA shutdown.
            await self._restore_in_progress()

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

        # ---- CMS: blade / side-brush wear ----
        # CMS = [blade_min, side_brush_min, robot_min, aux_min]
        # Max-minutes per research doc: [6000, 30000, 3600, ?]
        # Percentage = elapsed_minutes / max_minutes * 100, clamped to 0..100.
        blades_life_pct: "float | None" = None
        side_brush_life_pct: "float | None" = None
        cms = cfg.get("CMS")
        if isinstance(cms, list) and len(cms) >= 2:
            try:
                blade_elapsed = float(cms[0])
                brush_elapsed = float(cms[1])
                blades_life_pct = max(0.0, min(100.0, (1.0 - blade_elapsed / 6000.0) * 100.0))
                side_brush_life_pct = max(0.0, min(100.0, (1.0 - brush_elapsed / 30000.0) * 100.0))
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

        new_state = dataclasses.replace(
            self.data,
            # CMS — wear percentages
            blades_life_pct=blades_life_pct,
            side_brush_life_pct=side_brush_life_pct,
            # total_cleaning_time_min, total_cleaned_area_m2, cleaning_count,
            # first_cleaning_date: not present in g2408 CFG (24-key schema).
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
        )
        if new_state != self.data:
            self.async_set_updated_data(new_state)

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

    async def _refresh_map(self) -> None:
        """Fetch MAP.* JSON via cloud, decode, render, cache.

        Fetches the cloud MAP.0..27 batch, decodes via
        map_decoder.parse_cloud_map, renders via map_render.render_base_map
        (when no live session is active) or map_render.render_with_trail
        (when live_map.is_active()).  Stores the resulting PNG in
        self.cached_map_png.  md5-deduped — same MAP payload does not
        trigger a re-render when there is no active trail.

        All blocking I/O and rendering run in the executor per spec §3.
        """
        if not hasattr(self, "_cloud"):
            return
        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return
        from .map_decoder import parse_cloud_map
        from .map_render import render_base_map, render_with_trail
        map_data = parse_cloud_map(cloud_response)
        if map_data is None:
            return

        if self.live_map.is_active():
            # Live session active — always re-render so the trail reflects
            # the latest telemetry.  md5 dedup is intentionally skipped here
            # because the trail changes even when the base map hasn't.
            legs = list(self.live_map.legs)
            png = await self.hass.async_add_executor_job(
                render_with_trail, map_data, legs
            )
            self.cached_map_png = png
            self._last_map_md5 = map_data.md5
            LOGGER.info(
                "[MAP] rendered trail PNG (%d bytes), md5=%s, legs=%d, points=%d",
                len(png) if png else 0,
                map_data.md5,
                len(legs),
                self.live_map.total_points(),
            )
        else:
            # No active session — base map only; md5-deduped.
            if map_data.md5 == self._last_map_md5:
                return  # md5-deduped — no re-render needed
            png = await self.hass.async_add_executor_job(render_base_map, map_data)
            self.cached_map_png = png
            self._last_map_md5 = map_data.md5
            LOGGER.info(
                "[MAP] rendered base map PNG (%d bytes), md5=%s",
                len(png) if png else 0,
                map_data.md5,
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
        from .map_decoder import parse_cloud_map
        from .map_render import render_with_trail

        LOGGER.info("[F5.9.1] replay_session: looking up md5=%s", session_md5)

        # --- 1. Find the ArchivedSession entry by md5 ---
        sessions = await self.hass.async_add_executor_job(
            self.session_archive.list_sessions
        )
        entry = next((s for s in sessions if s.md5 == session_md5), None)
        if entry is None:
            LOGGER.warning(
                "[F5.9.1] replay_session: no session with md5=%s in archive "
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
        from protocol import session_summary as _session_summary
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

        if not legs:
            LOGGER.warning(
                "[F5.9.1] replay_session: md5=%s has no track segments "
                "(boundary layer absent or empty track)", session_md5
            )
            # Fall through — render_with_trail handles empty legs gracefully
            # (produces same output as render_base_map).

        # --- 4. Fetch + parse the current cloud map for the base layer ---
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

        # --- 5. Render and cache ---
        png = await self.hass.async_add_executor_job(
            render_with_trail, map_data, legs
        )
        self.cached_map_png = png
        # Invalidate the md5 cache so a subsequent _refresh_map re-renders
        # even if the map payload hasn't changed.
        self._last_map_md5 = None
        LOGGER.info(
            "[F5.9.1] replay_session: rendered replay PNG (%d bytes) "
            "for md5=%s, legs=%d, total_points=%d",
            len(png) if png else 0,
            session_md5,
            len(legs),
            sum(len(leg) for leg in legs),
        )

    def _init_cloud(self) -> DreameA2CloudClient:
        """Authenticate with the Dreame cloud and pick up device info."""
        client = DreameA2CloudClient(
            username=self._username,
            password=self._password,
            country=self._country,
        )
        client.login()
        client.get_device_info()  # populates _did, _model, _host on client
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
        self._mqtt.connect(
            host=self._mqtt_host,
            port=self._mqtt_port,
            username=username,
            password=password,
            client_id=self._cloud.mqtt_client_id(),
        )
        topic = self._cloud.mqtt_topic()
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

        # Session-start: any transition into 1 (start_pending)
        if new_task_state == 1 and prev != 1:
            self.live_map.begin_session(now_unix)

        # Resume after recharge: 4 → 2 transition
        elif prev == 4 and new_task_state == 2:
            self.live_map.begin_leg()

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

        # Sync MowerState's session view from LiveMapState
        new_state = dataclasses.replace(
            new_state,
            session_active=self.live_map.is_active(),
            session_started_unix=self.live_map.started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
        )

        self._prev_task_state = new_task_state
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
        LOGGER.debug("[F5.6.1] _periodic_session_retry: action=%s", action.name)
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

        LOGGER.info(
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

        LOGGER.info(
            "[F5.6.1] _do_oss_fetch: archived session md5=%r area=%.1fm² "
            "duration=%dmin (already_exists=%s)",
            summary.md5,
            summary.area_mowed_m2,
            summary.duration_min,
            archived_entry is None,
        )

        # Step 5: update MowerState — clear pending, populate latest_session_*,
        # increment archived_session_count, end the live_map session.
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

        # Build a minimal ArchivedSession from what we have in-memory.
        start_ts = self.live_map.started_unix or 0
        end_ts = now_unix
        duration_min = max(0, (end_ts - start_ts) // 60)
        # Use area_mowed_m2 from MowerState if available (telemetry-derived).
        area = self.data.area_mowed_m2 or 0.0

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

        # Clear pending state, end live_map session.
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

    # -----------------------------------------------------------------------
    # F5.7.1 — In-progress restore on HA boot + 30s debounced persist
    # -----------------------------------------------------------------------

    async def _restore_in_progress(self) -> None:
        """Restore a live session from sessions/in_progress.json on HA boot.

        Called once from _async_update_data's first-refresh path, after
        cloud auth + MQTT connect + session_archive.load_index.

        Reads the in-progress entry via executor (blocking disk I/O).  If a
        previous session was still active when HA shut down, repopulates
        LiveMapState.legs + started_unix and syncs MowerState fields
        (session_active=True, session_started_unix, session_track_segments).

        Race-condition guard: if an s2p56=1 push arrives on MQTT before
        _restore_in_progress finishes (i.e. _on_state_update has already
        called begin_session for a *new* mow), we skip the restore so we
        don't clobber the freshly-started session.
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
        # logged here or they'd be silently dropped.
        if (int(siid), int(piid)) in PROPERTY_MAPPING:
            if self.novel_registry.record_value(siid, piid, value, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        else:
            if self.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
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
        {"CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC"}
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
