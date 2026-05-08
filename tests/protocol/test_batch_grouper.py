"""Tests for batch family grouping + chunk reassembly."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.batch_grouper import (
    group_keys_by_prefix,
    join_family_chunks,
)


def test_group_by_prefix_basic():
    batch = {
        "MAP.0": "a", "MAP.1": "b", "MAP.info": "5",
        "M_PATH.0": "c", "M_PATH.info": "0",
        "prop.s_auth": "x",
        "standalone": "y",
    }
    fams = group_keys_by_prefix(batch)
    assert fams["MAP"] == ["MAP.0", "MAP.1", "MAP.info"]
    assert fams["M_PATH"] == ["M_PATH.0", "M_PATH.info"]
    assert fams["prop"] == ["prop.s_auth"]
    assert fams["standalone"] == ["standalone"]


def test_join_chunks_in_numeric_order():
    """MAP.10 must NOT come between MAP.1 and MAP.2 — sort numerically."""
    batch = {
        "MAP.0": "first",
        "MAP.1": "second",
        "MAP.10": "eleventh",  # alphabetical sort would put this between 1 and 2
        "MAP.2": "third",
        "MAP.info": "skip",
    }
    raw = join_family_chunks("MAP", batch)
    assert raw == "firstsecondthirdeleventh"


def test_join_chunks_skips_info_key():
    batch = {"MAP.0": "data", "MAP.info": "999"}
    assert join_family_chunks("MAP", batch) == "data"


def test_join_chunks_handles_missing_chunks():
    """If MAP.0 and MAP.2 exist but MAP.1 doesn't, treat the gap as empty."""
    batch = {"MAP.0": "a", "MAP.2": "c"}
    raw = join_family_chunks("MAP", batch)
    assert raw == "ac"


def test_join_chunks_empty_family():
    assert join_family_chunks("NOPE", {"MAP.0": "x"}) == ""
