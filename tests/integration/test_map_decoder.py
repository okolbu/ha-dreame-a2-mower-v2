"""Smoke tests for map_decoder.parse_cloud_map.

Uses a synthetic MAP.* payload shaped like the real g2408 cloud response
described in docs/research/cloud-map-geometry.md.  No live fixture file
exists yet; the values are taken from the worked example in §7 of that doc.

Real boundary (2026-04-19 capture):
  bx1=-10920, by1=-14080, bx2=20890, by2=20961
  totalArea=383.74 m²
  one forbidden zone with angle=-30.77°
"""
from __future__ import annotations

import sys
import types


# ---------------------------------------------------------------------------
# Minimal stub for 'protocol' package so import works outside HA venv.
# cloud_map_geom is a real module (pure Python, no HA deps); we just
# need the package path wired in.
# ---------------------------------------------------------------------------
import importlib
import importlib.util
import os
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
# Ensure protocol/ is importable.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Also make custom_components importable.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Synthetic fixture — mirrors the real g2408 cloud payload shape.
# ---------------------------------------------------------------------------

FORBIDDEN_ZONE_PATH = [
    {"x": 12819.85, "y": 12543.97},
    {"x":  1425.42, "y": 12543.97},
    {"x":  1430.15, "y": 20956.03},
    {"x": 12815.99, "y": 20961.15},
]

_MINIMAL_MAP = {
    "boundary": {"x1": -10920, "y1": -14080, "x2": 20890, "y2": 20961},
    "mowingAreas": {
        "value": [
            [
                1,
                {
                    "path": [
                        {"x": -5000, "y": -5000},
                        {"x": 15000, "y": -5000},
                        {"x": 15000, "y": 15000},
                        {"x": -5000, "y": 15000},
                    ],
                    "name": "Front Lawn",
                    "shapeType": 0,
                },
            ]
        ]
    },
    "forbiddenAreas": {
        "value": [
            [
                101,
                {
                    "path": FORBIDDEN_ZONE_PATH,
                    "angle": -30.77,
                    "shapeType": 2,
                },
            ]
        ]
    },
    "notObsAreas": {"value": []},
    "spotAreas": {"value": []},
    "contours": {
        "value": [
            [
                [1, 0],
                {
                    "path": [
                        {"x": -5000, "y": -5000},
                        {"x": 15000, "y": -5000},
                        {"x": 15000, "y": 15000},
                        {"x": -5000, "y": 15000},
                    ],
                    "shapeType": 0,
                },
            ]
        ]
    },
    "cleanPoints": {
        "value": [
            [1, {"path": [{"x": 5000, "y": 5000}]}],
        ]
    },
    "totalArea": 383.74,
    "md5sum": "volatile_cloud_hash_abc123",
    "mapIndex": 0,
    "hasBack": 1,
    "name": "",
    "cut": [],
    "merged": False,
}


