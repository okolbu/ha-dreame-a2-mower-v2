"""Pytest configuration shared by protocol/ + mower/ + integration/ tests.

Per spec §3, the protocol/ + mower/ test suites must run in a vanilla
pytest venv (no Home Assistant required). The integration/ test suite
adds pytest-homeassistant-custom-component fixtures separately.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Make the top-level protocol/ package importable in tests
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub the ``homeassistant`` package so that the custom_components package
# __init__.py can be imported without a full HA install.  Only the names
# that the integration's layer-3 glue code references at import time are
# needed here; the integration/ tests that need real HA fixtures use
# pytest-homeassistant-custom-component instead.
# ---------------------------------------------------------------------------
def _make_ha_stub() -> None:
    """Inject minimal homeassistant stubs into sys.modules.

    Clears any broken/partial homeassistant install first so that the
    stub takes precedence even if a system package is partially installed.
    """
    # Remove any pre-existing (possibly broken) homeassistant modules
    for key in list(sys.modules):
        if key == "homeassistant" or key.startswith("homeassistant."):
            del sys.modules[key]

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    # homeassistant.core
    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object  # type: ignore[attr-defined]
    core_mod.callback = lambda f: f  # type: ignore[attr-defined]

    class _ServiceCallStub:  # noqa: D101
        """Stub for homeassistant.core.ServiceCall used by services.py."""

        def __init__(self, hass=None, domain="", service="", data=None):
            self.hass = hass
            self.domain = domain
            self.service = service
            self.data = data or {}

    core_mod.ServiceCall = _ServiceCallStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.core"] = core_mod

    # homeassistant.config_entries
    ce_mod = types.ModuleType("homeassistant.config_entries")
    ce_mod.ConfigEntry = object  # type: ignore[attr-defined]
    ce_mod.ConfigFlow = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.config_entries"] = ce_mod

    # homeassistant.helpers.update_coordinator
    helpers_mod = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers_mod
    uc_mod = types.ModuleType("homeassistant.helpers.update_coordinator")

    class _DataUpdateCoordinatorStub:  # noqa: D101
        """Minimal stub — supports DataUpdateCoordinator[T] subscript."""

        def __class_getitem__(cls, item):  # type: ignore[override]
            return cls

    uc_mod.DataUpdateCoordinator = _DataUpdateCoordinatorStub  # type: ignore[attr-defined]
    uc_mod.UpdateFailed = Exception  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.update_coordinator"] = uc_mod

    # homeassistant.helpers.entity
    he_mod = types.ModuleType("homeassistant.helpers.entity")
    he_mod.Entity = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity"] = he_mod

    # homeassistant.helpers.entity_platform
    hep_mod = types.ModuleType("homeassistant.helpers.entity_platform")
    hep_mod.AddEntitiesCallback = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity_platform"] = hep_mod

    # homeassistant.helpers.event
    he_mod = types.ModuleType("homeassistant.helpers.event")
    he_mod.async_track_time_interval = lambda hass, action, interval: (lambda: None)  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.event"] = he_mod

    # homeassistant.helpers.config_validation — used by services.py
    cv_mod = types.ModuleType("homeassistant.helpers.config_validation")

    def _ensure_list(value):
        """Stub for cv.ensure_list."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    cv_mod.ensure_list = _ensure_list  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.config_validation"] = cv_mod

    # homeassistant.components.sensor
    sensor_mod = types.ModuleType("homeassistant.components.sensor")
    sensor_mod.SensorEntity = object  # type: ignore[attr-defined]
    sensor_mod.SensorDeviceClass = object  # type: ignore[attr-defined]
    sensor_mod.SensorStateClass = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.sensor"] = sensor_mod

    # homeassistant.components.binary_sensor
    bs_mod = types.ModuleType("homeassistant.components.binary_sensor")
    bs_mod.BinarySensorEntity = object  # type: ignore[attr-defined]
    bs_mod.BinarySensorDeviceClass = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.binary_sensor"] = bs_mod

    # homeassistant.components.lawn_mower
    lm_mod = types.ModuleType("homeassistant.components.lawn_mower")
    lm_mod.LawnMowerEntity = object  # type: ignore[attr-defined]
    lm_mod.LawnMowerActivity = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.lawn_mower"] = lm_mod

    # homeassistant.const — expose common CONF_* and other constants
    const_mod = types.ModuleType("homeassistant.const")
    const_mod.CONF_USERNAME = "username"  # type: ignore[attr-defined]
    const_mod.CONF_PASSWORD = "password"  # type: ignore[attr-defined]
    const_mod.CONF_HOST = "host"  # type: ignore[attr-defined]
    const_mod.CONF_PORT = "port"  # type: ignore[attr-defined]
    const_mod.CONF_NAME = "name"  # type: ignore[attr-defined]
    const_mod.CONF_TOKEN = "token"  # type: ignore[attr-defined]
    const_mod.UnitOfLength = object  # type: ignore[attr-defined]
    const_mod.UnitOfArea = object  # type: ignore[attr-defined]
    const_mod.UnitOfTime = object  # type: ignore[attr-defined]
    const_mod.PERCENTAGE = "%"  # type: ignore[attr-defined]
    sys.modules["homeassistant.const"] = const_mod

    # homeassistant.exceptions
    exc_mod = types.ModuleType("homeassistant.exceptions")
    exc_mod.ConfigEntryNotReady = Exception  # type: ignore[attr-defined]
    sys.modules["homeassistant.exceptions"] = exc_mod


_make_ha_stub()

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures directory."""
    return FIXTURES
