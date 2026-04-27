"""(siid, piid) → field_name mapping table for g2408.

Per spec §3 cross-cutting commitment: this is the single source of
truth for property mapping. No overlay/merge gymnastics.

The mapping supports **named disambiguators** for multi-purpose
(siid, piid) pairs. At least one such pair is documented on g2408
(the robot-voice / notification-type slot — exact siid/piid TBD as
the rebuild progresses). When an entry has a disambiguator callable,
it is invoked with the inbound payload value and returns the
alternate field name when the primary mapping isn't right.

Subsequent phases (F2..F7) extend this table as MowerState gains
fields. Each new entry MUST cite its protocol-doc §2.1 source.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PropertyMappingEntry:
    """One row of the property mapping table.

    field_name: the primary MowerState field this (siid, piid) feeds.
    disambiguator: optional callable that inspects the payload value
                   and returns an alternate field name when the primary
                   doesn't apply. Returns the primary field_name when
                   the primary applies. Returns None to indicate
                   "drop this push".
    """

    field_name: str
    disambiguator: Callable[[Any], str | None] | None = None


# F1-minimal table. F2..F7 add entries.
# Each entry's primary citation is in docs/research/g2408-protocol.md §2.1.
PROPERTY_MAPPING: dict[tuple[int, int], PropertyMappingEntry] = {
    (2, 1): PropertyMappingEntry(field_name="state"),                 # s2.1 STATUS
    (3, 1): PropertyMappingEntry(field_name="battery_level"),         # s3.1 BATTERY_LEVEL
    (3, 2): PropertyMappingEntry(field_name="charging_status"),       # s3.2 CHARGING_STATUS
}


def resolve_field(siid_piid: tuple[int, int], value: Any) -> str | None:
    """Resolve a (siid, piid) push to its target MowerState field name.

    Returns None if the pair is unknown — the caller is responsible
    for emitting a [NOVEL/property] warning in that case.

    If the entry has a disambiguator, it is invoked with the value and
    its return decides the field. Otherwise the primary field_name is
    returned unconditionally.
    """
    entry = PROPERTY_MAPPING.get(siid_piid)
    if entry is None:
        return None
    if entry.disambiguator is None:
        return entry.field_name
    return entry.disambiguator(value)
