"""Coerce integration-internal dataclasses to plain JSON-safe structures.

HA has two JSON encoders: the generic `homeassistant.helpers.json.JSONEncoder`
used by `mqtt_eventstream` and the richer `ExtendedJSONEncoder` used by the
state REST API. The generic encoder does not know about `@dataclass` values,
so an entity that exposes a dataclass in `extra_state_attributes` breaks the
event-stream broadcaster (2026-04-20 incident — see tests/protocol/
test_entity_jsonable.py for the regression pin).

Keep this helper dependency-free so it can be imported from test modules that
don't have Home Assistant installed.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def jsonable(value: Any) -> Any:
    """Return a JSON-serialisable copy of ``value``.

    Recurses through dicts, lists, and tuples so nested dataclasses are
    converted too. Dataclass instances become plain dicts. Everything else
    passes through unchanged.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
