"""End-to-end smoke + behavioural test for the state-machine audit tool."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools.state_machine_audit"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_audit_does_not_crash():
    r = _run()
    assert r.returncode in (0, 1), f"crashed with exit {r.returncode}: {r.stderr}"


def test_audit_prints_status_summary():
    r = _run()
    out = r.stdout
    assert "green" in out.lower()
    assert "red" in out.lower()


def test_audit_reports_battery_level():
    """sensor.battery_level must appear in the audit output."""
    r = _run()
    assert "sensor.battery_level" in r.stdout


def test_audit_reports_known_red_for_battery_level():
    """Pre-rewire: sensor.battery_level should be RED (idle + reboot)."""
    r = _run()
    # Find the battery line and confirm it's classified red somewhere
    lines = [ln for ln in r.stdout.splitlines() if "battery_level" in ln]
    assert any("RED" in ln.upper() for ln in lines), (
        "expected at least one RED battery_level row; got:\n" + "\n".join(lines)
    )


def test_audit_non_zero_exit_when_reds_exist():
    """Initial-state run has reds → exit 1."""
    r = _run()
    assert r.returncode == 1, f"expected exit 1; got {r.returncode}"
