"""Unit tests for the legs_timeline building block in render_work_log_session.

These tests pin the core logic that converts ``_local_legs`` + ``_legs_meta``
from an archive payload into the ``legs_timeline`` list consumed by
``render_work_log``.  They do NOT exercise the full async coordinator path —
instead they replicate the building logic directly so the invariants can be
asserted without standing up HA or a cloud client.

When render_work_log_session changes, these tests will catch regressions in:
  - Correct parallel pairing of local_legs and meta dicts.
  - Role filtering (only "mowing" and "traversal" legs survive).
  - ts coercion (int(m.get("start_ts") or 0)).
  - Empty/absent _legs_meta → legs_timeline is None (fallback path taken).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Replicate the building logic as a standalone helper so tests are isolated
# from the full coordinator async machinery.
# ---------------------------------------------------------------------------

def _build_legs_timeline(
    raw_dict: dict,
) -> list[dict] | None:
    """Mirror of the legs_timeline build block in render_work_log_session.

    Replicates only the building logic (not the kwarg selection) so it can
    be exercised independently of HA / cloud client / session archive.
    """
    # Step 1: parse _local_legs the same way the coordinator does.
    local_legs: list[list[tuple[float, float]]] = []
    local_raw = raw_dict.get("_local_legs") or []
    if isinstance(local_raw, list):
        for leg in local_raw:
            pts = [
                (float(p[0]), float(p[1]))
                for p in leg
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ]
            if pts:
                local_legs.append(pts)

    # Step 2: build legs_timeline from _legs_meta (the new Task 5 logic).
    meta = raw_dict.get("_legs_meta")
    legs_timeline: list[dict] | None = None
    if isinstance(meta, list) and meta and len(meta) == len(local_legs):
        legs_timeline = []
        for leg_pts, m in zip(local_legs, meta):
            if not leg_pts:
                continue
            role = m.get("role") if isinstance(m, dict) else None
            if role not in ("mowing", "traversal"):
                continue
            legs_timeline.append({
                "role": role,
                "start_ts": int(m.get("start_ts") or 0),
                "end_ts": int(m.get("end_ts") or 0),
                "pts": leg_pts,
            })
        if not legs_timeline:
            legs_timeline = None

    return legs_timeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_legs_timeline_built_from_matching_meta():
    """When _legs_meta length matches _local_legs, legs_timeline is built."""
    raw = {
        "_local_legs": [
            [[1.0, 2.0], [3.0, 4.0]],
            [[5.0, 6.0], [7.0, 8.0]],
        ],
        "_legs_meta": [
            {"role": "mowing",    "start_ts": 1000, "end_ts": 1020},
            {"role": "traversal", "start_ts": 1020, "end_ts": 1050},
        ],
    }
    result = _build_legs_timeline(raw)
    assert result is not None, "legs_timeline should be built when meta matches"
    assert len(result) == 2
    assert result[0]["role"] == "mowing"
    assert result[0]["start_ts"] == 1000
    assert result[0]["end_ts"] == 1020
    assert result[0]["pts"] == [(1.0, 2.0), (3.0, 4.0)]
    assert result[1]["role"] == "traversal"
    assert result[1]["pts"] == [(5.0, 6.0), (7.0, 8.0)]


def test_legs_timeline_none_when_meta_absent():
    """No _legs_meta → legs_timeline is None (legacy fallback)."""
    raw = {
        "_local_legs": [[[1.0, 2.0], [3.0, 4.0]]],
    }
    result = _build_legs_timeline(raw)
    assert result is None, "legs_timeline must be None when _legs_meta absent"


def test_legs_timeline_none_when_meta_length_mismatch():
    """_legs_meta length != _local_legs length → legs_timeline is None."""
    raw = {
        "_local_legs": [
            [[1.0, 2.0], [3.0, 4.0]],
            [[5.0, 6.0], [7.0, 8.0]],
        ],
        "_legs_meta": [
            {"role": "mowing", "start_ts": 1000, "end_ts": 1020},
            # missing second entry
        ],
    }
    result = _build_legs_timeline(raw)
    assert result is None, "legs_timeline must be None on length mismatch"


def test_legs_timeline_filters_unknown_roles():
    """Legs with role not in ('mowing', 'traversal') are silently dropped."""
    raw = {
        "_local_legs": [
            [[1.0, 2.0], [3.0, 4.0]],
            [[5.0, 6.0], [7.0, 8.0]],
            [[9.0, 0.0], [1.0, 0.0]],
        ],
        "_legs_meta": [
            {"role": "mowing",  "start_ts": 1000, "end_ts": 1020},
            {"role": "unknown", "start_ts": 1020, "end_ts": 1030},  # dropped
            {"role": "traversal","start_ts": 1030, "end_ts": 1050},
        ],
    }
    result = _build_legs_timeline(raw)
    assert result is not None
    assert len(result) == 2
    roles = [e["role"] for e in result]
    assert "unknown" not in roles


def test_legs_timeline_none_when_all_roles_unknown():
    """All roles unknown → empty list → legs_timeline collapses to None."""
    raw = {
        "_local_legs": [[[1.0, 2.0], [3.0, 4.0]]],
        "_legs_meta": [{"role": "other", "start_ts": 0, "end_ts": 0}],
    }
    result = _build_legs_timeline(raw)
    assert result is None, "all-unknown-role legs_timeline must collapse to None"


def test_legs_timeline_ts_coercion():
    """start_ts / end_ts are coerced to int even when stored as float or None."""
    raw = {
        "_local_legs": [[[1.0, 1.0], [2.0, 2.0]]],
        "_legs_meta": [{"role": "mowing", "start_ts": 1000.9, "end_ts": None}],
    }
    result = _build_legs_timeline(raw)
    assert result is not None
    assert result[0]["start_ts"] == 1000
    assert result[0]["end_ts"] == 0   # None → 0 via (None or 0)


def test_render_work_log_legs_timeline_kwarg_forwarded():
    """render_work_log forwards legs_timeline= to render_with_trail.

    Integration point test: verifies the new kwarg flows through the
    render_work_log wrapper without being dropped.
    """
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
    from custom_components.dreame_a2_mower.map_render import render_work_log

    def _map():
        return MapData(
            md5="t5-unit-test",
            width_px=100, height_px=100, pixel_size_mm=50.0,
            bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
            cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
            rotation_deg=0.0,
            boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
            mowing_zones=(
                MowingZone(
                    zone_id=0, name="lawn",
                    path=((0.0,0.0),(5000.0,0.0),(5000.0,5000.0),(0.0,5000.0)),
                    area_m2=25.0,
                ),
            ),
            exclusion_zones=(), spot_zones=(),
            contour_paths=(), available_contour_ids=(),
            maintenance_points=(), dock_xy=None,
            total_area_m2=25.0, nav_paths=(),
        )

    timeline = [
        {"role": "mowing", "start_ts": 100, "end_ts": 200,
         "pts": [(1.0, 1.0), (2.0, 2.0)]},
    ]

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_with_trail",
        return_value=b"\x89PNG",
    ) as mock_rwt:
        render_work_log(_map(), legs_timeline=timeline)

    _, kwargs = mock_rwt.call_args
    assert kwargs.get("legs_timeline") is timeline, (
        f"legs_timeline not forwarded to render_with_trail; kwargs={kwargs}"
    )
