"""Per-map select entities for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a select platform.  It is imported by select.py (the real
platform entry).

Contains:
  - DreameA2ZoneSelect              (per-map, uses map_device_info)
  - DreameA2SpotSelect              (per-map, uses map_device_info)
  - DreameA2EdgeSelect              (per-map, uses map_device_info)
  - DreameA2MowingModeSelect        (per-map, uses map_device_info)
  - DreameA2PerMapMowingDirectionSelect       (per-map, uses map_device_info)
  - DreameA2PerMapMowingDirectionModeSelect   (per-map, uses map_device_info)
  - DreameA2MapMowingEfficiencySelect         (per-map, uses map_device_info)
  - DreameA2PerMapEdgeMowingWalkModeSelect    (per-map, uses map_device_info)
"""
from __future__ import annotations

import dataclasses
from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id
from ._settings_writes import (
    settings_optimistic_write as _settings_select_optimistic_write,
)
from .const import LOGGER
from .coordinator import DreameA2MowerCoordinator
from ._select_base import _DreameA2DynamicTargetSelect


# ---------------------------------------------------------------------------
# v1.0.0a26: Zone / Spot pickers — dynamic options sourced from the cloud
# map. Setting one writes to active_selection_zones/spots so subsequent
# start_mowing dispatches use the picked target. Multi-pick is exposed as
# the start_zone_mowing / start_spot_mowing services.
# ---------------------------------------------------------------------------


class DreameA2ZoneSelect(_DreameA2DynamicTargetSelect):
    """Pick which mowing zone the next zone-mode start_mowing targets."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        # has_entity_name=True; device_name is prepended automatically.
        super().__init__(coordinator, "zone_target", "Zone", "mdi:grass", map_id=map_id)

    def _entries(self) -> list[tuple[int, str]]:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        if md is None:
            return []
        return [(z.zone_id, z.name) for z in getattr(md, "mowing_zones", ())]

    def _map_loaded(self) -> bool:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        return md is not None

    def _empty_placeholder(self) -> str:
        return "(no zones on this map)"

    def _selected_ids(self) -> tuple[int, ...]:
        return self.coordinator.data.active_selection_zones

    def _set_selected_ids(self, ids: tuple[int, ...]) -> None:
        new_state = dataclasses.replace(self.coordinator.data, active_selection_zones=ids)
        self.coordinator.async_set_updated_data(new_state)


class DreameA2SpotSelect(_DreameA2DynamicTargetSelect):
    """Pick which spot zone the next spot-mode start_mowing targets."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        # has_entity_name=True; device_name is prepended automatically.
        super().__init__(coordinator, "spot_target", "Spot", "mdi:target", map_id=map_id)

    def _entries(self) -> list[tuple[int, str]]:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        if md is None:
            return []
        return [(s.spot_id, s.name) for s in getattr(md, "spot_zones", ())]

    def _map_loaded(self) -> bool:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        return md is not None

    def _empty_placeholder(self) -> str:
        return "(no spots on this map)"

    def _selected_ids(self) -> tuple[int, ...]:
        return self.coordinator.data.active_selection_spots

    def _set_selected_ids(self, ids: tuple[int, ...]) -> None:
        new_state = dataclasses.replace(self.coordinator.data, active_selection_spots=ids)
        self.coordinator.async_set_updated_data(new_state)


