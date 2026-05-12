"""Entity-registry migration v1 -> v2: SN-based unique_ids.

Rewrites unique_ids from `{entry_id}_*` (and `{entry_id}_map_{N}_*`) to
`{stable_id}_*` (and `{stable_id}_map_{N}_*`). Stable id is the hardware
SN when available, falling back to mac then entry_id.

The rewrite map is built per task as entities are migrated to their new
shapes. Unmapped legacy entities are surfaced via persistent_notification
for manual cleanup via WS `config/entity_registry/remove`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Run unique_id rewrites and bump entry version."""
    if entry.version >= 2:
        return True

    _LOGGER.info(
        "%s: migrating config entry %s from v%d to v2 (SN-based unique_ids)",
        DOMAIN, entry.entry_id, entry.version,
    )

    rewrites = _collect_rewrites(hass, entry)
    if not rewrites:
        # SN not yet known (coordinator may not have done first_refresh).
        # Defer: do nothing, let setup proceed, retry post-refresh.
        _LOGGER.info(
            "%s: migration deferred until SN is known", DOMAIN,
        )
        return True

    rewritten, orphans = await _apply_rewrites(hass, entry, rewrites)

    if orphans:
        await _notify_orphans(hass, entry, orphans)

    hass.config_entries.async_update_entry(entry, version=2)
    _LOGGER.info(
        "%s: migration complete: %d entities rewritten, %d orphans",
        DOMAIN, len(rewritten), len(orphans),
    )
    return True


