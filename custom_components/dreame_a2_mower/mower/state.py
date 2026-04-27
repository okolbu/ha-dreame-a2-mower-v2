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

    # ------ F2 fields ------

    # Source: s2.2 (confirmed, apk fault index). Persistence: volatile.
    error_code: int | None = None

    # Source: s1.53 (confirmed). Persistence: volatile.
    obstacle_flag: bool | None = None

    # Source: s1.4 byte[29-30] decoded (confirmed). Persistence: volatile.
    area_mowed_m2: float | None = None

    # Source: s1.4 byte[24-25] decoded (confirmed). Persistence: volatile.
    total_distance_m: float | None = None

    # Source: s2.66[0] (confirmed). Persistence: persistent (slow-changing).
    total_lawn_area_m2: float | None = None

    # Source: s1.4 byte[8] decoded (confirmed). Persistence: volatile.
    mowing_phase: int | None = None

    # Source: s1.4 byte[1-2] decoded (confirmed). Persistence: persistent.
    position_x_m: float | None = None

    # Source: s1.4 byte[3-4] decoded (confirmed). Persistence: persistent.
    position_y_m: float | None = None

    # Source: computed (x, y rotated by station_bearing_deg). Persistence: persistent.
    position_north_m: float | None = None
    position_east_m: float | None = None

    # Source: LOCN routed action (confirmed). Persistence: persistent.
    # Sentinel [-1, -1] → both None.
    position_lat: float | None = None
    position_lon: float | None = None

    # Source: s6.3[1] (confirmed g2408 overlay). Persistence: volatile.
    wifi_rssi_dbm: int | None = None

    # Source: s6.3[0] (confirmed g2408 overlay). Persistence: volatile.
    cloud_connected: bool | None = None

    # Source: s1.1 byte[6] bit (confirmed heartbeat decode). Persistence: volatile.
    battery_temp_low: bool | None = None

    # Source: s2.65 (confirmed). Persistence: volatile.
    slam_task_label: str | None = None

    # Source: s2.56 (confirmed task-state codes 1..5). Persistence: volatile.
    task_state_code: int | None = None

    # Source: CFG.CMS (confirmed). Persistence: persistent.
    blades_life_pct: float | None = None
    side_brush_life_pct: float | None = None

    # Source: CFG (confirmed). Persistence: persistent.
    total_cleaning_time_min: int | None = None
    total_cleaned_area_m2: float | None = None
    cleaning_count: int | None = None
    first_cleaning_date: str | None = None

    # Source: config_flow option. Persistence: persistent.
    # 0..360 degrees compass — 0 means "station faces north, projection is
    # identity". Used to project position_x_m, position_y_m onto
    # position_north_m, position_east_m.
    station_bearing_deg: float | None = None

    # Source: computed (15s of no s1.4 telemetry while state==MOWING).
    # Persistence: volatile. F5 wires the detector; F2 leaves at None.
    manual_mode: bool | None = None
