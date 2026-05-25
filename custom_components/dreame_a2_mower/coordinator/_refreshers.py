"""refreshers mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_NOTIFICATION_MAP,
    S2P2_NOVEL_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
    _consumable_pct_remaining,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _RefreshersMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

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
        human_presence_scenario_standby: bool | None = None
        human_presence_scenario_mowing: bool | None = None
        human_presence_scenario_recharge: bool | None = None
        human_presence_scenario_patrol: bool | None = None
        human_presence_alert_voice: bool | None = None
        photo_consent: bool | None = None
        human_presence_alert_push_interval_min: int | None = None
        rec_raw = cfg.get("REC")
        if isinstance(rec_raw, list) and len(rec_raw) >= 2:
            try:
                human_presence_alert_enabled = bool(int(rec_raw[0]))
                human_presence_alert_sensitivity = int(rec_raw[1])
                if len(rec_raw) >= 9:
                    human_presence_scenario_standby = bool(int(rec_raw[2]))
                    human_presence_scenario_mowing = bool(int(rec_raw[3]))
                    human_presence_scenario_recharge = bool(int(rec_raw[4]))
                    human_presence_scenario_patrol = bool(int(rec_raw[5]))
                    human_presence_alert_voice = bool(int(rec_raw[6]))
                    photo_consent = bool(int(rec_raw[7]))
                    human_presence_alert_push_interval_min = int(rec_raw[8])
                elif len(rec_raw) >= 8:
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
            human_presence_scenario_standby=human_presence_scenario_standby,
            human_presence_scenario_mowing=human_presence_scenario_mowing,
            human_presence_scenario_recharge=human_presence_scenario_recharge,
            human_presence_scenario_patrol=human_presence_scenario_patrol,
            human_presence_alert_voice=human_presence_alert_voice,
            human_presence_alert_push_interval_min=human_presence_alert_push_interval_min,
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

