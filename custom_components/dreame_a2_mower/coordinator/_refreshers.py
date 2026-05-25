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
    S2P2_NOTIFICATION_MAP,
    S2P2_NOVEL_EVENT_TYPE,
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

