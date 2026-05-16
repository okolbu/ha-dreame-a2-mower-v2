"""Reconstruct wifi_samples from probe-captured s1p1 (heartbeat)
events paired with s1p4 (position) events.

Mirrors the live integration's logic in
coordinator/_mqtt_handlers.py around the append_wifi_sample call site.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

_DECODER_CACHE: dict[str, ModuleType] = {}


def _load_decoder_module(name: str) -> ModuleType:
    """Load a protocol decoder module DIRECTLY from its file,
    bypassing custom_components/dreame_a2_mower/__init__.py which
    pulls in homeassistant.* (not available on dev boxes).

    Caches by module name on first load.
    """
    if name in _DECODER_CACHE:
        return _DECODER_CACHE[name]
    repo_root = Path(__file__).resolve().parent.parent.parent
    src = repo_root / "custom_components" / "dreame_a2_mower" / "protocol" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"_rebuild_session_{name}", src,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {src}")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module so that dataclass
    # forward-reference resolution can find the module via __module__.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    _DECODER_CACHE[name] = mod
    return mod


def _coerce_blob(value: Any) -> bytes | None:
    """Normalise a probe value to bytes.

    Probe stores blobs as list[int] (verbatim JSON array).
    Base64 strings and raw bytes are also accepted for completeness.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, list):
        try:
            return bytes(value)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            return None
    return None


def _default_position_decoder(blob: bytes) -> tuple[float, float] | None:
    """Decode an s1p4 blob to (x_m, y_m) using the integration's decoder."""
    telemetry = _load_decoder_module("telemetry")
    try:
        if len(blob) in (
            telemetry.FRAME_LENGTH_BEACON,
            telemetry.FRAME_LENGTH_BUILDING,
        ):
            decoded = telemetry.decode_s1p4_position(blob)
            return (decoded.x_m, decoded.y_m)
        decoded = telemetry.decode_s1p4(blob)
        return (decoded.x_m, decoded.y_m)
    except Exception:
        return None


def _heartbeat_rssi(blob: bytes) -> int | None:
    """Decode an s1p1 heartbeat blob and extract wifi_rssi_dbm."""
    hb = _load_decoder_module("heartbeat")
    try:
        return hb.decode_s1p1(blob).wifi_rssi_dbm
    except Exception:
        return None


def reconstruct_wifi_samples(
    reader: Any,
    start_ts: int,
    end_ts: int,
    *,
    _position_decoder: Callable[[bytes], tuple[float, float] | None] | None = None,
    _heartbeat_decoder: Callable[[bytes], int | None] | None = None,
) -> list[tuple[float, float, int, int]]:
    """Reconstruct wifi_samples for a session window.

    Returns a list of (x_m, y_m, rssi_dbm, ts_unix) tuples matching
    the shape ``LiveMapState.wifi_samples`` produces.

    The two ``_*_decoder`` kwargs exist for unit tests; production
    callers leave them ``None`` and the live integration's decoders are
    used.
    """
    pos_dec = _position_decoder or _default_position_decoder
    hb_dec = _heartbeat_decoder or _heartbeat_rssi

    s1p1_events = reader.events_for_slot(1, 1, start_ts=start_ts, end_ts=end_ts)
    s1p4_events = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)

    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p1_events:
        timeline.append((ts, "hb", val))
    for ts, val in s1p4_events:
        timeline.append((ts, "pos", val))
    timeline.sort(key=lambda t: t[0])

    samples: list[tuple[float, float, int, int]] = []
    last_pos: tuple[float, float] | None = None
    for ts, kind, val in timeline:
        if kind == "pos":
            blob = _coerce_blob(val)
            if blob is None:
                continue
            decoded = pos_dec(blob)
            if decoded is not None:
                last_pos = decoded
        else:  # heartbeat
            if last_pos is None:
                continue
            blob = _coerce_blob(val)
            if blob is None:
                continue
            rssi = hb_dec(blob)
            if rssi is None:
                continue
            new_sample = (last_pos[0], last_pos[1], int(rssi), int(ts))
            # Dedup mirroring LiveMapState.append_wifi_sample:
            # within 25 cm radius at the same RSSI.
            if samples:
                lx, ly, lr, _lts = samples[-1]
                if lr == rssi:
                    dx = new_sample[0] - lx
                    dy = new_sample[1] - ly
                    if (dx * dx + dy * dy) < 0.0625:  # 25 cm squared
                        continue
            samples.append(new_sample)
    return samples
