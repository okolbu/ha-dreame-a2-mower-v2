"""Tests for M_PATH regex decoder."""
from __future__ import annotations

from pathlib import Path

from custom_components.dreame_a2_mower.protocol.m_path import (
    parse_m_path_batch,
)

FIXTURE = Path(__file__).parent / "fixtures" / "2026-05-08-m-path-sample.txt"


def test_parse_empty_string_returns_empty_dict():
    assert parse_m_path_batch("", split_pos=0) == {}


def test_parse_single_map_no_split():
    """No split (info=0): all coordinates belong to map_id=0."""
    raw = "[100,200],[200,300],[32767,-32768],[400,500]"
    result = parse_m_path_batch(raw, split_pos=0)
    assert set(result.keys()) == {0}
    # Coords are 1/10th-scale (decimeters); decoder multiplies by 10 for mm.
    assert result[0].segments == (
        ((1000, 2000), (2000, 3000)),
        ((4000, 5000),),
    )


def test_parse_two_maps_split_skips_first_segment():
    """split_pos > 0 means skip the first split_pos chars (legacy upstream pattern).
    Bytes [0:split_pos] are Map 0's data; remainder is Map 1's."""
    raw = FIXTURE.read_text()  # leading "[]" then Map 1 data
    # split_pos=2 means the leading "[]" is Map 0 (empty); skip it.
    result = parse_m_path_batch(raw, split_pos=2)
    assert 0 in result
    assert 1 in result
    assert result[0].segments == ()  # empty Map 0
    # Map 1 has two segments separated by a sentinel.
    assert len(result[1].segments) == 2
    assert result[1].segments[0] == ((-1000, -2000), (1000, 2000), (2000, 3000))
    assert result[1].segments[1] == ((4000, 5000), (5000, 6000))


def test_parse_no_pairs_returns_empty_segments():
    """Whitespace / empty content yields empty segments (not crash)."""
    result = parse_m_path_batch("[]", split_pos=0)
    assert 0 in result
    assert result[0].segments == ()


def test_parse_handles_split_pos_larger_than_raw():
    """Defensive: split_pos > len(raw) treated as 0."""
    raw = "[100,200]"
    result = parse_m_path_batch(raw, split_pos=999)
    assert 0 in result
