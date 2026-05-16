"""Number platform — settable numeric settings for the Dreame A2 Mower.

F4.6.1: VOL (voice volume), auto_recharge_battery_pct, resume_battery_pct
        are settable via coordinator.write_setting.

        human_presence_alert_sensitivity is read-only in F4 because the
        REC wire list has 9 elements of which only 2 are decoded into
        MowerState; the remaining 7 (standby, mowing, recharge, patrol,
        alert, photo_consent, push_min) are not stored, so a safe full-list
        reconstruction is not possible.  It will appear in the UI as a
        read-only number (entity_category=DIAGNOSTIC).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import (
    map_device_info,
    map_unique_id,
    mower_device_info,
    mower_unique_id,
)
from .const import CONF_STATION_BEARING_DEG, DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState

# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2NumberEntityDescription(NumberEntityDescription):
    """Number descriptor with typed value_fn and optional write helpers.

    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, user_entered_value).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update that coordinator.write_setting applies.
    """

    value_fn: Callable[[MowerState], float | int | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, float], Any] | None = None
    field_updates_fn: Callable[[MowerState, float], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Wire-value builders
# ---------------------------------------------------------------------------

def _build_vol(state: MowerState, value: float) -> Any:
    """VOL wire value is just an integer 0..100."""
    return int(value)


def _vol_field_updates(state: MowerState, value: float) -> dict[str, Any]:
    return {"volume_pct": int(value)}


def _build_bat_auto_recharge(state: MowerState, value: float) -> list:
    """Build the full BAT list with auto_recharge_battery_pct overridden.

    CFG.BAT = list(6) [recharge_pct, resume_pct, unknown_flag(=1),
                        custom_charging, start_min, end_min].
    Confirmed on g2408 (docs/research §6.2 + coordinator._refresh_cfg).

    All 6 fields are present in MowerState (F4.3.1), so the full list
    can be reconstructed safely.  The unknown_flag at index 2 is set to
    1 (the only observed value).
    """
    return [
        int(value),                                     # [0] recharge_pct  (new)
        int(state.resume_battery_pct or 95),            # [1] resume_pct
        1,                                              # [2] unknown_flag (always 1)
        int(state.custom_charging_enabled or False),    # [3] custom_charging
        int(state.charging_start_min or 0),             # [4] start_min
        int(state.charging_end_min or 0),               # [5] end_min
    ]


def _bat_auto_recharge_field_updates(
    state: MowerState, value: float
) -> dict[str, Any]:
    return {"auto_recharge_battery_pct": int(value)}


def _build_bat_resume(state: MowerState, value: float) -> list:
    """Build the full BAT list with resume_battery_pct overridden.

    Same shape as _build_bat_auto_recharge; only index 1 changes.
    """
    return [
        int(state.auto_recharge_battery_pct or 15),    # [0] recharge_pct
        int(value),                                     # [1] resume_pct   (new)
        1,                                              # [2] unknown_flag (always 1)
        int(state.custom_charging_enabled or False),    # [3] custom_charging
        int(state.charging_start_min or 0),             # [4] start_min
        int(state.charging_end_min or 0),               # [5] end_min
    ]


def _bat_resume_field_updates(state: MowerState, value: float) -> dict[str, Any]:
    return {"resume_battery_pct": int(value)}


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------

NUMBERS: tuple[DreameA2NumberEntityDescription, ...] = (
    # ------------------------------------------------------------------
    # Settable: VOL (CFG key — direct single-value write)
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="volume",
        name="Voice volume",
        native_min_value=0,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.volume_pct,
        cfg_key="VOL",
        build_value_fn=_build_vol,
        field_updates_fn=_vol_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[0] — auto-recharge threshold
    # Wire shape confirmed: list(6), all 6 fields in MowerState.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="auto_recharge_battery_pct",
        name="Auto-recharge battery threshold",
        native_min_value=10,
        native_max_value=25,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.auto_recharge_battery_pct,
        cfg_key="BAT",
        build_value_fn=_build_bat_auto_recharge,
        field_updates_fn=_bat_auto_recharge_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[1] — resume-after-charge threshold
    # Wire shape confirmed: list(6), all 6 fields in MowerState.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="resume_battery_pct",
        name="Resume-after-charge battery threshold",
        native_min_value=80,
        native_max_value=100,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.resume_battery_pct,
        cfg_key="BAT",
        build_value_fn=_build_bat_resume,
        field_updates_fn=_bat_resume_field_updates,
    ),

    # ------------------------------------------------------------------
    # Read-only: REC[1] — human presence alert sensitivity
    #
    # The REC wire list has 9 elements.  Only [0] (enabled) and [1]
    # (sensitivity) are decoded into MowerState.  Elements [2..8]
    # (standby, mowing, recharge, patrol, alert, photo_consent, push_min)
    # are NOT stored — so a safe full-list reconstruction is impossible.
    #
    # Shipped as read-only (DIAGNOSTIC) in F4.  Will become settable once
    # the remaining REC fields are added to MowerState in a future task.
    # ------------------------------------------------------------------
    DreameA2NumberEntityDescription(
        key="human_presence_alert_sensitivity",
        name="Human presence alert sensitivity",
        # REC[1] enum: 0=Low, 1=Medium, 2=High (per inventory.yaml id="REC",
        # decoded 2026-04-24, sample [1,1,1,1,1,1,0,1,3]; re-confirmed on
        # live g2408 2026-05-16 — app showed "Medium" while wire reported 1).
        # Was originally shipped as 0-100 % which rendered as "1% of 100%"
        # on the dashboard — fixed 2026-05-16. SelectEntity with Low/Med/High
        # labels would be more honest UX but a number-with-corrected-range
        # avoids the rename-orphan churn until the write path lands.
        native_min_value=0,
        native_max_value=2,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.human_presence_alert_sensitivity,
        # cfg_key intentionally omitted — read-only in F4
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [DreameA2Number(coordinator, desc) for desc in NUMBERS]
    entities.append(DreameA2StationBearingNumber(coordinator))
    # Per-map SETTINGS numbers (v1.0.10a7 — migrated from mower-scoped):
    #   - Each map carries its own copy of these 7 fields.
    #   - Old mower-scoped versions (DreameA2*Number subclasses below)
    #     became orphan unique_ids after this migration; users must
    #     delete them from the entity registry once on upgrade.
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.extend([
            DreameA2PerMapMowingHeightNumber(coordinator, map_id=map_id),
            DreameA2PerMapCutterPositionNumber(coordinator, map_id=map_id),
            DreameA2PerMapCutterPositionHeightNumber(coordinator, map_id=map_id),
            DreameA2PerMapEdgeMowingNumNumber(coordinator, map_id=map_id),
            DreameA2PerMapObstacleAvoidanceHeightNumber(coordinator, map_id=map_id),
            DreameA2PerMapObstacleAvoidanceDistanceNumber(coordinator, map_id=map_id),
            DreameA2PerMapObstacleAvoidanceSensitivityNumber(coordinator, map_id=map_id),
        ])
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2Number(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """A coordinator-backed number entity.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_set_native_value is called.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2NumberEntityDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the mower via the coordinator."""
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "number.%s: no write path configured (read-only in F4); "
                "ignoring set_native_value(%r)",
                desc.key,
                value,
            )
            return

        # Build the full wire value expected by the firmware.
        if desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, value)
        else:
            wire_value = value

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, value)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "number.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )


# ---------------------------------------------------------------------------
# SETTINGS-driven entities (per-map, v1.0.10a7)
#
# Each map sub-device gets its own number for these 7 fields. Reads the
# canonical per-map value from
#   cloud_state.settings.by_map_id_canonical[map_id][SETTING_FIELD]
# Writes via coordinator.write_settings(map_id=..., field=..., value=...)
# routed through the shared settings_optimistic_write helper, which also
# refreshes the MowerState mirror for any internal users.
# ---------------------------------------------------------------------------

class _PerMapSettingsNumberBase(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """Base for per-map SETTINGS-driven number entities.

    Subclasses set:
        _KEY            — entity key for unique_id + translation_key
        _SETTING_FIELD  — cloud SETTINGS field name (e.g. 'mowingHeight')
        _STATE_FIELD    — MowerState mirror field name
                          (e.g. 'settings_mowing_height')
        _NAME_SUFFIX    — entity-name suffix appended to map name
        plus the standard NumberEntity attrs (min/max/step/unit).
    """

    _KEY: str = ""
    _SETTING_FIELD: str = ""
    _STATE_FIELD: str = ""
    _NAME_SUFFIX: str = ""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_translation_key = self._KEY
        self._attr_unique_id = map_unique_id(coordinator, map_id, self._KEY)
        map_obj = coordinator._cached_maps_by_id.get(map_id)
        # has_entity_name=True + per-map device_info means HA prepends the
        # device name ("Map 1") to the entity name in the friendly_name and
        # in the auto-generated entity_id. Manually prefixing here would
        # produce a doubled "Map 1 Map 1 …" entity_id (see
        # docs/research/per-map-naming.md).
        self._attr_name = self._NAME_SUFFIX
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    @property
    def native_value(self) -> float | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        v = cs.settings.by_map_id_canonical.get(self._map_id, {}).get(
            self._SETTING_FIELD
        )
        return float(v) if v is not None else None

    @property
    def available(self) -> bool:
        if self.native_value is None:
            return False
        return super().available

    async def async_set_native_value(self, value: float) -> None:
        await _settings_optimistic_write(
            self,
            field=self._SETTING_FIELD,
            new_value=int(value),
            state_field=self._STATE_FIELD,
            map_id=self._map_id,
        )


class DreameA2PerMapMowingHeightNumber(_PerMapSettingsNumberBase):
    """Per-map mowing height (cm)."""

    _KEY = "settings_mowing_height"
    _SETTING_FIELD = "mowingHeight"
    _STATE_FIELD = "settings_mowing_height"
    _NAME_SUFFIX = "Mowing Height"
    _attr_native_min_value = 2
    _attr_native_max_value = 7
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"


class DreameA2PerMapCutterPositionNumber(_PerMapSettingsNumberBase):
    """Per-map cutter position."""

    _KEY = "settings_cutter_position"
    _SETTING_FIELD = "cutterPosition"
    _STATE_FIELD = "settings_cutter_position"
    _NAME_SUFFIX = "Cutter position"
    _attr_native_min_value = 0
    _attr_native_max_value = 3
    _attr_native_step = 1


class DreameA2PerMapCutterPositionHeightNumber(_PerMapSettingsNumberBase):
    """Per-map cutter position height (cm)."""

    _KEY = "settings_cutter_position_height"
    _SETTING_FIELD = "cutterPositionHeight"
    _STATE_FIELD = "settings_cutter_position_height"
    _NAME_SUFFIX = "Cutter height"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"


class DreameA2PerMapEdgeMowingNumNumber(_PerMapSettingsNumberBase):
    """Per-map edge passes."""

    _KEY = "settings_edge_mowing_num"
    _SETTING_FIELD = "edgeMowingNum"
    _STATE_FIELD = "settings_edge_mowing_num"
    _NAME_SUFFIX = "Edge passes"
    _attr_native_min_value = 1
    _attr_native_max_value = 3
    _attr_native_step = 1


class DreameA2PerMapObstacleAvoidanceHeightNumber(_PerMapSettingsNumberBase):
    """Per-map obstacle avoidance height (cm)."""

    _KEY = "settings_obstacle_avoidance_height"
    _SETTING_FIELD = "obstacleAvoidanceHeight"
    _STATE_FIELD = "settings_obstacle_avoidance_height"
    _NAME_SUFFIX = "Obstacle Avoidance Height"
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"


class DreameA2PerMapObstacleAvoidanceDistanceNumber(_PerMapSettingsNumberBase):
    """Per-map obstacle avoidance distance (cm)."""

    _KEY = "settings_obstacle_avoidance_distance"
    _SETTING_FIELD = "obstacleAvoidanceDistance"
    _STATE_FIELD = "settings_obstacle_avoidance_distance"
    _NAME_SUFFIX = "Obstacle Avoidance Distance"
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "cm"


class DreameA2PerMapObstacleAvoidanceSensitivityNumber(_PerMapSettingsNumberBase):
    """Per-map obstacle avoidance sensitivity."""

    _KEY = "settings_obstacle_avoidance_sensitivity"
    _SETTING_FIELD = "obstacleAvoidanceSensitivity"
    _STATE_FIELD = "settings_obstacle_avoidance_sensitivity"
    _NAME_SUFFIX = "Obstacle avoidance sensitivity"
    _attr_native_min_value = 1
    _attr_native_max_value = 3
    _attr_native_step = 1


# ---------------------------------------------------------------------------
# Config-option mirror entities (not device-backed; entry.options writeback)
# ---------------------------------------------------------------------------

class DreameA2StationBearingNumber(
    CoordinatorEntity[DreameA2MowerCoordinator], NumberEntity
):
    """User-settable compass bearing of the dock's local X axis.

    Mirrors the ``station_bearing_deg`` config-flow option for ease of
    access — same backing store (``entry.options``), so editing this
    entity OR the Configure dialog has the same effect. Writes update
    ``entry.options`` atomically via
    ``hass.config_entries.async_update_entry``.

    The bearing drives the dock-frame → compass-frame projection that
    populates ``sensor.position_north_m`` / ``sensor.position_east_m``.
    ``CFG.DOCK.yaw`` is unreliable on this firmware (drifts even when
    the dock has not physically moved), so this is a user-set value.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "station_bearing_deg"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 359
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "°"
    _attr_icon = "mdi:compass"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "station_bearing_deg")
        self._attr_device_info = mower_device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        """Read from entry.options via the coordinator's helper property.

        Falls back to 0.0 when unset so the entity always has a concrete
        value (the config-flow default is also 0).
        """
        val = self.coordinator.station_bearing_deg
        return float(val) if val is not None else 0.0

    async def async_set_native_value(self, value: float) -> None:
        """Persist new bearing to entry.options and refresh entity state.

        Also re-projects N/E from the current snapshot x/y so the
        ``sensor.position_north_m`` / ``sensor.position_east_m`` entities
        update immediately, without waiting for the next s1p4 frame. The
        mower can sit idle at the dock for hours, so deferring the
        re-projection until the next telemetry frame leaves N/E stale.
        """
        new_options = dict(self.coordinator.entry.options)
        new_options[CONF_STATION_BEARING_DEG] = int(value)
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry,
            options=new_options,
        )
        # entry.options is updated synchronously; next read of
        # coord.station_bearing_deg sees the new value.

        # Re-project N/E using the new bearing and the current x/y so the
        # compass-frame sensors update immediately. handle_position skips
        # fields whose value is unchanged, so feeding x/y at their current
        # value is a no-op for those fields but still propagates the new
        # north_m / east_m.
        from .coordinator import _project_north_east  # local: avoid cycle
        sm = self.coordinator.state_machine
        snap = sm.snapshot()
        if snap.position_x_m is not None and snap.position_y_m is not None:
            north_m, east_m = _project_north_east(
                snap.position_x_m, snap.position_y_m, float(value),
            )
            import time as _time
            sm.handle_position(
                x_m=snap.position_x_m,
                y_m=snap.position_y_m,
                north_m=north_m,
                east_m=east_m,
                now_unix=int(_time.time()),
            )

        # Push the state update so HA reflects the change immediately.
        self.async_write_ha_state()


# Shared optimistic-write helper. Renamed alias kept so callsites in
# this module stay unchanged.
from ._settings_writes import settings_optimistic_write as _settings_optimistic_write  # noqa: E402
