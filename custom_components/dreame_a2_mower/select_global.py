"""Device-level (global) select entities, description table, and wire-value builder helpers for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a select platform.  It is imported by select.py (the real
platform entry).

Contains:
  - DreameA2ActionModeSelect  (device-level, uses mower_device_info)
  - DreameA2SettingSelect     (device-level, uses mower_device_info)
  - DreameA2WorkLogSelect     (device-level, uses mower_device_info)
  - DreameA2LidarArchiveSelect (device-level, uses mower_device_info)
  - DreameA2ActiveMapSelect   (device-level, uses mower_device_info)
  - DreameA2WifiArchiveSelect (device-level, uses mower_device_info)
  - SETTING_SELECTS table and its wire-value builder helpers
  - Language/option constants (VOICE_LANGUAGE_NAMES, TEXT_LANGUAGE_NAMES, etc.)
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .wifi_archive_store import WifiArchiveEntry

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
from .const import DOMAIN, LOGGER, WORK_LOG_PLACEHOLDER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode, MowerState
from ._select_base import DreameA2SettingsSelectDescription


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
    # NOTE — parent-level `mowing_efficiency` removed 2026-05-15.
    # The PRE family on g2408 doesn't accept cloud writes (see memory
    # ``project_g2408_iobroker_negatives``), so this entity's
    # cfg_key="PRE" write was a phantom that silently failed. The
    # value source ``s.pre_mowing_efficiency`` also reflected only the
    # last active map's value — misleading on a multi-map device.
    # Replaced by per-map ``DreameA2MapMowingEfficiencySelect``
    # (read-only, reads from PRE shadow). Symmetric to the EdgeMaster
    # removal.

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
    _placeholder: str = WORK_LOG_PLACEHOLDER
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
        from .session_card import format_session_label

        eligible = [s for s in sessions if not getattr(s, "still_running", False)]
        eligible = sorted(eligible, key=lambda s: s.end_ts, reverse=True)[: self._max_options]
        labels: list[str] = [self._placeholder]
        mapping: dict[str, str] = {}
        for s in eligible:
            label = format_session_label(s)
            if label in mapping:
                label = f"{label} [{(getattr(s, 'md5', '') or '')[:6]}]"
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
            # Picking the placeholder clears the work-log camera AND the
            # picked-session summary so all per-session cards hide.
            self.coordinator._work_log_png = None
            self.coordinator._work_log_base_png = None
            self.coordinator._picked_session_summary = None
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
            for map_id, m in sorted(self.coordinator.cloud_state.maps_by_id.items())
        ]

    @property
    def current_option(self) -> str | None:
        # Optimistic UI: when a write is in flight (firmware not yet
        # committed via MAPL), show the user's just-selected target.
        if self._optimistic_target_map_id is not None:
            target = self._optimistic_target_map_id
            m = self.coordinator.cloud_state.maps_by_id.get(target)
            if m is not None:
                return self._label_for(target, m)
        # Default: read from MAPL-derived state.
        active = self.coordinator._active_map_id
        if active is None:
            return None
        m = self.coordinator.cloud_state.maps_by_id.get(active)
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
        for map_id, m in self.coordinator.cloud_state.maps_by_id.items():
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
# F3.2.1: Action-mode select
# ---------------------------------------------------------------------------

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
        # Same broadcast-render-broadcast dance as async_select_option:
        # without the re-render here, the dropdown shows the restored
        # mode (e.g. EDGE) but the camera image stays whatever was
        # rendered at coordinator-init time (typically the default
        # ALL_AREAS stripe preview). The first render after restoration
        # is what makes the initial dashboard view match the restored
        # selection. See feedback_camera_image_refresh_pattern.
        render_fn = getattr(self.coordinator, "_render_main_view", None)
        if callable(render_fn):
            await render_fn()
            self.coordinator.async_update_listeners()

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.action_mode.value

    async def async_select_option(self, option: str) -> None:
        """Update coordinator.data.action_mode, re-render, and broadcast.

        The broadcast-render-broadcast triplet is load-bearing. The
        camera entity rotates its access_token (which busts the
        browser's image-URL cache) only when `_main_view_png` bytes
        change AND a coordinator broadcast fires. Just setting the new
        state isn't enough: the render hasn't run yet, so the camera
        sees the new action_mode but unchanged PNG → no token rotation
        → the browser keeps the stale image until the next telemetry-
        driven render+broadcast cycle (≈1-2 minutes).

        Fix pattern (see also `feedback_camera_image_refresh_pattern`):
          1. async_set_updated_data — broadcasts the new field value
          2. await _render_main_view — produces the new PNG
          3. async_update_listeners — broadcasts again so the camera
             entity's _handle_coordinator_update fires, observes the
             PNG change, and rotates its access_token.
        """
        new_mode = ActionMode(option)
        new_state = dataclasses.replace(self.coordinator.data, action_mode=new_mode)
        self.coordinator.async_set_updated_data(new_state)
        render_fn = getattr(self.coordinator, "_render_main_view", None)
        if callable(render_fn):
            await render_fn()
            self.coordinator.async_update_listeners()


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
