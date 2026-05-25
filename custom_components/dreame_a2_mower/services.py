"""Service handlers for the Dreame A2 Mower integration.

Per spec §5.2: actions live in service calls; entities should be state.
This module wires the services declared in services.yaml to the
action-dispatch helpers in mower/actions.py (built in F3.5).

The handlers are registered in __init__.py via async_setup_entry, and
unregistered in async_unload_entry.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode

# Service names — keep in sync with services.yaml
SERVICE_SET_ACTIVE_SELECTION = "set_active_selection"
SERVICE_MOW_ZONE = "mow_zone"
SERVICE_MOW_EDGE = "mow_edge"
SERVICE_MOW_SPOT = "mow_spot"
SERVICE_RECHARGE = "recharge"
SERVICE_FIND_BOT = "find_bot"
SERVICE_LOCK_BOT = "lock_bot"
SERVICE_SUPPRESS_FAULT = "suppress_fault"
SERVICE_FINALIZE_SESSION = "finalize_session"
SERVICE_REPLAY_SESSION = "replay_session"
SERVICE_SHOW_LIDAR_FULLSCREEN = "show_lidar_fullscreen"
SERVICE_DUMP_MAP_DIAGNOSTICS = "dump_map_diagnostics"
SERVICE_DISCOVER_CLOUD_API = "discover_cloud_api"
SERVICE_SET_SCHEDULE_PLANS = "set_schedule_plans"
SERVICE_REFRESH_CLOUD_STATE = "refresh_cloud_state"
SERVICE_SHOW_PHOTO_PRIVACY_POLICY = "show_photo_privacy_policy"
SERVICE_SET_LANGUAGE = "set_language"
SERVICE_MOVE_LIDAR_SCAN = "move_lidar_scan"


# Schemas
SCHEMA_SET_SELECTION = vol.Schema(
    {
        vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("spots", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

SCHEMA_MOW_ZONE = vol.Schema(
    {vol.Required("zone_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_MOW_EDGE = vol.Schema(
    {
        # Each entry is a [map_id, contour_id] pair as expected by the
        # routed-action TASK envelope (s2.50 op=101, d:{edge: [[m,c],...]}).
        # Empty list edges every contour in the current map.
        vol.Optional("contour_ids", default=[]): vol.All(
            cv.ensure_list, [vol.All(cv.ensure_list, [vol.Coerce(int)])]
        ),
    }
)

SCHEMA_MOW_SPOT = vol.Schema(
    {vol.Required("spot_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_EMPTY = vol.Schema({})

SCHEMA_MOVE_LIDAR_SCAN = vol.Schema(
    {
        vol.Required("from_map_id"): vol.Coerce(int),
        vol.Required("filename"): str,
        vol.Required("to_map_id"): vol.Coerce(int),
    }
)

SCHEMA_REPLAY_SESSION = vol.Schema(
    {vol.Required("session_md5"): str}
)

SCHEMA_SET_SCHEDULE_PLANS = vol.Schema({
    vol.Required("slot_id"): vol.Coerce(int),
    vol.Required("plans"): vol.All(cv.ensure_list, [vol.Schema({
        vol.Required("time_min"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1439)),
        vol.Required("weekday_mask"): vol.All(vol.Coerce(int), vol.Range(min=1, max=127)),
        vol.Required("action_type"): vol.In([0, 1, 2]),
        vol.Optional("zone_id"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("extra_bytes_hex"): str,
    })]),
})


def _coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> DreameA2MowerCoordinator | None:
    """Resolve the (only) coordinator instance.

    Single-mower integration: there's at most one coordinator. If
    multi-mower is ever supported, the call would need to specify
    which one (e.g., via entity_id of the lawn_mower entity).
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        LOGGER.warning("No %s coordinator registered; service ignored", DOMAIN)
        return None
    return next(iter(coordinators.values()))


async def _handle_set_active_selection(call: ServiceCall) -> None:
    """Update coordinator.data.active_selection_zones / _spots."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zones = tuple(call.data.get("zones", []))
    spots = tuple(call.data.get("spots", []))
    new_state = dataclasses.replace(
        coordinator.data,
        active_selection_zones=zones,
        active_selection_spots=spots,
    )
    coordinator.async_set_updated_data(new_state)


async def _handle_mow_zone(call: ServiceCall) -> None:
    """Set zone selection then dispatch start_mowing in zone mode."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zone_ids = tuple(call.data["zone_ids"])
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.ZONE,
        active_selection_zones=zone_ids,
    )
    coordinator.async_set_updated_data(new_state)
    # Dispatch the actual start. Imported here to avoid circular imports.
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(MowerAction.START_ZONE_MOW, {"zones": list(zone_ids)})


