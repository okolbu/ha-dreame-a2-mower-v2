"""The Dreame A2 Mower integration.

Per spec §3 layer 3 — this is the HA glue layer. Wires the typed
domain model (mower/) to Home Assistant's coordinator + entity
infrastructure.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_SESSION_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    LOG_NOVEL_KEY,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
    PLATFORMS,
)
from .observability import NovelLogBuffer
from .services import async_register_services, async_unregister_services

# Module-level sentinel so static path registration happens only once per HA
# process (survives integration reloads).
_static_registered: bool = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Dreame A2 Mower integration from a config entry."""
    LOGGER.info("Setting up %s integration", DOMAIN)
    LOGGER.warning(
        "%s: cloud-discovery refactor introduced a unified CloudState "
        "container (Tasks 1-17). Old session-archive entries from prior "
        "schemas are skipped on first launch and rebuilt by probe-log "
        "replay. If lifetime totals look stale, trigger a manual cloud "
        "refresh or wait for the 2-min `_refresh_cloud_state` timer.",
        DOMAIN,
    )

    # F1: coordinator setup is added in F1.4. Stub for now so the
    # integration can register without errors.
    from .coordinator import DreameA2MowerCoordinator
    from .wifi_archive_store import WifiArchiveStore
    from pathlib import Path as _Path

    # Pre-load the wifi archive index via executor so the coordinator
    # __init__ (sync) never touches the disk directly.  The store is
    # constructed here solely for the one-shot index read; the coordinator
    # creates its own store instance for subsequent writes.
    _wifi_archive_dir = _Path(hass.config.path(DOMAIN, "wifi_archive"))
    _wifi_store_tmp = WifiArchiveStore(_wifi_archive_dir)
    _wifi_index = await hass.async_add_executor_job(_wifi_store_tmp.load_index)

    coordinator = DreameA2MowerCoordinator(hass, entry, wifi_index=_wifi_index)

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

    # F-novel-persist: load the persistent novel-observations file into
    # the watchdog's seen-sets so post-restart "first observation" logs
    # only fire for things never observed before by THIS mower. Then
    # attach the store so subsequent novel observations append exactly
    # one line per first-seen token. See spec
    # docs/superpowers/specs/2026-05-16-persistent-novel-log-design.md.
    from pathlib import Path as _Path
    from .observability import PersistentNovelStore as _PNS

    _novel_path = _Path(hass.config.path("dreame_a2_mower")) / "novel_observations.jsonl"
    _novel_store = _PNS(_novel_path)
    try:
        _replayed = await _novel_store.load(coordinator.novel_registry, hass=hass)
        # WARNING level (not INFO) so the line surfaces in HA's
        # system_log/list which only returns WARNING+. Once-per-setup,
        # so log noise is bounded; the count gives a quick health
        # signal that the persistent catalog is alive.
        LOGGER.warning(
            "[novel] replayed %d known observations from %s",
            _replayed, _novel_path,
        )
    except Exception:
        LOGGER.exception(
            "[novel] failed to load %s; novel-tracking continues "
            "in-memory only this session", _novel_path,
        )
    # Pass hass.loop so the registry can use run_coroutine_threadsafe
    # when scheduling appends from paho's MQTT-callback thread (which
    # has no running event loop of its own). Without this, append
    # coroutines get RuntimeWarning: "coroutine was never awaited"
    # and silently drop on every MQTT-driven novel observation.
    coordinator.novel_registry.attach_store(_novel_store, loop=hass.loop)
    coordinator._novel_store = _novel_store  # keep reference for unload/diag

    # F7.5.1: register the bundled WebGL LiDAR card at /dreame_a2_mower/<file>.
    # Done once per HA process; reloads are no-op. Users add a Lovelace
    # resource pointing at /dreame_a2_mower/dreame-a2-lidar-card.js
    # (type: module) to make the custom:dreame-a2-lidar-card type available.
    global _static_registered
    if not _static_registered:
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
                    await hass.http.async_register_static_paths(  # type: ignore[arg-type]
                        [(f"/{DOMAIN}", str(_www), False)]
                    )
                except Exception:
                    LOGGER.warning(
                        "Static-path registration for LiDAR card skipped "
                        "(unsupported HA version). Copy %s into /config/www/ "
                        "manually if you want the bundled card.", _www,
                    )
        # NOTE: the live-image card (dreame-mower-live-image-card.js) is
        # SERVED by the static path above but is NOT auto-registered via
        # frontend.add_extra_js_url. That auto-registration proved
        # unreliable — on YAML-mode dashboards the card rendered a red
        # "Configuration error" because it never landed in the dashboard's
        # element registry (customElements.get() returned undefined at
        # render time). The bundled dashboard uses picture-entity instead;
        # users who want the faster card add it as a Lovelace resource
        # manually (see README).
        _static_registered = True

    # F7.7.1: apply runtime archive-cap changes without reloading the entry.
    async def _options_updated(hass_arg: HomeAssistant, entry_arg: ConfigEntry) -> None:
        coord = hass_arg.data.get(DOMAIN, {}).get(entry_arg.entry_id)
        if coord is None:
            return
        # T12: apply retention/size-cap changes to all per-map archives.
        new_retention = int(entry_arg.options.get(
            CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP,
        ))
        new_max_bytes = (
            int(entry_arg.options.get(
                CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB,
            )) * 1024 * 1024
        )
        if hasattr(coord, "_lidar_archive_retention"):
            coord._lidar_archive_retention = new_retention
        if hasattr(coord, "_lidar_archive_max_bytes"):
            coord._lidar_archive_max_bytes = new_max_bytes
        for _arch in getattr(coord, "lidar_archives", {}).values():
            _arch.set_retention(new_retention)
            _arch.set_max_bytes(new_max_bytes)
        if (
            hasattr(coord, "session_archive")
            and coord.session_archive is not None
            and hasattr(coord.session_archive, "set_retention")
        ):
            coord.session_archive.set_retention(
                int(entry_arg.options.get(
                    CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP,
                ))
            )

    entry.async_on_unload(entry.add_update_listener(_options_updated))

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
        # Disconnect MQTT client first so paho thread + TCP socket are
        # released before platform unload tears down entities the
        # callback path writes into. disconnect() is sync — run in
        # executor to keep async_unload_entry non-blocking.
        mqtt = getattr(coordinator, "_mqtt", None)
        if mqtt is not None:
            await hass.async_add_executor_job(mqtt.disconnect)
        handler = getattr(coordinator, "_novel_log_handler", None)
        if handler is not None:
            logging.getLogger("custom_components.dreame_a2_mower").removeHandler(handler)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            async_unregister_services(hass)
    return unload_ok
