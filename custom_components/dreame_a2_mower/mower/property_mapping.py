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
                   doesn't apply. Return None to drop the push.

    extract_value: optional callable that transforms the wire payload
                   into the value to assign to the field. Used when the
                   wire shape is a list/dict and only part of it should
                   land on the dataclass. Defaults to identity (the
                   raw value is assigned).

    multi_field: optional list of (field_name, extract_fn) tuples for
                 wire payloads that update multiple MowerState fields
                 from one push (e.g., s6.3 carries both cloud_connected
                 and wifi_rssi_dbm). When set, field_name and
                 disambiguator are ignored — the coordinator iterates
                 multi_field and applies each.
    """

    field_name: str | None = None
    disambiguator: Callable[[Any], str | None] | None = None
    extract_value: Callable[[Any], Any] | None = None
    multi_field: tuple[tuple[str, Callable[[Any], Any]], ...] | None = None


# F1-minimal table. F2..F7 add entries.
# Each entry's primary citation is in docs/research/g2408-protocol.md §2.1.
PROPERTY_MAPPING: dict[tuple[int, int], PropertyMappingEntry] = {
    (2, 1): PropertyMappingEntry(field_name="state"),                 # s2.1 STATUS
    (3, 1): PropertyMappingEntry(field_name="battery_level"),         # s3.1 BATTERY_LEVEL
    (3, 2): PropertyMappingEntry(field_name="charging_status"),       # s3.2 CHARGING_STATUS

    # F2 additions:
    (1, 53): PropertyMappingEntry(field_name="obstacle_flag"),       # bool
    (2, 2): PropertyMappingEntry(field_name="error_code"),           # int
    # s2.56 SESSION-STATUS — wire shape is a dict envelope, not a bare int:
    #   {"status": []}             → no active task
    #   {"status": [[1, 0]]}        → task running
    #   {"status": [[1, 4]]}        → task paused-pending-resume
    #   {"status": [[1, 2]]}        → other sub-state (firmware-specific)
    #   {"status": [[1, 0, 0]]}     → 3-element variant (newer firmware)
    # Legacy device.py:1277-1315 reads status[0][1] (the SUB-state) as
    # the running/pending discriminator: 0 = running, 4 = paused.
    # Greenfield's F5 session-state machine treats task_state_code as a
    # single int and uses it for begin_session / begin_leg / session-end
    # transitions. The sub-state is the right value to expose because:
    #   - 0 (running) ↔ "actively mowing"
    #   - 4 (paused-pending-resume) ↔ "recharging / paused"
    #   - 0 → 4 → 0 = recharge round-trip; 4 → 0 triggers begin_leg.
    #   - empty status (None) = no task active = session-end.
    # (v1.0.0a18 fix: was previously stored as the raw dict, which made
    # task_state_code != int 1 always so begin_session never fired.)
    (2, 56): PropertyMappingEntry(
        field_name="task_state_code",
        extract_value=lambda v: (
            int(v["status"][0][1])
            if isinstance(v, dict)
            and isinstance(v.get("status"), list)
            and v["status"]
            and isinstance(v["status"][0], list)
            and len(v["status"][0]) >= 2
            else None
        ),
    ),
    (2, 65): PropertyMappingEntry(field_name="slam_task_label"),     # string

    # s2.66 is [area_m², ?]; we only consume [0] in F2.
    (2, 66): PropertyMappingEntry(
        field_name="total_lawn_area_m2",
        disambiguator=lambda v: "total_lawn_area_m2" if isinstance(v, list) and v else None,
        extract_value=lambda v: float(v[0]) if isinstance(v, list) and v else None,
    ),

    # s6.2 g2408 = [mowing_height_mm, mow_mode, edgemaster, ?]
    # Element [3] is observed-constant=2, not yet characterized.
    (6, 2): PropertyMappingEntry(
        multi_field=(
            ("pre_mowing_height_mm", lambda v: int(v[0]) if isinstance(v, list) and len(v) >= 1 else None),
            ("pre_mowing_efficiency", lambda v: int(v[1]) if isinstance(v, list) and len(v) >= 2 else None),
            ("pre_edgemaster", lambda v: bool(v[2]) if isinstance(v, list) and len(v) >= 3 else None),
        ),
    ),

    # s6.3 g2408 = [cloud_connected: bool, rssi_dbm: int]
    (6, 3): PropertyMappingEntry(
        disambiguator=lambda v: "cloud_connected" if isinstance(v, list) and v else None,
        multi_field=(
            ("cloud_connected", lambda v: bool(v[0]) if isinstance(v, list) and len(v) >= 1 else None),
            ("wifi_rssi_dbm", lambda v: int(v[1]) if isinstance(v, list) and len(v) >= 2 else None),
        ),
    ),

    # F7: LiDAR-scan upload announcement.
    # The mower writes a string OSS object_name to slot s99.20 each
    # time the user taps "Download LiDAR map" in the app. The
    # coordinator's _handle_lidar_object_name fetches the binary blob
    # via the cloud client and writes it to LidarArchive.
    (99, 20): PropertyMappingEntry(field_name="latest_lidar_object_name"),

    # v1.0.0a11: raw diagnostic slots — semantics not yet decoded.
    # Mapping them here makes them "known" so the [NOVEL/property] log
    # only fires once per process per slot via the value-novelty path.
    # Surfaced as diagnostic sensors per spec §5.6 for protocol-RE work.
    (5, 104): PropertyMappingEntry(
        field_name="s5p104_raw",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
    (5, 105): PropertyMappingEntry(
        field_name="s5p105_raw",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
    (5, 106): PropertyMappingEntry(
        field_name="s5p106_raw",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
    (5, 107): PropertyMappingEntry(
        field_name="s5p107_raw",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
    (6, 1): PropertyMappingEntry(
        field_name="s6p1_raw",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
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
