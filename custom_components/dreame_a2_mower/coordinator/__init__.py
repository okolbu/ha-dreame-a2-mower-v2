"""Coordinator package — assembled DreameA2MowerCoordinator + helpers.

Decomposed from a single-file 4997-LOC ``coordinator.py`` 2026-05-15.
See spec ``docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md``
and plan ``docs/superpowers/plans/2026-05-15-coordinator-decomposition.md``.

External callers continue to use ``from .coordinator import …``; the
package re-exports the same public surface as the old module.

Per-mixin file map (see CLAUDE.md § Coordinator structure):

- ``_core.py``           — __init__, _async_update_data, properties
- ``_property_apply.py`` — module-level helpers + (siid, piid)-to-state
- ``_refreshers.py``     — all cloud refresh cycles
- ``_cloud_state.py``    — cloud_state apply + map fetch/persist
- ``_mqtt_handlers.py``  — MQTT message routing + state transitions
- ``_writes.py``         — settings + action writes
- ``_session.py``        — finalize + persist + replay
- ``_rendering.py``      — live-map render + obstacle overlay
- ``_lidar_oss.py``      — LiDAR archive + OSS fetch
- ``_device_sync.py``    — registry sync + lifecycle events
- ``_wifi_archive.py``   — WiFi heatmap archive
"""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..mower.state import MowerState
from ._cloud_state import _CloudStateMixin
from ._core import _CoreMixin
from ._device_sync import _DeviceSyncMixin
from ._lidar_oss import _LidarOssMixin
from ._mqtt_handlers import _MqttHandlersMixin
from ._property_apply import (
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_NOTIFICATION_MAP,
    _project_north_east,
    apply_property_to_state,
)
from ._refreshers import _RefreshersMixin
from ._rendering import _RenderingMixin
from ._session import _SessionMixin
from ._wifi_archive import _WifiArchiveMixin
from ._writes import _WritesMixin


class DreameA2MowerCoordinator(
    _CoreMixin,
    _RefreshersMixin,
    _CloudStateMixin,
    _MqttHandlersMixin,
    _WritesMixin,
    _SessionMixin,
    _RenderingMixin,
    _LidarOssMixin,
    _DeviceSyncMixin,
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    """Coordinates MQTT + cloud clients and the typed MowerState.

    Per spec §3 layer 3. The class body is assembled from per-concern
    mixins (see module map above). Only ``_CoreMixin`` owns ``__init__``;
    every other mixin is a pure method container.
    """


__all__ = [
    "DreameA2MowerCoordinator",
    "apply_property_to_state",
    "_BLOB_SLOTS",
    "_SUPPRESSED_SLOTS",
    "S2P2_NOTIFICATION_MAP",
    "_project_north_east",
]
