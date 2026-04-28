"""Coordinator for the Dreame A2 Mower integration.

Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
MowerState, and the dispatch from inbound MQTT pushes to state
updates. Entities subscribe to coordinator updates and read from
``coordinator.data`` (the MowerState).
"""
from __future__ import annotations

import base64
import dataclasses
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cloud_client import DreameA2CloudClient
from .mqtt_client import DreameA2MqttClient
from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    LOG_NOVEL_PROPERTY,
    LOGGER,
)
from .mower.actions import ACTION_TABLE, MowerAction
from .mower.property_mapping import resolve_field
from .mower.state import ChargingStatus, MowerState, State

from protocol import telemetry as _telemetry
from protocol import heartbeat as _heartbeat


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

        # Base-map PNG cache — populated by _refresh_map every 6 hours.
        self.cached_map_png: bytes | None = None
        self._last_map_md5: str | None = None

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

        return self.data

    async def _refresh_cfg(self) -> None:
        """Fetch CFG via routed-action and update MowerState.

        Extracts blade / side-brush wear percentages from CFG.CMS.
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

        new_state = dataclasses.replace(
            self.data,
            blades_life_pct=blades_life_pct,
            side_brush_life_pct=side_brush_life_pct,
            # total_cleaning_time_min, total_cleaned_area_m2, cleaning_count,
            # first_cleaning_date: not present in g2408 CFG (24-key schema).
            # Leave unchanged (None) until a source is identified.
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
        map_decoder.parse_cloud_map, renders via map_render.render_base_map,
        and stores the resulting PNG in self.cached_map_png.  md5-deduped —
        same MAP payload does not trigger a re-render.

        All blocking I/O and rendering run in the executor per spec §3.
        """
        if not hasattr(self, "_cloud"):
            return
        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return
        from .map_decoder import parse_cloud_map
        from .map_render import render_base_map
        map_data = parse_cloud_map(cloud_response)
        if map_data is None:
            return
        if map_data.md5 == self._last_map_md5:
            return  # md5-deduped — no re-render needed
        png = await self.hass.async_add_executor_job(render_base_map, map_data)
        self.cached_map_png = png
        self._last_map_md5 = map_data.md5
        LOGGER.info("[MAP] rendered base map PNG (%d bytes), md5=%s", len(png) if png else 0, map_data.md5)

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

        Each message is a properties_changed batch with {"params": [
            {"siid": ..., "piid": ..., "value": ...},
            ...
        ]}.
        """
        method = payload.get("method")
        if method != "properties_changed":
            # F1: only properties_changed. F5 adds event_occured handling.
            return
        params = payload.get("params") or []
        for p in params:
            if "siid" in p and "piid" in p:
                self.handle_property_push(
                    siid=int(p["siid"]),
                    piid=int(p["piid"]),
                    value=p.get("value"),
                )

    def handle_property_push(self, siid: int, piid: int, value: Any) -> None:
        """Apply a property push and notify entities. Called from the
        MQTT message callback (which runs on paho's background thread).

        Per spec §3 async-first commitment: state updates must reach
        HA's coordinator on the event loop. We hop the thread boundary
        via call_soon_threadsafe; the actual async_set_updated_data
        call lands on the event loop's next iteration.
        """
        new_state = apply_property_to_state(self.data, siid, piid, value)
        if new_state != self.data:
            self.hass.loop.call_soon_threadsafe(
                self.async_set_updated_data, new_state
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
            # FINALIZE_SESSION — F5 wires the actual implementation. For
            # F3, log so the user knows the service was received.
            LOGGER.info("dispatch_action: local-only %s; F5 wires this", action.name)
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