async def _handle_mow_edge(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    contour_ids = call.data.get("contour_ids") or []
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(
        MowerAction.START_EDGE_MOW, {"contour_ids": contour_ids}
    )


async def _handle_mow_spot(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    spot_ids = tuple(int(s) for s in call.data["spot_ids"])
    if not spot_ids:
        LOGGER.warning("mow_spot: spot_ids list is empty; ignoring")
        return
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.SPOT,
        active_selection_spots=spot_ids,
    )
    coordinator.async_set_updated_data(new_state)
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(
        MowerAction.START_SPOT_MOW, {"spots": list(spot_ids)}
    )


async def _handle_simple_action(action_name: str):
    """Factory for parameterless action handlers (recharge, find_bot, etc.)."""
    from .mower.actions import MowerAction
    target = MowerAction[action_name]

    async def handler(call: ServiceCall) -> None:
        coordinator = _coordinator_from_call(call.hass, call)
        if coordinator is None:
            return
        await coordinator.dispatch_action(target, {})

    return handler



async def _handle_replay_session(call: ServiceCall) -> None:
    """Look up an archived session by md5 and render it into _work_log_png."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    md5 = call.data["session_md5"].strip()
    await coordinator.replay_session(md5)


async def _handle_set_schedule_plans(call: ServiceCall) -> None:
    """Replace one slot's full plan list, leave other slots untouched.

    Card-side flow: card holds the working set locally as the user edits;
    on Save it calls this service with the complete new plan list for ONE
    slot. The coordinator does the cloud round-trip; on success the next
    cloud refresh updates sensor attrs which the card re-reads.
    """
    from .cloud_state import SchedulePlan, ScheduleSlot

    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    cs = getattr(coordinator, "cloud_state", None)
    if cs is None:
        LOGGER.warning("set_schedule_plans: cloud_state not yet populated")
        return
    target_slot_id = int(call.data["slot_id"])
    new_plan_dicts = call.data["plans"]
    new_plans = tuple(
        SchedulePlan(
            time_min=int(p["time_min"]),
            weekday_mask=int(p["weekday_mask"]),
            action_type=int(p["action_type"]),
            zone_id=p.get("zone_id"),
            extra_bytes=bytes.fromhex(p["extra_bytes_hex"]) if p.get("extra_bytes_hex") else b"",
        )
        for p in new_plan_dicts
    )
    new_slots = []
    found = False
    for slot in cs.schedule.slots:
        if slot.slot_id == target_slot_id:
            new_slots.append(ScheduleSlot(
                slot_id=slot.slot_id,
                name=slot.name,
                raw_blob_b64="",
                plans=new_plans,
                # Preserve the slot's active/empty flag — the cloud emits 1
                # for the primary slot and 0 for an empty one; if we
                # hardcoded 0 here we'd silently turn an active slot off.
                mode=slot.mode,
            ))
            found = True
        else:
            new_slots.append(slot)
    if not found:
        # New slot inserted by the user. Default mode=1 (active) since the
        # caller is creating a slot that has plans — an empty slot would
        # not be created via this service. Empty/secondary slots are left
        # at the default mode=0 in cloud_state.ScheduleSlot.
        default_mode = 1 if new_plans else 0
        new_slots.append(ScheduleSlot(
            slot_id=target_slot_id, name="", raw_blob_b64="",
            plans=new_plans, mode=default_mode,
        ))
    ok = await coordinator.write_schedule(new_slots)
    LOGGER.info(
        "set_schedule_plans: slot %d, %d plan(s), accepted=%s",
        target_slot_id, len(new_plans), ok,
    )


async def _handle_show_lidar_fullscreen(call: ServiceCall) -> None:
    """Fire a bus event a Lovelace card can listen for to pop up the
    full-resolution LiDAR view. The handler accepts no parameters today;
    the convention exists for future extensibility (e.g. a specific
    archived md5 to display)."""
    call.hass.bus.async_fire("dreame_a2_mower_lidar_fullscreen", {})


async def _handle_dump_map_diagnostics(call: ServiceCall) -> None:
    """One-off diagnostic: dump raw cloud map-batch responses to the
    HA log so we can see what data the cloud is actually returning.
    Triggered by `service: dreame_a2_mower.dump_map_diagnostics`.
    """
    hass = call.hass
    coordinator = _coordinator_from_call(hass, call)
    if coordinator is None or not hasattr(coordinator, "_cloud") or coordinator._cloud is None:
        LOGGER.warning("dump_map_diagnostics: no coordinator/cloud client ready")
        return
    cloud = coordinator._cloud

    # 1. MAP.* + MAP.info batch (the live fetch_map endpoint)
    try:
        batch = await hass.async_add_executor_job(
            cloud.get_batch_device_datas,
            [f"MAP.{i}" for i in range(28)] + ["MAP.info"],
        )
    except Exception as ex:
        LOGGER.warning("dump_map_diagnostics: MAP.* batch raised: %s", ex)
        batch = None
    LOGGER.warning(
        "dump_map_diagnostics: MAP.* batch keys=%s, MAP.info=%r, "
        "non-empty MAP.x slots=%d",
        sorted((batch or {}).keys()),
        (batch or {}).get("MAP.info"),
        sum(1 for k, v in (batch or {}).items() if k.startswith("MAP.") and k != "MAP.info" and v),
    )

    # 2. Re-parse and dump per-map top-level keys
    try:
        parsed = await hass.async_add_executor_job(cloud.fetch_map)
    except Exception as ex:
        LOGGER.warning("dump_map_diagnostics: fetch_map raised: %s", ex)
        parsed = None
    if parsed is None:
        LOGGER.warning("dump_map_diagnostics: fetch_map returned None")
    else:
        for map_id, raw in sorted(parsed.items()):
            keys = sorted(raw.keys())
            paths_val = raw.get("paths")
            LOGGER.warning(
                "dump_map_diagnostics: map_id=%s keys=%s, paths=%r",
                map_id, keys,
                paths_val if isinstance(paths_val, dict) else type(paths_val).__name__,
            )

    # 3. Try a list of plausible alternative batch names
    for prefix in ("M_PATH", "PATH", "NAV", "LINK", "MPATH"):
        try:
            other = await hass.async_add_executor_job(
                cloud.get_batch_device_datas,
                [f"{prefix}.{i}" for i in range(28)] + [f"{prefix}.info"],
            )
        except Exception as ex:
            LOGGER.warning("dump_map_diagnostics: %s.* batch raised: %s", prefix, ex)
            continue
        non_empty = sum(1 for k, v in (other or {}).items() if v)
        LOGGER.warning(
            "dump_map_diagnostics: %s.* batch — keys returned=%d, non-empty=%d, sample=%r",
            prefix, len(other or {}), non_empty,
            next(((k, str(v)[:200]) for k, v in (other or {}).items() if v), None),
        )

    LOGGER.warning("dump_map_diagnostics: done")


# ---------------------------------------------------------------------------
# discover_cloud_api — helpers
# ---------------------------------------------------------------------------

def _group_keys_by_prefix(batch: dict[str, Any]) -> dict[str, list[str]]:
    """Group keys by their dot-prefix.

    'MAP.0' / 'MAP.1' / 'MAP.info' -> {'MAP': ['MAP.0', 'MAP.1', 'MAP.info']}
    'prop.s_auth_config' -> {'prop': ['prop.s_auth_config']}
    'standalone_key' -> {'standalone_key': ['standalone_key']}
    """
    out: dict[str, list[str]] = {}
    for k in sorted(batch.keys()):
        prefix = k.split(".", 1)[0]
        out.setdefault(prefix, []).append(k)
    return out


def _summarise_value(value: Any, depth: int = 2) -> Any:
    """Recursively summarise a JSON value: types + keys + lengths +
    sample. Capped at `depth` levels to keep output bounded."""
    if depth <= 0:
        return {"type": type(value).__name__, "_truncated": True}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "key_count": len(value),
            "keys": sorted(value.keys()) if all(isinstance(k, str) for k in value) else list(value.keys())[:20],
            "by_key": {
                k: _summarise_value(v, depth - 1)
                for k, v in list(value.items())[:20]
            },
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "first_element": _summarise_value(value[0], depth - 1) if value else None,
        }
    if isinstance(value, (str, int, float, bool, type(None))):
        return {"type": type(value).__name__, "value_preview": repr(value)[:200]}
    return {"type": type(value).__name__, "value_preview": repr(value)[:200]}


def _summarise_family(
    prefix: str,
    keys: list[str],
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Summarise one prefix family. If chunked (PREFIX.0..N + PREFIX.info),
    reassemble and JSON-decode; otherwise return per-key types."""
    import json as _json

    out: dict[str, Any] = {"key_count": len(keys), "keys": keys}
    chunked_keys = sorted(
        [k for k in keys if k.startswith(f"{prefix}.") and k != f"{prefix}.info"
         and k.split(".", 1)[1].isdigit()],
        key=lambda k: int(k.split(".", 1)[1]),
    )
    info_key = f"{prefix}.info"
    if not chunked_keys:
        # Standalone keys (no chunking) — record raw types per key.
        per_key: dict[str, Any] = {}
        for k in keys:
            v = batch.get(k)
            per_key[k] = {"type": type(v).__name__, "value_preview": repr(v)[:200]}
        out["per_key"] = per_key
        return out

    parts = [batch.get(k, "") or "" for k in chunked_keys]
    joined = "".join(parts)
    out["joined_length"] = len(joined)
    out["info"] = batch.get(info_key)

    # Try to JSON-decode (with optional split via .info)
    segments = [joined]
    info_raw = batch.get(info_key)
    if isinstance(info_raw, str) and info_raw.isdigit():
        split_pos = int(info_raw)
        if 0 < split_pos < len(joined):
            segments = [joined[:split_pos], joined[split_pos:]]
    parsed_segments: list[Any] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        try:
            parsed_segments.append(_json.loads(seg))
        except Exception:
            # Save first 200 chars as preview if JSON fails
            parsed_segments.append({"_decode_failed": seg[:200]})
    # If single segment, unwrap; if multiple, keep as list.
    structure = parsed_segments[0] if len(parsed_segments) == 1 else parsed_segments
    out["structure"] = _summarise_value(structure, depth=3)
    return out


async def _async_handle_discover_cloud_api(call: ServiceCall) -> None:
    """Recursively dump the device's cloud API surface to
    <config>/dreame_a2_mower/api_discovery.json. Triggered via the
    service `dreame_a2_mower.discover_cloud_api`. No parameters.

    Discovers chunked-data families (PREFIX.0..N + PREFIX.info) by
    grouping keys returned from get_batch_device_datas([]).  Probes
    cfg_individual endpoints from the integration's catalog. Walks
    the resulting JSON to record types/keys at every path. Output
    is structured for human inspection rather than raw dump.
    """
    import json as _json
    import os

    hass = call.hass
    coord = _coordinator_from_call(hass, call)
    if coord is None or not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("discover_cloud_api: no coordinator/cloud client ready")
        return
    cloud = coord._cloud

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "device": {
            "fw": getattr(cloud, "_firmware_version", None),
            "model": getattr(cloud, "_model", None),
            "did": getattr(cloud, "_did", None),
        },
        "batch_keys": {},
        "cfg_individual": {},
    }

    # 1. Empty-list batch fetch — returns the cloud's full key set.
    try:
        batch = await hass.async_add_executor_job(cloud.get_batch_device_datas, [])
    except Exception as ex:
        LOGGER.warning("discover_cloud_api: empty-list batch raised: %s", ex)
        batch = {}

    # 2. Group keys by prefix.
    families = _group_keys_by_prefix(batch or {})
    LOGGER.info(
        "discover_cloud_api: discovered %d families: %s",
        len(families), sorted(families.keys()),
    )

    # 3. For each family, attempt chunk reassembly + JSON decode + walk.
    for prefix, keys in families.items():
        report["batch_keys"][prefix] = _summarise_family(prefix, keys, batch)

    # 4. Probe cfg_individual catalog.
    try:
        from .protocol.cfg_action import _GET_ENDPOINT_CATALOGUE
    except Exception:
        _GET_ENDPOINT_CATALOGUE = []
    for key in _GET_ENDPOINT_CATALOGUE:
        try:
            from .protocol.cfg_action import probe_get
            raw = await hass.async_add_executor_job(probe_get, cloud.action, key)
        except Exception as ex:
            report["cfg_individual"][key] = {"_error": str(ex)[:200]}
            continue
        report["cfg_individual"][key] = _summarise_value(raw, depth=2)

    # 5. Write report.
    config_dir = hass.config.path(DOMAIN)
    try:
        os.makedirs(config_dir, exist_ok=True)
    except Exception:
        pass
    out_path = hass.config.path(DOMAIN, "api_discovery.json")
    try:
        await hass.async_add_executor_job(
            lambda: open(out_path, "w").write(_json.dumps(report, indent=2, default=str))
        )
    except Exception as ex:
        LOGGER.warning("discover_cloud_api: write to %s failed: %s", out_path, ex)
        return
    LOGGER.warning(
        "discover_cloud_api: wrote %s — %d batch families, %d cfg keys probed",
        out_path, len(report["batch_keys"]), len(report["cfg_individual"]),
    )


