"""Batch device-data primitives mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

from typing import Any

from ._helpers import _LOGGER


class _BatchMixin:

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
