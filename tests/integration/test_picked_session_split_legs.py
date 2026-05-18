"""Verify build_picked_session_summary exposes mowing_legs + traversal_legs.

The splitter (split_trail) classifies local-leg points that overlap the
cloud track_segments as mowing (light-green) and the remainder as
traversal (grey).  session_card.py must surface both lists as separate
attributes alongside the back-compat union `legs` key.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
# Helper: inject synthetic _local_legs and cloud track_segments.
# ---------------------------------------------------------------------------

class _MockBoundary:
    """Minimal stand-in for BoundaryLayer; track_segments reads boundary.track."""

    def __init__(self, cloud_segments: list):
        # SessionSummary.track_segments returns self.boundary.track
        # which is tuple[tuple[tuple[float,float],...],...]
        self.track = tuple(
            tuple(tuple(pt) for pt in seg) for seg in cloud_segments
        )
        self.boundary = ()


def _build_result_with_split(
    raw: dict,
    summary,
    entry,
    local_legs: list,
    cloud_segments: list,
):
    """Inject synthetic legs into raw/summary and call build_picked_session_summary.

    strategy: replace summary.boundary with a mock whose .track returns our
    synthetic cloud segments.  summary.track_segments is a property that returns
    self.boundary.track, so patching boundary is the right seam.
    """
    import dataclasses

    raw_mod = dict(raw)
    raw_mod["_local_legs"] = local_legs

    # Replace the frozen boundary field with our mock.
    summary_mod = dataclasses.replace(summary, boundary=_MockBoundary(cloud_segments))

    return build_picked_session_summary(raw_mod, summary_mod, entry, "test-label")


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


def test_split_classifies_traversal_correctly():
    """When local leg extends PAST the cloud segment, tail goes to traversal_legs."""
    raw, summary, entry = _load_session("short")

    # Cloud covers only (2,5)→(4,5); local continues to (8,8) = traversal.
    cloud = [[[2.0, 5.0], [4.0, 5.0]]]
    local = [[[2.0, 5.0], [4.0, 5.0], [8.0, 8.0]]]

    result = _build_result_with_split(raw, summary, entry, local, cloud)

    mowing_legs = result["mowing_legs"]
    traversal_legs = result["traversal_legs"]

    # At minimum one mowing leg covering the cloud portion.
    assert len(mowing_legs) >= 1, f"expected mowing_legs, got {mowing_legs}"
    # At minimum one traversal leg for the dock-return tail.
    assert len(traversal_legs) >= 1, f"expected traversal_legs, got {traversal_legs}"

    # Traversal segment must contain the out-of-cloud point (8, 8).
    trav_pts = [pt for leg in traversal_legs for pt in leg]
    assert any(
        abs(pt[0] - 8.0) < 0.01 and abs(pt[1] - 8.0) < 0.01
        for pt in trav_pts
    ), f"(8,8) traversal point not found in traversal_legs: {traversal_legs}"


def test_no_traversal_when_local_matches_cloud_exactly():
    """When local == cloud exactly, traversal_legs should be empty."""
    raw, summary, entry = _load_session("short")

    cloud = [[[2.0, 5.0], [4.0, 5.0]]]
    local = [[[2.0, 5.0], [4.0, 5.0]]]  # identical

    result = _build_result_with_split(raw, summary, entry, local, cloud)

    assert result["traversal_legs"] == [], (
        f"expected no traversal when local==cloud, got {result['traversal_legs']}"
    )
    assert len(result["mowing_legs"]) >= 1


def test_empty_cloud_all_local_is_traversal():
    """No cloud segments → all local motion is classified as traversal."""
    raw, summary, entry = _load_session("short")

    cloud: list = []
    local = [[[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]]

    result = _build_result_with_split(raw, summary, entry, local, cloud)

    assert result["mowing_legs"] == [], (
        f"expected empty mowing_legs with no cloud, got {result['mowing_legs']}"
    )
    assert len(result["traversal_legs"]) >= 1


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
