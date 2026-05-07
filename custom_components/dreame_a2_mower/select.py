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
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode, MowerState


# ---------------------------------------------------------------------------
# F3.2.1: Action-mode select (unchanged)
# ---------------------------------------------------------------------------

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
    entities.append(DreameA2ReplaySessionSelect(coordinator))
    entities.append(DreameA2ZoneSelect(coordinator))
    entities.append(DreameA2SpotSelect(coordinator))
    entities.append(DreameA2EdgeSelect(coordinator))
    entities.append(DreameA2ActiveMapSelect(coordinator))
    async_add_entities(entities)


class DreameA2ActionModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity, RestoreEntity
):
    """User-facing action_mode picker.

    Per spec §5.1: HA realization of the Dreame app's mode dropdown
    (All-areas / Edge / Zone / Spot — Manual is BT-only and omitted).

    Selection persists across HA restarts via RestoreEntity. The
    coordinator's MowerState is recreated on every config-entry setup
    so without restoration the picker would silently snap back to
    All-areas after every reboot/integration-reload — meaning a user
    who set up Spot mode then restarted would unintentionally trigger
    an all-areas mow on the next Start press.
    """

    _attr_has_entity_name = True
    _attr_name = "Action mode"
    _attr_options = [m.value for m in ActionMode]

    entity_description = SelectEntityDescription(
        key="action_mode",
        translation_key="action_mode",
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_mode"
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "", "unknown", "unavailable"):
            return
        try:
            restored = ActionMode(last_state.state)
        except ValueError:
            LOGGER.debug(
                "select.action_mode: unrecognised restored state %r — keeping default",
                last_state.state,
            )
            return
        if restored == self.coordinator.data.action_mode:
            return
        new_state = dataclasses.replace(self.coordinator.data, action_mode=restored)
        self.coordinator.async_set_updated_data(new_state)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.action_mode.value

    async def async_select_option(self, option: str) -> None:
        """Update coordinator.data.action_mode and broadcast."""
        new_mode = ActionMode(option)
        new_state = dataclasses.replace(self.coordinator.data, action_mode=new_mode)
        self.coordinator.async_set_updated_data(new_state)


# ---------------------------------------------------------------------------
# F4.6.3: Generic settings select — descriptor + entity class
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
# Wire-value builders — settable selects
# ---------------------------------------------------------------------------

# PRE safe defaults for indices 2..9 when g2408 PRE is shorter than 10.
# Index 2 = height_mm (default 60 = the app's default 6cm).
# Indices 3..9 = not characterised on this firmware; 0 is the safest sentinel.
# _build_pre_efficiency uses this constant so the padding source-of-truth
# lives in one place rather than being inlined in the builder.
# Layout: [height_mm_default, idx3, idx4, idx5, idx6, idx7, idx8, idx9]
_PRE_PAD_DEFAULTS = [60, 0, 0, 0, 0, 0, 0, 0]  # indices 2..9 (8 elements)


def _build_pre_efficiency(state: MowerState, option: str) -> list:
    """Build the PRE array with mowing_efficiency (index 1) overridden.

    On g2408, CFG.PRE is observed as list(2) [zone_id, mode].  protocol/
    cfg_action.set_pre() requires at least 10 elements.  We pad to 10
    using safe defaults: PRE[2] uses the current MowerState height if
    known, otherwise _PRE_PAD_DEFAULTS[0] (60mm); PRE[3..9] use
    _PRE_PAD_DEFAULTS[1..] (all 0).

    Observed PRE[0] (zone_id) is preserved from MowerState; if None,
    defaults to 0 (the factory zone_id observed on g2408).
    """
    mode_int = 0 if option == "Standard" else 1
    zone_id = int(state.pre_zone_id or 0)
    height_mm = int(state.pre_mowing_height_mm or _PRE_PAD_DEFAULTS[0])
    # 10-element array: [zone_id, mode, height_mm, *_PRE_PAD_DEFAULTS[1..]]
    return [zone_id, mode_int, height_mm] + _PRE_PAD_DEFAULTS[1:]


