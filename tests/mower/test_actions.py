"""Tests for mower/actions.py — the typed action enum + dispatch table."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.actions import (
    ACTION_TABLE,
    MowerAction,
)


def test_action_enum_includes_all_f3_actions():
    """The MowerAction enum has at least the 9 F3-required values."""
    expected = {
        "START_MOWING",
        "START_ZONE_MOW",
        "START_EDGE_MOW",
        "START_SPOT_MOW",
        "PAUSE",
        "DOCK",
        "RECHARGE",
        "STOP",
        "FIND_BOT",
        "LOCK_BOT_TOGGLE",
        "SUPPRESS_FAULT",
        "FINALIZE_SESSION",
    }
    actual = {a.name for a in MowerAction}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_action_table_has_siid_aiid_for_cloud_actions():
    """Every action that hits the cloud has (siid, aiid) defined."""
    cloud_actions = {
        MowerAction.START_MOWING,
        MowerAction.PAUSE,
        MowerAction.DOCK,
        MowerAction.STOP,
        MowerAction.SUPPRESS_FAULT,
    }
    for action in cloud_actions:
        assert action in ACTION_TABLE
        entry = ACTION_TABLE[action]
        assert "siid" in entry, f"{action} missing siid"
        assert "aiid" in entry, f"{action} missing aiid"


def test_finalize_session_is_local_only():
    """FINALIZE_SESSION has no (siid, aiid) — it's integration-local."""
    entry = ACTION_TABLE.get(MowerAction.FINALIZE_SESSION, {})
    assert "siid" not in entry  # local-only
