"""Markdown renderer for the entity-sources audit (Doc 3)."""
from __future__ import annotations

from tools.state_machine_audit_discover import EntityDescriptor, classify_holder
from tools.state_machine_audit_checks import Result


HEADER = """\
# Doc 3 — Entity → Field Dependency Matrix

> **Generated** by `tools/state_machine_audit.py`. Do not hand-edit; rerun the
> audit instead. Spec:
> `docs/superpowers/specs/2026-05-13-state-machine-audit-design.md`.

Sorted alphabetically by `<platform>.<key>` so entities reading the same
field cluster together. Status column collapses the three checks into one
worst-of indicator.

"""


def _worst(results_for_entity: list[Result]) -> str:
    statuses = {r.status for r in results_for_entity}
    if "red" in statuses:
        return "RED"
    if "yellow" in statuses:
        return "YELLOW"
    return "GREEN"


def render_doc3(
    entities: list[EntityDescriptor],
    results: list[Result],
) -> str:
    by_entity: dict[str, list[Result]] = {}
    for r in results:
        by_entity.setdefault(r.entity_key, []).append(r)

    lines: list[str] = [HEADER]
    lines.append("| Entity | Platform | Holder | Status | Sourcing | Idle | Reboot |")
    lines.append("|---|---|---|---|---|---|---|")
    for ed in sorted(entities, key=lambda e: (e.platform, e.key)):
        key = f"{ed.platform}.{ed.key}"
        rs = by_entity.get(key, [])
        worst = _worst(rs)
        holder = classify_holder(ed.value_fn_src)
        by_check = {r.check: r for r in rs}

        def cell(name: str) -> str:
            r = by_check.get(name)
            if r is None:
                return "—"
            return f"{r.status.upper()}: {r.detail or 'ok'}"

        lines.append(
            f"| `{key}` | {ed.platform} | {holder} | {worst} | "
            f"{cell('sourcing')} | {cell('idle')} | {cell('reboot')} |"
        )
    return "\n".join(lines) + "\n"
