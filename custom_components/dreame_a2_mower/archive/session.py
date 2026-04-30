"""Per-session summary archive on disk.

Each completed mowing session produces a JSON blob (see
`protocol.session_summary`). The archive persists one file per session so
future analysis can reconstruct history without re-fetching from the
Dreame cloud.

File layout:

    <root>/<YYYY-MM-DD>_<end_ts>_<md5[:8]>.json      raw JSON as received
    <root>/index.json                                 lightweight index

The archive is content-addressed by `summary.md5`: re-archiving the same
session is a no-op. The index file is rewritten atomically on every
archive. No data is ever deleted automatically — users can prune by hand.

No HA dependency here — the class takes a plain filesystem `Path`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1

# In-progress entry — single mutable file representing the currently-active
# logical run (one or more Dreame `event_occured` legs while
# `device.status.started` stays True). Surfaces in list_sessions() at the
# top so the picker shows it like any other run, with the Latest view
# auto-tracking it. Promoted to a regular archive entry when the session
# finally ends — or discarded if no completed-leg summary ever arrived.
IN_PROGRESS_NAME = "in_progress.json"
IN_PROGRESS_VERSION = 1
IN_PROGRESS_MAX_AGE_S = 12 * 3600  # stale beyond this; auto-cleaned on read


@dataclass(frozen=True)
class ArchivedSession:
    """Metadata for one archived session (as stored in `index.json`).

    `still_running` is False for every persisted entry and True only for the
    synthesized in-progress row surfaced via `SessionArchive.in_progress_entry()`.
    Consumers (the replay picker, the Latest-view loader) branch on this to
    pick up the live in-progress payload from disk instead of treating the
    entry as a finalized archive file.
    """

    filename: str
    start_ts: int
    end_ts: int
    duration_min: int
    area_mowed_m2: float
    map_area_m2: int
    md5: str
    still_running: bool = False

    @classmethod
    def from_summary(cls, filename: str, summary) -> "ArchivedSession":
        return cls(
            filename=filename,
            start_ts=int(summary.start_ts),
            end_ts=int(summary.end_ts),
            duration_min=int(summary.duration_min),
            area_mowed_m2=float(summary.area_mowed_m2),
            map_area_m2=int(summary.map_area_m2),
            md5=str(summary.md5),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_min": self.duration_min,
            "area_mowed_m2": self.area_mowed_m2,
            "map_area_m2": self.map_area_m2,
            "md5": self.md5,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedSession":
        return cls(
            filename=str(d.get("filename", "")),
            start_ts=int(d.get("start_ts", 0)),
            end_ts=int(d.get("end_ts", 0)),
            duration_min=int(d.get("duration_min", 0)),
            area_mowed_m2=float(d.get("area_mowed_m2", 0.0)),
            map_area_m2=int(d.get("map_area_m2", 0)),
            md5=str(d.get("md5", "")),
            still_running=bool(d.get("still_running", False)),
        )


class SessionArchive:
    """Filesystem-backed session archive."""

    # In-progress cache TTL — read_in_progress disk hits are throttled to
    # at most one per IN_PROGRESS_CACHE_TTL_S, since list_sessions() and
    # latest() get called from every coordinator tick AND the picker
    # entity. Cache invalidates immediately on write/delete.
    IN_PROGRESS_CACHE_TTL_S = 5.0

    def __init__(self, root: Path, retention: int = 0) -> None:
        """`retention` = max number of sessions to keep on disk. 0 means
        unlimited. Adjustable at runtime via `set_retention()`.

        The on-disk index is NOT read here — this constructor is called from
        the coordinator's sync `__init__`, which in turn runs on the HA
        event loop. `load_index()` must be invoked explicitly via
        `hass.async_add_executor_job` before any index-dependent accessor
        (`list_sessions`, `latest`, `count`, `has`) is used. Accessors
        return empty/None until then.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedSession] = []
        self._retention = int(retention) if retention else 0
        # In-progress cache: (read_at_monotonic, payload | None).
        # Sentinel `read_at = 0.0` means "not cached yet, read on next call".
        self._in_progress_cached: tuple[float, dict | None] = (0.0, None)
        self._index_loaded: bool = False

    # -------------------- index I/O --------------------

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def load_index(self) -> None:
        """Read `index.json` off disk into memory. Idempotent; safe to call
        multiple times. Blocks on file I/O — call from an executor, not
        the event loop."""
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
            rows = data.get("sessions", []) if isinstance(data, dict) else []
            self._index = [
                ArchivedSession.from_dict(r) for r in rows if isinstance(r, dict)
            ]
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("SessionArchive: index load failed (%s); starting fresh", ex)
            self._index = []

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "version": INDEX_VERSION,
            "sessions": [s.to_dict() for s in self._index],
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

    def latest(self) -> ArchivedSession | None:
        """Return the newest entry — in-progress wins if one is on disk.

        Used by the Latest view to decide what to display: an active run
        outranks any completed archive, even one that finished seconds ago,
        because `last_update_ts` is bumped on every coordinator tick.
        """
        self.load_index()
        in_progress = self.in_progress_entry()
        candidates = list(self._index)
        if in_progress is not None:
            candidates.append(in_progress)
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.end_ts)

    def list_sessions(self) -> list[ArchivedSession]:
        """Return all sessions ordered most-recent-first (by end_ts).

        The in-progress entry, if any, sorts to the front because its
        `end_ts` is the most-recent persistence tick — i.e. always now.
        """
        self.load_index()
        sessions = list(self._index)
        in_progress = self.in_progress_entry()
        if in_progress is not None:
            sessions.append(in_progress)
        return sorted(sessions, key=lambda s: s.end_ts, reverse=True)

    def has(self, md5: str) -> bool:
        self.load_index()
        return any(s.md5 == md5 for s in self._index)

    def find_covering_session(
        self, start_ts: int, window_s: int = 120
    ) -> ArchivedSession | None:
        """Return an archived session whose `start_ts` is within ±window_s
        seconds of the supplied timestamp, or None.

        Used at boot to detect the "HA offline while the session ended"
        case: the cloud writes the session-summary JSON, the normal
        archive path picks it up, but the stale `in_progress.json`
        persisted before HA went down still describes the same run. If
        we find a matching archive entry, the session is complete and
        the in_progress blob should be dropped — otherwise today's new
        mow renders on top of yesterday's path.

        Window default 120 s: session-summary JSON's `start_ts` and the
        live tracker's `session_start_ts` both come from the firmware's
        mow-start event but may differ by a few seconds (cloud parse
        time, leg boundaries, clock drift). 120 s is loose enough to
        absorb that jitter and still tight enough that two genuinely-
        different mows never collide (minimum gap in real use is many
        minutes)."""
        self.load_index()
        if start_ts <= 0:
            return None
        for s in self._index:
            if abs(int(s.start_ts) - int(start_ts)) <= window_s:
                return s
        return None

    # ------------------ in-progress entry I/O ------------------

    def _in_progress_path(self) -> Path:
        return self._root / IN_PROGRESS_NAME

    def read_in_progress(self) -> dict[str, Any] | None:
        """Load the in-progress payload from disk, or None.

        Stale entries (age > IN_PROGRESS_MAX_AGE_S) are auto-deleted —
        otherwise an orphaned crash from yesterday would keep
        re-spawning a phantom "current run" entry every boot.

        Cached for IN_PROGRESS_CACHE_TTL_S to keep this off the
        coordinator's hot path. `list_sessions()` and `latest()` both
        funnel through here on every tick (the picker entity reads
        them) — without caching, that produces a disk read + JSON
        parse for every coordinator update, which trips HA's blocking-
        I/O detector and floods the log. The cache is invalidated
        explicitly by `write_in_progress` and `delete_in_progress` so
        a same-tick read after a write sees fresh data.
        """
        import time as _time
        cached_at, cached_data = self._in_progress_cached
        now = _time.monotonic()
        if cached_at and (now - cached_at) < self.IN_PROGRESS_CACHE_TTL_S:
            return cached_data
        path = self._in_progress_path()
        data: dict[str, Any] | None = None
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                data = None
            if not isinstance(data, dict):
                data = None
            if data is not None:
                try:
                    age = _time.time() - float(data.get("last_update_ts", 0))
                except (TypeError, ValueError):
                    age = 9e9
                if age > IN_PROGRESS_MAX_AGE_S:
                    self.delete_in_progress()
                    data = None
        self._in_progress_cached = (now, data)
        return data

    def write_in_progress(self, payload: dict[str, Any]) -> None:
        """Atomically rewrite the in-progress file.

        The caller owns the schema; we only stamp `version` and
        `last_update_ts` so the reader can age-check without consulting
        the OS mtime (which can drift across reboots / docker mounts).
        """
        path = self._in_progress_path()
        tmp = path.with_suffix(".json.tmp")
        body = dict(payload)
        body["version"] = IN_PROGRESS_VERSION
        body["last_update_ts"] = time.time()
        try:
            tmp.write_text(json.dumps(body, default=str))
            tmp.replace(path)
            # Invalidate the read cache so a same-tick read after this
            # write picks up the fresh data instead of the stale one.
            self._in_progress_cached = (0.0, None)
        except OSError as ex:
            _LOGGER.warning("SessionArchive: failed to write in-progress: %s", ex)

    def delete_in_progress(self) -> None:
        path = self._in_progress_path()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        # Invalidate cache so subsequent reads in the same tick see
        # the deletion (otherwise they'd return the cached payload
        # for up to IN_PROGRESS_CACHE_TTL_S after delete).
        self._in_progress_cached = (0.0, None)

    def in_progress_entry(self) -> ArchivedSession | None:
        """Synthesize an ArchivedSession from the in-progress payload.

        Returns None when no fresh in-progress file exists. The synthesized
        entry has `md5=""` (no canonical hash until the cloud summary
        arrives) and `still_running=True` so the picker can render it
        with a "still running" suffix and consumers can branch on it.
        """
        data = self.read_in_progress()
        if data is None:
            return None
        try:
            start_ts = int(data.get("session_start_ts", 0))
            last_ts = int(data.get("last_update_ts", start_ts))
            area = float(data.get("area_mowed_m2", 0.0))
            map_area = int(data.get("map_area_m2", 0))
        except (TypeError, ValueError):
            return None
        duration_min = max(0, (last_ts - start_ts) // 60)
        return ArchivedSession(
            filename=IN_PROGRESS_NAME,
            start_ts=start_ts,
            end_ts=last_ts,
            duration_min=duration_min,
            area_mowed_m2=area,
            map_area_m2=map_area,
            md5="",
            still_running=True,
        )

    def promote_in_progress(
        self,
        summary,
        raw_json: dict[str, Any] | None = None,
    ) -> ArchivedSession | None:
        """Archive a final-leg summary AND remove the in-progress file.

        The leg summary is stored exactly the same way as a free-standing
        completed session (idempotent by md5). Then the in-progress
        payload is unlinked — the caller is responsible for deciding
        when to call this (i.e. only when the logical session has truly
        ended, not on every leg boundary mid-recharge cycle).
        """
        entry = self.archive(summary, raw_json=raw_json)
        self.delete_in_progress()
        return entry

    def archive(self, summary, raw_json: dict[str, Any] | None = None) -> ArchivedSession | None:
        """Persist one session summary. Idempotent by ``(md5, start_ts)``.

        `raw_json` is the original JSON dict (written verbatim to disk for
        audit/replay). If omitted, a minimal reconstruction from the
        summary dataclass is stored instead — lossy but still useful.

        Dedup key: ``(md5, start_ts)``. v1.0.0a51: ``md5`` alone is
        not sufficient because g2408's cloud reuses the same md5
        across every session that runs against an unchanged map (the
        md5 appears to be a map-content hash, not a session-content
        hash). Using ``md5`` alone caused every spot/zone mow after
        the first one to be silently dropped on the
        already-archived branch. The session's ``start_ts`` makes
        the key cloud-unique while still letting genuine retransmits
        of the *same* session (same start) be deduped.
        """
        md5 = str(getattr(summary, "md5", "") or "")
        start_ts = int(getattr(summary, "start_ts", 0))
        if md5 and start_ts and any(
            s.md5 == md5 and int(getattr(s, "start_ts", 0)) == start_ts
            for s in self._index
        ):
            return None

        end_ts = int(getattr(summary, "end_ts", 0))
        date_part = _format_date(end_ts)
        stem = f"{date_part}_{end_ts}_{md5[:8] or 'nohash'}.json"
        path = self._root / stem
        tmp = path.with_suffix(".json.tmp")
        try:
            if raw_json is not None:
                payload = raw_json
            else:
                payload = _summary_to_dict(summary)
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
            tmp.replace(path)
        except OSError as ex:
            _LOGGER.warning("SessionArchive: failed to write %s: %s", path, ex)
            return None

        entry = ArchivedSession.from_summary(filename=stem, summary=summary)
        self._index.append(entry)
        self._save_index()
        self._enforce_retention()
        return entry

    def _enforce_retention(self) -> None:
        """Prune oldest sessions beyond the configured cap.

        No-op when `self._retention` is 0 or None (unlimited). Otherwise
        keeps only the `_retention` most recent (by `end_ts`) entries
        on disk + in the index. Runs after every successful archive;
        typical cost is a single `path.unlink()` per mow once the
        archive is full.
        """
        keep = getattr(self, "_retention", 0)
        if not keep or keep <= 0:
            return
        if len(self._index) <= keep:
            return
        # Sort oldest-first, chop the excess from the front.
        sorted_idx = sorted(self._index, key=lambda s: s.end_ts)
        excess = len(sorted_idx) - keep
        to_drop = sorted_idx[:excess]
        for entry in to_drop:
            try:
                (self._root / entry.filename).unlink(missing_ok=True)
            except OSError as ex:
                _LOGGER.warning(
                    "SessionArchive: failed to prune %s: %s",
                    entry.filename,
                    ex,
                )
        # Keep only the most-recent `keep` entries in the in-memory
        # index and rewrite the index file.
        kept_files = {e.filename for e in sorted_idx[excess:]}
        self._index = [e for e in self._index if e.filename in kept_files]
        self._save_index()
        _LOGGER.info(
            "SessionArchive: pruned %d old session(s) past retention=%d",
            excess,
            keep,
        )

    def set_retention(self, keep: int) -> None:
        """Set the retention cap. 0 or negative means unlimited."""
        self._retention = int(keep) if keep else 0
        self._enforce_retention()

    def load(self, entry: ArchivedSession) -> dict[str, Any] | None:
        """Read the raw JSON of an archived session. None on error."""
        path = self._root / entry.filename
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as ex:
            _LOGGER.warning(
                "SessionArchive: failed to load %s: %s", entry.filename, ex
            )
            return None


# -------------------- helpers --------------------


def _format_date(unix_ts: int) -> str:
    if unix_ts <= 0:
        return "0000-00-00"
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "0000-00-00"


def _summary_to_dict(summary) -> dict[str, Any]:
    """Lossy reconstruction of the session JSON from a SessionSummary.

    Only used as a fallback when the raw JSON isn't available at archive
    time. Not symmetric with the wire format (polygons are stored in
    metres, not cm). Re-parsing this through `parse_session_summary`
    will not yield the same result.
    """
    return {
        "start": summary.start_ts,
        "end": summary.end_ts,
        "time": summary.duration_min,
        "mode": summary.mode,
        "result": summary.result,
        "stop_reason": summary.stop_reason,
        "areas": summary.area_mowed_m2,
        "map_area": summary.map_area_m2,
        "md5": summary.md5,
        "dock": list(summary.dock) if summary.dock else None,
        "_note": (
            "Reconstructed from SessionSummary dataclass — geometry in metres, "
            "not cm. Not wire-compatible."
        ),
    }
