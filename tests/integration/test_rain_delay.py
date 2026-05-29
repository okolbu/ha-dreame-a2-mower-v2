"""rain_delay_started_at lifecycle: set on s2p2→56, derived properties, clear."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord():
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c._rain_delay_started_at = None
    c.data = MowerState()
    return c


def test_rain_resume_at_none_when_not_raining():
    c = _coord()
    assert c.rain_resume_at_unix is None
    assert c.rain_delay_active is False


def test_rain_resume_at_projects_from_resume_hours():
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = 2
    assert c.rain_resume_at_unix == 1000 + 2 * 3600


def test_rain_delay_active_within_window(monkeypatch):
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = 2  # resume_at = 8200
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.coordinator._core.time.time",
        lambda: 5000,
    )
    assert c.rain_delay_active is True
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.coordinator._core.time.time",
        lambda: 9000,  # past resume_at
    )
    assert c.rain_delay_active is False


def test_rain_delay_active_unbounded_when_resume_hours_unknown():
    c = _coord()
    c._rain_delay_started_at = 1000
    c.data.rain_protection_resume_hours = None
    assert c.rain_resume_at_unix is None
    assert c.rain_delay_active is True


def test_fires_and_sets_started_at_on_edge_into_56():
    class _LC:
        def __init__(self): self.fired = []
        def trigger(self, t, d): self.fired.append((t, d))
    c = _coord()
    lc = _LC(); c._lifecycle_event = lc
    c._fire_rain_delay_started_if_edge(old=0, new=56, now_unix=500)
    assert c._rain_delay_started_at == 500
    assert lc.fired == [("rain_delay_started", {"at_unix": 500})]
    lc.fired.clear()
    c._fire_rain_delay_started_if_edge(old=56, new=56, now_unix=600)  # no refire
    assert lc.fired == []
