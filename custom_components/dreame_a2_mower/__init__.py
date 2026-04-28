"""The Dreame A2 Mower integration.

Per spec §3 layer 3 — this is the HA glue layer. Wires the typed
domain model (mower/) to Home Assistant's coordinator + entity
infrastructure.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS, LOG_NOVEL_PROPERTY, LOG_NOVEL_VALUE, LOG_NOVEL_KEY, LOG_NOVEL_KEY_SESSION_SUMMARY
from .observability import NovelLogBuffer
from .services import async_register_services, async_unregister_services


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Dreame A2 Mower integration from a config entry."""
    LOGGER.info("Setting up %s integration", DOMAIN)

    # F1: coordinator setup is added in F1.4. Stub for now so the
    # integration can register without errors.
    from .coordinator import DreameA2MowerCoordinator

    coordinator = DreameA2MowerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # F6.9.1: install the NOVEL log-line ring buffer so download_diagnostics
    # can include the recent novelty trail. Attaches to the integration's
    # package logger so unrelated log lines aren't captured.
    novel_log = NovelLogBuffer(
        maxlen=200,
        prefixes=(
            LOG_NOVEL_PROPERTY,
            LOG_NOVEL_VALUE,
            LOG_NOVEL_KEY,
            LOG_NOVEL_KEY_SESSION_SUMMARY,
        ),
    )
    log_handler = novel_log.as_handler()
    package_logger = logging.getLogger("custom_components.dreame_a2_mower")
    package_logger.addHandler(log_handler)
    coordinator.novel_log = novel_log
    coordinator._novel_log_handler = log_handler

    # F7.5.1: register the bundled WebGL LiDAR card at /dreame_a2_mower/<file>.
    # Done once per HA process; reloads are no-op. Users add a Lovelace
    # resource pointing at /dreame_a2_mower/dreame-a2-lidar-card.js
    # (type: module) to make the custom:dreame-a2-lidar-card type available.
    if not getattr(hass, "_dreame_a2_static_registered", False):
        from pathlib import Path as _Path
        _www = _Path(__file__).parent / "www"
        if _www.is_dir():
            try:
                from homeassistant.components.http import StaticPathConfig
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(f"/{DOMAIN}", str(_www), False)]
                )
            except ImportError:
                try:
                    await hass.http.async_register_static_paths(
                        [(f"/{DOMAIN}", str(_www), False)]
                    )
                except Exception:
                    LOGGER.warning(
                        "Static-path registration for LiDAR card skipped "
                        "(unsupported HA version). Copy %s into /config/www/ "
                        "manually if you want the bundled card.", _www,
                    )
        hass._dreame_a2_static_registered = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register integration-wide services. Idempotent — async_register_services
    # checks if services are already registered and no-ops if so.
    if not hass.services.has_service(DOMAIN, "mow_zone"):
        await async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    LOGGER.info("Unloading %s integration", DOMAIN)
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        handler = getattr(coordinator, "_novel_log_handler", None)
        if handler is not None:
            logging.getLogger("custom_components.dreame_a2_mower").removeHandler(handler)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            async_unregister_services(hass)
    return unload_ok
