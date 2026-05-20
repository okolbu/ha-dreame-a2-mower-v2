"""Device-level sensor entity classes and description tables for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it directly.  It is imported by sensor.py.

Contains: SENSORS, DIAGNOSTIC_SENSORS (description tables), all device-level
entity classes, and module-level helpers used exclusively by device sensors.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator
from .mower.error_codes import describe_error
from .mower.state import ChargingStatus, MowerState
from ._sensor_base import (
    DreameA2DiagnosticSensorEntityDescription,
    DreameA2SensorEntityDescription,
    _SnapshotEnumSensorBase,
)


# ---------------------------------------------------------------------------
# Module-level helpers and constants (device-sensor only)
# ---------------------------------------------------------------------------

# Cache the integration version once at module import time.
# manifest.json is static for the lifetime of the HA process; reading it
# repeatedly inside native_value would hit the event-loop blocking detector
# on every state refresh.  Import time is before the event loop enters its
# strict async-only mode, so a synchronous read here is safe.
_MANIFEST_VERSION: str | None = None


def _manifest_version() -> str:
    """Return the integration version string, reading manifest.json at most once."""
    global _MANIFEST_VERSION
    if _MANIFEST_VERSION is None:
        _manifest_path = Path(__file__).parent / "manifest.json"
        try:
            _MANIFEST_VERSION = str(
                json.loads(_manifest_path.read_text()).get("version", "unknown")
            )
        except Exception:  # noqa: BLE001
            _MANIFEST_VERSION = "unknown"
    return _MANIFEST_VERSION


def _describe_error_or_none(code: int | None) -> str | None:
    return describe_error(code) if code is not None else None


def _format_active_selection(state: MowerState) -> str | None:
    """Format zone/spot selection for display.

    Examples:
      action_mode=all_areas → 'All areas'
      action_mode=edge → 'Edge mow'
      action_mode=zone, zones=(3, 1, 2) → 'Zones 3 → 1 → 2'
      action_mode=zone, zones=() → 'No zones selected'
      action_mode=spot, spots=() → 'No spots selected'
    """
    from .mower.state import ActionMode
    mode = state.action_mode
    if mode == ActionMode.ALL_AREAS:
        return "All areas"
    if mode == ActionMode.EDGE:
        return "Edge mow"
    if mode == ActionMode.ZONE:
        zones = state.active_selection_zones
        if not zones:
            return "No zones selected"
        return "Zones " + " → ".join(str(z) for z in zones)
    if mode == ActionMode.SPOT:
        spots = state.active_selection_spots
        if not spots:
            return "No spots selected"
        return "Spots " + " → ".join(str(s) for s in spots)
    return None


def _api_endpoints_value(coord) -> int:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return 0
    return sum(1 for v in cloud.endpoint_log.values() if v == "accepted")


def _api_endpoints_attrs(coord) -> dict[str, list[str]]:
    cloud = getattr(coord, "_cloud", None)
    if cloud is None:
        return {"accepted": [], "rejected_80001": [], "error": []}
    log = cloud.endpoint_log
    return {
        "accepted": sorted(k for k, v in log.items() if v == "accepted"),
        "rejected_80001": sorted(k for k, v in log.items() if v == "rejected_80001"),
        "error": sorted(k for k, v in log.items() if v == "error"),
    }


def _freshness_value(coord) -> int | None:
    """Age in seconds of the oldest tracked field, or None if nothing
    has been stamped yet."""
    snap = coord.freshness.snapshot()
    if not snap:
        return None
    now = int(time.time())
    return now - min(snap.values())


def _freshness_attrs(coord) -> dict[str, int]:
    """Per-field age in seconds, keyed as ``{field}_age_s``."""
    snap = coord.freshness.snapshot()
    now = int(time.time())
    return {f"{name}_age_s": now - ts for name, ts in snap.items()}


# Schedule label helpers — module-level so tests / dashboard templates
# can reuse them. Mon..Sun ordering matches the firmware's weekday=1..7
# numbering decoded into bit 0..bit 6.
_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_ACTION_LABELS = {
    0: "all_area",
    1: "zone",
    2: "edge",
}


def _fmt_hhmm(time_min: int) -> str:
    return f"{time_min // 60:02d}:{time_min % 60:02d}"


def _fmt_weekdays(mask: int) -> list[str]:
    return [_WEEKDAY_LABELS[i] for i in range(7) if mask & (1 << i)]


def _fmt_action(action_type: int) -> str:
    return _ACTION_LABELS.get(action_type, f"unknown_{action_type}")


# ---------------------------------------------------------------------------
# Description tables
# ---------------------------------------------------------------------------

SENSORS: tuple[DreameA2SensorEntityDescription, ...] = (
    DreameA2SensorEntityDescription(
        key="charging_status",
        translation_key="charging_status",
        name="Charging status",
        device_class=SensorDeviceClass.ENUM,
        options=[c.name.lower() for c in ChargingStatus],
        value_fn=lambda s: (s.charging_status.name.lower() if s.charging_status is not None else None),
    ),

    # Telemetry-derived:
    DreameA2SensorEntityDescription(
        key="area_mowed_m2",
        name="Area mowed",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.area_mowed_m2 if s.area_mowed_m2 is not None else 0,
    ),
    DreameA2SensorEntityDescription(
        key="session_distance_m",
        name="Session distance",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.session_distance_m if s.session_distance_m is not None else 0,
    ),
    # mowing_phase / task_state_code / slam_task_label have been migrated
    # to DIAGNOSTIC_SENSORS so they read coord.state_machine.snapshot()
    # and survive HA restarts (last-known persisted via the snapshot
    # Store). See the entries near the bottom of DIAGNOSTIC_SENSORS.

    # State-related:
    DreameA2SensorEntityDescription(
        key="error_code",
        name="Error code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.error_code,
    ),
    DreameA2SensorEntityDescription(
        key="error_description",
        name="Error",
        value_fn=lambda s: _describe_error_or_none(s.error_code),
    ),

    # Lawn / environment:
    DreameA2SensorEntityDescription(
        # Keep the existing key for entity-id stability; the value_fn
        # now resolves to the *target* area (cloud-supplied area_m2 of
        # the selected zone/spot) when the user has picked a target,
        # falling back to the full lawn area otherwise. Reads as
        # 'Target area' so the friendly name matches the value.
        key="total_lawn_area_m2",
        name="Target area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: (
            s.target_area_m2 if s.target_area_m2 is not None else s.total_lawn_area_m2
        ),
    ),
    DreameA2SensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.wifi_ssid,
    ),
    DreameA2SensorEntityDescription(
        key="wifi_ip",
        name="WiFi IP",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.wifi_ip,
    ),
    # CFG.DOCK position fields. yaw user-confirmed to match compass
    # X-axis of the dock-relative frame; x/y are map-frame coords (NOT
    # necessarily 0,0 despite earlier integration assumptions).
    DreameA2SensorEntityDescription(
        key="dock_x_mm",
        name="Dock X",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.dock_x_mm,
    ),
    DreameA2SensorEntityDescription(
        key="dock_y_mm",
        name="Dock Y",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.dock_y_mm,
    ),
    DreameA2SensorEntityDescription(
        key="dock_yaw",
        name="Dock yaw",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # User-confirmed 2026-05-04: matches compass bearing for the
        # X-axis direction of the dock frame. Unit unclear (may be
        # degrees, may be deci-degrees — `near_yaw: 1912` is suspicious
        # if `yaw: 112` is degrees).
        value_fn=lambda s: s.dock_yaw,
    ),

    # CFG-derived consumables:
    DreameA2SensorEntityDescription(
        key="blades_life_pct",
        name="Blades life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.blades_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="cleaning_brush_life_pct",
        name="Cleaning brush life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.cleaning_brush_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="robot_maintenance_life_pct",
        name="Robot maintenance life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda s: s.robot_maintenance_life_pct,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowing_time_min",
        name="Total mowing time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.total_mowing_time_min,
    ),
    DreameA2SensorEntityDescription(
        key="total_mowed_area_m2",
        name="Total mowed area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_mowed_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="mowing_count",
        name="Mowing count",
        # Pre-greenfield used "x" as the unit; HA's recorder compares
        # incoming statistics against the historical unit and suppresses
        # long-term stats on mismatch. Keep the same unit so existing
        # statistics carry over without manual cleanup.
        native_unit_of_measurement="x",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.mowing_count,
    ),
    DreameA2SensorEntityDescription(
        key="first_mowing_date",
        name="First mowing date",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.first_mowing_date,
    ),
    DreameA2SensorEntityDescription(
        key="active_selection",
        name="Active selection",
        value_fn=_format_active_selection,
    ),

    # Settings-derived (s2.51) observability:
    DreameA2SensorEntityDescription(
        key="last_settings_change_unix",
        name="Last settings change",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_settings_change_unix,
    ),
    DreameA2SensorEntityDescription(
        key="language_text_idx",
        name="Language text index",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.language_text_idx,
    ),
    DreameA2SensorEntityDescription(
        key="language_voice_idx",
        name="Language voice index",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.language_voice_idx,
    ),

    # ------ v1.0.0a11: raw protocol diagnostic sensors per spec §5.6 ------
    DreameA2SensorEntityDescription(
        key="s5p104_raw",
        name="s5.104 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p104_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p105_raw",
        name="s5.105 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p105_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p106_raw",
        name="s5.106 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p106_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s5p107_raw",
        name="s5.107 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s5p107_raw,
    ),
    DreameA2SensorEntityDescription(
        key="s6p1_raw",
        name="s6.1 raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.s6p1_raw,
    ),

    # ------ F5.11.1: session history sensors ------

    DreameA2SensorEntityDescription(
        key="latest_session_area_m2",
        name="Latest session area",
        native_unit_of_measurement="m²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda s: s.latest_session_area_m2,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_duration_min",
        name="Latest session duration",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.latest_session_duration_min,
    ),
    DreameA2SensorEntityDescription(
        key="latest_session_unix_ts",
        name="Latest session time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: (
            datetime.fromtimestamp(s.latest_session_unix_ts, tz=UTC)
            if s.latest_session_unix_ts is not None
            else None
        ),
    ),
    DreameA2SensorEntityDescription(
        key="archived_session_count",
        name="Archived session count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_session_count,
    ),
    DreameA2SensorEntityDescription(
        key="lidar_archive_count",
        translation_key="lidar_archive_count",
        icon="mdi:cube-scan",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.archived_lidar_count,
    ),
    DreameA2SensorEntityDescription(
        key="session_track_point_count",
        name="Session track point count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            sum(len(leg) for leg in s.session_track_segments)
            if s.session_track_segments is not None
            else 0
        ),
    ),
    # REC[8] — push notification cooldown (minutes between successive
    # detection pushes). Wire enum {3, 10, 20} from the app's 3-radio-
    # button "Push interval" selector. Read-only on this firmware.
    DreameA2SensorEntityDescription(
        key="human_presence_push_interval_min",
        translation_key="human_presence_push_interval_min",
        name="Human presence push interval",
        native_unit_of_measurement="min",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.human_presence_alert_push_interval_min,
    ),

    # ------ Phase 2 recorder-merge safety-net sensor ------
    # charging_status_code_raw exists so HA's recorder captures charging
    # transitions as raw ints. T7's merge_recorder_samples reads it back
    # to backfill in_progress.json charging-state sample streams.
    # state_code_raw was removed (redundant with snapshot-backed
    # sensor.task_state_code) and error_code_raw was removed (redundant
    # with the existing sensor.error_code which already returns the raw int).
    DreameA2SensorEntityDescription(
        key="charging_status_code_raw",
        translation_key="charging_status_code_raw",
        name="Charging status code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.charging_status.value if s.charging_status is not None else None,
    ),
)


DIAGNOSTIC_SENSORS: tuple[DreameA2DiagnosticSensorEntityDescription, ...] = (
    # Battery percentage — reads the persisted snapshot value so it survives
    # HA restarts. The snapshot is loaded from disk via state_machine
    # .load_persisted() and updated on every s3p1 push via
    # _apply_battery_percent; reading coord.data.battery_level would show
    # Unknown after restart until the first push arrives. Note: lives in
    # DIAGNOSTIC_SENSORS only because that tuple uses the coord-aware
    # descriptor (value_fn(coord)). No entity_category is set, so this
    # remains a primary (non-diagnostic) entity.
    DreameA2DiagnosticSensorEntityDescription(
        key="battery_level",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda coord: coord.state_machine.snapshot().battery_percent,
    ),
    # WiFi RSSI — reads the persisted snapshot value so it survives HA
    # restarts. The snapshot is loaded from disk via state_machine
    # .load_persisted() and updated on every s1p1 heartbeat via
    # MowerStateMachine.handle_heartbeat; reading coord.data.wifi_rssi_dbm
    # would show Unknown after restart until the next heartbeat arrives.
    DreameA2DiagnosticSensorEntityDescription(
        key="wifi_rssi_dbm",
        name="WiFi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.state_machine.snapshot().wifi_rssi_dbm,
    ),
    # Position quartet — read from the persisted snapshot so values survive
    # HA restarts. position_x_m / position_y_m are written by
    # MowerStateMachine.handle_position on every s1p4 telemetry push;
    # position_north_m / position_east_m have no live writer yet (declared
    # for future expansion) and will read None until one is added.
    DreameA2DiagnosticSensorEntityDescription(
        key="position_x_m",
        name="Position X",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda coord: coord.state_machine.snapshot().position_x_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_y_m",
        name="Position Y",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda coord: coord.state_machine.snapshot().position_y_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_north_m",
        name="Position North",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda coord: coord.state_machine.snapshot().position_north_m,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="position_east_m",
        name="Position East",
        native_unit_of_measurement="m",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda coord: coord.state_machine.snapshot().position_east_m,
    ),
    # mowing_phase / task_state_code / slam_task_label — snapshot-backed so
    # last-known values survive HA restart instead of going Unknown until
    # the next live MQTT event. Writers in coordinator.handle_property_push
    # route s1p4 / s2p56 / s2p65 updates through state_machine.handle_misc_persisted.
    DreameA2DiagnosticSensorEntityDescription(
        key="mowing_phase",
        name="Mowing phase",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.state_machine.snapshot().mowing_phase,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="task_state_code",
        translation_key="task_state_code",
        name="Task state (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.state_machine.snapshot().task_state_code,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="slam_task_label",
        name="SLAM task",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coord: coord.state_machine.snapshot().slam_task_label,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="novel_observations",
        translation_key="novel_observations",
        icon="mdi:eye-question",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        value_fn=lambda coord: (
            coord.novel_registry.snapshot().count
            if coord.novel_registry.snapshot().count is not None
            else 0
        ),
        extra_state_attributes_fn=lambda coord: {
            "observations": [
                {
                    "category": o.category,
                    "detail": o.detail,
                    "first_seen_unix": o.first_seen_unix,
                }
                for o in coord.novel_registry.snapshot().observations
            ],
        },
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="data_freshness",
        translation_key="data_freshness",
        native_unit_of_measurement="s",
        icon="mdi:clock-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_freshness_value,
        extra_state_attributes_fn=_freshness_attrs,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="api_endpoints_supported",
        translation_key="api_endpoints_supported",
        icon="mdi:api",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_api_endpoints_value,
        extra_state_attributes_fn=_api_endpoints_attrs,
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="hardware_serial",
        translation_key="hardware_serial",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Hardware serial as printed on the mower (e.g. `G2408053AEE000nnnn`).
        # Sourced from CFG.DEV.sn (preferred path since v1.0.0a76); same
        # value the device-info card shows under "Serial Number".
        value_fn=lambda coord: getattr(coord.data, "hardware_serial", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="firmware_version_dev",
        translation_key="firmware_version_dev",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Firmware version reported by CFG.DEV.fw — e.g. "4.3.6_0550".
        # Cross-check against the cloud device record's info.version.
        value_fn=lambda coord: getattr(coord.data, "firmware_version", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="ota_capable_raw",
        translation_key="ota_capable_raw",
        icon="mdi:download-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # CFG.DEV.ota — int, semantic UNCONFIRMED. NOT the Auto-update
        # Firmware app toggle (those values don't match). Likely "OTA
        # capability" or "OTA update available". Surfaced raw so future
        # toggle-correlation can pin down the meaning.
        value_fn=lambda coord: getattr(coord.data, "ota_capable_raw", None),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="cloud_device_id",
        translation_key="cloud_device_id",
        icon="mdi:cloud-tags",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The Dreame/Xiaomi cloud's internal device record ID — what the
        # cloud API expects in `did` fields. NOT the hardware serial; it's
        # a 32-bit signed integer (often negative) and is unique to the
        # cloud account record, not the physical device. Surfaced for
        # users who need to query the cloud API directly outside HA.
        value_fn=lambda coord: (
            getattr(getattr(coord, "_cloud", None), "device_id", None)
        ),
    ),
    DreameA2DiagnosticSensorEntityDescription(
        key="mac_address",
        translation_key="mac_address",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # The mower's WiFi MAC. Pulled from the cloud device record's
        # `mac` field in get_devices() / select_first_g2408(). Also wired
        # into DeviceInfo.connections so HA's device card displays it
        # natively (and so other integrations can match against the same
        # physical device).
        value_fn=lambda coord: (
            getattr(getattr(coord, "_cloud", None), "mac_address", None)
        ),
    ),
)


# ---------------------------------------------------------------------------
# Device-level entity classes
# ---------------------------------------------------------------------------

class DreameA2CurrentActivitySensor(_SnapshotEnumSensorBase):
    _attr_name = "Current activity"
    _attr_icon = "mdi:robot-mower"
    _attr_translation_key = "current_activity"
    _SNAPSHOT_FIELD = "current_activity"
    _KEY = "current_activity"
    _attr_options = [
        "mowing", "paused", "repositioning", "returning", "charge_resume",
        "cruising_to_point", "at_point", "fast_mapping",
        "driving_blades_up", "idle",
    ]


class DreameA2LocationSensor(_SnapshotEnumSensorBase):
    _attr_name = "Location"
    _attr_icon = "mdi:map-marker"
    _attr_translation_key = "mower_location"
    _SNAPSHOT_FIELD = "location"
    _KEY = "mower_location"
    _attr_options = ["at_dock", "on_lawn", "at_point", "outside_known_area"]


class DreameA2PositioningHealthSensor(_SnapshotEnumSensorBase):
    _attr_name = "Positioning health"
    _attr_icon = "mdi:radar"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "positioning_health"
    _SNAPSHOT_FIELD = "positioning_health"
    _KEY = "positioning_health"
    _attr_options = ["localized", "relocating", "stuck"]


class DreameA2MqttConnectivitySensor(_SnapshotEnumSensorBase):
    _attr_name = "MQTT connectivity"
    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mqtt_connectivity"
    _SNAPSHOT_FIELD = "mqtt_connectivity"
    _KEY = "mqtt_connectivity"
    _attr_options = ["online", "stale"]


class DreameA2PickedSessionSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Exposes the picker-selected session as state + attributes.

    State = the picker label (matches the dropdown). Attributes carry
    the full summary dict built by session_card.build_picked_session_summary.
    Used by the Sessions tab's per-session detail cards.
    """

    _attr_has_entity_name = True
    _attr_name = "Picked session"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "picked_session")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        summary = self.coordinator._picked_session_summary
        return summary.get("label") if summary else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator._picked_session_summary or {}


