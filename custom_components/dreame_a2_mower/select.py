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
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .wifi_archive_store import WifiArchiveEntry

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from ._settings_writes import (
    settings_optimistic_write as _settings_select_optimistic_write,
)
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
    entities.append(DreameA2WorkLogSelect(coordinator))
    entities.append(DreameA2LidarArchiveSelect(coordinator))
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.extend([
            DreameA2MowingModeSelect(coordinator, map_id=map_id),
            DreameA2ZoneSelect(coordinator, map_id=map_id),
            DreameA2SpotSelect(coordinator, map_id=map_id),
            DreameA2EdgeSelect(coordinator, map_id=map_id),
        ])
    entities.append(DreameA2ActiveMapSelect(coordinator))
    # Per-map SETTINGS selects (v1.0.10a7 — migrated from mower-scoped).
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.extend([
            DreameA2PerMapMowingDirectionSelect(coordinator, map_id=map_id),
            DreameA2PerMapMowingDirectionModeSelect(coordinator, map_id=map_id),
            DreameA2PerMapEdgeMowingWalkModeSelect(coordinator, map_id=map_id),
        ])
    entities.append(DreameA2WifiArchiveSelect(coordinator))
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
    _attr_options: ClassVar[list[str]] = [m.value for m in ActionMode]

    entity_description = SelectEntityDescription(
        key="action_mode",
        translation_key="action_mode",
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "action_mode")
        self._attr_device_info = mower_device_info(coordinator)

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
    return [zone_id, mode_int, height_mm, *_PRE_PAD_DEFAULTS[1:]]


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


# ---------------------------------------------------------------------------
# CFG.LANG — language indices.
#
# The 16-language voice order was provided by the user 2026-05-09 from the
# Dreame app's voice-language picker. Index 7 = Norwegian was independently
# confirmed via CFG read while voice was set to Norwegian.
#
# The TEXT-language list is a SEPARATE picker in the app and may have a
# different order — TBD pending user enumeration. Until we have it
# confirmed, the text-language select shows "Index N" placeholders rather
# than language names. Users can still set arbitrary text indices via the
# `dreame_a2_mower.set_language` service.
# ---------------------------------------------------------------------------
VOICE_LANGUAGE_NAMES: tuple[str, ...] = (
    "English",          # 0
    "Chinese",          # 1
    "German",           # 2
    "French",           # 3
    "Italian",          # 4
    "Spanish",          # 5
    "Portuguese",       # 6
    "Norwegian",        # 7
    "Swedish",          # 8
    "Danish",           # 9
    "Finnish",          # 10
    "Dutch",            # 11
    "Turkish",          # 12
    "Polish",           # 13
    "Russian",          # 14
    "Lithuanian",       # 15
)

# Text language list — the mower's physical LCD screen language picker.
# Captured 2026-05-09 by user opening the lid and reading the LCD's
# language picker order (Danish picked, cloud read back text=0,
# confirming 0-indexed and Danish at position 0).
#
# Native names are alphabetical: Dansk, Deutsch, English, Español,
# Français, Italiano, Nederlands, Norsk, Polski, Suomi, Svenska,
# (Chinese 1), (Chinese 2). The two Chinese entries are likely
# Simplified and Traditional but were captured as glyphs the user
# couldn't read off ("box with vertical line through" + "stick-man" —
# best-guess Simplified + Traditional).
#
# **0-indexed on the LCD** (in contrast to the app's "Languages"
# picker which is 1-indexed and a *different* list of 33 i18n locales
# for the app's UI strings — see APP_TEXT_LANGUAGE_NAMES below for
# that catalog). The two are independent:
#   - LCD picker (this list) ←→ CFG.LANG[0]
#   - App picker (APP_TEXT_LANGUAGE_NAMES) ←→ app's own i18n locale,
#     no cloud key
#
# Verifying device-apply requires PHYSICAL access (open the lid).
# The Dreame app does NOT and is NOT expected to reflect changes to
# CFG.LANG[0].
TEXT_LANGUAGE_NAMES: tuple[str, ...] = (
    "Danish",               # 0  Dansk
    "German",               # 1  Deutsch
    "English",              # 2  English
    "Spanish",              # 3  Español
    "French",               # 4  Français
    "Italian",              # 5  Italiano
    "Dutch",                # 6  Nederlands
    "Norwegian",            # 7  Norsk
    "Polish",               # 8  Polski
    "Finnish",              # 9  Suomi
    "Swedish",              # 10 Svenska
    "Simplified Chinese",   # 11 (best-guess from user's "box with vertical line through" glyph)
    "Traditional Chinese",  # 12 (best-guess from user's "stick-man" glyph)
)
TEXT_LANGUAGE_OPTIONS: list[str] = list(TEXT_LANGUAGE_NAMES)

