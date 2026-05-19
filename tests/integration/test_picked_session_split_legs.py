"""Verify build_picked_session_summary exposes mowing_legs + traversal_legs.

The preferred classification path (v1.0.17+) uses the archive's captured
``_mowing_legs`` / ``_traversal_legs`` fields set at append-time by the
coordinator's live_map hook. Legacy archives without those fields now produce
``mowing_legs=[]`` / ``traversal_legs=[]`` and rely on the JS card's
``(a.legs || [])`` union-key fallback for display.

The fuzzy split_trail classifier and three tests that relied on it were removed
in Task 11. The remaining tests guard that the two keys always exist and that
serialised points are JSON-safe lists.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from custom_components.dreame_a2_mower.protocol import session_summary as _ss
from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "protocol" / "data" / "sessions"


def _load_session(name: str):
    raw = json.loads((_FIXTURE_DIR / f"{name}.json").read_text())
    summary = _ss.parse_session_summary(raw)
    entry = SimpleNamespace(
        md5=raw.get("md5"),
        filename=f"{name}.json",
        map_id=0,
        start_ts=raw["start"],
        end_ts=raw["end"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
    )
    return raw, summary, entry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_mowing_and_traversal_legs_keys_present():
    """build_picked_session_summary always exposes both split keys."""
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    assert "mowing_legs" in result, "mowing_legs key missing from summary"
    assert "traversal_legs" in result, "traversal_legs key missing from summary"


def test_legs_back_compat_key_still_present():
    """Legacy `legs` union key must survive the split addition (back-compat)."""
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    assert "legs" in result, "legacy 'legs' key removed — back-compat broken"


def test_points_are_lists_of_lists_not_tuples():
    """JSON-serialisable shape: [[[x, y], ...], ...] — lists, not tuples."""
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    for key in ("mowing_legs", "traversal_legs"):
        for leg in result[key]:
            assert isinstance(leg, list), f"{key}: leg should be list, got {type(leg)}"
            for pt in leg:
                assert isinstance(pt, list), (
                    f"{key}: point should be list, got {type(pt)}"
                )
                assert len(pt) == 2