def _pre_efficiency_field_updates(
    state: MowerState, option: str
) -> dict[str, Any]:
    return {"pre_mowing_efficiency": 0 if option == "Standard" else 1}


def _build_prot_path(_state: MowerState, option: str) -> int:
    """CFG.PROT wire encoding: 0 = direct path, 1 = smart path.

    The g2408 app exposes this as a binary choice between two named
    modes ("Direct Path" / "Smart Path"), not an enable/disable
    toggle, so it surfaces as a select rather than a switch in HA.
    """
    return 1 if option == "Smart Path" else 0


def _prot_path_field_updates(
    _state: MowerState, option: str
) -> dict[str, Any]:
    return {"navigation_path_smart": option == "Smart Path"}


def _build_wrp_resume_hours(state: MowerState, option: str) -> list:
    """Build the WRP wire value with resume_hours overridden.

    CFG.WRP = list(2) [enabled, resume_hours].
    Both fields are stored in MowerState; the enabled bit is read
    from rain_protection_enabled (defaulting to False so the write
    preserves whatever state the switch is in).

    option is one of the RESUME_HOURS_OPTIONS strings.  The numeric
    value is extracted by splitting on the first space.
    """
    enabled = bool(state.rain_protection_enabled)
    resume_hours = int(option.split()[0])
    return [int(enabled), resume_hours]


def _wrp_resume_hours_field_updates(
    state: MowerState, option: str
) -> dict[str, Any]:
    resume_hours = int(option.split()[0])
    return {"rain_protection_resume_hours": resume_hours}


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------

# rain_protection_resume_hours option labels.
# 0 = never resume automatically (app label: "Don't Mow After Rain").
# 1..24 = resume after N hours.
# g2408 confirmed values from app capture: 0, 1, 2, 3, 4, 6, 8, 12, 24.
_RESUME_HOURS_OPTIONS = [
    "0 hours",
    "1 hour",
    "2 hours",
    "3 hours",
    "4 hours",
    "6 hours",
    "8 hours",
    "12 hours",
    "24 hours",
]

