"""Diagnostics dump for HA's download_diagnostics button.

Returns a dict with redacted credentials so users can attach the file
to bug reports without leaking secrets. Spec §5.9 redaction keys:
username, password, token, did, mac.

Sections in the dump:
- config_entry         (redacted)
- state                (MowerState as dict)
- capabilities         (Capabilities dataclass as dict)
- novel_observations   (registry snapshot — list of {category, detail, first_seen_unix})
- freshness            (per-field last_updated map)
- endpoint_log         (cloud RPC accept/reject map)
- recent_novel_log_lines (tail of NOVEL log warnings, capped at 200)
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .mower.capabilities import Capabilities


REDACTION_KEYS: tuple[str, ...] = ("username", "password", "token", "did", "mac")


def redact(payload: Any) -> Any:
    """Return a deep copy of ``payload`` with values for any
    ``REDACTION_KEYS`` replaced by ``"**REDACTED**"``. Scalars and
    unknown types pass through unchanged."""
    if isinstance(payload, dict):
        return {
            k: ("**REDACTED**" if k in REDACTION_KEYS else redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def _as_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    snap = coordinator.novel_registry.snapshot()
    cloud = getattr(coordinator, "_cloud", None)
    endpoint_log = dict(getattr(cloud, "endpoint_log", {})) if cloud is not None else {}
    return {
        "config_entry": redact(dict(entry.data)),
        "state": _as_dict(coordinator.data),
        "capabilities": asdict(Capabilities()),
        "novel_observations": [
            {
                "category": o.category,
                "detail": o.detail,
                "first_seen_unix": o.first_seen_unix,
            }
            for o in snap.observations
        ],
        "freshness": coordinator.freshness.snapshot(),
        "endpoint_log": endpoint_log,
        "recent_novel_log_lines": coordinator.novel_log.lines(),
    }
