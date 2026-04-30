"""Regression test: replay every property push from the user's external
MQTT probe through ``apply_property_to_state`` and assert nothing
unhandled slips through.

The user runs an independent MQTT logger (``probe_a2_mqtt.py``) that
captures every inbound message from the mower in JSONL files at
``probe_log_*.jsonl`` outside this repo. Treating that history as a
ground-truth corpus catches two classes of regression:

1. **New (siid, piid) slots** that have shown up on the wire but the
   integration doesn't yet handle. Without this test, a slot first
   surfaces as a single ``[NOVEL/property]`` warning per process at
   runtime; here we surface them up-front during CI.
2. **Apply-side decoder crashes** — feeding a real recorded value
   through ``apply_property_to_state`` validates that each slot's
   handler accepts the on-wire shape (list of ints for blobs, dicts
   for s2.51, etc).

The test skips gracefully when no probe logs are found, so it doesn't
break clean checkouts or CI runners that don't have the user's
historical data.

The user keeps the external probe on the **legacy** integration base
for the time being so it stays a stable third-party witness — useful
for diffing greenfield's state inferences against an independent
parser when something looks wrong.
"""

from __future__ import annotations

import glob
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.coordinator import (
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    apply_property_to_state,
)
from custom_components.dreame_a2_mower.mower.property_mapping import PROPERTY_MAPPING
from custom_components.dreame_a2_mower.mower.state import MowerState


# (siid, piid) pairs we have OBSERVED on the wire across all historical
# probe logs but have not yet decoded. Each entry deserves a future
# protocol-RE pass; in the meantime keeping them here documents the
# backlog and lets the regression test pass.
#
# When a slot moves from "undecoded" to "mapped", add it to
# PROPERTY_MAPPING (or _BLOB_SLOTS / _SUPPRESSED_SLOTS) and remove it
# from this list.
_PROBE_KNOWN_UNDECODED: set[tuple[int, int]] = {
    # s1 status fields beyond obstacle_flag — semantics not nailed down.
    # (1, 50), (1, 51), (1, 52) suppressed in the novelty pipeline as
    # empty-dict / boundary-marker noise (see _SUPPRESSED_SLOTS).
    # s2 status block — most are mapped, these aren't yet.
    (2, 52),
    (2, 53),
    (2, 54),
    (2, 55),
    (2, 62),
    # s5 protocol-debug slots — observed values; ongoing RE.
    # 5p104, 5p105, 5p106, 5p107 mapped as raw int diagnostic sensors
    # in v1.0.0a11 / v1.0.0a20.
    (5, 108),
    # (6, 117) suppressed in v1.0.0a49 alongside s1p52 — small-int
    # heartbeat that doesn't drive any state machine.
}


def _probe_log_paths() -> list[Path]:
    """Return absolute paths to every available probe_log_*.jsonl.

    Looks in the user's known location (``/data/claude/homeassistant/``)
    plus the repo's own ``tests/fixtures/`` in case a sample is checked
    in for CI.
    """
    candidates: list[str] = []
    candidates.extend(
        glob.glob("/data/claude/homeassistant/probe_log_*.jsonl")
    )
    candidates.extend(
        glob.glob(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "fixtures",
                "probe_log_*.jsonl",
            )
        )
    )
    return [Path(p) for p in sorted(set(candidates))]


def _iter_property_pushes(path: Path) -> Iterator[tuple[int, int, object]]:
    """Yield (siid, piid, value) for every properties_changed param.

    JSONL lines that don't fit the probe's recorded shape are skipped.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "mqtt_message":
            continue
        if entry.get("method") != "properties_changed":
            continue
        params = entry.get("params") or []
        if not isinstance(params, list):
            continue
        for p in params:
            if not isinstance(p, dict):
                continue
            try:
                siid = int(p["siid"])
                piid = int(p["piid"])
            except (KeyError, TypeError, ValueError):
                continue
            yield (siid, piid, p.get("value"))


def _slot_is_known(siid: int, piid: int) -> bool:
    """A slot is considered 'known' if it's in any of the four buckets."""
    key = (siid, piid)
    return (
        key in PROPERTY_MAPPING
        or key in _BLOB_SLOTS
        or key in _SUPPRESSED_SLOTS
        or key in _PROBE_KNOWN_UNDECODED
    )


