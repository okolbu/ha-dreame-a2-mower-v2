"""Domain-level constants for the Dreame A2 Mower integration."""
from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import CONF_PASSWORD as CONF_PASSWORD
from homeassistant.const import CONF_USERNAME as CONF_USERNAME

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
    "event",
    "calendar",
]
"""HA platforms this integration sets up. F5 = session lifecycle surface added button."""

# Lifecycle event_types fired on event.dreame_a2_mower_lifecycle.
# See docs/events.md for payload schema.
EVENT_TYPE_MOWING_STARTED: Final = "mowing_started"
EVENT_TYPE_MOWING_PAUSED: Final = "mowing_paused"
EVENT_TYPE_MOWING_RESUMED: Final = "mowing_resumed"
EVENT_TYPE_MOWING_ENDED: Final = "mowing_ended"
EVENT_TYPE_DOCK_ARRIVED: Final = "dock_arrived"
EVENT_TYPE_DOCK_DEPARTED: Final = "dock_departed"

LIFECYCLE_EVENT_TYPES: Final[tuple[str, ...]] = (
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
)

ALERT_EVENT_TYPES: Final[tuple[str, ...]] = (
    "hanging",
    "emergency_stop",
    "human_detected",
    "blades_worn",
    "maintenance_reminder",
    "positioning_failed_stuck",
    "positioning_failed_transient",
    "battery_temp_low_charging_paused",
    "mowing_complete",
    "mowing_started",
    "scheduled_mowing_started",
    "low_battery_return",
    "rain_protection",
    "schedule_cancelled_busy",
    "continue_unfinished_task",
    "positioning_failure",
    "top_cover_open",
    "arrived_at_maintenance_point",
    "robot_in_hidden_zone",
    "station_disconnected",
)
"""App-notification event_types synthesised from s2p2 transitions.
The Dreame cloud uses s2p2 to dispatch APNS/FCM pushes; the integration
mirrors them as HA events so local automations can react without cloud
dependency.  Source: docs/research/g2408-protocol.md § s2p2."""

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

# Bearing (degrees clockwise from north) of the dock's local X axis.
# Used to project dock-frame (x_m, y_m) telemetry into global compass-frame
# (north_m, east_m) for position_north_m / position_east_m sensors.
#
# CFG.DOCK.yaw is unreliable (firmware reports values that drift even when
# the dock hasn't physically moved), so this is a user-set config option.
# When unset (None), N/E projection is skipped and those entities stay
# Unknown.
#
# Convention (verify on first use): X axis points along bearing direction;
# Y axis is 90 deg CCW from X (typical robotics convention). If the
# resulting N/E values are clearly wrong (e.g. signs flipped or 90 deg
# rotated), adjust the bearing value.
CONF_STATION_BEARING_DEG: Final = "station_bearing_deg"
DEFAULT_STATION_BEARING_DEG: Final = None  # type: ignore[assignment]  # optional; user sets if they want N/E projection

# Default values
DEFAULT_NAME: Final = "Dreame A2 Mower"
MANUFACTURER: Final = "Dreame"
DEFAULT_MODEL: Final = "dreame.mower.g2408"
DEFAULT_COUNTRY: Final = "eu"
DEFAULT_LIDAR_ARCHIVE_KEEP: Final = 20
DEFAULT_LIDAR_ARCHIVE_MAX_MB: Final = 200
DEFAULT_SESSION_ARCHIVE_KEEP: Final = 50

# UI strings
WORK_LOG_PLACEHOLDER: Final = "(pick a session)"

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