# ---------------------------------------------------------------------------
# Import the module under test.
# ---------------------------------------------------------------------------
from custom_components.dreame_a2_mower.map_decoder import (  # noqa: E402
    ExclusionZone,
    MaintenancePoint,
    MapData,
    MowingZone,
    join_map_parts,
    parse_cloud_map,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseCloudMap:
    """Core parse_cloud_map behaviour."""

    def test_returns_non_none_on_valid_input(self):
        """parse_cloud_map returns a MapData for a valid cloud dict."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result is not None

    def test_returns_map_data_type(self):
        """Result is a MapData instance."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert isinstance(result, MapData)

    def test_returns_none_for_non_dict(self):
        """None input → None output."""
        assert parse_cloud_map(None) is None  # type: ignore[arg-type]
        assert parse_cloud_map([]) is None  # type: ignore[arg-type]
        assert parse_cloud_map("string") is None  # type: ignore[arg-type]

    def test_returns_none_for_missing_boundary(self):
        """Dict without 'boundary' key → None."""
        assert parse_cloud_map({"mowingAreas": {}}) is None

    def test_returns_none_for_zero_boundary(self):
        """All-zero boundary (empty/error response) → None."""
        payload = dict(_MINIMAL_MAP)
        payload["boundary"] = {"x1": 0, "y1": 0, "x2": 0, "y2": 0}
        assert parse_cloud_map(payload) is None

    def test_md5_is_string(self):
        result = parse_cloud_map(_MINIMAL_MAP)
        assert isinstance(result.md5, str)
        assert len(result.md5) == 32  # MD5 hex

    def test_md5_is_stable(self):
        """Two calls with the same payload produce the same md5."""
        r1 = parse_cloud_map(_MINIMAL_MAP)
        r2 = parse_cloud_map(_MINIMAL_MAP)
        assert r1.md5 == r2.md5

    def test_md5_ignores_volatile_cloud_hash(self):
        """Changing cloud's md5sum field doesn't affect our md5."""
        import copy
        alt = copy.deepcopy(_MINIMAL_MAP)
        alt["md5sum"] = "different_cloud_hash"
        r1 = parse_cloud_map(_MINIMAL_MAP)
        r2 = parse_cloud_map(alt)
        assert r1.md5 == r2.md5

    def test_md5_changes_when_zones_change(self):
        """Mutating a zone path changes our md5."""
        import copy
        alt = copy.deepcopy(_MINIMAL_MAP)
        alt["mowingAreas"]["value"][0][1]["path"][0]["x"] = 99999
        r1 = parse_cloud_map(_MINIMAL_MAP)
        r2 = parse_cloud_map(alt)
        assert r1.md5 != r2.md5

    def test_canvas_dimensions_positive(self):
        """width_px and height_px are > 0."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.width_px > 0
        assert result.height_px > 0

    def test_pixel_size_mm(self):
        """pixel_size_mm is 50.0 (GRID_SIZE_MM)."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.pixel_size_mm == 50.0

    def test_rotation_deg_is_zero(self):
        """g2408 cloud maps have no rotation."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.rotation_deg == 0.0

    def test_boundary_polygon_four_corners(self):
        """boundary_polygon is a 4-tuple of (x, y) pairs."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert len(result.boundary_polygon) == 4
        for pt in result.boundary_polygon:
            assert len(pt) == 2

    def test_mowing_zones_extracted(self):
        """One mowing zone extracted correctly."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert len(result.mowing_zones) == 1
        zone = result.mowing_zones[0]
        assert isinstance(zone, MowingZone)
        assert zone.zone_id == 1
        assert zone.name == "Front Lawn"
        assert len(zone.path) == 4

    def test_exclusion_zones_extracted(self):
        """One exclusion zone extracted from forbiddenAreas."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert len(result.exclusion_zones) == 1
        ez = result.exclusion_zones[0]
        assert isinstance(ez, ExclusionZone)
        assert ez.subtype is None  # classic no-go (not ignore/spot)
        assert len(ez.points) == 4

    def test_exclusion_zone_rotation_applied(self):
        """Exclusion zone with angle=-30.77 is NOT stored as raw axis-aligned path.

        The decoded corners must differ from the input path after rotation +
        reflection, so we verify at least one coordinate moved.
        """
        result = parse_cloud_map(_MINIMAL_MAP)
        ez = result.exclusion_zones[0]
        # Raw first corner: (12819.85, 12543.97)
        raw_x, raw_y = 12819.85, 12543.97
        decoded_x, decoded_y = ez.points[0]
        # At least one axis should differ by more than rounding after rotation.
        assert abs(decoded_x - raw_x) > 1 or abs(decoded_y - raw_y) > 1

    def test_notobsareas_subtype_ignore(self):
        """notObsAreas entries get subtype='ignore'."""
        import copy
        payload = copy.deepcopy(_MINIMAL_MAP)
        payload["notObsAreas"] = {
            "value": [
                [202, {"path": [
                    {"x": 0, "y": 0}, {"x": 1000, "y": 0},
                    {"x": 1000, "y": 1000}, {"x": 0, "y": 1000},
                ], "angle": None}]
            ]
        }
        result = parse_cloud_map(payload)
        ignore_zones = [ez for ez in result.exclusion_zones if ez.subtype == "ignore"]
        assert len(ignore_zones) == 1

    def test_contour_paths_extracted(self):
        """Contour paths are extracted as cloud-frame tuples."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert len(result.contour_paths) == 1
        assert len(result.contour_paths[0]) == 4

    def test_maintenance_points_extracted(self):
        """Clean points are lifted into MaintenancePoint objects."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert len(result.maintenance_points) == 1
        mp = result.maintenance_points[0]
        assert isinstance(mp, MaintenancePoint)
        assert mp.point_id == 1
        assert mp.x_mm == 5000.0
        assert mp.y_mm == 5000.0

    def test_dock_xy_not_none(self):
        """dock_xy is set for a non-zero boundary map."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.dock_xy is not None
        assert len(result.dock_xy) == 2

    def test_dock_xy_charger_offset_applied(self):
        """dock_xy[0] == cloud_x_reflect - CHARGER_OFFSET_MM (800 mm)."""
        from custom_components.dreame_a2_mower.map_decoder import CHARGER_OFFSET_MM
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.dock_xy is not None
        assert result.dock_xy[0] == pytest.approx(result.cloud_x_reflect - CHARGER_OFFSET_MM)
        assert result.dock_xy[1] == pytest.approx(result.cloud_y_reflect)

    def test_cloud_reflect_values(self):
        """cloud_x_reflect / cloud_y_reflect equal bx1+bx2 and by1+by2."""
        result = parse_cloud_map(_MINIMAL_MAP)
        # bx1/bx2 may be expanded by the forbidden zone corners, but the
        # raw boundary is -10920..20890 → x_reflect_raw = 9970.
        # Forbidden zone corners after rotation could expand it.
        assert result.cloud_x_reflect == pytest.approx(result.bx1 + result.bx2)
        assert result.cloud_y_reflect == pytest.approx(result.by1 + result.by2)

    def test_total_area(self):
        """totalArea field is surfaced."""
        result = parse_cloud_map(_MINIMAL_MAP)
        assert result.total_area_m2 == pytest.approx(383.74)

    def test_total_area_defaults_to_zero(self):
        """Missing totalArea → 0.0."""
        import copy
        payload = copy.deepcopy(_MINIMAL_MAP)
        del payload["totalArea"]
        result = parse_cloud_map(payload)
        assert result.total_area_m2 == 0.0

    def test_empty_mowing_zones(self):
        """Payload with no zones returns empty mowing_zones and empty_map-compatible result."""
        import copy
        payload = copy.deepcopy(_MINIMAL_MAP)
        payload["mowingAreas"] = {"value": []}
        result = parse_cloud_map(payload)
        assert result is not None
        assert len(result.mowing_zones) == 0

    def test_frozen_dataclass(self):
        """MapData is frozen — mutation raises FrozenInstanceError."""
        import dataclasses
        result = parse_cloud_map(_MINIMAL_MAP)
        try:
            result.md5 = "mutated"  # type: ignore[misc]
            assert False, "Expected FrozenInstanceError"
        except (dataclasses.FrozenInstanceError, AttributeError):
            pass  # expected


class TestJoinMapParts:
    """join_map_parts helper."""

    def test_joins_parts_and_returns_dict(self):
        """Batch keys MAP.0..MAP.27 are joined and decoded."""
        import json
        raw = json.dumps(_MINIMAL_MAP)
        # Split across two keys to simulate the real batch.
        half = len(raw) // 2
        batch = {"MAP.0": raw[:half], "MAP.1": raw[half:]}
        # Fill remaining keys with empty strings.
        for i in range(2, 28):
            batch[f"MAP.{i}"] = ""
        result = join_map_parts(batch)
        assert isinstance(result, dict)
        assert "boundary" in result

    def test_returns_none_for_empty_batch(self):
        """Empty dict → None."""
        assert join_map_parts({}) is None

    def test_returns_none_for_all_empty_values(self):
        """All empty strings → None."""
        batch = {f"MAP.{i}": "" for i in range(28)}
        assert join_map_parts(batch) is None

    def test_wrapped_list_form(self):
        """Handles [json_string, ...] wrapped form."""
        import json
        inner = json.dumps(_MINIMAL_MAP)
        wrapped = json.dumps([inner])
        batch = {"MAP.0": wrapped}
        for i in range(1, 28):
            batch[f"MAP.{i}"] = ""
        result = join_map_parts(batch)
        assert isinstance(result, dict)
        assert "boundary" in result


import pytest  # noqa: E402 — keep at bottom so pytest.approx is available
