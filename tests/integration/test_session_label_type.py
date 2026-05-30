from types import SimpleNamespace
from custom_components.dreame_a2_mower.session_card import format_session_label


def _entry(**kw):
    base = dict(start_ts=1717081740, end_ts=1717083000, map_id=1,
                area_mowed_m2=0.0, duration_min=21, local_trail_complete=True)
    base.update(kw); return SimpleNamespace(**base)


def test_mode_and_start_mode_labels_match_decoded_mapping():
    """MODE_LABELS / START_MODE_LABELS must match the verified decode
    (inventory § summary_mode): 100 all-areas / 101 edge / 102 zone / 103 spot /
    108 patrol; start_mode 1=scheduled / 0=manual. (Old code had 102='All areas'
    and reversed start_mode — guesswork.)"""
    from custom_components.dreame_a2_mower.session_card import (
        MODE_LABELS, START_MODE_LABELS,
    )
    assert MODE_LABELS[100] == "All areas"
    assert MODE_LABELS[101] == "Edge"
    assert MODE_LABELS[102] == "Zone"
    assert MODE_LABELS[103] == "Spot"
    assert MODE_LABELS[108] == "Patrol"
    assert START_MODE_LABELS[1] == "Scheduled"
    assert START_MODE_LABELS[0].startswith("Manual")


def test_mow_label_unchanged():
    lbl = format_session_label(_entry(session_type="mow", area_mowed_m2=42.0))
    assert lbl.startswith("[Mowing] [Map 2]")


def test_maintenance_run_label():
    lbl = format_session_label(_entry(session_type="maintenance_run", outcome="could_not_reach"))
    assert lbl.startswith("[To Point] [Map 2]")
    assert "(blocked)" in lbl


def test_manual_drive_label():
    lbl = format_session_label(_entry(session_type="manual_drive"))
    assert lbl.startswith("[Manual] [Map 2]")


def test_back_compat_no_session_type_is_mow():
    lbl = format_session_label(_entry(area_mowed_m2=12.0))  # no session_type attr at all
    assert lbl.startswith("[Mowing] [Map 2]")
