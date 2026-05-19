# B1b — Retry Helper Consolidation (Design)

**Date:** 2026-05-19
**Status:** spec
**Parent (data-pipeline cycle):** `docs/superpowers/specs/2026-05-19-block1-data-pipeline-design.md`
**Discovery findings:** `docs/superpowers/specs/2026-05-19-block1-discovery-findings.md` § 2

## What this is

Second source-modifying phase of the integration audit. B1b extracts one
synchronous retry helper used by all three ad-hoc retry loops in
`cloud_client.py` and eliminates a confirmed stacked-loop bug that gives
action calls an effective ceiling of 9 attempts instead of 3.

## Goals

1. Add a single sync helper `_http_retry(action, *, max_attempts, delay_s,
   should_retry)` in `cloud_client.py`. Module-level function, not class
   member. Helper sees exceptions only — each call site's action lambda
   raises on logical failure.
2. Flip `cloud_client.py:1387` (`request()`) to use `_http_retry`. Default
   `should_retry` (retry on any exception) matches current behaviour. No
   user-visible change.
3. Flip `cloud_client.py:1219` (`get_file()`) to use `_http_retry`. The
   action lambda raises a private `_NonOKStatus` exception when
   `response.status_code != 200`. Default `should_retry` retries on it. No
   user-visible change.
4. Flip `cloud_client.py:578` (`send()` action path) to use `_http_retry`.
   **Delete the outer `for attempt in range(attempts)` loop entirely.** The
   inner `request()` retry is the only retry. The 8-second inter-attempt
   delay and 80001 break-fast behaviour stay, expressed through `delay_s`
   and a small `send`-local wrapper that performs the 80001 check.
5. Add unit tests pinning the helper's contract (success on first try /
   success after N / all fail / `should_retry=False` / `delay_s>0` /
   defensive `max_attempts<=0`).

## Non-goals

- No async sibling for `_http_retry`. All three call sites run in executor
  threads (sync code). Add an async sibling only when a real caller needs
  it (YAGNI).
- No file split. `_http_retry` lives in `cloud_client.py` module scope.
  B1d will relocate it to `cloud_client/_retry.py` as a 1-line move.
- No new retry logic beyond what already exists. The helper is a refactor
  that re-expresses current behaviour as one centralised primitive.
- No structural changes to `request()`, `get_file()`, or `send()` beyond
  what the flip needs. The 80001-break logic stays in `send()`, not
  hoisted into the helper.
- No changes to default retry counts at the public method level. The
  existing `retry_count=2` / `retry_count=4` / action-path `attempts=3`
  values stay; only the internal loop shape changes.
- No removal of `time.sleep(...)` in favour of `asyncio.sleep` — the call
  sites are executor threads where `time.sleep` is correct. (Async port
  is its own follow-up.)

## Hard constraint — no regression

Carried from the parent design:
- Entity `unique_id`, `entity_id`, friendly names, service signatures, event
  payloads, archive format unchanged.
- MowerState / CloudState shape unchanged.
- Cloud RPC behaviour from the caller's perspective unchanged. Auth, region
  routing, request headers, timeout, response parsing — all preserved.

**One documented behaviour change:** action calls' effective retry ceiling
drops from 3 × 3 = 9 to 3. This is the stacked-loop bug fix from discovery
§ 2.3, not a regression. Capture in the commit message + release notes.

## Helper contract

```python
def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int,
    delay_s: float = 0.0,
    should_retry: Callable[[BaseException], bool] = lambda _exc: True,
) -> T:
    """Run action() up to max_attempts times.

    On exception: if should_retry(exc) returns True AND attempts remain,
    sleep delay_s and retry. Otherwise re-raise the exception.
    On success: return action()'s return value immediately.

    Raises ValueError if max_attempts < 1 (defensive: caller bug).
    """
```

**Semantics:**
- `max_attempts=1`: action called once. No retry. Re-raise on failure.
- `max_attempts=N`: action called up to N times. Sleeps (N-1) times.
- `delay_s=0`: no sleep between attempts. Default.
- `should_retry` defaults to "any exception is retry-worthy", matching the
  existing `except Exception: retries += 1` pattern in all three sites.
- Helper uses blocking `time.sleep` — by design, since callers run in
  executor threads.

**Placement:** Module-level in `cloud_client.py`, immediately after
`_LOGGER` and before `class DreameA2CloudClient`. Imports added at top of
file: `from typing import Callable, TypeVar` and `T = TypeVar("T")`.