@pytest.fixture(scope="module")
def probe_pushes() -> list[tuple[int, int, object]]:
    """Aggregate every (siid, piid, value) tuple across all probe logs."""
    pushes: list[tuple[int, int, object]] = []
    for path in _probe_log_paths():
        pushes.extend(_iter_property_pushes(path))
    return pushes


def test_probe_logs_available_or_skip(probe_pushes):
    """Either we have probe data to validate against, or we skip cleanly.

    This is a soft-skip that documents whether the regression actually
    ran. CI without probe access still passes.
    """
    if not probe_pushes:
        pytest.skip(
            "No probe_log_*.jsonl found — skipping wire-data regression."
        )


def test_every_probe_slot_is_known(probe_pushes):
    """Every (siid, piid) pair the mower has ever pushed must be in one
    of the four 'known' buckets: PROPERTY_MAPPING, _BLOB_SLOTS,
    _SUPPRESSED_SLOTS, or _PROBE_KNOWN_UNDECODED.

    A failure here means the mower has emitted a slot we've never seen
    before. The fix is to either map it (preferred) or add it to
    _PROBE_KNOWN_UNDECODED with a comment indicating future RE work.
    """
    if not probe_pushes:
        pytest.skip("No probe data.")
    seen: set[tuple[int, int]] = {(s, p) for (s, p, _v) in probe_pushes}
    unknown = sorted(s for s in seen if not _slot_is_known(*s))
    assert not unknown, (
        f"New protocol slot(s) seen on the wire that the integration "
        f"doesn't handle and aren't in _PROBE_KNOWN_UNDECODED: {unknown}.\n"
        "Either map them (PROPERTY_MAPPING) or add to "
        "_PROBE_KNOWN_UNDECODED with an RE comment."
    )


def test_apply_property_to_state_handles_every_probe_value(probe_pushes):
    """Replay every recorded push through apply_property_to_state and
    assert it does not raise.

    Catches per-value decoder crashes (e.g., a numeric range that
    overflows int(), a missing dict key in the s2.51 dispatcher, an
    unsupported s1.4 frame length).

    The MowerState is reset between pushes so we test each in isolation
    (covers cold-state and warm-state paths roughly equally — most
    handlers don't depend on prior state).
    """
    if not probe_pushes:
        pytest.skip("No probe data.")
    crashes: list[tuple[int, int, object, str]] = []
    for siid, piid, value in probe_pushes:
        # Skip slots we explicitly don't handle yet (the apply path
        # does nothing for them; they'd just no-op).
        if (siid, piid) in _PROBE_KNOWN_UNDECODED:
            continue
        try:
            apply_property_to_state(MowerState(), siid, piid, value)
        except Exception as ex:  # pragma: no cover — the assertion below covers
            crashes.append((siid, piid, value, repr(ex)))
    assert not crashes, (
        f"apply_property_to_state crashed on {len(crashes)} historical "
        f"push(es). First few: {crashes[:5]}"
    )


def test_probe_known_undecoded_does_not_overlap_mapped():
    """Sanity: a slot can't be both 'mapped' and 'known undecoded'.

    Catches stale entries — once a slot lands in PROPERTY_MAPPING it
    must be removed from _PROBE_KNOWN_UNDECODED.
    """
    overlap = (
        _PROBE_KNOWN_UNDECODED
        & (set(PROPERTY_MAPPING) | _BLOB_SLOTS | _SUPPRESSED_SLOTS)
    )
    assert not overlap, (
        f"Slots in _PROBE_KNOWN_UNDECODED also present in a mapped "
        f"bucket: {sorted(overlap)} — remove them from "
        "_PROBE_KNOWN_UNDECODED."
    )
