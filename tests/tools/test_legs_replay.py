"""Tests for tools._rebuild_session_lib.legs_replay."""
from __future__ import annotations

from tools._rebuild_session_lib.legs_replay import reconstruct_legs


class _StubReader:
    def __init__(self, store: dict):
        self._store = store

    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs
                if (start_ts is None or t >= start_ts)
                and (end_ts is None or t <= end_ts)]


def test_reconstruct_legs_single_leg():
    """One leg with a few points, no s2p56 transitions."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    reader = _StubReader({
        (1, 4): [(100, [1, 2, 3]), (110, [4, 5, 6]), (120, [7, 8, 9])],
        (2, 56): [],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: next(pos),
    )
    assert len(legs) == 1
    assert legs[0] == [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]


def test_reconstruct_legs_pen_up_jump_starts_new_leg():
    """A jump > 5 m should start a new leg (matches live algorithm)."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (10.0, 0.0)])  # last is 9m jump
    reader = _StubReader({
        (1, 4): [(100, [1]), (110, [2]), (120, [3])],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: next(pos),
    )
    assert len(legs) == 2
    assert legs[0] == [[0.0, 0.0], [1.0, 0.0]]
    assert legs[1] == [[10.0, 0.0]]


def test_reconstruct_legs_recharge_round_trip_starts_new_leg():
    """s2p56 transition 4→0 (paused→running) should start a new leg
    even without a pen-up jump."""
    pos = iter([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    reader = _StubReader({
        (1, 4): [(100, [1]), (200, [2]), (300, [3])],
        # Paused at 150, resumed at 250 — leg 2 starts at the next position
        (2, 56): [
            (50,  {"status": [[1, 0]]}),  # initial running
            (150, {"status": [[1, 4]]}),  # pause
            (250, {"status": [[1, 0]]}),  # resume → triggers new leg
        ],
    })
    legs = reconstruct_legs(
        reader, start_ts=0, end_ts=400,
        _position_decoder=lambda b: next(pos),
    )
    # Timeline order matters:
    #   t=50  task sub=0  (initial)
    #   t=100 pos  → leg 0 gets (0,0)
    #   t=150 task sub=4  (paused)
    #   t=200 pos  → leg 0 gets (1,0)  [position arrives before the resume]
    #   t=250 task sub=0  (resumed, 4→0 transition) → begin_leg, leg 1 starts
    #   t=300 pos  → leg 1 gets (2,0)
    assert len(legs) == 2
    assert legs[0] == [[0.0, 0.0], [1.0, 0.0]]
    assert legs[1] == [[2.0, 0.0]]


def test_reconstruct_legs_empty():
    reader = _StubReader({})
    assert reconstruct_legs(
        reader, start_ts=0, end_ts=200,
        _position_decoder=lambda b: (0.0, 0.0),
    ) == []
