"""SCP-based HA session archive fetcher and pusher.

Uses sshpass + ssh + scp behind the scenes. Designed for the
dev-box workflow where credentials live in a local file.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchiveFilename:
    date: str           # "YYYY-MM-DD"
    end_ts: int
    md5: str            # 8-char hex OR "rec_<4-8 char>"
    raw: str            # original filename
    is_recovered: bool  # True if md5 starts with "rec_"


_FILENAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_(\d+)_(rec_[0-9a-f]+|[0-9a-f]{8})\.json$"
)


def parse_archive_filename(name: str) -> ArchiveFilename | None:
    """Parse a session archive filename. Returns None if it doesn't
    match the expected pattern."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    date, end_ts_s, md5 = m.groups()
    return ArchiveFilename(
        date=date,
        end_ts=int(end_ts_s),
        md5=md5,
        raw=name,
        is_recovered=md5.startswith("rec_"),
    )


def _run_ssh(cmd: list[str]) -> str:
    """Run ssh subprocess, return stdout. Raises on non-zero exit."""
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return res.stdout


def _run_scp(cmd: list[str]) -> None:
    """Run scp subprocess. Raises on non-zero exit."""
    subprocess.run(cmd, check=True, capture_output=True, text=True)


class HAArchiveFetcher:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        remote_dir: str,
        dry_run: bool = False,
    ) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.remote_dir = remote_dir
        self.dry_run = dry_run

    def list_archives(self) -> list[ArchiveFilename]:
        cmd = [
            "sshpass", "-p", self.password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.user}@{self.host}",
            f"ls {self.remote_dir}",
        ]
        out = _run_ssh(cmd)
        archives: list[ArchiveFilename] = []
        for line in out.splitlines():
            parsed = parse_archive_filename(line.strip())
            if parsed is not None:
                archives.append(parsed)
        return sorted(archives, key=lambda a: a.end_ts)

    def fetch_archive(self, remote_filename: str, local_path: Path) -> None:
        cmd = [
            "sshpass", "-p", self.password,
            "scp", "-o", "StrictHostKeyChecking=no",
            f"{self.user}@{self.host}:{self.remote_dir}/{remote_filename}",
            str(local_path),
        ]
        _run_scp(cmd)

    def push_archive(self, local_path: Path, remote_filename: str) -> None:
        if self.dry_run:
            return
        cmd = [
            "sshpass", "-p", self.password,
            "scp", "-o", "StrictHostKeyChecking=no",
            str(local_path),
            f"{self.user}@{self.host}:{self.remote_dir}/{remote_filename}",
        ]
        _run_scp(cmd)
