"""Tests for the centralised API-call log summarizer.

We don't want to dump full response bodies into DEBUG — they're noisy and
occasionally contain presigned OSS URLs or other secrets. The summarizer
produces a single-line description sufficient to follow a probe session
while omitting the body itself.
"""

from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.api_log import summarize_api_response


def test_summary_includes_url():
    line = summarize_api_response("home/getfileurl_v3", {"code": 0, "result": {}})
    assert "home/getfileurl_v3" in line


def test_summary_reports_code_when_present():
    line = summarize_api_response("x", {"code": 10001, "msg": "cannot be read"})
    assert "code=10001" in line


def test_summary_reports_dict_result_shape():
    payload = {"code": 0, "result": {"url": "https://...", "expires": 120}}
    line = summarize_api_response("x", payload)
    assert "result_type=dict" in line
    assert "expires" in line
    assert "url" in line


def test_summary_reports_list_result_shape():
    payload = {"code": 0, "result": [{"a": 1}, {"a": 2}, {"a": 3}]}
    line = summarize_api_response("x", payload)
    assert "result_type=list" in line
    assert "result_len=3" in line


def test_summary_for_none_payload():
    assert "payload=None" in summarize_api_response("x", None)


def test_summary_never_includes_full_result_values():
    """Summarizer must not leak arbitrary values — only structural info."""
    payload = {"code": 0, "result": {"token": "secret-should-not-leak"}}
    line = summarize_api_response("x", payload)
    assert "secret-should-not-leak" not in line


def test_summary_reports_top_level_keys_when_no_result_field():
    payload = {"code": 0, "msg": "ok", "something": 42}
    line = summarize_api_response("x", payload)
    # result-less payload — should still report shape
    assert "keys=" in line
    assert "msg" in line
    assert "something" in line


def test_summary_handles_scalar_result():
    payload = {"code": 0, "result": 42}
    line = summarize_api_response("x", payload)
    assert "result_type=int" in line
    # scalar type alone is structural — caller doesn't get the value either
    assert "42" not in line
