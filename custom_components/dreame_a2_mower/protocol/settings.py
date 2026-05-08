"""SETTINGS.* batch decoder + read-modify-write helper.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    [
      {"mode": 0, "settings": {"0": {<19 fields>}, "1": {<19 fields>}}},
      {"mode": 0, "settings": {"0": {...}, "1": {...}}}
    ]

Two top-level entries, both `mode: 0`, with the same map_id keys
inside. The semantic of the dual-level structure is UNKNOWN —
might be (a) per-mode profiles, (b) "current" + "default", or
(c) something else. We treat entry 0 as canonical for reads and
preserve entry 1 unchanged on writes.
"""
from __future__ import annotations

import copy
from typing import Any

from ..cloud_state import SettingsRoot


def parse_settings_batch(raw: list[dict[str, Any]]) -> SettingsRoot:
    """Parse a SETTINGS.* JSON-decoded payload into a SettingsRoot.

    Reads entry 0's `settings` dict (string-keyed by map_id) into
    `by_map_id_canonical` for fast active-follower entity reads.
    """
    by_map_id_canonical: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list) and raw:
        entry0 = raw[0]
        if isinstance(entry0, dict):
            settings_dict = entry0.get("settings")
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
    g2408 fw 4.3.6_0550): two top-level entries, both `mode: 0`, both
    carrying the same map_id sub-dicts. Writing to entry 0 only made
    the cloud accept the write (returned code=0) but the firmware/app
    kept reading from entry 1 — the toggle never appeared in the app.
    Mutating BOTH entries propagates correctly.

    Raises KeyError if map_id is not present in entry 0's settings dict.
    """
    new_raw = copy.deepcopy(raw)
    if not new_raw or not isinstance(new_raw[0], dict):
        raise KeyError(f"SETTINGS entry 0 missing or malformed; cannot set {field}")
    map_key = str(map_id)
    # Validate map_id exists in entry 0 (canonical entry).
    settings0 = new_raw[0].setdefault("settings", {})
    if map_key not in settings0:
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