SETTING_SELECTS: tuple[DreameA2SettingsSelectDescription, ...] = (
    # ------------------------------------------------------------------
    # Settable: PRE[1] — mowing efficiency
    #
    # Wire shape: list(10) per protocol/cfg_action.set_pre() constraint.
    # On g2408 only indices 0 (zone_id) and 1 (mode) are confirmed to
    # exist; indices 2..9 are padded with safe defaults.
    # Safe to write: the only mutable slot is index 1 (mode).
    # ------------------------------------------------------------------
    DreameA2SettingsSelectDescription(
        key="mowing_efficiency",
        name="Mowing efficiency",
        icon="mdi:speedometer",
        options=["Standard", "Efficient"],
        value_fn=lambda s: (
            "Standard" if s.pre_mowing_efficiency == 0
            else "Efficient" if s.pre_mowing_efficiency == 1
            else None
        ),
        cfg_key="PRE",
        build_value_fn=_build_pre_efficiency,
        field_updates_fn=_pre_efficiency_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: WRP[1] — rain protection resume hours
    #
    # Wire shape: list(2) [enabled, resume_hours].
    # Both fields stored in MowerState.  Safe to reconstruct.
    # Coordinates with switch.rain_protection (WRP[0]): both write
    # the full WRP list; whichever is last wins.  The select reads
    # current rain_protection_enabled from MowerState to preserve the
    # enabled bit when only the hours change.
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Settable: PROT — navigation path mode
    #
    # Wire shape: int {0, 1}. The Dreame app presents this as a binary
    # choice between two named modes — "Direct Path" (the mower drives
    # straight to the next mowing area) and "Smart Path" (uses an
    # internal nav-path planner). Surfaced as a select with those exact
    # labels so the device-info page and dashboard match the app's
    # vocabulary, instead of an opaque on/off toggle.
    # ------------------------------------------------------------------
    DreameA2SettingsSelectDescription(
        key="navigation_path",
        name="Navigation path",
        icon="mdi:routes",
        options=["Direct Path", "Smart Path"],
        value_fn=lambda s: (
            None if s.navigation_path_smart is None
            else "Smart Path" if s.navigation_path_smart
            else "Direct Path"
        ),
        cfg_key="PROT",
        build_value_fn=_build_prot_path,
        field_updates_fn=_prot_path_field_updates,
    ),

    DreameA2SettingsSelectDescription(
        key="rain_protection_resume_hours",
        name="Rain protection resume hours",
        icon="mdi:weather-rainy",
        options=_RESUME_HOURS_OPTIONS,
        value_fn=lambda s: (
            None if s.rain_protection_resume_hours is None
            else "1 hour" if s.rain_protection_resume_hours == 1
            else f"{s.rain_protection_resume_hours} hours"
        ),
        cfg_key="WRP",
        build_value_fn=_build_wrp_resume_hours,
        field_updates_fn=_wrp_resume_hours_field_updates,
    ),

    # ------------------------------------------------------------------
    # Read-only: CFG.LANG — language
    #
    # LANG on g2408 is list(2) [text_idx, voice_idx], stored as the
    # string "text=N,voice=M" in MowerState.language_code.
    # The set of valid text/voice index pairs is firmware-locale-specific
    # and not enumerable without a device LANG-options query.
    # The write path (set_cfg("LANG", ...)) is not confirmed on g2408.
    # Shipped read-only in F4.
    #
    # current_option will be the raw "text=N,voice=M" string or None.
    # options contains the currently-known value so HA doesn't error on
    # "unknown option"; it is populated dynamically in the entity class.
    # ------------------------------------------------------------------
    DreameA2SettingsSelectDescription(
        key="language",
        name="Language",
        icon="mdi:translate",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[],  # populated dynamically; see DreameA2SettingSelect.options
        value_fn=lambda s: s.language_code,
        # cfg_key intentionally omitted — read-only in F4
    ),
)


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class DreameA2SettingSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """A coordinator-backed select entity for enum-style CFG settings.

    Settable entities call coordinator.write_setting; read-only entities
    log a warning and no-op when async_select_option is called.

    The language select is a special case: its options list is not known
    at descriptor-definition time (it depends on the live language_code
    value).  We override the ``options`` property to return a single-item
    list containing the current value so HA never rejects the option as
    unknown.
    """

    _attr_has_entity_name = True
    entity_description: DreameA2SettingsSelectDescription

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        description: DreameA2SettingsSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    @property
    def options(self) -> list[str]:
        """Return the options list for this select.

        For the language select (which has an empty descriptor-level options
        list), we build a single-item list from the current value so HA's
        validation does not reject it as an unknown option.
        """
        desc_options = self.entity_description.options
        if desc_options:
            return list(desc_options)
        # Dynamic: language_code or empty list (entity shows unknown)
        current = self.entity_description.value_fn(self.coordinator.data)
        if current is not None:
            return [current]
        return []

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        """Write the selected option to the mower via the coordinator."""
        desc = self.entity_description
        if desc.cfg_key is None:
            LOGGER.warning(
                "select.%s: no write path configured (read-only in F4); "
                "ignoring select_option(%r)",
                desc.key,
                option,
            )
            return

        # Build the full wire value.
        if desc.build_value_fn is not None:
            wire_value = desc.build_value_fn(self.coordinator.data, option)
        else:
            wire_value = option

        # Collect optimistic field updates (optional).
        field_updates: dict[str, Any] | None = None
        if desc.field_updates_fn is not None:
            field_updates = desc.field_updates_fn(self.coordinator.data, option)

        success = await self.coordinator.write_setting(
            desc.cfg_key,
            wire_value,
            field_updates=field_updates,
        )
        if not success:
            LOGGER.warning(
                "select.%s: write_setting(%r, %r) returned False",
                desc.key,
                desc.cfg_key,
                wire_value,
            )


# ---------------------------------------------------------------------------
# v1.0.0a6: Session-replay picker
# ---------------------------------------------------------------------------


class DreameA2ReplaySessionSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Dropdown of archived sessions; picking one fires `replay_session`.

    Options are human-readable labels: ``YYYY-MM-DD HH:MM — N.N m² / Mmin``.
    The label maps back to a session md5 via an internal dict on the entity.
    Newest session first; capped at the most recent 50 to keep the dropdown
    sane.
    """

    _attr_has_entity_name = True
    _attr_name = "Replay session"
    _attr_icon = "mdi:history"
    _placeholder: str = "(pick a session to replay)"
    _max_options: int = 50

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_replay_session"
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client else None
        model = getattr(client, "model", None) if client else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )
        # v1.0.0a53: keyed by filename (unique) instead of md5 (which
        # g2408 reuses across sessions against an unchanged map).
        self._label_to_md5: dict[str, str] = {}
        self._attr_options: list[str] = [self._placeholder]
        self._attr_current_option = self._placeholder

    def _build_options_from_sessions(self, sessions: list) -> tuple[list[str], dict[str, str]]:
        """Pure formatter — no I/O."""
        from datetime import datetime

        sessions = sorted(sessions, key=lambda s: s.end_ts, reverse=True)[: self._max_options]
        labels: list[str] = [self._placeholder]
        mapping: dict[str, str] = {}
        for s in sessions:
            try:
                # v1.0.0a20: render in HA's system-local timezone (no
                # tz=timezone.utc) so users see times that match their
                # wall clock.
                ts_str = datetime.fromtimestamp(int(s.end_ts)).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (OverflowError, OSError, ValueError):
                ts_str = "??"
            # v1.0.0a92 (MM Task 11): prefix each session label with the
            # map it was mowed against so users can distinguish sessions
            # from different maps at a glance. map_id=-1 = legacy archive
            # entry that predates multi-map support (rendered as [Map ?]).
            map_id = getattr(s, "map_id", -1)
            if map_id == -1:
                map_prefix = "[Map ?]"
            else:
                map_prefix = f"[Map {map_id + 1}]"
            base = f"{map_prefix} {ts_str} — {s.area_mowed_m2:.1f} m² / {s.duration_min}min"
            # v1.0.0a19: visibly mark the still-running entry so users
            # can tell the live mow apart from completed archives.
            if getattr(s, "still_running", False):
                label = f"▶ {base} (in progress)"
            elif not getattr(s, "local_trail_complete", True):
                # 2026-05-05 trail-loss-on-restart finding: the archive
                # carries a `local_trail_complete` flag set False when the
                # archived `_local_legs` is anomalously short for the
                # session duration (typically because HA restarted mid-mow
                # and `_restore_in_progress` race-skipped restoring the
                # disk-backed pre-restart points). Mark in the picker so
                # the user knows which sessions to expect a degraded local
                # replay for. Cloud trajectory.track is unaffected; the
                # render path may still produce a usable trail from it.
                label = f"⚠ {base} (partial trail)"
            else:
                label = base
            if label in mapping:
                label = f"{label} [{s.md5[:6]}]"
            labels.append(label)
            # Use the unique filename so two sessions sharing an md5
            # (which g2408 routinely emits for sessions on an
            # unchanged map) are still individually selectable. Falls
            # back to md5 for the in-progress synthesized row whose
            # filename is the constant 'in_progress.json' but whose
            # md5 is "" (replay_session no-ops on falsy values).
            mapping[label] = s.filename or s.md5
        return labels, mapping

    async def _async_refresh_options(self) -> None:
        """Refresh the dropdown via executor — never blocks the event loop.

        list_sessions touches in_progress.json which is sync disk I/O;
        running it through hass.async_add_executor_job keeps the
        coordinator and HA's event loop unblocked.
        """
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return
        try:
            sessions = await self.hass.async_add_executor_job(archive.list_sessions)
        except Exception as ex:
            LOGGER.warning("select.replay_session: list_sessions failed: %s", ex)
            return
        labels, mapping = self._build_options_from_sessions(sessions)
        if labels == self._attr_options and mapping == self._label_to_md5:
            return
        self._attr_options = labels
        self._label_to_md5 = mapping
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Populate the dropdown once the entity is live."""
        await super().async_added_to_hass()
        await self._async_refresh_options()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        # Schedule an executor-backed refresh whenever the coordinator
        # broadcasts an update; the archive count typically only moves
        # after a finalize, so this is a cheap way to keep the dropdown
        # current without polling.
        super()._handle_coordinator_update()
        self.hass.async_create_task(self._async_refresh_options())

    @property
    def options(self) -> list[str]:
        # NEVER do I/O here — HA calls this property from the event loop.
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        # v1.0.0a14: keep the user's last pick visible so the dropdown
        # shows what the live map is currently rendering. Defaults to
        # the placeholder until the user picks something.
        return self._attr_current_option or self._placeholder

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            # Picking the placeholder is a no-op — keep whatever
            # session is currently being shown.
            return
        # Refresh in case the archive changed since the last read.
        await self._async_refresh_options()
        md5 = self._label_to_md5.get(option)
        if not md5:
            LOGGER.warning(
                "select.replay_session: unknown option %r — ignoring", option
            )
            return
        LOGGER.info(
            "select.replay_session: replay session md5=%s (label=%r)",
            md5,
            option,
        )
        try:
            await self.coordinator.replay_session(md5)
        except Exception as ex:
            LOGGER.warning("select.replay_session: replay_session(%s) raised: %s", md5, ex)
        # v1.0.0a14: keep the picked option as the current state so the
        # dropdown reflects what's drawn on the map.
        self._attr_current_option = option
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# v1.0.0a26: Zone / Spot pickers — dynamic options sourced from the cloud
# map. Setting one writes to active_selection_zones/spots so subsequent
# start_mowing dispatches use the picked target. Multi-pick is exposed as
# the start_zone_mowing / start_spot_mowing services.
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
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client else None
        model = getattr(client, "model", None) if client else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )
        self._label_to_id: dict[str, int] = {}
        self._attr_options: list[str] = [self._placeholder]
        self._attr_current_option: str | None = self._placeholder

    def _entries(self) -> list[tuple[int, str]]:
        """Subclasses return [(id, name), ...] from cached MapData."""
        raise NotImplementedError

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
            labels = [self._placeholder]
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
            sel_label = self._attr_current_option if self._attr_current_option in labels else labels[0]
        if labels == self._attr_options and sel_label == self._attr_current_option and mapping == self._label_to_id:
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


