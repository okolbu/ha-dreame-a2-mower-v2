# B1b — Retry Helper Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three ad-hoc retry loops in `cloud_client.py` with one sync helper `_http_retry`, eliminate the 3×3=9 stacked-loop bug on action calls, and pin the helper's contract with unit tests.

**Architecture:** Module-level sync helper `_http_retry(action, *, max_attempts, delay_s, should_retry)` lives in `cloud_client.py` near the top. Each call site's action lambda is responsible for raising on logical failure; the helper sees exceptions only and decides whether to retry. `time.sleep` is fine because all three call sites run in executor threads.

**Tech Stack:** Python 3.11+ (`typing.Callable`, `typing.TypeVar`), `pytest`, `unittest.mock`. No new dependencies.

**Reference docs (do NOT modify):**
- Design: `docs/superpowers/specs/2026-05-19-block1b-retry-helper-design.md`
- Discovery findings: `docs/superpowers/specs/2026-05-19-block1b-retry-helper-design.md` cites `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 2.

**Output:** 5 commits prefixed `audit-b1b:`. Push to `origin/main` after T5.

**Hard rules:**
- No source edits outside the files named in each task. If a task would need to touch a file not in its scope, STOP and report.
- Every task ends with `pytest tests/ -q` green.
- T4 is the only commit that intentionally changes user-visible behaviour (action ceiling 9 → 3); every other commit must be semantically equivalent to the pre-edit code.

---

## Task 1: Add `_http_retry` helper + unit tests

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` (add helper + imports near top)
- Create: `tests/unit/test_http_retry.py`

- [ ] **Step 1: Find the insertion point in `cloud_client.py`**

Run:
```bash
grep -n "^_LOGGER \|^_LOGGER=\|^_LOGGER:" custom_components/dreame_a2_mower/cloud_client.py
```

Confirm where `_LOGGER` is defined (likely near top, ~line 30-40). The helper goes right AFTER `_LOGGER` and any module-level constants, BEFORE the first class definition.

Run:
```bash
grep -n "^class \|^from typing\|^import typing\|^TypeVar" custom_components/dreame_a2_mower/cloud_client.py | head -5
```

If `from typing import Callable` or `TypeVar` already exists, you'll add `T = TypeVar("T")` after those imports. Otherwise add both.

- [ ] **Step 2: Write the failing test file**

Create `tests/unit/test_http_retry.py` with the full test content:

```python
"""Unit tests for cloud_client._http_retry.

Tests the retry helper's contract: max_attempts, delay_s,
should_retry, and the no-op / re-raise edge cases. The helper is
module-level in cloud_client.py and runs in executor threads, so
time.sleep is the correct sleep API.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from custom_components.dreame_a2_mower.cloud_client import _http_retry


def test_success_first_attempt():
    """Action returns immediately → called once → returns its value."""
    action = Mock(return_value="ok")
    result = _http_retry(action, max_attempts=3)
    assert result == "ok"
    assert action.call_count == 1


def test_success_after_n_attempts():
    """Action fails N-1 times, succeeds on N-th. Sleep called N-1 times."""
    action = Mock(side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), "ok"])
    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep") as mock_sleep:
        result = _http_retry(action, max_attempts=3, delay_s=1.5)
    assert result == "ok"
    assert action.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(1.5)


def test_all_attempts_fail_reraises_last():
    """Every attempt fails → helper re-raises the LAST exception."""
    last_exc = RuntimeError("attempt-3")
    action = Mock(side_effect=[RuntimeError("attempt-1"), RuntimeError("attempt-2"), last_exc])
    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep"):
        with pytest.raises(RuntimeError, match="attempt-3"):
            _http_retry(action, max_attempts=3)
    assert action.call_count == 3


def test_should_retry_false_reraises_immediately():
    """should_retry returns False → re-raise on first failure, no sleep."""
    action = Mock(side_effect=RuntimeError("non-retryable"))
    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="non-retryable"):
            _http_retry(action, max_attempts=3, should_retry=lambda _exc: False)
    assert action.call_count == 1
    mock_sleep.assert_not_called()


def test_delay_s_zero_skips_sleep():
    """delay_s=0 → time.sleep is never called even on retry."""
    action = Mock(side_effect=[RuntimeError("fail"), "ok"])
    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep") as mock_sleep:
        result = _http_retry(action, max_attempts=2, delay_s=0.0)
    assert result == "ok"
    mock_sleep.assert_not_called()


def test_max_attempts_one_no_retry():
    """max_attempts=1 → action runs once, no sleep, re-raises on failure."""
    action = Mock(side_effect=RuntimeError("once"))
    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep") as mock_sleep:
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

    with patch("custom_components.dreame_a2_mower.cloud_client.time.sleep"):
        result = _http_retry(action, max_attempts=2, should_retry=predicate)
    assert result == "ok"
    assert seen == [exc]  # exact instance, not a wrapper
```

