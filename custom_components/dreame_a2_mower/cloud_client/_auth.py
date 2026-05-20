"""Auth mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

import hashlib
import json
import time

import requests

from ._helpers import _LOGGER


class _AuthMixin:
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
