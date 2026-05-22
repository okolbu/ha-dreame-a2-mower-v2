"""OSS / WiFi-map mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

from typing import Any

import requests

from ._helpers import _LOGGER, _http_retry


class _OssMixin:

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

    def _download_wifi_object(
        self, map_id: int, obj_name: str
    ) -> dict[str, Any] | None:
        """Download + decode a wifimap OSS object, with per-(map_id, name) dedup.

        If ``list_wifi_candidates`` already decoded the object under a
        different map_id (e.g., during picker refresh), the cached body
        is reused — only the ``_map_id`` stamp is updated.
        """
        cache = getattr(self, "_wifi_map_cache", None)
        if cache is None:
            self._wifi_map_cache: dict[tuple[int, str], dict[str, Any]] = {}
            cache = self._wifi_map_cache
        cache_key = (map_id, obj_name)
        if cache_key in cache:
            _LOGGER.debug(
                "fetch_wifi_map: cache hit for map %d / %s", map_id, obj_name
            )
            return cache[cache_key]
        # Reuse a previously-decoded body for this object_name under a
        # different cache_key (typical when the archive picker pre-decoded
        # it under map_id=None or another map_id).
        for (_cached_mid, cached_name), cached_dec in list(cache.items()):
            if cached_name == obj_name:
                stamped = dict(cached_dec)
                stamped["_map_id"] = map_id
                cache[cache_key] = stamped
                return stamped

        url = self.get_interim_file_url(obj_name)
        if not url:
            _LOGGER.warning("fetch_wifi_map: no OSS URL for %s", obj_name)
            return None
        body = self.get_file(url)
        if not body:
            _LOGGER.warning("fetch_wifi_map: download empty for %s", obj_name)
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
        decoded["_object_name"] = obj_name
        decoded["_map_id"] = map_id
        cache[cache_key] = decoded
        return decoded

    def fetch_wifi_map(
        self,
        map_id: int,
        map_extent: tuple[float, float, float, float] | None = None,
        all_map_extents: "dict[int, tuple[float, float, float, float]] | None" = None,
    ) -> dict[str, Any] | None:
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
              "resolution": int,     # METRES per cell on g2408 (value 2
                                     # observed → 2m × 2m cells; user-
                                     # confirmed against actual lawn).
              "startX": int,         # bbox origin in cm (cloud frame).
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

        When ``all_map_extents`` is supplied, candidate selection is
        delegated to ``list_wifi_candidates`` so that geometry +
        positional tier-2 fallback is applied uniformly. This is the
        path used by the multi-map coordinator. Legacy callers that
        pass only ``map_extent`` use the single-map geometry-match
        path preserved below.
        """
        # Unified multi-map path: positional fallback baked in via
        # list_wifi_candidates. Both the archive picker and the live
        # camera resolve heatmap → map_id through the same logic.
        if all_map_extents is not None:
            entries = self.list_wifi_candidates(map_extents=all_map_extents)
            if not entries:
                _LOGGER.debug(
                    "fetch_wifi_map[map_id=%d]: no wifimap objects in cloud",
                    map_id,
                )
                return None
            match = next(
                (e for e in entries if e.get("map_id") == map_id),
                None,
            )
            if match is None:
                # No match for this map even after positional fallback.
                # This means the candidate count didn't equal the map
                # count; fall back to the newest object.
                chosen_name = entries[0]["object_name"]
                _LOGGER.info(
                    "fetch_wifi_map[map_id=%d]: no candidate matched "
                    "(geometry + positional both failed) — using newest %s",
                    map_id, chosen_name,
                )
            else:
                chosen_name = match["object_name"]
                _LOGGER.info(
                    "fetch_wifi_map[map_id=%d]: matched %s via %s",
                    map_id, chosen_name, match.get("_assigned_by") or "default",
                )
            return self._download_wifi_object(map_id, chosen_name)

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
        # Build candidate list (newest-first per ioBroker observation).
        candidates: list[str] = []
        if isinstance(names, list):
            candidates = [n for n in names if isinstance(n, str)]
        elif isinstance(names, dict):
            candidates = [v for v in names.values() if isinstance(v, str)]
        if not candidates:
            return None

        # Pick the right OSS object for this map_id. The cloud returns
        # multiple wifimap objects (one or more per map). Each object has
        # `startX/startY` (cm in cloud frame) and `width*resolution` /
        # `height*resolution` for its physical bbox. We download each
        # candidate's metadata and pick the one whose bbox center falls
        # inside the requested map's boundary bbox (`map_extent`).
        #
        # When `map_extent` is None (e.g., legacy callers), fall back to
        # the newest object — preserves prior behavior.
        import json as _json_pick

        def _decode_or_none(obj_name: str) -> dict[str, Any] | None:
            url = self.get_interim_file_url(obj_name)
            if not url:
                return None
            body = self.get_file(url)
            if not body:
                return None
            try:
                dec = _json_pick.loads(body)
            except Exception as e:
                _LOGGER.debug("_decode_or_none(%s): JSON/LZ4 decode failed: %s", obj_name, e)
                return None
            if isinstance(dec, dict) and "data" in dec:
                dec["_object_name"] = obj_name
                return dec
            return None

        chosen_decoded: dict[str, Any] | None = None
        chosen_name: str | None = None
        if map_extent is not None and len(candidates) > 1:
            ex_x1, ex_y1, ex_x2, ex_y2 = map_extent
            # Order extent so x1<=x2, y1<=y2 (cloud frames are usually
            # already ordered but defensive).
            ex_x1, ex_x2 = sorted((ex_x1, ex_x2))
            ex_y1, ex_y2 = sorted((ex_y1, ex_y2))
            for cand in candidates:
                dec = _decode_or_none(cand)
                if dec is None:
                    continue
                # Cloud body schema:
                #   startX, startY     — bbox origin in cm (cloud frame)
                #   width, height      — cell counts
                #   resolution         — cell size in METRES per cell on g2408
                # User-confirmed 2026-05-12 against actual lawn
                # dimensions; the earlier "decimeter" reading was wrong
                # by 10× (would have made the garden smaller than the
                # mower itself — see wifi-heatmap-todo.md Issue #1).
                try:
                    start_x_cm = float(dec.get("startX", 0))
                    start_y_cm = float(dec.get("startY", 0))
                    cells_w = int(dec.get("width", 0))
                    cells_h = int(dec.get("height", 0))
                    cell_size_m = int(dec.get("resolution", 1)) or 1
                except (TypeError, ValueError) as e:
                    _LOGGER.debug("fetch_wifi_map: skipping candidate %s: malformed cell geometry: %s", cand, e)
                    continue
                cell_size_cm = cell_size_m * 100
                bbox_w_cm = cells_w * cell_size_cm
                bbox_h_cm = cells_h * cell_size_cm
                centre_x_cm = start_x_cm + bbox_w_cm / 2.0
                centre_y_cm = start_y_cm + bbox_h_cm / 2.0
                inside = (
                    ex_x1 <= centre_x_cm <= ex_x2
                    and ex_y1 <= centre_y_cm <= ex_y2
                )
                _LOGGER.info(
                    "fetch_wifi_map[map_id=%d]: candidate %s "
                    "startX=%s startY=%s w=%d h=%d cell_size_m=%d → "
                    "centre_cm=(%.0f,%.0f) inside map_extent=(%.0f,%.0f,%.0f,%.0f)? %s",
                    map_id, cand, start_x_cm, start_y_cm, cells_w, cells_h,
                    cell_size_m, centre_x_cm, centre_y_cm,
                    ex_x1, ex_y1, ex_x2, ex_y2, inside,
                )
                if inside:
                    chosen_decoded = dec
                    chosen_name = cand
                    break
        if chosen_decoded is None:
            # Fallback: newest candidate (preserves legacy behavior when
            # map_extent is None, or when no candidate matched).
            chosen_name = candidates[0]
            _LOGGER.info(
                "fetch_wifi_map[map_id=%d]: no geometry match — falling back "
                "to newest candidate %s",
                map_id, chosen_name,
            )
        first = chosen_name
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

        # If geometry matching already decoded this candidate, reuse it
        # instead of re-downloading.
        if chosen_decoded is not None:
            chosen_decoded["_map_id"] = map_id
            cache[cache_key] = chosen_decoded
            return chosen_decoded

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

    def list_wifi_candidates(
        self,
        map_extents: "dict[int, tuple[float, float, float, float]] | None" = None,
    ) -> "list[dict]":
        """Return metadata for every wifimap object in the cloud, sorted newest-first.

        Calls the same OBJ probe as ``fetch_wifi_map`` but returns ALL objects
        (one per map, typically), not just the one that matches a given map_id.
        Each returned dict has:
            {
                "object_name": str,
                "unix_ts": int,       # parsed from filename; 0 if not parseable
                "map_id": int | None, # geometry-matched against map_extents
                "startX": float, "startY": float,
                "width": int, "height": int, "resolution": int,
            }

        map_extents: dict mapping map_id → (x1, y1, x2, y2) in cm (cloud frame).
        If empty or None, map_id is left as None for all candidates.
        """
        import re as _re
        import json as _json_lc
        try:
            obj_resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "OBJ", "d": {"type": "wifimap"}}],
            )
        except Exception as ex:
            _LOGGER.warning("list_wifi_candidates: OBJ probe error: %s", ex)
            return []
        if not isinstance(obj_resp, dict):
            return []
        outs = obj_resp.get("out") or []
        if not outs or not isinstance(outs[0], dict):
            return []
        names = (outs[0].get("d") or {}).get("name")
        if not names:
            return []
        candidates: "list[str]" = []
        if isinstance(names, list):
            candidates = [n for n in names if isinstance(n, str)]
        elif isinstance(names, dict):
            candidates = [v for v in names.values() if isinstance(v, str)]
        if not candidates:
            return []

        def _decode_candidate(obj_name: str) -> "dict[str, Any] | None":
            cache = getattr(self, "_wifi_map_cache", None)
            if cache is not None:
                for (mid, cached_name), cached_dec in cache.items():
                    if cached_name == obj_name:
                        return cached_dec
            url = self.get_interim_file_url(obj_name)
            if not url:
                return None
            body = self.get_file(url)
            if not body:
                return None
            try:
                dec = _json_lc.loads(body)
            except Exception as e:
                _LOGGER.debug("_decode_candidate(%s): JSON/LZ4 decode failed: %s", obj_name, e)
                return None
            if isinstance(dec, dict) and "data" in dec:
                dec["_object_name"] = obj_name
                return dec
            return None

        def _parse_unix_ts(obj_name: str) -> int:
            """Extract a unix timestamp from the object's filename component."""
            # Typical pattern: something/wifimap_<digits>.json or _<digits>_...
            m = _re.search(r"_(\d{9,11})(?:[._]|$)", obj_name)
            if m:
                return int(m.group(1))
            # Fallback: any 10-digit run.
            m = _re.search(r"\b(\d{10})\b", obj_name)
            if m:
                return int(m.group(1))
            return 0

        results: "list[dict]" = []
        extents = map_extents or {}
        for obj_name in candidates:
            dec = _decode_candidate(obj_name)
            if dec is None:
                continue
            # Cloud body schema:
            #   startX, startY     — bbox origin in cm (cloud frame)
            #   width, height      — cell counts
            #   resolution         — cell size in METRES per cell on g2408
            # (see fetch_wifi_map comment + wifi-heatmap-todo.md Issue #1).
            try:
                start_x_cm = float(dec.get("startX", 0))
                start_y_cm = float(dec.get("startY", 0))
                cells_w = int(dec.get("width", 0))
                cells_h = int(dec.get("height", 0))
                cell_size_m = int(dec.get("resolution", 1)) or 1
            except (TypeError, ValueError) as e:
                _LOGGER.debug("_decode_candidate(%s): malformed cell geometry, using fallback zeros: %s", obj_name, e)
                start_x_cm = start_y_cm = 0.0
                cells_w = cells_h = 0
                cell_size_m = 1

            # Geometry-match: find which map's extent contains this heatmap's centre.
            matched_map_id: "int | None" = None
            if extents:
                cell_size_cm = cell_size_m * 100
                bbox_w_cm = cells_w * cell_size_cm
                bbox_h_cm = cells_h * cell_size_cm
                centre_x_cm = start_x_cm + bbox_w_cm / 2.0
                centre_y_cm = start_y_cm + bbox_h_cm / 2.0
                for mid, (ex_x1, ex_y1, ex_x2, ex_y2) in extents.items():
                    x1, x2 = sorted((ex_x1, ex_x2))
                    y1, y2 = sorted((ex_y1, ex_y2))
                    if x1 <= centre_x_cm <= x2 and y1 <= centre_y_cm <= y2:
                        matched_map_id = mid
                        break

            results.append({
                "object_name": obj_name,
                "unix_ts": _parse_unix_ts(obj_name),
                "map_id": matched_map_id,
                "_assigned_by": "geometry" if matched_map_id is not None else None,
                "startX": start_x_cm,
                "startY": start_y_cm,
                "width": cells_w,
                "height": cells_h,
                "resolution": cell_size_m,
            })

        # Tier-2 positional fallback: when geometry matching leaves
        # ambiguity (e.g., overlapping or co-located map extents),
        # assign by array position iff the count of unmatched
        # candidates equals the count of unmatched maps. The cloud's
        # OBJ array order is "newest-first" globally, but when there
        # is exactly one heatmap per map this collapses to a stable
        # 1:1 mapping. Sorted map_ids ensure determinism.
        if extents and results:
            unmatched_map_ids = sorted(
                mid for mid in extents.keys()
                if not any(r.get("map_id") == mid for r in results)
            )
            unmatched_results = [r for r in results if r.get("map_id") is None]
            if (
                unmatched_map_ids
                and len(unmatched_map_ids) == len(unmatched_results)
            ):
                for r, mid in zip(unmatched_results, unmatched_map_ids):
                    r["map_id"] = mid
                    r["_assigned_by"] = "positional"
                    _LOGGER.info(
                        "list_wifi_candidates: positional fallback "
                        "assigned %s → map_id=%d",
                        r["object_name"], mid,
                    )

        results.sort(key=lambda r: r["unix_ts"], reverse=True)
        return results

    def get_file(self, url: str, retry_count: int = 4) -> Any:
        """Download raw bytes from a signed OSS URL.

        Source: legacy ``dreame/protocol.py`` ``get_file()``.
        """
        if not retry_count or retry_count < 0:
            retry_count = 0

        class _NonOKStatus(Exception):
            """Raised inside the action lambda when HTTP status != 200."""

        def _do_get() -> bytes:
            response = self._session.get(url, timeout=15)
            if response.status_code != 200:
                raise _NonOKStatus(response.status_code)
            return response.content

        def _log_and_retry(exc: BaseException) -> bool:
            if isinstance(exc, _NonOKStatus):
                _LOGGER.warning(
                    "Unable to get file at %s: HTTP %s", url, exc.args[0]
                )
            else:
                _LOGGER.warning("Unable to get file at %s: %s", url, exc)
            return True

        try:
            return _http_retry(
                _do_get,
                max_attempts=retry_count + 1,
                should_retry=_log_and_retry,
            )
        except (_NonOKStatus, requests.exceptions.RequestException):
            # HTTP non-200 / transport failure already logged by
            # _log_and_retry; a code bug in _do_get would propagate.
            return None
