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

from .const import DREAME_STRINGS as _DREAME_STRINGS_B64

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _random_agent_id() -> str:
    """Return a 13-char uppercase-hex random string used in the MQTT client-id.

    Mirrors legacy ``dreame/protocol.py`` ``_random_agent_id()``.
    """
    letters = "ABCDEF"
    return "".join(random.choice(letters) for _ in range(13))

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DreameA2CloudClient:
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

    def _api_task(self) -> None:
        while True:
            item = self._queue.get()
            if len(item) == 0:
                self._queue.task_done()
                return
            item[0](self._api_call(item[1], item[2], item[3]))
            sleep(0.1)
            self._queue.task_done()

    def _api_call_async(
        self, callback, url: str, params=None, retry_count: int = 2
    ) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._api_task, daemon=True)
            self._thread.start()
        self._queue.put((callback, url, params, retry_count))

    def _api_call(self, url: str, params=None, retry_count: int = 2) -> Any:
        return self.request(
            f"{self.get_api_url()}/{url}",
            json.dumps(params, separators=(",", ":")) if params is not None else None,
            retry_count,
        )

    def get_api_url(self) -> str:
        strings = self._ensure_strings()
        return f"https://{self._country}{strings[0]}:{strings[1]}"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Authenticate against the Dreame cloud and store the session token.

        Supports primary (username/password) and secondary (refresh-token)
        login paths.  On 401 with an expired refresh token, falls back to
        the primary path automatically.

        Source: legacy ``dreame/protocol.py`` ``DreameMowerDreameHomeCloudProtocol.login()``.
        """
        self._session.close()
        self._session = requests.session()
        self._logged_in = False

        strings = self._ensure_strings()

        try:
            if self._secondary_key:
                data = f"{strings[12]}{strings[13]}{self._secondary_key}"
            else:
                data = (
                    f"{strings[12]}{strings[14]}{self._username}"
                    f"{strings[15]}"
                    f"{hashlib.md5((self._password + strings[2]).encode('utf-8')).hexdigest()}"
                    f"{strings[16]}"
                )

            headers = {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Language": "en-US;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                strings[47]: strings[3],
                strings[49]: strings[5],
                strings[50]: self._ti if self._ti else strings[6],
            }
            if self._country == "cn":
                headers[strings[48]] = strings[4]

            response = self._session.post(
                self.get_api_url() + strings[17],
                headers=headers,
                data=data,
                timeout=10,
            )
            if response.status_code == 200:
                data = json.loads(response.text)
                if strings[18] in data:
                    self._key = data.get(strings[18])
                    self._secondary_key = data.get(strings[19])
                    self._key_expire = time.time() + data.get(strings[20]) - 120
                    self._logged_in = True
                    self._uuid = data.get("uid")
                    self._location = data.get(strings[21], self._location)
                    self._ti = data.get(strings[22], self._ti)
            else:
                try:
                    data = json.loads(response.text)
                    if (
                        "error_description" in data
                        and "refresh token" in data["error_description"]
                    ):
                        self._secondary_key = None
                        return self.login()
                except Exception:
                    pass
                _LOGGER.error("Login failed: %s", response.text)
        except requests.exceptions.Timeout:
            _LOGGER.warning("Login Failed: Read timed out. (read timeout=10)")
        except Exception as ex:
            _LOGGER.error("Login failed: %s", str(ex))

        if self._logged_in:
            self._fail_count = 0
            self._connected = True
        return self._logged_in

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def _handle_device_info(self, info: dict) -> None:
        strings = self._ensure_strings()
        self._uid = info[strings[8]]
        self._did = info["did"]
        self._model = info[strings[35]]
        self._host = info[strings[9]]
        mac = info.get("mac")
        # Normalise to lowercase colon-separated form for HA's
        # `dr.CONNECTION_NETWORK_MAC` matcher (the cloud sends uppercase).
        self._mac = mac.lower() if isinstance(mac, str) and mac else None
        self._sn = info.get("sn")
        if not self._sn:
            _LOGGER.warning(
                "cloud _handle_device_info: sn missing from device info;"
                " falling back to mac/entry_id for identifiers"
            )
        _LOGGER.info(
            "cloud _handle_device_info: did=%r model=%r mac=%r _host=%r",
            self._did, self._model, self._mac, self._host,
        )
        prop = info[strings[10]]
        if prop and prop != "":
            prop = json.loads(prop)
            if strings[11] in prop:
                self._stream_key = prop[strings[11]]

    def get_devices(self) -> Any:
        """Fetch the full device list for this account."""
        strings = self._ensure_strings()
        response = self._api_call(
            f"{strings[23]}/{strings[24]}/{strings[27]}/{strings[28]}"
        )
        if response and "data" in response and response["code"] == 0:
            return response["data"]
        return None

    def select_first_g2408(self) -> dict:
        """Discover the user's mower in the cloud device list and pin it.

        Calls ``get_devices()``, picks the first entry whose ``model``
        starts with ``dreame.mower.`` (single-model integration per spec
        §10), and runs ``_handle_device_info`` on it so subsequent calls
        — ``get_device_info`` and ``mqtt_host_port`` — have ``_did`` and
        ``_host`` populated.

        Raises ``ValueError`` if login hasn't run, no devices were
        returned, or no matching device exists.
        """
        if not self._logged_in:
            raise ValueError("login() must run before select_first_g2408()")
        response = self.get_devices()
        if not response:
            raise ValueError("get_devices() returned no data — auth lost?")
        records = response.get("page", {}).get("records", [])
        matches = [
            d for d in records
            if str(d.get("model", "")).startswith("dreame.mower.")
        ]
        if not matches:
            raise ValueError(
                "no dreame.mower.* device in account — config_flow should "
                "have validated this"
            )
        self._handle_device_info(matches[0])
        return matches[0]

    def get_device_info(self) -> Any:
        """Fetch device-info + OTC info for ``self._did``.

        Populates ``_uid``, ``_model``, ``_host`` (needed for MQTT bootstrap)
        and ``_stream_key``.  Falls back to ``get_devices()`` if the OTC
        endpoint returns an empty result.

        Source: legacy ``dreame/protocol.py`` ``get_device_info()``.
        """
        strings = self._ensure_strings()
        response = self._api_call(
            f"{strings[23]}/{strings[24]}/{strings[27]}/{strings[29]}",
            {"did": self._did},
        )
        if response and "data" in response and response["code"] == 0:
            data = response["data"]
            self._handle_device_info(data)
            response = self._api_call(
                f"{strings[23]}/{strings[25]}/{strings[30]}",
                {"did": self._did},
            )
            if response and "data" in response and response["code"] == 0:
                if strings[31] in response["data"]:
                    data = {
                        **response["data"][strings[31]][strings[32]],
                        **data,
                    }
                else:
                    _LOGGER.info(
                        "Get Device OTC Info empty, trying fallback... (%s)", response
                    )
                    devices = self.get_devices()
                    if devices is not None:
                        found = list(
                            filter(
                                lambda d: str(d["did"]) == self._did,
                                devices[strings[34]][strings[36]],
                            )
                        )
                        if len(found) > 0:
                            self._handle_device_info(found[0])
                            return found[0]
                    _LOGGER.warning(
                        "Get Device OTC Info fallback failed, proceeding with "
                        "basic device info"
                    )
                    return data
            return data
        return None

    def get_info(self, mac: str) -> tuple[str | None, str | None]:
        """Look up device by MAC and populate internal device-info fields.

        Returns ``(did_sentinel, host)`` or ``(None, None)`` if not found.
        Source: legacy ``dreame/protocol.py`` ``get_info()``.
        """
        if self._did is not None:
            return " ", self._host
        strings = self._ensure_strings()
        devices = self.get_devices()
        if devices is not None:
            found = list(
                filter(
                    lambda d: str(d["mac"]) == mac,
                    devices[strings[34]][strings[36]],
                )
            )
            if len(found) > 0:
                self._handle_device_info(found[0])
                return " ", self._host
        return None, None

    # ------------------------------------------------------------------
    # Cloud RPC — note: returns None on g2408 (80001 errors are expected)
    # ------------------------------------------------------------------

    def send_async(
        self,
        callback,
        method: str,
        parameters: Any = None,
        retry_count: int = 2,
    ) -> None:
        """Fire a cloud RPC and deliver the result to ``callback``.

        On g2408 the callback typically receives ``None`` because 80001 is
        the steady-state response.  Callers must handle ``None`` gracefully.

        Source: legacy ``dreame/protocol.py`` ``DreameMowerDreameHomeCloudProtocol.send_async()``.
        """
        host = ""
        if self._host and len(self._host):
            host = f"-{self._host.split('.')[0]}"
        if method == "action" and (not host or not host.lstrip("-").isdigit()):
            host = "-10000"

        strings = self._ensure_strings()
        self._id = self._id + 1
        url = f"{strings[37]}{host}/{strings[27]}/{strings[38]}"
        if method == "action" and url.startswith("http://"):
            url = "https://" + url[len("http://"):]

        self._api_call_async(
            lambda api_response: callback(
                None
                if (
                    api_response is None
                    or "data" not in api_response
                    or not api_response["data"]
                    or "result" not in api_response["data"]
                )
                else api_response["data"]["result"]
            ),
            url,
            {
                "did": str(self._did),
                "id": self._id,
                "data": {
                    "did": str(self._did),
                    "id": self._id,
                    "method": method,
                    "params": parameters,
                    "from": "XXXXXX",
                },
            },
            retry_count,
        )

    def send(self, method: str, parameters: Any = None, retry_count: int = 2) -> Any:
        """Synchronous cloud RPC.

        Returns ``None`` on failure (including 80001 on g2408).  The ``action``
        method path retries up to 3 times; 80001 breaks early to avoid a ~32 s
        stall (3 attempts × ~8 s) per call.

        Source: legacy ``dreame/protocol.py`` ``DreameMowerDreameHomeCloudProtocol.send()``.
        """
        host = ""
        if self._host and len(self._host):
            host = f"-{self._host.split('.')[0]}"
        original_host = host
        if method == "action" and (not host or not host.lstrip("-").isdigit()):
            host = "-10000"

        strings = self._ensure_strings()
        url = f"{strings[37]}{host}/{strings[27]}/{strings[38]}"
        if method == "action":
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            _LOGGER.debug(
                "cloud action URL: %s (derived host=%r final host=%r _host=%r)",
                url, original_host, host, self._host,
            )

        attempts = 3 if method == "action" else 1
        for attempt in range(attempts):
            self._id = self._id + 1
            api_response = self._api_call(
                url,
                {
                    "did": str(self._did),
                    "id": self._id,
                    "data": {
                        "did": str(self._did),
                        "id": self._id,
                        "method": method,
                        "params": parameters,
                        "from": "XXXXXX",
                    },
                },
                retry_count,
            )
            if (
                api_response
                and "data" in api_response
                and api_response["data"]
                and "result" in api_response["data"]
            ):
                self._last_send_error_code = None  # F6.8.1
                return api_response["data"]["result"]

            error_code = api_response.get("code") if api_response else None
            self._last_send_error_code = error_code  # F6.8.1
            if error_code:
                _LOGGER.warning(
                    "Cloud send error %s for %s (attempt %d/%d): %s",
                    error_code,
                    method,
                    attempt + 1,
                    attempts,
                    api_response.get("msg", ""),
                )
                # 80001 = "device unreachable via cloud relay".
                # On g2408 this is permanent — break fast to avoid ~32 s stall.
                if method == "action" and error_code != 80001 and attempt < attempts - 1:
                    sleep(8)
                    continue
            break
        return None

    def get_properties(self, parameters: Any = None, retry_count: int = 1) -> Any:
        """Fetch device properties via cloud RPC.

        Returns ``None`` on g2408 (80001 error is expected).
        """
        return self.send("get_properties", parameters=parameters, retry_count=retry_count)

    def set_property(
        self, siid: int, piid: int, value: Any = None, retry_count: int = 2
    ) -> Any:
        return self.set_properties(
            [
                {
                    "did": str(self._did),
                    "siid": siid,
                    "piid": piid,
                    "value": value,
                }
            ],
            retry_count=retry_count,
        )

    def set_properties(self, parameters: Any = None, retry_count: int = 2) -> Any:
        return self.send("set_properties", parameters=parameters, retry_count=retry_count)

    def action_async(
        self,
        callback,
        siid: int,
        aiid: int,
        parameters: list | None = None,
        retry_count: int = 2,
    ) -> None:
        if parameters is None:
            parameters = []
        _LOGGER.debug("Send Action Async: %s.%s %s", siid, aiid, parameters)
        self.send_async(
            callback,
            "action",
            parameters={
                "did": str(self._did),
                "siid": siid,
                "aiid": aiid,
                "in": parameters,
            },
            retry_count=retry_count,
        )

    def action(
        self,
        siid: int,
        aiid: int,
        parameters: list | None = None,
        retry_count: int = 2,
    ) -> Any:
        if parameters is None:
            parameters = []
        _LOGGER.debug("Send Action: %s.%s %s", siid, aiid, parameters)
        return self.send(
            "action",
            parameters={
                "did": str(self._did),
                "siid": siid,
                "aiid": aiid,
                "in": parameters,
            },
            retry_count=retry_count,
        )

    # ------------------------------------------------------------------
    # OSS file access — the only fully-reliable cloud surface on g2408
    # ------------------------------------------------------------------

    def get_interim_file_url(self, object_name: str = "") -> str | None:
        """Fetch a time-limited signed OSS URL for an object.

        This is the only reliable mechanism to download session-summary JSONs
        and LiDAR PCDs on g2408.  ``object_name`` is the MQTT-pushed object
        key from the ``event_occured`` message.

        Source: legacy ``dreame/protocol.py`` ``get_interim_file_url()``.
        See also: docs/research/g2408-protocol.md §1.2 (OSS download).
        """
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[39]}/{strings[55]}",
            {
                "did": str(self._did),
                strings[35]: self._model,
                strings[40]: object_name,
                strings[21]: self._country,
            },
        )
        if api_response is None:
            _LOGGER.warning(
                "[OSS] get_interim_file_url: API call returned None for "
                "object_name=%r — cloud transport failure",
                object_name,
            )
            return None
        if "data" not in api_response:
            _LOGGER.warning(
                "[OSS] get_interim_file_url: response had no `data` field "
                "for object_name=%r. Full response: %r",
                object_name,
                api_response,
            )
            return None
        return api_response["data"]

    def get_file_url(self, object_name: str = "") -> Any:
        """Fetch an OSS URL via the alternative (non-interim) endpoint."""
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[39]}/{strings[56]}",
            {
                "did": str(self._did),
                "uid": str(self._uid),
                strings[35]: self._model,
                "filename": object_name[1:],
                strings[21]: self._country,
            },
        )
        if api_response is None or "data" not in api_response:
            return None
        return api_response["data"]

    def fetch_wifi_map(self, map_id: int) -> dict[str, Any] | None:
        """Fetch the latest WiFi signal heatmap from OSS for a given map.

        Sequence (sourced from ioBroker.dreame v0.3.7
        ``main.js:fetchWifiMap``):
        1. Routed-action `s2.50 m='g' t='OBJ' d={type:'wifimap'}` returns
           ``{out: [{d: {name: [<obj1>, <obj2>, ...]}}]}`` — an array of
           OSS object names sorted newest-first.
        2. Pick the first (newest) object name.
        3. Check in-process dedup cache ``_wifi_map_cache[(map_id, obj_name)]``
           — if the same object was already downloaded for this map, return
           the cached result without hitting OSS again.
        4. Request a signed URL via ``get_interim_file_url``.
        5. Download the bytes and JSON-parse.

        The OBJ query does not support server-side map_id filtering on
        g2408 firmware — the cloud returns all wifimap objects across maps
        sorted newest-first. The ``map_id`` parameter is used to namespace
        the dedup cache so that a refresh for map 0 and map 1 are tracked
        independently. The decoded result is stamped with ``_map_id`` for
        the renderer and diagnostic attributes.

        Response shape (decoded):
            {
              "data":   list[int],   # width*height RSSI values; `1` = no
                                     # data, negative = dBm
              "width":  int,         # cells across
              "height": int,         # cells down
              "resolution": int,     # cm or dm per cell (TBD units; on
                                     # g2408 observed value 2)
              "startX": int,         # frame origin in cm (matches the
                                     # rest of the cloud map frame)
              "startY": int,
            }

        Returns the decoded dict on success, or None if any step fails
        (no wifi map cached, OSS download failed, JSON parse error,
        etc.). Trigger-side: on g2408 the direct MIoT `s6.aiid=4`
        "request fresh wifi map" path returns 80001 (closed); the
        device generates wifi maps on its own schedule (observed
        2026-05-09: two recent entries auto-generated). See
        docs/research/entity-validation-matrix.md `button.request_wifi_map`
        row for the trigger-side gap.
        """
        try:
            obj_resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "OBJ", "d": {"type": "wifimap"}}],
            )
        except Exception as ex:
            _LOGGER.warning("fetch_wifi_map: OBJ probe error: %s", ex)
            return None
        if not isinstance(obj_resp, dict):
            return None
        outs = obj_resp.get("out") or []
        if not outs or not isinstance(outs[0], dict):
            return None
        names = (outs[0].get("d") or {}).get("name")
        if not names:
            _LOGGER.debug("fetch_wifi_map: no wifimap objects in cloud")
            return None
        # Names list is newest-first per ioBroker observation.
        first = names[0] if isinstance(names, list) else (
            names.get("0") or next(iter(names.values()))
        )
        if not isinstance(first, str):
            return None

        # Dedup: if this (map_id, object_name) was already fetched, reuse it.
        cache = getattr(self, "_wifi_map_cache", None)
        if cache is None:
            self._wifi_map_cache: dict[tuple[int, str], dict[str, Any]] = {}
            cache = self._wifi_map_cache
        cache_key = (map_id, first)
        if cache_key in cache:
            _LOGGER.debug(
                "fetch_wifi_map: cache hit for map %d / %s", map_id, first
            )
            return cache[cache_key]

        url = self.get_interim_file_url(first)
        if not url:
            _LOGGER.warning("fetch_wifi_map: no OSS URL for %s", first)
            return None
        body = self.get_file(url)
        if not body:
            _LOGGER.warning("fetch_wifi_map: download empty for %s", first)
            return None
        try:
            import json as _json
            decoded = _json.loads(body)
        except Exception as ex:
            _LOGGER.warning("fetch_wifi_map: JSON parse failed: %s", ex)
            return None
        if not isinstance(decoded, dict) or "data" not in decoded:
            shape = (
                list(decoded.keys()) if isinstance(decoded, dict)
                else type(decoded).__name__
            )
            _LOGGER.warning("fetch_wifi_map: unexpected JSON shape: %r", shape)
            return None
        decoded["_object_name"] = first  # for diagnostic / debug
        decoded["_map_id"] = map_id
        cache[cache_key] = decoded
        return decoded

    def get_file(self, url: str, retry_count: int = 4) -> Any:
        """Download raw bytes from a signed OSS URL.

        Source: legacy ``dreame/protocol.py`` ``get_file()``.
        """
        retries = 0
        if not retry_count or retry_count < 0:
            retry_count = 0
        while retries < retry_count + 1:
            try:
                response = self._session.get(url, timeout=15)
            except Exception as ex:
                response = None
                _LOGGER.warning("Unable to get file at %s: %s", url, ex)
            if response is not None and response.status_code == 200:
                return response.content
            retries = retries + 1
        return None

    # ------------------------------------------------------------------
    # Historical data queries
    # ------------------------------------------------------------------

    def get_device_property(
        self, key: str, limit: int = 1, time_start: int = 0, time_end: int = 9999999999
    ) -> Any:
        return self.get_device_data(key, "prop", limit, time_start, time_end)

    def get_device_event(
        self, key: str, limit: int = 1, time_start: int = 0, time_end: int = 9999999999
    ) -> Any:
        return self.get_device_data(key, "event", limit, time_start, time_end)

    def get_device_data(
        self,
        key: str,
        type: str,
        limit: int = 1,
        time_start: int = 0,
        time_end: int = 9999999999,
    ) -> Any:
        strings = self._ensure_strings()
        data_keys = key.split(".")
        params = {
            "uid": str(self._uid),
            "did": str(self._did),
            "from": time_start if time_start else 1687019188,
            "limit": limit,
            "siid": data_keys[0],
            strings[21]: self._country,
            strings[42]: 3,
        }
        param_name = "piid"
        if type == "event":
            param_name = "eiid"
        elif type == "action":
            param_name = "aiid"
        params[param_name] = data_keys[1]
        api_response = self._api_call(
            f"{strings[23]}/{strings[25]}/{strings[43]}", params
        )
        if (
            api_response is None
            or "data" not in api_response
            or strings[33] not in api_response["data"]
        ):
            return None
        return api_response["data"][strings[33]]

    def get_batch_device_datas(self, props: Any) -> Any:
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[26]}/{strings[44]}",
            {"did": self._did, strings[35]: props},
        )
        if api_response is None or "data" not in api_response:
            return None
        return api_response["data"]

    def set_batch_device_datas(self, props: Any) -> Any:
        """Cloud-batch write — counterpart to `get_batch_device_datas`.

        Confirmed working 2026-05-08 against g2408's Dreame Cloud (eu region):
        endpoint `dreame-user-iot/iotuserdata/setDeviceData`, payload field
        `data` (NOT the `model` field that the GET endpoint accepts —
        Dreame's API is inconsistent across get/set on this surface).
        Returns `{"code": 0, "success": True, "msg": "设置成功"}` on success.

        `props` is a dict of `{cloud_key: cloud_value}` — same shape as the
        `get_batch_device_datas([])` response. Examples:
            client.set_batch_device_datas({"AI_HUMAN.0": '"true"'})
            client.set_batch_device_datas({"SCHEDULE.0": '{"d":[...],"v":N}'})

        Returns the parsed cloud response dict on both success and failure
        (so callers can read `code` / `msg` to surface rejection reasons),
        or None if the HTTP call itself failed (no response at all). On
        success some legacy endpoints return the response under `result`;
        we unwrap that one level for backwards-compatibility.

        Used to write chunked-batch keys that direct `set_property(s,p,v)`
        rejects with 80001 on g2408 (most siids are not exposed via direct
        MIoT writes on this device). See journal §"Systemic finding".
        """
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[26]}/{strings[45]}",
            # Field name "data" is hardcoded — `strings[35]` decodes to
            # "model", which the GET endpoint accepts but SET rejects with
            # `{"code":10007,"msg":"data:must not be empty"}`.
            {"did": self._did, "data": props},
        )
        if api_response is None:
            return None
        # Success: unwrap `result` if present, else return the top-level dict.
        if api_response.get("success") is True or api_response.get("code") == 0:
            if "result" in api_response and isinstance(api_response["result"], dict):
                return api_response["result"]
            return api_response
        # Failure: return the response dict so the caller can log code/msg.
        return api_response

    def write_chunked_key(
        self,
        key_prefix: str,
        value: str,
        info: str | None = None,
    ) -> tuple[bool, dict | None]:
        """Write a chunked-batch value to the cloud via setDeviceData.

        Splits `value` into ≤1024-char chunks (server-enforced cap),
        builds {key_prefix.0..N + key_prefix.info?}, calls
        set_batch_device_datas. Returns (ok, raw_response).

        `info` defaults to str(len(value)) when chunking is needed; for
        single-chunk writes (value ≤ 1024 chars) `.info` is omitted to
        match the AI_HUMAN.0 / SCHEDULE.0 single-chunk pattern observed
        live. Callers writing keys where `.info` carries something else
        (M_PATH offset, MAP split point) can pass `info=` explicitly.
        """
        CHUNK = 1024
        if len(value) <= CHUNK and info is None:
            payload = {f"{key_prefix}.0": value}
        else:
            chunks = [value[i:i + CHUNK] for i in range(0, len(value), CHUNK)] or [""]
            payload = {f"{key_prefix}.{i}": chunk for i, chunk in enumerate(chunks)}
            payload[f"{key_prefix}.info"] = info if info is not None else str(len(value))
        result = self.set_batch_device_datas(payload)
        if not isinstance(result, dict):
            return False, None
        ok = result.get("success") is True or result.get("code") == 0
        if not ok:
            # Surface the cloud's rejection details (code/msg) so callers
            # see something more useful than `rejected: None` in the log.
            _LOGGER.warning(
                "set_batch_device_datas %s rejected: code=%r msg=%r",
                key_prefix, result.get("code"), result.get("msg"),
            )
        return ok, result

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def request(self, url: str, data: Any, retry_count: int = 2) -> Any:
        """POST to a Dreame cloud API endpoint with token-auth headers.

        Auto-refreshes the session token when ``_key_expire`` is past.
        Returns parsed JSON or ``None`` on failure.

        Source: legacy ``dreame/protocol.py`` ``DreameMowerDreameHomeCloudProtocol.request()``.
        """
        strings = self._ensure_strings()
        retries = 0
        if not retry_count or retry_count < 0:
            retry_count = 0
        response = None
        while retries < retry_count + 1:
            try:
                if self._key_expire and time.time() > self._key_expire:
                    self.login()

                headers = {
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept-Language": "en-US;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    strings[47]: strings[3],
                    strings[49]: strings[5],
                    strings[50]: self._ti if self._ti else strings[6],
                    strings[51]: strings[52],
                    strings[46]: self._key,
                }
                if self._country == "cn":
                    headers[strings[48]] = strings[4]

                response = self._session.post(
                    url, headers=headers, data=data, timeout=15
                )
                break
            except requests.exceptions.Timeout:
                retries += 1
                response = None
                if self._connected:
                    _LOGGER.warning(
                        "Error while executing request: Read timed out. "
                        "(read timeout=15): %s",
                        data,
                    )
            except Exception as ex:
                retries += 1
                response = None
                if self._connected:
                    _LOGGER.warning("Error while executing request: %s", str(ex))

        if response is not None:
            if response.status_code == 200:
                self._fail_count = 0
                self._connected = True
                parsed = json.loads(response.text)
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    from .protocol.api_log import summarize_api_response
                    _LOGGER.debug(
                        "API response: %s",
                        summarize_api_response(url, parsed),
                    )
                return parsed
            elif response.status_code == 401 and self._secondary_key:
                _LOGGER.debug("Execute api call failed: Token Expired")
                self.login()
            else:
                _LOGGER.warning(
                    "Execute api call failed with response: %s", response.text
                )

        if self._fail_count == 5:
            _LOGGER.debug(
                "5 consecutive HTTP failures; marking cloud disconnected"
            )
            self._connected = False
        else:
            self._fail_count += 1
        return None

    # ------------------------------------------------------------------
    # Routed-action helpers
    # ------------------------------------------------------------------

    def fetch_cfg(self) -> dict[str, Any] | None:
        """Fetch CFG via the routed-action s2 aiid=50 {m:'g', t:'CFG'} path.

        Returns the parsed ``d`` field (a dict of CFG keys) on success,
        or None on failure. Logs warnings; does not raise.

        This uses the ``action`` cloud-RPC path (siid=2, aiid=50), which
        is the only cloud surface confirmed to work on g2408 — regular
        ``set_properties`` / ``action`` for other siids returns 80001.

        Source: docs/research/g2408-protocol.md §6.2; legacy
        dreame/device.py:refresh_cfg for request shape.
        """
        from .protocol.cfg_action import CfgActionError, get_cfg  # type: ignore[import]

        try:
            cfg = get_cfg(self.action)
        except CfgActionError as ex:
            _LOGGER.warning("fetch_cfg: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_cfg: unexpected error: %s", ex)
            return None
        _LOGGER.info("[CFG] fetched %d keys", len(cfg))
        _LOGGER.debug("[CFG] payload: %r", cfg)
        return cfg

    def fetch_locn(self) -> dict[str, Any] | None:
        """Fetch LOCN via the routed-action s2 aiid=50 {m:'g', t:'LOCN'} path.

        Returns a dict containing a ``pos`` key (e.g. ``{"pos": [lon, lat]}``)
        on success, or None on failure. Logs warnings; does not raise.

        The sentinel value ``pos: [-1, -1]`` means the dock GPS origin has
        not been configured — callers should treat this as "no position".

        Source: docs/research/g2408-protocol.md §2.1 LOCN; legacy
        dreame/device.py:refresh_locn for request shape and response handling.
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "LOCN")
        except CfgActionError as ex:
            _LOGGER.warning("fetch_locn: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_locn: unexpected error: %s", ex)
            return None

        # Unwrap optional `d` envelope — some firmware revisions wrap the
        # location dict in a `d` key; others return it directly.
        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_locn: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[LOCN] payload: %r", result)
        return result

    def fetch_dev(self) -> dict[str, Any] | None:
        """Fetch DEV via routed-action s2 aiid=50 {m:'g', t:'DEV'}.

        Returns ``{fw, mac, ota, sn}`` on success — the authoritative
        source for the mower's firmware version, MAC, OTA capability flag,
        and hardware serial. Cleaner than the legacy paths:

        - hardware_serial via s1p5 cloud `get_properties` (mostly returns
          80001 on g2408)
        - firmware_version via the cloud device record (`device.info.version`)
        - MAC from `get_devices()` (alt-source, this endpoint cross-checks)

        Returns None on failure (logs at WARNING). Confirmed working on
        g2408 from the 2026-05-04 cloud dump capture.
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "DEV")
        except CfgActionError as ex:
            _LOGGER.warning("fetch_dev: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_dev: unexpected error: %s", ex)
            return None

        # Unwrap optional `d` envelope (some firmware revisions wrap the
        # response in `{d: {...}}`, others return the dict directly).
        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_dev: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[DEV] payload: %r", result)
        return result

    def fetch_mihis(self) -> dict[str, Any] | None:
        """Fetch MIHIS via routed-action s2 aiid=50 {m:'g', t:'MIHIS'}.

        Returns ``{area: m², count: sessions, start: unix_ts, time: minutes}``
        — the cloud-side authoritative lifetime mowing totals matching
        the app's Work Logs header. NOT included in the all-keys
        `getCFG t:'CFG'` dump; needs this dedicated call.

        Returns None on failure (logs at WARNING).
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "MIHIS")
        except CfgActionError as ex:
            _LOGGER.warning("fetch_mihis: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_mihis: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_mihis: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[MIHIS] payload: %r", result)
        return result

    def fetch_dock(self) -> dict[str, Any] | None:
        """Fetch DOCK via routed-action s2 aiid=50 {m:'g', t:'DOCK'}.

        Returns ``{dock: {connect_status, in_region, near_x, near_y,
        near_yaw, path_connect, x, y, yaw}}`` — the dock's authoritative
        state and position in the map frame.

        Confirmed semantics (2026-05-04):
          - connect_status: 1 → mower currently in dock (more reliable
            than inferring from s2p1 == 6 CHARGING).
          - in_region: 1 if dock is inside the lawn polygon, 0 if outside.
          - yaw: dock orientation; matches compass bearing for the X-axis
            of the dock-relative coordinate frame on user's setup.
          - x, y: dock position in the map frame (NOT necessarily 0,0).
          - near_x, near_y, near_yaw, path_connect: semantics still TBD.

        Returns None on failure (logs at WARNING).
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "DOCK")
        except CfgActionError as ex:
            _LOGGER.warning("fetch_dock: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_dock: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_dock: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[DOCK] payload: %r", result)
        return result

    def fetch_net(self) -> dict[str, Any] | None:
        """Fetch NET via routed-action s2 aiid=50 {m:'g', t:'NET'}.

        Returns ``{current: ssid, list: [{ip, rssi, ssid}, ...]}`` —
        the device's currently-associated AP plus the catalogue of
        remembered APs with their last-seen RSSI.

        Useful for populating WiFi RSSI / SSID / IP at startup before
        the first s1p1 heartbeat arrives (which can take ~45 s after
        HA restart). Once the heartbeat starts flowing, byte[17] becomes
        the live RSSI source.

        Returns None on failure (logs at WARNING).
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "NET")
        except CfgActionError as ex:
            _LOGGER.warning("fetch_net: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_net: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_net: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[NET] payload: %r", result)
        return result

    def fetch_map(self) -> dict[int, dict[str, Any]] | None:
        """Fetch the cloud MAP.* batch and return per-map dicts keyed by map_id.

        Calls `get_batch_device_datas` with keys `MAP.0..MAP.127` plus
        `MAP.info`. Reassembles the non-empty chunks; uses `MAP.info` as a
        byte offset to split the joined string when multiple maps are present.
        Each segment is a JSON list `[{...}]` whose inner dict has a
        `mapIndex` field. Returns `{mapIndex: dict, ...}`.

        Range choice: 128 is wide enough for any plausible future expansion
        (the user's current setup uses ~46 chunks for 2 maps; 64 was chosen
        arbitrarily in a96 and proved fine up to a99). The cloud silently
        ignores keys it doesn't have and returns empty strings for them, so
        over-requesting is cheap — it costs nothing at the transport level.
        If g2408 firmware ever grows beyond 128 chunks, raise this to 256.
        (The original a96 value of 64 was confirmed adequate by the
        dump_map_diagnostics a98 run which observed MAP.0..MAP.45; 128 gives
        3× headroom without touching transport cost.)

        Returns None on any irrecoverable failure (network error, empty
        batch, every segment malformed). Partial results beat None when
        at least one map decodes.
        """
        try:
            map_keys = [f"MAP.{i}" for i in range(128)] + ["MAP.info"]
            batch = self.get_batch_device_datas(map_keys)
        except Exception as ex:
            _LOGGER.warning("fetch_map: get_batch_device_datas error: %s", ex)
            return None

        if not batch:
            _LOGGER.debug("fetch_map: empty cloud response")
            return None

        parts = [batch.get(f"MAP.{i}", "") or "" for i in range(128)]
        full = "".join(parts)
        if not full:
            _LOGGER.debug("fetch_map: all MAP.* keys empty")
            return None

        info_raw = batch.get("MAP.info", "") or ""
        try:
            split_pos = int(info_raw) if info_raw else 0
        except (TypeError, ValueError):
            split_pos = 0

        if split_pos > 0 and split_pos < len(full):
            segments = [full[:split_pos], full[split_pos:]]
        else:
            segments = [full]

        result: dict[int, dict[str, Any]] = {}
        import json as _json
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            try:
                parsed = _json.loads(seg)
            except (ValueError, _json.JSONDecodeError):
                continue
            # Cloud wraps each map as a 1-element list.
            entries = parsed if isinstance(parsed, list) else [parsed]
            for entry in entries:
                # Cloud sometimes returns a list-of-JSON-strings (each
                # string is a wrapped map dict). Decode if needed.
                if isinstance(entry, str):
                    try:
                        entry = _json.loads(entry)
                    except (ValueError, _json.JSONDecodeError):
                        continue
                if not isinstance(entry, dict):
                    continue
                if "boundary" not in entry and "mowingAreas" not in entry:
                    continue
                idx = entry.get("mapIndex", 0)
                try:
                    idx_int = int(idx)
                except (TypeError, ValueError):
                    idx_int = 0
                result[idx_int] = entry

        if not result:
            _LOGGER.debug("fetch_map: no usable map segments")
            return None

        _LOGGER.debug("fetch_map: decoded %d map(s) by id", len(result))
        return result

    def fetch_full_cloud_state(self) -> CloudState | None:
        """Fetch the device's full cloud state in one orchestrated call.

        - Empty-list `get_batch_device_datas([])` returns all chunked
          data families (MAP, M_PATH, SETTINGS, SCHEDULE, AI_HUMAN,
          FBD_NTYPE, OTA_INFO, TASKID, prop.s_*).
        - `fetch_cfg()` returns the 24 CFG keys (not in the empty-batch).
        - Probes for LOCN, DOCK, MAPL, MIHIS (each a separate cfg_individual
          call that's already wired).

        Returns None if the empty-batch call fails entirely (network
        error). Partial data — a missing family within a successful
        batch — produces the appropriate empty/None field on
        CloudState rather than failing the whole fetch.
        """
        from .cloud_state import CloudState, ScheduleData, SettingsRoot
        from .map_decoder import parse_cloud_maps
        from .protocol.batch_grouper import group_keys_by_prefix, join_family_chunks
        from .protocol.m_path import parse_m_path_batch
        from .protocol.schedule import parse_schedule_batch
        from .protocol.settings import parse_settings_batch

        try:
            batch = self.get_batch_device_datas([])
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: empty-batch raised: %s", ex)
            return None
        if batch is None:
            return None
        if not isinstance(batch, dict):
            _LOGGER.warning(
                "fetch_full_cloud_state: empty-batch returned %s, not dict",
                type(batch).__name__,
            )
            batch = {}

        # CFG (separate call — not in the empty-batch).
        try:
            cfg = self.fetch_cfg() or {}
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: fetch_cfg raised: %s", ex)
            cfg = {}

        # Group batch keys by family prefix.
        families = group_keys_by_prefix(batch)

        # MAP.* — reuse existing fetch_map logic via an inline parse.
        # The existing fetch_map() makes its own get_batch_device_datas
        # call; we already have the batch, so parse directly.
        maps_by_id: dict[int, Any] = {}
        if "MAP" in families:
            map_joined = join_family_chunks("MAP", batch)
            map_info_raw = batch.get("MAP.info") or ""
            try:
                split_pos = int(map_info_raw) if map_info_raw else 0
            except (TypeError, ValueError):
                split_pos = 0
            segments = (
                [map_joined[:split_pos], map_joined[split_pos:]]
                if 0 < split_pos < len(map_joined)
                else [map_joined]
            )
            import json as _json
            raw_by_id: dict[int, dict] = {}
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                try:
                    parsed = _json.loads(seg)
                except (ValueError, _json.JSONDecodeError):
                    continue
                entries = parsed if isinstance(parsed, list) else [parsed]
                for entry in entries:
                    if isinstance(entry, str):
                        try:
                            entry = _json.loads(entry)
                        except Exception:
                            continue
                    if not isinstance(entry, dict):
                        continue
                    if "boundary" not in entry and "mowingAreas" not in entry:
                        continue
                    idx = entry.get("mapIndex", 0)
                    try:
                        idx_int = int(idx)
                    except (TypeError, ValueError):
                        idx_int = 0
                    raw_by_id[idx_int] = entry
            maps_by_id = parse_cloud_maps(raw_by_id) if raw_by_id else {}

        # M_PATH.*
        mow_paths_by_map_id: dict[int, Any] = {}
        if "M_PATH" in families:
            m_path_joined = join_family_chunks("M_PATH", batch)
            m_path_info = batch.get("M_PATH.info") or ""
            try:
                m_split = int(m_path_info) if str(m_path_info).isdigit() else 0
            except (TypeError, ValueError):
                m_split = 0
            mow_paths_by_map_id = parse_m_path_batch(m_path_joined, m_split)

        # SETTINGS.*
        settings_root: SettingsRoot
        if "SETTINGS" in families:
            settings_joined = join_family_chunks("SETTINGS", batch)
            try:
                import json as _json
                settings_raw = _json.loads(settings_joined)
            except Exception:
                settings_raw = []
            settings_root = parse_settings_batch(settings_raw)
        else:
            settings_root = SettingsRoot(raw=[], by_map_id_canonical={})

        # SCHEDULE.*
        schedule: ScheduleData
        if "SCHEDULE" in families:
            sched_joined = join_family_chunks("SCHEDULE", batch)
            try:
                import json as _json
                sched_raw = _json.loads(sched_joined)
            except Exception:
                sched_raw = {}
            schedule = parse_schedule_batch(sched_raw)
        else:
            schedule = ScheduleData(version=0, slots=())

        # AI_HUMAN — single chunk, JSON-encoded boolean.
        ai_human_enabled: bool | None = None
        if "AI_HUMAN" in families:
            ai_joined = join_family_chunks("AI_HUMAN", batch)
            try:
                import json as _json
                ai_human_enabled = bool(_json.loads(ai_joined))
            except Exception:
                ai_human_enabled = None

        # FBD_NTYPE — list of per-map dicts: [{<map0_dict>}, {<map1_dict>}].
        forbidden_node_types_by_map: dict[int, dict[str, Any]] = {}
        if "FBD_NTYPE" in families:
            fbd_joined = join_family_chunks("FBD_NTYPE", batch)
            try:
                import json as _json
                fbd_list = _json.loads(fbd_joined)
                if isinstance(fbd_list, list):
                    for i, entry in enumerate(fbd_list):
                        if isinstance(entry, dict):
                            forbidden_node_types_by_map[i] = entry
            except Exception:
                pass

        # OTA_INFO — `[status, percent]`.
        ota_status: tuple[int, int] | None = None
        if "OTA_INFO" in families:
            ota_joined = join_family_chunks("OTA_INFO", batch)
            try:
                import json as _json
                ota_list = _json.loads(ota_joined)
                if isinstance(ota_list, list) and len(ota_list) >= 2:
                    ota_status = (int(ota_list[0]), int(ota_list[1]))
            except Exception:
                pass

        # TASKID — int.
        task_id = 0
        if "TASKID" in families:
            tid_joined = join_family_chunks("TASKID", batch)
            try:
                import json as _json
                task_id = int(_json.loads(tid_joined))
            except Exception:
                pass

        # prop.s_* — standalone keys.
        props: dict[str, str] = {}
        if "prop" in families:
            for k in families["prop"]:
                v = batch.get(k)
                if isinstance(v, str):
                    props[k] = v

        # Fast-cadence probes (each a separate cloud call).
        # Errors here don't fail the whole fetch — fields just stay None/empty.
        try:
            locn = self.fetch_locn()
        except Exception:
            locn = None
        try:
            dock = self.fetch_dock() or {}
        except Exception:
            dock = {}
        try:
            mapl = self.fetch_mapl()
        except Exception:
            mapl = None
        try:
            mihis = self.fetch_mihis() or {}
        except Exception:
            mihis = {}

        import time as _time
        return CloudState(
            cfg=cfg,
            maps_by_id=maps_by_id,
            mow_paths_by_map_id=mow_paths_by_map_id,
            settings=settings_root,
            schedule=schedule,
            ai_human_enabled=ai_human_enabled,
            forbidden_node_types_by_map=forbidden_node_types_by_map,
            ota_status=ota_status,
            task_id=task_id,
            props=props,
            locn=locn,
            dock=dock,
            mapl=mapl,
            mihis=mihis,
            fetched_at_unix=int(_time.time()),
        )

    def fetch_mapl(self) -> list | None:
        """Fetch MAPL via routed-action s2 aiid=50 {m:'g', t:'MAPL'}.

        MAPL is the multi-map active-map list. Each row is a list of the
        form ``[map_id, is_active, ?, ?, ?]`` where ``is_active == 1``
        marks the currently-selected map.

        Returns the raw list-of-rows on success, or None on failure.
        Logs at DEBUG; does not raise.
        """
        from .protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "MAPL")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_mapl: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.debug("fetch_mapl: unexpected error: %s", ex)
            return None

        # MAPL may be returned as a bare list or wrapped in a `d` key.
        if isinstance(payload, list):
            _LOGGER.debug("[MAPL] payload (bare list): %r", payload)
            return payload
        if isinstance(payload, dict):
            inner = payload.get("d")
            if isinstance(inner, list):
                _LOGGER.debug("[MAPL] payload (d-wrapped): %r", inner)
                return inner
            _LOGGER.debug("fetch_mapl: unexpected dict shape: %r", payload)
            return None
        _LOGGER.debug("fetch_mapl: unexpected payload type: %r", type(payload).__name__)
        return None

    def set_cfg(self, key: str, value: Any) -> bool:
        """Write a single CFG key via routed-action s2 aiid=50.

        Wire format: ``{m: 's', t: key, d: <d_payload>}`` sent as
        ``in[0]`` of the siid=2 aiid=50 action call.

        ``value`` accepts two shapes:

        - **dict** — sent as ``d`` directly (named-key payload). Use
          this for complex CFG keys that take more than one slot:
          e.g. ``WRP {"value":1,"time":8,"sen":0}``,
          ``DND {"value":1,"time":[1200,480]}``,
          ``LIT {"value":1,"time":[480,1200],"light":[1,1,1,1],"fill":0}``.
          Source for the named-key catalog: ioBroker.dreame v0.3.7
          (see docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md).
        - **anything else** — wrapped as ``{"value": value}``. This is
          the path for simple keys that take a single int / bool /
          all-bool list (CLS, VOL, FDP, STUN, AOP, PROT, ATA,
          MSG_ALERT, VOICE).

        The value MUST always end up wrapped under a ``value`` key —
        without it the device returns ``r=-3`` (not supported)
        inside the routed-action response and the cloud silently
        retains the old value (smoking-gun probe 2026-05-09 against
        all 16 known-writable CFG keys).

        Returns True only when the device's routed-action response has
        ``out[0].r == 0`` — i.e. the device actually accepted the
        write. Pre-fix code only checked the top-level HTTP code which
        is always 0 even when the device rejected the action.

        Wire-format coverage on g2408 (confirmed live 2026-05-09):

        Working with the wrapped {value: X} format (primitive callers):
        - Single int / bool: CLS, VOL, FDP, STUN, AOP, PROT
        - All-bool list[3]: ATA
        - All-bool list[4]: MSG_ALERT, VOICE

        Hypothesised to work with the named-key dict format (post-2026-05-09;
        verify per-key before relying on it):
        - WRP, DND, LOW, LIT — see ioBroker catalog above
        - CMS reset, PRE — full-array writes (separate set_pre helper)

        Still unknown wire format (no app-side reference):
        - BAT (list[6] mixed), REC (list[9] mixed), LANG (list[2] mixed)

        For unsupported shapes the device returns r=-3 and set_cfg
        returns False — the entity-layer caller's optimistic update
        is reverted.

        Source: probe `/tmp/probe_cfg_writes.py` 2026-05-09; full
        evidence in docs/research/wire-captures/cfg-write-regression-2026-05-09.md
        and the ioBroker catalog at iobroker-write-catalog-2026-05-09.md.
        """
        if isinstance(value, dict):
            d_payload: Any = value
        else:
            d_payload = {"value": value}
        payload = {"m": "s", "t": key, "d": d_payload}
        try:
            result = self.action(siid=2, aiid=50, parameters=[payload])
            if result is None:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud returned None (80001?)", key, value
                )
                return False
            if not isinstance(result, dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: unexpected response shape: %r",
                    key, value, result,
                )
                return False
            # HTTP-layer code = always 0 on a reachable cloud; the actual
            # action result is in `out[0].r`.
            top_code = result.get("code")
            if top_code is not None and top_code != 0:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud HTTP error code %s", key, value, top_code,
                )
                return False
            outs = result.get("out") or []
            if not outs or not isinstance(outs[0], dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: missing or malformed `out` in response: %r",
                    key, value, result,
                )
                return False
            r = outs[0].get("r")
            if r != 0:
                msg = outs[0].get("msg") or outs[0].get("e") or ""
                _LOGGER.warning(
                    "set_cfg %s=%r: device rejected (out[0].r=%r msg=%r). "
                    "Wire format may be wrong for this CFG key — see "
                    "docs/research/wire-captures/cfg-write-regression-2026-05-09.md",
                    key, value, r, msg,
                )
                return False
            return True
        except Exception as ex:
            _LOGGER.warning("set_cfg %s=%r failed: %s", key, value, ex)
            return False

    def set_pre(self, pre_array: list) -> bool:
        """Write the full 10-element PRE preferences array.

        Delegates to ``protocol.cfg_action.set_pre`` which constructs the
        routed-action envelope ``{m:'s', t:'PRE', d:{value: pre_array}}``.

        The caller is responsible for read-modify-write semantics: read the
        current PRE array via fetch_cfg(), mutate the target element, and
        pass the full updated array here.

        Returns True on success, False on any failure.

        Source: protocol/cfg_action.py set_pre(); docs/research/g2408-protocol.md §6.2.
        """
        from .protocol import cfg_action  # type: ignore[import]

        try:
            result = cfg_action.set_pre(self.action, pre_array)
            if result is None:
                _LOGGER.warning("set_pre: cloud returned None (80001?)")
                return False
            return True
        except ValueError as ex:
            _LOGGER.warning("set_pre: invalid array: %s", ex)
            return False
        except Exception as ex:
            _LOGGER.warning("set_pre failed: %s", ex)
            return False

    # NOTE: set_property(siid, piid, value, retry_count) -> Any already
    # exists above (lines ~572–585). It returns None on failure (including
    # the 80001 error g2408 typically returns for direct set_properties
    # calls) and the cloud result dict on success.  The bool-returning
    # façade used by coordinator.write_setting is:
    #   success = (await hass.async_add_executor_job(
    #       self.set_property, siid, piid, value)) is not None

    def routed_action(
        self, op: int, extra: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Send a routed mow/utility action via siid=2 aiid=50.

        On g2408 this is the only cloud-RPC path that works for action
        invocation — direct ``action()`` for other siids returns 80001.

        Wire format per protocol/cfg_action.py ``call_action_op``:
        ``{m: 'a', p: 0, o: op, **extra}`` sent as ``in[0]`` of the
        siid=2 aiid=50 action call.

        ``op`` is the Dreame action opcode from apk §"Actions":
          100 = globalMower, 101 = edgeMower / zoneMower, 102 = zoneMower,
          11 = suppressFault, 9 = findBot, etc.

        ``extra`` (optional) is merged into the payload dict, e.g.
        ``{"region": [zone_id]}`` for zone-mow, or ``{"region_id": [1, 2]}``
        for multi-zone.

        Source: protocol/cfg_action.py ``call_action_op``; legacy
        dreame/device.py ``_ALT_ACTION_SIID_MAP`` and ``call_action``.
        """
        from .protocol.cfg_action import call_action_op  # type: ignore[import]
        self._last_send_error_code = None
        result = call_action_op(self.action, op, extra)
        key = f"routed_action_op={op}"
        if result is not None:
            self.endpoint_log[key] = "accepted"
        elif self._last_send_error_code == 80001:
            self.endpoint_log[key] = "rejected_80001"
        else:
            self.endpoint_log[key] = "error"
        return result

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
