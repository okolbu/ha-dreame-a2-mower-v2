"""Tests for forbidden-zone rotation in the cloud-map parser."""

from __future__ import annotations

import math

import pytest

from protocol.cloud_map_geom import _rotate_path_around_centroid


def test_zero_angle_returns_same_coords():
    path = [
        {"x": 1000.0, "y": 2000.0},
        {"x": 2000.0, "y": 2000.0},
        {"x": 2000.0, "y": 3000.0},
        {"x": 1000.0, "y": 3000.0},
    ]
    out = _rotate_path_around_centroid(path, 0)
    for a, b in zip(path, out):
        assert math.isclose(a["x"], b["x"]) and math.isclose(a["y"], b["y"])


def test_none_angle_returns_same_coords():
    path = [{"x": 5.0, "y": 10.0}, {"x": 15.0, "y": 10.0}]
    out = _rotate_path_around_centroid(path, None)
    assert len(out) == 2
    assert out[0]["x"] == 5.0 and out[0]["y"] == 10.0


def test_90_degrees_rotates_unit_square():
    """Unit square centred at origin → 90° rotation swaps x/y with sign flip."""
    # corners in canonical order (CCW): (1,1), (-1,1), (-1,-1), (1,-1)
    path = [
        {"x": 1.0, "y": 1.0},
        {"x": -1.0, "y": 1.0},
        {"x": -1.0, "y": -1.0},
        {"x": 1.0, "y": -1.0},
    ]
    out = _rotate_path_around_centroid(path, 90)
    # 90° CCW rotation: (x,y) → (-y, x)
    expected = [(-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0), (1.0, 1.0)]
    for (ex, ey), got in zip(expected, out):
        assert math.isclose(got["x"], ex, abs_tol=1e-9)
        assert math.isclose(got["y"], ey, abs_tol=1e-9)


def test_centroid_unchanged_after_rotation():
    """Rotating around the centroid keeps the centroid in place."""
    path = [
        {"x": 100.0, "y": 200.0},
        {"x": 300.0, "y": 250.0},
        {"x": 280.0, "y": 500.0},
        {"x": 80.0, "y": 470.0},
    ]
    in_cx = sum(p["x"] for p in path) / 4
    in_cy = sum(p["y"] for p in path) / 4
    out = _rotate_path_around_centroid(path, 37.5)
    out_cx = sum(p["x"] for p in out) / 4
    out_cy = sum(p["y"] for p in out) / 4
    assert math.isclose(in_cx, out_cx, abs_tol=1e-6)
    assert math.isclose(in_cy, out_cy, abs_tol=1e-6)


def test_captured_forbiddenarea_has_expected_rotated_corners():
    """Fixture: the real capture from 2026-04-19 had axis-aligned path
    and angle=-30.77°. After rotation the corners should form a true
    rotated rectangle (edge vectors 90° apart, lengths preserved)."""
    path = [
        {"x": 12819.85, "y": 12543.97},
        {"x": 1425.42,  "y": 12543.97},
        {"x": 1430.15,  "y": 20956.03},
        {"x": 12815.99, "y": 20961.15},
    ]
    out = _rotate_path_around_centroid(path, -30.77)

    # After rotation the edges should still be perpendicular (roughly —
    # the input was already slightly off due to real-world measurement).
    def vec(a, b):
        return (b["x"] - a["x"], b["y"] - a["y"])

    def length(v):
        return math.hypot(*v)

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1]

    e01 = vec(out[0], out[1])
    e12 = vec(out[1], out[2])

    # Input side lengths (rotation is an isometry).
    in_e01 = vec(path[0], path[1])
    in_e12 = vec(path[1], path[2])
    assert math.isclose(length(e01), length(in_e01), rel_tol=1e-6)
    assert math.isclose(length(e12), length(in_e12), rel_tol=1e-6)

    # Rotation is an isometry, so the dot product between any two edges
    # is preserved (not necessarily zero — the raw capture has sub-mm
    # measurement noise).
    in_dot = dot(in_e01, in_e12)
    out_dot = dot(e01, e12)
    assert math.isclose(in_dot, out_dot, rel_tol=1e-6, abs_tol=1e-3)


def test_skips_malformed_points():
    path = [
        {"x": 1.0, "y": 2.0},
        {"y": 3.0},              # missing x
        "not a dict",            # bogus
        {"x": 4.0, "y": 5.0},
    ]
    out = _rotate_path_around_centroid(path, 45)
    # Two valid input points → two valid output points.
    assert len(out) == 2
