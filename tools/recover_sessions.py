#!/usr/bin/env python3
"""Reconstruct historical session JSONs from MQTT probe logs.

Reads `probe_log_*.jsonl` files (the format produced by the user's
probe_a2_mqtt.py / mower_tail.py recorders) and emits one session
JSON per detected mowing run, in the same shape the integration's
`SessionArchive.archive()` writes.

Each output file carries the locally-tracked legs under `_local_legs`
(same schema the integration uses post-v1.0.0a54), so a replay click
on the recovered entry will draw the actual mowed path.

The integration-running coordinator stays out of the way: this script
is read-only against the probe corpus and writes only to its own
output directory. Copying the produced files into
`/config/dreame_a2_mower/sessions/` and rebuilding `index.json` is a
manual final step (see the printed instructions at end of run).

Usage:
    python3 tools/recover_sessions.py \
        --probe-dir /data/claude/homeassistant/ \
        --out-dir tools/recovered_sessions/

The script is idempotent: re-running on the same probe corpus
produces the same output filenames (md5 derived deterministically
from start_ts) so it's safe to run multiple times.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reach into the integration package without triggering the
# custom_components/__init__.py that imports homeassistant. Load
# protocol/telemetry.py directly via importlib.
_REPO_ROOT = Path(__file__).resolve().parent.parent
import importlib.util as _ilu  # noqa: E402

_TELEMETRY_PATH = (
    _REPO_ROOT
    / "custom_components"
    / "dreame_a2_mower"
    / "protocol"
    / "telemetry.py"
)
_spec = _ilu.spec_from_file_location("_dreame_telemetry", _TELEMETRY_PATH)
assert _spec and _spec.loader
_telemetry = _ilu.module_from_spec(_spec)
# Register before exec so the @dataclass decorator (Py 3.14)
# can find the module in sys.modules during class build.
sys.modules["_dreame_telemetry"] = _telemetry
_spec.loader.exec_module(_telemetry)
FRAME_LENGTH = _telemetry.FRAME_LENGTH
decode_s1p4 = _telemetry.decode_s1p4


# ---------------------------------------------------------------------------
# Probe-log iteration
# ---------------------------------------------------------------------------


def iter_mqtt_pushes(probe_paths: list[Path]):
    """Yield ``(unix_ts, siid, piid, value)`` tuples in chronological order.

    Probe lines come pre-sorted within a single file but the ``timestamp``
    field is a local-time string; we parse it to a unix int once per row
    so downstream session-slicing is monotonic across multi-file inputs.
    """
    import datetime

    rows: list[tuple[int, int, int, Any]] = []
    for path in probe_paths:
        with path.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "mqtt_message":
                    continue
                ts_str = d.get("timestamp")
                if not isinstance(ts_str, str):
                    continue
                try:
                    ts_unix = int(
                        datetime.datetime.strptime(
                            ts_str, "%Y-%m-%d %H:%M:%S"
                        ).timestamp()
                    )
                except ValueError:
                    continue
                params = d.get("params") or []
                if not isinstance(params, list):
                    continue
                for p in params:
                    if not isinstance(p, dict):
                        continue
                    siid = p.get("siid")
                    piid = p.get("piid")
                    if siid is None or piid is None:
                        continue
                    rows.append((ts_unix, int(siid), int(piid), p.get("value")))
    rows.sort(key=lambda r: r[0])
    yield from rows


# ---------------------------------------------------------------------------
# s2p56 task-state extraction (mirrors property_mapping.py)
# ---------------------------------------------------------------------------


def extract_task_state(value: Any) -> int | None:
    if (
        isinstance(value, dict)
        and isinstance(value.get("status"), list)
        and value["status"]
        and isinstance(value["status"][0], list)
        and len(value["status"][0]) >= 2
    ):
        try:
            return int(value["status"][0][1])
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Leg builder (mirrors LiveMapState.append_point's dedup/split heuristics)
# ---------------------------------------------------------------------------


@dataclass
class _SessionBuilder:
    start_ts: int
    legs: list[list[tuple[float, float]]] = field(default_factory=lambda: [[]])
    last_area_mowed_m2: float = 0.0
    last_total_area_m2: float = 0.0
    last_ts: int = 0

    def append_point(self, x_m: float, y_m: float, ts: int) -> None:
        self.last_ts = ts
        leg = self.legs[-1]
        if leg:
            lx, ly = leg[-1]
            d2 = (x_m - lx) ** 2 + (y_m - ly) ** 2
            if d2 > 25.0:
                self.legs.append([])
                leg = self.legs[-1]
            elif d2 < 0.04:
                return
        leg.append((x_m, y_m))

    def begin_leg(self) -> None:
        if not self.legs or self.legs[-1]:
            self.legs.append([])

    def total_points(self) -> int:
        return sum(len(l) for l in self.legs)


# ---------------------------------------------------------------------------
# Session slicing
# ---------------------------------------------------------------------------


def slice_sessions(probe_paths: list[Path]) -> list[_SessionBuilder]:
    """Walk the merged probe stream and produce one builder per detected
    mow.  Session boundaries follow the same gate logic as the
    integration's finalize.decide():

      - start: prev not in {0, 4}, new in {0, 4}
      - end:   prev in {0, 4}, new not in {0, 4}
      - leg boundary: prev=4, new=0 → fresh leg without ending session
    """
    sessions: list[_SessionBuilder] = []
    current: _SessionBuilder | None = None
    prev_state: int | None = None

    for ts, siid, piid, value in iter_mqtt_pushes(probe_paths):
        if (siid, piid) == (2, 56):
            new_state = extract_task_state(value)
            was_active = prev_state in (0, 4)
            is_active = new_state in (0, 4)
            if is_active and not was_active:
                current = _SessionBuilder(start_ts=ts)
                sessions.append(current)
            elif current is not None:
                if was_active and not is_active:
                    current.last_ts = ts
                    current = None
                elif prev_state == 4 and new_state == 0:
                    current.begin_leg()
            prev_state = new_state
            continue

        if current is None or (siid, piid) != (1, 4):
            continue

        if not isinstance(value, list) or len(value) != FRAME_LENGTH:
            continue
        try:
            decoded = decode_s1p4(bytes(value))
        except Exception:
            continue
        current.append_point(decoded.x_m, decoded.y_m, ts)
        if decoded.area_mowed_m2 > 0:
            current.last_area_mowed_m2 = decoded.area_mowed_m2
        if decoded.total_uint24_m2 > 0:
            current.last_total_area_m2 = decoded.total_uint24_m2

    return sessions


# ---------------------------------------------------------------------------
# Session-summary JSON synthesis
# ---------------------------------------------------------------------------


def synthesise_summary(sb: _SessionBuilder) -> dict[str, Any]:
    """Build a dict in the same shape the integration's parser expects.

    The cloud's md5 field is per-map on g2408 and would dedup against
    existing entries; we mint a deterministic synthetic md5 prefixed
    with `rec_<start_ts>_` so the (md5, start_ts) dedup lets every
    recovered session through and re-running the script doesn't
    multiply rows.
    """
    legs_jsonable = [
        [[round(x, 3), round(y, 3)] for (x, y) in leg]
        for leg in sb.legs
        if leg
    ]
    end_ts = sb.last_ts or sb.start_ts
    duration_min = max(1, (end_ts - sb.start_ts) // 60)
    synthetic_md5 = "rec_" + hashlib.md5(
        f"{sb.start_ts}".encode()
    ).hexdigest()[:28]
    return {
        "start": sb.start_ts,
        "end": end_ts,
        "time": duration_min,
        "areas": round(sb.last_area_mowed_m2, 2),
        "map_area": int(sb.last_total_area_m2) if sb.last_total_area_m2 else 0,
        "md5": synthetic_md5,
        "mode": 0,
        "result": 0,
        "stop_reason": 0,
        "_local_legs": legs_jsonable,
        "_recovered_from": "probe_log",
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _format_date(unix_ts: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d")


def write_sessions(builders: list[_SessionBuilder], out_dir: Path) -> list[dict]:
    """Write one .json per builder into out_dir + return entries for index."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for sb in builders:
        if sb.total_points() < 5:
            continue
        summary = synthesise_summary(sb)
        stem = (
            f"{_format_date(summary['end'])}_{summary['end']}_"
            f"{summary['md5'][:8]}.json"
        )
        path = out_dir / stem
        path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        entries.append(
            {
                "filename": stem,
                "start_ts": summary["start"],
                "end_ts": summary["end"],
                "duration_min": summary["time"],
                "area_mowed_m2": summary["areas"],
                "map_area_m2": summary["map_area"],
                "md5": summary["md5"],
            }
        )
    return entries


