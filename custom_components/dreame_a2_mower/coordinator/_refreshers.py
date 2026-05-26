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

from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_EVENT_TYPES,
    S2P2_UNKNOWN_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
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

    # _poll_slow_properties REMOVED 2026-05-26.
    # It only fetched s6.3 ([cloud_connected, rssi_dbm]) and s1.5 (serial) via
    # the relay get_properties path, which 80001s when the device is asleep
    # (113 hourly :01 failures in production). Both targets are now redundant:
    #   • wifi_rssi_dbm comes from heartbeat byte[17] (~20 s cadence) directly.
    #   • cloud_connected is implied by MQTT being up (see coordinator
    #     `last_mqtt_unix` + binary_sensor.cloud_connected).
    #   • serial is provided by DEV (CFG.DEV.sn), which the integration's own
    #     comments flagged as authoritative.
    # See docs/research/app-api-surface-2026-05-25.md § 80001 for the full
    # write-up; nothing else called this method.

