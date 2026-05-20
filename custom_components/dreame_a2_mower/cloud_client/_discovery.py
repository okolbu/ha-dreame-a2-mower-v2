"""Device discovery mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

import json
from typing import Any

from ._helpers import _LOGGER


class _DiscoveryMixin:
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
