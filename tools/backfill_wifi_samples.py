"""Replay probe_log_*.jsonl into existing session-archive blobs to
back-fill the new ``wifi_samples`` field for historical sessions.

Motivation
----------
v1.0.10a6 adds ``wifi_samples`` — per-session (x_m, y_m, rssi_dbm,
ts_unix) tuples captured live during mowing — that the heatmap →
map_id correlator consumes. Sessions archived before that version
have empty ``wifi_samples`` (or the key absent entirely), so the
matcher has nothing to score against.

This tool reconstructs those samples offline from the captured probe
logs: every s1p1 heartbeat's wifi_rssi_dbm gets paired with the most
recent s1p4 (or short-frame BEACON / BUILDING) position seen before
that timestamp, then bucketed into the session whose
``[start_ts, end_ts]`` window contains it. The tool rewrites the
session blob with ``wifi_samples`` added; running twice is safe —
already-back-filled blobs are skipped (or merged, see ``--merge``).

Usage
-----
    python3 tools/backfill_wifi_samples.py \
        --probe-glob "/data/claude/homeassistant/probe_log_*.jsonl" \
        --sessions-dir /tmp/mirror/sessions \
        --dry-run

Defaults: ``--probe-glob`` = ``/data/claude/homeassistant/probe_log_*.jsonl``;
``--sessions-dir`` is required. Pass ``--dry-run`` to print what would
change without touching the disk.

Idempotency
-----------
- If a blob already has a non-empty ``wifi_samples`` list and
  ``--force`` is not set, the blob is left untouched.
- ``--force`` rebuilds ``wifi_samples`` from the probe logs,
  overwriting whatever was there.
- ``--merge`` keeps the existing samples and appends only the
  reconstructed tuples whose ``ts_unix`` is not already present.

The tool is read-only on the probe logs. The session blobs are
rewritten atomically (write to ``*.tmp``, then rename).
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

# Load the pure-Python decoders directly (skipping the package
# __init__ that pulls in homeassistant.* — this tool runs offline).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROTOCOL_DIR = _REPO_ROOT / "custom_components" / "dreame_a2_mower" / "protocol"

import importlib.util


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_heartbeat = _load_module("_bf_heartbeat", _PROTOCOL_DIR / "heartbeat.py")
_telemetry = _load_module("_bf_telemetry", _PROTOCOL_DIR / "telemetry.py")

_LOGGER = logging.getLogger("backfill_wifi_samples")


# ---------------------------------------------------------------------------
# Probe-log iteration helpers
# ---------------------------------------------------------------------------


def _iter_probe_entries(probe_paths: list[Path]) -> Iterator[dict[str, Any]]:
    """Yield each JSON-line entry from each probe log, oldest-first."""
    for path in sorted(probe_paths):
        try:
            fh = path.open("r", encoding="utf-8")
        except OSError as ex:
            _LOGGER.warning("could not open %s: %s", path, ex)
            continue
        with fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError as ex:
                    _LOGGER.debug("%s:%d JSON parse error: %s", path, lineno, ex)
                    continue
                if isinstance(entry, dict):
                    yield entry


def _parse_unix_ts(entry: dict[str, Any]) -> int | None:
    """Pull a unix-second timestamp out of a probe entry.

    The probe format uses local-tz ISO strings ("YYYY-MM-DD HH:MM:SS")
    without a tz designator. We treat them as the host's local time
    (the probe and HA both run on the user's hardware, same wall
    clock), then convert to UTC seconds. ``datetime.fromisoformat``
    handles the bare "YYYY-MM-DD HH:MM:SS" form natively.
    """
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return int(dt.astimezone().timestamp())
    return int(dt.timestamp())


def _bytes_from_value(value: Any) -> bytes | None:
    """Coerce a probe's ``value`` payload into a raw byte sequence."""
    if isinstance(value, list):
        try:
            return bytes(int(b) & 0xFF for b in value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        # Some probes capture base64-encoded blobs. Try base64 first;
        # fall back to a hex string if that fails.
        import base64
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            try:
                return bytes.fromhex(value)
            except ValueError:
                return None
    return None


def _extract_property_pushes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every ``{siid, piid, value}`` dict carried by this entry.

    Probe entries vary in shape: top-level ``params`` for older
    captures, or nested ``parsed_data.params`` for the current MQTT
    capture. Either way, the contents are a list of dicts.
    """
    if entry.get("type") != "mqtt_message":
        return []
    method = entry.get("method")
    if method != "properties_changed":
        return []
    params = entry.get("params")
    if not isinstance(params, list):
        params = (entry.get("parsed_data") or {}).get("params")
    if not isinstance(params, list):
        return []
    out: list[dict[str, Any]] = []
    for p in params:
        if not isinstance(p, dict):
            continue
        try:
            siid = int(p.get("siid", -1))
            piid = int(p.get("piid", -1))
        except (TypeError, ValueError):
            continue
        if siid < 0 or piid < 0:
            continue
        out.append({"siid": siid, "piid": piid, "value": p.get("value")})
    return out


# ---------------------------------------------------------------------------
# Reconstruction pipeline
# ---------------------------------------------------------------------------


@dataclass
class _Sample:
    """One reconstructed (x_m, y_m, rssi_dbm, ts_unix) sample."""

    x_m: float
    y_m: float
    rssi_dbm: int
    ts_unix: int

    def as_list(self) -> list[Any]:
        return [self.x_m, self.y_m, self.rssi_dbm, self.ts_unix]


def reconstruct_samples(probe_paths: list[Path]) -> list[_Sample]:
    """Pair every s1p1 heartbeat's RSSI with the most recent s1p4 position.

    Returns a list of samples ordered by ts_unix.
    """
    last_x_m: float | None = None
    last_y_m: float | None = None
    out: list[_Sample] = []
    for entry in _iter_probe_entries(probe_paths):
        ts = _parse_unix_ts(entry)
        if ts is None:
            continue
        for push in _extract_property_pushes(entry):
            blob = _bytes_from_value(push["value"])
            if blob is None:
                continue
            siid, piid = push["siid"], push["piid"]
            if (siid, piid) == (1, 4):
                # Telemetry — update last-known position.
                try:
                    if len(blob) == _telemetry.FRAME_LENGTH:
                        decoded = _telemetry.decode_s1p4(blob)
                        last_x_m, last_y_m = decoded.x_m, decoded.y_m
                    elif len(blob) in (
                        _telemetry.FRAME_LENGTH_BEACON,
                        _telemetry.FRAME_LENGTH_BUILDING,
                    ):
                        pos = _telemetry.decode_s1p4_position(blob)
                        last_x_m, last_y_m = pos.x_m, pos.y_m
                except _telemetry.InvalidS1P4Frame:
                    continue
            elif (siid, piid) == (1, 1):
                # Heartbeat — try to pair with the last seen position.
                if last_x_m is None or last_y_m is None:
                    continue
                try:
                    hb = _heartbeat.decode_s1p1(blob)
                except _heartbeat.InvalidS1P1Frame:
                    continue
                if hb.wifi_rssi_dbm is None:
                    continue
                out.append(
                    _Sample(
                        x_m=float(last_x_m),
                        y_m=float(last_y_m),
                        rssi_dbm=int(hb.wifi_rssi_dbm),
                        ts_unix=ts,
                    )
                )
    out.sort(key=lambda s: s.ts_unix)
    return out


# ---------------------------------------------------------------------------
# Session-archive integration
# ---------------------------------------------------------------------------


def _read_index(sessions_dir: Path) -> list[dict[str, Any]]:
    idx_path = sessions_dir / "index.json"
    if not idx_path.is_file():
        return []
    try:
        data = json.loads(idx_path.read_text())
    except (OSError, ValueError) as ex:
        _LOGGER.warning("index.json parse failed: %s", ex)
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("sessions")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _read_blob(sessions_dir: Path, filename: str) -> dict[str, Any] | None:
    path = sessions_dir / filename
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as ex:
        _LOGGER.warning("%s: parse failed: %s", filename, ex)
        return None
    return data if isinstance(data, dict) else None


def _write_blob_atomic(sessions_dir: Path, filename: str, body: dict[str, Any]) -> None:
    path = sessions_dir / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True, default=str))
    tmp.replace(path)


def _bucket_samples_by_session(
    samples: list[_Sample],
    sessions: list[dict[str, Any]],
) -> dict[str, list[_Sample]]:
    """Group reconstructed samples by session filename.

    Each sample is assigned to AT MOST one session — the one whose
    ``[start_ts, end_ts]`` interval contains the sample's ``ts_unix``.
    Overlapping intervals (shouldn't happen but legacy archives can
    have them) win to the latest start_ts.
    """
    # Pre-sort sessions by start_ts so we can scan linearly.
    ordered = sorted(
        sessions,
        key=lambda s: int(s.get("start_ts", 0)),
    )
    out: dict[str, list[_Sample]] = {}
    if not ordered:
        return out
    j = 0
    for sample in samples:
        # Advance j while the sample is past the session at j's end.
        # We don't drop j though, since later samples may still fall
        # before the next session's start.
        for s in ordered:
            try:
                start = int(s.get("start_ts", 0))
                end = int(s.get("end_ts", 0))
            except (TypeError, ValueError):
                continue
            if start <= sample.ts_unix <= end:
                fname = str(s.get("filename", ""))
                if fname:
                    out.setdefault(fname, []).append(sample)
                break
    return out


def _merge_samples(
    existing: list[list[Any]],
    new: list[_Sample],
    merge_mode: bool,
) -> tuple[list[list[Any]], int]:
    """Return (resulting samples as list-of-lists, count_added).

    When ``merge_mode`` is False, the result is just the ``new`` list.
    When True, ``existing`` is preserved and new samples are appended
    only when their ts_unix is not already present in ``existing``.
    """
    if not merge_mode:
        return [s.as_list() for s in new], len(new)
    seen_ts = set()
    for row in existing:
        try:
            seen_ts.add(int(row[3]))
        except (TypeError, ValueError, IndexError):
            continue
    out = [list(row) for row in existing if isinstance(row, list)]
    added = 0
    for s in new:
        if s.ts_unix in seen_ts:
            continue
        out.append(s.as_list())
        added += 1
    out.sort(key=lambda r: int(r[3]) if len(r) >= 4 else 0)
    return out, added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Back-fill wifi_samples on existing session-archive blobs by "
            "replaying captured probe logs."
        )
    )
    parser.add_argument(
        "--probe-glob",
        default="/data/claude/homeassistant/probe_log_*.jsonl",
        help="Glob pattern matching probe_log_*.jsonl files.",
    )
    parser.add_argument(
        "--sessions-dir",
        required=True,
        type=Path,
        help="Directory containing index.json + per-session JSON blobs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change but do not modify any files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite wifi_samples even if a non-empty list already exists.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Keep existing wifi_samples and append only new ts values.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    if args.force and args.merge:
        _LOGGER.error("--force and --merge are mutually exclusive")
        return 2

    probe_paths = [Path(p) for p in glob.glob(args.probe_glob)]
    if not probe_paths:
        _LOGGER.error("no probe logs matched %r", args.probe_glob)
        return 2
    _LOGGER.info("probe logs (%d):", len(probe_paths))
    for p in sorted(probe_paths):
        _LOGGER.info("  - %s", p)

    sessions_dir: Path = args.sessions_dir
    if not sessions_dir.is_dir():
        _LOGGER.error("sessions-dir not a directory: %s", sessions_dir)
        return 2
    sessions = _read_index(sessions_dir)
    _LOGGER.info("found %d sessions in %s/index.json", len(sessions), sessions_dir)
    if not sessions:
        return 0

    _LOGGER.info("reconstructing samples from probe logs (this may take a minute)…")
    all_samples = reconstruct_samples(probe_paths)
    _LOGGER.info("reconstructed %d (x, y, rssi, ts) samples", len(all_samples))

    bucketed = _bucket_samples_by_session(all_samples, sessions)
    _LOGGER.info("samples cover %d distinct sessions", len(bucketed))

    total_modified = 0
    total_added = 0
    total_skipped_already = 0
    total_no_data = 0
    for session in sessions:
        filename = str(session.get("filename", ""))
        if not filename:
            continue
        new_samples = bucketed.get(filename, [])
        if not new_samples:
            total_no_data += 1
            continue

        body = _read_blob(sessions_dir, filename)
        if body is None:
            continue

        existing = body.get("wifi_samples")
        if isinstance(existing, list) and existing and not args.force and not args.merge:
            _LOGGER.debug("%s: already has %d samples — skipping", filename, len(existing))
            total_skipped_already += 1
            continue

        if not isinstance(existing, list):
            existing = []

        merged, added = _merge_samples(existing, new_samples, merge_mode=args.merge)
        if not added:
            _LOGGER.debug("%s: no new samples to add", filename)
            total_skipped_already += 1
            continue

        body["wifi_samples"] = merged
        if args.dry_run:
            _LOGGER.info(
                "[dry-run] %s: would add %d samples (total %d)",
                filename, added, len(merged),
            )
        else:
            _write_blob_atomic(sessions_dir, filename, body)
            _LOGGER.info(
                "%s: added %d samples (total %d)",
                filename, added, len(merged),
            )
        total_modified += 1
        total_added += added

    _LOGGER.info("---")
    _LOGGER.info("sessions modified:        %d", total_modified)
    _LOGGER.info("samples added (total):    %d", total_added)
    _LOGGER.info("sessions with no samples: %d", total_no_data)
    _LOGGER.info("sessions already filled:  %d", total_skipped_already)
    if args.dry_run:
        _LOGGER.info("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
