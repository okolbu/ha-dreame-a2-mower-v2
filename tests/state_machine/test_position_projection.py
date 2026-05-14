"""Test the dock-frame to compass-frame projection helper.

P2+P3 of the position-fix plan: ``_project_north_east`` projects
(x_m, y_m) in the dock's local frame into compass-frame (north_m,
east_m) using the user-set ``station_bearing_deg`` option.

Convention (see coordinator._project_north_east docstring):
    north_m =  x_m * cos(yaw) - y_m * sin(yaw)
    east_m  =  x_m * sin(yaw) + y_m * cos(yaw)
"""
from __future__ import annotations

import math

from custom_components.dreame_a2_mower.coordinator import _project_north_east


def test_returns_none_when_inputs_missing() -> None:
    """Any None input -> (None, None); N/E sensors stay Unknown."""
    assert _project_north_east(None, 1.0, 0) == (None, None)
    assert _project_north_east(1.0, None, 0) == (None, None)
    assert _project_north_east(1.0, 1.0, None) == (None, None)


def test_zero_bearing_passes_through() -> None:
    """At bearing=0, dock-X points north -> north_m=x_m, east_m=y_m.

    cos(0)=1, sin(0)=0:
        north = x*1 - y*0 = x
        east  = x*0 + y*1 = y
    """
    north, east = _project_north_east(1.0, 2.0, 0)
    assert north is not None and east is not None
    assert math.isclose(north, 1.0)
    assert math.isclose(east, 2.0)


def test_ninety_bearing_swaps() -> None:
    """At bearing=90, dock-X points east -> east_m=x_m, north_m=-y_m.

    cos(90)=0, sin(90)=1:
        north = x*0 - y*1 = -y
        east  = x*1 + y*0 = x

    With y=0 the north value collapses to 0 (verified) and east=x.
    """
    north, east = _project_north_east(1.0, 0.0, 90)
    assert north is not None and east is not None
    assert math.isclose(north, 0.0, abs_tol=1e-9)
    assert math.isclose(east, 1.0)


def test_ninety_bearing_y_axis() -> None:
    """y-only check at bearing=90: north = -y, east = 0."""
    north, east = _project_north_east(0.0, 1.0, 90)
    assert north is not None and east is not None
    assert math.isclose(north, -1.0, abs_tol=1e-9)
    assert math.isclose(east, 0.0, abs_tol=1e-9)


def test_one_eighty_bearing_inverts() -> None:
    """At bearing=180, dock-X points south -> north_m=-x_m, east_m=-y_m."""
    north, east = _project_north_east(1.0, 2.0, 180)
    assert north is not None and east is not None
    assert math.isclose(north, -1.0, abs_tol=1e-9)
    assert math.isclose(east, -2.0, abs_tol=1e-9)


def test_user_bearing_91_with_known_position() -> None:
    """User's dock is reportedly at ~91 deg. Mower at dock-frame (0.27, -0.09).

    north_m =  0.27*cos(91) - (-0.09)*sin(91) ~= -0.00471 + 0.0900 ~= 0.0853
    east_m  =  0.27*sin(91) + (-0.09)*cos(91) ~= 0.2699 + 0.00157 ~= 0.2715
    """
    north, east = _project_north_east(0.27, -0.09, 91)
    assert north is not None and east is not None
    # Within 0.01 m tolerance — bearing accuracy isn't sub-cm anyway.
    assert abs(north - 0.0853) < 0.01
    assert abs(east - 0.2715) < 0.01


def test_origin_projects_to_origin() -> None:
    """At any bearing, dock-frame origin maps to compass-frame origin."""
    for bearing in (0, 45, 91, 180, 270, 359):
        north, east = _project_north_east(0.0, 0.0, bearing)
        assert north is not None and east is not None
        assert math.isclose(north, 0.0, abs_tol=1e-9)
        assert math.isclose(east, 0.0, abs_tol=1e-9)


def test_distance_preserved_under_rotation() -> None:
    """Rotation is an isometry: ||(x,y)|| == ||(north,east)|| at any bearing."""
    x, y = 3.0, 4.0  # distance = 5
    for bearing in (0, 30, 91, 180, 270, 359):
        north, east = _project_north_east(x, y, bearing)
        assert north is not None and east is not None
        dist = math.hypot(north, east)
        assert math.isclose(dist, 5.0, abs_tol=1e-9), (
            f"bearing={bearing} dist={dist} (expected 5.0)"
        )
