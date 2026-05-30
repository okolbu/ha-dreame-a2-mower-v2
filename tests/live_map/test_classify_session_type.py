from custom_components.dreame_a2_mower.live_map.classify import (
    CLOUD_FINALIZED_SESSION_TYPES,
    classify_session_type,
)


def test_manual_when_op_15():
    assert classify_session_type(
        last_task_op=15, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None,
    ) == ("manual_drive", None)


def test_mow_when_start_code_seen():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=True, area_ever_positive=False,
        last_point_end_code=None,
    )[0] == "mow"


def test_mow_when_area_positive_even_without_start_code():
    assert classify_session_type(
        last_task_op=103, saw_mow_start=False, area_ever_positive=True,
        last_point_end_code=None,
    )[0] == "mow"


def test_maintenance_run_arrived():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=75,
    ) == ("maintenance_run", "arrived")


def test_maintenance_run_could_not_reach():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=76,
    ) == ("maintenance_run", "could_not_reach")


def test_maintenance_run_unknown_outcome_on_midrun_abort():
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None,
    ) == ("maintenance_run", "unknown")


# ---------------------------------------------------------------------------
# Patrol (s2p50 op=108 / s2p2=51 / summary.mode=108) — a 4th session type that
# finalizes via the CLOUD path (it produces an OSS summary), unlike the other
# non-mow types. Verified 2026-05-30 against the real patrol archive
# (mode=108, start_mode=0, md5 present, area≈0).
# ---------------------------------------------------------------------------

def test_patrol_when_op_108():
    assert classify_session_type(
        last_task_op=108, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None,
    ) == ("patrol", None)


def test_patrol_when_s2p2_51_seen_even_without_op_echo():
    """Scheduled / op-not-echoed patrols still carry s2p2=51 on the wire."""
    assert classify_session_type(
        last_task_op=None, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None, saw_patrol_start=True,
    ) == ("patrol", None)


def test_patrol_beats_maintenance_default_even_with_end_code():
    """op=108 must classify patrol BEFORE the maintenance-run default — a
    patrol that ends near the dock could carry a 75/76, but it is still a
    patrol (cloud-finalized), not a maintenance run."""
    assert classify_session_type(
        last_task_op=108, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=76,
    )[0] == "patrol"


def test_manual_op_15_still_beats_patrol():
    """op=15 (manual) is checked first; never misread as patrol."""
    assert classify_session_type(
        last_task_op=15, saw_mow_start=False, area_ever_positive=False,
        last_point_end_code=None, saw_patrol_start=True,
    ) == ("manual_drive", None)


def test_cloud_finalized_types_are_mow_and_patrol():
    assert CLOUD_FINALIZED_SESSION_TYPES == frozenset({"mow", "patrol"})
    assert "maintenance_run" not in CLOUD_FINALIZED_SESSION_TYPES
    assert "manual_drive" not in CLOUD_FINALIZED_SESSION_TYPES
