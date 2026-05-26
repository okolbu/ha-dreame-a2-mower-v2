"""Cloud-notification resolver mixin (2026-05-26).

Replaces the previous hardcoded `S2P2_NOTIFICATION_MAP[code] = (slug, text)`
inline-firing model with a cloud-as-source-of-truth flow:

  - On every MQTT s2p2 transition, schedule `_resolve_s2p2_notification`.
  - That task waits ~10 s for the cloud to finish writing its push record,
    then fetches `/dreame-messaging/user/device-messages/v2` (latest 10).
  - It finds the first record matching `(siid, piid, value)` whose
    `messageId` is NOT in `_notif_seen_ids`.
  - On match: fire `event.dreame_a2_mower_notification` with the cloud's
    authoritative text (account-language-localised) + the s2p2 slug.
  - On no match: cloud didn't push (e.g. wear%-gated 28 with fresh blades) —
    no event fires.

In-memory state only (per the 2026-05-26 design call):
  - `_notif_text_cache: {(siid,piid,value) -> text}`  display fallback.
  - `_notif_seen_ids: OrderedDict[messageId, True]`   replay suppression,
                                                    capped at 100 (FIFO).
  - `_notif_baseline_done: bool`                     one-shot startup flag.

Cache and seen_ids are NEVER persisted — restart wipes them. On startup the
baseline fetch silently seeds `_notif_seen_ids` with whatever the cloud
currently holds, so old records don't replay as fresh events when HA boots.

See docs/research/app-api-surface-2026-05-25.md § device-messages/v2 and
docs/research/app-notification-history-2026-05-16.md § Empirical s2p2 mapping.
"""
from __future__ import annotations

import asyncio
import collections
from typing import Any

from ..const import LOGGER
from ._property_apply import S2P2_EVENT_TYPES, S2P2_UNKNOWN_EVENT_TYPE

# Tunables. The cloud push lands a few seconds after the MQTT s2p2 event,
# so we delay before fetching. 10s is comfortable; if it's too short we'll
# miss the record and fire nothing (which is correct).
_FETCH_DELAY_S: float = 10.0
_FETCH_PAGE_SIZE: int = 10
_SEEN_IDS_CAP: int = 100


