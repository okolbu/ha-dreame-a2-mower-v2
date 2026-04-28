"""Domain-level constants for the Dreame A2 Mower integration."""
from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import CONF_PASSWORD as CONF_PASSWORD  # noqa: PLC0414
from homeassistant.const import CONF_USERNAME as CONF_USERNAME  # noqa: PLC0414

DOMAIN: Final = "dreame_a2_mower"
"""HA domain identifier — kept identical to legacy for config-flow continuity."""

PLATFORMS: Final = [
    "lawn_mower",
    "sensor",
    "binary_sensor",
    "device_tracker",
    "camera",
    "select",
    "number",
    "switch",
    "time",
    "button",
]
"""HA platforms this integration sets up. F5 = session lifecycle surface added button."""

LOGGER: Final = logging.getLogger(__package__)
"""Module-level logger. Per spec §3, every layer-3 file uses this."""

# Config flow keys
# CONF_USERNAME and CONF_PASSWORD are re-exported from homeassistant.const
# (see import block above). CONF_COUNTRY stays local — it's our cloud-region
# key, not an HA standard constant.
CONF_COUNTRY: Final = "country"

# F7.7.1: archive retention options.
CONF_LIDAR_ARCHIVE_KEEP: Final = "lidar_archive_keep"
CONF_LIDAR_ARCHIVE_MAX_MB: Final = "lidar_archive_max_mb"
CONF_SESSION_ARCHIVE_KEEP: Final = "session_archive_keep"

# Default values
DEFAULT_NAME: Final = "Dreame A2 Mower"
DEFAULT_COUNTRY: Final = "eu"
DEFAULT_LIDAR_ARCHIVE_KEEP: Final = 20
DEFAULT_LIDAR_ARCHIVE_MAX_MB: Final = 200
DEFAULT_SESSION_ARCHIVE_KEEP: Final = 50

# Log prefixes — single source per spec §3 cross-cutting commitment.
LOG_NOVEL_PROPERTY: Final = "[NOVEL/property]"
LOG_NOVEL_VALUE: Final = "[NOVEL/value]"
LOG_NOVEL_KEY: Final = "[NOVEL_KEY]"
# Forward-compat slot: LOG_NOVEL_KEY is kept in the log_buffer prefix tuple
# so it captures any future namespaced NOVEL_KEY variants (e.g. when CFG
# schema validation lands and emits "[NOVEL_KEY/cfg]" messages).
LOG_NOVEL_KEY_SESSION_SUMMARY: Final = "[NOVEL_KEY/session_summary]"
LOG_EVENT: Final = "[EVENT]"
LOG_SESSION: Final = "[SESSION]"
LOG_MAP: Final = "[MAP]"

# Dreame cloud obfuscated-strings blob.
# gzip-compressed, base64-encoded JSON array of API endpoint fragments,
# header names, and field keys.  Decoded at runtime by DreameA2CloudClient.
# Source: legacy dreame/const.py DREAME_STRINGS.
DREAME_STRINGS: Final = (
    "H4sICAAAAAAEAGNsb3VkX3N0cmluZ3MuanNvbgBdUltv2jAU/iuoUtEmjZCEljBVPDAQgu0hK5eudJrQ"
    "wXaIV18y24yyX79jm45tebDPd67f+ZyvVwnXLqGGgWSJY6S+eneV9fJ+gfdidBKb8XUll5+a4nr1A12T"
    "kLhdSjCu1pJ1s+Q2uX3fesM/11qxuxYvl62sn6R3rSUBwbq9JE3f+p5kkO56xaDY5Xm/XxT9HaHkZpBV"
    "vYIOKrjJd5Cl0EuhGmTQp1Unw6IPYDlpPc0+is2XTDzm0yOZbV7K5+n9o1zk97NmtM6mTw+qLsvJfogF"
    "afjQsA7cwaIhwTpm1pyiveOKTrQErhA0RjfMuBOaqMCcepcAV2kjh/Ny2bYE40MQor03oNzWnRBikmGVY"
    "bbeOv3MVPsf5MMNWHvUhrYPlhkFMtS0X70BhE5AiD4oh7gbxe/AwdVdHc7QDUOYxKyNzS+j/2D20nB0b"
    "HkM7rn2hmPK8w0bn1t7Lh3cMu7qkZcioqjUJULBga9kPzlhaAhu3UPu46rSMVCuxvMItCPeCnsbkPacH"
    "/DeV0tNmQjsCK5vL5RwWodo6Z+KKTrWUsIro4oLX+ovL+D5rXytVw6vGkdo419uz9wkEJ1E1vY/PInDR"
    "igqorWXYbRnyl1CC0EQ+ARt+C9wUcNV0LAT/oqxVo4hWMXh0DSCk5DY/W5DdrPFY3umo49KaKBrI6Kjt"
    "Dajf3u//QbhJuZXdAMAAA=="
)
