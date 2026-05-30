from custom_components.dreame_a2_mower.live_map.classify import (
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