async def _handle_set_language(call: ServiceCall) -> None:
    """Set the mower's language indices via CFG.LANG.

    Wire format (verified live 2026-05-09 via the named-key probe on
    g2408 fw 4.3.6_0550): the routed-action `s2.50 m='s' t='LANG'`
    accepts a tagged-union dict ``{type: 'text'|'voice', value: <int>}``.
    Each call sets one index. To set both, this service emits two
    sequential writes.

    Source: ioBroker.dreame v0.3.7 apk.md catalog
    (`LANG | setTextLang/setVoiceLang | {type, value}`).

    The index → language-name mapping is firmware-locale-specific and
    not yet enumerated for g2408. See `docs/TODO.md` "Language index
    enumeration" for the work to discover the full mapping and ship a
    proper writable select.

    Service data:
      text  (int, optional): new value for CFG.LANG[0] (text language)
      voice (int, optional): new value for CFG.LANG[1] (voice language)
    At least one must be provided.
    """
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None or not hasattr(coordinator, "_cloud") or coordinator._cloud is None:
        LOGGER.warning("set_language: no coordinator/cloud client ready")
        return
    text = call.data.get("text")
    voice = call.data.get("voice")
    if text is None and voice is None:
        LOGGER.warning("set_language: at least one of `text` / `voice` is required")
        return
    cloud = coordinator._cloud
    if text is not None:
        ok = await call.hass.async_add_executor_job(
            cloud.set_cfg, "LANG", {"type": "text", "value": int(text)}
        )
        LOGGER.info("set_language: text=%s accepted=%s", text, ok)
    if voice is not None:
        ok = await call.hass.async_add_executor_job(
            cloud.set_cfg, "LANG", {"type": "voice", "value": int(voice)}
        )
        LOGGER.info("set_language: voice=%s accepted=%s", voice, ok)
    # Force a CFG refresh so MowerState catches up (the s2p51 push may
    # also fire on the device side, but the explicit refresh closes the
    # loop deterministically).
    await coordinator._refresh_cloud_state()


