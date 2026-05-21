"""map_render package — re-export shim.

All public names are defined in the sub-modules; this file re-exports
only the names that real callers import (``from ..map_render import
render_base_map``, etc.) so those imports keep working unchanged.
"""

from __future__ import annotations

from ._geometry import (
    _DEFAULT_PALETTE,
    _OBSTACLE_FILL,
    _OBSTACLE_OUTLINE,
    _cloud_to_px,
    _renderer_to_px,
    extract_projection,
)
from .base_map import render_base_map
from .main_view import render_main_view
from .trail import render_with_trail
from .work_log import render_work_log

__all__ = [
    "_DEFAULT_PALETTE",
    "_OBSTACLE_FILL",
    "_OBSTACLE_OUTLINE",
    "_cloud_to_px",
    "_renderer_to_px",
    "extract_projection",
    "render_base_map",
    "render_main_view",
    "render_with_trail",
    "render_work_log",
]