class DreameA2Sensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed sensor entity."""

    _attr_has_entity_name = True
    entity_description: DreameA2SensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class DreameA2DiagnosticSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """A coordinator-backed diagnostic sensor.

    Reads from the coordinator directly (registry, freshness tracker,
    endpoint log) rather than from MowerState. Uses
    ``DreameA2DiagnosticSensorEntityDescription`` with ``value_fn``
    accepting a coordinator and an optional
    ``extra_state_attributes_fn``.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2DiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2DiagnosticSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.extra_state_attributes_fn
        if fn is None:
            return None
        return fn(self.coordinator)


# ---------------------------------------------------------------------------
# Task 12: cloud_state-driven sensors — OTA status + schedule count.
# These read from coordinator.cloud_state directly (not MowerState).
# ---------------------------------------------------------------------------


class DreameA2OtaStatusSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Cloud-reported OTA upgrade status."""

    _attr_has_entity_name = True
    _attr_translation_key = "ota_status"
    _attr_name = "OTA status"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "ota_status")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> str | int | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None or cs.ota_status is None:
            return None
        return cs.ota_status[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None or cs.ota_status is None:
            return {}
        return {"percent": cs.ota_status[1]}


class DreameA2ScheduleCountSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Number of cloud-side schedule slots."""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule_count"
    _attr_name = "Schedule count"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "schedule_count")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> int | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        return len(cs.schedule.slots)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return {}
        return {
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "name": s.name,
                    "plans": [
                        {
                            "time": _fmt_hhmm(p.time_min),
                            "days": _fmt_weekdays(p.weekday_mask),
                            "action": _fmt_action(p.action_type),
                            "zone_id": p.zone_id,
                        }
                        for p in s.plans
                    ],
                }
                for s in cs.schedule.slots
            ],
            "version": cs.schedule.version,
        }


