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
    # F6 review fix #2: defense-in-depth — wrap state and endpoint_log in
    # redact() so future field additions can't silently leak credentials.
    # Freshness keys are field names (safe); log lines are plain strings (safe).
    # Falls back to the static Capabilities dataclass today; F7 may attach a
    # runtime-resolved capabilities object to the coordinator.
    _caps_attr = getattr(coordinator, "capabilities", None)
    caps = _caps_attr if is_dataclass(_caps_attr) else Capabilities()
    # v1.0.0a8: cloud + MQTT runtime state, redacted. Lets us debug
    # MQTT connection issues without needing access to HA's container log.
    cloud_state: dict[str, Any] = {}
    if cloud is not None:
        cloud_state = {
            "logged_in": getattr(cloud, "_logged_in", None),
            "connected": getattr(cloud, "_connected", None),
            "did": getattr(cloud, "_did", None),
            "uid": getattr(cloud, "_uid", None),       # masterUid from device-info
            "uuid": getattr(cloud, "_uuid", None),     # login uid from /oauth/token
            "model": getattr(cloud, "_model", None),
            "host": getattr(cloud, "_host", None),
            "country": getattr(cloud, "_country", None),
            "last_send_error_code": getattr(cloud, "_last_send_error_code", None),
        }
    mqtt = getattr(coordinator, "_mqtt", None)
    mqtt_state: dict[str, Any] = {}
    if mqtt is not None:
        mqtt_state = {
            "connected": getattr(mqtt, "_connected", None),
            "connecting": getattr(mqtt, "_connecting", None),
            "subscribe_topic": getattr(mqtt, "_subscribe_topic", None),
            "callback_registered": getattr(mqtt, "_callback", None) is not None,
            "client_present": getattr(mqtt, "_client", None) is not None,
            "username_set": getattr(mqtt, "_username", None) is not None,
            "first_topics": list(getattr(mqtt, "_first_topics", []) or []),
            "suback_results": list(getattr(mqtt, "_suback_results", []) or []),
        }
    return {
        "config_entry": redact(dict(entry.data)),
        "state": redact(_as_dict(coordinator.data)),
        "capabilities": asdict(caps),
        "cloud_state": redact(cloud_state),
        "mqtt_state": redact(mqtt_state),
        "novel_observations": redact([
            {
                "category": o.category,
                "detail": o.detail,
                "first_seen_unix": o.first_seen_unix,
            }
            for o in snap.observations
        ]),
        "freshness": coordinator.freshness.snapshot(),
        "endpoint_log": redact(endpoint_log),
        "recent_novel_log_lines": coordinator.novel_log.lines(),
    }
