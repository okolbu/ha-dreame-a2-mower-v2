"""Domain-level constants for the Dreame A2 Mower integration."""
from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "dreame_a2_mower"
"""HA domain identifier — kept identical to legacy for config-flow continuity."""

PLATFORMS: Final = ["lawn_mower", "sensor"]
"""HA platforms this integration sets up. F1 = lawn_mower + sensor only.
F2 onward extends this list."""

LOGGER: Final = logging.getLogger(__package__)
"""Module-level logger. Per spec §3, every layer-3 file uses this."""

# Config flow keys
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_COUNTRY: Final = "country"

# Default values
DEFAULT_NAME: Final = "Dreame A2 Mower"
DEFAULT_COUNTRY: Final = "eu"

# Log prefixes — single source per spec §3 cross-cutting commitment.
LOG_NOVEL_PROPERTY: Final = "[NOVEL/property]"
LOG_NOVEL_VALUE: Final = "[NOVEL/value]"
LOG_NOVEL_KEY: Final = "[NOVEL_KEY]"
LOG_EVENT: Final = "[EVENT]"
LOG_SESSION: Final = "[SESSION]"
LOG_MAP: Final = "[MAP]"
