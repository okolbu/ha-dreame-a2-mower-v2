"""Tests for the bounded NOVEL log-line ring buffer."""

from __future__ import annotations

import logging

from custom_components.dreame_a2_mower.observability.log_buffer import NovelLogBuffer


def _fresh_logger(name: str) -> logging.Logger:
    """Each test gets its own logger with no propagation, so test
    handlers don't leak across runs."""
    log = logging.getLogger(name)
    log.handlers.clear()
    log.propagate = False
    log.setLevel(logging.WARNING)
    return log


def test_buffer_records_matching_prefix():
    buf = NovelLogBuffer(maxlen=5, prefixes=("[NOVEL/property]",))
    handler = buf.as_handler()
    log = _fresh_logger("f6_9_1.test_a")
    log.addHandler(handler)
    log.warning("[NOVEL/property] siid=99 piid=42")
    log.warning("not novel: ignore me")
    lines = buf.lines()
    assert len(lines) == 1
    assert "siid=99" in lines[0]


def test_buffer_evicts_oldest_when_full():
    buf = NovelLogBuffer(maxlen=2, prefixes=("[NOVEL/value]",))
    handler = buf.as_handler()
    log = _fresh_logger("f6_9_1.test_b")
    log.addHandler(handler)
    log.warning("[NOVEL/value] one")
    log.warning("[NOVEL/value] two")
    log.warning("[NOVEL/value] three")
    lines = buf.lines()
    assert len(lines) == 2
    assert "two" in lines[0]
    assert "three" in lines[1]


def test_buffer_matches_any_listed_prefix():
    buf = NovelLogBuffer(
        maxlen=10,
        prefixes=("[NOVEL/property]", "[NOVEL_KEY/session_summary]"),
    )
    handler = buf.as_handler()
    log = _fresh_logger("f6_9_1.test_c")
    log.addHandler(handler)
    log.warning("[NOVEL/property] x")
    log.warning("[NOVEL_KEY/session_summary] y")
    log.warning("[NOVEL/value] z")  # not in our list
    lines = buf.lines()
    assert len(lines) == 2


def test_buffer_starts_empty():
    buf = NovelLogBuffer(maxlen=5, prefixes=("[NOVEL/property]",))
    assert buf.lines() == []


def test_lines_returns_independent_list():
    buf = NovelLogBuffer(maxlen=5, prefixes=("[NOVEL/property]",))
    handler = buf.as_handler()
    log = _fresh_logger("f6_9_1.test_d")
    log.addHandler(handler)
    log.warning("[NOVEL/property] a")
    snap1 = buf.lines()
    log.warning("[NOVEL/property] b")
    snap2 = buf.lines()
    # snap1 should not have grown.
    assert len(snap1) == 1
    assert len(snap2) == 2
