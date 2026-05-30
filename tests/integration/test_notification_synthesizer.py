"""Tests for the cloud-driven s2p2 notification resolver (2026-05-26).

Replaces the previous F13 inline-fire suite. The new flow:
  - MQTT s2p2 transition → schedule `_resolve_s2p2_notification`.
  - Resolver fetches device-messages/v2, finds matching record, fires
    HA event with the cloud's authoritative localised text.
  - Unseen `(siid, piid, value)` sources warn for maintainer follow-up.
"""
from __future__ import annotations

import collections
from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.const import NOTIFICATION_EVENT_TYPES
from custom_components.dreame_a2_mower.coordinator import (
    S2P2_EVENT_TYPES,
    DreameA2MowerCoordinator,
)
from custom_components.dreame_a2_mower.coordinator._notifications import (
    _english_text,
    _source_key,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_source_key_normalises_string_ints():
    """The cloud returns siid/piid/value as strings; _source_key coerces."""
    src = {"siid": "2", "piid": "2", "value": "28", "eiid": "0", "aiid": "0"}
    assert _source_key(src) == (2, 2, 28)


def test_source_key_returns_none_on_bad_shape():
    assert _source_key(None) is None
    assert _source_key("not a dict") is None
    assert _source_key({}) is None
    assert _source_key({"siid": "x", "piid": "2", "value": "1"}) is None


def test_english_text_prefers_en_falls_back_to_en_us():
    assert _english_text({"localizationContents": {"en": "hi", "de": "hallo"}}) == "hi"
    assert _english_text({"localizationContents": {"en-US": "hi"}}) == "hi"
    assert _english_text({"localizationContents": {"de": "hallo"}}) is None
    assert _english_text({"localizationContents": {}}) is None
    assert _english_text({}) is None
    assert _english_text(None) is None


# ---------------------------------------------------------------------------
# Resolver fixture + helpers
# ---------------------------------------------------------------------------


def _make_coord(
    *, baseline_done: bool = True, records: list[dict] | None = None,
) -> DreameA2MowerCoordinator:
    """Minimal coordinator stub wired for resolver assertions."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._notif_text_cache = {}
    coord._notif_seen_ids = collections.OrderedDict()
    coord._notif_baseline_done = baseline_done
    coord._notification_event = MagicMock()
    coord._last_notification = None
    cloud = MagicMock()
    cloud.device_id = "-112293549"
    cloud.fetch_device_messages = MagicMock(return_value=records)
    coord._cloud = cloud
    coord.hass = MagicMock()

    async def _aexec(fn, *args, **kw):
        return fn(*args, **kw)

    coord.hass.async_add_executor_job = _aexec
    return coord


@pytest.fixture(autouse=True)
def _zero_fetch_delay(monkeypatch):
    """Skip the 10-second post-MQTT delay in tests."""
    from custom_components.dreame_a2_mower.coordinator import _notifications
    monkeypatch.setattr(_notifications, "_FETCH_DELAY_S", 0)


def _record(siid, piid, value, *, msg_id: str, text: str,
            send_time: str = "2026-05-26 12:00:00") -> dict:
    return {
        "messageId": msg_id,
        "source": {
            "siid": str(siid), "piid": str(piid), "value": str(value),
            "eiid": "0", "aiid": "0",
        },
        "localizationContents": {"en": text},
        "sendTime": send_time,
    }


# ---------------------------------------------------------------------------
# Resolver behaviour
# ---------------------------------------------------------------------------


async def test_resolver_fires_when_cloud_record_matches():
    coord = _make_coord(records=[
        _record(2, 2, 48, msg_id="abc", text="Mowing task complete."),
    ])
    coord._fire_notification = MagicMock()

    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=48, now_unix=1_748_000_000,
    )

    coord._fire_notification.assert_called_once()
    kwargs = coord._fire_notification.call_args.kwargs
    assert kwargs["event_type"] == "mowing_complete"
    assert kwargs["text"] == "Mowing task complete."
    assert kwargs["code"] == 48
    assert kwargs["siid"] == 2 and kwargs["piid"] == 2
    assert kwargs["message_id"] == "abc"
    assert kwargs["send_time"] == "2026-05-26 12:00:00"
    # Cache + seen are updated.
    assert coord._notif_text_cache[(2, 2, 48)] == "Mowing task complete."
    assert "abc" in coord._notif_seen_ids


async def test_resolver_skips_when_no_matching_source():
    """Cloud didn't push for this transition (e.g. wear%-gated 28 fresh blades)."""
    coord = _make_coord(records=[
        _record(2, 2, 50, msg_id="abc", text="Mowing task started."),
    ])
    coord._fire_notification = MagicMock()

    # We saw s2p2=28 via MQTT but the cloud only has a 50 record.
    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=28, now_unix=1_748_000_000,
    )

    coord._fire_notification.assert_not_called()
    # Nothing added to cache or seen.
    assert coord._notif_text_cache == {}
    assert len(coord._notif_seen_ids) == 0