# The Dreame APP's "Languages" picker — the app's own UI display
# language, INDEPENDENT of the mower's text language. 33 entries,
# 1-indexed on the app side. Captured 2026-05-09 from screenshots
# (lang1.PNG / lang2.PNG / lang3.PNG). Kept here as a catalog for
# anyone investigating the app-side surface; not used by any HA
# entity since the app's i18n locale doesn't live in CFG.LANG.
APP_TEXT_LANGUAGE_NAMES: tuple[str | None, ...] = (
    None,                            # 0  unused (app uses 1-indexed)
    "Simplified Chinese",            # 1  简体中文
    "English",                       # 2
    "Traditional Chinese (Taiwan)",  # 3  繁體中文(台灣)
    "Traditional Chinese (Hong Kong)",  # 4  繁體中文(香港)
    "Spanish",                       # 5  Español
    "Russian",                       # 6  Русский
    "Korean",                        # 7  한국어
    "Italian",                       # 8  Italiano
    "French",                        # 9  Français
    "German",                        # 10 Deutsch
    "Indonesian",                    # 11 Indonesia
    "Polish",                        # 12 Polski
    "Vietnamese",                    # 13 Tiếng Việt
    "Japanese",                      # 14 日本語
    "Thai",                          # 15 ไทย
    "Turkish",                       # 16 Türkçe
    "Ukrainian",                     # 17 Українська Мова
    "Dutch",                         # 18 Nederlands
    "Portuguese",                    # 19 Português
    "Norwegian",                     # 20 Norsk
    "Swedish",                       # 21 Svenska
    "Danish",                        # 22 Dansk
    "Malay",                         # 23 Melayu
    "Arabic",                        # 24 العربية
    "Hebrew",                        # 25 עברית
    "Finnish",                       # 26 Suomi
    "Czech",                         # 27 Čeština
    "Slovak",                        # 28 Slovenčina
    "Hungarian",                     # 29 Magyar
    "Romanian",                      # 30 Română
    "Latvian",                       # 31 Latviešu
    "Slovenian",                     # 32 Slovenščina
    "Lithuanian",                    # 33 Lietuvių
)


def _build_text_language(state: MowerState, option: str) -> dict:
    """LANG text-language wire value: ``{type:'text', value:<idx>}``.

    Wire format verified live 2026-05-09 via named-key round-trip probe.
    The cloud accepts the tagged-union dict; device-apply confirmed
    2026-05-09 by user physically reading the mower's LCD after a flip.

    Text language is **0-indexed on the LCD** — `TEXT_LANGUAGE_NAMES[idx]`
    is the language at that LCD-side index. Note this differs from the
    app's *Languages* picker which is 1-indexed and a different list
    (`APP_TEXT_LANGUAGE_NAMES` — kept as a catalog but not used by any
    HA entity).
    """
    idx = TEXT_LANGUAGE_NAMES.index(option)
    return {"type": "text", "value": idx}


def _text_language_field_updates(state: MowerState, option: str) -> dict[str, Any]:
    idx = TEXT_LANGUAGE_NAMES.index(option)
    voice_idx = state.language_voice_idx if state.language_voice_idx is not None else 0
    return {
        "language_text_idx": idx,
        "language_code": f"text={idx},voice={voice_idx}",
    }


def _build_voice_language(state: MowerState, option: str) -> dict:
    """LANG voice-language wire value: ``{type:'voice', value:<idx>}``.

    Verified live 2026-05-09. Index → name mapping is the
    voice-language picker order from the Dreame app.
    """
    idx = VOICE_LANGUAGE_NAMES.index(option)
    return {"type": "voice", "value": idx}


