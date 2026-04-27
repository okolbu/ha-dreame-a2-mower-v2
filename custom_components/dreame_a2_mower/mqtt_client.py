"""Dreame A2 MQTT client — dumb-pipe MQTT connection layer.

Extracted from legacy ``dreame/protocol.py``
(``DreameMowerDreameHomeCloudProtocol`` paho internals) and split into its
own module so the coordinator owns decoding/dispatch and this class owns only
the transport.

MQTT topic format: ``/status/<did>/<uid>/<model>/<region>/``
Source: docs/research/g2408-protocol.md §1.1.

The caller is responsible for:
1. Obtaining credentials and topic from ``DreameA2CloudClient`` (via
   ``mqtt_credentials()``, ``mqtt_host_port()``, ``mqtt_client_id()``,
   ``mqtt_topic()``).
2. Registering a callback via ``register_callback()`` before calling
   ``connect()``.
3. Calling ``disconnect()`` during coordinator teardown.

The callback receives ``(topic: str, payload: dict)`` for every valid inbound
message.  The ``data`` envelope is unwrapped before delivery; the coordinator
sees the inner message dict only.  Invalid JSON payloads are logged at WARNING
and silently dropped.

Reconnection / token refresh:
- paho's built-in ``reconnect_delay_set(min=1, max=15)`` handles transient
  TCP drops (e.g. MQTT broker restart).
- On auth error (rc=5) the client calls ``on_auth_error_callback`` if
  registered, giving the coordinator a chance to refresh the token via
  ``DreameA2CloudClient.login()`` and then ``update_credentials()``.
- Source: legacy ``dreame/protocol.py`` ``_on_client_disconnect()`` logic.

Archive hook:
- ``attach_archive(archive)`` installs an optional raw-payload JSONL archive
  (same interface as ``protocol.mqtt_archive.MqttArchive``).  The archive
  sees every payload before JSON decoding — malformed payloads are still
  captured.
"""
from __future__ import annotations

import json
import logging
import ssl
from collections.abc import Callable
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)


