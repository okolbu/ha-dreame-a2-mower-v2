"""Tests for the F7.7.1 options flow."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, PropertyMock, patch

import voluptuous as vol


def _make_handler(options: dict | None = None):
    """Build a DreameA2MowerOptionsFlow with a stubbed config_entry.

    The base class exposes ``config_entry`` as a read-only property
    (resolved via ``self.handler``); we patch it with a PropertyMock so
    ``_build_schema`` sees a stub entry without booting HA.
    """
    from custom_components.dreame_a2_mower.config_flow import (
        DreameA2MowerOptionsFlow,
    )
    entry = MagicMock()
    entry.options = dict(options or {})
    handler = DreameA2MowerOptionsFlow()
    # Replace the read-only property with a PropertyMock returning the
    # stub entry. This is the same pattern HA core uses for unit-testing
    # subclasses of OptionsFlow.
    patcher = patch.object(
        type(handler), "config_entry", new_callable=PropertyMock,
        return_value=entry,
    )
    patcher.start()
    return handler, entry, patcher


def test_options_flow_can_be_constructed_with_no_args():
    """HA 2026.5+ requires the no-arg constructor: the base class
    provides ``config_entry`` as a property, so passing an entry to the
    subclass (and stashing it) raises AttributeError → 500 on the
    Configure cog endpoint."""
    from custom_components.dreame_a2_mower.config_flow import (
        DreameA2MowerOptionsFlow,
    )
    handler = DreameA2MowerOptionsFlow()  # must not raise
    assert handler is not None


def test_options_flow_schema_includes_lidar_keep_with_bounds():
    from custom_components.dreame_a2_mower.const import (
        CONF_LIDAR_ARCHIVE_KEEP,
    )

    handler, entry, patcher = _make_handler({})
    try:
        schema = handler._build_schema()
    finally:
        patcher.stop()
    keys = {str(k) for k in schema.schema.keys()}
    assert CONF_LIDAR_ARCHIVE_KEEP in keys

    # Validate bounds: 0 should fail, 1 should pass, 50 should pass, 51 should fail.
    for bad in (0, 51):
        with pytest_raises_invalid(schema, {CONF_LIDAR_ARCHIVE_KEEP: bad}):
            pass
    for good in (1, 20, 50):
        out = schema({CONF_LIDAR_ARCHIVE_KEEP: good})
        assert out[CONF_LIDAR_ARCHIVE_KEEP] == good


def test_options_flow_schema_includes_lidar_max_mb_with_bounds():
    from custom_components.dreame_a2_mower.const import (
        CONF_LIDAR_ARCHIVE_MAX_MB,
    )

    handler, entry, patcher = _make_handler({})
    try:
        schema = handler._build_schema()
    finally:
        patcher.stop()
    keys = {str(k) for k in schema.schema.keys()}
    assert CONF_LIDAR_ARCHIVE_MAX_MB in keys

    for bad in (49, 2001):
        with pytest_raises_invalid(schema, {CONF_LIDAR_ARCHIVE_MAX_MB: bad}):
            pass
    for good in (50, 200, 2000):
        out = schema({CONF_LIDAR_ARCHIVE_MAX_MB: good})
        assert out[CONF_LIDAR_ARCHIVE_MAX_MB] == good


def test_options_flow_schema_includes_session_keep_with_bounds():
    from custom_components.dreame_a2_mower.const import (
        CONF_SESSION_ARCHIVE_KEEP,
    )

    handler, entry, patcher = _make_handler({})
    try:
        schema = handler._build_schema()
    finally:
        patcher.stop()
    keys = {str(k) for k in schema.schema.keys()}
    assert CONF_SESSION_ARCHIVE_KEEP in keys

    for bad in (0, 201):
        with pytest_raises_invalid(schema, {CONF_SESSION_ARCHIVE_KEEP: bad}):
            pass
    for good in (1, 50, 200):
        out = schema({CONF_SESSION_ARCHIVE_KEEP: good})
        assert out[CONF_SESSION_ARCHIVE_KEEP] == good


def test_options_flow_uses_existing_options_as_defaults():
    """Re-opening the options flow shows the user's previously-saved
    values, not the integration defaults."""
    from custom_components.dreame_a2_mower.const import (
        CONF_LIDAR_ARCHIVE_KEEP,
        CONF_LIDAR_ARCHIVE_MAX_MB,
    )

    handler, entry, patcher = _make_handler({
        CONF_LIDAR_ARCHIVE_KEEP: 7,
        CONF_LIDAR_ARCHIVE_MAX_MB: 333,
    })
    try:
        schema = handler._build_schema()
    finally:
        patcher.stop()
    # Empty input → defaults populate
    out = schema({})
    assert out[CONF_LIDAR_ARCHIVE_KEEP] == 7
    assert out[CONF_LIDAR_ARCHIVE_MAX_MB] == 333


# ---- helpers ----

def pytest_raises_invalid(schema, payload):
    """Context manager that asserts the schema rejects the payload.
    voluptuous raises Invalid on out-of-range values."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        try:
            schema(payload)
        except vol.Invalid:
            yield
            return
        raise AssertionError(f"schema accepted out-of-range payload {payload!r}")

    return _ctx()
