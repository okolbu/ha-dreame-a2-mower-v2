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
from typing import Any, Optional, Tuple

import requests

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
# Cloud strings blob
# ---------------------------------------------------------------------------

# DREAME_STRINGS is the gzip-compressed, base64-encoded JSON array of
# obfuscated API endpoint fragments, header names, and field keys.  Imported
# from const.py so it lives in one place.
from .const import DREAME_STRINGS as _DREAME_STRINGS_B64


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
        did: Optional[str] = None,
    ) -> None:
        self.two_factor_url: Optional[str] = None
        self._username = username
        self._password = password
        self._country = country
        self._location = country
        self._did = did
        self._session = requests.session()
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[Thread] = None
        self._id = random.randint(1, 100)
        self._host: Optional[str] = None
        self._model: Optional[str] = None
        self._ti: Optional[str] = None
        self._fail_count = 0
        self._connected = False
        self._logged_in: Optional[bool] = None
        self._stream_key: Optional[str] = None
        self._secondary_key: Optional[str] = None
        self._key_expire: Optional[float] = None
        self._key: Optional[str] = None
        self._uid: Optional[str] = None
        self._uuid: Optional[str] = None
        self._strings: Optional[list] = None
        self.endpoint_log: dict[str, str] = {}
        """F6.8.1 endpoint accept/reject log. Key e.g. ``"routed_action_op=100"``,
        value ``"accepted" | "rejected_80001" | "error"``."""
        self._last_send_error_code: Optional[int] = None
        """F6.8.1 transport-layer last error code. Updated by ``send`` so callers
        that get None back can disambiguate 80001 from other failures."""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> Optional[str]:
        return self._did

    @property
    def uid(self) -> Optional[str]:
        return self._uid

    @property
    def model(self) -> Optional[str]:
        return self._model

    @property
    def country(self) -> str:
        return self._country

    @property
    def logged_in(self) -> Optional[bool]:
        return self._logged_in

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def object_name(self) -> str:
        return f"{self._model}/{self._uid}/{str(self._did)}/0"

    # ------------------------------------------------------------------
    # MQTT bootstrap helpers — used by DreameA2MqttClient
    # ------------------------------------------------------------------

    def mqtt_host_port(self) -> Tuple[str, int]:
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

    def mqtt_credentials(self) -> Tuple[str, str]:
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
        _LOGGER.info(
            "cloud _handle_device_info: did=%r model=%r _host=%r",
            self._did, self._model, self._host,
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
        if response:
            if "data" in response and response["code"] == 0:
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

    def get_info(self, mac: str) -> Tuple[Optional[str], Optional[str]]:
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
        parameters: list = None,
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
        parameters: list = None,
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

    def get_interim_file_url(self, object_name: str = "") -> Optional[str]:
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
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[26]}/{strings[45]}",
            {"did": self._did, strings[35]: props},
        )
        if api_response is None or "result" not in api_response:
            return None
        return api_response["result"]

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

    def fetch_cfg(self) -> "dict[str, Any] | None":
        """Fetch CFG via the routed-action s2 aiid=50 {m:'g', t:'CFG'} path.

        Returns the parsed ``d`` field (a dict of CFG keys) on success,
        or None on failure. Logs warnings; does not raise.

        This uses the ``action`` cloud-RPC path (siid=2, aiid=50), which
        is the only cloud surface confirmed to work on g2408 — regular
        ``set_properties`` / ``action`` for other siids returns 80001.

        Source: docs/research/g2408-protocol.md §6.2; legacy
        dreame/device.py:refresh_cfg for request shape.
        """
        from .protocol.cfg_action import get_cfg, CfgActionError  # type: ignore[import]

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

    def fetch_locn(self) -> "dict[str, Any] | None":
        """Fetch LOCN via the routed-action s2 aiid=50 {m:'g', t:'LOCN'} path.

        Returns a dict containing a ``pos`` key (e.g. ``{"pos": [lon, lat]}``)
        on success, or None on failure. Logs warnings; does not raise.

        The sentinel value ``pos: [-1, -1]`` means the dock GPS origin has
        not been configured — callers should treat this as "no position".

        Source: docs/research/g2408-protocol.md §2.1 LOCN; legacy
        dreame/device.py:refresh_locn for request shape and response handling.
        """
        from .protocol.cfg_action import probe_get, CfgActionError  # type: ignore[import]

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

    def fetch_map(self) -> "dict[str, Any] | None":
        """Fetch the cloud MAP.* batch and return the decoded map dict.

        Calls ``get_batch_device_datas`` with keys ``MAP.0`` … ``MAP.27``,
        joins the 28 string fragments, JSON-decodes them (handling the
        wrapped-list form some firmware versions emit), and returns the
        resulting dict.  Returns None on any failure.

        The returned dict is what ``map_decoder.parse_cloud_map`` expects —
        i.e. it should have keys like ``boundary``, ``mowingAreas``, etc.

        Source: legacy dreame/device.py lines 2341-2399 (MAP.* fetch path).
        """
        try:
            map_keys = [f"MAP.{i}" for i in range(28)]
            batch = self.get_batch_device_datas(map_keys)
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_map: get_batch_device_datas error: %s", ex)
            return None

        if not batch:
            _LOGGER.debug("fetch_map: empty cloud response")
            return None

        # Join the 28 string parts and JSON-decode.
        parts = [batch.get(f"MAP.{i}", "") or "" for i in range(28)]
        raw = "".join(parts)
        if not raw:
            _LOGGER.debug("fetch_map: all MAP.* keys empty")
            return None

        try:
            import json as _json
            decoder = _json.JSONDecoder()
            parsed, _ = decoder.raw_decode(raw)
        except (ValueError, _json.JSONDecodeError) as ex:
            _LOGGER.warning("fetch_map: JSON decode failed: %s", ex)
            return None

        if isinstance(parsed, list):
            # Wrapped form: try each element.
            for item in parsed:
                if isinstance(item, str):
                    try:
                        import json as _json2
                        candidate = _json2.loads(item)
                        if isinstance(candidate, dict) and (
                            "boundary" in candidate or "mowingAreas" in candidate
                        ):
                            _LOGGER.debug("fetch_map: decoded wrapped-list MAP (%d keys)", len(candidate))
                            return candidate
                    except (ValueError, Exception):
                        continue
                elif isinstance(item, dict) and (
                    "boundary" in item or "mowingAreas" in item
                ):
                    _LOGGER.debug("fetch_map: decoded wrapped-list MAP dict (%d keys)", len(item))
                    return item
            _LOGGER.debug("fetch_map: list form but no usable map entry")
            return None

        if isinstance(parsed, dict):
            _LOGGER.debug("fetch_map: decoded MAP dict (%d keys)", len(parsed))
            return parsed

        _LOGGER.warning("fetch_map: unexpected JSON root type: %s", type(parsed).__name__)
        return None

    def set_cfg(self, key: str, value: Any) -> bool:
        """Write a single CFG key via routed-action s2 aiid=50.

        Wire format: ``{m: 's', t: key, d: value}`` sent as ``in[0]`` of
        the siid=2 aiid=50 action call (the SET variant of the GET used by
        fetch_cfg).

        Returns True on cloud success (result dict with code==0), False on
        any failure (cloud error, timeout, 80001, etc.).

        Confirmed working on g2408 for CFG keys: CLS (child lock), VOL
        (volume), LANG (language). PRE writes use set_pre() instead.

        Source: docs/research/g2408-protocol.md §6.2; legacy
        dreame/device.py setCFG-routed-action pattern.
        """
        payload = {"m": "s", "t": key, "d": value}
        try:
            result = self.action(siid=2, aiid=50, parameters=[payload])
            # action() returns None on failure; on success it returns a dict
            # (or list) from the cloud. A dict with code==0 is unambiguous
            # success; any non-None result is treated as success here because
            # the g2408 CFG write ack shape varies across firmware versions.
            if result is None:
                _LOGGER.warning("set_cfg %s=%r: cloud returned None (80001?)", key, value)
                return False
            if isinstance(result, dict):
                code = result.get("code")
                if code is not None and code != 0:
                    _LOGGER.warning("set_cfg %s=%r: cloud error code %s", key, value, code)
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
        self, op: int, extra: "dict[str, Any] | None" = None
    ) -> "dict[str, Any] | None":
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
