"""Conftest for integration tests.

F1.4.2 tests are non-HA (they only exercise the pure apply_property_to_state
function). homeassistant is not installed in this environment yet
(pytest-homeassistant-custom-component is wired in F1.4.3). We inject
minimal stubs so the coordinator module can be imported and the class
definition parsed without errors.
"""
from __future__ import annotations

import sys
import types


def _patch_missing_stubs() -> None:
    """Add any sub-module stubs that weren't present in an earlier call."""
    if "homeassistant.components.logbook" not in sys.modules:
        ha_components = sys.modules.setdefault(
            "homeassistant.components",
            types.ModuleType("homeassistant.components"),
        )
        ha_logbook = types.ModuleType("homeassistant.components.logbook")
        ha_logbook.LOGBOOK_ENTRY_MESSAGE = "message"
        ha_logbook.LOGBOOK_ENTRY_NAME = "name"
        sys.modules["homeassistant.components.logbook"] = ha_logbook
        # Expose as attribute so dotted access works too.
        sys.modules["homeassistant.components"] = ha_components

    # Ensure homeassistant.core has the symbols used by logbook.py.
    ha_core = sys.modules.get("homeassistant.core")
    if ha_core is not None:
        if not hasattr(ha_core, "callback"):
            ha_core.callback = lambda fn: fn  # type: ignore[attr-defined]
        if not hasattr(ha_core, "Event"):
            ha_core.Event = type("Event", (), {})  # type: ignore[attr-defined]
        if not hasattr(ha_core, "HomeAssistant"):
            ha_core.HomeAssistant = type("HomeAssistant", (), {})  # type: ignore[attr-defined]


def _stub_homeassistant() -> None:
    """Insert thin stubs for homeassistant modules used at import-time."""
    if "homeassistant" in sys.modules:
        # Already stubbed — only patch in missing sub-modules so that
        # test files can import them (e.g. logbook.py needs
        # homeassistant.components.logbook but it may not have been wired
        # when the stub was first built).
        _patch_missing_stubs()
        return

    ha = types.ModuleType("homeassistant")
    ha_const = types.ModuleType("homeassistant.const")
    ha_core = types.ModuleType("homeassistant.core")
    ha_ce = types.ModuleType("homeassistant.config_entries")
    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    # Minimal stand-ins used as type annotations / base class

    class HomeAssistant:  # noqa: D101
        pass

    class ConfigEntry:  # noqa: D101
        data: dict = {}
        options: dict = {}

    class DataUpdateCoordinator:  # noqa: D101
        def __init__(self, hass, logger, *, name, update_interval):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval

        def async_set_updated_data(self, data):  # noqa: D102
            self.data = data

        def __class_getitem__(cls, item):  # support DataUpdateCoordinator[T]
            return cls

    # Constants re-exported from const.py via homeassistant.const
    ha_const.CONF_USERNAME = "username"
    ha_const.CONF_PASSWORD = "password"

    class ServiceCall:  # noqa: D101
        def __init__(self, hass, domain, service, data=None):
            self.hass = hass
            self.domain = domain
            self.service = service
            self.data = data or {}

    ha_cv = types.ModuleType("homeassistant.helpers.config_validation")

    def _ensure_list(value):
        """Stub for cv.ensure_list."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    ha_cv.ensure_list = _ensure_list

    class ConfigFlow:  # noqa: D101
        """Stub ConfigFlow that accepts domain= keyword in __init_subclass__."""

        def __init_subclass__(cls, domain=None, **kwargs):  # noqa: D105
            super().__init_subclass__(**kwargs)

        async def async_set_unique_id(self, unique_id):  # noqa: D102
            pass

        def _abort_if_unique_id_configured(self):  # noqa: D102
            pass

        def async_create_entry(self, title="", data=None):  # noqa: D102
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, **kwargs):  # noqa: D102
            return {"type": "form", **kwargs}

    ha_core.HomeAssistant = HomeAssistant
    ha_core.ServiceCall = ServiceCall
    ha_ce.ConfigEntry = ConfigEntry
    ha_ce.ConfigFlow = ConfigFlow

    # F7.7.1: OptionsFlow base class stub
    class OptionsFlow:  # noqa: D101
        config_entry = None

        def async_create_entry(self, title="", data=None):  # noqa: D102
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, **kwargs):  # noqa: D102
            return {"type": "form", **kwargs}

    ha_ce.OptionsFlow = OptionsFlow

    ha_uc.DataUpdateCoordinator = DataUpdateCoordinator

    # homeassistant.data_entry_flow — FlowResult used by config_flow.py
    ha_def = types.ModuleType("homeassistant.data_entry_flow")
    ha_def.FlowResult = dict

    # homeassistant.helpers.entity_registry — used by entity platform tests
    ha_er = types.ModuleType("homeassistant.helpers.entity_registry")

    class _RegistryEntry:  # noqa: D101
        entity_id: str = ""
        unique_id: str = ""
        config_entry_id: str | None = None

    class _EntityRegistry:  # noqa: D101
        entities: dict = {}

        def async_update_entity(self, entity_id, **kwargs):  # noqa: D102
            pass

    ha_er.RegistryEntry = _RegistryEntry  # type: ignore[attr-defined]
    ha_er.EntityRegistry = _EntityRegistry  # type: ignore[attr-defined]
    ha_er.async_get = lambda hass: _EntityRegistry()  # type: ignore[attr-defined]

    # homeassistant.components.logbook — used by logbook.py at import time
    ha_components = types.ModuleType("homeassistant.components")
    ha_logbook = types.ModuleType("homeassistant.components.logbook")
    ha_logbook.LOGBOOK_ENTRY_MESSAGE = "message"
    ha_logbook.LOGBOOK_ENTRY_NAME = "name"

    # homeassistant.core.callback — decorator used by logbook.py
    def callback(fn):  # noqa: D103
        return fn

    ha_core.callback = callback

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_ce
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv
    sys.modules["homeassistant.helpers.entity_registry"] = ha_er
    sys.modules["homeassistant.data_entry_flow"] = ha_def
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.logbook"] = ha_logbook


_stub_homeassistant()


import pytest  # noqa: E402


@pytest.fixture
def coordinator_with_two_maps():
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )

    # spec=DreameA2MowerCoordinator is omitted: the stub DataUpdateCoordinator
    # doesn't declare `hass` as a class attribute, so spec= would prevent
    # setting it and the guard in _sync_map_subdevices would short-circuit.
    coord = MagicMock()
    coord.sn = "G2408053AEE0006232"
    coord.hass = MagicMock()
    coord.entry = MagicMock()
    coord.entry.entry_id = "abc123"
    coord._cloud = MagicMock()
    coord._cloud.serial_number = "G2408053AEE0006232"
    coord._cloud.mac_address = "ef:ce:cc:aa:fe:fd"
    coord._cloud.model = "dreame.mower.g2408"
    m0 = MagicMock()
    m0.map_id = 0
    m0.name = "Front"
    m1 = MagicMock()
    m1.map_id = 1
    m1.name = "Back"
    coord.cloud_state.maps_by_id = {0: m0, 1: m1}
    # Bind the real method so the test exercises actual logic.
    coord._sync_map_subdevices = (
        DreameA2MowerCoordinator._sync_map_subdevices.__get__(coord)
    )
    return coord


def make_empty_cloud_state(**overrides):
    """Build a minimal real CloudState for tests that need dataclasses.replace.

    All fields default to empty; pass overrides (e.g. maps_by_id=...) as needed.
    """
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState,
        ScheduleData,
        SettingsRoot,
    )

    base = dict(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    base.update(overrides)
    return CloudState(**base)
