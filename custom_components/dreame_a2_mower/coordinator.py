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
        return self.data

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
