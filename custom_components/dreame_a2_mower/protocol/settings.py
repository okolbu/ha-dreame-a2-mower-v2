"""SETTINGS.* batch decoder + read-modify-write helper.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    [
      {"mode": 0, "settings": {"0": {<19 fields>}, "1": {<19 fields>}}},
      {"mode": 0, "settings": {"0": {...}, "1": {...}}}
    ]

Two top-level entries, both `mode: 0`, each keyed by the same map ids
but holding DIFFERENT values. Roles confirmed 2026-05-09 via a
controlled cloud diff against the user's two-device app setup:

- **Entry 0** = user-saved settings. `version` increments on every save.
  This is what the Dreame app reads, what every cloud writer updates,
  and what the integration must read.
- **Entry 1** = firmware-applied mirror. `version` stays at 0; only the
  device firmware updates this entry (after it actually applies a
  setting). Lags entry 0 by however long the device takes to apply
  the change — sometimes hours, sometimes never.

An earlier hypothesis (commit `db507c9`) had entry 1 marked as
"firmware-authoritative" based on the app appearing to ignore an HA
write that only touched entry 0 — that turned out to be the app's
cached UI not refreshing while the settings screen was open. Once
the app forces a refresh (Save tap, cold start of a second device),
it reads entry 0. Reading entry 1 gives stale "applied" state that
may not match what the user just configured — exactly the symptom
that v1.0.2a2 introduced for AI obstacle bits / walk mode / direction.

Writes still propagate to BOTH entries (defensive — keeps the two in
sync until the firmware-side update of entry 1 arrives). Reads come
from entry 0 only.

Cloud-side propagation note: writes via setDeviceData take ~5 minutes
to be reflected in a follow-up `get_batch_device_datas` read. The
integration's polling cadence should account for that lag.
"""
from __future__ import annotations

import copy
from typing import Any

from ..cloud_state import SettingsRoot


def parse_settings_batch(raw: list[dict[str, Any]]) -> SettingsRoot:
    """Parse a SETTINGS.* JSON-decoded payload into a SettingsRoot.

    Reads entry 0's `settings` dict (string-keyed by map_id) into
    `by_map_id_canonical` — that's the entry the Dreame app reads and
    where every cloud-side writer (app and HA) lands its updates
    (live-confirmed 2026-05-09 on g2408 fw 4.3.6_0550).
    """
    by_map_id_canonical: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list) and raw:
        canonical_entry = raw[0]
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
    g2408 fw 4.3.6_0550). Entry 0 is the canonical user-saved-settings
    entry that apps/HA read; entry 1 is a firmware-applied mirror that
    the device updates on its own schedule. Writing entry 0 is enough
    for any reader to see the new value; we still mutate entry 1 too
    (defensive — avoids stale-mirror reads in the rare cases where
    a downstream tool or test fixture reads it).

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
