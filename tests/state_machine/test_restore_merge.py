"""Pure restore-then-merge logic for in_progress.json reconciliation."""
from custom_components.dreame_a2_mower.coordinator._restore_merge import (
    merge_in_progress_payloads,
)


def test_disk_empty_uses_memory():
    """If disk payload is None, memory wins as-is."""
    mem = {
        "session_start_ts": 100,
        "track": [[100, 1, 1, 0.0, None, 0, "mowing"]],
        "battery_samples": [[100, 95]],
    }
    out = merge_in_progress_payloads(disk=None, memory=mem)
    assert out == mem


def test_memory_empty_uses_disk():
    """If memory has no session yet, disk wins (the common race case)."""
    disk = {
        "session_start_ts": 100,
        "track": [[100, 1, 1, 0.0, None, 0, "mowing"]],
        "battery_samples": [[100, 95]],
    }
    mem = {"session_start_ts": None, "track": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["session_start_ts"] == 100
    assert out["track"] == [[100, 1, 1, 0.0, None, 0, "mowing"]]
    assert out["battery_samples"] == [[100, 95]]


def test_merge_preserves_distinct_same_second_points():
    # Disk + memory are same-session prefixes captured at ~5 Hz: several
    # distinct positions share one integer second. The merge must keep ALL
    # distinct points (full-row dedup), not collapse them by timestamp.
    disk = {
        "session_start_ts": 1000,
        "track": [
            [1000.0, 0.0, 0.0, 0.0, None, 0, "traversal"],
            [1000.0, 0.5, 0.0, 0.0, None, 0, "traversal"],  # same t, diff x
            [1000.0, 1.0, 0.0, 0.1, None, 0, "mowing"],      # same t, diff x
        ],
    }
    memory = {
        "session_start_ts": 1000,
        "track": [
            [1000.0, 1.0, 0.0, 0.1, None, 0, "mowing"],      # exact dup of disk row → deduped
            [1001.0, 1.5, 0.0, 0.2, None, 0, "mowing"],      # new point
        ],
    }
    out = merge_in_progress_payloads(disk=disk, memory=memory)
    # 3 distinct disk rows + 1 new memory row; the exact-dup row collapses.
    assert len(out["track"]) == 4
    xs = [r[1] for r in out["track"]]
    assert xs == [0.0, 0.5, 1.0, 1.5]  # sorted by t, all distinct positions kept


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
    disk = {
        "session_start_ts": 100,
        "track": [[100, 99, 99, 0.0, None, 0, "mowing"]],
        "battery_samples": [[100, 50]],
    }
    mem = {"session_start_ts": 100_000_000, "track": [], "battery_samples": []}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["session_start_ts"] == 100_000_000
    assert out["track"] == []
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


def test_last_direction_merged_per_map_memory_wins_on_overlap():
    """Memory's value for an overlapping map_id beats disk's older value."""
    disk = {
        "session_start_ts": 100,
        "last_all_area_mow_direction_deg": {0: 45, 1: 90},
    }
    mem = {
        "session_start_ts": 100,
        "last_all_area_mow_direction_deg": {0: 135},  # overlap on map 0
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["last_all_area_mow_direction_deg"] == {0: 135, 1: 90}


def test_last_direction_restored_from_disk_when_memory_empty():
    """Memory has no recorded directions yet (e.g. fresh restart); disk fills in."""
    disk = {"session_start_ts": 100, "last_all_area_mow_direction_deg": {0: 45}}
    mem = {"session_start_ts": 100, "last_all_area_mow_direction_deg": {}}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["last_all_area_mow_direction_deg"] == {0: 45}


def test_last_direction_string_keys_from_json_normalized_to_int():
    """JSON round-trip stringifies int keys; restore normalizes back."""
    disk = {
        "session_start_ts": 100,
        # JSON-decoded payload has string keys
        "last_all_area_mow_direction_deg": {"0": 45, "1": 90},
    }
    mem = {"session_start_ts": 100, "last_all_area_mow_direction_deg": {}}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["last_all_area_mow_direction_deg"] == {0: 45, 1: 90}
