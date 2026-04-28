"""Observability subpackage.

Wraps the layer-1 watchdog (``protocol/unknown_watchdog.py``) with
timestamps and categorization, exposes registry snapshots to HA sensors
and the diagnostics handler. Modules in this package follow the layer-2
invariant of NO ``homeassistant.*`` imports — even though they live
under ``custom_components/`` for packaging reasons.
"""

from __future__ import annotations

from .registry import NovelObservation, NovelObservationRegistry, RegistrySnapshot

__all__ = ["NovelObservation", "NovelObservationRegistry", "RegistrySnapshot"]
