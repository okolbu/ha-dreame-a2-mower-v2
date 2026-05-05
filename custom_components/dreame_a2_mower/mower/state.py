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

    # Source: derived from cross-frame s1.4 telemetry diff
    # (protocol/wheel_bind.py). True once ≥2 consecutive 33-byte frames
    # show position held within 50 mm while area_mowed_m2 advances by
    # >0.05 m² — the signature of wheels stalled while the firmware's
    # area integrator keeps counting. Reproduces the 2026-05-05 edge-mow
    # FTRTS failure mode (firmware budget cap fires while wedged →
    # auto-dock planner can't route home from stuck pose).
    # Persistence: volatile (clears on first motion frame).
    wheel_bind_active: bool | None = None

    # Source: derived from cross-frame s1.4 telemetry diff
    # (protocol/wheel_bind.py). Counter of consecutive bind-shaped
    # frames; resets to 0 on motion. Surfaced as a diagnostic
    # attribute, not a sensor in its own right.
    wheel_bind_consecutive_frames: int = 0

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

    # Source: s1.1 byte[17] signed live RSSI (preferred while mowing /
    # connected) with a CFG.NET fallback that populates immediately on
    # HA startup so the sensor isn't Unknown for ~45 s waiting for the
    # first heartbeat. Confirmed 2026-04-30 by AP toggle test — tracks
    # from −64 to −97 dBm in lockstep with the app's signal bars.
    # Persistence: volatile.
    wifi_rssi_dbm: int | None = None

    # Source: CFG.NET.current — the SSID the mower is currently
    # associated with (e.g. "T55"). Persistence: volatile.
    wifi_ssid: str | None = None

    # Source: CFG.NET.list[where ssid==current].ip — the mower's IP on
    # that AP's network. Useful for diagnostics if the mower disappears
    # from the LAN. Persistence: volatile.
    wifi_ip: str | None = None

    # ------ CFG.DOCK fields ------
    # All sourced from `getCFG t:'DOCK'` (refreshed every minute). The
    # dock returns a single nested dict at `.d.dock` containing the
    # fields below. User-confirmed semantics on 2026-05-04.

    # connect_status: 1 → mower currently in dock; authoritative over
    # inferring from s2p1 == 6 CHARGING (which doesn't fire while the
    # mower sits docked but not actively drawing power). Persistence: volatile.
    mower_in_dock: bool | None = None

    # in_region: True iff the dock is inside the lawn polygon. User has
    # this False because the dock is placed just past the lawn edge.
    # Persistence: persistent (changes only on lawn re-mapping).
    dock_in_lawn_region: bool | None = None

    # x, y: dock position in the map's mower-frame coordinates.
    # Despite earlier integration assumptions that the dock is at (0,0),
    # the cloud reports a non-zero position. Units presumed to match
    # s1p4 telemetry x_mm / y_mm. Persistence: persistent.
    dock_x_mm: int | None = None
    dock_y_mm: int | None = None

    # yaw: dock orientation. User-confirmed 2026-05-04 to match compass
    # bearing for the X-axis direction of the dock-relative frame on
    # their setup. Unit unclear (possibly degrees; possibly something
    # else — `near_yaw: 1912` doesn't fit degrees if `yaw: 112` does).
    # Persistence: persistent.
    dock_yaw: int | None = None

    # near_x, near_y, near_yaw, path_connect: semantics TBD. Likely an
    # approach-point for path-to-dock plus a connection-quality flag.
    # Surfaced raw for future correlation. Persistence: persistent.
    dock_near_x: int | None = None
    dock_near_y: int | None = None
    dock_near_yaw: int | None = None
    dock_path_connect: int | None = None

    # Source: s6.3[0] (confirmed g2408 overlay). Persistence: volatile.
    cloud_connected: bool | None = None

    # Source: s1.1 byte[6] bit (confirmed heartbeat decode). Persistence: volatile.
    battery_temp_low: bool | None = None

    # Source: CFG.DEV.sn (preferred; reliable getCFG since v1.0.0a76)
    # with a legacy fallback to s1.5 cloud `get_properties` (mostly
    # returns 80001 on g2408). Hardware serial as printed on the device,
    # e.g. `G2408053AEE000nnnn`. Replaces the cloud `did` (a 32-bit
    # signed int) as the user-facing HA "Serial Number" field.
    # Persistence: persistent (never changes).
    hardware_serial: str | None = None

    # Source: CFG.DEV.fw — firmware version string as the device
    # itself reports it, e.g. "4.3.6_0550". Cross-reference with the
    # cloud device record's `info.version`; in practice they agree on
    # g2408 but DEV.fw is one hop closer to ground truth.
    # Persistence: persistent (changes only on OTA).
    firmware_version: str | None = None

    # Source: CFG.DEV.ota — int (observed `1`). Semantic UNCONFIRMED —
    # NOT the Auto-update Firmware app toggle (user has that OFF but
    # DEV.ota = 1, so values don't match). Most likely "OTA capability"
    # or "OTA update available". Surfaced as a raw int diagnostic until
    # we can correlate it with an app action. Persistence: persistent.
    ota_capable_raw: int | None = None

    # Source: s1.1 error bit-mask (confirmed 2026-04-30 19:37–19:39 against
    # corresponding app notifications). All volatile.
    #   drop_tilt        — byte[1] bit 1; "Robot tilted"
    #   bumper           — byte[1] bit 0; "Bumper error" (NOT mirrored to s2p2)
    #   lift             — byte[2] bit 1; "Robot lifted"
    #   emergency_stop       — byte[3] bit 7; "Emergency stop is activated".
    #                           The actual PIN-required latch — sets on
    #                           safety event (lid open / lift), clears
    #                           ONLY on PIN entry on the device. NOT a
    #                           live sensor: stays asserted even after
    #                           lid is closed / mower set down, until
    #                           the user types the PIN.
    #   safety_alert_active  — byte[10] bit 1; one-shot alert UI flag
    #                           paired with the Dreame app push
    #                           notification + mower red LED + voice
    #                           prompt. Sets ~1s after emergency_stop,
    #                           self-clears 30–90s later regardless of
    #                           PIN/lid state. Independent of the
    #                           emergency_stop latch.
    # Persistent rain/water condition is exposed via s2p2 == 56
    # (BAD_WEATHER); top-cover state via s2p2 == 73 (TOP_COVER_OPEN).
    drop_tilt: bool | None = None
    bumper: bool | None = None
    lift: bool | None = None
    emergency_stop: bool | None = None
    safety_alert_active: bool | None = None

    # Source: s2.65 (confirmed). Persistence: volatile.
    slam_task_label: str | None = None

    # Source: s2.56 (confirmed task-state codes 1..5). Persistence: volatile.
    task_state_code: int | None = None

    # Source: CFG.CMS (confirmed). Persistence: persistent.
    # Also derivable live from s2.51 CONSUMABLES counters using per-slot
    # thresholds (Blades 6000 min ≈ 100 h, Cleaning Brush 30000 min ≈ 500 h,
    # Robot Maintenance 3600 min ≈ 60 h — confirmed 2026-04-30 against the
    # app's "Consumables & Maintenance" page).
    blades_life_pct: float | None = None
    cleaning_brush_life_pct: float | None = None
    robot_maintenance_life_pct: float | None = None

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

    # ------ AMBIGUOUS_TOGGLE shape members ------
    # All four ride the s2.51 {value: 0|1} envelope (see protocol/config_s2p51.py
    # AMBIGUOUS_TOGGLE comment) and are read authoritatively from the
    # corresponding CFG key.

    # Source: CFG.FDP (confirmed). Persistence: persistent.
    frost_protection_enabled: bool | None = None

    # Source: CFG.STUN (confirmed; "Auto Recharge After Extended Standby").
    # Persistence: persistent.
    auto_recharge_standby_enabled: bool | None = None

    # Source: CFG.AOP (confirmed; "Capture Photos of AI-Detected Obstacles").
    # Persistence: persistent.
    ai_obstacle_photos_enabled: bool | None = None

    # Source: CFG.PROT (confirmed; mapping {0: direct, 1: smart}).
    # True ↔ "smart path", False ↔ "direct path". Persistence: persistent.
    navigation_path_smart: bool | None = None

    # ------ AMBIGUOUS_4LIST shape members ------
    # Per-row state for the two screens that share the s2.51 {value: [b,b,b,b]}
    # envelope. Authoritative read path is the corresponding CFG key
    # (CFG.MSG_ALERT and CFG.VOICE), since the s2.51 push itself is wire-
    # ambiguous (decoder routes it as Setting.AMBIGUOUS_4LIST). All four
    # slots in each set were toggle-confirmed against the live app on
    # 2026-04-30 — see protocol/config_s2p51.py for the slot map.

    # CFG.MSG_ALERT[0..3] — Notification Preferences (4 toggles).
    msg_alert_anomaly: bool | None = None
    msg_alert_error: bool | None = None
    msg_alert_task: bool | None = None
    msg_alert_consumables: bool | None = None

    # CFG.VOICE[0..3] — Voice Prompt Modes (4 toggles).
    voice_regular_notification: bool | None = None
    voice_work_status: bool | None = None
    voice_special_status: bool | None = None
    voice_error_status: bool | None = None

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
