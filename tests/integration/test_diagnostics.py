"""Tests for the download_diagnostics handler."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.diagnostics import (
    REDACTION_KEYS,
    async_get_config_entry_diagnostics,
    redact,
)


def test_redact_replaces_listed_keys():
    payload = {"username": "alice", "password": "p@ss", "did": "x123", "other": "ok"}
    out = redact(payload)
    assert out["username"] == "**REDACTED**"
    assert out["password"] == "**REDACTED**"
    assert out["did"] == "**REDACTED**"
    assert out["other"] == "ok"


def test_redact_handles_nested_dicts():
    payload = {"creds": {"password": "x", "country": "NO"}}
    out = redact(payload)
    assert out["creds"]["password"] == "**REDACTED**"
    assert out["creds"]["country"] == "NO"


def test_redact_handles_lists_of_dicts():
    payload = {"items": [{"token": "abc", "name": "a"}, {"token": "def", "name": "b"}]}
    out = redact(payload)
    assert out["items"][0]["token"] == "**REDACTED**"
    assert out["items"][0]["name"] == "a"
    assert out["items"][1]["token"] == "**REDACTED**"


def test_redact_passes_through_scalars():
    assert redact("hello") == "hello"
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(3.14) == 3.14


def test_redaction_keys_match_spec_section_5_9():
    """Spec §5.9 list: username, password, token, did, mac."""
    expected = {"username", "password", "token", "did", "mac"}
    assert expected.issubset(set(REDACTION_KEYS))


def test_diagnostics_dump_top_level_sections():
    """Smoke test: the dump has every required top-level section and
    config_entry credentials are redacted. Uses asyncio.run() to avoid
    needing pytest-asyncio (matches project pattern in test_coordinator.py)."""
    from custom_components.dreame_a2_mower.const import DOMAIN
    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker,
        NovelLogBuffer,
        NovelObservationRegistry,
    )
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coordinator = MagicMock()
    coordinator.data = MowerState(battery_level=42)
    coordinator.freshness = FreshnessTracker()
    coordinator.novel_registry = NovelObservationRegistry()
    coordinator.novel_log = NovelLogBuffer(
        maxlen=10, prefixes=("[NOVEL/property]",)
    )
    cloud = MagicMock()
    cloud.endpoint_log = {"routed_action_op=100": "accepted"}
    coordinator._cloud = cloud

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "abc123"
    entry.data = {
        "username": "alice",
        "password": "secret",
        "token": "tok",
        "did": "did1",
        "mac": "aa:bb",
        "host": "1.2.3.4",
    }
    hass.data = {DOMAIN: {"abc123": coordinator}}

    out = asyncio.run(async_get_config_entry_diagnostics(hass, entry))
    assert "config_entry" in out
    assert out["config_entry"]["password"] == "**REDACTED**"
    assert out["config_entry"]["username"] == "**REDACTED**"
    assert out["config_entry"]["token"] == "**REDACTED**"
    assert out["config_entry"]["did"] == "**REDACTED**"
    assert out["config_entry"]["mac"] == "**REDACTED**"
    assert out["config_entry"]["host"] == "1.2.3.4"  # not in REDACTION_KEYS

    assert "state" in out
    assert out["state"]["battery_level"] == 42

    assert "capabilities" in out
    assert out["capabilities"]["lidar_navigation"] is True

    assert out["novel_observations"] == []
    assert out["freshness"] == {}
    assert out["endpoint_log"] == {"routed_action_op=100": "accepted"}
    assert out["recent_novel_log_lines"] == []