class DreameA2WifiRefreshStatusSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Timestamp of the last WiFi archive refresh attempt.

    State is the unix timestamp (as datetime) of the last
    ``coordinator.refresh_wifi_archive`` invocation — typically when
    the user pressed the Refresh button. HA renders this as
    "X minutes ago" in the UI via ``SensorDeviceClass.TIMESTAMP``.

    ``extra_state_attributes`` exposes the per-refresh detail
    (`result`, `fetched`, `new`) for users who want to dig in.
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi map last refresh"
    _attr_icon = "mdi:wifi-refresh"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_refresh_status")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> datetime | None:
        status = getattr(self.coordinator, "_wifi_archive_last_refresh", {})
        ts = status.get("last_attempt_unix")
        if not isinstance(ts, (int, float)) or ts <= 0:
            return None
        return datetime.fromtimestamp(int(ts), tz=UTC)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = getattr(self.coordinator, "_wifi_archive_last_refresh", {})
        # Exclude `last_attempt_unix` from attributes — it's already the state.
        return {k: v for k, v in status.items() if k != "last_attempt_unix"}


class DreameA2WifiHeatmapAgeSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Age (in seconds) of the newest archived WiFi heatmap (v1.0.10a6+).

    State is the elapsed time between *now* and the parsed ``unix_ts``
    of the newest entry in ``coordinator._wifi_archive_index``. Unknown
    when the archive is empty.

    Use case: surface "heatmap is X hours old" so users can spot when
    the cloud's nightly auto-generation has stalled (typically because
    the mower hasn't been online recently).

    Returns ``None`` when the archive is empty or when the newest
    entry has an unparsed timestamp (``unix_ts == 0``).
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi heatmap age"
    _attr_icon = "mdi:wifi-cog"
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_heatmap_age")
        self._attr_device_info = mower_device_info(coordinator)

    def _newest_unix_ts(self) -> int | None:
        idx = getattr(self.coordinator, "_wifi_archive_index", None) or []
        if not idx:
            return None
        try:
            newest = max(int(e.unix_ts) for e in idx if int(e.unix_ts) > 0)
        except ValueError:
            return None
        return newest

    @property
    def native_value(self) -> int | None:
        newest = self._newest_unix_ts()
        if newest is None:
            return None
        import time as _time
        now_ts = int(_time.time())
        age = now_ts - newest
        return age if age >= 0 else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        newest = self._newest_unix_ts()
        if newest is None:
            return {}
        return {
            "newest_unix_ts": newest,
            "newest_iso": datetime.fromtimestamp(newest, tz=UTC).isoformat(),
            "archive_total": len(
                getattr(self.coordinator, "_wifi_archive_index", []) or []
            ),
        }


