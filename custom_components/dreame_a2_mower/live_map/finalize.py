"""Finalize-gate logic for in-progress sessions.

Per spec §5.7: redesigned from first principles using s2p56 task-state
codes (1=start_pending, 2=running, 3=complete, 4=resume_pending,
5=ended). Replaces the legacy patchwork.

The gate is consulted on every coordinator update. It examines the
mower's task_state_code + session_active + pending_session_*
fields and decides whether to:
  - begin a new session
  - begin a new leg (mid-session recharge → resume)
  - finalize a completed session (cloud-summary fetch + archive write)
  - promote an in-progress to "(incomplete)" archive (cloud-fetch
    expired)
  - no-op
"""
from __future__ import annotations

from enum import Enum, auto


class FinalizeAction(Enum):
    """What the finalize gate decides on this update tick."""

    NOOP = auto()
    BEGIN_SESSION = auto()
    BEGIN_LEG = auto()
    FINALIZE_COMPLETE = auto()
    FINALIZE_INCOMPLETE = auto()  # cloud-fetch expired; promote with what we have
    AWAIT_OSS_FETCH = auto()  # session ended; OSS key arrived; fetch is pending


def decide(state, prev_task_state: int | None, now_unix: int) -> FinalizeAction:
    """Pure function: examine MowerState + previous tick's task_state and
    return the action to take. The coordinator dispatches the action.

    `state` is a MowerState. `prev_task_state` is what the coordinator
    saw last tick.
    """
    # F5.5 implements the actual logic. Stub returns NOOP.
    return FinalizeAction.NOOP