- [ ] **Step 3: Run tests to verify they fail with ImportError**

Run: `pytest tests/unit/test_http_retry.py -v`
Expected: every test fails with `ImportError: cannot import name '_http_retry' from 'custom_components.dreame_a2_mower.cloud_client'`. This confirms the test file is wired up correctly and the symbol doesn't yet exist.

- [ ] **Step 4: Add the helper in `cloud_client.py`**

Add the import line (if missing — check first with grep):

```python
from typing import Callable, TypeVar
```

Add the TypeVar near the top of the file, after the typing imports:

```python
T = TypeVar("T")
```

Add the helper function immediately AFTER `_LOGGER` declaration and BEFORE the first `class` definition. Exact content:

```python
def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int,
    delay_s: float = 0.0,
    should_retry: Callable[[BaseException], bool] = lambda _exc: True,
) -> T:
    """Run action() up to max_attempts times, retrying on exception.

    Semantics:
      - max_attempts must be >= 1 (raises ValueError otherwise).
      - On success: return action()'s return value immediately.
      - On exception: if should_retry(exc) returns True AND attempts
        remain, sleep delay_s and retry. Otherwise re-raise.
      - delay_s == 0 (default): no sleep between attempts.

    Helper uses blocking time.sleep — by design, since callers run in
    executor threads.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return action()
        except BaseException as exc:
            last_exc = exc
            if not should_retry(exc):
                raise
            if attempt < max_attempts - 1 and delay_s > 0:
                time.sleep(delay_s)
    assert last_exc is not None  # unreachable: loop always raises or returns
    raise last_exc
```