# Mower-level entity keys (stay on the mower device, just re-keyed from
# {entry_id}_{key} to {sn}_{key}).  Entities listed here live on the
# single mower device.  Per-map entities migrate in Tasks 6-13 and are
# NOT in this list (their migration mappings are added when they move).
#
# Exclusions from this list (handled by later tasks):
#   - zone_target, spot_target, edge_target              (T6)
#   - schedule / schedule_*                              (T7)
#   - settings_edge_mowing_auto/safe/obstacle_avoidance,
#     settings_obstacle_avoidance_enabled,
#     ai_recognition_humans/animals/objects              (T8)
#   - map_{id}  (per-map snapshot cameras)               (T9)
#   - wifi_map, request_wifi_map                         (T11) ✓ done
#   - lidar_top_down, lidar_top_down_full  (T13) ✓ done (per-map; see _collect_rewrites)
_MOWER_LEVEL_KEYS: tuple[str, ...] = (
    # ---- binary_sensor.py: DreameA2BinarySensor ---------------------------
    "obstacle_detected",
    "rain_protection_active",
    "positioning_failed",
    "failed_to_return_to_station",
    "battery_temp_low",
    "mowing_session_active",
    "drop_tilt",
    "bumper",
    "lift",
    "emergency_stop",
    "safety_alert_active",
    "top_cover_open",
    "mower_in_dock",
    "dock_in_lawn_region",
    "wheel_bind_active",
    "edgemaster",
    "photo_consent",
    # ---- button.py: _DreameA2ActionButton + others -------------------------
    "start_mowing",
    "pause_mowing",
    "stop_mowing",
    "recharge",
    "find_bot",
    "lock_bot",
    "generate_3d_map",
    # request_wifi_map is now per-map (T11) — migrated in _collect_rewrites below.
    "finalize_session",
    "refresh_cloud_state",
    # ---- camera.py: DreameA2MapCamera, DreameA2WorkLogCamera ---------------
    "map",
    # DreameA2WorkLogCamera (camera) AND DreameA2WorkLogSelect (select)
    # share this key — HA's entity registry scopes uniqueness per platform
    # so the same unique_id key is fine on different platforms.
    "work_log",
    # ---- device_tracker.py: DreameA2GPSTracker -----------------------------
    "gps",
    # ---- event.py: lifecycle + alert ---------------------------------------
    "lifecycle",
    "alert",
    # ---- lawn_mower.py: DreameA2Mower --------------------------------------
    "lawn_mower",
    # ---- select.py: mower-level selects ------------------------------------
    "action_mode",
    "mowing_efficiency",
    "navigation_path",
    "rain_protection_resume_hours",
    "language",
    "lcd_language",
    "voice_language",
    "active_map",    # DreameA2ActiveMapSelect
    "settings_mowing_direction",
    "settings_mowing_direction_mode",
    "settings_edge_mowing_walk_mode",
    # ---- sensor.py: DreameA2Sensor (all descriptor keys) -------------------
    "battery_level",
    "charging_status",
    "position_x_m",
    "position_y_m",
    "position_north_m",
    "position_east_m",
    "area_mowed_m2",
    "session_distance_m",
    "mowing_phase",
    "error_code",
    "error_description",
    "task_state_code",
    "slam_task_label",
    "total_lawn_area_m2",
    "wifi_rssi_dbm",
    "wifi_ssid",
    "wifi_ip",
    "dock_x_mm",
    "dock_y_mm",
    "dock_yaw",
    "blades_life_pct",
    "cleaning_brush_life_pct",
    "robot_maintenance_life_pct",
    "total_mowing_time_min",
    "total_mowed_area_m2",
    "mowing_count",
    "first_mowing_date",
    "active_selection",
    "last_settings_change_unix",
    "language_text_idx",
    "language_voice_idx",
    "s5p104_raw",
    "s5p105_raw",
    "s5p106_raw",
    "s5p107_raw",
    "s6p1_raw",
    "latest_session_area_m2",
    "latest_session_duration_min",
    "latest_session_unix_ts",
    "archived_session_count",
    # ---- sensor.py: DreameA2DiagnosticSensor --------------------------------
    "lidar_archive_count",
    "session_track_point_count",
    "novel_observations",
    "data_freshness",
    "api_endpoints_supported",
    "hardware_serial",
    "firmware_version_dev",
    "ota_capable_raw",
    "cloud_device_id",
    "mac_address",
    # ---- sensor.py: cloud_state-driven sensors -----------------------------
    "ota_status",
    "schedule_count",
    # ---- switch.py: DreameA2Switch (CFG-backed) ----------------------------
    "child_lock",
    "dnd",
    "rain_protection",
    "low_speed_at_night",
    "custom_charging_period",
    "anti_theft_lift_alarm",
    "anti_theft_offmap_alarm",
    "anti_theft_realtime_location",
    "frost_protection",
    "auto_recharge_standby",
    "ai_obstacle_photos",
    "msg_alert_anomaly",
    "msg_alert_error",
    "msg_alert_task",
    "msg_alert_consumables",
    "voice_regular_notification",
    "voice_work_status",
    "voice_special_status",
    "voice_error_status",
    "led_period",
    "led_in_standby",
    "led_in_working",
    "led_in_charging",
    "led_in_error",
    "human_presence_alert",
    # ---- switch.py: DreameA2AiHumanDetectionSwitch (cloud_state-backed) ----
    "cloud_state_ai_human_enabled",
    # ---- number.py: DreameA2Number (CFG-backed) ----------------------------
    "volume",
    "auto_recharge_battery_pct",
    "resume_battery_pct",
    "human_presence_alert_sensitivity",
    # ---- number.py: SETTINGS-driven number entities -------------------------
    "settings_mowing_height",
    "settings_cutter_position",
    "settings_cutter_position_height",
    "settings_edge_mowing_num",
    "settings_obstacle_avoidance_height",
    "settings_obstacle_avoidance_distance",
    "settings_obstacle_avoidance_sensitivity",
    # ---- time.py: DreameA2Time (schedule/CFG time slots) --------------------
    "dnd_start_time",
    "dnd_end_time",
    "low_speed_at_night_start_time",
    "low_speed_at_night_end_time",
    "charging_start_time",
    "charging_end_time",
)


