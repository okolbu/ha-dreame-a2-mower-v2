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
            try:
                out.append(WifiArchiveEntry(**r))
            except TypeError:
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
        """Write the body to disk and append to the index (idempotent)."""
        self._validate_object_name(object_name)
        with self._lock:
            existing = {e.object_name: e for e in self.load_index()}
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
            all_entries = list(existing.values()) + [entry]
            self.index_path.write_text(
                json.dumps([asdict(e) for e in all_entries], indent=2)
            )
            return entry

    @staticmethod
    def _parse_unix_ts(object_name: str) -> int:
        """Extract a timestamp from the OSS object_name.

        Order:
        1. Date-partition components in the path
           (``ali_dreame/YYYY/MM/DD/...``) → unix midnight UTC of that date.
           Cloud OSS paths use this date-partitioning, and the
           underscore-digits in the filename portion are device session
           IDs, NOT unix timestamps (e.g., ``_154215647`` would parse
           to 1974). The date partition is the authoritative signal.
        2. Underscore-bracketed 10-digit unix epoch in the filename
           component only (legacy/test ``wifimap_1700000001.json``).
        3. 0 (unknown).
        """
        m = _TS_DATE_RE.search(object_name)
        if m:
            try:
                yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return int(
                    datetime(yyyy, mm, dd, tzinfo=timezone.utc).timestamp()
                )
            except ValueError:
                pass
        # Strip any path prefix — only look at the filename for the unix-ts
        # regex so we don't pick up session-id underscores from path segments.
        fname = object_name.rsplit("/", 1)[-1]
        m = _TS_UNIX_RE.search(fname)
        if m:
            return int(m.group(1))
        return 0