Confirm `time` is already imported at the top of `cloud_client.py` (it is — used by the existing `time.sleep(8)` in `send()`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_http_retry.py -v`
Expected: all 9 tests pass.

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass (1595 previous + 9 new = 1604; note actual baseline numbers from the last B1a commit).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py tests/unit/test_http_retry.py
git commit -m "audit-b1b: add _http_retry helper + 9 unit tests"
```

---

## Task 2: Flip `request()` to use `_http_retry`

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` — `request()` method (currently around L1378–L1428)

The change is internal-only — the public method signature and return-value semantics are unchanged. Current `request()` has a retry loop wrapping the HTTP POST; the post-loop block handles status 200/401/other. We replace the retry loop, NOT the post-loop block.

- [ ] **Step 1: Read the current `request()` body**

Run: `sed -n '1378,1428p' custom_components/dreame_a2_mower/cloud_client.py`

Note: line numbers may have shifted slightly due to T1's additions near the top of the file. Confirm the function with `grep -n "def request" custom_components/dreame_a2_mower/cloud_client.py`.

Current shape (abridged):
```python
def request(self, url: str, data: Any, retry_count: int = 2) -> Any:
    strings = self._ensure_strings()
    retries = 0
    if not retry_count or retry_count < 0:
        retry_count = 0
    response = None
    while retries < retry_count + 1:
        try:
            if self._key_expire and time.time() > self._key_expire:
                self.login()
            headers = { ... }
            response = self._session.post(url, headers=headers, data=data, timeout=15)
            break
        except requests.exceptions.Timeout:
            retries += 1
            response = None
            if self._connected:
                _LOGGER.warning("Error while executing request: Read timed out...")
        except Exception as ex:
            retries += 1
            response = None
            if self._connected:
                _LOGGER.warning("Error while executing request: %s", str(ex))
    # POST-LOOP: response is either a successful response or None.
    if response is not None:
        if response.status_code == 200:
            ...
        elif response.status_code == 401 and self._secondary_key:
            ...
        else:
            ...
```

- [ ] **Step 2: Replace the retry loop with `_http_retry`**

Use Edit. The `old_string` is the loop block from `retries = 0` through the final `_LOGGER.warning("Error while executing request: %s", str(ex))` (inclusive). The `new_string` is:

```python
        if not retry_count or retry_count < 0:
            retry_count = 0

        def _do_post() -> Any:
            if self._key_expire and time.time() > self._key_expire:
                self.login()
            headers = {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Language": "en-US;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                strings[47]: strings[3],
                strings[49]: strings[5],
                strings[50]: self._ti if self._ti else strings[6],
                strings[51]: strings[52],
                strings[46]: self._key,
            }
            if self._country == "cn":
                headers[strings[48]] = strings[4]
            return self._session.post(
                url, headers=headers, data=data, timeout=15
            )

        def _log_and_retry(exc: BaseException) -> bool:
            if isinstance(exc, requests.exceptions.Timeout):
                if self._connected:
                    _LOGGER.warning(
                        "Error while executing request: Read timed out. "
                        "(read timeout=15): %s",
                        data,
                    )
            elif self._connected:
                _LOGGER.warning("Error while executing request: %s", str(exc))
            return True

        try:
            response = _http_retry(
                _do_post,
                max_attempts=retry_count + 1,
                should_retry=_log_and_retry,
            )
        except Exception:
            response = None
```

Key points to verify when constructing the Edit:
- The `_do_post` closure captures `url`, `data`, `strings`, `self`.
- `_log_and_retry` always returns True (matches current behaviour: any exception triggers a retry).
- The wrapping `try/except Exception: response = None` preserves the current behaviour where total failure leaves `response = None` for the post-loop block to handle.
- The post-loop block (everything after) is unchanged.

- [ ] **Step 3: Verify `request()` compiles and is semantically equivalent**

Run: `python -m py_compile custom_components/dreame_a2_mower/cloud_client.py`
Expected: clean.

Run: `pytest tests/ -q`
Expected: all tests pass (no behavioural test should fail because behaviour is preserved).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py
git commit -m "audit-b1b: flip request() to use _http_retry"
```

---

## Task 3: Flip `get_file()` to use `_http_retry`

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` — `get_file()` method (currently around L1215–L1233)

`get_file()` retries on both exceptions and non-200 HTTP status. The flip introduces a private `_NonOKStatus` exception so the helper sees a single "raise" path.

- [ ] **Step 1: Read the current `get_file()` body**

Run: `grep -n "def get_file" custom_components/dreame_a2_mower/cloud_client.py`

Then `sed -n 'A,Bp' custom_components/dreame_a2_mower/cloud_client.py` with the right range.

Current shape:
```python
def get_file(self, url: str, retry_count: int = 4) -> Any:
    """Download raw bytes from a signed OSS URL.

    Source: legacy ``dreame/protocol.py`` ``get_file()``.
    """
    retries = 0
    if not retry_count or retry_count < 0:
        retry_count = 0
    while retries < retry_count + 1:
        try:
            response = self._session.get(url, timeout=15)
        except Exception as ex:
            response = None
            _LOGGER.warning("Unable to get file at %s: %s", url, ex)
        if response is not None and response.status_code == 200:
            return response.content
        retries = retries + 1
    return None
```

- [ ] **Step 2: Replace the loop with `_http_retry`**

Use Edit. `old_string` covers from `retries = 0` through `return None`. `new_string` is:

```python
        if not retry_count or retry_count < 0:
            retry_count = 0

        class _NonOKStatus(Exception):
            """Raised inside the action lambda when HTTP status != 200."""

        def _do_get() -> bytes:
            response = self._session.get(url, timeout=15)
            if response.status_code != 200:
                raise _NonOKStatus(response.status_code)
            return response.content

        def _log_and_retry(exc: BaseException) -> bool:
            if isinstance(exc, _NonOKStatus):
                _LOGGER.warning(
                    "Unable to get file at %s: HTTP %s", url, exc.args[0]
                )
            else:
                _LOGGER.warning("Unable to get file at %s: %s", url, exc)
            return True

        try:
            return _http_retry(
                _do_get,
                max_attempts=retry_count + 1,
                should_retry=_log_and_retry,
            )
        except Exception:
            return None
```

Verify:
- `_NonOKStatus` is defined inside `get_file()` (function scope, not module).
- `_do_get` returns `bytes` on success, raises on logical failure.
- `_log_and_retry` always returns True (matches current behaviour).
- The outer try/except converts re-raise after exhausting attempts into the legacy `return None`.

- [ ] **Step 3: Verify `get_file()` compiles and tests pass**

Run: `python -m py_compile custom_components/dreame_a2_mower/cloud_client.py`
Run: `pytest tests/ -q`
Both expected clean / green.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py
git commit -m "audit-b1b: flip get_file() to use _http_retry"
```

---

## Task 4: Flip `send()` action path — eliminate the stacked-loop bug

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client.py` — `send()` method (currently around L540–L620)

This task changes user-visible behaviour: action call retry ceiling drops from 3 × 3 = 9 to exactly 3 (1 inner attempt × 3 outer attempts). Wall-clock unchanged (~16 s with two 8 s delays).

- [ ] **Step 1: Read the current `send()` body**

Run: `grep -n "def send" custom_components/dreame_a2_mower/cloud_client.py | head -5`

Find the `send()` method (not `send_async`). Read the action-path block (currently around L578–L620):

```python
attempts = 3 if method == "action" else 1
for attempt in range(attempts):
    self._id = self._id + 1
    api_response = self._api_call(
        url,
        { ... },
        retry_count,
    )
    if (
        api_response
        and "data" in api_response
        and api_response["data"]
        and "result" in api_response["data"]
    ):
        self._last_send_error_code = None
        return api_response["data"]["result"]

    error_code = api_response.get("code") if api_response else None
    self._last_send_error_code = error_code
    if error_code:
        _LOGGER.warning(
            "Cloud send error %s for %s (attempt %d/%d): %s",
            error_code, method, attempt + 1, attempts, api_response.get("msg", ""),
        )
        if method == "action" and error_code != 80001 and attempt < attempts - 1:
            sleep(8)
            continue
    break
return None
```

- [ ] **Step 2: Replace the loop with the new structure**

The new structure uses `_http_retry` for action calls (with `retry_count=0` passed to `_api_call` to disable the inner retry) and falls through to a single attempt for non-action calls.

Use Edit. `old_string` is the entire block above (from `attempts = 3 if method == "action" else 1` through `return None`). `new_string` is:

```python
        class _SendFailed(Exception):
            """Raised when an action send returns a non-success, retryable response."""

        def _send_once() -> Any:
            self._id = self._id + 1
            inner_retry_count = 0 if method == "action" else retry_count
            api_response = self._api_call(
                url,
                {
                    "did": str(self._did),
                    "id": self._id,
                    "data": {
                        "did": str(self._did),
                        "id": self._id,
                        "method": method,
                        "params": parameters,
                        "from": "XXXXXX",
                    },
                },
                inner_retry_count,
            )
            if (
                api_response
                and "data" in api_response
                and api_response["data"]
                and "result" in api_response["data"]
            ):
                self._last_send_error_code = None
                return api_response["data"]["result"]

            error_code = api_response.get("code") if api_response else None
            self._last_send_error_code = error_code
            if error_code:
                _LOGGER.warning(
                    "Cloud send error %s for %s: %s",
                    error_code, method, api_response.get("msg", "") if api_response else "",
                )
                # 80001 = "device unreachable via cloud relay".
                # On g2408 this is permanent — fast-return None without retrying.
                if error_code == 80001:
                    return None
            raise _SendFailed(error_code)

        if method == "action":
            try:
                return _http_retry(
                    _send_once,
                    max_attempts=3,
                    delay_s=8.0,
                    should_retry=lambda exc: isinstance(exc, _SendFailed),
                )
            except _SendFailed:
                return None
        else:
            try:
                return _send_once()
            except _SendFailed:
                return None
```

Key correctness points:
- For `method == "action"`: `_send_once` uses `inner_retry_count=0` so `_api_call → request` runs the inner retry exactly once. Outer `_http_retry` runs `_send_once` up to 3 times with 8 s delays. Total attempts = 3 × 1 = 3. ✓ (was 3 × 3 = 9)
- For non-action calls: `_send_once` uses `inner_retry_count=retry_count` (the parameter the caller passed). Behaviour is "run once, with whatever inner retry the caller asked for". Same as today's `attempts=1` path.
- 80001 returns `None` directly from `_send_once` — no exception, no retry. Same as today's break.
- Per-attempt logging shows `error_code` and `msg` but drops the `attempt N/M` count (now meaningless after the structural change). The action-call retry pattern is still readable from the wall-clock timing.

- [ ] **Step 3: Confirm the file compiles**

Run: `python -m py_compile custom_components/dreame_a2_mower/cloud_client.py`
Expected: clean.

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass.

If any test fails because it asserted "send() called _api_call 9 times" or similar, that test was pinning the BUG and needs to be updated to assert "3 times". Surface the test name to the controller before changing it.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client.py
git commit -m "$(cat <<'EOF'
audit-b1b: flip send() action path to _http_retry; fix 3×3=9 ceiling

The previous outer-loop in send() ran 3 attempts; each called _api_call
which calls request() with retry_count=2 (3-attempt inner loop). Effective
ceiling: 9 attempts per user-initiated action.

New shape: action path passes retry_count=0 to _api_call so the inner
loop runs exactly once per outer attempt. Outer _http_retry runs that
once-per-call lambda up to 3 times with 8s delays. Total attempts = 3,
wall-clock unchanged (~16s with two 8s delays).

Discovery § 2.3 confirmed this as a bug, not behaviour to preserve.
EOF
)"
```

---

## Task 5: Final verification + push

**Files:** none (read-only verification).

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 2: Compile every integration file**

Run:
```bash
python -m py_compile $(find custom_components/dreame_a2_mower -name '*.py' -not -path '*/__pycache__/*')
```
Expected: clean (no output).

- [ ] **Step 3: Confirm `_http_retry` is module-public-ish**

The helper is named `_http_retry` (single underscore — module-private convention). Confirm it's accessible from the test:
```bash
python -c "from custom_components.dreame_a2_mower.cloud_client import _http_retry; print(_http_retry.__doc__.splitlines()[0])"
```
Expected: prints the first docstring line ("Run action() up to max_attempts times, retrying on exception.").

- [ ] **Step 4: Confirm no old retry-loop patterns remain**

Run:
```bash
grep -n "while retries < retry_count" custom_components/dreame_a2_mower/cloud_client.py
```
Expected: no output (both loops removed; only the `_http_retry` helper remains).

```bash
grep -n "for attempt in range(attempts)" custom_components/dreame_a2_mower/cloud_client.py
```
Expected: no output (the outer `send()` loop is gone).

- [ ] **Step 5: Confirm helper sites count is 3**

```bash
grep -c "_http_retry(" custom_components/dreame_a2_mower/cloud_client.py
```
Expected: 4 — one definition site + three call sites (request, get_file, send action path).

- [ ] **Step 6: Run `inventory_audit.py`**

```bash
python tools/inventory_audit.py 2>&1 | tail -5
```
Expected: passes (no `[error]` output).

- [ ] **Step 7: Push to origin/main**

```bash
git push origin main
```

Per memory `feedback_push_upstream_regularly.md`: HACS pulls from origin/main; push to keep history visible.

- [ ] **Step 8: User-led smoke check**

After push, the user does this on their live HA:
1. Trigger a `lawn_mower.start_mowing` action (or `button.start_mowing` / equivalent).
2. Confirm the mower starts (a routine action call succeeds).
3. Force-fail an action (e.g. while the mower is offline) and observe the log shows exactly 3 attempts, not 9. If you can't force-fail, monitor a real action call and confirm it doesn't take ~30s in the worst case.
4. Confirm general cloud refreshes (`Refresh from cloud` button) still work.

If the user reports a regression, identify the offending commit by bisecting B1b commits (`git bisect`) and revert.

---

## Done

After T5 passes:

- **Block 1b complete.** Three call sites in `cloud_client.py` consolidated onto one `_http_retry` helper. Stacked-loop bug fixed.
- 9 new unit tests pin the helper's contract.
- Helper relocates to `cloud_client/_retry.py` in B1d (out of scope here).

**Next phase:** B1c (`_cached_*` shadow removal + redundant refresher deletion) — independent of the retry helper. Brainstorm when ready.
