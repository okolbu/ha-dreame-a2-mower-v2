"""Audit-tool checks: sourcing / idle / reboot / orphan-field.

Each check produces a Result with status ∈ {"green", "yellow", "red"}.
Results are aggregated by the main entry point into a console table +
a generated Doc 3 matrix.
"""
from __future__ import annotations

import dataclasses
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Expectation:
    """Hand-edited expectation for one entity."""

    holder: str
    idle: Any  # literal value | "persisted_value" | "unavailable"
    reboot: str  # "required" | "unavailable_ok"
    note: str = ""


def load_expectations(path: Path) -> dict[str, Expectation]:
    """Load the expectations YAML into a dict keyed by `<platform>.<key>`."""
    if not path.exists():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text()) or {}
    out: dict[str, Expectation] = {}
    for entity_key, body in raw.items():
        if not isinstance(body, dict):
            continue
        out[entity_key] = Expectation(
            holder=body.get("holder", "other"),
            idle=body.get("idle"),
            reboot=body.get("reboot", "required"),
            note=body.get("note", ""),
        )
    return out


# StateSnapshot field set — derived dynamically so the audit stays in sync
# with the dataclass.
def _compute_snapshot_fields() -> frozenset[str]:
    # Reuse the test harness's HA stubs if not already in place.
    if "homeassistant" not in sys.modules:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
        import conftest  # noqa: F401

    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    return frozenset(f.name for f in dataclasses.fields(StateSnapshot))


SNAPSHOT_FIELDS: frozenset[str] = _compute_snapshot_fields()


@dataclass(frozen=True)
class Result:
    """One check's outcome for one entity."""

    entity_key: str  # e.g. "sensor.battery_level"
    check: str  # "sourcing" | "idle" | "reboot" | "orphan_field"
    status: str  # "green" | "yellow" | "red"
    detail: str


_MOWER_STATE_ATTR_RE = re.compile(r"\bs\.([a-zA-Z_][a-zA-Z0-9_]*)|\.data\.([a-zA-Z_][a-zA-Z0-9_]*)")


def _fields_read_from_mower_state(src: str) -> set[str]:
    """Return MowerState field names referenced by a value_fn source."""
    out: set[str] = set()
    for m in _MOWER_STATE_ATTR_RE.finditer(src):
        name = m.group(1) or m.group(2)
        if name:
            out.add(name)
    return out


def check_sourcing(ed: "EntityDescriptor") -> Result:
    """Snapshot-owned fields must be read from the snapshot, not MowerState.

    GREEN: no MowerState reads of snapshot-owned fields.
    RED:   any MowerState read of a snapshot-owned field.
    """
    from tools.state_machine_audit_discover import EntityDescriptor  # noqa: F401

    bad = _fields_read_from_mower_state(ed.value_fn_src) & SNAPSHOT_FIELDS
    if bad:
        return Result(
            entity_key=f"{ed.platform}.{ed.key}",
            check="sourcing",
            status="red",
            detail=f"reads snapshot-owned field(s) from MowerState: {sorted(bad)}",
        )
    return Result(
        entity_key=f"{ed.platform}.{ed.key}",
        check="sourcing",
        status="green",
        detail="",
    )


def check_idle(ed: "EntityDescriptor", exp: Expectation) -> Result:
    """Invoke the value_fn at cold-start; compare to expected idle value.

    GREEN:
      - exp.idle is a literal and the observed value equals it.
      - exp.idle == "persisted_value" and the observed value is not None.
      - exp.idle == "unavailable" and the value_fn raised or returned None.

    RED otherwise.

    YELLOW only when the value_fn cannot be invoked at all due to a
    missing fake-coord attribute — i.e. the audit harness needs a small
    extension; not a true failure of the entity.
    """
    from tools.state_machine_audit_fake_coord import observe_cold_value

    arg_kind = (
        "data" if ed.value_fn_src.lstrip().startswith("lambda s:")
        else "coord"
    )
    val, exc = observe_cold_value(ed.value_fn_src, arg_kind=arg_kind)
    key = f"{ed.platform}.{ed.key}"
    if exc is not None and not isinstance(exc, (AttributeError, KeyError)):
        return Result(
            entity_key=key,
            check="idle",
            status="yellow",
            detail=f"value_fn raised: {type(exc).__name__}: {exc}",
        )
    if exp.idle == "unavailable":
        if val is None or exc is not None:
            return Result(entity_key=key, check="idle", status="green", detail="")
        return Result(
            entity_key=key, check="idle", status="red",
            detail=f"expected unavailable, got {val!r}",
        )
    if exp.idle == "persisted_value":
        if val is not None:
            return Result(entity_key=key, check="idle", status="green", detail="")
        return Result(
            entity_key=key, check="idle", status="red",
            detail=f"expected persisted value, got None at cold-start",
        )
    # Literal expected value
    if val == exp.idle:
        return Result(entity_key=key, check="idle", status="green", detail="")
    return Result(
        entity_key=key, check="idle", status="red",
        detail=f"expected {exp.idle!r}, got {val!r}",
    )
