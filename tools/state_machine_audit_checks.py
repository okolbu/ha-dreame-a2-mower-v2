"""Audit-tool checks: sourcing / idle / reboot / orphan-field.

Each check produces a Result with status ∈ {"green", "yellow", "red"}.
Results are aggregated by the main entry point into a console table +
a generated Doc 3 matrix.
"""
from __future__ import annotations

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