class DreameA2EdgeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity, RestoreEntity
):
    """Pick which contour(s) the next edge-mode start_mowing targets.

    Demoted to DIAGNOSTIC so it doesn't crowd the default dashboard;
    the unified DreameA2MowingModeSelect is the user-facing entry point.

    Distinct from the Zone picker: contours are keyed by 2-int composite
    IDs in the cloud's ``MAP.*.contours.value`` table (see
    ``map_decoder.MapData.available_contour_ids``), not by the scalar
    zone IDs the Zone picker uses. On the user's single-merged-zone
    lawn the table contains the outer perimeter ``[1, 0]`` plus
    ``[1, 1]``, ``[1, 2]`` etc. for invisible sub-zone seams from
    successive mapping sessions; passing those seam contours to the
    firmware's edge-mow planner causes it to trace internal seams and
    drain the budget on irrelevant work, hence the 2026-05-05 FTRTS bug.

    Default option: ``"All perimeters"`` — passes the full list of
    every outer-perimeter contour (entries with second-int = 0). This
    matches the Dreame app's "Edge" button on a single-zone lawn and
    is the multi-zone-correct generalisation. Advanced users can pick
    a single-zone perimeter if multi-zone, or use the
    ``mow_edge`` service with explicit ``contour_ids`` to target seams.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:vector-polyline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _ALL_LABEL = "All perimeters"
    _PLACEHOLDER_NO_MAP = "(no map yet)"
    _PLACEHOLDER_NO_EDGES = "(no edges on this map)"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "edge_target")
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Edge"
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)
        # Each label resolves to a tuple of `(map_id, contour_index)` pairs.
        # _ALL_LABEL maps to "every (N, 0)"; per-zone labels map to a single pair.
        self._label_to_contours: dict[str, tuple[tuple[int, int], ...]] = {}
        self._attr_options: list[str] = [self._PLACEHOLDER_NO_MAP]
        self._attr_current_option: str | None = self._PLACEHOLDER_NO_MAP

    def _map_loaded(self) -> bool:
        """Return True if map data is available, False if still loading."""
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        return md is not None

    def _outer_contour_ids(self) -> tuple[tuple[int, int], ...]:
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        avail = getattr(md, "available_contour_ids", ()) if md is not None else ()
        return tuple(cid for cid in avail if len(cid) == 2 and cid[1] == 0)

    def _zone_name_for_contour(self, cid: tuple[int, int]) -> str | None:
        """Look up a human-readable zone name for the given contour ID.

        Contours and mowing-zones are independently keyed in the cloud
        map data, but the contour's first int (`cid[0]`) corresponds to
        the zone-region the perimeter belongs to. Return the matching
        zone's name from `MapData.mowing_zones` if present, else None.
        """
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        if md is None:
            return None
        for zone in getattr(md, "mowing_zones", ()) or ():
            if int(getattr(zone, "zone_id", -1)) == int(cid[0]):
                name = getattr(zone, "name", "") or ""
                return name.strip() or None
        return None

    def _build_labels(self) -> dict[str, tuple[tuple[int, int], ...]]:
        outers = self._outer_contour_ids()
        labels: dict[str, tuple[tuple[int, int], ...]] = {}
        if not outers:
            return labels
        if len(outers) == 1:
            # Single-zone lawn: just one option, no need for the "All"
            # wrapper. Append the zone's cloud-supplied name when present
            # ("Perimeter Zone1") so users see what their app shows them.
            cid = outers[0]
            zone_name = self._zone_name_for_contour(cid)
            label = f"Perimeter {zone_name}" if zone_name else "Perimeter"
            labels[label] = outers
            return labels
        # Multi-zone: "All perimeters" plus per-zone entries.
        labels[self._ALL_LABEL] = outers
        for cid in outers:
            zone_name = self._zone_name_for_contour(cid)
            if zone_name:
                labels[f"{zone_name} perimeter"] = (cid,)
            else:
                labels[f"Zone {cid[0]} perimeter"] = (cid,)
        return labels

    def _refresh(self) -> None:
        labels = self._build_labels()
        if not labels:
            # Distinguish "map not loaded" from "map loaded but no edges"
            placeholder = (
                self._PLACEHOLDER_NO_EDGES if self._map_loaded()
                else self._PLACEHOLDER_NO_MAP
            )
            self._attr_options = [placeholder]
            self._attr_current_option = placeholder
            self._label_to_contours = {}
            return

        opts = list(labels.keys())
        sel = tuple(self.coordinator.data.active_selection_edge_contours)

        # Reflect the saved selection into the dropdown if it's still
        # valid; otherwise auto-commit the first option (matches the
        # Zone/Spot picker's "what's shown is what Start mows" rule).
        chosen_label: str | None = None
        for label, contours in labels.items():
            if contours == sel:
                chosen_label = label
                break

        if chosen_label is None:
            chosen_label = opts[0]
            self._set_selected_contours(labels[chosen_label])

        self._attr_options = opts
        self._attr_current_option = chosen_label
        self._label_to_contours = labels

    def _set_selected_contours(
        self, contours: tuple[tuple[int, int], ...]
    ) -> None:
        new_state = dataclasses.replace(
            self.coordinator.data, active_selection_edge_contours=contours
        )
        self.coordinator.async_set_updated_data(new_state)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "",
            "unknown",
            "unavailable",
            self._PLACEHOLDER_NO_MAP,
            self._PLACEHOLDER_NO_EDGES,
        ):
            # Stash the restored label; _refresh will resolve it against
            # the current map's available contours.
            self._attr_current_option = last_state.state
        self._refresh()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self._refresh()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        contours = self._label_to_contours.get(option)
        if contours is None:
            LOGGER.warning(
                "select.edge_target: unknown option %r — ignoring (available: %s)",
                option,
                list(self._label_to_contours.keys()),
            )
            return
        self._set_selected_contours(contours)
        self._attr_current_option = option
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# P2-4: Unified per-map mowing-mode picker
# ---------------------------------------------------------------------------


class DreameA2MowingModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """One picker to start any mowing mode on a given map.

    Options:
    - "All areas"     → coordinator.start_mowing_all_areas(map_id=…)
    - "Edge"          → coordinator.start_mowing_edge(map_id=…)
    - "Zone: <name>"  → coordinator.start_mowing_zone(map_id=…, zone_id=…)
    - "Spot: <name>"  → coordinator.start_mowing_spot(map_id=…, spot_id=…)
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:mower"
    _attr_name = "Mowing mode"

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_unique_id = map_unique_id(coordinator, map_id, "mowing_mode")
        # _attr_name is the static class attribute "Mowing mode". HA's
        # has_entity_name=True prepends the device name (e.g. "Map 2")
        # to produce friendly_name "Map 2 Mowing mode" → slug
        # `select.map_2_mowing_mode`. Setting `_attr_name = f"{display_name} …"`
        # here would cause the device prefix to be doubled into the slug.
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)
        self._attr_current_option: str | None = "All areas"
        # Populated once by _build_options / options property.
        self._option_to_action: dict[str, tuple[str, int | None]] = {}
        self._attr_options: list[str] = self._build_options()

    def _build_options(self) -> list[str]:
        """Rebuild the option list from current map data."""
        md = self.coordinator.cloud_state.maps_by_id.get(self._map_id)
        opts: list[str] = ["All areas", "Edge"]
        self._option_to_action = {
            "All areas": ("all_areas", None),
            "Edge": ("edge", None),
        }
        for zone in getattr(md, "mowing_zones", ()) or ():
            label = f"Zone: {zone.name}"
            opts.append(label)
            self._option_to_action[label] = ("zone", int(zone.zone_id))
        for spot in getattr(md, "spot_zones", ()) or ():
            label = f"Spot: {spot.name}"
            opts.append(label)
            self._option_to_action[label] = ("spot", int(spot.spot_id))
        return opts

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self._attr_options = self._build_options()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        action = self._option_to_action.get(option)
        if action is None:
            LOGGER.warning(
                "select.mowing_mode: unknown option %r — ignoring", option
            )
            return
        kind, target_id = action
        if kind == "all_areas":
            await self.coordinator.start_mowing_all_areas(map_id=self._map_id)
        elif kind == "edge":
            await self.coordinator.start_mowing_edge(map_id=self._map_id)
        elif kind == "zone":
            await self.coordinator.start_mowing_zone(
                map_id=self._map_id, zone_id=target_id
            )
        elif kind == "spot":
            await self.coordinator.start_mowing_spot(
                map_id=self._map_id, spot_id=target_id
            )
        self._attr_current_option = option
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Task 12: SETTINGS-driven selects — mowing direction, direction mode,
#          edge walk mode.  All three read from coordinator.data (MowerState
#          fields populated by the SETTINGS decoder) and write via
#          coordinator._write_setting_placeholder.
# ---------------------------------------------------------------------------


