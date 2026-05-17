"""Pure splitter — local legs union cloud track-segments → (mowing, traversal)."""
from custom_components.dreame_a2_mower._render_trail_split import split_trail


def test_no_local_legs_all_cloud_mowing():
    """If only cloud segments exist (older session), everything is mowing."""
    mowing, traversal = split_trail(
        local_legs=[],
        cloud_segments=[[(0.0, 0.0), (1.0, 1.0)]],
    )
    assert mowing == [[(0.0, 0.0), (1.0, 1.0)]]
    assert traversal == []


def test_no_cloud_all_local_traversal():
    """If only local legs exist (cloud truncated), everything is traversal —
    we cannot tell what was mowing vs not, so default to grey."""
    mowing, traversal = split_trail(
        local_legs=[[(0.0, 0.0), (1.0, 1.0)]],
        cloud_segments=[],
    )
    assert mowing == []
    assert traversal == [[(0.0, 0.0), (1.0, 1.0)]]


def test_local_points_overlapping_cloud_are_mowing():
    """Local legs that touch cloud segments are reclassified as mowing —
    the cloud is authoritative about what counts as a cut."""
    local = [[(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]]
    cloud = [[(0.0, 0.0), (1.0, 1.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    # The first two points overlap cloud → mowing; the third (2,2) doesn't → traversal.
    # split_trail's contract: contiguous overlapping runs go into mowing;
    # the post-overlap tail becomes a traversal segment starting from the
    # last mowing point (so the visual line is continuous).
    assert mowing == [[(0.0, 0.0), (1.0, 1.0)]]
    assert traversal == [[(1.0, 1.0), (2.0, 2.0)]]


def test_dock_return_at_end_is_traversal():
    """Realistic case: mow a leg, then drive back to dock at end."""
    local = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (5.0, 5.0)]]
    cloud = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    assert mowing == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
    assert traversal == [[(2.0, 0.0), (5.0, 5.0)]]


def test_multiple_legs_handled_independently():
    local = [
        [(0.0, 0.0), (1.0, 0.0), (10.0, 10.0)],
        [(20.0, 20.0), (21.0, 20.0), (30.0, 30.0)],
    ]
    cloud = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(20.0, 20.0), (21.0, 20.0)],
    ]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    assert len(mowing) == 2
    assert len(traversal) == 2
    assert traversal[0] == [(1.0, 0.0), (10.0, 10.0)]
    assert traversal[1] == [(21.0, 20.0), (30.0, 30.0)]


def test_point_match_tolerance():
    """Local point within 1cm (10mm) of a cloud point is treated as the same."""
    local = [[(0.0, 0.0), (1000.005, 1000.005), (2000.0, 2000.0)]]  # mm coords
    cloud = [[(0.0, 0.0), (1000.0, 1000.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud, tol_mm=10.0)
    # The (1000.005, 1000.005) local point should be matched to (1000, 1000) cloud point.
    assert mowing == [[(0.0, 0.0), (1000.005, 1000.005)]]
    assert traversal == [[(1000.005, 1000.005), (2000.0, 2000.0)]]
