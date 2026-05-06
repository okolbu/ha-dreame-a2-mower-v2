"""pytest config for inventory tests — makes the integration importable."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `custom_components.dreame_a2_mower.*` importable from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
