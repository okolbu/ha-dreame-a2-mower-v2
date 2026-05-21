"""WiFi heatmap camera entities — selected and per-map."""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator


class DreameA2WifiSelectedCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Renders whichever WiFi heatmap the archive picker selects.

    Driven by ``select.dreame_a2_mower_wifi_archive`` (DreameA2WifiArchiveSelect)
    via ``coordinator._wifi_render_entry``.  Body is loaded on demand from
    ``coordinator._wifi_archive_store``.

    The camera key ``wifi_heatmap_selected`` in translations corresponds to
    entity_id ``camera.dreame_a2_mower_wifi_heatmap_selected``.

    Flip toggles are read at render time from:
        ``input_boolean.dreame_a2_mower_wifi_flip_x``
        ``input_boolean.dreame_a2_mower_wifi_flip_y``
    State changes on those entities bust the entity-picture cache automatically.
    """

    _FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
    _FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"

    _attr_has_entity_name = True
    _attr_name = "WiFi heatmap (selected)"
    _attr_content_type = "image/png"
    _attr_translation_key = "wifi_heatmap_selected"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_selected")
        self._attr_device_info = mower_device_info(coordinator)

    def _resolve_decoded(self) -> dict | None:
        """Return decoded wifi map body for the selected entry.

        Reads from the coordinator's in-memory body cache — no disk I/O.
        The cache is populated asynchronously by
        ``coordinator._async_load_wifi_body`` which is scheduled via
        ``async_create_task`` whenever ``set_wifi_render_entry`` is called
        with a new object_name.  Returns None when no entry is selected or
        the body has not yet been loaded (camera will be unavailable until
        the background load completes and triggers a listener update).
        """
        render = self.coordinator._wifi_render_entry
        if render is None:
            return None
        _map_id, obj_name = render
        if not obj_name:
            return None
        return self.coordinator._get_wifi_body_cached(obj_name)

    @property
    def available(self) -> bool:
        return self._resolve_decoded() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        flip_x = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_X_ENTITY, "on")
        )
        flip_y = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_Y_ENTITY, "on")
        )
        from .wifi_map_render import render_wifi_map_png
        return await self.hass.async_add_executor_job(
            lambda: render_wifi_map_png(decoded, flip_x=flip_x, flip_y=flip_y)
        )

    @property
    def entity_picture(self) -> str | None:
        """Cache-bust URL based on selected entry + data hash."""
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        import hashlib
        render = self.coordinator._wifi_render_entry
        if render is not None:
            key = f"{render[0]}:{render[1]}"
        else:
            active = self.coordinator._active_map_id
            key = f"active:{active}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = super().entity_picture
        if base is None:
            return None
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to flip toggle state changes to bust the image cache."""
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_state_change_event

        @callback
        def _flip_changed(_event) -> None:
            self.async_update_token()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._FLIP_X_ENTITY, self._FLIP_Y_ENTITY],
                _flip_changed,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token only when the selection changes.

        The decoded body is freshly loaded from disk on every call, so its
        object id() is meaningless — keying on it would rotate the token
        on every coordinator update.
        """
        render = self.coordinator._wifi_render_entry
        if render != getattr(self, "_last_seen_key", object()):
            self._last_seen_key = render
            self.async_update_token()
        super()._handle_coordinator_update()


class DreameA2WifiPerMapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Per-map WiFi heatmap camera (v1.0.10a6+).

    Renders the *newest* archive entry whose tagged ``map_id`` matches
    this camera's ``_map_id`` — i.e. one camera per logical map. The
    matching is driven by the fingerprint correlator
    (``wifi_match.match_heatmap_to_session``), with the
    geometry-inference path still serving as fallback for entries the
    fingerprint matcher cannot score.

    Unavailable while no tagged entry exists for this map (e.g. a
    brand-new map the cloud hasn't generated a heatmap for yet).
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _attr_translation_key = "wifi_heatmap_per_map"

    _FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
    _FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "wifi_heatmap"
        )
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_name = "WiFi heatmap"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=map_name
        )

    def _resolve_entry(self):
        """Newest archive entry tagged with this camera's map_id, or None."""
        index = getattr(self.coordinator, "_wifi_archive_index", None) or []
        matches = [e for e in index if int(getattr(e, "map_id", -1)) == self._map_id]
        if not matches:
            return None
        matches.sort(key=lambda e: int(e.unix_ts), reverse=True)
        return matches[0]

    def _resolve_decoded(self) -> dict | None:
        entry = self._resolve_entry()
        if entry is None:
            return None
        store = getattr(self.coordinator, "_wifi_archive_store", None)
        if store is None:
            return None
        return store.load_body(entry.object_name)

    @property
    def available(self) -> bool:
        return self._resolve_entry() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        flip_x = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_X_ENTITY, "on")
        )
        flip_y = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_Y_ENTITY, "on")
        )
        from .wifi_map_render import render_wifi_map_png
        return await self.hass.async_add_executor_job(
            lambda: render_wifi_map_png(decoded, flip_x=flip_x, flip_y=flip_y)
        )

    @property
    def entity_picture(self) -> str | None:
        entry = self._resolve_entry()
        if entry is None:
            return None
        import hashlib
        key = f"{self._map_id}:{entry.object_name}:{entry.unix_ts}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = super().entity_picture
        if base is None:
            return None
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to flip toggle state changes to bust the image cache."""
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_state_change_event

        @callback
        def _flip_changed(_event) -> None:
            self.async_update_token()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._FLIP_X_ENTITY, self._FLIP_Y_ENTITY],
                _flip_changed,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        entry = self._resolve_entry()
        key = entry.object_name if entry is not None else None
        if key != getattr(self, "_last_seen_key", object()):
            self._last_seen_key = key
            self.async_update_token()
        super()._handle_coordinator_update()
