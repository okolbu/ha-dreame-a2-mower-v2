"""SETTINGS.* batch decoder + read-modify-write helper.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    [
      {"mode": 0, "settings": {"0": {<19 fields>}, "1": {<19 fields>}}},
      {"mode": 0, "settings": {"0": {...}, "1": {...}}}
    ]

Two top-level entries, both `mode: 0`, each keyed by the same map_ids
but NOT necessarily holding the same values. Live evidence 2026-05-09:
the firmware/app is authoritative on the LAST entry — when the user
edits a setting in the Dreame app, only the last entry updates and
entry 0 drifts stale. We therefore read the last entry as canonical
and write to ALL entries, so cloud, app, and integration stay in sync
regardless of which side initiated the change.
"""
from __future__ import annotations

import copy
from typing import Any

from ..cloud_state import SettingsRoot


def parse_settings_batch(raw: list[dict[str, Any]]) -> SettingsRoot:
    """Parse a SETTINGS.* JSON-decoded payload into a SettingsRoot.

    Reads the LAST entry's `settings` dict (string-keyed by map_id) into
    `by_map_id_canonical` — that's the entry the firmware/app reads and
    writes (live-confirmed 2026-05-09 on g2408 fw 4.3.6_0550).
    """
    by_map_id_canonical: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list) and raw:
        canonical_entry = raw[-1]
        if isinstance(canonical_entry, dict):
            settings_dict = canonical_entry.get("settings")
            if isinstance(settings_dict, dict):
                for k, v in settings_dict.items():
                    try:
                        map_id = int(k)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(v, dict):
                        by_map_id_canonical[map_id] = v
    return SettingsRoot(
        raw=raw if isinstance(raw, list) else [],
        by_map_id_canonical=by_map_id_canonical,
    )


def write_setting(
    raw: list[dict[str, Any]],
    *,
    map_id: int,
    field: str,
    value: Any,
) -> list[dict[str, Any]]:
    """Read-modify-write: produce a new SETTINGS list with `field` set
    on EVERY entry's map_id sub-dict. Input is NOT mutated.

    Cloud SETTINGS has a dual-level structure (verified 2026-05-09 on
    g2408 fw 4.3.6_0550). Writing only one entry leaves the other one
    stale — the firmware/app reads from the last entry, while the
    integration historically read from entry 0. Writing to ALL entries
    keeps both sides consistent.

    Raises KeyError if map_id is not present in any entry.
    """
    new_raw = copy.deepcopy(raw)
    if not new_raw:
        raise KeyError(f"SETTINGS list empty; cannot set {field}")
    map_key = str(map_id)
    # Validate map_id exists in at least one entry.
    found = False
    for entry in new_raw:
        if isinstance(entry, dict):
            sd = entry.get("settings")
            if isinstance(sd, dict) and map_key in sd:
                found = True
                break
    if not found:
        raise KeyError(map_key)
    # Mutate the field in every entry that has this map_id. Entries that
    # don't carry the map_id (unlikely but defensive) are left alone.
    for entry in new_raw:
        if not isinstance(entry, dict):
            continue
        sd = entry.get("settings")
        if not isinstance(sd, dict):
            continue
        if map_key in sd and isinstance(sd[map_key], dict):
            sd[map_key][field] = value
    return new_raw