def _voice_language_field_updates(state: MowerState, option: str) -> dict[str, Any]:
    idx = VOICE_LANGUAGE_NAMES.index(option)
    text_idx = state.language_text_idx if state.language_text_idx is not None else 0
    return {
        "language_voice_idx": idx,
        "language_code": f"text={text_idx},voice={idx}",
    }


def _build_wrp_resume_hours(state: MowerState, option: str) -> dict:
    """Build the WRP wire value with resume_hours overridden.

    Wire format: ``{value, time:<hours>}`` (verified live 2026-05-09 via
    cloud + device-app round-trip).  The enabled bit is read from
    rain_protection_enabled (defaulting to False so the write preserves
    whatever state the switch is in).  The optional ``sen`` field is
    omitted — see _build_wrp in switch.py for rationale.

    option is one of the RESUME_HOURS_OPTIONS strings.  The numeric
    value is extracted by splitting on the first space.
    """
    enabled = bool(state.rain_protection_enabled)
    resume_hours = int(option.split()[0])
    return {"value": int(enabled), "time": resume_hours}


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
        name="Language (raw)",
        icon="mdi:translate",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[],  # populated dynamically; see DreameA2SettingSelect.options
        value_fn=lambda s: s.language_code,
        # cfg_key intentionally omitted — read-only diagnostic
    ),
    # ------------------------------------------------------------------
    # Settable: CFG.LANG — text language index (index 0 of LANG list).
    # Wire format verified live 2026-05-09: routed-action s2.50 m='s'
    # t='LANG' d={type:'text', value:<int>}. Discovered via the ioBroker
    # apk.md catalog (LANG | setTextLang/setVoiceLang | {type, value})
    # and live-confirmed via round-trip probe (both type='text' and
    # type='voice' returned r=0 with values preserved).
    # The 16-language order was provided by the user 2026-05-09 from
    # the Dreame app's language picker.
    # ------------------------------------------------------------------
    DreameA2SettingsSelectDescription(
        key="lcd_language",
        # entity_id: select.dreame_a2_mower_lcd_language. Renamed from
        # `text_language` 2026-05-09 to remove the ambiguity with the
        # Dreame APP's own "Languages" picker (which is the app's UI
        # locale and lives elsewhere — see APP_TEXT_LANGUAGE_NAMES).
        # The old `select.dreame_a2_mower_text_language` becomes an
        # orphan in the entity registry on rename; the integration's
        # async_setup removes it via the existing orphan-cleanup pass.
        name="Mower LCD language",
        icon="mdi:monitor",
        options=TEXT_LANGUAGE_OPTIONS,
        value_fn=lambda s: (
            TEXT_LANGUAGE_NAMES[s.language_text_idx]
            if s.language_text_idx is not None
            and 0 <= s.language_text_idx < len(TEXT_LANGUAGE_NAMES)
            else None
        ),
        cfg_key="LANG",
        build_value_fn=_build_text_language,
        field_updates_fn=_text_language_field_updates,
    ),
    # ------------------------------------------------------------------
    # Settable: CFG.LANG — voice language index (index 1 of LANG list).
    # Same wire format as text_language but type='voice'.
    # ------------------------------------------------------------------
    DreameA2SettingsSelectDescription(
        key="voice_language",
        name="Voice language",
        icon="mdi:account-voice",
        options=list(VOICE_LANGUAGE_NAMES),
        value_fn=lambda s: (
            VOICE_LANGUAGE_NAMES[s.language_voice_idx]
            if s.language_voice_idx is not None
            and 0 <= s.language_voice_idx < len(VOICE_LANGUAGE_NAMES)
            else None
        ),
        cfg_key="LANG",
        build_value_fn=_build_voice_language,
        field_updates_fn=_voice_language_field_updates,
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
        self._attr_unique_id = mower_unique_id(coordinator, description.key)
        self._attr_device_info = mower_device_info(coordinator)

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
# Work Log picker (renamed from DreameA2ReplaySessionSelect in Task 9)
# ---------------------------------------------------------------------------


class DreameA2WorkLogSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Dropdown of archived sessions; picking one fires `render_work_log_session`.

    Options are human-readable labels:
        ``[Mowing] [Map N] YYYY-MM-DD HH:MM — N.N m² / Mmin``

    The ``[Mowing]`` prefix tags every entry by category — when Patrol Logs
    become available, ``[Patrol]``-prefixed entries can be merged into the
    same picker.

    The label maps back to a session filename via an internal dict.
    Newest session first; capped at the most recent 50.

    In-progress sessions (``still_running == True``) are FILTERED OUT — the
    Main view shows the live mow; Work Logs is for finalised sessions only.
    """

    _attr_has_entity_name = True
    _attr_name = "Work Log"
    _attr_icon = "mdi:history"
    _placeholder: str = "(pick a session)"
    _max_options: int = 50

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "work_log")
        self._attr_device_info = mower_device_info(coordinator)
        self._label_to_filename: dict[str, str] = {}
        self._attr_options: list[str] = [self._placeholder]
        self._attr_current_option = self._placeholder

    def _build_options_from_sessions(self, sessions: list) -> tuple[list[str], dict[str, str]]:
        """Pure formatter — no I/O.

        Filters out still_running entries (in-progress lives on Main view).
        """
        from datetime import datetime

        eligible = [s for s in sessions if not getattr(s, "still_running", False)]
        eligible = sorted(eligible, key=lambda s: s.end_ts, reverse=True)[: self._max_options]
        labels: list[str] = [self._placeholder]
        mapping: dict[str, str] = {}
        for s in eligible:
            try:
                ts_str = datetime.fromtimestamp(int(s.end_ts)).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (OverflowError, OSError, ValueError):
                ts_str = "??"
            map_id = getattr(s, "map_id", -1)
            map_prefix = "[Map ?]" if map_id == -1 else f"[Map {map_id + 1}]"
            base = (
                f"[Mowing] {map_prefix} {ts_str}"
                f" — {s.area_mowed_m2:.1f} m² / {s.duration_min}min"
            )
            if not getattr(s, "local_trail_complete", True):
                label = f"⚠ {base} (partial trail)"
            else:
                label = base
            if label in mapping:
                label = f"{label} [{(s.md5 or '')[:6]}]"
            labels.append(label)
            mapping[label] = s.filename or s.md5
        return labels, mapping

    async def _async_refresh_options(self) -> None:
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return
        try:
            sessions = await self.hass.async_add_executor_job(archive.list_sessions)
        except Exception as ex:
            LOGGER.warning("select.work_log: list_sessions failed: %s", ex)
            return
        labels, mapping = self._build_options_from_sessions(sessions)
        if labels == self._attr_options and mapping == self._label_to_filename:
            return
        self._attr_options = labels
        self._label_to_filename = mapping
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_options()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self.hass.async_create_task(self._async_refresh_options())

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option or self._placeholder

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            # Picking the placeholder clears the work-log camera.
            self.coordinator._work_log_png = None
            update_listeners = getattr(self.coordinator, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()
            self._attr_current_option = self._placeholder
            self.async_write_ha_state()
            return
        await self._async_refresh_options()
        filename = self._label_to_filename.get(option)
        if not filename:
            LOGGER.warning(
                "select.work_log: unknown option %r — ignoring", option
            )
            return
        LOGGER.info(
            "select.work_log: render session %s (label=%r)", filename, option,
        )
        try:
            await self.coordinator.render_work_log_session(filename)
        except Exception as ex:
            LOGGER.warning("select.work_log: render_work_log_session(%s) raised: %s", filename, ex)
        self._attr_current_option = option
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Cross-map LiDAR archive picker
# ---------------------------------------------------------------------------


class DreameA2LidarArchiveSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Cross-map LiDAR archive picker.

    Options listing every archived LiDAR scan across maps, sorted
    newest-first, prefixed with ``[Map N]`` for clarity. Selection drives
    ``camera.dreame_a2_mower_lidar_selected`` rendering.

    The coordinator lazily loads each map's archive index on first read;
    options may be sparse at boot if the executor job hasn't run yet.
    """

    _attr_has_entity_name = True
    _attr_name = "LiDAR archive"
    _attr_icon = "mdi:radar"
    _attr_translation_key = "lidar_archive"
    _placeholder: str = "(no scans)"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "lidar_archive")
        self._attr_device_info = mower_device_info(coordinator)
        self._attr_current_option: str | None = self._placeholder
        self._attr_options: list[str] = [self._placeholder]

    @staticmethod
    def _format_option(map_id: int, entry: Any) -> str:
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(entry.unix_ts, tz=timezone.utc).astimezone()
        return f"[Map {map_id + 1}] {ts:%Y-%m-%d %H:%M}"

    def _rebuild_options(self) -> None:
        entries = self.coordinator.list_lidar_archive_entries()
        opts = [self._format_option(mid, e) for mid, e in entries]
        if not opts:
            opts = [self._placeholder]
        # Reflect current selection.
        render = self.coordinator._lidar_render_entry
        if render is None:
            # Default: show the newest scan.
            cur = opts[0]
        else:
            map_id, filename = render
            archive = self.coordinator.lidar_archives.get(map_id)
            cur = self._placeholder
            if archive is not None:
                for entry in archive.entries():
                    if entry.filename == filename:
                        cur = self._format_option(map_id, entry)
                        break
        self._attr_options = opts
        self._attr_current_option = cur if cur in opts else opts[0]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._rebuild_options()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self._rebuild_options()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            self.coordinator.set_lidar_render_entry(None, None)
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        # Reverse-engineer option string to find map_id + filename.
        for map_id, entry in self.coordinator.list_lidar_archive_entries():
            if self._format_option(map_id, entry) == option:
                self.coordinator.set_lidar_render_entry(map_id, entry.filename)
                self._attr_current_option = option
                self.async_write_ha_state()
                return
        LOGGER.warning("LidarArchiveSelect: unknown option %r", option)


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
        map_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, unique_suffix)
        self._attr_name = name
        self._attr_icon = icon
        map_data = coordinator._cached_maps_by_id.get(map_id)
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


