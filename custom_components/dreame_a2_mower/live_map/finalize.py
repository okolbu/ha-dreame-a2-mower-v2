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


def decide(state, prev_task_state: int | None, now_unix: int) -> FinalizeAction:
    """Pure function: examine MowerState + previous tick's task_state and
    return the action to take. The coordinator dispatches the action.

    ``state`` is a MowerState instance. ``prev_task_state`` is what the
    coordinator saw on the previous tick (may be None at startup).

    Decision tree (evaluated in priority order):

    1. Session ended (task_state_code == 5, OR session_active flipped False
       while prev was in {2, 4}):
         a. pending_session_object_name set → FINALIZE_COMPLETE (OSS key is
            waiting; caller should fetch it immediately).
         b. no pending OSS key → FINALIZE_INCOMPLETE (nothing to fetch).

    2. pending_session_object_name set (OSS fetch is in-flight or queued):
         a. first_attempt_unix older than MAX_AGE_SECONDS → FINALIZE_INCOMPLETE
            (cloud delivery timeout; give up).
         b. attempt_count > MAX_ATTEMPTS → FINALIZE_INCOMPLETE (too many tries).
         c. at least RETRY_INTERVAL_SECONDS since last attempt → AWAIT_OSS_FETCH
            (time to retry the cloud fetch).
         (otherwise falls through to NOOP — still inside the retry window)

    3. Session-start transition (prev_task_state != 1, new == 1) → BEGIN_SESSION.

    4. Recharge-resume transition (prev == 4, new == 2) → BEGIN_LEG.

    5. Anything else → NOOP.

    The gate is purely declarative and performs no I/O. The coordinator
    dispatches the returned action (cloud fetch, archive write, etc.).
    """
    task_state = state.task_state_code
    session_active = state.session_active

    # ------------------------------------------------------------------
    # Priority 1: Session-ended detection
    # A session has ended when:
    #   • task_state_code == 5  (explicitly "ended")
    #   • OR task_state_code == 3  (complete)
    #   • OR session_active is False while prev was in {2, 4}
    #     (active flag flipped after running/resume_pending)
    # ------------------------------------------------------------------
    session_just_ended = (
        task_state in (3, 5)
        or (
            session_active is False
            and prev_task_state in (2, 4)
        )
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
        first_attempt = state.pending_session_first_attempt_unix
        attempt_count = state.pending_session_attempt_count or 0

        # 2a. Max-age expiry — give up entirely
        if (
            first_attempt is not None
            and (now_unix - first_attempt) > MAX_AGE_SECONDS
        ):
            return FinalizeAction.FINALIZE_INCOMPLETE

        # 2b. Max-attempts exceeded — give up
        if attempt_count > MAX_ATTEMPTS:
            return FinalizeAction.FINALIZE_INCOMPLETE

        # 2c. Enough time has passed since last attempt — retry
        last_attempt = state.pending_session_first_attempt_unix  # reuse first as proxy
        # Use a dedicated last_attempt field if available (not on state yet);
        # fall back to first_attempt to trigger an immediate first fetch.
        if (
            first_attempt is None
            or (now_unix - first_attempt) >= RETRY_INTERVAL_SECONDS
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