def _collect_rewrites(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Build the {old_unique_id: new_unique_id} map for mower-level entities.

    Returns an empty dict when the SN is not yet known — migration will be
    re-run in T14 after the coordinator has established the cloud connection.
    """
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    sn = getattr(coord, "sn", None) if coord else None
    if not sn:
        _LOGGER.warning(
            "%s migration: SN not yet known; deferring unique_id rewrites",
            DOMAIN,
        )
        return {}

    old_prefix = f"{entry.entry_id}_"
    rewrites: dict[str, str] = {
        f"{old_prefix}{key}": f"{sn}_{key}"
        for key in _MOWER_LEVEL_KEYS
    }

    # Per-map selects: at v1 these lived on the mower device with
    # {entry_id}_{key} unique_ids. Map them onto the new per-map shape,
    # anchored to the (then) active map so the user's first-run entity
    # survives migration.
    active_map_id = getattr(coord, "_active_map_id", None) if coord else None
    if active_map_id is not None:
        for key in ("zone_target", "spot_target", "edge_target"):
            old = f"{entry.entry_id}_{key}"
            new = f"{sn}_map_{active_map_id}_{key}"
            rewrites[old] = new

        # Per-map setting switches: at v1 only the active map's setting existed.
        # Map the old {entry_id}_{key} unique_ids to the new per-map shape.
        for key in (
            "settings_edge_mowing_auto",
            "settings_edge_mowing_safe",
            "settings_edge_mowing_obstacle_avoidance",
            "settings_obstacle_avoidance_enabled",
            "ai_recognition_humans",
            "ai_recognition_animals",
            "ai_recognition_objects",
        ):
            rewrites[f"{entry.entry_id}_{key}"] = f"{sn}_map_{active_map_id}_{key}"

        # Per-map WiFi heatmap camera + button (T11): at v1 these were
        # mower-level entities. Anchor to the active map for migration.
        rewrites[f"{entry.entry_id}_wifi_map"] = (
            f"{sn}_map_{active_map_id}_wifi_map"
        )
        rewrites[f"{entry.entry_id}_request_wifi_map"] = (
            f"{sn}_map_{active_map_id}_request_wifi_map"
        )

        # Per-map LiDAR cameras (T13): at v1 these were mower-level entities.
        # Anchor to the active map for migration.
        rewrites[f"{entry.entry_id}_lidar_top_down"] = (
            f"{sn}_map_{active_map_id}_lidar_top_down"
        )
        rewrites[f"{entry.entry_id}_lidar_top_down_full"] = (
            f"{sn}_map_{active_map_id}_lidar_top_down_full"
        )

    # Per-map snapshot cameras (T9): {entry_id}_map_{N} → {sn}_map_{N}_map
    # All known map IDs are migrated (not only the active map).
    if coord is not None:
        for map_id in getattr(coord, "_cached_maps_by_id", {}):
            rewrites[f"{entry.entry_id}_map_{map_id}"] = (
                f"{sn}_map_{map_id}_map"
            )

    return rewrites


async def _apply_rewrites(
    hass: HomeAssistant,
    entry: ConfigEntry,
    rewrites: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Apply rewrites to the entity registry.

    Returns (rewritten_entity_ids, orphan_entity_ids).
    """
    registry = er.async_get(hass)
    rewritten: list[str] = []
    orphans: list[str] = []
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue
        if entity.unique_id in rewrites:
            new = rewrites[entity.unique_id]
            try:
                registry.async_update_entity(entity.entity_id, new_unique_id=new)
                rewritten.append(entity.entity_id)
                _LOGGER.debug(
                    "%s migration: %s unique_id %r -> %r",
                    DOMAIN, entity.entity_id, entity.unique_id, new,
                )
            except ValueError:
                _LOGGER.warning(
                    "%s migration: skipping %s, new_unique_id %r already exists in registry",
                    DOMAIN, entity.entity_id, new,
                )
        elif entity.unique_id.startswith(f"{entry.entry_id}_"):
            orphans.append(entity.entity_id)
    return rewritten, orphans


async def remove_per_map_wifi_orphans(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove per-map WiFi entity orphans left by Task 8 of the wifi-heatmap plan.

    Task 8 deleted:
    - ``DreameA2RequestWifiMapButton``  → unique_id suffix ``_request_wifi_map``
    - ``DreameA2WifiMapCamera``         → unique_id suffix ``_wifi_heatmap``
      (NOT ``_wifi_heatmap_selected``, which is the surviving single camera)

    On an existing HA install these entities linger as "unavailable" in the
    entity registry until manually removed.  This function cleans them up
    automatically when called from ``async_setup_entry``.

    The suffix check uses ``str.endswith()`` (not ``in``) so that
    ``*_wifi_heatmap_selected`` is never touched.
    """
    registry = er.async_get(hass)
    orphan_suffixes = (
        "_request_wifi_map",
        "_wifi_heatmap",  # exact suffix — does NOT match _wifi_heatmap_selected
    )
    removed: list[str] = []
    for entity_entry in list(registry.entities.values()):
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        uid = entity_entry.unique_id or ""
        if any(uid.endswith(s) for s in orphan_suffixes):
            registry.async_remove(entity_entry.entity_id)
            removed.append(entity_entry.entity_id)
            _LOGGER.info(
                "%s: removed per-map WiFi orphan entity %s (unique_id=%r)",
                DOMAIN, entity_entry.entity_id, uid,
            )
    if removed:
        _LOGGER.info(
            "%s: removed %d per-map WiFi orphan entities after Task 8 cleanup",
            DOMAIN, len(removed),
        )


async def remove_double_prefix_mowing_mode_orphans(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Rename ``select.map_<N>_map_<N>_mowing_mode`` entries to single-prefix.

    P2-4 of the Plan-2 quick-wins shipped with
    ``DreameA2MowingModeSelect.__init__`` setting
    ``self._attr_name = f"{display_name} Mowing Mode"`` — combined with
    ``has_entity_name=True`` and the device's own "Map N" name, HA
    produced a slug with the device prefix doubled
    (``select.map_2_map_2_mowing_mode``). Fixed in the follow-up by
    using a static ``_attr_name = "Mowing mode"``.

    Remove-and-let-HA-regenerate was unreliable (HA re-computed the
    same doubled slug on re-registration for reasons that aren't fully
    clear — possibly cached suggested_object_id state). Instead we
    rename the registry entry directly via ``async_update_entity``;
    that survives across reloads and avoids relying on the registry
    being empty at platform-setup time. Idempotent.
    """
    import re
    registry = er.async_get(hass)
    bad_eid = re.compile(r"^(select\.)map_(\d+)_map_\d+_mowing_mode$")
    renamed: list[tuple[str, str]] = []
    for entity_entry in list(registry.entities.values()):
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        m = bad_eid.match(entity_entry.entity_id)
        if not m:
            continue
        # m.group(2) is the user-facing map index (1, 2, ...) baked into the
        # device prefix; reuse it for the corrected slug.
        new_eid = f"{m.group(1)}map_{m.group(2)}_mowing_mode"
        # Skip if the target slug is already taken (shouldn't happen, but
        # guard against renaming into a collision).
        if any(e.entity_id == new_eid for e in registry.entities.values()):
            _LOGGER.warning(
                "%s: cannot rename %s → %s (target exists)",
                DOMAIN, entity_entry.entity_id, new_eid,
            )
            continue
        try:
            registry.async_update_entity(
                entity_entry.entity_id, new_entity_id=new_eid
            )
            renamed.append((entity_entry.entity_id, new_eid))
            _LOGGER.info(
                "%s: renamed double-prefix mowing-mode orphan %s → %s",
                DOMAIN, entity_entry.entity_id, new_eid,
            )
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning(
                "%s: rename %s → %s failed: %s",
                DOMAIN, entity_entry.entity_id, new_eid, ex,
            )
    if renamed:
        _LOGGER.info(
            "%s: renamed %d double-prefix mowing-mode orphans",
            DOMAIN, len(renamed),
        )


async def _notify_orphans(
    hass: HomeAssistant,
    entry: ConfigEntry,
    orphans: list[str],
) -> None:
    """Surface unmapped legacy entities via persistent_notification."""
    title = f"{DOMAIN}: migration left orphan entities"
    message = (
        "The Dreame A2 Mower integration migrated to SN-based entity ids. "
        "The following entities have legacy ids with no mapping and should "
        "be removed manually (Settings → Devices → entity → '...' menu):\n\n"
        + "\n".join(f"- `{eid}`" for eid in orphans)
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": title,
            "message": message,
            "notification_id": f"{DOMAIN}_migration_v2_orphans",
        },
        blocking=False,
    )