class DreameA2ZoneSelect(_DreameA2DynamicTargetSelect):
    """Pick which mowing zone the next zone-mode start_mowing targets."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator, map_id: int) -> None:
        # has_entity_name=True; device_name is prepended automatically.
        super().__init__(coordinator, "zone_target", "Zone", "mdi:grass", map_id=map_id)

    def _entries(self) -> list[tuple[int, str]]:
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
        if md is None:
            return []
        return [(z.zone_id, z.name) for z in getattr(md, "mowing_zones", ())]

    def _map_loaded(self) -> bool:
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
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
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
        if md is None:
            return []
        return [(s.spot_id, s.name) for s in getattr(md, "spot_zones", ())]

    def _map_loaded(self) -> bool:
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
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
        map_data = coordinator._cached_maps_by_id.get(map_id)
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
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
        return md is not None

    def _outer_contour_ids(self) -> tuple[tuple[int, int], ...]:
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
        avail = getattr(md, "available_contour_ids", ()) if md is not None else ()
        return tuple(cid for cid in avail if len(cid) == 2 and cid[1] == 0)

    def _zone_name_for_contour(self, cid: tuple[int, int]) -> str | None:
        """Look up a human-readable zone name for the given contour ID.

        Contours and mowing-zones are independently keyed in the cloud
        map data, but the contour's first int (`cid[0]`) corresponds to
        the zone-region the perimeter belongs to. Return the matching
        zone's name from `MapData.mowing_zones` if present, else None.
        """
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
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
        map_data = coordinator._cached_maps_by_id.get(map_id)
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
        md = self.coordinator._cached_maps_by_id.get(self._map_id)
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
        self._attr_unique_id = mower_unique_id(coordinator, "active_map")
        self._attr_device_info = mower_device_info(coordinator)
        # Optimistic UI: set while a changeMap write is in flight so the
        # dropdown doesn't revert to the old value before firmware commits.
        self._optimistic_target_map_id: int | None = None

    @property
    def options(self) -> list[str]:
        return [
            self._label_for(map_id, m)
            for map_id, m in sorted(self.coordinator._cached_maps_by_id.items())
        ]

    @property
    def current_option(self) -> str | None:
        # Optimistic UI: when a write is in flight (firmware not yet
        # committed via MAPL), show the user's just-selected target.
        if self._optimistic_target_map_id is not None:
            target = self._optimistic_target_map_id
            m = self.coordinator._cached_maps_by_id.get(target)
            if m is not None:
                return self._label_for(target, m)
        # Default: read from MAPL-derived state.
        active = self.coordinator._active_map_id
        if active is None:
            return None
        m = self.coordinator._cached_maps_by_id.get(active)
        if m is None:
            return None
        return self._label_for(active, m)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose `current_map_id` for dashboard conditional cards.

        Cards key off this stable integer rather than the select's state
        (the friendly name), so the dashboard survives the user renaming
        a map in the Dreame app.
        """
        return {"current_map_id": self.coordinator._active_map_id}

    @staticmethod
    def _label_for(map_id: int, map_data: Any) -> str:
        name = getattr(map_data, "name", None)
        if name:
            return str(name)
        return f"Map {map_id + 1}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Auto-clear the optimistic target when MAPL confirms it."""
        if (
            self._optimistic_target_map_id is not None
            and self.coordinator._active_map_id == self._optimistic_target_map_id
        ):
            self._optimistic_target_map_id = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        # Cloud + firmware reject "change active map" while the mower is
        # actively mowing. Refuse the action and surface a notification
        # instead of dispatching a call we know will fail. The flip-back-
        # to-active-map after a few seconds is the cloud's silent rejection.
        from .mower.state_snapshot import CurrentActivity as _CA, MowSession as _MS
        _snap = self.coordinator.state_machine.snapshot()
        _blocked = (
            _snap.current_activity in (
                _CA.MOWING, _CA.FAST_MAPPING, _CA.PAUSED,
                _CA.REPOSITIONING, _CA.CRUISING_TO_POINT, _CA.AT_POINT,
            )
            or _snap.mow_session == _MS.IN_SESSION
        )
        if _blocked:
            LOGGER.warning(
                "select.active_map: refusing change to %r — mower is %s "
                "(map switch only works while idle/docked)",
                option, _snap.current_activity.name,
            )
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"{DOMAIN}: Map switch blocked",
                    "message": (
                        f"Cannot switch to {option!r} while the mower is "
                        f"actively mowing or paused. Wait for the session "
                        f"to finish (or dock the mower), then try again."
                    ),
                    "notification_id": f"{DOMAIN}_active_map_switch_blocked",
                },
                blocking=False,
            )
            return

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

        # Set optimistic target so the UI doesn't revert during the
        # firmware-commit window. _apply_mapl's async_update_listeners
        # call will trigger a re-render once MAPL confirms; that re-render
        # will see _active_map_id == _optimistic_target_map_id and clear
        # the optimistic flag via _handle_coordinator_update.
        self._optimistic_target_map_id = target_map_id
        self.async_write_ha_state()

        # Dispatch the firmware command. The s1p50 ping the firmware
        # emits will trigger _refresh_mapl, which eventually reflects
        # the committed value.
        from .mower.actions import MowerAction
        try:
            await self.coordinator.dispatch_action(
                MowerAction.SET_ACTIVE_MAP, {"map_id": target_map_id}
            )
        except Exception as ex:
            LOGGER.warning(
                "select.active_map: dispatch failed: %s; reverting optimistic", ex
            )
            self._optimistic_target_map_id = None
            self.async_write_ha_state()
            return

        # Schedule a fallback clear of the optimistic flag after 10s.
        # If MAPL confirms within that window, the listener-triggered
        # re-render calls _handle_coordinator_update which clears it.
        # If MAPL never confirms (e.g. firmware rejected the write),
        # the timer fires and reverts to the actual MAPL state.
        from homeassistant.helpers.event import async_call_later

        @callback
        def _clear_optimistic(_now=None) -> None:
            self._optimistic_target_map_id = None
            self.async_write_ha_state()

        async_call_later(self.hass, 10.0, _clear_optimistic)
        # MAPL will reflect the change on the next refresh; the s1p50
        # ping (Task 8b) AND the o:200 echo will trigger a re-poll
        # within seconds.


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
        map_obj = coordinator._cached_maps_by_id.get(map_id)
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
        map_obj = coordinator._cached_maps_by_id.get(map_id)
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
        map_obj = coordinator._cached_maps_by_id.get(map_id)
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


