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


def test_audit_reports_battery_level_classifications():
    """Post-R7/R10: sensor.battery_level should appear and be GREEN.

    R3 rewired battery_level to read snapshot; R10 refined the YAML
    expectation to `idle: unavailable` + `reboot: required` to account
    for the audit-harness fake-coord cold-start limitation (no
    load_persisted call). Both idle and reboot checks should now be
    GREEN.
    """
    r = _run()
    lines = [ln for ln in r.stdout.splitlines() if "battery_level" in ln]
    assert lines, "expected battery_level rows in audit output"
    assert all("RED" not in ln.upper() for ln in lines), (
        "expected zero RED battery_level rows post-R10; got:\n"
        + "\n".join(lines)
    )


def test_audit_exit_zero_when_no_reds():
    """Post-R1..R10: audit should run clean (no reds) → exit 0."""
    r = _run()
    assert r.returncode == 0, (
        f"expected exit 0 (no reds) after R10 refinements; got {r.returncode}"
    )
