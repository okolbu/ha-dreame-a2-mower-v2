"""entity-inventory.yaml must cover every concrete entity class in code."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_entity_inventory_is_complete():
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "entity_inventory_audit.py")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "entity-inventory.yaml is missing entries:\n" + r.stdout
    )
