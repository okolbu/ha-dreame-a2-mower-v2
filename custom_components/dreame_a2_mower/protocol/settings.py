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
    on entry 0's map_id sub-dict. Entry 1 (and any beyond) is preserved
    unchanged. Input is NOT mutated.

    Raises KeyError if map_id is not present in entry 0's settings dict.
    """
    new_raw = copy.deepcopy(raw)
    if not new_raw or not isinstance(new_raw[0], dict):
        raise KeyError(f"SETTINGS entry 0 missing or malformed; cannot set {field}")
    settings_dict = new_raw[0].setdefault("settings", {})
    map_key = str(map_id)
    if map_key not in settings_dict:
        raise KeyError(map_key)
    settings_dict[map_key][field] = value
    return new_raw
