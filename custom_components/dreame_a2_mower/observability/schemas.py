"""Schema fingerprints for known JSON blobs.

Each schema is a nested dict where leaf-True means "we know about this
key". Lists of dicts use a single ``"[]"`` sub-key to describe the
expected element shape. ``SchemaCheck.diff_keys`` returns the dotted
paths of keys present in the payload but absent from the schema —
exactly the surface the registry's ``record_key`` method consumes.

NO ``homeassistant.*`` imports — layer-2 invariant.

Adding a new fingerprint
------------------------
Schemas live as module-level constants. To extend, add another constant
plus its tests; the wire-in logic in the coordinator references the
constant by name. Do not pull schemas from disk — drift in a
configuration file would be a worse failure mode than drift in the
code.
"""

from __future__ import annotations

from typing import Any


SCHEMA_SESSION_SUMMARY: dict[str, Any] = {
    "area": True,
    "duration": True,
    "started_at": True,
    "ended_at": True,
    "map": {
        "[]": {
            "track": True,
            "obstacles": True,
            "boundary": True,
        },
    },
    "battery_used_pct": True,
    "blade_runtime_min": True,
    "session_id": True,
}
"""Known top-level keys in the OSS session-summary JSON. Update as the
parser learns new fields. Keys present in the payload but not here
trigger a [NOVEL_KEY/session_summary] WARNING."""


SCHEMA_CFG: dict[str, Any] = {
    "CFG": True,
    "CMS": True,
    "CLS": True,
    "CMG": True,
    "RPM": True,
    "schedule": True,
}
"""Top-level keys in the s2.51 CFG blob."""


class SchemaCheck:
    """Compute the set of unexpected keys in a JSON payload."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def diff_keys(self, payload: Any) -> list[str]:
        """Return dotted paths of keys present in payload but absent from schema.

        Returns a sorted list. Non-dict payloads return ``[]`` (we can
        only diff dicts).
        """
        if not isinstance(payload, dict):
            return []
        return sorted(self._diff(payload, self._schema, prefix=""))

    def _diff(
        self,
        payload: Any,
        schema: dict[str, Any] | bool,
        prefix: str,
    ) -> list[str]:
        # Schema is a leaf marker (True). Anything below this level is
        # opaque to the validator; report nothing.
        if schema is True:
            return []
        if not isinstance(payload, dict):
            return []
        unknown: list[str] = []
        for key, value in payload.items():
            if key not in schema:
                unknown.append(f"{prefix}{key}" if prefix else key)
                continue
            sub = schema[key]
            if isinstance(value, list) and isinstance(sub, dict) and "[]" in sub:
                element_schema = sub["[]"]
                for item in value:
                    unknown.extend(self._diff(item, element_schema, f"{prefix}{key}[]."))
            elif isinstance(sub, dict):
                unknown.extend(self._diff(value, sub, f"{prefix}{key}."))
        return unknown
