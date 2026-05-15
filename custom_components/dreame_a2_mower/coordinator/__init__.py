"""Coordinator package — assembled DreameA2MowerCoordinator + helpers.

Decomposed from a single-file 4997-LOC ``coordinator.py`` 2026-05-15.
See spec ``docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md``
and plan ``docs/superpowers/plans/2026-05-15-coordinator-decomposition.md``.

External callers continue to use ``from .coordinator import …``; the
package re-exports the same public surface as the old module.

During the migration (tasks 2-11) the assembled class lives in the
transitional ``_coordinator_legacy.py`` sibling module and inherits
from the mixin classes as they're extracted. Task 12 moves the final
class assembly here and deletes ``_coordinator_legacy.py``.
"""
from __future__ import annotations

# Public re-exports from the property-apply submodule (consumed by
# ``number.py``, ``tests/state_machine/test_position_projection.py``,
# ``tests/integration/test_probe_type_check.py``).
from ._property_apply import (
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_NOTIFICATION_MAP,
    _project_north_east,
    apply_property_to_state,
)

# Transitional shim — load the legacy class definition. Task 12
# replaces this with the final class assembly.
from .._coordinator_legacy import DreameA2MowerCoordinator

__all__ = [
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "S2P2_NOTIFICATION_MAP",
    "_project_north_east",
]
