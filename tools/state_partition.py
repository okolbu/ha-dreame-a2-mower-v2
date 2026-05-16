#!/usr/bin/env python3
"""state_partition.py — verify a session JSON's time breakdown
against probe-log ground truth.

Usage:
    python3 tools/state_partition.py <session.json> <probe_log.jsonl>

Prints:
  - Per-state seconds (from probe log STATE transitions)
  - Per-error event timeline (from probe log s2p2 transitions)
  - The same algorithm as session_card._compute_time_breakdown
    applied to the probe-derived state_samples + error_samples
  - The integration's reported numbers (from session.json's
    in_progress.json-derived sample arrays)
  - Side-by-side comparison

Used to diagnose breakdown-vs-truth mismatches without modifying
the integration code path.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path


def parse_probe_log(probe_path: Path, start_ts: int, end_ts: int):
    """Walk a probe log; return (state_transitions, err_transitions)
    where each is a list of (unix_ts, code) within [start_ts, end_ts]."""
    state, err = [], []
    start_dt = dt.datetime.fromtimestamp(start_ts)
    end_dt = dt.datetime.fromtimestamp(end_ts)
    with probe_path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "pretty":
                continue
            try:
                ts_d = dt.datetime.fromisoformat(d["timestamp"])
            except Exception:
                continue
            if not (start_dt <= ts_d <= end_dt):
                continue
            text = d.get("text", "")
            ts_unix = int(ts_d.timestamp())
            try:
                if "s2p1 (STATE)" in text:
                    if "->" in text:
                        new = int(text.split("->", 1)[1].strip().split()[0])
                    else:
                        new = int(text.split("=", 1)[1].strip().split()[0])
                    state.append((ts_unix, new))
                elif "s2p2" in text:
                    if "->" in text:
                        new = int(text.split("->", 1)[1].strip().split()[0])
                    else:
                        new = int(text.split("=", 1)[1].strip().split()[0])
                    err.append((ts_unix, new))
            except Exception:
                pass
    return state, err


def main(session_path: Path, probe_path: Path) -> None:
    sess = json.loads(session_path.read_text())
    start_ts, end_ts = int(sess["start"]), int(sess["end"])
    elapsed_min = (end_ts - start_ts) // 60

    state_probe, err_probe = parse_probe_log(probe_path, start_ts, end_ts)

    # Import session_card directly as a standalone module to avoid pulling
    # in HA via the package __init__ (which fails outside the HA runtime).
    import importlib.util as ilu

    repo_root = Path(__file__).resolve().parent.parent
    sc_path = repo_root / "custom_components" / "dreame_a2_mower" / "session_card.py"
    spec = ilu.spec_from_file_location("session_card", sc_path)
    sc = ilu.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(sc)  # type: ignore[union-attr]
    _compute_time_breakdown = sc._compute_time_breakdown

    # Probe-truth breakdown
    truth = _compute_time_breakdown(
        battery_samples=[], charging_samples=[],
        start_ts=start_ts, end_ts=end_ts,
        error_samples=[[t, c] for t, c in err_probe],
        state_samples=[[t, c] for t, c in state_probe],
    )

    # Integration-as-was breakdown (uses session.json's in_progress samples)
    integration = _compute_time_breakdown(
        battery_samples=sess.get("battery_samples") or [],
        charging_samples=sess.get("charging_status_samples") or [],
        start_ts=start_ts, end_ts=end_ts,
        error_samples=sess.get("error_samples") or [],
        state_samples=sess.get("state_samples") or [],
    )

    print(f"=== Session {session_path.name} ===")
    print(f"  start:  {dt.datetime.fromtimestamp(start_ts)}")
    print(f"  end:    {dt.datetime.fromtimestamp(end_ts)}")
    print(f"  wall:   {elapsed_min} min ({elapsed_min/60:.2f} h)")
    print()
    print("=== Probe-derived (ground truth) ===")
    print(f"  state transitions: {len(state_probe)}")
    print(f"  error transitions: {len(err_probe)}")
    _print_breakdown(truth, elapsed_min)
    print()
    print("=== Integration-archive samples ===")
    print(f"  state samples: {len(sess.get('state_samples') or [])}")
    print(f"  error samples: {len(sess.get('error_samples') or [])}")
    _print_breakdown(integration, elapsed_min)


def _print_breakdown(b, elapsed_min: int) -> None:
    mow, chg, rain, other = b
    s = (mow or 0) + (chg or 0) + rain + (other or 0)
    print(f"  Mowing:    {mow} min")
    print(f"  Charging:  {chg} min")
    print(f"  Rain:      {rain} min")
    print(f"  Other:     {other} min")
    matches = "matches" if s == elapsed_min else f"OFF BY {s - elapsed_min}"
    print(f"  SUM:       {s} min  ({matches})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: state_partition.py <session.json> <probe_log.jsonl>",
              file=sys.stderr)
        sys.exit(2)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
