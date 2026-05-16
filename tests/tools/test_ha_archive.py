"""Tests for tools._rebuild_session_lib.ha_archive."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools._rebuild_session_lib.ha_archive import (
    HAArchiveFetcher,
    parse_archive_filename,
)


def test_parse_archive_filename_with_md5():
    name = "2026-05-16_1778893682_7bff1b02.json"
    parsed = parse_archive_filename(name)
    assert parsed is not None
    assert parsed.date == "2026-05-16"
    assert parsed.end_ts == 1778893682
    assert parsed.md5 == "7bff1b02"
    assert parsed.is_recovered is False


def test_parse_archive_filename_recovered():
    name = "2026-04-20_1776681188_rec_6fe0.json"
    parsed = parse_archive_filename(name)
    assert parsed is not None
    assert parsed.date == "2026-04-20"
    assert parsed.end_ts == 1776681188
    assert parsed.md5 == "rec_6fe0"
    assert parsed.is_recovered is True


def test_parse_archive_filename_returns_none_on_garbage():
    assert parse_archive_filename("not_a_session.txt") is None


def test_fetcher_list_archives_parses_remote_ls():
    fake_ls = (
        "2026-05-15_1778893682_7bff1b02.json\n"
        "2026-04-20_1776681188_rec_6fe0.json\n"
        "garbage.txt\n"
    )
    with patch(
        "tools._rebuild_session_lib.ha_archive._run_ssh",
        return_value=fake_ls,
    ):
        f = HAArchiveFetcher(host="x", user="x", password="x", remote_dir="/r")
        archives = f.list_archives()
    assert len(archives) == 2
    # Sorted by end_ts ascending
    assert archives[0].end_ts == 1776681188
    assert archives[1].end_ts == 1778893682


def test_fetcher_dry_run_does_not_scp(tmp_path: Path):
    """In dry-run mode, push() returns the would-be path but doesn't
    actually invoke scp."""
    # Create a fake local file (push reads it; in dry-run nothing happens)
    fake = tmp_path / "x.json"
    fake.write_text("{}")
    f = HAArchiveFetcher(
        host="x", user="x", password="x", remote_dir="/r",
        dry_run=True,
    )
    with patch("tools._rebuild_session_lib.ha_archive._run_scp") as mock_scp:
        f.push_archive(local_path=fake, remote_filename="x.json")
        mock_scp.assert_not_called()
