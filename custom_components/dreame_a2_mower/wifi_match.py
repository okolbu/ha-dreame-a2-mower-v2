"""WiFi heatmap → map_id correlator (v1.0.10a6+).

The Dreame cloud auto-generates heatmaps overnight and drops them into
OSS with no map_id in the body or filename. Inferring which logical
map a heatmap belongs to via geometry alone is fragile when:

- Two maps share an overlapping bbox (rare but possible on small
  lots / shared dock locations).
- Maps have identical extents (e.g. user remapped after a firmware
  update without moving the dock).
- The heatmap predates the current set of maps (delayed cloud
  flush during a map rotation).

This module solves the problem from the **other** direction: each
mowing session records its own RSSI fingerprint in
``LiveMapState.wifi_samples`` — a list of ``(x_m, y_m, rssi_dbm,
ts_unix)`` tuples captured at every s1p1 heartbeat. Those fingerprints
are persisted with the session archive blob. When a new heatmap
arrives, we score it against each recent session's samples and pick
the session whose map_id agrees best.

Scoring formula (see ``match_heatmap_to_session``):

    coverage    = fraction of session samples that fall inside the
                  heatmap's bbox
    mean_delta  = mean |sample_rssi − heatmap_cell_rssi| over samples
                  that landed in a cell with non-null data
    score       = coverage / (1 + mean_delta / 10)

The 1/(1 + Δ/10) shape gives a heavy preference to low-disagreement
matches without going to zero on noisy ones — a session that is
clearly inside the bbox but has 15 dBm typical agreement scores
0.4× of a perfectly-overlapping session, not 0.

Anything that fails to land any samples inside the heatmap bbox is
skipped (coverage = 0). The function returns ``None`` when no
candidate produced a non-zero score.

No HA dependency — this module is layer-2 (pure Python / dataclasses).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# (x_m, y_m, rssi_dbm, ts_unix)
WifiSample = tuple[float, float, int, int]


# RSSI grid sentinel: 1 = "no data captured in this cell" per the
# cloud's wifimap body schema.
NO_DATA_SENTINEL = 1


@dataclass(frozen=True)
class MatchScore:
    """Per-candidate match diagnostic. Exposed for logging / tests."""

    map_id: int
    coverage: float
    mean_delta: float
    score: float
    samples_in_bbox: int
    samples_total: int


def match_heatmap_to_session(
    heatmap_grid: Sequence[int],
    heatmap_width: int,
    heatmap_height: int,
    heatmap_resolution_m: int,
    heatmap_start_x_m: float,
    heatmap_start_y_m: float,
    candidates: Iterable[tuple[int, Sequence[WifiSample]]],
) -> int | None:
    """Pick the session whose RSSI samples best fit ``heatmap_grid``.

    See module docstring for the scoring formula.

    Parameters
    ----------
    heatmap_grid:
        Flat ``width * height`` row-major sequence of dBm values from
        the cloud body's ``data`` field. ``1`` means "no data" and is
        skipped when computing ``mean_delta`` (but still contributes
        to ``coverage`` since the sample IS inside the heatmap's
        physical bbox).
    heatmap_width, heatmap_height, heatmap_resolution_m:
        Cell counts and physical cell size, in metres. g2408 uses
        2 m × 2 m cells (``resolution=2``).
    heatmap_start_x_m, heatmap_start_y_m:
        Bbox origin in metres (charger-relative). Cloud bodies expose
        these in cm via ``startX``/``startY``; callers must convert
        before calling this function.
    candidates:
        Iterable of ``(map_id, samples)`` pairs. ``samples`` may be
        empty — those candidates produce ``score=0`` and are skipped.

    Returns
    -------
    int | None
        The ``map_id`` of the best-scoring candidate, or ``None`` when
        no candidate scored above zero.
    """
    scores = score_candidates(
        heatmap_grid=heatmap_grid,
        heatmap_width=heatmap_width,
        heatmap_height=heatmap_height,
        heatmap_resolution_m=heatmap_resolution_m,
        heatmap_start_x_m=heatmap_start_x_m,
        heatmap_start_y_m=heatmap_start_y_m,
        candidates=candidates,
    )
    if not scores:
        return None
    best = max(scores, key=lambda s: s.score)
    if best.score <= 0.0:
        return None
    return best.map_id


def score_candidates(
    *,
    heatmap_grid: Sequence[int],
    heatmap_width: int,
    heatmap_height: int,
    heatmap_resolution_m: int,
    heatmap_start_x_m: float,
    heatmap_start_y_m: float,
    candidates: Iterable[tuple[int, Sequence[WifiSample]]],
) -> list[MatchScore]:
    """Return per-candidate scores. Use when you need the diagnostics
    (which session was second-best, what was the mean dBm delta, …)
    in addition to the winning map_id."""
    if heatmap_width <= 0 or heatmap_height <= 0 or heatmap_resolution_m <= 0:
        return []
    if len(heatmap_grid) < heatmap_width * heatmap_height:
        return []
    res = float(heatmap_resolution_m)
    out: list[MatchScore] = []
    for map_id, samples in candidates:
        n = len(samples) if samples is not None else 0
        if n == 0:
            out.append(
                MatchScore(
                    map_id=map_id,
                    coverage=0.0,
                    mean_delta=0.0,
                    score=0.0,
                    samples_in_bbox=0,
                    samples_total=0,
                )
            )
            continue
        inside = 0
        delta_sum = 0.0
        delta_count = 0
        for sample in samples:
            try:
                x_m = float(sample[0])
                y_m = float(sample[1])
                rssi = int(sample[2])
            except (TypeError, ValueError, IndexError):
                continue
            cx = int((x_m - heatmap_start_x_m) / res)
            cy = int((y_m - heatmap_start_y_m) / res)
            if 0 <= cx < heatmap_width and 0 <= cy < heatmap_height:
                inside += 1
                cell_val = heatmap_grid[cy * heatmap_width + cx]
                if cell_val != NO_DATA_SENTINEL:
                    delta_sum += abs(rssi - int(cell_val))
                    delta_count += 1
        if inside == 0:
            score = 0.0
            mean_delta = 0.0
        else:
            coverage = inside / n
            mean_delta = (delta_sum / delta_count) if delta_count > 0 else 100.0
            score = coverage / (1.0 + mean_delta / 10.0)
        out.append(
            MatchScore(
                map_id=map_id,
                coverage=(inside / n) if n else 0.0,
                mean_delta=mean_delta,
                score=score,
                samples_in_bbox=inside,
                samples_total=n,
            )
        )
    return out
