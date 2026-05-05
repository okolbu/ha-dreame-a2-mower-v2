"""Tests for inventory_gen.py's chapter renderer."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_gen.py"


def test_render_one_property() -> None:
    expected = (FIXTURES / "render_one_property.expected.md").read_text()
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                str(FIXTURES / "render_one_property.yaml"),
                "--output-dir", str(out_dir),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        canonical = (out_dir / "g2408-canonical.md").read_text()
        assert "## Properties" in canonical
        for line in expected.splitlines():
            if line.strip():
                assert line in canonical, f"missing line: {line!r}"


def test_render_skips_empty_chapters() -> None:
    """A section with no rows should not render an empty table."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                str(FIXTURES / "good_inventory.yaml"),
                "--output-dir", str(out_dir),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        canonical = (out_dir / "g2408-canonical.md").read_text()
        assert "## Properties" in canonical
        assert "## Events\n\n_(none)_" in canonical
