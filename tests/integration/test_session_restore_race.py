"""Race scenario: MQTT push beats _restore_in_progress, merge keeps both sides' data."""
from custom_components.dreame_a2_mower.coordinator._restore_merge import (
    merge_in_progress_payloads,
)


def test_merge_preserves_disk_samples_when_memory_has_post_restart_samples():
    """The canonical 19h-session bug: disk has 8h of samples, memory has 1h of
    post-restart MQTT-pushed samples. After merge, all 9h survive.
    """
    disk = {
        "session_start_ts": 1000,
        "track": [
            [1010, 1, 1, 0.0, None, 0, "mowing"],
            [1020, 2, 2, 0.5, None, 0, "mowing"],
        ],
        "battery_samples": [[1010, 99], [1020, 98], [1030, 97]],
        "wifi_samples": [[0, 0, -60, 1010]],
        "charging_status_samples": [],
        "state_samples": [[1010, 0]],
        "error_samples": [],
        "charge_at_start": 100,
        "settings_snapshot": {"mowingHeight": 4},
    }
    memory = {
        "session_start_ts": 1000,
        "track": [[2000, 3, 3, 1.0, None, 0, "mowing"]],
        "battery_samples": [[2000, 90]],
        "wifi_samples": [],
        "charging_status_samples": [[2005, 1]],
        "state_samples": [],
        "error_samples": [],
        "charge_at_start": None,
        "settings_snapshot": None,
    }
    merged = merge_in_progress_payloads(disk=disk, memory=memory)
    assert [s[0] for s in merged["battery_samples"]] == [1010, 1020, 1030, 2000]
    track_xy = [(row[1], row[2]) for row in merged["track"]]
    assert (1, 1) in track_xy and (2, 2) in track_xy and (3, 3) in track_xy
    assert len(merged["wifi_samples"]) == 1
    assert merged["charging_status_samples"] == [[2005, 1]]
    assert merged["charge_at_start"] == 100
    assert merged["settings_snapshot"] == {"mowingHeight": 4}
