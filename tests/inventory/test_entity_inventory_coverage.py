"""entity-inventory.yaml must cover every concrete entity class in code."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.xfail(
    reason="entity-inventory port in progress — Task 10 of the port flips this green",
    strict=True,
)
def test_entity_inventory_is_complete():
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "entity_inventory_audit.py")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "entity-inventory.yaml is missing entries:\n" + r.stdout
    )
