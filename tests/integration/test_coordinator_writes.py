"""Tests for coordinator-level write helpers + mutex."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock


def test_coordinator_init_declares_chunked_write_lock():
    """Regex check that __init__ creates self._chunked_write_lock as Lock()."""
    src = Path("custom_components/dreame_a2_mower/coordinator.py").read_text()
    assert re.search(
        r"self\._chunked_write_lock\s*:\s*asyncio\.Lock\s*=\s*asyncio\.Lock\(\)",
        src,
    ), "coordinator.__init__ should declare self._chunked_write_lock"
