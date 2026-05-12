"""MowerStateMachine — single owner of the multi-dim mower state.

Inputs (MQTT slots, cloud-poll results, heartbeat ticks) in;
StateSnapshot out. Pure-Python; the only HA dependency is the
optional Store used by load_persisted / save_persisted (added later).
"""
from __future__ import annotations

import logging
from typing import Any

from .state_snapshot import StateSnapshot

_LOGGER = logging.getLogger(__name__)


class MowerStateMachine:
    """Multi-dim mower state machine."""

    def __init__(self) -> None:
        self._snapshot: StateSnapshot = StateSnapshot.initial()
        self._dirty: bool = False

    def snapshot(self) -> StateSnapshot:
        """Cheap accessor — returns the current immutable snapshot."""
        return self._snapshot

    def _replace(self, **kwargs: Any) -> StateSnapshot:
        """Replace snapshot fields, marking dirty if changed."""
        import dataclasses
        new = dataclasses.replace(self._snapshot, **kwargs)
        if new != self._snapshot:
            self._snapshot = new
            self._dirty = True
        return new

    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _clear_dirty(self) -> None:
        self._dirty = False

    def handle_mqtt_property(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> StateSnapshot:
        """Apply one MQTT property change. Returns the (possibly new) snapshot.

        Unknown (siid, piid) combinations are logged at DEBUG and the
        snapshot is returned unchanged.
        """
        key = (int(siid), int(piid))

        # Scalar slots — battery, charging, etc.
        if key == (3, 1):
            return self._apply_scalar("battery_percent", int(value), now_unix)
        if key == (3, 2):
            return self._apply_scalar("charging", bool(int(value)), now_unix)

        _LOGGER.debug(
            "MowerStateMachine: unrecognised slot s%dp%d value=%r",
            siid, piid, value,
        )
        return self._snapshot

    def _apply_scalar(
        self, field_name: str, new_value: Any, now_unix: int
    ) -> StateSnapshot:
        """Update a scalar field with freshness stamping.

        No-op on same value (returns current snapshot, does not bump
        the field's freshness timestamp).
        """
        current = getattr(self._snapshot, field_name)
        if current == new_value:
            return self._snapshot
        new_freshness = dict(self._snapshot.field_freshness)
        new_freshness[field_name] = now_unix
        return self._replace(
            **{field_name: new_value},
            field_freshness=new_freshness,
        )
