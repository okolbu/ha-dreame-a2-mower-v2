"""Helpers for grouping a batch response by prefix family.

Used by cloud_client.fetch_full_cloud_state to find chunked families
(MAP.*, M_PATH.*, SETTINGS.*, etc.) and reassemble them.
"""
from __future__ import annotations

from typing import Any


def group_keys_by_prefix(batch: dict[str, Any]) -> dict[str, list[str]]:
    """Group keys by their dot-prefix.

    'MAP.0', 'MAP.1', 'MAP.info' -> {'MAP': ['MAP.0', 'MAP.1', 'MAP.info']}
    'standalone_key' -> {'standalone_key': ['standalone_key']}
    Within each family, keys are returned sorted; numeric chunk keys
    sort BEFORE non-numeric keys like '.info'.
    """
    by_prefix: dict[str, list[str]] = {}
    for k in batch:
        prefix = k.split(".", 1)[0] if "." in k else k
        by_prefix.setdefault(prefix, []).append(k)
    # Sort each family's keys: numeric-suffix keys first (numerically),
    # then non-numeric.
    for prefix, keys in by_prefix.items():
        keys.sort(key=_chunk_sort_key)
    return by_prefix


def _chunk_sort_key(key: str) -> tuple[int, int | str]:
    """Sort key: numeric suffix first (in numeric order), then alpha."""
    if "." not in key:
        return (1, key)
    suffix = key.split(".", 1)[1]
    if suffix.isdigit():
        return (0, int(suffix))
    return (1, suffix)


def join_family_chunks(prefix: str, batch: dict[str, Any]) -> str:
    """Join the numerically-suffixed chunks of one family in order.

    Skips '<prefix>.info' and any non-numeric keys. Empty/missing
    chunks are treated as empty strings.
    """
    chunked = sorted(
        (k for k in batch
         if "." in k
         and k.split(".", 1)[0] == prefix
         and k.split(".", 1)[1].isdigit()),
        key=lambda k: int(k.split(".", 1)[1]),
    )
    return "".join(batch.get(k, "") or "" for k in chunked)
