"""Shared base classes and description dataclass for the select platform.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a select platform.  It is imported by select_global.py,
select_map_settings.py, and select.py.

Acyclic import order:
    _select_base  ←  select_global / select_map_settings  ←  select.py
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id
from .const import LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import MowerState


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DreameA2SettingsSelectDescription(SelectEntityDescription):
    """Select descriptor for enum-style CFG settings.

    ``value_fn``       — reads the current option string from MowerState,
                         or None if no observation yet.
    ``cfg_key``        — if set, the entity is writable via
                         coordinator.write_setting(cfg_key, full_value).
                         If None, the select is read-only in F4.
    ``build_value_fn`` — builds the full wire value to pass to write_setting.
                         Takes (current_state, new_option_string).
    ``field_updates_fn`` — returns {field_name: value} for the optimistic
                            state update applied by coordinator.write_setting.
    """

    value_fn: Callable[[MowerState], str | None]
    cfg_key: str | None = None
    build_value_fn: Callable[[MowerState, str], Any] | None = None
    field_updates_fn: Callable[[MowerState, str], dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Abstract base for Zone / Spot / dynamic-target selects
# ---------------------------------------------------------------------------

class _DreameA2DynamicTargetSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity, RestoreEntity
):
    """Base for selects whose options come from MapData.{mowing,spot}_zones."""

    _attr_has_entity_name = True
    _placeholder: str = "(no map yet)"

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        unique_suffix: str,
        name: str,
        icon: str,
        map_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, unique_suffix)
        self._attr_name = name
        self._attr_icon = icon
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)
        self._label_to_id: dict[str, int] = {}
        self._attr_options: list[str] = [self._placeholder]
        self._attr_current_option: str | None = self._placeholder

    def _entries(self) -> list[tuple[int, str]]:
        """Subclasses return [(id, name), ...] from cached MapData."""
        raise NotImplementedError

    def _map_loaded(self) -> bool:
        """Subclasses return True if map data is available, False if still loading."""
        raise NotImplementedError

    def _empty_placeholder(self) -> str:
        """Subclasses return placeholder text when map is loaded but has no entries."""
        return "(no entries)"

    def _selected_ids(self) -> tuple[int, ...]:
        """Subclasses return the currently-selected ID tuple from MowerState."""
        raise NotImplementedError

    def _set_selected_ids(self, ids: tuple[int, ...]) -> None:
        """Subclasses replace the selection on coordinator.data."""
        raise NotImplementedError

    def _refresh(self) -> None:
        entries = self._entries()
        labels: list[str] = []
        mapping: dict[str, int] = {}
        for entry_id, name in entries:
            label = f"{name} (#{entry_id})" if name else f"#{entry_id}"
            if label in mapping:
                label = f"{label} [{entry_id}]"
            labels.append(label)
            mapping[label] = entry_id
        if not labels:
            # Distinguish "map not loaded" from "map loaded but no entries"
            placeholder = (
                self._empty_placeholder() if self._map_loaded()
                else self._placeholder
            )
            labels = [placeholder]
        # Reflect current selection in the dropdown if possible.
        sel_ids = self._selected_ids()
        sel_label: str | None = None
        if sel_ids:
            for lbl, eid in mapping.items():
                if eid == sel_ids[0]:
                    sel_label = lbl
                    break
        if sel_label is None and mapping:
            # The dropdown always visually highlights some row; previously
            # we'd surface labels[0] without writing to
            # active_selection_*, so a user who pressed Start without
            # explicitly tapping the picker got a silent "no spot
            # selected" no-op while the UI claimed Spot 1 was chosen.
            # Auto-commit the first entry so what is shown is what the
            # next Start will actually mow. Idempotent: subsequent
            # refreshes find a non-empty sel_ids and take the lookup
            # branch above instead.
            first_label = labels[0]
            sel_label = first_label
            self._set_selected_ids((int(mapping[first_label]),))
        elif sel_label is None:
            cur = self._attr_current_option
            sel_label = cur if cur in labels else labels[0]
        if (
            labels == self._attr_options
            and sel_label == self._attr_current_option
            and mapping == self._label_to_id
        ):
            return
        self._attr_options = labels
        self._label_to_id = mapping
        self._attr_current_option = sel_label

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the previously-picked target *before* _refresh runs its
        # auto-commit-first-entry fallback. Otherwise reboot resets the
        # selection to "first entry" instead of preserving the user's
        # actual choice.
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "", "unknown", "unavailable"):
            restored_id = self._extract_id_from_label(last_state.state)
            if restored_id is not None and not self._selected_ids():
                self._set_selected_ids((restored_id,))
        self._refresh()
        self.async_write_ha_state()

    @staticmethod
    def _extract_id_from_label(label: str) -> int | None:
        """Pull the numeric id back out of a label like ``Front lawn (#1)``.

        Format mirrors what `_refresh` builds: name + ``(#id)``. Restoring
        from the rendered label dodges the need for a separate persistence
        layer — RestoreEntity already gives us the last visible string.
        """
        import re

        match = re.search(r"#(\d+)", label)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

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
        target_id = self._label_to_id.get(option)
        if target_id is None:
            LOGGER.warning("select.%s: unknown option %r — ignoring", self._attr_unique_id, option)
            return
        self._set_selected_ids((int(target_id),))
        self._attr_current_option = option
        self.async_write_ha_state()