## Per-site flip detail

### `request()` at L1387

Current:
```python
while retries < retry_count + 1:
    try:
        response = ...HTTP POST...
        return response
    except requests.Timeout as exc:
        _LOGGER.warning(...)
    except Exception as exc:
        _LOGGER.warning(...)
    retries += 1
```

After:
```python
def _do_request() -> requests.Response:
    return ...HTTP POST...
return _http_retry(
    _do_request,
    max_attempts=retry_count + 1,
)
```

Existing per-attempt warning logs are preserved by wrapping the action
with `try: ...; except: _LOGGER.warning(...); raise`. Or moved into a
`should_retry` predicate that logs as a side effect (cleaner). Pick at
implementation time; both preserve user-visible behaviour.

### `get_file()` at L1219

Current: same loop shape as `request()` but also retries on
`response.status_code != 200` (not just exceptions).

After:
```python
class _NonOKStatus(Exception):
    """Raised inside get_file's action lambda when HTTP status != 200."""

def _do_fetch() -> bytes:
    response = ...HTTP GET...
    if response.status_code != 200:
        raise _NonOKStatus(response.status_code)
    return response.content

return _http_retry(
    _do_fetch,
    max_attempts=retry_count + 1,
)
```

`_NonOKStatus` is a private class defined inside `get_file()` (function
scope) so it doesn't pollute the module namespace.

### `send()` at L578 (action path)

Current (stacked loops):
```python
attempts = 3 if method == "action" else 1
for attempt in range(attempts):
    response = self._api_call(...)  # has its own retry loop in request()
    if action_code == 80001:
        break  # fast-break, don't retry
    if response_ok:
        break
    if attempt < attempts - 1:
        time.sleep(8)
```

The outer loop runs up to 3 times. Each iteration calls `_api_call → request`
which has its own 3-attempt retry loop. Effective ceiling: 9. This is the
bug.

After (single layer of retry):
```python
def _send_once() -> response_type:
    response = self._api_call(...)
    code = _extract_action_code(response)
    if code == 80001:
        return response  # fast-break: don't retry
    if not _response_ok(response):
        raise _SendFailed(code)  # triggers retry
    return response

if method == "action":
    return _http_retry(
        _send_once,
        max_attempts=3,
        delay_s=8.0,
        should_retry=lambda exc: isinstance(exc, _SendFailed),
    )
else:
    return _send_once()  # non-action: single try, no retry
```

Notes:
- The inner `request()`'s own retry loop is unaffected. After T2 it uses
  `_http_retry` internally with `max_attempts=retry_count+1` (default 3).
- The OUTER retry around `_api_call → request` had 3 iterations × 3 inner
  iterations = 9. After T4 the outer loop is 3 attempts of a single
  request, so action calls fall through `request()`'s 3-attempt inner
  loop *once per outer attempt* — still 9 in the worst case? **No.** The
  inner `request()`'s 3-attempt loop runs on each outer attempt. Total =
  3 × 3 = 9 attempts.

  **Correction:** to actually hit 3 attempts total, we must either:
  (a) tell `_api_call` to call `request(retry_count=0)` when invoked from
      the action path (single inner attempt × 3 outer = 3 total), OR
  (b) call `request()` directly from `_send_once` with `retry_count=0`,
      bypassing `_api_call`'s default, OR
  (c) replace the outer retry loop entirely with the inner one and
      remove the `send()`-level outer loop. Then action calls get
      `request()`'s 3-attempt retry (no 8s delay) — different from
      current behaviour.

  **Resolution:** use option (a) or (b). The action path passes
  `retry_count=0` to `request()` so the inner loop runs exactly once.
  Outer `_http_retry(max_attempts=3, delay_s=8.0)` runs that single
  attempt up to 3 times with 8s delays between. Total: 3 attempts, 16s
  of inter-attempt delay. **Matches the design's "9→3" claim.**

  The discovery doc § 2.2 said: "Note: this site runs in an executor
  thread (blocking), so the helper needs a sync sibling OR the wrap goes
  around the executor-submit call from `_api_call`." We're going with the
  retry_count=0 approach, which is cleaner.

`_SendFailed` is private to `send()` (function scope) like `_NonOKStatus`.
`_extract_action_code` and `_response_ok` are existing helpers if they
exist; otherwise inline the equivalent checks.

## Tests

**Location:** `tests/unit/test_http_retry.py` (mirrors existing
`tests/unit/test_*.py` shape — small, pure-function tests, no HA env).

