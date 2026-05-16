"""Detect session windows from probe-captured s2p56 task_state events.

A session starts when the firmware transitions from "no task"
(None) or "complete" (2) into "running" (0). A session ends when
it leaves the running/paused set (0/4) for "complete" (2) or "no
task" (None).

Re-emissions of the same sub_state (heartbeat duplicates) are
ignored — only true transitions count.

Mid-log handling
----------------
If the probe started while the mower was already mid-session, the
very first event will be sub_state 0 with no preceding _IDLE seen.
We still set open_start from that first 0 event, but we mark the
start as "implicit" (no confirmed _IDLE→0 transition). An implicit
start is accepted only when the session ends via None ("no task" /
fully idle), which is an unambiguous terminator. If an implicit
session ends via state 2 ("complete", a transitional state), we
discard it because we cannot confirm whether the probe genuinely
observed the beginning of that task.
"""
from __future__ import annotations

from dataclasses import dataclass

_SENTINEL = object()  # module-level sentinel for "no prior event seen"

_RUNNING = {0, 4}
_IDLE = {2, None}


@dataclass(frozen=True)
class Window:
    start_ts: int
    end_ts: int


def detect_windows(events: list[tuple[int, int | None]]) -> list[Window]:
    """events is a list of (ts_unix, sub_state) sorted by ts.

    Returns one Window per complete (start + end) session. Sessions
    that lack a clear start and end in state 2 (ambiguous mid-log),
    or that have no end event (probe truncated), are dropped.
    """
    windows: list[Window] = []
    sorted_evs = sorted(events, key=lambda e: e[0])

    prev = _SENTINEL
    open_start: int | None = None
    start_confirmed: bool = False  # True if preceded by an _IDLE state

    for ts, sub in sorted_evs:
        if prev is _SENTINEL:
            # First event seen. If it is 0 (running), record tentative
            # open_start but leave start_confirmed=False. We don't know
            # whether the mower just started or was already mid-session.
            if sub == 0:
                open_start = ts
                start_confirmed = False
            prev = sub
            continue

        if sub == prev:
            continue  # heartbeat re-emit; no state change

        # True transition: prev → sub
        if sub == 0 and prev in _IDLE:
            # Confirmed start: we saw the _IDLE→running edge.
            open_start = ts
            start_confirmed = True
        elif prev in _RUNNING and sub in _IDLE:
            if open_start is not None and (start_confirmed or sub is None):
                # Accept the window only if the start was confirmed,
                # OR the end is None (fully idle — unambiguous finish).
                windows.append(Window(start_ts=open_start, end_ts=ts))
            open_start = None
            start_confirmed = False

        prev = sub

    return windows
