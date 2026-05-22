"""Shared module-level helpers for the cloud_client package (B1d split)."""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

_LOGGER = logging.getLogger("custom_components.dreame_a2_mower.cloud_client")

T = TypeVar("T")


def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int,
    delay_s: float = 0.0,
    should_retry: Callable[[BaseException], bool] = lambda _exc: True,
) -> T:
    """Run action() up to max_attempts times, retrying on exception.

    Semantics:
      - max_attempts must be >= 1 (raises ValueError otherwise).
      - On success: return action()'s return value immediately.
      - On exception: if should_retry(exc) returns True AND attempts
        remain, sleep delay_s and retry. Otherwise re-raise.
      - delay_s == 0 (default): no sleep between attempts.

    Helper uses blocking time.sleep — by design, since callers run in
    executor threads.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return action()
        except Exception as exc:
            # NB: catch Exception, NOT BaseException — KeyboardInterrupt,
            # SystemExit, and asyncio.CancelledError must propagate (a
            # cancelled executor task should not be retried for ~24s).
            last_exc = exc
            if not should_retry(exc):
                raise
            if attempt < max_attempts - 1 and delay_s > 0:
                time.sleep(delay_s)
    assert last_exc is not None  # unreachable: loop always raises or returns
    raise last_exc


def _random_agent_id() -> str:
    """Return a 13-char uppercase-hex random string used in the MQTT client-id.

    Mirrors legacy ``dreame/protocol.py`` ``_random_agent_id()``.
    """
    letters = "ABCDEF"
    return "".join(random.choice(letters) for _ in range(13))
