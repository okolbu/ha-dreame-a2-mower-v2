"""Sensor platform for the Dreame A2 Mower.

F1: battery_level + charging_status. F2 adds the rest of §2.1's
confirmed-source sensors.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.error_codes import describe_error
from .mower.state import ChargingStatus, MowerState


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


@dataclass(frozen=True, kw_only=True)
class DreameA2SensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor with a typed value_fn."""

    value_fn: Callable[[MowerState], Any]


@dataclass(frozen=True, kw_only=True)
class DreameA2DiagnosticSensorEntityDescription(SensorEntityDescription):
    """Sensor descriptor for diagnostic entities that read coordinator state.

    Unlike ``DreameA2SensorEntityDescription`` whose ``value_fn`` takes
    a ``MowerState``, diagnostic sensors need access to the coordinator
    itself (for the registry, freshness tracker, endpoint log). The
    ``value_fn`` here takes the coordinator.
    """

    value_fn: Callable[[Any], Any]
    extra_state_attributes_fn: Callable[[Any], dict[str, Any]] | None = None


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

    # ------ Phase 2 recorder-merge safety-net sensors ------
    # These three raw-int sensors exist so HA's recorder captures
    # state/charging/error transitions. T7's merge_recorder_samples
    # reads them back to backfill in_progress.json sample streams.
    DreameA2SensorEntityDescription(
        key="state_code_raw",
        translation_key="state_code_raw",
        name="State code (raw)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.task_state_code,
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


class _SnapshotEnumSensorBase(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Common base for ENUM sensors that read an enum field from the snapshot."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _SNAPSHOT_FIELD: str = "override-me"
    _KEY: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, self._KEY)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        snap = self.coordinator.state_machine.snapshot()
        val = getattr(snap, self._SNAPSHOT_FIELD)
        return val.value if val is not None else None


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = (
        [DreameA2Sensor(coordinator, desc) for desc in SENSORS]
        + [DreameA2DiagnosticSensor(coordinator, desc) for desc in DIAGNOSTIC_SENSORS]
        + [
            DreameA2OtaStatusSensor(coordinator),
            DreameA2ScheduleCountSensor(coordinator),
            DreameA2WifiRefreshStatusSensor(coordinator),
            DreameA2WifiHeatmapAgeSensor(coordinator),
            DreameA2LastNotificationSensor(coordinator),
            DreameA2CurrentActivitySensor(coordinator),
            DreameA2LocationSensor(coordinator),
            DreameA2PositioningHealthSensor(coordinator),
            DreameA2MqttConnectivitySensor(coordinator),
            DreameA2CloudDeviceIdSensor(coordinator),
            DreameA2ApiEndpointSensor(coordinator),
            DreameA2IntegrationVersionSensor(coordinator),
            DreameA2PickedSessionSensor(coordinator),
        ]
    )
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.extend([
            DreameA2MapNameSensor(coordinator, map_id=map_id),
            DreameA2MapAreaSensor(coordinator, map_id=map_id),
            DreameA2MapSegmentCountSensor(coordinator, map_id=map_id),
            DreameA2MaintenancePointsSensor(coordinator, map_id=map_id),
            DreameA2ExclusionZonesSensor(coordinator, map_id=map_id),
            DreameA2IgnoreObstacleZonesSensor(coordinator, map_id=map_id),
            DreameA2SpotsCountSensor(coordinator, map_id=map_id),
            DreameA2MapPreMowingHeightSensor(coordinator, map_id=map_id),
            # DreameA2MapPreMowingEfficiencySensor removed 2026-05-15 —
            # superseded by select.dreame_a2_mower_map_N_mowing_efficiency
            # (DreameA2MapMowingEfficiencySelect in select.py).
            DreameA2MapPreEdgemasterSensor(coordinator, map_id=map_id),
            DreameA2MapSessionAreaTotalSensor(coordinator, map_id=map_id),
            DreameA2MapSessionTimeTotalSensor(coordinator, map_id=map_id),
            DreameA2MapSessionCountSensor(coordinator, map_id=map_id),
        ])
    async_add_entities(entities)


class _DreameA2PerMapSensorBase(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Base for per-map sensors. Subclasses set _KEY and override _compute_value."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _KEY: str = "override-me"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, self._KEY)
        map_data = coordinator._cached_maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, map_name)

    def _map(self):
        return self.coordinator._cached_maps_by_id.get(self._map_id)

    def _compute_value(self, map_data):
        raise NotImplementedError

    @property
    def native_value(self):
        m = self._map()
        if m is None:
            return None
        return self._compute_value(m)


class DreameA2MapNameSensor(_DreameA2PerMapSensorBase):
    """Sensor reporting the map name."""

    _attr_name = "Name"
    _attr_translation_key = "map_name"
    _attr_icon = "mdi:label-outline"
    _KEY = "name"

    def _compute_value(self, m):
        # Cloud frequently returns empty `name` — the Dreame app shows a
        # "Map N" default in that case. Mirror it so the dashboard isn't
        # blank. map_id is 0-based on the wire; humans count from 1.
        name = getattr(m, "name", None)
        if name:
            return name
        return f"Map {self._map_id + 1}"


class DreameA2MapAreaSensor(_DreameA2PerMapSensorBase):
    """Sensor reporting the total map area in m²."""

    _attr_name = "Area"
    _attr_translation_key = "map_area"
    _attr_icon = "mdi:vector-square"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "area"

    def _compute_value(self, m):
        return getattr(m, "total_area_m2", None)


class DreameA2MapSegmentCountSensor(_DreameA2PerMapSensorBase):
    """Sensor reporting the number of mowing segments on the map."""

    _attr_name = "Segments"
    _attr_translation_key = "map_segments"
    _attr_icon = "mdi:vector-polyline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "segments"

    def _compute_value(self, m):
        zones = getattr(m, "mowing_zones", ())
        return len(zones) if zones is not None else 0


class DreameA2MaintenancePointsSensor(_DreameA2PerMapSensorBase):
    """Per-map list of user-placed Maintenance Points.

    State is the count; `extra_state_attributes['points']` lists each
    point as ``{id, x_mm, y_mm}``. Decoded from MAP key ``cleanPoints``
    (see inventory.yaml ``map_key_cleanPoints``). Read-only; placement
    happens in the Dreame app.
    """

    _attr_name = "Maintenance points"
    _attr_translation_key = "maintenance_points"
    _attr_icon = "mdi:map-marker-radius"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "maintenance_points"

    def _compute_value(self, m):
        pts = getattr(m, "maintenance_points", None) or ()
        return len(pts)

    @property
    def extra_state_attributes(self):
        m = self._map()
        if m is None:
            return {"points": []}
        pts = getattr(m, "maintenance_points", None) or ()
        return {
            "points": [
                {
                    "id": getattr(p, "point_id", None),
                    "x_mm": getattr(p, "x_mm", None),
                    "y_mm": getattr(p, "y_mm", None),
                }
                for p in pts
            ]
        }


class DreameA2ExclusionZonesSensor(_DreameA2PerMapSensorBase):
    """Per-map count of exclusion (red / no-go) zones.

    Decoded from MAP key `forbiddenAreas`. Stored on the unified
    `MapData.exclusion_zones` tuple with `subtype is None`.
    """

    _attr_name = "Exclusion zones"
    _attr_translation_key = "exclusion_zones"
    _attr_icon = "mdi:vector-rectangle"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "exclusion_zones"

    def _compute_value(self, m):
        zones = getattr(m, "exclusion_zones", None) or ()
        return sum(1 for z in zones if getattr(z, "subtype", None) is None)


class DreameA2IgnoreObstacleZonesSensor(_DreameA2PerMapSensorBase):
    """Per-map count of Designated Ignore Obstacle (green) zones.

    Decoded from MAP key `notObsAreas`. Stored on the unified
    `MapData.exclusion_zones` tuple with `subtype == "ignore"`.
    """

    _attr_name = "Ignore-obstacle zones"
    _attr_translation_key = "ignore_obstacle_zones"
    _attr_icon = "mdi:vector-square"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "ignore_obstacle_zones"

    def _compute_value(self, m):
        zones = getattr(m, "exclusion_zones", None) or ()
        return sum(1 for z in zones if getattr(z, "subtype", None) == "ignore")


class DreameA2SpotsCountSensor(_DreameA2PerMapSensorBase):
    """Per-map count of user-defined Spot mow zones.

    Spots are individually addressable mow targets (cloud key
    ``spotAreas``); the s2.50 op=103 spot-mow task expects one or more
    spot_id integers in ``d.area``. Stored on `MapData.spot_zones` as a
    tuple of `SpotZone` entries (see map_decoder.py). Read-only —
    spot placement happens in the Dreame app.
    """

    _attr_name = "Spots"
    _attr_translation_key = "map_spots"
    _attr_icon = "mdi:map-marker-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "spots"

    def _compute_value(self, m):
        spots = getattr(m, "spot_zones", None) or ()
        return len(spots)


# ---------------------------------------------------------------------------
# Per-map s6.2 PRE-family shadow sensors (height / efficiency / edgemaster).
# ---------------------------------------------------------------------------
# The Dreame app stores these three fields per-map app-side; the device
# protocol only exposes the ACTIVE map's last-pushed values via s6.2.
# We learn the per-map values over time by tagging each s6.2 push with
# the currently-active map_id (see coordinator.handle_property_push +
# state_machine.handle_pre_shadow_update). Entities below read from
# `coordinator.state_machine.snapshot().pre_shadow_by_map_id` and
# return None until the user has saved settings on that map at least
# once in the Dreame app.
#
# All three are EntityCategory.DIAGNOSTIC — read-only observables with
# no write path (the device protocol doesn't accept per-map values on
# g2408 firmware). For the writable counterpart of mowing_height, see
# the per-map `number.<map>_settings_mowing_height` entity from
# v1.0.10a7. See docs/research/g2408-protocol.md § s6.2.

class _DreameA2PerMapPreShadowBase(_DreameA2PerMapSensorBase):
    """Base for per-map sensors that read from the state-machine PRE shadow."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _shadow_entry(self) -> dict | None:
        sm = getattr(self.coordinator, "state_machine", None)
        if sm is None:
            return None
        try:
            snap = sm.snapshot()
        except Exception:
            return None
        shadow = getattr(snap, "pre_shadow_by_map_id", None) or {}
        entry = shadow.get(self._map_id)
        if not isinstance(entry, dict):
            return None
        return entry

    @property
    def native_value(self):
        # Override the base (which reads MapData via _map()); shadow lives
        # on the snapshot, not on MapData. Returns None when the shadow
        # has no entry for this map yet (user hasn't saved settings on
        # this map since install).
        entry = self._shadow_entry()
        if entry is None:
            return None
        return self._compute_shadow_value(entry)

    def _compute_shadow_value(self, entry: dict):
        raise NotImplementedError


class DreameA2MapPreMowingHeightSensor(_DreameA2PerMapPreShadowBase):
    """Per-map shadow of last-saved mowing height (cm).

    Populated from s6.2 pushes tagged with the active map_id. Unknown
    until the user saves settings on this map in the Dreame app.
    """

    _attr_name = "PRE mowing height"
    _attr_translation_key = "map_pre_mowing_height_cm"
    _attr_icon = "mdi:ruler"
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _KEY = "pre_mowing_height_cm"

    def _compute_shadow_value(self, entry):
        # Wire value is millimetres (5 mm steps per inventory.yaml id=s6p2).
        # Use float division so half-cm app saves (e.g. 45 mm → 4.5 cm)
        # survive — earlier `int(mm) // 10` floor-divided and silently
        # truncated 4.5 cm to 4 cm. User confirmed 2026-05-17 that the
        # wire push was correctly 45 mm but the sensor showed 4.
        mm = entry.get("mowing_height_mm")
        if mm is None:
            return None
        try:
            return int(mm) / 10
        except (TypeError, ValueError):
            return None


# DreameA2MapPreMowingEfficiencySensor removed 2026-05-15 — superseded
# by ``select.dreame_a2_mower_map_N_mowing_efficiency`` (see
# ``DreameA2MapMowingEfficiencySelect`` in select.py). Both surfaced
# the same PRE-shadow value, but the new select is a proper enum
# entity rather than a string sensor.


class DreameA2MapPreEdgemasterSensor(_DreameA2PerMapPreShadowBase):
    """Per-map shadow of last-saved EdgeMaster setting.

    Populated from s6.2 pushes tagged with the active map_id. Unknown
    until the user saves settings on this map in the Dreame app.
    """

    _attr_name = "PRE EdgeMaster"
    _attr_translation_key = "map_pre_edgemaster"
    _attr_icon = "mdi:vector-square-edit"
    _KEY = "pre_edgemaster"

    def _compute_shadow_value(self, entry):
        value = entry.get("edgemaster")
        if value is None:
            return None
        return "On" if bool(value) else "Off"


class _DreameA2PerMapSessionSensorBase(_DreameA2PerMapSensorBase):
    """Per-map aggregator over the session archive index.

    Reads ``session_archive._index`` directly instead of calling the
    public ``list_sessions()`` because the latter is executor-only
    (re-reads disk via ``load_index()`` + sorts). The ``_index`` list
    is preloaded at boot and safe to read from the event loop. The
    legacy/unknown `map_id == -1` entries are naturally excluded by
    the `== self._map_id` filter (never matches a real map_id).
    """

    def _sessions_for_map(self):
        archive = getattr(self.coordinator, "session_archive", None)
        index = getattr(archive, "_index", None) or []
        return [s for s in index if getattr(s, "map_id", None) == self._map_id]


class DreameA2MapSessionAreaTotalSensor(_DreameA2PerMapSessionSensorBase):
    """Sum of mowed area (m²) across all sessions for this map."""

    _attr_name = "Total area mowed"
    _attr_translation_key = "map_session_area_total"
    _attr_icon = "mdi:vector-square"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_area_total"

    def _compute_value(self, m):
        total = 0.0
        for s in self._sessions_for_map():
            total += float(getattr(s, "area_mowed_m2", 0) or 0)
        return round(total, 1)


class DreameA2MapSessionTimeTotalSensor(_DreameA2PerMapSessionSensorBase):
    """Sum of mowing duration (minutes) across all sessions for this map."""

    _attr_name = "Total mowing time"
    _attr_translation_key = "map_session_time_total"
    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_time_total"

    def _compute_value(self, m):
        return sum(int(getattr(s, "duration_min", 0) or 0) for s in self._sessions_for_map())


class DreameA2MapSessionCountSensor(_DreameA2PerMapSessionSensorBase):
    """Number of completed mowing sessions for this map."""

    _attr_name = "Mowing sessions"
    _attr_translation_key = "map_session_count"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _KEY = "session_count"

    def _compute_value(self, m):
        return len(self._sessions_for_map())


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


class DreameA2CloudDeviceIdSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Surfaces the cloud-assigned device id (e.g. BM169439).

    HA auto-disables diagnostic entities whose native_value is None
    at first read, so return a "unknown" string rather than None when
    the cloud client isn't ready yet.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Cloud device id"
    _attr_translation_key = "cloud_device_id"
    _attr_icon = "mdi:cloud-tag"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "cloud_device_id")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        cloud = getattr(self.coordinator, "_cloud", None)
        if cloud is None:
            return "unknown"
        return getattr(cloud, "device_id", None) or "unknown"


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

    _cached_version: str | None = None

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "integration_version")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self):
        if self._cached_version is not None:
            return self._cached_version
        import json
        from pathlib import Path
        manifest = Path(__file__).parent / "manifest.json"
        try:
            data = json.loads(manifest.read_text())
            self._cached_version = str(data.get("version", "unknown"))
        except Exception:
            self._cached_version = "unknown"
        return self._cached_version
