"""Unit tests for cloud_client._http_retry.

Tests the retry helper's contract: max_attempts, delay_s,
should_retry, and the no-op / re-raise edge cases. The helper is
module-level in cloud_client/_helpers.py and runs in executor threads, so
time.sleep is the correct sleep API.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from custom_components.dreame_a2_mower.cloud_client._helpers import _http_retry


def test_success_first_attempt():
    """Action returns immediately → called once → returns its value."""
    action = Mock(return_value="ok")
    result = _http_retry(action, max_attempts=3)
    assert result == "ok"
    assert action.call_count == 1


def test_success_after_n_attempts():
    """Action fails N-1 times, succeeds on N-th. Sleep called N-1 times."""
    action = Mock(side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), "ok"])
    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep") as mock_sleep:
        result = _http_retry(action, max_attempts=3, delay_s=1.5)
    assert result == "ok"
    assert action.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(1.5)


def test_all_attempts_fail_reraises_last():
    """Every attempt fails → helper re-raises the LAST exception."""
    last_exc = RuntimeError("attempt-3")
    action = Mock(side_effect=[RuntimeError("attempt-1"), RuntimeError("attempt-2"), last_exc])
    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep"):
        with pytest.raises(RuntimeError, match="attempt-3"):
            _http_retry(action, max_attempts=3)
    assert action.call_count == 3


def test_should_retry_false_reraises_immediately():
    """should_retry returns False → re-raise on first failure, no sleep."""
    action = Mock(side_effect=RuntimeError("non-retryable"))
    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="non-retryable"):
            _http_retry(action, max_attempts=3, should_retry=lambda _exc: False)
    assert action.call_count == 1
    mock_sleep.assert_not_called()


def test_delay_s_zero_skips_sleep():
    """delay_s=0 → time.sleep is never called even on retry."""
    action = Mock(side_effect=[RuntimeError("fail"), "ok"])
    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep") as mock_sleep:
        result = _http_retry(action, max_attempts=2, delay_s=0.0)
    assert result == "ok"
    mock_sleep.assert_not_called()


def test_max_attempts_one_no_retry():
    """max_attempts=1 → action runs once, no sleep, re-raises on failure."""
    action = Mock(side_effect=RuntimeError("once"))
    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="once"):
            _http_retry(action, max_attempts=1, delay_s=5.0)
    assert action.call_count == 1
    mock_sleep.assert_not_called()


def test_max_attempts_zero_raises_valueerror():
    """max_attempts=0 → helper raises ValueError before calling action."""
    action = Mock()
    with pytest.raises(ValueError):
        _http_retry(action, max_attempts=0)
    action.assert_not_called()


def test_max_attempts_negative_raises_valueerror():
    """max_attempts<0 → same defensive ValueError."""
    action = Mock()
    with pytest.raises(ValueError):
        _http_retry(action, max_attempts=-1)
    action.assert_not_called()


def test_should_retry_sees_exception_instance():
    """should_retry is called with the actual exception instance."""

    class CustomError(RuntimeError):
        pass

    exc = CustomError("custom")
    action = Mock(side_effect=[exc, "ok"])
    seen = []

    def predicate(e: BaseException) -> bool:
        seen.append(e)
        return True

    with patch("custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep"):
        result = _http_retry(action, max_attempts=2, should_retry=predicate)
    assert result == "ok"
    assert seen == [exc]  # exact instance, not a wrapper