async def _handle_show_photo_privacy_policy(call: ServiceCall) -> None:
    """Surface the verbatim Dreame "AI Obstacle Recognition Privacy Policy"
    text as an HA persistent_notification.

    The policy is the gate behind the in-app *Privacy Policy for
    Capturing and Transmitting Photos* sub-menu. The integration cannot
    accept it on the user's behalf — REC writes return r=-3 on this
    firmware, and a privacy policy that flips without an explicit
    accept-screen would be a UX bug. This service exists so the policy
    text is reviewable from inside HA without opening the Dreame app.

    The notification is dismissable via the bell icon. The acceptance
    state itself is surfaced read-only at
    `binary_sensor.dreame_a2_mower_photo_consent` (CFG.REC[7]).
    """
    # Imported lazily — `homeassistant.components.*` isn't available in
    # the test environment that stubs only `homeassistant.const`.
    from homeassistant.components.persistent_notification import (
        async_create as async_create_notification,
    )
    policy_path = Path(__file__).parent / "data" / "privacy_policy_photo.md"
    try:
        text = await call.hass.async_add_executor_job(policy_path.read_text)
    except OSError as ex:
        LOGGER.warning("show_photo_privacy_policy: %s not readable: %s", policy_path, ex)
        return
    async_create_notification(
        call.hass,
        text,
        title="Dreame A2 — AI Photo Capture Privacy Policy",
        notification_id="dreame_a2_mower_photo_privacy_policy",
    )


