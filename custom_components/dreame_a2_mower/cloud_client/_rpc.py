"""Transport / RPC mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

import json
import logging
import time
from threading import Thread
from time import sleep
from typing import Any

import requests

from ._helpers import _LOGGER, _http_retry


class _RpcMixin:

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

        class _SendFailed(Exception):
            """Raised when an action send returns a non-success, retryable response."""

        def _send_once() -> Any:
            self._id = self._id + 1
            inner_retry_count = 0 if method == "action" else retry_count
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
                inner_retry_count,
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
                    "Cloud send error %s for %s: %s",
                    error_code, method, api_response.get("msg", "") if api_response else "",
                )
                # 80001 = "device unreachable via cloud relay".
                # On g2408 this is permanent — fast-return None without retrying.
                if error_code == 80001:
                    return None
            raise _SendFailed(error_code)

        if method == "action":
            try:
                return _http_retry(
                    _send_once,
                    max_attempts=3,
                    delay_s=8.0,
                    should_retry=lambda exc: isinstance(exc, _SendFailed),
                )
            except _SendFailed as exc:
                # Cloud returned a non-success after retries (error_code
                # already logged at WARNING above when present). A code bug
                # parsing the response is NOT caught here — it propagates.
                _LOGGER.debug("send action: no result after retries (%s)", exc)
                return None
        else:
            try:
                return _send_once()
            except _SendFailed as exc:
                _LOGGER.debug("send %s: no result (%s)", method, exc)
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

    def request(self, url: str, data: Any, retry_count: int = 2) -> Any:
        """POST to a Dreame cloud API endpoint with token-auth headers.

        Auto-refreshes the session token when ``_key_expire`` is past.
        Returns parsed JSON or ``None`` on failure.

        Source: legacy ``dreame/protocol.py`` ``DreameMowerDreameHomeCloudProtocol.request()``.
        """
        strings = self._ensure_strings()
        if not retry_count or retry_count < 0:
            retry_count = 0

        def _do_post() -> Any:
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
            return self._session.post(
                url, headers=headers, data=data, timeout=15
            )

        def _log_and_retry(exc: BaseException) -> bool:
            if isinstance(exc, requests.exceptions.Timeout):
                if self._connected:
                    _LOGGER.warning(
                        "Error while executing request: Read timed out. "
                        "(read timeout=15): %s",
                        data,
                    )
            elif self._connected:
                _LOGGER.warning("Error while executing request: %s", str(exc))
            return True

        try:
            response = _http_retry(
                _do_post,
                max_attempts=retry_count + 1,
                should_retry=_log_and_retry,
            )
        except requests.exceptions.RequestException:
            # Transport failure already logged by _log_and_retry; a code bug
            # in _do_post would propagate instead of being masked as None.
            response = None

        if response is not None:
            if response.status_code == 200:
                self._fail_count = 0
                self._connected = True
                parsed = json.loads(response.text)
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    from ..protocol.api_log import summarize_api_response
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
        from ..protocol.cfg_action import call_action_op  # type: ignore[import]
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
