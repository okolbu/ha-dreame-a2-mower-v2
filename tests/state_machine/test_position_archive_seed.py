"""Test the cold-start position seed from session_archive."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from custom_components.dreame_a2_mower.coordinator import (
    _read_last_position_from_archive,
)


def _make_archive(tmp_path: Path, legs: list, filename: str = "session_test.json"):
    """Build a minimal archive structure on disk."""
    (tmp_path / filename).write_text(json.dumps({"_local_legs": legs}))
    entry = SimpleNamespace(filename=filename, still_running=False)
    archive = SimpleNamespace(
        root=tmp_path,
        load_index=lambda: None,
        list_sessions=lambda: [entry],
    )
    return archive


def test_returns_last_point_of_last_leg(tmp_path: Path):
    archive = _make_archive(tmp_path, legs=[
        [[1.0, 1.0], [1.5, 1.5]],
        [[2.0, 2.0], [0.27, -0.09]],  # most recent point
    ])
    assert _read_last_position_from_archive(archive) == (0.27, -0.09)


def test_returns_none_when_no_sessions(tmp_path: Path):
    archive = SimpleNamespace(
        root=tmp_path,
        load_index=lambda: None,
        list_sessions=lambda: [],
    )
    assert _read_last_position_from_archive(archive) is None


def test_skips_empty_legs(tmp_path: Path):
    """Trailing empty legs should be skipped to find the last real point."""
    archive = _make_archive(tmp_path, legs=[
        [[1.0, 2.0]],
        [],  # empty trailing leg
    ])
    assert _read_last_position_from_archive(archive) == (1.0, 2.0)


def test_skips_in_progress_entries(tmp_path: Path):
    """still_running=True entries are in-progress; skip and use the next."""
    (tmp_path / "real.json").write_text(json.dumps({"_local_legs": [[[5.0, 5.0]]]}))
    in_prog = SimpleNamespace(filename="in_progress.json", still_running=True)
    real = SimpleNamespace(filename="real.json", still_running=False)
    archive = SimpleNamespace(
        root=tmp_path,
        load_index=lambda: None,
        list_sessions=lambda: [in_prog, real],
    )
    assert _read_last_position_from_archive(archive) == (5.0, 5.0)


def test_skips_unreadable_blob(tmp_path: Path):
    """If the most recent session's blob is unreadable, try older ones."""
    (tmp_path / "good.json").write_text(json.dumps({"_local_legs": [[[3.0, 4.0]]]}))
    bad = SimpleNamespace(filename="missing.json", still_running=False)
    good = SimpleNamespace(filename="good.json", still_running=False)
    archive = SimpleNamespace(
        root=tmp_path,
        load_index=lambda: None,
        list_sessions=lambda: [bad, good],
    )
    assert _read_last_position_from_archive(archive) == (3.0, 4.0)
