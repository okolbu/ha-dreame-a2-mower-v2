"""Bounded ring buffer of NOVEL log lines for diagnostics dumps.

Wires into Python's ``logging`` framework via ``as_handler()``. The
returned handler filters records by message prefix and appends matching
lines to a ``collections.deque`` capped at ``maxlen``. A diagnostics
dump reads ``lines()`` to include the recent novelty trail without the
user having to grep their HA log file.

NO ``homeassistant.*`` imports — layer-2.
"""

from __future__ import annotations

import logging
from collections import deque


class NovelLogBuffer:
    def __init__(self, *, maxlen: int, prefixes: tuple[str, ...]) -> None:
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._prefixes = tuple(prefixes)

    def as_handler(self) -> logging.Handler:
        outer = self

        class _BufferHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                msg = record.getMessage()
                if any(msg.startswith(p) for p in outer._prefixes):
                    outer._buffer.append(msg)

        return _BufferHandler()

    def lines(self) -> list[str]:
        return list(self._buffer)