class _NotificationsMixin:
    """Coordinator mixin: cloud-driven notification resolution.

    Expected on `self` (initialised by `_CoreMixin.__init__`):
      - `_notif_text_cache: dict[tuple[int,int,int], str]`
      - `_notif_seen_ids: collections.OrderedDict[str, Any]`
      - `_notif_baseline_done: bool`
      - `_cloud: DreameA2CloudClient`
      - `hass: HomeAssistant`

    Expected on `self` (provided by `_DeviceSyncMixin`):
      - `_fire_notification(*, event_type, text, code, siid, piid,
                            send_time, message_id, now_unix)`
    """

    async def _establish_notification_baseline(self) -> None:
        """One-shot at setup. Populate seen_ids + warm text cache.

        NEVER fires events — these records are the pre-history snapshot.
        Subsequent s2p2 transitions only fire when a NEW messageId arrives.
        """
        if self._notif_baseline_done:
            return
        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            return
        did = getattr(cloud, "device_id", None) or getattr(cloud, "_did", None)
        if not did:
            return
        records = await self.hass.async_add_executor_job(
            cloud.fetch_device_messages, did, _FETCH_PAGE_SIZE,
        )
        if records is None:
            LOGGER.debug(
                "[notif] baseline: cloud unreachable; will retry on next s2p2"
            )
            return
        for r in records:
            mid = r.get("messageId")
            if mid:
                self._mark_notification_seen(mid)
            key = _source_key(r.get("source"))
            if key is None:
                continue
            text = _english_text(r)
            if text:
                self._notif_text_cache[key] = text
        self._notif_baseline_done = True
        LOGGER.info(
            "[notif] baseline established: %d records seen, %d distinct sources cached",
            len(records), len(self._notif_text_cache),
        )

    def _mark_notification_seen(self, message_id: str) -> None:
        """FIFO insert into `_notif_seen_ids` with `_SEEN_IDS_CAP`."""
        d = self._notif_seen_ids
        if message_id in d:
            d.move_to_end(message_id)
        else:
            d[message_id] = True
        while len(d) > _SEEN_IDS_CAP:
            d.popitem(last=False)

    async def _resolve_s2p2_notification(
        self, *, siid: int, piid: int, value: int, now_unix: int,
    ) -> None:
        """Cloud resolver — called from `_on_state_update` per s2p2 transition.

        Sleeps `_FETCH_DELAY_S`, fetches the latest device-messages page,
        finds the first record with source matching `(siid, piid, value)` and
        an unseen messageId. Fires the notification event with cloud text.
        """
        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            return
        did = getattr(cloud, "device_id", None) or getattr(cloud, "_did", None)
        if not did:
            return

        # If we haven't established baseline yet, do it now (silent — this
        # s2p2's record will be among the baselined ones and no event will
        # fire for it; subsequent transitions will).
        if not self._notif_baseline_done:
            await self._establish_notification_baseline()
            return

        await asyncio.sleep(_FETCH_DELAY_S)

        records = await self.hass.async_add_executor_job(
            cloud.fetch_device_messages, did, _FETCH_PAGE_SIZE,
        )
        if records is None:
            LOGGER.debug(
                "[notif] s%dp%d=%d resolver: cloud unreachable; no event fired",
                siid, piid, value,
            )
            return

        # Find the FIRST unseen record whose source matches.
        target_key = (siid, piid, value)
        matching: dict[str, Any] | None = None
        for r in records:
            key = _source_key(r.get("source"))
            if key != target_key:
                continue
            mid = r.get("messageId")
            if not mid or mid in self._notif_seen_ids:
                continue
            matching = r
            break

        if matching is None:
            LOGGER.debug(
                "[notif] s%dp%d=%d transition: cloud did not push (or already seen)",
                siid, piid, value,
            )
            return

        text = _english_text(matching) or ""
        message_id = matching["messageId"]
        send_time = matching.get("sendTime")

        is_novel_source = target_key not in self._notif_text_cache
        self._notif_text_cache[target_key] = text
        self._mark_notification_seen(message_id)

        if is_novel_source:
            LOGGER.warning(
                "[notif] novel s%dp%d=%d source from cloud: text=%r "
                "(message_id=%s) — please report this code+text to the "
                "integration maintainer so it can be added to S2P2_EVENT_TYPES.",
                siid, piid, value, text, message_id,
            )

        event_type = S2P2_EVENT_TYPES.get(value, S2P2_UNKNOWN_EVENT_TYPE)
        self._fire_notification(
            event_type=event_type,
            text=text,
            code=value,
            siid=siid,
            piid=piid,
            send_time=send_time,
            message_id=message_id,
            now_unix=now_unix,
        )


# Module-level helpers (pure, no `self`) so they're trivially testable.

def _source_key(src: Any) -> tuple[int, int, int] | None:
    """Normalise a record's `source` dict to (siid, piid, value) ints.

    The cloud returns siid/piid/value as STRINGS (e.g. ``"2"``, ``"28"``).
    Returns None if any field is missing or non-numeric.
    """
    if not isinstance(src, dict):
        return None
    try:
        return (int(src["siid"]), int(src["piid"]), int(src["value"]))
    except (KeyError, TypeError, ValueError):
        return None


def _english_text(record: Any) -> str | None:
    """Pull the English localisation from a notification record.

    Falls back to ``en-US`` if ``en`` is absent. Returns None if neither
    exists or `record` isn't shaped right. The cloud uses account-language
    for the user-facing app push; for now the integration's event payload
    uses ``en`` as a stable default (HA UI shows what the user reads in
    their language separately, via translation_key).
    """
    if not isinstance(record, dict):
        return None
    loc = record.get("localizationContents")
    if not isinstance(loc, dict):
        return None
    return loc.get("en") or loc.get("en-US") or None
