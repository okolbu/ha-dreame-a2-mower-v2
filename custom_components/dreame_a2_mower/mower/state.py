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
from enum import Enum, IntEnum


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


class ActionMode(str, Enum):
    """User's mode selection for the next start_mowing dispatch.

    Mirrors the Dreame app's main-screen dropdown (per APP_INFO.txt).
    Manual mode is BT-only on g2408 and intentionally omitted.

    Persistence: persistent (intent survives HA restart).
    """
    ALL_AREAS = "all_areas"
    EDGE = "edge"
    ZONE = "zone"
    SPOT = "spot"


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

    # Source: integrated from live_map.legs by the coordinator
    # (LiveMapState.total_distance_m()). Resets at session end.
    # Persistence: volatile.
    session_distance_m: float | None = None

    # Source: s2.66[0] (confirmed). Persistence: persistent (slow-changing).
    total_lawn_area_m2: float | None = None

    # Source: s1.4 telemetry bytes [26-28] (uint24 LE × 100 cent → m²).
    # The mower's per-task target area: full lawn for all-areas mode,
    # the chosen zone/spot area in zone/spot mode. Drops to None when
    # no session is active. v1.0.0a51 added.
    task_total_area_m2: float | None = None

    # Derived in coordinator._compute_target_area_m2(): the cloud-
    # supplied area for the current zone/spot selection (sum of selected
    # entries) when the user has picked a target, otherwise the full
    # lawn area. Lets the dashboard show "what's actually being mowed"
    # rather than the whole-lawn figure during spot/zone runs.
    target_area_m2: float | None = None

    # Source: s1.4 byte[8] decoded (confirmed). Persistence: volatile.
    mowing_phase: int | None = None

    # Source: s1.4 byte[1-2] decoded (confirmed). Persistence: persistent.
    position_x_m: float | None = None

    # Source: s1.4 byte[3-4] decoded (confirmed). Persistence: persistent.
    position_y_m: float | None = None

    # Source: s1.4 (heading byte, dock-relative frame). Persistence: persistent.
    # Used by map_render to rotate the mower icon so its asymmetric
    # front-to-back shape shows the actual driving direction.
    position_heading_deg: float | None = None

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
    cleaning_brush_life_pct: float | None = None

    # Source: CFG (confirmed). Persistence: persistent.
    total_mowing_time_min: int | None = None
    total_mowed_area_m2: float | None = None
    mowing_count: int | None = None
    first_mowing_date: str | None = None

    # Source: config_flow option. Persistence: persistent.
    # 0..360 degrees compass — 0 means "station faces north, projection is
    # identity". Used to project position_x_m, position_y_m onto
    # position_north_m, position_east_m.
    station_bearing_deg: float | None = None

    # Source: computed (15s of no s1.4 telemetry while state==MOWING).
    # Persistence: volatile. F5 wires the detector; F2 leaves at None.
    manual_mode: bool | None = None

    # ------ F3 fields (action intent) ------

    # Source: integration state (user selection via select.action_mode).
    # Persistence: persistent. Default ALL_AREAS matches the Dreame app's
    # main screen default.
    action_mode: ActionMode = ActionMode.ALL_AREAS

    # Source: integration state (set via dreame_a2_mower.set_active_selection
    # service or the dashboard's map-card click flow).
    # Persistence: persistent (user shouldn't lose selection across HA reboot).
    active_selection_zones: tuple[int, ...] = ()
    active_selection_spots: tuple[int, ...] = ()

    # ------ F4 fields: CFG-derived settings ------

    # Source: CFG.CLS (confirmed). Persistence: persistent.
    child_lock_enabled: bool | None = None

    # Source: CFG.VOL (confirmed, 0..100%). Persistence: persistent.
    volume_pct: int | None = None

    # Source: CFG.LANG (confirmed, index pair [text_idx, voice_idx]).
    # Stored as raw string representation; F4 exposes read-only.
    # Persistence: persistent.
    language_code: str | None = None

    # Source: CFG.PRE[0] (zone_id). Persistence: persistent.
    pre_zone_id: int | None = None

    # Source: CFG.PRE[1] (0=Standard, 1=Efficient); also pushed via s6.2[1].
    # Persistence: persistent.
    pre_mowing_efficiency: int | None = None

    # Source: CFG.PRE[2] (mm, range 30..70 in 5mm steps); also pushed via s6.2[0].
    # Persistence: persistent.
    pre_mowing_height_mm: int | None = None

    # Source: CFG.PRE[8] (edge detection / edgemaster bool); also pushed via s6.2[2].
    # Persistence: persistent.
    pre_edgemaster: bool | None = None

    # ------ F4 fields: s2.51-derived settings ------

    # Source: CFG.WRP (confirmed); also pushed via s2.51 Setting.RAIN_PROTECTION.
    # Persistence: persistent.
    rain_protection_enabled: bool | None = None

    # Source: CFG.WRP (confirmed); also pushed via s2.51 Setting.RAIN_PROTECTION.
    # Persistence: persistent.
    rain_protection_resume_hours: int | None = None

    # Source: CFG.LOW (confirmed); also pushed via s2.51 Setting.LOW_SPEED_NIGHT.
    # Persistence: persistent.
    low_speed_at_night_enabled: bool | None = None

    # Source: CFG.LOW (confirmed); also pushed via s2.51 Setting.LOW_SPEED_NIGHT.
    # Persistence: persistent.
    low_speed_at_night_start_min: int | None = None

    # Source: CFG.LOW (confirmed); also pushed via s2.51 Setting.LOW_SPEED_NIGHT.
    # Persistence: persistent.
    low_speed_at_night_end_min: int | None = None

    # Source: CFG.ATA (confirmed); also pushed via s2.51 Setting.ANTI_THEFT.
    # Persistence: persistent.
    anti_theft_lift_alarm: bool | None = None

    # Source: CFG.ATA (confirmed); also pushed via s2.51 Setting.ANTI_THEFT.
    # Persistence: persistent.
    anti_theft_offmap_alarm: bool | None = None

    # Source: CFG.ATA (confirmed); also pushed via s2.51 Setting.ANTI_THEFT.
    # Persistence: persistent.
    anti_theft_realtime_location: bool | None = None

    # Source: CFG.DND (confirmed); also pushed via s2.51 Setting.DND.
    # Persistence: persistent.
    dnd_enabled: bool | None = None

    # Source: CFG.DND (confirmed); also pushed via s2.51 Setting.DND.
    # (minutes since midnight). Persistence: persistent.
    dnd_start_min: int | None = None

    # Source: CFG.DND (confirmed); also pushed via s2.51 Setting.DND.
    # (minutes since midnight). Persistence: persistent.
    dnd_end_min: int | None = None

    # Source: CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING.
    # (auto-recharge threshold). Persistence: persistent.
    auto_recharge_battery_pct: int | None = None

    # Source: CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING.
    # (resume-mowing threshold). Persistence: persistent.
    resume_battery_pct: int | None = None

    # Source: CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING.
    # Persistence: persistent.
    custom_charging_enabled: bool | None = None

    # Source: CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING.
    # (charging schedule start). Persistence: persistent.
    charging_start_min: int | None = None

    # Source: CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING.
    # (charging schedule end). Persistence: persistent.
    charging_end_min: int | None = None

    # Source: CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD.
    # Persistence: persistent.
    led_period_enabled: bool | None = None

    # Source: CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD.
    # Persistence: persistent.
    led_in_standby: bool | None = None

    # Source: CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD.
    # Persistence: persistent.
    led_in_working: bool | None = None

    # Source: CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD.
    # Persistence: persistent.
    led_in_charging: bool | None = None

    # Source: CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD.
    # Persistence: persistent.
    led_in_error: bool | None = None

    # Source: CFG.REC (confirmed); also pushed via s2.51 Setting.HUMAN_PRESENCE_ALERT.
    # Persistence: persistent.
    human_presence_alert_enabled: bool | None = None

    # Source: CFG.REC (confirmed); also pushed via s2.51 Setting.HUMAN_PRESENCE_ALERT.
    # Persistence: persistent.
    human_presence_alert_sensitivity: int | None = None

    # Source: s2.51 Setting.LANGUAGE values["text_idx"]. Persistence: persistent.
    language_text_idx: int | None = None

    # Source: s2.51 Setting.LANGUAGE values["voice_idx"]. Persistence: persistent.
    language_voice_idx: int | None = None

    # Source: s2.51 Setting.TIMESTAMP values["time"] (unix epoch of last settings push).
    # Observability hook — not a user-visible setting. Persistence: persistent.
    last_settings_change_unix: int | None = None

    # ------ F5 fields: session lifecycle ------

    # Volatile — mirror of LiveMapState.is_active(), populated by
    # coordinator._on_state_update on every push. begin_session fires
    # when task_state_code transitions from None → non-None (any
    # active task), end_session fires from the finalize gate when
    # task_state_code transitions back to None. Persistence: volatile
    # (coordinator resets on boot until first s2p56 push arrives).
    session_active: bool | None = None

    # Volatile — unix timestamp when the current session started (set
    # when task_state_code first transitions from None → non-None).
    # Persistence: volatile.
    session_started_unix: int | None = None

    # Volatile — list of leg-tracks; each leg is a tuple of (x_m, y_m) points.
    # Empty until first s1p4 arrives during an active session.
    # Persistence: volatile (in-progress restore is handled by archive/session.py).
    session_track_segments: tuple[tuple[tuple[float, float], ...], ...] | None = None

    # Persistent — OSS object key for the session-summary JSON; set by event_occured,
    # cleared after successful fetch. Persistence: persistent.
    pending_session_object_name: str | None = None

    # Persistent — unix timestamp when the OSS event_occured first arrived.
    # Used by finalize gate for max-age expiry (spec §6 cloud robustness).
    # Persistence: persistent.
    pending_session_first_event_unix: int | None = None

    # Persistent — unix timestamp of the most recent OSS fetch attempt.
    # Set each time the coordinator calls _do_oss_fetch.
    # Used by finalize gate for retry-interval gating. Persistence: persistent.
    pending_session_last_attempt_unix: int | None = None

    # Persistent — number of fetch attempts for pending_session_object_name.
    # Used by finalize gate for max-attempts cutoff. Persistence: persistent.
    pending_session_attempt_count: int | None = None

    # Persistent — md5 of the most recently archived completed session.
    # Source: archive/session.py on successful archive. Persistence: persistent.
    latest_session_md5: str | None = None

    # Persistent — unix timestamp when the most recent session ended.
    # Source: session-summary JSON parsed by protocol/session_summary.py.
    # Persistence: persistent.
    latest_session_unix_ts: int | None = None

    # Persistent — area mowed in the most recent session (m²).
    # Source: session-summary JSON. Persistence: persistent.
    latest_session_area_m2: float | None = None

    # Persistent — duration of the most recent session (minutes).
    # Source: session-summary JSON. Persistence: persistent.
    latest_session_duration_min: int | None = None

    # Persistent — total number of sessions in the on-disk archive.
    # Source: archive/session.py load_index. Persistence: persistent.
    archived_session_count: int | None = None

    # ------ F7 fields ------

    # Source: s99.20 (confirmed). Persistence: volatile.
    # Last LiDAR-scan OSS object key announced by the mower. The
    # coordinator's _handle_lidar_object_name (F7.2.2) consults this to
    # schedule a fetch + archive write. Cleared after the archive accepts
    # the new bytes.
    latest_lidar_object_name: str | None = None

    # F7: count of archived LiDAR scans on disk. Persistence: persistent.
    archived_lidar_count: int | None = None

    # ------ Raw diagnostic slots (v1.0.0a11) ------
    # Slots seen on the wire whose semantics aren't decoded yet.
    # Surfaced as diagnostic sensors so values can be observed without
    # triggering a [NOVEL/property] warning per push. Per spec §5.6.

    # s5.104 — observed value 7 during start_mowing. Likely a status
    # subtype; raw int.
    s5p104_raw: int | None = None

    # s5.105 — observed value 1 during a mow. Raw int.
    s5p105_raw: int | None = None

    # s5.106 — observed values 5, 7, 8 during state transitions. Likely
    # a phase/substate enum; raw int.
    s5p106_raw: int | None = None

    # s5.107 — observed value 177 during a mow. Raw int.
    s5p107_raw: int | None = None

    # s6.1 — observed value 200 during a mow start. Possibly a wifi RSSI
    # alternate encoding; raw int.
    s6p1_raw: int | None = None