class DreameA2PerMapMowingDirectionSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Per-map mowing direction (degrees)."""

    _OPTIONS = ("0°", "90°", "180°", "270°")

    _attr_has_entity_name = True
    _attr_translation_key = "settings_mowing_direction"
    _attr_options: ClassVar[list[str]] = list(_OPTIONS)
    _attr_should_poll = False

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "settings_mowing_direction"
        )
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Mowing Direction"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    @property
    def current_option(self) -> str | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        v = cs.settings.by_map_id_canonical.get(self._map_id, {}).get(
            "mowingDirection"
        )
        if v is None:
            return None
        try:
            return self._OPTIONS[int(v) // 90]
        except (IndexError, TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        if self.current_option is None:
            return False
        return super().available

    async def async_select_option(self, option: str) -> None:
        try:
            idx = self._OPTIONS.index(option)
        except ValueError:
            return
        await _settings_select_optimistic_write(
            self, field="mowingDirection", new_value=idx * 90,
            state_field="settings_mowing_direction",
            map_id=self._map_id,
        )


class DreameA2PerMapMowingDirectionModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Per-map mowing pattern — Striped / Crisscross / Chequerboard."""

    _OPTIONS = ("Striped", "Crisscross", "Chequerboard")

    _attr_has_entity_name = True
    _attr_translation_key = "mowing_pattern"
    _attr_options: ClassVar[list[str]] = list(_OPTIONS)
    _attr_should_poll = False

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "settings_mowing_direction_mode"
        )
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Mowing Pattern"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    @property
    def current_option(self) -> str | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        v = cs.settings.by_map_id_canonical.get(self._map_id, {}).get(
            "mowingDirectionMode"
        )
        if v is None:
            return None
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None
        return self._OPTIONS[iv] if 0 <= iv < len(self._OPTIONS) else None

    @property
    def available(self) -> bool:
        if self.current_option is None:
            return False
        return super().available

    async def async_select_option(self, option: str) -> None:
        if option not in self._OPTIONS:
            return
        idx = self._OPTIONS.index(option)
        await _settings_select_optimistic_write(
            self, field="mowingDirectionMode", new_value=idx,
            state_field="settings_mowing_direction_mode",
            map_id=self._map_id,
        )


