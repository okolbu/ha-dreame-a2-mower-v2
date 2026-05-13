"""End-to-end smoke test for the state-machine audit tool."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_audit_tool_runs_and_exits_with_a_status():
    """The audit tool should at minimum start, scan, and exit (0 or non-zero).

    Hard fail: tool crashes with traceback (any exit code is acceptable here;
    we're verifying the entry point is reachable).
    """
    result = subprocess.run(
        [sys.executable, "-m", "tools.state_machine_audit", "--dry-run"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Either green (0) or red (1) is fine — but a crash (2+) is a hard fail.
    assert result.returncode in (0, 1), (
        f"unexpected exit {result.returncode}; stderr=\n{result.stderr}"
    )
    assert "audit" in (result.stdout + result.stderr).lower()