async def test_resolver_skips_when_message_id_already_seen():
    """Dedup: same messageId in baseline → no event on subsequent MQTT."""
    coord = _make_coord(records=[
        _record(2, 2, 48, msg_id="abc", text="Mowing task complete."),
    ])
    coord._fire_notification = MagicMock()
    coord._notif_seen_ids["abc"] = True  # pre-seeded (baseline)

    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=48, now_unix=1_748_000_000,
    )

    coord._fire_notification.assert_not_called()


async def test_resolver_uses_unknown_slug_for_novel_codes():
    """A code not in S2P2_EVENT_TYPES still fires, with slug 'unknown_s2p2'."""
    coord = _make_coord(records=[
        _record(2, 2, 99999, msg_id="abc", text="Brand new code"),
    ])
    coord._fire_notification = MagicMock()

    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=99999, now_unix=1_748_000_000,
    )

    assert coord._fire_notification.call_args.kwargs["event_type"] == "unknown_s2p2"
    assert coord._fire_notification.call_args.kwargs["text"] == "Brand new code"


async def test_resolver_does_nothing_when_cloud_unreachable():
    coord = _make_coord(records=None)  # fetch returns None
    coord._fire_notification = MagicMock()

    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=48, now_unix=1_748_000_000,
    )

    coord._fire_notification.assert_not_called()


async def test_baseline_silently_seeds_seen_ids_and_cache():
    """Startup baseline pre-populates seen_ids + warm cache, no events."""
    coord = _make_coord(baseline_done=False, records=[
        _record(2, 2, 48, msg_id="a", text="Mowing task complete."),
        _record(2, 2, 50, msg_id="b", text="Mowing task started."),
        _record(2, 2, 28, msg_id="c", text="Blades are severely worn. Replace them soon."),
    ])
    coord._fire_notification = MagicMock()

    await coord._establish_notification_baseline()

    assert coord._notif_baseline_done is True
    assert {"a", "b", "c"} <= set(coord._notif_seen_ids.keys())
    assert coord._notif_text_cache[(2, 2, 48)] == "Mowing task complete."
    assert coord._notif_text_cache[(2, 2, 50)] == "Mowing task started."
    assert coord._notif_text_cache[(2, 2, 28)].startswith("Blades")
    # Crucially: NO events were fired for the baseline records.
    coord._fire_notification.assert_not_called()


async def test_resolver_runs_baseline_lazily_if_not_done():
    """If baseline never ran (cloud was down at setup), the first s2p2
    transition kicks it off — but no event fires for that transition
    (its record is part of the baseline snapshot)."""
    coord = _make_coord(baseline_done=False, records=[
        _record(2, 2, 48, msg_id="a", text="Mowing task complete."),
    ])
    coord._fire_notification = MagicMock()

    await coord._resolve_s2p2_notification(
        siid=2, piid=2, value=48, now_unix=1_748_000_000,
    )

    # Baseline ran (seen_ids populated), but no event fired this round.
    assert coord._notif_baseline_done is True
    coord._fire_notification.assert_not_called()


