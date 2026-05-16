"""Reconstruct wifi_samples from probe-captured s1p1 (heartbeat)
events paired with s1p4 (position) events.

Mirrors the live integration's logic in
coordinator/_mqtt_handlers.py around the append_wifi_sample call site.
"""
from __future__ import annotations

import base64
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


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


def _ensure_decoders_importable() -> None:
    """Add repo root to sys.path so we can import the integration's
    decoders. Called lazily from the production decoder paths."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _default_position_decoder(blob: bytes) -> tuple[float, float] | None:
    """Decode an s1p4 blob to (x_m, y_m) using the integration's decoder."""
    _ensure_decoders_importable()
    from custom_components.dreame_a2_mower.protocol import telemetry
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
    _ensure_decoders_importable()
    from custom_components.dreame_a2_mower.protocol import heartbeat as _hb
    try:
        return _hb.decode_s1p1(blob).wifi_rssi_dbm
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
