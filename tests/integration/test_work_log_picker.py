"""Tests for DreameA2WorkLogSelect — picker filters + label format."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect


def _make_archived(**kwargs):
    defaults = dict(
        filename="x.json",
        start_ts=1700000000,
        end_ts=1700001800,
        duration_min=30,
        area_mowed_m2=42.5,
        map_area_m2=100,
        md5="aabbccdd",
        still_running=False,
        local_trail_complete=True,
        map_id=0,
    )
    defaults.update(kwargs)
    return ArchivedSession(**defaults)


def _make_picker():
    coord = MagicMock()
    coord.entry.entry_id = "test"
    coord._cloud = None
    return DreameA2WorkLogSelect(coord)


def test_label_has_mowing_and_map_prefix():
    picker = _make_picker()
    s = _make_archived(map_id=0)
    labels, mapping = picker._build_options_from_sessions([s])
    assert labels[1].startswith("[Mowing] [Map 1]")


def test_label_has_map_question_mark_for_legacy():
    picker = _make_picker()
    s = _make_archived(map_id=-1)
    labels, mapping = picker._build_options_from_sessions([s])
    assert labels[1].startswith("[Mowing] [Map ?]")


def test_in_progress_session_is_filtered_out():
    """A session with still_running=True must NOT appear in picker options."""
    picker = _make_picker()
    in_progress = _make_archived(filename="in_progress.json", md5="", still_running=True)
    completed = _make_archived(filename="abc.json", md5="abc")
    labels, mapping = picker._build_options_from_sessions([in_progress, completed])
    assert len(labels) == 2  # placeholder + 1 completed
    assert "in progress" not in " ".join(labels).lower()
    assert any("[Mowing]" in l for l in labels)


def test_partial_trail_marker_preserved():
    """A non-running session with local_trail_complete=False keeps the ⚠ marker."""
    picker = _make_picker()
    s = _make_archived(local_trail_complete=False)
    labels, mapping = picker._build_options_from_sessions([s])
    assert "⚠" in labels[1]
    assert "[Mowing]" in labels[1]


def test_unique_id_uses_work_log_suffix():
    coord = MagicMock()
    coord.entry.entry_id = "abc123"
    coord._cloud = None
    picker = DreameA2WorkLogSelect(coord)
    assert picker._attr_unique_id == "abc123_work_log"
