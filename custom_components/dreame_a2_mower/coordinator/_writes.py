"""writes mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..inventory.loader import load_inventory
from ..live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from ..live_map.finalize import decide as _finalize_decide
from ..live_map.state import LiveMapState
from ..mower.actions import ACTION_TABLE, MowerAction
from ..mower.property_mapping import PROPERTY_MAPPING, resolve_field
from ..mower.state import ChargingStatus, MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_NOTIFICATION_MAP,
    S2P2_NOVEL_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
    _consumable_pct_remaining,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _WritesMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def write_schedule(
        self,
        new_slots: tuple[Any, ...] | list[Any],
    ) -> bool:
        """Push a new SCHEDULE blob to the cloud via write_chunked_key.

        new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
        source of truth; .raw_blob_b64 is ignored — re-encoded). Bumps
        the schedule version by 1 and refreshes cloud_state on success.
        """
        from ..protocol.schedule import build_schedule_set_value

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule: cloud client not ready")
            return False
        cs = self.cloud_state
        current_v = cs.schedule.version if cs is not None else 0
        new_v = current_v + 1
        json_value = build_schedule_set_value(tuple(new_slots), version=new_v)
        LOGGER.info(
            "[schedule-write] v %d → %d, len(d)=%d, json_len=%d",
            current_v, new_v, len(new_slots), len(json_value),
        )
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SCHEDULE", json_value,
            )
            if not ok:
                LOGGER.warning("[schedule-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    async def write_ai_human_enabled(self, enabled: bool) -> bool:
        """Toggle AI_HUMAN.0 (Capture Photos AI Obstacles) via write_chunked_key.

        Cloud value is a JSON-encoded boolean string (`"true"` / `"false"`).
        Privacy auth is gated app-side; here we trust that AI_HUMAN.0
        being writable means the user has accepted the policy in the app.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_ai_human_enabled: cloud client not ready")
            return False
        value = '"true"' if enabled else '"false"'
        LOGGER.info("[ai-human-write] AI_HUMAN.0 → %s", value)
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "AI_HUMAN", value,
            )
            if not ok:
                LOGGER.warning("[ai-human-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    def _fetch_fresh_settings_blob(self) -> list[dict[str, Any]] | None:
        """Pull SETTINGS chunks fresh from the cloud and return the
        decoded list. Returns None if the fetch fails or the response
        is malformed.

        Runs in the executor (called via async_add_executor_job from
        write_settings). Targets only the SETTINGS keys instead of the
        full empty-batch dump — one HTTP round-trip, ~1-2KB response.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return None
        # Optimistic key list — we only need the chunks the cloud
        # actually has. We over-fetch up to .8 (8 chunks = 8KB total
        # blob) plus .info; missing keys come back as None and are
        # filtered by the chunk-walk below.
        keys = [f"SETTINGS.{i}" for i in range(8)] + ["SETTINGS.info"]
        try:
            response = self._cloud.get_batch_device_datas(keys)
        except Exception as ex:  # pragma: no cover — defensive
            LOGGER.debug("[settings-write] fresh fetch raised: %s", ex)
            return None
        if not isinstance(response, dict):
            return None
        info = response.get("SETTINGS.info")
        if info is None:
            return None
        try:
            total = int(info)
        except (TypeError, ValueError):
            return None
        chunks: list[str] = []
        i = 0
        while True:
            chunk = response.get(f"SETTINGS.{i}")
            if chunk is None:
                break
            chunks.append(str(chunk))
            i += 1
        if not chunks:
            return None
        full = "".join(chunks)[:total]
        import json as _json
        try:
            parsed = _json.loads(full)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None

    async def write_settings(self, *, map_id: int, field: str, value: Any) -> bool:
        """Push one SETTINGS field change to the cloud.

        Pre-write fresh-fetch: pulls the current SETTINGS blob from the
        cloud right before the write so the resulting blob carries
        whatever values the app (or another HA instance) most recently
        saved. Without this step, HA's read-modify-write would be based
        on the last 2-min poll's snapshot — every other field on every
        map would be stamped back to its stale value, clobbering anything
        the app changed in the meantime.

        Read-modify-write mutates the target field on every entry that
        carries the target map_id; other fields and other maps are left
        untouched. Serializes against _chunked_write_lock so concurrent
        writes can't race against the same fresh fetch.

        Returns True iff cloud accepted (code=0). Triggers a cloud_state
        refresh on success so the local view reflects what landed.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_settings: cloud client not ready")
            return False
        from ..protocol.settings import parse_settings_batch, write_setting

        async with self._chunked_write_lock:
            # Always try a fresh fetch first so the RMW is on cloud-current data.
            fresh_raw = await self.hass.async_add_executor_job(
                self._fetch_fresh_settings_blob,
            )
            if fresh_raw is not None:
                settings_raw = fresh_raw
                # Mirror onto cloud_state so subsequent reads see fresh values.
                # Defensive: cloud_state may not exist yet if write happens
                # before the first periodic refresh.
                cs = self.cloud_state
                if cs is not None:
                    self.cloud_state = dataclasses.replace(
                        cs, settings=parse_settings_batch(fresh_raw),
                    )
            else:
                # Fresh fetch failed; fall back to the cached state and accept
                # the higher-stale-cache risk for this one write.
                cs = self.cloud_state
                if cs is None:
                    LOGGER.warning(
                        "write_settings: cloud_state empty and fresh fetch failed"
                    )
                    return False
                settings_raw = cs.settings.raw
                LOGGER.warning(
                    "[settings-write] fresh fetch failed; falling back to cached state"
                )
            try:
                new_raw = write_setting(
                    settings_raw, map_id=map_id, field=field, value=value,
                )
            except KeyError as ex:
                LOGGER.warning("write_settings: KeyError %s", ex)
                return False
            import json as _json
            json_value = _json.dumps(new_raw, separators=(",", ":"))
            LOGGER.info(
                "[settings-write] field=%s map=%d value=%r json_len=%d (fresh=%s)",
                field, map_id, value, len(json_value), fresh_raw is not None,
            )
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SETTINGS", json_value,
            )
            if not ok:
                LOGGER.warning("[settings-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    async def write_setting(
        self,
        cfg_key: str,
        new_full_value: Any,
        field_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Write a settings value to the mower via the CFG write path.

        The entity layer (F4.6.x) is responsible for constructing the full
        wire-level value (e.g. the complete DND list ``[enabled, start_min,
        end_min]``) and passing it as ``new_full_value``.  This method relays
        it to the right ``cloud_client`` method without interpreting the value.

        ``cfg_key`` must be one of the known CFG key strings (``CLS``, ``VOL``,
        ``LANG``, ``DND``, ``WRP``, ``LOW``, ``BAT``, ``LIT``, ``ATA``,
        ``REC``) or the special key ``PRE`` (full-array write via
        ``cloud_client.set_pre``).

        Optimistic state update (optional):
          If ``field_updates`` is provided it must be a ``{field_name: value}``
          dict whose keys are valid ``MowerState`` field names.  The state is
          updated optimistically before the cloud call and reverted if the cloud
          call fails.  When ``field_updates`` is ``None`` (the default) no
          optimistic update is applied — the entity layer handles its own
          optimistic state.

        Returns ``True`` on cloud success, ``False`` on failure.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_setting %s: cloud client not ready", cfg_key)
            return False

        if cfg_key not in self._CFG_SINGLE_KEYS and cfg_key != "PRE":
            LOGGER.warning("write_setting: unknown cfg_key %r", cfg_key)
            return False

        # Optimistic update — snapshot state and apply field_updates now.
        prior_state = self.data
        if field_updates:
            try:
                self.async_set_updated_data(
                    dataclasses.replace(self.data, **field_updates)
                )
            except TypeError as ex:
                LOGGER.warning(
                    "write_setting %s: invalid field_updates %r — %s; skipping optimistic update",
                    cfg_key, field_updates, ex,
                )
                # Don't revert — no update was applied; just proceed with the write.

        # Dispatch to the right cloud_client method.
        success = await self._dispatch_cfg_write(cfg_key, new_full_value)

        if not success:
            LOGGER.warning(
                "write_setting %s=%r: cloud write failed; reverting optimistic update",
                cfg_key, new_full_value,
            )
            if field_updates and self.data != prior_state:
                self.async_set_updated_data(prior_state)

        return success

    async def _dispatch_cfg_write(self, cfg_key: str, value: Any) -> bool:
        """Route a CFG write to the appropriate cloud_client method.

        All CFG single-key writes use ``cloud_client.set_cfg``.
        ``PRE`` uses ``cloud_client.set_pre`` (full-array write).

        Runs the blocking I/O in the executor per spec §3.
        """
        if cfg_key == "PRE":
            if not isinstance(value, list):
                LOGGER.warning(
                    "_dispatch_cfg_write PRE: expected list, got %r",
                    type(value).__name__,
                )
                return False
            return await self.hass.async_add_executor_job(
                self._cloud.set_pre, value
            )

        # All other CFG keys — single-key set via set_cfg().
        return await self.hass.async_add_executor_job(
            self._cloud.set_cfg, cfg_key, value
        )

    async def dispatch_action(
        self, action: MowerAction, parameters: dict[str, Any] | None = None
    ) -> None:
        """Dispatch a typed mower action.

        Looks up the action in ACTION_TABLE. local_only actions are handled
        internally (currently only FINALIZE_SESSION — its actual
        implementation lands in F5). Cloud actions go via the routed path
        (s2 aiid=50) since the direct (siid, aiid) call returns 80001 on
        g2408.

        For actions that have a ``routed_o`` opcode, uses
        ``cloud_client.routed_action(op, extra)`` — the working path on g2408.
        For actions that have only ``siid``/``aiid`` (no opcode), falls back
        to a direct ``cloud_client.action(siid, aiid)`` call.

        Errors and timeouts are logged but not raised — the integration
        keeps going. F4+ surfaces persistent failures via diagnostic
        sensors.
        """
        parameters = parameters or {}
        entry = ACTION_TABLE.get(action)
        if entry is None:
            LOGGER.warning("dispatch_action: unknown action %r", action)
            return

        if entry.get("local_only"):
            # FINALIZE_SESSION — integration-internal action; routes to the
            # finalize-incomplete path (F5.10.1).  Forces an "(incomplete)"
            # archive of whatever the live_map currently holds, clears
            # pending_session_* state, and calls live_map.end_session().
            # Safe to call even when no session is active (no-ops cleanly).
            if action == MowerAction.FINALIZE_SESSION:
                import time as _time
                LOGGER.info(
                    "dispatch_action: FINALIZE_SESSION — running finalize-incomplete path"
                )
                await self._run_finalize_incomplete(int(_time.time()))
            else:
                LOGGER.info(
                    "dispatch_action: local-only %s — no implementation yet", action.name
                )
            return

        # cfg_toggle_field path — reads the named MowerState field, computes
        # the toggled (boolean NOT) value, and calls write_setting.
        # Used for LOCK_BOT_TOGGLE → CFG key CLS.  This branch runs before
        # the cloud-client path; write_setting itself handles executor dispatch.
        cfg_toggle_field = entry.get("cfg_toggle_field")
        if cfg_toggle_field is not None:
            cfg_key = entry.get("cfg_key")
            if not cfg_key:
                LOGGER.warning(
                    "dispatch_action %s: cfg_toggle_field set but cfg_key missing — skipped",
                    action.name,
                )
                return
            current = getattr(self.data, cfg_toggle_field, None)
            toggled = not bool(current)
            LOGGER.info(
                "dispatch_action: %s toggle %s=%r → %r via write_setting(%r)",
                action.name, cfg_toggle_field, current, toggled, cfg_key,
            )
            await self.write_setting(
                cfg_key,
                int(toggled),  # CLS wire value is int {0, 1}
                field_updates={cfg_toggle_field: toggled},
            )
            return

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("dispatch_action: cloud client not ready; %s deferred", action.name)
            return

        routed_o = entry.get("routed_o")
        payload_fn = entry.get("payload_fn")

        # START_EDGE_MOW default-contour resolution. When the caller doesn't
        # specify ``contour_ids``, we want to edge every zone's outer
        # perimeter (entries in the cached map's contour table whose
        # second-int = 0). This matches the Dreame app's behaviour and
        # avoids the firmware's "edge every contour including merged
        # sub-zone seams" mode that drains the edge-mode budget on
        # invisible internal segments and triggers FTRTS.
        # See docs/research/g2408-protocol.md §4.6 (2026-05-05 finding).
        if action == MowerAction.START_EDGE_MOW and not parameters.get("contour_ids"):
            map_data = self.cloud_state.maps_by_id.get(self._active_map_id)
            avail = getattr(map_data, "available_contour_ids", ()) if map_data else ()
            outer = [list(cid) for cid in avail if len(cid) == 2 and cid[1] == 0]
            if outer:
                parameters = {**parameters, "contour_ids": outer}
                LOGGER.info(
                    "dispatch_action: START_EDGE_MOW defaulting contour_ids to "
                    "all outer perimeters %s (from %d cached contours)",
                    outer, len(avail),
                )
            # else: fall through to _edge_mow_payload's [[1, 0]] last-resort
            # fallback (map data not loaded yet on this start).

        try:
            extra = payload_fn(parameters) if payload_fn else None
        except ValueError as ex:
            LOGGER.warning("dispatch_action %s: payload error: %s", action.name, ex)
            return

        LOGGER.info(
            "dispatch_action: %s via routed op=%s extra=%s",
            action.name, routed_o, extra,
        )

        try:
            if routed_o is not None:
                # Action opcode path — works on g2408 (cfg_action.call_action_op).
                await self.hass.async_add_executor_job(
                    self._cloud.routed_action, routed_o, extra
                )
            else:
                # Direct siid/aiid path — returns 80001 on g2408 for most actions,
                # but included for completeness (PAUSE/DOCK/STOP/etc. may succeed
                # via this path on some firmware or cloud configurations).
                siid = entry.get("siid")
                aiid = entry.get("aiid")
                if siid is None or aiid is None:
                    LOGGER.warning(
                        "dispatch_action: %s has no routed_o and no siid/aiid — skipped",
                        action.name,
                    )
                    return
                await self.hass.async_add_executor_job(
                    self._cloud.action, siid, aiid
                )
        except Exception as ex:
            LOGGER.warning("dispatch_action %s failed: %s", action.name, ex)

    # ------------------------------------------------------------------
    # Unified mowing-mode wrappers (used by DreameA2MowingModeSelect)
    # ------------------------------------------------------------------

    async def _ensure_active_map(self, map_id: int) -> None:
        """Switch to map_id via SET_ACTIVE_MAP (op=200) if it isn't already active.

        No-op when the requested map is already active or when
        _active_map_id is None (not yet polled — single-map devices never
        set it, so we fall through and let the firmware pick).  Logs a
        warning and continues on failure so the subsequent mow command
        still fires against whatever map is currently active.
        """
        current = self._active_map_id
        if current is None or current == map_id:
            return
        try:
            await self.dispatch_action(
                MowerAction.SET_ACTIVE_MAP, {"map_id": map_id}
            )
        except Exception as ex:
            LOGGER.warning(
                "start_mowing: SET_ACTIVE_MAP(map_id=%d) failed: %s — "
                "proceeding with current active map %s",
                map_id,
                ex,
                current,
            )

    async def start_mowing_all_areas(self, *, map_id: int) -> None:
        """Start all-areas mow on the given map (op=100).

        Switches the active map first if needed.  The all-areas TASK
        envelope doesn't carry a map_id itself; op=200 SET_ACTIVE_MAP
        must be sent first when the requested map isn't already active.
        """
        await self._ensure_active_map(map_id)
        await self.dispatch_action(MowerAction.START_MOWING, {})

    async def start_mowing_edge(self, *, map_id: int) -> None:
        """Start edge mow on the given map (op=101)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(MowerAction.START_EDGE_MOW, {})

    async def start_mowing_zone(self, *, map_id: int, zone_id: int) -> None:
        """Start zone mow for a specific zone on the given map (op=102)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_ZONE_MOW, {"zones": [zone_id]}
        )

    async def start_mowing_spot(self, *, map_id: int, spot_id: int) -> None:
        """Start spot mow for a specific spot on the given map (op=103)."""
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_SPOT_MOW, {"spots": [spot_id]}
        )

