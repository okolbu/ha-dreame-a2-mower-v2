"""Per-map session-total sensor entity classes for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it directly.  It is imported by sensor.py.

Contains: DreameA2MapSessionAreaTotalSensor, DreameA2MapSessionTimeTotalSensor,
DreameA2MapSessionCountSensor.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass

from ._sensor_base import _DreameA2PerMapSessionSensorBase


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
