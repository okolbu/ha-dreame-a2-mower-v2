"""Pure restore-then-merge logic for in_progress.json reconciliation."""
from custom_components.dreame_a2_mower.coordinator._restore_merge import (
    merge_in_progress_payloads,
)


def test_disk_empty_uses_memory():
    """If disk payload is None, memory wins as-is."""
    mem = {"session_start_ts": 100, "legs": [[[1, 1]]], "battery_samples": [[100, 95]]}
    out = merge_in_progress_payloads(disk=None, memory=mem)
    assert out == mem


def test_memory_empty_uses_disk():
    """If memory has no session yet, disk wins (the common race case)."""
    disk = {"session_start_ts": 100, "legs": [[[1, 1]]], "battery_samples": [[100, 95]]}
    mem = {"session_start_ts": None, "legs": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["session_start_ts"] == 100
    assert out["legs"] == [[[1, 1]]]
    assert out["battery_samples"] == [[100, 95]]


def test_legs_union_dedupes_on_point_equality():
    """Same-session legs get unioned; identical points deduped."""
    disk = {
        "session_start_ts": 100,
        "legs": [[[1, 1], [2, 2]]],
    }
    mem = {
        "session_start_ts": 100,
        "legs": [[[2, 2], [3, 3]]],
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["legs"] == [[[1, 1], [2, 2], [3, 3]]]


def test_samples_union_dedupes_on_full_tuple():
    """Each sample list is unioned + deduped + sorted by ts."""
    disk = {
        "session_start_ts": 100,
        "battery_samples": [[100, 95], [200, 90], [300, 85]],
    }
    mem = {
        "session_start_ts": 100,
        "battery_samples": [[300, 85], [400, 80]],
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["battery_samples"] == [[100, 95], [200, 90], [300, 85], [400, 80]]


def test_stale_disk_session_is_dropped():
    """If disk start_ts > 5 min off from memory start_ts, drop disk (stale)."""
    disk = {"session_start_ts": 100, "legs": [[[99, 99]]], "battery_samples": [[100, 50]]}
    mem = {"session_start_ts": 100_000_000, "legs": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["session_start_ts"] == 100_000_000
    assert out["legs"] == []
    assert out["battery_samples"] == []


def test_charge_at_start_restored_when_memory_none():
    disk = {"session_start_ts": 100, "charge_at_start": 95}
    mem = {"session_start_ts": 100, "charge_at_start": None}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["charge_at_start"] == 95


def test_charge_at_start_memory_wins_when_set():
    disk = {"session_start_ts": 100, "charge_at_start": 95}
    mem = {"session_start_ts": 100, "charge_at_start": 90}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["charge_at_start"] == 90


def test_settings_snapshot_restored_when_memory_none():
    disk = {"session_start_ts": 100, "settings_snapshot": {"mowingHeight": 4}}
    mem = {"session_start_ts": 100, "settings_snapshot": None}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["settings_snapshot"] == {"mowingHeight": 4}