class DreameA2LastNotificationSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Most recent app-style notification synthesized from s2p2 transitions.

    Sticks at the last emitted value; never auto-clears. Shows the
    human-readable text with code + event_type as extra attributes.
    Source: coordinator._last_notification (updated by _fire_alert).
    """

    _attr_has_entity_name = True
    _attr_name = "Last notification"
    _attr_icon = "mdi:bell-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "last_notification")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> str | None:
        entry = getattr(self.coordinator, "_last_notification", None)
        if not entry:
            return None
        return entry.get("text")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = getattr(self.coordinator, "_last_notification", None)
        if not entry:
            return {}
        return {
            "event_type": entry.get("event_type"),
            "code": entry.get("code"),
            "fired_at": entry.get("fired_at"),
        }


class DreameA2ApiEndpointSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Cloud API endpoint host:port the integration is talking to."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "API endpoint"
    _attr_translation_key = "api_endpoint"
    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "api_endpoint")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        cloud = getattr(self.coordinator, "_cloud", None)
        if cloud is None:
            return None
        host = getattr(cloud, "host", None) or "eu.iot.dreame.tech"
        return f"{host}:19973"


class DreameA2IntegrationVersionSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Currently-running integration version, sourced from manifest.json."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Integration version"
    _attr_translation_key = "integration_version"
    _attr_icon = "mdi:package-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "integration_version")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        return _manifest_version()
