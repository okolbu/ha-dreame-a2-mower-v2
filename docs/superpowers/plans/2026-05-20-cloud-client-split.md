# cloud_client.py Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 2287-LOC `cloud_client.py` monolith into a mixin package `cloud_client/` (shell + `_helpers` + 6 concern mixins), preserving behavior and all import paths.

**Architecture:** A mixin package mirroring the coordinator decomposition (CLAUDE.md "Coordinator structure"): one `_<Concern>Mixin` per file, a shell class `DreameA2CloudClient` inheriting them all, only the shell's `__init__` owning `self._*` state. Method bodies move verbatim; the public class is re-exported so all 25 importers are untouched.

**Tech Stack:** Python 3, Home Assistant custom integration, pytest. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-20-cloud-client-split-design.md`

**Context:** On branch `main` (HEAD `06b9c01`). Commit each task on `main` with the `audit-b1d:` prefix, authored as the user, no co-author trailer. Do NOT push (the user handles push/release after). Full suite command: `python -m pytest tests -q` (≈1601 passed / 4 skipped baseline).

---

## File Structure (end state)

`custom_components/dreame_a2_mower/cloud_client/`
- `__init__.py` — shell `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin, _BatchMixin, _FetchersMixin)`: `__init__`, simple + MQTT-accessor properties, `_ensure_strings`, `disconnect`, the `DREAME_STRINGS` import, the mixin imports, and the public re-export.
- `_helpers.py` — `_LOGGER`, `_http_retry`, `_random_agent_id` (module-level).
- `_auth.py` — `_AuthMixin`.
- `_discovery.py` — `_DiscoveryMixin`.
- `_rpc.py` — `_RpcMixin`.
- `_oss.py` — `_OssMixin`.
- `_batch.py` — `_BatchMixin`.
- `_fetchers.py` — `_FetchersMixin`.

## Conventions (read once, applied in Tasks 3-8)

**Relative-import rule.** Files in `cloud_client/` are one package level deeper than the old module. Domain imports therefore use **`from ..`** (e.g. `from ..const import …`, `from ..protocol.cfg_action import …`). Sibling-module imports inside the package use **`from .`** (e.g. `from ._helpers import _LOGGER`). Task 1 re-anchors all existing domain imports to `..`; methods moved in later tasks keep those `..` imports verbatim (mixin files are the same depth as `__init__.py`).

**Standard mixin preamble.** Every mixin file (`_auth.py` … `_fetchers.py`) starts with this exact block (only the docstring and class name differ). It intentionally over-imports — Task 9 prunes per file. This guarantees no NameError mid-split. Per-task code reviewers: unused imports here are expected and removed in Task 9.

```python
"""<Concern> mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

import base64
import hashlib
import json
import queue
import random
import time
import zlib
from threading import Thread
from time import sleep
from typing import Any, Callable, TypeVar

import requests

from ._helpers import _LOGGER, _http_retry, _random_agent_id


class _<Concern>Mixin:
```

**Method move = verbatim.** When moving a method, copy its body byte-for-byte (including decorators like `@property` — but NOTE: no properties move; all properties stay on the shell — and including any `from ..…` local imports inside the method). Do not edit logic, logging, or exception handling.

**No `__init__` in mixins.** Mixins are pure method containers. Only the shell `__init__.py` defines `__init__` / assigns `self._*`.

**TYPE_CHECKING hints are omitted** (no static-analysis gate runs in CI here; cross-mixin `self.foo` calls resolve via MRO at runtime). Don't add them.

---

### Task 1: Convert the module to a package

**Files:**
- Move: `custom_components/dreame_a2_mower/cloud_client.py` → `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create the package dir and move the file**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
mkdir custom_components/dreame_a2_mower/cloud_client
git mv custom_components/dreame_a2_mower/cloud_client.py custom_components/dreame_a2_mower/cloud_client/__init__.py
```

- [ ] **Step 2: Re-anchor all relative domain imports `.` → `..`**

```bash
sed -i -E 's/(^[[:space:]]*)from \./\1from ../' custom_components/dreame_a2_mower/cloud_client/__init__.py
```

- [ ] **Step 3: Verify the re-anchor**

```bash
grep -c "from \.\." custom_components/dreame_a2_mower/cloud_client/__init__.py        # expect 17
grep -nE "from \.[a-z]" custom_components/dreame_a2_mower/cloud_client/__init__.py | grep -v "from \.\." || echo "no single-dot domain imports left (good)"
```
Expected: count `17`; second command prints the "good" line.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS — same totals as baseline (≈1601 passed, 4 skipped). The package imports identically to the old module; `from ...cloud_client import DreameA2CloudClient` still resolves.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b1d: convert cloud_client.py to a package (cloud_client/__init__.py)"
```

---

### Task 2: Extract `_helpers.py` (shared module-level functions + logger)

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_helpers.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`
- Modify: `tests/unit/test_http_retry.py` (white-box test follows the helper)

- [ ] **Step 1: Create `_helpers.py`**

Move `_http_retry` and `_random_agent_id` verbatim out of `__init__.py` into this new file, and define the shared `_LOGGER` with an explicit name (so it stays identical to today's `cloud_client` logger):

```python
"""Shared module-level helpers for the cloud_client package (B1d split)."""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

_LOGGER = logging.getLogger("custom_components.dreame_a2_mower.cloud_client")

T = TypeVar("T")


def _http_retry(
    action: Callable[[], T],
    *,
    max_attempts: int,
    delay_s: float = 0.0,
    should_retry: Callable[[BaseException], bool] = lambda _exc: True,
) -> T:
    # ... move the EXISTING body verbatim from __init__.py ...


def _random_agent_id() -> str:
    # ... move the EXISTING body verbatim from __init__.py ...
```
(Copy the two function bodies exactly as they currently are in `__init__.py`.)

- [ ] **Step 2: Update `__init__.py` to import from `_helpers`**

In `cloud_client/__init__.py`:
- Delete the `_http_retry` and `_random_agent_id` function definitions (now in `_helpers`).
- Delete the module-level `_LOGGER = logging.getLogger(__name__)` line and the `T = TypeVar("T")` line.
- Add near the top (after the stdlib imports): `from ._helpers import _LOGGER, _http_retry, _random_agent_id`
  (Import all three so the shell namespace still exposes `_http_retry` — preserves the `from ...cloud_client import _http_retry` path used by tests.)

- [ ] **Step 3: Update the white-box helper test**

In `tests/unit/test_http_retry.py`:
- Change the import `from custom_components.dreame_a2_mower.cloud_client import _http_retry` → `from custom_components.dreame_a2_mower.cloud_client._helpers import _http_retry`.
- Change all 6 patch targets `"custom_components.dreame_a2_mower.cloud_client.time.sleep"` → `"custom_components.dreame_a2_mower.cloud_client._helpers.time.sleep"` (that's where `_http_retry` now resolves `time`).

```bash
sed -i 's#cloud_client import _http_retry#cloud_client._helpers import _http_retry#' tests/unit/test_http_retry.py
sed -i 's#cloud_client\.time\.sleep#cloud_client._helpers.time.sleep#g' tests/unit/test_http_retry.py
```

- [ ] **Step 4: Run the affected tests, then the full suite**

Run: `python -m pytest tests/unit/test_http_retry.py -v` → all 9 pass.
Run: `python -m pytest tests -q` → baseline totals, no regressions.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_helpers.py (_LOGGER, _http_retry, _random_agent_id)"
```

---

### Task 3: Extract `_auth.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_auth.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_auth.py`** with the Standard Mixin Preamble (Conventions), docstring concern "Auth", class `_AuthMixin`. Move this method verbatim from the shell class into `_AuthMixin`:
  - `login`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._auth import _AuthMixin` (with the other `from ._…` imports).
  - Change the class header to `class DreameA2CloudClient(_AuthMixin):`.
  - Delete the `login` method from the shell class body (now in `_AuthMixin`).

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals. (If a NameError surfaces, an import is missing from the preamble — add it from the original module import set.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_auth.py (_AuthMixin: login)"
```

---

### Task 4: Extract `_discovery.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_discovery.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_discovery.py`** with the Standard Mixin Preamble (Conventions), docstring concern "Device discovery", class `_DiscoveryMixin`. Move these methods verbatim into `_DiscoveryMixin`:
  - `_handle_device_info`, `get_devices`, `select_first_g2408`, `get_device_info`, `get_info`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._discovery import _DiscoveryMixin`.
  - Add `_DiscoveryMixin` to the class bases → `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin):`.
  - Delete the 5 moved methods from the shell class body.

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_discovery.py (_DiscoveryMixin)"
```

---

### Task 5: Extract `_rpc.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_rpc.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_rpc.py`** with the Standard Mixin Preamble (Conventions), docstring concern "Transport / RPC", class `_RpcMixin`. Move these methods verbatim into `_RpcMixin` (keep their local `from ..protocol…` imports intact):
  - `_api_task`, `_api_call_async`, `_api_call`, `get_api_url`, `send_async`, `send`, `get_properties`, `set_property`, `set_properties`, `action_async`, `action`, `request`, `routed_action`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._rpc import _RpcMixin`.
  - Add to bases → `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin):`.
  - Delete the 13 moved methods from the shell class body.

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_rpc.py (_RpcMixin: send/request/action/routed_action)"
```

---

### Task 6: Extract `_oss.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_oss.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_oss.py`** with the Standard Mixin Preamble (Conventions), docstring concern "OSS / WiFi map", class `_OssMixin`. Move these methods verbatim into `_OssMixin` (their nested helper functions `_decode_or_none` / `_decode_candidate` live inside the method bodies and move with them):
  - `get_interim_file_url`, `get_file_url`, `_download_wifi_object`, `fetch_wifi_map`, `list_wifi_candidates`, `get_file`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._oss import _OssMixin`.
  - Add to bases → `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin):`.
  - Delete the 6 moved methods from the shell class body.

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals. (The `tests/protocol/test_cloud_client_wifi_candidates.py` suite exercises `list_wifi_candidates` directly — confirm it passes.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_oss.py (_OssMixin: OSS URLs + wifi map fetch/list)"
```

---

### Task 7: Extract `_batch.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_batch.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_batch.py`** with the Standard Mixin Preamble (Conventions), docstring concern "Batch device-data primitives", class `_BatchMixin`. Move these methods verbatim into `_BatchMixin`:
  - `get_device_property`, `get_device_event`, `get_device_data`, `get_batch_device_datas`, `set_batch_device_datas`, `write_chunked_key`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._batch import _BatchMixin`.
  - Add to bases → `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin, _BatchMixin):`.
  - Delete the 6 moved methods from the shell class body.

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals. (`tests/protocol/test_cloud_chunker.py` exercises `write_chunked_key` — confirm it passes.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_batch.py (_BatchMixin: batch device-data primitives)"
```

---

### Task 8: Extract `_fetchers.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py`
- Modify: `custom_components/dreame_a2_mower/cloud_client/__init__.py`

- [ ] **Step 1: Create `_fetchers.py`** with the Standard Mixin Preamble (Conventions), docstring concern "Cloud-state fetchers + CFG writers", class `_FetchersMixin`. Move these methods verbatim into `_FetchersMixin` (keep their local `from ..cloud_state import …`, `from ..map_decoder import …`, `from ..protocol… import …` imports intact):
  - `fetch_cfg`, `fetch_locn`, `fetch_dev`, `fetch_mihis`, `fetch_dock`, `fetch_net`, `fetch_map`, `fetch_full_cloud_state`, `fetch_mapl`, `set_cfg`, `set_pre`

- [ ] **Step 2: Wire into the shell.** In `__init__.py`:
  - Add `from ._fetchers import _FetchersMixin`.
  - Complete the bases → `class DreameA2CloudClient(_AuthMixin, _DiscoveryMixin, _RpcMixin, _OssMixin, _BatchMixin, _FetchersMixin):`.
  - Delete the 11 moved methods from the shell class body.

- [ ] **Step 3: Run the full suite** — `python -m pytest tests -q` → baseline totals. (`test_fetch_full_cloud_state.py`, `test_cloud_client_fetch_map.py`, `test_cloud_client_set_cfg.py` exercise these directly — confirm they pass.)

- [ ] **Step 4: Verify the shell is now just the state-owning core**

```bash
grep -nE "^    (async )?def " custom_components/dreame_a2_mower/cloud_client/__init__.py
```
Expected: only `__init__`, the simple/MQTT properties, `_ensure_strings`, and `disconnect` remain as methods on the shell class.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b1d: extract cloud_client/_fetchers.py (_FetchersMixin: fetch_* + set_cfg/set_pre)"
```

---

### Task 9: Prune imports, add guard test, document the structure

**Files:**
- Modify: all `cloud_client/*.py` (prune unused imports)
- Create: `tests/protocol/test_cloud_client_package.py`
- Modify: `custom_components/dreame_a2_mower/CLAUDE.md`

- [ ] **Step 1: Prune unused imports in each package file.** For every file in `custom_components/dreame_a2_mower/cloud_client/`, for each imported name, check whether it is referenced elsewhere in that file; remove imports with no other reference. Procedure per name (example for `base64` in `_auth.py`):

```bash
# count non-import references; if the only hit is the import line, it's unused
grep -n "base64" custom_components/dreame_a2_mower/cloud_client/_auth.py
```

Keep `from ._helpers import _LOGGER, _http_retry, _random_agent_id` in `__init__.py` (the `_http_retry` re-export is intentional for `tests/unit`); in each mixin, keep only the `_helpers` names actually used. After pruning, syntax-check:

```bash
python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('custom_components/dreame_a2_mower/cloud_client/*.py')]; print('all parse OK')"
```

- [ ] **Step 2: Write the package guard test**

Create `tests/protocol/test_cloud_client_package.py`:

```python
"""Guard: the cloud_client package re-exports the public client with its full
method surface. Catches an accidental drop during the B1d mixin split."""
from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def test_public_client_importable_and_complete():
    # One representative public member per mixin + the shell, so a dropped
    # mixin (missing base class) fails loudly.
    expected = [
        "login",                       # _auth
        "get_device_info", "get_info",  # _discovery
        "send", "request", "routed_action",  # _rpc
        "fetch_wifi_map", "get_file",  # _oss
        "get_batch_device_datas", "write_chunked_key",  # _batch
        "fetch_full_cloud_state", "set_cfg", "fetch_map",  # _fetchers
        "mqtt_host_port", "disconnect",  # shell
    ]
    missing = [name for name in expected if not hasattr(DreameA2CloudClient, name)]
    assert not missing, f"missing methods after split: {missing}"
```

- [ ] **Step 3: Run the guard + full suite**

Run: `python -m pytest tests/protocol/test_cloud_client_package.py -v` → PASS.
Run: `python -m pytest tests -q` → baseline + 1 (the new guard), 4 skipped.

- [ ] **Step 4: Document the new structure in CLAUDE.md**

Add a section to `custom_components/dreame_a2_mower/CLAUDE.md` titled **"## Cloud client structure (load-bearing)"**, parallel to the existing "Coordinator structure" section. Include: the package path; the file→concern table (the 8 files from this plan's File Structure); the mixin rules ("one `_<Concern>Mixin` per file"; "only the shell `__init__.py` owns `__init__`/`self._*`"; "shared module-level helpers live in `_helpers.py`"; "domain imports use `from ..`, sibling imports `from .`"; "public `DreameA2CloudClient` is re-exported from `__init__.py` — keep that re-export"); and a "Don't reintroduce a single `cloud_client.py`" note.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "audit-b1d: prune imports, add package guard test, document cloud client structure"
```

---

## Self-Review

**Spec coverage:**
- 8-file mixin package (shell + _helpers + 6 mixins) → Tasks 1-8. ✓
- 7-concern granularity (`_batch` vs `_fetchers` split) → Tasks 7, 8. ✓
- Pure structural / verbatim bodies → Conventions + every mixin task's "verbatim" instruction. ✓
- Shared `_LOGGER` (explicit name) for byte-identical log names → Task 2. ✓
- Public re-export, 25 importers unchanged → Task 1 (package import) + the re-export kept in __init__. ✓
- White-box test break-risks (`_http_retry` import + `time.sleep` patch) → Task 2 Step 3. ✓
- Relative-import re-anchor → Task 1 Step 2 + Conventions. ✓
- Guard test → Task 9. ✓
- CLAUDE.md "Cloud client structure" → Task 9. ✓
- Swallow-bug fixes / `_oss` further split → explicitly out of scope (not in any task). ✓

**Placeholder scan:** No TBD/TODO. The mixin tasks specify methods by stable name (line numbers shift as edits land) + the exact preamble + exact `__init__` wiring + exact commands. Bodies are moved verbatim (no new logic to spell out).

**Type/name consistency:** Mixin class names (`_AuthMixin`, `_DiscoveryMixin`, `_RpcMixin`, `_OssMixin`, `_BatchMixin`, `_FetchersMixin`) and the bases list are consistent across Tasks 3-8. Method-name lists partition the ~60 methods with no overlap and no omission (cross-checked against the spec's placement table; shell retains `__init__` + 13 properties + `_ensure_strings` + `disconnect`).
