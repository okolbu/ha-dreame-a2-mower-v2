"""AST-based entity-description discovery.

Walks the platform Python files under custom_components/dreame_a2_mower/
and extracts every *EntityDescription instance — capturing key, name,
platform, and the literal source text of each `value_fn` so the checks
module can both invoke it and classify its holder.

Source-text extraction is preferred over symbolic eval because value_fns
are often lambdas that close over module-scope helpers; AST gives us
faithful source without import-time side effects.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

CCDIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "dreame_a2_mower"
)

PLATFORMS: tuple[str, ...] = (
    "binary_sensor",
    "sensor",
    "switch",
    "select",
    "number",
    "time",
)


@dataclass(frozen=True)
class EntityDescriptor:
    """One discovered entity description."""

    platform: str
    key: str
    name: str | None
    value_fn_src: str
    source_file: str
    line: int


def _kwarg_str(call: ast.Call, name: str) -> str | None:
    """Pull a string-literal kwarg out of a Call node, or None."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            v = kw.value.value
            if isinstance(v, str):
                return v
    return None


def _kwarg_source(call: ast.Call, name: str, source: str) -> str | None:
    """Pull a kwarg's source text out of a Call node, or None."""
    for kw in call.keywords:
        if kw.arg == name:
            return ast.get_source_segment(source, kw.value)
    return None


def discover_entities() -> list[EntityDescriptor]:
    """Discover all EntityDescription instances across platform modules."""
    out: list[EntityDescriptor] = []
    for platform in PLATFORMS:
        path = CCDIR / f"{platform}.py"
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match calls like DreameA2BinarySensorEntityDescription(...) or
            # any *EntityDescription suffix.
            name_id = ""
            if isinstance(func, ast.Name):
                name_id = func.id
            elif isinstance(func, ast.Attribute):
                name_id = func.attr
            if not name_id.endswith("EntityDescription"):
                continue
            key = _kwarg_str(node, "key")
            if not key:
                continue
            name = _kwarg_str(node, "name")
            # Prefer `value_fn` (most platforms) but fall back to
            # `minutes_fn` for the Time platform, which uses a different
            # kwarg name to read an integer-minutes field off the snapshot.
            value_fn_src = (
                _kwarg_source(node, "value_fn", source)
                or _kwarg_source(node, "minutes_fn", source)
                or ""
            )
            # Skip entities without any value reader (e.g. the action_mode
            # SelectEntityDescription, which reads state via a property on
            # the entity class itself rather than a closure). The audit
            # only verifies read paths driven by a kwarg-supplied callable.
            if not value_fn_src:
                continue
            out.append(
                EntityDescriptor(
                    platform=platform,
                    key=key,
                    name=name,
                    value_fn_src=value_fn_src,
                    source_file=str(path.relative_to(CCDIR.parent.parent)),
                    line=node.lineno,
                )
            )
    return out
