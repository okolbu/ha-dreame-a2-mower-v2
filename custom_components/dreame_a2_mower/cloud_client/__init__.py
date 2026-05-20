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

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin, _BatchMixin):
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
        from ..protocol.cfg_action import CfgActionError, get_cfg  # type: ignore[import]

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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        except (TypeError, ValueError) as e:
            _LOGGER.debug("fetch_map: MAP.info parse failed %r: %s", info_raw, e)
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
            except (ValueError, _json.JSONDecodeError) as e:
                _LOGGER.debug("fetch_map: skipping malformed segment: %s", e)
                continue
            # Cloud wraps each map as a 1-element list.
            entries = parsed if isinstance(parsed, list) else [parsed]
            for entry in entries:
                # Cloud sometimes returns a list-of-JSON-strings (each
                # string is a wrapped map dict). Decode if needed.
                if isinstance(entry, str):
                    try:
                        entry = _json.loads(entry)
                    except (ValueError, _json.JSONDecodeError) as e:
                        _LOGGER.debug("fetch_map: skipping malformed double-encoded entry: %s", e)
                        continue
                if not isinstance(entry, dict):
                    continue
                if "boundary" not in entry and "mowingAreas" not in entry:
                    continue
                idx = entry.get("mapIndex", 0)
                try:
                    idx_int = int(idx)
                except (TypeError, ValueError) as e:
                    _LOGGER.debug("fetch_map: mapIndex cast failed %r: %s", idx, e)
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
        from ..cloud_state import CloudState, ScheduleData, SettingsRoot
        from ..map_decoder import parse_cloud_maps
        from ..protocol.batch_grouper import group_keys_by_prefix, join_family_chunks
        from ..protocol.m_path import parse_m_path_batch
        from ..protocol.schedule import parse_schedule_batch
        from ..protocol.settings import parse_settings_batch

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
            except (TypeError, ValueError) as e:
                _LOGGER.debug("parse_full_cloud_state: MAP.info parse failed %r: %s", map_info_raw, e)
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
                        except Exception as e:
                            _LOGGER.debug("parse_full_cloud_state: MAP entry double-decode failed: %s", e)
                            continue
                    if not isinstance(entry, dict):
                        continue
                    if "boundary" not in entry and "mowingAreas" not in entry:
                        continue
                    idx = entry.get("mapIndex", 0)
                    try:
                        idx_int = int(idx)
                    except (TypeError, ValueError) as e:
                        _LOGGER.debug("parse_full_cloud_state: mapIndex cast failed %r: %s", idx, e)
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
            except (TypeError, ValueError) as e:
                _LOGGER.debug("parse_full_cloud_state: M_PATH.info parse failed %r: %s", m_path_info, e)
                m_split = 0
            mow_paths_by_map_id = parse_m_path_batch(m_path_joined, m_split)

        # SETTINGS.*
        settings_root: SettingsRoot
        if "SETTINGS" in families:
            settings_joined = join_family_chunks("SETTINGS", batch)
            try:
                import json as _json
                settings_raw = _json.loads(settings_joined)
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: SETTINGS JSON parse failed: %s", e, exc_info=True)
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
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: SCHEDULE JSON parse failed: %s", e, exc_info=True)
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
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: AI_HUMAN JSON parse failed: %s", e)
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
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: FBD_NTYPE JSON parse failed: %s", e, exc_info=True)
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
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: OTA_INFO JSON parse failed: %s", e)
                pass

        # TASKID — int.
        task_id = 0
        if "TASKID" in families:
            tid_joined = join_family_chunks("TASKID", batch)
            try:
                import json as _json
                task_id = int(_json.loads(tid_joined))
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: TASKID JSON parse failed: %s", e)
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
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_locn raised: %s", e)
            locn = None
        try:
            dock = self.fetch_dock() or {}
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_dock raised: %s", e)
            dock = {}
        try:
            mapl = self.fetch_mapl()
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_mapl raised: %s", e)
            mapl = None
        try:
            mihis = self.fetch_mihis() or {}
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_mihis raised: %s", e)
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
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

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
        from ..protocol import cfg_action  # type: ignore[import]

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