def write_index(entries: list[dict], out_dir: Path) -> None:
    """Emit a stand-alone index.json fragment for inspection."""
    (out_dir / "index_recovered.json").write_text(
        json.dumps({"sessions": entries, "version": 1}, indent=2, sort_keys=True)
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe-dir",
        default="/data/claude/homeassistant/",
        help="Directory containing probe_log_*.jsonl files",
    )
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "tools" / "recovered_sessions"),
        help="Output directory for the rebuilt session JSONs",
    )
    args = parser.parse_args(argv)

    probe_paths = sorted(Path(args.probe_dir).glob("probe_log_*.jsonl"))
    if not probe_paths:
        print(f"no probe_log_*.jsonl files in {args.probe_dir}", file=sys.stderr)
        return 1

    print(f"reading {len(probe_paths)} probe files…")
    for p in probe_paths:
        print(f"  {p.name}  ({p.stat().st_size // 1024} KiB)")

    builders = slice_sessions(probe_paths)
    print(f"\ndetected {len(builders)} candidate sessions:")
    for sb in builders:
        print(
            f"  start={sb.start_ts} end={sb.last_ts} "
            f"duration={(sb.last_ts - sb.start_ts) // 60}min "
            f"legs={len(sb.legs)} points={sb.total_points()} "
            f"area={sb.last_area_mowed_m2:.1f}m²"
        )

    out_dir = Path(args.out_dir)
    entries = write_sessions(builders, out_dir)
    write_index(entries, out_dir)
    print(f"\nwrote {len(entries)} session JSONs to {out_dir}/")
    print(f"        plus index_recovered.json with the same {len(entries)} entries")

    print(
        "\nTo install on a live HA, copy the .json files into "
        "/config/dreame_a2_mower/sessions/ then either:\n"
        "  - merge entries from index_recovered.json into "
        "/config/dreame_a2_mower/sessions/index.json (keeping the\n"
        "    existing entries), and reload the integration; or\n"
        "  - delete /config/dreame_a2_mower/sessions/index.json so the\n"
        "    integration rebuilds it from the on-disk files at next setup\n"
        "    (it does NOT do this today — load_index won't auto-discover).\n"
        "Recommend the merge path."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