async def _handle_refresh_cloud_state(call: ServiceCall) -> None:
    """Force an on-demand re-fetch of all cloud-derived state.

    Same code path as the periodic 2-min poll and the s6p2 tripwire,
    but fires immediately. Use it from automations or manually when
    you want HA's view of CFG / SETTINGS / SCHEDULE / MAP / etc. to
    catch up without waiting.
    """
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    LOGGER.info("service.refresh_cloud_state: forcing cloud refresh")
    await coordinator._refresh_cloud_state()


async def _async_move_lidar_scan(call: ServiceCall) -> None:
    """Move a LiDAR PCD between two maps' archives."""
    from homeassistant.exceptions import ServiceValidationError

    hass = call.hass
    from_map_id = int(call.data["from_map_id"])
    filename = str(call.data["filename"])
    to_map_id = int(call.data["to_map_id"])

    if from_map_id == to_map_id:
        raise ServiceValidationError(
            f"from_map_id and to_map_id must differ ({from_map_id})"
        )

    coordinator = _coordinator_from_call(hass, call)
    if coordinator is None:
        return

    src = coordinator.lidar_archive_for(from_map_id)
    dst = coordinator.lidar_archive_for(to_map_id)

    moved = await hass.async_add_executor_job(src.move_entry_to, filename, dst)
    if not moved:
        raise ServiceValidationError(
            f"scan {filename!r} not found in map_{from_map_id} archive"
        )

    LOGGER.info(
        "move_lidar_scan: moved %r from map %d -> map %d",
        filename,
        from_map_id,
        to_map_id,
    )
    # Refresh state listeners so the picker re-enumerates.
    await coordinator.async_request_refresh()


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all the integration's service handlers."""
    hass.services.async_register(DOMAIN, SERVICE_SET_ACTIVE_SELECTION,
                                  _handle_set_active_selection, schema=SCHEMA_SET_SELECTION)
    hass.services.async_register(DOMAIN, SERVICE_MOW_ZONE,
                                  _handle_mow_zone, schema=SCHEMA_MOW_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_EDGE,
                                  _handle_mow_edge, schema=SCHEMA_MOW_EDGE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_SPOT,
                                  _handle_mow_spot, schema=SCHEMA_MOW_SPOT)
    hass.services.async_register(DOMAIN, SERVICE_RECHARGE,
                                  await _handle_simple_action("RECHARGE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FIND_BOT,
                                  await _handle_simple_action("FIND_BOT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_LOCK_BOT,
                                  await _handle_simple_action("LOCK_BOT_TOGGLE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_SUPPRESS_FAULT,
                                  await _handle_simple_action("SUPPRESS_FAULT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FINALIZE_SESSION,
                                  await _handle_simple_action("FINALIZE_SESSION"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_REPLAY_SESSION,
                                  _handle_replay_session, schema=SCHEMA_REPLAY_SESSION)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE_PLANS,
                                  _handle_set_schedule_plans, schema=SCHEMA_SET_SCHEDULE_PLANS)
    hass.services.async_register(DOMAIN, SERVICE_SHOW_LIDAR_FULLSCREEN,
                                  _handle_show_lidar_fullscreen, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_DUMP_MAP_DIAGNOSTICS,
                                  _handle_dump_map_diagnostics, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_DISCOVER_CLOUD_API,
                                  _async_handle_discover_cloud_api, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_CLOUD_STATE,
                                  _handle_refresh_cloud_state, schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_SHOW_PHOTO_PRIVACY_POLICY,
                                  _handle_show_photo_privacy_policy, schema=SCHEMA_EMPTY)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_LANGUAGE,
        _handle_set_language,
        schema=vol.Schema({
            vol.Optional("text"): vol.Coerce(int),
            vol.Optional("voice"): vol.Coerce(int),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_MOVE_LIDAR_SCAN,
        _async_move_lidar_scan,
        schema=SCHEMA_MOVE_LIDAR_SCAN,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_SET_ACTIVE_SELECTION, SERVICE_MOW_ZONE, SERVICE_MOW_EDGE, SERVICE_MOW_SPOT,
        SERVICE_RECHARGE, SERVICE_FIND_BOT, SERVICE_LOCK_BOT, SERVICE_SUPPRESS_FAULT,
        SERVICE_FINALIZE_SESSION, SERVICE_REPLAY_SESSION, SERVICE_SET_SCHEDULE_PLANS,
        SERVICE_SHOW_LIDAR_FULLSCREEN, SERVICE_DUMP_MAP_DIAGNOSTICS, SERVICE_DISCOVER_CLOUD_API,
        SERVICE_REFRESH_CLOUD_STATE, SERVICE_SHOW_PHOTO_PRIVACY_POLICY,
        SERVICE_SET_LANGUAGE, SERVICE_MOVE_LIDAR_SCAN,
    ):
        hass.services.async_remove(DOMAIN, svc)
