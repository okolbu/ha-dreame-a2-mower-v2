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


def _stub_homeassistant() -> None:
    """Insert thin stubs for homeassistant modules used at import-time."""
    if "homeassistant" in sys.modules:
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

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_ce
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv
    sys.modules["homeassistant.data_entry_flow"] = ha_def


_stub_homeassistant()
