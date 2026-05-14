"""Disk-backed archive of cloud-side WiFi heatmap (wifimap) objects.

The cloud's OBJ probe returns OSS object names that may be either flat
(e.g., ``wifimap_1700000001.json``) or nested path-style with
date-partitioned directories (e.g.,
``ali_dreame/2026/05/11/BM169439/-112293549_154215647.0550.txt``). We
keep the FULL object_name as identity (the cloud needs it verbatim
for ``get_interim_file_url``), and derive a flat disk-safe filename
by replacing ``/`` with ``__`` (reversible).

Dedup: ``object_name`` is unique per cloud-side generation, so
"already on disk?" is a sufficient identity check. No content hash.

Path layout:

    /config/dreame_a2_mower/wifi_archive/
        index.json
        wifimap_1700000001.json
        ali_dreame__2026__05__11__BM169439__-112293549_154215647.0550.txt
        ...
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Standalone "_<10-digit-unix>" pattern (legacy `wifimap_<ts>.json`).
_TS_UNIX_RE = re.compile(r"_(\d{9,11})(?:[._]|$)")
# Date-partition pattern in the object path: /YYYY/MM/DD/ — used for
# date-partitioned OSS layouts that don't embed a unix timestamp in
# the filename component.
_TS_DATE_RE = re.compile(r"(?:^|/)(\d{4})/(\d{2})/(\d{2})(?:/|$)")
# Filename-component "_<9-digit HHMMSSxxx>" sub-second component.
# Observed in g2408 OSS object names:
#   ali_dreame/2026/05/13/BM169439/-112293549_082656885.0550.txt
# The 9-digit run after the device-id underscore decodes as:
#     HH (2) | MM (2) | SS (2) | sss (3 — millis)
# Used to add hour-of-day resolution to date-partitioned timestamps
# so two distinct heatmaps generated the same day get distinct
# unix_ts values (was producing collision-labeled duplicate rows in
# the WiFi archive picker; see wifi-heatmap-todo.md).
_TS_HMS_RE = re.compile(r"_(\d{6})\d{3}(?:[._]|$)")
_INDEX_NAME = "index.json"
_DISK_SEP = "__"


@dataclass(frozen=True)
class WifiArchiveEntry:
    object_name: str
    unix_ts: int
    width: int
    height: int
    resolution: int
    startX: int
    startY: int
    first_seen_unix: int
    # v1.0.10a6+: heatmap → map_id correlation. Tagged by the
    # fingerprint matcher (wifi_match.py) using the per-session
    # wifi_samples captured during recent mows; falls back to
    # geometry inference when no recent session matches. -1 = unknown
    # (legacy entries from before the matcher existed, or entries
    # the matcher could not score).
    map_id: int = -1


class WifiArchiveStore:
    """Owns ``wifi_archive/`` and ``index.json`` for one device."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def index_path(self) -> Path:
        return self._root / _INDEX_NAME

    @staticmethod
    def _validate_object_name(object_name: str) -> None:
        """Reject names that would escape the archive root.

        Cloud OSS object names CAN include forward slashes for date
        partitioning, so ``/`` is allowed. What's not allowed:
        ``..`` segments, absolute paths, ``~`` expansion, or anything
        that would resolve outside the archive root.
        """
        if not object_name:
            raise ValueError("empty object_name")
        if object_name.startswith("/") or object_name.startswith("~"):
            raise ValueError(f"invalid object_name (absolute): {object_name!r}")
        # PosixPath.parts splits on '/' and yields '..' as a part if present.
        parts = object_name.split("/")
        if any(p in ("..", "") for p in parts if p != ""):
            # disallow '..' anywhere
            if ".." in parts:
                raise ValueError(f"invalid object_name (traversal): {object_name!r}")
        if "\x00" in object_name:
            raise ValueError(f"invalid object_name (null byte): {object_name!r}")

    @staticmethod
    def _disk_filename(object_name: str) -> str:
        """Reversible flatten of an OSS object_name to a disk-safe filename."""
        return object_name.replace("/", _DISK_SEP)

    def has_object(self, object_name: str) -> bool:
        self._validate_object_name(object_name)
        return (self._root / self._disk_filename(object_name)).is_file()

    def load_index(self) -> list[WifiArchiveEntry]:
        if not self.index_path.is_file():
            return []
        try:
            raw = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[WifiArchiveEntry] = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            try:
                out.append(
                    WifiArchiveEntry(
                        object_name=str(r["object_name"]),
                        unix_ts=int(r.get("unix_ts", 0)),
                        width=int(r.get("width", 0)),
                        height=int(r.get("height", 0)),
                        resolution=int(r.get("resolution", 0)),
                        startX=int(r.get("startX", 0)),
                        startY=int(r.get("startY", 0)),
                        first_seen_unix=int(r.get("first_seen_unix", 0)),
                        # Backward-compat: legacy entries default to -1
                        # (unknown). The fingerprint matcher fills this in
                        # the next time it runs against fresh heatmaps.
                        map_id=int(r["map_id"]) if "map_id" in r else -1,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def load_body(self, object_name: str) -> dict[str, Any] | None:
        self._validate_object_name(object_name)
        body_path = self._root / self._disk_filename(object_name)
        if not body_path.is_file():
            return None
        try:
            raw = json.loads(body_path.read_text())
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def archive(
        self,
        object_name: str,
        body: dict[str, Any],
        first_seen_unix: int,
    ) -> WifiArchiveEntry:
        """Write the body to disk and append to the index (idempotent).

        Dedup happens at three levels:
        1. Exact ``object_name`` match → return the existing entry verbatim.
        2. Same parsed ``unix_ts`` AND identical geometry signature
           (``width``/``height``/``resolution``/``startX``/``startY``)
           → suppress the index append. The body file still lives on
           disk under its unique disk-safe filename, but the picker
           dropdown only shows one row per (unix_ts, geometry) pair.
           This catches the case where the cloud re-emits the same
           heatmap under a freshly-rotated object_name (observed in
           the live archive 2026-05-13 with two identically-shaped
           heatmaps stamped at midnight UTC of the same date).
        """
        self._validate_object_name(object_name)
        with self._lock:
            existing_list = self.load_index()
            existing = {e.object_name: e for e in existing_list}
            if object_name in existing:
                return existing[object_name]
            body_path = self._root / self._disk_filename(object_name)
            body_path.write_text(json.dumps(body))
            entry = WifiArchiveEntry(
                object_name=object_name,
                unix_ts=self._parse_unix_ts(object_name),
                width=int(body.get("width", 0)),
                height=int(body.get("height", 0)),
                resolution=int(body.get("resolution", 0)),
                startX=int(body.get("startX", 0)),
                startY=int(body.get("startY", 0)),
                first_seen_unix=first_seen_unix,
            )

            # Geometry+timestamp dedup: skip the index append when a
            # prior entry has identical (unix_ts, geometry-signature).
            # The body file stays on disk (for forensic / debug
            # access) but the picker only sees the original row.
            geometry_dup = next(
                (
                    e for e in existing_list
                    if e.unix_ts == entry.unix_ts
                    and e.width == entry.width
                    and e.height == entry.height
                    and e.resolution == entry.resolution
                    and e.startX == entry.startX
                    and e.startY == entry.startY
                ),
                None,
            )
            if geometry_dup is not None:
                return geometry_dup

            all_entries = existing_list + [entry]
            self.index_path.write_text(
                json.dumps([asdict(e) for e in all_entries], indent=2)
            )
            return entry

    def set_map_id(self, object_name: str, map_id: int) -> bool:
        """Tag an archived entry's heatmap with a resolved map_id.

        Called by the fingerprint matcher after scoring incoming
        heatmaps against recent session wifi_samples. Idempotent and
        safe to call repeatedly — only rewrites the index when the
        new map_id actually differs from what's already stored.

        Returns True iff the index was modified.
        """
        self._validate_object_name(object_name)
        with self._lock:
            existing_list = self.load_index()
            modified = False
            new_list: list[WifiArchiveEntry] = []
            for e in existing_list:
                if e.object_name == object_name and e.map_id != int(map_id):
                    new_list.append(
                        WifiArchiveEntry(
                            object_name=e.object_name,
                            unix_ts=e.unix_ts,
                            width=e.width,
                            height=e.height,
                            resolution=e.resolution,
                            startX=e.startX,
                            startY=e.startY,
                            first_seen_unix=e.first_seen_unix,
                            map_id=int(map_id),
                        )
                    )
                    modified = True
                else:
                    new_list.append(e)
            if modified:
                self.index_path.write_text(
                    json.dumps([asdict(e) for e in new_list], indent=2)
                )
            return modified

    @staticmethod
    def _parse_unix_ts(object_name: str) -> int:
        """Extract a timestamp from the OSS object_name.

        Order:
        1. Date-partition components in the path
           (``ali_dreame/YYYY/MM/DD/...``) → unix midnight UTC of that
           date, refined to second resolution by the HHMMSS prefix of
           the underscore-digits in the filename component when present
           (e.g., ``-112293549_082656885.0550.txt`` → 08:26:56). This
           refinement is what stops two heatmaps generated on the same
           day from collapsing onto an identical ``unix_ts`` (and thus
           an identical picker label).
           Cloud OSS paths use this date-partitioning, and the bulk of
           the underscore-digits are device session IDs, NOT unix
           timestamps (e.g., ``_154215647`` would parse to 1974 if
           treated as epoch).
        2. Underscore-bracketed 10-digit unix epoch in the filename
           component only (legacy/test ``wifimap_1700000001.json``).
        3. 0 (unknown).
        """
        date_match = _TS_DATE_RE.search(object_name)
        if date_match:
            try:
                yyyy = int(date_match.group(1))
                mm = int(date_match.group(2))
                dd = int(date_match.group(3))
                base_ts = int(
                    datetime(yyyy, mm, dd, tzinfo=timezone.utc).timestamp()
                )
            except ValueError:
                base_ts = 0
            if base_ts:
                # Look for an HH:MM:SS prefix in the filename component
                # to disambiguate intra-day duplicates.
                fname = object_name.rsplit("/", 1)[-1]
                hms_match = _TS_HMS_RE.search(fname)
                if hms_match:
                    raw = hms_match.group(1)
                    try:
                        hh = int(raw[0:2])
                        mn = int(raw[2:4])
                        ss = int(raw[4:6])
                        if (
                            0 <= hh < 24
                            and 0 <= mn < 60
                            and 0 <= ss < 60
                        ):
                            return base_ts + hh * 3600 + mn * 60 + ss
                    except ValueError:
                        pass
                return base_ts
        # Strip any path prefix — only look at the filename for the unix-ts
        # regex so we don't pick up session-id underscores from path segments.
        fname = object_name.rsplit("/", 1)[-1]
        m = _TS_UNIX_RE.search(fname)
        if m:
            return int(m.group(1))
        return 0
