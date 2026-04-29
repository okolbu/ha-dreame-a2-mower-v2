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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.dreame_a2_mower.mower.state import MowerState

# ---------------------------------------------------------------------------
# Module-level constants (per spec §5.7 / task F5.5.1)
# ---------------------------------------------------------------------------

MAX_AGE_SECONDS: int = 30 * 60       # 30 minutes — give up on cloud-summary fetch
MAX_ATTEMPTS: int = 10                # max OSS fetch attempts before giving up
RETRY_INTERVAL_SECONDS: int = 60     # minimum gap between retry attempts


class FinalizeAction(Enum):
    """What the finalize gate decides on this update tick."""

    NOOP = auto()
    BEGIN_SESSION = auto()
    BEGIN_LEG = auto()
    FINALIZE_COMPLETE = auto()
    FINALIZE_INCOMPLETE = auto()  # cloud-fetch expired; promote with what we have
    AWAIT_OSS_FETCH = auto()  # session ended; OSS key arrived; fetch is pending


def decide(state: "MowerState", prev_task_state: int | None, now_unix: int) -> FinalizeAction:
    """Pure function: examine MowerState + previous tick's task_state and
    return the action to take. The coordinator dispatches the action.

    ``state`` is a MowerState instance. ``prev_task_state`` is what the
    coordinator saw on the previous tick (may be None at startup).

    The decoded task_state_code values on g2408 (from the s2p56 dict
    envelope, post-v1.0.0a18 decode) are:

      - 0 (running)    — actively mowing
      - 4 (paused)     — paused / waiting to resume (recharge boundary)
      - None           — no active task (status: []) → SESSION END

    The original implementation here checked task_state ∈ {3, 5} for
    session-end (the legacy semantically-named codes), but those values
    never appear on g2408. The result was that finalize never fired
    automatically, and finished sessions were missing from the archive
    picker until the user pressed "Finalize stuck session" by hand.

    Decision tree (evaluated in priority order):

    1. Session ended — prev_task_state was 0 (running) or 4 (paused) and
       new task_state is None (no active task):
         a. pending_session_object_name set → FINALIZE_COMPLETE
         b. no pending OSS key → FINALIZE_INCOMPLETE

    2. pending_session_object_name set: see retry / max-age logic below.

    3-5. BEGIN_SESSION / BEGIN_LEG / NOOP — currently driven directly
       by _on_state_update; the gate's BEGIN_* values are kept for
       compatibility with the dispatcher but are not the trigger path.

    The gate is purely declarative and performs no I/O. The coordinator
    dispatches the returned action (cloud fetch, archive write, etc.).
    """
    task_state = state.task_state_code

    # ------------------------------------------------------------------
    # Priority 1: Session-ended detection
    # On g2408 the natural end-of-session signal is task_state_code
    # transitioning from 0 (running) or 4 (paused) to None (no task).
    # ------------------------------------------------------------------
    session_just_ended = (
        task_state is None and prev_task_state in (0, 4)
    )

    if session_just_ended:
        if state.pending_session_object_name:
            return FinalizeAction.FINALIZE_COMPLETE
        return FinalizeAction.FINALIZE_INCOMPLETE

    # ------------------------------------------------------------------
    # Priority 2: Pending OSS fetch in-flight
    # Evaluated only when session has NOT just ended (i.e. we're polling
    # on a subsequent tick waiting for the cloud-summary to appear).
    # ------------------------------------------------------------------
    if state.pending_session_object_name:
        first_event = state.pending_session_first_event_unix
        last_attempt = state.pending_session_last_attempt_unix
        attempt_count = state.pending_session_attempt_count or 0

        # 2a. Max-age expiry — give up entirely (based on when event first arrived)
        if (
            first_event is not None
            and (now_unix - first_event) > MAX_AGE_SECONDS
        ):
            return FinalizeAction.FINALIZE_INCOMPLETE

        # 2b. Max-attempts exceeded — give up
        if attempt_count > MAX_ATTEMPTS:
            return FinalizeAction.FINALIZE_INCOMPLETE

        # 2c. Enough time has passed since last attempt — retry
        # last_attempt is None on first try (never attempted) → fetch immediately.
        if (
            last_attempt is None
            or (now_unix - last_attempt) >= RETRY_INTERVAL_SECONDS
        ):
            return FinalizeAction.AWAIT_OSS_FETCH

        # Still inside retry window — nothing to do
        return FinalizeAction.NOOP

    # ------------------------------------------------------------------
    # Priority 3: Session-start transition
    # prev_task_state != 1, new == 1  (start_pending)
    # ------------------------------------------------------------------
    if task_state == 1 and prev_task_state != 1:
        return FinalizeAction.BEGIN_SESSION

    # ------------------------------------------------------------------
    # Priority 4: Recharge-resume transition
    # prev == 4 (resume_pending), new == 2 (running)
    # ------------------------------------------------------------------
    if prev_task_state == 4 and task_state == 2:
        return FinalizeAction.BEGIN_LEG

    # ------------------------------------------------------------------
    # Priority 5: Nothing interesting
    # ------------------------------------------------------------------
    return FinalizeAction.NOOP
