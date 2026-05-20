"""Per-map metadata sensor entity classes for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it directly.  It is imported by sensor.py.

Contains: DreameA2MapNameSensor, DreameA2MapAreaSensor,
DreameA2MapSegmentCountSensor, DreameA2MaintenancePointsSensor,
DreameA2ExclusionZonesSensor, DreameA2IgnoreObstacleZonesSensor,
DreameA2SpotsCountSensor, DreameA2MapPreMowingHeightSensor,
DreameA2MapPreEdgemasterSensor.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass

from ._sensor_base import (
    _DreameA2PerMapPreShadowBase,
    _DreameA2PerMapSensorBase,
)


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
# Per-map s6.2 PRE-family shadow sensors (height / edgemaster).
# ---------------------------------------------------------------------------
# The Dreame app stores these fields per-map app-side; the device
# protocol only exposes the ACTIVE map's last-pushed values via s6.2.
# We learn the per-map values over time by tagging each s6.2 push with
# the currently-active map_id (see coordinator.handle_property_push +
# state_machine.handle_pre_shadow_update). Entities below read from
# `coordinator.state_machine.snapshot().pre_shadow_by_map_id` and
# return None until the user has saved settings on that map at least
# once in the Dreame app.
#
# All are EntityCategory.DIAGNOSTIC — read-only observables with
# no write path (the device protocol doesn't accept per-map values on
# g2408 firmware). For the writable counterpart of mowing_height, see
# the per-map `number.<map>_settings_mowing_height` entity from
# v1.0.10a7. See docs/research/g2408-protocol.md § s6.2.

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