class DreameA2MapMowingEfficiencySelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Per-map mowing efficiency — read-only.

    Symmetric to ``DreameA2MapEdgemasterSwitch``. Reads from the s6.2
    PRE shadow (``state_machine.snapshot().pre_shadow_by_map_id[map_id]
    ["mowing_efficiency"]``). Each s6.2 push from the device is tagged
    with the active map_id at push time, so this entity converges
    per-map as the user saves Mowing-Settings in the Dreame app on
    each map. Unavailable until the first save on that map has been
    observed since install.

    No working device-write surface for Mowing Efficiency has been
    identified on g2408 firmware (PRE family doesn't accept cloud
    writes — see memory ``project_g2408_iobroker_negatives``).
    async_select_option logs and no-ops; the per-map entity replaces
    the parent-level ``select.mowing_efficiency`` which had a phantom
    CFG.PRE write that silently failed on this firmware.
    """

    _OPTIONS = ("Standard", "Efficient")

    _attr_has_entity_name = True
    _attr_options: ClassVar[list[str]] = list(_OPTIONS)
    _attr_should_poll = False
    _attr_icon = "mdi:speedometer"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "mowing_efficiency"
        )
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Mowing efficiency"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    def _shadow_value(self) -> int | None:
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
        v = entry.get("mowing_efficiency")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @property
    def current_option(self) -> str | None:
        v = self._shadow_value()
        if v == 0:
            return "Standard"
        if v == 1:
            return "Efficient"
        return None

    @property
    def available(self) -> bool:
        if self.current_option is None:
            return False
        return super().available

    async def async_select_option(self, option: str) -> None:
        LOGGER.warning(
            "select.<map>_mowing_efficiency: no working device-write path "
            "on g2408; ignoring select_option(%r)",
            option,
        )


class DreameA2PerMapEdgeMowingWalkModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Per-map edge mowing walk mode."""

    _OPTIONS = ("walk_0", "walk_1")

    _attr_has_entity_name = True
    _attr_translation_key = "settings_edge_mowing_walk_mode"
    _attr_options: ClassVar[list[str]] = list(_OPTIONS)
    _attr_should_poll = False

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "settings_edge_mowing_walk_mode"
        )
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "Edge walk mode"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    @property
    def current_option(self) -> str | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        v = cs.settings.by_map_id_canonical.get(self._map_id, {}).get(
            "edgeMowingWalkMode"
        )
        if v is None:
            return None
        try:
            opt = f"walk_{int(v)}"
        except (TypeError, ValueError):
            return None
        return opt if opt in self._OPTIONS else None

    @property
    def available(self) -> bool:
        if self.current_option is None:
            return False
        return super().available

    async def async_select_option(self, option: str) -> None:
        if option not in self._OPTIONS:
            return
        try:
            n = int(option.split("_")[1])
        except (IndexError, ValueError):
            return
        await _settings_select_optimistic_write(
            self, field="edgeMowingWalkMode", new_value=n,
            state_field="settings_edge_mowing_walk_mode",
            map_id=self._map_id,
        )