async def test_seen_ids_fifo_cap():
    """_mark_notification_seen caps at _SEEN_IDS_CAP via FIFO eviction."""
    coord = _make_coord()
    from custom_components.dreame_a2_mower.coordinator import _notifications

    for i in range(_notifications._SEEN_IDS_CAP + 25):
        coord._mark_notification_seen(f"msg-{i}")

    assert len(coord._notif_seen_ids) == _notifications._SEEN_IDS_CAP
    # Oldest evicted; newest retained.
    assert "msg-0" not in coord._notif_seen_ids
    assert f"msg-{_notifications._SEEN_IDS_CAP + 24}" in coord._notif_seen_ids


# ---------------------------------------------------------------------------
# Consistency tests
# ---------------------------------------------------------------------------


def test_s2p2_event_types_keys_cover_expected_codes():
    """Sanity: known codes (apk-sourced or empirically verified) are in the map."""
    expected = {
        0, 2, 4, 23, 27, 28, 30, 31, 33, 36, 43, 47, 48, 50, 51, 53, 54, 56, 63, 70, 71, 73, 74, 75, 76, 78, 117,
    }
    assert set(S2P2_EVENT_TYPES.keys()) == expected


def test_s2p2_71_slug_reflects_standby_return_not_positioning_failure():
    """s2p2=71 = 'standby outside station too long → auto-return' (verified
    2026-05-30 vs user-confirmed app text + corpus 5/5 return-context), NOT the
    apk's 'positioning failed'."""
    assert S2P2_EVENT_TYPES[71] == "standby_outside_station_too_long"
    assert "positioning_failure" not in S2P2_EVENT_TYPES.values()


def test_s2p2_event_types_values_are_unique():
    """Every slug in S2P2_EVENT_TYPES is unique."""
    slugs = list(S2P2_EVENT_TYPES.values())
    assert len(slugs) == len(set(slugs)), "duplicate slug in S2P2_EVENT_TYPES"


def test_every_slug_is_in_notification_event_types():
    """The notification entity must declare every slug we can emit, including
    the fallback `unknown_s2p2`."""
    for code, slug in S2P2_EVENT_TYPES.items():
        assert slug in NOTIFICATION_EVENT_TYPES, (
            f"s2p2={code} slug={slug!r} not declared in NOTIFICATION_EVENT_TYPES"
        )
    assert "unknown_s2p2" in NOTIFICATION_EVENT_TYPES


def test_notification_event_types_cover_all_s2p2_slugs():
    """Every S2P2_EVENT_TYPES slug must be a declared NOTIFICATION_EVENT_TYPE.

    The notification EventEntity drops any event_type not in its declared
    _attr_event_types (= NOTIFICATION_EVENT_TYPES). If a slug is added to
    S2P2_EVENT_TYPES without updating const, that notification silently
    never fires. This pins the comment-only lockstep.
    """
    from custom_components.dreame_a2_mower.mower.error_codes import (
        S2P2_UNKNOWN_EVENT_TYPE,
    )

    declared = set(NOTIFICATION_EVENT_TYPES)
    for slug in set(S2P2_EVENT_TYPES.values()):
        assert slug in declared, f"{slug!r} fired but not declared on the entity"
    assert S2P2_UNKNOWN_EVENT_TYPE in declared


def test_logbook_message_tables_cover_all_event_types():
    """logbook.py holds the 3rd/4th hand-kept slug copies. Every declared
    event_type should have an explicit human message (the underscore-replace
    fallback works but is ugly)."""
    from custom_components.dreame_a2_mower import logbook as lb
    from custom_components.dreame_a2_mower.const import LIFECYCLE_EVENT_TYPES

    for slug in NOTIFICATION_EVENT_TYPES:
        assert slug in lb._NOTIFICATION_MESSAGES, f"logbook missing notif {slug!r}"
    for slug in LIFECYCLE_EVENT_TYPES:
        assert slug in lb._LIFECYCLE_MESSAGES, f"logbook missing lifecycle {slug!r}"