**Cases:**

1. `test_success_first_attempt`: action returns immediately, called once,
   returns its value.
2. `test_success_after_n_attempts`: action fails N-1 times, succeeds on
   N-th call. `time.sleep` mocked; called N-1 times with `delay_s`.
3. `test_all_attempts_fail_reraises_last`: action raises every time;
   `_http_retry` re-raises the LAST exception (not the first).
4. `test_should_retry_false_reraises_immediately`: action fails on
   attempt 1; `should_retry` returns False; `_http_retry` re-raises on
   attempt 1 without sleeping.
5. `test_delay_s_zero_skips_sleep`: action fails N-1 times, `delay_s=0`,
   `time.sleep` mock NEVER called.
6. `test_max_attempts_one_no_retry`: `max_attempts=1`, action fails,
   re-raises. `time.sleep` not called.
7. `test_max_attempts_zero_raises_valueerror`: `max_attempts=0` → helper
   raises `ValueError` before calling action.
8. `test_max_attempts_negative_raises_valueerror`: `max_attempts=-1`
   same as above.
9. `test_should_retry_sees_exception_instance`: action raises a custom
   exception subclass (defined in the test); `should_retry` is called with
   that exact instance, allowing per-exception-type retry policies.

Tests use `unittest.mock.patch` to mock `time.sleep` (the only side
effect) and `unittest.mock.Mock` for the action callable.

## Approach — 5 sequential tasks

```
T1 add helper + tests → T2 flip request() → T3 flip get_file()
  → T4 flip send() (eliminate stacked loop) → T5 final verify + push
```

| Task | Commit prefix | Risk | Behaviour change |
|---|---|---|---|
| T1 helper + tests | `audit-b1b:` | none | none (new code, no caller yet) |
| T2 `request()` flip | `audit-b1b:` | low | none (semantically equivalent) |
| T3 `get_file()` flip | `audit-b1b:` | low | none (non-200 still triggers retry) |
| T4 `send()` flip | `audit-b1b:` | medium | **action ceiling 9 → 3** (documented fix) |
| T5 verify + push | `audit-b1b:` | none | none |

Serial. Each task ends with `pytest tests/ -q` green.

## Verification per task

After each task:
- `pytest tests/ -q` green.
- `python -m py_compile custom_components/dreame_a2_mower/cloud_client.py` clean.

T4 additionally:
- Manual log review of an action call in dev to confirm 3 attempts (not 9)
  on a forced failure. **Or** add a temporary integration test that mocks
  `_api_call` to always fail and asserts `request` calls = 3.

T5 additionally:
- `tools/inventory_audit.py` clean.
- User-led smoke check (reload integration, trigger an action via
  `lawn_mower.start` or `button.start_mowing`, confirm it works).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| `should_retry` predicate misses an edge case the existing `except Exception` caught | Default predicate is `lambda _exc: True` — retries on every exception, exact match to current behaviour. |
| `_NonOKStatus` shadows an existing class name | Defined inside `get_file()` function scope. No module namespace collision. |
| `send()`'s `retry_count=0` change to `_api_call` affects non-action callers | Only the action path passes `retry_count=0`. Non-action callers continue to use the existing default via `_api_call`. |
| The 8s delay drops to 0 if `_http_retry` is wired wrong in `send()` | T4's unit test for the helper covers `delay_s>0` sleep. Plus a `send()`-level integration assertion (mock failure → 3 attempts × 8s sleeps × 2 = 16s total wall-clock). |
| Helper raises `ValueError` at a runtime call site that passes a bad `max_attempts` | All callers pass `retry_count + 1` where `retry_count` is a positive int. Defensive guard catches dev bugs. |
| Cloud transport behaviour changes for the user | The retry ceiling change is the only behavioural delta. Documented in the T4 commit and the next release notes. |

## What stays for B1c / B1d / later

- **B1c:** `_cached_*` shadow removal, redundant refresher deletion. Independent of the retry helper.
- **B1d:** `cloud_client.py` 2197-LOC file split. `_http_retry` relocates to `cloud_client/_retry.py` then; this is a 1-line `mv` plus an import update in the 3 callers. Out of scope for B1b.
- **Async sibling:** add when the first async caller appears. Defer.

## Open questions

(none in the design itself — per-task plans may surface their own)

## What's next

After user signs off, the writing-plans skill produces the B1b
implementation plan (5 tasks, executed via subagent-driven development).
