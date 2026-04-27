"""Typed domain model for the Dreame A2 (g2408) mower.

Per spec §3 layer 2: this module imports nothing from
``homeassistant.*``. It is the bridge between the pure-Python protocol
codecs (in ``protocol/``) and the HA platform glue (in
``custom_components/dreame_a2_mower/``).

Per spec §8, every field on ``MowerState`` declares its authoritative
source via docstring + a §2.1 citation. Fields default to ``None``
(meaning: no data observed yet).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class State(IntEnum):
    """Mower state per s2.1.

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.1``,
    confirmed via ioBroker apk decompilation.

    Persistence: volatile (HA shows ``unavailable`` when stale).
    """

    WORKING = 1
    STANDBY = 2
    PAUSED = 3
    RETURNING = 5
    CHARGING = 6
    MAPPING = 11
    CHARGED = 13
    UPDATING = 14


class ChargingStatus(IntEnum):
    """Charging status per s3.2 (g2408 enum offset vs upstream).

    Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s3.2``.

    Persistence: volatile.
    """

    NOT_CHARGING = 0
    CHARGING = 1
    CHARGED = 2


@dataclass(slots=True)
class MowerState:
    """The integration's typed view of the mower's current state.

    Each field's authoritative source and unknowns policy is documented
    on the field itself. Fields default to ``None`` until the first
    fresh data arrives from MQTT or the cloud API.

    Subsequent F2..F7 phases extend this dataclass with additional
    fields. New fields MUST default to ``None`` and MUST cite their
    source per spec §8.
    """

    # Source: s2.1 (confirmed). Persistence: volatile.
    state: State | None = None

    # Source: s3.1 (confirmed). Range 0..100. Persistence: volatile.
    battery_level: int | None = None

    # Source: s3.2 (confirmed, g2408 enum offset). Persistence: volatile.
    charging_status: ChargingStatus | None = None