class DreameA2MqttClient:
    """Dumb-pipe MQTT client for the Dreame A2 mower.

    Wraps paho-mqtt with the specific TLS + credential setup the Dreame cloud
    broker requires.  Owns no decoding logic — raw ``data`` dicts from each
    inbound MQTT message are forwarded to the registered callback unchanged.

    Interface for F1:
    - ``connect(host, port, username, password, client_id)``
    - ``subscribe(topic)``
    - ``register_callback(callback)``
    - ``disconnect()``

    Additional hooks:
    - ``register_connected_callback(cb)`` — called on successful broker connect
    - ``register_auth_error_callback(cb)`` — called on rc=5 (credential
      rotation needed)
    - ``update_credentials(username, password)`` — hot-swap credentials on
      token refresh without full reconnect (paho queues the change and applies
      it on the next connection attempt)
    - ``attach_archive(archive)`` — install a raw-payload JSONL archiver
    """

    def __init__(self) -> None:
        self._client: Any = None  # paho.mqtt.client.Client, imported lazily
        self._callback: Optional[Callable[[str, dict], None]] = None
        self._connected_callback: Optional[Callable[[], None]] = None
        self._auth_error_callback: Optional[Callable[[], None]] = None
        self._archive: Any = None
        self._connected: bool = False
        self._connecting: bool = False
        self._username: Optional[str] = None
        self._password: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_callback(self, callback: Callable[[str, dict], None]) -> None:
        """Register the inbound-message callback.

        The callback receives ``(topic: str, payload: dict)`` where ``payload``
        is the ``data`` value from the MQTT envelope.  Called on the paho
        worker thread — the coordinator must schedule state updates on the HA
        event loop.
        """
        self._callback = callback

    def register_connected_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked once on successful broker connection."""
        self._connected_callback = callback

    def register_auth_error_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when the broker rejects credentials (rc=5).

        The coordinator should call ``DreameA2CloudClient.login()`` and then
        ``update_credentials()`` in response.
        """
        self._auth_error_callback = callback

    def attach_archive(self, archive: Any) -> None:
        """Install a raw-payload JSONL archive.

        The archive's ``write(topic, payload)`` method is called on every
        inbound payload before JSON decoding.  Errors from the archive are
        caught and logged — archive failures must not break the live pipeline.

        Source: legacy ``dreame/protocol.py`` ``attach_mqtt_archive()``.
        """
        self._archive = archive

    def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
    ) -> None:
        """Establish a TLS connection to the Dreame MQTT broker.

        Uses paho's ``loop_start()`` so the connection runs on a background
        thread.  The ``_on_connect`` callback fires when the broker accepts the
        connection; ``subscribe()`` is typically called from there (or via
        ``register_connected_callback``).

        Source: legacy ``dreame/protocol.py`` ``connect()`` paho setup block
        (~lines 241–261).

        Args:
            host: MQTT broker hostname (from ``DreameA2CloudClient.mqtt_host_port()``).
            port: MQTT broker port (typically 8883 for TLS).
            username: MQTT username (the cloud UID / ``_uuid``).
            password: MQTT password (the current session token / ``_key``).
            client_id: MQTT client-id string (from
                ``DreameA2CloudClient.mqtt_client_id()``).
        """
        # Import paho lazily so the module remains importable in test envs
        # that don't have paho installed.
        try:
            from paho.mqtt import client as mqtt_client
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "paho-mqtt is required for DreameA2MqttClient.connect(). "
                "Install it with: pip install paho-mqtt"
            ) from exc

        self._username = username
        self._password = password

        if self._client is None:
            _LOGGER.info("Connecting to MQTT broker %s:%s", host, port)
            try:
                self._client = mqtt_client.Client(
                    mqtt_client.CallbackAPIVersion.VERSION1,
                    client_id,
                    clean_session=True,
                    userdata=self,
                )
                self._client.on_connect = DreameA2MqttClient._on_connect
                self._client.on_disconnect = DreameA2MqttClient._on_disconnect
                self._client.on_message = DreameA2MqttClient._on_message
                self._client.reconnect_delay_set(1, 15)
                self._client.tls_set(cert_reqs=ssl.CERT_NONE)
                self._client.tls_insecure_set(True)
                self._client.username_pw_set(username, password)
                self._connecting = True
                self._client.connect(host, port, keepalive=50)
                self._client.loop_start()
            except Exception as ex:
                _LOGGER.error("MQTT connect failed: %s", ex)
                self._client = None
                self._connecting = False
        elif not self._connected:
            # Reconnect with potentially refreshed credentials.
            self._client.username_pw_set(username, password)

    def subscribe(self, topic: str) -> None:
        """Subscribe to an MQTT topic.

        Should be called after the connection is established (i.e. from the
        ``register_connected_callback``).  Calling before ``connect()`` is a
        no-op with a WARNING log.

        Source: legacy ``dreame/protocol.py`` ``_on_client_connect()`` line ~150.
        """
        if self._client is None:
            _LOGGER.warning(
                "DreameA2MqttClient.subscribe(%r) called before connect() — "
                "topic will not be subscribed.",
                topic,
            )
            return
        _LOGGER.debug("MQTT subscribing to %s", topic)
        self._client.subscribe(topic)

    def update_credentials(self, username: str, password: str) -> None:
        """Hot-swap MQTT credentials (called after a token refresh).

        paho queues the credential change and applies it on the next
        connection attempt.  The existing paho loop is not restarted.

        Source: legacy ``dreame/protocol.py`` ``_set_client_key()`` logic.
        """
        self._username = username
        self._password = password
        if self._client is not None:
            self._client.username_pw_set(username, password)

    def disconnect(self) -> None:
        """Stop the paho loop and disconnect cleanly.

        Source: legacy ``dreame/protocol.py``
        ``DreameMowerDreameHomeCloudProtocol.disconnect()`` paho block.
        """
        if self._client is not None:
            _LOGGER.info("MQTT disconnecting")
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False
        self._connecting = False
        self._callback = None
        self._connected_callback = None

    @property
    def is_connected(self) -> bool:
        """True once the broker has acknowledged the connection."""
        return self._connected

    # ------------------------------------------------------------------
    # paho static callbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _on_connect(client, self: "DreameA2MqttClient", flags, rc: int) -> None:
        """paho on_connect callback.

        Source: legacy ``dreame/protocol.py``
        ``DreameMowerDreameHomeCloudProtocol._on_client_connect()``.
        """
        self._connecting = False
        if rc == 0:
            if not self._connected:
                self._connected = True
                _LOGGER.info("MQTT broker connected (rc=0)")
            if self._connected_callback:
                try:
                    self._connected_callback()
                except Exception as ex:
                    _LOGGER.warning("connected_callback raised: %s", ex)
        else:
            _LOGGER.warning("MQTT broker connection failed: rc=%s", rc)
            self._connected = False

    @staticmethod
    def _on_disconnect(client, self: "DreameA2MqttClient", rc: int) -> None:
        """paho on_disconnect callback.

        rc=0  — clean disconnect (we called disconnect()).
        rc=5  — auth error; ask the coordinator to refresh the token.
        other — transient; paho's reconnect_delay_set handles backoff.

        Source: legacy ``dreame/protocol.py``
        ``DreameMowerDreameHomeCloudProtocol._on_client_disconnect()``.
        """
        if rc != 0:
            if not self._connecting:
                self._connecting = True
                _LOGGER.info(
                    "MQTT broker disconnected (rc=%s) — paho will reconnect", rc
                )
            if rc == 5 and self._auth_error_callback:
                # Auth failure — token may have expired.
                try:
                    self._auth_error_callback()
                except Exception as ex:
                    _LOGGER.warning("auth_error_callback raised: %s", ex)

    @staticmethod
    def _on_message(client, self: "DreameA2MqttClient", message) -> None:
        """paho on_message callback — decode and forward to registered callback.

        Writes the raw payload to the archive first (so even unparseable
        messages are captured).  Unwraps the ``data`` envelope before
        forwarding.

        Source: legacy ``dreame/protocol.py``
        ``DreameMowerDreameHomeCloudProtocol._on_client_message()``.
        """
        topic: str = getattr(message, "topic", "?")

        # Archive hook — fires before JSON decoding, catches everything.
        if self._archive is not None:
            try:
                self._archive.write(topic=topic, payload=message.payload)
            except Exception as ex:
                _LOGGER.warning("MQTT archive write failed: %s", ex)

        if not self._callback:
            return

        # Decode JSON.
        try:
            response = json.loads(message.payload.decode("utf-8"))
        except Exception as ex:
            try:
                sample = message.payload[:200].hex()
            except Exception:
                sample = "<unreadable>"
            _LOGGER.warning(
                "[UNKNOWN] MQTT payload on topic %s did not decode as JSON "
                "(%s); first 200 bytes hex=%s",
                topic,
                ex,
                sample,
            )
            return

        # Unwrap the Dreame envelope: { "data": { "method": ..., ... } }.
        if "data" in response and response["data"]:
            try:
                self._callback(topic, response["data"])
            except Exception as ex:
                _LOGGER.warning(
                    "MQTT message callback raised on topic %s: %s", topic, ex
                )
        else:
            _LOGGER.debug(
                "MQTT message without 'data' field on topic %s: %s",
                topic,
                response,
            )
