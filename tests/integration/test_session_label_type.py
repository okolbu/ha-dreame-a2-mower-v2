from types import SimpleNamespace
from custom_components.dreame_a2_mower.session_card import format_session_label


def _entry(**kw):
    base = dict(start_ts=1717081740, end_ts=1717083000, map_id=1,
                area_mowed_m2=0.0, duration_min=21, local_trail_complete=True)
    base.update(kw); return SimpleNamespace(**base)


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
