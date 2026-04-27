"""Daily-rotating JSONL archive of raw MQTT payloads.

Companion to :class:`protocol.unknown_watchdog.UnknownFieldWatchdog`:
the watchdog flags novelty synchronously, but its log line carries only
a tiny payload sample. The archive preserves the *full* wire payload so
anything flagged as novel can be recovered later for deeper analysis.

Design notes
------------
- One file per UTC-date, ``YYYY-MM-DD.jsonl`` under the configured
  archive directory. Keeps individual files small enough to grep.
- Non-JSON payloads are stored as ``payload_hex`` instead of ``payload``
  so the on-disk format is always valid JSONL.
- Pruning runs opportunistically at the first write of each new day;
  any file older than ``retain_days`` whose stem parses as a date is
  deleted. Files that don't match the date pattern are left alone so
  a human-placed README or companion note in the archive folder
  survives rotation.
- Thread-safe: the MQTT client callback thread is the sole writer but
  a :class:`threading.Lock` is held anyway so a future consumer
  (diagnostics dump, archive inspector) can safely share the instance.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Callable, Optional


_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")


def _default_clock() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class MqttArchive:
    """Append-only daily rotation of raw MQTT payloads to JSONL.

    Parameters
    ----------
    directory
        Destination folder. Created lazily on first write.
    retain_days
        Files whose filename-date is strictly older than ``today -
        retain_days`` are removed on each rotation. Default ``7``.
    clock
        Injectable "now" — tests pin it to a fixed value so rotation
        and pruning are deterministic.
    """

    def __init__(
        self,
        directory: Path,
        retain_days: int = 7,
        clock: Callable[[], dt.datetime] = _default_clock,
    ) -> None:
        self._dir = Path(directory)
        self._retain_days = int(retain_days)
        self._clock = clock
        self._lock = threading.Lock()
        self._current_date: Optional[dt.date] = None

    def write(self, topic: str, payload: bytes) -> None:
        now = self._clock()
        today = now.date() if isinstance(now, dt.datetime) else dt.date.today()

        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)

            if self._current_date != today:
                self._current_date = today
                self._prune(today)

            entry: dict = {
                "ts_ms": int(now.timestamp() * 1000) if isinstance(now, dt.datetime) else None,
                "topic": topic,
            }
            try:
                entry["payload"] = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                entry["payload_hex"] = payload.hex()

            path = self._dir / f"{today.isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False))
                fh.write("\n")

    def _prune(self, today: dt.date) -> None:
        cutoff = today - dt.timedelta(days=self._retain_days)
        for entry in self._dir.iterdir():
            if not entry.is_file():
                continue
            match = _DATE_FILE_RE.match(entry.name)
            if not match:
                continue
            try:
                file_date = dt.date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    entry.unlink()
                except OSError:
                    pass
