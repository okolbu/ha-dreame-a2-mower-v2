"""Select platform — action_mode picker and enum settings for the Dreame A2 Mower.

F3.2.1: DreameA2ActionModeSelect — user's mode selection (All-areas / Edge /
        Zone / Spot). Preserved as-is.

F4.6.3: DreameA2SettingSelect — generic select for enum-style CFG settings.

Settable selects (write via coordinator.write_setting):
  - select.mowing_efficiency → CFG.PRE[1] (0=Standard, 1=Efficient)
      PRE wire on g2408 is list(2) [zone_id, mode].  set_pre() in
      protocol/cfg_action.py requires at least 10 elements, so the write
      path pads the array to 10 elements using safe observed defaults for
      indices 2..9 (0 / False).  Only indices [0] (pre_zone_id) and [1]
      (mode) are guaranteed to be correct; the remaining elements may not
      exist on g2408's firmware and will be trimmed server-side.

  - select.rain_protection_resume_hours → CFG.WRP[1] (resume_hours int)
      WRP wire is list(2) [enabled, resume_hours].  Both fields are stored
      in MowerState (rain_protection_enabled, rain_protection_resume_hours),
      so full reconstruction is safe.  The enabled bit is read from the
      current MowerState.  0 = "Do not resume after rain".

Read-only selects (no confirmed write path in F4):
  - select.language → CFG.LANG (language indices as text=N,voice=N string)
      LANG write path not confirmed on g2408.  The options set is also
      device-specific (language pack depends on firmware locale bundle).
      Shipped read-only; expose the raw language_code string as the
      current option (or None if language_code is None).

Implementation is split across sibling modules:
  - _select_base.py:          DreameA2SettingsSelectDescription + _DreameA2DynamicTargetSelect
  - select_global.py:         Device-level entities + SETTING_SELECTS table + helpers
  - select_map_settings.py:   Per-map entities
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator

# Global (device-level) entities and table
from .select_global import (
    DreameA2ActionModeSelect,
    DreameA2SettingSelect,
    DreameA2WorkLogSelect,
    DreameA2LidarArchiveSelect,
    DreameA2ActiveMapSelect,
    DreameA2WifiArchiveSelect,
    SETTING_SELECTS,
)

# Per-map entities
from .select_map_settings import (
    DreameA2ZoneSelect,
    DreameA2SpotSelect,
    DreameA2EdgeSelect,
    DreameA2MowingModeSelect,
    DreameA2PerMapMowingDirectionSelect,
    DreameA2PerMapMowingDirectionModeSelect,
    DreameA2MapMowingEfficiencySelect,
    DreameA2PerMapEdgeMowingWalkModeSelect,
)

# ---------------------------------------------------------------------------
# backward-compat re-exports for tests
# Tests import these helpers directly from the select module
# (see tests/integration/test_entity_builders.py).
# ---------------------------------------------------------------------------
from .select_global import (
    _PRE_PAD_DEFAULTS,
    _build_pre_efficiency,
    _build_wrp_resume_hours,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = [DreameA2ActionModeSelect(coordinator)]
    entities.extend(
        DreameA2SettingSelect(coordinator, desc) for desc in SETTING_SELECTS
    )
    entities.append(DreameA2WorkLogSelect(coordinator))
    entities.append(DreameA2LidarArchiveSelect(coordinator))
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.extend([
            DreameA2MowingModeSelect(coordinator, map_id=map_id),
            DreameA2ZoneSelect(coordinator, map_id=map_id),
            DreameA2SpotSelect(coordinator, map_id=map_id),
            DreameA2EdgeSelect(coordinator, map_id=map_id),
        ])
    entities.append(DreameA2ActiveMapSelect(coordinator))
    # Per-map SETTINGS selects (v1.0.10a7 — migrated from mower-scoped).
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.extend([
            DreameA2PerMapMowingDirectionSelect(coordinator, map_id=map_id),
            DreameA2PerMapMowingDirectionModeSelect(coordinator, map_id=map_id),
            DreameA2PerMapEdgeMowingWalkModeSelect(coordinator, map_id=map_id),
            DreameA2MapMowingEfficiencySelect(coordinator, map_id=map_id),
        ])
    entities.append(DreameA2WifiArchiveSelect(coordinator))
    async_add_entities(entities)
