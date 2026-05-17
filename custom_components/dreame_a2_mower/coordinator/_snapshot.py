"""Full firmware-state snapshot at session-start (settings_snapshot v2).

Replaces the v1 narrow per-map-only snapshot with a structured capture
covering everything that could affect or explain mowing behaviour:

  - per_map:    cloud SETTINGS dict for the active map (same as v1 content)
  - device_wide: CFG/SETTINGS fields that change mow behaviour
  - peripheral:  Human Presence + photo consent (could explain stops)
  - forensic:    LED / voice / anti-theft / child lock (no expected impact)

Each section is independently populated; missing data sources leave the
corresponding slot as None. The v1 fallback in session_card.py handles
older archives.

MowerState field names used here are EXACT — verified 2026-05-17 against
mower/state.py. Differences from the plan spec:

  Plan name                          -> Actual MowerState name
  child_lock                         -> child_lock_enabled
  anti_theft_off_map_alarm           -> anti_theft_offmap_alarm
  led_while_working                  -> led_in_working
  led_while_charging                 -> led_in_charging
  led_on_error                       -> led_in_error
  auto_recharge_battery_threshold    -> auto_recharge_battery_pct
  custom_charging_period_enabled     -> custom_charging_enabled
  voice_language_idx / language_text_idx -> language_voice_idx / language_text_idx
  voice_volume                       -> (no such field; slot is always None)
  resume_after_charge_battery_threshold -> (no such field; slot is always None)
"""
from __future__ import annotations

from typing import Any

SNAPSHOT_VERSION = 2


def _safe(obj: Any, attr: str, default=None):
    """Return obj.attr, or default on AttributeError / missing attr.

    Used so the builder tolerates MowerState fields that don't exist yet
    (e.g., schema additions not yet deployed to the firmware) without
    raising AttributeError.
    """
    try:
        v = getattr(obj, attr, _SENTINEL)
    except AttributeError:
        return default
    if v is _SENTINEL:
        return default
    return v


_SENTINEL = object()


def _build_per_map(coordinator) -> dict[str, Any] | None:
    """Return the cloud SETTINGS dict for the currently active map, or None."""
    active = getattr(coordinator, "_active_map_id", None)
    if active is None:
        return None
    cs = getattr(coordinator, "cloud_state", None)
    if cs is None:
        return None
    settings = getattr(cs, "settings", None)
    if settings is None:
        return None
    per_map = getattr(settings, "by_map_id_canonical", {}).get(int(active))
    if not isinstance(per_map, dict):
        return None
    return dict(per_map)


def _build_device_wide(coordinator) -> dict[str, Any]:
    """Capture device-wide firmware settings that influence mowing behaviour."""
    s = coordinator.data
    return {
        "rain_protection_enabled": _safe(s, "rain_protection_enabled"),
        "rain_protection_resume_hours": _safe(s, "rain_protection_resume_hours"),
        "frost_protection_enabled": _safe(s, "frost_protection_enabled"),
        "navigation_path_smart": _safe(s, "navigation_path_smart"),
        "auto_recharge_battery_pct": _safe(s, "auto_recharge_battery_pct"),
        "auto_recharge_standby_enabled": _safe(s, "auto_recharge_standby_enabled"),
        "custom_charging_enabled": _safe(s, "custom_charging_enabled"),
        "dnd_enabled": _safe(s, "dnd_enabled"),
        "low_speed_at_night_enabled": _safe(s, "low_speed_at_night_enabled"),
    }


def _build_peripheral(coordinator) -> dict[str, Any]:
    """Capture Human Presence and photo settings — potential mid-session pause drivers."""
    s = coordinator.data
    return {
        "human_presence_alert_enabled": _safe(s, "human_presence_alert_enabled"),
        "human_presence_alert_sensitivity": _safe(s, "human_presence_alert_sensitivity"),
        "human_presence_scenario_standby": _safe(s, "human_presence_scenario_standby"),
        "human_presence_scenario_mowing": _safe(s, "human_presence_scenario_mowing"),
        "human_presence_scenario_recharge": _safe(s, "human_presence_scenario_recharge"),
        "human_presence_scenario_patrol": _safe(s, "human_presence_scenario_patrol"),
        "human_presence_alert_voice": _safe(s, "human_presence_alert_voice"),
        "human_presence_alert_push_interval_min": _safe(s, "human_presence_alert_push_interval_min"),
        "photo_consent": _safe(s, "photo_consent"),
        "ai_obstacle_photos_enabled": _safe(s, "ai_obstacle_photos_enabled"),
    }


def _build_forensic(coordinator) -> dict[str, Any]:
    """Capture LED, voice, anti-theft, and child lock — no expected mow impact."""
    s = coordinator.data
    return {
        "led_in_standby": _safe(s, "led_in_standby"),
        "led_in_error": _safe(s, "led_in_error"),
        "led_in_charging": _safe(s, "led_in_charging"),
        "led_in_working": _safe(s, "led_in_working"),
        "led_period_enabled": _safe(s, "led_period_enabled"),
        "language_voice_idx": _safe(s, "language_voice_idx"),
        "language_text_idx": _safe(s, "language_text_idx"),
        "anti_theft_lift_alarm": _safe(s, "anti_theft_lift_alarm"),
        "anti_theft_offmap_alarm": _safe(s, "anti_theft_offmap_alarm"),
        "anti_theft_realtime_location": _safe(s, "anti_theft_realtime_location"),
        "child_lock_enabled": _safe(s, "child_lock_enabled"),
    }


def build_settings_snapshot_v2(coordinator, captured_at_unix: int) -> dict[str, Any]:
    """Build the v2 settings_snapshot dict for session-begin.

    Caller is the session-begin handler in coordinator/_mqtt_handlers.py;
    it assigns the result to live_map.settings_snapshot which is then
    persisted via _persist_in_progress and copied into the final archive
    at session-finalize.
    """
    return {
        "version": SNAPSHOT_VERSION,
        "captured_at_unix": captured_at_unix,
        "per_map": _build_per_map(coordinator),
        "device_wide": _build_device_wide(coordinator),
        "peripheral": _build_peripheral(coordinator),
        "forensic": _build_forensic(coordinator),
    }