class DreameA2ZoneSelect(_DreameA2DynamicTargetSelect):
    """Pick which mowing zone the next zone-mode start_mowing targets."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "zone_target", "Zone", "mdi:grass")

    def _entries(self) -> list[tuple[int, str]]:
        md = getattr(self.coordinator, "_cached_map_data", None)
        if md is None:
            return []
        return [(z.zone_id, z.name) for z in getattr(md, "mowing_zones", ())]

    def _selected_ids(self) -> tuple[int, ...]:
        return self.coordinator.data.active_selection_zones

    def _set_selected_ids(self, ids: tuple[int, ...]) -> None:
        new_state = dataclasses.replace(self.coordinator.data, active_selection_zones=ids)
        self.coordinator.async_set_updated_data(new_state)


class DreameA2SpotSelect(_DreameA2DynamicTargetSelect):
    """Pick which spot zone the next spot-mode start_mowing targets."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "spot_target", "Spot", "mdi:target")

    def _entries(self) -> list[tuple[int, str]]:
        md = getattr(self.coordinator, "_cached_map_data", None)
        if md is None:
            return []
        return [(s.spot_id, s.name) for s in getattr(md, "spot_zones", ())]

    def _selected_ids(self) -> tuple[int, ...]:
        return self.coordinator.data.active_selection_spots

    def _set_selected_ids(self, ids: tuple[int, ...]) -> None:
        new_state = dataclasses.replace(self.coordinator.data, active_selection_spots=ids)
        self.coordinator.async_set_updated_data(new_state)


