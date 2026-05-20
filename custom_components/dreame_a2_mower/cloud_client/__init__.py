"""Dreame A2 cloud client — auth, device-info, and OSS download paths.

Lifted from legacy ``dreame/protocol.py`` (``DreameMowerDreameHomeCloudProtocol``
+ ``DreameMowerProtocol`` wrapper) and renamed ``DreameA2CloudClient``.

Transport details: docs/research/g2408-protocol.md §1 — Cloud RPC.

Key behaviours preserved from legacy:
- Cloud RPC (``get_properties`` / ``set_properties`` / ``action``) consistently
  returns HTTP error-code 80001 ("device unreachable") on g2408 even while
  MQTT is live.  This is expected; callers must not treat it as a hard error.
  Source: legacy ``dreame/protocol.py`` ``send()`` retry path / comments.
- OSS signed-URL fetch (``get_interim_file_url`` + ``get_file``) is the only
  fully-reliable cloud surface on g2408.  Session-summary JSONs and LiDAR PCDs
  are all retrieved this way.
- MQTT connection / subscribe logic has been split into ``mqtt_client.py``
  (``DreameA2MqttClient``).  This class no longer owns the paho loop.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import queue
import random
import time
import zlib
from threading import Thread
from time import sleep
from typing import Any

import requests

from ..const import DREAME_STRINGS as _DREAME_STRINGS_B64
from ._helpers import _LOGGER, _http_retry, _random_agent_id
from ._auth import _AuthMixin
from ._discovery import _DiscoveryMixin
from ._rpc import _RpcMixin
from ._oss import _OssMixin
from ._batch import _BatchMixin
from ._fetchers import _FetchersMixin

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin, _BatchMixin, _FetchersMixin):
    """Dreame Home cloud REST + MQTT-bootstrap client for the A2 mower.

    Handles:
    - Authentication (login, token refresh, secondary-key / refresh-token path)
    - Device-info fetching (``get_device_info``, ``get_devices``, ``get_info``)
    - Cloud RPC (``send`` / ``send_async`` / ``get_properties`` / ``set_property``
      / ``set_properties`` / ``action`` / ``action_async``) — note these return
      ``None`` on g2408 due to 80001 errors; see module docstring.
    - OSS file access (``get_interim_file_url``, ``get_file_url``, ``get_file``)
    - Historical device-data queries (``get_device_property``,
      ``get_device_event``, ``get_device_data``, ``get_batch_device_datas``,
      ``set_batch_device_datas``)
    - MQTT bootstrap: ``mqtt_host`` property returns the host:port string that
      ``DreameA2MqttClient`` needs; ``mqtt_topic`` returns the subscribe topic.

    Callers instantiate this directly (no wrapper needed):
    .. code-block:: python

        client = DreameA2CloudClient(username, password, country, device_id)
        client.login()
        info = client.get_device_info()
        host, port = client.mqtt_host_port()
    """

    def __init__(
        self,
        username: str,
        password: str,
        country: str = "cn",
        did: str | None = None,
    ) -> None:
        self.two_factor_url: str | None = None
        self._username = username
        self._password = password
        self._country = country
        self._location = country
        self._did = did
        self._session = requests.session()
        self._queue: queue.Queue = queue.Queue()
        self._thread: Thread | None = None
        self._id = random.randint(1, 100)
        self._host: str | None = None
        self._model: str | None = None
        self._mac: str | None = None
        self._sn: str | None = None
        self._ti: str | None = None
        self._fail_count = 0
        self._connected = False
        self._logged_in: bool | None = None
        self._stream_key: str | None = None
        self._secondary_key: str | None = None
        self._key_expire: float | None = None
        self._key: str | None = None
        self._uid: str | None = None
        self._uuid: str | None = None
        self._strings: list | None = None
        self.endpoint_log: dict[str, str] = {}
        """F6.8.1 endpoint accept/reject log. Key e.g. ``"routed_action_op=100"``,
        value ``"accepted" | "rejected_80001" | "error"``."""
        self._last_send_error_code: int | None = None
        """F6.8.1 transport-layer last error code. Updated by ``send`` so callers
        that get None back can disambiguate 80001 from other failures."""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str | None:
        return self._did

    @property
    def mac_address(self) -> str | None:
        """The mower's WiFi MAC address as reported in the cloud device record.

        Lower-cased to follow HA's `dr.CONNECTION_NETWORK_MAC` convention.
        Populated by ``_handle_device_info`` from the ``mac`` field in
        ``get_devices()`` / ``select_first_g2408()`` payloads.
        """
        return self._mac

    @property
    def uid(self) -> str | None:
        return self._uid

    @property
    def model(self) -> str | None:
        return self._model

    @property
    def serial_number(self) -> str | None:
        """Hardware serial number from the cloud device record.

        Populated by ``_handle_device_info``. None if the cloud omitted it.
        """
        return self._sn

    @property
    def country(self) -> str:
        return self._country

    @property
    def logged_in(self) -> bool | None:
        return self._logged_in

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def object_name(self) -> str:
        return f"{self._model}/{self._uid}/{self._did!s}/0"

    # ------------------------------------------------------------------
    # MQTT bootstrap helpers — used by DreameA2MqttClient
    # ------------------------------------------------------------------

    def mqtt_host_port(self) -> tuple[str, int]:
        """Return ``(host, port)`` extracted from the cloud bind-info ``_host``.

        ``_host`` from Dreame cloud is ``"<ip-or-hostname>:<port>"``.
        Raises ``ValueError`` if not yet populated (call ``get_device_info``
        first).

        Source: legacy ``dreame/protocol.py`` ``connect()`` lines ~257–258.
        """
        if not self._host:
            raise ValueError(
                "mqtt_host_port() called before device info was fetched — "
                "call get_device_info() first"
            )
        parts = self._host.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 8883
        return host, port

    def mqtt_client_id(self) -> str:
        """Return the MQTT client-id string the apk uses.

        Format: ``<strings[53]><uid><strings[54]><random_agent_id><strings[54]><host>``.
        Source: legacy ``dreame/protocol.py`` ``connect()`` lines ~246–248.
        """
        strings = self._ensure_strings()
        host = self._host.split(":")[0] if self._host else ""
        return (
            f"{strings[53]}{self._uid}{strings[54]}"
            f"{_random_agent_id()}{strings[54]}{host}"
        )

    def mqtt_credentials(self) -> tuple[str, str]:
        """Return ``(username, password)`` for the MQTT broker.

        Username = ``self._uuid`` (numeric UID from login response).
        Password = current ``self._key`` (rotated on token refresh).

        Source: legacy ``dreame/protocol.py`` ``_set_client_key()``.
        """
        return self._uuid, self._key

    def mqtt_topic(self) -> str:
        """Return the subscribe topic for this device.

        Format: ``/<strings[7]>/<did>/<uid>/<model>/<country>/``
        Source: legacy ``dreame/protocol.py`` ``_on_client_connect()`` line ~150.

        Maps to: ``/status/<did>/<mac-hash>/dreame.mower.g2408/<region>/``
        as documented in docs/research/g2408-protocol.md §1.1.
        """
        strings = self._ensure_strings()
        return (
            f"/{strings[7]}/{self._did}/{self._uid}"
            f"/{self._model}/{self._country}/"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_strings(self) -> list:
        if self._strings is None:
            self._strings = json.loads(
                zlib.decompress(
                    base64.b64decode(_DREAME_STRINGS_B64), zlib.MAX_WBITS | 32
                )
            )
        return self._strings

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def disconnect(self) -> None:
        """Close the HTTP session and stop the async API thread."""
        self._session.close()
        self._connected = False
        self._logged_in = False
        if self._thread:
            self._queue.put([])
        self._thread = None