# ---------------------------------------------------------------------------
# WiFi archive picker — cross-map; drives DreameA2WifiSelectedCamera
# ---------------------------------------------------------------------------


class DreameA2WifiArchiveSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Cross-map WiFi heatmap archive picker.

    Lists every wifimap object found in the cloud, sorted newest-first,
    labeled ``[Map N] YYYY-MM-DD HH:MM``. Drives
    ``camera.dreame_a2_mower_wifi_heatmap_selected`` via
    ``coordinator._wifi_render_entry``.

    Options are re-enumerated on every coordinator update (because a
    button-triggered refresh may have pulled a new object from cloud).
    """

    _attr_has_entity_name = True
    _attr_name = "WiFi archive"
    _attr_icon = "mdi:wifi-marker"
    _attr_translation_key = "wifi_archive"
    _placeholder: str = "(no WiFi maps)"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_archive")
        self._attr_device_info = mower_device_info(coordinator)
        self._attr_current_option: str | None = self._placeholder
        self._attr_options: list[str] = [self._placeholder]
        # Cache of label → entry for reverse-lookup in async_select_option.
        self._label_to_entry: dict[str, "WifiArchiveEntry"] = {}

    @staticmethod
    def _format_option(entry: "WifiArchiveEntry") -> str:
        """Label '[Map N] YYYY-MM-DD HH:MM' when the matcher has tagged
        a map_id; fall back to '[Map ?]' for untagged legacy entries."""
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(entry.unix_ts, tz=timezone.utc).astimezone()
        raw = getattr(entry, "map_id", -1)
        try:
            mid = int(raw) if raw is not None else -1
        except (TypeError, ValueError):
            mid = -1
        if mid < 0:
            return f"[Map ?] {dt:%Y-%m-%d %H:%M}"
        # User-facing maps are 1-indexed everywhere else in the UI.
        return f"[Map {mid + 1}] {dt:%Y-%m-%d %H:%M}"

    def _rebuild_options(self) -> None:
        entries = list(getattr(self.coordinator, "_wifi_archive_index", []))
        entries.sort(key=lambda e: e.unix_ts, reverse=True)
        opts = [self._format_option(e) for e in entries]
        label_map: dict[str, "WifiArchiveEntry"] = {}
        for e, label in zip(entries, opts):
            label_map[label] = e
        if not opts:
            opts = [self._placeholder]
        # Reflect current selection.
        render = self.coordinator._wifi_render_entry
        cur: str
        if render is None:
            cur = opts[0]
        else:
            _, selected_obj = render
            cur = self._placeholder
            for label, entry in label_map.items():
                if entry.object_name == selected_obj:
                    cur = label
                    break
        self._attr_options = opts
        self._label_to_entry = label_map
        self._attr_current_option = cur if cur in opts else opts[0]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._rebuild_options()
        self._seed_initial_render()
        self.async_write_ha_state()

    def _seed_initial_render(self) -> None:
        """If the coordinator has no active wifi render but a real entry
        is selectable, point it at the current (top) option.

        Without this the dropdown's apparent default doesn't drive the
        camera — the user has to manually pick a different option, then
        the first one again, before anything renders.
        """
        if self.coordinator._wifi_render_entry is not None:
            return
        cur = self._attr_current_option
        if cur is None or cur == self._placeholder:
            return
        entry = self._label_to_entry.get(cur)
        if entry is None:
            return
        self.coordinator.set_wifi_render_entry(None, entry.object_name)

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self._rebuild_options()

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            self.coordinator.set_wifi_render_entry(None, None)
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        entry = self._label_to_entry.get(option)
        if entry is None:
            # Label map may be stale — rebuild and retry.
            self._rebuild_options()
            entry = self._label_to_entry.get(option)
        if entry is not None:
            # map_id intentionally None — correlation unsolved (see wifi-heatmap-todo.md).
            self.coordinator.set_wifi_render_entry(None, entry.object_name)
            self._attr_current_option = option
            self.async_write_ha_state()
            return
        LOGGER.warning("WifiArchiveSelect: unknown option %r", option)
