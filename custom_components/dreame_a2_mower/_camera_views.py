"""HTTP view endpoints for the camera platform."""
from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ._png import png_response
from .const import DOMAIN


class MapImageView(HomeAssistantView):
    """HTTP endpoint that serves the live / replay map PNG with explicit
    no-cache headers.

    GET ``/api/dreame_a2_mower/map.png`` (public — see Auth note below).

    This exists to work around Safari's aggressive image caching. HA's
    default ``/api/camera_proxy/`` view emits **no** ``Cache-Control``
    header, leaving caching policy to the browser. Chrome and Firefox are
    conservative and refetch when the URL's query string changes; Safari
    is sticky and serves the cached response anyway. By routing the map
    image through our own view we can emit ``Cache-Control: no-store,
    max-age=0`` and force every fetch to be a fresh round-trip.

    The coordinator is looked up from ``hass.data`` per-request, so
    config-entry reloads are picked up without re-registering the view.

    Auth: ``requires_auth = False``. The bundled dashboard's replay-map
    card uses a markdown ``<img>`` whose src points here; HA's frontend
    only auto-signs URLs surfaced via ``entity_picture`` on cards that
    consume it (picture-glance, etc.), and the markdown card does not.
    A plain ``<img>`` request carries no Authorization header so an
    auth-required view returns 401. The map PNG is a top-down render of
    the lawn — there's no PII. If your HA is internet-exposed and you
    don't want strangers fetching this, gate access at the reverse
    proxy / frontend level. (LiDAR PCD downloads remain auth-required.)
    """

    url = "/api/dreame_a2_mower/map.png"
    name = "api:dreame_a2_mower:map"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")

        map_id_raw = request.query.get("map_id")
        if map_id_raw is not None:
            try:
                map_id = int(map_id_raw)
            except (TypeError, ValueError):
                return web.Response(status=400, text="Bad map_id")
            png = coordinator._static_map_pngs_by_id.get(map_id)
        else:
            # Active-map (Main view) PNG.
            png = coordinator._main_view_png

        if not png:
            return web.Response(status=404, text="No map rendered yet")

        # Pragma: no-cache kept for Safari HTTP/1.0 cache stacks.
        return png_response(png, extra_headers={"Pragma": "no-cache"})


class WorkLogImageView(HomeAssistantView):
    """HTTP endpoint serving the Work Log camera's PNG with no-cache headers."""

    url = "/api/dreame_a2_mower/work_log.png"
    name = "api:dreame_a2_mower:work_log"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")
        # ?trail=false returns the no-trail base variant (for the replay
        # card's animation background — the SVG overlay draws the trail
        # itself, so the base must NOT pre-paint the trail or the user
        # sees both for a moment before animation starts).
        use_trail = request.query.get("trail", "true").lower() != "false"
        if not use_trail:
            png = coordinator._work_log_base_png
        else:
            # Fallback to active-map CLEAN base when no log is picked
            # (mirrors DreameA2WorkLogCamera._resolve_png) so the dashboard
            # card never shows a broken image just because the picker is on
            # placeholder. Uses _active_map_base_png (no trail, no M_PATH)
            # rather than _static_map_pngs_by_id (which has M_PATH).
            png = coordinator._work_log_png or coordinator._active_map_base_png
        if not png:
            return web.Response(status=204)
        return png_response(png)


class LidarSelectedPcdView(HomeAssistantView):
    """Serve the PCD bytes of the currently picker-selected LiDAR scan.

    Routed at /api/dreame_a2_mower/lidar/selected.pcd. The
    ``select.dreame_a2_mower_lidar_archive`` entity drives which scan is
    served via the coordinator's ``_lidar_render_entry`` field.

    Falls back to the active map's latest scan when nothing is explicitly
    selected.
    """

    url = "/api/dreame_a2_mower/lidar/selected.pcd"
    name = "api:dreame_a2_mower:lidar_selected_pcd"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        if not domain_data:
            return web.Response(status=503, text="Integration not loaded")
        coord = next(iter(domain_data.values()))
        render = coord._lidar_render_entry
        if render is None:
            # No selection — fall back to active map's latest.
            active = coord._active_map_id
            if active is None:
                return web.Response(status=404, text="No selection")
            archive = coord.lidar_archive_for(active)
            if archive is None:
                return web.Response(status=404, text="No archive")
            latest = await hass.async_add_executor_job(archive.latest)
            if latest is None:
                return web.Response(status=404, text="Archive empty")
            pcd_path = archive.root / latest.filename
        else:
            map_id, filename = render
            archive = coord.lidar_archive_for(map_id)
            if archive is None:
                return web.Response(status=404, text="No archive")
            pcd_path = archive.root / filename
        try:
            pcd_bytes = await hass.async_add_executor_job(pcd_path.read_bytes)
        except (FileNotFoundError, OSError):
            return web.Response(status=404, text="File missing")
        return web.Response(
            body=pcd_bytes,
            content_type="application/octet-stream",
            headers={"Cache-Control": "no-cache"},
        )


class LidarPcdDownloadView(HomeAssistantView):
    """HTTP endpoint that serves the most recent archived ``.pcd`` blob for a map.

    GET ``/api/dreame_a2_mower/lidar/{map_id}/latest.pcd`` (auth required).

    The coordinator is looked up from ``hass.data`` on each request so
    a config-entry reload is picked up without re-registering the view.
    Spec §5.9: auth required (creds discipline).

    Returns 404 with a brief explanation when:
      - ``map_id`` is not a valid integer,
      - no coordinator is registered yet,
      - the coordinator has no archive for that map_id,
      - the archive has no entries,
      - the on-disk .pcd file referenced by index.json is missing.
    """

    url = "/api/dreame_a2_mower/lidar/{map_id}/latest.pcd"
    name = "api:dreame_a2_mower:lidar_latest"
    requires_auth = True

    async def get(self, request: web.Request, map_id: str) -> web.StreamResponse:
        try:
            mid = int(map_id)
        except (ValueError, TypeError):
            return web.Response(status=404, text="Invalid map_id")
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        archive = None
        for coordinator in entries.values():
            cand = coordinator.lidar_archive_for(mid)
            if cand is not None:
                archive = cand
                break
        if archive is None:
            return web.Response(status=404, text="LiDAR archive not available")
        latest = await hass.async_add_executor_job(archive.latest)
        if latest is None:
            return web.Response(status=404, text="No LiDAR scans archived yet")
        path = archive.root / latest.filename
        if not path.is_file():
            return web.Response(status=404, text="Archived scan file missing")
        resp = web.FileResponse(path=path)
        resp.headers["Content-Type"] = "application/octet-stream"
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{latest.filename}"'
        )
        return resp
