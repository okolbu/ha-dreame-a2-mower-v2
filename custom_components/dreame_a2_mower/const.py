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