class DreameA2EdgeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity, RestoreEntity
):
    """Pick which contour(s) the next edge-mode start_mowing targets.

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
    _attr_name = "Edge"
    _attr_icon = "mdi:vector-polyline"

    _ALL_LABEL = "All perimeters"
    _PLACEHOLDER = "(no map yet)"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_edge_target"
        client = getattr(coordinator, "_cloud", None)
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )
        # Each label resolves to a tuple of `(map_id, contour_index)` pairs.
        # _ALL_LABEL maps to "every (N, 0)"; per-zone labels map to a single pair.
        self._label_to_contours: dict[str, tuple[tuple[int, int], ...]] = {}
        self._attr_options: list[str] = [self._PLACEHOLDER]
        self._attr_current_option: str | None = self._PLACEHOLDER

    def _outer_contour_ids(self) -> tuple[tuple[int, int], ...]:
        md = getattr(self.coordinator, "_cached_map_data", None)
        avail = getattr(md, "available_contour_ids", ()) if md is not None else ()
        return tuple(cid for cid in avail if len(cid) == 2 and cid[1] == 0)

    def _zone_name_for_contour(self, cid: tuple[int, int]) -> str | None:
        """Look up a human-readable zone name for the given contour ID.

        Contours and mowing-zones are independently keyed in the cloud
        map data, but the contour's first int (`cid[0]`) corresponds to
        the zone-region the perimeter belongs to. Return the matching
        zone's name from `MapData.mowing_zones` if present, else None.
        """
        md = getattr(self.coordinator, "_cached_map_data", None)
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
            self._attr_options = [self._PLACEHOLDER]
            self._attr_current_option = self._PLACEHOLDER
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
            self._PLACEHOLDER,
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
# Task 9 (multi-map plan): Active-map selector — read-only Phase 1
# ---------------------------------------------------------------------------


class DreameA2ActiveMapSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Active-map selector. Writable via s2.50 op:200 changeMap.

    Dispatches SET_ACTIVE_MAP (MowerAction) which builds the TASK envelope
    ``{"m":"a","p":0,"o":200,"d":{"idx":<map_index>}}`` and routes it through
    the coordinator's dispatch_action path (siid=2, aiid=50).

    The firmware's MAPL is the source of truth; the s1p50 ping and the
    o:200 echo will trigger a coordinator re-poll within seconds of the
    cloud call completing.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "active_map"
    _attr_name = "Active map"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_active_map"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    @property
    def options(self) -> list[str]:
        return [
            self._label_for(map_id, m)
            for map_id, m in sorted(self.coordinator._cached_maps_by_id.items())
        ]

    @property
    def current_option(self) -> str | None:
        active = self.coordinator._active_map_id
        if active is None:
            return None
        m = self.coordinator._cached_maps_by_id.get(active)
        if m is None:
            return None
        return self._label_for(active, m)

    @staticmethod
    def _label_for(map_id: int, map_data: Any) -> str:
        name = getattr(map_data, "name", None)
        if name:
            return str(name)
        return f"Map {map_id + 1}"

    async def async_select_option(self, option: str) -> None:
        # Reverse-lookup: map the option label back to a map_id.
        target_map_id: int | None = None
        for map_id, m in self.coordinator._cached_maps_by_id.items():
            if self._label_for(map_id, m) == option:
                target_map_id = map_id
                break
        if target_map_id is None:
            LOGGER.warning(
                "select.active_map: option=%r not found in cached maps", option
            )
            return
        if target_map_id == self.coordinator._active_map_id:
            # Already active; just refresh.
            await self.coordinator._refresh_mapl()
            self.async_write_ha_state()
            return

        from .mower.actions import MowerAction
        await self.coordinator.dispatch_action(
            MowerAction.SET_ACTIVE_MAP, {"map_id": target_map_id}
        )
        # MAPL will reflect the change on the next refresh; the s1p50
        # ping (Task 8b) AND the o:200 echo will trigger a re-poll
        # within seconds.
