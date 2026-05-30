"""Canonical s2p50 TASK-op / OSS-summary `mode` enum — single source of truth.

The g2408 TASK op code (s2p50 ``o``) and the OSS session-summary ``mode`` field
share one enum: 100=all_areas, 101=edge, 102=zone, 103=spot, 108=patrol. Verified
across 10 OSS dumps (100-103) + the live 2026-05-30 patrol archive (108);
inventory.yaml § summary_mode.

This module exists so the mapping lives in ONE place. The same fact used to be
duplicated in three spots that drifted out of sync (102 was once mislabelled
"All areas"):
  - ``session_summary._MOW_TYPE_BY_MODE``  → machine slugs
  - ``session_card.MODE_LABELS``           → human display labels
  - ``state_machine`` op→activity map      → which ops are mow variants

Op codes that are NOT session modes (109=cruise, 10=fast-mapping, 15=manual) are
deliberately absent — they have no OSS ``mode`` value and no session-card label, so
they stay with their individual consumers (the state machine / classifier).

Pure module — no internal imports — so every consumer (protocol, session_card,
the state machine) can import it without coupling or cycle risk.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeInfo:
    """One row of the mode enum."""

    slug: str
    """Machine slug, e.g. ``"all_areas"`` (matches ``mower.state.ActionMode``
    values for the mow variants)."""

    label: str
    """Human display label, e.g. ``"All areas"`` — shown on the session card."""

    is_mow: bool
    """True for the blades-down mow variants (100-103); False for patrol (108),
    a blades-up cruise that produces a cloud summary but mows nothing."""


MODE_BY_CODE: dict[int, ModeInfo] = {
    100: ModeInfo("all_areas", "All areas", True),
    101: ModeInfo("edge", "Edge", True),
    102: ModeInfo("zone", "Zone", True),
    103: ModeInfo("spot", "Spot", True),
    108: ModeInfo("patrol", "Patrol", False),
}

# Blades-down mow-variant codes (excludes patrol 108). The state machine uses
# this to decide whether a TASK op opens a mow_session.
MOW_MODE_CODES: frozenset[int] = frozenset(
    code for code, info in MODE_BY_CODE.items() if info.is_mow
)


def mode_slug(code: int) -> str | None:
    """Machine slug for a mode/op code, or None for an unknown code."""
    info = MODE_BY_CODE.get(code)
    return info.slug if info else None


def mode_label(code: int) -> str | None:
    """Human display label for a mode/op code, or None for an unknown code."""
    info = MODE_BY_CODE.get(code)
    return info.label if info else None
