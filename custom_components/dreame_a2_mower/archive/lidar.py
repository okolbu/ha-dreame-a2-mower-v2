"""On-disk archive of LiDAR point-cloud scans uploaded by the mower.

Whenever the app taps "Download LiDAR map", the g2408 uploads a new PCD
binary to Alibaba OSS and announces the object key over MQTT on
``s99p20``. This archive persists each downloaded file verbatim so users
can open the same data in a desktop viewer (Open3D, CloudCompare,
MeshLab) and so future post-mow analysis has a historical record.

Content-addressed by md5 — re-downloading the same object key is a
no-op. Mirrors the shape of :mod:`session_archive`; intentionally kept
HA-free so the tests can run without the HA runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1


@dataclass(frozen=True)
class ArchivedLidarScan:
    """Metadata for one archived scan (as stored in ``index.json``)."""

    filename: str
    object_name: str
    unix_ts: int
    size_bytes: int
    md5: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "object_name": self.object_name,
            "unix_ts": self.unix_ts,
            "size_bytes": self.size_bytes,
            "md5": self.md5,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedLidarScan":
        return cls(
            filename=str(d.get("filename", "")),
            object_name=str(d.get("object_name", "")),
            unix_ts=int(d.get("unix_ts", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
            md5=str(d.get("md5", "")),
        )


def _format_date(unix_ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown-date"


class LidarArchive:
    """Filesystem-backed point-cloud archive."""

    def __init__(self, root: Path, retention: int = 0) -> None:
        """`retention` = max number of PCDs to keep on disk. 0 means
        unlimited. Each PCD is ~2-3 MB on this hardware, so an
        aggressive cap is sensible. Adjustable at runtime via
        `set_retention()`.

        The on-disk index is NOT read here — `load_index()` must be invoked
        via `hass.async_add_executor_job` from async context before any
        index-dependent accessor is used. Mirrors `SessionArchive` so the
        two archives can be set up with the same pattern.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedLidarScan] = []
        self._retention = int(retention) if retention else 0
        self._index_loaded: bool = False

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def load_index(self) -> None:
        """Read `index.json` off disk. Idempotent; blocking — call from an
        executor. See `SessionArchive.load_index` for the same pattern."""
        if self._index_loaded:
            return
        self._load_index()
        self._index_loaded = True

    def _load_index(self) -> None:
        path = self._index_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            rows = data.get("scans", []) if isinstance(data, dict) else []
            self._index = [
                ArchivedLidarScan.from_dict(r) for r in rows if isinstance(r, dict)
            ]
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("LidarArchive: index load failed (%s); starting fresh", ex)
            self._index = []

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "version": INDEX_VERSION,
            "scans": [s.to_dict() for s in self._index],
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)

    # -------------------- public API --------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def count(self) -> int:
        self.load_index()
        return len(self._index)

    def latest(self) -> ArchivedLidarScan | None:
        self.load_index()
        if not self._index:
            return None
        return max(self._index, key=lambda s: s.unix_ts)

    def list_scans(self) -> list[ArchivedLidarScan]:
        self.load_index()
        return sorted(self._index, key=lambda s: s.unix_ts, reverse=True)

    def has(self, md5: str) -> bool:
        self.load_index()
        return any(s.md5 == md5 for s in self._index)

    def archive(
        self, object_name: str, unix_ts: int, data: bytes
    ) -> ArchivedLidarScan | None:
        """Persist one PCD blob. Idempotent by md5. Returns the archive
        record on first insert, ``None`` when the md5 already exists or
        the payload is empty."""
        if not data:
            return None
        md5 = hashlib.md5(data).hexdigest()
        if self.has(md5):
            return None

        stem = f"{_format_date(unix_ts)}_{int(unix_ts)}_{md5[:8]}.pcd"
        path = self._root / stem
        tmp = path.with_suffix(".pcd.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as ex:
            _LOGGER.warning("LidarArchive: write failed (%s): %s", ex, path)
            return None

        scan = ArchivedLidarScan(
            filename=stem,
            object_name=str(object_name or ""),
            unix_ts=int(unix_ts),
            size_bytes=len(data),
            md5=md5,
        )
        self._index.append(scan)
        self._save_index()
        self._enforce_retention()
        return scan

    def _enforce_retention(self) -> None:
        """Prune oldest PCDs beyond the configured cap. Mirrors
        SessionArchive._enforce_retention; PCDs are a lot larger
        (2-3 MB each) so users will want this on by default."""
        keep = getattr(self, "_retention", 0)
        if not keep or keep <= 0:
            return
        if len(self._index) <= keep:
            return
        sorted_idx = sorted(self._index, key=lambda s: s.unix_ts)
        excess = len(sorted_idx) - keep
        to_drop = sorted_idx[:excess]
        for scan in to_drop:
            try:
                (self._root / scan.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "LidarArchive: failed to prune %s: %s",
                    scan.filename,
                    ex,
                )
        kept_files = {s.filename for s in sorted_idx[excess:]}
        self._index = [s for s in self._index if s.filename in kept_files]
        self._save_index()
        _LOGGER.info(
            "LidarArchive: pruned %d old scan(s) past retention=%d",
            excess,
            keep,
        )

    def set_retention(self, keep: int) -> None:
        self._retention = int(keep) if keep else 0
        self._enforce_retention()
