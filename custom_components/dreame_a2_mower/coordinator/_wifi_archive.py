"""WiFi archive refresh mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import time as _time_module_alias  # avoid shadowing if class body imports `time`
from typing import TYPE_CHECKING, Any

from ..const import LOGGER

if TYPE_CHECKING:
    pass  # cross-mixin type imports — none needed for this mixin


class _WifiArchiveMixin:
    """Periodic WiFi-heatmap archive refresh + per-session sample read."""

    async def refresh_wifi_archive(self) -> dict:
        """Fetch all cloud wifimap objects and archive new ones to disk.

        Idempotent: objects already on disk are skipped. Returns:
            {"fetched": int, "new": int, "archive_total": int}
        """
        import time as _time

        if self._wifi_archive_store is None or not hasattr(self, "_cloud"):
            return {"fetched": 0, "new": 0, "archive_total": 0}

        extents = self._build_map_extents()
        candidates = await self.hass.async_add_executor_job(
            lambda: self._cloud.list_wifi_candidates(map_extents=extents)
        )
        if not isinstance(candidates, list):
            candidates = []

        new_count = 0
        now_ts = int(_time.time())
        for cand in candidates:
            obj_name = cand.get("object_name") if isinstance(cand, dict) else None
            if not isinstance(obj_name, str):
                continue
            if self._wifi_archive_store.has_object(obj_name):
                continue
            body = await self.hass.async_add_executor_job(
                self._download_and_archive_wifi, obj_name, now_ts
            )
            if body is not None:
                new_count += 1

        self._wifi_archive_index = self._wifi_archive_store.load_index()

        # v1.0.10a6+: tag each archive entry with its best-fit map_id
        # via RSSI fingerprint match against recent session samples.
        # Runs after each refresh so newly-downloaded heatmaps get a
        # map_id immediately, AND previously-archived entries that had
        # no session samples to compare against can be retroactively
        # tagged once back-fill samples are available.
        try:
            matched = await self.hass.async_add_executor_job(
                self._tag_wifi_archive_map_ids
            )
            if matched:
                # Reload index so consumers see the freshly-stamped map_id.
                self._wifi_archive_index = self._wifi_archive_store.load_index()
        except Exception:
            LOGGER.exception("refresh_wifi_archive: fingerprint matcher failed")

        result = "downloaded" if new_count > 0 else "no_data"
        self._wifi_archive_last_refresh = {
            "last_attempt_unix": int(_time.time()),
            "result": result,
            "fetched": len(candidates),
            "new": new_count,
        }
        self.async_update_listeners()

        return {
            "fetched": len(candidates),
            "new": new_count,
            "archive_total": len(self._wifi_archive_index),
        }

    def _download_and_archive_wifi(
        self, object_name: str, first_seen_unix: int
    ) -> dict | None:
        """Executor-side: download body from OSS and write to disk."""
        url = self._cloud.get_interim_file_url(object_name)
        if not url:
            return None
        raw = self._cloud.get_file(url)
        if not raw:
            return None
        try:
            import json as _json
            body = _json.loads(raw)
        except Exception:
            return None
        if not isinstance(body, dict) or "data" not in body:
            return None
        self._wifi_archive_store.archive(object_name, body, first_seen_unix)
        return body

    # --------------- v1.0.10a6+: fingerprint matcher plumbing ---------------

    # How many recent sessions to score against each heatmap. 30 is a
    # generous ceiling — beyond that the dock has typically moved or
    # the mower was reset and old samples no longer reflect the
    # current RF environment. Tuneable if user feedback indicates
    # otherwise.
    _WIFI_MATCH_RECENT_SESSIONS = 30

    def _read_session_wifi_samples(
        self, filename: str
    ) -> list[tuple[float, float, int, int]]:
        """Read one session blob from disk and extract wifi_samples.

        Tolerates missing / legacy blobs (no wifi_samples key, garbage
        rows). Executor-side; called from the matcher loop.
        """
        path = self.session_archive.root / filename
        try:
            import json as _json
            body = _json.loads(path.read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(body, dict):
            return []
        raw = body.get("wifi_samples")
        if not isinstance(raw, list):
            return []
        out: list[tuple[float, float, int, int]] = []
        for row in raw:
            try:
                out.append((float(row[0]), float(row[1]), int(row[2]), int(row[3])))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def _tag_wifi_archive_map_ids(self) -> int:
        """Score each WifiArchiveEntry against the most-recent sessions
        and write back ``map_id`` when the matcher finds a winner.

        Executor-side (blocking disk reads + writes). Returns the
        number of entries whose map_id was updated.

        Strategy:
        1. Load the current archive index. Skip entries that already
           have map_id >= 0 (those were tagged on a prior refresh).
        2. Load the N most-recent finalized sessions from
           ``self.session_archive`` and pull each session's
           wifi_samples + map_id from its on-disk blob.
        3. For each un-tagged heatmap entry, load its body, build a
           candidate list ``[(session_map_id, samples), …]``, and
           invoke ``match_heatmap_to_session``.
        4. If the matcher returns a non-None map_id, persist it via
           ``WifiArchiveStore.set_map_id``.
        """
        from ..wifi_match import match_heatmap_to_session

        store = self._wifi_archive_store
        if store is None:
            return 0

        # Step 1: snapshot the index.
        entries = store.load_index()
        if not entries:
            return 0
        # Skip already-tagged.
        untagged = [e for e in entries if int(getattr(e, "map_id", -1)) < 0]
        if not untagged:
            return 0

        # Step 2: collect (session_map_id, samples) for recent sessions.
        try:
            self.session_archive.load_index()
        except Exception:
            return 0
        recent_sessions = self.session_archive.list_sessions()[
            : self._WIFI_MATCH_RECENT_SESSIONS
        ]
        # Skip the synthesized in-progress entry (still_running=True);
        # it has no archived JSON blob to read samples from.
        session_candidates: list[
            tuple[int, list[tuple[float, float, int, int]]]
        ] = []
        for s in recent_sessions:
            if getattr(s, "still_running", False):
                continue
            sid = int(getattr(s, "map_id", -1))
            if sid < 0:
                continue
            samples = self._read_session_wifi_samples(s.filename)
            if not samples:
                continue
            session_candidates.append((sid, samples))

        if not session_candidates:
            return 0

        # De-dup candidates by map_id while preserving sample list —
        # concatenate so a busier map gets more fingerprints than one
        # with a single session.
        merged: dict[int, list[tuple[float, float, int, int]]] = {}
        for sid, samples in session_candidates:
            merged.setdefault(sid, []).extend(samples)
        flat_candidates = list(merged.items())

        # Step 3+4: load each untagged entry's body, score, persist.
        modified = 0
        for entry in untagged:
            body = store.load_body(entry.object_name)
            if not isinstance(body, dict):
                continue
            grid = body.get("data")
            if not isinstance(grid, list):
                continue
            try:
                width = int(body.get("width", 0))
                height = int(body.get("height", 0))
                res = int(body.get("resolution", 1)) or 1
                # Cloud reports startX/startY in cm; convert to metres.
                start_x_m = float(body.get("startX", 0)) / 100.0
                start_y_m = float(body.get("startY", 0)) / 100.0
            except (TypeError, ValueError):
                continue
            map_id = match_heatmap_to_session(
                heatmap_grid=grid,
                heatmap_width=width,
                heatmap_height=height,
                heatmap_resolution_m=res,
                heatmap_start_x_m=start_x_m,
                heatmap_start_y_m=start_y_m,
                candidates=flat_candidates,
            )
            if map_id is None:
                continue
            if store.set_map_id(entry.object_name, int(map_id)):
                modified += 1
                LOGGER.info(
                    "[wifi-match] tagged %s → map_id=%d "
                    "(scored against %d session(s))",
                    entry.object_name, map_id, len(flat_candidates),
                )
        return modified

