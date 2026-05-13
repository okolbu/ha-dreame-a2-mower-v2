"""Minimal fake coordinator for invoking entity value_fns at cold-start.

The real coordinator pulls in HA, config entries, MQTT, cloud HTTP, etc.
None of that matters for cold-start observation. We need:

  - .state_machine.snapshot()  — MowerStateMachine in initial state
  - .data                      — MowerState() defaults
  - .cloud_state               — CloudState() defaults

Plus a permissive __getattr__ so value_fns that reach for less-common
attributes don't crash discovery; they get a None instead.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Make sure the integration package is importable. tests/conftest.py
# stubs HA; reuse the same pattern when this module is imported outside
# of pytest.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_ha_stubs() -> None:
    """Import HA stubs if running outside pytest (where conftest.py runs)."""
    if "homeassistant" in sys.modules:
        return
    # Defer to the same shim the test suite uses.
    sys.path.insert(0, str(ROOT / "tests"))
    import conftest  # noqa: F401 — side effect: stubs ha


class _PermissiveCoord:
    """Coord-shaped object that returns None for unknown attrs."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def __getattr__(self, item: str) -> Any:
        return None


def _empty_cloud_state() -> Any:
    """Build a CloudState with all-empty/None initial fields.

    CloudState is a frozen dataclass with 15 required fields and no
    factory method; this mirrors the canonical empty form used in
    tests/test_cloud_state_dataclasses.py.
    """
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState,
        ScheduleData,
        SettingsRoot,
    )

    return CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        locn=None,
        dock={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )


def build_fake_coord() -> _PermissiveCoord:
    """Construct a coordinator with all state holders in their initial state."""
    _ensure_ha_stubs()
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state import MowerState

    return _PermissiveCoord(
        state_machine=MowerStateMachine(),
        data=MowerState(),
        cloud_state=_empty_cloud_state(),
        # Sometimes touched by value_fns:
        live_map=SimpleNamespace(is_active=lambda: False, legs=[]),
    )
