"""Tests for the minimal PCD v0.7 parser used by the LiDAR pipeline.

Sample fixture `lidar_sample.pcd` is the real g2408 upload captured
2026-04-19 12:10:34 (145,257 points, 2.32 MB).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.protocol.pcd import PCDHeaderError, parse_pcd_header, parse_pcd


def test_header_from_real_capture(fixtures_dir: Path):
    data = (fixtures_dir / "lidar_sample.pcd").read_bytes()
    header, body_offset = parse_pcd_header(data)

    assert header.version == "0.7"
    assert header.fields == ["x", "y", "z", "rgb"]
    assert header.sizes == [4, 4, 4, 4]
    assert header.types == ["F", "F", "F", "U"]
    assert header.counts == [1, 1, 1, 1]
    assert header.width == 145257
    assert header.height == 1
    assert header.points == 145257
    assert header.data == "binary"
    assert body_offset == 184


def test_parse_full_cloud_returns_expected_point_count(fixtures_dir: Path):
    data = (fixtures_dir / "lidar_sample.pcd").read_bytes()
    cloud = parse_pcd(data)
    assert len(cloud.xyz) == 145257
    assert cloud.xyz.shape == (145257, 3)
    assert cloud.rgb.shape == (145257, 3)


def test_xyz_ranges_match_known_sample(fixtures_dir: Path):
    data = (fixtures_dir / "lidar_sample.pcd").read_bytes()
    cloud = parse_pcd(data)
    x_min, x_max = cloud.xyz[:, 0].min(), cloud.xyz[:, 0].max()
    y_min, y_max = cloud.xyz[:, 1].min(), cloud.xyz[:, 1].max()
    z_min, z_max = cloud.xyz[:, 2].min(), cloud.xyz[:, 2].max()
    # Values documented in the g2408 RE memory from this capture.
    assert -36.0 < x_min < -35.9 and 48.7 < x_max < 48.8
    assert -37.7 < y_min < -37.6 and 63.9 < y_max < 64.0
    assert -1.10 < z_min < -1.08 and 11.38 < z_max < 11.39


def test_rgb_decoded_as_separate_channels(fixtures_dir: Path):
    data = (fixtures_dir / "lidar_sample.pcd").read_bytes()
    cloud = parse_pcd(data)
    # First sample point in this fixture has rgb=(0, 3, 0) per earlier analysis.
    assert tuple(cloud.rgb[0]) == (0, 3, 0)


def test_header_rejects_missing_required_fields():
    bad = (
        b"# .PCD v0.7\n"
        b"VERSION 0.7\n"
        b"FIELDS x y z\n"
        b"SIZE 4 4 4\n"
        b"# missing TYPE/COUNT/WIDTH/HEIGHT/POINTS/DATA\n"
        b"DATA ascii\n"
    )
    with pytest.raises(PCDHeaderError):
        parse_pcd_header(bad)


def test_header_rejects_non_binary_data_format():
    """First pass only supports the format the mower actually emits."""
    bad = (
        b"# .PCD v0.7\n"
        b"VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        b"WIDTH 3\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 3\nDATA ascii\n"
    )
    with pytest.raises(PCDHeaderError):
        parse_pcd(bad)


def test_parse_pcd_cloud_carries_point_stride_and_bytes_per_point():
    """Consumers (render / archive) may want raw bytes too."""
    data = (
        b"VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        b"WIDTH 1\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 1\nDATA binary\n"
    )
    # one point at (1.0, 2.0, 3.0)
    body = b"\x00\x00\x80\x3f\x00\x00\x00\x40\x00\x00\x40\x40"
    cloud = parse_pcd(data + body)
    assert cloud.bytes_per_point == 12
    assert len(cloud.xyz) == 1
    # default rgb filled with zeros when not present in the file
    assert cloud.rgb.shape == (1, 3)
