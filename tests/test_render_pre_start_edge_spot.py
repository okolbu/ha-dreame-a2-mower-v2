"""Tests for EDGE / SPOT idle-preview branches in render_main_view.

Regression coverage for the dotted-overlay introduced in Task 8:
- EDGE mode: light-green base + dotted lawn-boundary polygon.
- SPOT mode: light-green base + dotted spot rectangles with fill.

Both tests use a real MapData + SpotZone / MowingZone constructed via
parse_cloud_map so the frozen dataclass contract is satisfied.
"""
from __future__ import annotations

import copy
import pathlib
import sys

# ---------------------------------------------------------------------------
# Path wiring — same pattern as other integration tests.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Re-use the synthetic fixture from test_map_decoder.
# ---------------------------------------------------------------------------
from tests.integration.test_map_decoder import _MINIMAL_MAP  # noqa: E402

from custom_components.dreame_a2_mower.map_decoder import (  # noqa: E402
    parse_cloud_map,
    SpotZone,
)
from custom_components.dreame_a2_mower.map_render import render_main_view  # noqa: E402
from custom_components.dreame_a2_mower.mower.state import ActionMode  # noqa: E402
from custom_components.dreame_a2_mower.mower.state_snapshot import (  # noqa: E402
    MowSession,
)

# PNG magic bytes.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _map_data_with_spot():
    """Return a MapData with one spot zone for SPOT-mode tests."""
    payload = copy.deepcopy(_MINIMAL_MAP)
    # Add a spot zone.  spotAreas format: [[spot_id, {path: [...], name: str}]]
    payload["spotAreas"] = {
        "value": [
            [
                1,
                {
                    "path": [
                        {"x": -2000, "y": -2000},
                        {"x":  2000, "y": -2000},
                        {"x":  2000, "y":  2000},
                        {"x": -2000, "y":  2000},
                    ],
                    "name": "Spot A",
                    "shapeType": 0,
                },
            ]
        ]
    }
    md = parse_cloud_map(payload)
    assert md is not None, "parse_cloud_map returned None"
    return md


def _map_data_no_spot():
    """Return a standard MapData (no spot zones) for EDGE-mode tests."""
    md = parse_cloud_map(_MINIMAL_MAP)
    assert md is not None, "parse_cloud_map returned None"
    return md


class _FakeState:
    """Minimal state object accepted by render_main_view's idle-preview branch."""

    def __init__(self, action_mode: ActionMode) -> None:
        self.action_mode = action_mode
        self.last_all_area_mow_direction_deg: dict = {}
        self.settings_mowing_direction_mode: int = 0


class TestEdgeIdlePreview:
    """EDGE mode: light base + dotted boundary."""

    def test_returns_png(self):
        md = _map_data_no_spot()
        state = _FakeState(ActionMode.EDGE)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=MowSession.BETWEEN_SESSIONS,
        )
        assert isinstance(png, bytes), "render_main_view did not return bytes"
        assert png[:8] == _PNG_SIGNATURE, f"Not a PNG: {png[:8]!r}"

    def test_png_non_trivial(self):
        """Result must be bigger than a pure-blank 1×1 PNG (sanity check)."""
        md = _map_data_no_spot()
        state = _FakeState(ActionMode.EDGE)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=MowSession.BETWEEN_SESSIONS,
        )
        assert len(png) > 500, f"PNG suspiciously small: {len(png)} bytes"

    def test_none_session_also_triggers_preview(self):
        """mow_session=None (not IN_SESSION) should also yield the idle preview."""
        md = _map_data_no_spot()
        state = _FakeState(ActionMode.EDGE)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=None,
        )
        assert png[:8] == _PNG_SIGNATURE


class TestSpotIdlePreview:
    """SPOT mode: light base + dotted spot rectangles with fill."""

    def test_returns_png(self):
        md = _map_data_with_spot()
        state = _FakeState(ActionMode.SPOT)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=MowSession.BETWEEN_SESSIONS,
        )
        assert isinstance(png, bytes), "render_main_view did not return bytes"
        assert png[:8] == _PNG_SIGNATURE, f"Not a PNG: {png[:8]!r}"

    def test_png_non_trivial(self):
        md = _map_data_with_spot()
        state = _FakeState(ActionMode.SPOT)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=MowSession.BETWEEN_SESSIONS,
        )
        assert len(png) > 500, f"PNG suspiciously small: {len(png)} bytes"

    def test_no_spot_zones_still_renders(self):
        """SPOT mode with zero spot zones still renders a base map."""
        md = _map_data_no_spot()
        state = _FakeState(ActionMode.SPOT)
        png = render_main_view(
            md,
            state=state,
            map_id=0,
            mow_session=MowSession.BETWEEN_SESSIONS,
        )
        assert png[:8] == _PNG_SIGNATURE
