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

    ha_core.HomeAssistant = HomeAssistant
    ha_core.ServiceCall = ServiceCall
    ha_ce.ConfigEntry = ConfigEntry
    ha_uc.DataUpdateCoordinator = DataUpdateCoordinator

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_ce
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc
    sys.modules["homeassistant.helpers.config_validation"] = ha_cv


_stub_homeassistant()
