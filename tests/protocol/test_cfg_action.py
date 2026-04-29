"""Tests for protocol.cfg_action — unwrapping + error paths.
The send_action callable is mocked; no real network."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.cfg_action import (
    CfgActionError,
    call_action_op,
    get_cfg,
    get_dock_pos,
    set_pre,
)


def test_get_cfg_unwraps_result_out_d():
    """A successful getCFG returns result.out[0].d as a dict."""
    captured = {}

    def fake_send(siid, aiid, params):
        captured["call"] = (siid, aiid, params)
        return {"result": {"out": [{"d": {"WRP": [1, 8, 0], "VOL": 80}}]}}

    cfg = get_cfg(fake_send)
    assert cfg == {"WRP": [1, 8, 0], "VOL": 80}
    assert captured["call"] == (2, 50, [{"m": "g", "t": "CFG"}])


def test_get_cfg_raises_on_missing_d():
    def fake_send(*_args, **_kw):
        return {"result": {"out": [{"unrelated": 1}]}}

    with pytest.raises(CfgActionError):
        get_cfg(fake_send)


def test_get_cfg_raises_on_empty_out():
    def fake_send(*_args, **_kw):
        return {"result": {"out": []}}

    with pytest.raises(CfgActionError):
        get_cfg(fake_send)


def test_get_dock_pos_unwraps_dock_subkey():
    def fake_send(*_args, **_kw):
        return {"result": {"out": [{"d": {"dock": {"x": 10, "y": -5, "yaw": 90, "connect_status": 1}}}]}}

    dock = get_dock_pos(fake_send)
    assert dock == {"x": 10, "y": -5, "yaw": 90, "connect_status": 1}


def test_set_pre_validates_array_length():
    with pytest.raises(ValueError):
        set_pre(lambda *_a, **_kw: None, [0, 1, 2])  # too short


def test_set_pre_sends_value_envelope():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    pre = [0, 0, 35, 100, 80, 0, 0, 0, 0, 1]
    set_pre(fake_send, pre)
    assert captured == [(2, 50, [{"m": "s", "t": "PRE", "d": {"value": pre}}])]


def test_call_action_op_basic():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    call_action_op(fake_send, 100)
    assert captured == [(2, 50, [{"m": "a", "p": 0, "o": 100}])]


def test_call_action_op_with_zone_extra():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    call_action_op(fake_send, 102, extra={"region": [1, 2]})
    assert captured == [(2, 50, [{"m": "a", "p": 0, "o": 102, "d": {"region": [1, 2]}}])]


def test_call_action_op_never_merges_extras_at_top_level():
    """Regression guard for the v1.0.0a34 fix.

    Prior to that release, ``extra`` was merged at the top of the
    envelope (``{m,p,o,region:[1]}``). The mower's parser silently
    dropped the unrecognised top-level field, which is what made
    every parametric routed action (zone-mow, spot-mow, edge-mow)
    look like it succeeded while doing nothing on the device.

    The verified format wraps extras under ``d``. This test asserts
    that for every parametric op shape we wire today, no payload
    field other than {m, p, o, d} ends up at the top of the
    envelope.
    """
    captured: list[dict] = []

    def fake_send(_siid, _aiid, params):
        captured.append(params[0])
        return {"result": {"out": [{"d": {}}]}}

    fixtures = [
        (102, {"region": [1, 2]}),       # zone-mow
        (103, {"area": [1]}),            # spot-mow
        (101, {"edge": [[1, 0]]}),       # edge-mow
        (100, {"region_id": [1], "area_id": []}),  # all-areas (full form)
    ]
    for op, extra in fixtures:
        captured.clear()
        call_action_op(fake_send, op, extra=extra)
        envelope = captured[0]
        assert set(envelope.keys()) <= {"m", "p", "o", "d"}, (
            f"op={op}: stray top-level keys "
            f"{set(envelope.keys()) - {'m', 'p', 'o', 'd'}}; "
            "extras must be wrapped under 'd'"
        )
        assert envelope.get("d") == extra, (
            f"op={op}: extras lost or not nested under 'd' (got {envelope!r})"
        )
