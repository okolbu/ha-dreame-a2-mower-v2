"""Tests for seed_in_session — used by _restore_in_progress on HA boot.

When the coordinator restores live_map from sessions/in_progress.json,
we KNOW a real mow session was active (the file is only written during
active mow). Use that as a direct signal to flip the state machine into
IN_SESSION + MOWING rather than waiting for telemetry-based reconcile.
"""
from __future__ import annotations


def test_seed_in_session_from_initial_state():
    """Initial (BETWEEN_SESSIONS, IDLE) → IN_SESSION + MOWING."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.seed_in_session(now_unix=1000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.field_freshness["mow_session"] == 1000
    assert snap.field_freshness["current_activity"] == 1000


def test_seed_in_session_does_not_clobber_authoritative_state():
    """If state machine already received a real start event, seed is a no-op."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=500)
    before = sm.snapshot()
    sm.seed_in_session(now_unix=1000)
    after = sm.snapshot()
    # Freshness for mow_session must not have been bumped by seed
    assert after.field_freshness["mow_session"] == 500
    assert after.mow_session == MowSession.IN_SESSION
    assert after.current_activity == CurrentActivity.MOWING


def test_seed_in_session_does_not_clobber_paused():
    """If the mower came back as PAUSED (s2p1=4 received post-boot), don't
    overwrite that with MOWING. mow_session is already IN_SESSION."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    import dataclasses
    sm = MowerStateMachine()
    # Pretend handle_mqtt_property put us in PAUSED + IN_SESSION
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.PAUSED,
        field_freshness={
            **sm._snapshot.field_freshness,
            "mow_session": 800,
            "current_activity": 800,
        },
    )
    sm.seed_in_session(now_unix=1000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.PAUSED  # not clobbered
