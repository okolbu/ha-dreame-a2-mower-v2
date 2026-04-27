"""One-line structural summaries for Dreame cloud API responses.

The raw responses from the `/api/v2/…` endpoints routinely carry presigned
OSS URLs, bearer tokens, and other secrets that don't belong in a DEBUG
log. Every caller in ``dreame/protocol.py`` used to decide ad-hoc whether
to log at all; most didn't, which meant whole categories of failure
(silent 10001s, empty-list responses) had no audit trail.

This helper returns a single line describing the *shape* of each response
— enough to trace the call sequence during an RE session — without
leaking the values themselves.
"""

from __future__ import annotations

from typing import Any


def summarize_api_response(url: str, payload: Any) -> str:
    """Return a one-line structural description of an API response.

    Leaks *no* values — only types, lengths, and key names. Callers
    hand this straight to ``_LOGGER.debug`` without further formatting.
    """
    if payload is None:
        return f"url={url} payload=None"

    if not isinstance(payload, dict):
        return f"url={url} payload_type={type(payload).__name__}"

    parts = [f"url={url}"]
    if "code" in payload:
        parts.append(f"code={payload['code']}")

    if "result" in payload:
        result = payload["result"]
        result_type = type(result).__name__
        parts.append(f"result_type={result_type}")
        if isinstance(result, dict):
            parts.append(f"result_keys={sorted(result.keys())}")
        elif isinstance(result, list):
            parts.append(f"result_len={len(result)}")
            if result and isinstance(result[0], dict):
                parts.append(f"result_item_keys={sorted(result[0].keys())}")
    else:
        parts.append(f"keys={sorted(payload.keys())}")

    return " ".join(parts)
