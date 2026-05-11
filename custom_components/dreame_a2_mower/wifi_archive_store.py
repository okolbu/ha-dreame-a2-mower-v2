"""Disk-backed archive of cloud-side WiFi heatmap (wifimap) objects.

The cloud's OBJ probe returns OSS object names that embed a unix
timestamp (e.g., ``wifimap_1700000001.json``). The store keeps one
file per unique ``object_name`` plus an ``index.json`` that mirrors
the per-entry metadata for fast picker rebuilds.

Dedup: ``object_name`` is unique per cloud-side generation, so
"already on disk?" is a sufficient identity check. No content hash.

Path layout:

    /config/dreame_a2_mower/wifi_archive/
        index.json
        wifimap_1700000001.json
        wifimap_1700000002.json
        ...
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


_TS_RE = re.compile(r"_(\d{9,11})(?:[._]|$)")
_INDEX_NAME = "index.json"


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

    @property
    def index_path(self) -> Path:
        return self._root / _INDEX_NAME

    def has_object(self, object_name: str) -> bool:
        return (self._root / object_name).is_file()

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
        body_path = self._root / object_name
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
        existing = {e.object_name: e for e in self.load_index()}
        if object_name in existing:
            return existing[object_name]
        body_path = self._root / object_name
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
        m = _TS_RE.search(object_name)
        return int(m.group(1)) if m else 0
