"""s2p51 multiplexed config decoder/encoder for Dreame A2 (g2408).

Every "More Settings" change on the mower (DnD, Rain Protection, LED schedule,
etc.) is transported via the single s2p51 property with different payload
shapes. This module recognises each shape and returns a typed event, or flags
the payload as ambiguous when multiple settings share identical shape.

See docs/superpowers/specs/2026-04-17-dreame-a2-mower-ha-integration-design.md
and the project memory for the full shape catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class S2P51DecodeError(ValueError):
    """Raised when an s2p51 payload does not match any known shape."""


# Per-slot consumable identity for the CONSUMABLES list shape — slot
# names and runtime-threshold (in minutes) confirmed 2026-04-30 against
# the app's "Consumables & Maintenance" page (Blades 100h ≈ 6000m,
# Cleaning Brush 500h ≈ 30000m, Robot Maintenance 60h ≈ 3600m). Index 3
# is Link Module on the g2408, which is integrated and reports `-1` —
# no wear timer applies. Single source of truth: the coordinator
# imports it for entity wiring; mower_tail.py imports it for the
# settings narrative.
CONSUMABLE_SLOT_NAMES: tuple[str, ...] = (
    "Blades",
    "Cleaning Brush",
    "Robot Maintenance",
    "Link Module",
)

CONSUMABLE_THRESHOLDS_MIN: tuple[int | None, ...] = (
    6000,   # 0: Blades
    30000,  # 1: Cleaning Brush
    3600,   # 2: Robot Maintenance
    None,   # 3: Link Module — sentinel -1, no wear timer
)


class Setting(StrEnum):
    TIMESTAMP = "timestamp"
    AMBIGUOUS_TOGGLE = "ambiguous_toggle"
    AMBIGUOUS_4LIST = "ambiguous_4list"
    CONSUMABLES = "consumables"
    DND = "dnd"
    LOW_SPEED_NIGHT = "low_speed_night"
    CHARGING = "charging"
    LED_PERIOD = "led_period"
    ANTI_THEFT = "anti_theft"
    RAIN_PROTECTION = "rain_protection"
    HUMAN_PRESENCE_ALERT = "human_presence_alert"
    LANGUAGE = "language"


@dataclass(frozen=True)
class S2P51Event:
    setting: Setting
    values: dict[str, Any]


def decode_s2p51(payload: dict[str, Any]) -> S2P51Event:
    if not payload:
        raise S2P51DecodeError("empty payload")

    if "time" in payload and "tz" in payload:
        return S2P51Event(
            setting=Setting.TIMESTAMP,
            values={"time": int(payload["time"]), "tz": payload["tz"]},
        )

    # Language event — fires when the user changes app text language
    # and/or robot voice language. Confirmed 2026-04-24 via a Robot
    # Voice change on g2408: payload `{'text': 2, 'voice': 7}` drove
    # CFG.LANG from [2, 0] to [2, 7] (text_idx unchanged, voice_idx
    # flipped to 7 = Norwegian). See docs/research/g2408-protocol.md
    # §6.2 for the LANG index catalogue.
    if set(payload.keys()) == {"text", "voice"}:
        return S2P51Event(
            setting=Setting.LANGUAGE,
            values={
                "text_idx": int(payload["text"]),
                "voice_idx": int(payload["voice"]),
            },
        )

    # DnD sends three keys and is unambiguous.
    if set(payload.keys()) == {"end", "start", "value"}:
        return S2P51Event(
            setting=Setting.DND,
            values={
                "start_min": int(payload["start"]),
                "end_min": int(payload["end"]),
                "enabled": bool(payload["value"]),
            },
        )

    if set(payload.keys()) == {"value"}:
        value = payload["value"]
        if isinstance(value, int):
            # Ambiguous — this shape is used by multiple settings and the
            # envelope doesn't name which one. Membership is closed (all
            # 5 candidates toggle-verified 2026-04-30):
            # - Child Lock           → CFG.CLS  ({0:off, 1:on})
            # - Frost Protection     → CFG.FDP  ({0:off, 1:on})
            # - Auto Recharge Standby→ CFG.STUN ({0:off, 1:on})
            # - AI Obstacle Photos   → CFG.AOP  ({0:off, 1:on})
            # - Navigation Path      → CFG.PROT ({0:direct, 1:smart})
            # Caller resolves which one fired via a getCFG diff — see
            # sensor.cfg_keys_raw (alpha.116+); the wire envelope itself
            # has no discriminator.
            return S2P51Event(
                setting=Setting.AMBIGUOUS_TOGGLE,
                values={"value": value},
            )
        if isinstance(value, list):
            return _decode_list_payload(value)

    raise S2P51DecodeError(f"unknown payload shape: {payload!r}")


def _decode_list_payload(value: list[int]) -> S2P51Event:
    n = len(value)
    try:
        if n == 2:
            return S2P51Event(
                setting=Setting.RAIN_PROTECTION,
                values={"enabled": bool(value[0]), "resume_hours": int(value[1])},
            )
        if n == 3:
            # Discriminating Low-Speed Nighttime vs Anti-Theft:
            #
            # Low-Speed Nighttime has shape [enabled, start_min, end_min] where
            # start_min and end_min are in the range 0–1440 (minutes in a day).
            #
            # Anti-Theft has shape [lift_alarm, offmap_alarm, realtime_location]
            # where all three values are 0 or 1 (boolean flags).
            #
            # We discriminate by any(v > 1 for v in value): if any element exceeds 1
            # it must be a minute value, routing to Low-Speed Nighttime; otherwise
            # all values are 0/1 and we route to Anti-Theft.
            #
            # Known ambiguity: [0, 0, 0] could be either disabled Low-Speed
            # Nighttime at midnight OR all Anti-Theft flags off. On real g2408
            # data both interpretations are valid, and we route [0, 0, 0] to
            # Anti-Theft per observed device behaviour.
            if any(v > 1 for v in value):
                return S2P51Event(
                    setting=Setting.LOW_SPEED_NIGHT,
                    values={
                        "enabled": bool(value[0]),
                        "start_min": int(value[1]),
                        "end_min": int(value[2]),
                    },
                )
            return S2P51Event(
                setting=Setting.ANTI_THEFT,
                values={
                    "lift_alarm": bool(value[0]),
                    "offmap_alarm": bool(value[1]),
                    "realtime_location": bool(value[2]),
                },
            )
        if n == 4:
            # CONSUMABLES — runtime counters per consumable slot. Distinguished
            # from the ambiguous-4-bool shape by any value being out of {0, 1}:
            # we've observed counters of 3084 (≈51 hours) for Blades and
            # Cleaning Brush, and `-1` as a sentinel for "no timer applies"
            # on integrated parts like the g2408's built-in Link Module.
            # Slot mapping (1-indexed list as shown in the app's
            # "Consumables & Maintenance" page):
            #   0 = #1 Blades
            #   1 = #2 Cleaning Brush
            #   2 = #3 Robot Maintenance
            #   3 = #4 Link Module ( -1 on g2408 — integrated, no timer )
            # Confirmed 2026-04-30 19:57:16 — fake-replacing the Cleaning
            # Brush in the app rewrote the array from [3084, 3084, 0, -1]
            # to [3084, 0, 0, -1]; only index 1 changed.
            if any(v > 1 or v < 0 for v in value):
                return S2P51Event(
                    setting=Setting.CONSUMABLES,
                    values={"counters": [int(v) for v in value]},
                )
            # AMBIGUOUS — exactly two CFG keys ride this 4-bool shape
            # with no envelope discriminator:
            #   - MSG_ALERT (Notification Preferences) — 4-row screen.
            #     Index 0 = Anomaly Messages (toggle-confirmed
            #     2026-04-30 22:34:14 → 22:34:15: index 0 flipped
            #     1→0 then 0→1). Index 2 = Task Messages.
            #   - VOICE (Voice Prompt Modes) — 4-row Robot Voice screen.
            #     `[regular_notif, work_status, special_status, error_status]`.
            #     Index 1 = Work Status confirmed 2026-04-30 22:34:08:
            #     index 1 flipped 0→1 cleanly.
            # Toggling either screen emits one event with the new state
            # of just that screen — there's no "both arrays in one
            # message" effect, just successive emits. Caller resolves
            # which screen fired via getCFG diff (sensor.cfg_keys_raw
            # `_last_diff` names the key that changed).
            return S2P51Event(
                setting=Setting.AMBIGUOUS_4LIST,
                values={"value": [bool(x) for x in value]},
            )
        if n == 6:
            return S2P51Event(
                setting=Setting.CHARGING,
                values={
                    "recharge_pct": int(value[0]),
                    "resume_pct": int(value[1]),
                    "unknown_flag": int(value[2]),
                    "custom_charging": bool(value[3]),
                    "start_min": int(value[4]),
                    "end_min": int(value[5]),
                },
            )
        if n == 8:
            return S2P51Event(
                setting=Setting.LED_PERIOD,
                values={
                    "enabled": bool(value[0]),
                    "start_min": int(value[1]),
                    "end_min": int(value[2]),
                    "standby": bool(value[3]),
                    "working": bool(value[4]),
                    "charging": bool(value[5]),
                    "error": bool(value[6]),
                    "reserved": int(value[7]),
                },
            )
        if n == 9:
            return S2P51Event(
                setting=Setting.HUMAN_PRESENCE_ALERT,
                values={
                    "enabled": bool(value[0]),
                    "sensitivity": int(value[1]),
                    "standby": bool(value[2]),
                    "mowing": bool(value[3]),
                    "recharge": bool(value[4]),
                    "patrol": bool(value[5]),
                    "alert": bool(value[6]),
                    "photos": bool(value[7]),
                    "push_min": int(value[8]),
                },
            )
    except (ValueError, TypeError) as e:
        raise S2P51DecodeError(f"malformed list payload {value!r}: {e}") from e
    raise S2P51DecodeError(f"unknown list payload shape (len={n}): {value!r}")


def encode_s2p51(event: S2P51Event) -> dict[str, Any]:
    """Encode an S2P51Event back into a wire-format payload dict.

    AMBIGUOUS_TOGGLE events cannot be round-tripped because the decoder cannot
    name the specific setting; callers must first replace the setting with a
    concrete toggle using external context (i.e. the app action that fired).
    """
    setting = event.setting
    v = event.values

    if setting is Setting.TIMESTAMP:
        return {"time": str(v["time"]), "tz": v["tz"]}
    if setting is Setting.LANGUAGE:
        return {"text": int(v["text_idx"]), "voice": int(v["voice_idx"])}
    if setting is Setting.DND:
        return {
            "end": int(v["end_min"]),
            "start": int(v["start_min"]),
            "value": int(bool(v["enabled"])),
        }
    if setting is Setting.LOW_SPEED_NIGHT:
        return {"value": [
            int(bool(v["enabled"])), int(v["start_min"]), int(v["end_min"])
        ]}
    if setting is Setting.ANTI_THEFT:
        return {"value": [
            int(bool(v["lift_alarm"])),
            int(bool(v["offmap_alarm"])),
            int(bool(v["realtime_location"])),
        ]}
    if setting is Setting.RAIN_PROTECTION:
        return {"value": [
            int(bool(v["enabled"])), int(v["resume_hours"])
        ]}
    if setting is Setting.CHARGING:
        return {"value": [
            int(v["recharge_pct"]),
            int(v["resume_pct"]),
            int(v["unknown_flag"]),
            int(bool(v["custom_charging"])),
            int(v["start_min"]),
            int(v["end_min"]),
        ]}
    if setting is Setting.LED_PERIOD:
        return {"value": [
            int(bool(v["enabled"])),
            int(v["start_min"]),
            int(v["end_min"]),
            int(bool(v["standby"])),
            int(bool(v["working"])),
            int(bool(v["charging"])),
            int(bool(v["error"])),
            int(v["reserved"]),
        ]}
    if setting is Setting.HUMAN_PRESENCE_ALERT:
        return {"value": [
            int(bool(v["enabled"])),
            int(v["sensitivity"]),
            int(bool(v["standby"])),
            int(bool(v["mowing"])),
            int(bool(v["recharge"])),
            int(bool(v["patrol"])),
            int(bool(v["alert"])),
            int(bool(v["photos"])),
            int(v["push_min"]),
        ]}
    if setting is Setting.AMBIGUOUS_TOGGLE:
        raise S2P51DecodeError(
            "ambiguous toggle cannot be encoded — resolve to a concrete setting first"
        )
    if setting is Setting.AMBIGUOUS_4LIST:
        raise S2P51DecodeError(
            "ambiguous 4-bool list cannot be encoded — resolve to a concrete setting "
            "(MSG_ALERT or VOICE) first via CFG diff"
        )
    if setting is Setting.CONSUMABLES:
        raise S2P51DecodeError(
            "consumables runtime counters are device-reported and cannot be encoded "
            "— consumable replacements go through a different action path"
        )
    raise S2P51DecodeError(f"unknown setting: {setting!r}")
