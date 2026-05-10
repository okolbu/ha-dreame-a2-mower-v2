"""One-shot migration helper: flat lidar archive → per-map subdirs.

On first startup after T12 the lidar root may contain a flat layout from
the pre-T12 release::

    lidar/
        2024-01-01_1704067200_aabbccdd.pcd
        index.json

This helper moves those files into ``lidar/0/`` so the per-map archive
logic can take over.  It is intentionally **pure Python / sync** so that:

- Tests can call it directly without an async runtime.
- ``async_setup_entry`` can run it in an executor job.

Return value: the number of files actually moved (0 → nothing done).
"""
from __future__ import annotations

import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def migrate_flat_lidar_archive(root: Path) -> int:
    """Move ``root/*.pcd`` + ``root/index.json`` into ``root/0/``.

    Returns the number of files moved, or 0 if:
    - ``root/0/`` already exists (already migrated), or
    - there are no ``*.pcd`` files and no ``index.json`` (nothing to do).
    """
    root = Path(root)

    # Idempotency guard: if the per-map subdir already exists, skip.
    if (root / "0").is_dir():
        _LOGGER.debug("[LIDAR-MIGRATION] root/0/ exists — skipping")
        return 0

    flat_pcds = sorted(root.glob("*.pcd"))
    flat_index = root / "index.json"

    if not flat_pcds and not flat_index.is_file():
        _LOGGER.debug("[LIDAR-MIGRATION] nothing to migrate at %s", root)
        return 0

    dest = root / "0"
    dest.mkdir(parents=True, exist_ok=True)

    moved = 0
    for pcd in flat_pcds:
        try:
            pcd.rename(dest / pcd.name)
            moved += 1
        except OSError as ex:
            _LOGGER.warning(
                "[LIDAR-MIGRATION] failed to move %s: %s", pcd.name, ex
            )

    if flat_index.is_file():
        try:
            flat_index.rename(dest / "index.json")
            moved += 1
        except OSError as ex:
            _LOGGER.warning(
                "[LIDAR-MIGRATION] failed to move index.json: %s", ex
            )

    _LOGGER.info(
        "[LIDAR-MIGRATION] moved %d file(s) from %s → %s",
        moved,
        root,
        dest,
    )
    return moved
